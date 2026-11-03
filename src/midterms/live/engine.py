"""The live election-night engine behind the dashboard.

Threads:
- one per state results feed: calls its adapter every few seconds (feeds.fetch makes
  each check a conditional request, at most every 15 s per file) and keeps the latest
  frame when it changes;
- the market feeds (streams.py) writing into a shared quote book;
- the compute loop: when votes change, reprojects every race and both chambers
  (~0.5 s); when only prices change, recomputes the after-fee edges (milliseconds).
  Each change becomes a new snapshot pushed to the dashboard.

Model per race (P that the non-Republican wins):
- races a feed covers and that are past project.MIN_SHARE: project.project_race;
- House districts in those states: uniform swing from the state's top race;
- everything else: its pre-election center moved by the national swing seen so far
  (signal.NAT_FOLLOW of the reporting-weighted shift in projected races), with the
  national part of its SD shrunk as more races report, the same rule as
  signal.senate_control. P(D Senate) is signal.senate_control; P(D House) is
  house.simulate with the same national shift.

Prior (prior_mode): "market" (default) starts every race from the market's price,
turned into a margin with the race's own SD, tracked until the first votes land in any
feed and then frozen; chamber control is offset (in log-odds) to the market at the same
moment. So before votes the model equals the market, and every later gap comes from
votes, not from our pre-election disagreement with the market. "model" starts from our
own forecast instead (signal.priors). Our own pre-election P is kept as `own_p`.

Signals: a race x venue x side opens when its after-fee edge reaches EDGE_MIN and the
race is projected from votes (pre-election edges are shown but don't fire unless
prior_signals), and closes when the edge falls below EDGE_MIN / 2. Opens and closes
are logged with prices. Reads only; places no orders.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import threading
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import norm

from .. import house as H
from .. import senate as S
from ..snapshot import ROOT
from . import markets as M
from . import signal as SG
from . import ingest
from . import streams
from .project import P_CAP, house_from_state, project_race

LIVE = ROOT / "data" / "live"
EDGE_MIN = 0.03
COUNTED_OUT = 0.99           # no new signals once a race is essentially fully counted
PRICE_RANGE = (0.03, 0.97)   # no signals at the extremes: fees and locked-up capital eat them
LIVE_STATUSES = ("projected", "uniform swing")
STATE_NAMES = {v: k for k, v in S.NAME_TO_ABB.items()}


def national_shift(sen_priors: dict, projs: dict) -> tuple[float, float]:
    """(mean shift, national SD) for races not yet reporting; same rule as signal.senate_control."""
    rep = {k: p for k, p in projs.items() if p.status == "projected" and k in sen_priors}
    if not rep:
        return 0.0, 3.0
    w = np.array([p.share_in for p in rep.values()])
    d = np.array([p.margin - sen_priors[k][0] for k, p in rep.items()])
    shift = SG.NAT_FOLLOW * float(np.sum(w * d) / w.sum())
    return shift, 3.0 * (1 - 0.3 * min(1.0, len(rep) / 5))


def _p(m, sd):
    return np.clip(norm.cdf(np.asarray(m, float) / np.asarray(sd, float)), *P_CAP)


class Engine:
    def __init__(self, *, feeds: dict[str, Callable[[], pd.DataFrame]], sen_priors: dict, house: pd.DataFrame,
                 universe: pd.DataFrame | None, baseline_col: str = "margin24", expected: dict | None = None,
                 names: dict | None = None, mode: str = "live", edge_min: float = EDGE_MIN,
                 prior_signals: bool = False, log_dir: Path | None = None, sim_market: Callable | None = None,
                 feed_every: float = 3.0, chambers: bool = True, prior_mode: str = "market"):
        self.feeds, self.sen_priors, self.house = feeds, sen_priors, house
        self.universe, self.baseline_col, self.expected = universe, baseline_col, expected or {}
        self.names, self.mode, self.edge_min, self.prior_signals = names or {}, mode, edge_min, prior_signals
        self.sim_market, self.feed_every, self.chambers = sim_market, feed_every, chambers
        self.prior_mode = prior_mode
        self.anchor: dict[str, float] = {}          # race -> market-implied center (points)
        self._mids: dict[str, float] = {}
        self.frozen_at: float | None = None
        self.control_offset: dict[str, float] = {}
        self._sd = {k: sd for k, (c, sd) in sen_priors.items()}
        self._own_center = {k: c for k, (c, sd) in sen_priors.items()}
        if len(house):
            self._sd.update(dict(zip(house["district"], house["sd"])))
            self._own_center.update(dict(zip(house["district"], house["center"])))
        self.log_dir = log_dir or LIVE / dt.date.today().isoformat()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.book = streams.Book()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.frames: dict[str, pd.DataFrame] = {}
        self.feed_status: dict[str, dict] = {s: dict(state=s, status="starting") for s in feeds}
        self.results_version = 0
        self.model = pd.DataFrame()
        self.control: dict[str, float | None] = {"S": None, "H": None}
        self.national = (0.0, 3.0)
        self.history: dict[str, deque] = {}
        self.events: deque = deque(maxlen=300)
        self.open: dict[tuple, dict] = {}
        self.snapshot_version = 0
        self.snapshot_bytes = b"{}"
        self.cond = threading.Condition()
        self._last_quotes: dict[tuple, tuple] = {}
        self._compute_ms = 0.0
        self.book_bytes: bytes | None = None   # map shapes, tiles and pre-election race book for the map tab

    # ---- results ------------------------------------------------------------------
    def _feed_loop(self, state: str, fn: Callable[[], pd.DataFrame]):
        last_hash = None
        while not self.stop.is_set():
            t0 = time.time()
            st = self.feed_status[state]
            try:
                df = fn()
                h = hashlib.md5(pd.util.hash_pandas_object(df[["fips", "race", "party", "vote_type", "votes", "complete"]],
                                                           index=False).values.tobytes()).hexdigest() if len(df) else "empty"
                warning = df.attrs.get("warning")   # e.g. a Texas county failing while the others read fine
                st.update(status="partial" if warning else "ok", last_check=time.time(), rows=len(df), error=warning,
                          votes=float(df["votes"].sum()) if len(df) else 0.0)
                if h != last_hash:
                    last_hash = h
                    with self.lock:
                        self.frames[state] = df
                        self.results_version += 1
                    st["last_change"] = time.time()
            except Exception as e:
                st.update(status="error", error=_plain(e), last_check=time.time())
            self.stop.wait(max(0.5, self.feed_every - (time.time() - t0)))

    def _priors_now(self) -> tuple[dict, pd.DataFrame]:
        sen, house = self.sen_priors, self.house
        if self.prior_mode == "market" and self.anchor:
            sen = {k: (self.anchor.get(k, c), sd) for k, (c, sd) in sen.items()}
            if len(house):
                house = house.assign(center=[self.anchor.get(d, c) for d, c in zip(house["district"], house["center"])])
        return sen, house

    def _update_anchor(self, prices: pd.DataFrame) -> bool:
        """Market mode, before any votes: move each race's starting center to its market
        price. Freezes when the first votes appear. Returns True if a center moved."""
        if self.prior_mode != "market" or self.frozen_at:
            return False
        with self.lock:
            votes = any(len(df) and df["votes"].sum() > 0 for df in self.frames.values())
        if votes:
            self.frozen_at = time.time()
            self._event("note", dict(race="all", note="first votes in: starting prices frozen"))
            return False
        p = prices.dropna(subset=["bid", "ask"])
        p = p[(p["ask"] - p["bid"]) <= 0.10]
        changed = False
        for race, m in p.groupby("race")["mid"].mean().items():
            self._mids[race] = float(m)
            sd = self._sd.get(race)
            if sd is None or not np.isfinite(sd):
                continue
            c = float(sd * norm.ppf(np.clip(m, 0.03, 0.97)))
            if not 0.03 <= m <= 0.97:
                # safe seat: a 99c price says little about the margin, so keep our own
                # center where it's more lopsided than the clipped market one
                own = self._own_center.get(race)
                if own is not None and np.sign(own) == np.sign(c) and abs(own) > abs(c):
                    c = own
            if abs(c - self.anchor.get(race, np.inf)) > 0.05:
                self.anchor[race] = c
                changed = True
        return changed

    def _project(self):
        with self.lock:
            frames = dict(self.frames)
        sen_priors, house = self._priors_now()
        own = {k: float(_p(c, sd)) for k, (c, sd) in self.sen_priors.items()}
        if len(self.house):
            own.update(dict(zip(self.house["district"], _p(self.house["center"], self.house["sd"]))))
        projs = {}
        for state, df in frames.items():
            if df is None or df.empty:
                continue
            for race in sorted(set(df["race"]) & set(sen_priors)):
                rows = df[df["race"] == race]
                c, sd = sen_priors[race]
                kw = {"expected": self.expected[state]} if state in self.expected else {}
                try:
                    projs[race] = project_race(rows, state, c, sd, baseline_col=self.baseline_col, race=race, **kw)
                except Exception as e:
                    self.feed_status[state]["error"] = f"projection {race}: {e!r}"[:200]
        shift, nat_sd = national_shift(sen_priors, projs)
        moving = any(p.status == "projected" for p in projs.values())
        rest_status = "national swing" if moving else "pre-election"
        rows = []
        for race, (c, sd) in sen_priors.items():
            p = projs.get(race)
            if p is not None and p.status == "projected":
                rows.append(dict(race=race, model_margin=p.margin, model_sd=p.sd, model_p=p.p_d, share_in=p.share_in,
                                 status="projected", counted=p.counted))
            else:
                sd2 = float(np.sqrt(max(sd ** 2 - 9.0, 1.0) + nat_sd ** 2))
                rows.append(dict(race=race, model_margin=c + shift, model_sd=sd2, model_p=float(_p(c + shift, sd2)),
                                 share_in=p.share_in if p is not None else 0.0,
                                 status=rest_status))
        if len(house):
            h = house[~house["same_party"]] if "same_party" in house else house
            done = set()
            for race, p in projs.items():
                st = race.split("-")[1]
                dist = h[h["state"] == st]
                if p.status == "projected" and len(dist):
                    hs = house_from_state(p, sen_priors[race][0], dist)
                    rows += [dict(race=r.district, model_margin=r.live_margin, model_sd=r.live_sd, model_p=r.live_p_d,
                                  share_in=p.share_in, status="uniform swing") for r in hs.itertuples()]
                    done |= set(dist["district"])
            rest = h[~h["district"].isin(done)]
            sd2 = np.sqrt(np.maximum(rest["sd"].to_numpy(float) ** 2 - 9.0, 1.0) + nat_sd ** 2)
            m = rest["center"].to_numpy(float) + shift
            rows += [dict(race=d, model_margin=mm, model_sd=s, model_p=pp, share_in=0.0,
                          status=rest_status)
                     for d, mm, s, pp in zip(rest["district"], m, sd2, _p(m, sd2))]
        model = pd.DataFrame(rows)
        model["own_p"] = model["race"].map(own)
        control = {"S": None, "H": None}
        if self.chambers:
            control["S"] = SG.senate_control(sen_priors, {k: v for k, v in projs.items() if k.startswith("SEN-")},
                                             n=40_000)
            if len(house):
                control["H"] = float(H.simulate(house, nat_mean=shift, nat_sd=nat_sd, n=20_000, seed=0)[1]["p_d_majority"])
            if self.prior_mode == "market":
                for k, v in control.items():
                    m = self._mids.get(f"CONTROL-{k}")
                    if v is None:
                        continue
                    if not self.frozen_at and m is not None:
                        self.control_offset[k] = _logit(m) - _logit(v)
                    control[k] = float(1 / (1 + np.exp(-(_logit(v) + self.control_offset.get(k, 0.0)))))
            if not hasattr(self, "_own_control"):
                self._own_control = {"S": SG.senate_control(self.sen_priors, {}, n=40_000),
                                     "H": float(H.simulate(self.house, n=20_000, seed=0)[1]["p_d_majority"]) if len(self.house) else None}
            model = pd.concat([model, pd.DataFrame([
                dict(race=f"CONTROL-{k}", model_p=v, own_p=self._own_control.get(k), status="live" if moving else "pre-election")
                for k, v in control.items() if v is not None])], ignore_index=True)
        with self.lock:
            self.model, self.control, self.national = model, control, (shift, nat_sd)
        # log after votes change, and at most once a minute while only starting prices move
        if self.results_version != getattr(self, "_logged_rv", None) or time.time() - getattr(self, "_logged_t", 0) > 60:
            self._log_model(model)
            self._logged_rv, self._logged_t = self.results_version, time.time()

    # ---- prices and signals --------------------------------------------------------
    def prices(self) -> pd.DataFrame:
        if self.sim_market is not None:
            return self.sim_market(self)
        if self.universe is None:
            return pd.DataFrame(columns=["race", "venue", "bid", "ask", "mid"])
        q = self.book.frame()
        if q.empty:
            return pd.DataFrame(columns=["race", "venue", "bid", "ask", "mid"])
        return M.to_race(self.universe, q)

    def _signals(self, sig: pd.DataFrame):
        now = time.time()
        live = sig if self.prior_signals else sig[sig["status"].isin(LIVE_STATUSES + ("live",))]
        seen = set()
        for r in live.itertuples():
            if not np.isfinite(r.best_edge):
                continue
            key = (r.race, r.venue, r.best_side)
            price = r.ask if r.best_side.startswith("YES") else 1 - r.bid
            counted_out = (r.share_in or 0) >= COUNTED_OUT
            if r.best_edge >= self.edge_min and PRICE_RANGE[0] <= price <= PRICE_RANGE[1] and not counted_out:
                seen.add(key)
                if key not in self.open:
                    self.open[key] = dict(race=r.race, venue=r.venue, side=r.best_side, opened=now, edge=r.best_edge,
                                          max_edge=r.best_edge, price=price, model_p=r.model_p, share_in=r.share_in)
                    self._event("open", self.open[key])
                else:
                    o = self.open[key]
                    o.update(edge=r.best_edge, price=price, model_p=r.model_p, share_in=r.share_in,
                             max_edge=max(o["max_edge"], r.best_edge))
            elif key in self.open and r.best_edge >= self.edge_min / 2:
                seen.add(key)
                self.open[key].update(edge=r.best_edge, price=price, model_p=r.model_p)
        for key in [k for k in self.open if k not in seen]:
            o = self.open.pop(key)
            o["closed"] = now
            self._event("close", o)

    def _event(self, kind: str, o: dict):
        e = dict(ts=time.time(), kind=kind, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in o.items()})
        self.events.appendleft(e)
        path = self.log_dir / "events.csv"
        pd.DataFrame([e]).to_csv(path, mode="a", header=not path.exists(), index=False)

    def _log_model(self, model: pd.DataFrame):
        path = self.log_dir / "model.csv"
        model.assign(ts=dt.datetime.now(dt.UTC)).to_csv(path, mode="a", header=not path.exists(), index=False)

    def _log_quotes(self, prices: pd.DataFrame):
        rows = []
        for r in prices.itertuples():
            k, v = (r.race, r.venue), (r.bid, r.ask)
            if self._last_quotes.get(k) != v:
                self._last_quotes[k] = v
                rows.append(dict(ts=dt.datetime.now(dt.UTC), race=r.race, venue=r.venue, bid=r.bid, ask=r.ask))
        if rows:
            path = self.log_dir / "quotes.csv"
            pd.DataFrame(rows).to_csv(path, mode="a", header=not path.exists(), index=False)

    # ---- snapshot -----------------------------------------------------------------
    def _snapshot(self, sig: pd.DataFrame, prices: pd.DataFrame):
        now = time.time()
        with self.lock:
            model = self.model.copy()
        q = {(r.race, r.venue): r for r in prices.itertuples()}
        e = {r.race: r for r in sig.itertuples()} if len(sig) else {}
        best = sig.sort_values("best_edge", ascending=False).drop_duplicates("race") if len(sig) else sig
        best = {r.race: r for r in best.itertuples()} if len(best) else {}
        races = []
        for r in model.itertuples():
            row = dict(race=r.race, name=self.names.get(r.race, ""), p=_r(r.model_p), own_p=_r(getattr(r, "own_p", None)), margin=_r(getattr(r, "model_margin", None), 2),
                       sd=_r(getattr(r, "model_sd", None), 2), share_in=_r(getattr(r, "share_in", None), 3), status=r.status)
            for v in ("kalshi", "polymarket"):
                x = q.get((r.race, v))
                row[v] = None if x is None else dict(bid=_r(x.bid), ask=_r(x.ask))
            b = best.get(r.race)
            row["edge"] = None if b is None or not np.isfinite(b.best_edge) else dict(venue=b.venue, side=b.best_side, value=_r(b.best_edge))
            races.append(row)
            self._history(r.race, now, row)
        snap = dict(mode=self.mode, simulated_market=self.sim_market is not None, now=now, edge_min=self.edge_min,
                    national=dict(shift=_r(self.national[0], 2), sd=_r(self.national[1], 2)),
                    compute_ms=round(self._compute_ms, 1), prior=dict(mode=self.prior_mode, frozen_at=self.frozen_at),
                    feeds=list(self.feed_status.values()), markets=self.book.status if self.sim_market is None else
                    {"kalshi": dict(mode="simulated", connected=True, last_msg=now)},
                    races=races, signals=sorted(self.open.values(), key=lambda o: -o["edge"]),
                    ingest={st: {k: v for k, v in (ingest.latest(st) or {}).items() if k != "frame"} for st in ("KS",)},
                    events=list(self.events)[:100])
        body = json.dumps(snap, default=_json).encode()
        with self.cond:
            self.snapshot_bytes = body
            self.snapshot_version += 1
            self.cond.notify_all()

    def _history(self, race: str, now: float, row: dict):
        h = self.history.setdefault(race, deque(maxlen=1500))
        mid = lambda v: None if not row[v] or row[v]["bid"] is None or row[v]["ask"] is None else round((row[v]["bid"] + row[v]["ask"]) / 2, 4)
        point = (round(now, 1), row["p"], mid("kalshi"), mid("polymarket"))
        if not h or h[-1][1:] != point[1:] or now - h[-1][0] > 60:
            h.append(point)

    def history_json(self) -> bytes:
        return json.dumps({k: list(v) for k, v in self.history.items()}).encode()

    # ---- main loop ----------------------------------------------------------------
    def _compute_loop(self):
        seen_results, seen_book, last_push, last_project = -1, -1, 0.0, 0.0
        while not self.stop.is_set():
            try:
                rv, bv = self.results_version, self.book.version
                sim = self.sim_market is not None
                if rv != seen_results or bv != seen_book or (sim and time.time() - last_push > 1) or time.time() - last_push > 5:
                    t0 = time.time()
                    prices = self.prices()
                    moved = self._update_anchor(prices)
                    if rv != seen_results or self.model.empty or (moved and time.time() - last_project > 5):
                        self._project()
                        seen_results, last_project = rv, time.time()
                        prices = self.prices()
                    seen_book = bv
                    sig = SG.edges(self.model, prices) if len(prices) and len(self.model) else pd.DataFrame()
                    if len(sig):
                        self._signals(sig)
                    self._log_quotes(prices)
                    self._compute_ms = 1000 * (time.time() - t0)
                    self._snapshot(sig, prices)
                    last_push = time.time()
            except Exception:
                traceback.print_exc()
            self.stop.wait(0.25)

    def start(self, kalshi_ws: bool | None = None):
        if self.universe is not None and self.sim_market is None:
            streams.start(self.universe, self.book, self.stop, kalshi_ws=kalshi_ws)
        for state, fn in self.feeds.items():
            threading.Thread(target=self._feed_loop, args=(state, fn), daemon=True).start()
        threading.Thread(target=self._compute_loop, daemon=True).start()


def _logit(p: float) -> float:
    p = float(np.clip(p, 0.005, 0.995))
    return float(np.log(p / (1 - p)))


def _plain(e: Exception) -> str:
    """A feed error in words for the dashboard chip."""
    t = repr(e)
    if "election id not set" in t:
        return "2026 election id not set yet"
    if "JSONDecodeError" in t or "404" in t or "403" in t:
        return "2026 results file not posted yet"
    if "429" in t:
        return "host asked us to slow down; retrying"
    if "Timeout" in t or "ConnectionError" in t:
        return "host not responding; retrying"
    return t[:160]


def _r(x, n=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(x) else round(x, n)


def _json(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (pd.Timestamp, dt.datetime)):
        return o.isoformat()
    return str(o)


def race_names(snap: str | None = None) -> dict[str, str]:
    """race key -> 'Dem name v Rep name' from Split Ticket."""
    snap = snap or S.latest_snapshot()
    out = {}
    st = pd.read_csv(gzip.open(snap + "split_ticket_senate_seats.csv.gz"))
    for r in st.itertuples():
        ab = S.NAME_TO_ABB.get(r.State)
        if ab:
            out[f"SEN-{ab}"] = f"{STATE_NAMES.get(ab, ab)}: {_short(r.dem_name)} v {_short(r.rep_name)}"
    try:
        h = H.districts(snap)
        for r in h.itertuples():
            out[r.district] = f"{_short(r.dem_name)} v {_short(r.rep_name)}"
    except Exception:
        pass
    out["CONTROL-S"], out["CONTROL-H"] = "Senate control", "House control"
    return out


def _short(n) -> str:
    return n if isinstance(n, str) else "?"

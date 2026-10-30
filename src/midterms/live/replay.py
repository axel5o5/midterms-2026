"""Replaying a past election night to test the projection.

Take a state's final 2024 county results by vote type, reveal (county, vote
type) cells in a plausible reporting order, and project after each step. The
projection only sees what's been revealed plus information available before
that election: the 2020 county presidential margins as the baseline, 2022
vote-type leans, 2020 county turnout x 2022 vote-type shares as the expected
vote, and the final 2024 polling average as the prior.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import feeds
from .baselines import county_baseline, expected_vote, norm_county
from .project import project_race

PA_SAMPLE = feeds.ROOT / "data" / "reference" / "enr_samples" / "PA" / "countybreak_2024.json"  # electionreturns.pa.gov, election 105
ORDERS = ("mail_first", "ed_first_mail_late")


def pa_2024_rows(path: Path = PA_SAMPLE) -> pd.DataFrame:
    """2024 PA presidential results by county and vote type, from electionreturns.pa.gov's
    county-break JSON (election id 105) saved during the feeds research."""
    js = json.loads(json.loads(path.read_text()) if path.read_text().startswith('"') else path.read_text())
    fl = dict(zip(county_baseline("PA")["key"], county_baseline("PA")["fips"]))
    rows = []
    for county_list in js["Election"]["Statewide"]:
        for county, cands in county_list.items():
            for c in cands:
                for col, vt in (("ElectionDayVotes", "election_day"), ("MailInVotes", "mail"), ("ProvisionalVotes", "provisional")):
                    rows.append(dict(state="PA", fips=fl.get(norm_county(county)), county=county, race="PRES-PA",
                                     party=feeds._party(c["PartyName"]), candidate=c["CandidateName"], vote_type=vt,
                                     votes=float(c[col] or 0), ts=None))
    return feeds._frame(rows)


def expected_2024(state: str) -> pd.DataFrame:
    """What a forecaster would have expected before 2024: 2020 county turnout split by
    2022 vote-type shares, with 2022 leans."""
    e = expected_vote(state)
    tot20 = county_baseline(state).set_index("fips")["pres2020_total"]
    e["expected"] = e["fips"].map(tot20) * e["share"].fillna(1.0)
    return e.dropna(subset=["expected"])


def reveal_order(rows: pd.DataFrame, plan: str, rng: np.random.Generator) -> list[tuple[str, str]]:
    """Cells (fips, vote_type) in reporting order.
    mail_first: early and mail everywhere first (NC, GA, FL style), then Election Day,
      small counties tending first, then provisional.
    ed_first_mail_late: Election Day first in small counties, mail mixed in, the two
      biggest counties' mail last (PA, WI, MI style)."""
    cells = rows.groupby(["fips", "vote_type"])["votes"].sum().reset_index()
    size = rows.groupby("fips")["votes"].sum()
    cells["size"] = cells["fips"].map(size)
    noise = rng.normal(0, 1, len(cells))
    if plan == "mail_first":
        tier = cells["vote_type"].map({"early": 0, "mail": 0, "election_day": 1, "provisional": 2, "total": 1}).fillna(1)
        key = tier * 100 + np.where(tier == 1, np.log(cells["size"]) + noise, noise)
    else:
        big = size.nlargest(2).index
        is_mail = cells["vote_type"] == "mail"
        tier = np.where(is_mail & cells["fips"].isin(big), 2, np.where(cells["vote_type"] == "provisional", 3, 1))
        key = tier * 100 + np.log(cells["size"]) + 1.5 * noise
    cells = cells.assign(key=key).sort_values("key")
    return list(zip(cells["fips"], cells["vote_type"]))


def replay(rows: pd.DataFrame, state: str, prior: float, prior_sd: float = 4.9, plan: str = "mail_first",
           steps: int = 15, seed: int = 0, **kw) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    exp = expected_2024(state)
    tot = rows.groupby("party")["votes"].sum()
    truth = 100 * (tot.get("D", 0) - tot.get("R", 0)) / tot.sum()
    order = reveal_order(rows, plan, rng)
    cuts = np.unique(np.linspace(0, len(order), steps + 1).astype(int))[1:]
    rows_k = rows.set_index(["fips", "vote_type"])
    n_cells = rows.groupby("fips")["vote_type"].nunique()
    out = []
    for c in cuts:
        shown = rows_k.loc[rows_k.index.isin(order[:c])].reset_index()
        # a county is "complete" once all of its cells are out (what a feed's county status reports)
        revealed = pd.Series(1, index=pd.MultiIndex.from_tuples(order[:c])).groupby(level=0).size()
        shown["complete"] = shown["fips"].map(revealed).eq(shown["fips"].map(n_cells))
        p = project_race(shown, state, prior, prior_sd, baseline_col="margin20", expected=exp, **kw)
        out.append(dict(state=state, plan=plan, seed=seed, cells=c, share_in=shown["votes"].sum() / rows["votes"].sum(),
                        margin=p.margin, sd=p.sd,
                        p_d=p.p_d, truth=truth, status=p.status,
                        counted_margin=100 * (shown.loc[shown.party == "D", "votes"].sum() - shown.loc[shown.party == "R", "votes"].sum()) / max(shown["votes"].sum(), 1)))
    return pd.DataFrame(out)


ROWS_2024 = feeds.ROOT / "data" / "reference" / "replay_2024_rows.parquet"
PLANS = {"NC": "mail_first", "GA": "mail_first", "IA": "mail_first", "TX": "mail_first", "FL": "mail_first",
         "PA": "ed_first_mail_late", "MN": "ed_first_mail_late"}


def rows_2024(refresh: bool = False) -> pd.DataFrame:
    """2024 presidential results by county and vote type for the replay states."""
    if ROWS_2024.exists() and not refresh:
        return pd.read_parquet(ROWS_2024)
    out = [feeds.ga("2024NovGen"), feeds.nc("2024-11-05"), feeds.clarity("IA", 122322), feeds.fl("2024-11-05"),
           feeds.tx(49664), feeds.mn("2024-11-05")]
    out = [d[d["race"].str.startswith("PRES-")] for d in out] + [pa_2024_rows()]
    allr = pd.concat(out, ignore_index=True).assign(ts=None)
    ROWS_2024.parent.mkdir(parents=True, exist_ok=True)
    allr.to_parquet(ROWS_2024, index=False)
    return allr


def calibration(seeds: int = 8, steps: int = 10, **kw) -> pd.DataFrame:
    rows = rows_2024()
    miss = pd.read_csv(feeds.ROOT / "data" / "history" / "pres2024_state_miss.csv").set_index("state")
    frames = []
    for st, plan in PLANS.items():
        d = rows[rows["state"] == st].drop(columns=["complete"], errors="ignore")
        for seed in range(seeds):
            frames.append(replay(d, st, prior=float(miss.loc[st, "poll_d_margin"]), plan=plan, steps=steps, seed=seed, **kw))
    return pd.concat(frames, ignore_index=True)


# ---- live replay for the dashboard ---------------------------------------------------

# When each state's first votes appear and how long its count runs, as fractions of the
# replay's length (roughly poll-closing order on a real night, compressed).
REPLAY_START = {"GA": 0.00, "FL": 0.02, "NC": 0.06, "PA": 0.10, "TX": 0.14, "MN": 0.22, "IA": 0.26}
REPLAY_SPAN = 0.65


class ReplayFeed:
    """A state's 2024 results revealed in batches over `minutes` of wall-clock time, so the
    dashboard can be watched moving. Batches land at random times, like real file updates."""

    def __init__(self, state: str, rows: pd.DataFrame, minutes: float, t0: float, seed: int = 0, batches: int = 25):
        rng = np.random.default_rng(seed)
        self.state, self.rows = state, rows.drop(columns=["complete"], errors="ignore")
        self.order = reveal_order(self.rows, PLANS.get(state, "mail_first"), rng)
        start = t0 + 60 * minutes * REPLAY_START.get(state, 0.0)
        self.times = np.sort(start + rng.uniform(0, 60 * minutes * REPLAY_SPAN, batches))
        self.times[0] = start
        self.cuts = np.unique(np.linspace(0, len(self.order), batches + 1).astype(int))[1:]
        self.n_cells = self.rows.groupby("fips")["vote_type"].nunique()
        self._k = self.rows.set_index(["fips", "vote_type"])

    def __call__(self) -> pd.DataFrame:
        import time as _t
        k = int(np.searchsorted(self.times, _t.time(), side="right"))
        if k == 0:
            return feeds._frame([])
        shown_cells = self.order[: self.cuts[min(k, len(self.cuts)) - 1]]
        shown = self._k.loc[self._k.index.isin(shown_cells)].reset_index()
        revealed = pd.Series(1, index=pd.MultiIndex.from_tuples(shown_cells)).groupby(level=0).size()
        shown["complete"] = shown["fips"].map(revealed).eq(shown["fips"].map(self.n_cells))
        return shown


class LaggedMarket:
    """Simulated quotes for a replay: each race's mid follows the model's P from `lag`
    seconds earlier plus a slow random drift (sd ~2 points), with a 2-point spread.
    For watching the signal mechanics only; it says nothing about real market speed."""

    def __init__(self, lag: float = 20.0, drift_sd: float = 0.02, seed: int = 0):
        self.lag, self.drift_sd, self.rng = lag, drift_sd, np.random.default_rng(seed)
        self.offset: dict[str, float] = {}

    def __call__(self, engine) -> pd.DataFrame:
        import time as _t
        now, rows = _t.time(), []
        for race, h in engine.history.items():
            if not h:
                continue
            past = next((pt for pt in reversed(h) if pt[0] <= now - self.lag), h[0])
            o = self.offset.get(race, 0.0)
            o = 0.97 * o + self.rng.normal(0, self.drift_sd * np.sqrt(1 - 0.97 ** 2))
            self.offset[race] = o
            mid = float(np.clip(past[1] + o, 0.02, 0.98))
            rows.append(dict(race=race, venue="kalshi", bid=round(mid - 0.01, 3), ask=round(mid + 0.01, 3), mid=mid))
        return pd.DataFrame(rows, columns=["race", "venue", "bid", "ask", "mid"])

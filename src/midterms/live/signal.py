"""Election-night signal: projections vs Kalshi and Polymarket, logged.

One pass:
1. priors()          pre-election center and SD for every Senate race and House
                     district (Senate: lean-adjusted polls + Split Ticket with the
                     2024 carry-over; House: house.py's center).
2. project           each Senate race a feed covers (project.project_race); House
                     districts in those states by uniform swing from the Senate race.
3. senate_control()  P(D Senate): reported races at their projected margin and SD,
                     unreported ones from the pre-election model with the national
                     error nudged toward the swing seen so far.
4. edges()           model P against each venue's bid/ask, after Kalshi's taker fee
                     0.07*P*(1-P) (Polymarket charged no taker fee on these markets
                     when checked; set POLY_FEE if that changes).
No orders are placed anywhere; this only reads and logs.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from .. import house as H
from .. import pres2024 as P24
from .. import senate as S
from ..snapshot import ROOT
from .project import Projection, house_from_state, project_race

LIVE = ROOT / "data" / "live"
POLY_FEE = 0.0
NAT_FOLLOW = 0.5   # share of the swing seen in reported Senate races passed to unreported ones


def kalshi_fee(p):
    return 0.07 * np.asarray(p) * (1 - np.asarray(p))


def priors() -> tuple[dict[str, tuple[float, float]], pd.DataFrame]:
    """race -> (center, SD) for Senate races, and the House district table (with SDs)."""
    df = S.races()
    from .. import carryover as CO
    df["center"] = CO.center(df, "robust")
    m = S.ErrorModel()
    sd = np.sqrt(m.nat_sd ** 2 + m.race_sd(df["n_polls_30d"].to_numpy()) ** 2)
    sen = {f"SEN-{s}": (float(c), float(v)) for s, c, v in zip(df["state"], df["center"], sd) if pd.notna(c)}
    h = H.districts()
    h["sd"] = np.sqrt(3.0 ** 2 + 2.7 ** 2 + H.race_sd(h["n_polls"].to_numpy()) ** 2)
    return sen, h


def senate_control(sen_priors: dict, projections: dict[str, Projection], n: int = 50_000, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    df = S.races()
    df["c"] = df["state"].map(lambda s: sen_priors.get(f"SEN-{s}", (np.nan, np.nan))[0])
    df["c"] = df["c"].fillna(df["st_margin"])
    rep = {k: p for k, p in projections.items() if p.status == "projected"}
    shift = 0.0
    if rep:
        w = np.array([p.share_in for p in rep.values()])
        d = np.array([p.margin - sen_priors[k][0] for k, p in rep.items()])
        shift = NAT_FOLLOW * float(np.sum(w * d) / w.sum())
    m = S.ErrorModel(nat_mean=shift, nat_sd=3.0 * (1 - 0.3 * min(1.0, len(rep) / 5)))
    race_sd = m.race_sd(df["n_polls_30d"].to_numpy())
    nat = m.nat_mean + m.nat_sd * S._t(rng, m.nat_df, (n, 1))
    margins = df["c"].to_numpy(float) + nat + race_sd * S._t(rng, m.race_df, (n, len(df)))
    for i, s in enumerate(df["state"]):
        p = rep.get(f"SEN-{s}")
        if p is not None:
            margins[:, i] = p.margin + p.sd * rng.standard_normal(n)
    up_d = (df["held_by"] == "D").sum()
    seats = S.SENATE_NOW["D"] - up_d + (margins > 0).sum(axis=1)
    return float((seats >= 51).mean())


def edges(model: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """One row per race x venue: model P, bid/ask, and the after-fee edge of the better side."""
    q = model.merge(prices, on="race", how="inner")
    fee_yes = np.where(q["venue"] == "kalshi", kalshi_fee(q["ask"]), POLY_FEE)
    fee_no = np.where(q["venue"] == "kalshi", kalshi_fee(1 - q["bid"]), POLY_FEE)
    q["edge_yes"] = q["model_p"] - q["ask"] - fee_yes          # buy YES (D side) at the ask
    q["edge_no"] = q["bid"] - q["model_p"] - fee_no            # buy NO at 1 - bid
    q["best_side"] = np.where(q["edge_yes"] >= q["edge_no"], "YES (D)", "NO (D loses)")
    q["best_edge"] = q[["edge_yes", "edge_no"]].max(axis=1)
    return q


def run_pass(feed: pd.DataFrame, prices: pd.DataFrame | None, sen_priors: dict, house: pd.DataFrame,
             baseline_col: str = "margin24") -> tuple[pd.DataFrame, float | None]:
    """Project from one feed snapshot and compare to prices. Returns the signal rows and P(D Senate)."""
    projs = {}
    for race in sorted(set(feed["race"]) & set(sen_priors)):
        rows = feed[feed["race"] == race]
        c, sd = sen_priors[race]
        projs[race] = project_race(rows, rows["state"].iloc[0], c, sd, baseline_col=baseline_col, race=race)
    model = [dict(race=k, model_p=p.p_d, model_margin=p.margin, model_sd=p.sd, share_in=p.share_in, status=p.status)
             for k, p in projs.items()]
    for race, p in projs.items():
        st = race.split("-")[1]
        dist = house[house["state"] == st]
        if len(dist) and p.status == "projected":
            hs = house_from_state(p, sen_priors[race][0], dist)
            model += [dict(race=r.district, model_p=r.live_p_d, model_margin=r.live_margin, model_sd=r.live_sd,
                           share_in=p.share_in, status="uniform swing") for r in hs.itertuples()]
    model = pd.DataFrame(model)
    p_control = senate_control(sen_priors, {k: v for k, v in projs.items() if k.startswith("SEN-")}) \
        if any(k.startswith("SEN-") for k in projs) else None
    if prices is None or model.empty:
        return model, p_control
    sig = edges(model, prices)
    return sig, p_control


def log(sig: pd.DataFrame, p_control: float | None, day: str | None = None) -> Path:
    day = day or dt.date.today().isoformat()
    path = LIVE / day / "signals.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    out = sig.assign(ts=dt.datetime.now(dt.UTC), p_d_senate=p_control)
    out.to_csv(path, mode="a", header=not path.exists(), index=False)
    return path


def table(sig: pd.DataFrame, n: int = 12, min_share: float = 0.05) -> str:
    if sig.empty or "best_edge" not in sig:
        return "(no priced races projected yet)"
    t = sig[sig["share_in"] >= min_share].sort_values("best_edge", ascending=False).head(n)
    cols = ["race", "venue", "share_in", "model_margin", "model_sd", "model_p", "bid", "ask", "best_side", "best_edge"]
    return t[cols].round(3).to_string(index=False)

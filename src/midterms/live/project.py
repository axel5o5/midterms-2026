"""Projecting a race from partial county returns.

The unit is the county. Each county's final margin is projected as its
baseline (presidential margin, 2024 by default) plus a statewide swing, plus a
shrunk county-specific deviation; the votes still to come in a county are
whatever closes the gap between that projected total and what's already been
counted there.

The statewide swing is a precision-weighted mix of
- the prior: the pre-election center minus the baseline statewide margin, with
  the pre-election SD (senate.ErrorModel: ~4.9 for a well-polled race);
- counties that have finished counting (full weight);
- counties partly in, at PARTIAL_WEIGHT: their swing is estimated from the vote
  types counted so far against those types' 2022 leans, and those leans move
  from one election to the next (in 2024 Republicans shifted into early voting,
  so early ballots ran redder than their 2022 lean and Election Day bluer).

Working at the county level is what keeps that shift from skewing the
projection: a county's mail-first count can't by itself drag its projected
total, only nudge it. The data's SE is the vote-weighted dispersion of county
swings over the effective number of counties, times INFLATE for correlated
reporting (early counties aren't a random sample) — calibrated on the
replays in notebook 03. Final SD = uncounted share x swing SD, plus county
noise and a turnout term. P(D) = Phi(margin / SD), capped to [0.005, 0.995];
below MIN_SHARE of expected votes the race reports its prior.

Expected votes: baselines.expected_vote (2022 midterm totals x pace), scaled
by turnout learned from counties that have finished. A county is finished when
the feed marks it complete (or, in a replay, when all its cells are revealed).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm

from .baselines import county_baseline, expected_vote

MIN_SHARE = 0.05
INFLATE = 3.0          # correlation inflation of the data SE (see notebook 03)
PARTIAL_WEIGHT = 0.2   # weight of partly counted counties in the statewide swing
COUNTY_KAPPA = 5000.0  # votes at which a county's own deviation gets half weight
TURNOUT_SD = 1.0       # points of margin per unit of uncounted share, for turnout misses
LEAN_DRIFT_SD = 12.0   # systematic error of partial-county swings judged against 2022 leans
SD_SLOPE, SD_CAP = 9.0, 2.5  # SD floor = min(SD_CAP, SD_SLOPE x uncounted share), see notebook 03
OWN_WEIGHT = 0.8       # max weight of a partly counted county's own swing in its remaining votes
REP_SD = 5.0           # how far the finished counties' swing can sit from the whole state's,
                       # scaled by the share of expected votes not yet in finished counties
P_CAP = (0.005, 0.995)


@dataclass
class Projection:
    race: str
    margin: float          # projected final margin, D - R, points
    sd: float
    p_d: float
    share_in: float        # counted / projected total
    counted: float
    swing: float = np.nan  # posterior statewide swing vs the baseline
    info: dict = field(default_factory=dict)
    status: str = "projected"   # or "prior" (too little in)


def _wmean(x, w):
    w = np.asarray(w, float)
    return float(np.sum(np.asarray(x, float) * w) / w.sum()) if w.sum() > 0 else np.nan


def _wsd(x, w):
    m = _wmean(x, w)
    w = np.asarray(w, float)
    return float(np.sqrt(np.sum(w * (np.asarray(x, float) - m) ** 2) / w.sum())) if w.sum() > 0 else np.nan


def project_race(rows: pd.DataFrame, state: str, prior_margin: float, prior_sd: float = 4.9,
                 baseline_col: str = "margin24", expected: pd.DataFrame | None = None,
                 inflate: float = INFLATE, partial_weight: float = PARTIAL_WEIGHT, rep_sd: float = REP_SD,
                 race: str | None = None) -> Projection:
    """Project one race from its tidy feed rows (one state). Rows may carry a boolean
    `complete` marking (county, vote type) cells the feed reports as fully counted."""
    race = race or (rows["race"].iloc[0] if len(rows) else "?")
    base = county_baseline(state).set_index("fips")[baseline_col]
    exp = (expected if expected is not None else expected_vote(state)).copy()
    lean = exp.set_index(["fips", "vote_type"])["lean"] if "lean" in exp else pd.Series(dtype=float)

    r = rows.dropna(subset=["fips"]).copy()
    if "complete" not in r:
        r["complete"] = False
    cell = r.groupby(["fips", "vote_type", "party"])["votes"].sum().unstack("party", fill_value=0.0)
    for p in ("D", "R", "O"):
        if p not in cell:
            cell[p] = 0.0
    cell["n"] = cell[["D", "R", "O"]].sum(axis=1)
    cell["complete"] = r.groupby(["fips", "vote_type"])["complete"].any()
    cell = cell.reset_index()
    cell["lean"] = [lean.get((f, v), 0.0) for f, v in zip(cell["fips"], cell["vote_type"])]

    county = pd.DataFrame({"expected": exp.groupby("fips")["expected"].sum()})
    county["base"] = county.index.map(base)
    county = county.dropna(subset=["base"])
    g = cell.groupby("fips")
    county["D"] = g["D"].sum()
    county["R"] = g["R"].sum()
    county["n"] = g["n"].sum()
    county = county.fillna({"D": 0.0, "R": 0.0, "n": 0.0})
    # finished: the feed marks every row of the county complete (county-level reporting status)
    done = r.groupby("fips")["complete"].all()
    county["done"] = county.index.map(done).fillna(False).astype(bool)

    total_exp = county["expected"].sum()
    base_margin = _wmean(county["base"], county["expected"])
    s0 = prior_margin - base_margin
    counted = county["n"].sum()
    if total_exp <= 0 or counted / total_exp < MIN_SHARE:
        p = float(np.clip(norm.cdf(prior_margin / prior_sd), *P_CAP))
        return Projection(race, prior_margin, prior_sd, p, counted / total_exp if total_exp else 0.0, counted, s0,
                          status="prior")

    # turnout learned from finished counties, shrunk toward 1
    fin = county[county["done"] & (county["expected"] > 0)]
    turnout = 1.0
    if len(fin) >= 3:
        k = len(fin) / (len(fin) + 5)
        turnout = k * fin["n"].sum() / fin["expected"].sum() + (1 - k)
    county["remaining"] = np.where(county["done"], 0.0, (county["expected"] * turnout - county["n"]).clip(lower=0))

    # county swings: finished counties directly; partial ones via their counted types' leans
    county["margin_obs"] = 100 * (county["D"] - county["R"]) / county["n"].where(county["n"] > 0)
    cell["margin"] = 100 * (cell["D"] - cell["R"]) / cell["n"].where(cell["n"] > 0)
    cell["swing"] = cell["margin"] - (cell["fips"].map(base) + cell["lean"])
    part_swing = cell.dropna(subset=["swing"]).groupby("fips").apply(lambda d: _wmean(d["swing"], d["n"]), include_groups=False)
    county["swing"] = np.where(county["done"], county["margin_obs"] - county["base"], county.index.map(part_swing))
    # Two data sources, each with a sampling error (dispersion over effective counties,
    # inflated for correlated reporting) plus a systematic floor that doesn't shrink with
    # more counties: finished counties may be unrepresentative (rural / small first),
    # partly counted ones are judged against vote-type leans that drift between elections.
    total_w = county["expected"].sum()
    frac_done = county.loc[county["done"], "expected"].sum() / total_w
    prec, num = 1 / prior_sd ** 2, s0 / prior_sd ** 2
    sd_county = 8.0
    sources = {"finished": (county[county["done"] & county["swing"].notna() & (county["n"] > 0)], rep_sd * (1 - frac_done)),
               "partial": (county[~county["done"] & county["swing"].notna() & (county["n"] > 0)], LEAN_DRIFT_SD)}
    used = {}
    for name, (d, sys_sd) in sources.items():
        if len(d) == 0:
            continue
        w = d["n"].to_numpy(float)
        n_eff = w.sum() ** 2 / np.sum(w ** 2)
        sd_c = max(_wsd(d["swing"], w) if len(d) > 1 else 8.0, 2.0)
        if name == "finished" or len(sources["finished"][0]) == 0:
            sd_county = sd_c
        se2 = sd_c ** 2 * inflate / n_eff + sys_sd ** 2
        prec += 1 / se2
        num += _wmean(d["swing"], w) / se2
        used[name] = round(_wmean(d["swing"], w), 2)
    s_post, var_post = num / prec, 1 / prec

    # project each unfinished county's total, then the margin of its remaining votes
    dev = (county["swing"] - s_post).fillna(0.0) * county["n"] / (county["n"] + COUNTY_KAPPA)
    county["proj_total"] = county["base"] + s_post + np.where(county["done"], 0.0, partial_weight * dev)
    final_n = county["n"] + county["remaining"]
    gap = county["proj_total"] * final_n - 100 * (county["D"] - county["R"])
    rem_a = np.where(county["remaining"] > 0.02 * final_n,
                     (gap / county["remaining"].where(county["remaining"] > 0)).clip(-95, 95), county["proj_total"])
    # Second estimate for partly counted counties: the county's own counted swing, carried
    # to its remaining vote types through their 2022 leans. Blended in by how much of the
    # county is counted, so a county that's 80% in is mostly projected from itself.
    exp_cell = exp.assign(lean=exp["lean"] if "lean" in exp else 0.0).set_index(["fips", "vote_type"])
    n_cell = cell.set_index(["fips", "vote_type"])["n"]
    rem_cell = (exp_cell["expected"] * turnout - n_cell.reindex(exp_cell.index).fillna(0)).clip(lower=0)
    rem_lean = (rem_cell * exp_cell["lean"]).groupby(level=0).sum() / rem_cell.groupby(level=0).sum().where(lambda x: x > 0)
    cnt_lean = cell.assign(wl=cell["lean"] * cell["n"]).groupby("fips")["wl"].sum() / county["n"].where(county["n"] > 0)
    rem_b = county["margin_obs"] - county.index.map(cnt_lean).fillna(0.0) + county.index.map(rem_lean).fillna(0.0)
    w_b = (OWN_WEIGHT * county["n"] / final_n.where(final_n > 0)).fillna(0.0)
    county["rem_margin"] = np.where(county["n"] > 0, w_b * rem_b.clip(-95, 95).fillna(0.0) + (1 - w_b) * rem_a, rem_a)

    tot = final_n.sum()
    margin = 100 * ((county["D"] - county["R"]).sum() + (county["remaining"] * county["rem_margin"] / 100).sum()) / tot
    rem_share = county["remaining"].sum() / tot
    var_county = sd_county ** 2 * float(np.sum(county["remaining"] ** 2)) / tot ** 2
    sd = float(np.sqrt(rem_share ** 2 * var_post + var_county + (TURNOUT_SD * rem_share) ** 2 + 0.05 ** 2))
    # Floor from the 2024 replays (notebook 03): the real error stayed near 2 points from
    # 20% to 80% counted (the last big counties are the least like the first ones), so the
    # SD can't drop below min(SD_CAP, SD_SLOPE x uncounted share).
    sd = max(sd, min(SD_CAP, SD_SLOPE * rem_share))
    p = float(np.clip(norm.cdf(margin / sd), *P_CAP))
    return Projection(race, float(margin), sd, p, float(counted / tot), float(counted), float(s_post),
                      dict(prior_swing=round(s0, 2), turnout=round(turnout, 3), finished_counties=int(county["done"].sum()),
                           counties=len(county), source_swings=used))


def project_state(feed: pd.DataFrame, priors: dict[str, tuple[float, float]], **kw) -> list[Projection]:
    """Project every race in `priors` (race key -> (center, sd)) that the feed covers."""
    out = []
    for race, (center, sd) in priors.items():
        rows = feed[feed["race"] == race]
        if rows.empty:
            continue
        out.append(project_race(rows, rows["state"].iloc[0], center, sd, race=race, **kw))
    return out


def house_from_state(top: Projection, top_prior: float, districts: pd.DataFrame, idio_sd: float = 4.0) -> pd.DataFrame:
    """House districts in a state by uniform swing from its top race: each district's
    pre-election center moves by how far the top race has moved from its prior.
    (County baselines can't be split by district, so this doesn't use a district's
    own partial counts.)"""
    shift = top.margin - top_prior
    sd = float(np.sqrt(idio_sd ** 2 + top.sd ** 2))
    m = districts["center"] + shift
    return districts.assign(live_margin=m, live_sd=sd, live_p_d=np.clip(norm.cdf(m / sd), *P_CAP))

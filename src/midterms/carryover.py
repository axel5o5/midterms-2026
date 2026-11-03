"""Which state-level polling adjustments predict a race's polling miss, tested out of sample.

Target: a statewide race's polling miss beyond that year's national miss
(err - mean err of all statewide races that cycle), 1998-2022, from 538's raw polls
(data/history/race_poll_errors.csv). Positive = the Democrat beat the polls.

Candidate predictors, each built only from earlier elections:
- fade:  points the Democrat polls above the state's last presidential margin
         (candidates far above their state's lean tend to fall back);
- pres:  the state's miss in the most recent earlier presidential race, beyond that
         year's national miss (the current "2024 carry-over");
- hist:  the state's average miss over every statewide race in the previous
         `window` years, beyond each year's national miss.

Specs are linear, no intercept, fitted on all cycles but one and scored on the one
left out (leave-one-cycle-out), on midterm Senate and governor races, which is what
2026 is. `backtest()` returns the scores.

Result (2026-11-02, 344 midterm races in 6 cycles, n_hist >= 2):
  Headline: 12-year window, complete fade/pres/hist predictors, held-out RMSE:
  pres split by direction  5.243
  pres alone               5.269
  pres + hist              5.350
  fade + pres              5.382
  fade + pres + hist       5.476
  hist alone               5.506
  none                     5.555
  fade alone               5.567
  fade + hist              5.605
  The 8-year window has the same sample and identical pres-only/split results;
  pres + hist is 5.338, fade + pres + hist 5.454, hist alone 5.481,
  and fade + hist 5.564. Other scores are unchanged.

The main model uses direction-specific presidential carry-over and no fade:
BETA_PRES_D = 0.54 when polls underrated Democrats (positive relative miss),
BETA_PRES_R = 0.26 when polls underrated Republicans (negative relative miss).
Full-sample fits are 0.538 and 0.257; cycle-bootstrap 90% ranges are 0.374-0.632
and -0.018-0.476, respectively, at either window. Split carry-over helped in
2010, 2014, 2018 and 2022 and hurt in 2002 and 2006.
By prior miss direction, RMSE is 5.579 -> 5.047 -> 5.003 for positive misses
(182 races) and 5.526 -> 5.507 -> 5.499 for negative misses (162 races), for
none -> one weight -> split. Split mean signed errors (actual minus predicted)
are -0.507 and -0.560, versus -0.104 and -0.047 with one weight: its small RMSE
gain does not improve signed bias. The old BETA_PRES = 0.42 stays as the
"one weight (Oct 30)" version. The longer state record stays as a variation,
at BETA_HIST (its own fit, 8-year window).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .snapshot import ROOT

ERRORS = ROOT / "data" / "history" / "race_poll_errors.csv"
PRES24 = ROOT / "data" / "history" / "pres2024_state_miss.csv"
BETA_PRES = 0.42
# No-intercept least squares on table(12), complete fade/pres/hist, n_hist >= 2,
# midterm Senate/governor races only: pres clipped above/below zero, 344 races.
BETA_PRES_D, BETA_PRES_R = 0.54, 0.26
BETA_HIST = 0.43
VARIANTS = {
    # name: (fade slope, presidential weight for miss > 0, for miss < 0, longer record)
    "robust": (0.0, BETA_PRES_D, BETA_PRES_R, 0.0),
    "one weight (Oct 30)": (0.0, BETA_PRES, BETA_PRES, 0.0),
    "first version": (-0.082, 0.34, 0.34, 0.0),
    "longer state record": (0.0, 0.0, 0.0, BETA_HIST),
    "no adjustments": (0.0, 0.0, 0.0, 0.0),
}


def center(df: pd.DataFrame, variant: str = "robust") -> pd.Series:
    """Expected margin for each Senate race under a variant, from senate.races() columns:
    the poll average (faded by the variant's slope) averaged with Split Ticket, plus the
    variant's carry-over."""
    slope, bd, br, bh = VARIANTS[variant]
    poll = df["poll_margin"] + slope * (df["poll_margin"] - df["lean_2024"])
    base = pd.concat([poll, df["st_margin"]], axis=1).mean(axis=1)
    hist = df["state"].map(state_history_2026()).fillna(0.0) if bh else 0.0
    miss = df["miss24_rel"].fillna(0.0)
    return base + bd * miss.clip(lower=0) + br * miss.clip(upper=0) + bh * hist


def table(window: int = 8) -> pd.DataFrame:
    d = pd.read_csv(ERRORS)
    sw = d[d["type_simple"].isin(["Sen-G", "Gov-G", "Pres-G"])].copy()
    nat = sw.groupby("cycle")["err"].mean()
    sw["rel"] = sw["err"] - sw["cycle"].map(nat)
    pres = sw[sw["type_simple"] == "Pres-G"].set_index(["cycle", "location"])
    races = sw[sw["type_simple"].isin(["Sen-G", "Gov-G"])].copy()
    rows = []
    for r in races.itertuples():
        prev_pres = r.cycle - 4 if r.cycle % 4 == 0 else r.cycle - (r.cycle % 4)   # last presidential year before
        lean_year = r.cycle - (r.cycle % 4)                                         # last presidential result known at the time
        lean = pres["actual"].get((lean_year, r.location)) if r.cycle % 4 else pres["actual"].get((r.cycle - 4, r.location))
        p = pres["rel"].get((prev_pres, r.location))
        h = sw[(sw["location"] == r.location) & (sw["cycle"] < r.cycle) & (sw["cycle"] >= r.cycle - window)]["rel"]
        rows.append(dict(cycle=r.cycle, state=r.location, type=r.type_simple, y=r.rel, poll=r.poll,
                         fade=(r.poll - lean) if lean is not None else np.nan,
                         pres=p if p is not None else np.nan, hist=h.mean() if len(h) else np.nan, n_hist=len(h),
                         midterm=(r.cycle % 4 == 2)))
    t = pd.DataFrame(rows)
    t["pres_d"] = t["pres"].clip(lower=0)
    t["pres_r"] = t["pres"].clip(upper=0)
    return t


SPECS = {
    "none": [],
    "fade": ["fade"],
    "pres (2024-style carry-over)": ["pres"],
    "pres split by direction": ["pres_d", "pres_r"],
    "hist (longer state record)": ["hist"],
    "fade + pres": ["fade", "pres"],
    "fade + hist": ["fade", "hist"],
    "pres + hist": ["pres", "hist"],
    "fade + pres + hist": ["fade", "pres", "hist"],
}


def _fit(t: pd.DataFrame, cols: list[str]) -> np.ndarray:
    if not cols:
        return np.zeros(0)
    return np.linalg.lstsq(t[cols].to_numpy(float), t["y"].to_numpy(float), rcond=None)[0]


def backtest(window: int = 8, midterm_only: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Leave-one-cycle-out scores per spec, and full-sample coefficients."""
    t = table(window).dropna(subset=["fade", "pres", "hist"])
    t = t[t["n_hist"] >= 2]
    test = t[t["midterm"]] if midterm_only else t
    scores, coefs = [], []
    for name, cols in SPECS.items():
        pred = pd.Series(np.nan, index=test.index)
        for c in sorted(test["cycle"].unique()):
            train = t[t["cycle"] != c]
            if midterm_only:
                train = train[train["midterm"]]
            b = _fit(train, cols)
            idx = test.index[test["cycle"] == c]
            pred[idx] = test.loc[idx, cols].to_numpy(float) @ b if cols else 0.0
        err = test["y"] - pred
        by_cycle = err.groupby(test["cycle"]).apply(lambda e: np.sqrt(np.mean(e ** 2)))
        scores.append(dict(spec=name, rmse=float(np.sqrt(np.mean(err ** 2))), mae=float(err.abs().mean()),
                           worst_cycle_rmse=float(by_cycle.max()), races=len(test), cycles=test["cycle"].nunique()))
        b = _fit(test if midterm_only else t, cols)
        coefs.append(dict(spec=name, **{c: float(v) for c, v in zip(cols, b)}))
    s = pd.DataFrame(scores)
    s["vs_none"] = s["rmse"] - s.loc[s["spec"] == "none", "rmse"].iloc[0]
    return s.sort_values("rmse"), pd.DataFrame(coefs)


def fairness(window: int = 12) -> pd.DataFrame:
    """Held-out errors by prior miss direction; signed error is actual minus predicted.

    Uses the same complete-case, n_hist >= 2, midterm-only sample as backtest().
    Zero prior misses belong to neither group.
    """
    t = table(window).dropna(subset=["fade", "pres", "hist"])
    t = t[(t["n_hist"] >= 2) & t["midterm"]]
    rows = []
    for name in ("none", "pres (2024-style carry-over)", "pres split by direction"):
        cols = SPECS[name]
        pred = pd.Series(np.nan, index=t.index)
        for c in sorted(t["cycle"].unique()):
            train, test = t[t["cycle"] != c], t[t["cycle"] == c]
            pred.loc[test.index] = test[cols].to_numpy(float) @ _fit(train, cols) if cols else 0.0
        for direction, mask in (("pres > 0", t["pres"] > 0), ("pres < 0", t["pres"] < 0)):
            err = (t["y"] - pred)[mask]
            rows.append(dict(spec=name, direction=direction, races=len(err),
                             rmse=float(np.sqrt(np.mean(err ** 2))), mean_signed_error=float(err.mean())))
    return pd.DataFrame(rows)


def bootstrap(cols: list[str], window: int = 8, n: int = 2000, seed: int = 0) -> pd.DataFrame:
    """Coefficient spread when whole cycles are resampled (races within a year are correlated)."""
    t = table(window).dropna(subset=["fade", "pres", "hist"])
    t = t[(t["n_hist"] >= 2) & t["midterm"]]
    cycles = t["cycle"].unique()
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        pick = rng.choice(cycles, len(cycles))
        s = pd.concat([t[t["cycle"] == c] for c in pick])
        out.append(_fit(s, cols))
    return pd.DataFrame(out, columns=cols).describe(percentiles=[0.05, 0.5, 0.95]).T


def state_history_2026(window: int = 8) -> pd.Series:
    """Each state's average miss beyond the national miss over 2018-2024 statewide races
    (2024 presidential from pres2024_state_miss.csv), for the 2026 'hist' term."""
    d = pd.read_csv(ERRORS)
    sw = d[d["type_simple"].isin(["Sen-G", "Gov-G", "Pres-G"])].copy()
    sw["rel"] = sw["err"] - sw["cycle"].map(sw.groupby("cycle")["err"].mean())
    recent = sw[sw["cycle"] >= 2026 - window][["location", "rel"]].rename(columns={"location": "state"})
    p24 = pd.read_csv(PRES24)[["state", "miss_vs_national"]].rename(columns={"miss_vs_national": "rel"})
    return pd.concat([recent, p24], ignore_index=True).groupby("state")["rel"].mean()

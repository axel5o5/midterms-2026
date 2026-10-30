"""2026 House: one row per district from every source, and a simulation of
the chamber with the same error model as the Senate.

Error model (docs/polling-error-research.md):
- national miss: t(5), SD 3.0, shared with every race (and the Senate);
- state miss: SD 2.7, one draw per state shared by all its districts;
- race miss: no public polls t(6) SD 8; 1-3 polls t(6) SD 7 / 6 / 5;
  4+ polls t(10) SD sqrt(2.5^2 + 25/n).

Center: the mean of Split Ticket's and DDHQ's margins, plus our own district
polling average (Silver Bulletin's poll list, sponsored polls moved 5 points
against the sponsor) where a district has 2+ polls in the last 60 days. The models already
carry district partisanship, incumbency and money; the polls add direct
evidence where it exists. DDHQ blends markets into its numbers, so it is not
independent of Kalshi/Polymarket. No state-lean regression: district 2024
presidential margins after the 2025-26 redistricting aren't in hand.

Margins are the non-Republican candidate minus the Republican, in points.
"""

from __future__ import annotations

import gzip
import json
import re

import numpy as np
import pandas as pd

from .senate import NAME_TO_ABB, _signed, _t, latest_snapshot

AT_LARGE = {"AK", "DE", "ND", "SD", "VT", "WY"}
MAJORITY = 218
SPONSOR_SHIFT = 5.0  # points against the sponsor (brief: 4-6)
MIN_POLLS = 2


def key(state: str, district) -> str:
    """('CA', 22) / ('AK', 'At-Large') -> 'CA-22' / 'AK-AL'."""
    state = state.upper()
    s = str(district).strip().upper()
    if state in AT_LARGE or s in ("AL", "AT-LARGE", "0", "00", ""):
        return f"{state}-AL"
    return f"{state}-{int(re.sub(r'\D', '', s)):02d}"


def districts(snap: str | None = None, poll_days: int = 60) -> pd.DataFrame:
    snap = snap or latest_snapshot()

    # Split Ticket: all 435
    st = pd.read_csv(gzip.open(snap + "split_ticket_house_seats.csv.gz"))
    st["district"] = [key(*cd.split("-")) for cd in st["cd"]]
    st["st_margin"] = st["prediction"].map(_signed)
    st["st_p_d"] = st["win_prob_d"] / 100
    st["d_is_ind"] = st["dem_name"].str.contains(r"\(Ind\)", na=False)
    df = st[["district", "dem_name", "rep_name", "bucket", "st_margin", "st_p_d", "d_is_ind"]].copy()

    # Who holds the seat: Split Ticket's projected winner, switched where it marks a flip.
    # (DDHQ / The Hill used to supply this; its robots.txt disallows AI crawlers, so
    # it was dropped on 2026-10-29.)
    projected = np.where(st["st_margin"] > 0, "D", "R")
    flips = st["flip"].astype(str).str.upper().eq("Y").to_numpy()
    df["held_by"] = np.where(flips, np.where(projected == "D", "R", "D"), projected)

    # Silver Bulletin district averages + poll counts (last `poll_days`)
    sb = pd.read_csv(gzip.open(snap + "silver_bulletin_averages.csv.gz"))
    sb = sb[sb["group"] == "House"].sort_values("date").groupby("id").tail(1).copy()
    sb["district"] = [key(*i.split("_")[1].split("-")) for i in sb["id"]]
    sb["poll_margin"] = sb[["avg_D", "avg_D2", "avg_I", "avg_I2"]].max(axis=1) - sb[["avg_R", "avg_R2", "avg_R3"]].max(axis=1)
    polls = pd.read_csv(gzip.open(snap + "silver_bulletin_polls.csv.gz"))
    polls = polls[polls["id"].str.match(r"^\d{4}_[A-Z]{2}-\d+$", na=False)]
    polls["endDate"] = pd.to_datetime(polls["endDate"], errors="coerce")
    recent = polls[polls["endDate"] >= pd.Timestamp.today() - pd.Timedelta(days=poll_days)].copy()
    recent["district"] = [key(*i.split("_")[1].split("-")) for i in recent["id"]]
    # Our own district average: each poll's non-R minus R margin, sponsored polls
    # moved SPONSOR_SHIFT points against the sponsor (56% of these are sponsored).
    def poll_margin(r):
        vals = {"anti_r": [], "r": []}
        for i in (1, 2, 3, 4):
            party, val = r.get(f"party{i}"), r.get(f"value{i}")
            if pd.isna(val) or pd.isna(party):
                continue
            vals["r" if party == "R" else "anti_r"].append(val)
        if not vals["r"] or not vals["anti_r"]:
            return np.nan
        return max(vals["anti_r"]) - max(vals["r"])
    recent["margin"] = recent.apply(poll_margin, axis=1)
    recent["margin_adj"] = recent["margin"] - recent["partisan"].map({"d": SPONSOR_SHIFT, "r": -SPONSOR_SHIFT}).fillna(0)
    counts = recent.groupby("district").agg(n_polls=("id", "size"),
                                            n_partisan=("partisan", lambda s: s.isin(["d", "r"]).sum()),
                                            poll_avg_adj=("margin_adj", "mean"))
    df = df.merge(sb[["district", "poll_margin"]], on="district", how="left").merge(counts, on="district", how="left")
    df[["n_polls", "n_partisan"]] = df[["n_polls", "n_partisan"]].fillna(0).astype(int)

    # Kalshi: KXHOUSERACE-<ST><NN|AL>-26, markets -D / -R
    k = pd.read_csv(snap + "kalshi.csv")
    k = k[k["event"].str.startswith("KXHOUSERACE-", na=False)].copy()
    code = k["event"].str.extract(r"KXHOUSERACE-([A-Z]{2})(AL|\d{2})-")
    k["district"] = [key(s, d) for s, d in zip(code[0], code[1])]
    k["side"] = k["market"].str[-1]
    k["mid"] = (k["yes_bid"] + k["yes_ask"]) / 2
    kd = k[k["side"] == "D"].groupby("district").agg(kalshi_p_d=("mid", "first"), kalshi_spread=("yes_ask", "first"))
    kd["kalshi_spread"] = kd["kalshi_spread"] - k[k["side"] == "D"].groupby("district")["yes_bid"].first()
    kd["kalshi_volume"] = k.groupby("district")["volume"].sum()
    df = df.merge(kd, on="district", how="left")

    # Polymarket: <st>-<nn|al>-house-election-winner[-id]; outcomes labelled (D)/(R)
    p = pd.read_csv(snap + "polymarket.csv")
    p = p[p["event"].str.match(r"^[a-z]{2}-(al|\d{1,2})-house-election-winner(-\d+)?$", na=False)].copy()
    code = p["event"].str.extract(r"^([a-z]{2})-(al|\d{1,2})-")
    p["district"] = [key(s, d) for s, d in zip(code[0], code[1])]
    p["party"] = p["outcome"].str.extract(r"\((D|R|I|Ind)\)\s*$")[0]
    # unlabelled outcomes: match the non-Republican candidate's last name from Split Ticket
    last = df.set_index("district")["dem_name"].str.replace(r"\s*\(.*\)", "", regex=True).str.split().str[-1].str.lower()
    unl = p["party"].isna()
    p.loc[unl, "party"] = [("D" if isinstance(last.get(dd), str) and last.get(dd) in str(o).lower() else None)
                           for dd, o in zip(p.loc[unl, "district"], p.loc[unl, "outcome"])]
    pd_ = p[p["party"].isin(["D", "I", "Ind"])].groupby("district").agg(pm_p_d=("yes_price", "sum"))
    pd_["pm_volume"] = p.groupby("district")["volume"].sum()
    df = df.merge(pd_.clip(upper=1e12), on="district", how="left")
    df["pm_p_d"] = df["pm_p_d"].clip(upper=1)

    # Center: Split Ticket's margin, averaged with our sponsor-adjusted district poll
    # average where there are at least MIN_POLLS polls (one poll is mostly noise).
    polls_ok = df["n_polls"] >= MIN_POLLS
    df["center"] = np.where(polls_ok, df[["st_margin", "poll_avg_adj"]].mean(axis=1), df["st_margin"])
    # top-two races with two Democrats or two Republicans are decided by party already
    df["same_party"] = df["st_margin"].abs() >= 100
    df["state"] = df["district"].str[:2]
    return df.sort_values("district").reset_index(drop=True)


def race_sd(n_polls: np.ndarray) -> np.ndarray:
    n = np.asarray(n_polls, dtype=float)
    sd = np.sqrt(2.5 ** 2 + 25.0 / np.maximum(n, 1))
    sd = np.where(n == 0, 8.0, sd)
    sd = np.where(n == 1, 7.0, sd)
    sd = np.where(n == 2, 6.0, sd)
    sd = np.where(n == 3, 5.0, sd)
    return sd


def simulate(df: pd.DataFrame, center: str = "center", nat_mean: float = 0.0, nat_sd: float = 3.0,
             state_sd: float = 2.7, n: int = 100_000, seed: int = 0, chunk: int = 20_000):
    """P(D majority) and seat distribution. Independents (AK-AL) aren't counted
    toward the Democratic 218."""
    rng = np.random.default_rng(seed)
    c = df[center].to_numpy(float)
    sd = race_sd(df["n_polls"].to_numpy())
    thin = df["n_polls"].to_numpy() <= 3
    states = df["state"].to_numpy()
    uniq, inv = np.unique(states, return_inverse=True)
    counts_d = (~df["d_is_ind"]).to_numpy()
    seats, wins = [], np.zeros(len(df))
    for start in range(0, n, chunk):
        m = min(chunk, n - start)
        nat = nat_mean + nat_sd * _t(rng, 5, (m, 1))
        st = state_sd * rng.standard_normal((m, len(uniq)))[:, inv]
        race = np.where(thin, _t(rng, 6, (m, len(df))), _t(rng, 10, (m, len(df)))) * sd
        d_win = (c + nat + st + race) > 0
        wins += d_win.sum(axis=0)
        seats.append((d_win & counts_d).sum(axis=1))
    seats = np.concatenate(seats)
    out = df.assign(sim_p_d=wins / n, race_sd=sd)
    summary = dict(p_d_majority=(seats >= MAJORITY).mean(), seats_median=float(np.median(seats)),
                   seats_mean=seats.mean(), seats_p10=np.percentile(seats, 10), seats_p90=np.percentile(seats, 90))
    return out, summary, seats


def implied_lean(df: pd.DataFrame, target: float, n: int = 40_000, **kw) -> float:
    """National polling lean (+ = D beat polls) that makes P(D majority) = target."""
    lo, hi = -6.0, 6.0
    for _ in range(14):
        mid = (lo + hi) / 2
        p = simulate(df, nat_mean=mid, n=n, seed=1, **kw)[1]["p_d_majority"]
        lo, hi = (mid, hi) if p < target else (lo, mid)
    return (lo + hi) / 2

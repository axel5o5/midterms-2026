"""Every 2026 race with every source side by side, plus the reasoning behind Holdout's number:
the data behind the map pages (scripts/build_mapbook.py and the live dashboard's map).

One record per race (Senate "SEN-IA", House "IA-01", governor "GOV-IA"), every
probability P(the Democrat, or the non-Republican, wins):
- ours: Senate, the poll average blended with Split Ticket, plus the 2024 carry-over
  (carryover.BETA_PRES, chosen by an out-of-sample backtest), simulated with
  senate.ErrorModel, with the other carryover.VARIANTS alongside; House,
  house.districts()' center simulated with house.simulate. No governor model.
- split_ticket, polls (Silver Bulletin average and 30-day poll count), kalshi and
  polymarket mids (1 - P(Republican), as in live/markets.py), and the published
  raters from Wikipedia's ratings tables (Senate and governor only).
- reasoning: a headline and the steps from the polls to Holdout's number, written from
  the numbers themselves.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import re

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import house as H
from . import carryover as CO
from . import pres2024 as P24
from . import senate as S
from .live import markets as M

STATE_NAMES = {v: k for k, v in S.NAME_TO_ABB.items()}
RATING_SCORE = {"safe": 3, "solid": 3, "likely": 2, "lean": 1, "tilt": 0.5, "tossup": 0}


# ---- ratings -------------------------------------------------------------------------

def ratings(snap: str, page: str) -> dict[str, dict[str, str]]:
    """{'SEN-IA': {'Cook': 'Lean R', ...}} from Wikipedia's ratings table (page: 'senate' or
    'governors'): the article HTML in snapshots from 2026-10-30 on, the API wikitext before."""
    import io
    import os
    html = snap + f"wikipedia_{page}.html.gz"
    if os.path.exists(html):
        tabs = pd.read_html(io.StringIO(gzip.open(html).read().decode()), match="Sabato")
        if not tabs:
            return {}
        t = tabs[0]
        t.columns = [c[-1] if isinstance(c, tuple) else c for c in t.columns]
        raters = {c: re.sub(r"\[.*", "", c).split(" ")[0] for c in t.columns
                  if re.search(r"\b(19|20)\d\d\b", str(c)) and "election" not in str(c).lower()}
        out = {}
        for _, row in t.iterrows():
            ab = S.NAME_TO_ABB.get(re.sub(r"\s*\(.*|\[.*", "", str(row.iloc[0])).strip())
            key = f"{'SEN' if page == 'senate' else 'GOV'}-{ab}"
            if not ab or key in out:          # first row wins (special elections follow)
                continue
            r = {}
            for col, name in raters.items():
                v = re.sub(r"\s*\(flip\)|\[.*", "", str(row[col])).strip()
                if re.match(r"^(Safe|Solid|Likely|Lean|Tilt) [DRI]$|^Tossup$", v):
                    r[name] = v
            if r:
                out[key] = r
        return out
    t = json.load(gzip.open(snap + f"wikipedia_{page}.json.gz"))["parse"]["wikitext"]
    if isinstance(t, dict):
        t = t.get("*") or next(iter(t.values()))
    i = t.find("== Predictions ==")
    if i < 0:
        return {}
    tab = t[t.find("{|", i): t.find("\n|}", t.find("{|", i))]
    out = {}
    for row in tab.split("\n|-")[1:]:
        m = re.search(r"^!\s*\[\[[^|\]]*\|([^\]]+)\]\]", row.strip(), re.M)
        if not m:
            continue
        name = re.sub(r"\s*\(.*", "", m.group(1)).strip()
        ab = S.NAME_TO_ABB.get(name)
        if not ab:
            continue
        r = {}
        for src, cell in re.findall(r"<!--\s*([^>]+?)\s*-->\s*\|([^\n]*)", row):
            hit = re.search(r"USRaceRating\|([A-Za-z]+)(?:\|([A-Z]))?", cell)
            if hit:
                lvl, party = hit.group(1).capitalize(), hit.group(2)
                r[src] = "Tossup" if lvl.lower() == "tossup" else f"{lvl} {party or ''}".strip()
        if r:
            key = f"{'SEN' if page == 'senate' else 'GOV'}-{ab}"
            out[key] = r if key not in out else out[key]   # first table row wins (special elections follow)
    return out


def rating_score(r: dict[str, str]) -> float | None:
    """Mean rating on -3 (Safe R) .. +3 (Safe D)."""
    vals = []
    for v in r.values():
        lvl, *party = v.split()
        s = RATING_SCORE.get(lvl.lower())
        if s is None:
            continue
        vals.append(0 if not party else s if party[0] == "D" else -s)
    return float(np.mean(vals)) if vals else None


def rating_summary(r: dict[str, str]) -> str:
    if not r:
        return ""
    c = pd.Series(list(r.values())).value_counts()
    return ", ".join(f"{n} {k}" for k, n in c.items())


# ---- markets -------------------------------------------------------------------------

def governor_universe(snap: str) -> pd.DataFrame:
    rows = []
    k = pd.read_csv(snap + "kalshi.csv")
    g = k[k["event"].str.match(r"^GOVPARTY[A-Z]{2}-26$", na=False)]
    for ev, gg in g.groupby("event"):
        st = ev[8:10]
        r = gg[gg["market"].str.endswith("-R")]
        if len(r):
            rows.append(dict(race=f"GOV-{st}", venue="kalshi", id=r["market"].iloc[0], invert=True, label=r["outcome"].iloc[0]))
    raw = json.load(gzip.open(snap + "polymarket_raw.json.gz"))
    for e in raw:
        hit = re.match(r"^([a-z-]+)-governor-(?:winner|election)-2026$", e.get("slug") or "")
        if not hit:
            continue
        st = S.NAME_TO_ABB.get(hit.group(1).replace("-", " ").title())
        if not st:
            continue
        ms = [m for m in e.get("markets", []) if m.get("clobTokenIds") and not m.get("closed")]
        rep = [m for m in ms if "(R)" in (m.get("groupItemTitle") or "")]
        if len(rep) == 1:
            rows.append(dict(race=f"GOV-{st}", venue="polymarket", id=json.loads(rep[0]["clobTokenIds"])[0], invert=True,
                             label=rep[0]["groupItemTitle"]))
    return pd.DataFrame(rows)


def governor_names(snap: str) -> dict[str, tuple[str | None, str | None]]:
    """GOV-XX -> (Democrat, Republican) nominee names, from Polymarket's party-labelled
    outcomes, else Kalshi's GOVPARTY markets."""
    out: dict[str, list] = {}
    k = pd.read_csv(snap + "kalshi.csv")
    for r in k[k["event"].str.match(r"^GOVPARTY[A-Z]{2}-26$", na=False)].itertuples():
        side = r.market.rsplit("-", 1)[-1]
        if side in ("D", "R"):
            out.setdefault(f"GOV-{r.event[8:10]}", [None, None])[0 if side == "D" else 1] = r.outcome
    for e in json.load(gzip.open(snap + "polymarket_raw.json.gz")):
        hit = re.match(r"^([a-z-]+)-governor-(?:winner|election)-2026$", e.get("slug") or "")
        st = S.NAME_TO_ABB.get(hit.group(1).replace("-", " ").title()) if hit else None
        if not st:
            continue
        for m in e.get("markets", []):
            lab = m.get("groupItemTitle") or ""
            for i, tag in enumerate(("(D)", "(R)")):
                if tag in lab:
                    out.setdefault(f"GOV-{st}", [None, None])[i] = lab.replace(tag, "").strip()
    return {k: tuple(v) for k, v in out.items()}


def market_mids(snap: str, venues: tuple[str, ...] = ("kalshi", "polymarket")) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Live quotes now for every race mapped; (per race x venue quotes, universe with labels).
    Public builds pass venues=("polymarket",): Kalshi's developer agreement (v1.1, section 3)
    doesn't allow sharing its API data."""
    u = pd.concat([M.universe(snap), governor_universe(snap)], ignore_index=True)
    u = u[u["venue"].isin(venues)]
    q = M.poll(u)
    return q, u


# ---- per-race tables -----------------------------------------------------------------

def _p(m, sd):
    return np.clip(norm.cdf(np.asarray(m, float) / np.asarray(sd, float)), 0.005, 0.995)


def _fmt_m(m) -> str:
    if m is None or not np.isfinite(m):
        return "n/a"
    return ("D+" if m >= 0 else "R+") + f"{abs(m):.1f}"


def _pct(p) -> str:
    if p is None or not np.isfinite(p):
        return "n/a"
    return ">99%" if p > 0.99 else "<1%" if p < 0.01 else f"{int(100 * p + 0.5 + 1e-9)}%"   # half up, as the page's JS rounds (1e-9: 0.445 is 44.4999... in floating point)


def senate(snap: str) -> tuple[pd.DataFrame, dict]:
    df = S.races(snap)
    variants = {}
    for v in CO.VARIANTS:
        m = CO.center(df, v)
        sim, sm = S.simulate(df.assign(_c=m), "_c", S.ErrorModel(), n=100_000, seed=0)
        variants[v] = (m.to_numpy(), sim["sim_p_d"].to_numpy(), sm)
    m, p, summ = variants["robust"]
    df["ours_margin"], df["ours_p"] = m, p
    df["ours_sd"] = np.sqrt(3.0 ** 2 + sim["race_sd"].to_numpy() ** 2)
    for v, (vm, vp, _) in variants.items():
        df[f"var_{v}"] = vp
    summ["variants"] = {v: float(sm["p_d_control"]) for v, (_, _, sm) in variants.items()}
    names = pd.read_csv(gzip.open(snap + "split_ticket_senate_seats.csv.gz"))
    names["state"] = names["State"].map(S.NAME_TO_ABB)
    df = df.merge(names[["state", "dem_name", "rep_name", "bucket"]], on="state", how="left")
    df["race"] = "SEN-" + df["state"]
    return df, summ


def governors(snap: str) -> pd.DataFrame:
    sb = pd.read_csv(gzip.open(snap + "silver_bulletin_averages.csv.gz"))
    sb = sb[sb["group"] == "Governor"].sort_values("date").groupby("id").tail(1).copy()
    sb["state"] = sb["id"].str.extract(r"_([A-Z]{2})-G")[0]
    sb["poll_margin"] = sb[[c for c in ("avg_D", "avg_D2", "avg_I", "avg_I2") if c in sb]].max(axis=1) - \
        sb[[c for c in ("avg_R", "avg_R2", "avg_R3") if c in sb]].max(axis=1)
    polls = pd.read_csv(gzip.open(snap + "silver_bulletin_polls.csv.gz"))
    polls = polls[polls["id"].str.match(r"^2026_[A-Z]{2}-G", na=False)].copy()
    polls["endDate"] = pd.to_datetime(polls["endDate"], errors="coerce")
    n = polls[polls["endDate"] >= pd.Timestamp.today() - pd.Timedelta(days=30)].groupby(
        polls["id"].str.extract(r"_([A-Z]{2})-G")[0]).size()
    sb["n_polls_30d"] = sb["state"].map(n).fillna(0).astype(int)
    sb["race"] = "GOV-" + sb["state"]
    return sb[["race", "state", "poll_margin", "n_polls_30d"]].dropna(subset=["state"])


# ---- reasoning -----------------------------------------------------------------------

def _market(r) -> float | None:
    v = [x for x in (r.get("kalshi"), r.get("polymarket")) if x is not None and np.isfinite(x)]
    return float(np.mean(v)) if v else None


def senate_reasoning(r: dict) -> dict:
    lines = []
    if r["n_polls"] and np.isfinite(r["polls_margin"]):
        lines.append(f"Polling average {_fmt_m(r['polls_margin'])} from {r['n_polls']} polls in the last 30 days (Silver Bulletin).")
        adj = r["poll_adj"] - r["polls_margin"]
        if abs(adj) >= 0.1:
            lines.append(f"Lean adjustment {adj:+.1f}: candidates polling {abs(r['polls_margin'] - r['lean_2024']):.0f} points "
                         f"{'above' if r['polls_margin'] > r['lean_2024'] else 'below'} their state's 2024 result "
                         f"({_fmt_m(r['lean_2024'])}) have tended to fall back toward it.")
    else:
        lines.append("No public polls in the last 30 days.")
    lines.append(f"Split Ticket's model: {_fmt_m(r['split_ticket_margin'])} ({_pct(r['split_ticket'])}).")
    lines.append(f"Holdout averages the polls with Split Ticket: {_fmt_m(r['blend'])}.")
    co = r["ours_margin"] - r["blend"]
    if abs(co) >= 0.1:
        lines.append(f"2024 carry-over {co:+.1f}: the state's 2024 presidential polls missed by {r['miss24_rel']:+.1f} beyond the "
                     f"national miss, and about {100 * CO.BETA_PRES:.0f}% of that kind of miss has carried into the next midterm "
                     f"(fitted on 1998-2022 midterms and tested one year at a time).")
    lines.append(f"Result: {_fmt_m(r['ours_margin'])} with an SD of {r['ours_sd']:.1f} points, so {_pct(r['ours'])} for the Democrat.")
    return dict(headline=_headline(r), lines=lines)


def house_reasoning(r: dict) -> dict:
    lines = [f"Split Ticket's model: {_fmt_m(r['split_ticket_margin'])} ({_pct(r['split_ticket'])}), rated {r['rating_text'] or 'n/a'}."]
    if r["n_polls"] >= H.MIN_POLLS and np.isfinite(r.get("poll_avg_adj") or np.nan):
        lines.append(f"{r['n_polls']} district polls in 60 days average {_fmt_m(r['poll_avg_adj'])} after moving sponsored polls "
                     f"{H.SPONSOR_SHIFT:.0f} points against the sponsor; Holdout averages that with Split Ticket: {_fmt_m(r['ours_margin'])}.")
    else:
        lines.append(f"{'One district poll' if r['n_polls'] == 1 else 'No district polls'}: Holdout uses Split Ticket's margin.")
    lines.append(f"Uncertainty ±{r['ours_sd']:.1f} points (national, state and district error), so {_pct(r['ours'])} for the Democrat.")
    return dict(headline=_headline(r), lines=lines)


def governor_reasoning(r: dict) -> dict:
    m = _market(r)
    lines = []
    if r["n_polls"] and np.isfinite(r["polls_margin"]):
        lines.append(f"Polling average {_fmt_m(r['polls_margin'])} from {r['n_polls']} polls in the last 30 days (Silver Bulletin).")
    if r["rating_text"]:
        lines.append(f"Raters: {r['rating_text']}.")
    lines.append("Holdout doesn't model governor races; this shows the sources side by side.")
    head = f"Markets give the Democrat {_pct(m)}." if m is not None else "No market prices."
    return dict(headline=head, lines=lines)


def _headline(r: dict) -> str:
    ours, m = r.get("ours"), _market(r)
    if m is None:
        return f"Holdout gives the Democrat {_pct(ours)}; no market prices."
    gap = 100 * (ours - m)
    if abs(gap) < 5:
        return f"Holdout and the markets agree: {_pct(ours)} vs {_pct(m)}."
    side = "less" if gap < 0 else "more"
    why = ""
    sd = r.get("ours_sd")
    if sd and 0.02 < m < 0.98:
        implied = sd * norm.ppf(m)
        why += (f" At Holdout's uncertainty (±{sd:.1f}) the market price means about {_fmt_m(implied)}, against Holdout's "
                f"{_fmt_m(r['ours_margin'])}: {abs(implied - r['ours_margin']):.1f} points of margin apart.")
    if r["office"] == "S":
        steps = {"the lean adjustment": r["poll_adj"] - r["polls_margin"] if r["n_polls"] else 0.0,
                 "the 2024 carry-over": r["ours_margin"] - r["blend"],
                 "Split Ticket's lower number" if r["split_ticket_margin"] < r["ours_margin"] else "Split Ticket's higher number":
                     0.5 * (r["split_ticket_margin"] - (r["poll_adj"] if r["n_polls"] else r["split_ticket_margin"]))}
        big = max(steps.items(), key=lambda kv: -kv[1] if gap < 0 else kv[1])
        if (gap < 0 and big[1] < -0.3) or (gap > 0 and big[1] > 0.3):
            why += f" Its biggest step that way: {big[0]} ({big[1]:+.1f})."
    elif r["office"] == "H":
        why += " With no district polls Holdout leans on Split Ticket's fundamentals." if r["n_polls"] < H.MIN_POLLS else ""
    return f"Holdout is {abs(gap):.0f} points {side} bullish on the Democrat than markets ({_pct(ours)} vs {_pct(m)}).{why}"


# ---- build ---------------------------------------------------------------------------

def build(snap: str | None = None, venues: tuple[str, ...] = ("kalshi", "polymarket")) -> dict:
    snap = snap or S.latest_snapshot()
    q, u = market_mids(snap, venues)
    mids = q.pivot_table(index="race", columns="venue", values="mid", aggfunc="first")
    rate = {**ratings(snap, "senate"), **ratings(snap, "governors")}
    races = []

    sen, summ = senate(snap)
    for r in sen.itertuples():
        rec = dict(race=r.race, office="S", state=r.state, dem=r.dem_name, rep=r.rep_name, held_by=r.held_by,
                   ours=float(r.ours_p), ours_margin=float(r.ours_margin), ours_sd=float(r.ours_sd),
                   split_ticket=float(r.st_p_d), split_ticket_margin=float(r.st_margin),
                   polls_margin=float(r.poll_margin) if pd.notna(r.poll_margin) else np.nan, n_polls=int(r.n_polls_30d or 0),
                   poll_adj=float(r.poll_adj) if pd.notna(r.poll_adj) else np.nan, blend=float(r.blend),
                   lean_2024=float(r.lean_2024), miss24_rel=float(r.miss24_rel) if pd.notna(r.miss24_rel) else 0.0,
                   variants={v: float(sen.loc[r.Index, f"var_{v}"]) for v in CO.VARIANTS})
        races.append(rec)

    h = H.districts(snap)
    hs, hsum, _ = H.simulate(h, n=40_000, seed=0)
    for r in hs.itertuples():
        if r.same_party:
            continue
        races.append(dict(race=r.district, office="H", state=r.state, dem=r.dem_name, rep=r.rep_name, held_by=r.held_by,
                          ours=float(r.sim_p_d), ours_margin=float(r.center),
                          ours_sd=float(np.sqrt(3.0 ** 2 + 2.7 ** 2 + r.race_sd ** 2)),
                          split_ticket=float(r.st_p_d), split_ticket_margin=float(r.st_margin), n_polls=int(r.n_polls),
                          poll_avg_adj=float(r.poll_avg_adj) if pd.notna(r.poll_avg_adj) else np.nan,
                          polls_margin=np.nan, rating_text=r.bucket))

    gov = governors(snap)
    labels = u[u["race"].str.startswith("GOV-")].groupby("race")["label"].first()
    gnames = governor_names(snap)
    for st in sorted({k.split("-")[1] for k in mids.index if k.startswith("GOV-")} | set(gov["state"])):
        g = gov[gov["state"] == st]
        races.append(dict(race=f"GOV-{st}", office="G", state=st,
                          dem=gnames.get(f"GOV-{st}", (None, None))[0],
                          rep=gnames.get(f"GOV-{st}", (None, None))[1] or re.sub(r"\s*\(R\)", "", labels.get(f"GOV-{st}", "") or "") or None,
                          held_by=None,
                          ours=None, polls_margin=float(g["poll_margin"].iloc[0]) if len(g) else np.nan,
                          n_polls=int(g["n_polls_30d"].iloc[0]) if len(g) else 0))

    for rec in races:
        k = rec["race"]
        rec["kalshi"] = _f(mids.loc[k, "kalshi"]) if k in mids.index and "kalshi" in mids else None
        rec["polymarket"] = _f(mids.loc[k, "polymarket"]) if k in mids.index and "polymarket" in mids else None
        if rec["office"] != "H":
            rec["ratings"] = rate.get(k, {})
            rec["rating_score"] = rating_score(rec["ratings"])
            rec["rating_text"] = rating_summary(rec["ratings"])
        rec["market"] = _market(rec)
        rec["reasoning"] = (senate_reasoning if rec["office"] == "S" else house_reasoning if rec["office"] == "H"
                            else governor_reasoning)(rec)
        rec["name"] = (f"{STATE_NAMES.get(rec['state'], rec['state'])} {'Senate' if rec['office'] == 'S' else 'governor' if rec['office'] == 'G' else ''}".strip()
                       if rec["office"] != "H" else k)

    st_ctrl = {c: pd.read_csv(gzip.open(snap + f"split_ticket_control_{x}.csv.gz")).set_index("Group")["Probability"].get("Democrats")
               for c, x in (("H", "a"), ("S", "b"))}
    control = {c: dict(ours=float(v), split_ticket=float(st_ctrl[c]) / 100 if st_ctrl[c] is not None else None,
                       kalshi=_f(mids.loc[f"CONTROL-{c}", "kalshi"]) if f"CONTROL-{c}" in mids.index and "kalshi" in mids else None,
                       polymarket=_f(mids.loc[f"CONTROL-{c}", "polymarket"]) if f"CONTROL-{c}" in mids.index and "polymarket" in mids else None)
               for c, v in (("S", summ["p_d_control"]), ("H", hsum["p_d_majority"]))}
    control["S"]["variants"] = summ["variants"]
    control["S"]["seats"] = dict(mean=float(summ["mean_d_seats"]), p10=float(summ["seats_p10"]), p90=float(summ["seats_p90"]))
    control["H"]["seats"] = dict(median=float(hsum["seats_median"]), p10=float(hsum["seats_p10"]), p90=float(hsum["seats_p90"]))
    return dict(asof=dt.datetime.now(dt.UTC).isoformat(timespec="minutes"), snapshot=snap.rstrip("/").split("snapshots/")[-1],
                control=control, races=[_clean(r) for r in races])


def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _clean(d):
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_clean(v) for v in d]
    if isinstance(d, (float, np.floating)):
        return None if not np.isfinite(d) else round(float(d), 4)
    if isinstance(d, np.integer):
        return int(d)
    return d

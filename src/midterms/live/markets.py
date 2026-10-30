"""Live Kalshi and Polymarket prices for every race we model, for election night.

Both batch endpoints are fast (tested 2026-10-29): Kalshi `/markets?tickers=`
returns 40 markets in ~0.07s, Polymarket `POST /midpoints` 32 tokens in ~0.15s,
so polling everything every few seconds stays well inside polite rates.

Race keys: Senate "SEN-TX", House "TX-28" / "AK-AL", chambers "CONTROL-S" /
"CONTROL-H". Every price is P(the Democrat, or the non-Republican, wins).
Kalshi's Senate tickers don't always match the state (SENATELA is titled
Kentucky), so markets are mapped by their title.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

from ..house import key as hkey
from ..senate import NAME_TO_ABB, latest_snapshot
from ..snapshot import ROOT

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
CLOB = "https://clob.polymarket.com"
LIVE = ROOT / "data" / "live"
_s = requests.Session()
_s.headers["User-Agent"] = "Mozilla/5.0 (personal election research)"


def universe(snap: str | None = None) -> pd.DataFrame:
    """Every market to watch: race, venue, id (Kalshi ticker / Polymarket token), invert.

    Candidate races are priced from the Republican's market, inverted: P(non-Republican
    wins) = 1 - P(Republican wins), and buying NO on the Republican is the trade. That
    sidesteps the long lists of minor and placeholder outcomes ("Candidate C".."Q") whose
    prices would otherwise be summed. Races with no Republican outcome (same-party top-two)
    fall back to a single Democratic outcome. Chamber control uses the Democratic market.
    """
    snap = snap or latest_snapshot()
    rows = []
    k = pd.read_csv(snap + "kalshi.csv")
    for chamber in ("S", "H"):
        m = k[k["market"] == f"CONTROL{chamber}-2026-D"]
        if len(m):
            rows.append(dict(race=f"CONTROL-{chamber}", venue="kalshi", id=m["market"].iloc[0], invert=False, label="Democrats"))
    # Senate: "<State> Senate winner?" events; mapped by title (SENATELA is titled Kentucky)
    sen = k[k["event_title"].str.match(r"^[A-Z][A-Za-z ]+ Senate winner\?$", na=False)].copy()
    sen["state"] = sen["event_title"].str.replace(" Senate winner?", "", regex=False).map(NAME_TO_ABB)
    for st, g in sen.dropna(subset=["state"]).groupby("state"):
        r = g[g["market"].str.endswith("-R")]
        if len(r):
            rows.append(dict(race=f"SEN-{st}", venue="kalshi", id=r["market"].iloc[0], invert=True, label=r["outcome"].iloc[0]))
    # House: KXHOUSERACE-<ST><NN>-26-R (or -D where there's no Republican)
    hs = k[k["event"].str.startswith("KXHOUSERACE", na=False)].copy()
    for ev, g in hs.groupby("event"):
        hit = re.match(r"KXHOUSERACE-([A-Z]{2})(\d{1,2}|AL)-", ev)
        if not hit:
            continue
        race = hkey(*hit.groups())
        r, d = g[g["market"].str.endswith("-R")], g[g["market"].str.endswith("-D")]
        if len(r):
            rows.append(dict(race=race, venue="kalshi", id=r["market"].iloc[0], invert=True, label=r["outcome"].iloc[0]))
        elif len(d):
            rows.append(dict(race=race, venue="kalshi", id=d["market"].iloc[0], invert=False, label=d["outcome"].iloc[0]))

    rep_last, dem_last = _last_names(snap)
    raw = json.load(gzip.open(snap + "polymarket_raw.json.gz"))
    for e in raw:
        slug = e.get("slug") or ""
        race = None
        if slug.startswith("which-party-will-win-the-senate-in-2026"):
            race = "CONTROL-S"
        elif slug.startswith("which-party-will-win-the-house-in-2026"):
            race = "CONTROL-H"
        elif "senate-election-winner" in slug:
            st = NAME_TO_ABB.get(slug.split("-senate-election-winner")[0].replace("-", " ").title())
            race = f"SEN-{st}" if st else None
        else:
            hit = re.match(r"^([a-z]{2})-(\d{1,2}|al)-house-election-winner", slug)
            if hit:
                race = hkey(*hit.groups())
        if not race:
            continue
        ms = [m for m in e.get("markets", []) if m.get("clobTokenIds") and not m.get("closed")]
        labels = [m.get("groupItemTitle") or m.get("question") or "" for m in ms]
        tok = lambda m: json.loads(m["clobTokenIds"])[0]
        if race.startswith("CONTROL"):
            pick = [(m, l, False) for m, l in zip(ms, labels) if "Democratic" in l][:1]
        else:
            rl, dl = rep_last.get(race, ""), dem_last.get(race, "")
            rep = [(m, l) for m, l in zip(ms, labels) if "(R)" in l or (rl and rl in l.lower())]
            dem = [(m, l) for m, l in zip(ms, labels) if "(D)" in l or (dl and dl in l.lower())]
            pick = [(rep[0][0], rep[0][1], True)] if len(rep) == 1 else [(dem[0][0], dem[0][1], False)] if len(dem) == 1 else []
        for m, l, inv in pick:
            rows.append(dict(race=race, venue="polymarket", id=tok(m), invert=inv, label=l))
    return pd.DataFrame(rows).drop_duplicates(["race", "venue"])


def _last_names(snap: str) -> tuple[dict[str, str], dict[str, str]]:
    """race key -> lower-case last name of the Republican, and of the non-Republican, from Split Ticket."""
    out, dem = {}, {}
    last = lambda n: re.sub(r"\s*\(.*\)", "", n).split()[-1].lower()
    st = pd.read_csv(gzip.open(snap + "split_ticket_senate_seats.csv.gz"))
    for r in st.itertuples():
        ab = NAME_TO_ABB.get(r.State)
        if ab and isinstance(r.rep_name, str):
            out[f"SEN-{ab}"] = last(r.rep_name)
        if ab and isinstance(r.dem_name, str):
            dem[f"SEN-{ab}"] = last(r.dem_name)
    try:
        from ..house import districts
        h = districts(snap)
        for r in h.itertuples():
            if isinstance(r.rep_name, str):
                out[r.district] = last(r.rep_name)
            if isinstance(r.dem_name, str):
                dem[r.district] = last(r.dem_name)
    except Exception:
        pass
    return out, dem


def _kalshi(tickers: list[str]) -> pd.DataFrame:
    out = []
    for i in range(0, len(tickers), 100):
        r = _s.get(KALSHI + "/markets", params={"tickers": ",".join(tickers[i:i + 100]), "limit": 200}, timeout=20)
        r.raise_for_status()
        for m in r.json().get("markets", []):
            bid, ask = float(m.get("yes_bid_dollars") or 0), float(m.get("yes_ask_dollars") or 0)
            out.append(dict(id=m["ticker"], bid=bid, ask=ask, mid=(bid + ask) / 2 if ask else bid,
                            last=float(m.get("last_price_dollars") or 0), volume=float(m.get("volume_fp") or 0)))
        time.sleep(0.1)
    return pd.DataFrame(out)


def _polymarket(tokens: list[str]) -> pd.DataFrame:
    out = []
    for i in range(0, len(tokens), 200):
        chunk = tokens[i:i + 200]
        mids = _s.post(CLOB + "/midpoints", json=[{"token_id": t} for t in chunk], timeout=20).json()
        px = _s.post(CLOB + "/prices", json=[{"token_id": t, "side": s} for t in chunk for s in ("BUY", "SELL")],
                     timeout=20).json()
        for t in chunk:
            p = px.get(t, {})
            # CLOB /prices: "BUY" is the best bid and "SELL" the best ask (checked against
            # /book on 2026-10-30; the earlier reading had them swapped)
            out.append(dict(id=t, bid=float(p.get("BUY", "nan")), ask=float(p.get("SELL", "nan")),
                            mid=float(mids.get(t, "nan"))))
        time.sleep(0.1)
    return pd.DataFrame(out)


def to_race(u: pd.DataFrame, quotes: pd.DataFrame) -> pd.DataFrame:
    """Per-market quotes (id, bid, ask) -> per race and venue, in P(non-Republican wins).
    Inverted markets: bid = 1 - ask(R), ask = 1 - bid(R). A missing side stays NaN."""
    q = u.merge(quotes, on="id", how="left")
    inv = q["invert"].astype(bool)
    bid, ask = q["bid"].where(q["bid"] > 0), q["ask"].where((q["ask"] > 0) & (q["ask"] < 1))
    q["bid"] = (1 - ask).where(inv, bid)
    q["ask"] = (1 - bid).where(inv, ask)
    q["mid"] = (q["bid"] + q["ask"]) / 2
    return q[["race", "venue", "bid", "ask", "mid"]]


def poll(u: pd.DataFrame) -> pd.DataFrame:
    """One REST pass over every market; race, venue, bid, ask, mid with a UTC timestamp."""
    ts = dt.datetime.now(dt.UTC)
    k = _kalshi(u.loc[u["venue"] == "kalshi", "id"].tolist())
    p = _polymarket(u.loc[u["venue"] == "polymarket", "id"].tolist())
    return to_race(u, pd.concat([k, p], ignore_index=True)).assign(ts=ts)


def log(prices: pd.DataFrame, day: str | None = None) -> Path:
    day = day or dt.date.today().isoformat()
    path = LIVE / day / "prices.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(path, mode="a", header=not path.exists(), index=False)
    return path

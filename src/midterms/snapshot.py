"""Daily snapshots of 2026 midterm odds, through election night.

Market prices on Kalshi and Polymarket stay retrievable after settlement, but
forecasters' and pollsters' daily numbers mostly don't, and neither does the
full list of which markets existed. So each run saves:

- Kalshi: every open event in the House/Senate/governor/control series for
  2026, with its markets' bid/ask/last/volume (flat CSV + raw JSON).
- Polymarket: every open event tagged `midterms`, with its markets' prices.
- Forecasters and polling averages: each URL in `FORECAST_SOURCES`, saved raw.

Files land in data/snapshots/<YYYY-MM-DD>/<HHMM>/ and are committed: this is
the record that can't be rebuilt later.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / "data" / "snapshots"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
STOP_AFTER = dt.date(2026, 11, 6)  # results are in; markets keep their own history
KALSHI_KEYS = ("HOUSE", "SENATE", "GOV", "CONTROL")

# Tested 2026-10-29 from this machine, no login. name -> (url, file suffix); saved gzipped.
# Left out on purpose: DDHQ / The Hill (robots.txt disallows AI crawlers; removed 2026-10-29),
# 270toWin (robots.txt disallows AI crawlers; removed 2026-10-29), VoteHub (its robots.txt prohibits automated collection of
# its data without written permission; removed 2026-10-29), The Economist (robots.txt
# blocks automated fetches), Race to
# the WH (robots.txt; its data embeds hadn't updated in weeks), and anything behind a
# login or a bot wall (Cook, Sabato, Inside Elections, NYT, RCP, Silver Bulletin's
# paid model). Cook/Sabato/Inside ratings come through Wikipedia.
_SB = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vSyuZYuGnnjFdpjryAiGq6SeRe0ZOoGHKYzPzbxF1X_Ee_cE7411tTG"
       "dUbpRerX8_Xe7uRfw_Rkd1Hj/pub?single=true&output=csv&gid=")
# Wikipedia article pages (/wiki/), which robots.txt allows. Until 2026-10-30 this used
# the API (/w/api.php), which robots.txt disallows for every crawler; snapshots before
# then hold that JSON (wikipedia_*.json.gz), later ones the article HTML (.html.gz).
_WIKI = "https://en.wikipedia.org/wiki/"
FORECAST_SOURCES: dict[str, tuple[str, str]] = {
    # Silver Bulletin polling averages (generic ballot, House, Senate, governor) and the polls behind them
    "silver_bulletin_averages": (_SB + "0", ".csv"),
    "silver_bulletin_polls": (_SB + "523113073", ".csv"),
    # ratings: Wikipedia's tables carry Cook / Sabato / Inside Elections
    "wikipedia_senate": (_WIKI + "2026_United_States_Senate_elections", ".html"),
    "wikipedia_house": (_WIKI + "2026_United_States_House_of_Representatives_elections", ".html"),
    "wikipedia_governors": (_WIKI + "2026_United_States_gubernatorial_elections", ".html"),
}
# Split Ticket's model is published as Datawrapper charts; each id redirects to its
# current version, and an explicit old version would return an old CSV.
DATAWRAPPER = {"split_ticket_house_seats": "u9EZf", "split_ticket_senate_seats": "g4hHM",
               "split_ticket_control_a": "5UEYH", "split_ticket_control_b": "toEMi",
               "split_ticket_seat_dist_a": "gKHb7", "split_ticket_seat_dist_b": "X2WrG"}


def _datawrapper_csv(chart_id: str) -> tuple[bytes, str]:
    import re
    page = _get(f"https://datawrapper.dwcdn.net/{chart_id}/").text  # a meta-refresh to the current version
    hit = re.search(r"url=(https://datawrapper\.dwcdn\.net/[^/]+/\d+/)", page)
    if not hit:
        raise ValueError(f"no version redirect found for {chart_id}")
    base = hit.group(1)
    return _get(base + "dataset.csv").content, base

_s = requests.Session()
_s.headers["User-Agent"] = "Mozilla/5.0 (personal election research; one fetch a day)"


def _get(url: str, params: dict | None = None, *, tries: int = 6, timeout: float = 60) -> requests.Response:
    for i in range(tries):
        r = _s.get(url, params=params, timeout=timeout)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** i)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def _is_2026_midterm(event_ticker: str) -> bool:
    parts = event_ticker.split("-")
    if len(parts) < 2 or not any(k in parts[0] for k in KALSHI_KEYS):
        return False
    return parts[-1] == "2026" or parts[-1].startswith("26")


def kalshi() -> tuple[list[dict], list[dict]]:
    events, cursor = [], None
    while True:
        params = {"status": "open", "limit": 200, "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        js = _get(KALSHI + "/events", params).json()
        events += [e for e in js.get("events", []) if _is_2026_midterm(e["event_ticker"])]
        cursor = js.get("cursor")
        if not cursor:
            break
        time.sleep(0.25)
    rows = []
    for e in events:
        for m in e.get("markets", []):
            rows.append(dict(source="kalshi", event=e["event_ticker"], event_title=e.get("title"),
                             market=m["ticker"], outcome=m.get("yes_sub_title"),
                             yes_bid=m.get("yes_bid_dollars"), yes_ask=m.get("yes_ask_dollars"),
                             last=m.get("last_price_dollars"), volume=m.get("volume_fp"),
                             close_time=m.get("close_time")))
    return events, rows


def polymarket() -> tuple[list[dict], list[dict]]:
    events, offset = [], 0
    while True:
        page = _get(GAMMA + "/events", {"tag_slug": "midterms", "closed": "false", "limit": 100, "offset": offset}).json()
        events += page
        if len(page) < 100:
            break
        offset += 100
        time.sleep(0.1)
    rows = []
    for e in events:
        for m in e.get("markets", []):
            if not m.get("outcomePrices"):
                continue  # placeholder outcomes ("Party A")
            rows.append(dict(source="polymarket", event=e["slug"], event_title=e.get("title"),
                             market=m.get("id"), outcome=m.get("groupItemTitle") or m.get("question"),
                             yes_price=json.loads(m["outcomePrices"])[0], best_bid=m.get("bestBid"),
                             best_ask=m.get("bestAsk"), volume=m.get("volumeNum"), end_date=m.get("endDate")))
    return events, rows


PM_EVENT_KEYS = ("id", "slug", "title", "startDate", "endDate", "volume", "liquidity", "closed")
PM_MARKET_KEYS = ("id", "question", "groupItemTitle", "outcomes", "outcomePrices", "clobTokenIds", "bestBid",
                  "bestAsk", "lastTradePrice", "volumeNum", "liquidityNum", "endDate", "closed")


def _slim_polymarket(events: list[dict]) -> list[dict]:
    """Keep what scoring needs later (prices, outcomes, the token ids for price
    history); drop descriptions and images, which are most of the 66MB."""
    return [{**{k: e.get(k) for k in PM_EVENT_KEYS},
             "markets": [{k: m.get(k) for k in PM_MARKET_KEYS} for m in e.get("markets", [])]} for e in events]


def _write_json_gz(path: Path, obj) -> None:
    with gzip.open(path, "wt") as f:
        json.dump(obj, f)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def run(now: dt.datetime | None = None) -> Path | None:
    now = now or dt.datetime.now()
    if now.date() > STOP_AFTER:
        print(f"{now:%Y-%m-%d}: past {STOP_AFTER}, nothing to do")
        return None
    out = SNAPSHOTS / f"{now:%Y-%m-%d}" / f"{now:%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    log = []
    for name, fn in (("kalshi", kalshi), ("polymarket", polymarket)):
        try:
            raw, rows = fn()
            if name == "polymarket":
                raw = _slim_polymarket(raw)
            _write_json_gz(out / f"{name}_raw.json.gz", raw)
            _write_csv(out / f"{name}.csv", rows)
            log.append(f"{name}: {len(raw)} events, {len(rows)} markets")
        except Exception as e:  # one source failing shouldn't lose the others
            log.append(f"{name}: FAILED {e!r}")
    for name, (url, suffix) in FORECAST_SOURCES.items():
        try:
            body = _get(url).content
            with gzip.open(out / f"{name}{suffix}.gz", "wb") as f:
                f.write(body)
            log.append(f"{name}: {len(body):,} bytes")
        except Exception as e:  # one source failing shouldn't lose the others
            log.append(f"{name}: FAILED {e!r}")
        time.sleep(1)
    for name, chart in DATAWRAPPER.items():
        try:
            body, version_url = _datawrapper_csv(chart)
            with gzip.open(out / f"{name}.csv.gz", "wb") as f:
                f.write(body)
            log.append(f"{name}: {len(body):,} bytes from {version_url}")
        except Exception as e:
            log.append(f"{name}: FAILED {e!r}")
    (out / "log.txt").write_text("\n".join(log) + "\n")
    print(f"{out.relative_to(ROOT)}\n  " + "\n  ".join(log))
    return out


if __name__ == "__main__":
    run()

"""Election-night live dashboard: model odds vs Kalshi and Polymarket, updating as votes
and prices move. Reads only; places no orders.

    uv run python scripts/live.py                      # election night (all wired states)
    uv run python scripts/live.py --replay-2024        # 2024 presidential replay, ~12 min, simulated market
    uv run python scripts/live.py --replay-2024 --minutes 5
    uv run python scripts/live.py --states NC FL       # only these results feeds

Opens http://127.0.0.1:8765. Optional Kalshi key for live Kalshi prices (otherwise
Kalshi is checked every 5 s): see src/midterms/live/streams.py. Logs to
data/live/<date>/ (model.csv, quotes.csv, events.csv); replays log to data/live/replay/.
Keep the Mac awake: `caffeinate -i uv run python scripts/live.py`.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import webbrowser

import pandas as pd

from midterms.live import engine as E
from midterms.live import feeds as F
from midterms.live import ingest
from midterms.live import markets as M
from midterms.live import replay as R
from midterms.live import signal as SG
from midterms.live import streams
from midterms.live.server import serve


def build_book(eng, replay: bool) -> None:
    """Map shapes and tiles right away; the pre-election race book (reasoning, sources) after."""
    from midterms import geo as G
    from midterms import house as H
    from midterms import racebook as RB
    base = dict(states=G.states(), tiles=G.house_tiles(H.districts()["district"].tolist()),
                prefix="PRES" if replay else "SEN", races=[])
    eng.book_bytes = json.dumps(base).encode()
    if not replay:
        try:
            book = RB.build()
            eng.book_bytes = json.dumps({**base, "races": book["races"], "control": book["control"]}).encode()
        except Exception as e:
            print(f"race book failed: {e!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="*", default=None)
    ap.add_argument("--replay-2024", action="store_true")
    ap.add_argument("--minutes", type=float, default=12.0, help="replay length")
    ap.add_argument("--edge", type=float, default=E.EDGE_MIN, help="after-fee edge that opens a signal")
    ap.add_argument("--prior-signals", action="store_true", help="also fire on pre-election edges")
    ap.add_argument("--prior", choices=["market", "model"], default="market",
                    help="start each race from the market price at first votes (default) or from our own forecast")
    ap.add_argument("--kalshi-rest", action="store_true", help="ignore a Kalshi key; poll REST")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    if args.replay_2024:
        rows = R.rows_2024()
        miss = pd.read_csv("data/history/pres2024_state_miss.csv").set_index("state")
        states = args.states or list(R.PLANS)
        t0 = time.time() + 3
        feeds = {s: R.ReplayFeed(s, rows[rows["state"] == s], args.minutes, t0, seed=i) for i, s in enumerate(states)}
        priors = {f"PRES-{s}": (float(miss.loc[s, "poll_d_margin"]), 4.9) for s in states}
        names = {f"PRES-{s}": f"{E.STATE_NAMES.get(s, s)}: Harris v Trump (2024)" for s in states}
        eng = E.Engine(feeds=feeds, sen_priors=priors, house=pd.DataFrame(), universe=None, baseline_col="margin20",
                       expected={s: R.expected_2024(s) for s in states}, names=names, mode="replay 2024",
                       edge_min=args.edge, prior_signals=args.prior_signals, log_dir=E.LIVE / "replay",
                       sim_market=R.LaggedMarket(), feed_every=1.0, chambers=False, prior_mode="model")
    else:
        states = args.states or ["NC", "GA", "IA", "SC", "MN", "FL", "TX", "OH", "KS", "NE", "MI"]
        sen, house = SG.priors()
        feeds = {s: F.ADAPTERS[s] for s in states if s in F.ADAPTERS}
        # Kansas: the page you send from your browser (all counties), else the big counties' own sites
        if "KS" in states:
            feeds["KS"] = ingest.combined("KS", fallback=(lambda: F.ADAPTERS["KS"]()) if "KS" in F.ADAPTERS else None)
        eng = E.Engine(feeds=feeds, sen_priors=sen, house=house,
                       universe=M.universe(), names=E.race_names(), mode="live", edge_min=args.edge,
                       prior_signals=args.prior_signals, prior_mode=args.prior)
    eng.start(kalshi_ws=False if args.kalshi_rest else None)
    threading.Thread(target=build_book, args=(eng, args.replay_2024), daemon=True).start()
    srv = serve(eng, port=args.port)
    url = f"http://127.0.0.1:{args.port}"
    kalshi = "websocket (key found)" if streams.kalshi_credentials() and not args.kalshi_rest else "REST every 5s"
    print(f"{eng.mode}: {url}  |  results: {', '.join(eng.feeds)}  |  Kalshi: {kalshi}  |  Ctrl-C to stop")
    if not args.no_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        eng.stop.set()


if __name__ == "__main__":
    main()

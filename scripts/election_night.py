"""Election-night loop, plain terminal version (the live dashboard is scripts/live.py):
poll results feeds and markets, project, log, print the biggest edges.

    uv run python scripts/election_night.py                  # live, every 90s, all wired states
    uv run python scripts/election_night.py --once           # one pass
    uv run python scripts/election_night.py --states NC GA   # only these feeds
    uv run python scripts/election_night.py --test-2024 --once
        # end-to-end check today: 2024 feeds (NC, IA, FL, TX, MN), presidential races,
        # 2024 polling averages as priors, 2020 county margins as the baseline; no market comparison

Reads only; places no orders. Logs to data/live/<date>/signals.csv and prices.csv.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
import traceback

import pandas as pd

from midterms.live import feeds as F
from midterms.live import markets as M
from midterms.live import signal as SG


def gather(states: list[str], test_2024: bool) -> pd.DataFrame:
    frames = []
    for st in states:
        try:
            if test_2024:
                fn = {"NC": lambda: F.nc("2024-11-05"), "IA": lambda: F.clarity("IA", 122322),
                      "FL": lambda: F.fl("2024-11-05"), "TX": lambda: F.tx(49664), "MN": lambda: F.mn("2024-11-05")}.get(st)
                if fn is None:
                    continue
            else:
                fn = F.ADAPTERS.get(st)
                if fn is None:
                    continue
            frames.append(fn())
        except F.Blocked as e:
            print(f"  {st}: skipped, {e}", file=sys.stderr)
        except Exception as e:  # one broken feed shouldn't stop the night
            print(f"  {st}: feed error {e!r}", file=sys.stderr)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=F.COLS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="*", default=["NC", "GA", "IA", "SC", "MN", "FL", "TX", "OH"])
    ap.add_argument("--interval", type=int, default=90)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--test-2024", action="store_true")
    args = ap.parse_args()

    if args.test_2024:
        miss = pd.read_csv("data/history/pres2024_state_miss.csv").set_index("state")
        sen_priors = {f"PRES-{s}": (float(miss.loc[s, "poll_d_margin"]), 4.9) for s in args.states if s in miss.index}
        house = pd.DataFrame(columns=["state", "district", "center"])
        baseline = "margin20"
        universe = None
    else:
        sen_priors, house = SG.priors()
        baseline = "margin24"
        universe = M.universe()

    while True:
        t0 = time.time()
        feed = gather(args.states, args.test_2024)
        prices = None
        if universe is not None:
            try:
                prices = M.poll(universe)
                M.log(prices)
            except Exception as e:
                print(f"  markets: {e!r}", file=sys.stderr)
        try:
            sig, p_ctrl = SG.run_pass(feed, prices, sen_priors, house, baseline_col=baseline)
            if not sig.empty:
                SG.log(sig, p_ctrl)
            stamp = dt.datetime.now().strftime("%H:%M:%S")
            print(f"\n[{stamp}] {feed['state'].nunique()} feeds, {len(sig)} rows"
                  + (f", P(D Senate) {p_ctrl:.1%}" if p_ctrl is not None else ""))
            if prices is not None:
                print(SG.table(sig))
            else:
                print(sig.sort_values("race").round(3).to_string(index=False))
        except Exception:
            traceback.print_exc()
        if args.once:
            break
        time.sleep(max(5, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    main()

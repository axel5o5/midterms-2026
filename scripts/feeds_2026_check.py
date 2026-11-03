"""Run the Iowa, South Carolina and Texas 2026 feeds once against the live hosts.

    uv run python scripts/feeds_2026_check.py            # IA SC TX
    uv run python scripts/feeds_2026_check.py IA

For each state: the election id used, the races and counties found, total votes, and
counties marked complete. Exits 1 if any feed raised or a configured Texas county
failed (a wrong id, a file for another election, a host refusing us), so it can be run on the night before trusting the board.
Requests go through feeds.fetch: robots check, rate limits, raw copies under
data/raw-live/.
"""

from __future__ import annotations

import sys

from midterms.live import feeds as F
from midterms.live import feeds_tx as T


def main(states: list[str]) -> int:
    bad = 0
    for st in states:
        try:
            df = F.ADAPTERS[st]()
        except Exception as e:  # noqa: BLE001 - report every state
            print(f"{st}: FAILED {type(e).__name__}: {e}")
            bad += 1
            continue
        which = {"IA": lambda: f"Clarity {F.feed_id('IA', F.IA_EID_2026)}",
                 "SC": lambda: f"Clarity {F.feed_id('SC', F.SC_EID_2026)}",
                 "TX": lambda: "counties " + ", ".join(sorted(df["county"].unique()))}.get(st, lambda: "")()
        done = df.groupby("fips")["complete"].all().sum() if len(df) else 0
        print(f"{st}: ok, {which}; {len(df)} rows, races {sorted(df['race'].unique())}, "
              f"{df['fips'].nunique()} counties ({done} complete), {df['votes'].sum():,.0f} votes")
        if df.attrs.get("warning"):
            print(f"   FAILED in part: {df.attrs['warning']}")
            bad += 1
        waiting = {c: e for c, e in T.last_errors.items() if e == "no 2026 id yet"} if st == "TX" else {}
        if waiting:
            print(f"   TX counties waiting for an id: {', '.join(waiting)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["IA", "SC", "TX"]))

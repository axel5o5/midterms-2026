# Early vote, 2026 against the same point in 2022

*Research note, 2026-10-29. 2026 figures from the University of Florida Election Lab's early-vote tracker as of 2026-10-29; 2022 figures from snapshots taken as close as possible to the same point before that election (about November 3, 2022).*

**Mixed, with no sign of a polling miss in either direction.** Democrats' share of the party-registered early vote is up on 2022 in North Carolina, Nevada, Oregon, Colorado and Maryland, flat in Maine, and down in Iowa and Pennsylvania. Turnout so far is ahead of 2022's pace in most states with a clean comparison. Early-vote party splits measure who has voted, not how they voted, and they shift with changes in voting rules and habits, so this is context for the polls rather than a correction to them.

---

**How to read the table.** D−R is (Democratic − Republican ballots) as a share of all ballots with a party label, including unaffiliated and minor-party voters, in percentage points. "Share of 2022 final" is ballots cast so far as a percentage of the state's total 2022 turnout. The computed values are in [`early_vote_2022_vs_2026.json`](../data/history/early_vote_2022_vs_2026.json); the script and raw downloads that produced them aren't kept in this repo.

## States with a 2022 snapshot within about a day of November 3

| State | 2022 D−R | 2026 D−R | Change | 2022 share of 2022 final | 2026 share of 2022 final |
|---|---|---|---|---|---|
| NC | +6.8 | +14.6 | +7.7 | 46 | 57 |
| NV | about +1.5 (approximate, from blog text) | +6.0 | about +4.5 | about 47 | 55 |
| OR | +7.5 | +11.8 | +4.3 | 44 | 48 |
| CO | +3.4 | +7.3 | +3.9 | 39 | 48 |
| MD | +38.8 (mail through Oct 31; +41.2 at most with final mail) | +43.2 | +4.4 (+2.0 against the upper bound) | 33 (to 39) | 40 |
| ME | +26.1 | +26.2 | +0.1 | 28 | 36 |
| IA | +21.1 | +14.4 | −6.7 | 22 | 30 |
| PA (mail only, both years) | +49.2 | +40.0 | −9.3 | 19 | 18 |

## States where the 2022 snapshot is off-date (indicative only)

| State (2022 snapshot date) | 2022 D−R | 2026 D−R | Change | 2022 share of 2022 final | 2026 share of 2022 final |
|---|---|---|---|---|---|
| KS (Nov 4, 2022; 2026 as of Oct 28) | −9.6 | +3.3 | +12.9 | 28 | 28 |
| SD (Nov 4) | −23.4 | −23.2 | +0.2 | 23 | 17 |
| NE (Nov 1, from rounded percentages) | −7.2 | −4.6 | +2.6 | 22 | 29 |
| FL (Nov 1, two days early) | −4.5 | −1.8 | +2.7 | 39 | 53 |
| AZ (Nov 6 mail, three days late) | +1.3 | −1.1 | −2.4 | n/a | n/a |
| NJ (Nov 6, late) | +36.1 | +38.4 | +2.3 | n/a | n/a |
| CT (Nov 7 mail, late) | +34.7 | +31.1 | −3.5 | n/a | n/a |

Not used: Louisiana (the 2022 figure came only from a search snippet, because the source blocks AI crawlers), and California (the state publishes no party split for returned ballots; the JSON keeps an approximate figure, flagged).

Not obtained: Utah, New Mexico (read about only: about 260,000 ballots, about 54% Democratic and 34% Republican, per Source NM), Idaho, Wyoming, Delaware, Rhode Island, Oklahoma, West Virginia, Arkansas, Kentucky.

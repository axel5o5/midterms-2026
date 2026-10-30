# Other forecasters and the 2018/2022 track record

*Research notes, 2026-10-29. "T" = I read the source page itself; "R" = read about it secondhand. Toplines are as published on the date shown; only Split Ticket's numbers are collected into the snapshots.*

**Published 2026 Senate odds run from the Economist's 53% to Silver Bulletin's 76% for Democrats, and the spread comes down to how big a national polling miss each assumes and whether markets are an input. In 2018 and 2022 the forecast blending polls, fundamentals and expert ratings scored best across all races and beat the markets on the races they traded, and the markets did about as well as a good model. (On Polymarket's 32 races in 2022, the polls-only forecast did better still.)**

---

## The 2026 models

| model | inputs | error model | House / Senate, D | data public? |
|---|---|---|---|---|
| Silver Bulletin (FLIPR), [method](https://www.natesilver.net/p/flipr-midterms-model-methodology) (T) | polls, fundamentals, expert ratings (~1/6) | national, state, demographic, local layers; slightly fat tails; no SDs published | 95% / 76.4% (Oct 22, R) | generic-ballot polls only |
| The Economist (T page) | polls, fundamentals incl. specials and fundraising | 25,001 simulations; no SDs published | 95% / 53% (Oct 27–28) | no 2026 code; 2020 Stan model on GitHub |
| Strength In Numbers, [method](https://blog.fiftyplusone.news/p/2026-forecast-methodology) (T) | polls, fundamentals, expert ratings | six levels, Student-t ~10 df, SD grows with √days | 99% / 73% (Oct 1) | 2012–2024 backtest only |
| VoteHub, [method PDF](https://votehub.com/wp-content/uploads/2026/05/2026_votehub_midterm_methodology.pdf) (T) | fundamentals, polls, ratings, **Kalshi** | multivariate normal, SD = a + b·days^ν | – / 60% (Oct 23, R) | no (and its terms prohibit automated collection) |
| DDHQ / The Hill, [docs](https://votes-docs.decisiondeskhq.com) (T) | Kalman generic ballot, FEC money, polls, **Polymarket/Kalshi by √volume** | one national factor, normal race errors | 79% / 57–60% | race JSON is public, but The Hill's robots.txt disallows AI crawlers, so I stopped collecting it on 2026-10-29 |
| Split Ticket (The Argument), [method](https://www.theargumentmag.com/p/split-ticket-2026-midterms-model) (T) | see the method page | correlated demographic, state and national errors (sizes not published); implied ~5.5pt on the margin | 89.7% / 61% (Senate chart possibly stale) | chart CSVs, saved in each snapshot (not republished) |
| whyalwaysrose/midterms-forecast (GitHub, T) | VoteHub polls, PyMC | national 3.3pt, state 3.9pt, Student-t 5 df | – | yes (MIT) |
| PS symposium (academic, R via EurekAlert) | fundamentals | e.g. Fair: D 50.6% two-party, SE 2.4 | House: D +31 to +42 seats in most | papers |

Where they disagree: models that use markets (DDHQ, VoteHub) come in lower on the Senate; the size of the national error term (~3–3.3pt where it's readable) and fat tails vary; Silver and SIN weight polls more than the fundamentals-heavy academic models.

Left out on purpose: 270toWin and fiftyplusone.news (robots.txt disallows AI crawlers); Cook, Sabato, Inside Elections (bot walls on their own sites; their ratings are read from Wikipedia's ratings tables instead).

## Track record, 2018 and 2022

538's archived final forecasts (Lite = polls only, Classic = + fundamentals, Deluxe = + expert ratings), PredictIt 2018 (Wayback snapshots), Polymarket 2022 (third-party trade dump), against MEDSL certified results. Same races within each block.

| cycle | races | source | Brier | margin MAE (pts) |
|---|---|---|---|---|
| 2018, all | 446 | 538 Lite / Classic / Deluxe | 0.045 / 0.040 / 0.037 | 7.2 / 4.6 / 4.6 |
| 2022, all | 455 | 538 Lite / Classic / Deluxe | 0.037 / 0.037 / 0.034 | 5.9 / 5.5 / 5.5 |
| 2018, PredictIt's races | 118 | PredictIt vs 538 Lite / Classic / Deluxe | 0.096 vs 0.109 / 0.095 / 0.088 | – |
| 2022, Polymarket's races | 32 | Polymarket vs 538 Lite / Classic / Deluxe | 0.130 vs 0.101 / 0.117 / 0.112 | – |

- In 2022 the competitive races came in about 2.4 points more Democratic than 538 projected, and Polymarket leaned the same way: the sources share their misses.
- Both 538 and PredictIt were underconfident on Democratic favorites in the 50–90% range.
- Polymarket 2022 is 32 thinly traded races, weak evidence for 2026.

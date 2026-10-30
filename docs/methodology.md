---
title: "Holdout: a 2026 midterm model whose adjustments had to predict elections they weren't fit to"
date: 2026-10-30
description: "The methodology behind Holdout: data, error model, out-of-sample model selection, the election-night projection, and how it will be scored."
---

# Holdout: a 2026 midterm model whose adjustments had to predict elections they weren't fit to

*Axel Browne · October 30, 2026 · methodology, written before the election*

**Abstract.** Holdout is a forecast of the 2026 US Senate and House elections, built to be scored against prediction markets and published forecasts after November 3. Its center averages a polling average with Split Ticket's model. Its uncertainty is a three-part polling error (national, state, race) measured on 25 years of polls. Its one systematic adjustment is the result of a test: each candidate adjustment was fitted on all midterm years but one and scored on the year left out. Of three plausible state-level adjustments, only carrying over 42% of a state's previous presidential polling miss reduced the held-out error (5.27 vs 5.56 points of margin across 344 Senate and governor races); a fade toward each state's partisan lean, which looked right in-sample, did not. On election night the same machinery projects races from county returns, starting from market prices at the first votes so that any disagreement it flags comes from counted votes. Every input and every version of the model was saved before the election, so the evaluation is fixed in advance.

---

## 1. Why build a model at all

The project's question is how well each kind of source calls an election: prediction markets against models, and all of them against the polls. Answering it needs a record of what each source said and when, which is the main data product here (Section 2). A model of my own adds one thing the published forecasts can't: every assumption is written down and testable, so when it disagrees with the markets I can say exactly why.

The design rule follows from that. An adjustment earns a place only if it predicts polling misses in elections it was not fitted to. Several adjustments that are standard intuitions in election analysis fail that test (Section 4), and the main version of Holdout keeps only what passed. The others stay as labelled variations, scored alongside it.

## 2. Data

**Forecast and market snapshots.** Twice a day from October 29 to November 6, a scheduled job saves every midterm market on Polymarket (1,259 events) through its public API [[1](#ref-1)]; Split Ticket's race-level model [[2](#ref-2)]; Silver Bulletin's published polling averages and the polls behind them; and the ratings of eleven raters as tabulated on Wikipedia. Each run is committed with its timestamp. Market prices can be recovered later; a forecaster's daily number mostly can't, which is why this runs before the election rather than after.

**Historical polls.** Final polling averages and results for every statewide race since 1998 come from FiveThirtyEight's raw polls archive [[3](#ref-3)]. A race's *miss* is its result minus its final polling average, in points of the Democratic margin (positive means the Democrat beat the polls).

**Results and baselines.** County presidential results for 2020 and 2024 [[4](#ref-4)], county returns by vote mode for 2022 [[5](#ref-5)], turnout by voting method from the EAC's Election Administration and Voting Survey [[6](#ref-6)], certified 2025 Virginia and New Jersey governor results from the two states, and map shapes from us-atlas [[7](#ref-7)].

**Collection rules.** Every host was checked for robots.txt and terms of use before collection. Sources that disallow AI crawlers or prohibit automated collection were left out (Decision Desk HQ, 270toWin, VoteHub, The Economist), and no bot check was circumvented. The public repository republishes code, derived data and the model's outputs, not other sources' raw data.

## 3. The model

### 3.1 Center

For Senate race $i$ in state $s$, Holdout's expected Democratic margin is

$$c_i = \tfrac{1}{2}\left(p_i + t_i\right) + \beta\, m_s ,$$

where $p_i$ is Silver Bulletin's polling average (Split Ticket's margin stands in when a race has no polls), $t_i$ is Split Ticket's margin, $m_s$ is the state's polling miss in the 2024 presidential race beyond that year's national miss, and $\beta = 0.42$ (Section 4). Averaging polls with a model that includes fundamentals follows the practice of published forecasts [[8](#ref-8), [9](#ref-9)]; averaging rather than re-deriving Split Ticket's fundamentals keeps Holdout's own assumptions few. Where an independent is the main opponent of the Republican (Nebraska, Montana, South Dakota), the margin is the non-Republican candidate's.

For House district $j$, the center is Split Ticket's margin, averaged with the district's polling average where it has two or more polls in 60 days; sponsored polls are moved 5 points against the sponsor first. The carry-over is applied to Senate races only; whether it also helps House races is one of the things the evaluation will test. Governor races are not modelled.

### 3.2 Error

Each race's margin is simulated as

$$y_i = c_i + \nu + \sigma_s + \varepsilon_i ,$$

a national error $\nu$ shared by every race, a state error $\sigma_s$ shared by races in one state, and a race error $\varepsilon_i$. This decomposition, and the finding that the shared parts are large, follow Shirani-Mehr et al. [[10](#ref-10)]; the magnitudes are my own estimates from the 1998–2022 archive, where a competitive statewide race's final average missed the margin by about 5 points (root mean square), roughly 40% of that variance shared nationally and 30% within states ([brief](polling-error-research.md)); AAPOR's evaluations report midterm Senate and governor errors of similar size, 4.0 to 5.8 points from 2002 to 2014 [[11](#ref-11)].

| Term | Distribution | SD (points of margin) |
|---|---|---|
| National $\nu$ | Student-*t*, 5 df, scaled to unit variance | 3.0 |
| State $\sigma_s$ | Normal | 2.7 |
| Race $\varepsilon_i$ | Student-*t*, 10 df | 2.7 with 5+ polls in 30 days; $\sqrt{2.5^2 + 25/n}$ with $n$ = 1–4; 8 with none |

For a well-polled Senate race the three add to $\sqrt{3.0^2 + 2.7^2 + 2.7^2} \approx 4.9$ points, which matches the miss measured directly. The national term has fat tails, my choice rather than an established convention, because a single year's shared miss can be large (2020's was 5.5 points). Its mean is zero: across 25 years its sign has flipped from cycle to cycle with no usable memory ([brief](polling-error-research.md)), so Holdout makes no call on the direction of this year's miss.

House districts use the same national and state terms, with a race error whose SD depends on the number of district polls (8, 7, 6 and 5 points for 0–3 polls) and *t* tails (6 df when thin, 10 otherwise).

### 3.3 Simulation

Each of 100,000 draws produces a margin for every race. Senate control counts Democratic and Democratic-caucusing seats not up in 2026 plus the races won; Democrats need 51, since the Vice President breaks ties for Republicans. House control needs 218. A race's probability is the share of draws its non-Republican candidate wins.

## 4. Choosing the adjustments out of sample

### 4.1 Candidates

The first version of the model carried two adjustments, both estimated in-sample on the same history they were meant to explain:

- **Fade**: polls overstate candidates who run far ahead of their state's lean, so pull the margin back by $\gamma \times$ (poll margin − state's last presidential margin). Fitted in-sample, $\gamma = -0.08$.
- **Presidential carry-over**: a state's miss in the last presidential race, beyond that year's national miss, partly recurs.

A third was added when testing: **state record**, the state's average miss beyond the national miss over every statewide race in the previous 8 or 12 years.

### 4.2 Test

The target is each race's miss beyond its year's national miss, the part a state-level adjustment could predict. Each combination of adjustments is a linear model with no intercept, fitted on five of the six midterms from 2002 to 2022 and scored on the sixth, rotating through all six [[12](#ref-12), [13](#ref-13)]. Holding out whole years matters because races in one year share a national miss: holding out individual races would let the model see the answer through its neighbours [[14](#ref-14)]. The sample is 344 Senate and governor races with a previous presidential miss and at least two earlier statewide races in the state.

### 4.3 Results

| Adjustment | Held-out RMSE (points) | vs none |
|---|---|---|
| Presidential carry-over | **5.27** | −0.29 |
| Carry-over + state record | 5.35 | −0.21 |
| Fade + carry-over | 5.38 | −0.17 |
| State record | 5.51 | −0.05 |
| None | 5.56 | 0 |
| Fade | 5.57 | +0.01 |

Only the carry-over helps, and adding anything to it makes the held-out score worse. It improved the score in each of the last four midterms (2010, 2014, 2018, 2022) and worsened it in 2002 and 2006. Its weight is 0.42; resampling whole years puts 90% of fits between 0.22 and 0.56. Two further checks:

- **Thin inputs.** Kansas's 2024 miss rests on a single poll, so I tested discounting misses by the number of polls behind them, $\beta \cdot n/(n+k)$. Every discount scored worse (5.27 rising to 5.29 at $k$ = 8). In the history, states with thin polling kept being mispolled, so a miss from a thin record still carries signal.
- **Why the fade fails.** The pattern behind it is real in the raw numbers: in 69 races since 2000 where a Democrat or independent polled within 5 points in a state that voted Republican by 10 or more, the Republican beat the polls by 2.4 points on average. About 1.1 points of that is those years' national miss, and the remainder does not scale with distance from the lean in a way that predicts new races. A weak opponent can put a candidate far above the lean for reasons the polls capture correctly.

The main version of Holdout therefore uses the carry-over alone. The first version (fade plus a 0.34 carry-over), a state-record version and a no-adjustment version are kept as variations and scored with it.

## 5. Election night

On election night a local dashboard reads official county results from state and county election sites and live prediction-market prices. It is read-only and places no orders.

**Projection.** Each county's final margin is projected as its 2024 presidential margin plus a statewide swing plus a shrunk county-specific deviation. The swing is a precision-weighted combination of the pre-election center, counties that have finished counting, and, at lower weight, partly counted counties. A partly counted county's swing is judged against how each vote type (mail, early, Election Day) leaned relative to the county in the previous comparable election, so a county that counts its mail first does not read as a Democratic swing. The leans come from 2022 returns by mode [[5](#ref-5)], or from a county's own 2024 files where 2022 has no breakdown. Expected turnout comes from 2022, rescaled by counties that finish. The projection's SD combines the swing's posterior uncertainty, county noise and a turnout term, with a floor that shrinks as the count completes. The closest published relative is The Washington Post's county-level model, which also projects outstanding votes from a past-result baseline without polls [[15](#ref-15), [16](#ref-16)].

**Starting point.** Each race starts from the market's price, converted to a margin at the race's own SD, $c_0 = \mathrm{SD}_i \cdot \Phi^{-1}(\text{mid})$, frozen when the first votes arrive anywhere. Pre-election disagreements between Holdout and the markets therefore can't fire as election-night signals; anything flagged after that comes from counted votes.

**Signals.** A signal opens when the projection's probability differs from a venue's executable price by at least 3¢ after Kalshi's taker fee, $0.07\,p(1-p)$; not at prices outside 3–97¢, where fees and locked-up capital dominate; and not once a race is 99% counted. Markets aggregate public information well [[17](#ref-17), [18](#ref-18)], so most signals are expected to be errors in the projection, and the log exists to measure that.

**Validation.** Replaying the 2024 presidential count in seven states (North Carolina, Georgia, Pennsylvania, Iowa, Florida, Texas, Minnesota), each in eight simulated reporting orders, using only information available before 2024: the 90% intervals covered the final margin in about 97% of snapshots between 10% and 95% counted, with an average absolute miss of 1.7 points. The uncertainty settings were tuned on these replays, so coverage on real counts should be lower. Florida and Texas were the hard cases: the first counties to finish were least like the last.

## 6. Where Holdout stood before the election

| | Holdout | First version | No adjustments | Polymarket |
|---|---|---|---|---|---|
| Senate control (D) | 73% | 68% | 78% | 73% |
| House majority (D) | 96% | | | 94% |

Holdout sits 9 to 15 points below Polymarket in three Senate races (Kansas 39% vs 54%, Iowa 33% vs 45%, Texas 63% vs 72%). At Holdout's uncertainty those are 1.3 to 1.7 points of expected margin, and in each the gap comes from the carry-over: these are the states where the 2024 polls overstated Harris most. A separate reconciliation (notebook 01) expressed every published Senate forecast as the national polling bias that would reproduce its probability under this error model: forecasts from 53% to 76% all fall within about 2 points of bias of each other.

## 7. What is different here

- **Adjustments selected by held-out years, not fitted in-sample.** Election models commonly include adjustments justified by in-sample fit or intuition. Scoring each adjustment on entire held-out election years, and keeping only those that help, removed an intuitive one (the fade) and changed the forecast by several points in the races where it mattered.
- **A measured, out-of-sample carry-over of state polling error.** Gelman et al. note a positive correlation between a state's polling errors in successive elections but choose not to model it [[19](#ref-19)]; Isakov and Kuriwaki use 2016's state errors as a scenario for 2020 [[20](#ref-20)]; the AAPOR task force concluded that one election's polling errors can't predict the next's [[11](#ref-11)]. Estimating the carry-over from a presidential race into the following midterm, at 42% (90% range 0.22–0.56), and showing that it predicts held-out midterms, is to my knowledge new, and it holds only weakly (it lost in two of six years).
- **Separating pre-election disagreement from what the votes say.** Anchoring the election-night projection to the market price at the first votes means a signal reflects counted votes only, not a standing difference of opinion between the model and the market.
- **Comparing forecasts as implied polling bias.** Translating each published probability into the national polling bias that reproduces it puts very different-looking forecasts on one scale, and shows how small most disagreements are in the quantity that actually varies.
- **A pre-registered evaluation.** Every source's numbers and every version of the model were committed with timestamps before the election, so the scoring cannot be tuned after the fact.

## 8. Limitations

- **Six midterms.** The carry-over's gain is about 5% of the error, it lost in two of six years, and the 90% range of its weight is wide.
- **Overlap with Split Ticket.** Split Ticket's model may already reflect some state-level polling history; averaging it in and then applying the carry-over could partly double-count.
- **Thin 2024 inputs.** Kansas's 2024 miss rests on a single survey; Iowa's comes from published averages that include one final-week outlier.
- **Election-night coverage.** Feeds exist for 11 states; several states' official results sit behind bot checks, and those races move only with their prior and the national swing. The projection's settings were tuned on the replays used to validate it.
- **No governor model**, and House centers lean on one external model.

## 9. How it will be scored

After the results are certified: the probability each source gave the eventual winner over the final days, and how far ahead each race locked in; Brier score, log loss and calibration across all House, Senate and governor races; markets against models; Holdout against its three variations, which is the direct test of choosing adjustments out of sample; and the election-night tool's coverage on real counts against the 97% from the replays, with how quickly flagged gaps closed.

## Code and data

Everything above is in the [repository](https://github.com/axel5o5/midterms-2026): the error model (`src/midterms/senate.py`, `house.py`), the model-selection test (`src/midterms/carryover.py`, [notebook 04](../notebooks/04_model_selection.ipynb)), the election-night projection (`src/midterms/live/`, [notebook 03](../notebooks/03_election_night.ipynb)), and the [interactive map](https://axel5o5.github.io/midterms-2026/).

## References

1. <a id="ref-1"></a>Polymarket (n.d.). *Polymarket API documentation*. https://docs.polymarket.com
2. <a id="ref-2"></a>The Argument (2026, June 17). *2026 midterms model* [Split Ticket]. https://www.theargumentmag.com/p/split-ticket-2026-midterms-model
3. <a id="ref-3"></a>FiveThirtyEight (2024). *raw_polls.csv* [Data set], fivethirtyeight/data, pollster-ratings. https://github.com/fivethirtyeight/data/tree/master/pollster-ratings (CC BY 4.0)
4. <a id="ref-4"></a>McGovern, T., Larson, S., Ro, J., & Hodges, M. (2025). *US_County_Level_Election_Results_08-24* (v2.0.0) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.14679171
5. <a id="ref-5"></a>MIT Election Data + Science Lab (2025). *U.S. Senate precinct-level returns 2022* (v3) and *State offices precinct-level returns 2022* (v5) [Data sets]. Harvard Dataverse. https://doi.org/10.7910/DVN/IAD3XR, https://doi.org/10.7910/DVN/OAARCY
6. <a id="ref-6"></a>U.S. Election Assistance Commission (2026). *2024 Election Administration and Voting Survey dataset* (v2.0). https://www.eac.gov/research-and-data/studies-and-reports
7. <a id="ref-7"></a>Bostock, M. (2023). *us-atlas* (v3.0.1), from U.S. Census Bureau 2017 cartographic boundary files. https://github.com/topojson/us-atlas
8. <a id="ref-8"></a>Linzer, D. A. (2013). Dynamic Bayesian forecasting of presidential elections in the states. *Journal of the American Statistical Association*, 108(501), 124–134. https://doi.org/10.1080/01621459.2012.737735
9. <a id="ref-9"></a>Heidemanns, M., Gelman, A., & Morris, G. E. (2020). An updated dynamic Bayesian forecasting model for the U.S. presidential election. *Harvard Data Science Review*, 2(4). https://doi.org/10.1162/99608f92.fc62f1e1
10. <a id="ref-10"></a>Shirani-Mehr, H., Rothschild, D., Goel, S., & Gelman, A. (2018). Disentangling bias and variance in election polls. *Journal of the American Statistical Association*, 113(522), 607–614. https://doi.org/10.1080/01621459.2018.1448823
11. <a id="ref-11"></a>AAPOR Task Force on 2020 Pre-Election Polling (2021). *An evaluation of the 2020 general election polls*. American Association for Public Opinion Research. https://aapor.org/wp-content/uploads/2022/11/AAPOR-Task-Force-on-2020-Pre-Election-Polling_Report-FNL.pdf
12. <a id="ref-12"></a>Stone, M. (1974). Cross-validatory choice and assessment of statistical predictions. *Journal of the Royal Statistical Society: Series B*, 36(2), 111–133. https://doi.org/10.1111/j.2517-6161.1974.tb00994.x
13. <a id="ref-13"></a>Hastie, T., Tibshirani, R., & Friedman, J. (2009). *The elements of statistical learning* (2nd ed.). Springer. https://doi.org/10.1007/978-0-387-84858-7
14. <a id="ref-14"></a>Roberts, D. R., Bahn, V., Ciuti, S., Boyce, M. S., Elith, J., Guillera-Arroita, G., et al. (2017). Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic structure. *Ecography*, 40(8), 913–929. https://doi.org/10.1111/ecog.02881
15. <a id="ref-15"></a>Cherian, J., & Bronner, L. (2020). *How The Washington Post estimates outstanding votes for the 2020 presidential election* [Technical report]. https://s3.us-east-1.amazonaws.com/elex-models-prod/2020-general/write-up/election_model_writeup.pdf
16. <a id="ref-16"></a>Gibbs, I., & Candès, E. (2021). *Adaptive conformal inference under distribution shift* (arXiv:2106.00170). https://doi.org/10.48550/arXiv.2106.00170
17. <a id="ref-17"></a>Wolfers, J., & Zitzewitz, E. (2004). Prediction markets. *Journal of Economic Perspectives*, 18(2), 107–126. https://doi.org/10.1257/0895330041371321
18. <a id="ref-18"></a>Berg, J. E., Nelson, F. D., & Rietz, T. A. (2008). Prediction market accuracy in the long run. *International Journal of Forecasting*, 24(2), 285–300. https://doi.org/10.1016/j.ijforecast.2008.03.007
19. <a id="ref-19"></a>Gelman, A., Goodrich, B., & Han, G. (2024). Grappling with uncertainty in forecasting the 2024 U.S. presidential election. *Harvard Data Science Review*, 6(4). https://doi.org/10.1162/99608f92.a919e3fa
20. <a id="ref-20"></a>Isakov, M., & Kuriwaki, S. (2020). Towards principled unskewing: Viewing 2020 election polls through a corrective lens from 2016. *Harvard Data Science Review*, 2(4). https://doi.org/10.1162/99608f92.86a46f38

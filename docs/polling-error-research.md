# Polling error for 2026: what history supports

*Research brief, 2026-10-29, five days before the election. Figures are on the **margin** (D minus R, in points) unless marked. "Documented" means the number is on the linked page. "Mine" means I computed it from 538's raw polls file. "Inference" is a judgment call.*

**A final polling average in a competitive statewide race has missed the margin by about 5 points (RMSE) since 1998. Roughly 40% of that error variance is one national miss shared by every race. Another 30% is shared within a state, and the rest belongs to the race. The national miss has no usable direction: its sign has flipped back and forth from cycle to cycle. Use mean 0 for it, a fat tail, and a separate run with the lean switched on rather than baking a lean in.**

> **Update 2026-10-30:** the error model in this brief is unchanged. The two state-level adjustments that the first version of Holdout, my midterm model, added on top of it ([notebook 01](../notebooks/01_polling_error_and_senate.ipynb): a fade of −0.08 per point a candidate polls above the state's lean, and a 0.34 carry-over of the 2024 polling miss) were in-sample estimates. Scored one midterm year at a time ([notebook 04](../notebooks/04_model_selection.ipynb)), only the carry-over predicted misses, at a weight of 0.42; the fade and a longer state record didn't.

Recommended error model: margin error = national + state + race.

| term | shared by | distribution | SD (points of margin) | main evidence |
|---|---|---|---|---|
| national | every race, plus the generic ballot | Student-t, df = 5, scaled so the SD is 3.0 | **3.0** | mine: cycle-level bias RMS 2.9 to 3.2 (1998 to 2022); midterm-only 2.0 to 2.5; 2025 off-year R+6.1 |
| state | Senate, governor and House races in one state | normal | **2.7** | mine plus Shirani-Mehr et al.: Senate and governor errors in the same state correlate 0.45 (0.66 since 2014) |
| race, well polled (5+ independent pollsters) | one race | normal | **2.7** | mine: within-cycle SD about 3.9 for competitive Senate races |
| race, thinly polled statewide | one race | t, df = 10 | **sqrt(2.5² + 25 / n_pollsters)**: 5.6 at one pollster, 3.7 at three | mine: error by number of pollsters |
| race, House district with 1 to 3 public polls | one race | t, df = 6 | **5 to 7** | mine: within SD 7.7 with one pollster; 538 district polls 6.7 |
| race, House district with no public polls | one race | t, df = 6 | **8** | inference; FiftyPlusOne uses 8 to 9 for unpolled seats |

What to do this week:
1. **Check the total.** A well-polled Senate race comes out at sqrt(3.0² + 2.7² + 2.7²) ≈ 4.9, which matches the 4.9 I measure historically. Split Ticket's implied 5.5 is about 10% wider. That gap is a reasonable allowance for this year's method changes, so both are defensible. A D+3.0 race comes out about 73% D under this error model and 71% under theirs.
2. **Keep the national mean at 0**, and run two side scenarios: national mean D+1.5 (polls understate Democrats, the 2025 pattern) and R+1.5. Report how far each moves House and Senate control. The case for each direction is in section 3.
3. **Before averaging, move each partisan or internal poll about 4 to 6 points against its sponsor, or drop it.** In 2026, 56% of House polls come from Democratic-aligned pollsters.
4. **When scoring the generic ballot against the House popular vote**, expect polls to read about 1 point more Democratic than the vote even if they are perfectly accurate, because of uncontested seats (538). Split Ticket's uncontested-adjusted national vote is the cleaner target.
5. **Don't estimate uncertainty from how spread out the polls are.** Herding makes that spread too narrow. Use the historical error of averages, as above.

---

## 1. Size of the error

**Documented, individual polls.** 538's weighted-average error covers polls in the final 21 days, on the margin.
- Since 1998, by office: president 4.3, Senate 5.4, House 6.1, governor 5.4.
- 2022 was 4.8 across Senate, House and governor, "the lowest error since at least 1998" ([Rakich, 538/ABC, 2024-09-16](https://abcnews.com/538/read-political-polls-2024/story?id=113560546); [538, "The polls were historically accurate in 2022", 2023-03-10, archived](https://web.archive.org/web/2023/https://fivethirtyeight.com/features/2022-election-polling-accuracy/)).
- The same 2023 piece splits the House figure: generic-ballot polls 3.9, district polls 6.7.

538 per-cycle table (same source):

| cycle | Senate | House | governor |
|---|---|---|---|
| 2005-06 | 5.2 | 6.5 | 5.1 |
| 2009-10 | 4.9 | 7.0 | 4.7 |
| 2013-14 | 5.3 | 6.8 | 4.5 |
| 2017-18 | 4.2 | 4.9 | 5.2 |
| 2021-22 | 4.8 | 4.0 | 5.1 |
| all years | 5.4 | 6.1 | 5.4 |

**Documented, 2024 and 2020** (AAPOR task forces, last two weeks, individual polls).
- 2024, all contests: absolute error 3.3, signed D+2.7. Senate 3.3 / D+2.4, governor 5.0 / D+3.8, House (28 polls) 7.0 / D+4.9 ([AAPOR 2024 report](https://aapor.org/wp-content/uploads/2025/10/AAPOR-Task-Force-on-2024-Pre-Election-Polling_Report.pdf), Table 2.1.1).
- 2020, Senate and governor combined: absolute 6.7, signed D+6.0, "the largest in at least 20 years" ([AAPOR 2020 report](https://aapor.org/wp-content/uploads/2022/11/AAPOR-Task-Force-on-2020-Pre-Election-Polling_Report-FNL.pdf)).
- The 2020 report's Table 4 gives Senate and governor absolute error by midterm: 2002 4.8, 2006 4.0, 2010 4.8, 2014 5.8, 2018 4.6.
- Silver Bulletin puts the 2023-24 average at 4.5, its lowest on record, with Senate 4.1 ([Silver Bulletin, 2025-02-17](https://www.natesilver.net/p/so-how-did-the-polls-do-in-2024-its)).

**Documented, academic.**
- [Shirani-Mehr, Goel, Rothschild & Gelman (JASA 2018)](https://5harad.com/papers/polling-errors.pdf), 608 state races from 1998 to 2014: poll RMSE about 3.5 points "about twice as large as that implied by most reported margins of error". Average absolute election-level bias is 2.1 (Senate), 2.3 (governor) and 1.2 (president).
- These figures are on **two-party vote share**, so roughly double them for margin.
- The headline: even an average of infinitely many polls still misses a typical Senate race by about 4 margin points, because the polls share a bias.
- [Jennings & Wlezien (Nature Human Behaviour 2018)](https://eprints.soton.ac.uk/421260/1/JenningsWlezien_PollingErrors.pdf), 351 elections in 45 countries: mean absolute error on vote share about 2.0, "has been 2.0% since 2000". They find no trend, so polls are not getting worse.

**Mine: error of the average, not of single polls.** That is what Holdout needs. Method:
- Data: [538's raw_polls.csv](https://github.com/fivethirtyeight/data/tree/master/pollster-ratings). It runs through the 2022 cycle and stops there, because 538 was shut down in March 2025 ([Nieman Lab](https://www.niemanlab.org/2025/03/fivethirtyeight-is-shutting-down-as-part-of-broader-cuts-at-abc-and-disney/)).
- Polls in the final 21 days. Average within each pollster first, then take a simple mean across pollsters for each race.
- Signed error = poll margin minus actual margin, so positive means Democrats were overstated.
- Even-year races where the average was within 10 points.

| race type | races | RMSE | MAE | national (cycle) bias RMS | within-cycle SD |
|---|---|---|---|---|---|
| Senate | 144 | 4.97 | 3.87 | 2.85 | 3.93 |
| Senate, midterms only | 76 | 4.87 | 3.72 | 2.53 | 4.23 |
| Governor | 140 | 5.18 | 4.01 | 3.21 | 4.65 |
| Governor, midterms only | 111 | 5.26 | 4.08 | 1.98 | 4.85 |
| House district | 464 | 7.60 | 5.73 | 3.22 | 6.98 |
| House district, 3+ pollsters | 74 | 5.39 | 4.33 | 4.09 | 4.50 |

My simple averages run a little worse than a careful quality-weighted average such as Silver's or DDHQ's (DDHQ's published averages, read as reported; I don't collect its data). For Holdout's purpose, that is the conservative direction.

**Generic ballot.**
- 538's final generic-ballot averages missed the House vote by 2.9 on average over 1996-2020: "2.5 points in midterms" ([538, "Why was the national polling environment so off in 2020?", archived](https://web.archive.org/web/2021/https://fivethirtyeight.com/features/why-was-the-national-polling-environment-so-off-in-2020/)).
- Final RCP average vs House vote, midterms: 2006 D+12 vs D+8, 2010 R+9 vs R+7, 2014 R+2 vs R+6, 2018 D+7 vs D+9 ([538, archived](https://web.archive.org/web/2020/https://fivethirtyeight.com/features/our-best-tool-for-predicting-midterm-elections-works-in-presidential-years-too/)).
- 2022: RCP R+2.5 and 538 R+1.2, against an R+2.8 popular vote ([Washington Monthly, secondary](https://washingtonmonthly.com/2024/05/07/democrats-just-took-the-lead-in-this-poll-average-and-no-one-noticed/)). Split Ticket's uncontested-adjusted figure was R+1.6 ([Split Ticket](https://split-ticket.org/2022/12/12/estimating-2022s-generic-ballot/)).
- Mine, from the same raw file: the generic-ballot error RMS is 3.3. Polls overstated Democrats in 10 of 13 cycles, by an average of 2.4. 538 says that about 1 point of this is expected from uncontested seats ([538 2022 accuracy piece](https://web.archive.org/web/2023/https://fivethirtyeight.com/features/2022-election-polling-accuracy/)).
- 538's own observation: in 13 cycles, "just one time the House vote was clearly more Democratic than the final polling average" ([538, 2021, archived](https://web.archive.org/web/2021/https://fivethirtyeight.com/features/why-was-the-national-polling-environment-so-off-in-2020/)).
- Both figures count generic-ballot polls against the raw House vote, so part of the gap is the uncontested-seat effect, not poll bias.

## 2. How the error is shared

**National share. Mine, documented by others.**
- The cycle-wide mean explains about 20% of the variance of all race errors (all margins).
- Among competitive races (average within 10 points) the national part is larger: RMS 2.9 against a total RMSE of 5.0, about 35 to 40% of variance.
- A second pass on the same data, grouped differently, found 24% pooled and 30% for races with 3+ polls (my own figure, not published elsewhere).
- [538's 2018 House model notes](https://web.archive.org/web/2018/https://fivethirtyeight.com/features/2018-house-forecast-methodology/) that "about three-quarters of the uncertainty in the House forecasts comes from local, district-by-district factors". That is a model output, consistent with this split.

**State share.**
- Documented: Shirani-Mehr et al. find election-level bias correlates "0.45 for gubernatorial versus senatorial, 0.50 for presidential versus senatorial, and 0.39 for gubernatorial versus presidential" within a state and year ([paper](https://5harad.com/papers/polling-errors.pdf)). Their stated mechanism is turnout: a Democratic turnout surprise hits every race on the ballot.
- Mine, after removing each cycle's national mean: Senate-governor correlation is 0.46 for 1998-2022 (n=181) and **0.66 since 2014** (n=72). Senate-president is 0.48.
- That rise fits ticket-splitting collapsing. I take the state share of within-cycle variance as about 0.5 to 0.6, which is where state SD 2.7 and race SD 2.7 come from.
- Documented model practice: Silver's 2026 model (FLIPR) has "a statewide draw shared by House, Senate and governor races" ([methodology](https://www.natesilver.net/p/flipr-midterms-model-methodology)). Split Ticket's 2026 model uses "correlated error terms on demographic, state, and national levels" but publishes no sizes ([The Argument](https://www.theargumentmag.com/p/split-ticket-2026-midterms-model)).

**Region and demographics.**
- Mine: grouping state errors by census region within a cycle adds almost nothing. Regional SD is about 0.7, so a region term isn't worth it.
- The demographic pattern is real in presidential years:
  - 2016: Trump's beat of his polls correlated 0.78 with a state's non-college white share ([538, archived](https://web.archive.org/web/2017/https://fivethirtyeight.com/features/pollsters-probably-didnt-talk-to-enough-white-voters-without-college-degrees/)).
  - 2020: AAPOR found polls "overstated Biden's support more in Whiter, more rural, and less densely populated states" ([AAPOR 2020](https://aapor.org/wp-content/uploads/2022/11/AAPOR-Task-Force-on-2020-Pre-Election-Polling_Report-FNL.pdf)).
  - 2024: Democrats were overstated by 3.6 in non-swing states against 2.0 in swing states ([AAPOR 2024](https://aapor.org/wp-content/uploads/2025/10/AAPOR-Task-Force-on-2024-Pre-Election-Polling_Report.pdf)).
- It was **not** present as a uniform pattern in 2018 or 2022. 538 on 2022: "some states zigged and other states zagged". Examples: Pennsylvania Senate R+4.2 but Florida governor D+9.2 ([538 2022 accuracy](https://web.archive.org/web/2023/https://fivethirtyeight.com/features/2022-election-polling-accuracy/)).
- Inference: no demographic tilt in the base model. If you add one as a sensitivity check, try a term proportional to the state's non-college white share at about SD 1.5 per standard deviation of that share. Trump is not on the ballot, so the evidence for it in a midterm is weak.

**Tails.**
- Documented model choices: 538 in 2024 used "a Student's t distribution with five degrees of freedom" ([538/ABC methodology](https://abcnews.go.com/538/538s-2024-presidential-election-forecast-works/story?id=110867585)). 538 in 2016 used df=10 for national, regional and state terms. The Economist's 2020 code has t(4) commented out in favor of a normal ([repo](https://github.com/TheEconomist/us-potus-model)).
- Silver's FLIPR uses "slightly fat-tailed distributions … dialed down from previous years" ([FLIPR methodology](https://www.natesilver.net/p/flipr-midterms-model-methodology)).
- Mine: for competitive Senate races the race-level errors fit a normal (a t fit runs off to infinite df). For governor races, df is about 11. House districts have genuinely fat tails, df about 6.
- The fat tail matters most for the national term. 2020's D+6.5 Senate bias and 2025's R+6.1 are both 2-SD events under SD 3. Two of about 13 cycles is more than a normal predicts, but 13 cycles can't pin down a df. Use df=5 as 538 did (inference).

## 3. Direction: can the lean be called?

**Documented: the sign is not predictable from the last cycle.**
- Silver Bulletin's bias by cycle (all races): 2016 D+3.0, 2018 R+0.5, 2020 D+4.7, 2022 D+0.8, 2024 D+2.9, 2025 **R+6.1**. The average since 1998 is D+1.1, and "bias has historically been unpredictable cycle-to-cycle" ([Silver Bulletin, 2026-01-14](https://www.natesilver.net/p/actually-sometimes-polls-underestimate)).
- AAPOR's counts differ slightly (2022 R+0.6, 2018 D+0.1). It notes Democrats and Republicans "have each been underestimated about equally often since the dawn of modern polling in the 1930s" ([AAPOR 2024 executive summary](https://aapor.org/wp-content/uploads/2025/10/Task-Force-on-2024-Pre-Election-Polling-Report-Executive-Summary.pdf)).
- My own check on the archive (notebook 01): cycle-to-cycle bias has had near-zero memory since 1998. *(An earlier version quoted a 538 article for this; the quote couldn't be found on re-checking, so it was removed on 2026-10-30.)*
- Mine: lag-1 autocorrelation of combined Senate and governor bias is 0.15, and the sign matches the prior cycle 54% of the time, a coin flip.
- The D-overstatement streak (2016, 2020, 2024) is a **presidential-year** pattern. Midterms with Trump in office, 2018 and 2022, were within a point of zero. Silver floats that it "could be a Trump-specific issue" ([Silver Bulletin 2024 review](https://www.natesilver.net/p/so-how-did-the-polls-do-in-2024-its)).

**Out-party and undecideds.**
- Documented: generic polls "persistently underestimate the ultimate support for the non-presidential ('out') party", but "the tendency to underestimate is greatest early in the election year and recedes as the campaign progresses" ([Bafumi, Erikson & Wlezien, PS 2018](https://www.cambridge.org/core/journals/ps-political-science-and-politics/article/forecasting-the-2018-midterm-election-using-national-polls-and-district-information/4A1E30B9D66A6DFAEA1B84A3566CCAE8)).
- So the out-party edge is already in the polls by late October. It is not an extra late-October correction.
- The final-poll record cuts both ways: 2006 overstated the out-party (D) and 2014 understated it (R).
- Undecideds: Silver's work found they "tend to break evenly, with a slight advantage for the challenger" ([Prospect summary, 2012](https://prospect.org/2012/10/31/will-undecided-voters-break-overwhelmingly-romney/)). There is no midterm out-party study.
- Inference: split undecideds in proportion to decided voters, with no out-party bonus.

**Herding.**
- Documented: in 2024, 78% of swing-state polls (193 of 249) landed within 2.5 points of a close race. Silver argues herding makes "polling averages less accurate" ([Silver Bulletin, 2024-11-01](https://www.natesilver.net/p/theres-more-herding-in-swing-state)). AAPOR found "no evidence to support this", and attributes the narrow spread to weighting on political variables ([AAPOR 2024 executive summary](https://aapor.org/wp-content/uploads/2025/10/Task-Force-on-2024-Pre-Election-Polling-Report-Executive-Summary.pdf)).
- Either way, poll-to-poll spread now understates real uncertainty. That is why the table above takes its SDs from historical misses of averages.

**Method changes since 2020: the direction is contested.**
- Documented: Pew now weights to past presidential vote ([Pew, 2025-07-23](https://www.pewresearch.org/methods/2025/07/23/why-and-how-were-weighting-surveys-for-past-presidential-vote/)). Times/Siena now weights to validated or imputed recalled 2024 vote ([Gelman blog on the change](https://statmodeling.stat.columbia.edu/2026/06/30/survey-statistics-big-changes-in-the-times-siena-poll/)).
- Case that polls understate Democrats in 2026:
  - In 2025, polls had an R+6.1 bias. In Virginia, "pollsters who weighted to a 2021 or 2024 electorate, which were redder years, were less accurate" ([Silver Bulletin](https://www.natesilver.net/p/actually-sometimes-polls-underestimate)).
  - Morris: pollsters weighting to 2024 "will probably underestimate Democrats" ([Strength In Numbers, 2025-11-08](https://www.gelliottmorris.com/p/podcast-with-paul-krugman-what-can)).
  - Jain: disapproving Trump voters under-report having voted for him, which which, by my inference rather than the article's claim, would push recalled-vote weighting to add Republicans ([The Argument, 2026-02-25](https://www.theargumentmag.com/p/the-trump-voters-telling-pollsters)).
- Case for the opposite:
  - Morris's own poll found weighted 2024 Trump voters are too concentrated in the bluest zip codes, which "may end up artificially inflating support for Democrats on the House generic ballot" ([Strength In Numbers, 2026-10-28](https://www.gelliottmorris.com/p/2026-10-28-lab-trump-voters-blue-zip-codes); size paywalled).
  - Silver warns pollsters may overcorrect for 2025 ([same Jan 2026 piece](https://www.natesilver.net/p/actually-sometimes-polls-underestimate)).
- 2025 races in detail:
  - NJ governor: Sherrill won by 14.4 against averages of about +3.5 (RCP) to +5 (DDHQ) ([result](https://en.wikipedia.org/wiki/2025_New_Jersey_gubernatorial_election); [DDHQ](https://decisiondeskhq.substack.com/p/virginia-and-new-jerseys-elections)).
  - VA governor: Spanberger won by 15.4. Silver puts the Virginia error at 5.9 ([result](https://en.wikipedia.org/wiki/2025_Virginia_gubernatorial_election)).
  - Both are off-year, low-turnout races where the Democratic coalition is more likely to vote. A November midterm sits between that and a presidential electorate.

**Inference on the national mean.**
- The 2025 miss and the specials (section 4) point to a Democratic lean of maybe 1 to 2 points. Cycle-to-cycle bias has had near-zero memory for 25 years. The specials signal overshot in 2022, and many pollsters have just changed weighting in reaction to 2025.
- Markets (about 92% D House, 67% D Senate) are already slightly more Democratic than Split Ticket (89.7% / 60.8%), which suggests traders price in some of that lean.
- Keeping Holdout's main run at 0 and reporting the D+1.5 and R+1.5 runs gives a clean way to score afterward whether the lean was worth taking.

## 4. Midterm-specific issues

**Likely-voter screens flipped direction.**
- Documented: historically the registered-to-likely shift helped Republicans by about 4 points in 2010 ([Silver, 538, 2010, archived](https://web.archive.org/web/2010/https://fivethirtyeight.com/features/the-democrats-new-normal/)).
- In Pew's 2014 study, the registered sample was D+4 and verified voters R+3 ([Pew, 2016](https://www.pewresearch.org/methods/2016/01/07/polls-and-votes-the-2014-elections-by-the-numbers/)).
- In 2018 that gap vanished ([ABC/WaPo, 2018-11-04](https://www.goodmorningamerica.com/news/story/democrats-voter-preference-trump-health-care-center-stage-58935954)).
- Silver Bulletin now applies a likely-voter adjustment that **helps** Democrats: D+8.7 becomes D+9.2 ([generic ballot page, 2026-10-28](https://www.natesilver.net/p/generic-ballot-average-2026-nate-silver-bulletin-congress-polls)). Silver estimates Democrats gain about 2.5 points among likely voters in polls that report both ([2026-08-03](https://www.natesilver.net/p/what-trumps-latest-slump-means-for)).
- Inference: turnout modeling is the likeliest single source of this year's national miss. The direction is unknown. This is part of why the national SD stays at 3 even though midterm-only history suggests 2 to 2.5.

**Special elections.**
- Documented: Democrats have run 12.5 points ahead of Harris on average across 110 specials since January 2025 ([The Downballot, 2026-08-19](https://www.the-downballot.com/p/100-specials-since-trumps-return)).
- In 2017-18 the overperformance was about 9 points against Clinton, and the House vote came in at D+8.6. The signal pointed right ([The Conversation via Salon, 2026-03-01](https://www.salon.com/2026/03/01/do-special-election-results-spell-doom-for-republicans-in-2026-partner)).
- After Dobbs in 2022, specials showed Democrats "outperformed their expected margins … by an average of 9 points" ([538, 2022-08-24, archived](https://web.archive.org/web/2022/https://fivethirtyeight.com/features/yes-special-elections-really-are-signaling-a-better-than-expected-midterm-for-democrats/)), yet the House vote was R+2.8. The signal overshot by a lot.
- MultiState projects a 6-to-9-point Democratic environment from the special elections ([MultiState, 2026-10-14](https://www.multistate.us/insider/2026/10/14/democrats-special-election-edge-still-points-to-a-big-year-democratic-wave)). *(An earlier version quoted it calling this "a ceiling"; that wording isn't on the page, so the quote was removed on 2026-10-30.)*
- The 2018 overperformance faded to near zero over May-October. The 2026 signal has held at about 10 on far fewer races.
- Inference: specials are evidence about the environment, which the D+8.7 generic ballot already reflects. No one has shown they predict the poll **bias**. Treat them as support for the D+1.5 scenario, not as a shift to the national mean.

**Thinly polled House races.**
- Documented: district polls average 6.7 error against 3.9 for generic-ballot polls ([538 2022 accuracy](https://web.archive.org/web/2023/https://fivethirtyeight.com/features/2022-election-polling-accuracy/)).
- House internal polls released publicly were "about six points more favorable to their candidate" ([Silver, 538, 2012, archived](https://web.archive.org/web/2013/https://fivethirtyeight.com/features/when-internal-polls-mislead-a-whole-campaign-may-be-to-blame/)). Senate partisan polls were about 4.25 ([Enten, 538, 2014, archived](https://web.archive.org/web/2014/https://fivethirtyeight.com/features/how-partisan-are-partisan-senate-polls/)).
- In 2026, "Democratic-aligned pollsters account for 56 percent of House polls", against a 24% norm ([FiftyPlusOne, 2026-09-18](https://blog.fiftyplusone.news/p/why-does-every-poll-seem-to-show)).
- Unpolled districts are "less competitive than you'd infer", because a poll is a sign someone thinks the race is close ([538 2018 House methodology](https://web.archive.org/web/2018/https://fivethirtyeight.com/features/2018-house-forecast-methodology/)).
- FiftyPlusOne's 2026 model uses spreads of about 9 (House) and 8 (Senate) for no-poll seats ([methodology](https://blog.fiftyplusone.news/p/2026-forecast-methodology)). The page doesn't say whether these are SDs or interval widths.
- Mine, from 538's House district races: the within-cycle error falls as more pollsters cover a race.

| independent pollsters in the race | Senate within-cycle MAE | House within-cycle MAE |
|---|---|---|
| 1 | 6.1 | 6.3 |
| 2 | 4.7 | 5.4 |
| 3 | 3.6 | 4.4 |
| 5+ | 3.3 | — |

  The thinly-polled formula in the top table, sqrt(2.5² + 25/n), reproduces the Senate column to within about half a point.

## What I couldn't verify

- 538's per-cycle **bias** table from the 2023 piece.
- A full 1998-2022 table of final generic-ballot averages from one source.
- Cohn's NYT analyses (blocked).
- Any published component SDs from Split Ticket, Silver Bulletin or the Economist. They describe their structure but not the numbers, so Holdout's SDs rest on my own decomposition plus the published correlations.
- Morris is quoted in secondary coverage ([Alternet, 2026-09-17](https://www.alternet.org/trump-republicans-midterm-disaster/)) as saying recalled-vote weighting adds "a little less than one percentage point" to Republicans. His own Oct 28 piece flags a bias the other way. I couldn't reconcile the two, so neither moves the mean.
- My decomposition uses simple averages of 538's poll file, not anyone's published averages, and covers 13 even-year cycles. The national SD in particular rests on very few data points.

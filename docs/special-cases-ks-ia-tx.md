# Kansas, Iowa, Texas: why Holdout sits below the markets

**After I tested its adjustments against 1998–2022, Holdout, my midterm model, still puts all three Democrats below the markets: Kansas 39% (Polymarket 54%), Iowa 33% (45%), Texas 63% (72%). In each, one choice separates Holdout from the markets: whether the 2024 presidential polling miss in that state carries into 2026. History says it does, at about 42%, and that's the only state-level adjustment that predicted past misses out of sample. The three independent research briefs land between Holdout and the markets: Kansas 40–45%, Iowa 38–44%, Texas 62–66%.**

What to do with it:
- **Leave Holdout as tested.** The fade toward each state's lean is gone, because it didn't predict anything. The carry-over stays at 0.42. Its other versions are on the [map page](https://axel5o5.github.io/midterms-2026/) and get scored against the results.
- **Treat Texas as settled and Iowa as the shakiest.** Holdout's Texas number matches the brief's independent estimate. Iowa's carry-over rests on 2024 polling averages that included Selzer's outlier, and the brief's best single fix is removing her.
- **Kansas has no results feed in the election-night tool.** It's the most interesting of the three races to watch live, and right now it would only move with the national swing. Wiring up a Kansas feed is the one build item this points to.
  *Done 2026-10-30:* the state results site is behind a bot check the tool doesn't try to get past, so a browser bookmark sends the page you have open to the dashboard, with Johnson, Sedgwick and Douglas counties (46% of the 2024 vote) as a backup. See the feeds table in the [README](../README.md#election-night).
- **Don't read the market gaps as edges yet.** All three markets moved on single polls this month, and Holdout has no track record against them. That's what Tuesday's log is for.

---

## The numbers

| | Polls (30-day average) | Split Ticket | Holdout | First version | No adjustments | Research brief | Polymarket |
|---|---|---|---|---|---|---|---|
| Kansas: Hamilton v Marshall | D+3.1 (8) | R+1.6 | R+1.2, 39% | 36% | 57% | 40–45% | 54% |
| Iowa: Turek v Hinson | D+0.9 (13) | R+0.3 | R+2.0, 33% | 32% | 52% | 38–44% | 45% |
| Texas: Talarico v Paxton | D+2.9 (22) | D+2.7 | D+1.5, 63% | 60% | 73% | 62–66% | 72% |

At Holdout's uncertainty (SD about 4.9 points), the gaps are small in margin. Polymarket's prices imply about D+0.5 in Kansas, R+0.7 in Iowa and D+2.8 in Texas, so Holdout is 1.3 to 1.7 points of margin from the market in each race. Near 50%, a point of margin is worth about 8 points of probability.

## How Holdout was chosen

[`carryover.backtest`](../src/midterms/carryover.py): fit on all midterm years but one, score on the one left out. The data is 344 Senate and governor races across six midterms (2002–2022). The target is each race's polling miss beyond that year's national miss.

| Adjustment | Out-of-sample average miss (points) |
|---|---|
| Previous presidential miss in the state (the "2024 carry-over") | **5.27** |
| That plus the state's longer record | 5.35 |
| Fade toward the state's lean plus the carry-over | 5.38 |
| Longer state record alone | 5.51 |
| Nothing | 5.56 |
| Fade alone | 5.57 |

- **The carry-over:** it improved 2010, 2014, 2018 and 2022 and hurt 2002 and 2006. Its weight is 0.42, and 90% of the resampled-year fits fall between 0.22 and 0.56.
- **Discounting thin inputs:** a version that discounts misses built from three or fewer polls did slightly worse (5.27 to 5.29). In past data, states with thin polling kept being mispolled.
- **Close red-state races in general** (a state that voted Republican by 10+, where the Democrat or independent polled within 5 or better; 69 races since 2000): the Republican beat the polls by 2.4 points on average. About 1.1 of that was the year's national miss and 1.3 was specific to these races. Nineteen polled between R+1 and D+4, and the non-Republican won 11. See [`red_state_close_polls.csv`](../data/history/red_state_close_polls.csv).

## What the three briefs agree on

**The same contrast shows up in every state.** The Republican Senate candidate is weak, but the Republican ticket isn't:
- **Kansas:** Marshall's net favorability is −17 (CNN). He faces a story about 700+ lawsuits against former patients, and two former Republican governors endorsed Hamilton. Yet Masterson leads the governor race by 4–5 in the same polls.
- **Texas:** Paxton is at 40/58 (Fox), and Abbott runs 3–7 points ahead of him in the same samples.
- **Iowa:** the reverse. Democrat Rob Sand leads the governor race by about 7 and trades around 90%.

The fade adjustment would have penalized exactly these candidate effects. That's one reason dropping it is right.

**The polling averages have tilts in both directions:**
- **Texas** includes a Democratic-linked poll (TPOR, built by Slingshot), a Democratic firm (GSG) and a registered-voter poll (Univision). Without them, the last two weeks average D+1.9.
- **Iowa:** six of the eleven polls are from Republican-affiliated firms and average Hinson +1.4. The nonpartisan polls average Turek +1.7, or about +0.6 after adding CNN and NYT/Siena.
- **Kansas:** the Washington Post's D+9 poll says registered Democrats were more than twice as likely as Republicans to finish the survey, and the Post warns its own number likely overstates Hamilton.

**Late deciders and the early vote don't show a wave:**
- **Kansas:** at least 6 in 10 undecided voters lean Republican (CNN). Emerson has voters who haven't voted yet favoring Marshall 48–45, and early voters favoring Hamilton 66–32.
- **Iowa:** the Democratic ballot lead (54K) trails the same point in 2022 (57.5K, a year Grassley won by 12).
- **Texas:** early votes passed 6.2M, already more than all of 2022's early vote, and the Hispanic share is up 2 points on 2024.

**The markets moved on single polls:**
- **Kansas** went from 40 to 50 the day CNN's poll came out.
- **Iowa** jumped around Marist's Turek +8 on Sept 23.
- **Texas** rose 7 points in the last week of October with no clear trigger.

**Republicans are spending as if all three are real races:**
- The main Republican Senate super PAC (SLF) moved $10.7M from North Carolina into Kansas and reportedly plans $53M in Iowa.
- In Texas, Musk-funded Texas PAC money ($178M) and MAGA Inc. ($40M) far outweigh Talarico's 7-to-1 edge in his own fundraising.

## Where the carry-over is weakest

Holdout's 2024 inputs come from [`pres2024.py`](../src/midterms/pres2024.py), which reads Wikipedia's polling tables (cached, from 2026-10-29):

- **Kansas:** a single Fort Hays State poll of registered voters, three versions of the same survey averaging Trump +8. Trump won by 16.1. A carry-over from one poll is mostly that poll's own error. The backtest says thin inputs still predicted, but this is as thin as it gets.
- **Iowa:** 2024 polling averages (Silver Bulletin, 270toWin, about Trump +4.5) against Trump's actual +13.2. Selzer's final Harris +3 is one poll inside those averages, and she has since retired. The brief estimates removing her moves Holdout from 33% to about 39%. That's probably too much when the input is an average rather than her single poll.
- **Texas:** 2024 polling averages from four aggregators, with a tighter spread. This is the best-supported of the three.

Iowa is the one state where every source agrees polls overstate Democrats: Republicans beat the polls in all 10 Iowa races from 2014 to 2024. Midterm misses were smaller (about 3 points in 2018, 2.6 in 2022) than presidential ones (6–9).

## Things I couldn't settle

- **Poll numbers that don't match the releases:** several entries in Silver Bulletin's poll list differ from the pollsters' own releases. For example, Emerson's Kansas poll is 49–45 (50–47 with leaners), not 49.5–47.1; there are also YouGov and Quantus entries in Texas. They may be adjusted or alternate versions. I haven't reconciled them.
- **Overlap with Split Ticket:** Split Ticket's model may already include something like a fade or a state history. If so, averaging it in and then applying the carry-over overlaps partly. Kansas landing exactly on Split Ticket's R+1.6 in the first version was arithmetic coincidence, but the question stands.
- **The CNN Kansas segment:**
  - **Marshall at −17:** checks out (it's favorability, not approval).
  - **Persuadable voters lean Republican:** checks out.
  - **Hamilton as clergy:** checks out (senior pastor at the largest United Methodist church). Talarico is a seminarian, but I found no evidence he's ordained.
  - **"Trump 15 points underwater":** that's NYT/Siena only; Emerson has −6.
  - **"First time in 30+ years":** true only for Senate races. Kelly won the governorship in 2018 and 2022.

## Sources

The three research briefs behind this write-up (a source and date for every fact) are kept in the private repo, because they quote news coverage at length. The research skipped sites whose robots.txt blocks AI crawlers, and flagged facts that appeared only on those sites as unverified.

# Write-ups

- [The methodology paper](methodology.md): how Holdout, my midterm model, is built and tested (also on the [site](https://axel5o5.github.io/midterms-2026/methodology.html)).
- [The write-up](writeup.md): what was built before Tuesday and why, in one read (also on the [site](https://axel5o5.github.io/midterms-2026/writeup.html)).

**The research notes behind Holdout, written in the week before the election (2026-10-29 and 30).** Start with the polling-error brief if you want the error model, or with Kansas, Iowa, Texas if you want to know why Holdout disagrees with the markets. The numbers that matter most are in the [main README](../README.md); the test that chose it is in [notebook 04](../notebooks/04_model_selection.ipynb).

| Write-up | What it answers |
|---|---|
| [Polling error for 2026](polling-error-research.md) | How big a polling miss to expect, how it's shared between the nation, the state and the race, and whether its direction can be called. The sizes in Holdout come from here. |
| [Kansas, Iowa, Texas](special-cases-ks-ia-tx.md) | Why Holdout sits 9 to 15 points below the markets in three red-state Senate races, and how much of that to trust. |
| [Other forecasters and the 2018/2022 track record](forecasters-and-track-record.md) | What the published 2026 models use and assume, and how models and markets scored in the last two midterms. |
| [Early vote, 2022 vs 2026](early-vote-2022-vs-2026.md) | The party split of ballots cast so far, against the same point in 2022, state by state. |

Two dated changes run through these notes:
- **2026-10-29:** DDHQ / The Hill, 270toWin and VoteHub stopped being collected once I saw their robots.txt or terms. Notes written before then may quote their published numbers; none of their data feeds Holdout.
- **2026-10-30:** the first version of Holdout (a "red-state fade" plus a 0.34 carry-over of the 2024 polling miss, both fitted in-sample) was replaced by the tested one (carry-over only, at 0.42) after [notebook 04](../notebooks/04_model_selection.ipynb). Notes that predate it say so at the top.

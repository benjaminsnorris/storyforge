# Pilot results (2026-11-26)

The raw results of [PILOT.md](../PILOT.md)'s run, summarized. The decisions and the results table are on PILOT.md, under "Results".

- **Set-up.** storyforge 1.205.0 (main at 360a6996b). The book was a remote-less clone of iliad-adult main (85251a5), then `source import` (unchanged) and `cleanup`, which filled 231 `death_scene`s; tagged `pilot-base`. Each run started from that tag with `STORYFORGE_COST_THRESHOLD=1.25`. No re-check ran: each run added only its scene's three gate ledger rows.
- **Pre-fix prose.** Rebuilt from the session logs as the runbook says. Every first-run quote in report A §2 for the eight scenes is in the rebuilt files (18 of 18). The blocking read's input tokens match the Nov 16 logged calls exactly (3,517 and 3,543 on `aphrodite-drives-helen-to-bed`), so the prose is byte-identical.
- **Runs.** 24 gate runs (`tandem`, `open`, `tandem --no-extract-thinking` on each scene), plus 15 calls of the blocking read alone (5 per scene, 2 readings each) on the three scenes whose real catches were missed.
- **Spend.** $17.04 against the $13 estimate and the $20 stop: tandem $5.91, open $5.00, thinking off $5.08, blocking read alone $1.04 (priced from logged usage; a direct call writes no ledger row). The open checker's first run cost $1.01 (a cold cache); later scenes cost $0.36–0.90 a run.

## Files

- `runs.csv`: one row per run. Each run's blocking findings (code, checker tag, Q number from report A), the verdicts in the same order, cost, wall time, and extraction rows (total, and `mutable` state).
- `blocking-recall.csv`: how often the blocking read found the real catches the rule needs.
- `source-entering.csv`: #769's source entering-state questions per scene and the findings they made.

## Verdicts

- REAL / FALSE / DEBATABLE were judged by reading the rebuilt prose.
- A finding report A doesn't list is marked new. An open-checker finding with no review label is marked "unlabelled, judged …".
- Every run's report and logs are kept outside the repo, in `~/Developer/iliad-adult-pilot-results` on the machine that ran it.

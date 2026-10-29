# Storyforge rethink — status and handoff

Last updated 2026-10-28, at v1.80.0. Start here when resuming the rethink in a new session. The plan is `docs/plans/2026-10-28-storyforge-rethink.md`; the corpus survey is `docs/plans/2026-10-28-storyforge-corpus-survey.md`.

## Where we are

**Phase 0 (evals and baseline) is done except E4 and E6.** Chunks 0–4 of plan §7 are merged. **Phase 1 has started:** model tiers resolve at runtime (no pinned versions), and the baseline was re-recorded on the current models (v1.80.0).

| Plan chunk | State | PRs |
|---|---|---|
| 0 Corpus survey | done | (survey doc, #337) |
| 1 Harness | done | #337 |
| 2 E1 corpus | done: 144 cases (130 prose), 30 held out | #340 |
| 3 E2 / E7 / E8 | done: E2 Carol (evals-56), E2 on E1, E7 Carol, E8 three pass families | #341, #342, #343, #344, #346 |
| 4 E3 / E5 | done | #346 |
| — E4 | done (overnight): shared-dark Act 1 drafted with today's `write`, judged; see the E4 note below | E4 PR (v1.81.0) |
| — E6 | not started: needs a budget decision (below) | |
| 5 Phase 1 | in progress: models (runtime tier resolution, thinking allowance), the whole bug checklist (#359, v1.80.2) and the E3 tier comparison (no routing change) done; structured outputs and warn-and-continue → halt to go | v1.80.0 PR, #359 |

## Baseline (`evals/baseline.json`)

All eight suites replay offline: 2106 recorded calls, $0 to rerun, $10.80 if run live. Re-recorded on v1.80.0 with the current models (Opus 5.5, Sonnet 5.5, Haiku 5.5, resolved at runtime); the v1.78.0 figures are in parentheses. The E5 and E8 judges moved to the new Opus too, so part of those deltas is the judge.

| Suite | Measures | Baseline (v1.78.0) | Gate |
|---|---|---|---|
| `e1-corpus` | gold-set health | 144 cases, 130 prose; 53 tool-introduced, 47 author-labeled, 25 unfixed at HEAD | pass |
| `e2-carol` | 37 errors injected into *A Christmas Carol* | 0 detected (0) | recall ≥ 0.9 per code, precision ≥ 0.8 |
| `e2-corpus-validate` | deterministic continuity checks vs 51 real E1 errors | code-matched recall 0.12 (likely incidental), precision 0.035 (unchanged: no model) | same |
| `e2-corpus-drift` | timeline drift check vs the same 51 | recall 0.10 (0.16), precision 0.40 (0.30) | same |
| `e3-extraction` | extraction captures the fact behind each E1 error | 0.24 (0.16); 0.82 with partial (0.43) | ≥ 0.85 |
| `e5-roundtrip` | facts a redraft-from-brief changes (10 shared-dark Act 1 scenes) | 3.2 per scene (7.2) | coverage only (trend metric) |
| `e7-classics` | continuity flags on *A Christmas Carol* (2 runs) and *The Plastic Age* (1 run); no real errors | 115 flags, all noise: 96 FP, 7 deliberate, 12 extraction errors (Carol alone: 60) | 0 noise, 0 unreviewed |
| `e8-revision-safety` | today's passes reintroduce E1 tool-introduced errors | 5 of 22, 1 halted (v1.80.2: a cut-off naturalness redraft now halts) | 0 |
| `e4-generation` | draft shared-dark Act 1 (23 scenes) with today's `write`, judge it | CP10k 18.2 (judge), 0.48 (shipped checker); BPS 3.09; length drift 0.071; voice 4.71 (author 4.75). $5.76 live | coverage only (trend metric) |

Read the exact numbers from `evals/baseline.json`; compare a run with `python3 evals/run.py` (deltas are printed).

## How to run

```bash
python3 evals/run.py                # all suites, replay (free); exit 0 pass / 1 gate failed / 2 errored
python3 evals/run.py --suite NAME
python3 evals/run.py --mode auto    # record what's missing (spends; check cost first)
python3 evals/e1/cli.py verify      # every E1 quote against the book repos
python3 evals/e8/cli.py plan        # E8 cases + estimated recording cost, no API calls
```

Prerequisites:

- **Python 3.10+.** On this machine `python3` is 3.9; use `/opt/homebrew/bin/python3.13`. pytest isn't installed globally — make a venv (`python3.13 -m venv … && pip install pytest pytest-cov`) and put it first on `PATH`, or `test_illustrate_cmd.py::test_a_nonzero_return_reaches_the_shell` fails because it shells out to `python3`.
- **The book repos** (private, `benjaminsnorris/<name>`) cloned under `STORYFORGE_CORPUS_DIR` (default `~/Developer`): shared-dark, thornwall, lantern-folk, governor, meridian-line, understory, slipform. E1 verify, E2-corpus, E3, E5 and E8 need them; without them those suites error rather than pass. Read-only: never commit or check out anything in them.
- `ANTHROPIC_API_KEY` only for recording.

## Conventions learned the hard way

- **Recordings key on the exact request.** Any prompt change (including plugin craft files that reach prompts) is a cassette miss; replay mode then errors, it never goes live. Re-record that suite with `--mode auto`. Keep temp paths and dates out of prompts.
- **A cassette failure errors the suite even if command code swallows it** (the harness reads the cassette log). Don't "fix" a miss by catching it.
- **Every exclusion is reported with its reason** in suite notes. About half of E1 (trees older than `reference/scenes.csv`) cannot be run by current Storyforge; that is reported, not migrated.
- **Holdout** (`evals/fixtures/e1/holdout.json`) is frozen once assigned; any suite scoring on E1 excludes it. Run `evals/e1/cli.py holdout` only after adding cases.
- **Stated simplifications** (in each module's docstring): E3 runs each scene with an empty extraction chain; E8's revision-plan family is narrowed to the case's scene and omits reader annotations; E5 falls back to `part` when `scenes.csv` has no `act`; the E5 judge is occasionally loose (one listed "mismatch" said it contradicted nothing).
- **Models are never pinned.** `common.model_for_tier` resolves each tier to the newest model from the Models API; the catalog call is recorded, so replays are stable. A new release means re-recording, and the eval delta decides whether to keep it. `api` adds `THINKING_ALLOWANCE` to every `max_tokens` (current models always think). Don't write tests that pin API facts such as model caps.
- **Versions:** another session (evals-56, working in the `storyforge-evals` repo) also opens Storyforge PRs. Whoever merges second takes the next version and resolves the one-line `plugin.json` conflict. Ask before claiming a version if the other session is active.

## Overnight run (2026-10-28 → 29): Ben's instructions

Ben is asleep; work through **Next steps** in order without asking. Rules:

- **Budget:** E4 is approved, target **under $20** for building and recording it. Separately, **$25** for everything else (E3 tier comparison, re-records after prompt changes). Before any recording, estimate its cost (`evals/e8/cli.py plan`-style or from `baseline.json` "if live" figures, adjusted to current per-model prices in `costs.PRICING`). If a step would push either budget past its cap, skip it and record why here. Keep a running spend tally in this section.
- **PRs:** one PR per logical step, `./tests/run-tests.sh` (or `python -m pytest tests/`) green and `python3 evals/run.py` run before merging; merge with `gh pr merge N --merge --delete-branch`. Bump the version per `CLAUDE.md`. No 5-agent review overnight; note in each PR that it is pending.
- **evals-56** (another session, storyforge-evals) works on `timeline.py` and has claimed 1.79.1. Message it (SendMessage) before touching `timeline.py` or claiming a version; never touch its working tree in `~/Developer/evals`.
- **Stop and leave a note here** rather than guess on anything that changes what the author sees in a book's prose or deletes author data.
- In the morning Ben wants: what merged, eval deltas vs baseline, spend, and anything skipped with the reason, at the top of this section.

Spend so far: $0 of $20 (E4), $0 of $25 (other). (The v1.80.0 re-record before this run cost $9.70 under a separate approval.)

## E4 notes (2026-10-28 overnight)

- **How it runs** (`evals/e4`): Act 1 prose is removed, then the 23 scenes are drafted in reading order the way `write --direct` drafts them (shared cached context, `cmd_write._build_prompt` with briefs, each scene's deps reading the new drafts). An Opus judge reads each scene against the drafts before it plus the character, world and systems bibles and `characters.csv`, and lists contradictions (by code) and broken brief promises. The shipped checker is the timeline drift check `write` runs after drafting. Direct mode, not batch (batch is refused under a cassette). The plan's human spot-check is still owed.
- **BPS mostly measures corrupt briefs, not drafting.** At the pinned commit (`0eaa3867`, shared with E5), the briefs of at least six Act 1 scenes (`claires-cold`, `waking-hank`, `name-surfaces`, `the-school`, `drive`, `fire-ostrowski`, and by the judge's notes also `harmons-hands` and `waking-maren`) describe a different story: Mallen, Yael, a prison facility, Olinsky, a Meszaros lawsuit. None of that is in the bibles or the prose. They were introduced by Storyforge's own `Polish: upstream brief fixes` / `Naturalness: upstream brief fixes` passes (`_fix_upstream_briefs`) from `0940bd4d` (2026-04-07) to `f56db284` (04-16), and they are still at shared-dark HEAD. The drafter followed the book, so the judge counted every beat of those briefs as broken (e.g. `waking-hank`: 9). **Decision for Ben:** re-pin E4 to a commit with sound briefs, exclude those scenes, or fix the briefs in shared-dark. This also affects E5 and E8, which redraft from the same briefs. It looks like a serious live bug in `_fix_upstream_briefs` (it can invent characters and plot), and it's a source of E1 brief-level `tool-introduced` cases.
- **One draft is a refusal.** `waking-hank`'s draft came back with `stop_reason: refusal`, cut off mid-word at 528 words. Today's `write` accepts it: its only check is ≥100 words, and the direct and batch paths have no truncation guard. E4 records that faithfully. evals-56 is making `api` raise on refusals (v1.80.4+). After that, E4's replay errors at that scene, and E4 must be re-recorded from there (≈$5, inside the E4 budget).

## E3 tier comparison (2026-10-28 overnight)

Same 49 facts, extraction model forced with `STORYFORGE_MODEL`, Opus judge unchanged. Recordings in `evals/fixtures/tier-comparison/` (replay free; see `evals/README.md`).

| Extraction model | captured | partial | missing | recall | with partial | cost if live |
|---|---|---|---|---|---|---|
| Haiku 5.5 | 13 | 23 | 13 | 0.265 | 0.735 | $0.52 |
| Sonnet 5.5 (today's `evaluation` tier) | 12 | 28 | 9 | 0.245 | 0.816 | $2.51 |
| Opus 5.5 | 13 | 29 | 7 | 0.265 | 0.857 | $5.02 |

**Decision: no routing change.** Sonnet is within one or two facts of Opus on a single run of 49 cases, which is inside run-to-run noise (E6 hasn't measured that noise yet), at half the cost. Haiku misses clearly more (13 vs 7). So `cmd_extract`'s fact phases stay on Sonnet (`evaluation`), and `select_revision_model`'s continuity branch stays on Sonnet. `_TASK_TIER['extraction']` (Haiku: timeline cue reads, `enrich`) isn't measured by E3. Moving it to Sonnet would mean re-recording `e2-corpus-drift` (~$16 at Sonnet) while evals-56 is changing the timeline prompt, so it's left for Ben with this evidence: E3 says Haiku drops facts.

## Open decisions for Ben

1. **E6.** Two more independent E4 runs plus the paid E2 suites under separate recording keys: ~$40. Not approved; leave for Ben.
2. **`author-labeled` strictness.** Cases drawn from Claude-written continuity reports carry `label_source` but not the tag (counting them adds 12 governor cases). Kept strict unless Ben says otherwise.
3. **Missing pieces of E8**: hone physical-states replay; 13 March-era revision-plan cases are unreplayable.

## Next steps, in order

0. **Verify main first.** v1.80.0 merged right after main moved to 1.79.3 (evals-56's timeline spike repair, post-processing only), and the post-merge checks didn't finish. Run `python -m pytest tests/` and `python3 evals/run.py`; every suite should replay with no errors and match `baseline.json`. If the drift suite's numbers moved because of the spike repair, refresh the baseline with `--baseline` and note it here. Fix anything broken before step 1.
1. **E4** (plan §4.2, decision 7): draft shared-dark Act 1 (23 scenes) end to end with today's `write`, judge it (CP10k, BPS), record under a cassette, add to `baseline.json`. Earlier estimate was ~$14 at old prices; re-estimate first. This is the "before" picture for Phase 3, so build it before Phase 1 changes the drafting prompts.
2. **Phase 1 bug checklist** (plan, Phase 1): the five unchecked items. Deterministic, no spend; each gets a regression test.
3. **Fact-work tier comparison on E3** (plan, "Model selection"): run E3 with fact work on opus, sonnet and haiku (`STORYFORGE_MODEL` or the `_TASK_TIER` map) and keep the cheapest that matches opus. Then route `_TASK_TIER['extraction']` and `select_revision_model`'s continuity branch accordingly.
4. **Structured outputs** replacing `KEY: value` parsers (`extract.py`, parser consumers in `prompts.py`); current Opus writes `**VERDICT: yes.**`, so line-anchored parsers are fragile now. Then **warn-and-continue → halt** (plan Phase 1 success criteria, including the three silent-failure regression tests). Re-record affected suites within budget.

## Key paths

- `evals/` — harness (`harness/`, `run.py`), suite modules (`e1`, `e2`, `e3`, `e5`, `e8`), suites (`suites/`), fixtures and recordings (`fixtures/`), `baseline.json`. Guide: `evals/README.md`; E1 labeling guide: `evals/e1/FORMAT.md`.
- `scripts/lib/python/storyforge/cassette.py` — record/replay (inert unless `STORYFORGE_CASSETTE` is set).
- `docs/history.md` — design rationale moved out of `CLAUDE.md`.
- storyforge-evals repo (`~/Developer/evals`, `benjaminsnorris/storyforge-evals`) — classics runs and gold labels (Carol, Gatsby, Plastic Age), worked by evals-56.

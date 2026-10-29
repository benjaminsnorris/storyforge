# Storyforge rethink — status and handoff

Last updated 2026-10-28, at v1.78.0 (main `ba3a551`). Start here when resuming the rethink in a new session. The plan is `docs/plans/2026-10-28-storyforge-rethink.md`; the corpus survey is `docs/plans/2026-10-28-storyforge-corpus-survey.md`.

## Where we are

**Phase 0 (evals and baseline) is done except E4 and E6.** Chunks 0–4 of plan §7 are merged; `evals/baseline.json` is committed. Phase 1 has not started.

| Plan chunk | State | PRs |
|---|---|---|
| 0 Corpus survey | done | (survey doc, #337) |
| 1 Harness | done | #337 |
| 2 E1 corpus | done: 144 cases (130 prose), 30 held out | #340 |
| 3 E2 / E7 / E8 | done: E2 Carol (evals-56), E2 on E1, E7 Carol, E8 three pass families | #341, #342, #343, #344, #346 |
| 4 E3 / E5 | done | #346 |
| — E4 / E6 | **not started**: needs a budget decision (below) | |
| 5 Phase 1 | not started; bug checklist is in the plan under Phase 1 | |

## Baseline (`evals/baseline.json`)

All eight suites replay offline: 2105 recorded calls, $0 to rerun, $15.11 if run live.

| Suite | Measures | Baseline | Gate |
|---|---|---|---|
| `e1-corpus` | gold-set health | 144 cases, 130 prose; 53 tool-introduced, 47 author-labeled, 25 unfixed at HEAD | pass |
| `e2-carol` | 37 errors injected into *A Christmas Carol* | 0 detected | recall ≥ 0.9 per code, precision ≥ 0.8 |
| `e2-corpus-validate` | deterministic continuity checks vs 51 real E1 errors | code-matched recall 0.12 (likely incidental), precision 0.035 | same |
| `e2-corpus-drift` | timeline drift check vs the same 51 | recall 0.06 (TIM 3/12), precision 0.30 | same |
| `e3-extraction` | extraction captures the fact behind each E1 error | 0.16 (0.43 with partial); TRT 0/14 | ≥ 0.85 |
| `e5-roundtrip` | facts a redraft-from-brief changes (10 shared-dark Act 1 scenes) | 7.2 per scene | coverage only (trend metric) |
| `e7-classics` | continuity flags on *A Christmas Carol* (no real errors) | 60 flags, all noise (48 FP, 6 deliberate, 6 extraction errors) | 0 noise, 0 unreviewed |
| `e8-revision-safety` | today's passes reintroduce E1 tool-introduced errors | 4 of 23 | 0 |

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
- **Versions:** another session (evals-56, working in the `storyforge-evals` repo) also opens Storyforge PRs. Whoever merges second takes the next version and resolves the one-line `plugin.json` conflict. Ask before claiming a version if the other session is active.

## Open decisions for Ben

1. **E4 + E6 budget.** E4 drafts shared-dark Act 1 (23 scenes, ~21k target words) end to end with today's `write`, then judges it: ~$14/run. E6 needs two more independent runs of E4 and the paid E2 suites (each under its own recording key, since replays would repeat one answer): ~$40 more. Proposed: E4 alone first.
2. **The Plastic Age E7 flags** (storyforge-evals PR #10, `gold/plastic-age/e7-flags.csv`, 60 flags; first pass 50 FP / 9 extraction-error / 1 deliberate) need `ben_verdict`. Once in, add the book to `evals/fixtures/e7/` from `projects/plastic-age/reference/` **at commit `72cd806`** (later timeline passes change `scenes.csv`).
3. **`author-labeled` strictness.** Cases drawn from Claude-written continuity reports carry `label_source` but not the tag (counting them adds 12 governor cases). Kept strict unless Ben says otherwise.
4. **Missing pieces of E8**: hone physical-states replay; 13 March-era revision-plan cases are unreplayable.

## Next steps, in order

1. Ben decides E4/E6 budget → build E4 (and E6), re-record, refresh `baseline.json` with `--baseline`.
2. Add The Plastic Age to E7 once verdicts land.
3. Phase 1 (plan chunk 5): model upgrades, extended thinking for fact work, structured outputs replacing `KEY: value` parsers, warn-and-continue → halt, and the **Phase 1 bug checklist** in the plan. Measure each change with `python3 evals/run.py` against the baseline; re-record suites whose prompts changed.

## Key paths

- `evals/` — harness (`harness/`, `run.py`), suite modules (`e1`, `e2`, `e3`, `e5`, `e8`), suites (`suites/`), fixtures and recordings (`fixtures/`), `baseline.json`. Guide: `evals/README.md`; E1 labeling guide: `evals/e1/FORMAT.md`.
- `scripts/lib/python/storyforge/cassette.py` — record/replay (inert unless `STORYFORGE_CASSETTE` is set).
- `docs/history.md` — design rationale moved out of `CLAUDE.md`.
- storyforge-evals repo (`~/Developer/evals`, `benjaminsnorris/storyforge-evals`) — classics runs and gold labels (Carol, Gatsby, Plastic Age), worked by evals-56.

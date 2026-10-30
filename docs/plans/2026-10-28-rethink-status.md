# Storyforge rethink — status and handoff

Last updated 2026-10-29 (night), at v1.87.1 (E8 gaps done in #383; next is E6). Handoff for the next session: **Decisions** and **Next steps** below. Start here when resuming the rethink in a new session. The plan is `docs/plans/2026-10-28-storyforge-rethink.md`; the corpus survey is `docs/plans/2026-10-28-storyforge-corpus-survey.md`.

## Where we are

**Phase 0 (evals and baseline) is done except E6.** Chunks 0–4 of plan §7 and E4 are merged. **Phase 1 is mostly done:**
- **Models:** tiers resolve at runtime, with a thinking allowance.
- **Bugs:** the whole bug checklist is fixed.
- **E3 tier comparison:** no routing change.
- **Structured outputs:** the knowledge and physical-state chains use them.
- **Loud failures for bad replies:**
  - cut-off drafts (#364);
  - refusals, via the fallback (#368);
  - invented names in brief rewrites (#373);
  - refused, cut-off and errored batch replies (#374);
  - cut-off replies in direct-mode score, timeline cues and scenes-setup (v1.84.5).

**Phase 1 regression tests.** The three silent-failure tests from the success criteria exist:
- `tests/commands/test_cmd_revise.py::TestPassThatChangesNothing` (understory `5ac1c26`);
- `tests/test_redraft_guard.py` (thornwall `19530d5`; the "reference doc" was `scenes/council.md`, a scene file);
- `tests/test_hone.py::test_a_mapping_never_takes_an_alias_from_its_owner` (meridian-line `5433d3f`).

**Left in Phase 1:**
- the remaining `KEY: value` parsers. Characterize, intent and brief fields moved to structured outputs in v1.85.0 (#377), and the skeleton in v1.88.0 (#388): one reply fills `scenes.csv` and the timeline cues, whose texts `timeline.CUE_FIELDS` shares with the cue read. Left: extract's cleanup passes (`FIX:` lines in `parse_knowledge_cleanup_response` and `parse_mice_cleanup_response`) and the `prompts.py` consumers;
- the remaining warn-and-continue sites.

**Dashboard (v1.86.0, #378, closes #371):** Storyforge sends versioned `dashboard_data` (schema version 1, contract in `docs/agent-reference.md`), and Bookshelf renders it (bookshelf#30). The renderer and `dashboard_html` are gone, and `storyforge visualize` writes `working/dashboard-data.json`. Folding the data into the Phase 2 `export` bundle is still to do.

**E2 recall:** the Phase 1 criterion "E2 recall improves over baseline" is not met. E2-Carol finds 0 of 37, and e2-corpus-drift recall is about 0.10. Most of Carol's injected errors (physical state, knowledge, numbers) are outside what the timeline check reads, so real recall depends on the Phase 2 ledger and the Phase 3 checker.

| Plan chunk | State | PRs |
|---|---|---|
| 0 Corpus survey | done | (survey doc, #337) |
| 1 Harness | done | #337 |
| 2 E1 corpus | done: 144 cases (130 prose), 30 held out | #340 |
| 3 E2 / E7 / E8 | done: E2 Carol (evals-56), E2 on E1, E7 Carol, E8 (seven pass families, 37 cases run) | #341, #342, #343, #344, #346, #383 |
| 4 E3 / E5 | done | #346 |
| — E4 | done (overnight): shared-dark Act 1 drafted with today's `write`, judged; see the E4 notes below | #361 (v1.81.0), re-recorded in #363 |
| — E6 | not started: approved, about $40 (Next steps 2) | |
| 5 Phase 1 | mostly done (see above); the other `KEY: value` parsers and the remaining warn-and-continue sites to go | v1.80.0 PR, #359, #361, #363, #364, #368, #373, #374 |

## Baseline (`evals/baseline.json`)

All eight suites replay offline: 2106 recorded calls, $0 to rerun, $10.80 if run live. Re-recorded on v1.80.0 with the current models (Opus 5.5, Sonnet 5.5, Haiku 5.5, resolved at runtime); the v1.78.0 figures are in parentheses. The E5 and E8 judges moved to the new Opus too, so part of those deltas is the judge.

| Suite | Measures | Baseline (v1.78.0) | Gate |
|---|---|---|---|
| `e1-corpus` | gold-set health | 144 cases, 130 prose; 53 tool-introduced, 47 author-labeled, 25 unfixed at HEAD | pass |
| `e2-carol` | 37 errors injected into *A Christmas Carol* | 0 detected (0) | recall ≥ 0.9 per code, precision ≥ 0.8 |
| `e2-corpus-validate` | deterministic continuity checks vs 51 real E1 errors | code-matched recall 0.12 (likely incidental), precision 0.035 (unchanged: no model) | same |
| `e2-corpus-drift` | timeline drift check vs the same 51 | recall 0.10 (0.16), precision 0.40 (0.30) | same |
| `e3-extraction` | extraction captures the fact behind each E1 error | 0.29 with structured outputs (0.24 before, v1.80.0); 0.76 with partial (0.82) | ≥ 0.85 |
| `e5-roundtrip` | facts a redraft-from-brief changes (10 shared-dark Act 1 scenes) | 3.2 per scene (7.2) | coverage only (trend metric) |
| `e7-classics` | continuity flags on *A Christmas Carol* (2 runs) and *The Plastic Age* (1 run); no real errors | 115 flags, all noise: 96 FP, 7 deliberate, 12 extraction errors (Carol alone: 60) | 0 noise, 0 unreviewed |
| `e8-revision-safety` | today's passes reintroduce E1 tool-introduced errors | 6 of 35, 2 halted (a naturalness redraft with no reply and a refused redraft-from-brief); 15 unreplayable, each with its reason (5 of 21 before the E8 gaps work) | 0 |
| `e4-generation` | draft shared-dark Act 1 (23 scenes) with today's `write`, judge it | 22 drafted, 1 refused; CP10k 18.2 (judge), 0.49 (shipped checker); BPS 2.86; length drift 0.054; voice 4.69 (author 4.75). $5.77 if live | every scene drafted (fails: 1 refused) |

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

### Morning summary (2026-10-29)

**Merged** (5-agent review pending on all of them; it was skipped overnight):

| PR | Version | What |
|---|---|---|
| #359 | 1.80.2 | All five open Phase 1 checklist bugs fixed, each with a regression test (details in the plan's checklist) |
| #361 | 1.81.0 | E4 generation benchmark; E3 model-tier comparison (no routing change) |
| #363 | 1.83.0 | Structured outputs (`api.invoke(output_schema=…)`) for the knowledge and physical-state chains; extract Phase 3b/3c halt at a failed scene instead of skipping it; E4/E8 count refusals as outcomes; E3 and E4 re-recorded |

evals-56 merged #357 (1.80.1), #358 (1.80.3, physical-state `resolves`), #360 (1.81.1, `RefusalError`; timeline no longer asks for written reasoning) and #362 (1.82.0, Phase 0 budget from the context window) in the same window. The versions were coordinated.

**Eval deltas vs the v1.80.0 baseline:**
- **E3:** recall 0.245 → 0.286 (12 → 14 captured). With partial, 0.816 → 0.755 (missing 9 → 12). Most of the move came with structured outputs, from single runs on 49 cases; it's inside noise until E6 measures variance.
- **E8:** reintroduced 5 (unchanged). Replayed 23 → 21, because 2 cases now halt: one cut-off and one refused redraft. Both used to be judged as finished scenes.
- **E2-corpus-validate:** flag counts moved because of #358 (precision 0.036 → 0.031).
- **E4:** new. CP10k 18.2 (judge) vs 0.49 for the shipped checker; BPS 2.86 (mostly the corrupt briefs below); 1 of 23 scenes refused.
- **Unchanged:** E1, E2-Carol, E2-drift, E5, E7.

**Spend:** $8.45 of $20 on E4 (first recording $5.76, re-record after the refusal change $2.69). $6.09 of $25 on everything else (E3 Haiku $0.48 and Opus $3.73 for the tier comparison; E3 re-record $1.88).

**Skipped, and why:**
- **The other seven `KEY: value` parsers** in `extract.py` (characterize, skeleton, intent, briefs, cleanup), the `prompts.py` consumers, and the remaining warn-and-continue sites. I did the two fact-work chains that E3 measures. The rest is a larger refactor with no eval covering it and no review overnight.
- **The `validate` check for a physical state whose owner is absent.** It adds two unlabeled E7 flags (Christmas Carol `scrooge-cold-exterior`, Plastic Age `caps-pocketed-carl`; both look like extraction errors), and labeling them is your call.
- **Routing `_TASK_TIER['extraction']` off Haiku.** E3 doesn't measure timeline cues or `enrich`, and the drift re-record would cost ~$16.
- **"A pass cannot overwrite a reference doc"** (plan Phase 1 success criteria). I couldn't tie it to a specific survey case; say which one you meant.

**Needs your decision** (details in the E4 notes below):
1. ~~**shared-dark briefs.**~~ Done in v1.84.2. `_fix_upstream_briefs` saw a scene's title, POV, outcome, value at stake, arc and current brief, but not its characters, place, plan or prose. From ac569274 (2026-04-07) to f56db284 it rewrote 21 of the 23 Act 1 briefs, and 17 of those name people the book never mentions (Mallen, and *Chicago P.D.*'s Danny Olinsky and Detective Ruzek); it also recast the book's own Hank Voigt as a police sergeant. It now sees the scene's characters, place, plan and prose. A rewrite is rejected with a WARNING when it lacks a field or names a capitalized word found nowhere in the reference files, the scene's prose or the brief fields the fix keeps. The check can't catch a known name given a new role. Only scenes whose brief changed are redrafted, and the run lists the scenes left unchanged and why. Follow-up: `hone.hone_briefs` also rewrites briefs and could use the same check (move it to a shared module then). **E4/E5 were re-pinned** (Ben's call) to 5e9bdf39, the commit before the fix ran, and re-recorded ($7.06 with E8's two naturalness cases). E4: BPS 2.86 → 0.26, CP10k 18.2 → 16.1, 23/23 drafted. E5: mismatches 32 → 64, because the old pin's prose had been redrafted from the same rewritten briefs. **Still Ben's:** the briefs at shared-dark HEAD are still the rewritten ones; restoring them is author data.
2. ~~**Refusals.**~~ Done in v1.84.0, #368 (Ben chose the recommendation). Prose calls send `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`): `write` drafts, `revise` redrafts, the polish loop, and every pass that isn't structural/registry (those write CSV). A refusal is re-run on Anthropic's fallback model for that category. Each reply it writes logs a WARNING, is listed again at the end of the run, and is named in the commit (`refusal fallback: written by <model>`); where the call's cost is logged (write, revise passes) it is costed as that model. Batch mode retries a refused scene once directly with the fallback. Non-prose calls (extract, score, timeline, evaluate) don't opt in. Under a cassette the fallback is stripped, so evals measure the requested model (waking-hank still replays as refused). Not done: the refused attempt's own tokens (`usage.iterations`) aren't costed, and `_redraft_from_briefs`, `_redraft_scenes` and the polish loop log no cost at all (pre-existing). The review also fixed the polish loop, which never wrote its scenes (wrong `extract-scenes` arguments) yet marked the pass completed.
3. ~~**`write` writes cut-off drafts.**~~ Done in #364 (v1.83.1): `write` refuses a refused, cut-off, mid-sentence, empty or under-100-word reply, skips that scene and exits 1 naming it (Ben chose skip-and-continue). Batch results now keep `stop_reason`. The review also fixed coach/strict briefs being saved over scene prose and revise's redraft-from-briefs reporting success when a redraft was not written. Follow-up done in v1.84.4 (batch mode): `api.download_batch_results` marks a refused, cut-off or errored batch item `fail`, writes no `.txt` for it (removing a stale one, and an errored item's stale `.json`), and names it in a WARNING. The ten other batch callers (`timeline`, `score` ×2, `extract` ×3, `evaluate`, `enrich`, `elaborate`, `scenes_setup`) no longer use such a reply. Most skip non-`ok` items; extract and score's fidelity reader read the `.txt` directly and are protected because it is no longer there. `write` and `evaluate` pass `keep_incomplete=True`: write retries refusals, and evaluate keeps a cut-off report with a WARNING, as in direct mode. The review also made scenes-setup leave a chapter whose detection failed unsplit (exit 1), extract name scenes with no reply (exit 1), score and enrich cost every paid reply, and score and timeline name the scenes they have no fresh result for. Direct paths done in v1.84.5: score's scene scoring, timeline's cue reads and scenes-setup's detection treat a reply cut off at `max_tokens` as a failure (a refusal already raised).
4. ~~**E2-Carol:** 37 of its recorded Haiku replies hit `max_tokens`.~~ Checked 2026-10-29: not the cause. Those 37 (and 85 more) are orphaned recordings sent with `max_tokens: 1024`, from before 561c7876 added the thinking allowance. Replay now uses 61 cue reads at 17,024, all `end_turn`. The 0 recall is real: the drift check (`timeline.check_scenes`) raised 1 distinct flag across the 37 injected errors. Improving it is timeline work (evals-56's area); the orphans could be pruned.

### Original instructions

Ben is asleep; work through **Next steps** in order without asking. Rules:

- **Budget:** E4 is approved, target **under $20** for building and recording it. Separately, **$25** for everything else (E3 tier comparison, re-records after prompt changes). Before any recording, estimate its cost (`evals/e8/cli.py plan`-style or from `baseline.json` "if live" figures, adjusted to current per-model prices in `costs.PRICING`). If a step would push either budget past its cap, skip it and record why here. Keep a running spend tally in this section.
- **PRs:** one PR per logical step, `./tests/run-tests.sh` (or `python -m pytest tests/`) green and `python3 evals/run.py` run before merging; merge with `gh pr merge N --merge --delete-branch`. Bump the version per `CLAUDE.md`. No 5-agent review overnight; note in each PR that it is pending.
- **evals-56** (another session, storyforge-evals) works on `timeline.py` and has claimed 1.79.1. Message it (SendMessage) before touching `timeline.py` or claiming a version; never touch its working tree in `~/Developer/evals`.
- **Stop and leave a note here** rather than guess on anything that changes what the author sees in a book's prose or deletes author data.
- In the morning Ben wants: what merged, eval deltas vs baseline, spend, and anything skipped with the reason, at the top of this section.

Spend: $8.45 of $20 (E4), $6.09 of $25 (other). (The v1.80.0 re-record before this run cost $9.70 under a separate approval.)

## E4 notes (2026-10-28 overnight)

- **How it runs** (`evals/e4`): Act 1 prose is removed, then the 23 scenes are drafted in reading order the way `write --direct` drafts them (shared cached context, `cmd_write._build_prompt` with briefs, each scene's deps reading the new drafts). An Opus judge reads each scene against the drafts before it plus the character, world and systems bibles and `characters.csv`, and lists contradictions (by code) and broken brief promises. The shipped checker is the timeline drift check `write` runs after drafting. Direct mode, not batch (batch is refused under a cassette). The plan's human spot-check is still owed.
- *(Superseded: E4/E5 now pin 5e9bdf39 and the fix pass is guarded; see decision 1 above.)* **BPS mostly measures corrupt briefs, not drafting.** At the then-pinned commit (`0eaa3867`, shared with E5), the briefs of at least six Act 1 scenes (`claires-cold`, `waking-hank`, `name-surfaces`, `the-school`, `drive`, `fire-ostrowski`, and by the judge's notes also `harmons-hands` and `waking-maren`) describe a different story: Mallen, Yael, a prison facility, Olinsky, a Meszaros lawsuit. None of that is in the bibles or the prose. They were introduced by Storyforge's own `Polish: upstream brief fixes` / `Naturalness: upstream brief fixes` passes (`_fix_upstream_briefs`) from `ac569274` (2026-04-07) to `f56db284` (04-16), and they are still at shared-dark HEAD. The drafter followed the book, so the judge counted every beat of those briefs as broken (e.g. `waking-hank`: 9). **Decision for Ben:** re-pin E4 to a commit with sound briefs, exclude those scenes, or fix the briefs in shared-dark. This also affects E5 and E8, which redraft from the same briefs. It looks like a serious live bug in `_fix_upstream_briefs` (it can invent characters and plot), and it's a source of E1 brief-level `tool-introduced` cases.
- **One draft is a refusal.** `waking-hank`'s draft came back with `stop_reason: refusal` (category `cyber`), cut off mid-word at 528 words, and the first recording (#361) judged it as a scene. Since v1.81.1, `api` raises `RefusalError`, which stops `write` at that scene. E4 now records the scene as `refused` and drafts on, so the coverage gate fails. It was re-recorded in v1.83.0 ($2.69).

## E3 tier comparison (2026-10-28 overnight)

Same 49 facts, extraction model forced with `STORYFORGE_MODEL`, Opus judge unchanged. Recordings in `evals/fixtures/tier-comparison/` (replay free; see `evals/README.md`).

| Extraction model | captured | partial | missing | recall | with partial | cost if live |
|---|---|---|---|---|---|---|
| Haiku 5.5 | 13 | 23 | 13 | 0.265 | 0.735 | $0.52 |
| Sonnet 5.5 (today's `evaluation` tier) | 12 | 28 | 9 | 0.245 | 0.816 | $2.51 |
| Opus 5.5 | 13 | 29 | 7 | 0.265 | 0.857 | $5.02 |

**Decision: no routing change.** Sonnet is within one or two facts of Opus on a single run of 49 cases, which is inside run-to-run noise (E6 hasn't measured that noise yet), at half the cost. Haiku misses clearly more (13 vs 7). So `cmd_extract`'s fact phases stay on Sonnet (`evaluation`), and `select_revision_model`'s continuity branch stays on Sonnet. `_TASK_TIER['extraction']` (Haiku: timeline cue reads, `enrich`) isn't measured by E3. Moving it to Sonnet would mean re-recording `e2-corpus-drift` (~$16 at Sonnet) while evals-56 is changing the timeline prompt, so it's left for Ben with this evidence: E3 says Haiku drops facts.

## Decisions (Ben, 2026-10-29 evening)

1. **E6 is approved** (about $40). Estimate it first, and stop if it would pass $45.
2. **Shared-dark's original briefs:** leave them. HEAD keeps the rewritten briefs. E4 and E5 are pinned to 5e9bdf39, from before the bad briefs, so the evals don't depend on HEAD.
3. **`author-labeled` stays strict** (Claude's call, delegated by Ben). Cases taken from Claude-written continuity reports keep `label_source` but don't get the tag. `author-labeled` is the subset where a person confirmed the error. A model-written report is evidence, not a human label, and counting it would mix the two kinds of ground truth (it would add 12 governor cases). Revisit only if a gate needs more author-labeled cases than the strict set has.
4. **Close the E8 gaps.** Ben wants every E8 case that today's Storyforge can meaningfully run to be replayed.

## Next steps, in order (handoff for a new session)

Start by reading this doc, `CLAUDE.md` and `docs/agent-reference.md`.
- **Checks:** run `python -m pytest tests/` and `python3 evals/run.py`. Main should replay every suite with no errors and no deltas. At v1.87.1 (#383) it did: 7,096 tests, and only the gates that already failed still fail. Replay needs no API key. Expect about 5 minutes for the tests and 6 to 10 for the evals; most of the eval time is e2-corpus-drift and e2-corpus-validate. pytest-xdist doesn't help (the time is file I/O, not CPU), so run the tests serially.
- **Coordination:**
  - Two other sessions open Storyforge PRs and claim versions: **evals-56** (timeline, classics) and **evals-79** (extract, publish fixes). Message them (SendMessage) before claiming a version or touching `timeline.py`. Eval-only and test-only PRs bump nothing.
  - evals-56's TIME_GAP/TIME_SPAN wording for `timeline.CUE_INSTRUCTIONS` merged in v1.86.1 (#380).
  - Never touch `~/Developer/evals` or evals-56's worktrees (`~/Developer/storyforge-*`).
- **Process:** one PR per step, followed by the 5-agent review (CLAUDE.md). The `pr-review-toolkit` agents it names aren't installed here; #383 used three available reviewers covering the same five angles (correctness, silent failures, tests, comments, types). Then wait for Ben's "fix all of them in logical commits", and merge in order once the checks pass.
- **Spending:** estimate before any recording.

1. ~~**E8 gaps.**~~ Done (#383; $3.88 recorded, $0.70 re-recorded after the review). 37 cases are run, up from 23. 35 are judged and 2 halt, as before (a refused redraft and a naturalness redraft with no reply). Of the 35, 6 are reintroduced (was 5 of 21). What changed:
   - **Scene metadata migrated:** a pre-pass tree with `scene-metadata.csv` gets a port of the scenes.csv step of Storyforge's removed `storyforge-migrate-elaborate` (e22a58c4), applied in the copy. It approximates the books' history: they actually got `scenes.csv` from `extract`'s skeleton phase. This adds governor-013 and -014, shared-dark-030, -037 and -038, and thornwall-020.
   - **Data passes judged on what they write:** brief fix (thornwall-033, -035), `hone` physical-states (governor-020, thornwall-037), `illustrate --state` (lantern-folk-029 to -032) and `illustrate --prompts` (lantern-folk-033). A separate judge prompt reads what the pass wrote. The prose judge prompt is unchanged.
   - **Renamed scenes** are found through E1's id-maps.
   - **The suite's notes** now list every unreplayable case.
   - **Case data:**
     - thornwall-028's introducing commit is 749a82b, which wrote both "six" and "nine" years (7919d1a only reworded "six").
     - thornwall-015's error dates from s20's first draft (6456a04), not pattern-thinning.
   - **New reintroduction:** thornwall-020 (revision plan, a newly migrated tree). The data passes reintroduced nothing.
   - **Review fixes:** a data pass that exits non-zero errors the suite, a cut-off hone batch halts, and a keyless replay works (illustrate checks the key itself). `written()` diffs CSVs by row id, so a brief fix shows only its row. `errors_per_10k_words` counts prose hits only. A `not_present` that was never judged says so.
   - **Still excluded (14 holdout, plus):**
     - **10 YAML-era trees** (governor-011, thornwall-002, -005, -008, -011, -013, -014, -015, -019, -021). Today's `revise` refuses YAML plans, and Storyforge's YAML-to-CSV migration was lost in #13's squash. Replaying them would mean inventing both conversions. Ben's call if he wants that.
     - **shared-dark-018 and -023:** redrafted from an outline before briefs existed. Today's redraft needs briefs, and none are invented.
     - **lantern-folk-027 (PRM):** the pass wrote only the promise (a11). The missing payoff is in a scene it never touched.
     - **lantern-folk-034:** no introducing commit, because the prompt files were untracked render output.
     - **lantern-folk-032:** the `--state` pass logged the prose of the time faithfully; the log went stale after a later prose fix, which a replay can't show (`EXCLUDED_CASES`).
     - **thornwall-028:** its introducing commit wrote both sides, so the pre-pass tree has no established fact to contradict (`EXCLUDED_CASES`).
2. **E6** (approved, about $40): two more independent E4 runs plus the paid E2 suites, under separate recording keys, to measure run-to-run variance. Plan §4.2 has the design. E3's tier comparison and E3's recall moves are both "inside noise until E6"; report them against E6's spread.
3. **Phase 1 leftovers:**
   - ~~Extract's **skeleton** phase.~~ Done in v1.88.0 (#388). A skeleton reply that is unusable for any scene now stops the calendar from being placed (it used to re-place every scene from stale or missing cues, with force). The remaining line parsers are extract's cleanup passes (`FIX:` lines) and the `prompts.py` consumers.
   - Then the remaining **warn-and-continue** sites. Grep for `WARNING` followed by `continue` in paths that write output.
4. **Follow-ups noted in PRs:**
   - `hone.hone_briefs` also rewrites briefs and should use the brief-fix name check (`cmd_revise._invented_names`; move it to a shared module).
   - `skills/forge` routes to `scenes` and `recommend` skills that don't exist.
   - `dashboard_data` should fold into the Phase 2 `export` bundle.

Then **Phase 2** (plan §5): ledger, `commitments.csv`, per-character state, `export`.

## Key paths

- `evals/` — harness (`harness/`, `run.py`), suite modules (`e1`, `e2`, `e3`, `e5`, `e8`), suites (`suites/`), fixtures and recordings (`fixtures/`), `baseline.json`. Guide: `evals/README.md`; E1 labeling guide: `evals/e1/FORMAT.md`.
- `scripts/lib/python/storyforge/cassette.py` — record/replay (inert unless `STORYFORGE_CASSETTE` is set).
- `docs/history.md` — design rationale moved out of `CLAUDE.md`.
- storyforge-evals repo (`~/Developer/evals`, `benjaminsnorris/storyforge-evals`) — classics runs and gold labels (Carol, Gatsby, Plastic Age), worked by evals-56.

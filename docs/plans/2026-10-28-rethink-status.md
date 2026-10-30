# Storyforge rethink — status and handoff

Last updated 2026-10-30 (late), at v1.98.0 (phase 4's rubric tightened and linked to the registry facts, F-127/F-128). **A fresh session starts here:** read **Start here** and **Next steps** below, then `CLAUDE.md` and `docs/agent-reference.md`. The plan is `docs/plans/2026-10-28-storyforge-rethink.md`; the corpus survey is `docs/plans/2026-10-28-storyforge-corpus-survey.md`. Everything after **Next steps** is reference and history.

## Start here

**Where the rethink is:**
- **Phase 0 (evals and baseline): done**, E6 included.
- **Phase 1 (cheap fixes): done** (E2 recall didn't improve; that waits on the Phase 3 checker).
- **Phase 2 (ledger and export): done** (v1.97.0).
  - **Done:** `reference/commitments.csv` (`storyforge/ledger.py`) replaces `knowledge.csv` and `physical-states.csv`, and every consumer uses it (#416, #417). All seven books are migrated and merged on their `main`. Derived per-character state exists (`ledger.active_states`). The rubric-driven extraction is extract **phase 4** (#424). The audit log and `storyforge audit` exist (#423). `storyforge export` writes the versioned bundle with `dashboard_data` folded in (#422).
  - **Success criteria (plan §5):** E3 recall ≥ 0.85: **met, 0.898** (was 0.286). Export round-trips: **met** (`evals/export_check.py`: 7 of 7 books byte-identical). E5 mismatches below baseline: **met, 64 → 23** (6.4 → 2.3 per scene; v1.97.0). E4 did not get worse (CP10k 16.1 → 14.2, contradictions 35 → 31, 23/23 drafted). E8 unchanged (reintroduced 6, per 10k words 1.74 → 1.69).
  - **Drafting reads the ledger** (v1.97.0): `build_scene_prompt_from_briefs` (write and revise's redraft-from-brief) has an "Established Facts" section from `ledger.drafting_slice`: for the POV, on-stage characters and location, `pronouns` from characters.csv, `fixed` facts before the scene, states entering it (at most `prompts.MAX_STATES_PER_SUBJECT` = 25 each, the rest named), and the scene's own facts ("the brief wins where they differ"). E5 now runs extract phase 4 over its sample first (10 Sonnet calls), so the redraft sees the prose's commitments. **Not like-for-like with the old E5 number:** part of the fall is the redraft being shown facts read off the prose it is judged against, which is the design (a pinned fact should survive a redraft). The character bible is still sent whole: slimming it to fixed facts + voice is author data, left for Ben.
- **Phase 3 (the gate and sequential loop): next** (Next steps 1). F-127/F-128 are in (v1.98.0); first, re-score their precision on Carol (Next steps 1).

**What exists now, for orientation** (contracts in `docs/agent-reference.md`):
- **Ledger:** `ledger.load`/`save(…, command=)` (every save appends to `working/audit-log.csv`); typed views `knowledge_view`/`physical_view` (registry rows only, which briefs reference by id); `active_states`, `established_before`, `scene_order`; `LedgerError` / `NotMigratedError`.
- **Two kinds of fact rows:**
  - **Registry facts** (extract 3b/3c, hone; `introduced_by` extract/hone/migration) are what briefs' `knowledge_in/out` and `physical_state_in/out` name.
  - **Commitments** (extract phase 4, `introduced_by=commitments`, `ledger.COMMITMENTS_PASS`) cover all seven types, each with a quote. They're outside the views and untouched by view writes.
  - **Phase 3's gate is where the two meet.**
- **`storyforge audit`:** a per-act digest of unreviewed binding facts, tiered as decision 2 says. `--mark seen|rejected`. Hand edits are caught through `working/.audit-snapshot.csv`. `audit.halting_conditions` is the immediate tier, for the gate to call.
- **`storyforge export`:** `working/export/bundle.json`, `schema_version` 1, tables stored losslessly.

| Plan chunk | State | PRs |
|---|---|---|
| 0–4 Survey, harness, E1, E2/E7/E8, E3/E5 | done | #337–#346, #383 |
| — E4, E6 | done | #361, #363, #397, #399 |
| 5 Phase 1 | done | #359–#405 |
| 6 Phase 2 | built; E5 criterion open (Next steps 1) | #401, #416, #417, #420–#424 |
| 7 Phase 3 | next | — |

## Next steps, in order (handoff for a new session)

**Before starting:**
- **Environment:** use `~/.venvs/storyforge` (Python 3.12, has pytest). Put it first on `PATH` for the suite, because three `test_illustrate_cmd.py` tests shell out to `python3`, which is 3.9 here. The book repos under `~/Developer` are read-only unless Ben says otherwise: work on copies.
- **Checks:** `PATH=~/.venvs/storyforge/bin:$PATH python -m pytest tests/` (5 to 10 minutes; 7,525+ tests at v1.96.0) and `python evals/run.py` (6 to 10 minutes, replay, no key). Main replays every suite with no errors. The gates that fail are E2 (all three), E7 noise and E8 reintroduced; E3, E4 and E5 pass.
- **Coordination:** other sessions open Storyforge PRs and claim versions; today that was **evals-b5** (F-122 to F-124, F-123's forced-3b fix). Find live ones with ListAgents, agree a version by SendMessage before merging, and say when you touch `cmd_extract.py`, `ledger.py` or `cmd_validate.py`. Eval-only and test-only PRs bump nothing. Never touch `~/Developer/evals` or other sessions' worktrees.
- **Process:** one PR per step, on branch `storyforge/{name}-{timestamp}`. Work in a scratchpad worktree when a suite is running in the main checkout: switching branches under a running suite breaks it. Get one to three general reviewers covering correctness, silent failures, tests and comments. Fix every verified finding before merging (Ben's standing instruction this session), and list them in a PR comment.
- **Spending:** re-records don't need asking (Ben, 2026-10-30: "just do it"); estimate from the `if live` figures or `evals/e8/cli.py plan` and report what was spent.

**Done in v1.98.0: F-127 and F-128** (phase 4; Ben approved).
- **F-127, the rubric:** "locations at scene end" became locations that carry past the scene; it now names what to leave out (staging, set dressing, asides, figurative language read literally, a time the text neither states nor shows), and keeps what a vision or ghost shows as a commitment.
- **F-128, linking:** phase 4 is offered the registry facts in force and those recorded for the scene (`cmd_extract._phase4_known`), each marked state/fixed and registry; past `MAX_KNOWN_COMMITMENTS` the scene's people and place come first, fixed before states. A commitment's `ends` sets `resolves` on this pass's own earlier states. Reported for the author, never applied: prose that disagrees with a registry fact recorded for the same scene, a registry state the prose ends where its `resolves` says otherwise, facts tied to no scene in the run, and the cap.
- **Evals ($4.59, plus under $1 on a recording stopped for review fixes):** E3 recall 0.898 → 0.857 (still ≥ 0.85; 2 of 49 captured became partial/missing). E5 23 → 29: the new mismatches are nearly all staging and set dressing (which hand trembles, pen vs pencil, a door frame's material), what F-127 stops recording. E3/E5 don't measure precision, and nobody has re-scored it yet (evals-9a, who offered, ended its session): see Next steps 1.
- **Still open from Phase 2:** fill `characters.csv` `pronouns` (phase 4 output or a hone gap; drafting already shows it). Ben wants phase 4 run on the seven books now that both landed (his call when).

**1. Re-score phase 4 on *A Christmas Carol* at v1.98.0** (F-127/F-128's check; nothing else measures precision).
- Run `storyforge extract` phase 4 on a copy of the Carol project in storyforge-evals (`~/Developer/evals`, read-only: copy it out; evals-9a's v1.96.1 run cost $2.84).
- Score against `gold/christmas-carol/commitments.csv` the way `phase4-results.csv` (recall 0.98, 0.82 one row per fact) and `phase4-precision.csv` (every 7th row: 52% commitments, 44% incidental, 4% wrong) were scored. Also count rows (558 for 40 scenes) and phase-4 rows that restate a migrated row (18 of 80).
- If precision didn't move or recall fell much, revisit the rubric before Phase 3 leans on phase 4.

**2. Phase 3: the gate and sequential loop** (plan §3.2–3.3 and §5 Phase 3; chunk 7).
- **The gate:** extract, check, fix, commit after every draft, redraft or revision.
  - Extract with phase 4's rubric.
  - Check against the ledger slice, using a tool-using checker.
  - Fix with targeted edits.
  - Commit the scene's facts as binding, through `ledger.save`, which writes the audit entry.
  - Halt on `audit.halting_conditions` and on plan contradictions.
- **The loop:** sequential drafting with prior prose (decision 4), plus the context-size experiment.
- **Success:** E4 CP10k and BPS halve vs baseline, and E2 precision ≥ 0.8.
- **Settle first:** how registry facts and commitments merge; that's the gate's job (see "Two kinds of fact rows" above).

**Open follow-ups, not scheduled:**
- **The books' validate findings** are the author's. Thornwall's Garren (16 states) and governor's `governor` (9) have no `characters.csv` entry. Briefs name physical states the ledger doesn't hold, in the hundreds for shared-dark, governor and meridian-line. Understory has 16 cells with parenthetical text that `migrate` step 5 left for hand edits.
- **Rejected facts are still used** by consumers, because the views don't filter on `status`. This is Phase 4's reject flow.
- **F-123 limitation:** a hand-added fact that no brief's `knowledge_out` lists isn't offered to later 3b scenes.
- **Export bundle size:** governor's is 46 MB, mostly its score rationale CSV, which `dashboard_data` repeats.
- **Phase 4 model:** it runs on the `evaluation` tier (Sonnet). The plan says "strongest model", but Sonnet passes the gate; switch only on evidence.
- **From before today, still open:** other writers of briefs and intent don't use `brief_names`' check (#393); `scoring_story_power` hasn't been reviewed for warn-and-continue; measure E8 over three runs before Phase 4 gates on it; replaying the 10 YAML-era E8 trees is Ben's call.

## 2026-10-30 late (storyforge-25)

Ben: "pick up and carry on"; re-records approved without asking. Two PRs: drafting from the ledger (#430, v1.97.0, Phase 2's last criterion) and F-127/F-128 (v1.98.0). #430's reviewer: 3 high, 5 medium, 1 low, all fixed except phase 4's missing `resolves` (done in F-127 as `ends`). F-127/F-128's reviewer: 3 high, 3 medium, 2 low, all fixed. Spend: $11.52 for #430 (E5 $2.61 with phase 4, E4 $5.29, E8 $3.62), about $5.5 for F-127/F-128 (E3 $2.34, E5 $2.24, a stopped recording). evals-9a merged 1.96.1–1.96.3 (F-125, F-119, F-126) in the same window.

## 2026-10-30 afternoon and evening (storyforge-59)

**Ben's instructions this session:** go through Next steps; re-recording and migrating his books were approved; merge the book PRs; fix migrate step 5 and migrate understory; finish Phase 2. Review findings were fixed directly, without waiting for his go-ahead.

**PRs, evening** (after the afternoon table below):

| PR | Version | What |
|---|---|---|
| #420 | 1.93.1 | `migrate` step 5 leaves a cell whose normalizing would drop parenthetical text (and lists it); the MICE normalizer keeps a `[note]` after a thread name |
| #421 | 1.93.2 | `commit_and_push` pushes a branch with no upstream with `-u`, and warns when a push fails (migrate's branch had stayed local) |
| #422 | 1.94.0 | `storyforge export` (bundle contract in agent-reference); `evals/export_check.py` |
| #423 | 1.95.0 | audit log, `storyforge audit`, `audit.halting_conditions` |
| #424 | 1.96.0 | extract phase 4 (the decision-5 rubric) and evals-b5's F-123 fix (forced 3b offers what this run showed; declared facts placed in `knowledge_out`; live P&P forced 3b: 32 knowledge flags on 1.93.0, 2 with the offer fix alone, 0 with both commits). E3 0.286 → 0.898 ($3.12 recorded) |

**Books:** all seven ledger PRs were merged (shared-dark#88, thornwall#71, lantern-folk#15, governor#82, meridian-line#86, understory#36, slipform#24). Understory then got the full `migrate` (#37), which normalized 15 cells and left 16 for hand edits.

**Spend this session:** $3.80 (E3 and E8 after #417), $3.12 (E3 for phase 4 and F-123).

**Afternoon PRs** — Ben's five decisions and both ledger PRs. Each PR had one to three general reviewers; every verified finding was fixed before merging (the PR comments list them).

| PR | Version | What |
|---|---|---|
| #409 | 1.90.9 | score leaves `latest` on the last complete cycle; an incomplete cycle gets `cycle-N/incomplete.txt`, which `project.latest_scores`' fallback skips; revise's lightweight re-score doesn't repoint `latest` past failed scenes |
| #412 | 1.90.10 | a configured cover that's missing fails: `assembly.configured_cover_path` raises; publish exits 1; assemble names epub and web as not generated (exit 1), makes no placeholder, and the web book uses the configured cover |
| #414 | 1.90.12 | enrich's timeline step message and `--skip-timeline` removed |
| #415 | 1.91.0 | `owed` column in `revision-plan.csv`: a prose pass's unwritten scenes (all unwritten targets when the reply was cut off), saved in the commit with the written ones; a re-run revises only those. GN briefs skip scenes whose brief has goal, page_layout and panel_breakdown |
| #416 | 1.92.0 | `storyforge/ledger.py` and the migration; `evals/ledger_check.py`. The round trip is cell by cell (4,243 single-cell mutations over the seven books, all caught) |
| #417 | 1.93.0 | every registry reader and writer on `reference/commitments.csv`; `storyforge migrate` step 4; F-123 (extract 3b offers only earlier facts). E3 and E8 re-recorded ($3.80) |

evals-b5 merged #410, #411, #413 and #418 (1.90.11, 1.92.1–1.92.3) in the same window; versions were agreed by message.

**What #417 changed for authors:**
- Writes keep untouched rows byte-identical; a malformed ledger (bad header, wrong cell count, blank, padded or duplicate id) raises `ledger.LedgerError` and commands exit 1. Old files present make commands exit 1 with "run `storyforge migrate`".
- An unresolved physical `character` (thornwall's Garren ×16, governor's `governor` ×9) keeps its name in `aliases` with `subject` blank; validate reports each. Facts whose `scene_id` isn't a scene (shared-dark's `burnside`, `playground`, `site-review`) are offered like backstory with a WARNING and reported by validate.
- validate now checks briefs' `physical_state_in/out` against the ledger, which it never did: on migrated copies that's 521 findings for shared-dark, 402 governor, 352 meridian-line, 150 thornwall, 19 understory (understory's 1,212 knowledge findings go away). These are real author data, not migration bugs.
- `characters.csv` has an optional `pronouns` column (cleanup knows it; no finding when absent). Nothing fills it yet.

**Eval deltas** (baseline re-written after #417): E3 recall 0.286 unchanged, with partial 0.755 → 0.714 (inside E6's range); E8 reintroduced 6 of 35 unchanged; E2-corpus-validate precision 0.0312 → 0.0305 (the new owner and scene reports on controls); E7 115 → 105 flags (from evals-b5's #411).

**The books (Ben approved running the migration, 2026-10-30):** only `migrate`'s step 4 was run (not the whole command: step 5's normalize mangles understory's MICE entries, a bug on main before this work). Each book had branch `storyforge/migrate-ledger-20261030-0747` and a PR, all **merged in the evening** (see above): shared-dark#88, thornwall#71, lantern-folk#15, governor#82, meridian-line#86, understory#36, slipform#24. Eval trees are pinned commits and are migrated in each suite's copy, so the evals don't depend on this.


**Ben's decisions, 2026-10-30 morning** (on the overnight run's open questions):
1. **Ledger migration mapping:** accepted as proposed in `docs/plans/2026-10-30-ledger-migration-proposal.md`. That includes:
   - four added columns (`category`, `aliases`, `resolves`, `action_gating`);
   - `origin = migrated` and `introduced_by = migration` for migrated rows;
   - unresolved physical `character` names reported, `subject` left blank;
   - understory's statement taken from the first alias;
   - `backstory` and blank `origin` left as a blank `scene_id`, reported;
   - **two PRs:** `ledger.py` plus the migration first, then the consumer switch.
   The re-record spend for the consumer switch (about $20) was not separately approved: estimate it and confirm with Ben before recording.
2. **A configured cover that's missing fails:** `production.cover_image` set but the file absent makes `assemble` and `publish` exit 1 naming it, with no fallback to auto-detect.
3. **Remove enrich's timeline references:** step 8's message and the `--skip-timeline` flag. enrich does not run the timeline.
4. **Score's `latest` stays on the last complete cycle:** an incomplete cycle is still saved and committed, but `working/scores/latest` doesn't move to it.
5. **Per-scene pass state:** a revise pass that stopped over skipped scenes re-runs only those scenes, not every target.

**Phase 1 regression tests** (the plan's three silent-failure cases):
- `tests/commands/test_cmd_revise.py::TestPassThatChangesNothing` (understory `5ac1c26`);
- `tests/test_redraft_guard.py` (thornwall `19530d5`; the "reference doc" was `scenes/council.md`, a scene file);
- `tests/test_hone.py::test_a_mapping_never_takes_an_alias_from_its_owner` (meridian-line `5433d3f`).

**Dashboard (v1.86.0, #378, closes #371):** Storyforge sends versioned `dashboard_data` (schema version 1, contract in `docs/agent-reference.md`), and Bookshelf renders it (bookshelf#30). It folds into the Phase 2 `export` bundle unchanged, as `dashboard_data` (contract in `docs/agent-reference.md`, "Export bundle"); `evals/export_check.py` round-trips all seven books.

**E2 recall:** the Phase 1 criterion "E2 recall improves over baseline" is not met. E2-Carol finds 0 of 37, and e2-corpus-drift recall is about 0.06 (E6's three runs: 0.078, 0.059, 0.020). Most of Carol's injected errors (physical state, knowledge, numbers) are outside what the timeline check reads, so real recall depends on the Phase 2 ledger and the Phase 3 checker.

**Line parsers outside extract** (not on Phase 1's list; move them when their phase touches them): hone's `MENTION:` replies, scoring's `SCORES:` blocks (`scoring.parse_score_output`), `scenes.py`'s `SCENE:` lines.

## Baseline (`evals/baseline.json`)

All eight suites replay offline: 2106 recorded calls, $0 to rerun, $10.80 if run live. Re-recorded on v1.80.0 with the current models (Opus 5.5, Sonnet 5.5, Haiku 5.5, resolved at runtime); the v1.78.0 figures are in parentheses. The E5 and E8 judges moved to the new Opus too, so part of those deltas is the judge.

| Suite | Measures | Baseline (v1.78.0) | Gate |
|---|---|---|---|
| `e1-corpus` | gold-set health | 144 cases, 130 prose; 53 tool-introduced, 47 author-labeled, 25 unfixed at HEAD | pass |
| `e2-carol` | 37 errors injected into *A Christmas Carol* | 0 detected (0) | recall ≥ 0.9 per code, precision ≥ 0.8 |
| `e2-corpus-validate` | deterministic continuity checks vs 51 real E1 errors | code-matched recall 0.12 (likely incidental), precision 0.035 (unchanged: no model) | same |
| `e2-corpus-drift` | timeline drift check vs the same 51 | recall 0.10 (0.16), precision 0.40 (0.30) | same |
| `e3-extraction` | extraction captures the fact behind each E1 error | **0.898** with extract phase 4 (v1.96.0; was 0.29 with 3b/3c alone); 1.0 with partial | ≥ 0.85 (passes) |
| `e5-roundtrip` | facts a redraft-from-brief changes (10 shared-dark Act 1 scenes) | **2.3 per scene** with the ledger in the drafting prompt (v1.97.0; 6.4 at the 5e9bdf39 pin before it) | coverage only (trend metric) |
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

## Overnight run (2026-10-29 → 30)

Ben asked for work to continue overnight without waiting on him, and approved E6 at whatever it cost. Every PR got a review (one to three reviewer agents covering the five angles), and every finding I verified was fixed before merging. The review comments on each PR list what was found and what was left.

| PR | Version | What |
|---|---|---|
| #388 | 1.89.0 | Extract's skeleton phase uses structured outputs; `timeline.CUE_FIELDS` shared with the cue read (its prompt is byte-identical). Review found that a failed skeleton reply let the calendar be re-placed from stale cues; fixed. |
| #393 | 1.89.4 | `hone`'s brief and intent rewrites get revise's invented-name check (`storyforge.brief_names`). A delegated revise pass now redrafts only the scenes hone changed. |
| #394 | 1.90.0 | Nine warn-and-continue sites that wrote wrong or incomplete output (table in the PR). **Behaviour change:** `score`, `assemble`, `elaborate`, `revise` and the GN commands now exit 1 on incomplete output. The worst was `illustrate --state` deleting author rows it couldn't read. |
| #397 | — | Eval record mode no longer re-calls a request the run already recorded (found by E6). |
| #400 | 1.90.4 | Removed extract's unused cleanup-pass parsers (Phase 1's last parser item). |
| #401 | — | Ledger migration proposal (Phase 2 start): mapping and the decisions it needs. |
| #402 | 1.90.5 | forge routed to skills that don't exist; test for every skill a SKILL.md names. |
| #403 | 1.90.6 | evaluate paired custom evaluators with persona files by position (class C, a real bug). |
| #405 | 1.90.7 | enrich: unenriched scenes named and exit 1; its dead timeline step now says so. |
| #399 | — | E6: runs 2 and 3, `evals/consistency.py`, the spread. |
| #404, #406 | — | Status updates: the class-C and count-only follow-ups. |

**Coordination:** evals-79 and evals-1e also merged Storyforge PRs overnight (1.89.1–1.89.3, 1.90.1–1.90.3, 1.90.8). Versions were agreed by message each time.

**Class-C and count-only sites** from #394's triage, as followed up overnight:
- **Fixed:** evaluator/persona pairing by position (#403); enrich (#405).
- **Left as is:** an unreadable `scoring-overrides.csv` (it's append-only, so accepted findings just show again, with a WARNING); `scenes_export`, `script_package` and `revise_gn` (their skips are visible or affect only derived views).
- **Decided by Ben, now Next steps 2 and 3:** the cover fallback, and enrich's timeline step.

**Ben decided the open questions the next morning:** see **Start here**.

## E6 (2026-10-30)

Run-to-run variance of the paid suites: three independent live runs of the same code (v1.87.1, 3c01088d). Run 1 is the default recordings (`evals/fixtures/cassettes/`); runs 2 and 3 are `evals/fixtures/e6/run2` and `run3`. `python3 evals/consistency.py` replays all three (free) and writes `evals/e6/spread.json`; `evals/e6/e8-cases.json` is each E8 case's outcome per run. Not a default suite: the extra runs are a snapshot of one commit's prompts (see `evals/e6/__init__.py`), so they replay only while the requests match those of 3c01088d; a later prompt change is a miss. **Range** below is max − min over the three runs; three runs underestimate the true spread, so a move about the size of the range is not evidence either way.

| Suite | Metric | run 1, 2, 3 | Range |
|---|---|---|---|
| E2-Carol | recall | 0.027, 0, 0.027 | one case of 37 |
| E2-drift | recall | 0.078, 0.059, 0.020 (4, 3, 1 of 51 cases) | 0.059 |
| E2-drift | precision | 0.40, 0.25, 0.33 | 0.15 |
| E3 | recall (captured) | 0.286, 0.286, 0.265 (14, 14, 13) | 0.020 |
| E3 | with partial | 0.755, 0.714, 0.694 | 0.061 |
| E3 | missing | 12, 14, 15 | 3 |
| E4 | CP10k (judge) | 16.1, 14.2, 16.7 | 2.5 |
| E4 | CP10k (checker) | 0.46, 0.92, 0.47 | 0.46 |
| E4 | broken promises | 6, 7, 6 | 1 |
| E4 | voice | 4.80, 4.78, 4.71 | 0.10 |
| E8 | reintroduced (of replayed) | 6/35, 10/37, 11/36 | 5 |
| E8 | halted | 2, 0, 1 | 2 |

**What the claims made from single runs come to:**
- **E3, structured outputs** (recall 0.245 → 0.286, two more facts captured): twice the range, so probably real but small. "With partial" moved 0.816 → 0.755, the size of its range: noise.
- **E3 tier comparison:** Opus missed 2 fewer facts than Sonnet; Sonnet's own misses vary by 3. No evidence Opus extracts better, so **no routing change** stands. Haiku missed 4 more than Sonnet, just over the range, so "Haiku drops facts" holds weakly. (The tier runs predate structured outputs; their misses aren't comparable to today's.)
- **E2-drift, v1.80.0 model re-record** (recall 0.16 → 0.10, 8 → 5 of 51 cases; precision 0.30 → 0.40): both the size of the range (recall's 3 cases equals it exactly). Drift recall rests on 1–4 recalled cases of 51, from 1–2 true flags, so a one-case change is noise.
- **E4, re-pin to 5e9bdf39:** CP10k 18.2 → 16.1 is within the range (2.5). BPS 2.86 → 0.26 is far outside it and stands: the corrupt briefs were real.
- **E8 gaps** (reintroduced 5 → 6): noise. **The baseline's 6 is the low end:** runs 2 and 3 reintroduced 10 and 11.

**E8, per case** (`e8-cases.json`): 6 cases reintroduce their error in every run (governor-016, governor-023, shared-dark-040, thornwall-020, thornwall-026, thornwall-030). 6 more do in one or two runs (governor-014, -022, -024; shared-dark-037, -041; thornwall-025), and 8 others flip between consistent, not present and halted. **For Phase 4's gate (reintroduced == 0), one run is not enough.** Measure E8 over at least three runs and report always / sometimes / never per case; a fix should move the "always" cases and shrink the "sometimes" ones.

**Reliability, seen in passing:** one Haiku cue read, of about 5,500 drift-suite calls over the three runs, (run 3, governor's shimming-the-cot) came back as prose with no `TIME_RELATION` line. The drift suite's bootstrap stops at any failed cue read, so the suite errored. The reply is kept in `evals/fixtures/e6/run3-cue-failure/`; run 3's drift suite was recorded again without it.

**A harness bug it found (#397):** `--mode record` called a request live twice when two cases sent it (two E3 facts from one scene), and the second reply overwrote the first, so the first case's judge prompt could never replay. Record mode now replays a key the run already recorded. Runs 2 and 3 were patched in `auto` mode ($0.26; 33 judge and extraction calls). The E3 and E8 numbers above are the replayable ones; the record-time values differed by one fact (E3 run 2: 0.265) and one case (E8 run 2: 11).

**Spend:** $34.82 (run 2 $17.56, run 3 $16.30, run 3's drift retry $0.70, the patch $0.26). Ben's approval was "about $40", later "whatever it costs".

## E8 gaps (2026-10-29, #383)

Done (#383; $3.88 recorded, $0.70 re-recorded after the review). 37 cases are run, up from 23. 35 are judged and 2 halt, as before (a refused redraft and a naturalness redraft with no reply). Of the 35, 6 are reintroduced (was 5 of 21). What changed:
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

## Key paths

- `evals/` — harness (`harness/`, `run.py`), suite modules (`e1`, `e2`, `e3`, `e5`, `e8`), suites (`suites/`), fixtures and recordings (`fixtures/`), `baseline.json`. Guide: `evals/README.md`; E1 labeling guide: `evals/e1/FORMAT.md`.
- `scripts/lib/python/storyforge/cassette.py` — record/replay (inert unless `STORYFORGE_CASSETTE` is set).
- `docs/history.md` — design rationale moved out of `CLAUDE.md`.
- storyforge-evals repo (`~/Developer/evals`, `benjaminsnorris/storyforge-evals`) — classics runs and gold labels (Carol, Gatsby, Plastic Age), worked by evals-56.

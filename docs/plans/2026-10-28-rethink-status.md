# Storyforge rethink — status and handoff

Last updated 2026-10-30 (night), at v1.106.0 on PR #450 (open). **Phase 3 steps 1–4 are done; #450 is the one thing in flight** (see **In flight** below). #440's phase 5 is complete (5a–5g, with the E9 suite; see Next steps 2) and handed to storyforge-evals. **A fresh session starts here:** read **In flight**, **Start here** and **Next steps** below, then `CLAUDE.md` and `docs/agent-reference.md`. The plan is `docs/plans/2026-10-28-storyforge-rethink.md`; the corpus survey is `docs/plans/2026-10-28-storyforge-corpus-survey.md`. Everything after **Next steps** is reference and history.

## In flight (2026-10-30 night, storyforge-e9)

**PR #450** (branch `storyforge/brief-word-promises-20261030-1732`, v1.106.0 after merging main at v1.105.0): brief items written in words become promises; extraction's `supersedes`/`ends` on a registry fact become **disputes** the checker must rule on (contradiction or `cleared`; no ruling blocks as `UNRULED`), replacing the `plan-contradiction` halt (Ben's decision). Review: 3 high, 3 medium, 2 low, all fixed and listed in the PR's comments. Full suite green (7,750). E4 run 4 recorded and pruned to the 312 recordings its replay reads.

**To finish it:** run `python evals/run.py --baseline` on the branch (free replay; every suite should replay with no errors and only E4 and E2-carol-checker numbers differing from main), commit `evals/baseline.json`, then `gh pr merge 450 --merge --delete-branch`. Ben approved merging with run 4 as the baseline. Then tell evals-b6 nothing (their trigger is the persistence check, below).

**E4 through the gated `write`, four runs** (one each; target CP10k ≤ 7.1, broken promises ≤ 3):

| Run | Code | CP10k | Broken promises | Gate still failing | Cost |
|---|---|---|---|---|---|
| pre-gate | v1.98.0 | 14.2 | 6 | — | — |
| 1 | #443 | 6.0 | 11 | 3 | $13.23 |
| 2 | + promises in words | 6.8 | 6 | 8 | $13.99 |
| 3 | + checker decides (no plan halt) | 9.7 | 4 | 9 | $14.00 |
| 4 | + disputes (#450 as merged) | 12.1 | 5 | 6 | $12.88 |

Run 4's 26 contradictions: 12 in scenes the gate failed (caught; `write` would stop there), 14 in scenes it passed (missed), 20 after the first failure (E4 drafts on where `write` stops, from a ledger missing that scene's facts). The headline mixes all three, and run-to-run variance is large: neither target can be called met or missed yet.

**Next, in order (Ben agreed, 2026-10-30):**
1. **Fix E4's measure** (eval-only PR, no recording: re-score the existing cassettes). Report CP10k over scenes that passed the gate (what `write` would commit), the gate's catch rate against the judge (caught vs missed per scene), and make the headline stop at the first gate failure, as `write` does.
2. **Close the checker's blind spot.** The judge reads the character and world bibles; the checker sees only the ledger and the manuscript, so a fact that lives only in a bible ("Marie is Claire's sister") can't be checked. Give the checker the bibles (a tool or a prompt section; mind F-130: skip template-identical bibles), re-record E2-carol-checker and E4 (~$18). Most direct lever on the CP10k target.
3. **The persistence check** (Ben's trigger for running phase 4 on the seven books; see Open follow-ups): a second gate question on extracted facts, "does this fact last beyond the scene?". When it is on main, tell evals (evals-b6; their NEXT step 2, F-127).
4. **Gate revise's redraft-from-brief** through `gate_and_fix` like `write` (today it warns and lists the scenes pending). Revise's prose passes wait for Phase 4.
5. **Step 5, the context-size experiment** (decision 4): preceding scene + latest scene per thread vs the whole manuscript so far with caching, on E4 and cost per scene.
6. **Parallel vs sequential on E4**, which decides whether `--batch` stays or is deleted.
7. **Smaller:** the low-confidence halt (a `confidence` field on phase 4's schema; re-records E3 and E5, ~$5); fill `characters.csv` `pronouns`.

Then **Phase 4** (safe revision): dependency graph and re-check set (which also unblocks redrafting a scene later facts lean on), reject-fact flow, every revision pass through the gate.

**Budget note:** each E4 recording is about $13–14 and varies a lot between runs. Plan two or three runs per decision that matters, or say when one is being read alone. E4 spent today: $54.10; E2-carol-checker $7.83.

## Start here

**Where the rethink is:**
- **Phase 0 (evals and baseline): done**, E6 included.
- **Phase 1 (cheap fixes): done** (E2 recall didn't improve; that waits on the Phase 3 checker).
- **Phase 2 (ledger and export): done** (v1.97.0).
  - **Done:** `reference/commitments.csv` (`storyforge/ledger.py`) replaces `knowledge.csv` and `physical-states.csv`, and every consumer uses it (#416, #417). All seven books are migrated and merged on their `main`. Derived per-character state exists (`ledger.active_states`). The rubric-driven extraction is extract **phase 4** (#424). The audit log and `storyforge audit` exist (#423). `storyforge export` writes the versioned bundle with `dashboard_data` folded in (#422).
  - **Success criteria (plan §5):** E3 recall ≥ 0.85: **met, 0.898** (was 0.286). Export round-trips: **met** (`evals/export_check.py`: 7 of 7 books byte-identical). E5 mismatches below baseline: **met, 64 → 23** (6.4 → 2.3 per scene; v1.97.0). E4 did not get worse (CP10k 16.1 → 14.2, contradictions 35 → 31, 23/23 drafted). E8 unchanged (reintroduced 6, per 10k words 1.74 → 1.69).
  - **Drafting reads the ledger** (v1.97.0): `build_scene_prompt_from_briefs` (write and revise's redraft-from-brief) has an "Established Facts" section from `ledger.drafting_slice`: for the POV, on-stage characters and location, `pronouns` from characters.csv, `fixed` facts before the scene, states entering it (at most `prompts.MAX_STATES_PER_SUBJECT` = 25 each, the rest named), and the scene's own facts ("the brief wins where they differ"). E5 now runs extract phase 4 over its sample first (10 Sonnet calls), so the redraft sees the prose's commitments. **Not like-for-like with the old E5 number:** part of the fall is the redraft being shown facts read off the prose it is judged against, which is the design (a pinned fact should survive a redraft). The character bible is still sent whole: slimming it to fixed facts + voice is author data, left for Ben.
- **Phase 3 (the gate and sequential loop): next** (Next steps 1). Phase 4's rubric was tightened and linked to the registry (F-127/F-128, v1.98.0) and re-scored on *Carol* (below).

**What exists now, for orientation** (contracts in `docs/agent-reference.md`):
- **Ledger:** `ledger.load`/`save(…, command=)` (every save appends to `working/audit-log.csv`); typed views `knowledge_view`/`physical_view` (registry rows only, which briefs reference by id); `active_states`, `established_before`, `scene_order`, `drafting_slice` (a scene's share, for the drafting prompt); `LedgerError` / `NotMigratedError`.
- **Extraction for the gate:** `extract.build_commitments_prompt` / `COMMITMENTS_SCHEMA` / `parse_commitments_response` (the rubric; offered facts in force and the scene's registry facts, `ends`), and `extract.known_for_scene` (what a scene is offered). Phase 4 today is a whole-book batch pass in `cmd_extract._run_phase_4`; the gate needs the same per scene.
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
| 6 Phase 2 | done | #401, #416, #417, #420–#424, #430, #432 |
| 7 Phase 3 | in progress: steps 1–4 done (design, gate, fix + check, gated write) | #436, #437, #439, #443 |

## Next steps, in order (handoff for a new session)

**Before starting:**
- **Environment:** use `~/.venvs/storyforge` (Python 3.12, has pytest). Put it first on `PATH` for the suite, because three `test_illustrate_cmd.py` tests shell out to `python3`, which is 3.9 here. The book repos under `~/Developer` are read-only unless Ben says otherwise: work on copies.
- **Checks:** `PATH=~/.venvs/storyforge/bin:$PATH python -m pytest tests/` (5 to 10 minutes; 7,854 tests at v1.102.0; where the venv is missing, `python3 -m pytest tests/ --no-cov -p no:cacheprovider` runs in about a minute). A stale, gitignored `tests/fixtures/test-project/working/dashboard.html` in a checkout fails `test_score_runs_no_dashboard_step` and `test_renders_no_html_and_commits_nothing`; move it aside and `python evals/run.py` (6 to 10 minutes, replay, no key). Main replays every suite with no errors. The gates that fail are E2 (all three), E7 noise, E8 reintroduced and E9's full-floor and ladder gates (Carol's L5 scene layer, a finding for evals); E4, E5 and E9's phase-5 gates pass (E3: see the open follow-up below).
- **Coordination:** other sessions open Storyforge PRs and claim versions; on 2026-10-30 that was evals-b5 and evals-9a (the F-numbers are storyforge-evals' `FINDINGS.md`, which is in `~/Developer/evals`). Find live ones with ListAgents, agree a version by SendMessage before merging, and say when you touch `cmd_extract.py`, `ledger.py` or `cmd_validate.py`. Eval-only and test-only PRs bump nothing. Never touch `~/Developer/evals` or other sessions' worktrees.
- **Process:** one PR per step, on branch `storyforge/{name}-{timestamp}`. Work in a scratchpad worktree when a suite is running in the main checkout: switching branches under a running suite breaks it. Get one to three general reviewers covering correctness, silent failures, tests and comments. Fix every verified finding before merging (Ben's standing instruction this session), and list them in a PR comment.
- **Spending:** re-records don't need asking (Ben, 2026-10-30: "just do it"); estimate from the `if live` figures or `evals/e8/cli.py plan` and report what was spent.

**Done in v1.98.0: F-127 and F-128** (phase 4; Ben approved).
- **F-127, the rubric:** "locations at scene end" became locations that carry past the scene; it now names what to leave out (staging, set dressing, asides, figurative language read literally, a time the text neither states nor shows), and keeps what a vision or ghost shows as a commitment.
- **F-128, linking:** phase 4 is offered the registry facts in force and those recorded for the scene (`extract.known_for_scene`), each marked state/fixed and registry; past `MAX_KNOWN_COMMITMENTS` the scene's people and place come first, fixed before states. A commitment's `ends` sets `resolves` on this pass's own earlier states. Reported for the author, never applied: prose that disagrees with a registry fact recorded for the same scene, a registry state the prose ends where its `resolves` says otherwise, facts tied to no scene in the run, and the cap.
- **Evals:** E3 recall 0.898 → 0.857 (still ≥ 0.85). E5 23 → 29: the new mismatches are nearly all staging and set dressing (which hand trembles, pen vs pencil), what F-127 stops recording.
- **Carol re-score** (v1.98.0 vs v1.96.1; files in `evals/fixtures/carol-phase4/`, scored by a fresh-context agent the way evals-9a scored v1.96.1, not by Ben):

| | v1.96.1 | v1.98.0 |
|---|---|---|
| phase-4 rows (40 scenes, 28k words) | 548 (19.3 per 1,000 words) | **455 (16.0)**; physical 163 → 98 |
| cost | $2.84 | $2.82 |
| precision (every 7th row) | 52% commitment, 44% incidental, 4% wrong (n=80) | **58%, 42%, 0%** (n=65) |
| restates a migrated row of its scene | 18 of 80 | **10 of 65** |
| recall, phase-4 rows alone | 0.98 | 0.86 (0.91 with partial) |
| recall, ledger (phase 4 + migrated) | 0.98 | **0.975** (78 of 80) |

  - **Reading it:** the linking works (fewer restatements; the two facts phase 4 no longer finds, C50 and C52, are migrated rows it was told not to restate). Wrong rows are gone. **Precision moved little:** 42% is still incidental, mostly description inside visions (the moor, the throne of food, Belle's tableau), momentary staging the rubric names but the model keeps, and narrator asides. A prompt alone doesn't get it much further; the gate (below) is the place for a second check ("does this persist past the scene?"), or a stronger model (the plan says strongest; phase 4 runs on Sonnet).
  - **The 200-fact cap binds early:** 23 of Carol's 40 scenes were offered only 200 of the facts in force (up to 94 left out). On a full novel it binds nearly everywhere. The gate's checker is meant to query the ledger by tool rather than get a bundle (plan §3.2); phase 4's offer should move to that too.
  - **One real disagreement found:** Carol's migrated `fan-died-leaving-nephew-fred` says Fan "died young"; the prose says "She died a woman". The report path worked (phase 4 flagged it, unlinked). The other two flags were the same fact worded differently: noise to cut in the gate.
- **Still open from Phase 2:** fill `characters.csv` `pronouns` (phase 4 output or a hone gap; drafting already shows it). Ben wants phase 4 run on the seven books (and the classics, about $75) now that F-127/F-128 landed; **his call when**, given the precision above.

**1. Phase 3: the gate and sequential loop** (plan §3.2–3.3, §5 Phase 3, decisions 2 and 4; chunk 7). Success: **E4 CP10k and BPS halve** against the last pre-gate numbers at the 5e9bdf39 pin (v1.98.0 baseline: CP10k 14.2, BPS 0.26 = 6 broken promises in 23 scenes; so ≤ 7.1 and ≤ 3 promises), and **E2 precision ≥ 0.8** (today 0 / 0.40 / 0.03 for Carol / drift / validate). Then parallel waves vs sequential on E4; keep parallel only if equal.

Suggested order, one PR each (each with a reviewer, evals re-recorded without asking):
1. **Done: the merge of registry facts and commitments** (`docs/plans/2026-10-30-gate-ledger-design.md`; Ben decided 2026-10-30). Two roles in one ledger: registry rows are the plan's vocabulary (what briefs name), commitments are what the prose said. The gate checks prose against every binding fact in force (both kinds) and the brief's promises (an unestablished `knowledge_out` / `physical_state_out` is a broken promise), halts on a contradiction with a registry fact, writes only commitments (`introduced_by` = the drafting command, so `ledger.is_commitment` replaces the `== COMMITMENTS_PASS` tests), and fills a confirmed registry fact's blank `quote`.
2. **Done (v1.99.0 #437, v1.100.0 #439): the gate as a library.** `api.converse` (tool loop), `ledger.is_commitment` / `fill_quote` (#437); `storyforge/checker.py` and `storyforge/gate.py`, phase 4's per-scene logic shared through `extract.known_for_scene` / `commitment_rows`. **E2 on the checker** (`e2-carol-checker`): precision **0.83** (Phase 3's E2 criterion ≥ 0.8 met; drift check 0), located recall 0.78, code-matched 0.65, no flag on controls or benign edits (after #439's review fixes, $3.92; the first recording, $3.88, had 0.84 / 0.86 / 0.73: one run each, so the gap is partly variance; measure over three runs before tuning). Recall gates (≥ 0.9 per code) still fail; PRM fell to 2 of 5. The gate blocks on unverified findings and unresolved extraction problems; the low-confidence halt isn't wired (phase 4's schema has no confidence; adding it re-records E3 and E5). Not yet measured on the corpus cases (e2-corpus-*), which need the book repos. **Steps 3–4 done (v1.101.0, #443):** `gate.gate_and_fix` (fix once, re-check), `storyforge check` (advisor mode), `write` sequential and gated by default (`--batch` opt-in, every scene listed in `working/gate-pending.csv`; revise's redrafts listed too; its prose passes are still ungated, Phase 4). **E4 through the gated loop** ($13.23): **CP10k 14.2 → 6.0** (target ≤ 7.1 met); **broken promises 6 → 11** (target ≤ 3 missed): 8 are `physical_state_out` items shared-dark's briefs write in words ("no sleep 36h") that no ledger fact names, which the checker listed but never checked. Gate fixed 10 scenes; 3 still failing after the fix (missing-persons: a real REL contradiction, Marie as Claire's mother vs the registry's sister). One run: measure variance before reading small moves. **Next:** brief items in words become promises the checker enforces (in progress), re-record E4; then gate revise's redraft-from-brief, then step 5 (context size). **Ben's decisions for steps 3–4 (2026-10-30):** advisor mode is a new `storyforge check` command (reports, never edits; commits the scene's facts only when clean); when the gate still fails after one fix in `write`, the run stops (prose kept, ledger untouched, exit 1); `write` is sequential and gated by default, batch an explicit `--batch` opt-in with a WARNING that it isn't gated, until the E4 parallel-vs-sequential comparison. Original note: The gate as a library (`storyforge/gate.py`): for one scene, extract (phase 4's prompt per scene, with `_phase4_known`), `audit.halting_conditions` on the proposal, check, then commit the facts through `ledger.save(…, command=)`. **Check** is the new part: a tool-using model call (tools: search the manuscript, query the ledger by subject/scene/type) that returns contradictions with binding facts and broken brief promises, by code. Fail loud: any step that fails halts (no warn-and-continue). Add the plan-contradiction halt that `halting_conditions` can't see. Measure the checker on **E2** (Carol's 37 injected errors, the drift and validate cases) before wiring it in: that is where E2 precision ≥ 0.8 is earned.
3. **Fix**: targeted edits for each flagged contradiction or broken promise, re-check once; advisor mode reports instead of editing (`--advisor` or coaching level; decide).
4. **Wire it into `write`** (`_run_direct_mode`, `_verify_and_commit_scene`): sequential drafting is the default; each scene drafted from its brief, the ledger slice (already in the prompt since v1.97.0) and prior prose per decision 4 (the preceding scene in full and the latest scene of each active thread), then gated, then committed. Batch mode can't gate between scenes; decide whether it stays (plan: delete the open-loop wave scheduler if evals say so). Then revise's redraft-from-brief.
5. **The context-size experiment** (decision 4): that window vs the full manuscript so far with caching, on E4 and cost per scene; the default is whichever is equal or better, a tie going to more context.

E4 (`evals/e4`) drafts with `cmd_write._build_prompt` in direct mode today; it must follow the gated loop once it ships (it is the success measure). Budget: E4 live is $5.29; a gated E4 adds extract + check (+ fix) per scene, likely 2–3×.

**2. #440 / F-130: extraction writes the upper reference layers** (a separate track from Phase 3; plan `docs/plans/2026-10-30-extract-upper-layers.md`, which has the design, the step table, the PR order, the costs and Ben's five decisions). The goal is to go from a finished book to every file a Storyforge project has, describing the book as written, so the classics can validate the scorers. New code goes in `storyforge/extract_describe.py` as extract **phase 5**, with only a thin dispatcher (`_run_phase_5`) in `cmd_extract.py`.
- **Done (v1.101.1 #442, v1.102.0 #444, v1.103.0 #446, v1.104.0 #447, v1.105.0 #448):**
  - The write gate: `write_described`, provenance in `working/extraction-provenance.csv`, and the cell record in `working/extraction-cells.csv`. A file or cell is replaced only while it still holds what phase 5 wrote.
  - **5a** writes `spine.csv` and `architecture.csv`, plus blank scene summaries, `architecture_scene` and a placeholder genre.
  - **5b** writes `themes.csv` and `motif-taxonomy.csv`, plus `theme_threads`. Brief `motifs` become ids, and every description moves to the new free-text brief column `motif_details` (Ben: ids in the brief, nothing lost).
  - **5c** (`run_pitch`) writes `story-summary.md` and `story-architecture.md` from one call. The summary is in `parse_story_summary`'s shape and is checked against the L0–L2 floors with the scorer's own counters (one retry). The architecture's lengths, act shares, POV counts, theme and motif names come from the CSVs; its acts are the book's own (`scenes.csv:act`), while the summary's Act-shape is always three movements (the L2 floor). Live on *Carol* (a clean copy of the E7 run1 reference set, no phase 0 profile): 5a–5c $0.44, 5c $0.15, L0–L4 pass; one bug found and fixed (the model repeated the "Closing image:" label).
  - **5d/5e/5f** (`run_characters`, `run_world`, `run_voice`), one after another: `character-bible.md` (up to 16 characters ranked POV, role, scenes; the ledger's fixed facts with quotes; lines with a speech tag naming the character, via `prose_analysis.dialogue_spans`), `world-bible.md` and `systems-bible.md` (a stub saying why when the book has no formal system), `voice-guide.md` (described from sampled prose with code-measured sentence length, dialogue share and contractions; imperative list items are sent back) and `voice-profile.csv` (elaborate's shape, `banned_words` empty). An unmigrated ledger is described without facts, and said. Live on the E2 *Carol* book (with prose, ledger migrated): 5a–5f $0.99, every step wrote; two bugs fixed (a `supporting` Tiny Tim was ranked below minor characters; `;`-separated location cells were read as one name). The migrated ledger has only `state` rows, so facts in the bibles were tested, not seen live; a phase 4 run first would show them.
  - **5g** (`run_timeline`, no model): `timeline.md` (days, earlier time, frames and visions from the scene CSVs; skipped and said when no scene has a `timeline_day`) and `chapter-map.csv` when the project has none (from `#` headings at the top of chapters' first scenes; `heading=none` with the heading text as `title`, since the heading stays in the prose; a heading equal to the scene's own title isn't a chapter's).
  - **E9** (`evals/suites/e9_reference.py`, recorded $0.82, 7 calls, replays): phase 5 on the E2 *Carol* book (40 scenes with prose, registries migrated). **Passes:** phase 5 wrote, no unfilled reference file (decision 1's exemptions aside), everything it changed is in what it commits, L0–L4 floors (phase 5's own) clean, no schema problem, and a rerun calls no model, writes nothing and changes nothing. **Fails, as findings for storyforge-evals:** two L5 floor checks on Carol's scene layer (phases 1–3; phase 5 only marks status and fills blank summaries): the frame narrator's scene has its POV off stage, and 6 scenes lack `time_of_day` (the frame narrator's also lacks `duration`). So the scene-map rung isn't solid and `status` stops at `scene-map`. Whether L5 should exempt frame narration is a rubric question (the issue's reason for using classics).
  - Fixes on the way:
    - template headers now match `elaborate._FILE_MAP` (and cleanup, migrate-medium, `scenes.py` and the init skill derive from it);
    - phase 3b keeps its scene summaries;
    - extracted scenes get `status=drafted`;
    - `update_scene` keeps unknown columns.
  - #442–#447 had the 5-agent review, with every finding fixed (see their PR comments).
- **Live on *Carol*** (the E7 fixture copy, migrated; $0.79 in all):
  - an 8-event spine, 20 anchors, 6 themes and 26 motifs;
  - the L3/L4 floors pass;
  - no motif or `architecture_scene` validate errors.
- **Next, one PR each** (plan "PRs, in order"):
  1. ~~**5d/5e/5f:**~~ done in #447; ~~**5g** and E9~~ in #448 (notes kept for the record): character bible, world bible (a systems-bible stub when the book has no formal system), voice guide plus `voice-profile.csv`.
     - Describe, never prescribe: elaborate's voice prompt is prescriptive, so don't reuse it.
     - Dialogue samples need a new helper (`prose_analysis.extract_dialogue` joins every line).
     - Books with an unmigrated ledger need a stated fallback.
  2. **Hand-off to storyforge-evals:** gold reference notes per book and a re-score of *Carol* and *Gatsby*. **Posted** on #440 (https://github.com/benjaminsnorris/storyforge/issues/440#issuecomment-6536796072), with E9's L5 findings and the three-act coverage question; #440 stays open until evals reports back.
- **Each step reuses:** `Run`, `_ask` (one retry with the parser's problems), `_gate` (a step writes all its files or none), `_write_all`, `_set_cells` and `_csv_text` (unquoted; model text never goes through a quoting writer). Each step returns `written` / `skipped` / `partial`. Add each new path to `WRITTEN_PATHS`; a test checks every changed file is committed.
- **Deferred:** tell 3b's prompt its summary is kept (≤35 words). That's a prompt change, so it re-records E3; fold it into a recording you're making anyway.

**Open follow-ups, not scheduled:**
- **The gate's persistence check (Ben, 2026-10-30, via evals-b6):** phase 4 is not run on the seven books until the gate has a second check on extracted facts: "does this fact last beyond the scene?" (the Carol re-score's 42% incidental rows). Then run it once. When that check is on main, tell evals (their NEXT step 2, F-127).
- **E3 fails its gate on main since #443:** recall 0.841 < 0.85, with 49 → 44 facts. Replaying on a clean worktree of main gives the same result, so it isn't #442 or #444. Check with whoever owns #443's re-baseline.
- **F-130 (evals-8b; Ben approved): extraction never fills the reference docs.** *Next steps 2 (#440): phase 5 is done (5a–5g, E9); the hand-off to storyforge-evals remains.* On all eight classics `story-architecture.md`, `world-bible.md`, `voice-guide.md`, `character-bible.md`, `story-summary.md` (and `spine.csv`, `themes.csv`, `motif-taxonomy.csv`) are untouched templates, yet score's character and narrative passes and `scoring_bible.py` read them. evals-8b is adding the guard (a file identical to its template counts as absent; `cmd_score.py`, `scoring_bible.py`, about v1.98.1). **The real fix is ours:** an extract phase that writes those docs from the Phase 0 profile (`working/extraction-profile.json`: narrative_mode, act_structure, major_threads, central_conflict, protagonist_arc, tone, key_locations) and the CSVs. It fits the plan's "bible = fixed facts + voice" (the bible could be generated from the ledger's `fixed` facts). Also check `build_shared_context`, which sends `character-bible.md` and `world-bible.md` to every drafting call: a template there is noise in E4, E5 and E8.
- **The summary's three acts vs a book's own acts:** 5c's `story-summary.md` Act-shape is always `### Act 1–3` (the L2 floor), and `scoring_coverage._coverage_acts_to_spine` wants a spine row with `act` 1, 2 and 3. That holds on *Carol*, but a book whose `scenes.csv:act` values aren't 1–3 (five staves numbered 1–5, `Part One`) fails coverage although L0–L4 pass. Whether L2 should follow the book's own division is a rubric question, not a 5c fix.
- **The books' validate findings** are the author's. Thornwall's Garren (16 states) and governor's `governor` (9) have no `characters.csv` entry. Briefs name physical states the ledger doesn't hold, in the hundreds for shared-dark, governor and meridian-line. Understory has 16 cells with parenthetical text that `migrate` step 5 left for hand edits.
- **Rejected facts are still used** by consumers, because the views don't filter on `status`. This is Phase 4's reject flow.
- **F-123 limitation:** a hand-added fact that no brief's `knowledge_out` lists isn't offered to later 3b scenes.
- **Export bundle size:** governor's is 46 MB, mostly its score rationale CSV, which `dashboard_data` repeats.
- **Phase 4 model:** it runs on the `evaluation` tier (Sonnet). The plan says "strongest model", but Sonnet passes the gate; switch only on evidence.
- **From before today, still open:** other writers of briefs and intent don't use `brief_names`' check (#393); `scoring_story_power` hasn't been reviewed for warn-and-continue; measure E8 over three runs before Phase 4 gates on it; replaying the 10 YAML-era E8 trees is Ben's call.

## 2026-10-30 late (storyforge-25)

Ben: "pick up and carry on"; re-records approved without asking. Two PRs: drafting from the ledger (#430, v1.97.0, Phase 2's last criterion) and F-127/F-128 (v1.98.0). #430's reviewer: 3 high, 5 medium, 1 low, all fixed except phase 4's missing `resolves` (done in F-127 as `ends`). F-127/F-128's reviewer: 3 high, 3 medium, 2 low, all fixed. Spend: $11.52 for #430 (E5 $2.61 with phase 4, E4 $5.29, E8 $3.62), about $5.5 for F-127/F-128 (E3 $2.34, E5 $2.24, a stopped recording), $2.82 for the Carol phase 4 re-run. evals-9a merged 1.96.1–1.96.3 (F-125, F-119, F-126) in the same window.

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
| `e3-extraction` | extraction captures the fact behind each E1 error | **0.857** with phase 4's tightened rubric (v1.98.0; 0.898 at v1.96.0; 0.29 with 3b/3c alone); 0.98 with partial | ≥ 0.85 (passes) |
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

# Storyforge agent reference

Lookup tables and subsystem rules moved out of `CLAUDE.md` on 2026-10-28 so that file stays short. `CLAUDE.md` says when to read each section here. Design rationale and bug history are in `docs/history.md`.

## Shared modules

| Module | Use for |
|---|---|
| `common` | `detect_project_root`, `log`, `read_yaml_field(field, project_dir)`, `parse_yaml_scalar`, `yaml_single_quote`, `yaml_scalar_issue`, `detect_newline`, `update_artifact_entry`, `select_model`, `select_revision_model`, `get_coaching_level`, `check_chapter_map_freshness`, `get_plugin_dir`, `extract_craft_sections`, `install_signal_handlers`, `csv_safe`, `is_unfilled_template` (a reference doc still its template: readers skip it, extract phase 5 may fill it), pipeline manifest (`get_current_cycle`, `start_new_cycle`, `update_cycle_field`) |
| `git` | `create_branch`, `ensure_branch_pushed`, `create_draft_pr`, `update_pr_task`, `commit_and_push`, `run_review_phase` |
| `cli` | `base_parser`, `add_scene_filter_args`, `resolve_filter_args` |
| `runner` | `run_parallel(items, fn, max_workers, label)` returns `{item: result-or-Exception}` — check for exceptions; `run_batched`; `HealingZone` |
| `api` | `invoke_api` (text, `''` on failure), `invoke`, `invoke_to_file`, `extract_text`, `submit_batch` / `poll_batch` / `download_batch_results` (refused, cut-off and errored items are marked `fail` with no `.txt` and a WARNING; `keep_incomplete=True` keeps refused/cut-off replies for a caller that checks `stop_problem` itself). Prose calls pass `fallback=True` (server-side refusal fallback, WARNING naming the model that wrote the reply; not on the Batches API); `fallback_model(response)` names that model. `converse(prompt, model, tools, handlers, output_schema=, log_file=, max_turns=)` is the tool-using loop (Phase 3's checker): strict tools, append-only history with thinking blocks passed back, auto-cached; returns a `ToolRun` (`response`, `responses`, `calls`, summed `usage`, `cost(model)`); every exception it raises carries the exchange so far as `.run`. A stop other than end_turn/max_tokens/stop_sequence with no tool call raises `ToolLoopError`. A handler raises `ToolInputError` for input the model should correct (sent back as an error result); any other exception propagates; `ToolLoopError` past `max_turns` |
| `costs` | `calculate_cost`, `estimate_cost`, `check_threshold`, `log_operation`, `print_summary` |
| `scene_filter` | `build_scene_list`, `apply_scene_filter` |
| `csv_cli` | `get_field`, `get_row`, `get_column`, `list_ids`, `update_field`, `append_row` |
| `history` | `append_cycle`, `get_scene_history`, `detect_stalls`, `detect_regressions` |
| `ledger` | `reference/commitments.csv` (plan §3.1), the one store of knowledge facts and physical states (it replaced `knowledge.csv` and `physical-states.csv`). `load(project_dir)` / `load_from(ref_dir)` raise `NotMigratedError` while either old file is on disk, and `LedgerError` (its parent) when `file_problems` finds a header that isn't exactly `COLUMNS`, a row with the wrong cell count, a blank id or a duplicate id, rather than silently fixing them on the next write; commands call `exit_if_not_migrated(project_dir)` first, and the dispatcher turns a late `NotMigratedError` into exit 1. `save(project_dir, rows, command=)` / `save_to(ref_dir, rows, command=)`: `command` (the writer's name) is required, since every write is audit-logged (see `audit`); `write_ledger` is the bare file writer and logs nothing. Typed views in the old files' shapes: `knowledge_view` (id/name/aliases/category/origin = scene) and `physical_view` (id/character = subject id/description/category/acquired/resolves/action_gating), `read_view(ref_dir, type)`, `view_map`, `alias_map`. Write a view back with `write_view(ref_dir, type, rows, origin=, introduced_by=, command=None)` (`replace_view`; the audit entries carry `command`, defaulting to `introduced_by`): only the cells the writer changed are rewritten; every other row goes back byte-identical. A physical view's `character` is the subject id, or for a subject the migration couldn't resolve (left blank) the name it kept in `aliases`; validate reports such rows. Never write the old files. Also `read_ledger` / `write_ledger` (LF, prose through `csv_safe`), `validate_ledger`, `scene_order`, `active_states(rows, scene_id, order, subject=, entering=)` (derived per-character state), `established_before` (facts from earlier scenes only, F-123: extract's phase 3b offers a scene only these, plus backstory), `drafting_slice(rows, scene_id, order, subjects)` (a scene's share for drafting: subjects' `fixed` facts before it and states entering it, the scene's own facts, and `unplaced` facts whose scene id isn't a scene; `prompts._established_facts_block` renders it as the drafting prompt's "Established Facts", with characters.csv `pronouns` and at most `MAX_STATES_PER_SUBJECT` states each), `is_commitment(row)` (a commitment, what the prose said, is `introduced_by` in `COMMITMENT_WRITERS`: phase 4's `commitments` and the gate's `draft`/`redraft`/`revise`/`advisor`; anything else, blank included, is a registry fact that briefs name and the views carry; `docs/plans/2026-10-30-gate-ledger-design.md`), `fill_quote(rows, id, quote)` (sets a binding knowledge/physical registry fact's blank `quote`, returns False when one is there; the gate's only change to a registry row); `replace_view`/`write_view` refuse a commitment writer's name, `exit_if_unordered(project_dir)` (write and revise stop up front on a scene without a numeric `seq`), and the migration (`migrate_registries`, `round_trip_differences`, and `migrate_files`, the whole step `storyforge migrate` runs as step 4). `evals/ledger_check.py` runs the migration on copies of the book repos; `evals/harness.migrate_tree` migrates every eval tree before Storyforge reads it |
| `audit` | The audit log, digest and immediate tier (plan decision 2). `ledger.save_to` (so `save`, `write_view`) diffs the ledger file before and after each write and appends one entry per added/changed/removed fact to `working/audit-log.csv` (`record`, `diff_entries`); `migrate_files` appends one `migrated` summary entry instead of one per row. A log that can't be written is a WARNING naming the file and the lost fact ids; the ledger write stands (the digest reads the ledger's `reviewed`, never the log). Edits that bypass the writers (by hand, or a skill editing commitments.csv) are caught from `working/.audit-snapshot.csv`, the ledger as last logged: `log_hand_edits` logs the snapshot-to-disk difference as `command=hand-edit` before every logged save and on every `storyforge audit` run. The snapshot is committed with the log; a project without one starts one and logs nothing. Digest: `select(rows, project_dir, Scope, order)`, `group`, `tier_of`; `mark(rows, ids, 'seen'/'rejected')` stamps `reviewed` `seen:<date>` / `rejected:<date>` (rejected also sets `status=rejected`); `leaning_scenes` (briefs naming a fact). `halting_conditions(proposed, rows)` returns the `Halt`s Phase 3's gate stops on: `supersedes-fixed`, `changes-fixed`, `low-confidence` (a `confidence` key on the proposal, not a ledger column; phase 4's schema has none yet); a contradiction with the plan is a gate checker finding |
| `checker` | The gate's check of one scene (plan §3.2 step 2): `check_scene(project_dir, scene_id, prose=, promises=True, model=, log_file=)` → `CheckResult` (`findings`, `unverified`, `kept`, `kept_unverified`, `run`). A tool-using call (`api.converse`; tools `search_manuscript`, `read_scene`, `query_ledger`) on the `checking` tier (opus), with the bibles that have the author's text (`REFERENCE_DOCS`, `reference_docs`; a template copy is left out, F-130) whole in its system prompt, reports contradictions with other scenes, a bible (`established_scene` the file name, quote verified in it) or binding ledger facts, by E1/E2 code (`CODE_OF_TYPE`), and with `promises` the brief's broken promises (outcome, key_actions, key_dialogue, `knowledge_out`/`physical_state_out` registry facts) plus the registry facts the prose establishes (`kept`). Every quote is checked against the text it names; a finding that fails is `unverified`, returned apart, never dropped. Refusal, cut-off, off-schema or endless tool loop raise `CheckError`. Measured on `e2-carol-checker` |
| `persistence` | The second question on extracted facts: does it last beyond the scene? `judge(scene_id, prose, found, model=, log_file=)` → `Verdict` (`kept`, `dropped` as (entry, why), `asked`, `exempt`) over phase 4's parsed reply, before it becomes rows; one structured call (`SCHEMA`, numbered items) on the caller's model. An entry that `supersedes` or `ends` another is kept without asking. Fails loud (`PersistenceError`): a refusal, a cut-off reply, or verdicts that don't answer every item exactly once; nothing is dropped by default. Called by extract phase 4 (dropped facts logged per scene and counted) and the gate (`GateResult.dropped`, a NOTE in `report_lines`) |
| `gate` | `gate_scene(project_dir, scene_id, command=, prose=None, log_dir=)` → `GateResult`: extract the scene's commitments (phase 4's rubric via `extract.known_for_scene` / `commitment_rows`; facts the persistence check drops are `dropped`, reported, never committed), halt (`audit.halting_conditions`; extraction's `supersedes`/`ends` on a registry fact are not applied but reported, `REPORTED`: the checker judges contradictions with the plan), check (`checker`), and commit only when `passed` (no halts, no findings): the scene's earlier commitments are replaced, rows carry `introduced_by=command` (`GATE_COMMANDS`: draft/redraft/revise/advisor), kept promises fill registry quotes, saved through `ledger.save`. A step that can't finish raises `GateError` and writes nothing; so does a later fact leaning on a commitment the scene would replace (Phase 4's re-check). Fixing is the caller's: `gate_and_fix` gates, fixes once (`fix_scene`: one call on the `revision` tier returning `find`/`replace` edits for the halts, findings and unverified findings, the last marked UNVERIFIED; each `find` exactly once, no overlaps, else `GateError`) and gates the fixed prose. A fix with no edits is not re-gated (the first verdict stands); extraction-only failures are re-gated without one. The caller writes `.prose` at once (the ledger is committed with its quotes when `.result.passed`); a `GateError` from the fix or re-check carries `.first`. A scene starting with frontmatter is refused. `report_lines(result)` is the verdict as one-line strings. `working/gate-pending.csv` (`pending`, `mark_pending`, `clear_pending`; a commit clears its scene) lists scenes whose prose didn't pass; `write` won't draft past one |
| `extract_describe` | Extract phase 5 (#440; plan `docs/plans/2026-10-30-extract-upper-layers.md`). `write_described(project_dir, rel, content, step=, version=, force=, provenance=)` → `Verdict` is the only way phase 5 writes: `_POLICY` decides per `FileState` (missing/empty/header-only/template are free, `extracted` only under `--force`, never `edited`/`author`/`symlink`/`unreadable`/`unverified`), then it writes and records the hash in `working/extraction-provenance.csv` (`read_provenance` → rows, `{}`, or None when unusable; `ProvenanceError` rather than rewriting an unusable record). `scene_table(ref_dir)` is the shared evidence; `run_structure` (5a), `run_themes` (5b) and `run_pitch` (5c: `story-summary.md` in `parse_story_summary`'s shape, checked against the L0–L2 floors with the scorer's own counters, and `story-architecture.md`, whose lengths, POV counts, themes and motif names come from the CSVs; a step stopped part-way stops the steps after it), `run_characters` (5d: `character-bible.md`; characters ranked POV, role, scenes; facts are the ledger's binding `fixed` trait/relationship/physical rows, reported as absent when there is no ledger or it isn't migrated or can't be read; sample lines are quotes with a speech tag naming the character against the quote, via `prose_analysis.dialogue_spans`; an unreadable scene file or registry, or one with no `id`/`name` column, stops the step naming it; provenance headers name only the sources used), `run_world` (5e: `world-bible.md` and `systems-bible.md`, a stub saying why when the book has no formal system), `run_voice` (5f: `voice-guide.md` with code-measured sentence length, dialogue share and contractions, with each measure labelled by what it covers and none taken under 1,000 words, dialogue not measured when speech is in single quotes, and `voice-profile.csv` in `schema.VOICE_PROFILE_COLUMNS` with `banned_words` empty; list items that read as instructions are sent back; skipped when no scene has prose) and `run_timeline` (5g, no model: `timeline.md` from the scene CSVs' timeline columns, with earlier time, frames and visions described, never flagged, and the profile's `timeline_span`; `chapter-map.csv` from the `#` headings at the top of chapters' first scenes, `heading=none` so the book's own line stays the heading, and none written when a scene has no prose or a heading is also its scene's title; `timeline_plan` is what the dry run prints) are the steps, each returning `written`/`skipped`/`partial`. Phase 5 skips graphic-novel projects. Eval: E9 (`evals/suites/e9_reference.py`). Model text reaches CSVs only through `_csv_text` (unquoted, `csv_safe`). Scene-CSV cells go through `_set_cells`, which replaces a filled cell only while it still holds what phase 5 wrote (`working/extraction-cells.csv`), so `--force` never overwrites an author's edit and never leaves a regenerated file's old ids behind. 5b splits each brief's motifs: `motifs` becomes registry ids (so `validate` passes), and every description, including images that recur nowhere else, moves to the new free-text `motif_details` column, which drafting reads beside it |
| `brief_names` | `invented_names(fields, known_text)` (capitalized words a rewrite brings in that the book never uses), `reference_text(project_dir, exclude=...)` (reference docs and registries, without the files model rewrites write). Checked by revise's upstream brief fix and `hone`'s brief and intent rewrites (`hone._apply_checked_rewrites`, which trusts neither `scene-briefs.csv` nor `scene-intent.csv`); other writers of those files are not checked yet |

## Skills

Skills live in `skills/{name}/SKILL.md` with `name` + `description` frontmatter. Required sections: **Locating the Storyforge Plugin**, **Read Project State**, **Determine Mode**, **Commit After Every Deliverable** (`git add -A && git commit -m "..." && git push`), **Coaching Level Behavior**.

When a skill delegates to a command, offer two options and wait for the author's choice:
- **Option A: Run it here** (note that commands invoking Claude require unsetting `CLAUDECODE`).
- **Option B: Run it yourself** — give `cd [project_dir] && [plugin_path]/storyforge thing [flags]` and stop.

Coaching levels: **full** — creative partner, recommends and offers to run. **coach** — asks guiding questions, does no creative work. **strict** — reports data and commands only; the author decides everything.

## Project Data

CSVs are pipe-delimited (`|`), arrays use `;`, header row first, no quoting, empty field = nothing between delimiters. Semicolons inside content become commas or `\;`.

| File | Holds |
|---|---|
| `reference/story-summary.md` | `## Logline` (canonical; `storyforge.yaml:project.logline` is deprecated), `## Synopsis`, `## Act-shape` (`### Act N`), `## Theme` |
| `reference/outline.md` | Read-only render of spine/architecture/scenes `summary` columns; regenerated by sync |
| `reference/spine.csv` | 5–10 irreducible events (id, seq, title, summary, function, act) |
| `reference/architecture.csv` | 15–25 anchor scenes; `spine_event` required, refs `spine.csv:id` |
| `reference/scenes.csv` | Scene identity. `id` is a permanent 3–5 word event slug, never positional. `act` structural, `part` physical. Optional `architecture_scene` |
| `reference/scene-intent.csv` | Function, value shift, characters, MICE threads, `theme_threads` (refs `themes.csv`) |
| `reference/scene-briefs.csv` | Drafting contracts (goal, conflict, outcome, crisis, decision, knowledge in/out, key actions/dialogue, continuity_deps, …) |
| `reference/voice-profile.csv` | `_project` row + per-character voice rows |
| `reference/themes.csv`, `characters.csv`, `locations.csv`, `motif-taxonomy.csv`, `values.csv`, `mice-threads.csv` | Registries. `characters.csv` may carry `pronouns` (plan §3.1; optional, nothing fills it yet) |
| `reference/commitments.csv` | The commitments ledger (`storyforge.ledger`): every knowledge fact (`type=knowledge`) and physical state (`type=physical`), joined to scenes by `scene_id`. Replaced `knowledge.csv` and `physical-states.csv`; `storyforge migrate` moves those in and deletes them, and every command that reads the facts stops until it has. Briefs' `knowledge_in/out` and `physical_state_in/out` hold its ids |
| `reference/chapter-map.csv` | Chapter-to-scene mapping |
| `reference/illustration-plan.csv`, `reference/visual-state.csv`, `reference/canon/` | Interior illustrations (see below) |
| `working/scores/score-history.csv` | Per-scene, per-principle scores by cycle |
| `working/scoring-overrides.csv`, `working/scoring-verdicts.csv` | Author-accepted findings; boundary-diff verdicts |
| `working/annotations.csv` | Bookshelf reader annotations |
| `working/craft-weights.csv` | Principle weights (keyed by `principle`) |
| `working/costs/ledger.csv` | Per-invocation costs |
| `working/audit-log.csv` | Append-only audit log of the ledger (`storyforge.audit`): `timestamp\|scene_id\|fact_id\|change\|command\|type\|subject\|columns\|statement`, LF, cells through `csv_safe`. `change`: added, changed (`columns` names what), removed, superseded, rejected, reviewed (an audit mark), migrated (one summary entry for `storyforge migrate`). `command`: the row's `introduced_by` for an added fact, else the writer. Written only by ledger writes (and `hand-edit` entries for changes made outside them); commit it with `reference/commitments.csv` and `working/.audit-snapshot.csv` |
| `working/.audit-snapshot.csv` | The ledger as the audit log last recorded it (`storyforge.audit`), so a hand edit to commitments.csv is logged as `hand-edit`. Committed; never edit it |
| `working/export/bundle.json` | `storyforge export`'s output (see Export bundle) |

Scene files (`scenes/{id}.md`) are pure prose — **no frontmatter**. Filename is the scene ID; all metadata lives in CSVs.

## Dashboard data (`dashboard_data`, schema version 1)

Storyforge defines and sends the dashboard's data; Bookshelf renders it (benjaminsnorris/bookshelf#30; Bookshelf's copy of the contract is `src/lib/dashboard/schema.ts`). `visualize.load_dashboard_data` builds it, `publish` sends it, and `storyforge visualize` writes it to `working/dashboard-data.json`.

- `schema_version`: `1` (`visualize.DASHBOARD_SCHEMA_VERSION`). Bookshelf reads a missing one as 1. It is a major version. Adding a list or a CSV column doesn't change it. Renaming or removing a key, or changing a value's type, bumps it, and Bookshelf must support the new version first, since it refuses one it can't draw. `tests/test_dashboard_data.py` pins the keys.
- `project`: `title`, `genre`, `phase`, `scene_count`, `total_words`, `target_words`, `generated`. All strings.
- One list of rows per section. Each row is a CSV record, every value a string, with header names as keys. Values are not escaped; the renderer escapes them.

| Key | Rows from |
|---|---|
| `scenes` | `reference/scenes.csv`. `location` may hold several places joined with `;`, and the renderer splits it. `act` is structural, `part` the book's physical division. A `setting` column is copied to `location` when there is no `location` column |
| `intents`, `briefs` | `reference/scene-intent.csv`, `reference/scene-briefs.csv`, in `scenes.csv` `seq` order |
| `characters`, `motif_taxonomy`, `locations`, `values`, `mice_threads` | the matching `reference/*.csv` registry |
| `knowledge` | the ledger's knowledge facts in `knowledge.csv`'s old columns (`ledger.knowledge_view`: id, name, aliases, category, origin). `origin` is the fact's scene id; a backstory fact (true before scene 1) has an empty `origin`, where `knowledge.csv` said `backstory` (the migration blanks it) |
| `scores`, `scene_rationales`, `narrative_scores`, `narrative_rationales`, `act_scores`, `act_rationales`, `character_scores`, `character_rationales`, `genre_scores`, `genre_rationales`, `fidelity_scores`, `fidelity_rationales` | `working/scores/latest/*.csv` |
| `repetition_scores` | `working/scores/latest/repetition-latest.csv` |
| `structural_scores` | `working/scores/structural-latest.csv` |
| `weights` | `working/craft-weights.csv` |
| `brief_quality` | computed (`hone` brief issues and gaps): `scene_id`, `field` and `issue` are strings; the counts (`beat_count`, `target_words`, `char_count`, `max_chars`, `abstract_count`, `concrete_count`) may be numbers |

A missing CSV gives an empty list.

## Export bundle (`storyforge export`, schema version 1)

`export.build_bundle(project_dir)` builds one JSON bundle of the book's structured state (plan §3.5); `storyforge export` writes it to `working/export/bundle.json` (`--output PATH`, `--stdout`), as UTF-8 with sorted keys and LF. Storygild and Bookshelf read the bundle and pin its `schema_version`. No API calls. An unmigrated project or a malformed ledger exits 1 (`ledger.LedgerError`). `tests/test_export.py` pins the keys; `evals/export_check.py` exports a copy of each book and checks the round trip.

- `schema_version`: `1` (`export.SCHEMA_VERSION`), a major version. Adding a key, a table or a table kind doesn't change it. Renaming or removing a key, or changing a value's type, bumps it, in the same commit, with the tests.
- `storyforge_version`: the plugin version that wrote it (`.claude-plugin/plugin.json`).
- `project`: `title`, `genre`, `medium`, `phase` from `storyforge.yaml`. All strings.
- `score_cycle`: the latest complete score cycle (`project.latest_scores`) relative to the project, or `null`.
- `tables`: `{relative path: table}`. A table is `kind`, `header` (list of strings), `rows` (lists of strings), `line_ending` (`"\n"` or `"\r\n"`), `final_newline`, `bom`. Cells are exactly the text between `|`s, unstripped; blank lines are rows of one empty cell. `export.tables_from_bundle(bundle)` returns `{path: text}`, and writing each text as UTF-8 with `newline=''` gives back the original bytes. A file with mixed line endings is split on LF (its CRs stay in cells), and a CRLF file with a CR that doesn't end a line keeps it inside its cell; both are named in `warnings`. The bundle is written atomically (a temporary file beside it, then a rename); an unwritable output path exits 1.

| `kind` | Files |
|---|---|
| `reference` | every `reference/*.csv`: scenes, intent, briefs, registries, `commitments.csv`, chapter map, voice profile, spine, architecture, visual state. The timeline calendar is `scenes.csv`'s `timeline_day` / `time_mode` |
| `scores` | the CSVs in `score_cycle`, and `working/scores/structural-latest.csv` |
| `timeline` | `working/timeline*.csv` (the timeline's stored cues) |
| `audit` | **provisional**: `working/audit*.csv` and the CSVs under `working/audit/`, as raw rows. Empty until the audit log (`working/audit-log.csv`, another PR) exists; it fills from then with no code change. Other files under `working/audit/` are named in `warnings` |

- `dashboard_data`: `visualize.load_dashboard_data`'s output, unchanged, with its own `schema_version` (see Dashboard data); `null`, with a warning, if it couldn't be built.
- `warnings`: every file the bundle meant to carry and couldn't (unreadable, not UTF-8), and anything a consumer should know about a table. Empty means everything was read.

Left out: scene prose and manuscripts (`assemble` / `produce`) and score history before the latest cycle. **Eval results are not in a book's bundle**, though plan §3.5 lists them: evals measure Storyforge, not the book, and their results belong to the Storyforge repo (`evals/results/`).

## Architecture

- `evals/` — eval harness and suites
- `scripts/lib/python/storyforge/` — commands (`cmd_*.py`), shared infrastructure, domain modules (scoring, prompts, extraction, illustrations, …)
- `skills/` — interactive skills; `scripts/prompts/` — prompt templates; `references/` — craft engine, rubrics, schemas; `templates/` — project scaffolding; `docs/` — GitHub Pages + design docs

Commands (`storyforge <name>`; full flag notes in `docs/history.md`):

| Command | Purpose |
|---|---|
| `status` | Deterministic next-step verdict; `--json` for tooling (forge routes on `next.stage`) |
| `audit` | Ledger digest (plan decision 2): binding facts with blank `reviewed`, tiered fixed → relationship/knowledge → physical → other, grouped by subject. Default is per act: the earliest act with an unreviewed fact, plus facts with no scene. Scopes `--act`, `--character` (subject or `known_by`), `--scenes A..B` (reading order), `--thread` (facts from scenes whose `mice_threads` carry it: threads map to scenes, not facts), `--all`; `--include-reviewed`, `--include-migrated` (migrated facts are left out by default, said in a note). Acts come from scenes.csv `act`, else `part` (said in a note). A scope naming a missing scene, character, thread or act exits 1. `--mark seen\|rejected IDS\|all` writes through the ledger and commits (a failed commit exits 1); `all` marks exactly what the same scope lists, and the listing's hint is that command; explicit ids ignore scope flags (WARNING). Re-marking is a no-op; a superseded fact can't be rejected. `--dry-run`; `--json` (stdout is the JSON only, logs go to stderr) |
| `check` | Advisor mode (plan §3.2): the gate on prose already written, never editing it. Named scenes are sorted into reading order and each goes through `gate.gate_scene(command='advisor')`; a pass commits its commitments (and fills promised registry quotes). The first scene that fails or can't be checked stops the run: it goes into `working/gate-pending.csv` and the rest are listed as not checked. Report in `working/check-report.md` (`gate.report_lines`), committed with the ledger. Exit 1 on a failure, an id that isn't a checkable scene (unknown, cut or merged), or a failed commit. Scenes by id, range, `--scenes`, `--act`, `--from-seq` |
| `elaborate` | Stages: spine / architecture / map / briefs / page-architecture / prompts |
| `propose-summaries` | Draft `summary` cells from the level above (`--level 3/4/5`) |
| `write` | Draft scenes from their briefs, one at a time in reading order, each with earlier prose after the shared context in the system prompt (`--prior-prose` / `drafting.prior_prose`: `window`, the default, the preceding scene and the latest scene of each MICE thread the scene carries; `full`, the manuscript so far, cached as it grows; `none`; `prompts.prior_prose_blocks`, also used by revise's redraft-from-brief and E4/E8; batch and interactive send none), each gated (`gate.gate_and_fix`: extract, check, fix once, re-check) before the next. A scene that still fails is committed for the author, listed in `working/gate-pending.csv`, and stops the run; `write` stops at a bad reply too, refuses to draft past a pending scene, and refuses (before spending) a redraft whose commitments later facts lean on. `--batch`: the Batch API, ungated, every scene listed pending (WARNING). Coaching coach/strict write briefs or constraints, not prose, and are not gated |
| `evaluate` | 6-evaluator panel + synthesis |
| `score` | 25-principle craft + fidelity scoring; also elaboration checks (`--level`, `--compare`, `--drift`, `--boundary`, `--bible-consistency`, `--story-power`) |
| `revise` | Revision passes; `--polish`, `--polish --loop`, `--naturalness`. A redraft from rewritten briefs (`_redraft_from_briefs`, `_redraft_scenes`) goes in reading order through `write`'s gate (`cmd_write._gate_drafted_scene`) and, like `write`, stops at a scene the gate does not pass or whose commitments later facts lean on; `RedraftError` names that scene and those not reached. Prose passes are not gated yet (Phase 4) |
| `hone` (`reconcile` alias) | CSV data quality; `--diagnose`, `--loop`, `--findings` |
| `validate` | Structural/schema/illustration/canon validation; exits 1 on failures |
| `extract` | Structural data from prose. Phases 0–4 build the scene layer; `--phase 5` (also the last step of a full run) describes the layers above it: spine, architecture, themes, motifs, story summary, story architecture, character, world and systems bibles, voice guide and profile, timeline, chapter map (`extract_describe`) |
| `enrich`, `timeline`, `repetition` | Metadata enrichment, timeline, cross-chapter repetition |
| `cleanup` | Project health; `--scenes`, `--csv`, `--dry-run` |
| `assemble` | Chapters + epub/PDF/HTML (GN: artist handoff bundle) |
| `publish`, `annotations`, `visualize` | Bookshelf publish, reader annotations, dashboard data (see Dashboard data) |
| `export` | The book's structured state as one versioned JSON bundle (see Export bundle) |
| `cover`, `illustrate` | Cover; interior illustrations (prose only) |
| `scenes-setup` (`scenes`), `scenes-export`, `scenes-import`, `sync` | Scene files and CSV ↔ `scenes-review.md` round-trip |
| `migrate`, `migrate-medium` | Idempotent project migrations; novel ↔ graphic-novel conversion |
| `review` | Pipeline review |

Skills: `forge` (hub), `elaborate`, `extract`, `revise`, `score`, `hone`, `cleanup`, `publish`, `produce`, `init`, `cover`, `illustrate`, `title`, `press-kit`, `migrate-medium`, `script-package`. `forge`, `elaborate`, `hone`, `init` adapt to `project.medium`.

Pipeline: Seed → Pitch (Logline → Synopsis → Act-shape) → Spine → Architecture → Scene Map → Briefs → Validate → Draft → Evaluate → Polish → Produce. Evaluation findings route upstream to a `fix_location` (brief/intent/structural/craft) — fix in CSVs before prose.

## Graphic Novel Mode

`project.medium: graphic-novel`. Most commands route to `*_gn` modules (`write`, `score`, `evaluate`, `revise`, `extract`); `assemble` routes to `cmd_script_package`. `publish` and `annotations` are not yet supported (#215). Per-page files live in `pages/<prefix>-pN.md`; renders in `manuscript/pages/<page_id>.png`. Image prompts target GPT Image 2: one 5-section prompt per page, identical character-anchor strings, positive framing, explicit portrait orientation. Spec: `docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md`.

## Interior Illustrations (prose books)

`storyforge illustrate` (refuses GN projects). Invariants that must not break:
- **Never add anything to `content_html`.** Bookshelf derives highlight offsets from visible text; the marker is stripped and emitted as `illustrations: [{key, after_paragraph}]`. `tests/test_illustrate_cmd.py` asserts byte-identity — don't weaken it. `after_paragraph` counts top-level `<p>` only.
- **Markers (`![[illus:id]]`) are never prose** — strip them (`illustrations.strip_markers`) before scoring, word counts, or analysis.
- **Canon anchors are verbatim strings** (`## Embeddable block` in `reference/canon/**`), reused identically in every prompt; never revise one a rendered image used.
- **Plan `status` only moves forward**; staleness is a stated reason (`stale_render_reason`), never a demotion.
- **The packet (`manuscript/illustration-packet/`) is a render** — regenerated wholesale, never hand-edited. Prompt bodies live in `reference/illustration-prompts/`.
- **No other illustration id ever reaches the image model** (`packet.RowContrast.for_model`).
- Publishing assets must always include the cover (`assembly.require_cover_asset`).
- Declare `IllustrationFindingKind` names bare; `cmd_cleanup` adds the `illus_` prefix.

## Commit Message Prefixes
Plugin work: `Add` / `Update` / `Fix` / `Remove`, and `Bump version to X.Y.Z`. Book work: `Audit:`, `Draft scene:`, `Develop:`, `Voice:`, `Evaluate:`, `Revision:`, `Produce:`, `Review:`, `Title:`, `Press kit:`, `Cover:`, `Elaborate:`, `Extract:`, `Score:`, `Polish:`, `Enrich:`, `Visualize:`.

## PR Review Workflow

When asked for "the 5-agent review", or after creating a PR, launch all five in parallel in the background: `pr-review-toolkit:code-reviewer`, `pr-test-analyzer`, `silent-failure-hunter`, `type-design-analyzer`, `comment-analyzer`. Give each a substantive prompt naming the PR's risk areas and relevant conventions. When all report, consolidate one deduplicated punch list (CRITICAL / HIGH / IMPORTANT / SUGGESTIONS), verify each finding against the code, note false positives, and wait for "fix all of them in logical commits". Fix in ~4–6 commits (critical bugs, types, silent failures + comments, test gaps, version bump), each with regression tests, finding IDs (CR-/SF-/TD-/T-/C-N) in the message, and an immediate push.

# Storyforge Plugin Development

## Git Rules — MANDATORY
- **NEVER commit to main.** All changes must be on a feature branch.
  - If on `main`: create a `storyforge/{command}-{timestamp}` branch first.
  - If on any non-main branch: stay on it — do not create a new branch.
- **ALWAYS commit and push after every change.** No exceptions.
- Never tell the user something is "done" without having committed and pushed.
- If you make multiple related changes, commit them in logical groups — but do it immediately, not at the end of the conversation.
- Every commit must be pushed before moving on to the next task.
- Commit any uncommitted files before creating branches or PRs.

## Version File
- `.claude-plugin/plugin.json` — **ALWAYS bump `version` on every release commit.**
- Minor version (0.X.0) for new features. Patch version (0.0.X) for fixes.

## Script Standards

All autonomous scripts are Python modules in `scripts/lib/python/storyforge/cmd_*.py`.
The `./storyforge` runner dispatches to these modules via `storyforge.__main__`.

### Python Conventions
- Each command module has `parse_args(argv)` and `main(argv=None)`
- Import shared utilities from `storyforge.common`, `storyforge.git`, `storyforge.cli`, `storyforge.runner`
- Use `argparse` for CLI flags (matching the original interface)
- Use `storyforge.runner` for parallel execution rather than rolling your own pool. It is a thread pool, which is the right choice for the I/O-bound API work these commands do (and it sidesteps the pickling constraints a process pool puts on worker functions) — but treat the executor type as `runner`'s implementation detail, not something a caller should name
- Use `storyforge.api` for all Claude API calls

### Shared Modules — USE THEM
Before writing new code, check if a shared function already exists.

**common.py:**
- `detect_project_root()` — returns project directory path
- `log(msg)` — timestamped logging to stdout + optional log file
- `read_yaml_field(field, project_dir)` — read from storyforge.yaml
- `select_model(task_type)` — returns the right model (opus for creative, sonnet for analytical)
- `select_revision_model(pass_name, purpose)` — model for revision passes
- `get_coaching_level(project_dir)` — returns full/coach/strict
- `check_chapter_map_freshness(project_dir)` — returns (is_fresh, missing_from_map, extra_in_map)
- `get_plugin_dir()` — returns plugin root directory
- `extract_craft_sections(*section_nums)` — extract from craft engine
- `install_signal_handlers()` — SIGINT/SIGTERM handling
- Pipeline manifest: `get_current_cycle()`, `start_new_cycle()`, `update_cycle_field()`

**git.py:**
- `create_branch(command_name, project_dir)` — creates `storyforge/{type}-*` branch
- `ensure_branch_pushed(project_dir)` — push branch to remote
- `create_draft_pr(title, body, project_dir, label)` — create draft PR
- `update_pr_task(task_text, project_dir, pr_number)` — check off a task
- `commit_and_push(project_dir, message, paths)` — stage, commit, push
- `run_review_phase(review_type, project_dir, pr_number)` — full review workflow

**cli.py:**
- `base_parser(prog, description)` — argparse with common flags (--dry-run, --parallel, etc.)
- `add_scene_filter_args(parser)` — adds --scenes, --act, --from-seq
- `resolve_filter_args(args)` — returns (mode, value, value2) tuple

**runner.py:**
- `run_parallel(items, worker_fn, max_workers, label)` — ThreadPoolExecutor parallel execution; honours `STORYFORGE_PARALLEL` and the shutdown flag, and returns `{item: result-or-Exception}` (a raised worker is a value in that dict, so the caller must check for it)
- `run_batched(items, worker_fn, merge_fn, batch_size)` — batched with merge step
- `HealingZone(description, project_dir)` — retry with Claude diagnosis on failure

**api.py:**
- `invoke_api(prompt, model, max_tokens)` — high-level: returns text or empty string on failure
- `invoke(prompt, model, max_tokens)` — returns full API response dict
- `invoke_to_file(prompt, model, log_file, max_tokens)` — writes JSON response to file
- `extract_text(response)` — extract text from API response dict
- `submit_batch(batch_file)` / `poll_batch(batch_id)` / `download_batch_results(results_url, ...)` — Batch API

**costs.py:**
- `calculate_cost(model, input_tokens, output_tokens, ...)` — USD from token counts
- `estimate_cost(operation, scope_count, avg_words, model)` — forecast cost
- `check_threshold(estimated_cost)` — check against threshold
- `log_operation(project_dir, operation, model, ...)` — append to ledger
- `print_summary(project_dir, operation)` — print totals

**scene_filter.py:**
- `build_scene_list(metadata_csv)` — ordered scene IDs, excluding cut/merged
- `apply_scene_filter(metadata_csv, all_ids, mode, value, value2)` — filter by mode

**csv_cli.py:**
- `get_field(file, id, field, key_column)` — read one cell
- `get_row(file, id, key_column)` — read one row
- `get_column(file, field)` — read one column
- `list_ids(file)` — list all IDs
- `update_field(file, id, field, value, key_column)` — update one cell
- `append_row(file, row)` — append a row

**history.py:**
- `append_cycle(scores_dir, cycle, project_dir)` — append scene scores to history
- `get_scene_history(project_dir, scene_id, principle)` — returns [(cycle, score)]
- `detect_stalls(project_dir, principle, min_cycles, max_score)` — scenes stuck on a principle
- `detect_regressions(project_dir, principle, threshold)` — scenes where score dropped

### Command Module Pattern
```python
def parse_args(argv):
    parser = argparse.ArgumentParser(prog='storyforge <name>')
    # ... flags matching the CLI interface
    return parser.parse_args(argv)

def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()
    # ... orchestration logic
```

### Parallel Execution Pattern
```python
from storyforge.runner import run_parallel, run_batched

results = run_parallel(scene_ids, process_scene, max_workers=6, label='scene')
# or with merge step:
results = run_batched(scene_ids, process_scene, merge_fn=merge_results, batch_size=6)
```

### Claude API Invocation
```python
from storyforge.api import invoke_api, invoke_to_file, submit_batch, poll_batch

# Simple: get text response
text = invoke_api(prompt, model, max_tokens=4096)

# With file logging
response = invoke_to_file(prompt, model, log_file, max_tokens=4096)

# Batch API
batch_id = submit_batch(batch_file)
results_url = poll_batch(batch_id, log_fn=log)
succeeded = download_batch_results(results_url, output_dir, log_dir)
```

## Skill Standards

Interactive skills live in `skills/{name}/SKILL.md`.

### Frontmatter
```yaml
---
name: skill-name
description: One-line description. Used by Claude Code to decide when to invoke.
---
```

### Required Sections
1. **Locating the Storyforge Plugin** — resolve plugin root path
2. **Read Project State** — list which files to read
3. **Determine Mode** — what to do based on user's request
4. **Commit After Every Deliverable** — `git add -A && git commit -m "..." && git push`
5. **Coaching Level Behavior** — adapt for full/coach/strict

### Script Delegation Pattern
When a skill delegates to an autonomous script, always offer two options:

> **Option A: Run it here**
> I'll launch the command in this conversation. [If the command invokes Claude: "This requires unsetting CLAUDECODE."]
>
> **Option B: Run it yourself**
> Copy this command and run it in a separate terminal:
> ```bash
> cd [project_dir] && [plugin_path]/storyforge thing [flags]
> ```

Wait for the author's choice. If Option B, provide the full command and end.

### Coaching Level Adaptation
- **full:** Proactive. Recommend actions, offer to run, explain implications. Creative partner.
- **coach:** Guided. Present options as questions, help the author think through decisions. Don't do creative work.
- **strict:** Passive. Report data, provide commands, don't interpret or recommend. Author makes all decisions.

## CSV Data Format

All structured data uses pipe-delimited CSV:
- **Field delimiter:** `|`
- **Array delimiter within fields:** `;`
- **First row:** header with field names
- **No quoting** — pipes don't appear in natural prose
- **Semicolons in content:** use comma instead or escape as `\;`
- **Empty fields:** zero characters between delimiters

### Key CSV Files

**Prose tier — story summary at progressive granularity:**
- `reference/story-summary.md` — four sections: `## Logline` (1 sentence), `## Synopsis` (1 paragraph), `## Act-shape` (3 paragraphs, one `### Act N` each), `## Theme` (2-4 sentences). Per-section `_updated` timestamps in YAML frontmatter are written and parsed (`common.py`) but **nothing consumes them** — there is no cascade drift detection. See the staleness-unification issue. `## Logline` is canonical; `storyforge.yaml:project.logline` is deprecated as an input.
- `reference/outline.md` — read-only render of the expanding outline. Three numbered sections (Spine / Architecture / Scenes), each populated from the `summary` column of the corresponding CSV. Sync regenerates this file on every commit; authors edit summaries in the CSVs.

**Structural-anchor tier — each its own discrete CSV:**
- `reference/spine.csv` — 5-10 irreducible events (id, seq, title, summary, function, part). `summary` is a single sentence — what happens in this event.
- `reference/architecture.csv` — 15-25 anchor scenes (id, seq, title, summary, part, pov, spine_event, action_sequel, emotional_arc, value_at_stake, value_shift, turning_point). `summary` is a single sentence; `spine_event` is required and references `spine.csv:id`.

**Manuscript tier:**
- `reference/scenes.csv` — structural identity (id, seq, title, summary, part, pov, location, timeline_day, time_of_day, duration, type, status, word_count, target_words, target_pages, panel_count, page_count, architecture_scene). `summary` is a single sentence describing what happens; `architecture_scene` is optional and references `architecture.csv:id` (empty for purely interstitial scenes).
- `reference/scene-intent.csv` — narrative dynamics (id, function, action_sequel, emotional_arc, value_at_stake, value_shift, turning_point, characters, on_stage, mice_threads, theme_threads). `theme_threads` references `themes.csv:id`.
- `reference/scene-briefs.csv` — drafting contracts (id, goal, conflict, outcome, crisis, decision, knowledge_in, knowledge_out, key_actions, key_dialogue, emotions, motifs, continuity_deps, has_overflow)
- `reference/illustration-plan.csv` — one row per interior illustration (id, scene_id, anchor, placement, layout, beat, rationale, subject, composition, palette, mood, motifs, canon_refs, status, asset_file, prompt_file, sha256, width, height, ingested_at, state_override, register, scene_digest, treatment, treatment_at). `id` is the scene-marker key and (lowercased) the Bookshelf asset key; `anchor` is a verbatim quote from the scene, which is what lets a plan row survive revision; `placement` is where in the prose, `layout` is how much page; `ingested_at` is the ISO date a render was ingested, and is what the reference chain compares against the newest `canon_updated`; `state_override` is `entity:state` true in this image only; `register` (`darkest` | `brightest`) marks the book's lighting extremes for the anchor batch; `scene_digest` is the prose the render was made from; `treatment` is the staging `--sequence` assigns and `treatment_at` the ISO date it did so (which is what makes "the render predates its treatment" decidable rather than guessed). The last six are all in `illustrations.OPTIONAL_PLAN_COLUMNS`, so a plan predating any of them still validates and the first write upgrades the header (empty `ingested_at` means pre-canon). `absent` and `contrast` are **not** schema columns — an author may add them by hand and `write_plan` preserves them, and the packet reads them into each image prompt's Constraints block. `prompt_file` points into `reference/illustration-prompts/` since #306. Prose books only.
- `reference/canon/` — the reference tier interior-illustration prompts inherit (prose books; supersedes the single-document `reference/illustration-direction.md`, see "Interior Illustrations" below). Three book-level files at the canon root (`visual-foundation`, `visual-vocabulary`, `content-limits` — `prompts_illustrate.CANON_PLAN`) plus one per-entity file per character/creature/location/prop under `characters/`, `locations/`, `motifs/`, whose `## Embeddable block` *is* the continuity anchor.
- `reference/voice-profile.csv` — structured voice constraints (_project row for banned words/register, per-character rows for preferred words/metaphor families/rhythm/dialogue style)

**Cross-cutting registries:**
- `reference/themes.csv` — abstract concerns the story argues (id, name, tier, description). Distinct from motif-taxonomy.csv (concrete recurring vehicles). Per-scene tracking via `theme_threads` on scene-intent.csv.

**Shared:**
- `working/annotations.csv` — reader annotations from Bookshelf (id, scene_id, chapter, color, color_label, text, note, reader, created_at, status, fix_location, fetched_at)
- `working/craft-weights.csv` — craft principle weights (keyed by `principle` column, not `id`)
- `working/costs/ledger.csv` — per-invocation cost tracking
- `reference/chapter-map.csv` — chapter-to-scene mapping
- `working/scores/score-history.csv` — per-scene, per-principle scores across cycles (cycle, scene_id, principle, score)
- `working/scoring-overrides.csv` — per-finding "considered, accepted" markers (scope, axis, finding_id, verdict, rationale, recorded_at). Cascade / quality gates skip findings the author has overridden.
- `working/scoring-verdicts.csv` — diff+verdict persistence for cross-level boundary diffs (scope, boundary, verdict, rationale, actor, recorded_at). Actor is `llm` (proposed in full-coaching mode) or `author`.
- `references/ai-tell-words.csv` — universal AI-tell vocabulary (word, category, severity, replacement_hint)

### Scene Files
- Pure prose markdown. **No YAML frontmatter.**
- Filename is the scene ID: `scenes/the-finest-cartographer.md` → id is `the-finest-cartographer`
- Word count, status, and all metadata live in the CSV files, not in the scene file.

## Testing

Tests use pytest. Files live in `tests/test_*.py`. Shared fixtures in `tests/conftest.py`.

### Fixtures (conftest.py)
- `fixture_dir` — path to `tests/fixtures/test-project` (read-only)
- `project_dir` — fresh copy of fixture in tmp_path (for write tests)
- `plugin_dir` — path to the Storyforge plugin root
- `ref_dir`, `meta_csv`, `intent_csv`, `briefs_csv` — convenience paths

### Test Pattern
```python
# test_thing.py
import os
from storyforge.common import read_yaml_field, detect_project_root

def test_yaml_field(fixture_dir):
    result = read_yaml_field('project.title', fixture_dir)
    assert result == "The Cartographer's Silence"

def test_detect_root(fixture_dir):
    root = detect_project_root(os.path.join(fixture_dir, 'scenes'))
    assert root == fixture_dir
```

Run: `./tests/run-tests.sh` or `python3 -m pytest tests/` or `pytest tests/test_thing.py`.

## Architecture Quick Reference

- **Commands** (`scripts/lib/python/storyforge/cmd_*.py`) — autonomous execution. Invoke Claude, create branches/PRs, commit.
- **Skills** (`skills/*/SKILL.md`) — interactive Claude Code sessions. Guide the author, delegate to commands.
- **Core modules** (`scripts/lib/python/storyforge/common.py`, `git.py`, `cli.py`, `runner.py`, `api.py`, `costs.py`, `scene_filter.py`) — shared infrastructure.
- **Domain modules** (`scripts/lib/python/storyforge/`) — scene data helpers, extraction, scoring, prompts, visualization.
- **Prompts** (`scripts/prompts/`) — prompt templates for evaluators and scoring.
- **References** (`references/`) — craft engine, scoring rubrics, schemas, default weights.
- **Templates** (`templates/`) — project scaffolding for init.
- **Tests** (`tests/`) — pytest test suite.
- **Docs** (`docs/`) — GitHub Pages site with visualization pages.

### Commands

| Command | Module | Purpose |
|---------|--------|---------|
| `storyforge annotations` | `cmd_annotations.py` | Fetch reader annotations from Bookshelf, reconcile, route by color intent. |
| `storyforge write` | `cmd_write.py` | Draft scenes (brief-aware, parallel wave drafting) |
| `storyforge evaluate` | `cmd_evaluate.py` | Multi-agent evaluation panel (6 evaluators + synthesis) |
| `storyforge revise` | `cmd_revise.py` | Execute revision passes. `--polish` for craft-only. `--polish --loop` for score→polish convergence. `--naturalness` for AI pattern removal. |
| `storyforge score` | `cmd_score.py` | Craft scoring (25 principles + fidelity scoring against briefs). `--principles P1,P2` targets specific principles; deterministic principles skip the LLM pipeline (see `DETERMINISTIC_PRINCIPLES` in `cmd_score.py`). **Elaboration entry points:** `--level N` / `--all-levels` (floor checks); `--compare a b [c]` (prose-tier multi-candidate report); `--compare ... --semantic` (LLM ceiling axes); `--drift` (read-only deterministic drift report); `--boundary N->M` / `--all-boundaries` (LLM faithfulness diff, optional `--scope`); `--bible-consistency` (LLM check vs character/world/voice bibles, ~$20-25/run); `--story-power` (8-axis pitch-tier scorecard; auto-extends to act-shape mode with per-act 3×8 matrix + 4 cross-act structural axes when `## Act-shape` is populated; auto-extends to spine mode with per-event 3-axis matrix + 5 whole-spine axes + weak-handoff diagnostic when `reference/spine.csv` exists; auto-extends to architecture mode with per-scene 2-axis matrix + 5 whole-architecture axes + field-coherence pre-pass + proposed field updates and scene insertions when `reference/architecture.csv` exists, register-aware via `project.register`; auto-extends to scene-map mode with per-scene 2-axis matrix + 5 whole-map axes + continuity pre-pass + proposed scene operations (merge/split/insert/reorder/promote) when `reference/scenes.csv` exists; auto-extends to briefs mode with per-brief 2-axis matrix + 5 whole-briefs axes + scene-engine / knowledge-orphan / outcome-streak / motif-singleton pre-pass + proposed brief-field updates when `reference/scene-briefs.csv` exists; **cross-tier meta-diagnostic** runs over ≥2 tier outputs synthesizing patterns no single tier sees (deterministic pre-pass: lowest-axis recurrence, scene-id overlap in proposals, field-coherence cascade, project-level disposition; LLM synthesis with typed-target proposals; cost-discipline skips LLM when pre-pass empty AND <3 tiers); coaching-aware; delta tracking; see `references/story-power-rubric.md`). All scoring respects `working/scoring-overrides.csv` — accepted findings surface tagged but don't count toward failure totals. |
| `storyforge status` | `cmd_status.py` | Deterministic next-step verdict — walks the elaboration ladder (L0–L6 floor checks), folds coverage/consistency into blockers, derives draft/evaluate rungs from scene status. `--json` for tooling (forge routes on `next.stage`). No LLM, read-only. |
| `storyforge elaborate` | `cmd_elaborate.py` | Run elaboration stages (spine/architecture/map/briefs/page-architecture/prompts) |
| `storyforge extract` | `cmd_extract.py` | Extract structural data from prose. `--force` overwrites. |
| `storyforge validate` | `cmd_validate.py` | Structural + schema validation, plus the illustration plan and `reference/canon/`. `--structural` for scoring. Exits 1 on structural failures, schema failures, blocking illustration findings, or **error**-severity canon findings (`canon.canon_gate`); canon warnings and info report and pass. |
| `storyforge hone` | `cmd_hone.py` | CSV data quality — registries, briefs, intent, gaps. `--diagnose` for read-only. `--loop` for autonomous convergence. `--findings FILE` for evaluation-driven fixes. |
| `storyforge reconcile` | `cmd_reconcile.py` | Backwards-compatible wrapper for hone |
| `storyforge repetition` | `cmd_repetition.py` | Cross-chapter repeated phrase detection. Standalone or via scoring. |
| `storyforge enrich` | `cmd_enrich.py` | Metadata enrichment from prose |
| `storyforge assemble` | `cmd_assemble.py` | Chapter assembly + epub/PDF/HTML generation |
| `storyforge visualize` | `cmd_visualize.py` | Multi-page manuscript dashboard |
| `storyforge timeline` | `cmd_timeline.py` | Timeline construction |
| `storyforge cleanup` | `cmd_cleanup.py` | Project structure cleanup. `--scenes` strips writing-agent artifacts from scene files. `--csv` runs only the CSV integrity report (schema + row checks). Also validates the illustration plan against its markers and files. |
| `storyforge cover` | `cmd_cover.py` | Cover design |
| `storyforge illustrate` | `cmd_illustrate.py` | Interior illustrations (prose only). `--direction` writes the book-level art direction (format, visual promise, recurring visual language, content limits, continuity anchors) — authored once, inherited by every prompt; `--plan` proposes moments (deterministic pre-pass over spine/architecture/motifs/chapter distribution, then an LLM pass that argues against those findings); `--prompts` writes GPT Image 2 art direction per illustration (calls fan out 5 at a time via `runner.run_parallel`; all writes stay sequential), sending the scene **split at the illustration's reading position** with the following paragraphs in a forbidden block and an unresolved position stated out loud (#308), passing the visual state resolved at each row's scene — `packet.state_for_row`, the same resolution `--package` renders — plus `absent` and `contrast`, naming the resolved style reference (`production.cover_artwork`, else the `cover-illustration.*` convention) once before any call and refusing outright when that declaration names a missing file, with `--no-prior-refs` for a cover-only reference chain; `--ingest PATH` brings rendered files in, records sha256 + dimensions + `ingested_at`, and embeds markers; `--embed` re-inserts markers; `--state` writes the visual-state transition log (`reference/visual-state.csv` — what changes on schedule, as opposed to canon's what-must-never-change; coaching-aware, `full` never revises a transition the author wrote and refuses a proposal naming a scene that does not exist, `strict` never rewrites an existing log); `--audit` reads the prose against that matrix and reports contradictions (deterministic pre-pass narrows to candidate scenes, then one Sonnet call; no findings and no candidates means no call; read-only wrt prose and the log; writes `working/illustration-contradictions.md` + `working/illustration-audit-provenance.csv`); `--sequence` assigns each row a distinct `treatment` in one cheap call (beats and layouts only, never scene prose) so twenty independent generation calls stop converging on one shot — never overwrites an author's treatment, reports duplicates; `--package` assembles `manuscript/illustration-packet/` (five root files plus `image-prompts/{id}.md` per illustration, no API calls, regenerated wholesale so it is a render and never hand-edited; anchors copied byte-identically, gaps stated in the packet, the four-slot anchor batch with every guessed slot disclosed, and every upload file carrying only what the image model should read); `--diagnose` is a read-only health report with the recommended render order, every ingested illustration whose art predates the current canon (with the reason, since the fix is a re-render and never a `status` demotion), the anchor batch, the resolved style reference, and the state/audit/staging/packet rungs; `--review` writes the whole-sequence continuity checklist. Coaching-aware. Refuses to run on graphic-novel projects (they use the page pipeline). |
| `storyforge scenes-setup` | `cmd_scenes_setup.py` | Scene file and metadata setup |
| `storyforge scenes-export` | `cmd_scenes_export.py` | Export scenes to `reference/scenes-review.md` (header-driven; round-trips every column present in the CSVs, including GN additions) |
| `storyforge scenes-import` | `cmd_scenes_import.py` | Import edited `scenes-review.md` back into scene CSVs |
| `storyforge sync` | `cmd_sync.py` | Sync scene CSVs ↔ `reference/scenes-review.md` against git HEAD. Exports when CSVs are dirty, imports when MD is dirty, writes `working/sync-conflict.md` and exits 1 when both moved. `--install-hook` drops a pre-commit hook that runs this on every commit. |
| `storyforge review` | `cmd_review.py` | Pipeline review |
| `storyforge migrate` | `cmd_migrate.py` | Project migration. Nine steps: registry rename/seed/normalize/validate (1-5) + elaboration v1 (6-8): bootstrap `story-summary.md`, extract `status=spine` rows into `spine.csv`, extract `status=architecture` rows into `architecture.csv`. Step 9 moves `manuscript/assets/illustrations/prompts/*.md` to `reference/illustration-prompts/` and rewrites the plan's `prompt_file` column (#306). All steps idempotent. Step 7/8 upgrade pre-`summary` headers in place. |
| `storyforge propose-summaries` | `cmd_propose_summaries.py` | Draft candidate one-sentence `summary` cells from the level above. `--level 3` proposes from act-shape into spine; `--level 4` proposes from spine into architecture; `--level 5` proposes from architecture into scene-map. Coaching-aware: `full` writes to the target CSV (preserves existing summaries); `coach` writes a review brief; `strict` produces a rule-based constraint checklist (no LLM). |

### Skills

| Skill | Purpose |
|-------|---------|
| `forge`† | Hub — reads project state, recommends next action, routes to skills |
| `elaborate`† | All creative development: spine → architecture → voice → map → briefs. Character, world, story architecture. |
| `extract` | Reverse elaboration — extract structural data from existing prose |
| `revise` | Plan + execute revision (upstream CSV fixes + prose polish). `--polish` for craft-only. |
| `score` | Craft + fidelity scoring |
| `hone`† | CSV data quality — registries, brief concretization, intent quality, evaluation-driven fixes, gap detection. `--diagnose` for read-only assessment. |
| `cleanup` | Project health check — CSV schema validation, scene artifact cleanup, structural drift fixes. Generates report, works through action items. |
| `publish` | Assemble web book + generate dashboard + push to bookshelf |
| `produce` | Epub, PDF, print formats |
| `init`† | New project initialization |
| `cover` | Cover design |
| `illustrate` | Interior illustrations — decide where they belong, art-direct them, ingest the renders, embed the references |
| `title` | Title development |
| `press-kit` | Marketing materials |

† Medium-aware: behavior adapts to `project.medium` (novel | graphic-novel).

### Elaboration Pipeline

New projects use the elaboration pipeline: progressive structural development before drafting.

```
Seed → Pitch (Logline → Synopsis → Act-shape) → Spine → Architecture → Scene Map → Briefs → Validate/Diagnose → Draft → Evaluate → Polish → Produce
```

The pitch/prose tier (`reference/story-summary.md`) comes first: `storyforge status` reports the ladder position and won't consider a project ready for the spine until the prose-tier rungs read `solid` (floor checks `score --level 0/1/2`, pressure-tested by `score --story-power`).

Each stage populates columns in the three-file CSV model. Validation gates between stages catch structural issues before they become prose problems. Evaluation findings route back to the appropriate CSV (brief/intent/structural) for upstream fixes rather than prose revision.

Key principles:
- **Validate cheap, fix cheap** — catch problems as CSV edits, not prose rewrites
- **Parallel drafting** — scenes with no `continuity_deps` can be drafted simultaneously
- **Evaluation feeds upstream** — findings map to `fix_location` (brief/intent/structural/craft)
- **Coaching levels are roles** — full=creative partner, coach=dramaturg, strict=continuity editor

### Python Modules

**Infrastructure (new in v1.0):**

| Module | Purpose |
|--------|---------|
| `__main__.py` | CLI dispatcher — `storyforge <command>` routing |
| `common.py` | Logging, YAML reading, model selection, coaching, signal handling, pipeline manifest |
| `git.py` | Branch/PR workflow, commit helpers, review phase |
| `cli.py` | Shared argparse helpers, common flags |
| `runner.py` | Parallel execution (ThreadPoolExecutor), healing zones |
| `scene_filter.py` | Scene list building and filtering |

**Domain modules:**

| Module | Purpose |
|--------|---------|
| `annotations.py` | Reader annotation processing: fetch, reconcile, route, exemplar promotion |
| `api.py` | Anthropic API (Messages + Batch), response parsing, cost calculation |
| `bookshelf.py` | Bookshelf API client: Supabase auth, publishing, annotation fetching |
| `costs.py` | Cost tracking, estimation, threshold checking, ledger |
| `csv_cli.py` | Pipe-delimited CSV operations (get/set/list/append) |
| `schema.py` | Column schema definitions, enum/registry/MICE validation |
| `elaborate.py` | Scene data helpers, validation engine, wave planner |
| `extract.py` | Extraction prompt builders, response parsers |
| `prompts.py` | Scene drafting prompt builders |
| `prompts_elaborate.py` | Elaboration stage prompt builders |
| `scoring.py` | Score parsing, diagnosis, proposals, fidelity scoring |
| `structural.py` | Structural scoring engine (8 dimensions, deterministic) |
| `status.py` | Next-step verdict: ladder-state walk, blockers, draft-state, recommendation mapping (backs `storyforge status`) |
| `hone.py` | CSV data quality: registries, brief detection (abstract/overspecified/verbose), intent detection (vague/overlong/flat/abstract arc/subset/mismatch), evaluation findings, gaps |
| `reconcile.py` | Backwards-compatible re-exports from hone.py |
| `repetition.py` | Cross-chapter n-gram repetition detection, scoring integration |
| `visualize.py` | Dashboard data loading |
| `enrich.py` | Metadata enrichment |
| `assembly.py` | Chapter assembly, publish manifest generation |
| `parsing.py` | Scene content extraction |
| `project.py` | Project state management |
| `revision.py` | Revision prompt builders |
| `timeline.py` | Timeline construction |
| `cover.py` | Cover generation |
| `illustrations.py` | Illustration plan I/O, the `![[illus:id]]` marker (parse/insert/strip), `reading_position` — the one predicate for how much of a scene the reader has read when an image appears, shared by `insert_marker` and `--prompts` — plus `split_at_position` / `SceneSplit` / `first_sentence` and `spoiler_findings` over it, per-target resolution, selection pre-pass, render order (and `visual_key_horizon`, which the anchor batch names in its disclosure), `stale_render_reason` — the one predicate for whether a row's finished art predates the canon now governing it — plan validation. Continuity anchors and book-level direction now live in `canon.py` / `prompts_illustrate.py`; this module keeps only a read of the retired `illustration-direction.md` for the one-time hand-edit safety net |
| `visual_state.py` | The visual-state transition log: read/write, forward resolution (`state_at`), the five-check deterministic pre-pass (`prepass`), digest drift (`digest_drift`), and audit provenance |
| `packet.py` | What goes in the handoff packet and proof the copies are exact: `resolve` (image prompts, anchors, references, and the `gaps` coverage record), `rows_in_reading_order`, `needs_render` (id → why it still needs a render, over one staleness predicate shared with `--prompts`' reference chain), `state_context` → `RowContext` / `state_for_row` / `contrast_for_row` (shared with `--prompts`, so the two artifacts cannot describe one row differently within a run), `entry_for` → `image_prompt_for` (the only rendering of a plan row *into the packet*; `prompts_illustrate.render_prompt_file` renders one into the source prompt file, which is why that file can go stale and the upload cannot), the body recovery moved from the retired export (`_body_for`, `_derived_body`, `body_truncated`), `_self_reference_note`, `state_grid`, `anchor_batch`, `anchor_block`, `anchor_copy_drift`, `packet_stale` (whose sources now include the prompt bodies, since `--package` inlines them), `image_prompt_file` (which re-checks the id against `_ID_RE` before it names a path). No rendering, no LLM |
| `prompts_packet.py` | The packet renderers — `render_readme` (runbook, upload list, anchor batch, gaps), `render_illustrations` (the index and the author-facing notes), `render_image_prompt` (the upload file, whose heading set `IMAGE_PROMPT_SECTIONS` bounds), `render_canon`, `render_visual_state`, `render_acceptance`, `_cell` — plus the sequence pre-pass request + parser (`build_sequence_request`, `parse_sequence_response`), `duplicate_treatments`, and the coach brief / strict checklist for `--sequence` |
| `prompts_illustrate.py` | Illustration selection + art-direction prompt builders, `prompt_constraints` (shared with the packet's upload file so the source prompt file and the upload cannot state different constraints for one row) / `prompt_acceptance_lines` (now only the source prompt file's, since the upload carries no acceptance block) and `parse_prompt_file` (the reader of `render_prompt_file`, kept beside it), book-level canon-file builders (`CANON_PLAN` templates, filled-canon and anchor stubs, the direction request and its response parser), sequence-review renderer, coach brief, strict checklist, the visual-state request / brief / checklist, and the contradiction-audit request + report renderer |
| `canon.py` | `reference/canon/` typed canon files: frontmatter + section parsing, validation (id/type/location/required sections/unfilled scaffolds/`canon_truncated_embeddable_block`), registry cross-check, and the `## Embeddable block` — a verbatim string that serves as a GN per-panel prompt block and as a prose continuity anchor (`anchor_texts`, `is_canon_block_populated`). Also canon-embed drift detection against `pages/*.md`. Both mediums depend on it |
| `scenes.py` | Scene file management |
| `exemplars.py` | Prose exemplar validation |
| `prose_analysis.py` | Shared text analysis: passive voice, dialogue extraction, adverbs, fillers, AI-tell vocabulary |
| `scoring_passive.py` | Deterministic scorer: avoid_passive (passive voice clusters/density) |
| `scoring_adverbs.py` | Deterministic scorer: avoid_adverbs (dialogue-tag, weak-verb, redundant) |
| `scoring_weather.py` | Deterministic scorer: no_weather_dreams (scene opening patterns) |
| `scoring_rhythm.py` | Deterministic scorer: sentence_as_thought (sentence length variance) |
| `scoring_economy.py` | Deterministic scorer: economy_clarity (composite filler/AI-tell/passive/adverb) |
| `scoring_gn.py` | Deterministic GN scorers: brief_fidelity, panel_density, dialogue_compression, layout_rhythm, caption_economy, panel_composition_depth |

## Graphic Novel Mode

Set `project.medium: graphic-novel` in storyforge.yaml at init time to switch a project into graphic-novel mode. To convert an existing project between mediums, use `storyforge migrate-medium --to {novel|graphic-novel}` (archives current state, resets scene drafts, transforms CSV schemas).

**Supported (Plans 1 + 2 + 3):**
- `elaborate` (spine, architecture, scene-map, voice, briefs)
- `hone`, `validate`, `cleanup`
- `write` — drafts panel scripts per scene (mirrors novel-mode write; routes to `cmd_write_gn`)
- `assemble` — produces the artist handoff bundle: `manuscript/{script.md, visual-references.md, chapter-map.md, handoff-readme.md, style-guide.md}` (routes to `cmd_script_package`). The style guide is coaching-aware: `full` LLM-synthesizes from world/character/voice bibles; `coach` produces a cues + author-questions template; `strict` produces a blank section template with constraint lists. Falls back to the coach template when ANTHROPIC_API_KEY is missing.
- Schema validation enforces graphic-novel column rules (target_pages required, panel_breakdown required at briefed status)
- `score` — 6 deterministic GN principles in `scoring_gn.py` (brief_fidelity, panel_density, dialogue_compression, layout_rhythm, caption_economy, panel_composition_depth); no API calls, instant and cost-free (routes to `cmd_score_gn`)
- `evaluate` — 3-persona evaluation panel (panel-composition, pacing, dialogue critics) that adds subjective findings the deterministic scorers can't catch (routes to `cmd_evaluate_gn`)
- `revise` — findings-driven polish pass; reads score + evaluator findings and produces a revised panel script per scene. One API call per scene (routes to `cmd_revise_gn`). Pass `--no-findings` to polish blind.
- `extract` — bootstrap GN structural data from existing scripts (`--from-script PATH`, deterministic parse via `script_format.py`) or from prose (`--from-prose PATH`, LLM-driven adaptation, coaching-aware). Routes to `cmd_extract_gn`.

**Not yet supported (followups tracked as issues):**
- `publish`, `annotations` — Bookshelf integration for GN (#215)

**Schema additions:**
- `reference/scenes.csv` adds: `target_pages`, `panel_count`, `page_count`
- `reference/scene-briefs.csv` adds: `page_layout`, `panel_breakdown`, `visual_keywords`, `page_turn_beats`, `caption_strategy`
- `reference/voice-profile.csv` `_project` row adds: `caption_voice`, `lettering_style`

**Per-page files (issue #251):**
- A `pages/` directory (sibling to `scenes/`) can hold per-page markdown files at `pages/<prefix>-pN.md` where the prefix is `sN` for scene ids starting with `sN-` (e.g., `s01-studio-finalization` → `s01`) or the full scene id otherwise.
- Each page file has YAML frontmatter (`page_id`, `scene_id`, `page_within_scene`, `total_pages_in_scene`, `panel_count`, plus recommended `spread_position`, `characters_present`, `location`, `timeline`, and v3 fields `schema_version: 3`, `target_model`, `references_required`, `canon_referenced`) and body sections: Scene context, Page architecture, Panel script, Image-generation workflow, Page-specific notes.
- When `pages/` is populated, `script-package` assembles the artist bundle from page files (preferring the `## Panel script` section of each), `extract --from-pages` syncs `panel_count` + `page_count` on `scenes.csv` from the page metadata, and `cleanup` validates page-file frontmatter and filename / `page_id` consistency.
- Scene files (`scenes/<scene_id>.md`) remain the creative source of truth — function, page index, cross-page continuity notes live there.

**Page architecture (issues #252, #260):** `storyforge elaborate --stage page-architecture` writes a single `## Page architecture` authoring-context section (Intent / Panel hierarchy / Layout) into each page file in `pages/`. It captures panel hierarchy, eye flow, and pacing intent — commentary for the artist and the page prompt, not a render directive. Requires `reference/canon/panel-registers.md` and `reference/canon/page-rhythm-rules.md` to be populated. (The v2 monochrome page-blocking prompt was removed in #260: GPT Image 2 plans layout and renders the whole page in one shot, so there is no blocking pass.)

**Image-generation prompts (issue #260, supersedes #253):** `storyforge elaborate --stage prompts` writes a `## Image-generation workflow` section into each page file: an approach note, a labeled reference-image list (from frontmatter `references_required`), and a single whole-page **page prompt** in OpenAI's 5-section template (Scene / Subject / Important details / Use case / Constraints) with concrete per-panel beats. Tuned for GPT Image 2 (ChatGPT Images 2.0, `gpt-image-2`). Five validated principles (benjaminsnorris/ashes PR #9): (1) one prompt renders the whole page — no per-panel/composition pass; (2) reference images carry style + character likeness, so prompt prose stays short (~250-400 words); (3) the 5-section template, structure over brevity; (4) the character anchor is the IDENTICAL string in every panel; (5) positive framing replaces negation (negated keywords leak into the image). Preconditions: scene brief `panel_breakdown`, a populated `## Page architecture`, and a populated `## Panel script`. Canon *informs* the prompt (passed as distillation context) but is not embedded inline and does not gate the stage. `script-package` aggregates the workflows into `manuscript/page-prompts.md` plus a `manuscript/reference-images.md` manifest.

**GPT Image 2 quirk defaults (issue #263):** two failure modes surfaced repeatedly in lived iteration (benjaminsnorris/ashes PR #9) and are now baked into the `prompts` stage. (1) **Landscape drift** — GPT Image 2 returns landscape pages unless told otherwise, so every page prompt emits an explicit orientation directive in BOTH the Use case and Constraints. The default is portrait (`Render in PORTRAIT orientation — taller than wide, ~2:3 aspect ratio. Do not render as landscape or square.`); the orientation directive is the one place explicit negation is used, distinct from the content positive-framing rule. Per-page frontmatter `page_aspect: portrait | landscape | square` (default portrait) opts out. (2) **Close-up convergence** — when a page has ≥2 panels that are close-ups of the same subject, GPT Image 2 renders near-identical compositions, so the prompt emits a differentiation directive (one panel subject-in-isolation, one act-of-interaction at the contact point, one different-scale/angle). `pages.detect_closeup_convergence(panel_script)` groups close-ups that share a content word — a coarse subject proxy, not true noun extraction (hand vs. candle vs. portrait don't group; low false-positive rate on distinct subjects). It recognizes `**Panel N**` (the `storyforge write` format), `### Panel N`, and numbered-beat markers. `cleanup` validates `page_aspect` (`page_invalid_aspect`; `page_non_portrait_aspect` warns on a non-portrait value lacking a trailing `# justification` comment) and warns (`page_undifferentiated_closeups`) when a page prompt has same-subject close-ups but no differentiation language.

**Rendered page images (issue #261):** rendered pages have a canonical home at `manuscript/pages/<page_id>.png` — one PNG per page file, filenames matching the page IDs 1:1 (scene + page-within-scene naming, stable across scene reordering; book-wide page numbers stay derived from the chapter map). Each PNG is the *current* canonical render of that page; iteration history lives in git (no separate `drafts/` directory — re-render replaces the PNG and commit). `references_required` in a page's frontmatter can point at `manuscript/pages/*.png` for prior-page style/continuity anchors, so render order is also dependency order. `cleanup` flags an orphan PNG (no matching page file) as `page_render_orphan`; an *unrendered* page (page file with no PNG) is valid in-flight state, not a finding. `script-package` logs an "N of M pages rendered" count and, once at least one page is rendered, adds a `manuscript/pages/` inventory line to the handoff readme (before any render it logs 0-of-M progress to stdout only); orphan renders always log a WARNING. The PNGs already live under the bundle dir, so they are not copied. `forge` reports render status in GN mode and names the next unrendered page. `pages.page_render_report(project_dir)` returns `{rendered, unrendered, orphans}` (by `page_id`).

See the design spec: `docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md`.

## Interior Illustrations (prose books)

`storyforge illustrate` handles interior art for prose books — distinct from the cover, and distinct from GN mode's page pipeline (which it refuses to run on). See benjaminsnorris/storyforge#278.

**The reference tier** — `reference/canon/`, authored once, inherited by every prompt. It replaced the single hand-authored `reference/illustration-direction.md` document (see "No migration" below); prose books now share the canon-file model graphic-novel pages already used. It is the highest-leverage artifact in the flow: a per-illustration prompt can be re-rolled for cents, but a book whose images disagree with each other has to be re-rendered wholesale.

Three book-level files live at the canon **root**, defined in `prompts_illustrate.CANON_PLAN`:

| Canon file (`canon_id`) | `canon_type` | Carries |
|---|---|---|
| `visual-foundation` | `foundation` | Medium, rendering style, audience |
| `visual-vocabulary` | `vocabulary` | The rules that repeat — palette, camera height, depth of field, the standing no-text rule |
| `content-limits` | `rules` | What the art must never show |

`prompts_illustrate.book_level_direction()` reads each file's `## Embeddable block` body, and that is exactly what reaches a prompt as house style — an author-added fourth root-level canon file contributes nothing, because only these three ids are read. A canon file that is absent or still placeholder text is reported by `illustrations.missing_reference_sections`, which `--prompts` checks before it spends anything — a scaffold fed to an image model as though it were direction is worse than no file.

**Continuity anchors** are per-entity canon files under `characters/`, `locations/`, `motifs/` — one per character, creature, location, or prop the art must keep consistent. An entity canon file's `## Embeddable block` **is** the anchor: `canon.anchor_texts()` returns every populated one keyed by `canon_id`, and a plan row's `canon_refs` are matched against those slugs, not display names. Creature anchors live under `characters/` and prop anchors under `motifs/` — there is no separate creature or prop subdirectory — because `canon_missing_registry_entry` requires a matching row in the subdirectory's registry CSV (`characters.csv`, `locations.csv`, `motif-taxonomy.csv`) and the canon filename stem must equal that row's `id`. Each anchor body is reused **verbatim** in every prompt that features it — identical strings are the whole mechanism, so an anchor is an input to the art, never derived from whichever illustration rendered first. Never revise an anchor a rendered illustration already used; re-render from the corrected anchor instead. A model-proposed anchor persists as a typed canon stub (`prompts_illustrate.append_anchor_stubs`); the registry row is deliberately **not** auto-created — `canon_missing_registry_entry` reports the gap instead, since an author confirming a name is cheaper than silently canonizing a model's guess.

**A `##` heading inside an Embeddable block is an error, not a silence.** `embeddable_block_text` stops at the next `##` *followed by whitespace*, so an author who sub-heads the anchor itself (`## Wardrobe`) loses every word below that line — and the anchor is the string every prompt embeds verbatim, so the images then drift on whatever the dropped tail described. **The byte-identity checks cannot catch this**: `tests/test_packet.py` and `tests/test_illustrate_package.py` both compare against `anchor_texts`, the truncating function, so every check agrees with every other about a value already wrong. The extractor is deliberately *not* widened, because `## Wardrobe` and a legitimate author-added `## Notes` are indistinguishable to it — reading further would swallow a real section and feed it to an image model as description. So the truncation stays and `canon_truncated_embeddable_block` reports it. `canon.embeddable_block_truncations` finds the offenders (all of them, in source order, one finding per file); its window closes at the first `_SECTIONS_AFTER_ANCHOR` heading — **not** `REQUIRED_SECTIONS`, which contains the section being scanned, so a *duplicated* `## Embeddable block` once read as a clean terminator and halved the anchor with zero findings. `ParsedCanonFile.body_line_offset` exists so the finding can name the file line the author will actually look at.

**Severity `error`, and it now blocks.** Same class as `canon_id_mismatch` in that both break prompt assembly where the anchor is consumed — the failure modes differ, and truncation's is worse: a `canon_id` mismatch fails the lookup and surfaces as an unanchored row that `_warn_unanchored_rows` announces, whereas a truncation hands every consumer a shorter string they all accept, and once art exists the only repair is a re-render.

**Where canon findings are surfaced, and which ones gate.** `canon.canon_gate` splits `validate_canon_directory`'s output into `errors` and everything else, and `cmd_validate` folds `errors` into its exit code alongside structural / schema / illustration-plan — so `storyforge validate` exits 1 on a canon error. Only `error` blocks: `canon_unfilled_template` is `info` and warnings leave a working project, so a book mid-`--direction` still validates. Gating on those would make the check impossible to adopt, which is how a gate gets switched off wholesale. A project with no `reference/canon/` yields nothing, matching `cmd_cleanup.report_canon_files`' guard — never having run `--direction` is in-flight state, not a failure. `cleanup` still reports every canon finding at every severity and, as before, does not fail (`main` returns `None` on every path); it is the report, `validate` is the gate. Before this, an `error`-severity canon finding blocked nothing anywhere, which made the severity contract decorative (#295).

**A truncated anchor blocks through a second, separate path**, because `canon`'s own finding reaches only `cleanup` and `validate`, while the commands that *spend money* on a short anchor are `--prompts` and `--package`. `canon.truncated_anchor_ids` is the shared source; `illustrations.truncated_anchor_findings` emits `canon_anchor_truncated` from `validate_plan` (blocking — see `BLOCKING_FINDINGS`), which buys `validate`, `illustrate --diagnose`, and cleanup's Interior Illustrations section from one placement; `cmd_illustrate._warn_truncated_anchors` warns pre-fan-out beside `_warn_unanchored_rows`, since after the calls the money is spent; and `packet.resolve` records it as a gap. That last one matters because a truncated block is neither absent nor a scaffold, so `illustrations.missing_reference_sections` reports it **clean** while the packet copies only the text above the stray `##` — `book_level_direction`'s docstring used to delegate its silence to that check, and now says explicitly that it does not cover truncation (#293).

**This is medium-agnostic despite living in this section.** `validate_canon_file` runs for every medium, and GN's `check_canon_drift` reads the same extractor — so a truncated block shortens GN inline page embeds too, and that drift check compares truncated-to-truncated exactly the way the packet tests do.

**The truncation check runs before the frontmatter early returns, and must stay there.** `validate_canon_file` returns early on missing and unclosed frontmatter, but `embeddable_block_text`, `get_canon_embeddable_block`, `is_canon_block_populated` and `prompts_illustrate.book_level_direction` never read frontmatter — so a root `CANON_PLAN` file's truncated house style reached every prompt in the book while the truncation went unreported. That was a swallowed finding, not deferred triage.

**Anything interpolated into a finding `detail` from author prose goes through `common.csv_safe` first.** `working/cleanup-report.csv` is unquoted pipe-delimited, so a `|` shifts every later field one column right and empties the trailing `status` cell that `build_cleanup_report` sets to `pending` and `skills/forge/SKILL.md` scans for — the finding then silences itself in its only durable artifact. The helper lives in `common` rather than `illustrations` because `illustrations` imports `canon`; `illustrations._csv_safe` and `visual_state._csv_safe` both delegate to it so there is one such function.

`embeds_as` is required frontmatter only for `graphic-novel` projects (`canon.GN_ONLY_FRONTMATTER_KEYS`, layered onto `canon.ALWAYS_REQUIRED_FRONTMATTER_KEYS`) — it serves the GN page pipeline's inline-embed convention, which a prose project has no use for. Canon validation (`canon.validate_canon_directory`) now runs for every medium; there is no novel-specific exemption.

**There is no migration.** The one project with a hand-authored `illustration-direction.md` predating this phase keeps hand-editing its content into canon files at its own pace. `direction_anchor_mismatch` (`illus_direction_anchor_mismatch` once `cmd_cleanup` prefixes it — see the finding-name convention below) is the one-time safety net for that transition: it warns when a canon anchor's text differs from a same-named `### Name` section still present in `illustration-direction.md`, catching a transcription slip before it silently invalidates already-rendered art. It goes silent — by design — once that document is deleted, which is the intended end state.

**The plan** — `reference/illustration-plan.csv`, one row per illustration. `id` doubles as the scene-marker key and (lowercased via `asset_key`) the Bookshelf asset key; it accepts exactly what the marker regex accepts, so a hand-written `LF-01` validates. `anchor` is a short verbatim quote from the scene; matching is whitespace-tolerant so an anchor survives reflow, and a drifted or ambiguous anchor is *reported* rather than placing art at a guessed offset. `placement` (`before_anchor` | `after_anchor` | `scene_open` | `scene_close`) is *where in the prose*, always relative to the whole paragraph containing the anchor — an illustration never splits a paragraph. `layout` (`full_page` | `half_page` | `double_page` | `inline`) is *how much page*; "full-page opener" is a `full_page` layout at a `scene_open` placement. Layout drives aspect first, because a double-page spread is landscape whatever the composition note says.

**The scene reaches `--prompts` split at the illustration's reading position** (#308), because the beat immediately *after* an anchor is the one the model reaches for. `illustrations.reading_position` is the single predicate for "how much of this scene has the reader read?", and `insert_marker` now splits at the same offset — so `--embed` and `--prompts` cannot disagree about where an image sits. It returns `int | None` rather than a `-1` sentinel: a caller that skips the error check gets a `TypeError` out of the slice instead of `body[:-1]`, which is nearly the whole scene and is precisely the bug.

The failure was not model carelessness. The request used to be a 2400-character window straddling the anchor with **nothing marking which side was which**, and the planning guidance asks for "a beat the reader is already leaning into" — which makes the most vivid sentence in the scene very often the one the anchor was placed in front of. Handed the whole scene and asked for the strongest image, the model reached for exactly the thing the illustration was meant to precede. Three of three anchor-batch rows checked by hand on *The Lantern Folk* had it, including the book's final image, which rendered the resolution paragraph one page early. **Every automated gate passed**: `validate` 26/0, `--diagnose` clean, the contradiction audit clean, anchors resolving, no state drift.

**The unread paragraphs are sent, not omitted.** A model that cannot see the next page still invents toward it, so naming it is what makes it avoidable. This is **not** a fifth exception to positive framing — the four (`absent`, the colour logic, orientation, no-text) govern what the *image* prompt may negate, and this is an instruction to the model *writing* that prompt, which says explicitly to steer away silently and never name the beat in the body, "not even to exclude it". A negated phrase there would put the spoiled beat in the render, which is #263's finding.

**`SceneSplit` has three states and consumers must tell them apart.** Resolved; an image legitimately at a scene's end (`unread == '' and error == ''`), where the spoiler check is *vacuous* and no acceptance line is emitted, because rendering it would teach the author to tick a box that never had anything in it; and a position nobody could resolve, which is **stated** — the request says the split is unknown and the prompt file's `## Accept only if` says the check could not be made. Silence there would read as "there is nothing after this image", the same failure arrived at from the other direction. Same doctrine as `--audit`'s "Not assessed", `packet.NOT_RECORDED`, and `staleness_unchecked_finding`.

**The acceptance line quotes the next sentence** (item 2), and lands in the do-NOT-paste block rather than in Constraints — it is a check on the *render*, and it quotes prose the image model must never see. It is the only one of the four fixes that catches a bad render rather than preventing one, which is the point: the failure was invisible to every gate and was found by reading three rows by hand.

**`state_mid_scene_change`** (item 3) is the same root cause from the other side. `state_at` resolves at scene granularity, so the log holds one value for an entity across a whole scene — but a `scene_close` image is read *after* that scene's turn, so when the entity changes during the scene the resolved state is usually the one going in. That is LF-13: the Great Lamp's transition read "flame shrinking" and the illustration's whole subject was the Lamp dead. **Reported, never re-resolved** — guessing "scene_close means the post-transition state" would be wrong for every scene whose change lands in its opening paragraph, and this pipeline reports an ambiguous anchor rather than placing art at a guessed offset for the same reason. A `state_override` is the fix and suppresses it, exactly as it suppresses `state_unspecified`. Scoped to `scene_close` because every other placement now has a resolvable position inside the scene.

**`prompt_spoils_unread`** (item 4) covers art already directed, which matters because 17 of 20 rows on the book this was filed about needed re-rendering anyway and every one was directed by a prompt built the old way. Six-word shingles, and **"distinctive" is a set difference, not a frequency heuristic**: `(body ∩ unread) - read`, because a phrase the reader has already read is what the body is *supposed* to describe. Silent when there is no prompt file (unprompted is in-flight state), when the body could not be recovered, and when the position is unknown — an ambiguous anchor already has its own finding, and guessing here would warn about prose that may not be after the image at all.

Both kinds are **warnings**: the book is publishable either way, and both are about art not yet rendered, which is the moment they are worth anything. `illustrations.py` had never logged before `spoiler_findings`, so its unreadable-file path needed the local `log` import — without it a `PermissionError` came out of `validate_plan`, the single finding collector, taking every other check with it. That is the `ill.sha256_of` regression (#298) shape, and a test holds it.

**The visual-state matrix** — `reference/visual-state.csv`, a **sparse transition log**, added in phase 2 (#278). The canon tier says what must **never** change; nothing said what changes **on schedule** — wardrobe by chapter, a lamp lit or dark, how many village lights survive. Four of ten real findings on a real book traced to that gap. Columns: `entity|from_scene|state|evidence`.

- **A transition takes effect AT its own scene, not after it.** `state_at`'s comparison is `<=`; there is a test on exactly that boundary. An entity whose first transition is later than the queried scene is **absent** from the result, not blank — "not yet established" and "established as empty" are different, and callers report them differently. Two transitions for one entity at the same scene resolve to the later row in the file.
- **Granularity is `{canon_id}-{aspect}`**, one track per independently-changing aspect: `nora-clothing`, not `nora`, because clothing and injury change on different schedules and a single track would force restating one to change the other. A bare `canon_id` where an entity has one track. A plan row's `canon_refs` of `nora` is satisfied by any `nora-*` track — matching is by exact id and by `f'{ref}-'` prefix.
- **Sparse, not a dense scene × entity grid**, because scene-map operations insert, merge, split, and reorder: a transition keyed "from `act2-sc01` onward" still means something after a scene lands before it, where a dense grid would have no row and fall silently blank. The trade is that a row can name a scene since cut, which is why `state_unknown_scene` is an **error**. A `from_scene` that exists in `scenes.csv` but is absent from the chapter map is a *different* finding — `state_unmapped_scene`, a **warning**: the row is fine and the map is incomplete. Conflating the two would block a half-chaptered book's `validate` and push an author to delete good rows. The split defers to `common.check_chapter_map_freshness`, which excludes cut/merged/archived scenes, so a transition on a cut scene stays an error.
- **`evidence`** is a verbatim quote from `from_scene`'s prose, matched whitespace-tolerantly through `find_anchor` after `strip_markers`. It is what makes a row checkable against the manuscript, so `--state` drops any proposed row missing it.
- **State true in one image only** is not a transition — a tear-streaked face, arms raised against a light. That goes in the plan's `state_override` (`entity:state;entity:state`, split on the **first** colon so a state may contain one), and it satisfies `state_unspecified` just as a real transition does.

**The contradiction audit** — `--audit`, read-only with respect to the prose and the log. Two transitions never disagree with each other, because things are allowed to change; the contradiction is a scene *between* them asserting a state the span cannot support, and only reading prose against the resolved matrix finds it. `visual_state.prepass` runs four deterministic checks and narrows to `candidate_scenes` (scenes mentioning a tracked entity at or after that entity's first transition); the prompt receives the **already-resolved** forward walk so the model never re-derives the `<=` boundary. No findings and no candidates means **no LLM call**, and the report says which — a report that skipped the pass renders "Not assessed", never "None found". **The report never claims coverage it does not have**, because trust is its only product: it names scenes with no prose, scenes whose prose exceeded the per-scene character cap (`_AUDIT_SCENE_CHARS`, logged with both lengths and *excluded from provenance* — the digest covers the whole scene, so recording a partly-read one would keep the unread tail from ever returning as `audit_stale`), and drafted scenes the chapter map omits, which have no reading position and so are never examined at all. Any of those downgrades the clean line to "None found in the prose that was read". A response whose rows were *partly* readable discloses the drop count under Coverage and heads the findings list "Incomplete — N of N+M rows": stdout is not enough when the skill tells the author to read the report first. An unparseable response, or one whose every row was malformed (`parse_audit_response` → `'unusable'`), records no findings — a model that found three contradictions we cannot parse must never render as agreement — and the report file is **truncated to a dated failure stub** rather than left alone, because a leftover "None found" from an earlier run is the same lie with an older date on it.

**`--audit` exits 0 whenever it produces a report, even over a broken log.** It is a report; `--diagnose` and `validate` are the gates and exit 1 on the same `state_unknown_scene`. `skills/illustrate/SKILL.md` carries the consequence: a `state_unknown_scene` in the report means the pass read prose against a matrix that is wrong, so its conclusions are unreliable until the log is fixed, whatever the exit code said. Provenance rows (`scene_id|digest|audited_at`) cover exactly the scenes read, digested via `illustrations.prose_digest` (marker-free + `normalize_for_comparison`), so embedding a marker or reflowing a paragraph does not read as staleness while a real revision does. `--ingest` records the same digest as the plan's `scene_digest`, which is what makes `prose_changed` detectable.

`prepass` is **silent** — it returns `scene_count`, `tracked_entities`, `undrafted_scenes`, `unmapped_scenes`, and `search_terms` and lets the caller report the narrowing, because `validate_plan` calls it too and neither `validate` nor `cleanup` is auditing anything.

**Search terms are only shortened against canon.** `_entity_search_terms` humanizes the whole entity id and adds a shorter form *only* when some prefix of the id is a known `canon_id`. Guessing that the last segment is the aspect looks harmless until you notice which entities are state-only: a lantern count or a lamp's lit/dark state is not a character, location, or motif with an invariant design, so it systematically has no canon file. `village-lights` would degenerate to `village`, and on a village-set book that makes nearly every scene a candidate — one call that cannot run at all, which is worse than a partial read because it is not partial. The term set per entity is returned and logged so a wide narrowing is diagnosable.

**Render order** — `render_order()` puts the **visual key** first: the biggest establisher among the *early* illustrations, not the biggest overall. The climax usually names the most entities because it is where everyone converges, and picking it would be backwards — the key exists so later images have something real to reference, which only works if most illustrations come after it. Everything else follows story order, which automatically locks each entity's design in its earliest appearance. `locks` reports the anchors an illustration is first to show.

**Retiring an illustration** — set `status=superseded` and run `--embed`, which removes its marker. A superseded row also stops resolving into epub/PDF/web even while its file is on disk, so no target ships retired art. **The two targets gate differently, and the difference is load-bearing:** `illustrations.resolve_for_local` (epub/PDF/web) excludes only `superseded`, while `manifest_assets` (Bookshelf) requires `ingested` exactly. `FILED_STATUSES` gates neither — its only consumer is `validate_plan`'s file/digest check, so any claim that it gates a publish target is false. That asymmetry is why **status only ever moves forward**: `--prompts` writes `prompt_file` on any row but sets `status=prompted` only from `planned` / `prompted` / `superseded`. Re-prompting `rendered` or `ingested` art keeps its status and logs that a re-render is pending. Demoting it was a bug, never a legitimate exclusion — it took a live book's publishable set from 20/20 to 19/20 with no warning, invisible to `--diagnose` because an unrendered row is valid in-flight state. Naming a `superseded` row in `--ids` revives it as far as `prompted` (never straight to `ingested` — the replacement render does not exist yet); a bulk run still never touches one.

**The handoff packet** — `--package` assembles `manuscript/illustration-packet/`: `README.md`, `canon.md`, `visual-state.md`, `illustrations.md`, `acceptance.md`, plus `image-prompts/{id}.md` per illustration. (`reference-images.md` was a sixth root file until #306; its list and its disclosures moved into README beside the runbook step they are about.) It replaces fifteen separate prompt pastes with one bundle a long-running generation session works through, which is what the author's lived experience (and GN's #260 conclusion, reached first) says actually works: hyper-detailed leaf prompts underperform, shared reference material does better. Assembly only — **no API calls**, no timestamps, so regeneration over unchanged sources is byte-identical (there is a test, and `run_package` deliberately does **not** call `validate_plan`: its findings would duplicate the gaps and make the README depend on the previous packet's staleness). `packet.py` resolves and validates; `prompts_packet.py` renders.

**It is a render, never hand-edited.** Regenerated wholesale, so an edit is lost on the next run and never reaches the plan; changes belong in the plan, the transition log, or the canon files. `packet_stale` (warning) fires when the packet is older than any of those three — mtime, strictly, so a source written in the same tick as the packet is the `--package` run itself. `is_built` is all five root files or none; a half-written packet is a different problem from a stale one. **`image-prompts/` is written first and `is_built` keys on the root files alone**, so an interrupted run cannot flip it True over a bundle with nothing to upload in it — the window is closed by write order rather than by widening the predicate, because a packet legitimately has no image prompts when the plan has no rows.

**Anchor copies are byte-identical, and that is checked twice on purpose.** `resolve` hands anchors through from `canon.anchor_texts` untouched, and a test compares its output per `canon_id`; a second test compares the **written** `canon.md`, including a long anchor a tidying renderer would rewrap. The first catches a transform during resolution, the second during rendering, and only the second catches a re-wrap — consolidating them looks like removing a duplicate and actually drops the guard on the rendering path. Copies are wrapped in `<!-- canon-embed: id -->` markers, which gives `anchor_copy_drift` a parser it does not have to write (`canon.find_canon_embeds`) and gives that convention its first legitimate *writer* — before this, nothing in the pipeline emitted those markers, so `check_canon_drift` guarded a shape only hand-editing produced. Drift is compared after `normalize_for_comparison`: cosmetic whitespace is not drift, a changed word is. An unclosed marker, an invalid marker id, an anchor whose canon file has since gone, and an unreadable packet file are all reported rather than passing for "no drift".

**The packet never claims coverage it does not have.** `resolve`'s `gaps` is the record — a row with no `beat` (the index renders `packet.NOT_RECORDED`, so thin reads as thin) or no `subject`, rows whose art direction was never written (aggregated `cause -> ids` by `_body_cause_gaps`), a `canon_refs` entry resolving to no populated canon file, an entity with no stated visual state at its scene, a scene that is cut or has no reading position, a book-level canon file absent or still a scaffold (separated, because `--direction` fixes the first and is a no-op on the second), and an audit never run or stale. Every gap is logged as a WARNING **and** written into `README.md`, because the author reads the packet an hour after the log scrolled past. Plan health lives in `--diagnose` instead, which is the gate.

**One root cause, one gap — and the survivor is emitted after resolution, not before.** A `canon_refs` entry resolving to no populated canon file used to emit *two*: the anchor gap and "no transition states its visual state there". `packet._unanchored_gap` is the survivor, and it is built *after* the state walk because what it should say depends on what happened. Asserting it up front produced a falsehood: "no visual state is reported for it either" was unconditional while the suppression was conditional on nothing resolving, so for an unanchored entity that *does* have a transition the entry showed the state and the gap denied it — then condemned the correct row that produced it.

The remedy is likewise two-sided, and both halves have to be offered. `visual_state.prepass` does not consult anchors, so `state_unspecified` still fires for the same row telling the author to add a transition; a gap saying that a transition row "states a change to a design nothing has stated" put two opposite instructions twenty lines apart in one `--diagnose`, which is strictly worse than the duplication the suppression removed. The reason neither remedy can be presented as the only one is the **state-only entity class**: a lantern count or a lamp's lit/dark state has no invariant design, so it has no canon file *by design*, and for those the transition row is right and `--direction` is wrong.

The suppression is keyed on the anchor rather than on "any missing state", so an *anchored* entity with no transition still gets its own gap. Under `include_anchor_gaps=False` (`--prompts`) both are suppressed **for those refs only**, which is correct because `_warn_unanchored_rows` covers them at every coaching level and names the missing anchor rather than a missing transition. The gap section's value is proportional to its signal-to-noise — the same reasoning behind `treatment_at` (#290).

**Stale rows outside the anchor batch reach README.** `packet.stale_render_gaps` adds one aggregate gap (`N of M`, with ids), because a stale row was otherwise marked in its own entry heading and, if it happened to fill one of the four slots, in the batch table — which on a twenty-row book put seventeen of them nowhere in README while the author was told to work the file top to bottom. Aggregated `count → ids` per `_warn_unanchored_rows`: one project-wide cause behind every row means twenty identical sentences, and `--diagnose`'s rung line is likewise a *count* that defers to the findings list for the per-row reasons, since stating both said the same sentence five times for a four-row book.


**`Absent` plus the colour rules are the deliberate exception to positive framing**, narrow and enumerable: named entities that must not appear, and violations of stated colour logic. Orientation and no-text are the other two. Do not widen this into general prohibitions — #263's finding that negated content keywords leak into the render still holds for description.

**The upload file** — `--package` also writes `manuscript/illustration-packet/image-prompts/{id}.md`, one per illustration (#306). This replaced `--export`, which shipped in 1.56.1 and produced a **167 MB directory holding four distinct images**: every one of twenty units got the same reference set, because `_references_for` takes the cover plus the first three non-stale ingested rows. Per-unit reference directories only pay for themselves if the references differ per unit, and structurally they almost never will.

**The governing rule inverted, because the author uploads the file rather than pasting a region out of it.** It was *"mark what must not be pasted"*; it is now **everything in an image prompt is for the model, or it is not in the file**. The export's per-unit file was 13,940 bytes of which **9,500 were seventeen near-identical paragraphs about canon staleness**, all above a paste boundary an upload ignores. Of the five sections that left, two were byte-identical across all twenty files (`## References`, `### About these reference images`) and the other three varied only in a path or a single line — the tell that none of them were per-illustration facts worth a per-unit file. The reference-chain disclosures and the provenance sentence went to `README.md` once, the upload list to README's runbook step, the "Read this first" blockers and the assigned staging to `illustrations.md`.

**Size is a correctness property, not tidiness.** ~2 KB is read into context whole; at 14 KB an upload is near the size where retrieval and summarization begin, and a summarized continuity anchor is a paraphrased one — which defeats the identical-string mechanism the whole canon tier rests on. `prompts_packet.IMAGE_PROMPT_SECTIONS` enumerates the five headings a file may carry and a test asserts the rendered set is a subset, because a regression here uploads canon-staleness prose to an image model and *nothing about the resulting image would look wrong*.

**`## Accept only if` left the upload file, reversing #297's second copy.** #297 put the resolved state in twice on purpose — a Constraints bullet for the model, an acceptance line for the author — and **the paste boundary is what made those two audiences rather than one**. An upload collapses them, so the second copy stopped being a check and became the longest string in the file repeated verbatim, distorting emphasis in a document whose only job is directing a render. `acceptance.md` now says the per-image checks *are* that file's Constraints bullets; the check survives, the duplication does not. #297's reasoning is untouched — the state still reaches the prompt and still outranks the anchors. The **source** prompt file keeps its own `## Accept only if`, because it is author-facing and never uploaded.

**The prompt bodies moved to `reference/illustration-prompts/{id}.md`** (`ill.PROMPTS_SUBDIR`; `LEGACY_PROMPTS_SUBDIR` is the pre-#306 path, read only by `cmd_migrate.step9_move_illustration_prompts`). `manuscript/assets/illustrations/` holds illustrations. **A body cannot live only in the packet**: it is the output of a paid API call, and the packet is a render — regenerated wholesale, byte-identical, safe to delete and safe to gitignore. Putting non-reproducible output inside a directory documented as disposable is how it gets lost. The migrate step **moves, never copies**: two bodies for one illustration, one of which `--package` reads, is the divergence this change removes. A destination collision is reported and left alone, and a `prompt_file` cell naming something else is untouched — an author who typed a path meant that path.

**The two-file split stays and is load-bearing.** `--package` recovers the body via `pi.parse_prompt_file` and re-derives the Constraints from the plan. There is no `prompt_stale`, so a source file written before a matrix edit still carries the old state; the upload carries the state in force *now*, and a file containing both would contradict itself. Everything `export.py` knew about recovering a body — `_body_for`, `_derived_body`, the declared-but-missing case, `body_truncated` — moved to `packet.py` with its branches unchanged; the warning strings were rephrased for the new artifact, and `_derived_body`'s headings promoted from `###` to `##` so a plan-row stand-in matches the `## Constraints` the renderer appends.

**`illustrations.md` stopped describing images and became the index.** It used to carry an 80–120 word entry per row derived from the plan, while `--prompts` separately paid for a 250–400 word body the packet ignored and merely pointed at — two renderings of one row, which is exactly what #297 was filed about. It is now a table (reading order, scene, aspect, `Art`, staging, beat) plus a **Before you upload** section carrying only rows with something to say: `Re-render`, thin art direction, the self-reference note, an unresolved visual state. **`render_entry` and the 80–120 word budget are deleted.** The budget existed to stop the renderer restating what the shared sections said; there is one rendering of a row now, so there is nothing to restate. This *narrows* #297 rather than closing it: within one run `--prompts` and `--package` resolve state through the same `state_for_row` / `contrast_for_row` and cannot disagree at write time, while across runs they still can — there is no `prompt_stale`, and `--package` re-deriving the Constraints is what keeps the upload current regardless.

**The self-reference note replaces an exclusion the book-level list cannot make.** `_references_for` excludes a row from its own chain, because re-rendering an illustration with its own previous version in front of the model is how a re-render reproduces what it was meant to replace. One list uploaded once cannot do that, so `packet._self_reference_note` tells the author instead. Deliberately author-facing: phrased for the model it would be a negation, and the exceptions to positive framing stay enumerable at four (`absent`, colour logic, orientation, no-text).

**A markdown table cell is a new injection surface.** `prompts_packet._cell` escapes `|` and collapses newlines — an unescaped pipe in author prose shifts every later column left and drops the last, which is `common.csv_safe`'s failure mode in a different renderer.

**`--anchor-batch` retired with `--export`** (it was refused without it, and the batch is in README regardless). `--export` is a stub exiting 2 with a pointer, kept for one version so the flag produces a sentence rather than a bare argparse error. `illus_export_stale` left `cleanup` and `validate`, and `anchor_copy_drift`'s two-tree walk dropped back to one.

**`packet_stale` reports three things, and says when it can report none.** A packet older than the plan, the transition log, a canon file, **or a prompt body** — resolved through each row's `prompt_file` cell rather than by listing `reference/illustration-prompts/`, because an unmigrated project and a declared path elsewhere are both supported and a directory listing saw neither. An image prompt **missing for a live plan row**, which mtime cannot see: `is_built` keys on the root files, and on a *rebuild* those already exist, so a failure inside `_write_image_prompts` (which clears before it writes) left `--diagnose` printing "built and current" over the directory the author was told to upload from — the write-order argument only ever covered a first build. And when the walk itself fails, **unknown rather than current**: two unguarded `os.listdir` calls raised `PermissionError` straight out of `validate_plan`, the single finding collector, which is the `ill.sha256_of` regression (#298) reintroduced. What it still does **not** check is an image prompt's content against what `render_image_prompt` would produce now, so a hand-edit of a file documented as a render goes undetected — stated in the docstring rather than left for the silence to imply otherwise.

**An illegal plan `id` is refused before anything is written**, and this survived the retirement of `run_export` only because it was moved. `ill.illegal_plan_ids` runs in `run_package` before `resolve`; `packet.image_prompt_file` raises as the un-bypassable backstop; and `_write_image_prompts` resolves every path *before* it removes anything, so even a caller that skipped the gate cannot get past the delete loop. Length is bounded in `illegal_plan_ids` and not in `_ID_RE`, which is shared with the marker regex: a 300-character id is a legal marker and an `OSError` at `open()`, inside the same post-deletion window. `run_package` skipping `validate_plan` is a *reporting* argument and was never a reason to skip the one check whose absence is destructive.

**Exclusion notes aggregate by `ill.stale_render_kind`, not by the sentence.** `stale_render_reason` interpolates the row's own `ingested_at`, so keying on its prose gave one group per ingest date — twenty renders across a working session became one near-identical note per day, the shape the aggregation removes, rebuilt by the choice of key. Each kind gets its own plural clause (`_STALE_KIND_CLAUSES`, asserted total over the Literal), because splicing a clause written about one row into a plural frame produced "17 illustration(s) are not listed — **its** `ingested_at` is empty". A test asserts a kind is non-empty exactly when a reason is.

**A superseded export directory is reported, never deleted.** It is 167 MB on the book this was filed about, so an author wants it gone — but a command that removes a directory it did not write, on a path the author may have put files under, is the destructive shape this pipeline has been bitten by before.

**Reference images are never copied** into the packet; README's runbook step carries project-relative paths, because a copy is a second thing to invalidate — **and because the author frequently works from a machine other than the one holding the repo**, so a gitignored copy would be the one part of the bundle that does not travel while `manuscript/assets/**` is tracked and already there. The list comes from `--prompts`' own `_references_for`, so the packet inherits the canon-gated exclusions rather than growing a second chain — and `_references_for` takes an optional `notes` out-list so those exclusions are *rendered* under "Read this before you upload", not merely logged. **Those notes aggregate by reason, not by row** (`excluded_stale` is keyed on the `stale_render_reason` string, so two different reasons stay two notes and neither loses the half of the sentence that says what to fix); emitted per row they were the seventeen paragraphs #306 was filed about. The per-file WARNING logs stay per-file — "every exclusion is logged" is a stated invariant, and a log is not the artifact whose signal-to-noise is the feature. That matters more than it looks: with every prior render excluded as pre-canon the list shrinks to the cover, which reads identically to a book where nothing has been rendered yet, and the author then uploads the cover alone and generates the rest with no likeness reference. Cover-only-with-ingested-art is also a README gap. The four-image cap (`_MAX_REFERENCES`) is disclosed too, and is checked *after* the exclusion checks so a stale render past the fourth reference is not hidden behind a cap that is not why it was dropped.

**A rendered row is marked as one.** `Entry` carries `status`, and `illustrations.md`'s `Art` column reads `done` / `to render` / **`re-render`** via `_ART_CELLS`. The documented flow renders the anchor batch, ingests it, and regenerates, so the normal mid-flight packet mixes finished and pending rows while the author works the index top to bottom — identical cells would have them re-rendering finished art. `Entry.status` is typed `PlanStatus`, and `_RENDERED_STATUSES` is enumerated *positively* so an out-of-vocabulary value falls toward pending: reading a row that needed no reading costs a glance, while skipping one because a typo made it look finished loses an illustration from the book.

**"Rendered" means rendered *from the current canon*, and `status` cannot answer that.** `illustrations.stale_render_reason` is the one predicate — an `ingested` row whose `ingested_at` predates the newest `canon_updated` (empty and unparseable both counting as pre-canon, for the reason the reference chain does) needs a re-render. `packet.needs_render` maps id → reason over reading order, and `Entry.stale_reason`, `_render_batch`, `_report_anchor_batch`, `_report_packet_rung`, `ill.next_to_render`/`plan_report`, and `--diagnose`'s render-order marks (`~` canon-stale, `*` current, blank for no art) all read one of those two. `plan_report.ingested` stays a literal count of the column, because that is what publishing gates on; `awaiting_render` is **not** its complement — a row can be both filed and canon-stale.

**Three states over two levels, read through one function.** `packet.render_state(needs, id)` returns `done` (absent from the mapping) / `pending` (`''`) / `stale` (a reason), and `ids_in_state` narrows and deduplicates — the anchor batch's darkest and brightest can be one illustration. Five hand-written copies of that discrimination is five chances to spell `needs.get(id)` where `id in needs` was meant, and *that* misreading collapses `pending` into `done`, which is #300 at the one call site (`_report_packet_rung`) that is a go/no-go on a paid render run.

**Silence must mean "checked and current", never "could not check".** With no parseable `canon_updated` anywhere the predicate returns `''` for every row and every downstream signal renders exactly as it does for a genuinely current set — #300's output from the code that fixes #300, and the shipped canon templates carry `canon_updated: TODO`. So `illustrations.staleness_unchecked_finding` says so out loud, in `--diagnose`, in `validate`, in `cleanup`, and in the packet's README gaps. It requires canon to *exist*: a project that has never run `--direction` has nothing for its art to be stale against, matching `cmd_cleanup.report_canon_files`' guard. This is `--audit`'s "Not assessed" rather than "None found", and `style_reference_warnings`' policy for the same missing cutoff — which does not cover it, because that returns early when no cover artwork resolves and speaks only about the cover when it does.

**Both kinds are findings, so `cleanup` and `validate` see them.** `canon_stale_render` (per row) and `canon_staleness_unchecked` (one, carrying `file: reference/canon/` since its fix is not in a plan row) — placed with `prose_changed` and `audit_stale`, which are the same shape, "this ingested render is out of date relative to its source". Both **warnings**: canon-stale art still ships and still reads correctly, so blocking would take a working book offline over a re-render the author may be deferring, and the entire point is that this fact and publishability are separate. Before this the signal existed only as log lines, so `working/cleanup-report.csv` — the durable artifact `skills/forge/SKILL.md` scans — never mentioned that a book's whole set needed re-rendering.

**One canon-tree walk per run.** `canon.newest_canon_updated` logs a WARNING per file with an unparseable `canon_updated`, so N walks read as N broken files. `--package` walked five times and `--diagnose` twice; the cutoff is now read once in `run_diagnose`/`run_package` and threaded through `resolve` → `state_context` / `_packet_references` / the style reference, plus `needs_render`, `plan_report`, and `validate_plan`. `resolve` also resolves the style reference *once* and hands it to both the reference list and the gaps. There is a test on the walk count, because the parameters that prevent this existed and went unused. Before this the batch was a bare status check, and a run **contradicted itself out loud**: `_references_for` excluded all twenty of *The Lantern Folk*'s ingested renders as pre-canon and logged twenty WARNING lines, while the batch table reported four of the same images `Rendered: yes`, every entry said `ingested — do not regenerate`, and `--diagnose` said "ready to hand over". A session working that packet top to bottom would have regenerated nothing, skipped phase 1, and run the churn against a cover-only reference list — the exact failure the two-phase order exists to prevent (#300).

**The fix is a stated reason, deliberately not a `status` demotion.** Demoting to `prompted` was the working workaround, and it makes the packet honest by dropping the row from the Bookshelf publish manifest while the epub, the PDF, and the web book keep shipping it — a *split* penalty, not a clean one, and worse than losing all four: the editions then disagree about art the author believes they retired. (The first version of this section claimed all four targets, which is false; see "Retiring an illustration" for which gate is which.) Needing a re-render and being publishable are different facts with different homes now, so a canon-stale row keeps shipping while the packet says `re-render` and names why. `prompts_packet._entry_state` returns one of `done` / `pending` / `stale`, so the three marks are mutually exclusive structurally rather than by if-ordering; `STALE_MARK` and a `**Re-render.**` line replace `DONE_MARK`. That line pushes a spec-length entry from 116 to 152 words, which is why it has a *measured* bound (`test_the_re_render_note_costs_only_its_own_lines`, ≤40 words, body byte-identical) and the budget sweep runs over `pending` entries — a docstring claiming an exemption the test did not grant was a latent failure waiting for the first stale spec-length entry. `rendered` status is never judged: it means a file exists Storyforge has never seen, so it carries no `ingested_at` and there is no date to compare — the same *gate* `_staging_postdates_render` uses, though the opposite policy on a missing date.

**`treatment_at` is why the treatment-order gap is trustworthy.** `--sequence` stamps the ISO date it staged a row, and the gap fires only when that date is strictly later than `ingested_at` — the render then genuinely does not follow its treatment. A missing or unparseable stamp says **nothing**: an unstamped legacy row, or a treatment the author wrote by hand (which `--sequence` never stamps, because it never overwrites one), is not evidence of a problem. The first cut had no stamp and could only report "the packet cannot tell which came first", which on a 12-row book staged in the documented order produced 12 of 14 gaps — 86% noise in the one section whose credibility every other disclosure depends on. A gap channel that cries wolf is worse than the silence it replaced, because it teaches the author to skip the section where the real warnings live.

**A blank `state` cell is a gap, not a silence.** `read_transitions` requires only `entity`, so a row with an empty `state` is admitted — and it *matches* a `canon_refs` entry, which suppressed the "no transition states its visual state there" gap and then rendered as nothing. Half-filling the matrix was therefore strictly worse than not filling it, because it deleted the warning telling you to finish.

**The anchor batch** — four slots, derived on every read and never stored so it cannot disagree with the plan: **establisher** (the visual key from `render_order`), **darkest register**, **brightest register**, and **later-state exemplar** (the illustration showing the most entities in a state later than their first, ties to the earliest position; it counts only entities the row's `canon_refs` name, since an image can lock a changed wardrobe only if the wardrobe is in it). Phase 1 of the handoff renders and approves these, so the churn references four real images instead of four descriptions.

**A guessed slot is disclosed, in the packet and in the log.** Nothing populates `register`, so on most projects darkest and brightest fall back to the first and last illustration in reading order — and `fallback` says so, along with an unfillable slot and a batch that brackets nothing (both extremes resolving to one row). A silent guess about which image is the darkest in the book is how an author discovers at image twenty that nothing is.

**An empty establisher slot names the horizon when the horizon is the reason, and summarises rather than enumerates.** The visual key is chosen from the first `ill.visual_key_horizon(row_count)` illustrations in reading order, so a plan whose early rows name no `canon_refs` and whose later rows do got "no illustration names a continuity anchor in `canon_refs`" — flatly false about that plan. `packet._no_establisher_note` keeps the plain wording when it is true and otherwise names the horizon, how many later rows do name anchors, and which. The horizon is a deliberate constraint (the key exists so the images *after* it have something real to reference, which the climax cannot do), so the wording changed and the selection did not; the horizon comes from one function so the number the disclosure names is the one the selection used (#290). `packet._and_more` bounds the id list at three plus a count: on a twenty-row book the horizon is six, so filling `canon_refs` from the middle outward leaves fourteen ids, and fourteen backticked ids mid-sentence is what makes a `fallback` note skippable — these notes are the only disclosure channel for a guessed or unfillable slot, so their readability *is* the feature.

**The batch is reported at most once per run.** `run_package(report_batch=…)`, wired from `main` as `not args.diagnose` — `--diagnose` owns the report when both are asked for. `main` early-returns on `--diagnose`, so that argument is provably always True today and the parameter exists anyway: without it, removing that early return silently starts printing the batch twice, and nothing in the duplicated output points back at where the second copy came from (#290).

**The sequence pre-pass** — `--sequence`, one cheap call that sees every row's beat, layout and register (never the scene prose) and assigns each a `treatment` along five axes: camera distance, camera height, time of day, how much of the frame the subject occupies, interior versus environmental. The evidence is measured: of twenty renders on the real book, four were the same shot of the same two figures, because twenty independent calls cannot see each other. **Not** one call that writes all the prompts — that regresses retry granularity (one failure becomes twenty), output quality (a long response gets terser toward the end, so the last illustrations get the worst prompts), and parsing (one malformed heading eats several prompts). An author-written `treatment` is never overwritten (a disagreeing proposal is logged, not dropped silently), and **duplicate treatments across rows are reported** — variety is the whole purpose, so a repeat defeats the pass while both prompts still look fine. `treatment` is in `OPTIONAL_PLAN_COLUMNS`, feeds `build_art_direction_request` as a requirement rather than a hint, and renders in the packet entry. `--sequence` runs before `--prompts` in the phase order for exactly that reason.

**Sequence review** — `--review` writes `working/illustration-sequence-review.md`. Per-illustration validation passes on images that are individually fine and collectively inconsistent; only the set shows drift (a character an inch taller in image nine, light brightening where the story darkens). Reviewing before the set is complete is the cheap moment, because every later illustration references the earlier ones.

**The marker** — `![[illus:{id}]]` on its own line in `scenes/{scene_id}.md`. Deliberately *not* a markdown image: one marker resolves three ways, and a literal `![](path)` would be right for exactly one target.

| Target | Resolution |
|--------|------------|
| epub / PDF / HTML | Markdown image with a **project-relative** path; every pandoc call passes `--resource-path <project_dir>`. Relative rather than absolute so git-tracked chapter files stay portable. |
| Web book | Files copied to `output/web/illustrations/`, `src` rewritten. |
| Bookshelf manifest | Marker **stripped** from `content_html`; emitted instead as per-scene `illustrations: [{key, after_paragraph}]` plus a book-level `assets` array (metadata only, no bytes). |

**The load-bearing invariant:** illustrations must never add anything to `content_html`. Bookshelf derives highlight offsets from the scene's visible text (`htmlToVisibleText`), so any visible insertion — a `<figcaption>` is the obvious temptation — shifts every downstream offset in that scene and silently re-anchors or orphans real reader highlights. Captions live in asset metadata and the reader renders them. `tests/test_illustrate_cmd.py` asserts the manifest's `content_html` and `word_count` are byte-identical with and without illustrations, across all four placements; do not weaken that test.

**`after_paragraph` counts top-level `<p>` elements only** — a paragraph nested in a blockquote is not a placement boundary. This is a *contract* with benjaminsnorris/bookshelf#12, which is not yet implemented: the reader must walk the scene container's direct children for the offsets to line up. If that repo counts descendants instead, every `after_paragraph` shifts.

**Markers are never prose.** They are stripped at every deterministic scorer entry (`scoring_passive/adverbs/weather/rhythm/economy`), in every `prose_analysis` detector, at the scene loads feeding `score`'s evaluator and fidelity prompts, and from the publish manifest's `word_count`. `strip_markers` is byte-identical to the un-illustrated prose for every placement, which is what lets the scorer tests assert equality. A marker scored as a sentence perturbs rhythm variance.

A revision pass *does* see scene text, and a model has no reason to reproduce a marker — so `cmd_revise` runs the rewritten prose through `illustrations.preserve_markers`, restoring what the rewrite dropped and reporting what it could not re-anchor. `cmd_enrich` and `cmd_revise` write `scenes.csv:word_count` through `illustrations.count_prose_words`. **Not yet covered** (#278 follow-up): `repetition.py` and `cmd_evaluate.py` still read scene text raw — a marker can become a cross-chapter n-gram candidate, and the 6-evaluator panel sees it.

**Art direction** reuses the GPT Image 2 principles from #260/#263 (adapted — the GN "one prompt renders the whole page" rule does not transfer, and is replaced by the orientation directive): the 5-section OpenAI template — of which the model is asked for the first **four** (Scene / Subject / Important details / Use case) because `render_prompt_file` appends the Constraints block deterministically, and requesting both produced a `## Constraints` with a nested, contradicting `### Constraints` — reference images carrying style and likeness (cover art plus prior ingested illustrations — that chain is what makes a book's art cohere), an **identical** character-anchor string everywhere a character appears (authored up front as an entity canon file under `reference/canon/{characters,locations,motifs}/`, appended to but never revised once a rendered illustration has used it), positive framing over negation, and an explicit orientation directive. Aspect comes from `layout` first (`double_page` → landscape), then from a `landscape` / `square` mention in the row's `composition`; portrait otherwise.

**The resolved visual state reaches `--prompts`, and it outranks the anchors.** `build_art_direction_request` takes `state` / `absent` / `contrast`, and `cmd_illustrate.run_prompts` fills them from `packet.state_for_row` and `packet.contrast_for_row` — **the same functions `--package` calls**, over a `packet.state_context` read once per run. That sharing is the fix, not an optimization: the matrix was wired into the packet and not into the request, so a prompt file and the packet entry built from one row disagreed about the same costume in both directions (#297). An anchor necessarily describes the whole book, so no anchor can say which night *this* image is; worse, an emphatic anchor clause ("the jacket is how the reader finds him in a dark image", added after a sequence review) actively pulls a night-one image into the night-two coat. So the block is worded as a requirement that **outranks the character anchors** — anything softer loses to a paragraph of vivid prose. `state_override` wins over the forward walk exactly as in the packet, and `absent` renders as an explicit exclusion (one of the two *content* exceptions to positive framing, with the colour logic; orientation and no-text are the other two, and are about form rather than content — four in total, per the spec and `packet._self_reference_note`). `--prompts` passes `include_anchor_gaps=False` because `_warn_unanchored_rows` already reports that same finding before the fan-out — and that warning runs at **every** coaching level for exactly this reason. It was gated on `needs_api` while the suppression was unconditional, so under `--coaching strict` the accurate finding vanished and `state_unspecified` fired in its place, telling the author to add a transition row when the fix is to author the canon anchor. The remaining state gaps are aggregated `gap → ids` after phase 1 (the `_warn_unanchored_rows` pattern — one untracked entity across twenty rows was twenty near-identical lines), and a closing line counts the rows carrying no resolved state. The state lands **twice** in the prompt file for the reason orientation does: as a deterministic Constraints bullet the image model reads, and as the spec's per-image acceptance lines in `## Accept only if`, which prompt files did not carry. Hand-editing a prompt body to correct a costume — the working fix on the real book — makes the file no longer reproducible from the plan. **A state that did not resolve is stated, not omitted**: omitting it left Constraints byte-identical to a pre-#297 file and an acceptance block announcing "checked against this illustration's row" while dropping the only check #297 was filed about, so `## Accept only if` always renders and says when nothing resolved — `packet.NOT_RECORDED`'s reasoning applied to the artifact read on the same timescale. It is marked *do NOT paste*, following the GN page renderer, because it sits after "paste everything below" and can name another illustration by id via `contrast`.

**The sharing holds within one run, not across runs.** A prompt file is a render like the packet, but there is no `prompt_stale` — editing the transition log after `--prompts` diverges the two silently, so re-run `--prompts --ids …` after editing the matrix. `packet.state_context` takes the caller's plan (the **whole** plan, never the `--ids` subset, or the single row becomes its own book-start), and `contrast_for_row` distinguishes a row *absent* from `predecessors` from the first illustration in the book: reading order excludes `superseded` while `--ids` deliberately revives one, so a `.get(id, '')` default gave the revived row no contrast clause while the packet built after ingest had one.

**The style reference is declarable and staleness-checked.** `cmd_illustrate.resolve_style_reference` resolves the cover *artwork* every prompt inherits as house style: `production.cover_artwork` first, then the `manuscript/assets/cover-illustration.{png,jpg,jpeg,webp}` convention. Deliberately **not** `production.cover_image`, which names the file that *ships* — on a real book that is the composite with the title typeset into the raster, and feeding baked-in lettering to a prompt whose own constraints say "no text, no letters, no words" is a wasted generation. Before the key existed, a project with four cover variations had exactly one filename that counted, chosen by convention, and twenty prompts inherited a cover the author had explicitly rejected while nothing in the log named the file (#299). So `--prompts` logs the resolved path **once per run, before any call**, with its symlink target — a symlinked convention filename is the documented workaround for several variations, and the target is the name the author recognizes. The reference is checked against the newest `canon_updated` by mtime (`canon.predates_canon`, the one comparison the ingested-render check now shares) and a stale one is a WARNING, never an exclusion: under `--no-prior-refs` it is 100% of the style signal, which is why `resolve_style_reference` computes its own cutoff instead of taking `_reference_cutoff`'s — that returns `''` under exactly that flag, so inheriting it would leave the highest-stakes run the only unchecked one. Unlike an empty `ingested_at`, an unreadable mtime is *not* stale: there is no bookkeeping column here for a file to predate. `describe_style_reference` (the headline) and `style_reference_warnings` (the problems) are split because the packet's "What is not in that list" section must carry only problems — a positive resolution line there reads as an exclusion. **Every way the reference can be wrong or unverified produces a warning**, including the two that yield no verdict: no parseable `canon_updated` anywhere, and an unreadable mtime. Both used to read as checked-and-fresh, and `--no-prior-refs` skips the line that used to mention the first — a silent *unchecked* reference is #299 with a smaller blast radius, and `--audit` renders "Not assessed" rather than "None found" for the same reason. A declared path is extension-checked (a `production/cover.svg` compositing source is the realistic miss) and relativized when it names a file inside the project, because it reaches git-tracked prompt files and the packet, whose contract is project-relative paths. A dangling symlink at the convention path is reported as such rather than as "no cover artwork — add this file", which would name a file visible in `ls`. `--prompts` **refuses before spending** when the declaration names a missing file: unlike staleness that is unambiguous, and warning-then-spending-then-exiting-0 is what the skill commits on. The problems also reach `--diagnose` (the health gate), `--dry-run`, and the packet's `gaps` — the last unconditionally, since a stale cover on a book with no ingested art failed the `_has_ingested_art` composite and appeared in no log line and no README gap. The extension list is **not** behaviour-neutral: a jpeg-only project resolved no cover before and now gets the cover plus three priors rather than four.

**The reference chain is canon-gated.** A prior ingested illustration is a style reference only if its `ingested_at` is on or after the newest `canon_updated` in `reference/canon/`. Art rendered before the canon that now governs it was directed by rules that no longer apply, so feeding it back teaches the new render the drift the canon was rewritten to remove — and because the visual key renders first, a whole set inherits it. An **empty** `ingested_at` counts as pre-canon (the column postdates the schema, so "unknown" is not a reason for optimism). Every exclusion is a WARNING naming the file and why; a cover-only or empty chain is said plainly rather than emitting a quietly-short reference list. With no parseable `canon_updated` anywhere, nothing can be judged stale and the chain is unfiltered. `--no-prior-refs` is the explicit rebuild switch.

**Anchors are inputs, not residue.** `--prompts` builds every request before the first call goes out, so a canon stub a model proposes mid-run is written after all of them and reaches no other prompt in that run. Twenty rows with no anchor for one character therefore invent her twenty times: the first stub wins the canon file (`append_anchor_stubs` never revises an existing anchor) and the other nineteen prompt files disagree with it. `_warn_unanchored_rows` runs before the fan-out and names the rows plus the missing ids, because that is the only moment the author can fix it for free; the post-hoc stub log names the `--prompts --ids …` re-run for the rows that missed the new stubs. `append_anchor_stubs` is a fallback for canon that does not exist yet, never the intended path — authoring anchors up front avoids the situation entirely. (Before the fan-out the anchor set was re-read per row, so intra-run propagation worked by accident.)

**Anchors are labeled, matched by id.** `canon_id` stays the matching key for `canon_refs` and for the anchor dict; the prompt *renders* a display name — `display_name:` frontmatter, else the registry `name`, else the title-cased slug (reported, since it is a guess). A slug-labeled anchor got the slug echoed back in the model's prose.

**Plan writes are LF.** `write_plan` passes `lineterminator='\n'` to the csv writer, whose default `'\r\n'` turned every one-cell edit into a whole-file diff and produced exactly the state `cleanup`'s `crlf_line_endings` check flags. Opening the file with `newline='\n'` does not fix this — the writer emits the terminator itself. Same one-line fix applied to `elaborate._write_csv` and `history.append_cycle`, the other two `csv.DictWriter` call sites; `csv_cli` writes `'\n'` by hand and was always fine.

**Rendering happens outside Storyforge.** The command emits prompts; the author renders and `--ingest` brings files back. Files match plan rows by filename stem — an unmatched file is reported, never guessed at.

**Ingest fails safe.** A truncated file — what an aborted render download leaves — is refused before anything is written, because `image_dimensions` reads 32 bytes and would report plausible dimensions for a header-only stub. Files are copied via a temp path and `os.replace`, so an interrupted copy cannot destroy the previous render, and a legitimate replacement is logged with both shapes.

**Unrendered is valid in-flight state**, not a finding — same posture as GN page renders (#261). `cleanup` reports genuine incoherence under "Interior Illustrations" (`illus_orphan_marker`, `illus_missing_file`, `illus_orphan_file`, `illus_anchor_drift`, `illus_duplicate_marker`, plus row-level schema problems) and the visual-state kinds (`illus_state_unknown_scene` — the only error of the seven — plus `illus_state_unmapped_scene`, `illus_evidence_not_found`, `illus_state_unspecified`, `illus_state_mid_scene_change`, `illus_prose_changed`, `illus_audit_stale`) and the illustration's position within its scene (`illus_prompt_spoils_unread`, #308) and the packet kinds (`illus_packet_stale`, `illus_anchor_copy_drift` — both warnings, since the packet is a render and either is one `--package` away) and `illus_canon_anchor_truncated` (blocking: a canon Embeddable block cut short by a `##` heading inside it, so every prompt embeds a shorter anchor than the file appears to hold — #293); `validate` fails on the blocking ones and warns on drift.

**Finding-name convention:** `IllustrationFindingKind` members (`illustrations.py`) are bare — `orphan_marker`, `missing_file`, `direction_anchor_mismatch`, etc. `cmd_cleanup.py`'s `_check_illustrations` prefixes each with `illus_` when building the report (`f'illus_{kind}'`), which is where every `illus_*` name above comes from. Adding a new kind already spelled with the prefix (`illus_foo` instead of `foo`) renders as `illus_illus_foo` in the report — declare kinds bare and let `cmd_cleanup` add the prefix.

**Bookshelf side:** benjaminsnorris/bookshelf#11 (content-addressed `book_assets` + digest-diff upload; the cover migrates onto it) and #12 (reading experience). The `assets` / `illustrations` manifest shape is the interface between the repos — keep them in sync.

**Publishing image bytes** (#284) is a three-step contract, and Storyforge long implemented only the third — an illustrated book failed at `assets_missing_bytes` before chapters were written:

1. `POST /api/books/{slug}/assets` — declare every asset's digest; receive the ones whose bytes are missing plus a signed upload URL each.
2. `PUT` those bytes to the signed URLs. Keeps image size out of the publish route's budget, and unchanged art costs zero bytes on re-publish.
3. `PUT /api/books/{slug}` — the metadata-only manifest.

Steps 1 and 2 live in `bookshelf.py` (`negotiate_assets`, `signed_upload_target`, `upload_asset_bytes`, `sync_assets`) and are **role-generic on purpose**: `sync_assets` takes the asset list and a digest→local-path map *from its caller* and never reads `illustration-plan.csv` or branches on `role`. `cmd_publish` owns resolving digests to files; `assembly.generate_publish_manifest` writes that map to `working/publish-asset-sources.json` from the same pass that computed the digests, so uploaded bytes always match the declared digest. Chunk at `MAX_ASSETS_PER_REQUEST` (200); upload concurrency 8, matching the endpoint's `SIGN_CONCURRENCY` against a 30s `maxDuration`.

The **signed-URL call shape** is the one part read out of Supabase rather than bookshelf: `createSignedUploadUrl` returns an **absolute** `signedUrl` with the token already in the query string, and that token — not the caller's JWT — is the whole credential. `signed_upload_target` isolates it; do not inline that call shape anywhere else.

**Assets must never ship without a cover.** Bookshelf derives `books.cover_image_url` from the `role: 'cover'` asset and treats a manifest declaring *any* assets as authoritative about the cover — so an assets array with no cover entry nulls the column and **publishing illustrations deletes the live book's cover**. `assembly.require_cover_asset` refuses that manifest; it is a refusal, not a warning, because the loss is silent on the reader side. `cmd_publish` re-checks the manifest it reads back — not against a hand-edit of `working/publish-manifest.json`, which regeneration overwrites, but against a bypassed generator. An empty `assets: []` is never emitted either — `Boolean([])` is true in JS, so the server would read it as a removal.

The cover is a **second source path into the same array**, not a plan row: resolved explicit path → `production.cover_image` → autodetect `production/` then `manuscript/assets/`, restricted to the extensions the bucket accepts. The YAML field beats autodetect because a project can hold a `production/cover.svg` compositing source next to the rendered PNG that ships. `cover_base64` is retired; `--cover` is a deprecated no-op and `--no-cover` is the escape hatch for a book with no assets. Extensions normalize `jpg`→`jpeg` on this side too — the storage path is `{digest}.{extension}`, so two spellings would give one image two paths.

## PR Review Workflow — MANDATORY

When the user asks for "the 5-agent review" or after creating a PR, run **all five** specialized review agents **in parallel** (single message, multiple `Agent` tool calls). The five agents are:

1. `pr-review-toolkit:code-reviewer` — bugs, project-convention violations, schema mismatches
2. `pr-review-toolkit:pr-test-analyzer` — uncovered branches, missing behavioral assertions, mock-helper fragility
3. `pr-review-toolkit:silent-failure-hunter` — error swallowing, missing WARN logs, regressions of patterns earlier reviews fixed
4. `pr-review-toolkit:type-design-analyzer` — TypedDict shape, Literal narrowing, invariant enforcement
5. `pr-review-toolkit:comment-analyzer` — docstring drift, over-commenting, rubric vs implementation lies

**Run them in the background.** Each completes async; acknowledge each briefly when it lands ("X analysis in: N findings"). Do NOT start fixing until the user explicitly says to (typically "fix all of them in logical commits") OR all five have reported in.

**Each prompt must be substantive.** Specify the PR's risk areas by name, reference prior-tier reviews of related code (so the agent doesn't rediscover the same patterns), and quote project conventions from this file. Terse prompts produce shallow agent work — these prompts have repeatedly caught real bugs.

**After all five report in**, consolidate into a single punch list (CRITICAL / HIGH / IMPORTANT / SUGGESTIONS) ordered by severity, deduplicated across reviewers. Show the list to the user. Wait for "fix all of them in logical commits".

**Fix in logical commits**, typically 4-6:
- Commit 1: CRITICAL bugs first (often the code-reviewer's CRITICAL + silent-failure HIGH together)
- Commit 2: Type tightening (the type-design IMPORTANT items)
- Commit 3: LOW silent-failure + comment cleanup
- Commit 4: Test gaps (close every uncovered branch the test-analyzer flagged)
- Commit 5: Version bump + any code-reviewer follow-ups

Every commit must include:
- The fix(es)
- A regression test for each fix (per the project's regression-test memory)
- A descriptive message naming each finding addressed (CR-N from code-reviewer, SF-N from silent-failure, TD-N from type-design, T-N from test-analyzer, C-N from comment-analyzer)
- Immediate `git push` (per the always-commit-and-push memory)

**Trust but verify.** The review agents have surfaced real bugs every round — but they've also occasionally been wrong (e.g., the f-string brace-escape finding in PR #238 was a false positive). Read the agent's reasoning, verify by checking the code, and document false-positives explicitly so a future agent doesn't reintroduce them.

After all fixes land, the user typically asks to "merge it and pull main" — use `gh pr merge N --merge --delete-branch` (regular merge, not squash, per the no-squash-merge memory).

## Commit Message Prefixes
Use domain-specific prefixes:
- `Draft scene:` / `Develop:` / `Voice:` / `Evaluate:` / `Revision:` / `Produce:` / `Review:` / `Title:` / `Press kit:` / `Cover:` — for book project work
- `Elaborate:` — elaboration pipeline stages
- `Extract:` — reverse elaboration from prose
- `Score:` — scoring cycles
- `Polish:` — prose polish passes
- `Enrich:` — metadata enrichment
- `Visualize:` — dashboard generation
- `Add` / `Update` / `Fix` / `Remove` — for plugin development
- `Bump version to X.Y.Z` — version bumps

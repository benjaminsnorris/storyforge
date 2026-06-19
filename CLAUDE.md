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
- Use `concurrent.futures.ProcessPoolExecutor` for parallel execution via `storyforge.runner`
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
- `run_parallel(items, worker_fn, max_workers, label)` — ProcessPoolExecutor parallel execution
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
- `reference/story-summary.md` — four sections: `## Logline` (1 sentence), `## Synopsis` (1 paragraph), `## Act-shape` (3 paragraphs, one `### Act N` each), `## Theme` (2-4 sentences). Per-section `_updated` timestamps in YAML frontmatter feed cascade drift detection. `## Logline` is canonical; `storyforge.yaml:project.logline` is deprecated as an input.
- `reference/outline.md` — read-only render of the expanding outline. Three numbered sections (Spine / Architecture / Scenes), each populated from the `summary` column of the corresponding CSV. Sync regenerates this file on every commit; authors edit summaries in the CSVs.

**Structural-anchor tier — each its own discrete CSV:**
- `reference/spine.csv` — 5-10 irreducible events (id, seq, title, summary, function, part). `summary` is a single sentence — what happens in this event.
- `reference/architecture.csv` — 15-25 anchor scenes (id, seq, title, summary, part, pov, spine_event, action_sequel, emotional_arc, value_at_stake, value_shift, turning_point). `summary` is a single sentence; `spine_event` is required and references `spine.csv:id`.

**Manuscript tier:**
- `reference/scenes.csv` — structural identity (id, seq, title, summary, part, pov, location, timeline_day, time_of_day, duration, type, status, word_count, target_words, target_pages, panel_count, page_count, architecture_scene). `summary` is a single sentence describing what happens; `architecture_scene` is optional and references `architecture.csv:id` (empty for purely interstitial scenes).
- `reference/scene-intent.csv` — narrative dynamics (id, function, action_sequel, emotional_arc, value_at_stake, value_shift, turning_point, characters, on_stage, mice_threads, theme_threads). `theme_threads` references `themes.csv:id`.
- `reference/scene-briefs.csv` — drafting contracts (id, goal, conflict, outcome, crisis, decision, knowledge_in, knowledge_out, key_actions, key_dialogue, emotions, motifs, continuity_deps, has_overflow)
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
| `storyforge elaborate` | `cmd_elaborate.py` | Run elaboration stages (spine/architecture/map/briefs/page-architecture/prompts) |
| `storyforge extract` | `cmd_extract.py` | Extract structural data from prose. `--force` overwrites. |
| `storyforge validate` | `cmd_validate.py` | Structural + schema validation. `--structural` for scoring. |
| `storyforge hone` | `cmd_hone.py` | CSV data quality — registries, briefs, intent, gaps. `--diagnose` for read-only. `--loop` for autonomous convergence. `--findings FILE` for evaluation-driven fixes. |
| `storyforge reconcile` | `cmd_reconcile.py` | Backwards-compatible wrapper for hone |
| `storyforge repetition` | `cmd_repetition.py` | Cross-chapter repeated phrase detection. Standalone or via scoring. |
| `storyforge enrich` | `cmd_enrich.py` | Metadata enrichment from prose |
| `storyforge assemble` | `cmd_assemble.py` | Chapter assembly + epub/PDF/HTML generation |
| `storyforge visualize` | `cmd_visualize.py` | Multi-page manuscript dashboard |
| `storyforge timeline` | `cmd_timeline.py` | Timeline construction |
| `storyforge cleanup` | `cmd_cleanup.py` | Project structure cleanup. `--scenes` strips writing-agent artifacts from scene files. `--csv` runs only the CSV integrity report (schema + row checks). |
| `storyforge cover` | `cmd_cover.py` | Cover design |
| `storyforge scenes-setup` | `cmd_scenes_setup.py` | Scene file and metadata setup |
| `storyforge scenes-export` | `cmd_scenes_export.py` | Export scenes to `reference/scenes-review.md` (header-driven; round-trips every column present in the CSVs, including GN additions) |
| `storyforge scenes-import` | `cmd_scenes_import.py` | Import edited `scenes-review.md` back into scene CSVs |
| `storyforge sync` | `cmd_sync.py` | Sync scene CSVs ↔ `reference/scenes-review.md` against git HEAD. Exports when CSVs are dirty, imports when MD is dirty, writes `working/sync-conflict.md` and exits 1 when both moved. `--install-hook` drops a pre-commit hook that runs this on every commit. |
| `storyforge review` | `cmd_review.py` | Pipeline review |
| `storyforge migrate` | `cmd_migrate.py` | Project migration. Eight steps: registry rename/seed/normalize/validate (1-5) + elaboration v1 (6-8): bootstrap `story-summary.md`, extract `status=spine` rows into `spine.csv`, extract `status=architecture` rows into `architecture.csv`. All steps idempotent. Step 7/8 upgrade pre-`summary` headers in place. |
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
| `title` | Title development |
| `press-kit` | Marketing materials |

† Medium-aware: behavior adapts to `project.medium` (novel | graphic-novel).

### Elaboration Pipeline

New projects use the elaboration pipeline: progressive structural development before drafting.

```
Seed → Spine → Architecture → Scene Map → Briefs → Validate/Diagnose → Draft → Evaluate → Polish → Produce
```

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
| `runner.py` | Parallel execution (ProcessPoolExecutor), healing zones |
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

**Rendered page images (issue #261):** rendered pages have a canonical home at `manuscript/pages/<page_id>.png` — one PNG per page file, filenames matching the page IDs 1:1 (scene + page-within-scene naming, stable across scene reordering; book-wide page numbers stay derived from the chapter map). Each PNG is the *current* canonical render of that page; iteration history lives in git (no separate `drafts/` directory — re-render replaces the PNG and commit). `references_required` in a page's frontmatter can point at `manuscript/pages/*.png` for prior-page style/continuity anchors, so render order is also dependency order. `cleanup` flags an orphan PNG (no matching page file) as `page_render_orphan`; an *unrendered* page (page file with no PNG) is valid in-flight state, not a finding. `script-package` logs an "N of M pages rendered" count and, once at least one page is rendered, adds a `manuscript/pages/` inventory line to the handoff readme (before any render it logs 0-of-M progress to stdout only); orphan renders always log a WARNING. The PNGs already live under the bundle dir, so they are not copied. `forge` reports render status in GN mode and names the next unrendered page. `pages.page_render_report(project_dir)` returns `{rendered, unrendered, orphans}` (by `page_id`).

See the design spec: `docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md`.

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

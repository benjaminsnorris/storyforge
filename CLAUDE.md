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

- `reference/scenes.csv` — structural identity (id, seq, title, part, pov, location, timeline_day, time_of_day, duration, type, status, word_count, target_words)
- `reference/scene-intent.csv` — narrative dynamics (id, function, action_sequel, emotional_arc, value_at_stake, value_shift, turning_point, characters, on_stage, mice_threads)
- `reference/scene-briefs.csv` — drafting contracts (id, goal, conflict, outcome, crisis, decision, knowledge_in, knowledge_out, key_actions, key_dialogue, emotions, motifs, continuity_deps, has_overflow)

**Shared:**
- `working/craft-weights.csv` — craft principle weights (keyed by `principle` column, not `id`)
- `working/costs/ledger.csv` — per-invocation cost tracking
- `reference/chapter-map.csv` — chapter-to-scene mapping
- `working/scores/score-history.csv` — per-scene, per-principle scores across cycles (cycle, scene_id, principle, score)

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
| `storyforge write` | `cmd_write.py` | Draft scenes (brief-aware, parallel wave drafting) |
| `storyforge evaluate` | `cmd_evaluate.py` | Multi-agent evaluation panel (6 evaluators + synthesis) |
| `storyforge revise` | `cmd_revise.py` | Execute revision passes. `--polish` for craft-only. `--polish --loop` for score→polish convergence. `--naturalness` for AI pattern removal. |
| `storyforge score` | `cmd_score.py` | Craft scoring (25 principles + fidelity scoring against briefs) |
| `storyforge elaborate` | `cmd_elaborate.py` | Run elaboration stages (spine/architecture/map/briefs) |
| `storyforge extract` | `cmd_extract.py` | Extract structural data from prose. `--force` overwrites. |
| `storyforge validate` | `cmd_validate.py` | Structural + schema validation. `--structural` for scoring. |
| `storyforge hone` | `cmd_hone.py` | CSV data quality — registries, briefs, intent, gaps. `--diagnose` for read-only. `--loop` for autonomous convergence. `--findings FILE` for evaluation-driven fixes. |
| `storyforge reconcile` | `cmd_reconcile.py` | Backwards-compatible wrapper for hone |
| `storyforge enrich` | `cmd_enrich.py` | Metadata enrichment from prose |
| `storyforge assemble` | `cmd_assemble.py` | Chapter assembly + epub/PDF/HTML generation |
| `storyforge visualize` | `cmd_visualize.py` | Multi-page manuscript dashboard |
| `storyforge timeline` | `cmd_timeline.py` | Timeline construction |
| `storyforge cleanup` | `cmd_cleanup.py` | Project structure cleanup. `--scenes` strips writing-agent artifacts from scene files. `--csv` runs only the CSV integrity report (schema + row checks). |
| `storyforge cover` | `cmd_cover.py` | Cover design |
| `storyforge scenes-setup` | `cmd_scenes_setup.py` | Scene file and metadata setup |
| `storyforge review` | `cmd_review.py` | Pipeline review |
| `storyforge migrate` | `cmd_migrate.py` | Project migration |

### Skills

| Skill | Purpose |
|-------|---------|
| `forge` | Hub — reads project state, recommends next action, routes to skills |
| `elaborate` | All creative development: spine → architecture → voice → map → briefs. Character, world, story architecture. |
| `extract` | Reverse elaboration — extract structural data from existing prose |
| `revise` | Plan + execute revision (upstream CSV fixes + prose polish). `--polish` for craft-only. |
| `score` | Craft + fidelity scoring |
| `hone` | CSV data quality — registries, brief concretization, intent quality, evaluation-driven fixes, gap detection. `--diagnose` for read-only assessment. |
| `publish` | Assemble web book + generate dashboard + push to bookshelf |
| `produce` | Epub, PDF, print formats |
| `init` | New project initialization |
| `cover` | Cover design |
| `title` | Title development |
| `press-kit` | Marketing materials |

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
| `api.py` | Anthropic API (Messages + Batch), response parsing, cost calculation |
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

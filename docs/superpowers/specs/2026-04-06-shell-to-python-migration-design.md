# Shell to Python Migration — Design Spec

**Issue:** #123
**Date:** 2026-04-06
**Status:** Approved

## Goal

Replace all 18 bash scripts and 5 shared shell libraries with Python equivalents. Zero `.sh` files in `scripts/` when done. The `./storyforge` runner becomes Python. Tests migrate to pytest.

## Decisions

- **Full migration** in a single branch/PR
- **Tests → pytest** (bash tests can't work once shell libraries are gone)
- **Runner → Python** (`./storyforge` becomes `#!/usr/bin/env python3`)
- **Visualize HTML template** extracted to `templates/dashboard.html`

## Architecture

```
storyforge                  ← Python entry point (chmod +x)
scripts/
  lib/
    python/
      storyforge/
        __init__.py
        __main__.py         ← CLI dispatcher
        cli.py              ← Shared argparse helpers, common flags
        common.py           ← Port of common.sh (logging, yaml, model selection)
        git.py              ← Port of git ops (branch, PR, push)
        runner.py           ← Parallel execution (concurrent.futures)
        api.py              ← Extend existing (add streaming, healing zone)
        costs.py            ← Extend existing (add threshold prompting)
        csv_cli.py          ← Keep as-is
        schema.py           ← Keep as-is
        
        # Command modules:
        cmd_validate.py, cmd_hone.py, cmd_write.py, cmd_evaluate.py,
        cmd_revise.py, cmd_score.py, cmd_enrich.py, cmd_extract.py,
        cmd_elaborate.py, cmd_visualize.py, cmd_timeline.py,
        cmd_assemble.py, cmd_cleanup.py, cmd_cover.py, cmd_migrate.py,
        cmd_scenes_setup.py, cmd_review.py, cmd_reconcile.py
        
        # Existing domain modules (keep, extend):
        elaborate.py, extract.py, prompts.py, prompts_elaborate.py,
        scoring.py, structural.py, hone.py, reconcile.py,
        enrich.py, assembly.py, parsing.py, project.py,
        visualize.py, timeline.py, revision.py, cover.py,
        scenes.py, exemplars.py

templates/
  dashboard.html            ← Extracted from storyforge-visualize

tests/
  conftest.py               ← Shared fixtures
  test_common.py, test_csv.py, test_validate.py, ...
  run-tests.sh              ← Thin wrapper: `pytest tests/`
  fixtures/                 ← Keep as-is
```

## Patterns

### CLI Dispatcher (`__main__.py`)
```python
COMMANDS = {'validate': 'storyforge.cmd_validate', ...}

def main():
    cmd = sys.argv[1]
    module = importlib.import_module(COMMANDS[cmd])
    module.main(sys.argv[2:])
```

### Command Module Pattern
```python
def parse_args(argv):
    parser = argparse.ArgumentParser(prog=f'storyforge {name}')
    return parser.parse_args(argv)

def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
```

### Parallel Execution
```python
from concurrent.futures import ProcessPoolExecutor, as_completed
with ProcessPoolExecutor(max_workers=args.parallel) as pool:
    futures = {pool.submit(process_scene, sid): sid for sid in ids}
    for future in as_completed(futures):
        result = future.result()
```

### Git Operations (`git.py`)
```python
def create_branch(branch_type, project_dir): ...
def ensure_branch_pushed(project_dir): ...
def create_draft_pr(title, body, project_dir, label): ...
```

## Migration Order

1. Foundation: `common.py`, `git.py`, `cli.py`, `runner.py`
2. Simple: validate, reconcile, review, hone
3. Medium: cleanup, assemble, migrate, enrich, elaborate
4. Complex: write, score, extract, timeline, cover, scenes-setup
5. Most complex: evaluate, revise, visualize
6. Runner + shell deletion
7. Tests → pytest
8. CLAUDE.md + version bump

## What Gets Dropped

- All `.sh` files in `scripts/` and `scripts/lib/`
- BSD sed hacks, bash 3 workarounds
- Heredoc prompt construction
- Shell process management (register_child_pid, etc.)
- `extract_claude_response` (replaced by proper JSON parsing)

## What Stays the Same

- All CLI flags and behavior
- `./storyforge <command>` invocation
- Git branch/PR workflow
- Parallel execution semantics
- Interactive mode, coaching levels, cost tracking
- CSV data format (pipe-delimited)

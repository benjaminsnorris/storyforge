# Comprehensive Test Suite Design

## Problem

Test coverage is 26% overall. All 16 `cmd_*.py` command modules are 0-13% covered. Core infrastructure (`common.py`, `git.py`, `api.py`, `runner.py`) is 0-27%. Every runtime bug found in v1.4.x lived in these untested orchestration paths: wrong kwargs, missing imports, signature mismatches, pickle errors, missing function implementations. The existing 430 tests cover domain logic well (56-96%) but don't exercise the wiring between modules.

## Goals

- Catch import errors, signature mismatches, and missing functions before they ship
- Test command orchestration logic without hitting the Anthropic API
- Verify end-to-end pipeline flows with real file I/O and mocked API responses
- Ratchet coverage floor so it can only go up
- Target: 26% → ~45% (Phase A) → ~70% (Phase B) → 80%+ (Phase C)

## Decisions

- **Three-phase approach:** wiring tests (A), command module tests (B), integration tests (C)
- **API mocking:** Patch at the `storyforge.api` level (`invoke`, `invoke_to_file`, `invoke_api`), with a few `urllib`-level tests for `api.py` internals (retry, timeout, error parsing)
- **Directory structure:** `tests/wiring/`, `tests/commands/`, `tests/integration/` — existing tests stay in `tests/`
- **Coverage floor:** Ratchet via `--cov-fail-under` in pyproject.toml, set after each phase

## Phase A: Wiring Tests

**Directory:** `tests/wiring/`

**Purpose:** Catch import errors, signature mismatches, missing functions, and wrong kwargs across every module. Pure introspection — no fixtures, no API calls, no file I/O.

### Test Files

**`test_imports.py`** — Every module importable, all public functions accessible
- Import every module in `storyforge/`
- For each module, verify all functions referenced in CLAUDE.md's shared module tables are present
- Verify `__main__.py` can import all command modules it dispatches to

**`test_signatures.py`** — Caller/callee kwarg matching
- For each shared function (`csv_cli.update_field`, `csv_cli.get_field`, `api.invoke`, `api.invoke_to_file`, `git.create_branch`, `git.commit_and_push`, `runner.run_parallel`, etc.): find all call sites, verify kwargs match the function signature
- Use `ast.parse` to find call sites, `inspect.signature` to check parameters
- This is the test that would have caught `key_column` vs `key_col`

**`test_cli_dispatch.py`** — CLI entry points handle all commands
- `__main__.py` dispatcher handles every documented command name
- `assembly.py` CLI dispatcher handles all documented subcommands (assemble, chapter, chapter-scenes, extract-prose, word-count, metadata, toc, genre-css, count-chapters, read-chapter-field)
- `prompts.py` CLI dispatcher handles all its subcommands

**Migration:** Move existing `test_regressions.py` content into the appropriate wiring test files. Remove `test_regressions.py` or leave as a thin re-export.

### Estimated Scope
- ~150-200 tests
- <1 second execution time
- Coverage impact: 26% → ~45%

---

## Phase B: Command Module Tests

**Directory:** `tests/commands/`

**Purpose:** Test orchestration logic in each `cmd_*.py` — argument parsing, plan generation, scope resolution, scene filtering, branch/commit flow — with mocked API.

### Shared Fixtures (`tests/commands/conftest.py`)

```python
@pytest.fixture
def mock_api(monkeypatch):
    """Patch all API functions to return canned responses."""
    # Patches invoke, invoke_to_file, invoke_api
    # Returns a controller object to set per-call responses

@pytest.fixture
def mock_git(monkeypatch):
    """Patch git operations to avoid real git calls."""
    # Patches _git, current_branch, has_gh
    # Returns a controller to inspect calls made

def load_api_response(name):
    """Load a canned API response from tests/fixtures/api-responses/."""
```

### Test Files — One Per Command Module

Priority order (by bug frequency and usage):

| File | Module | Key Test Areas |
|------|--------|---------------|
| `test_cmd_revise.py` | `cmd_revise.py` | parse_args, polish plan generation, naturalness plan generation, plan CSV reading, pass execution with mock API, scope resolution, model selection, response processing, loop mode iteration |
| `test_cmd_write.py` | `cmd_write.py` | parse_args, prompt building, scene extraction from response, batch mode JSONL generation, word count updates, commit flow |
| `test_cmd_score.py` | `cmd_score.py` | parse_args, parallel scoring dispatch, score parsing, diagnostics CSV, fidelity scoring, merge step |
| `test_cmd_assemble.py` | `cmd_assemble.py` | parse_args, format resolution, manuscript assembly orchestration, format dispatch |
| `test_cmd_hone.py` | `cmd_hone.py` | parse_args, domain resolution, loop mode, diagnose mode, coaching level |
| `test_cmd_evaluate.py` | `cmd_evaluate.py` | parse_args, evaluator dispatch, batch vs direct mode, synthesis |
| `test_cmd_elaborate.py` | `cmd_elaborate.py` | parse_args, stage dispatch, MICE thread inference, gap-fill |
| `test_cmd_extract.py` | `cmd_extract.py` | parse_args, extraction phases, force mode |
| `test_cmd_enrich.py` | `cmd_enrich.py` | parse_args, enrichment dispatch, batch mode |
| `test_cmd_cleanup.py` | `cmd_cleanup.py` | parse_args, dry-run mode, gitignore updates |
| `test_cmd_migrate.py` | `cmd_migrate.py` | parse_args, migration steps, no-commit mode |
| `test_cmd_visualize.py` | `cmd_visualize.py` | parse_args, dashboard generation |
| `test_cmd_timeline.py` | `cmd_timeline.py` | parse_args, timeline construction |
| `test_cmd_scenes_setup.py` | `cmd_scenes_setup.py` | parse_args, scene file creation |
| `test_cmd_cover.py` | `cmd_cover.py` | parse_args, SVG generation |
| `test_cmd_review.py` | `cmd_review.py` | parse_args, review phase dispatch |

### Also Test Core Infrastructure

| File | Module | Key Test Areas |
|------|--------|---------------|
| `test_common.py` | `common.py` | detect_project_root, read_yaml_field, select_model, coaching level, pipeline manifest CRUD, signal handlers |
| `test_git.py` | `git.py` | create_branch, ensure_on_branch, commit_and_push, create_draft_pr, run_review_phase (all with mock git) |
| `test_api.py` | `api.py` | Retry logic, timeout threading, heartbeat, error handling (mock at urllib level) |
| `test_runner.py` | `runner.py` | run_parallel, run_batched, HealingZone (with mock API) |
| `test_cli.py` | `cli.py` | base_parser, scene filter args, coaching override |
| `test_costs.py` | `costs.py` | calculate_cost, estimate_cost, threshold checking, ledger operations |

### Estimated Scope
- ~300-400 tests
- <5 seconds execution time
- Coverage impact: ~45% → ~70%

---

## Phase C: Integration Tests

**Directory:** `tests/integration/`

**Purpose:** End-to-end flows that exercise the full pipeline against fixture projects. Real file I/O, CSV parsing, git operations (in tmp dirs). Mocked at the API boundary only.

### Shared Fixtures (`tests/integration/conftest.py`)

```python
@pytest.fixture
def git_project(tmp_path):
    """A real git repo with test-project fixture, initialized and committed."""
    # Copies fixture, runs git init, makes initial commit
    # Returns project_dir

@pytest.fixture
def mock_api_rich(monkeypatch):
    """API mock with response matching — returns different responses
    based on prompt content (drafting vs scoring vs evaluation)."""

# Canned API responses stored in tests/fixtures/api-responses/
# - drafting-response.json (scene prose with markers)
# - scoring-response.json (principle scores + rationales)
# - evaluation-response.json (evaluator findings)
# - revision-response.json (revised scene prose)
# - synthesis-response.json (evaluation synthesis)
```

### Test Files

**`test_draft_score_polish.py`** — The core production loop
- Draft scenes (mock API returns prose), verify scene files written and metadata updated
- Score scenes (mock API returns scores), verify score CSVs populated
- Polish loop iterates: score → polish → re-score, verify convergence detection
- Verify commits happen at each step, branch created if on main

**`test_elaborate_pipeline.py`** — Progressive elaboration
- Spine stage populates scenes.csv and scene-intent.csv
- Architecture stage adds columns
- Map stage creates full scene list
- Briefs stage populates scene-briefs.csv
- Validation gates between stages catch structural issues

**`test_hone_to_draft.py`** — Data quality into drafting
- Hone fixes brief issues, verify CSV updates
- Draft uses the fixed briefs, verify prompt includes updated brief content

**`test_assemble_pipeline.py`** — Manuscript production
- Assemble markdown from chapter map and scene files
- Web book generation with template filling (real template files, no pandoc needed)
- Cover placeholder generation

**`test_extract_roundtrip.py`** — Prose to data and back
- Feed scene files into extraction
- Verify three-file CSV model populated
- Re-draft from extracted data, verify prose is generated

**`test_branch_pr_workflow.py`** — Git workflow end-to-end
- Start on main, verify branch created before first commit
- Start on existing branch, verify no new branch
- Verify PR creation and task checking (mock gh CLI)
- Review phase: review saved, cleanup runs, recommendations generated

**`test_error_recovery.py`** — Resilience
- API failure mid-batch: verify partial results preserved
- Signal interrupt: verify graceful shutdown
- Missing files: verify clear error messages

### Extended Fixture Project

Add to `tests/fixtures/`:
- `api-responses/` — canned JSON responses for each API call type
- `test-project/` — extend with more scenes, a pipeline.csv, score history, voice guide

### Estimated Scope
- ~100-150 tests
- <30 seconds execution time
- Coverage impact: ~70% → 80%+

---

## Infrastructure

### Coverage Floor Ratchet

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "--cov=scripts/lib/python/storyforge --cov-fail-under=26"
```

Update the floor after each phase lands:
- After Phase A: set to 40
- After Phase B: set to 65
- After Phase C: set to 78

### Execution

```bash
pytest tests/wiring/       # <1s — run on every commit
pytest tests/commands/      # <5s — run before push
pytest tests/integration/   # <30s — run before merge
pytest tests/               # everything
```

### Conftest Organization

- `tests/conftest.py` — existing fixtures (fixture_dir, project_dir, plugin_dir), unchanged
- `tests/wiring/conftest.py` — minimal, possibly empty
- `tests/commands/conftest.py` — mock_api, mock_git, canned response loader
- `tests/integration/conftest.py` — git_project, mock_api_rich, extended fixtures

---

## Implementation Order

1. **Phase A** — wiring tests (~150-200 tests, 1-2 sessions)
2. **Phase B top 6** — cmd_revise, cmd_write, cmd_score, cmd_assemble, cmd_hone, cmd_evaluate (~200 tests, 2-3 sessions)
3. **Phase B remaining** — 10 more command modules + core infrastructure (~150 tests, 1-2 sessions)
4. **Phase C** — integration tests (~100-150 tests, 2-3 sessions)

Total: ~600-900 new tests across 7-10 sessions.

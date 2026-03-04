# Test Infrastructure — Design

**Date:** 2026-03-03
**Status:** Draft
**Scope:** Adding a test suite, dry-run modes, and fixture project to Storyforge so that changes to scripts and library functions can be verified without invoking Claude or modifying real projects.

## Problem

Storyforge's autonomous scripts (`storyforge-write`, `storyforge-evaluate`, `storyforge-revise`) and their library functions (`common.sh`, `prompt-builder.sh`, `revision-passes.sh`) do real work — YAML parsing, scope resolution, prompt assembly, git operations. There are no tests. A change to `read_pass_field` or `resolve_scope` could silently break the entire revision pipeline with no way to detect the regression short of running a full revision on a real project.

## Goals

1. **Unit tests for library functions** — verify parsing, extraction, and prompt construction without calling Claude.
2. **Dry-run modes for scripts** — build and print prompts without invoking Claude, for inspection and automated testing.
3. **Fixture project** — a minimal but complete storyforge project that all tests run against.
4. **Fast feedback** — the full test suite should run in under 10 seconds.
5. **No external dependencies** — tests run with bash, standard Unix tools, and the same libraries they test. No test frameworks.

## Architecture

### Directory Structure

```
tests/
├── run-tests.sh              # Test runner — sources libraries, runs all tests
├── fixtures/
│   └── test-project/         # Minimal storyforge project
│       ├── storyforge.yaml
│       ├── reference/
│       │   ├── voice-guide.md
│       │   ├── character-bible.md
│       │   ├── continuity-tracker.md
│       │   └── key-decisions.md
│       ├── scenes/
│       │   ├── scene-index.yaml
│       │   ├── act1-sc01.md
│       │   ├── act1-sc02.md
│       │   └── act2-sc01.md
│       └── working/
│           ├── evaluations/
│           │   └── eval-test/
│           │       ├── findings.yaml
│           │       └── synthesis.md
│           └── plans/
│               └── revision-plan.yaml
├── test-common.sh            # Tests for common.sh functions
├── test-prompt-builder.sh    # Tests for prompt-builder.sh functions
├── test-revision-passes.sh   # Tests for revision-passes.sh functions
└── test-craft-sections.sh    # Tests for craft engine extraction
```

### Test Runner

`tests/run-tests.sh` — discovers and runs all `test-*.sh` files. Reports pass/fail counts. Exit code 0 on all pass, 1 on any failure.

```bash
#!/bin/bash
# Usage: ./tests/run-tests.sh
# Or:    ./storyforge test
```

Also accessible via `./storyforge test` (add a `test` command to the runner script).

### Test Helpers

A minimal assertion library in the test runner or a shared helper:

```bash
assert_equals() {
    local expected="$1" actual="$2" label="${3:-}"
    if [[ "$expected" == "$actual" ]]; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected: ${expected}"
        echo "    Actual:   ${actual}"
    fi
}

assert_contains() {
    local haystack="$1" needle="$2" label="${3:-}"
    if echo "$haystack" | grep -qF "$needle"; then
        PASS=$((PASS + 1))
        echo "  PASS: ${label}"
    else
        FAIL=$((FAIL + 1))
        echo "  FAIL: ${label}"
        echo "    Expected to contain: ${needle}"
    fi
}

assert_not_contains() { ... }
assert_exit_code() { ... }
assert_file_exists() { ... }
```

### Fixture Project

A minimal storyforge project with enough content to exercise all library functions:

- `storyforge.yaml` — complete config with all fields populated
- `scene-index.yaml` — 3 scenes across 2 acts, with full metadata
- 3 stub scene files — minimal content (100-200 words each), with YAML frontmatter
- `voice-guide.md` — minimal but valid voice guide
- `character-bible.md` — 2 characters with basic profiles
- `continuity-tracker.md` — a few entries
- `findings.yaml` — 3-4 test findings at different severities
- `revision-plan.yaml` — 2 passes with different types (prose, character), one with guidance entries, one with subtasks

The fixture project should NOT be a git repo (tests shouldn't depend on git state). Git-dependent tests can initialize a temp repo in setup.

## Unit Tests

### test-common.sh

| Test | What it verifies |
|------|-----------------|
| `read_yaml_field "project.title"` | Returns correct value from nested YAML |
| `read_yaml_field "phase"` | Returns top-level field |
| `read_yaml_field "nonexistent"` | Returns empty string |
| `detect_project_root` | Finds storyforge.yaml from a subdirectory |
| `extract_craft_sections 2` | Returns Scene Craft section |
| `extract_craft_sections 2 3 5` | Returns 3 sections with separators |
| `extract_craft_sections 99` | Returns empty (no such section) |
| `extract_craft_sections` (no args) | Returns empty |

### test-prompt-builder.sh

| Test | What it verifies |
|------|-----------------|
| `get_scene_metadata "act1-sc01"` | Returns correct YAML block |
| `get_previous_scene "act1-sc02"` | Returns "act1-sc01" |
| `get_previous_scene "act1-sc01"` | Returns empty (first scene) |
| `list_reference_files` | Returns all reference files, sorted |
| `get_scene_status "act1-sc01"` | Returns correct status |
| `build_scene_prompt "act1-sc01"` | Contains voice guide reference |
| `build_scene_prompt "act1-sc01"` | Contains CRAFT PRINCIPLES section |
| `build_scene_prompt "act1-sc01"` | Contains scene metadata |
| `build_scene_prompt "act1-sc01"` | Contains previous scene instruction |
| `build_scene_prompt "act2-sc01"` | References correct previous scene |

### test-revision-passes.sh

| Test | What it verifies |
|------|-----------------|
| `resolve_scope "full"` | Returns all scene files |
| `resolve_scope "act-1"` | Returns only act 1 scenes |
| `resolve_scope "act1-sc01,act2-sc01"` | Returns exactly 2 files |
| `resolve_scope "nonexistent"` | Returns error |
| `build_revision_prompt` with prose pass | Contains Prose Craft section |
| `build_revision_prompt` with character pass | Contains Character Craft section |
| `build_revision_prompt` with continuity pass | Does NOT contain craft sections |
| `build_revision_prompt` with pass config | Contains Pass Configuration block |
| Keyword matching: "prose-tightening" | Selects sections 3+5 |
| Keyword matching: "character-arc-deepening" | Selects sections 4+5 |
| Keyword matching: "continuity-audit" | Selects no sections |
| Keyword matching: "general-cleanup" | Falls through to default 2+3+5 |

### test-craft-sections.sh

| Test | What it verifies |
|------|-----------------|
| Section 1 starts with "## 1." | Header format is correct |
| Section 2 contains "Enter Late" | Scene Craft content present |
| Section 7 contains "Coaching Posture" | Last section extractable |
| All sections 1-7 extractable | No gaps in numbering |
| Each section has content | No empty extractions |
| Sections don't overlap | Section 2 doesn't contain section 3 content |

## Dry-Run Modes

### storyforge-write --dry-run

- Runs all setup: argument parsing, prerequisite checks, scene filtering
- For each scene that would be drafted: builds the prompt and prints it to stdout
- Does NOT invoke Claude
- Does NOT modify any files or make git commits
- Exit code 0 if all prompts built successfully

### storyforge-evaluate --dry-run

- Runs all setup: argument parsing, scope filtering, evaluator discovery
- For each evaluator: builds the prompt and prints it to stdout
- Builds the synthesis prompt and prints it
- Does NOT invoke Claude or create evaluation directories

### storyforge-revise --dry-run

- Runs all setup: plan reading, pass filtering
- For each pending pass: builds the revision prompt and prints it
- Does NOT invoke Claude, modify the plan YAML, or make commits

### Implementation

Each script checks for `--dry-run` in its argument parsing. The main execution loop checks a `DRY_RUN` flag before invoking Claude:

```bash
DRY_RUN=false

# In argument parsing:
--dry-run)
    DRY_RUN=true
    shift
    ;;

# In execution:
if [[ "$DRY_RUN" == true ]]; then
    echo "===== DRY RUN: ${SCENE_ID} ====="
    echo "$PROMPT"
    echo "===== END DRY RUN ====="
    continue
fi
```

## Runner Integration

Add `test` as a command in the storyforge runner script (`templates/storyforge-runner.sh`):

```bash
COMMAND="${1:?Usage: ./storyforge <write|evaluate|revise|test> [options]}"

# ...

case "$COMMAND" in
    test)
        exec "${PLUGIN_ROOT}/tests/run-tests.sh" "$@"
        ;;
    *)
        SCRIPT="$PLUGIN_ROOT/scripts/storyforge-$COMMAND"
        # ...
esac
```

This allows `./storyforge test` from any project directory.

## Implementation Order

1. **Fixture project** — create the test fixtures first so everything else has data to test against.
2. **Test runner + helpers** — the assertion library and test discovery.
3. **test-common.sh** — tests for the most foundational functions.
4. **Dry-run modes** — add `--dry-run` to all three scripts.
5. **test-prompt-builder.sh** — tests for prompt construction (depends on dry-run for verification).
6. **test-revision-passes.sh** — tests for revision prompt construction.
7. **test-craft-sections.sh** — tests for craft engine extraction.
8. **Runner integration** — add `test` command to the runner script.

## Open Questions

1. **Should tests run against the real craft engine or a test copy?** Running against the real file means tests break if the craft engine changes (which is useful — it catches unintended changes). But it also means tests are fragile to content edits.

2. **Git-dependent tests?** Some functions (`verify_revision_changes`, the commit/push in scripts) depend on git. Should we test these with a temp git repo, or skip them?

3. **Should dry-run be the default in CI?** If Storyforge ever gets CI, the test suite + dry-run would be the natural pipeline.

4. **Test coverage target?** Aim for all library functions covered. Scripts tested via dry-run mode. Interactive skills are not testable in this framework (they depend on Claude conversation).

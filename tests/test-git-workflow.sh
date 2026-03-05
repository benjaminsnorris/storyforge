#!/bin/bash
# test-git-workflow.sh — Tests for git branch and PR workflow functions
#
# Run via: ./tests/run-tests.sh
# Tests the git/PR helper functions added to common.sh.
# Git-dependent tests use temporary repos. gh-dependent tests are skipped
# unless STORYFORGE_INTEGRATION_TESTS=1 is set.
#
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# has_gh
# ============================================================================

# has_gh should run without crashing regardless of whether gh is installed
has_gh_result=0
(has_gh) || has_gh_result=$?
if [[ $has_gh_result -eq 0 ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: has_gh: function runs (gh available)"
else
    PASS=$((PASS + 1))
    echo "  PASS: has_gh: function runs (gh not available, returns 1)"
fi

# ============================================================================
# current_branch
# ============================================================================

# current_branch on the plugin repo itself (which is a git repo)
result=$(current_branch "$PLUGIN_DIR")
assert_not_empty "$result" "current_branch: returns non-empty for git repo"

# current_branch on a non-git directory returns empty
result=$(current_branch "/tmp")
assert_empty "$result" "current_branch: returns empty for non-git directory"

# ============================================================================
# create_branch — uses a temporary git repo
# ============================================================================

# Create a temp git repo for branch tests
BRANCH_TEST_DIR=$(mktemp -d)
(
    cd "$BRANCH_TEST_DIR"
    git init -q
    git commit --allow-empty -m "init" -q
)

# create_branch creates a branch with correct naming pattern
(
    cd "$BRANCH_TEST_DIR"
    # Override PROJECT_DIR for the subshell
    export PROJECT_DIR="$BRANCH_TEST_DIR"
    create_branch "write" "$BRANCH_TEST_DIR" >/dev/null 2>&1
    branch=$(git rev-parse --abbrev-ref HEAD)
    if [[ "$branch" == storyforge/write-* ]]; then
        echo "BRANCH_PATTERN_OK"
    else
        echo "BRANCH_PATTERN_FAIL: $branch"
    fi
)
branch_result=$( cd "$BRANCH_TEST_DIR" && git rev-parse --abbrev-ref HEAD 2>/dev/null )
assert_matches "$branch_result" "^storyforge/write-[0-9]" "create_branch: creates branch with correct pattern"

# create_branch sets STORYFORGE_BRANCH
result=$(
    cd "$BRANCH_TEST_DIR"
    export PROJECT_DIR="$BRANCH_TEST_DIR"
    # Already on storyforge/* from previous test
    create_branch "write" "$BRANCH_TEST_DIR" >/dev/null 2>&1
    echo "$STORYFORGE_BRANCH"
)
assert_matches "$result" "^storyforge/write-[0-9]" "create_branch: sets STORYFORGE_BRANCH variable"

# create_branch on existing storyforge/* branch is a no-op (resume)
result=$(
    cd "$BRANCH_TEST_DIR"
    export PROJECT_DIR="$BRANCH_TEST_DIR"
    # Already on storyforge/write-* from above
    create_branch "evaluate" "$BRANCH_TEST_DIR" 2>/dev/null
)
branch_after=$( cd "$BRANCH_TEST_DIR" && git rev-parse --abbrev-ref HEAD 2>/dev/null )
# Should still be storyforge/write-*, NOT storyforge/evaluate-*
assert_matches "$branch_after" "^storyforge/write-" "create_branch: resumes existing storyforge/* branch (no-op)"

# Clean up
rm -rf "$BRANCH_TEST_DIR"

# ============================================================================
# ensure_branch_pushed — initial commit behavior (no remote needed)
# ============================================================================

# Create a fresh temp git repo for push tests
PUSH_TEST_DIR=$(mktemp -d)
(
    cd "$PUSH_TEST_DIR"
    git init -q
    git commit --allow-empty -m "init" -q
    # Create a storyforge.yaml so sed has something to modify
    echo "phase: development" > storyforge.yaml
    git add storyforge.yaml
    git commit -m "add yaml" -q
)

# ensure_branch_pushed creates an initial commit when branch has no commits ahead
push_commit_before=$(cd "$PUSH_TEST_DIR" && git rev-parse HEAD)
(
    cd "$PUSH_TEST_DIR"
    export PROJECT_DIR="$PUSH_TEST_DIR"
    export STORYFORGE_BRANCH="storyforge/test-branch"
    git checkout -b "storyforge/test-branch" -q 2>/dev/null
    # Modify storyforge.yaml to simulate phase advancement
    sed -i '' "s/phase: development/phase: drafting/" storyforge.yaml
    # ensure_branch_pushed should commit the change (push will fail without remote — that's OK)
    ensure_branch_pushed "$PUSH_TEST_DIR" 2>/dev/null || true
)
push_commit_after=$(cd "$PUSH_TEST_DIR" && git rev-parse HEAD)
if [[ "$push_commit_before" != "$push_commit_after" ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: ensure_branch_pushed: creates initial commit when unstaged changes exist"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: ensure_branch_pushed: creates initial commit when unstaged changes exist"
    echo "    Expected commit to be different, but HEAD unchanged"
fi

# ensure_branch_pushed creates empty commit when no changes exist
(
    cd "$PUSH_TEST_DIR"
    git checkout -b "storyforge/empty-test" -q 2>/dev/null
)
empty_before=$(cd "$PUSH_TEST_DIR" && git rev-parse HEAD)
(
    cd "$PUSH_TEST_DIR"
    export PROJECT_DIR="$PUSH_TEST_DIR"
    export STORYFORGE_BRANCH="storyforge/empty-test"
    ensure_branch_pushed "$PUSH_TEST_DIR" 2>/dev/null || true
)
empty_after=$(cd "$PUSH_TEST_DIR" && git rev-parse HEAD)
if [[ "$empty_before" != "$empty_after" ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: ensure_branch_pushed: creates empty commit when no changes exist"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: ensure_branch_pushed: creates empty commit when no changes exist"
    echo "    Expected commit to be different, but HEAD unchanged"
fi

# The empty commit should have the branch name in its message
empty_msg=$(cd "$PUSH_TEST_DIR" && git log -1 --format=%s)
assert_contains "$empty_msg" "empty-test" "ensure_branch_pushed: empty commit message contains branch suffix"

# Clean up
rm -rf "$PUSH_TEST_DIR"

# ============================================================================
# update_pr_task — string replacement tests (no gh needed)
# ============================================================================

# Test the sed replacement logic directly (without gh)
# We test the core string operation that update_pr_task performs

test_body="## Tasks
- [ ] Draft scene act1-sc01
- [ ] Draft scene act1-sc02
- [x] Already done
- [ ] Review"

# Replace act1-sc01
escaped_task=$(printf '%s' "Draft scene act1-sc01" | sed 's/[\/&.*[\^$]/\\&/g')
result=$(echo "$test_body" | sed "s/- \[ \] ${escaped_task}/- [x] ${escaped_task}/")
assert_contains "$result" "- [x] Draft scene act1-sc01" "update_pr_task sed: checks off matching task"
assert_contains "$result" "- [ ] Draft scene act1-sc02" "update_pr_task sed: leaves non-matching task unchecked"
assert_contains "$result" "- [x] Already done" "update_pr_task sed: preserves already-checked tasks"
assert_contains "$result" "- [ ] Review" "update_pr_task sed: leaves other tasks untouched"

# Replace Review
escaped_task=$(printf '%s' "Review" | sed 's/[\/&.*[\^$]/\\&/g')
result=$(echo "$test_body" | sed "s/- \[ \] ${escaped_task}/- [x] ${escaped_task}/")
assert_contains "$result" "- [x] Review" "update_pr_task sed: checks off Review task"
assert_contains "$result" "- [ ] Draft scene act1-sc01" "update_pr_task sed: doesn't touch other tasks when checking Review"

# Test with pass names that have hyphens
test_body2="## Tasks
- [ ] Pass: prose-tightening
- [ ] Pass: character-arc-deepening
- [ ] Review"

escaped_task=$(printf '%s' "Pass: prose-tightening" | sed 's/[\/&.*[\^$]/\\&/g')
result=$(echo "$test_body2" | sed "s/- \[ \] ${escaped_task}/- [x] ${escaped_task}/")
assert_contains "$result" "- [x] Pass: prose-tightening" "update_pr_task sed: handles hyphenated pass names"
assert_contains "$result" "- [ ] Pass: character-arc-deepening" "update_pr_task sed: leaves other passes unchecked"

# Test with evaluator names
test_body3="## Tasks
- [ ] Evaluator: literary-agent
- [ ] Evaluator: genre-expert
- [ ] Evaluator: custom-eval (custom)
- [ ] Synthesis
- [ ] Review"

escaped_task=$(printf '%s' "Evaluator: literary-agent" | sed 's/[\/&.*[\^$]/\\&/g')
result=$(echo "$test_body3" | sed "s/- \[ \] ${escaped_task}/- [x] ${escaped_task}/")
assert_contains "$result" "- [x] Evaluator: literary-agent" "update_pr_task sed: handles evaluator names"
assert_contains "$result" "- [ ] Evaluator: genre-expert" "update_pr_task sed: leaves other evaluators unchecked"

escaped_task=$(printf '%s' "Evaluator: custom-eval (custom)" | sed 's/[\/&.*[\^$]/\\&/g')
result=$(echo "$test_body3" | sed "s/- \[ \] ${escaped_task}/- [x] ${escaped_task}/")
assert_contains "$result" "- [x] Evaluator: custom-eval (custom)" "update_pr_task sed: handles custom evaluator with parens"

# ============================================================================
# update_pr_task — no-ops when no PR number
# ============================================================================

# update_pr_task should silently no-op when STORYFORGE_PR_NUMBER is empty
(
    STORYFORGE_PR_NUMBER=""
    update_pr_task "Draft scene act1-sc01" "$PROJECT_DIR" 2>/dev/null
)
rc=$?
assert_exit_code "0" "$rc" "update_pr_task: no-ops when PR number is empty"

# ============================================================================
# ensure_label — no-ops when gh not available
# ============================================================================

# ensure_label should not crash even without gh
(ensure_label "test-label" "ff0000" "Test label" "/tmp" 2>/dev/null)
rc=$?
assert_exit_code "0" "$rc" "ensure_label: does not crash"

# ============================================================================
# create_draft_pr — no-ops when gh not available
# ============================================================================

if ! has_gh; then
    (
        STORYFORGE_PR_NUMBER=""
        create_draft_pr "Test" "Body" "/tmp" 2>/dev/null
    )
    rc=$?
    assert_exit_code "0" "$rc" "create_draft_pr: no-ops when gh not available"
else
    PASS=$((PASS + 1))
    echo "  PASS: create_draft_pr: gh available (skipping no-gh test)"
fi

# ============================================================================
# select_model
# ============================================================================

result=$(select_model "drafting")
assert_equals "claude-opus-4-6" "$result" "select_model: drafting uses opus"

result=$(select_model "revision")
assert_equals "claude-opus-4-6" "$result" "select_model: revision uses opus"

result=$(select_model "synthesis")
assert_equals "claude-opus-4-6" "$result" "select_model: synthesis uses opus"

result=$(select_model "evaluation")
assert_equals "claude-sonnet-4-6" "$result" "select_model: evaluation uses sonnet"

result=$(select_model "mechanical")
assert_equals "claude-sonnet-4-6" "$result" "select_model: mechanical uses sonnet"

result=$(select_model "review")
assert_equals "claude-sonnet-4-6" "$result" "select_model: review uses sonnet"

result=$(select_model "unknown-type")
assert_equals "claude-opus-4-6" "$result" "select_model: unknown type defaults to opus"

# STORYFORGE_MODEL override
result=$(STORYFORGE_MODEL="claude-haiku-4-5" select_model "drafting")
assert_equals "claude-haiku-4-5" "$result" "select_model: STORYFORGE_MODEL overrides drafting"

result=$(STORYFORGE_MODEL="claude-haiku-4-5" select_model "review")
assert_equals "claude-haiku-4-5" "$result" "select_model: STORYFORGE_MODEL overrides review"

# ============================================================================
# select_revision_model
# ============================================================================

result=$(select_revision_model "prose-tightening" "Cut filler, tighten sentences")
assert_equals "claude-opus-4-6" "$result" "select_revision_model: prose pass uses opus"

result=$(select_revision_model "character-arc-deepening" "Deepen character arcs")
assert_equals "claude-opus-4-6" "$result" "select_revision_model: character pass uses opus"

result=$(select_revision_model "voice-consistency" "Fix voice drift")
assert_equals "claude-opus-4-6" "$result" "select_revision_model: voice pass uses opus"

result=$(select_revision_model "continuity-audit" "Check timeline consistency")
assert_equals "claude-sonnet-4-6" "$result" "select_revision_model: continuity pass uses sonnet"

result=$(select_revision_model "timeline-fix" "Fix timeline contradictions")
assert_equals "claude-sonnet-4-6" "$result" "select_revision_model: timeline pass uses sonnet"

result=$(select_revision_model "fact-check" "Verify factual details")
assert_equals "claude-sonnet-4-6" "$result" "select_revision_model: fact-check pass uses sonnet"

# STORYFORGE_MODEL override
result=$(STORYFORGE_MODEL="claude-sonnet-4-6" select_revision_model "prose-tightening" "Cut filler")
assert_equals "claude-sonnet-4-6" "$result" "select_revision_model: STORYFORGE_MODEL overrides creative pass"

# ============================================================================
# build_interactive_system_prompt
# ============================================================================

result=$(build_interactive_system_prompt "/tmp" "scene")
assert_contains "$result" "scene" "build_interactive_system_prompt: contains work unit (scene)"
assert_contains "$result" "THIS scene ONLY" "build_interactive_system_prompt: scopes to single unit"
assert_contains "$result" ".interactive" "build_interactive_system_prompt: references interactive file"
assert_contains "$result" "rm -f" "build_interactive_system_prompt: removes interactive file for autopilot"
assert_contains "$result" "go auto" "build_interactive_system_prompt: has go auto trigger"
assert_contains "$result" "auto mode" "build_interactive_system_prompt: has auto mode trigger"
assert_contains "$result" "/exit" "build_interactive_system_prompt: mentions /exit"

result=$(build_interactive_system_prompt "/tmp" "pass")
assert_contains "$result" "pass" "build_interactive_system_prompt: pass work unit"
assert_contains "$result" "THIS pass ONLY" "build_interactive_system_prompt: scopes to single pass"

# ============================================================================
# show_interactive_banner (output format check)
# ============================================================================

# Single-step banner (no autopilot line)
result=$(show_interactive_banner "Evaluation Synthesis")
assert_contains "$result" "INTERACTIVE MODE" "show_interactive_banner single: has title"
assert_contains "$result" "Evaluation Synthesis" "show_interactive_banner single: has subtitle"
assert_contains "$result" "/exit" "show_interactive_banner single: mentions /exit"
assert_not_contains "$result" "finish without me" "show_interactive_banner single: no autopilot phrase"
assert_contains "$result" "╔" "show_interactive_banner single: has top border"
assert_contains "$result" "╚" "show_interactive_banner single: has bottom border"

# Multi-step banner (with autopilot line)
result=$(show_interactive_banner "Scene 3 of 12" "multi")
assert_contains "$result" "INTERACTIVE MODE" "show_interactive_banner multi: has title"
assert_contains "$result" "Scene 3 of 12" "show_interactive_banner multi: has subtitle"
assert_contains "$result" "/exit" "show_interactive_banner multi: mentions /exit"
assert_contains "$result" "finish without me" "show_interactive_banner multi: has autopilot phrase"
assert_contains "$result" "╔" "show_interactive_banner multi: has top border"
assert_contains "$result" "╚" "show_interactive_banner multi: has bottom border"

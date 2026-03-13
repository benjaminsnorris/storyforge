#!/bin/bash
# test-migrate.sh — Tests for storyforge-migrate script
#
# Run via: ./tests/run-tests.sh tests/test-migrate.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, assertion functions (from run-tests.sh)

MIGRATE_SCRIPT="${PLUGIN_DIR}/scripts/storyforge-migrate"

# ============================================================================
# Helper: create a fresh temp copy of the fixture
# ============================================================================

setup_migrate_tmpdir() {
    local tmpdir
    tmpdir=$(mktemp -d)
    cp -R "${FIXTURE_DIR}/"* "$tmpdir/"
    # Remove pre-existing CSV files so migration can create them fresh
    rm -f "$tmpdir/scenes/metadata.csv"
    rm -f "$tmpdir/scenes/intent.csv"
    echo "$tmpdir"
}

cleanup_migrate_tmpdir() {
    [[ -n "$1" && -d "$1" ]] && rm -rf "$1"
}

# ============================================================================
# Test: Dry-run mode makes no changes
# ============================================================================

TMPDIR_DRY=$(setup_migrate_tmpdir)

# Capture file state before
before_index_md5=$(md5 -q "$TMPDIR_DRY/scenes/scene-index.yaml" 2>/dev/null || md5sum "$TMPDIR_DRY/scenes/scene-index.yaml" | awk '{print $1}')
before_scene_md5=$(md5 -q "$TMPDIR_DRY/scenes/act1-sc01.md" 2>/dev/null || md5sum "$TMPDIR_DRY/scenes/act1-sc01.md" | awk '{print $1}')

# Run dry-run
output=$("$MIGRATE_SCRIPT" --dry-run --project-dir "$TMPDIR_DRY" 2>&1)

# Verify no CSV files created
if [[ -f "$TMPDIR_DRY/scenes/metadata.csv" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: dry-run should not create metadata.csv"
else
    PASS=$((PASS + 1))
    echo "  PASS: dry-run: metadata.csv not created"
fi

if [[ -f "$TMPDIR_DRY/scenes/intent.csv" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: dry-run should not create intent.csv"
else
    PASS=$((PASS + 1))
    echo "  PASS: dry-run: intent.csv not created"
fi

# Verify scene files unchanged
after_index_md5=$(md5 -q "$TMPDIR_DRY/scenes/scene-index.yaml" 2>/dev/null || md5sum "$TMPDIR_DRY/scenes/scene-index.yaml" | awk '{print $1}')
after_scene_md5=$(md5 -q "$TMPDIR_DRY/scenes/act1-sc01.md" 2>/dev/null || md5sum "$TMPDIR_DRY/scenes/act1-sc01.md" | awk '{print $1}')

assert_equals "$before_index_md5" "$after_index_md5" "dry-run: scene-index.yaml unchanged"
assert_equals "$before_scene_md5" "$after_scene_md5" "dry-run: act1-sc01.md unchanged"

# Verify no backup created
if [[ -d "$TMPDIR_DRY/working/backups/pre-migration" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: dry-run should not create backup directory"
else
    PASS=$((PASS + 1))
    echo "  PASS: dry-run: no backup directory created"
fi

# Verify output mentions dry run
assert_contains "$output" "DRY RUN" "dry-run: output mentions DRY RUN"

cleanup_migrate_tmpdir "$TMPDIR_DRY"

# ============================================================================
# Test: Execute mode — scene metadata migration
# ============================================================================

TMPDIR_EXEC=$(setup_migrate_tmpdir)

output=$("$MIGRATE_SCRIPT" --execute --project-dir "$TMPDIR_EXEC" 2>&1)

# --- metadata.csv ---
assert_file_exists "$TMPDIR_EXEC/scenes/metadata.csv" "execute: metadata.csv created"

meta_header=$(head -1 "$TMPDIR_EXEC/scenes/metadata.csv")
assert_equals "id|seq|title|pov|setting|part|type|timeline_day|time_of_day|status|word_count|target_words" "$meta_header" "execute: metadata.csv header correct"

# Check row count (4 scenes + 1 header = 5 lines)
meta_lines=$(wc -l < "$TMPDIR_EXEC/scenes/metadata.csv" | tr -d ' ')
assert_equals "5" "$meta_lines" "execute: metadata.csv has 5 lines (header + 4 scenes)"

# Check act1-sc01 row
meta_content=$(cat "$TMPDIR_EXEC/scenes/metadata.csv")
assert_contains "$meta_content" "act1-sc01" "execute: metadata.csv contains act1-sc01"
assert_contains "$meta_content" "The Finest Cartographer" "execute: metadata.csv contains title"
assert_contains "$meta_content" "Dorren Hayle" "execute: metadata.csv contains pov"
assert_contains "$meta_content" "Pressure Cartography Office" "execute: metadata.csv contains setting"
assert_contains "$meta_content" "2400" "execute: metadata.csv contains word_count"
assert_contains "$meta_content" "drafted" "execute: metadata.csv contains status"

# Check act2-sc01 row (has null words → should be empty)
act2_row=$(grep "^act2-sc01|" "$TMPDIR_EXEC/scenes/metadata.csv")
assert_contains "$act2_row" "pending" "execute: act2-sc01 has pending status"
assert_contains "$act2_row" "2800" "execute: act2-sc01 has target_words 2800"

# --- intent.csv ---
assert_file_exists "$TMPDIR_EXEC/scenes/intent.csv" "execute: intent.csv created"

intent_header=$(head -1 "$TMPDIR_EXEC/scenes/intent.csv")
assert_equals "id|function|emotional_arc|characters|threads|motifs|notes" "$intent_header" "execute: intent.csv header correct"

intent_content=$(cat "$TMPDIR_EXEC/scenes/intent.csv")
assert_contains "$intent_content" "act1-sc01" "execute: intent.csv contains act1-sc01"
assert_contains "$intent_content" "Establishes Dorren as institutional gatekeeper" "execute: intent.csv contains function"

# intent.csv should have 5 lines (header + 4 scenes)
intent_lines=$(wc -l < "$TMPDIR_EXEC/scenes/intent.csv" | tr -d ' ')
assert_equals "5" "$intent_lines" "execute: intent.csv has 5 lines"

# ============================================================================
# Test: Execute mode — frontmatter stripping
# ============================================================================

# act1-sc01.md should no longer start with ---
first_line=$(head -1 "$TMPDIR_EXEC/scenes/act1-sc01.md")
assert_not_contains "$first_line" "---" "execute: act1-sc01.md frontmatter stripped"

# act1-sc02.md should no longer start with ---
first_line=$(head -1 "$TMPDIR_EXEC/scenes/act1-sc02.md")
assert_not_contains "$first_line" "---" "execute: act1-sc02.md frontmatter stripped"

# act2-sc01.md should no longer start with ---
first_line=$(head -1 "$TMPDIR_EXEC/scenes/act2-sc01.md")
assert_not_contains "$first_line" "---" "execute: act2-sc01.md frontmatter stripped"

# new-x1.md had no frontmatter — first line should still be content
first_line_new=$(head -1 "$TMPDIR_EXEC/scenes/new-x1.md")
assert_not_contains "$first_line_new" "---" "execute: new-x1.md has no frontmatter marker"

# Content should be preserved after stripping
scene_content=$(cat "$TMPDIR_EXEC/scenes/act1-sc01.md")
assert_contains "$scene_content" "Dorren Hayle pressed the brass calipers" "execute: act1-sc01.md content preserved"

scene_content=$(cat "$TMPDIR_EXEC/scenes/act1-sc02.md")
assert_contains "$scene_content" "Dorren sat at her desk" "execute: act1-sc02.md content preserved"

# ============================================================================
# Test: Execute mode — backup created
# ============================================================================

assert_file_exists "$TMPDIR_EXEC/working/backups/pre-migration/scenes/scene-index.yaml" "execute: backup of scene-index.yaml"
assert_file_exists "$TMPDIR_EXEC/working/backups/pre-migration/scenes/act1-sc01.md" "execute: backup of act1-sc01.md"

# Backup should have original frontmatter
backup_first=$(head -1 "$TMPDIR_EXEC/working/backups/pre-migration/scenes/act1-sc01.md")
assert_equals "---" "$backup_first" "execute: backup has original frontmatter"

# ============================================================================
# Test: Execute mode — chapter-map.csv
# ============================================================================

if [[ -f "$TMPDIR_EXEC/reference/chapter-map.yaml" ]]; then
    assert_file_exists "$TMPDIR_EXEC/reference/chapter-map.csv" "execute: chapter-map.csv created"

    cm_header=$(head -1 "$TMPDIR_EXEC/reference/chapter-map.csv")
    assert_equals "seq|title|heading|part|scenes" "$cm_header" "execute: chapter-map.csv header correct"

    cm_content=$(cat "$TMPDIR_EXEC/reference/chapter-map.csv")
    assert_contains "$cm_content" "The Finest Cartographer" "execute: chapter-map.csv contains chapter title"
    assert_contains "$cm_content" "act1-sc01" "execute: chapter-map.csv contains scene ref"
    assert_contains "$cm_content" "numbered-titled" "execute: chapter-map.csv contains heading type"

    # 2 chapters + 1 header = 3 lines
    cm_lines=$(wc -l < "$TMPDIR_EXEC/reference/chapter-map.csv" | tr -d ' ')
    assert_equals "3" "$cm_lines" "execute: chapter-map.csv has 3 lines"
fi

# ============================================================================
# Test: Execute mode — findings.csv
# ============================================================================

if [[ -d "$TMPDIR_EXEC/working/evaluations/eval-test" ]]; then
    assert_file_exists "$TMPDIR_EXEC/working/evaluations/eval-test/findings.csv" "execute: findings.csv created"

    f_header=$(head -1 "$TMPDIR_EXEC/working/evaluations/eval-test/findings.csv")
    assert_equals "id|severity|category|location|finding|suggestion" "$f_header" "execute: findings.csv header correct"

    f_content=$(cat "$TMPDIR_EXEC/working/evaluations/eval-test/findings.csv")
    assert_contains "$f_content" "high" "execute: findings.csv contains severity"
    assert_contains "$f_content" "pacing" "execute: findings.csv contains category"
    assert_contains "$f_content" "act1-sc01" "execute: findings.csv contains location"

    # 4 findings + 1 header = 5 lines
    f_lines=$(wc -l < "$TMPDIR_EXEC/working/evaluations/eval-test/findings.csv" | tr -d ' ')
    assert_equals "5" "$f_lines" "execute: findings.csv has 5 lines"
fi

# ============================================================================
# Test: Execute mode — revision-plan.csv
# ============================================================================

if [[ -f "$TMPDIR_EXEC/working/plans/revision-plan.yaml" ]]; then
    assert_file_exists "$TMPDIR_EXEC/working/plans/revision-plan.csv" "execute: revision-plan.csv created"

    rp_header=$(head -1 "$TMPDIR_EXEC/working/plans/revision-plan.csv")
    assert_equals "pass|name|purpose|scope|targets|guidance|protection|findings|status|model_tier" "$rp_header" "execute: revision-plan.csv header correct"

    rp_content=$(cat "$TMPDIR_EXEC/working/plans/revision-plan.csv")
    assert_contains "$rp_content" "prose-tightening" "execute: revision-plan.csv contains pass name"
    assert_contains "$rp_content" "character-arc-deepening" "execute: revision-plan.csv contains second pass"
    assert_contains "$rp_content" "pending" "execute: revision-plan.csv contains status"

    # 2 passes + 1 header = 3 lines
    rp_lines=$(wc -l < "$TMPDIR_EXEC/working/plans/revision-plan.csv" | tr -d ' ')
    assert_equals "3" "$rp_lines" "execute: revision-plan.csv has 3 lines"
fi

# ============================================================================
# Test: Execute mode — pipeline.csv
# ============================================================================

if [[ -f "$TMPDIR_EXEC/working/pipeline.yaml" ]]; then
    assert_file_exists "$TMPDIR_EXEC/working/pipeline.csv" "execute: pipeline.csv created"

    pp_header=$(head -1 "$TMPDIR_EXEC/working/pipeline.csv")
    assert_equals "cycle|started|status|evaluation|plan|summary" "$pp_header" "execute: pipeline.csv header correct"

    pp_content=$(cat "$TMPDIR_EXEC/working/pipeline.csv")
    assert_contains "$pp_content" "2026-03-05" "execute: pipeline.csv contains date"
    assert_contains "$pp_content" "evaluating" "execute: pipeline.csv contains status"
    assert_contains "$pp_content" "eval-20260305-103251" "execute: pipeline.csv contains evaluation ref"

    # 3 cycles + 1 header = 4 lines
    pp_lines=$(wc -l < "$TMPDIR_EXEC/working/pipeline.csv" | tr -d ' ')
    assert_equals "4" "$pp_lines" "execute: pipeline.csv has 4 lines"
fi

# ============================================================================
# Test: --skip-backup flag
# ============================================================================

TMPDIR_NOBK=$(setup_migrate_tmpdir)
"$MIGRATE_SCRIPT" --execute --skip-backup --project-dir "$TMPDIR_NOBK" >/dev/null 2>&1

if [[ -d "$TMPDIR_NOBK/working/backups/pre-migration" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: --skip-backup should not create backup directory"
else
    PASS=$((PASS + 1))
    echo "  PASS: --skip-backup: no backup created"
fi

# But CSVs should still be created
assert_file_exists "$TMPDIR_NOBK/scenes/metadata.csv" "--skip-backup: metadata.csv still created"

cleanup_migrate_tmpdir "$TMPDIR_NOBK"

# ============================================================================
# Cleanup
# ============================================================================

cleanup_migrate_tmpdir "$TMPDIR_EXEC"

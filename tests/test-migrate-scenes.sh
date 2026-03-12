#!/bin/bash
# test-migrate-scenes.sh — Tests for scripts/storyforge-migrate-scenes
#
# Run via: ./tests/run-tests.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions (from run-tests.sh)

MIGRATE_SCRIPT="${PLUGIN_DIR}/scripts/storyforge-migrate-scenes"

# ============================================================================
# Helper: build a temp project with numeric scene IDs
# ============================================================================

_make_migrate_fixture() {
    local tmpdir
    tmpdir="$(mktemp -d)"

    # Minimal storyforge.yaml
    cat > "${tmpdir}/storyforge.yaml" <<'YAML'
project:
  title: "Test Project"
  genre: "fiction"
phase: drafting
artifacts:
  scene_index:
    exists: true
    path: scenes/scene-index.yaml
  chapter_map:
    exists: true
    path: reference/chapter-map.yaml
YAML

    mkdir -p "${tmpdir}/scenes"
    mkdir -p "${tmpdir}/reference"

    # Scene 1: "Geometry of Dying"
    cat > "${tmpdir}/scenes/1.md" <<'MD'
---
id: "1"
title: "Geometry of Dying"
pov: "Alice"
status: "drafted"
---

Scene one content here.
MD

    # Scene 2: "The Bridge at Midnight"
    cat > "${tmpdir}/scenes/2.md" <<'MD'
---
id: "2"
title: "The Bridge at Midnight"
pov: "Bob"
status: "drafted"
---

Scene two content here.
MD

    # Scene 3: "Geometry of Dying (Reprise)"  — will collide slug with scene 1
    cat > "${tmpdir}/scenes/3.md" <<'MD'
---
id: "3"
title: "Geometry of Dying (Reprise)"
pov: "Alice"
status: "pending"
---

Scene three content here.
MD

    # scene-index.yaml
    cat > "${tmpdir}/scenes/scene-index.yaml" <<'YAML'
scenes:
  - id: 1
    title: "Geometry of Dying"
    pov: "Alice"
    status: drafted

  - id: 2
    title: "The Bridge at Midnight"
    pov: "Bob"
    status: drafted

  - id: 3
    title: "Geometry of Dying (Reprise)"
    pov: "Alice"
    status: pending
YAML

    # chapter-map.yaml
    cat > "${tmpdir}/reference/chapter-map.yaml" <<'YAML'
chapters:
  - title: "Part One"
    scenes:
      - 1
      - 2

  - title: "Part Two"
    scenes:
      - 3
YAML

    echo "$tmpdir"
}

_make_already_slugged_fixture() {
    local tmpdir
    tmpdir="$(mktemp -d)"

    cat > "${tmpdir}/storyforge.yaml" <<'YAML'
project:
  title: "Test Project"
  genre: "fiction"
phase: drafting
artifacts:
  scene_index:
    exists: true
    path: scenes/scene-index.yaml
  chapter_map:
    exists: true
    path: reference/chapter-map.yaml
YAML

    mkdir -p "${tmpdir}/scenes"
    mkdir -p "${tmpdir}/reference"

    # Scene with numeric ID
    cat > "${tmpdir}/scenes/1.md" <<'MD'
---
id: "1"
title: "Opening Scene"
status: "drafted"
---

Content.
MD

    # Scene already using a slug ID
    cat > "${tmpdir}/scenes/already-a-slug.md" <<'MD'
---
id: "already-a-slug"
title: "Already Slugged"
status: "drafted"
---

Content.
MD

    cat > "${tmpdir}/scenes/scene-index.yaml" <<'YAML'
scenes:
  - id: 1
    title: "Opening Scene"
    status: drafted

  - id: already-a-slug
    title: "Already Slugged"
    status: drafted
YAML

    cat > "${tmpdir}/reference/chapter-map.yaml" <<'YAML'
chapters:
  - title: "Only Chapter"
    scenes:
      - 1
      - already-a-slug
YAML

    echo "$tmpdir"
}

# ============================================================================
# Test 1: Dry-run slug generation — preview only, no file changes
# ============================================================================

_tmpdir1="$(_make_migrate_fixture)"

result=$(bash "$MIGRATE_SCRIPT" --dry-run --project "$_tmpdir1" 2>&1)
rc=$?

assert_exit_code "0" "$rc" "migrate dry-run: exits 0"
assert_contains "$result" "geometry-of-dying" "migrate dry-run: shows slug for scene 1"
assert_contains "$result" "bridge-at-midnight" "migrate dry-run: shows slug for scene 2"
assert_contains "$result" "geometry-of-dying-reprise" "migrate dry-run: shows disambiguated slug for scene 3"

# Files must NOT be renamed
assert_file_exists "${_tmpdir1}/scenes/1.md" "migrate dry-run: 1.md not renamed"
assert_file_exists "${_tmpdir1}/scenes/2.md" "migrate dry-run: 2.md not renamed"
assert_file_exists "${_tmpdir1}/scenes/3.md" "migrate dry-run: 3.md not renamed"

# Index must NOT be modified
idx_content=$(cat "${_tmpdir1}/scenes/scene-index.yaml")
assert_contains "$idx_content" "id: 1" "migrate dry-run: scene-index.yaml unchanged"

rm -rf "$_tmpdir1"

# ============================================================================
# Test 2: Actual migration — files renamed, YAML updated, frontmatter updated
# ============================================================================

_tmpdir2="$(_make_migrate_fixture)"

result=$(bash "$MIGRATE_SCRIPT" --project "$_tmpdir2" 2>&1)
rc=$?

assert_exit_code "0" "$rc" "migrate: exits 0"

# Old files gone
if [[ -f "${_tmpdir2}/scenes/1.md" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: migrate: 1.md should have been renamed"
else
    PASS=$((PASS + 1))
    echo "  PASS: migrate: 1.md was renamed"
fi

if [[ -f "${_tmpdir2}/scenes/2.md" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: migrate: 2.md should have been renamed"
else
    PASS=$((PASS + 1))
    echo "  PASS: migrate: 2.md was renamed"
fi

if [[ -f "${_tmpdir2}/scenes/3.md" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: migrate: 3.md should have been renamed"
else
    PASS=$((PASS + 1))
    echo "  PASS: migrate: 3.md was renamed"
fi

# New slug files exist
assert_file_exists "${_tmpdir2}/scenes/geometry-of-dying.md" "migrate: geometry-of-dying.md created"
assert_file_exists "${_tmpdir2}/scenes/bridge-at-midnight.md" "migrate: bridge-at-midnight.md created"
assert_file_exists "${_tmpdir2}/scenes/geometry-of-dying-reprise.md" "migrate: geometry-of-dying-reprise.md created"

# Frontmatter id: fields updated
sc1_content=$(cat "${_tmpdir2}/scenes/geometry-of-dying.md")
assert_contains "$sc1_content" 'id: "geometry-of-dying"' "migrate: frontmatter id updated for scene 1"

sc2_content=$(cat "${_tmpdir2}/scenes/bridge-at-midnight.md")
assert_contains "$sc2_content" 'id: "bridge-at-midnight"' "migrate: frontmatter id updated for scene 2"

sc3_content=$(cat "${_tmpdir2}/scenes/geometry-of-dying-reprise.md")
assert_contains "$sc3_content" 'id: "geometry-of-dying-reprise"' "migrate: frontmatter id updated for scene 3"

# scene-index.yaml updated
idx_content=$(cat "${_tmpdir2}/scenes/scene-index.yaml")
assert_contains "$idx_content" "geometry-of-dying" "migrate: scene-index.yaml updated with slug 1"
assert_contains "$idx_content" "bridge-at-midnight" "migrate: scene-index.yaml updated with slug 2"
assert_contains "$idx_content" "geometry-of-dying-reprise" "migrate: scene-index.yaml updated with slug 3"
assert_not_contains "$idx_content" "id: 1" "migrate: scene-index.yaml no longer has numeric id 1"
assert_not_contains "$idx_content" "id: 2" "migrate: scene-index.yaml no longer has numeric id 2"
assert_not_contains "$idx_content" "id: 3" "migrate: scene-index.yaml no longer has numeric id 3"

# chapter-map.yaml updated
chap_content=$(cat "${_tmpdir2}/reference/chapter-map.yaml")
assert_contains "$chap_content" "geometry-of-dying" "migrate: chapter-map.yaml updated with slug 1"
assert_contains "$chap_content" "bridge-at-midnight" "migrate: chapter-map.yaml updated with slug 2"
assert_contains "$chap_content" "geometry-of-dying-reprise" "migrate: chapter-map.yaml updated with slug 3"

rm -rf "$_tmpdir2"

# ============================================================================
# Test 3: Already-slugged scenes are skipped
# ============================================================================

_tmpdir3="$(_make_already_slugged_fixture)"

result=$(bash "$MIGRATE_SCRIPT" --project "$_tmpdir3" 2>&1)
rc=$?

assert_exit_code "0" "$rc" "migrate skip: exits 0"

# The already-slugged file must still exist unchanged
assert_file_exists "${_tmpdir3}/scenes/already-a-slug.md" "migrate skip: already-slug file preserved"

# Output should mention SKIP for the already-slugged scene
assert_contains "$result" "SKIP" "migrate skip: already-slug scene is skipped"

# The numeric scene should be migrated
assert_file_exists "${_tmpdir3}/scenes/opening-scene.md" "migrate skip: numeric scene was migrated"

if [[ -f "${_tmpdir3}/scenes/1.md" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: migrate skip: 1.md should have been renamed"
else
    PASS=$((PASS + 1))
    echo "  PASS: migrate skip: 1.md was renamed"
fi

rm -rf "$_tmpdir3"

# ============================================================================
# Test 4: Slug collision handling
# ============================================================================

_tmpdir4="$(_make_migrate_fixture)"

result=$(bash "$MIGRATE_SCRIPT" --dry-run --project "$_tmpdir4" 2>&1)

# Scene 1 and scene 3 both start with "Geometry of Dying" — they should get different slugs
assert_contains "$result" "geometry-of-dying" "migrate collision: base slug present"
assert_contains "$result" "geometry-of-dying-reprise" "migrate collision: disambiguated slug present"

# Verify they are DIFFERENT slugs (both present means they didn't overwrite each other)
slug1_count=$(echo "$result" | grep -c "geometry-of-dying-reprise" || true)
assert_not_contains "$result" "geometry-of-dying -> geometry-of-dying" "migrate collision: no duplicate slug assignment"

rm -rf "$_tmpdir4"

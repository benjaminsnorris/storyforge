# Slug-Based Scene Naming Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch scene file naming from numeric IDs (`1.md`, `2.md`) to descriptive slugs (`geometry-of-dying.md`, `sheriffs-ledger.md`), reinforcing that scenes are single POV passes designed to be reshuffled freely.

**Architecture:** The core shell scripts already treat scene IDs as opaque strings — no code changes needed in assembly, evaluation, or prompt building. The work is: (1) update documentation, schema, and skill instructions to establish slug naming as the convention, (2) add a migration command for existing projects, (3) reinforce the scene-as-camera-pass philosophy in scene creation workflows.

**Tech Stack:** Bash scripts, YAML, Markdown skill definitions

---

## File Structure

### New Files
- `scripts/storyforge-migrate-scenes` — CLI tool to rename numeric scenes to slugs
- `tests/test-migrate-scenes.sh` — Tests for the migration tool

### Modified Files
- `references/scene-schema.md` — Update naming convention guidance
- `skills/scenes/SKILL.md` — Update scene creation to use slugs, reinforce POV philosophy
- `skills/develop/SKILL.md` — Reinforce scene philosophy in development workflows
- `skills/forge/SKILL.md` — Update scene references
- `skills/produce/SKILL.md` — Update any scene naming references
- `skills/plan-revision/SKILL.md` — Update ID examples
- `templates/storyforge.yaml` — Update scene-index template examples
- `scripts/lib/revision-passes.sh` — Simplify resolve_scene_file() fallback
- `tests/test-revision-passes.sh` — Update tests for simplified resolver

### No Changes Needed (already format-agnostic)
- `scripts/lib/assembly.sh` — uses `${scene_id}.md` directly
- `scripts/storyforge-evaluate` — uses `${id}.md` directly
- `scripts/storyforge-write` — uses `${SCENE_ID}.md` directly
- `scripts/lib/prompt-builder.sh` — uses `${scene_id}.md` directly
- `scripts/lib/common.sh` — uses `${scene_id}.md` directly

---

## Chunk 1: Documentation and Convention

### Task 1: Update Scene Schema Reference

**Files:**
- Modify: `references/scene-schema.md`

- [ ] **Step 1: Read current scene-schema.md**

Read the full file to understand current naming guidance.

- [ ] **Step 2: Update naming convention section**

Replace the current naming pattern guidance (lines ~101-108) with:

```markdown
### Scene ID Convention

Scene IDs are descriptive slugs that identify the scene by its content, not its position:

- **Format:** lowercase, hyphen-separated words (e.g., `geometry-of-dying`, `sheriffs-ledger`, `hidden-canyon`)
- **Length:** 2-5 words — specific enough to identify, short enough to type
- **Content-based:** Name describes what happens or the key image, not sequence
- **No numbers:** Avoid numeric IDs or positional prefixes — ordering lives in `scene-index.yaml` and `chapter-map.yaml`

Good: `geometry-of-dying`, `first-meridian`, `woman-in-cellars-light`
Bad: `1`, `scene-01`, `ch3-sc2`, `act1-opening`

For new scenes without clear content yet, use a working slug: `opening-chase`, `bridge-confrontation`, `quiet-morning`. Rename later if the scene evolves.
```

- [ ] **Step 3: Add scene philosophy section**

Add after the naming convention:

```markdown
### What Is a Scene?

A scene is a single continuous pass of experience — one camera angle before the lens shifts. The moment the POV changes, or time jumps, or location shifts, that's a new scene.

Scenes are **not mini-chapters**. They may be extremely short (a single paragraph) or long (several pages). Length is dictated by the experience, not by structural convention.

Scenes are designed to be **reshuffled**. The ordering in `scene-index.yaml` is a working sequence, not a permanent assignment. If the story is better served by moving a scene, move it — that's what the index is for.
```

- [ ] **Step 4: Commit**

```bash
git add references/scene-schema.md
git commit -m "Update scene schema: slug-based naming, camera-pass philosophy"
```

### Task 2: Update Scene Index Template

**Files:**
- Modify: `templates/storyforge.yaml`

- [ ] **Step 1: Read current template**

Read the storyforge.yaml template to find scene-index examples.

- [ ] **Step 2: Update scene-index example IDs**

Change example IDs from `act1-sc01` pattern to descriptive slugs:

```yaml
scenes:
  - id: "geometry-of-dying"
    title: "The Geometry of Dying"
    pov: character-name
    location: location-name
    timeline_position: 1
    status: outline
    summary: >
      Brief description of what happens in this scene.
  - id: "sheriffs-ledger"
    title: "The Sheriff's Ledger"
    ...
```

- [ ] **Step 3: Commit**

```bash
git add templates/storyforge.yaml
git commit -m "Update scene-index template to use slug-based IDs"
```

### Task 3: Update Scenes Skill

**Files:**
- Modify: `skills/scenes/SKILL.md`

- [ ] **Step 1: Read current scenes skill**

Read the full SKILL.md to understand current scene creation guidance.

- [ ] **Step 2: Update ID generation guidance**

When the skill creates or proposes new scenes, it should:
- Generate slugs from the scene title or key image (e.g., "The Geometry of Dying" → `geometry-of-dying`)
- Never use numeric IDs or positional prefixes
- Keep slugs to 2-5 hyphenated words

- [ ] **Step 3: Add scene philosophy reminder**

Add near the top of the skill:

```markdown
**Scene philosophy:** A scene is a single continuous pass of experience — one camera angle. Not a mini-chapter. Scenes can be a single paragraph or many pages. They are designed to be reshuffled freely; order lives in the index, not the filename.
```

- [ ] **Step 4: Commit**

```bash
git add skills/scenes/SKILL.md
git commit -m "Update scenes skill: slug-based IDs, camera-pass philosophy"
```

### Task 4: Update Plan-Revision Skill

**Files:**
- Modify: `skills/plan-revision/SKILL.md`

- [ ] **Step 1: Read current plan-revision skill**

Find the CRITICAL instruction about scene ID matching (around line 85).

- [ ] **Step 2: Update the ID matching instruction**

Update the example to use slug-based IDs instead of numeric:

```markdown
CRITICAL: Scene IDs in scope lists must match scene-index.yaml exactly. Read the `- id:`
values from `scenes/scene-index.yaml` and use them verbatim. Scene IDs are descriptive
slugs — they could be `geometry-of-dying`, `sheriffs-ledger`, or `hidden-canyon`.
Do NOT construct IDs by guessing — always read from the index.
```

- [ ] **Step 3: Commit**

```bash
git add skills/plan-revision/SKILL.md
git commit -m "Update plan-revision skill: slug-based ID examples"
```

### Task 5: Update Develop and Forge Skills

**Files:**
- Modify: `skills/develop/SKILL.md`
- Modify: `skills/forge/SKILL.md`

- [ ] **Step 1: Read both skills**

Identify any scene naming references or scene creation guidance.

- [ ] **Step 2: Add scene philosophy where scene creation is discussed**

Anywhere scenes are created or proposed, reinforce:
- Slugs not numbers
- Camera-pass definition
- Scenes are meant to be reshuffled

- [ ] **Step 3: Commit**

```bash
git add skills/develop/SKILL.md skills/forge/SKILL.md
git commit -m "Reinforce scene philosophy in develop and forge skills"
```

---

## Chunk 2: Migration Tool

### Task 6: Write Migration Tool Tests

**Files:**
- Create: `tests/test-migrate-scenes.sh`

- [ ] **Step 1: Write test scaffold**

```bash
#!/bin/bash
# Test: storyforge-migrate-scenes
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
source "${PLUGIN_DIR}/tests/test-helpers.sh"

MIGRATE_SCRIPT="${PLUGIN_DIR}/scripts/storyforge-migrate-scenes"

setup_test_project() {
    local tmp
    tmp=$(mktemp -d)
    mkdir -p "$tmp/scenes" "$tmp/reference"

    # Create numeric scene files
    cat > "$tmp/scenes/1.md" << 'SCENE'
---
id: 1
title: "The Geometry of Dying"
pov: colson
---
Opening scene content.
SCENE

    cat > "$tmp/scenes/2.md" << 'SCENE'
---
id: 2
title: "The Sheriff's Ledger"
pov: halloran
---
Second scene content.
SCENE

    cat > "$tmp/scenes/3.md" << 'SCENE'
---
id: 3
title: "First Meridian"
pov: colson
---
Third scene content.
SCENE

    # Create scene-index.yaml
    cat > "$tmp/scenes/scene-index.yaml" << 'YAML'
scenes:
  - id: 1
    title: "The Geometry of Dying"
  - id: 2
    title: "The Sheriff's Ledger"
  - id: 3
    title: "First Meridian"
YAML

    # Create chapter-map.yaml
    cat > "$tmp/reference/chapter-map.yaml" << 'YAML'
chapters:
  - title: "The Geometry of Dying"
    scenes:
      - 1
      - 2
  - title: "First Meridian"
    scenes:
      - 3
YAML

    echo "$tmp"
}
```

- [ ] **Step 2: Write test for slug generation from title**

```bash
test_slug_generation() {
    local project
    project=$(setup_test_project)

    # Run migration in dry-run mode
    local output
    output=$(bash "$MIGRATE_SCRIPT" --project "$project" --dry-run 2>&1)

    # Verify slug proposals
    assert_contains "$output" "1.md -> geometry-of-dying.md"
    assert_contains "$output" "2.md -> sheriffs-ledger.md"
    assert_contains "$output" "3.md -> first-meridian.md"

    # Verify files NOT renamed in dry-run
    assert_file_exists "$project/scenes/1.md"
    assert_file_exists "$project/scenes/2.md"

    rm -rf "$project"
    echo "PASS: test_slug_generation"
}
```

- [ ] **Step 3: Write test for actual migration**

```bash
test_migration_renames_files() {
    local project
    project=$(setup_test_project)
    cd "$project" && git init && git add -A && git commit -m "init" && cd -

    bash "$MIGRATE_SCRIPT" --project "$project"

    # Files renamed
    assert_file_exists "$project/scenes/geometry-of-dying.md"
    assert_file_exists "$project/scenes/sheriffs-ledger.md"
    assert_file_exists "$project/scenes/first-meridian.md"
    assert_file_not_exists "$project/scenes/1.md"
    assert_file_not_exists "$project/scenes/2.md"

    # scene-index.yaml updated
    assert_contains "$(cat "$project/scenes/scene-index.yaml")" "id: geometry-of-dying"
    assert_contains "$(cat "$project/scenes/scene-index.yaml")" "id: sheriffs-ledger"

    # chapter-map.yaml updated
    assert_contains "$(cat "$project/reference/chapter-map.yaml")" "geometry-of-dying"
    assert_contains "$(cat "$project/reference/chapter-map.yaml")" "sheriffs-ledger"

    # Frontmatter in scene files updated
    assert_contains "$(cat "$project/scenes/geometry-of-dying.md")" "id: geometry-of-dying"

    rm -rf "$project"
    echo "PASS: test_migration_renames_files"
}
```

- [ ] **Step 4: Write test for slug collision handling**

```bash
test_slug_collision() {
    local project
    project=$(setup_test_project)

    # Add a scene with a title that would produce same slug
    cat > "$project/scenes/4.md" << 'SCENE'
---
id: 4
title: "The Geometry of Dying (Reprise)"
---
Content.
SCENE

    # Update scene-index
    cat >> "$project/scenes/scene-index.yaml" << 'YAML'
  - id: 4
    title: "The Geometry of Dying (Reprise)"
YAML

    cd "$project" && git init && git add -A && git commit -m "init" && cd -

    local output
    output=$(bash "$MIGRATE_SCRIPT" --project "$project" --dry-run 2>&1)

    # Should handle collision by appending a disambiguator
    assert_contains "$output" "geometry-of-dying-reprise.md"

    rm -rf "$project"
    echo "PASS: test_slug_collision"
}
```

- [ ] **Step 5: Run tests to verify they fail**

```bash
bash tests/test-migrate-scenes.sh
```

Expected: FAIL — script doesn't exist yet.

- [ ] **Step 6: Commit**

```bash
git add tests/test-migrate-scenes.sh
git commit -m "Add tests for scene migration tool"
```

### Task 7: Implement Migration Tool

**Files:**
- Create: `scripts/storyforge-migrate-scenes`

- [ ] **Step 1: Write the migration script**

```bash
#!/bin/bash
set -eo pipefail

# storyforge-migrate-scenes — Convert numeric scene IDs to descriptive slugs
#
# Reads scene-index.yaml, generates slugs from scene titles, and:
#   1. Renames scene files (e.g., 1.md → geometry-of-dying.md)
#   2. Updates scene-index.yaml IDs
#   3. Updates chapter-map.yaml scene references
#   4. Updates frontmatter id: fields in scene files
#
# Usage:
#   ./storyforge migrate-scenes              # Run migration
#   ./storyforge migrate-scenes --dry-run    # Preview changes only

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# --- Argument parsing ---
DRY_RUN=false
PROJECT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --project) PROJECT_DIR="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$PROJECT_DIR" ]]; then
    detect_project_root
fi

SCENE_INDEX="${PROJECT_DIR}/scenes/scene-index.yaml"
CHAPTER_MAP="${PROJECT_DIR}/reference/chapter-map.yaml"
SCENES_DIR="${PROJECT_DIR}/scenes"

# --- Slug generation ---
slugify() {
    local title="$1"
    echo "$title" \
        | tr '[:upper:]' '[:lower:]' \
        | sed 's/[^a-z0-9 ]/ /g' \
        | sed 's/  */ /g' \
        | sed 's/^ //;s/ $//' \
        | tr ' ' '-' \
        | sed 's/--*/-/g' \
        | sed 's/^the-//'
}

# --- Read scenes from index ---
# Extract id and title pairs
declare -a OLD_IDS=()
declare -a TITLES=()
declare -a NEW_SLUGS=()

while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*id:[[:space:]]*(.*) ]]; then
        id="${BASH_REMATCH[1]}"
        id=$(echo "$id" | sed 's/^["'"'"']//;s/["'"'"']$//' | xargs)
        OLD_IDS+=("$id")
    elif [[ "$line" =~ ^[[:space:]]*title:[[:space:]]*(.*) ]]; then
        title="${BASH_REMATCH[1]}"
        title=$(echo "$title" | sed 's/^["'"'"']//;s/["'"'"']$//' | xargs)
        TITLES+=("$title")
    fi
done < "$SCENE_INDEX"

# --- Generate slugs and check for collisions ---
declare -A SLUG_COUNT=()

for (( i=0; i<${#OLD_IDS[@]}; i++ )); do
    slug=$(slugify "${TITLES[$i]}")

    # Handle collisions
    if [[ -n "${SLUG_COUNT[$slug]}" ]]; then
        SLUG_COUNT[$slug]=$(( ${SLUG_COUNT[$slug]} + 1 ))
        slug="${slug}-${SLUG_COUNT[$slug]}"
    else
        SLUG_COUNT[$slug]=1
    fi

    NEW_SLUGS+=("$slug")
done

# --- Preview or execute ---
echo "Scene ID Migration: ${#OLD_IDS[@]} scenes"
echo "========================================"

for (( i=0; i<${#OLD_IDS[@]}; i++ )); do
    old="${OLD_IDS[$i]}"
    new="${NEW_SLUGS[$i]}"

    if [[ "$old" == "$new" ]]; then
        echo "  SKIP: ${old}.md (already a slug)"
    else
        echo "  ${old}.md -> ${new}.md"
    fi
done

if [[ "$DRY_RUN" == true ]]; then
    echo ""
    echo "(dry run — no changes made)"
    exit 0
fi

echo ""
echo "Applying changes..."

# 1. Rename scene files
for (( i=0; i<${#OLD_IDS[@]}; i++ )); do
    old="${OLD_IDS[$i]}"
    new="${NEW_SLUGS[$i]}"
    [[ "$old" == "$new" ]] && continue

    if [[ -f "${SCENES_DIR}/${old}.md" ]]; then
        git -C "$PROJECT_DIR" mv "scenes/${old}.md" "scenes/${new}.md" 2>/dev/null \
            || mv "${SCENES_DIR}/${old}.md" "${SCENES_DIR}/${new}.md"
    fi
done

# 2. Update frontmatter id: in scene files
for (( i=0; i<${#OLD_IDS[@]}; i++ )); do
    old="${OLD_IDS[$i]}"
    new="${NEW_SLUGS[$i]}"
    [[ "$old" == "$new" ]] && continue

    scene_file="${SCENES_DIR}/${new}.md"
    if [[ -f "$scene_file" ]]; then
        sed -i '' "s/^id: *[\"']*${old}[\"']*/id: ${new}/" "$scene_file"
    fi
done

# 3. Update scene-index.yaml
for (( i=0; i<${#OLD_IDS[@]}; i++ )); do
    old="${OLD_IDS[$i]}"
    new="${NEW_SLUGS[$i]}"
    [[ "$old" == "$new" ]] && continue

    # Replace id: old with id: new (handle quoted and unquoted)
    sed -i '' "s/id: *[\"']*${old}[\"']*/id: ${new}/" "$SCENE_INDEX"
done

# 4. Update chapter-map.yaml
for (( i=0; i<${#OLD_IDS[@]}; i++ )); do
    old="${OLD_IDS[$i]}"
    new="${NEW_SLUGS[$i]}"
    [[ "$old" == "$new" ]] && continue

    # Replace scene references in the scenes: lists
    # Handle: - 1  or  - "1"  or  - '1'
    sed -i '' "s/- *[\"']*${old}[\"']* *$/- ${new}/" "$CHAPTER_MAP"
done

echo "Migration complete."
echo ""
echo "Next steps:"
echo "  1. Review changes: git diff"
echo "  2. Verify assembly: ./storyforge assemble --format markdown --no-pr"
echo "  3. Commit: git add -A && git commit -m 'Migrate scene IDs to descriptive slugs'"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/storyforge-migrate-scenes
```

- [ ] **Step 3: Run tests**

```bash
bash tests/test-migrate-scenes.sh
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/storyforge-migrate-scenes
git commit -m "Add scene migration tool: numeric IDs to descriptive slugs"
```

### Task 8: Add migrate-scenes to storyforge CLI

**Files:**
- Modify: meridian-line `storyforge` wrapper (and template)

- [ ] **Step 1: Add migrate-scenes case to the storyforge wrapper template**

The wrapper script in each project delegates to plugin scripts. Add `migrate-scenes` to the usage help and case statement. Since the wrapper uses a generic `storyforge-$COMMAND` pattern, this should already work if the script is named `storyforge-migrate-scenes`. Verify by running:

```bash
cd /path/to/project && ./storyforge migrate-scenes --dry-run
```

- [ ] **Step 2: Commit if changes needed**

---

## Chunk 3: Simplify Legacy Fallback

### Task 9: Simplify resolve_scene_file()

**Files:**
- Modify: `scripts/lib/revision-passes.sh:13-58`
- Modify: `tests/test-revision-passes.sh`

- [ ] **Step 1: Read current resolve_scene_file()**

Read lines 13-58 of revision-passes.sh to understand the three-tier fallback.

- [ ] **Step 2: Simplify to exact match + warning**

Replace the complex fallback with:

```bash
resolve_scene_file() {
    local scene_dir="$1"
    local sid="$2"

    # Exact match
    if [[ -f "${scene_dir}/${sid}.md" ]]; then
        echo "${scene_dir}/${sid}.md"
        return 0
    fi

    # Legacy numeric fallback: strip "scene-" prefix and leading zeros
    local stripped="${sid#scene-}"
    stripped="${stripped#Scene-}"
    stripped=$(echo "$stripped" | sed 's/^0*//')
    [[ -z "$stripped" ]] && stripped="0"

    if [[ "$stripped" != "$sid" && -f "${scene_dir}/${stripped}.md" ]]; then
        echo "[WARN] Scene '${sid}' resolved via legacy fallback to '${stripped}.md'. Consider running: ./storyforge migrate-scenes" >&2
        echo "${scene_dir}/${stripped}.md"
        return 0
    fi

    return 1
}
```

- [ ] **Step 3: Update tests to expect warning**

Update test-revision-passes.sh: the fallback tests should still pass but now emit a warning to stderr.

- [ ] **Step 4: Run tests**

```bash
bash tests/test-revision-passes.sh
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/revision-passes.sh tests/test-revision-passes.sh
git commit -m "Simplify scene file resolver, add migration warning for legacy numeric IDs"
```

---

## Chunk 4: Migrate Meridian Line (Optional — Run Separately)

### Task 10: Migrate Meridian Line Scenes

This task is run in the meridian-line project, not storyforge.

- [ ] **Step 1: Preview migration**

```bash
cd /Users/bennorris/Developer/meridian-line
CLAUDE_PLUGIN_ROOT=/Users/bennorris/Developer/storyforge ./storyforge migrate-scenes --dry-run
```

Review the proposed slug mappings. Adjust any that aren't clear enough.

- [ ] **Step 2: Run migration**

```bash
CLAUDE_PLUGIN_ROOT=/Users/bennorris/Developer/storyforge ./storyforge migrate-scenes
```

- [ ] **Step 3: Verify assembly still works**

```bash
CLAUDE_PLUGIN_ROOT=/Users/bennorris/Developer/storyforge ./storyforge assemble --format markdown --no-pr
```

- [ ] **Step 4: Review and commit**

```bash
git diff
git add -A
git commit -m "Migrate scene IDs from numeric to descriptive slugs"
```

- [ ] **Step 5: Verify web assembly**

```bash
CLAUDE_PLUGIN_ROOT=/Users/bennorris/Developer/storyforge ./storyforge assemble --format web --annotate --no-pr
```

Open in browser and verify annotations still work (scene `data-scene` attributes will now use slugs).

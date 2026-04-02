# Drop Legacy scene-metadata.csv Support

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all references to the legacy `scene-metadata.csv` file, making `scenes.csv` the only supported structural CSV. Existing projects must run `storyforge extract` to migrate.

**Architecture:** Every script and module currently resolves scene structural data through either `scene-metadata.csv` (legacy) or `scenes.csv` (elaboration pipeline), with fallback detection logic. We drop all fallback paths and point everything at `scenes.csv` directly. The `scene-intent.csv` file name is unchanged but its column set expands to match the elaboration model. `scene-briefs.csv` becomes a standard optional file.

**Key column differences:**
- Legacy `scene-metadata.csv`: `id|seq|title|pov|location|part|type|timeline_day|time_of_day|status|word_count|target_words`
- New `scenes.csv`: `id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words`
- Differences: column order (part moved before pov), added `duration` column. All code reads by column name so order doesn't matter — just need to update header constants.

**Legacy intent:** `id|function|emotional_arc|characters|threads|motifs|notes`
**New intent:** `id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads`

---

### Task 1: Python — prompts.py (core resolution functions)

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts.py:145-164`

The `_resolve_metadata_csv()` and `_resolve_intent_csv()` functions are imported by `enrich.py` and used throughout `prompts.py`. Replace them with direct-path resolvers for the three-file model.

- [ ] **Step 1: Replace `_resolve_metadata_csv` with `_resolve_scenes_csv`**

In `scripts/lib/python/storyforge/prompts.py`, replace lines 145-153:

```python
def _resolve_scenes_csv(project_dir: str) -> str:
    """Find the scenes CSV (structural identity)."""
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    if os.path.isfile(path):
        return path
    return ''
```

- [ ] **Step 2: Simplify `_resolve_intent_csv`**

Replace lines 156-164 — remove the `scenes/intent.csv` fallback:

```python
def _resolve_intent_csv(project_dir: str) -> str:
    """Find the scene-intent CSV."""
    path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    if os.path.isfile(path):
        return path
    return ''
```

- [ ] **Step 3: Add `_resolve_briefs_csv`**

Add after `_resolve_intent_csv`:

```python
def _resolve_briefs_csv(project_dir: str) -> str:
    """Find the scene-briefs CSV (drafting contracts)."""
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    if os.path.isfile(path):
        return path
    return ''
```

- [ ] **Step 4: Update `get_scene_metadata` to use `_resolve_scenes_csv`**

In the `get_scene_metadata()` function (line 167), replace the call to `_resolve_metadata_csv` with `_resolve_scenes_csv`. Update the docstring to say "scenes.csv" instead of "scene-metadata.csv".

- [ ] **Step 5: Update `get_previous_scene` to use `_resolve_scenes_csv`**

In `get_previous_scene()` (line 235), replace `_resolve_metadata_csv(project_dir)` with `_resolve_scenes_csv(project_dir)`.

- [ ] **Step 6: Run tests**

```bash
cd /Users/cadencedev/Developer/storyforge/.worktrees/clean-up-scene-metadata && ./tests/run-tests.sh tests/test-python.sh
```

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/prompts.py && git commit -m "Update prompts.py: drop scene-metadata.csv, use scenes.csv" && git push
```

---

### Task 2: Python — enrich.py (imports and field constants)

**Files:**
- Modify: `scripts/lib/python/storyforge/enrich.py:15-31`

`enrich.py` imports `_resolve_metadata_csv` from `prompts.py` and defines `METADATA_FIELDS` referencing fields "stored in scene-metadata.csv".

- [ ] **Step 1: Update imports**

In `scripts/lib/python/storyforge/enrich.py`, line 18, replace `_resolve_metadata_csv` with `_resolve_scenes_csv` in the import statement:

```python
from .prompts import (
    _read_csv_header_and_rows,
    read_csv_field,
    _resolve_scenes_csv,
    _resolve_intent_csv,
)
```

- [ ] **Step 2: Update field constant comments**

Line 27: change comment from `#: Fields stored in scene-metadata.csv` to `#: Fields stored in scenes.csv`

- [ ] **Step 3: Update all calls from `_resolve_metadata_csv` to `_resolve_scenes_csv`**

Search the file for any remaining calls to `_resolve_metadata_csv` and replace with `_resolve_scenes_csv`. This includes any usage in `apply_enrich_result()` and `build_enrich_prompt()`.

- [ ] **Step 4: Run tests**

```bash
cd /Users/cadencedev/Developer/storyforge/.worktrees/clean-up-scene-metadata && ./tests/run-tests.sh tests/test-python.sh
```

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/enrich.py && git commit -m "Update enrich.py: drop scene-metadata.csv, use scenes.csv" && git push
```

---

### Task 3: Python — revision.py (metadata CSV helpers)

**Files:**
- Modify: `scripts/lib/python/storyforge/revision.py:64-86`

`revision.py` has its own `_find_metadata_csv()` function that checks for `scene-metadata.csv` with fallback to `scenes/metadata.csv`. Replace it.

- [ ] **Step 1: Replace `_find_metadata_csv` with `_find_scenes_csv`**

Replace the function at lines 78-86:

```python
def _find_scenes_csv(project_dir: str) -> str:
    """Locate the scenes CSV."""
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    if os.path.isfile(path):
        return path
    raise FileNotFoundError('scenes.csv not found in reference/')
```

- [ ] **Step 2: Update the section comment**

Line 64-66: change `# Metadata CSV helpers` to `# Scene CSV helpers`.

- [ ] **Step 3: Update all callers of `_find_metadata_csv`**

Search the file for all calls to `_find_metadata_csv` and replace with `_find_scenes_csv`. This includes `resolve_scope()` and any other functions that read scene metadata for revision scope resolution.

- [ ] **Step 4: Run tests**

```bash
cd /Users/cadencedev/Developer/storyforge/.worktrees/clean-up-scene-metadata && ./tests/run-tests.sh tests/test-python.sh
```

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/revision.py && git commit -m "Update revision.py: drop scene-metadata.csv, use scenes.csv" && git push
```

---

### Task 4: Python — scenes.py (header constants and row generation)

**Files:**
- Modify: `scripts/lib/python/storyforge/scenes.py:139-211`

`scenes.py` defines `_METADATA_HEADER` with the legacy column order, and `generate_metadata_rows()` produces rows in that order. Update to the `scenes.csv` column order. Also update `_INTENT_HEADER` to the new intent columns.

- [ ] **Step 1: Update `_METADATA_HEADER` to `_SCENES_HEADER`**

Replace line 139:

```python
_SCENES_HEADER = 'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words'
```

- [ ] **Step 2: Update `_INTENT_HEADER`**

Replace line 140:

```python
_INTENT_HEADER = 'id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads'
```

- [ ] **Step 3: Rename `generate_metadata_rows` to `generate_scenes_rows` and update column order**

Replace the function (lines 143-182):

```python
def generate_scenes_rows(scenes: list[dict],
                         part_num: int | None = None,
                         seq_start: int = 1) -> list[str]:
    """Generate pipe-delimited CSV rows for ``scenes.csv``.

    Each row uses the header order:
    ``id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words``

    The scene dicts must have at least ``title`` (str).  They may
    optionally include ``word_count`` (int) and ``slug`` (str).  If
    ``slug`` is absent it is derived from ``title`` via
    :func:`generate_slug`.

    Args:
        scenes: Scene dicts as returned by :func:`parse_scene_boundaries`
            (or any list of dicts with a ``title`` key).
        part_num: Optional part/act number to fill the ``part`` column.
        seq_start: Starting sequence number (default 1).

    Returns:
        List of pipe-delimited row strings (no header row included).
    """
    rows: list[str] = []
    used_slugs: set[str] = set()

    for i, scene in enumerate(scenes):
        title = scene.get('title', '')
        slug = scene.get('slug', '') or generate_slug(title)
        if not slug:
            slug = f'scene-{seq_start + i}'
        slug = unique_slug(slug, used_slugs)

        seq = seq_start + i
        part = str(part_num) if part_num is not None else ''
        word_count = str(scene.get('word_count', ''))

        # id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words
        row = f'{slug}|{seq}|{title}|{part}|||||||||{word_count}|'
        rows.append(row)

    return rows
```

- [ ] **Step 4: Update `generate_intent_rows` for new columns**

Replace the function (lines 185-211):

```python
def generate_intent_rows(scenes: list[dict]) -> list[str]:
    """Generate pipe-delimited CSV rows for ``scene-intent.csv``.

    Each row uses the header order:
    ``id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads``

    The scene dicts must have at least ``title`` (str) and optionally
    ``slug`` (str).

    Args:
        scenes: Scene dicts (must have ``title``; optionally ``slug``).

    Returns:
        List of pipe-delimited row strings (no header row included).
    """
    rows: list[str] = []
    used_slugs: set[str] = set()

    for scene in scenes:
        title = scene.get('title', '')
        slug = scene.get('slug', '') or generate_slug(title)
        if not slug:
            slug = f'scene-{len(rows) + 1}'
        slug = unique_slug(slug, used_slugs)

        # id|function|scene_type|emotional_arc|value_at_stake|value_shift|turning_point|threads|characters|on_stage|mice_threads
        row = f'{slug}||||||||||'
        rows.append(row)

    return rows
```

- [ ] **Step 5: Update `generate_rename_plan` if it references `scene-metadata.csv`**

Search `generate_rename_plan()` (around line 293) for any references to `scene-metadata.csv` and replace with `scenes.csv`.

- [ ] **Step 6: Update all callers of `generate_metadata_rows`**

Search the codebase for any calls to `generate_metadata_rows` (likely in `storyforge-scenes-setup`) and update them to call `generate_scenes_rows` instead. Also update references to `_METADATA_HEADER` → `_SCENES_HEADER`.

- [ ] **Step 7: Run tests**

```bash
cd /Users/cadencedev/Developer/storyforge/.worktrees/clean-up-scene-metadata && ./tests/run-tests.sh tests/test-python.sh
```

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/python/storyforge/scenes.py && git commit -m "Update scenes.py: rename to scenes.csv format, drop legacy headers" && git push
```

---

### Task 5: Python — visualize.py (simplify detection)

**Files:**
- Modify: `scripts/lib/python/storyforge/visualize.py:139-150`

`visualize.py` has a two-stage fallback resolution. Simplify to direct paths.

- [ ] **Step 1: Replace detection block**

Replace lines 139-150 with:

```python
    # Three-file model: scenes.csv + scene-intent.csv + scene-briefs.csv
    metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
```

- [ ] **Step 2: Remove `_resolve_csv` helper if no longer used**

Check if `_resolve_csv` is used elsewhere in the file. If this was its only caller, delete the function.

- [ ] **Step 3: Run tests**

```bash
cd /Users/cadencedev/Developer/storyforge/.worktrees/clean-up-scene-metadata && ./tests/run-tests.sh tests/test-python.sh
```

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/python/storyforge/visualize.py && git commit -m "Update visualize.py: drop legacy CSV detection, use scenes.csv" && git push
```

---

### Task 6: Shell scripts — replace scene-metadata.csv with scenes.csv

**Files:**
- Modify: `scripts/storyforge-write`
- Modify: `scripts/storyforge-evaluate`
- Modify: `scripts/storyforge-revise`
- Modify: `scripts/storyforge-enrich`
- Modify: `scripts/storyforge-visualize`
- Modify: `scripts/storyforge-timeline`
- Modify: `scripts/storyforge-scenes-setup`
- Modify: `scripts/storyforge-cleanup`
- Modify: `scripts/storyforge-score`

Every shell script follows the same pattern: a `METADATA_CSV` variable set to `scene-metadata.csv` with fallback to `scenes/metadata.csv`. Replace each with a direct path to `scenes.csv` and remove all fallback logic.

- [ ] **Step 1: storyforge-write**

Line 237: Replace `METADATA_CSV="${PROJECT_DIR}/reference/scene-metadata.csv"` with `METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"`

Line 239: Delete the fallback line `[[ ! -f "$METADATA_CSV" ]] && METADATA_CSV="${SCENES_DIR}/metadata.csv"`

- [ ] **Step 2: storyforge-evaluate**

Lines 328-329: Replace with `METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"` and delete the fallback.

Lines 859-861: Same replacement — `METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"` and delete fallback.

- [ ] **Step 3: storyforge-revise**

Line 231: Replace `local meta_csv="${project_dir}/reference/scene-metadata.csv"` with `local meta_csv="${project_dir}/reference/scenes.csv"`

Line 273: Update comment from `# Append to scene-metadata.csv` to `# Append to scenes.csv`

Lines 644-645: Replace with `METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"` and delete fallback.

Lines 1075-1076: Same replacement and delete fallback.

- [ ] **Step 4: storyforge-enrich**

Lines 198-202: Replace entire block with:
```bash
METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"
INTENT_CSV="${PROJECT_DIR}/reference/scene-intent.csv"
```

Line 457: Replace `git add "reference/scene-metadata.csv"` with `git add "reference/scenes.csv"`

Line 1111: Replace `METADATA_CSV="${PROJECT_DIR}/reference/scene-metadata.csv"` with `METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"`

Lines 1126-1127: Replace `git add "reference/scene-metadata.csv"` with `git add "reference/scenes.csv"`

- [ ] **Step 5: storyforge-visualize**

Lines 59-62: Replace entire block with:
```bash
METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"
INTENT_CSV="${PROJECT_DIR}/reference/scene-intent.csv"
```

Line 71: Update error message from `reference/scene-metadata.csv` to `reference/scenes.csv`

- [ ] **Step 6: storyforge-timeline**

Lines 173-174: Replace with:
```bash
METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"
INTENT_CSV="${PROJECT_DIR}/reference/scene-intent.csv"
```

Line 182: Update error message from `reference/scene-metadata.csv` to `reference/scenes.csv`

Line 881: Replace `git add "reference/scene-metadata.csv"` with `git add "reference/scenes.csv"`

- [ ] **Step 7: storyforge-scenes-setup**

Lines 131-132: Replace with:
```bash
METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"
INTENT_CSV="${PROJECT_DIR}/reference/scene-intent.csv"
```

Lines 143-148: Delete the migration block that moves `scenes/metadata.csv` → `reference/scene-metadata.csv`.

Lines 231-236: Update `ensure_metadata_csv()` to create `scenes.csv` with the new header:
```bash
ensure_metadata_csv() {
    if [[ ! -f "$METADATA_CSV" ]]; then
        echo "id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words" > "$METADATA_CSV"
        log "Created reference/scenes.csv"
    fi
}
```

All `git add reference/scene-metadata.csv` lines (1141, 1213, 1258): Replace with `git add reference/scenes.csv`

- [ ] **Step 8: storyforge-cleanup**

Line 378: Replace `local meta_csv="${project_dir}/reference/scene-metadata.csv"` with `local meta_csv="${project_dir}/reference/scenes.csv"`

- [ ] **Step 9: storyforge-score — remove legacy fallback from detection**

Lines 177-190: Replace the entire if/else block with direct assignment:
```bash
METADATA_CSV="${PROJECT_DIR}/reference/scenes.csv"
INTENT_CSV="${PROJECT_DIR}/reference/scene-intent.csv"
BRIEFS_CSV="${PROJECT_DIR}/reference/scene-briefs.csv"
HAS_BRIEFS=false
[[ -f "$BRIEFS_CSV" ]] && HAS_BRIEFS=true
```

- [ ] **Step 10: Run full test suite**

```bash
cd /Users/cadencedev/Developer/storyforge/.worktrees/clean-up-scene-metadata && ./tests/run-tests.sh
```

- [ ] **Step 11: Commit**

```bash
git add scripts/storyforge-* && git commit -m "Update all scripts: drop scene-metadata.csv, use scenes.csv" && git push
```

---

### Task 7: Skills — update all SKILL.md references

**Files:**
- Modify: `skills/forge/SKILL.md`
- Modify: `skills/produce/SKILL.md`
- Modify: `skills/extract/SKILL.md`
- Modify: `skills/score/SKILL.md`
- Modify: `skills/press-kit/SKILL.md`
- Modify: `skills/init/SKILL.md`

- [ ] **Step 1: forge/SKILL.md**

Line 30: Replace `reference/scenes.csv` (elaboration pipeline) or `reference/scene-metadata.csv` (legacy)` with just `reference/scenes.csv`

Line 67: Replace `reference/scenes.csv` or `reference/scene-metadata.csv` exists` with `reference/scenes.csv` exists`

Line 198: Replace `Scene data (\`reference/scenes.csv\` or \`reference/scene-metadata.csv\`)` with `Scene data (\`reference/scenes.csv\`)`

- [ ] **Step 2: produce/SKILL.md**

Line 24: Replace `reference/scenes.csv (or legacy scene-metadata.csv)` with `reference/scenes.csv`

Line 243: Replace `scene IDs from scene-metadata.csv` with `scene IDs from scenes.csv`

- [ ] **Step 3: extract/SKILL.md**

Line 22: Replace `reference/scenes.csv` or `reference/scene-metadata.csv`` with `reference/scenes.csv`

- [ ] **Step 4: score/SKILL.md**

Line 37: Replace `reference/scene-metadata.csv` with `reference/scenes.csv`

- [ ] **Step 5: press-kit/SKILL.md**

Line 29: Replace `reference/scene-metadata.csv` with `reference/scenes.csv`

- [ ] **Step 6: init/SKILL.md**

Line 179: Replace `{project-dir}/reference/scene-metadata.csv` with `{project-dir}/reference/scenes.csv`. Update the header in the code block below it to use the new column order.

- [ ] **Step 7: Commit**

```bash
git add skills/*/SKILL.md && git commit -m "Update all skills: drop scene-metadata.csv references" && git push
```

---

### Task 8: Templates, schemas, and CLAUDE.md

**Files:**
- Modify: `templates/storyforge.yaml`
- Modify: `references/storyforge-yaml-schema.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: templates/storyforge.yaml**

Line 74: Replace `path: reference/scene-metadata.csv` with `path: reference/scenes.csv`

- [ ] **Step 2: references/storyforge-yaml-schema.md**

Line 76: Update the `scene_index` description to reference `scenes.csv` instead of `scene-metadata.csv`. Update the path value.

Line 98: Update the data-format note to reference `scenes.csv`.

Line 255: Replace `path: reference/scene-metadata.csv` with `path: reference/scenes.csv`

- [ ] **Step 3: CLAUDE.md — remove "Legacy" section from CSV Data Format**

In the "Key CSV Files" section, remove the "Legacy (existing projects)" block that documents `scene-metadata.csv`. The "Elaboration pipeline" section becomes the only model.

- [ ] **Step 4: Commit**

```bash
git add templates/storyforge.yaml references/storyforge-yaml-schema.md CLAUDE.md && git commit -m "Update templates and docs: drop scene-metadata.csv references" && git push
```

---

### Task 9: Test fixtures and test-csv.sh

**Files:**
- Modify: `tests/test-csv.sh:7`
- Rename: `tests/fixtures/cleanup-project/reference/scene-metadata.csv` → `tests/fixtures/cleanup-project/reference/scenes.csv`
- Delete: `tests/fixtures/test-project/reference/scene-metadata.csv` (test-project already has `scenes.csv`)
- Modify: `tests/fixtures/cleanup-project/reference/scenes.csv` (update header to new format)

- [ ] **Step 1: test-csv.sh — update fixture path**

Line 7: Replace `META_CSV="${FIXTURE_DIR}/reference/scene-metadata.csv"` with `META_CSV="${FIXTURE_DIR}/reference/scenes.csv"`

- [ ] **Step 2: Rename cleanup-project fixture**

```bash
cd /Users/cadencedev/Developer/storyforge/.worktrees/clean-up-scene-metadata
mv tests/fixtures/cleanup-project/reference/scene-metadata.csv tests/fixtures/cleanup-project/reference/scenes.csv
```

- [ ] **Step 3: Update cleanup-project scenes.csv header**

The file currently has the legacy header `id|seq|title|pov|location|part|type|timeline_day|time_of_day|status|word_count|target_words`. Update the first line to `id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words`.

Then update each data row to match the new column order (part moves before pov, add empty duration column).

- [ ] **Step 4: Update cleanup-project scene-intent.csv header if needed**

Check if the cleanup-project `scene-intent.csv` uses the legacy header. If so, update it to the new column order and add empty values for new columns.

- [ ] **Step 5: Delete legacy fixture from test-project**

```bash
rm tests/fixtures/test-project/reference/scene-metadata.csv
```

- [ ] **Step 6: Search for any remaining test files that reference scene-metadata**

```bash
grep -r "scene-metadata" tests/
```

Fix any remaining references.

- [ ] **Step 7: Run full test suite**

```bash
cd /Users/cadencedev/Developer/storyforge/.worktrees/clean-up-scene-metadata && ./tests/run-tests.sh
```

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "Update test fixtures: rename scene-metadata.csv to scenes.csv" && git push
```

---

### Task 10: Final validation and codebase sweep

- [ ] **Step 1: Sweep for any remaining references**

```bash
cd /Users/cadencedev/Developer/storyforge/.worktrees/clean-up-scene-metadata
grep -r "scene-metadata" --include="*.sh" --include="*.py" --include="*.md" --include="*.yaml" . | grep -v ".git/" | grep -v "docs/superpowers/plans/"
```

Any remaining hits must be fixed. Acceptable exceptions: this plan file, git history references in changelogs.

- [ ] **Step 2: Run full test suite one final time**

```bash
./tests/run-tests.sh
```

Expected: all 791 tests pass, 0 failures.

- [ ] **Step 3: Commit any remaining fixes**

If the sweep found anything, fix and commit.

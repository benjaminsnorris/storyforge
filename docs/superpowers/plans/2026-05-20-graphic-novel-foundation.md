# Graphic Novel Mode — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `project.medium = graphic-novel` support to Storyforge so a graphic-novel project can be initialized and taken through the briefs stage with full schema validation and hone diagnostics. Drafting and production are deferred to Plan 2.

**Architecture:** Add a `project.medium` field in `storyforge.yaml`. Extend the three scene CSVs with graphic-novel columns (target_pages, panel_count, page_count on scenes; page_layout, panel_breakdown, visual_keywords, page_turn_beats, caption_strategy on scene-briefs). Make shared commands (elaborate, validate, hone, cleanup) medium-aware by reading `project.medium` once and branching at the precise points where behavior diverges. Prose-craft scoring modules skip graphic-novel scenes. New `prompts_elaborate_gn.py` carries graphic-novel-specific elaboration prompts.

**Tech Stack:** Python 3, pytest, argparse, pipe-delimited CSV, YAML config, the existing `storyforge` package layout.

**Companion spec:** `docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md`

**Plan 2 (followup, not in this plan):** `cmd_write_gn.py`, `cmd_script_package.py`, `prompts_gn.py`, `script_format.py`, `script-package` skill, dispatcher routing for `write`/`assemble`, integration test for the full pipeline.

**Branch:** Work happens on `storyforge/graphic-novel-foundation-{timestamp}`. Every task ends with `git add -A && git commit -m "..." && git push`.

---

## File Structure

### Created files

| Path | Purpose |
|---|---|
| `scripts/lib/python/storyforge/prompts_elaborate_gn.py` | Graphic-novel elaboration-stage prompts (scene-map target_pages question, briefs prompt) |
| `tests/fixtures/test-project-gn/storyforge.yaml` | Test fixture project config (medium: graphic-novel) |
| `tests/fixtures/test-project-gn/reference/scenes.csv` | Fixture scene index with target_pages populated |
| `tests/fixtures/test-project-gn/reference/scene-intent.csv` | Fixture scene intents |
| `tests/fixtures/test-project-gn/reference/scene-briefs.csv` | Fixture briefs with graphic-novel columns populated |
| `tests/fixtures/test-project-gn/reference/voice-profile.csv` | Fixture voice profile with caption_voice/lettering_style |
| `tests/fixtures/test-project-gn/reference/character-bible.md` | Fixture character bible with Visual sections |
| `tests/fixtures/test-project-gn/reference/world-bible.md` | Fixture world bible with visual notes |
| `tests/fixtures/test-project-gn/scenes/.gitkeep` | Empty scenes directory (drafting is Plan 2) |
| `tests/test_medium.py` | Tests for `get_medium()` helper and medium-aware command branches |
| `tests/test_schema_gn.py` | Tests for graphic-novel column schema validation |

### Modified files

| Path | Change |
|---|---|
| `scripts/lib/python/storyforge/common.py` | Add `get_medium(project_dir)` helper returning `'novel'` or `'graphic-novel'` |
| `scripts/lib/python/storyforge/schema.py` | Add column definitions for `target_pages`, `panel_count`, `page_count`, `page_layout`, `panel_breakdown`, `visual_keywords`, `page_turn_beats`, `caption_strategy`. Make `validate_schema` medium-aware (require `target_pages` for graphic-novel, `target_words` for novel) |
| `scripts/lib/python/storyforge/cmd_validate.py` | Pass `medium` into schema validation |
| `scripts/lib/python/storyforge/cmd_cleanup.py` | Medium-aware CSV schema checks |
| `scripts/lib/python/storyforge/cmd_hone.py` | Graphic-novel brief diagnostics (missing panel_breakdown, page_turn_beats that don't land on page-1 panels) |
| `scripts/lib/python/storyforge/cmd_elaborate.py` | Branch at scene-map (target_pages prompt), voice (caption_voice/lettering_style), briefs (use `prompts_elaborate_gn` for graphic-novel mode) |
| `scripts/lib/python/storyforge/repetition.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_passive.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_adverbs.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_weather.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_rhythm.py` | Skip graphic-novel scenes |
| `scripts/lib/python/storyforge/scoring_economy.py` | Skip graphic-novel scenes |
| `templates/storyforge.yaml` | Add `project.medium` field with comments |
| `templates/reference/scenes.csv` | Add `target_pages\|panel_count\|page_count` to header |
| `templates/reference/scene-briefs.csv` | Add `page_layout\|panel_breakdown\|visual_keywords\|page_turn_beats\|caption_strategy` to header |
| `skills/init/SKILL.md` | Add medium question, route to elaboration pipeline when graphic-novel |
| `skills/forge/SKILL.md` | Read `project.medium` and acknowledge mode in status output |
| `skills/elaborate/SKILL.md` | Medium-aware behavior at scene-map / voice / briefs stages |
| `skills/hone/SKILL.md` | Document graphic-novel brief diagnostics |
| `.claude-plugin/plugin.json` | Bump minor version (new feature) |
| `CLAUDE.md` | Add graphic-novel mode notes in command and skill tables |

---

## Phase 1 — Foundation: medium field, helper, templates

### Task 1: `get_medium()` helper

**Files:**
- Modify: `scripts/lib/python/storyforge/common.py`
- Create: `tests/test_medium.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_medium.py`:

```python
"""Tests for project.medium handling."""

import os
import shutil
from pathlib import Path

import pytest

from storyforge.common import get_medium


def test_get_medium_returns_novel_when_field_absent(project_dir):
    """A project without project.medium defaults to 'novel'."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    assert 'medium:' not in content
    assert get_medium(project_dir) == 'novel'


def test_get_medium_returns_graphic_novel_when_set(project_dir):
    """A project with project.medium: graphic-novel returns that value."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    # Insert under `project:` block
    content = content.replace(
        'project:\n',
        'project:\n  medium: graphic-novel\n',
        1,
    )
    with open(yaml_path, 'w') as f:
        f.write(content)
    assert get_medium(project_dir) == 'graphic-novel'


def test_get_medium_returns_novel_for_explicit_novel(project_dir):
    """A project with project.medium: novel returns 'novel'."""
    yaml_path = os.path.join(project_dir, 'storyforge.yaml')
    with open(yaml_path) as f:
        content = f.read()
    content = content.replace(
        'project:\n',
        'project:\n  medium: novel\n',
        1,
    )
    with open(yaml_path, 'w') as f:
        f.write(content)
    assert get_medium(project_dir) == 'novel'
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_medium.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_medium' from 'storyforge.common'`.

- [ ] **Step 3: Implement `get_medium()` in `common.py`**

Add at the end of `scripts/lib/python/storyforge/common.py`:

```python
def get_medium(project_dir):
    """Return the project's medium: 'novel' (default) or 'graphic-novel'.

    Reads `project.medium` from storyforge.yaml. Unknown values fall back
    to 'novel' with a logged warning rather than failing — old projects
    without the field stay valid.
    """
    value = read_yaml_field('project.medium', project_dir)
    if not value:
        return 'novel'
    value = value.strip().lower()
    if value in ('novel', 'graphic-novel'):
        return value
    log(f"Warning: project.medium='{value}' is not a recognized value; defaulting to 'novel'")
    return 'novel'
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_medium.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/common.py tests/test_medium.py
git commit -m "Add get_medium() helper for project.medium field"
git push
```

---

### Task 2: Update storyforge.yaml template

**Files:**
- Modify: `templates/storyforge.yaml`

- [ ] **Step 1: Add `medium` field with documentation**

Edit `templates/storyforge.yaml` under `project:`. Insert the `medium` field directly after `title:`:

```yaml
project:
  title: "PROJECT_TITLE"                # Working title of the novel
  # Delivery medium:
  #   novel          — prose manuscript (default; produces epub/PDF)
  #   graphic-novel  — panel script for an artist (produces script package)
  # Set at init; durable. Switching mediums means a new project.
  medium: novel
  genre: "PROJECT_GENRE"                # Primary genre ...
  ...
```

- [ ] **Step 2: Verify the template still loads**

Run from the project root:

```bash
python3 -c "from pathlib import Path; import yaml; yaml.safe_load(Path('templates/storyforge.yaml').read_text())"
```

Expected: no output, no exception.

- [ ] **Step 3: Commit**

```bash
git add templates/storyforge.yaml
git commit -m "Add project.medium field to storyforge.yaml template"
git push
```

---

### Task 3: Update CSV templates

**Files:**
- Modify: `templates/reference/scenes.csv`
- Modify: `templates/reference/scene-briefs.csv`

- [ ] **Step 1: Update scenes.csv header**

Replace the entire content of `templates/reference/scenes.csv` with the new header line:

```
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words|target_pages|panel_count|page_count
```

- [ ] **Step 2: Update scene-briefs.csv header**

Replace the entire content of `templates/reference/scene-briefs.csv` with:

```
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out|page_layout|panel_breakdown|visual_keywords|page_turn_beats|caption_strategy
```

- [ ] **Step 3: Verify pipe count consistency**

Run:

```bash
awk -F'|' '{print NF}' templates/reference/scenes.csv templates/reference/scene-briefs.csv
```

Expected output (one line per file): `16` (scenes.csv has 16 columns), `22` (scene-briefs.csv has 22 columns).

- [ ] **Step 4: Commit**

```bash
git add templates/reference/scenes.csv templates/reference/scene-briefs.csv
git commit -m "Add graphic-novel columns to scenes and scene-briefs CSV templates"
git push
```

---

## Phase 2 — Schema validation: medium-aware column rules

### Task 4: Add new column definitions to `schema.py`

**Files:**
- Modify: `scripts/lib/python/storyforge/schema.py`
- Create: `tests/test_schema_gn.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_schema_gn.py`:

```python
"""Tests for graphic-novel schema columns and medium-aware validation."""

import os
import pytest

from storyforge.schema import COLUMN_SCHEMA, validate_schema


GN_SCENES_COLUMNS = ('target_pages', 'panel_count', 'page_count')
GN_BRIEFS_COLUMNS = (
    'page_layout', 'panel_breakdown', 'visual_keywords',
    'page_turn_beats', 'caption_strategy',
)


@pytest.mark.parametrize('column', GN_SCENES_COLUMNS)
def test_gn_scenes_columns_defined(column):
    assert column in COLUMN_SCHEMA, f'{column} missing from COLUMN_SCHEMA'
    assert COLUMN_SCHEMA[column]['file'] == 'scenes.csv'


@pytest.mark.parametrize('column', GN_BRIEFS_COLUMNS)
def test_gn_briefs_columns_defined(column):
    assert column in COLUMN_SCHEMA, f'{column} missing from COLUMN_SCHEMA'
    assert COLUMN_SCHEMA[column]['file'] == 'scene-briefs.csv'


def test_target_pages_is_integer():
    assert COLUMN_SCHEMA['target_pages']['type'] == 'integer'


def test_panel_count_is_integer():
    assert COLUMN_SCHEMA['panel_count']['type'] == 'integer'


def test_page_count_is_integer():
    assert COLUMN_SCHEMA['page_count']['type'] == 'integer'


def test_gn_brief_text_columns_are_free_text():
    for col in GN_BRIEFS_COLUMNS:
        assert COLUMN_SCHEMA[col]['type'] == 'free_text', (
            f'{col} should be free_text in v1 (extensible later)'
        )
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_schema_gn.py -v`
Expected: FAIL — multiple assertion failures for missing columns.

- [ ] **Step 3: Add the column definitions in `schema.py`**

In `scripts/lib/python/storyforge/schema.py`, inside the `COLUMN_SCHEMA` dict, add these entries. Place the scenes.csv entries near the existing `target_words` definition; place the scene-briefs.csv entries near the existing `has_overflow` definition.

```python
    # scenes.csv — graphic-novel additions
    'target_pages': {
        'type': 'integer', 'file': 'scenes.csv', 'stage': 'scene-map',
        'description': 'Target page count (graphic-novel mode). Set at scene-map stage; analog of target_words.',
    },
    'panel_count': {
        'type': 'integer', 'file': 'scenes.csv', 'stage': 'drafting',
        'description': 'Panel count after drafting (graphic-novel mode). Populated by cmd_write_gn.',
    },
    'page_count': {
        'type': 'integer', 'file': 'scenes.csv', 'stage': 'drafting',
        'description': 'Page count after drafting (graphic-novel mode). Populated by cmd_write_gn.',
    },
```

```python
    # scene-briefs.csv — graphic-novel additions
    'page_layout': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'briefs',
        'description': 'High-level layout rhythm (e.g., "9-panel grid", "splash p3"). Graphic-novel only.',
    },
    'panel_breakdown': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'briefs',
        'description': 'Per-page panel structure (e.g., "p1:splash; p2:6-grid"). Graphic-novel only.',
    },
    'visual_keywords': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'briefs',
        'description': 'Visual beats that must appear, semicolon-separated. Graphic-novel only.',
    },
    'page_turn_beats': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'briefs',
        'description': 'Beats that must land on a page turn. Graphic-novel only.',
    },
    'caption_strategy': {
        'type': 'free_text', 'file': 'scene-briefs.csv', 'stage': 'briefs',
        'description': 'Narration style ("minimal", "journal voiceover", "none"). Graphic-novel only.',
    },
```

- [ ] **Step 4: Run to confirm passing**

Run: `pytest tests/test_schema_gn.py -v`
Expected: all 13 parametrized tests pass.

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `pytest tests/ -x -q`
Expected: all passing. If any test fails because it counted columns or relied on the schema being fixed-size, fix it as part of this task before committing.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/schema.py tests/test_schema_gn.py
git commit -m "Add graphic-novel column definitions to schema.py"
git push
```

---

### Task 5: Medium-aware `validate_schema()`

**Files:**
- Modify: `scripts/lib/python/storyforge/schema.py`
- Modify: `tests/test_schema_gn.py`

The current `validate_schema(ref_dir, project_dir)` walks columns and checks each cell. In graphic-novel mode, certain rules invert: scenes must have `target_pages` (not `target_words`); briefs without `page_layout` or `panel_breakdown` are flagged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_schema_gn.py`:

```python
import shutil
from pathlib import Path


@pytest.fixture
def gn_project_dir(tmp_path, fixture_dir):
    """A novel fixture copied and flipped to graphic-novel mode.

    Used until the dedicated GN fixture lands in Task 6.
    """
    dest = tmp_path / 'gn-project'
    shutil.copytree(fixture_dir, dest)
    yaml_path = dest / 'storyforge.yaml'
    content = yaml_path.read_text()
    yaml_path.write_text(
        content.replace('project:\n', 'project:\n  medium: graphic-novel\n', 1)
    )
    return str(dest)


def test_validate_schema_gn_flags_missing_target_pages(gn_project_dir):
    """In graphic-novel mode, a scene with no target_pages but a target_words
    value should be flagged."""
    ref_dir = os.path.join(gn_project_dir, 'reference')
    result = validate_schema(ref_dir, gn_project_dir)
    # At least one scene should fail because target_pages is missing
    failing_columns = {f['column'] for f in result.get('failures', [])}
    assert 'target_pages' in failing_columns


def test_validate_schema_novel_does_not_require_target_pages(fixture_dir):
    """In novel mode, target_pages absence is fine — target_words is what matters."""
    ref_dir = os.path.join(fixture_dir, 'reference')
    result = validate_schema(ref_dir, fixture_dir)
    failing_columns = {f['column'] for f in result.get('failures', [])}
    assert 'target_pages' not in failing_columns
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_schema_gn.py::test_validate_schema_gn_flags_missing_target_pages -v`
Expected: FAIL — schema validation doesn't yet know about medium.

- [ ] **Step 3: Make `validate_schema` medium-aware**

In `scripts/lib/python/storyforge/schema.py`, locate `validate_schema(ref_dir, project_dir=None)`. Near the top, after the function reads the schema, add medium detection and conditional rules.

```python
def validate_schema(ref_dir, project_dir=None):
    # ... existing setup ...

    medium = 'novel'
    if project_dir is not None:
        from storyforge.common import get_medium
        medium = get_medium(project_dir)

    # ... existing per-cell validation loop ...

    # After the per-cell loop, add medium-aware required-field checks:
    if medium == 'graphic-novel':
        # Every non-cut/non-merged scene needs target_pages
        scenes_rows = _read_csv(os.path.join(ref_dir, 'scenes.csv'))
        for row in scenes_rows:
            status = (row.get('status') or '').strip()
            if status in ('cut', 'merged'):
                continue
            if not (row.get('target_pages') or '').strip():
                failures.append({
                    'file': 'scenes.csv',
                    'row': row.get('id', ''),
                    'column': 'target_pages',
                    'value': '',
                    'reason': 'target_pages is required in graphic-novel mode',
                })
```

(The exact placement depends on the current loop's variable names. Read the surrounding code and mirror the existing failure-record shape.)

- [ ] **Step 4: Confirm tests pass**

Run: `pytest tests/test_schema_gn.py -v`
Expected: all passing.

Run: `pytest tests/ -x -q`
Expected: all passing (no novel-mode regression).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/schema.py tests/test_schema_gn.py
git commit -m "Make schema validation medium-aware (require target_pages in GN mode)"
git push
```

---

## Phase 3 — Test fixture for graphic-novel mode

### Task 6: Create `tests/fixtures/test-project-gn/`

**Files:**
- Create: `tests/fixtures/test-project-gn/storyforge.yaml`
- Create: `tests/fixtures/test-project-gn/reference/scenes.csv`
- Create: `tests/fixtures/test-project-gn/reference/scene-intent.csv`
- Create: `tests/fixtures/test-project-gn/reference/scene-briefs.csv`
- Create: `tests/fixtures/test-project-gn/reference/voice-profile.csv`
- Create: `tests/fixtures/test-project-gn/reference/character-bible.md`
- Create: `tests/fixtures/test-project-gn/reference/world-bible.md`
- Create: `tests/fixtures/test-project-gn/scenes/.gitkeep`
- Modify: `tests/conftest.py`

This fixture is a small graphic-novel project carried through the briefs stage. 3 scenes, briefs populated with all graphic-novel columns. Used by every subsequent task.

- [ ] **Step 1: Create the directory tree**

```bash
mkdir -p tests/fixtures/test-project-gn/{reference,scenes,working}
touch tests/fixtures/test-project-gn/scenes/.gitkeep
```

- [ ] **Step 2: Write `storyforge.yaml`**

Write `tests/fixtures/test-project-gn/storyforge.yaml`:

```yaml
project:
  title: "The Cartographer's Silence — GN"
  medium: graphic-novel
  genre: "fantasy"
  target_words: 0
  logline: "A cartographer who maps lands he has never visited finds his pages begin filling themselves."
  coaching_level: full

artifacts:
  scene_index:
    exists: true
    path: reference/scenes.csv
    updated: 2026-05-20

phase: briefs
```

- [ ] **Step 3: Write `reference/scenes.csv`**

```
id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words|target_pages|panel_count|page_count
the-blank-page|1|The Blank Page|1|cartographer|study|1|night|short|introspection|briefed||||6||
shadows-arrive|2|Shadows Arrive|1|cartographer|study|1|night|short|action|briefed||||4||
the-first-mark|3|The First Mark|1|cartographer|study|2|dawn|short|revelation|briefed||||5||
```

- [ ] **Step 4: Write `reference/scene-intent.csv`**

```
id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads
the-blank-page|setup the cartographer's blocked craft|sequel|resigned to curious|creative will|+/+|action|cartographer|cartographer|+inquiry:the-empty-map
shadows-arrive|threat materialises in the workspace|action|curious to alarmed|safety|-/--|action|cartographer|cartographer|+character:cartographer-doubt
the-first-mark|map fills itself for the first time|action|alarmed to changed|knowledge|+/++|revelation|cartographer|cartographer|+inquiry:the-empty-map
```

- [ ] **Step 5: Write `reference/scene-briefs.csv`**

```
id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out|page_layout|panel_breakdown|visual_keywords|page_turn_beats|caption_strategy
the-blank-page|fill the blank page|inability to begin|no-and|recognise the pattern|set the pen down|knows he is blocked|accepts the night is lost|stare at parchment;dip pen;lay it down|It always begins this way|resigned, watchful|empty map; lamp|the work is dead but he is not|—|false|fatigued|fatigued|splash p1, 4-panel grid p2|p1:splash; p2:4-grid; p3:splash + 3|blank parchment close;trembling hand;lamp glow on paper|p2 to p3 splash reveal|journal voiceover
shadows-arrive|finish for the night|something moves in the room|no|see what it is|stand to face it|night routine|shadow has a shape|shut book;turn head;rise|Who's there?|alarmed, alert|shadow; door; lamp|the room knows him|continuity:lamp-positioned-by-window|false|fatigued|alert|6-panel grid throughout|p1:6-grid; p2:6-grid|shadow under door;wind moving curtains;lamp guttering|p1 to p2 reveal|none
the-first-mark|find the page changed|the page has filled itself|yes-but|believe what he sees|reach for the pen|map is empty|map shows a country he has never seen|return to desk;see filled page;reach|This place — I never drew it|stunned, drawn|filled map; pen; dawn light|the map maps him|continuity:lamp-position|false|alert|stunned|splash double-spread p2-3|p1:3-tier; p2-3:double-spread|filled-map close;cartographer's eyes wide;dawn through window|p1 to p2-3 double-spread reveal|none
```

- [ ] **Step 6: Write `reference/voice-profile.csv`**

```
character|register|preferred_words|banned_words|metaphor_families|rhythm|dialogue_style|caption_voice|lettering_style
_project|literate-spare|map;ink;line;edge;blank|stuff;thing;basically|cartography;cosmology;weather|short-sentence-mosaic|terse-formal|journal-voiceover|loose-natural
cartographer|formal|parchment;quill;degrees|stuff;basically|cartography|measured|terse|—|—
```

- [ ] **Step 7: Write `reference/character-bible.md`**

```markdown
# Characters

## Cartographer

**Role:** Protagonist
**Age look:** Mid-fifties, weather-worn

### Visual

- Silhouette: tall, narrow, stoop-shouldered from years over a drafting table
- Signature elements: round wire spectacles, ink-stained right hand, leather apron
- Costume continuity: same dark waistcoat across all scenes in part 1
- Distinctive: a small burn-scar on the left thumb from an early apprenticeship
```

- [ ] **Step 8: Write `reference/world-bible.md`**

```markdown
# World

## The Study

The cartographer's study is the entire first act's stage.

### Visual

- Visual keywords: tall bookshelves; lamplight; window facing east; large drafting table; rolled parchment in cubbies
- Mood: amber, warm, dust in beams of light
- Continuity: the lamp is always positioned on the right edge of the drafting table; the window is always to the east
```

- [ ] **Step 9: Add fixture pointer in `conftest.py`**

Edit `tests/conftest.py`. After the existing `FIXTURE_DIR = TESTS_DIR / 'fixtures' / 'test-project'` line, add:

```python
FIXTURE_DIR_GN = TESTS_DIR / 'fixtures' / 'test-project-gn'


@pytest.fixture
def fixture_dir_gn():
    """Path to the graphic-novel test-project fixture."""
    return str(FIXTURE_DIR_GN)


@pytest.fixture
def project_dir_gn(tmp_path):
    """A fresh copy of the graphic-novel fixture in a temp directory."""
    dest = tmp_path / 'test-project-gn'
    shutil.copytree(FIXTURE_DIR_GN, dest)
    return str(dest)
```

- [ ] **Step 10: Smoke-test the fixture**

Add to `tests/test_medium.py`:

```python
def test_gn_fixture_loads(fixture_dir_gn):
    """The graphic-novel fixture exists and is graphic-novel mode."""
    assert os.path.isfile(os.path.join(fixture_dir_gn, 'storyforge.yaml'))
    assert get_medium(fixture_dir_gn) == 'graphic-novel'


def test_gn_fixture_schema_passes(fixture_dir_gn):
    """The graphic-novel fixture passes schema validation."""
    from storyforge.schema import validate_schema
    ref_dir = os.path.join(fixture_dir_gn, 'reference')
    result = validate_schema(ref_dir, fixture_dir_gn)
    assert result['failed'] == 0, f"Fixture has schema failures: {result.get('failures')}"
```

- [ ] **Step 11: Run all tests**

Run: `pytest tests/test_medium.py tests/test_schema_gn.py -v`
Expected: all passing. If the schema validation flags the fixture, fix the fixture (probably by populating any missing required field).

- [ ] **Step 12: Commit**

```bash
git add tests/fixtures/test-project-gn/ tests/conftest.py tests/test_medium.py
git commit -m "Add graphic-novel test fixture"
git push
```

---

## Phase 4 — Wire validation, cleanup, hone

### Task 7: `cmd_validate` already wires schema medium-awareness (verify)

The schema layer is medium-aware via Task 5. `cmd_validate.py` already passes `project_dir` to `validate_schema`. Verify with an end-to-end test.

**Files:**
- Modify: `tests/test_medium.py`

- [ ] **Step 1: Add an end-to-end test**

Append to `tests/test_medium.py`:

```python
def test_cmd_validate_passes_on_gn_fixture(project_dir_gn, monkeypatch):
    """Running `storyforge validate` on the GN fixture exits 0."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import cmd_validate
    with pytest.raises(SystemExit) as exc_info:
        cmd_validate.main(['--quiet'])
    assert exc_info.value.code == 0
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_medium.py::test_cmd_validate_passes_on_gn_fixture -v`
Expected: PASS.

If it fails because some other validation layer (e.g., structural) chokes on graphic-novel data, fix that layer in this same task — read the failure, find the root cause in the structural code path, and either skip the check in graphic-novel mode or make it medium-aware. Do not catch the exception; fix the layer.

- [ ] **Step 3: Commit**

```bash
git add tests/test_medium.py scripts/lib/python/storyforge/
git commit -m "Verify cmd_validate works in graphic-novel mode"
git push
```

---

### Task 8: Make `cmd_cleanup --csv` medium-aware

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_cleanup.py`
- Modify: `tests/test_medium.py`

`cmd_cleanup` runs schema validation as part of its CSV integrity report. It must invoke the medium-aware schema check.

- [ ] **Step 1: Inspect the current cleanup CSV check**

Read `scripts/lib/python/storyforge/cmd_cleanup.py`. Find the function that runs schema validation (look for a call to `validate_schema`). Note whether it currently passes `project_dir` (it should, but verify).

- [ ] **Step 2: Write a failing test**

Append to `tests/test_medium.py`:

```python
def test_cmd_cleanup_csv_passes_on_gn_fixture(project_dir_gn, monkeypatch, capsys):
    """`storyforge cleanup --csv` exits 0 on the GN fixture."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import cmd_cleanup
    with pytest.raises(SystemExit) as exc_info:
        cmd_cleanup.main(['--csv'])
    # Acceptable: clean exit (0) — or 1 if the CSV report flags non-schema issues
    # we don't care about. Assert that no failures mention target_pages or any
    # GN-only column with a 'missing' reason.
    captured = capsys.readouterr()
    assert 'target_pages' not in captured.err or 'missing' not in captured.err
```

- [ ] **Step 3: Run**

Run: `pytest tests/test_medium.py::test_cmd_cleanup_csv_passes_on_gn_fixture -v`
Expected: behavior depends on current code. Fix any failure by ensuring `cmd_cleanup`'s schema check passes `project_dir` through to `validate_schema`.

- [ ] **Step 4: Make any required fix in `cmd_cleanup.py`**

If the call site doesn't pass `project_dir`, change it. Example fix (exact location varies):

```python
# Before:
result = validate_schema(ref_dir)
# After:
result = validate_schema(ref_dir, project_dir)
```

- [ ] **Step 5: Verify**

Run: `pytest tests/test_medium.py -v`
Expected: all passing.

Run: `pytest tests/ -x -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_cleanup.py tests/test_medium.py
git commit -m "Wire cmd_cleanup CSV report to medium-aware schema validation"
git push
```

---

### Task 9: Add graphic-novel brief diagnostics to `cmd_hone`

**Files:**
- Modify: `scripts/lib/python/storyforge/hone.py`
- Modify: `tests/test_medium.py`

`hone` runs brief-quality diagnostics. Add graphic-novel-specific checks: every brief must have `panel_breakdown` populated; `page_turn_beats` must reference page-1 panels of non-first pages in the breakdown.

- [ ] **Step 1: Inspect `hone.py`**

Read `scripts/lib/python/storyforge/hone.py`. Find the brief-quality diagnostic functions (look for ones that examine `goal`, `conflict`, `outcome` and produce findings). Identify the dispatch pattern.

- [ ] **Step 2: Write failing tests**

Append to `tests/test_medium.py`:

```python
def test_hone_gn_flags_missing_panel_breakdown(project_dir_gn, monkeypatch):
    """A graphic-novel brief missing panel_breakdown is flagged by hone."""
    # Blank out panel_breakdown for one scene
    from storyforge.csv_cli import update_field
    briefs = os.path.join(project_dir_gn, 'reference', 'scene-briefs.csv')
    update_field(briefs, 'the-blank-page', 'panel_breakdown', '')

    from storyforge.hone import diagnose_briefs
    findings = diagnose_briefs(project_dir_gn)
    flagged = [f for f in findings if f.get('scene_id') == 'the-blank-page'
               and f.get('field') == 'panel_breakdown']
    assert flagged, 'expected a panel_breakdown finding for the-blank-page'


def test_hone_novel_does_not_flag_panel_breakdown(project_dir, monkeypatch):
    """Novel-mode briefs are not checked for panel_breakdown."""
    from storyforge.hone import diagnose_briefs
    findings = diagnose_briefs(project_dir)
    panel_findings = [f for f in findings if f.get('field') == 'panel_breakdown']
    assert not panel_findings
```

(The actual function name `diagnose_briefs` may differ — substitute the real entrypoint after reading `hone.py`.)

- [ ] **Step 3: Run**

Run: `pytest tests/test_medium.py -v -k hone`
Expected: FAIL — no graphic-novel diagnostics yet.

- [ ] **Step 4: Add the diagnostics**

In `scripts/lib/python/storyforge/hone.py`, add a new function (placed near other brief diagnostics):

```python
def _diagnose_gn_briefs(project_dir, briefs_rows):
    """Return findings for graphic-novel-specific brief gaps.

    Checks:
      - panel_breakdown must be non-empty on every briefed scene
      - page_turn_beats entries should describe beats; we cannot verify against
        panel_breakdown structure without a parser, so we only check non-empty
        when the brief itself has a non-trivial layout (v1 heuristic)
    """
    findings = []
    for row in briefs_rows:
        scene_id = row.get('id', '')
        if not (row.get('panel_breakdown') or '').strip():
            findings.append({
                'scene_id': scene_id,
                'field': 'panel_breakdown',
                'severity': 'high',
                'message': 'panel_breakdown is empty — graphic-novel briefs must specify per-page panel structure',
                'fix_location': 'brief',
            })
        if not (row.get('page_layout') or '').strip():
            findings.append({
                'scene_id': scene_id,
                'field': 'page_layout',
                'severity': 'medium',
                'message': 'page_layout intent is empty — describe the rhythm of this scene',
                'fix_location': 'brief',
            })
    return findings
```

Then wire it into the main `diagnose_briefs` entrypoint. Locate the existing function, read its body, and at the start (after loading the briefs rows) add:

```python
from storyforge.common import get_medium
medium = get_medium(project_dir)
if medium == 'graphic-novel':
    findings.extend(_diagnose_gn_briefs(project_dir, briefs_rows))
```

- [ ] **Step 5: Verify**

Run: `pytest tests/test_medium.py -v -k hone`
Expected: PASS.

Run: `pytest tests/ -x -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/hone.py tests/test_medium.py
git commit -m "Add graphic-novel brief diagnostics to hone"
git push
```

---

## Phase 5 — Scoring modules skip graphic-novel scenes

### Task 10: Add medium guard to prose-craft scorers

**Files:**
- Modify: `scripts/lib/python/storyforge/repetition.py`
- Modify: `scripts/lib/python/storyforge/scoring_passive.py`
- Modify: `scripts/lib/python/storyforge/scoring_adverbs.py`
- Modify: `scripts/lib/python/storyforge/scoring_weather.py`
- Modify: `scripts/lib/python/storyforge/scoring_rhythm.py`
- Modify: `scripts/lib/python/storyforge/scoring_economy.py`
- Modify: `tests/test_medium.py`

The deterministic prose-craft scorers are not meaningful for panel scripts. In graphic-novel mode they return an empty score set rather than running.

- [ ] **Step 1: Write a failing test (one is enough — same pattern across modules)**

Append to `tests/test_medium.py`:

```python
@pytest.mark.parametrize('module_name', [
    'repetition',
    'scoring_passive',
    'scoring_adverbs',
    'scoring_weather',
    'scoring_rhythm',
    'scoring_economy',
])
def test_scorer_skips_in_gn_mode(project_dir_gn, monkeypatch, module_name):
    """Prose-craft scorers return empty results in graphic-novel mode."""
    import importlib
    monkeypatch.chdir(project_dir_gn)
    module = importlib.import_module(f'storyforge.{module_name}')
    # Each module exposes a top-level scoring entrypoint. Use `score_project`
    # if present, otherwise fall back to whichever public function the module exports.
    entrypoint = getattr(module, 'score_project', None)
    assert entrypoint is not None, f'{module_name} must expose a score_project entry'
    result = entrypoint(project_dir_gn)
    # In GN mode, the scorer should return an explicit "skipped" sentinel
    assert result.get('skipped') is True, (
        f'{module_name}.score_project should return {{"skipped": True}} in GN mode'
    )
    assert result.get('reason') == 'graphic-novel'
```

(If a module's public entrypoint is named differently, note that in the test by substituting the real name. The instruction at the call site reads as a contract — every scorer must expose `score_project(project_dir)` returning `{'skipped': True, 'reason': 'graphic-novel'}` when medium is graphic-novel.)

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_medium.py -v -k scorer_skips`
Expected: FAIL across all six parametrizations.

- [ ] **Step 3: Add the guard to each scorer**

For each of the six modules, locate the top-level `score_project(project_dir)` function (or rename/wrap the existing entrypoint if it has a different name). At the very top of the function, add:

```python
def score_project(project_dir):
    from storyforge.common import get_medium
    if get_medium(project_dir) == 'graphic-novel':
        return {'skipped': True, 'reason': 'graphic-novel'}
    # ... existing body ...
```

If a module doesn't currently expose a `score_project` function (it may be called from `cmd_score.py` via a different name), expose one as a thin wrapper that calls the existing implementation. Then the test contract becomes uniform.

- [ ] **Step 4: Verify**

Run: `pytest tests/test_medium.py -v -k scorer_skips`
Expected: PASS for all six.

Run: `pytest tests/ -x -q`
Expected: all passing. If any existing scorer test now fails because of the new function-shape requirement, fix it in this task.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/repetition.py \
        scripts/lib/python/storyforge/scoring_passive.py \
        scripts/lib/python/storyforge/scoring_adverbs.py \
        scripts/lib/python/storyforge/scoring_weather.py \
        scripts/lib/python/storyforge/scoring_rhythm.py \
        scripts/lib/python/storyforge/scoring_economy.py \
        tests/test_medium.py
git commit -m "Prose-craft scorers skip graphic-novel projects"
git push
```

---

## Phase 6 — Elaborate stage branches

### Task 11: Create `prompts_elaborate_gn.py`

**Files:**
- Create: `scripts/lib/python/storyforge/prompts_elaborate_gn.py`
- Modify: `tests/test_medium.py`

This module mirrors `prompts_elaborate.py` for graphic-novel mode. v1 provides two prompts: scene-map (target_pages) and briefs (graphic-novel columns).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_medium.py`:

```python
def test_prompts_elaborate_gn_imports():
    from storyforge import prompts_elaborate_gn
    assert hasattr(prompts_elaborate_gn, 'build_scene_map_prompt')
    assert hasattr(prompts_elaborate_gn, 'build_briefs_prompt')


def test_scene_map_prompt_mentions_pages():
    from storyforge.prompts_elaborate_gn import build_scene_map_prompt
    prompt = build_scene_map_prompt(
        project_dir='/tmp/fake',
        scenes_csv_content='id|seq|title\nscene-a|1|Test',
        architecture_doc='# Architecture\n\nThree acts.',
    )
    assert 'target_pages' in prompt
    assert 'target_words' not in prompt


def test_briefs_prompt_mentions_gn_columns():
    from storyforge.prompts_elaborate_gn import build_briefs_prompt
    prompt = build_briefs_prompt(
        project_dir='/tmp/fake',
        scene_id='scene-a',
        scene_row={'id': 'scene-a', 'title': 'Test', 'target_pages': '6'},
        intent_row={'function': 'setup'},
        existing_brief_row={},
    )
    for col in ('page_layout', 'panel_breakdown', 'visual_keywords',
                'page_turn_beats', 'caption_strategy'):
        assert col in prompt, f'prompt missing GN column instruction: {col}'
```

- [ ] **Step 2: Confirm failure**

Run: `pytest tests/test_medium.py -v -k prompts_elaborate_gn`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the module**

Create `scripts/lib/python/storyforge/prompts_elaborate_gn.py`:

```python
"""Graphic-novel elaboration-stage prompts.

Mirrors prompts_elaborate.py for graphic-novel-mode projects. v1 covers:
  - scene-map (asks target_pages instead of target_words)
  - briefs (populates the five graphic-novel-specific brief columns alongside
    the standard brief fields)

Voice-stage extensions (caption_voice, lettering_style) live in the existing
prompts_elaborate.py voice prompt as conditional sections — they're small
additions, not a full prompt rewrite.
"""

SCENE_MAP_GN_PREAMBLE = """\
You are mapping the scene index for a graphic novel project.

For each scene, you will set:
  - target_pages (NOT target_words) — how many pages this scene occupies
  - location, pov, timeline_day, time_of_day, type
  - characters, on_stage, mice_threads

Page counts are the unit of pacing in comics. A scene can be 1 page (a
quick beat), 3-4 pages (a typical sequence), or 6-8+ pages (a major set
piece). Most scenes are 2-4 pages.
"""

BRIEFS_GN_PREAMBLE = """\
You are writing scene briefs for a graphic novel.

Every standard brief column applies (goal, conflict, outcome, crisis,
decision, knowledge_in, knowledge_out, key_actions, key_dialogue,
emotions, motifs, subtext, continuity_deps, physical_state_in,
physical_state_out). All have the same meaning as in prose: they describe
the scene's narrative contract.

Additionally, populate these graphic-novel columns:

  - page_layout: high-level rhythm intent for the scene, e.g.,
    "9-panel grid", "splash p3, 6-panel grid after", "double-spread climax p4-5"

  - panel_breakdown: per-page panel structure, e.g.,
    "p1:splash; p2:6-grid; p3:splash+3"
    Use semicolon-separated entries, one per page. Page tokens: splash,
    N-grid (e.g. 6-grid, 9-grid), double-spread, tier, irregular.

  - visual_keywords: visual beats that must appear in the panel art,
    semicolon-separated, e.g., "blank parchment close; trembling hand;
    shadow under door". These are story beats the artist must include.

  - page_turn_beats: which beats must land on a page turn (recto-to-verso
    reveal). Semicolon-separated descriptions, each anchored to a panel
    in panel_breakdown. Used by the script-validation pass.

  - caption_strategy: narration style for this scene. Values:
    "minimal", "journal voiceover", "omniscient narration", "none",
    or a custom short phrase.
"""


def build_scene_map_prompt(project_dir, scenes_csv_content, architecture_doc):
    """Build the scene-map elaboration prompt for graphic-novel mode."""
    return f"""{SCENE_MAP_GN_PREAMBLE}

# Story architecture

{architecture_doc}

# Current scene index

```
{scenes_csv_content}
```

Return the updated scene index as a pipe-delimited CSV with the same columns,
populating target_pages for each scene.
"""


def build_briefs_prompt(project_dir, scene_id, scene_row, intent_row, existing_brief_row):
    """Build the brief-stage elaboration prompt for one scene (graphic-novel mode)."""
    scene_summary = (
        f"id: {scene_row.get('id', '')}\n"
        f"title: {scene_row.get('title', '')}\n"
        f"target_pages: {scene_row.get('target_pages', '')}\n"
        f"type: {scene_row.get('type', '')}\n"
        f"pov: {scene_row.get('pov', '')}\n"
        f"location: {scene_row.get('location', '')}\n"
    )
    intent_summary = "\n".join(f"{k}: {v}" for k, v in intent_row.items())
    existing = "\n".join(f"{k}: {v}" for k, v in existing_brief_row.items() if v)

    return f"""{BRIEFS_GN_PREAMBLE}

# Scene to brief

{scene_summary}

# Scene intent

{intent_summary}

# Existing brief (if any)

{existing or '(none)'}

Return the brief as a single pipe-delimited row matching the scene-briefs.csv
header. Populate every column you can; leave only truly unknown fields blank.
"""
```

- [ ] **Step 4: Verify**

Run: `pytest tests/test_medium.py -v -k prompts_elaborate_gn`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/prompts_elaborate_gn.py tests/test_medium.py
git commit -m "Add prompts_elaborate_gn for graphic-novel scene-map and briefs"
git push
```

---

### Task 12: Wire `cmd_elaborate` to use graphic-novel prompts

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_elaborate.py`
- Modify: `tests/test_medium.py`

`cmd_elaborate` has stage handlers for spine / architecture / scene-map / voice / briefs. In graphic-novel mode the scene-map and briefs stages call into `prompts_elaborate_gn` instead of `prompts_elaborate`.

- [ ] **Step 1: Inspect `cmd_elaborate.py`**

Read `scripts/lib/python/storyforge/cmd_elaborate.py`. Find the dispatch from `--stage` to handler functions. Note how each handler calls the corresponding prompt builder in `prompts_elaborate`.

- [ ] **Step 2: Write a failing test**

Append to `tests/test_medium.py`:

```python
def test_elaborate_scene_map_uses_gn_prompts(project_dir_gn, monkeypatch):
    """In graphic-novel mode, the scene-map stage calls build_scene_map_prompt from
    prompts_elaborate_gn, not prompts_elaborate."""
    called = {'gn': False, 'novel': False}

    def fake_gn_prompt(*args, **kwargs):
        called['gn'] = True
        return 'fake-gn-prompt'

    def fake_novel_prompt(*args, **kwargs):
        called['novel'] = True
        return 'fake-novel-prompt'

    from storyforge import prompts_elaborate_gn, prompts_elaborate
    monkeypatch.setattr(prompts_elaborate_gn, 'build_scene_map_prompt', fake_gn_prompt)
    monkeypatch.setattr(prompts_elaborate, 'build_scene_map_prompt', fake_novel_prompt, raising=False)

    # Stub API to prevent real calls
    from storyforge import api
    monkeypatch.setattr(api, 'invoke_api', lambda *a, **kw: 'id|seq|title\nscene-a|1|Test')

    monkeypatch.chdir(project_dir_gn)
    from storyforge import cmd_elaborate
    try:
        cmd_elaborate.main(['--stage', 'scene-map', '--dry-run'])
    except SystemExit:
        pass

    assert called['gn'], 'expected graphic-novel scene-map prompt to be called'
    assert not called['novel'], 'expected novel scene-map prompt NOT to be called'
```

- [ ] **Step 3: Confirm failure**

Run: `pytest tests/test_medium.py -v -k elaborate_scene_map_uses_gn`
Expected: FAIL.

- [ ] **Step 4: Branch the handlers in `cmd_elaborate.py`**

Read the scene-map handler. Wherever it imports/calls `prompts_elaborate.build_scene_map_prompt`, replace with a medium-aware lookup. Example pattern (substitute the real handler shape):

```python
from storyforge.common import get_medium

def _scene_map_stage(project_dir, args):
    medium = get_medium(project_dir)
    if medium == 'graphic-novel':
        from storyforge.prompts_elaborate_gn import build_scene_map_prompt
    else:
        from storyforge.prompts_elaborate import build_scene_map_prompt
    # ... existing prompt-building and API-call logic ...
```

Apply the same pattern to the briefs handler — branch on medium, import from `prompts_elaborate_gn` for graphic-novel.

For voice stage, add a small conditional in the existing voice prompt builder: if medium is graphic-novel, append a paragraph asking the model to set `caption_voice` and `lettering_style` on the `_project` row of `voice-profile.csv`. No new prompt module needed for voice.

- [ ] **Step 5: Verify**

Run: `pytest tests/test_medium.py -v`
Expected: all passing.

Run: `pytest tests/ -x -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_elaborate.py tests/test_medium.py
git commit -m "Branch cmd_elaborate scene-map and briefs by medium"
git push
```

---

## Phase 7 — Skill updates

These updates do not change behavior of any cmd module. They update guidance documents so the interactive Claude experience knows about graphic-novel mode.

### Task 13: Update `init` skill

**Files:**
- Modify: `skills/init/SKILL.md`

- [ ] **Step 1: Add the medium question**

In `skills/init/SKILL.md`, find Step 1's question list (between "Title" and "Pipeline approach"). Insert a new question after "Coaching level" and before "Pipeline approach":

```markdown
7. **Medium** — "What are you writing?
   - **Novel** (default) — prose manuscript. Storyforge produces epub and PDF output.
   - **Graphic novel** — panel script for an artist. Storyforge produces an artist-ready script package (markdown + PDF), character/setting visual references, and a chapter map. Drafting outputs page-by-page panel breakdowns instead of prose.

   This choice is durable — a graphic-novel and a prose adaptation are separate projects."
```

Re-number the subsequent "Pipeline approach" question to 8.

- [ ] **Step 2: Add graphic-novel routing notes**

After the medium question section, add:

```markdown
If the author chose **graphic novel**, the elaboration pipeline is required — present only the elaboration option in the next question and explain that the structural rigor matters more when art is the delivery vehicle.
```

- [ ] **Step 3: Update Step 3 (storyforge.yaml generation)**

Add a note that `project.medium` must be written into the yaml. Insert in the bulleted list of fields:

```markdown
- Medium (novel or graphic-novel)
```

- [ ] **Step 4: Verify the skill file is readable markdown**

```bash
head -30 skills/init/SKILL.md
```

Expected: valid YAML frontmatter followed by markdown.

- [ ] **Step 5: Commit**

```bash
git add skills/init/SKILL.md
git commit -m "Add medium question to init skill"
git push
```

---

### Task 14: Update `forge` skill

**Files:**
- Modify: `skills/forge/SKILL.md`

- [ ] **Step 1: Add medium-awareness note**

In `skills/forge/SKILL.md`, find the "Read Project State" section. Add a bullet directing the skill to read `project.medium` and reflect it in any status output. Example addition:

```markdown
- **Medium**: Read `project.medium` from storyforge.yaml. If `graphic-novel`, prefix any status summary with "Graphic novel project" and recommend graphic-novel-mode actions (e.g., elaborate stages, hone, validate — drafting and production are Plan 2).
```

- [ ] **Step 2: Add a known-limits note**

Add a section near the end (or in the routing section, wherever fits):

```markdown
## Graphic-novel mode in v1

The following commands and skills are NOT yet supported in graphic-novel mode:
`write`, `evaluate`, `score`, `revise`, `assemble`, `publish`, `annotations`, `extract`.

The following ARE supported: `elaborate` (spine, architecture, scene-map, voice, briefs), `hone`, `validate`, `cleanup`.

If the author asks for an unsupported action, explain the limit and offer to help with what is supported.
```

- [ ] **Step 3: Commit**

```bash
git add skills/forge/SKILL.md
git commit -m "Make forge skill medium-aware"
git push
```

---

### Task 15: Update `elaborate` skill

**Files:**
- Modify: `skills/elaborate/SKILL.md`

- [ ] **Step 1: Add medium-aware behavior notes**

In `skills/elaborate/SKILL.md`, find the section that documents each stage. After the existing description of each affected stage, add a paragraph for graphic-novel-mode behavior.

For **scene-map**:

```markdown
### Graphic-novel mode

In graphic-novel mode, the scene-map stage asks for `target_pages` per scene instead of `target_words`. Page-count guidance:
- Short scene (single beat): 1-2 pages
- Standard scene: 2-4 pages
- Set piece / chapter centerpiece: 5-8+ pages
- Full graphic-novel target: 100-200 pages typical for one volume
```

For **voice**:

```markdown
### Graphic-novel mode

Voice in graphic-novel mode still describes per-character speech register, but the `_project` row of `voice-profile.csv` carries two extra fields:
- `caption_voice` — narration style: `journal-voiceover`, `omniscient`, `first-person`, `none`
- `lettering_style` — visual treatment hint: `loose-natural`, `typeset`, `hand-lettered-feel`
```

For **briefs**:

```markdown
### Graphic-novel mode

Graphic-novel briefs populate five additional columns alongside the standard ones:
- `page_layout` — high-level rhythm intent (e.g., "9-panel grid", "splash p3")
- `panel_breakdown` — per-page structure (e.g., "p1:splash; p2:6-grid")
- `visual_keywords` — visual beats that must appear, semicolon-separated
- `page_turn_beats` — beats that must land on a page turn
- `caption_strategy` — narration style for this scene

All standard brief columns still apply with full meaning. `key_actions` reads as a panel-beat list; `key_dialogue` becomes the word-balloon contract; `continuity_deps` covers visual continuity too.
```

- [ ] **Step 2: Commit**

```bash
git add skills/elaborate/SKILL.md
git commit -m "Add graphic-novel notes to elaborate skill stages"
git push
```

---

### Task 16: Update `hone` skill

**Files:**
- Modify: `skills/hone/SKILL.md`

- [ ] **Step 1: Document graphic-novel diagnostics**

Add a section to `skills/hone/SKILL.md` after the existing diagnostic descriptions:

```markdown
## Graphic-novel diagnostics

When `project.medium = graphic-novel`, hone runs additional brief-quality checks:
- Every briefed scene must have a non-empty `panel_breakdown`
- Every briefed scene must have a non-empty `page_layout`
- Standard diagnostics (abstract briefs, overspecified beats, vague intent) still apply with the same meanings

Findings are reported alongside the standard diagnostic output.
```

- [ ] **Step 2: Commit**

```bash
git add skills/hone/SKILL.md
git commit -m "Document graphic-novel diagnostics in hone skill"
git push
```

---

## Phase 8 — Version bump and CLAUDE.md

### Task 17: Bump plugin version

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Read current version**

Run: `python3 -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])"`
Expected: a version string (e.g., `0.10.0`).

- [ ] **Step 2: Bump the minor version**

This is a new feature (graphic-novel mode foundation), so bump the minor version. If the current version is `0.10.0`, set it to `0.11.0`.

Edit `.claude-plugin/plugin.json`:

```json
{
  "version": "0.11.0",
  ...
}
```

- [ ] **Step 3: Verify the file still parses**

Run: `python3 -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])"`
Expected: `0.11.0` (or the appropriately-bumped value).

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to 0.11.0 for graphic-novel mode foundation"
git push
```

---

### Task 18: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add graphic-novel section**

In `CLAUDE.md`, add a new section after "Architecture Quick Reference" describing graphic-novel mode:

```markdown
## Graphic Novel Mode

Set `project.medium: graphic-novel` in storyforge.yaml at init time to switch a project into graphic-novel mode. Medium is durable; switching means a new project.

**Supported in current version (Plan 1):**
- `elaborate` (spine, architecture, scene-map, voice, briefs)
- `hone`, `validate`, `cleanup`
- Schema validation enforces graphic-novel column rules (target_pages required, panel_breakdown required at briefed status)

**Not yet supported (Plan 2):**
- `write`, `evaluate`, `score`, `revise`, `assemble`, `publish`, `annotations`, `extract`

**Schema additions:**
- `reference/scenes.csv` adds: `target_pages`, `panel_count`, `page_count`
- `reference/scene-briefs.csv` adds: `page_layout`, `panel_breakdown`, `visual_keywords`, `page_turn_beats`, `caption_strategy`
- `reference/voice-profile.csv` `_project` row adds: `caption_voice`, `lettering_style`

See the design spec: `docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md`.
```

- [ ] **Step 2: Update the Skills table**

Find the existing skills table and add a footnote/marker on `init`, `forge`, `elaborate`, `hone` indicating they are medium-aware. Example: add an asterisk and a note below the table:

```markdown
\* Medium-aware: behavior adapts to `project.medium` (novel | graphic-novel).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "Document graphic-novel mode in CLAUDE.md"
git push
```

---

## Phase 9 — Full sweep

### Task 19: Run the full test suite

**Files:** none

- [ ] **Step 1: Clean run**

Run: `pytest tests/ -v`
Expected: all tests pass. No skips, no xfails.

- [ ] **Step 2: If any test fails, fix the root cause**

Do not skip tests, do not mark xfail, do not catch the exception silently. Read the failure, find the cause in the production code, fix it, re-run.

- [ ] **Step 3: Verify a graphic-novel project goes through elaborate cleanly (manual)**

```bash
cd /tmp && rm -rf gn-smoke && mkdir gn-smoke && cd gn-smoke
# Copy the fixture as a starting point
cp -r /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project-gn/. .
# Verify schema passes
PYTHONPATH=/Users/cadencedev/Developer/storyforge/scripts/lib/python \
  python3 -m storyforge validate
echo "exit code: $?"
```

Expected: exit code 0, validation passes.

- [ ] **Step 4: Final commit (if any fixes were needed)**

If Step 2 required any fix, commit it:

```bash
git add -A
git commit -m "Fix regression caught by full-sweep test run"
git push
```

If no fixes were needed, this step is a no-op.

---

### Task 20: Open the pull request

**Files:** none

- [ ] **Step 1: Confirm branch is pushed**

Run: `git status` — should show clean working tree, branch pushed to origin.

- [ ] **Step 2: Create the draft PR**

```bash
gh pr create --draft --title "Add graphic-novel mode foundation (Plan 1)" --body "$(cat <<'EOF'
## Summary

Implements Plan 1 of graphic-novel-mode support. Adds `project.medium` field, extends scene CSVs with graphic-novel columns, makes shared planning commands (elaborate, validate, hone, cleanup) medium-aware, and skips prose-craft scoring for graphic-novel projects.

Plan 2 (drafting and artist handoff) is the natural followup.

## Spec
`docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md`

## Plan
`docs/superpowers/plans/2026-05-20-graphic-novel-foundation.md`

## Scope

**In:** schema, templates, validation, hone diagnostics, scoring guards, elaborate branches, prompts_elaborate_gn, fixture, skill updates, version bump.

**Out (Plan 2):** cmd_write_gn, cmd_script_package, prompts_gn, script_format, script-package skill, dispatcher routing for write/assemble.

## Test plan

- [x] `pytest tests/` — all passing
- [x] New `tests/test_medium.py` and `tests/test_schema_gn.py` cover the medium helper, schema branches, scorer guards, prompt module, and cmd_elaborate routing
- [x] New `tests/fixtures/test-project-gn/` exercises the full briefs-stage data shape
- [x] Manual smoke: `python3 -m storyforge validate` passes on the fixture

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Report the PR URL**

Print the PR URL returned by `gh pr create`.

---

## Self-Review Notes

After writing this plan, check:

**Spec coverage:** every spec section other than "drafting" and "production" (Plan 2 territory) has at least one task. The `extract` and `migrate` items are explicitly out of scope.

**Type/name consistency:** `get_medium()` returns `'novel'` or `'graphic-novel'`. `score_project()` is the contract scorer-modules expose. `_diagnose_gn_briefs()` is private; `diagnose_briefs()` is the public entrypoint hone exposes. `build_scene_map_prompt` and `build_briefs_prompt` are the entrypoints in `prompts_elaborate_gn.py`.

**Placeholder scan:** no TBD/TODO; every code change has the actual code; every test step has the actual assertion. The hone task notes that the public function name may need substitution after reading `hone.py` — that's a documented research-and-mirror step, not a placeholder.

**Sequencing dependencies:** Tasks 1-3 are independent. Task 4 depends on Task 1 (uses `get_medium`). Task 5 depends on Task 4. Task 6 (fixture) depends on Task 5 (schema validation must pass on it). Tasks 7-9 depend on Task 6. Task 10 depends on Task 1. Tasks 11-12 depend on Task 1. Tasks 13-16 are independent docs. Tasks 17-20 happen last.

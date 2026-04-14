# Annotation-Driven Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch reader annotations from the Bookshelf API, track their status in a per-project CSV, route them by color intent into the revision pipeline, and promote strong passages as exemplars.

**Architecture:** A new `annotations.py` module handles fetching, reconciliation, and routing logic. A new `cmd_annotations.py` command exposes it as `storyforge annotations`. The revision and hone commands check for unaddressed annotations on startup and incorporate them into plans. Exemplar promotion is coaching-level aware.

**Tech Stack:** Python stdlib only. Pipe-delimited CSV. Reuses `bookshelf.py` for API access.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `scripts/lib/python/storyforge/annotations.py` | Color mapping, fetch+reconcile logic, route by intent, exemplar promotion, revision findings generation |
| Create | `scripts/lib/python/storyforge/cmd_annotations.py` | CLI command module (parse_args, main, summary output) |
| Create | `tests/test_reader_annotations.py` | All annotation tests (reconciliation, routing, exemplar, revision integration) |
| Modify | `scripts/lib/python/storyforge/__main__.py` | Register `annotations` command |
| Modify | `scripts/lib/python/storyforge/bookshelf.py` | Add `COLOR_LABELS` mapping |
| Modify | `scripts/lib/python/storyforge/cmd_revise.py` | Check for annotations CSV, incorporate into plans, update status after passes |
| Modify | `scripts/lib/python/storyforge/cmd_hone.py` | Check for annotations CSV, convert to findings format |
| Modify | `CLAUDE.md` | Add command, module, CSV file |

---

## Task 1: Color Mapping and Annotation Processing Core

**Files:**
- Create: `scripts/lib/python/storyforge/annotations.py`
- Create: `tests/test_reader_annotations.py`
- Modify: `scripts/lib/python/storyforge/bookshelf.py`

- [ ] **Step 1: Write color mapping and routing tests**

```python
# tests/test_reader_annotations.py
import os


def test_color_labels():
    """COLOR_LABELS maps all five colors to labels."""
    from storyforge.annotations import COLOR_LABELS
    assert COLOR_LABELS['pink'] == 'Needs Revision'
    assert COLOR_LABELS['orange'] == 'Cut / Reconsider'
    assert COLOR_LABELS['blue'] == 'Research Needed'
    assert COLOR_LABELS['green'] == 'Strong Passage'
    assert COLOR_LABELS['yellow'] == 'Important'


def test_color_to_fix_location():
    """COLOR_TO_FIX_LOCATION maps colors to revision intent."""
    from storyforge.annotations import COLOR_TO_FIX_LOCATION
    assert COLOR_TO_FIX_LOCATION['pink'] == 'craft'
    assert COLOR_TO_FIX_LOCATION['orange'] == 'structural'
    assert COLOR_TO_FIX_LOCATION['blue'] == 'research'
    assert COLOR_TO_FIX_LOCATION['green'] == 'protection'
    assert COLOR_TO_FIX_LOCATION['yellow'] == 'craft'


def test_route_annotation_pink():
    """Pink annotation routes to craft with status new."""
    from storyforge.annotations import route_annotation
    ann = {'color': 'pink', 'note': 'pacing drags here'}
    status, fix_loc = route_annotation(ann)
    assert status == 'new'
    assert fix_loc == 'craft'


def test_route_annotation_green():
    """Green annotation routes to protection."""
    from storyforge.annotations import route_annotation
    ann = {'color': 'green', 'note': 'beautiful passage'}
    status, fix_loc = route_annotation(ann)
    assert status == 'new'
    assert fix_loc == 'protection'


def test_route_annotation_yellow_no_note():
    """Yellow annotation without note is skipped."""
    from storyforge.annotations import route_annotation
    ann = {'color': 'yellow', 'note': ''}
    status, fix_loc = route_annotation(ann)
    assert status == 'skipped'
    assert fix_loc == 'craft'


def test_route_annotation_yellow_with_note():
    """Yellow annotation with note routes to craft."""
    from storyforge.annotations import route_annotation
    ann = {'color': 'yellow', 'note': 'interesting choice here'}
    status, fix_loc = route_annotation(ann)
    assert status == 'new'
    assert fix_loc == 'craft'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reader_annotations.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Create annotations.py with color mapping and routing**

```python
# scripts/lib/python/storyforge/annotations.py
"""Reader annotation processing — fetch, reconcile, route, and exemplar promotion.

Fetches reader annotations from the Bookshelf API, maintains a stateful CSV
at working/annotations.csv, routes annotations by color intent into the
revision pipeline, and promotes strong passages as exemplars.
"""

import csv
import os
from datetime import datetime, timezone


# ============================================================================
# Color intent mapping
# ============================================================================

COLOR_LABELS = {
    'pink': 'Needs Revision',
    'orange': 'Cut / Reconsider',
    'blue': 'Research Needed',
    'green': 'Strong Passage',
    'yellow': 'Important',
}

COLOR_TO_FIX_LOCATION = {
    'pink': 'craft',
    'orange': 'structural',
    'blue': 'research',
    'green': 'protection',
    'yellow': 'craft',
}

ANNOTATIONS_HEADER = [
    'id', 'scene_id', 'chapter', 'color', 'color_label', 'text', 'note',
    'reader', 'created_at', 'status', 'fix_location', 'fetched_at',
]


def route_annotation(ann: dict) -> tuple[str, str]:
    """Determine status and fix_location for an annotation based on color and note.

    Args:
        ann: Annotation dict with at least 'color' and 'note' keys.

    Returns:
        Tuple of (status, fix_location).
    """
    color = ann.get('color', 'yellow')
    note = ann.get('note', '') or ''
    fix_location = COLOR_TO_FIX_LOCATION.get(color, 'craft')

    if color == 'yellow' and not note.strip():
        return 'skipped', fix_location

    return 'new', fix_location
```

- [ ] **Step 4: Add COLOR_LABELS to bookshelf.py for API fallback**

In `scripts/lib/python/storyforge/bookshelf.py`, add after the `_ENV_VARS` tuple (around line 33):

```python
# Color labels — used when API does not return color_label field.
# Will be removed when benjaminsnorris/bookshelf#5 lands.
COLOR_LABELS = {
    'pink': 'Needs Revision',
    'orange': 'Cut / Reconsider',
    'blue': 'Research Needed',
    'green': 'Strong Passage',
    'yellow': 'Important',
}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_reader_annotations.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/annotations.py scripts/lib/python/storyforge/bookshelf.py tests/test_reader_annotations.py
git commit -m "Add annotation color mapping and routing logic"
git push
```

---

## Task 2: Reconciliation Logic

**Files:**
- Modify: `scripts/lib/python/storyforge/annotations.py`
- Modify: `tests/test_reader_annotations.py`

- [ ] **Step 1: Write reconciliation tests**

Add to `tests/test_reader_annotations.py`:

```python
def test_load_annotations_csv_empty(tmp_path):
    """load_annotations_csv returns empty dict when file missing."""
    from storyforge.annotations import load_annotations_csv
    result = load_annotations_csv(str(tmp_path))
    assert result == {}


def test_load_annotations_csv_with_data(tmp_path):
    """load_annotations_csv returns dict keyed by annotation ID."""
    from storyforge.annotations import load_annotations_csv, ANNOTATIONS_HEADER
    csv_path = tmp_path / 'working' / 'annotations.csv'
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(
        '|'.join(ANNOTATIONS_HEADER) + '\n'
        'abc-123|arrival|1|pink|Needs Revision|the wagon lurched|pacing drags|Alice|2026-04-10|new|craft|2026-04-14\n'
    )
    result = load_annotations_csv(str(tmp_path))
    assert 'abc-123' in result
    assert result['abc-123']['scene_id'] == 'arrival'
    assert result['abc-123']['status'] == 'new'


def test_save_annotations_csv(tmp_path):
    """save_annotations_csv writes valid pipe-delimited CSV."""
    from storyforge.annotations import save_annotations_csv, load_annotations_csv, ANNOTATIONS_HEADER
    rows = {
        'abc-123': {
            'id': 'abc-123', 'scene_id': 'arrival', 'chapter': '1',
            'color': 'pink', 'color_label': 'Needs Revision',
            'text': 'the wagon lurched', 'note': 'pacing drags',
            'reader': 'Alice', 'created_at': '2026-04-10',
            'status': 'new', 'fix_location': 'craft',
            'fetched_at': '2026-04-14',
        }
    }
    save_annotations_csv(str(tmp_path), rows)
    # Read back and verify
    loaded = load_annotations_csv(str(tmp_path))
    assert 'abc-123' in loaded
    assert loaded['abc-123']['note'] == 'pacing drags'


def test_reconcile_new_annotation():
    """reconcile adds new annotations with status 'new'."""
    from storyforge.annotations import reconcile
    existing = {}
    api_annotations = [
        {
            'id': 'new-1',
            'scene': {'slug': 'arrival', 'scene_number': 1},
            'chapter': {'number': 1, 'title': 'Chapter 1'},
            'text': 'the dust rose',
            'note': 'too generic',
            'color': 'pink',
            'color_label': 'Needs Revision',
            'user': {'display_name': 'Alice'},
            'created_at': '2026-04-10T00:00:00Z',
        }
    ]
    result, summary = reconcile(existing, api_annotations)
    assert 'new-1' in result
    assert result['new-1']['status'] == 'new'
    assert result['new-1']['fix_location'] == 'craft'
    assert summary['new'] == 1


def test_reconcile_preserves_existing_status():
    """reconcile preserves status of already-tracked annotations."""
    from storyforge.annotations import reconcile
    existing = {
        'old-1': {
            'id': 'old-1', 'scene_id': 'arrival', 'chapter': '1',
            'color': 'pink', 'color_label': 'Needs Revision',
            'text': 'the dust rose', 'note': 'fixed this',
            'reader': 'Alice', 'created_at': '2026-04-10',
            'status': 'addressed', 'fix_location': 'craft',
            'fetched_at': '2026-04-13',
        }
    }
    api_annotations = [
        {
            'id': 'old-1',
            'scene': {'slug': 'arrival', 'scene_number': 1},
            'chapter': {'number': 1, 'title': 'Chapter 1'},
            'text': 'the dust rose',
            'note': 'fixed this',
            'color': 'pink',
            'color_label': 'Needs Revision',
            'user': {'display_name': 'Alice'},
            'created_at': '2026-04-10T00:00:00Z',
        }
    ]
    result, summary = reconcile(existing, api_annotations)
    assert result['old-1']['status'] == 'addressed'
    assert summary['new'] == 0
    assert summary['existing'] == 1


def test_reconcile_marks_removed():
    """reconcile marks annotations not in API as 'removed'."""
    from storyforge.annotations import reconcile
    existing = {
        'gone-1': {
            'id': 'gone-1', 'scene_id': 'arrival', 'chapter': '1',
            'color': 'pink', 'color_label': 'Needs Revision',
            'text': 'deleted text', 'note': '',
            'reader': 'Alice', 'created_at': '2026-04-10',
            'status': 'new', 'fix_location': 'craft',
            'fetched_at': '2026-04-13',
        }
    }
    api_annotations = []  # annotation was deleted
    result, summary = reconcile(existing, api_annotations)
    assert result['gone-1']['status'] == 'removed'
    assert summary['removed'] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reader_annotations.py::test_load_annotations_csv_empty -v`
Expected: FAIL — `load_annotations_csv` does not exist

- [ ] **Step 3: Implement reconciliation in annotations.py**

Add to `scripts/lib/python/storyforge/annotations.py`:

```python
# ============================================================================
# CSV persistence
# ============================================================================

def load_annotations_csv(project_dir: str) -> dict[str, dict[str, str]]:
    """Load working/annotations.csv into a dict keyed by annotation ID.

    Returns empty dict if file does not exist.
    """
    path = os.path.join(project_dir, 'working', 'annotations.csv')
    if not os.path.isfile(path):
        return {}

    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')

    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return {}

    header = lines[0].split('|')
    result = {}
    for line in lines[1:]:
        fields = line.split('|')
        row = {header[i]: (fields[i] if i < len(fields) else '')
               for i in range(len(header))}
        ann_id = row.get('id', '').strip()
        if ann_id:
            result[ann_id] = row
    return result


def save_annotations_csv(project_dir: str,
                         annotations: dict[str, dict[str, str]]) -> str:
    """Write annotations dict to working/annotations.csv.

    Returns the path written to.
    """
    work_dir = os.path.join(project_dir, 'working')
    os.makedirs(work_dir, exist_ok=True)
    path = os.path.join(work_dir, 'annotations.csv')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('|'.join(ANNOTATIONS_HEADER) + '\n')
        for ann in sorted(annotations.values(),
                          key=lambda a: a.get('created_at', '')):
            values = [ann.get(col, '') for col in ANNOTATIONS_HEADER]
            f.write('|'.join(values) + '\n')
    return path


# ============================================================================
# Reconciliation
# ============================================================================

def reconcile(existing: dict[str, dict[str, str]],
              api_annotations: list[dict]) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """Reconcile local annotations CSV with fresh API data.

    New annotations get status/fix_location from route_annotation().
    Existing annotations preserve their status.
    Annotations no longer in the API get status 'removed' (unless already
    addressed/skipped/protected/exemplar).

    Args:
        existing: Current annotations keyed by ID (from load_annotations_csv).
        api_annotations: List of annotation dicts from the Bookshelf API.

    Returns:
        Tuple of (updated annotations dict, summary counts dict).
    """
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    api_ids = set()
    result = dict(existing)
    summary = {'new': 0, 'existing': 0, 'removed': 0, 'total': 0}

    for ann in api_annotations:
        ann_id = ann.get('id', '')
        if not ann_id:
            continue
        api_ids.add(ann_id)

        scene = ann.get('scene') or {}
        chapter = ann.get('chapter') or {}
        user = ann.get('user') or {}
        color = ann.get('color', 'yellow')
        note = ann.get('note', '') or ''

        if ann_id in existing:
            # Preserve existing status — just update fetched_at
            result[ann_id]['fetched_at'] = now
            summary['existing'] += 1
        else:
            # New annotation
            status, fix_location = route_annotation(ann)
            result[ann_id] = {
                'id': ann_id,
                'scene_id': scene.get('slug', ''),
                'chapter': str(chapter.get('number', '')),
                'color': color,
                'color_label': ann.get('color_label', '') or COLOR_LABELS.get(color, color),
                'text': ann.get('text', ''),
                'note': note,
                'reader': user.get('display_name', 'Anonymous'),
                'created_at': ann.get('created_at', ''),
                'status': status,
                'fix_location': fix_location,
                'fetched_at': now,
            }
            summary['new'] += 1

    # Mark annotations not in API as removed (unless already in a terminal state)
    terminal_states = {'addressed', 'skipped', 'protected', 'exemplar'}
    for ann_id, ann in result.items():
        if ann_id not in api_ids and ann.get('status') not in terminal_states:
            if ann.get('status') != 'removed':
                ann['status'] = 'removed'
                summary['removed'] += 1

    summary['total'] = len(result)
    return result, summary
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_reader_annotations.py -v`
Expected: PASS (all 12 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/annotations.py tests/test_reader_annotations.py
git commit -m "Add annotation reconciliation logic (load, save, reconcile)"
git push
```

---

## Task 3: Revision Findings Generation

**Files:**
- Modify: `scripts/lib/python/storyforge/annotations.py`
- Modify: `tests/test_reader_annotations.py`

- [ ] **Step 1: Write findings generation tests**

Add to `tests/test_reader_annotations.py`:

```python
def test_generate_revision_findings():
    """generate_revision_findings aggregates annotations per scene."""
    from storyforge.annotations import generate_revision_findings
    annotations = {
        'a1': {'id': 'a1', 'scene_id': 'arrival', 'color': 'pink',
               'color_label': 'Needs Revision', 'text': 'the wagon lurched',
               'note': 'pacing drags', 'status': 'new', 'fix_location': 'craft'},
        'a2': {'id': 'a2', 'scene_id': 'arrival', 'color': 'pink',
               'color_label': 'Needs Revision', 'text': 'she counted again',
               'note': 'repetitive', 'status': 'new', 'fix_location': 'craft'},
        'a3': {'id': 'a3', 'scene_id': 'field-book', 'color': 'orange',
               'color_label': 'Cut / Reconsider', 'text': 'long description',
               'note': '', 'status': 'new', 'fix_location': 'structural'},
        'a4': {'id': 'a4', 'scene_id': 'arrival', 'color': 'green',
               'color_label': 'Strong Passage', 'text': 'beautiful line',
               'note': 'love this', 'status': 'new', 'fix_location': 'protection'},
        'a5': {'id': 'a5', 'scene_id': 'arrival', 'color': 'pink',
               'color_label': 'Needs Revision', 'text': 'old fix',
               'note': 'done', 'status': 'addressed', 'fix_location': 'craft'},
    }
    craft, structural, protection = generate_revision_findings(annotations)

    # Craft findings: 2 pink for 'arrival' (a5 is addressed, excluded)
    assert len(craft) == 1  # one finding per scene
    assert craft[0]['scene_id'] == 'arrival'
    assert 'pacing drags' in craft[0]['guidance']
    assert 'repetitive' in craft[0]['guidance']

    # Structural: 1 orange for 'field-book'
    assert len(structural) == 1
    assert structural[0]['scene_id'] == 'field-book'

    # Protection: 1 green for 'arrival'
    assert len(protection) == 1
    assert protection[0]['scene_id'] == 'arrival'
    assert 'beautiful line' in protection[0]['text']


def test_generate_revision_findings_excludes_skipped():
    """Skipped and removed annotations are excluded from findings."""
    from storyforge.annotations import generate_revision_findings
    annotations = {
        'a1': {'id': 'a1', 'scene_id': 'arrival', 'color': 'pink',
               'text': 'text', 'note': '', 'status': 'skipped', 'fix_location': 'craft'},
        'a2': {'id': 'a2', 'scene_id': 'arrival', 'color': 'pink',
               'text': 'text', 'note': '', 'status': 'removed', 'fix_location': 'craft'},
    }
    craft, structural, protection = generate_revision_findings(annotations)
    assert craft == []
    assert structural == []
    assert protection == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reader_annotations.py::test_generate_revision_findings -v`
Expected: FAIL — `generate_revision_findings` does not exist

- [ ] **Step 3: Implement findings generation**

Add to `scripts/lib/python/storyforge/annotations.py`:

```python
# ============================================================================
# Revision findings generation
# ============================================================================

def generate_revision_findings(
    annotations: dict[str, dict[str, str]],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Generate revision findings from unaddressed annotations.

    Groups annotations by scene and fix_location. Only includes annotations
    with status 'new'.

    Args:
        annotations: Dict of annotations keyed by ID.

    Returns:
        Tuple of (craft_findings, structural_findings, protection_passages).
        craft_findings: list of {scene_id, guidance} for pink annotations.
        structural_findings: list of {scene_id, guidance} for orange annotations.
        protection_passages: list of {scene_id, text, note} for green annotations.
    """
    # Filter to actionable annotations
    actionable = [a for a in annotations.values() if a.get('status') == 'new']

    # Group by scene + fix_location
    craft_by_scene: dict[str, list[dict]] = {}
    structural_by_scene: dict[str, list[dict]] = {}
    protection_list: list[dict] = []

    for ann in actionable:
        scene_id = ann.get('scene_id', '')
        fix_loc = ann.get('fix_location', '')

        if fix_loc == 'craft':
            craft_by_scene.setdefault(scene_id, []).append(ann)
        elif fix_loc == 'structural':
            structural_by_scene.setdefault(scene_id, []).append(ann)
        elif fix_loc in ('protection', 'exemplar'):
            protection_list.append({
                'scene_id': scene_id,
                'text': ann.get('text', ''),
                'note': ann.get('note', ''),
            })

    # Aggregate craft findings per scene
    craft_findings = []
    for scene_id, anns in sorted(craft_by_scene.items()):
        parts = []
        for i, ann in enumerate(anns, 1):
            text = ann.get('text', '')[:100]
            note = ann.get('note', '')
            label = ann.get('color_label', ann.get('color', ''))
            entry = f'{i}. "{text}"'
            if note:
                entry += f' — Reader note: "{note}"'
            else:
                entry += ' — (no note)'
            parts.append(entry)
        guidance = (
            f'Scene "{scene_id}" — {len(anns)} reader annotation(s) ({label}):\n'
            + '\n'.join(parts)
        )
        craft_findings.append({'scene_id': scene_id, 'guidance': guidance})

    # Aggregate structural findings per scene
    structural_findings = []
    for scene_id, anns in sorted(structural_by_scene.items()):
        parts = []
        for i, ann in enumerate(anns, 1):
            text = ann.get('text', '')[:100]
            note = ann.get('note', '')
            entry = f'{i}. "{text}"'
            if note:
                entry += f' — Reader note: "{note}"'
            parts.append(entry)
        guidance = (
            f'Scene "{scene_id}" — {len(anns)} reader annotation(s) (Cut / Reconsider):\n'
            + '\n'.join(parts)
        )
        structural_findings.append({'scene_id': scene_id, 'guidance': guidance})

    return craft_findings, structural_findings, protection_list
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_reader_annotations.py -v`
Expected: PASS (all 14 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/annotations.py tests/test_reader_annotations.py
git commit -m "Add revision findings generation from annotations"
git push
```

---

## Task 4: Exemplar Promotion (Coaching-Level Aware)

**Files:**
- Modify: `scripts/lib/python/storyforge/annotations.py`
- Modify: `tests/test_reader_annotations.py`

- [ ] **Step 1: Write exemplar promotion tests**

Add to `tests/test_reader_annotations.py`:

```python
def test_promote_exemplars_full(tmp_path):
    """In full mode, exemplar candidates are added to exemplars.csv."""
    from storyforge.annotations import promote_exemplars
    os.makedirs(tmp_path / 'working', exist_ok=True)
    os.makedirs(tmp_path / 'scenes', exist_ok=True)
    # Write a scene file so the excerpt can be read
    (tmp_path / 'scenes' / 'arrival.md').write_text(
        'The wagon lurched forward. Beautiful prose here that readers loved.'
    )
    annotations = {
        'g1': {'id': 'g1', 'scene_id': 'arrival', 'color': 'green',
               'color_label': 'Strong Passage',
               'text': 'Beautiful prose here that readers loved',
               'note': 'this is stunning', 'status': 'new',
               'fix_location': 'protection'},
    }
    promoted = promote_exemplars(str(tmp_path), annotations, coaching_level='full')
    assert len(promoted) == 1
    assert promoted[0] == 'g1'
    # Check exemplars.csv was written
    ex_path = tmp_path / 'working' / 'exemplars.csv'
    assert ex_path.exists()
    content = ex_path.read_text()
    assert 'arrival' in content
    assert 'reader-validated' in content


def test_promote_exemplars_coach(tmp_path):
    """In coach mode, exemplar candidates are written to coaching brief."""
    from storyforge.annotations import promote_exemplars
    os.makedirs(tmp_path / 'working' / 'coaching', exist_ok=True)
    annotations = {
        'g1': {'id': 'g1', 'scene_id': 'arrival', 'color': 'green',
               'color_label': 'Strong Passage',
               'text': 'Beautiful prose',
               'note': 'love this', 'status': 'new',
               'fix_location': 'protection'},
    }
    promoted = promote_exemplars(str(tmp_path), annotations, coaching_level='coach')
    assert promoted == []  # coach mode doesn't auto-promote
    brief_path = tmp_path / 'working' / 'coaching' / 'exemplar-candidates.md'
    assert brief_path.exists()
    content = brief_path.read_text()
    assert 'arrival' in content
    assert 'Beautiful prose' in content


def test_promote_exemplars_strict(tmp_path):
    """In strict mode, nothing is written — candidates are returned for display."""
    from storyforge.annotations import promote_exemplars
    annotations = {
        'g1': {'id': 'g1', 'scene_id': 'arrival', 'color': 'green',
               'text': 'text', 'note': 'nice', 'status': 'new',
               'fix_location': 'protection'},
    }
    promoted = promote_exemplars(str(tmp_path), annotations, coaching_level='strict')
    assert promoted == []  # strict mode doesn't auto-promote or write files


def test_promote_exemplars_skips_no_note():
    """Green annotations without notes are not exemplar candidates."""
    from storyforge.annotations import promote_exemplars
    annotations = {
        'g1': {'id': 'g1', 'scene_id': 'arrival', 'color': 'green',
               'text': 'text', 'note': '', 'status': 'new',
               'fix_location': 'protection'},
    }
    promoted = promote_exemplars('/tmp/fake', annotations, coaching_level='full')
    assert promoted == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reader_annotations.py::test_promote_exemplars_full -v`
Expected: FAIL — `promote_exemplars` does not exist

- [ ] **Step 3: Implement exemplar promotion**

Add to `scripts/lib/python/storyforge/annotations.py`:

```python
# ============================================================================
# Exemplar promotion
# ============================================================================

def _get_exemplar_candidates(annotations: dict[str, dict[str, str]]) -> list[dict]:
    """Get green annotations with notes — these are exemplar candidates."""
    return [
        a for a in annotations.values()
        if a.get('color') == 'green'
        and a.get('status') == 'new'
        and (a.get('note', '') or '').strip()
    ]


def promote_exemplars(project_dir: str,
                      annotations: dict[str, dict[str, str]],
                      coaching_level: str = 'full') -> list[str]:
    """Promote reader-validated strong passages based on coaching level.

    Full: adds to working/exemplars.csv, returns list of promoted IDs.
    Coach: writes working/coaching/exemplar-candidates.md, returns [].
    Strict: returns [] (candidates listed in summary output only).

    Args:
        project_dir: Path to book project root.
        annotations: Dict of annotations keyed by ID.
        coaching_level: One of 'full', 'coach', 'strict'.

    Returns:
        List of annotation IDs that were promoted to exemplar status.
    """
    candidates = _get_exemplar_candidates(annotations)
    if not candidates:
        return []

    if coaching_level == 'full':
        return _promote_full(project_dir, candidates)
    elif coaching_level == 'coach':
        _promote_coach(project_dir, candidates)
        return []
    else:
        return []


def _promote_full(project_dir: str, candidates: list[dict]) -> list[str]:
    """Full mode: add to exemplars.csv."""
    exemplars_path = os.path.join(project_dir, 'working', 'exemplars.csv')
    os.makedirs(os.path.dirname(exemplars_path), exist_ok=True)

    if not os.path.isfile(exemplars_path):
        with open(exemplars_path, 'w') as f:
            f.write('principle|scene_id|score|excerpt|cycle\n')

    # Read existing to avoid duplicates
    existing = set()
    with open(exemplars_path) as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 2 and parts[0] != 'principle':
                existing.add((parts[0], parts[1]))

    promoted = []
    with open(exemplars_path, 'a') as f:
        for ann in candidates:
            scene_id = ann.get('scene_id', '')
            key = ('reader-validated', scene_id)
            if key in existing:
                continue
            excerpt = ann.get('text', '')[:200].replace('|', '-')
            note = ann.get('note', '').replace('|', '-')
            f.write(f'reader-validated|{scene_id}|5|{excerpt} (reader: {note})|reader\n')
            promoted.append(ann['id'])

    return promoted


def _promote_coach(project_dir: str, candidates: list[dict]) -> None:
    """Coach mode: write exemplar-candidates.md."""
    coaching_dir = os.path.join(project_dir, 'working', 'coaching')
    os.makedirs(coaching_dir, exist_ok=True)
    path = os.path.join(coaching_dir, 'exemplar-candidates.md')

    lines = ['# Exemplar Candidates (Reader-Validated)\n\n']
    lines.append('These passages were highlighted as "Strong Passage" by readers ')
    lines.append('and include notes explaining why. Consider adding them to your ')
    lines.append('exemplar file for use in drafting prompts.\n\n')

    for ann in candidates:
        scene_id = ann.get('scene_id', '')
        text = ann.get('text', '')
        note = ann.get('note', '')
        reader = ann.get('reader', 'Anonymous')
        lines.append(f'## Scene: {scene_id}\n\n')
        lines.append(f'> {text}\n\n')
        lines.append(f'**Reader ({reader}):** {note}\n\n')
        lines.append('---\n\n')

    with open(path, 'w') as f:
        f.writelines(lines)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_reader_annotations.py -v`
Expected: PASS (all 18 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/annotations.py tests/test_reader_annotations.py
git commit -m "Add coaching-level-aware exemplar promotion from reader annotations"
git push
```

---

## Task 5: Command Module

**Files:**
- Create: `scripts/lib/python/storyforge/cmd_annotations.py`
- Modify: `scripts/lib/python/storyforge/__main__.py`

- [ ] **Step 1: Create the command module**

```python
# scripts/lib/python/storyforge/cmd_annotations.py
"""storyforge annotations — Fetch and process reader annotations from Bookshelf.

Fetches reader annotations, reconciles against working/annotations.csv,
routes by color intent, and promotes exemplar candidates.

Usage:
    storyforge annotations                    # Fetch and reconcile
    storyforge annotations --status new       # Show only unaddressed
    storyforge annotations --color pink       # Filter by color
    storyforge annotations --scene arrival    # Filter by scene
    storyforge annotations --dry-run          # Show what would be fetched
"""

import argparse
import os
import re
import sys

from storyforge.common import (
    detect_project_root, install_signal_handlers, log, read_yaml_field,
    get_coaching_level,
)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge annotations',
        description='Fetch and process reader annotations from Bookshelf.',
    )
    parser.add_argument('--status', choices=['new', 'addressed', 'skipped',
                                              'protected', 'exemplar', 'removed'],
                        help='Filter display to one status')
    parser.add_argument('--color', choices=['pink', 'orange', 'blue', 'green', 'yellow'],
                        help='Filter display to one color')
    parser.add_argument('--scene', help='Filter display to one scene ID')
    parser.add_argument('--dry-run', action='store_true',
                        help='Fetch and display without writing CSV')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()

    from storyforge.bookshelf import authenticate, check_env, get_annotations
    from storyforge.annotations import (
        load_annotations_csv, save_annotations_csv, reconcile,
        promote_exemplars, COLOR_LABELS,
    )

    # Derive book slug from title
    title = (read_yaml_field('project.title', project_dir)
             or read_yaml_field('title', project_dir) or '')
    if not title:
        log('ERROR: No project title found in storyforge.yaml')
        sys.exit(1)
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

    # Authenticate
    env = check_env()
    log('Authenticating with Supabase...')
    try:
        token = authenticate(
            env['BOOKSHELF_SUPABASE_URL'],
            env['BOOKSHELF_SUPABASE_ANON_KEY'],
            env['BOOKSHELF_EMAIL'],
            env['BOOKSHELF_PASSWORD'],
        )
    except RuntimeError as e:
        log(f'Authentication failed: {e}')
        sys.exit(1)

    # Fetch annotations
    log(f'Fetching annotations for "{title}" (slug: {slug})...')
    try:
        data = get_annotations(env['BOOKSHELF_URL'], token, slug)
    except RuntimeError as e:
        log(f'Failed to fetch annotations: {e}')
        sys.exit(1)

    api_annotations = data.get('annotations', [])
    log(f'API returned {len(api_annotations)} annotation(s)')

    # Reconcile
    existing = load_annotations_csv(project_dir)
    updated, summary = reconcile(existing, api_annotations)

    log(f'Reconciliation: {summary["new"]} new, '
        f'{summary["existing"]} existing, '
        f'{summary["removed"]} removed, '
        f'{summary["total"]} total')

    # Exemplar promotion
    coaching_level = get_coaching_level(project_dir)
    promoted = promote_exemplars(project_dir, updated, coaching_level)
    for ann_id in promoted:
        updated[ann_id]['status'] = 'exemplar'
        updated[ann_id]['fix_location'] = 'exemplar'

    if promoted:
        log(f'Promoted {len(promoted)} passage(s) to exemplars')

    # Save
    if not args.dry_run:
        path = save_annotations_csv(project_dir, updated)
        log(f'Saved: {path}')
    else:
        log('Dry run — not writing annotations CSV')

    # Display summary by color
    display = list(updated.values())
    if args.status:
        display = [a for a in display if a.get('status') == args.status]
    if args.color:
        display = [a for a in display if a.get('color') == args.color]
    if args.scene:
        display = [a for a in display if a.get('scene_id') == args.scene]

    if display:
        log('')
        log(f'Annotations ({len(display)}):')
        for ann in display:
            scene = ann.get('scene_id', '?')
            color = ann.get('color', '?')
            label = ann.get('color_label', COLOR_LABELS.get(color, color))
            status = ann.get('status', '?')
            text = ann.get('text', '')[:60]
            note = ann.get('note', '')
            line = f'  [{status}] {scene} ({label}): "{text}"'
            if note:
                line += f' — {note[:40]}'
            log(line)

    # Count unaddressed by intent
    new_craft = sum(1 for a in updated.values()
                    if a.get('status') == 'new' and a.get('fix_location') == 'craft')
    new_structural = sum(1 for a in updated.values()
                         if a.get('status') == 'new' and a.get('fix_location') == 'structural')
    new_protection = sum(1 for a in updated.values()
                         if a.get('status') == 'new' and a.get('fix_location') == 'protection')
    new_research = sum(1 for a in updated.values()
                       if a.get('status') == 'new' and a.get('fix_location') == 'research')

    if new_craft or new_structural or new_protection or new_research:
        log('')
        log('Unaddressed:')
        if new_craft:
            log(f'  {new_craft} craft revision(s) (pink/yellow)')
        if new_structural:
            log(f'  {new_structural} structural revision(s) (orange)')
        if new_protection:
            log(f'  {new_protection} passage(s) to protect (green)')
        if new_research:
            log(f'  {new_research} research item(s) (blue)')
```

- [ ] **Step 2: Register the command**

In `scripts/lib/python/storyforge/__main__.py`, add to COMMANDS dict:

```python
    'annotations': 'storyforge.cmd_annotations',
```

- [ ] **Step 3: Test dispatch**

Run: `python3 -m storyforge annotations --help`
Expected: Shows help text

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_annotations.py scripts/lib/python/storyforge/__main__.py
git commit -m "Add storyforge annotations command"
git push
```

---

## Task 6: Revision Pipeline Integration

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py`
- Modify: `tests/test_reader_annotations.py`

- [ ] **Step 1: Write integration test**

Add to `tests/test_reader_annotations.py`:

```python
def test_load_annotation_findings_for_revise(tmp_path):
    """Annotations CSV with new entries produces revision findings."""
    from storyforge.annotations import (
        load_annotations_csv, save_annotations_csv, generate_revision_findings,
    )
    # Create an annotations CSV
    annotations = {
        'a1': {'id': 'a1', 'scene_id': 'arrival', 'chapter': '1',
               'color': 'pink', 'color_label': 'Needs Revision',
               'text': 'the wagon lurched', 'note': 'pacing issue',
               'reader': 'Alice', 'created_at': '2026-04-10',
               'status': 'new', 'fix_location': 'craft', 'fetched_at': '2026-04-14'},
    }
    save_annotations_csv(str(tmp_path), annotations)

    # Load and generate findings
    loaded = load_annotations_csv(str(tmp_path))
    craft, structural, protection = generate_revision_findings(loaded)
    assert len(craft) == 1
    assert craft[0]['scene_id'] == 'arrival'
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_reader_annotations.py::test_load_annotation_findings_for_revise -v`
Expected: PASS (this tests existing functions wired together)

- [ ] **Step 3: Add annotation awareness to cmd_revise.py**

In `cmd_revise.py`, find the section in `main()` where the plan is generated (around lines 1244-1260 where `_generate_polish_plan`, `_generate_naturalness_plan`, etc. are called). After the plan is generated but before the main pass loop starts (around line 1420), add annotation loading:

```python
    # ---- Load reader annotations if available ----
    annotations_csv = os.path.join(project_dir, 'working', 'annotations.csv')
    annotation_findings = []
    annotation_protection = []
    if os.path.isfile(annotations_csv) and not getattr(args, 'no_annotations', False):
        from storyforge.annotations import load_annotations_csv, generate_revision_findings
        ann_data = load_annotations_csv(project_dir)
        craft_findings, struct_findings, prot_passages = generate_revision_findings(ann_data)
        annotation_findings = craft_findings + struct_findings
        annotation_protection = prot_passages
        if annotation_findings:
            log(f'Reader annotations: {len(annotation_findings)} finding(s) from unaddressed annotations')
        if annotation_protection:
            log(f'Reader annotations: {len(annotation_protection)} passage(s) to protect')
```

Also add `--no-annotations` flag to the argument parser (in `parse_args`, around line 67):

```python
    parser.add_argument('--no-annotations', action='store_true',
                        help='Exclude reader annotations from revision plan')
```

Then, in the pass execution loop, inject annotation guidance into the revision prompt. Find where the `guidance` variable is assembled for each pass (around line 1458-1476). After the existing guidance is loaded, append annotation findings:

```python
        # Inject reader annotation findings for this pass
        if annotation_findings:
            pass_fix_loc = _read_pass_field(plan_rows, pass_num, 'fix_location')
            relevant = [f for f in annotation_findings
                        if (pass_fix_loc == 'craft' and 'Needs Revision' in f['guidance'])
                        or (pass_fix_loc != 'craft')]
            if relevant:
                guidance += '\n\n## Reader Annotations\n'
                guidance += 'The following passages were flagged by readers:\n\n'
                for finding in relevant:
                    guidance += finding['guidance'] + '\n\n'

        # Inject reader protection constraints
        if annotation_protection and protection:
            prot_texts = [p['text'][:80] for p in annotation_protection]
            protection += '\nReader-validated passages (do not rewrite): ' + '; '.join(f'"{t}"' for t in prot_texts)
        elif annotation_protection:
            prot_texts = [p['text'][:80] for p in annotation_protection]
            protection = 'Reader-validated passages (do not rewrite): ' + '; '.join(f'"{t}"' for t in prot_texts)
```

- [ ] **Step 4: Add annotation status update after passes**

At the end of the pass loop (after a pass completes successfully for a scene), update the annotation status. Find where `commit_and_push` is called after each pass completes (around line 1567), and before it add:

```python
        # Update annotation status for revised scenes
        if annotation_findings and os.path.isfile(annotations_csv):
            from storyforge.annotations import load_annotations_csv, save_annotations_csv
            ann_data = load_annotations_csv(project_dir)
            revised_scenes = set()
            # Collect scene IDs that were revised in this pass
            if pass_scope == 'full':
                scenes_dir_path = os.path.join(project_dir, 'scenes')
                if os.path.isdir(scenes_dir_path):
                    revised_scenes = {f[:-3] for f in os.listdir(scenes_dir_path) if f.endswith('.md')}
            else:
                revised_scenes = set(t.strip() for t in pass_targets.split(';') if t.strip())

            updated_count = 0
            for ann_id, ann in ann_data.items():
                if (ann.get('status') == 'new'
                        and ann.get('scene_id') in revised_scenes
                        and ann.get('fix_location') in ('craft', 'structural')):
                    ann['status'] = 'addressed'
                    updated_count += 1

            if updated_count:
                save_annotations_csv(project_dir, ann_data)
                log(f'  Updated {updated_count} annotation(s) to "addressed"')
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_reader_annotations.py tests/test_revise_args.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_reader_annotations.py
git commit -m "Wire reader annotations into revision pipeline"
git push
```

---

## Task 7: Hone Pipeline Integration

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_hone.py`

- [ ] **Step 1: Add annotation awareness to cmd_hone.py**

Find where `cmd_hone.py` loads external findings (search for `load_external_findings` or `--findings`). After the existing findings loading, add annotation loading:

```python
    # Load reader annotations if available
    annotations_csv = os.path.join(project_dir, 'working', 'annotations.csv')
    if os.path.isfile(annotations_csv):
        from storyforge.annotations import load_annotations_csv, generate_revision_findings
        ann_data = load_annotations_csv(project_dir)
        craft_findings, _, _ = generate_revision_findings(ann_data)
        if craft_findings:
            log(f'Reader annotations: {len(craft_findings)} finding(s) from unaddressed annotations')
            # Convert to hone findings format
            for finding in craft_findings:
                scene_id = finding['scene_id']
                guidance = finding['guidance']
                external_findings.append({
                    'scene_id': scene_id,
                    'field': '',
                    'target_file': 'scene-briefs.csv',
                    'guidance': guidance,
                    'issue': 'evaluation',
                })
```

The exact insertion point depends on how `cmd_hone.py` collects external findings. Read the file to find where `external_findings` or the equivalent list is built, and append annotation findings there.

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_reader_annotations.py tests/test_hone_findings.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_hone.py
git commit -m "Wire reader annotations into hone pipeline"
git push
```

---

## Task 8: Documentation Updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `skills/forge/SKILL.md`
- Modify: `skills/revise/SKILL.md`
- Modify: `skills/hone/SKILL.md`

- [ ] **Step 1: Update CLAUDE.md**

Add to the Commands table (alphabetical order):
```
| `storyforge annotations` | `cmd_annotations.py` | Fetch reader annotations from Bookshelf, reconcile, route by color intent. |
```

Add to the Key CSV Files section under Shared:
```
- `working/annotations.csv` — reader annotations from Bookshelf (id, scene_id, color, text, note, status, fix_location)
```

Add to the Domain modules table:
```
| `annotations.py` | Reader annotation processing: fetch, reconcile, route, exemplar promotion |
```

- [ ] **Step 2: Update skills/forge/SKILL.md**

Add routing for: "annotations" / "reader feedback" / "what did my readers say" / "reader highlights" → `storyforge annotations` command.

Add `working/annotations.csv` to the project state files the forge checks on startup.

- [ ] **Step 3: Update skills/revise/SKILL.md**

Add a note that revise checks for `working/annotations.csv` and incorporates unaddressed reader annotations into the revision plan. Mention `--no-annotations` to skip.

- [ ] **Step 4: Update skills/hone/SKILL.md**

Add a note that hone checks for reader annotations and surfaces them alongside auto-detected quality issues.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md skills/forge/SKILL.md skills/revise/SKILL.md skills/hone/SKILL.md
git commit -m "Update CLAUDE.md and skills with annotations documentation"
git push
```

---

## Task 9: Version Bump and Final Validation

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Bump version**

Read `.claude-plugin/plugin.json`, increment the minor version.

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to X.Y.0"
git push
```

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
            result[ann_id]['fetched_at'] = now
            summary['existing'] += 1
        else:
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

    terminal_states = {'addressed', 'skipped', 'protected', 'exemplar'}
    for ann_id, ann in result.items():
        if ann_id not in api_ids and ann.get('status') not in terminal_states:
            if ann.get('status') != 'removed':
                ann['status'] = 'removed'
                summary['removed'] += 1

    summary['total'] = len(result)
    return result, summary

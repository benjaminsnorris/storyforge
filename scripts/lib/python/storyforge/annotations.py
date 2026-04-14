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
    actionable = [a for a in annotations.values() if a.get('status') == 'new']

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

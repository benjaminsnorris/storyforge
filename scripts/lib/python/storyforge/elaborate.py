"""Elaboration pipeline helpers — scene data access and structural validation.

Provides a unified interface over the three-file scene CSV model:
  - reference/scenes.csv       (structural identity and position)
  - reference/scene-intent.csv (purpose, dynamics, tracking)
  - reference/scene-briefs.csv (drafting contract)

All files are pipe-delimited with 'id' as the join key.
"""

import csv
import os
from typing import Any


DELIMITER = '|'

# Column-to-file mapping (which file owns which columns)
_SCENES_COLS = [
    'id', 'seq', 'title', 'part', 'pov', 'location',
    'timeline_day', 'time_of_day', 'duration', 'status',
    'word_count', 'target_words',
]
_INTENT_COLS = [
    'id', 'function', 'scene_type', 'emotional_arc', 'value_at_stake',
    'value_shift', 'turning_point', 'threads', 'characters', 'on_stage',
    'mice_threads',
]
_BRIEFS_COLS = [
    'id', 'goal', 'conflict', 'outcome', 'crisis', 'decision',
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'continuity_deps', 'has_overflow',
]

_FILE_MAP = {
    'scenes.csv': _SCENES_COLS,
    'scene-intent.csv': _INTENT_COLS,
    'scene-briefs.csv': _BRIEFS_COLS,
}


# ============================================================================
# CSV I/O
# ============================================================================

def _read_csv(path: str) -> list[dict[str, str]]:
    """Read a pipe-delimited CSV into a list of dicts."""
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=DELIMITER)
        return list(reader)


def _read_csv_as_map(path: str) -> dict[str, dict[str, str]]:
    """Read a pipe-delimited CSV into a dict keyed by 'id'."""
    rows = _read_csv(path)
    return {row['id']: row for row in rows if 'id' in row}


def _write_csv(path: str, rows: list[dict[str, str]], columns: list[str]) -> None:
    """Write rows to a pipe-delimited CSV with the given column order."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=columns, delimiter=DELIMITER,
            extrasaction='ignore',
        )
        writer.writeheader()
        writer.writerows(rows)


def _file_for_column(col: str) -> str | None:
    """Return the CSV filename that owns the given column."""
    for filename, cols in _FILE_MAP.items():
        if col in cols:
            return filename
    return None


# ============================================================================
# Read helpers
# ============================================================================

def get_scene(scene_id: str, ref_dir: str) -> dict[str, str] | None:
    """Return all columns for a scene, merged across all three files.

    Args:
        scene_id: The scene's id value.
        ref_dir: Path to the reference/ directory containing the CSV files.

    Returns:
        A dict with all columns, or None if the scene doesn't exist in scenes.csv.
    """
    scenes = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    if scene_id not in scenes:
        return None

    row = dict(scenes[scene_id])

    # Merge intent columns
    intents = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    if scene_id in intents:
        for k, v in intents[scene_id].items():
            if k != 'id':
                row[k] = v
    else:
        for col in _INTENT_COLS:
            if col != 'id':
                row.setdefault(col, '')

    # Merge brief columns
    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    if scene_id in briefs:
        for k, v in briefs[scene_id].items():
            if k != 'id':
                row[k] = v
    else:
        for col in _BRIEFS_COLS:
            if col != 'id':
                row.setdefault(col, '')

    return row


def get_scenes(
    ref_dir: str,
    columns: list[str] | None = None,
    filters: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Query scenes with optional column selection and filtering.

    Args:
        ref_dir: Path to the reference/ directory.
        columns: If provided, only include these columns in each result dict.
        filters: If provided, only include scenes where each key==value matches.

    Returns:
        A list of dicts, one per matching scene, sorted by seq.
    """
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    results = []
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    for sid in sorted_ids:
        row = dict(scenes_map[sid])
        if sid in intent_map:
            for k, v in intent_map[sid].items():
                if k != 'id':
                    row[k] = v
        else:
            for col in _INTENT_COLS:
                if col != 'id':
                    row.setdefault(col, '')
        if sid in briefs_map:
            for k, v in briefs_map[sid].items():
                if k != 'id':
                    row[k] = v
        else:
            for col in _BRIEFS_COLS:
                if col != 'id':
                    row.setdefault(col, '')

        if filters:
            if not all(row.get(k) == v for k, v in filters.items()):
                continue

        if columns:
            row = {k: row[k] for k in columns if k in row}

        results.append(row)

    return results


def get_column(ref_dir: str, column: str) -> list[str]:
    """Return one column's values across all scenes, sorted by seq.

    Args:
        ref_dir: Path to the reference/ directory.
        column: The column name to extract.

    Returns:
        A list of string values, one per scene, in seq order.
    """
    scenes = get_scenes(ref_dir, columns=['id', column])
    return [s.get(column, '') for s in scenes]


# ============================================================================
# Write helpers
# ============================================================================

def update_scene(scene_id: str, ref_dir: str, updates: dict[str, str]) -> None:
    """Update specific columns for a scene, writing to the correct file(s).

    Args:
        scene_id: The scene's id value.
        ref_dir: Path to the reference/ directory.
        updates: Dict of column_name -> new_value.
    """
    file_updates: dict[str, dict[str, str]] = {}
    for col, val in updates.items():
        filename = _file_for_column(col)
        if filename is None:
            continue
        file_updates.setdefault(filename, {})[col] = val

    for filename, cols_to_update in file_updates.items():
        path = os.path.join(ref_dir, filename)
        rows = _read_csv(path)
        col_order = _FILE_MAP[filename]

        found = False
        for row in rows:
            if row.get('id') == scene_id:
                row.update(cols_to_update)
                found = True
                break

        if not found:
            new_row = {c: '' for c in col_order}
            new_row['id'] = scene_id
            new_row.update(cols_to_update)
            rows.append(new_row)

        _write_csv(path, rows, col_order)


def add_scenes(ref_dir: str, scenes: list[dict[str, str]]) -> None:
    """Add new scene rows across all three files.

    Each scene dict can contain columns from any file. Columns are routed
    to the appropriate file. Missing columns are filled with empty strings.

    Args:
        ref_dir: Path to the reference/ directory.
        scenes: List of dicts, each with at minimum 'id' and 'seq'.
    """
    for filename, col_order in _FILE_MAP.items():
        path = os.path.join(ref_dir, filename)
        existing = _read_csv(path)

        for scene in scenes:
            new_row = {c: '' for c in col_order}
            new_row['id'] = scene['id']
            for col in col_order:
                if col in scene:
                    new_row[col] = scene[col]
            existing.append(new_row)

        _write_csv(path, existing, col_order)


# ============================================================================
# Wave planner — parallel drafting groups
# ============================================================================

def compute_drafting_waves(ref_dir: str) -> list[list[str]]:
    """Compute parallel drafting waves from continuity_deps.

    Scenes with no deps go in wave 1. Scenes whose deps are all in
    earlier waves go in the next wave. Returns a list of waves, each
    wave being a list of scene IDs that can be drafted in parallel.

    Args:
        ref_dir: Path to the reference/ directory.

    Returns:
        List of waves, e.g. [['scene-a', 'scene-b'], ['scene-c'], ['scene-d']]
    """
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))

    # Only include briefed/drafted scenes
    eligible = set()
    for sid, scene in scenes_map.items():
        status = scene.get('status', '')
        if status in ('briefed', 'drafted', 'polished'):
            eligible.add(sid)

    # Build dependency graph
    deps: dict[str, set[str]] = {}
    for sid in eligible:
        brief = briefs_map.get(sid, {})
        dep_str = brief.get('continuity_deps', '').strip()
        if dep_str:
            deps[sid] = {d.strip() for d in dep_str.split(';') if d.strip() and d.strip() in eligible}
        else:
            deps[sid] = set()

    # Topological sort into waves
    waves: list[list[str]] = []
    assigned: set[str] = set()
    remaining = set(eligible)

    while remaining:
        # Find scenes whose deps are all assigned
        wave = []
        for sid in sorted(remaining, key=lambda s: int(scenes_map.get(s, {}).get('seq', 0))):
            if deps.get(sid, set()).issubset(assigned):
                wave.append(sid)

        if not wave:
            # Circular dependency — break it by taking the lowest-seq scene
            lowest = min(remaining, key=lambda s: int(scenes_map.get(s, {}).get('seq', 0)))
            wave = [lowest]

        waves.append(wave)
        assigned.update(wave)
        remaining -= set(wave)

    return waves


# ============================================================================
# Structural scoring — pre-draft quality checks on brief data
# ============================================================================

def score_structure(ref_dir: str) -> list[dict]:
    """Score structural quality of scenes based on brief and intent data.

    Returns a list of per-scene score dicts with:
      - scene_id
      - score (0-5)
      - issues (list of strings describing problems)

    Scenes without briefs get score 0. Scenes with complete, well-formed
    briefs that pass all checks get score 5.
    """
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    results = []
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    for sid in sorted_ids:
        scene = scenes_map[sid]
        intent = intent_map.get(sid, {})
        brief = briefs_map.get(sid, {})
        issues = []
        score = 5  # Start perfect, deduct for problems

        # No brief at all
        if not brief or not brief.get('goal', '').strip():
            results.append({'scene_id': sid, 'score': 0, 'issues': ['No brief data']})
            continue

        # Goal/conflict/outcome chain
        if not brief.get('goal', '').strip():
            issues.append('Missing goal')
            score -= 1
        if not brief.get('conflict', '').strip():
            issues.append('Missing conflict')
            score -= 1
        if not brief.get('outcome', '').strip():
            issues.append('Missing outcome')
            score -= 1

        # Crisis should be a genuine dilemma
        crisis = brief.get('crisis', '').strip()
        if not crisis:
            issues.append('Missing crisis')
            score -= 1

        # Value shift should not be flat
        vs = intent.get('value_shift', '').strip()
        if vs:
            parts = vs.split('/')
            if len(parts) == 2 and parts[0].strip() == parts[1].strip():
                issues.append(f'Flat value shift: {vs}')
                score -= 1

        # Knowledge flow
        if not brief.get('knowledge_in', '').strip() and int(scene.get('seq', 0)) > 1:
            issues.append('Missing knowledge_in (not the first scene)')
            score -= 1
        if not brief.get('knowledge_out', '').strip():
            issues.append('Missing knowledge_out')
            score -= 1

        score = max(0, min(5, score))
        results.append({'scene_id': sid, 'score': score, 'issues': issues})

    return results


# ============================================================================
# Structural validation
# ============================================================================

# Required columns per status level
_REQUIRED_BY_STATUS = {
    'spine': ['id', 'seq', 'title', 'function'],
    'architecture': ['id', 'seq', 'title', 'part', 'pov', 'function',
                      'scene_type', 'emotional_arc', 'value_at_stake',
                      'value_shift', 'turning_point', 'threads'],
    'mapped': ['id', 'seq', 'title', 'part', 'pov', 'location',
               'timeline_day', 'time_of_day', 'function', 'scene_type',
               'emotional_arc', 'value_at_stake', 'value_shift',
               'turning_point', 'threads', 'characters', 'on_stage'],
    'briefed': ['id', 'seq', 'title', 'part', 'pov', 'location',
                'timeline_day', 'time_of_day', 'function', 'scene_type',
                'emotional_arc', 'value_at_stake', 'value_shift',
                'turning_point', 'threads', 'characters', 'on_stage',
                'goal', 'conflict', 'outcome'],
    'drafted': ['id', 'seq', 'title', 'part', 'pov', 'location',
                'timeline_day', 'time_of_day', 'function', 'scene_type',
                'emotional_arc', 'value_at_stake', 'value_shift',
                'turning_point', 'threads', 'characters', 'on_stage',
                'goal', 'conflict', 'outcome'],
    'polished': ['id', 'seq', 'title', 'part', 'pov', 'location',
                 'timeline_day', 'time_of_day', 'function', 'scene_type',
                 'emotional_arc', 'value_at_stake', 'value_shift',
                 'turning_point', 'threads', 'characters', 'on_stage',
                 'goal', 'conflict', 'outcome'],
}


def _check(category: str, check: str, passed: bool, message: str,
           severity: str = 'blocking', scene_id: str = '') -> dict:
    """Build a single check result."""
    result = {
        'category': category,
        'check': check,
        'passed': passed,
        'message': message,
        'severity': severity,
    }
    if scene_id:
        result['scene_id'] = scene_id
    return result


def _validate_threads(scenes_map, intent_map, checks):
    """Check thread management: MICE nesting, dormancy, resolution."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    open_threads = []  # stack of (thread_name, scene_id)
    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        mice = intent.get('mice_threads', '').strip()
        if not mice:
            continue
        for entry in mice.split(';'):
            entry = entry.strip()
            if not entry:
                continue
            if entry.startswith('+'):
                thread_name = entry[1:]
                open_threads.append((thread_name, sid))
            elif entry.startswith('-'):
                thread_name = entry[1:]
                if open_threads and open_threads[-1][0] == thread_name:
                    open_threads.pop()
                elif any(t[0] == thread_name for t in open_threads):
                    checks.append(_check(
                        'threads', 'mice-nesting', False,
                        f"MICE nesting violation: closing '{thread_name}' in {sid} "
                        f"but '{open_threads[-1][0]}' (opened in {open_threads[-1][1]}) "
                        f"should close first",
                        scene_id=sid,
                    ))
                    open_threads = [(t, s) for t, s in open_threads if t != thread_name]
                else:
                    checks.append(_check(
                        'threads', 'mice-nesting', False,
                        f"Closing MICE thread '{thread_name}' in {sid} but it was never opened",
                        scene_id=sid,
                    ))

    if not any(c['check'] == 'mice-nesting' and not c['passed'] for c in checks):
        checks.append(_check('threads', 'mice-nesting', True, 'MICE threads nest correctly'))

    if open_threads:
        unclosed = [f"{name} (opened in {sid})" for name, sid in open_threads]
        checks.append(_check(
            'threads', 'unclosed-mice-threads', False,
            f"Unclosed MICE threads: {unclosed}",
            severity='advisory',
        ))


def _validate_timeline(scenes_map, checks):
    """Check timeline consistency: no backwards jumps without markers."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    prev_day = None
    prev_id = None
    for sid in sorted_ids:
        day_str = scenes_map[sid].get('timeline_day', '').strip()
        if not day_str:
            continue
        try:
            day = int(day_str)
        except ValueError:
            continue

        if prev_day is not None and day < prev_day:
            checks.append(_check(
                'timeline', 'timeline-order', False,
                f"Scene {sid} (day {day}) comes after {prev_id} (day {prev_day}) — backwards jump",
                scene_id=sid,
            ))

        prev_day = day
        prev_id = sid

    if not any(c['check'] == 'timeline-order' and not c['passed'] for c in checks):
        checks.append(_check('timeline', 'timeline-order', True, 'Timeline order is consistent'))


def _validate_knowledge(scenes_map, briefs_map, checks):
    """Check knowledge flow: knowledge_in should be available from prior scenes."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    available_knowledge = set()
    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        knowledge_in = brief.get('knowledge_in', '').strip()

        if knowledge_in and available_knowledge:
            facts_in = {f.strip() for f in knowledge_in.split(';') if f.strip()}
            unknown = facts_in - available_knowledge
            if unknown:
                checks.append(_check(
                    'knowledge', 'knowledge-availability', False,
                    f"Scene {sid} requires knowledge not established by prior scenes: "
                    f"{sorted(unknown)}",
                    scene_id=sid,
                    severity='advisory',
                ))

        knowledge_out = brief.get('knowledge_out', '').strip()
        if knowledge_out:
            for fact in knowledge_out.split(';'):
                fact = fact.strip()
                if fact:
                    available_knowledge.add(fact)

    if not any(c['category'] == 'knowledge' and not c['passed'] for c in checks):
        checks.append(_check('knowledge', 'knowledge-availability', True,
                             'Knowledge flow is consistent'))


def _validate_pacing(scenes_map, intent_map, checks):
    """Check pacing: polarity stretches, scene type rhythm, turning point variety."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    scene_types = []
    value_shifts = []
    turning_points = []

    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        st = intent.get('scene_type', '').strip()
        vs = intent.get('value_shift', '').strip()
        tp = intent.get('turning_point', '').strip()
        if st:
            scene_types.append((sid, st))
        if vs:
            value_shifts.append((sid, vs))
        if tp:
            turning_points.append((sid, tp))

    # Flat polarity: 3+ consecutive scenes where value doesn't change
    flat_threshold = 3
    flat_run = []
    for sid, vs in value_shifts:
        parts = vs.split('/')
        is_flat = len(parts) == 2 and parts[0].strip() == parts[1].strip()
        if is_flat:
            flat_run.append(sid)
        else:
            if len(flat_run) >= flat_threshold:
                checks.append(_check(
                    'pacing', 'flat-polarity', False,
                    f"Flat polarity stretch ({len(flat_run)} scenes): {flat_run}",
                    severity='advisory',
                ))
            flat_run = []
    if len(flat_run) >= flat_threshold:
        checks.append(_check(
            'pacing', 'flat-polarity', False,
            f"Flat polarity stretch ({len(flat_run)} scenes): {flat_run}",
            severity='advisory',
        ))

    if not any(c['check'] == 'flat-polarity' and not c['passed'] for c in checks):
        checks.append(_check('pacing', 'flat-polarity', True, 'No flat polarity stretches'))

    # Scene type rhythm: no 4+ consecutive same type
    type_threshold = 4
    type_found = False
    if len(scene_types) >= type_threshold:
        for i in range(len(scene_types) - type_threshold + 1):
            window = scene_types[i:i + type_threshold]
            if all(t[1] == window[0][1] for t in window):
                ids = [t[0] for t in window]
                checks.append(_check(
                    'pacing', 'scene-type-rhythm', False,
                    f"{type_threshold}+ consecutive '{window[0][1]}' scenes: {ids}",
                    severity='advisory',
                ))
                type_found = True
                break

    if not type_found:
        checks.append(_check('pacing', 'scene-type-rhythm', True,
                             'Scene type rhythm is varied'))

    # Turning point variety: no 4+ consecutive same type
    tp_found = False
    if len(turning_points) >= type_threshold:
        for i in range(len(turning_points) - type_threshold + 1):
            window = turning_points[i:i + type_threshold]
            if all(t[1] == window[0][1] for t in window):
                ids = [t[0] for t in window]
                checks.append(_check(
                    'pacing', 'turning-point-variety', False,
                    f"{type_threshold}+ consecutive '{window[0][1]}' turning points: {ids}",
                    severity='advisory',
                ))
                tp_found = True
                break

    if not tp_found:
        checks.append(_check('pacing', 'turning-point-variety', True,
                             'Turning point types are varied'))


def validate_structure(ref_dir: str) -> dict:
    """Run all structural validation checks against the scene CSVs.

    Returns:
        A dict with 'passed' (bool), 'checks' (list of check results),
        and 'failures' (list of failed checks only).
    """
    checks: list[dict] = []

    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))

    scene_ids = set(scenes_map.keys())
    intent_ids = set(intent_map.keys())
    briefs_ids = set(briefs_map.keys())

    # --- Identity: no orphaned rows ---
    orphaned_intent = intent_ids - scene_ids
    checks.append(_check(
        'identity', 'orphaned-intent-rows',
        len(orphaned_intent) == 0,
        f"Intent rows with no matching scene: {sorted(orphaned_intent)}" if orphaned_intent
        else "All intent rows have matching scenes",
    ))

    orphaned_briefs = briefs_ids - scene_ids
    checks.append(_check(
        'identity', 'orphaned-brief-rows',
        len(orphaned_briefs) == 0,
        f"Brief rows with no matching scene: {sorted(orphaned_briefs)}" if orphaned_briefs
        else "All brief rows have matching scenes",
    ))

    # --- Completeness: required columns for status ---
    for sid, scene in scenes_map.items():
        status = scene.get('status', 'spine')
        if status not in _REQUIRED_BY_STATUS:
            continue

        required = _REQUIRED_BY_STATUS[status]
        merged = dict(scene)
        if sid in intent_map:
            merged.update({k: v for k, v in intent_map[sid].items() if k != 'id'})
        if sid in briefs_map:
            merged.update({k: v for k, v in briefs_map[sid].items() if k != 'id'})

        missing = [col for col in required if not merged.get(col, '').strip()]
        checks.append(_check(
            'completeness', f'required-columns-{sid}',
            len(missing) == 0,
            f"Scene {sid} (status={status}) missing required columns: {missing}" if missing
            else f"Scene {sid} has all required columns for status={status}",
            scene_id=sid,
        ))

    # --- Thread, timeline, knowledge, pacing ---
    _validate_threads(scenes_map, intent_map, checks)
    _validate_timeline(scenes_map, checks)
    _validate_knowledge(scenes_map, briefs_map, checks)
    _validate_pacing(scenes_map, intent_map, checks)

    failures = [c for c in checks if not c['passed']]
    return {
        'passed': len(failures) == 0,
        'checks': checks,
        'failures': failures,
    }

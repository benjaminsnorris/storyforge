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

# Time modes that are never the story's present: frame narration from after
# the story, and a vision (a future or a "shadow" the story doesn't treat as
# fixed, such as A Christmas Carol's Stave IV)
OFF_PRESENT_MODES = frozenset({'frame', 'vision'})


DELIMITER = '|'

# Column-to-file mapping (which file owns which columns)
# `summary` is a one-sentence outline shared by spine, architecture, and
# scenes — read top-to-bottom, the summary column is the expanding outline
# of the story. Other columns add structural detail for downstream
# elaboration.
_SCENES_COLS = [
    # `part` is the book's physical division (from the manuscript's part
    # headings; empty for a book without parts). `act` is the structural act.
    'id', 'seq', 'title', 'summary', 'part', 'act', 'pov', 'location',
    'timeline_day', 'time_of_day', 'duration', 'type', 'status',
    'word_count', 'target_words',
    # How the scene sits in time (scene | summary | frame | vision) and the calendar
    # date its own text states, in EDTF (docs/plans/timeline-pass.md)
    'time_mode', 'timeline_date',
    # Graphic-novel-mode columns (ignored in novel mode, written in GN mode)
    'target_pages', 'panel_count', 'page_count',
    # Pointer back to the architecture anchor this map scene serves
    # (empty for purely interstitial scenes).
    'architecture_scene',
]
_INTENT_COLS = [
    'id', 'function', 'action_sequel', 'emotional_arc', 'value_at_stake',
    'value_shift', 'turning_point', 'characters', 'on_stage',
    'mice_threads',
    # Themes (abstract concerns) this scene engages — references themes.csv.
    'theme_threads',
]
_BRIEFS_COLS = [
    'id', 'goal', 'conflict', 'outcome', 'crisis', 'decision',
    'knowledge_in', 'knowledge_out', 'key_actions', 'key_dialogue',
    'emotions', 'motifs', 'subtext', 'continuity_deps', 'has_overflow',
    'physical_state_in', 'physical_state_out',
    # Graphic-novel-mode columns (ignored in novel mode, written in GN mode)
    'page_layout', 'panel_breakdown', 'visual_keywords',
    'page_turn_beats', 'caption_strategy',
]
# Structural-anchor tier: discrete CSVs with their own row identity.
_SPINE_COLS = [
    'id', 'seq', 'title', 'summary', 'function', 'act',
]
_ARCHITECTURE_COLS = [
    'id', 'seq', 'title', 'summary', 'act', 'pov', 'spine_event',
    'action_sequel', 'emotional_arc', 'value_at_stake',
    'value_shift', 'turning_point',
]

# Order matters: `_file_for_column` returns the first file whose column
# list contains the lookup. The manuscript-tier files come first because
# they own shared column names (seq, title, act, etc.) in the legacy code
# path. Structural-anchor files (spine.csv, architecture.csv) follow; they
# share several column names with the manuscript files, so callers that
# need to disambiguate by tier should use a tier-aware helper rather than
# `_file_for_column` alone.
_FILE_MAP = {
    'scenes.csv': _SCENES_COLS,
    'scene-intent.csv': _INTENT_COLS,
    'scene-briefs.csv': _BRIEFS_COLS,
    'spine.csv': _SPINE_COLS,
    'architecture.csv': _ARCHITECTURE_COLS,
}


# ============================================================================
# CSV I/O
# ============================================================================

def _read_csv(path: str) -> list[dict[str, str]]:
    """Read a pipe-delimited CSV into a list of dicts.

    Coerces None values to '' so callers can safely call .strip() etc.
    (csv.DictReader stores None when rows have fewer fields than headers.)

    Strips ``\\r`` from all field values and header names so that CRLF line
    endings (and stray ``\\r`` characters embedded by awk-based CSV edits)
    never propagate into downstream code.
    """
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    reader = csv.DictReader(raw.splitlines(), delimiter=DELIMITER)
    rows = [{k: (v if v is not None else '') for k, v in row.items()}
            for row in reader]
    # spine.csv and architecture.csv renamed `part` to `act`. Their writers
    # emit only the current columns, so reading a pre-migration file without
    # this would drop the acts on the next rewrite.
    if os.path.basename(path) in _ACT_RENAMED_FILES:
        for row in rows:
            if 'part' in row and not row.get('act', '').strip():
                row['act'] = row.pop('part')
    return rows


_ACT_RENAMED_FILES = frozenset({'spine.csv', 'architecture.csv'})


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
            # csv defaults to '\r\n', which makes a one-cell edit a whole-file
            # diff and trips cleanup's own `crlf_line_endings` check. Every
            # other writer in the project emits LF.
            lineterminator='\n',
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
    """Update specific columns for a *manuscript-tier* scene.

    Writes to whichever of scenes.csv / scene-intent.csv / scene-briefs.csv
    own each column, based on `_file_for_column` (which returns the
    first matching file in `_FILE_MAP`).

    **Manuscript tier only.** This function does NOT update spine.csv or
    architecture.csv. Several columns are shared between the manuscript
    files and the structural-anchor files (id, seq, title, act, pov,
    action_sequel, emotional_arc, value_at_stake, value_shift,
    turning_point) — for those columns, `_file_for_column` returns the
    manuscript-tier file because `_FILE_MAP` puts those first. If a
    caller wanted to edit a row in spine.csv or architecture.csv via
    this function, the wrong file would silently get the write and an
    empty manuscript row could even be created. Use a tier-specific
    write path for structural-anchor edits (today, edit those CSVs
    directly; a tier-aware helper can be added if real callers emerge).

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
    'architecture': ['id', 'seq', 'title', 'act', 'pov', 'function',
                      'action_sequel', 'emotional_arc', 'value_at_stake',
                      'value_shift', 'turning_point'],
    'mapped': ['id', 'seq', 'title', 'act', 'pov', 'location',
               'timeline_day', 'time_of_day', 'function', 'action_sequel',
               'emotional_arc', 'value_at_stake', 'value_shift',
               'turning_point', 'characters', 'on_stage'],
    'briefed': ['id', 'seq', 'title', 'act', 'pov', 'location',
                'timeline_day', 'time_of_day', 'function', 'action_sequel',
                'emotional_arc', 'value_at_stake', 'value_shift',
                'turning_point', 'characters', 'on_stage',
                'goal', 'conflict', 'outcome'],
    'drafted': ['id', 'seq', 'title', 'act', 'pov', 'location',
                'timeline_day', 'time_of_day', 'function', 'action_sequel',
                'emotional_arc', 'value_at_stake', 'value_shift',
                'turning_point', 'characters', 'on_stage',
                'goal', 'conflict', 'outcome'],
    'polished': ['id', 'seq', 'title', 'act', 'pov', 'location',
                 'timeline_day', 'time_of_day', 'function', 'action_sequel',
                 'emotional_arc', 'value_at_stake', 'value_shift',
                 'turning_point', 'characters', 'on_stage',
                 'goal', 'conflict', 'outcome'],
}


def _check(category: str, check: str, passed: bool, message: str,
           severity: str = 'blocking', scene_id: str = '',
           fields=None) -> dict:
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
    if fields is not None:
        result['fields'] = fields
    return result


def _mice_type(thread_name, registry_types=None):
    """Extract the MICE type from a thread name, falling back to registry.

    Args:
        thread_name: e.g., 'inquiry:who-killed' or bare 'dex-secret'
        registry_types: optional dict of thread_id -> type from mice-threads.csv
    """
    if ':' in thread_name:
        return thread_name.split(':')[0]
    # Bare name — resolve from registry
    if registry_types and thread_name in registry_types:
        return registry_types[thread_name]
    return 'unknown'


def _validate_threads(scenes_map, intent_map, checks, ref_dir=''):
    """Report MICE thread data problems and how threads interleave.

    All findings are advisory. Kowal's nesting (same-type threads closing in
    reverse order) is guidance, not a rule: literary novels interleave
    threads deliberately, so interleaving is described, never an error.
    What is checked is the notation itself: each thread opens once ("+"),
    closes at most once ("-"), and is otherwise mentioned by bare name.
    """
    registry_types = {}
    if ref_dir:
        reg_path = os.path.join(ref_dir, 'mice-threads.csv')
        if os.path.isfile(reg_path):
            for row in _read_csv(reg_path):
                rid = row.get('id', '').strip()
                rtype = (row.get('type') or '').strip()
                if rid and rtype:
                    registry_types[rid] = rtype
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    opens = {}    # thread -> [scene ids with "+thread"]
    closes = {}   # thread -> [scene ids with "-thread"]
    open_now = {}  # mice type -> [(thread, scene opened)] in opening order
    interleaved = []
    for sid in sorted_ids:
        mice = intent_map.get(sid, {}).get('mice_threads', '').strip()
        for entry in (e.strip() for e in mice.split(';') if e.strip()):
            name = entry[1:]
            if entry.startswith('+'):
                opens.setdefault(name, []).append(sid)
                if len(opens[name]) == 1:
                    open_now.setdefault(_mice_type(name, registry_types), []).append((name, sid))
            elif entry.startswith('-'):
                closes.setdefault(name, []).append(sid)
                stack = open_now.get(_mice_type(name, registry_types), [])
                names = [t for t, _ in stack]
                if name in names:
                    later = names[names.index(name) + 1:]
                    if later:
                        interleaved.append(f"'{name}' closes in {sid} while "
                                           f"'{later[-1]}' (opened later) is still open")
                    stack[:] = [(t, s) for t, s in stack if t != name]

    for name, sids in opens.items():
        if len(sids) > 1:
            checks.append(_check(
                'threads', 'mice-ops', False,
                f"MICE thread '{name}' is opened in {len(sids)} scenes "
                f"({', '.join(sids[:4])}{'...' if len(sids) > 4 else ''}); "
                f"it should open once, with later scenes mentioning it by bare name",
                scene_id=sids[1], severity='advisory',
            ))
    for name, sids in closes.items():
        if len(sids) > 1:
            checks.append(_check(
                'threads', 'mice-ops', False,
                f"MICE thread '{name}' is closed in {len(sids)} scenes "
                f"({', '.join(sids[:4])}{'...' if len(sids) > 4 else ''}); "
                f"it should close once, where it resolves",
                scene_id=sids[1], severity='advisory',
            ))
        if name not in opens:
            checks.append(_check(
                'threads', 'mice-ops', False,
                f"MICE thread '{name}' is closed in {sids[0]} but never opened",
                scene_id=sids[0], severity='advisory',
            ))
    if not any(c['check'] == 'mice-ops' and not c['passed'] for c in checks):
        checks.append(_check('threads', 'mice-ops', True,
                             'MICE threads open once and close at most once'))

    if interleaved:
        checks.append(_check(
            'threads', 'mice-interleaving', False,
            f"{len(interleaved)} MICE thread closing(s) interleave rather than nest "
            f"(descriptive, not an error): " + '; '.join(interleaved[:5])
            + ('...' if len(interleaved) > 5 else ''),
            severity='advisory',
        ))

    unclosed = [f"{name} (opened in {sids[0]})" for name, sids in opens.items()
                if name not in closes]
    if unclosed:
        checks.append(_check(
            'threads', 'unclosed-mice-threads', False,
            f"Unclosed MICE threads: {unclosed}",
            severity='advisory',
        ))


def _validate_timeline(scenes_map, checks):
    """Describe how the reading order moves through story time.

    The story's present is the latest day reached so far in reading order.
    A scene set before it is a flashback (or a crosscut, when the POV
    changes). These are devices, not errors, so they are advisory and listed
    plainly; assess_flashbacks in structural.py gauges whether they work.

    A run of consecutive scenes set before the same present is one finding
    (F-122: a multi-plot novel's crosscuts gave one line per scene), the same
    passage assess_flashbacks reports: frame and vision scenes are skipped
    without ending it, and a scene with no day ends it. The finding names
    the run's first and last scene and its count, and lists every scene in
    ``scenes``, so grouping loses nothing.
    """
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    present_day = None
    present_id = None
    runs, current = [], None
    for sid in sorted_ids:
        # Frame narration and visions are never the story's present
        if (scenes_map[sid].get('time_mode') or '').strip() in OFF_PRESENT_MODES:
            continue
        day_str = scenes_map[sid].get('timeline_day', '').strip()
        try:
            day = int(day_str)
        except ValueError:
            current = None
            continue

        if present_day is not None and day < present_day:
            pov = scenes_map[sid].get('pov', '').strip()
            present_pov = scenes_map[present_id].get('pov', '').strip()
            kind = 'crosscut' if pov and present_pov and pov != present_pov else 'flashback'
            if current is None:
                current = {'present_day': present_day, 'present_id': present_id, 'scenes': []}
                runs.append(current)
            current['scenes'].append((sid, day, kind))
        else:
            current = None
            present_day, present_id = day, sid

    for run in runs:
        scenes = run['scenes']
        present = f"the story's present (day {run['present_day']}, reached in {run['present_id']})"
        first_id, first_day, first_kind = scenes[0]
        if len(scenes) == 1:
            message = (f"{first_kind.capitalize()}: {first_id} (day {first_day}) "
                       f"is set before {present}")
        else:
            last_id, last_day, _ = scenes[-1]
            crosscuts = sum(1 for _, _, kind in scenes if kind == 'crosscut')
            flashbacks = len(scenes) - crosscuts
            label = 'Crosscut' if crosscuts else 'Flashback'
            message = (f"{label}: {len(scenes)} scenes, {first_id} (day {first_day}) to "
                       f"{last_id} (day {last_day}), are set before {present}")
            earliest = min(day for _, day, _ in scenes)
            if earliest < min(first_day, last_day):
                message += f'; reaching back to day {earliest}'
            if crosscuts and flashbacks:
                message += f'; {crosscuts} crosscut, {flashbacks} flashback'
        check = _check('timeline', 'timeline-order', False, message,
                       scene_id=first_id, severity='advisory')
        check['scenes'] = [sid for sid, _, _ in scenes]
        checks.append(check)

    if not runs:
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


def present_in_scene(scene: dict, intent: dict) -> set[str]:
    """Lowercased ids of the characters present in a scene: its ``on_stage``
    (``characters`` when that is empty) plus its POV. Empty when the scene
    records neither, which means "unknown", not "nobody"."""
    raw = intent.get('on_stage', '') or intent.get('characters', '')
    present = {c.strip().lower() for c in raw.split(';') if c.strip()}
    pov = (scene.get('pov') or '').strip().lower()
    if pov:
        present.add(pov)
    return present


def state_owner_absent(state: dict, scenes_map: dict, intent_map: dict) -> bool:
    """True when a physical state's character is known not to be present in
    the scene that acquires it (governor d7e98f3: Elias's burns given to
    Tessa). Unknown presence is not absence."""
    character = (state.get('character') or '').strip().lower()
    acquired = (state.get('acquired') or '').strip()
    if not character or acquired not in scenes_map:
        return False
    present = present_in_scene(scenes_map[acquired], intent_map.get(acquired, {}))
    return bool(present) and character not in present


def _validate_physical_states(scenes_map, briefs_map, intent_map, checks, ref_dir: str = ''):
    """Check physical state flow: physical_state_in must come from prior scenes' physical_state_out."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    available_states = set()

    # Lazy-load the physical-states registry (needed for checks 2 and 3)
    registry = None  # dict: state_id -> registry row

    def _get_registry():
        nonlocal registry
        if registry is None:
            if ref_dir:
                registry_path = os.path.join(ref_dir, 'physical-states.csv')
                registry = _read_csv_as_map(registry_path)
            else:
                registry = {}
        return registry

    position = {s: i for i, s in enumerate(sorted_ids)}
    for sid in sorted_ids:
        brief = briefs_map.get(sid, {})
        state_in_raw = brief.get('physical_state_in', '').strip()
        state_out_raw = brief.get('physical_state_out', '').strip()

        states_in = {s.strip() for s in state_in_raw.split(';') if s.strip()} if state_in_raw else set()
        states_out = {s.strip() for s in state_out_raw.split(';') if s.strip()} if state_out_raw else set()

        # Check 1 — state availability
        if states_in:
            unknown = states_in - available_states
            if unknown:
                checks.append(_check(
                    'physical_state', 'state-availability', False,
                    f"Scene {sid} references physical states not established by prior scenes: "
                    f"{sorted(unknown)}",
                    scene_id=sid,
                    severity='advisory',
                ))

        # Check 2 — state disappearance (advisory)
        # A state that appears in state_in but not state_out silently vanishes,
        # unless the registry says it resolves in this scene. The registry
        # names one resolving scene, so a state that recurs (sleep, a coat)
        # ends again after it: once that scene has passed, a later ending is
        # a recurrence, not a vanishing (Carol: Scrooge asleep again after
        # Belle, awake "in the middle of a prodigiously tough snore", F-110)
        for state_id in states_in:
            if state_id not in states_out:
                reg = _get_registry()
                reg_row = reg.get(state_id, {})
                resolves_at = reg_row.get('resolves', '').strip()
                resolves_here = resolves_at == sid
                resolved_before = (resolves_at in position
                                   and position[resolves_at] < position[sid])
                if not (resolves_here or resolved_before):
                    checks.append(_check(
                        'physical_state', 'state-disappearance', False,
                        f"Scene {sid}: state '{state_id}' is in physical_state_in but not "
                        f"physical_state_out and registry does not list this scene as its resolution",
                        scene_id=sid,
                        severity='advisory',
                    ))

        # Accumulate available states from this scene's output
        available_states.update(states_out)

    # Check 3 — on-stage relevance (advisory)
    # If a character has an active action-gating state and is on-stage in a scene
    # but that state is not in physical_state_in, flag it.
    reg = _get_registry()
    if reg:
        # Build a map: character -> set of action-gating state IDs
        action_gating_by_char = {}
        for state_id, row in reg.items():
            if row.get('action_gating', '').strip().lower() == 'true':
                char = row.get('character', '').strip()
                if char:
                    action_gating_by_char.setdefault(char, set()).add(state_id)

        if action_gating_by_char:
            # Walk scenes again, tracking which action-gating states are currently active
            active_action_gating = set()  # set of state IDs currently active
            for sid in sorted_ids:
                brief = briefs_map.get(sid, {})
                state_in_raw = brief.get('physical_state_in', '').strip()
                state_out_raw = brief.get('physical_state_out', '').strip()

                states_in = {s.strip() for s in state_in_raw.split(';') if s.strip()} if state_in_raw else set()
                states_out = {s.strip() for s in state_out_raw.split(';') if s.strip()} if state_out_raw else set()

                intent_row = intent_map.get(sid, {})
                on_stage_raw = intent_row.get('on_stage', '').strip()
                on_stage = {c.strip() for c in on_stage_raw.split(';') if c.strip()} if on_stage_raw else set()

                for char, ag_states in action_gating_by_char.items():
                    active_for_char = ag_states & active_action_gating
                    if active_for_char and char in on_stage:
                        # Character is on stage with active action-gating states —
                        # at least one should appear in physical_state_in
                        missing_from_in = active_for_char - states_in
                        if missing_from_in:
                            checks.append(_check(
                                'physical_state', 'on-stage-relevance', False,
                                f"Scene {sid}: '{char}' is on-stage with active action-gating "
                                f"state(s) {sorted(missing_from_in)} not listed in physical_state_in",
                                scene_id=sid,
                                severity='advisory',
                            ))

                # Update active action-gating states from this scene's output
                active_action_gating.update(s for s in states_out if s in reg and
                                            reg[s].get('action_gating', '').strip().lower() == 'true')
                # Remove states that dropped out of state_out relative to state_in
                # (a state was in state_in but not state_out means it was resolved)
                for state_id in states_in - states_out:
                    active_action_gating.discard(state_id)
                # ... and so does a state the registry says resolves here, which
                # the briefs often drop without listing it in physical_state_in
                # (Pride and Prejudice: a Hunsford headache gated 69 scenes).
                active_action_gating -= {s for s in active_action_gating
                                         if reg.get(s, {}).get('resolves', '').strip() == sid}

    if not any(c['category'] == 'physical_state' and not c['passed'] for c in checks):
        checks.append(_check('physical_state', 'state-availability', True,
                             'Physical state flow is consistent'))


def _validate_pacing(scenes_map, intent_map, checks):
    """Check pacing: polarity stretches, scene type rhythm, turning point variety."""
    sorted_ids = sorted(scenes_map.keys(),
                        key=lambda sid: int(scenes_map[sid].get('seq', 0)))

    action_sequels = []
    value_shifts = []
    turning_points = []

    for sid in sorted_ids:
        intent = intent_map.get(sid, {})
        st = intent.get('action_sequel', '').strip()
        vs = intent.get('value_shift', '').strip()
        tp = intent.get('turning_point', '').strip()
        if st:
            action_sequels.append((sid, st))
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
    if len(action_sequels) >= type_threshold:
        for i in range(len(action_sequels) - type_threshold + 1):
            window = action_sequels[i:i + type_threshold]
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

    Each check has a `severity` field — ``'blocking'`` (default) or
    ``'advisory'``. Blocking failures indicate structural problems that
    must be fixed before drafting (orphaned rows, missing required
    columns, timeline contradictions, broken MICE nesting). Advisory
    failures are reported as FYI signals — for example, crosscut pacing
    on a single timeline_day — and do not gate the pipeline.

    Returns:
        A dict with:
          - ``'passed'`` (bool): ``True`` when no BLOCKING failures exist.
            Advisory failures are reported in ``'failures'`` but do NOT
            affect ``'passed'``.
          - ``'checks'`` (list): every check run, passed or failed.
          - ``'failures'`` (list): all failed checks (blocking AND
            advisory). Callers that need to distinguish should inspect
            each entry's ``'severity'`` field.
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

    # --- Identity: seq is unique ---
    # Two scenes sharing a seq have no defined reading order, and renumbering
    # would pick one silently (thornwall seq 58). The author decides the order.
    by_seq: dict[str, list[str]] = {}
    for sid, scene in scenes_map.items():
        seq = scene.get('seq', '').strip()
        if seq:
            by_seq.setdefault(seq, []).append(sid)
    dup_seqs = {seq: sids for seq, sids in by_seq.items() if len(sids) > 1}
    checks.append(_check(
        'identity', 'duplicate-seq',
        not dup_seqs,
        "Scenes share a seq (reading order is undefined): "
        + '; '.join(f"seq {seq}: {sorted(sids)}"
                    for seq, sids in sorted(dup_seqs.items()))
        if dup_seqs else "Every seq is unique",
    ))

    # --- Completeness: required columns for status ---
    # A pre-migration project has its acts in `part` and `act` empty: report
    # that once, rather than as a missing column on every scene.
    unmigrated = (scenes_map
                  and not any(s.get('act', '').strip() for s in scenes_map.values())
                  and any(s.get('part', '').strip() for s in scenes_map.values()))
    if unmigrated:
        checks.append(_check(
            'completeness', 'act-migration', False,
            "Acts are still in the part column (act is empty on every scene). "
            "Run `storyforge cleanup`, which moves them into act",
        ))
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

        missing = [col for col in required if not merged.get(col, '').strip()
                   and not (unmigrated and col == 'act')]
        checks.append(_check(
            'completeness', f'required-columns-{sid}',
            len(missing) == 0,
            f"Scene {sid} (status={status}) missing required columns: {missing}" if missing
            else f"Scene {sid} has all required columns for status={status}",
            scene_id=sid,
            fields=missing if missing else None,
        ))

    # --- Thread, timeline, knowledge, pacing ---
    _validate_threads(scenes_map, intent_map, checks, ref_dir=ref_dir)
    _validate_timeline(scenes_map, checks)
    _validate_knowledge(scenes_map, briefs_map, checks)
    _validate_pacing(scenes_map, intent_map, checks)
    _validate_physical_states(scenes_map, briefs_map, intent_map, checks, ref_dir=ref_dir)

    failures = [c for c in checks if not c['passed']]
    blocking_failures = [c for c in failures if c.get('severity', 'blocking') != 'advisory']
    return {
        'passed': len(blocking_failures) == 0,
        'checks': checks,
        'failures': failures,
    }


# Gap group definitions: which fields belong to which group
_GAP_GROUPS = {
    'scene-fields': {
        'fields': ['type', 'time_of_day', 'duration', 'act'],
        'file': 'scenes.csv',
        'batch_type': 'parallel',
    },
    'intent-fields': {
        'fields': ['action_sequel', 'emotional_arc', 'value_at_stake',
                   'value_shift', 'turning_point'],
        'file': 'scene-intent.csv',
        'batch_type': 'parallel',
    },
    'thread-fields': {
        'fields': ['mice_threads'],
        'file': 'scene-intent.csv',
        'batch_type': 'parallel',
    },
    'location-timeline': {
        'fields': ['location', 'timeline_day'],
        'file': 'scenes.csv',
        'batch_type': 'parallel',
    },
    'knowledge': {
        'fields': ['knowledge_in', 'knowledge_out', 'continuity_deps'],
        'file': 'scene-briefs.csv',
        'batch_type': 'sequential',
    },
}


def analyze_gaps(ref_dir: str) -> dict:
    """Analyze validation failures and categorize them into gap groups.

    Returns a dict with:
        - 'groups': dict of group_name -> {'fields': [...], 'scenes': {scene_id: [missing_fields]}, 'batch_type': str}
        - 'structural': list of non-completeness validation failures (MICE, timeline, knowledge-availability)
        - 'total_gaps': int count of all individual field gaps
        - 'validation': the full validation report
    """
    report = validate_structure(ref_dir)

    # Collect per-scene missing fields from completeness failures
    scene_missing: dict = {}
    for failure in report['failures']:
        if failure['category'] == 'completeness' and failure.get('scene_id'):
            sid = failure['scene_id']
            fields = failure.get('fields', [])
            if fields:
                scene_missing[sid] = fields

    # Categorize into gap groups
    groups: dict = {}
    total_gaps = 0

    for group_name, group_def in _GAP_GROUPS.items():
        group_fields = set(group_def['fields'])
        scenes_in_group: dict = {}

        for sid, missing in scene_missing.items():
            overlap = [f for f in missing if f in group_fields]
            if overlap:
                scenes_in_group[sid] = overlap
                total_gaps += len(overlap)

        if scenes_in_group:
            groups[group_name] = {
                'fields': group_def['fields'],
                'scenes': scenes_in_group,
                'batch_type': group_def['batch_type'],
                'count': sum(len(v) for v in scenes_in_group.values()),
            }

    # Collect structural failures (non-completeness)
    structural = [
        f for f in report['failures']
        if f['category'] in ('threads', 'timeline', 'knowledge')
        and f['severity'] == 'blocking'
    ]

    return {
        'groups': groups,
        'structural': structural,
        'total_gaps': total_gaps,
        'validation': report,
    }

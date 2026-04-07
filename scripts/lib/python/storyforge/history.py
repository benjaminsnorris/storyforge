"""Score history tracking across scoring cycles.

Maintains working/scores/score-history.csv with columns:
  cycle | scene_id | principle | score

Functions:
  append_cycle(scores_dir, cycle, project_dir) — append from scene-scores.csv
  get_scene_history(project_dir, scene_id, principle) — [(cycle, score), ...]
  detect_stalls(project_dir, principle, ...) — scenes stuck at low scores
  detect_regressions(project_dir, principle, ...) — scenes with score drops
"""

import csv
import os

DELIMITER = '|'
HISTORY_HEADER = ['cycle', 'scene_id', 'principle', 'score']
HISTORY_FILENAME = 'score-history.csv'


# ============================================================================
# Private helpers
# ============================================================================

def _history_path(project_dir: str) -> str:
    """Return path to working/scores/score-history.csv."""
    return os.path.join(project_dir, 'working', 'scores', HISTORY_FILENAME)


def _is_principle_column(col: str) -> bool:
    """Return True if column holds a score value.

    Excludes 'id' and columns ending in '_rationale'.
    """
    if col == 'id':
        return False
    if col.endswith('_rationale'):
        return False
    return True


def _read_history(project_dir: str) -> list[dict[str, str]]:
    """Read score-history.csv, return list of row dicts.

    Returns [] if the file does not exist.
    Coerces None → '' (csv.DictReader returns None for short rows).
    """
    path = _history_path(project_dir)
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=DELIMITER)
        return [{k: (v if v is not None else '') for k, v in row.items()}
                for row in reader]


# ============================================================================
# Public API
# ============================================================================

def append_cycle(scores_dir: str, cycle: int, project_dir: str) -> int:
    """Read scene-scores.csv from scores_dir and append rows to score-history.csv.

    Skips non-principle columns (id, *_rationale).
    Creates score-history.csv with header if it doesn't exist; appends if it does.

    Returns:
        Number of rows appended (scenes × principles).
    """
    scores_path = os.path.join(scores_dir, 'scene-scores.csv')
    if not os.path.exists(scores_path):
        return 0

    # Read the scene-scores CSV
    with open(scores_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=DELIMITER)
        score_rows = [{k: (v if v is not None else '') for k, v in row.items()}
                      for row in reader]

    if not score_rows:
        return 0

    # Determine principle columns from the header
    all_cols = list(score_rows[0].keys())
    principles = [c for c in all_cols if _is_principle_column(c)]

    # Build history rows
    new_rows: list[dict[str, str]] = []
    for scene_row in score_rows:
        scene_id = scene_row.get('id', '')
        for principle in principles:
            new_rows.append({
                'cycle': str(cycle),
                'scene_id': scene_id,
                'principle': principle,
                'score': scene_row.get(principle, ''),
            })

    if not new_rows:
        return 0

    # Ensure output directory exists
    history_path = _history_path(project_dir)
    os.makedirs(os.path.dirname(history_path), exist_ok=True)

    # Write (create with header) or append
    write_header = not os.path.exists(history_path)
    with open(history_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_HEADER, delimiter=DELIMITER)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)

    return len(new_rows)


def get_scene_history(
    project_dir: str,
    scene_id: str,
    principle: str,
) -> list[tuple[int, float]]:
    """Return (cycle, score) tuples for one scene+principle, sorted by cycle.

    Returns [] if no history file exists or no matching rows.
    """
    rows = _read_history(project_dir)
    matches = [
        r for r in rows
        if r.get('scene_id') == scene_id and r.get('principle') == principle
    ]
    result = []
    for r in matches:
        try:
            result.append((int(r['cycle']), float(r['score'])))
        except (ValueError, KeyError):
            pass
    return sorted(result, key=lambda x: x[0])


def detect_stalls(
    project_dir: str,
    principle: str,
    min_cycles: int = 2,
    max_score: float = 3.0,
) -> list[dict]:
    """Find scenes stuck at low scores for consecutive recent cycles.

    A stall is when the most-recent min_cycles scores are all <= max_score
    with no improvement (the last score is not higher than the first of the
    trailing window).

    Returns list of:
      {scene_id, scores: [(cycle, score), ...], cycles_stalled: int}
    """
    rows = _read_history(project_dir)
    if not rows:
        return []

    # Collect all scene IDs for this principle
    scene_ids = list(dict.fromkeys(
        r['scene_id'] for r in rows if r.get('principle') == principle
    ))

    stalls = []
    for scene_id in scene_ids:
        history = get_scene_history(project_dir, scene_id, principle)
        if len(history) < min_cycles:
            continue

        # Look at the most-recent min_cycles entries
        trailing = history[-min_cycles:]
        scores = [s for _, s in trailing]

        # All must be <= max_score (still stuck in the low-score zone)
        if any(s > max_score for s in scores):
            continue

        stalls.append({
            'scene_id': scene_id,
            'scores': trailing,
            'cycles_stalled': min_cycles,
        })

    return stalls


def detect_regressions(
    project_dir: str,
    principle: str,
    threshold: float = -0.5,
) -> list[dict]:
    """Find scenes where score dropped by >= |threshold| between consecutive cycles.

    Returns list of:
      {scene_id, from_cycle, to_cycle, from_score, to_score, delta}
    """
    rows = _read_history(project_dir)
    if not rows:
        return []

    # Collect all scene IDs for this principle
    scene_ids = list(dict.fromkeys(
        r['scene_id'] for r in rows if r.get('principle') == principle
    ))

    regressions = []
    for scene_id in scene_ids:
        history = get_scene_history(project_dir, scene_id, principle)
        if len(history) < 2:
            continue

        for i in range(len(history) - 1):
            cycle_a, score_a = history[i]
            cycle_b, score_b = history[i + 1]
            delta = score_b - score_a
            if delta <= threshold:
                regressions.append({
                    'scene_id': scene_id,
                    'from_cycle': cycle_a,
                    'to_cycle': cycle_b,
                    'from_score': score_a,
                    'to_score': score_b,
                    'delta': delta,
                })

    return regressions

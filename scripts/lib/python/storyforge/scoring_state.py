"""Author-state files for elaboration v1 (#229).

Two small parsers + writers for the per-author state that lives under
working/:

  - working/scoring-overrides.csv — per-finding "considered, accepted"
    markers with a one-line rationale. Scores still surface but the
    cascade / quality-gate logic ignores them for refusal purposes.

  - working/scoring-verdicts.csv — diff+verdict persistence for the
    upward-faithfulness comparisons at level boundaries. Records who
    decided (the LLM proposed it in `full` coaching, the author in
    `strict`) and whether the verdict was author-confirmed.

Also includes helpers for the drafting-mode bypass:

  - is_drafting_mode(project_dir) — true if STORYFORGE_DRAFTING=1 in
    the environment or `project.cascade_mode: drafting` (or `paused`)
    in storyforge.yaml.
"""

import csv
import os

from storyforge.common import detect_project_root, read_yaml_field


OVERRIDES_PATH = os.path.join('working', 'scoring-overrides.csv')
VERDICTS_PATH = os.path.join('working', 'scoring-verdicts.csv')

OVERRIDES_HEADER = ['scope', 'axis', 'finding_id', 'verdict', 'rationale', 'recorded_at']
VERDICTS_HEADER = ['scope', 'boundary', 'verdict', 'rationale', 'actor', 'recorded_at']

VALID_OVERRIDE_VERDICTS = frozenset({'accepted', 'rejected'})
VALID_BOUNDARY_VERDICTS = frozenset(
    {'correct=upstream', 'correct=downstream', 'both are right', 'needs work'}
)
VALID_ACTORS = frozenset({'llm', 'author'})


# ============================================================================
# scoring-overrides.csv
# ============================================================================

def read_overrides(project_dir: str | None = None) -> list[dict]:
    """Return the list of override entries. Empty list if file absent."""
    project_dir = project_dir or detect_project_root()
    path = os.path.join(project_dir, OVERRIDES_PATH)
    if not os.path.isfile(path):
        return []
    return _read_pipe_csv(path)


def append_override(scope: str, axis: str, finding_id: str, verdict: str,
                    rationale: str, recorded_at: str,
                    project_dir: str | None = None) -> None:
    """Append an override entry. Creates the file if absent."""
    if verdict not in VALID_OVERRIDE_VERDICTS:
        raise ValueError(
            f'verdict must be one of {sorted(VALID_OVERRIDE_VERDICTS)}; got {verdict!r}'
        )
    project_dir = project_dir or detect_project_root()
    path = os.path.join(project_dir, OVERRIDES_PATH)
    _append_pipe_csv(
        path, OVERRIDES_HEADER,
        {'scope': scope, 'axis': axis, 'finding_id': finding_id,
         'verdict': verdict, 'rationale': rationale,
         'recorded_at': recorded_at},
    )


def is_override_accepted(scope: str, axis: str, finding_id: str,
                         project_dir: str | None = None) -> bool:
    """Return True if there's an `accepted` override for this finding."""
    for entry in read_overrides(project_dir):
        if (entry.get('scope') == scope
                and entry.get('axis') == axis
                and entry.get('finding_id') == finding_id
                and entry.get('verdict') == 'accepted'):
            return True
    return False


# ============================================================================
# scoring-verdicts.csv
# ============================================================================

def read_verdicts(project_dir: str | None = None) -> list[dict]:
    """Return the list of recorded verdicts. Empty list if file absent."""
    project_dir = project_dir or detect_project_root()
    path = os.path.join(project_dir, VERDICTS_PATH)
    if not os.path.isfile(path):
        return []
    return _read_pipe_csv(path)


def append_verdict(scope: str, boundary: str, verdict: str, rationale: str,
                   actor: str, recorded_at: str,
                   project_dir: str | None = None) -> None:
    """Append a verdict entry for a boundary diff. Creates file if absent."""
    if verdict not in VALID_BOUNDARY_VERDICTS:
        raise ValueError(
            f'verdict must be one of {sorted(VALID_BOUNDARY_VERDICTS)}; '
            f'got {verdict!r}'
        )
    if actor not in VALID_ACTORS:
        raise ValueError(
            f'actor must be one of {sorted(VALID_ACTORS)}; got {actor!r}'
        )
    project_dir = project_dir or detect_project_root()
    path = os.path.join(project_dir, VERDICTS_PATH)
    _append_pipe_csv(
        path, VERDICTS_HEADER,
        {'scope': scope, 'boundary': boundary, 'verdict': verdict,
         'rationale': rationale, 'actor': actor,
         'recorded_at': recorded_at},
    )


def get_verdict(scope: str, boundary: str,
                project_dir: str | None = None) -> dict | None:
    """Return the most-recent verdict for a (scope, boundary) pair, or None."""
    matches = [
        e for e in read_verdicts(project_dir)
        if e.get('scope') == scope and e.get('boundary') == boundary
    ]
    if not matches:
        return None
    # The file is append-only; the last matching row is the freshest.
    return matches[-1]


# ============================================================================
# Drafting-mode bypass
# ============================================================================

def is_drafting_mode(project_dir: str | None = None) -> bool:
    """True when cascade-blocking checks should be suspended.

    Two sources, in priority order:
      1. STORYFORGE_DRAFTING=1 environment variable (one-off bypass).
      2. project.cascade_mode in storyforge.yaml — values `drafting` or
         `paused` both suppress; `live` (default) does not.
    """
    if os.environ.get('STORYFORGE_DRAFTING') == '1':
        return True
    mode = (read_yaml_field('project.cascade_mode', project_dir)
            or 'live').strip().lower()
    return mode in ('drafting', 'paused')


# ============================================================================
# Internal: pipe-CSV I/O
# ============================================================================

def _read_pipe_csv(path: str) -> list[dict]:
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='|')
        return [dict(row) for row in reader]


def _append_pipe_csv(path: str, header: list[str], row: dict) -> None:
    needs_header = not os.path.isfile(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header, delimiter='|')
        if needs_header:
            writer.writeheader()
        writer.writerow(row)

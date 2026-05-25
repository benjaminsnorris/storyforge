"""Author-state files for elaboration v1 (#229).

Two small parsers + writers for the per-author state that lives under
working/:

  - working/scoring-overrides.csv — per-finding "considered, accepted"
    markers with a one-line rationale. Scores still surface but the
    cascade / quality-gate logic ignores them for refusal purposes.

  - working/scoring-verdicts.csv — diff+verdict persistence for the
    upward-faithfulness comparisons at level boundaries. Records the
    verdict (one of VALID_BOUNDARY_VERDICTS), who recorded it (`llm`
    or `author`), and the coaching level in effect at the time of
    record (`full` — LLM proposed, author can override; `coach` — LLM
    proposed, author confirmed; `strict` — author authored).

Also includes helpers for the drafting-mode bypass:

  - is_drafting_mode(project_dir) — true if STORYFORGE_DRAFTING=1 in
    the environment or `project.cascade_mode: drafting` (or `paused`)
    in storyforge.yaml.

CSV format notes:
  These files use the project's standard pipe-delimited convention —
  manual split('|') / join('|'), NOT csv.DictReader/DictWriter (which
  RFC-4180-quotes fields containing the delimiter, breaking downstream
  consumers that do raw splits). Per CLAUDE.md, "pipes don't appear in
  natural prose"; the rationale field is the only free-text input and
  pipes in rationales are silently sanitized to '/' on write (with a
  log line so the author can see the substitution if they care).
"""

import os

from storyforge.common import detect_project_root, log, read_yaml_field


OVERRIDES_PATH = os.path.join('working', 'scoring-overrides.csv')
VERDICTS_PATH = os.path.join('working', 'scoring-verdicts.csv')

OVERRIDES_HEADER = ['scope', 'axis', 'finding_id', 'verdict', 'rationale', 'recorded_at']
VERDICTS_HEADER = ['scope', 'boundary', 'verdict', 'rationale',
                   'actor', 'coaching_level', 'recorded_at']

VALID_OVERRIDE_VERDICTS = frozenset({'accepted', 'rejected'})
VALID_BOUNDARY_VERDICTS = frozenset(
    {'correct=upstream', 'correct=downstream', 'both are right', 'needs work'}
)
VALID_ACTORS = frozenset({'llm', 'author'})
VALID_COACHING_LEVELS = frozenset({'full', 'coach', 'strict'})
VALID_CASCADE_MODES = frozenset({'live', 'drafting', 'paused'})


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
                   actor: str, coaching_level: str, recorded_at: str,
                   project_dir: str | None = None) -> None:
    """Append a verdict entry for a boundary diff. Creates file if absent.

    coaching_level records the context in effect when the verdict was
    recorded (full / coach / strict). Combined with `actor`, this captures
    both who decided and how much the LLM contributed — useful for the
    audit story (e.g., "the LLM auto-recorded this in full mode; was it
    reviewed?").
    """
    if verdict not in VALID_BOUNDARY_VERDICTS:
        raise ValueError(
            f'verdict must be one of {sorted(VALID_BOUNDARY_VERDICTS)}; '
            f'got {verdict!r}'
        )
    if actor not in VALID_ACTORS:
        raise ValueError(
            f'actor must be one of {sorted(VALID_ACTORS)}; got {actor!r}'
        )
    if coaching_level not in VALID_COACHING_LEVELS:
        raise ValueError(
            f'coaching_level must be one of {sorted(VALID_COACHING_LEVELS)}; '
            f'got {coaching_level!r}'
        )
    project_dir = project_dir or detect_project_root()
    path = os.path.join(project_dir, VERDICTS_PATH)
    _append_pipe_csv(
        path, VERDICTS_HEADER,
        {'scope': scope, 'boundary': boundary, 'verdict': verdict,
         'rationale': rationale, 'actor': actor,
         'coaching_level': coaching_level,
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

    Unknown cascade_mode values log a WARNING and fall through to live —
    a silent fall-through would mean a typo'd `drating` value masks the
    author's intent.
    """
    if os.environ.get('STORYFORGE_DRAFTING') == '1':
        return True
    raw = (read_yaml_field('project.cascade_mode', project_dir) or '').strip().lower()
    if raw and raw not in VALID_CASCADE_MODES:
        log(f'WARNING: project.cascade_mode is {raw!r}; expected one of '
            f'{sorted(VALID_CASCADE_MODES)}. Treating as `live`.')
        return False
    mode = raw or 'live'
    return mode in ('drafting', 'paused')


# ============================================================================
# Internal: pipe-CSV I/O
# ============================================================================
#
# These helpers use the project's standard pipe-delimited convention —
# manual split('|') / join('|'). Per CLAUDE.md, "pipes don't appear in
# natural prose"; the rationale field is the only free-text input here
# and pipes in rationales get sanitized to '/' on write (with a log
# line). Using csv.DictReader/Writer would RFC-4180-quote rationale
# fields containing the delimiter, breaking downstream consumers that
# do raw splits.

def _sanitize_field(value: str) -> str:
    """Replace any pipe in `value` with '/' so the field doesn't break
    the project's split-on-pipe convention. Logs once when substitution
    happens so the author can see what changed."""
    if '|' in value:
        log(f'INFO: replaced pipe character(s) in rationale: {value!r}')
        return value.replace('|', '/')
    return value


def _read_pipe_csv(path: str) -> list[dict]:
    """Read a pipe-delimited CSV the project way: split on '|', no quoting.

    Strips \\r so CRLF line endings don't bleed into field values. Rows
    whose column count doesn't match the header are logged at WARNING
    and skipped — a single corrupted row no longer silently disables
    every override downstream.
    """
    try:
        with open(path, encoding='utf-8') as f:
            raw = f.read().replace('\r\n', '\n').replace('\r', '')
    except UnicodeDecodeError as e:
        log(f'WARNING: could not read {path} as utf-8 ({e}); treating as empty')
        return []
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0].split('|')
    rows = []
    for i, line in enumerate(lines[1:], start=2):
        fields = line.split('|')
        if len(fields) != len(header):
            log(f'WARNING: {path}:{i} has {len(fields)} columns, expected '
                f'{len(header)}; skipping row')
            continue
        rows.append(dict(zip(header, fields)))
    return rows


def _append_pipe_csv(path: str, header: list[str], row: dict) -> None:
    """Append one row, manual join, sanitizing pipes in the rationale field
    only (other fields are constrained to known sets and won't contain
    pipes)."""
    needs_header = not os.path.isfile(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sanitized = dict(row)
    if 'rationale' in sanitized:
        sanitized['rationale'] = _sanitize_field(sanitized['rationale'])
    with open(path, 'a', encoding='utf-8') as f:
        if needs_header:
            f.write('|'.join(header) + '\n')
        f.write('|'.join(sanitized.get(c, '') for c in header) + '\n')

"""Cross-tier coverage checks — every upstream row has ≥ 1 downstream row.

Where `scoring_consistency` checks that downstream references resolve
upward (orphan detection), this module checks that every upstream row
has at least one downstream row pointing back at it. Together they
catch fragmentation between layers of the expanding outline.

Coverage runs at the *upstream* level (the one being checked for
fan-out):

  - level 2 (act-shape) — every Act has ≥ 1 spine event in that part
  - level 3 (spine)     — every spine event has ≥ 1 architecture anchor
  - level 4 (architecture) — every anchor has ≥ 1 mapped scene

Higher-numbered levels don't have a downstream tier yet within the
elaboration pipeline (briefs ARE the downstream of architecture/scenes;
drafts ARE the downstream of briefs — both are covered by the boundary
diffs at 5->6 and 6->7).
"""

import os
import re

from storyforge.common import log, parse_story_summary
from storyforge.scoring_state import is_override_accepted


_COVERAGE_LEVELS = (2, 3, 4)


def _read_csv(path: str) -> list[dict]:
    """Read a pipe-delimited CSV into a list of dicts. Returns [] if absent."""
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return []
    headers = lines[0].split('|')
    rows: list[dict] = []
    for line in lines[1:]:
        cells = line.split('|')
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def _check(check: str, passed: bool, detail: str = '',
           severity: str = 'medium') -> dict:
    return {
        'check': check, 'passed': passed, 'detail': detail,
        'severity': severity,
    }


def _result(level: int, checks: list[dict]) -> dict:
    passed = sum(1 for c in checks if c['passed'])
    failed = sum(1 for c in checks if not c['passed'])
    accepted = sum(1 for c in checks if c.get('accepted'))
    return {
        'level': level, 'name': 'coverage',
        'checks': checks, 'passed': passed,
        'failed': failed, 'accepted': accepted,
    }


def score_coverage_at_level(project_dir: str, level: int) -> dict:
    """Run cross-tier coverage checks for the given upstream level.

    Returns a result dict matching the shape used by scoring_levels and
    scoring_consistency (same _print_level_result renderer). When the
    level's upstream file is absent, returns a single low-severity skip
    so the report makes the gap visible without spamming.
    """
    if level not in _COVERAGE_LEVELS:
        return _result(level, [_check(
            f'no coverage checks at level {level}', True, '',
        )])

    if level == 2:
        checks = _coverage_acts_to_spine(project_dir)
    elif level == 3:
        checks = _coverage_spine_to_architecture(project_dir)
    elif level == 4:
        checks = _coverage_architecture_to_scenes(project_dir)
    else:
        checks = []

    # Author overrides — same scope/axis convention as consistency.
    scope = f'level-{level}'
    for c in checks:
        if not c['passed']:
            if is_override_accepted(
                scope=scope, axis='coverage',
                finding_id=c['check'], project_dir=project_dir,
            ):
                c['accepted'] = True

    return _result(level, checks)


def score_coverage_all_levels(project_dir: str) -> list[dict]:
    """Run coverage at every level that has a downstream tier."""
    return [score_coverage_at_level(project_dir, level)
            for level in _COVERAGE_LEVELS]


# ---------------------------------------------------------------------------
# Per-boundary coverage helpers
# ---------------------------------------------------------------------------

def _coverage_acts_to_spine(project_dir: str) -> list[dict]:
    """Every Act named in story-summary.md's act-shape has ≥ 1 spine event
    whose `part` matches that act number."""
    summary = parse_story_summary(project_dir) or {}
    act_shape = summary.get('act_shape', '')
    if not act_shape.strip():
        return [_check(
            'act-shape present (required to check act coverage)',
            False,
            'reference/story-summary.md § Act-shape is empty',
            severity='high',
        )]
    act_numbers = _act_numbers_in(act_shape)
    if not act_numbers:
        return [_check(
            'act-shape declares Act sub-sections',
            False,
            'no `### Act N` sub-sections found in story-summary.md',
            severity='high',
        )]

    spine_rows = _read_csv(os.path.join(project_dir, 'reference', 'spine.csv'))
    if not spine_rows:
        return [_check(
            'spine.csv has rows (required to check Act → spine coverage)',
            False,
            'reference/spine.csv has no rows yet — run elaborate at the '
            'spine stage', severity='high',
        )]

    spine_parts: dict[str, int] = {}
    for row in spine_rows:
        part = row.get('part', '').strip()
        if part:
            spine_parts[part] = spine_parts.get(part, 0) + 1

    checks: list[dict] = []
    for n in sorted(act_numbers):
        n_str = str(n)
        count = spine_parts.get(n_str, 0)
        checks.append(_check(
            f'Act {n} has ≥ 1 spine event',
            count >= 1,
            (f'no spine.csv rows have part={n_str}'
             if count == 0 else ''),
            severity='medium',
        ))
    return checks


def _coverage_spine_to_architecture(project_dir: str) -> list[dict]:
    """Every spine event has ≥ 1 architecture anchor referencing it."""
    spine_rows = _read_csv(os.path.join(project_dir, 'reference', 'spine.csv'))
    if not spine_rows:
        return [_check(
            'spine.csv has rows', False,
            'reference/spine.csv is missing or empty',
            severity='high',
        )]
    arch_rows = _read_csv(os.path.join(project_dir, 'reference', 'architecture.csv'))
    if not arch_rows:
        return [_check(
            'architecture.csv has rows', False,
            'reference/architecture.csv is missing or empty — run elaborate '
            'at the architecture stage', severity='high',
        )]

    referenced = {r.get('spine_event', '').strip() for r in arch_rows}
    missing = [r.get('id', '') for r in spine_rows
               if r.get('id', '') and r.get('id', '') not in referenced]
    return [_check(
        'every spine event has an architecture anchor',
        not missing,
        (f'{len(missing)} spine event(s) without architecture anchors: '
         + ', '.join(missing[:5])
         + ('…' if len(missing) > 5 else ''))
        if missing else '',
        severity='medium',
    )]


def _coverage_architecture_to_scenes(project_dir: str) -> list[dict]:
    """Every architecture anchor has ≥ 1 mapped scene referencing it via
    architecture_scene."""
    arch_rows = _read_csv(os.path.join(project_dir, 'reference', 'architecture.csv'))
    if not arch_rows:
        return [_check(
            'architecture.csv has rows', False,
            'reference/architecture.csv is missing or empty',
            severity='high',
        )]
    scene_rows = _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))
    map_rows = [r for r in scene_rows
                if r.get('status', '').strip()
                in ('mapped', 'briefed', 'drafted', 'polished')]
    if not map_rows:
        return [_check(
            'scenes.csv has mapped rows', False,
            'reference/scenes.csv has no rows at status mapped/briefed/'
            'drafted/polished — run elaborate at the scene-map stage',
            severity='high',
        )]

    referenced = {r.get('architecture_scene', '').strip() for r in map_rows}
    missing = [r.get('id', '') for r in arch_rows
               if r.get('id', '') and r.get('id', '') not in referenced]
    return [_check(
        'every architecture anchor has a mapped scene',
        not missing,
        (f'{len(missing)} anchor(s) without mapped scenes: '
         + ', '.join(missing[:5])
         + ('…' if len(missing) > 5 else ''))
        if missing else '',
        severity='medium',
    )]


_ACT_HEADER = re.compile(r'^###\s+Act\s+(\d+)', re.MULTILINE)


def _act_numbers_in(act_shape: str) -> list[int]:
    """Extract the Act numbers declared in story-summary.md's act-shape."""
    return [int(m) for m in _ACT_HEADER.findall(act_shape)]

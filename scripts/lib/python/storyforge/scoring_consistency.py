"""Cross-cutting registry consistency checks (#229).

Generalizes the registry-orphan check from `hone.py` so it runs across
every structural level (3–6, plus the manuscript-tier scenes), not just
at brief stage. Builds on `schema.validate_schema` which already does
the heavy lifting; this module exposes the results per level so they
flow into the level-rubric reports.

Findings shape (per the level-rubric contract in scoring_levels):

    {
        'level': int,
        'name': 'registry-consistency',
        'checks': [
            {'check': 'no orphans in <file>.<column>', 'passed': bool,
             'detail': str, 'severity': 'medium'},
            ...
        ],
        'passed': int,
        'failed': int,
    }
"""

import os

from storyforge.schema import validate_schema


# Map each level → the CSV files whose registry references apply at that level.
# Files appear at the earliest level where their columns become populated.
LEVEL_FILES = {
    3: ['spine.csv'],
    4: ['architecture.csv'],
    5: ['scenes.csv', 'scene-intent.csv'],
    6: ['scene-briefs.csv'],
}


def _result(level: int, checks: list[dict]) -> dict:
    passed = sum(1 for c in checks if c['passed'])
    failed = sum(1 for c in checks if not c['passed'])
    accepted = sum(1 for c in checks if c.get('accepted') and not c['passed'])
    return {
        'level': level,
        'name': 'registry-consistency',
        'checks': checks,
        'passed': passed,
        'failed': failed,
        'accepted': accepted,
    }


def _check(check: str, passed: bool, detail: str = '', severity: str = 'medium') -> dict:
    return {'check': check, 'passed': passed, 'detail': detail, 'severity': severity}


def score_consistency_at_level(project_dir: str, level: int) -> dict:
    """Return registry-conformance findings scoped to one level's files.

    Reuses the cross-file `validate_schema` pass (which already enumerates
    all registry orphans) and filters its findings down to the files that
    apply to this level.
    """
    if level not in LEVEL_FILES:
        return _result(level, [_check(
            f'no registry checks at level {level}',
            True,
            '',
        )])

    ref_dir = os.path.join(project_dir, 'reference')
    report = validate_schema(ref_dir, project_dir)

    # Collect orphans grouped by (file, column)
    level_files = set(LEVEL_FILES[level])
    by_target: dict[tuple[str, str], list[dict]] = {}
    for err in report.get('errors', []):
        if err.get('constraint') != 'registry':
            continue
        fname = err.get('file', '')
        if fname not in level_files:
            continue
        key = (fname, err.get('column', ''))
        by_target.setdefault(key, []).append(err)

    checks: list[dict] = []
    if not by_target:
        # Nothing failed; emit one synthetic "passed" check.
        checks.append(_check(
            'all registry references resolve',
            True,
            '',
        ))
    else:
        for (fname, col), errs in sorted(by_target.items()):
            unresolved = sorted({u for e in errs for u in e.get('unresolved', [])})
            detail = (
                f'{len(errs)} row(s) in {fname} reference unknown '
                f'{errs[0].get("registry", "?")} entries: '
                + ', '.join(unresolved[:5])
                + ('…' if len(unresolved) > 5 else '')
            )
            checks.append(_check(
                f'no orphans in {fname}.{col}',
                False,
                detail,
                severity='medium',
            ))

    # Apply author overrides — same scope/axis convention as scoring_levels
    # but with axis='registry-consistency' so overrides target the right
    # finding family. Failed checks get tagged `accepted=True` when the
    # author has recorded an override.
    from storyforge.scoring_state import is_override_accepted
    scope = f'level-{level}'
    for c in checks:
        if not c['passed']:
            if is_override_accepted(
                scope=scope, axis='registry-consistency',
                finding_id=c['check'], project_dir=project_dir,
            ):
                c['accepted'] = True

    return _result(level, checks)


def score_consistency_all_levels(project_dir: str) -> list[dict]:
    """Run consistency checks at every structural level (3–6)."""
    return [score_consistency_at_level(project_dir, level)
            for level in sorted(LEVEL_FILES)]

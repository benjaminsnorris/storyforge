"""Per-level floor checks for the elaboration hierarchy.

Floor checks ask "is this level complete and consistent?" — they're
deterministic, cheap, and produce specific actionable findings.
Reuses existing scoring (structural.py, hone.py) at level 6 + 7 rather
than re-implementing.

Each scorer returns:
    {
        'level': int,
        'name': str,
        'checks': [
            {'check': str, 'passed': bool, 'detail': str | None, 'severity': str},
            ...
        ],
        'passed': int,
        'failed': int,
    }
"""

import os
import re
from typing import TypedDict

from storyforge.elaborate import _read_csv


# ============================================================================
# Types
# ============================================================================

# Severity is part of the cascade contract — a finding's severity controls
# whether the cascade or quality-gate logic treats it as blocking. Validated
# at construction so a typo can't silently degrade behavior.
VALID_SEVERITIES = frozenset({'high', 'medium', 'low'})


class CheckResult(TypedDict, total=False):
    """One floor-check finding. Contract for every entry in LevelResult.checks."""
    check: str         # required — the check name (stable, used as finding_id)
    passed: bool       # required — did the check evaluation pass
    detail: str        # required — explanation surfaced to the author
    severity: str      # required — one of VALID_SEVERITIES
    accepted: bool     # optional, default False — author override applied


class LevelResult(TypedDict):
    """The result dict every per-level scorer returns.

    Invariants: passed + failed == len(checks); accepted ≤ failed
    (passed checks are never marked accepted).
    """
    level: int
    name: str
    checks: list[CheckResult]
    passed: int
    failed: int
    accepted: int


# ============================================================================
# Helpers
# ============================================================================

def _result(level: int, name: str, checks: list[CheckResult]) -> LevelResult:
    passed = sum(1 for c in checks if c['passed'])
    failed = sum(1 for c in checks if not c['passed'])
    accepted = sum(1 for c in checks if c.get('accepted') and not c['passed'])
    return {
        'level': level,
        'name': name,
        'checks': checks,
        'passed': passed,
        'failed': failed,
        'accepted': accepted,
    }


def _apply_overrides(project_dir: str, result: LevelResult) -> LevelResult:
    """Tag each failed check whose author-override is `accepted` and
    recompute the result's `accepted` count.

    Override scope = `level-N`, axis = `level-quality`, finding_id = the
    check string itself (it's human-readable and stable across runs).
    """
    from storyforge.scoring_state import is_override_accepted
    scope = f'level-{result["level"]}'
    new_checks: list[CheckResult] = []
    for c in result['checks']:
        c_out: CheckResult = dict(c)  # type: ignore[assignment]
        c_out.setdefault('accepted', False)
        if not c['passed']:
            if is_override_accepted(
                scope=scope, axis='level-quality',
                finding_id=c['check'], project_dir=project_dir,
            ):
                c_out['accepted'] = True
        new_checks.append(c_out)
    accepted = sum(1 for c in new_checks if c.get('accepted') and not c['passed'])
    return {**result, 'checks': new_checks, 'accepted': accepted}


def _check(check: str, passed: bool, detail: str = '',
           severity: str = 'medium') -> CheckResult:
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f'severity must be one of {sorted(VALID_SEVERITIES)}; got {severity!r}'
        )
    return {'check': check, 'passed': passed, 'detail': detail, 'severity': severity}


def _read_story_summary_section(project_dir: str, section: str) -> str:
    """Return the body of a single story-summary.md section, or ''."""
    from storyforge.common import parse_story_summary
    parsed = parse_story_summary(project_dir)
    if parsed is None:
        return ''
    return parsed.get(section, '')


def _count_sentences(text: str) -> int:
    """Crude sentence count. Good enough for length floor checks."""
    if not text.strip():
        return 0
    # Split on sentence terminators followed by whitespace or end of string.
    # Avoids splitting on common abbreviations by requiring a capital or end.
    parts = re.split(r'[.!?]+(?:\s+|$)', text.strip())
    return sum(1 for p in parts if p.strip())


def _count_words(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


# ============================================================================
# Level 0 — Logline
# ============================================================================

def score_logline(project_dir: str) -> dict:
    text = _read_story_summary_section(project_dir, 'logline').strip()
    checks: list[dict] = []

    checks.append(_check(
        'present',
        bool(text),
        '' if text else 'reference/story-summary.md § Logline is empty',
        severity='high',
    ))

    word_count = _count_words(text)
    checks.append(_check(
        'length ≤ 35 words',
        word_count <= 35 if text else True,
        f'logline has {word_count} words; aim for ≤ 35' if word_count > 35 else '',
        severity='medium',
    ))

    return _result(0, 'logline', checks)


# ============================================================================
# Level 1 — Synopsis
# ============================================================================

def score_synopsis(project_dir: str) -> dict:
    text = _read_story_summary_section(project_dir, 'synopsis').strip()
    checks: list[dict] = []

    checks.append(_check(
        'present',
        bool(text),
        '' if text else 'reference/story-summary.md § Synopsis is empty',
        severity='high',
    ))

    sentence_count = _count_sentences(text)
    in_range = 4 <= sentence_count <= 8
    checks.append(_check(
        'length 4–8 sentences',
        in_range if text else True,
        (f'synopsis has {sentence_count} sentences; aim for 4–8'
         if text and not in_range else ''),
        severity='medium',
    ))

    return _result(1, 'synopsis', checks)


# ============================================================================
# Level 2 — Act-shape
# ============================================================================

def score_act_shape(project_dir: str) -> dict:
    text = _read_story_summary_section(project_dir, 'act_shape').strip()
    checks: list[dict] = []

    checks.append(_check(
        'present',
        bool(text),
        '' if text else 'reference/story-summary.md § Act-shape is empty',
        severity='high',
    ))

    # The template uses `### Act 1 / Act 2 / Act 3` sub-sections.
    act_headers = re.findall(r'^###\s+Act\s+\d+', text, flags=re.MULTILINE)
    has_three_acts = len(act_headers) == 3
    checks.append(_check(
        'exactly 3 acts',
        has_three_acts if text else True,
        (f'expected 3 `### Act N` sub-sections, found {len(act_headers)}'
         if text and not has_three_acts else ''),
        severity='medium',
    ))

    return _result(2, 'act-shape', checks)


# ============================================================================
# Level 3 — Spine
# ============================================================================

def score_spine(project_dir: str, medium: str = 'novel') -> dict:
    spine_path = os.path.join(project_dir, 'reference', 'spine.csv')
    checks: list[dict] = []

    if not os.path.isfile(spine_path):
        checks.append(_check(
            'spine.csv exists',
            False,
            'reference/spine.csv is missing — run elaborate at the spine stage',
            severity='high',
        ))
        return _result(3, 'spine', checks)

    rows = _read_csv(spine_path)
    n = len(rows)

    if medium == 'graphic-novel':
        ok_count = 4 <= n <= 8
        range_str = '4–8 (graphic novel)'
    else:
        ok_count = 5 <= n <= 10
        range_str = '5–10 (novel)'

    checks.append(_check(
        f'row count in {range_str}',
        ok_count,
        f'spine.csv has {n} rows; expected {range_str}' if not ok_count else '',
        severity='medium',
    ))

    # Every row needs a non-empty function (what the event does for the story).
    missing_function = [r.get('id', '?') for r in rows if not r.get('function', '').strip()]
    checks.append(_check(
        'function non-empty for every event',
        not missing_function,
        (f'{len(missing_function)} event(s) missing function: '
         + ', '.join(missing_function[:5])
         + ('…' if len(missing_function) > 5 else ''))
        if missing_function else '',
        severity='medium',
    ))

    return _result(3, 'spine', checks)


# ============================================================================
# Level 4 — Architecture
# ============================================================================

def score_architecture(project_dir: str, medium: str = 'novel') -> dict:
    arch_path = os.path.join(project_dir, 'reference', 'architecture.csv')
    spine_path = os.path.join(project_dir, 'reference', 'spine.csv')
    checks: list[dict] = []

    if not os.path.isfile(arch_path):
        checks.append(_check(
            'architecture.csv exists',
            False,
            'reference/architecture.csv is missing — run elaborate at the architecture stage',
            severity='high',
        ))
        return _result(4, 'architecture', checks)

    rows = _read_csv(arch_path)
    n = len(rows)

    if medium == 'graphic-novel':
        ok_count = 10 <= n <= 18
        range_str = '10–18 (graphic novel)'
    else:
        ok_count = 15 <= n <= 25
        range_str = '15–25 (novel)'

    checks.append(_check(
        f'row count in {range_str}',
        ok_count,
        f'architecture.csv has {n} rows; expected {range_str}' if not ok_count else '',
        severity='medium',
    ))

    # Required columns populated per row.
    required = ['part', 'pov', 'action_sequel', 'emotional_arc',
                'value_at_stake', 'value_shift', 'turning_point']
    missing_any = []
    for r in rows:
        empty = [c for c in required if not r.get(c, '').strip()]
        if empty:
            missing_any.append((r.get('id', '?'), empty))
    checks.append(_check(
        'all required columns populated',
        not missing_any,
        (f'{len(missing_any)} row(s) missing required columns; '
         f'first: {missing_any[0][0]} missing {", ".join(missing_any[0][1])}'
         if missing_any else ''),
        severity='medium',
    ))

    # spine_event must reference a real spine.csv id. When spine.csv is
    # absent AND any architecture row has a spine_event value, the
    # cross-reference check can't run — emit an explicit failed check so
    # the author sees the gap rather than thinking architecture is clean.
    # If spine.csv is absent and NO row has spine_event populated, skip
    # the spine-reference check entirely; everything else still runs.
    if not os.path.isfile(spine_path):
        non_empty_spine_refs = [r.get('id', '?') for r in rows
                                if r.get('spine_event', '').strip()]
        if non_empty_spine_refs:
            checks.append(_check(
                'spine_event references resolve to spine.csv',
                False,
                (f'spine.csv is missing; {len(non_empty_spine_refs)} architecture '
                 f'row(s) have spine_event values that cannot be validated. '
                 'Run step 7 of migrate or `storyforge elaborate spine` to populate.'),
                severity='medium',
            ))
    if os.path.isfile(spine_path):
        spine_ids = {r.get('id', '').strip() for r in _read_csv(spine_path)}
        bad_refs = [r.get('id', '?') for r in rows
                    if r.get('spine_event', '').strip()
                    and r.get('spine_event', '').strip() not in spine_ids]
        empty_refs = [r.get('id', '?') for r in rows
                      if not r.get('spine_event', '').strip()]
        checks.append(_check(
            'spine_event references resolve to spine.csv',
            not bad_refs,
            (f'{len(bad_refs)} row(s) reference unknown spine events: '
             + ', '.join(bad_refs[:5])
             + ('…' if len(bad_refs) > 5 else ''))
            if bad_refs else '',
            severity='high',
        ))
        checks.append(_check(
            'spine_event populated for every row',
            not empty_refs,
            (f'{len(empty_refs)} row(s) have empty spine_event: '
             + ', '.join(empty_refs[:5])
             + ('…' if len(empty_refs) > 5 else ''))
            if empty_refs else '',
            severity='medium',
        ))

    # Both action and sequel scenes present (≥ 25% of each).
    if rows:
        action_count = sum(1 for r in rows if r.get('action_sequel', '').strip() == 'action')
        sequel_count = sum(1 for r in rows if r.get('action_sequel', '').strip() == 'sequel')
        frac_action = action_count / len(rows)
        frac_sequel = sequel_count / len(rows)
        both_present = frac_action >= 0.25 and frac_sequel >= 0.25
        checks.append(_check(
            'both action and sequel scenes present (≥ 25% each)',
            both_present,
            (f'action: {frac_action:.0%}, sequel: {frac_sequel:.0%}'
             if not both_present else ''),
            severity='low',
        ))

    return _result(4, 'architecture', checks)


# ============================================================================
# Level 5 — Scene map
# ============================================================================

def score_scene_map(project_dir: str) -> dict:
    scenes_path = os.path.join(project_dir, 'reference', 'scenes.csv')
    intent_path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    checks: list[dict] = []

    if not os.path.isfile(scenes_path):
        checks.append(_check('scenes.csv exists', False,
                             'reference/scenes.csv is missing', severity='high'))
        return _result(5, 'scene-map', checks)

    rows = _read_csv(scenes_path)
    intent_by_id = {r.get('id', ''): r for r in _read_csv(intent_path)}

    # Filter to manuscript-tier rows (status >= mapped). Earlier-status rows
    # belong to spine.csv / architecture.csv after migration.
    map_rows = [r for r in rows
                if r.get('status', '').strip()
                in ('mapped', 'briefed', 'drafted', 'polished')]

    # Required operational columns at the map level.
    required = ['location', 'timeline_day', 'time_of_day', 'duration']
    missing_any = []
    for r in map_rows:
        empty = [c for c in required if not r.get(c, '').strip()]
        if empty:
            missing_any.append((r.get('id', '?'), empty))
    checks.append(_check(
        'operational metadata populated (location, timeline_day, time_of_day, duration)',
        not missing_any,
        (f'{len(missing_any)} row(s) missing metadata; first: '
         f'{missing_any[0][0]} missing {", ".join(missing_any[0][1])}'
         if missing_any else ''),
        severity='medium',
    ))

    # POV character must appear in on_stage for that scene.
    # If on_stage is unpopulated (intent CSV hasn't been filled yet at
    # this tier), don't false-positive the cross-check — surface a
    # separate lower-severity finding for the unpopulated state.
    bad_pov = []
    unpopulated_pov = []
    for r in map_rows:
        sid = r.get('id', '?')
        pov = r.get('pov', '').strip()
        on_stage = intent_by_id.get(sid, {}).get('on_stage', '').strip()
        if not pov:
            continue
        if not on_stage:
            unpopulated_pov.append(sid)
            continue
        on_stage_set = {s.strip() for s in on_stage.split(';') if s.strip()}
        if pov not in on_stage_set:
            bad_pov.append(sid)
    checks.append(_check(
        'POV is on-stage in every scene with on_stage populated',
        not bad_pov,
        (f'{len(bad_pov)} scene(s) have POV not in on_stage: '
         + ', '.join(bad_pov[:5])
         + ('…' if len(bad_pov) > 5 else ''))
        if bad_pov else '',
        severity='medium',
    ))
    if unpopulated_pov:
        # Lower-severity informational: not yet wired up.
        checks.append(_check(
            'on_stage data populated for every POV scene',
            False,
            (f'{len(unpopulated_pov)} scene(s) have a POV but on_stage is '
             f'empty (the POV check will run once on_stage is populated)'),
            severity='low',
        ))

    return _result(5, 'scene-map', checks)


# ============================================================================
# Level 6 — Briefs
# ============================================================================

def score_briefs(project_dir: str) -> dict:
    """Level 6 floor checks reuse the existing structural-scoring logic.

    This wrapper exposes those results in the level-rubric format. Full
    detail still lives in structural.py and the existing `score` command.
    """
    briefs_path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    checks: list[dict] = []

    if not os.path.isfile(briefs_path):
        checks.append(_check('scene-briefs.csv exists', False,
                             'reference/scene-briefs.csv is missing — '
                             'no briefs yet?', severity='high'))
        return _result(6, 'briefs', checks)

    rows = _read_csv(briefs_path)
    # Required fields at brief stage.
    required = ['goal', 'conflict', 'outcome', 'crisis', 'decision']
    missing_any = []
    for r in rows:
        empty = [c for c in required if not r.get(c, '').strip()]
        if empty:
            missing_any.append((r.get('id', '?'), empty))
    checks.append(_check(
        'goal/conflict/outcome/crisis/decision populated',
        not missing_any,
        (f'{len(missing_any)} brief(s) missing fields; first: '
         f'{missing_any[0][0]} missing {", ".join(missing_any[0][1])}'
         if missing_any else ''),
        severity='medium',
    ))

    return _result(6, 'briefs', checks)


# ============================================================================
# Dispatch
# ============================================================================

LEVEL_SCORERS = {
    0: score_logline,
    1: score_synopsis,
    2: score_act_shape,
    3: score_spine,
    4: score_architecture,
    5: score_scene_map,
    6: score_briefs,
}

LEVEL_NAMES = {
    0: 'logline',
    1: 'synopsis',
    2: 'act-shape',
    3: 'spine',
    4: 'architecture',
    5: 'scene-map',
    6: 'briefs',
}


def score_level(project_dir: str, level: int, medium: str = 'novel') -> dict:
    """Run the floor checks for one level. Returns the standard result dict.

    Each failed check is run through `_apply_overrides` so author-accepted
    findings get tagged with `accepted=True` and excluded from the
    `failed`-but-not-`accepted` count that quality-gate code consumes.
    """
    if level not in LEVEL_SCORERS:
        raise ValueError(f'unknown level: {level}')
    scorer = LEVEL_SCORERS[level]
    # Only spine + architecture take medium today.
    if level in (3, 4):
        raw = scorer(project_dir, medium=medium)
    else:
        raw = scorer(project_dir)
    return _apply_overrides(project_dir, raw)


def score_all_levels(project_dir: str, medium: str = 'novel') -> list[dict]:
    """Run floor checks for all levels 0–6. Returns a list of result dicts."""
    return [score_level(project_dir, level, medium) for level in sorted(LEVEL_SCORERS)]

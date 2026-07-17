"""storyforge status — deterministic next-step verdict.

Composes the existing floor / consistency / coverage scorers plus phase and
scene draft-state into a single routable verdict: where the project sits on
the elaboration ladder and the single recommended next action.

No LLM, no writes. Pure over project files.
"""

import os

from storyforge.scoring_levels import score_all_levels, LEVEL_NAMES
from storyforge.scoring_consistency import score_consistency_all_levels
from storyforge.scoring_coverage import score_coverage_all_levels
from storyforge.common import parse_story_summary, read_yaml_field
from storyforge.elaborate import _read_csv

LADDER_LEVELS = [0, 1, 2, 3, 4, 5, 6]
PROSE_STAGES = ('logline', 'synopsis', 'act-shape')

# Rung name -> `elaborate --stage` argument (only rungs with a command stage).
ELABORATE_STAGE = {
    'spine': 'spine',
    'architecture': 'architecture',
    'scene-map': 'map',
    'briefs': 'briefs',
}

# Which reference CSV backs each structural rung.
_LEVEL_CSV = {
    3: 'spine.csv',
    4: 'architecture.csv',
    5: 'scenes.csv',
    6: 'scene-briefs.csv',
}

# Prose-tier level -> parse_story_summary key.
_PROSE_KEY = {0: 'logline', 1: 'synopsis', 2: 'act_shape'}


def artifact_present(project_dir: str, level: int) -> bool:
    """True when the artifact backing `level` exists with real content."""
    if level in _PROSE_KEY:
        parsed = parse_story_summary(project_dir)
        if parsed is None:
            return False
        return bool(parsed.get(_PROSE_KEY[level], '').strip())
    path = os.path.join(project_dir, 'reference', _LEVEL_CSV[level])
    # Presence means "at least one data row with real content" — read through
    # the same DictReader-backed parser the floor checks use so a short/ragged
    # row is counted (not silently dropped) and a delimiter-only blank row
    # ("|||") does not masquerade as content. Missing file → [] → False.
    rows = _read_csv(path)
    # Guard `isinstance(v, str)`: a ragged row with more fields than headers
    # lands the overflow under DictReader's None restkey as a list, which we
    # must not .strip() (and which never counts as real content anyway).
    return any(isinstance(v, str) and v.strip()
               for row in rows for v in row.values())


def _real_failed(floor: dict) -> int:
    """Floor failures that the author has NOT accepted via override."""
    return floor['failed'] - floor['accepted']


def ladder_states(project_dir: str, medium: str = 'novel') -> list[dict]:
    """Return per-rung state for levels 0-6, derived from floor checks only.

    Coverage/consistency are NOT folded in here — they look downstream and
    would wrongly keep an upstream rung `thin`; they surface as blockers.
    """
    floors = {r['level']: r for r in score_all_levels(project_dir, medium)}
    ladder = []
    for level in LADDER_LEVELS:
        floor = floors[level]
        if not artifact_present(project_dir, level):
            state, detail = 'not_started', ''
        elif _real_failed(floor) == 0:
            state, detail = 'solid', ''
        else:
            state = 'thin'
            fails = [c['detail'] or c['check'] for c in floor['checks']
                     if not c['passed'] and not c.get('accepted')]
            detail = fails[0] if fails else ''
        ladder.append({'level': level, 'name': LEVEL_NAMES[level],
                       'state': state, 'detail': detail})
    return ladder


# Scene statuses that count as drafted-or-later.
_DRAFTED_STATUSES = {'drafted', 'polished'}
_EXCLUDED_STATUSES = {'cut', 'merged'}

# yaml / legacy phase names normalized onto the post-briefs ladder phases.
_PHASE_ALIASES = {
    'drafting': 'draft',
    'evaluation': 'evaluate',
    'revision': 'evaluate',
    'review': 'evaluate',
    'polish': 'evaluate',
    'production': 'evaluate',
    'complete': 'evaluate',
}

# Ladder index for each comparable phase name. Rungs keep their level (0-6);
# draft/evaluate both sit past briefs, so both require rungs 0-6 to be solid.
_PHASE_INDEX = {name: level for level, name in LEVEL_NAMES.items()}
_PHASE_INDEX['draft'] = 7
_PHASE_INDEX['evaluate'] = 7


def collect_blockers(project_dir: str) -> list[dict]:
    """Coverage + consistency failures for rungs whose artifact is present."""
    blockers: list[dict] = []
    for source, results in (
        ('coverage', score_coverage_all_levels(project_dir)),
        ('consistency', score_consistency_all_levels(project_dir)),
    ):
        for r in results:
            level = r['level']
            if not artifact_present(project_dir, level):
                continue
            for c in r['checks']:
                if not c['passed'] and not c.get('accepted'):
                    blockers.append({'source': source, 'level': level,
                                     'detail': c['detail'] or c['check']})
    seen = set()
    deduped = []
    for b in blockers:
        key = (b['source'], b['level'], b['detail'])
        if key not in seen:
            seen.add(key)
            deduped.append(b)
    return deduped


def _read_scene_statuses(project_dir: str) -> list[str]:
    """Scene `status` values from scenes.csv (missing file/rows → []).

    Uses the DictReader-backed reader (not a raw split) so a row too short to
    reach the `status` column is kept with an empty status rather than
    silently dropped — otherwise draft_stage would undercount scenes and could
    report a false "all drafted" verdict.
    """
    rows = _read_csv(os.path.join(project_dir, 'reference', 'scenes.csv'))
    return [r.get('status', '') for r in rows]


def draft_stage(project_dir: str) -> tuple[str, int, int]:
    """Return (stage, drafted, total) for the post-briefs rungs.

    stage is 'evaluate' once every non-cut/merged scene is drafted+; else
    'draft'. total counts scenes excluding cut/merged.
    """
    statuses = [s for s in _read_scene_statuses(project_dir)
                if s not in _EXCLUDED_STATUSES]
    total = len(statuses)
    drafted = sum(1 for s in statuses if s in _DRAFTED_STATUSES)
    if total > 0 and drafted == total:
        return 'evaluate', drafted, total
    return 'draft', drafted, total


def _recommend(stage: str) -> tuple[dict, dict | None]:
    """Map the current stage to (next, then) step objects."""
    if stage in PROSE_STAGES:
        level = {'logline': 0, 'synopsis': 1, 'act-shape': 2}[stage]
        nxt = {'stage': stage,
               'action': f'Develop the {stage} (elaborate skill, prose tier)',
               'command': f'storyforge score --level {level}',
               'reason': f'The {stage} floor is not yet met'}
        then = {'stage': 'story-power',
                'action': 'Pressure-test the pitch with the story-power scorecard',
                'command': 'storyforge score --story-power',
                'reason': 'Validate narrative design before building the spine'}
        return nxt, then
    if stage in ELABORATE_STAGE:
        order = list(ELABORATE_STAGE)
        nxt = {'stage': stage,
               'action': f'Develop the {stage}',
               'command': f'storyforge elaborate --stage {ELABORATE_STAGE[stage]}',
               'reason': f'{stage} is the next incomplete rung'}
        i = order.index(stage)
        if i + 1 < len(order):
            nxt_name = order[i + 1]
            then = {'stage': nxt_name,
                    'action': f'Develop the {nxt_name}',
                    'command': f'storyforge elaborate --stage {ELABORATE_STAGE[nxt_name]}',
                    'reason': ''}
        else:
            then = {'stage': 'draft', 'action': 'Draft scenes',
                    'command': 'storyforge write', 'reason': ''}
        return nxt, then
    if stage == 'draft':
        return ({'stage': 'draft', 'action': 'Draft scenes',
                 'command': 'storyforge write',
                 'reason': 'Briefs are complete; scenes are ready to draft'},
                {'stage': 'evaluate', 'action': 'Evaluate drafted scenes',
                 'command': 'storyforge evaluate', 'reason': ''})
    return ({'stage': 'evaluate', 'action': 'Evaluate and polish',
             'command': 'storyforge evaluate',
             'reason': 'All scenes are drafted'}, None)


def build_status(project_dir: str, medium: str = 'novel') -> dict:
    """Compose the full next-step verdict. Deterministic, read-only."""
    ladder = ladder_states(project_dir, medium)

    # Current phase = first rung that is not solid; if all solid, derive from
    # scene draft-state.
    phase = None
    for rung in ladder:
        if rung['state'] != 'solid':
            phase = rung['name']
            break
    if phase is None:
        phase, _drafted, _total = draft_stage(project_dir)

    declared = (read_yaml_field('phase', project_dir) or '').strip()
    normalized = _PHASE_ALIASES.get(declared, declared)
    # The declared yaml phase is a coarse milestone that legitimately LAGS the
    # fine-grained ladder — by convention `phase: drafting` stays put through
    # evaluation and revision, and no command advances it past `drafting`. So
    # we do NOT require declared == computed (that would fire a spurious
    # blocker on every post-drafting project). We flag only a real
    # contradiction: the declared phase claims progress whose prerequisites
    # aren't met — some ladder rung UPSTREAM of the declared phase is not solid
    # (e.g. "phase: architecture" while spine is still thin). A declared phase
    # on an all-not_started project is init intent (new projects default to
    # phase: spine), and an unrecognized/pre-spine phase (development,
    # scene-design, '') isn't comparable — both count as matching.
    declared_idx = _PHASE_INDEX.get(normalized)
    all_not_started = all(r['state'] == 'not_started' for r in ladder)
    if not declared or all_not_started or declared_idx is None:
        matches, unmet = True, []
    else:
        unmet = [r for r in ladder
                 if r['level'] < declared_idx and r['state'] != 'solid']
        matches = not unmet

    blockers = collect_blockers(project_dir)
    if declared and not matches:
        names = ', '.join(r['name'] for r in unmet)
        blockers.insert(0, {
            'source': 'phase', 'level': -1,  # sentinel: not a ladder rung
            'detail': (f"storyforge.yaml phase is '{declared}' but upstream "
                       f"rung(s) not yet solid: {names}"),
        })

    nxt, then = _recommend(phase)
    return {
        'phase': phase,
        'phase_declared': declared,
        'phase_matches_yaml': matches,
        'ladder': ladder,
        'next': nxt,
        'then': then,
        'blockers': blockers,
    }

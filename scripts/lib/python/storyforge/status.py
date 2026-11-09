"""storyforge status — deterministic next-step verdict.

Composes the existing floor / consistency / coverage scorers plus phase and
scene draft-state into a single routable verdict: where the project sits on
the elaboration ladder and the single recommended next action.

No LLM, no writes. Pure over project files.
"""

import os
from typing import Literal

from storyforge.scoring_levels import score_all_levels, LEVEL_NAMES
from storyforge.scoring_consistency import score_consistency_all_levels
from storyforge.scoring_coverage import score_coverage_all_levels
from storyforge.common import (
    MEDIUM_GRAPHIC_NOVEL, VOICE_GUIDE_REMEDY, VOICE_STAGE, VOICE_STAGE_COMMAND,
    parse_story_summary, read_yaml_field, resolve_voice_guide,
)
from storyforge.elaborate import _read_csv

LADDER_LEVELS = [0, 1, 2, 3, 4, 5, 6]
PROSE_STAGES = ('logline', 'synopsis', 'act-shape')

# Closed sets, mirrored in the skill/CLI docs — express them as Literals (as
# scoring_levels.py does for its result shapes) so drift is visible in-type.
RungState = Literal['solid', 'thin', 'not_started']
Stage = Literal['logline', 'synopsis', 'act-shape', 'spine', 'architecture',
                'scene-map', 'briefs', 'story-power', 'voice', 'draft', 'evaluate',
                'check']

# Rung name -> `elaborate --stage` argument (only rungs with a command stage).
ELABORATE_STAGE = {
    'spine': 'spine',
    'architecture': 'architecture',
    'scene-map': 'map',
    'briefs': 'briefs',
}

# The voice rung (#596): between briefs and drafting, a prose book needs a
# voice guide with the author's text in it (`common.resolve_voice_guide`: not
# missing, init's template, empty, unreadable, or only persistent-prompt.md).
# Not a floor-checked ladder level. Before drafting, `build_status` makes it
# the phase and `next` (or `then`, while scenes wait on the gate) and a
# `voice` blocker; once every scene is drafted, the blocker alone. A graphic
# novel's script is written from voice-profile.csv, so it has no voice rung.

#: what status recommends for drafting (Storyforge's unattended drafting
#: passes --keep-going, Ben 2026-11-04)
WRITE_COMMAND = 'storyforge write --keep-going'
#: what clears scenes waiting on the gate; `next.stage` 'check' while any wait
CHECK_COMMAND = 'storyforge check --pending'

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


def draft_stage(project_dir: str) -> tuple[Stage, int, int]:
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


def _recommend(stage: Stage) -> tuple[dict, dict | None]:
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
                    'command': WRITE_COMMAND, 'reason': ''}
        return nxt, then
    if stage == VOICE_STAGE:
        return ({'stage': VOICE_STAGE, 'action': 'Develop the voice guide',
                 'command': VOICE_STAGE_COMMAND,
                 'reason': ('Briefs are complete; drafting needs a voice guide with '
                            "the author's text (see the voice blocker)")},
                {'stage': 'draft', 'action': 'Draft scenes',
                 'command': WRITE_COMMAND, 'reason': ''})
    if stage == 'draft':
        return ({'stage': 'draft', 'action': 'Draft scenes',
                 'command': WRITE_COMMAND,
                 'reason': 'Briefs are complete; scenes are ready to draft'},
                {'stage': 'evaluate', 'action': 'Evaluate drafted scenes',
                 'command': 'storyforge evaluate', 'reason': ''})
    if stage == 'evaluate':
        return ({'stage': 'evaluate', 'action': 'Evaluate and polish',
                 'command': 'storyforge evaluate',
                 'reason': 'All scenes are drafted'}, None)
    # Fail loud rather than silently returning "go evaluate" for an unknown
    # stage — guards the PROSE_STAGES / ELABORATE_STAGE / LEVEL_NAMES invariant
    # (which is mirrored by hand and could drift, e.g. the scene-map↔map
    # spelling) instead of shipping a wrong verdict.
    raise ValueError(f'_recommend: unrecognized stage {stage!r}')


def gate_waiting(project_dir: str) -> list[dict[str, str]]:
    """The rows of working/gate-pending.csv, in reading order where known
    (an unreadable file is one row saying so)."""
    from storyforge import gate, ledger
    try:
        rows = gate.pending(project_dir)
    except gate.GateError as e:
        return [{'scene_id': gate.PENDING_PATH, 'command': 'unreadable', 'reason': str(e)}]
    try:
        order = ledger.scene_order(project_dir)
    except Exception:
        order = {}
    out = [rows[s] for s in sorted(rows, key=lambda s: (order.get(s, 10**9), s))]
    # #557: the scenes listed to fix toward the source (their own file)
    try:
        fixes = gate.source_fixes(project_dir)
    except gate.GateError as e:
        fixes = {gate.SOURCE_FIX_PATH: {'scene_id': gate.SOURCE_FIX_PATH, 'reason': str(e)}}
    out += [{'scene_id': s, 'command': 'source-fix', 'reason': fixes[s]['reason']}
            for s in sorted(fixes, key=lambda s: (order.get(s, 10**9), s))]
    return out


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

    # #596: briefs to drafting with no voice guide. Before drafting the
    # voice stage is the phase (next, or then while scenes wait on the gate);
    # once every scene is drafted only the blocker is reported, since
    # evaluation and revision read the voice guide too.
    voice_blocker = None
    if phase in ('draft', 'evaluate') and medium != MEDIUM_GRAPHIC_NOVEL:
        voice = resolve_voice_guide(project_dir)
        if voice.kind != 'ok':
            voice_blocker = {
                'source': VOICE_STAGE, 'level': -1,  # sentinel: not a ladder rung
                'detail': (f'{voice.detail}: drafting has no voice guide to follow, '
                           f'and write refuses to draft. Fill it: {VOICE_GUIDE_REMEDY}'),
            }
            if phase == 'draft':
                phase = VOICE_STAGE

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
    if voice_blocker:
        blockers.insert(0, voice_blocker)
    if declared and not matches:
        names = ', '.join(r['name'] for r in unmet)
        blockers.insert(0, {
            'source': 'phase', 'level': -1,  # sentinel: not a ladder rung
            'detail': (f"storyforge.yaml phase is '{declared}' but upstream "
                       f"rung(s) not yet solid: {names}"),
        })

    nxt, then = _recommend(phase)
    # #556's review: scenes waiting on the gate (a provisional commit from
    # `write --keep-going` among them) are blockers, and come before the
    # next rung, except while scenes are left to draft (#641): write drafts
    # past them, holding back only the scenes that depend on one, so drafting
    # stays next and the check comes after it
    waiting = gate_waiting(project_dir)
    for row in waiting:
        blockers.append({'source': 'gate', 'level': -1,
                         'detail': f"{row['scene_id']} ({row['command']}): {row['reason']}"})
    if waiting:
        provisional = sum(r['command'] == 'provisional' for r in waiting)
        listed = (f'{len(waiting)} scene(s) in working/gate-pending.csv'
                  + (f', {provisional} committed provisionally' if provisional else ''))
        # its own stage (TD-6): forge routes on next.stage, and the phase's
        # stage (voice, draft) would send it to that work instead
        check = {'stage': 'check', 'action': 'Clear the scenes waiting on the gate',
                 'command': CHECK_COMMAND,
                 'reason': f'{listed}: fix them (or `storyforge check --accept`), then check'}
        if nxt['stage'] == 'draft':
            nxt = dict(nxt, reason=(f'{nxt["reason"]}; {listed} (the gate blockers): write '
                                    f'drafts past them, holding back only the scenes that '
                                    f'depend on one'))
            then = check
        else:
            then, nxt = nxt, check
    return {
        'phase': phase,
        'phase_declared': declared,
        'phase_matches_yaml': matches,
        'ladder': ladder,
        'next': nxt,
        'then': then,
        'blockers': blockers,
    }

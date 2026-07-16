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
from storyforge.common import parse_story_summary

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
    if not os.path.isfile(path):
        return False
    with open(path, encoding='utf-8') as f:
        rows = [ln for ln in f.read().splitlines() if ln.strip()]
    return len(rows) > 1  # header + at least one data row


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

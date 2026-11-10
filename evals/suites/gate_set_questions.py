"""The gate set (#677) gated with the question layer (#649, `check
--questions`) in place of the open checker: the same items, scored the same
way as `gate-set` (see it). Decision 5 retires the open checker once this
suite's recall matches `gate-set`'s.

Private and frozen like `gate-set`; its recordings are
`gate-set/cassettes/gate-set-questions/` in the storyforge-evals repo.
Extraction's requests are the same as `gate-set`'s, but each suite keeps
its own recordings. **Not recorded yet.**
"""

from __future__ import annotations

import gate_set
from gate_set import runner
from harness import Suite

NAME = 'gate-set-questions'
MIN_POSITIVES = 40

#: The recorded values, each held exactly (#488); None until recorded
FLOORS: dict[str, float | None] = {
    'recall': None, 'recall_per_case': None, 'cases_caught': None,
    'stop_rate_positive': None, 'false_alarm_on_fact': None, 'stop_rate_control': None,
    'unfinished': None,
}


def run(ctx):
    return runner.run(ctx, 'questions', FLOORS, MIN_POSITIVES)


SUITE = Suite(NAME, 'The gate with the question layer (#649) alone on E8\'s recorded, judged '
                    'replays; private set',
              run, frozen=True, cassettes=lambda run: gate_set.cassettes_dir(NAME, run=run))

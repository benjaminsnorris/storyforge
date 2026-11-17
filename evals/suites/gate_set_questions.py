"""The gate set (#677) gated with the question layer (#649, `check
--questions`) in place of the open checker: the same items, scored the same
way as `gate-set` (see it). Decision 5 retires the open checker once this
suite's recall matches `gate-set`'s.

**Each case is gated with its own fact in the ledger** (`gate_set.FACTS_FILE`,
`seed_facts`). The question layer asks only about ledger rows, and the
corpus books' ledgers mostly lack the cases' facts: the first recording
(2026-11-16, unseeded) caught 1-2 of 46 because it had nothing to ask. So
this measures the questions given the fact, which is what a book whose
ledger is kept up would give it; the open checker's suite gets no rows (it
reads the established scene's prose). A case whose fact is only in the
gated scene gets no row and is never asked (named in the notes).

Private and frozen like `gate-set`; its recordings are
`gate-set/cassettes/gate-set-questions/` (and `run2/`, `run3/`) in the
storyforge-evals repo. Each suite keeps its own recordings. Recording it
needs ``--over-budget`` until the baseline has its forecast.
"""

from __future__ import annotations

import gate_set
from gate_set import runner
from harness import Suite

NAME = 'gate-set-questions'
MIN_POSITIVES = 40   # as gate-set's

#: The recorded values, each held exactly (#488); None until recorded
FLOORS: dict[str, float | None] = {
    'recall': None, 'recall_per_case': None, 'cases_caught': None,
    'stop_rate_positive': None, 'false_alarm_on_fact': None, 'stop_rate_control': None,
    'unfinished': None,
}


def run(ctx):
    return runner.run(ctx, 'questions', FLOORS, MIN_POSITIVES, seeded=True)


SUITE = Suite(NAME, 'The gate with the question layer (#649) alone on E8\'s recorded, judged '
                    'replays; private set',
              run, frozen=True, cassettes=lambda run: gate_set.cassettes_dir(NAME, run=run))

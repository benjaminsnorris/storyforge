"""The gate set (#677) gated with the question layer (#649, `check
--questions`) in place of the open checker: the same items, scored the same
way as `gate-set` (see it). Decision 5 retires the open checker once this
suite's recall matches `gate-set`'s.

**Each case is gated with its own fact in the ledger** (`gate_set.FACTS_FILE`,
`seed_facts`). The question layer asks about a case's fact only through a
ledger row, and the corpus books' ledgers mostly lack the cases' facts: the
first recording (2026-11-16, unseeded) caught 1-2 of 46 because it had
nothing to ask. So this measures the questions given the fact, which is
what a book whose ledger is kept up would give it; the open checker's suite
gets no rows (it reads the established scene's prose). A case whose book
doesn't state the fact outside the gated scene gets no row and is gated
without one (named in the notes); a seeded row is still asked only when
`questions.facts_to_ask` selects it (its subject present, or in no
registry) and `questions.ask_questions` keeps it within the cap, and the
notes name the items where it
wasn't. `recall` is over every positive, `recall_seeded` over the seeded
cases', and `recall_asked` over those whose fact was asked: the last is
the questions' own recall.

Private and frozen like `gate-set`; its recordings are
`gate-set/cassettes/gate-set-questions/` and, for runs 2 and 3,
`gate-set/cassettes/run2/gate-set-questions/` and `run3/`, in the
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
    # recorded 2026-11-16, seeded; topped up 2026-11-17 after names written
    # surname first ("Erdel, Tam") count as present; topped up 2026-11-26
    # (PR #754, $1.18 with the comparison) after the question order, the
    # earlier-scene promise skip and the namesake guard (#739, #740, #746),
    # at the cap of 30 the comparison chose (docs/history.md). Run 1; runs
    # 2 and 3: recall 0.413 and 0.3696, false alarms 2 and 3, control stops
    # 0.6452 and 0.5806. Before PR #754, runs 1-3 were recall
    # 0.413/0.3696/0.3913, false alarms 1/2/1, control stops
    # 0.4839/0.6129/0.5484: recall held, false alarms rose (4 to 7 over the
    # three runs). Of 46 positives, 39 are seeded and 32 asked about their
    # fact
    'recall': 0.413, 'recall_per_case': 0.4689, 'cases_caught': 9,
    'stop_rate_positive': 0.7391, 'false_alarm_on_fact': 2, 'stop_rate_control': 0.5161,
    'unfinished': 0,
    'recall_seeded': 0.4872, 'recall_asked': 0.5625, 'asked_positives': 32,
    'asked_controls': 23,
}


def run(ctx):
    return runner.run(ctx, 'questions', FLOORS, MIN_POSITIVES, seeded=True)


SUITE = Suite(NAME, 'The gate with the question layer (#649) alone on E8\'s recorded, judged '
                    'replays; private set',
              run, frozen=True, cassettes=lambda run: gate_set.cassettes_dir(NAME, run=run))

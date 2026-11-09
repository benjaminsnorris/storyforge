"""The blocking set (#646): today's blocking read (`storyforge.blocking`,
two readings per scene) against known blocking slips from *A Year and a
Day* (gawain) and *Wrath Like Smoke* (iliad-adult), and clean scenes for
false alarms. See ``evals/blocking_set``.

The set and its recordings are private (the author's unpublished prose) and
live in the storyforge-evals repo; on a machine without it the suite is
reported unavailable (``stale``, exit code unaffected), saying where to put
it. Frozen (#645): recorded once, on purpose, as three runs
(``--mode record --suite blocking-set --runs 3``); a miss is ``stale``. The suite writes each case's outcome, with the findings'
quotes, to ``blocking-set/results/latest.json`` there (gitignored), never to
this repo: notes carry counts and case ids only. The stage sheet (#647) is
measured on the same set by `blocking-set-sheet`; run both side by side with
``--suite blocking-set --suite blocking-set-sheet`` (`blocking_set.runner`).
"""

from __future__ import annotations

import blocking_set
from blocking_set import runner
from harness import Suite

NAME = 'blocking-set'
#: The set must keep its size: it has 117 in-scene fixed cases (the plan's
#: "gawain's 35 and Wrath's 70", as built); 100 guards against a build
#: that drops a source
MIN_CASES = 100

#: The gates: the recorded baseline's values, each to be held exactly
#: (#488). For recall a rise is a gain, for false alarms, left_flagged and
#: flags a fall is; a gain moves the value here in the same commit, a loss
#: is a decision. `None` until the baseline is recorded: the gate then
#: fails and the note says what to write here. A metric the run doesn't
#: emit fails its gate either way (a category or book gone from the set).
#: `recall_found_by_readers` is the independent number (slips people
#: found); `recall_found_by_tool` is partly the read agreeing with itself.
FLOORS: dict[str, float | None] = {
    'recall': None,
    'recall_hands': None, 'recall_posture': None, 'recall_sightline': None,
    'recall_worn': None, 'recall_position': None, 'recall_light': None,
    'recall_other': None,
    'recall_book_gawain': None, 'recall_book_wrath': None,
    'recall_found_by_readers': None, 'recall_found_by_tool': None,
    'false_alarms_per_10k': None,
    'left_flagged': None,
    'flags': None,
}


def run(ctx):
    return runner.run(ctx, 'read', FLOORS, MIN_CASES)


SUITE = Suite(NAME, 'Blocking read vs known blocking slips (gawain, Wrath) and clean scenes; '
                    'private set', run, frozen=True,
              cassettes=lambda run: blocking_set.cassettes_dir(NAME, run=run))

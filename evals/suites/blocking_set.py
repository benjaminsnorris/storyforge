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
#: is a decision. A metric the run doesn't emit fails its gate (a
#: category or book gone from the set).
#: `recall_found_by_readers` is the independent number (slips people
#: found); `recall_found_by_tool` is partly the read agreeing with itself.
FLOORS: dict[str, float | None] = {
    # Recorded 2026-11-09 (three runs, $20.31, opus, two readings a scene),
    # gated on run 1's values. Across the three runs: recall 0.6154 / 0.6496
    # / 0.6496, readers' 0.3235 / 0.3824 / 0.4118, false alarms per 10k
    # 1.27 / 1.27 / 0.85, flags 99 / 101 / 96; the small categories move
    # most (sightline 0.33 / 0.67 / 0.75 on 12 cases, light 0.33 / 0.50 /
    # 0.17 on 6, posture 0.91 / 0.55 / 0.82 on 11)
    'recall': 0.6154,
    'recall_hands': 0.7353, 'recall_posture': 0.9091, 'recall_sightline': 0.3333,
    'recall_worn': 0.4545, 'recall_position': 0.6129, 'recall_light': 0.3333,
    'recall_other': 0.5833,
    'recall_book_gawain': 0.4318, 'recall_book_wrath': 0.726,
    'recall_found_by_readers': 0.3235, 'recall_found_by_tool': 0.7349,
    'false_alarms_per_10k': 1.27,
    'left_flagged': 1,
    'flags': 99,
}


#: The set and the recordings FLOORS were measured on (#679 review): a
#: different set errors, and a replay with fewer recordings (run 1's) is
#: unavailable, naming the checkout, not read as a changed request.
#: Re-recording sets both again (`blocking_set.fingerprint`, `.recordings`)
RECORDED = {'set': '3244134c57b027323561416afdfc3d70119e9f8330ed5fe91ffab1b7997053fb',
            'recordings': 185}


def run(ctx):
    return runner.run(ctx, 'read', FLOORS, MIN_CASES, RECORDED)


SUITE = Suite(NAME, 'Blocking read vs known blocking slips (gawain, Wrath) and clean scenes; '
                    'private set', run, frozen=True,
              cassettes=lambda run: blocking_set.cassettes_dir(NAME, run=run))

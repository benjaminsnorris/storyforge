"""The blocking set (#646): today's blocking read (`storyforge.blocking`,
`BLOCKING_READINGS` readings per scene, three since #774) against known blocking slips from *A Year and a
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
#: The set must keep its size: it has 146 in-scene fixed cases (gawain's
#: 44, Wrath's Nov 8 73, and 29 from Wrath's overnight gate run, 2026-11-27);
#: 130 guards against a build that drops a source
MIN_CASES = 130

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
    # 0.17 on 6, posture 0.91 / 0.55 / 0.82 on 11).
    # 2026-11-27: report A's 38 blocking-read findings on Wrath's overnight
    # gate run joined the set (29 real, 9 debatable; books `wrath-gate`, the
    # first-gated prose, and `wrath-gate-fix`, fix-round prose; PILOT.md
    # step 3). Their 28 scenes were recorded as three runs ($6.65); the
    # other scenes' recordings replay unchanged, so gawain's, Wrath's Nov 8,
    # the readers', the false alarms and left_flagged keep their values.
    # The pooled and category values below are run 1's on the larger set:
    # recall 0.6027 / 0.6438 / 0.6301, wrath-gate 12 / 15 / 15 of 25,
    # wrath-gate-fix 4 / 3 / 1 of 4, flags 122 / 128 / 118, debatable
    # flagged 3 / 6 / 3 of 9. The added cases were found by the same read
    # (`tool`), so recall_found_by_tool fell (0.7349 to 0.6875): a bigger
    # set, not a weaker read
    'recall': 0.6027,
    'recall_hands': 0.7442, 'recall_posture': 0.8, 'recall_sightline': 0.375,
    'recall_worn': 0.4615, 'recall_position': 0.5789, 'recall_light': 0.3333,
    'recall_other': 0.5333,
    'recall_book_gawain': 0.4318, 'recall_book_wrath': 0.726,
    'recall_book_wrath-gate': 0.48, 'recall_book_wrath-gate-fix': 1.0,
    'recall_found_by_readers': 0.3235, 'recall_found_by_tool': 0.6875,
    'false_alarms_per_10k': 1.27,
    'left_flagged': 1,
    'flags': 122,
}


#: The set and the recordings FLOORS were measured on (#679 review): a
#: different set errors, and a replay with fewer recordings (run 1's) is
#: unavailable, naming the checkout, not read as a changed request.
#: Re-recording sets both again (`blocking_set.fingerprint`, `.recordings`)
RECORDED = {'set': '14a0145c377ee8b71751f48ff7177ef53ba30effde652755d6a714bd5c44baf7',
            'recordings': 241}


def run(ctx):
    return runner.run(ctx, 'read', FLOORS, MIN_CASES, RECORDED)


SUITE = Suite(NAME, 'Blocking read vs known blocking slips (gawain, Wrath) and clean scenes; '
                    'private set', run, frozen=True,
              cassettes=lambda run: blocking_set.cassettes_dir(NAME, run=run))

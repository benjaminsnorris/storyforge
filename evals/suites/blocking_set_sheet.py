"""The blocking set (#646) checked by the stage sheet (#647,
`storyforge.stage_sheet`): a small model records each scene's physical
action as transitions, code checks them, and a yes/no question asked twice
covers the rest. Measured against the same known slips and clean scenes as
the whole-scene blocking read (`blocking-set`), which the gate keeps as its
default until this matches its recall with no more false alarms (plan A4).

Side by side: ``python3 evals/run.py --suite blocking-set --suite
blocking-set-sheet``. The read runs first (name order) and writes its
per-case outcomes; this suite's notes then compare the two case by case,
in counts and case ids. Each scene stands alone (the set's scenes aren't
consecutive, so nothing is carried over). The model is the stage sheet's
default (the extraction tier) unless `STORYFORGE_STAGE_SHEET_MODEL` names
another, which is a different request and so a re-record.

Private like `blocking-set`: its recordings live beside the set in the
storyforge-evals repo (`blocking-set/cassettes/blocking-set-sheet/`), and
its per-case outcomes go to `blocking-set/results/latest-stage-sheet.json`
there; notes carry counts and case ids only. Without that checkout the
suite is reported unavailable (``stale``, exit code unaffected). Frozen
like it too (#645): recorded on purpose, as three runs (``--mode record
--suite blocking-set-sheet --runs 3``); a miss is ``stale``. (The
recordings so far are the main run only, made before it was frozen.)
"""

from __future__ import annotations

import blocking_set
from blocking_set import runner
from harness import Suite

NAME = 'blocking-set-sheet'
MIN_CASES = 100

#: The sheet's own recorded values, each held exactly (#488: a gain moves its
#: floor in the same commit). The plan's target is the read's values
#: (`blocking-set`'s FLOORS: recall 0.6154, false alarms 1.27 per 10k): recall at least its, false
#: alarms no higher. Recall is still far below the read's three-scene check
#: (26 of 117), and false alarms rose with it once hands kept their state
FLOORS: dict[str, float | None] = {
    # re-recorded 2026-11-09 after #671's review fixes (haiku 5.5, $0.85 for
    # the set): hands as two slots, a question per reach or sightline, events
    # in the prose's order. The first recording: recall 0.1368, false alarms
    # 2.54 per 10k, 126 flags
    'recall': 0.2222,
    'recall_hands': 0.4412, 'recall_posture': 0.2727, 'recall_sightline': 0.0,
    'recall_worn': 0.2727, 'recall_position': 0.129, 'recall_light': 0.0,
    'recall_other': 0.0833,
    # read from a free replay after porting #670's matching (each finding
    # catches at most one case, whole-word places), which left the values
    # above unchanged
    'recall_book_gawain': 0.2273, 'recall_book_wrath': 0.2192,
    'recall_found_by_readers': 0.2353, 'recall_found_by_tool': 0.2169,
    'false_alarms_per_10k': 15.65,
    'left_flagged': 2,
    'flags': 288,
}


#: The set and the recordings FLOORS were measured on (#679 review): a
#: different set errors, and a replay with fewer recordings (the main run's) is
#: unavailable, naming the checkout, not read as a changed request.
#: Re-recording sets both again (`blocking_set.fingerprint`, `.recordings`)
RECORDED = {'set': '3244134c57b027323561416afdfc3d70119e9f8330ed5fe91ffab1b7997053fb',
            'recordings': 273}


def run(ctx):
    return runner.run(ctx, 'stage-sheet', FLOORS, MIN_CASES, RECORDED)


SUITE = Suite(NAME, 'Stage sheet (#647) vs the known blocking slips and clean scenes of the '
                    'blocking set; private set', run,
              frozen=True, cassettes=lambda run: blocking_set.cassettes_dir(NAME, run=run))

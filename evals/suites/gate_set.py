"""The gate set (#677): today's gate, the open checker (its default), on prose
E8 already recorded and judged for one known error each (`evals/gate_set`).

The gate runs once per item (`gate.gate_scene`, no fix loop) in the item's
pre-pass book. `recall` is the share of positives (replays the judge found
reintroducing the case's error) on whose evidence sentence a blocking
verified finding lands; `recall_per_case` weighs each E1 case the same,
since positives cluster on a few cases. `stop_rate_positive` is E8's own
measure (the gate didn't pass the scene, for any reason).
`false_alarm_on_fact` counts controls (replays stating the fact correctly)
with a finding on that correct statement. Decision 5 retires the open
checker when `gate-set-questions` matches this suite's recall.

Private like the blocking set: the set and its recordings live in the
storyforge-evals repo (`gate-set/`; recordings in `gate-set/cassettes/gate-set/`
and, for runs 2 and 3, `gate-set/cassettes/run2/gate-set/` and `run3/`);
notes carry counts and ids only, and without that checkout the suite is
reported unavailable (``stale``). Frozen (#645): recorded on purpose, as
three runs. Needs the corpus books cloned under ``STORYFORGE_CORPUS_DIR``, as
E8 does. First recorded 2026-11-16 (three runs, about $43 each, with
``--over-budget`` and Ben's approval: `gate_set.runner.record_command`);
`FLOORS` are run 1's (the default cassettes, which a replay reads), so
missing recordings are the harness's error. **Stale since #713** (the
typed-state extraction prompt changed while it was being recorded): its
replay misses every item until it is re-recorded (about $130, Ben's call).
"""

from __future__ import annotations

import gate_set
from gate_set import runner
from harness import Suite

NAME = 'gate-set'
#: The set has 46 positives (built 2026-11-09); a rebuild that loses more
#: than six (a recording or a case gone) fails this gate rather than
#: measuring a smaller set against the same floors
MIN_POSITIVES = 40

#: The recorded values, each held exactly (#488); None until recorded
FLOORS: dict[str, float | None] = {
    # recorded 2026-11-16 at 4d26a353 (run 1; runs 2 and 3: recall 0.5 and
    # 0.5652, false alarms 3 and 3, control stops 0.7419 and 0.8065)
    'recall': 0.5652, 'recall_per_case': 0.5411, 'cases_caught': 10,
    'stop_rate_positive': 0.9565, 'false_alarm_on_fact': 5, 'stop_rate_control': 0.7419,
    'unfinished': 0,
}


def run(ctx):
    return runner.run(ctx, 'open', FLOORS, MIN_POSITIVES)


SUITE = Suite(NAME, 'The gate (open checker) alone on E8\'s recorded, judged replays; private set',
              run, frozen=True, cassettes=lambda run: gate_set.cassettes_dir(NAME, run=run))

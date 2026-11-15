"""The control for writing in the voice (#654 test 6, `voice-austen`): the
same scene, drafted with the same request less the voice. The fixture book
has its `voice:` block cut, so the shared context carries no Austen
description and no exemplars; everything else (the briefs, the bibles, the
craft engine, the drafting prompt) is byte for byte what `voice-austen`
sends. Then the same meter and the same four-way judge.

What it answers: how much of `voice-austen`'s result the exemplars earn.
The meter and the judge are read side by side with `voice-austen`'s
(`evals/README.md`, "Writing in the voice"): if a scene with no voice
lands as near her, the exemplars aren't what moves it.

The request is one `write` never sends: `write` refuses a book with no
voice (`require_voice`, #652). The drafting prompt still says "Write toward
the voice's passages", with none in the context, as it would for such a
book.

**Frozen** (#645), recorded on purpose as three runs: `python3 evals/run.py
--mode record --suite voice-austen-control --runs 3`. The gates hold what
run 1 recorded (#488), in the direction of the comparison: a control that
came nearer her than recorded would close the gap `voice-austen` is read
against.
"""

from harness import Gate, Suite, SuiteOutput
from suites import voice_austen as va

#: what run 1 recorded (2026-11-15); the gates hold these (#488). Runs 2
#: and 3 put her 7th and 6th of eight; the judge named her 4 of 4 every run
RECORDED_RANK = 8
RECORDED_JUDGE = 4


def run(ctx):
    metrics, notes = va.measure(ctx, voiced=False)
    notes.append('The control: read beside voice-austen (the same scene with the voice). '
                 'The gates hold what run 1 recorded (#488).')
    return SuiteOutput(
        metrics=metrics,
        gates=[Gate('meter_rank', metrics['meter_rank'], '>=', RECORDED_RANK),
               Gate('judge_austen', metrics['judge_austen'], '<=', RECORDED_JUDGE)],
        notes=notes,
    )


SUITE = Suite('voice-austen-control', 'B7 test 6\'s control: the same scene drafted with no '
              'voice, on the meter and before the same judge', run, frozen=True)

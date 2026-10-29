"""E2 on A Christmas Carol: labelled errors injected one at a time into the
text, against the current detector (rethink plan §4.2). See ``evals/e2``."""

import os

import e2
from harness import Gate, Suite, SuiteOutput

BOOK = 'carol'
DETECTOR = 'drift-check'


def run(ctx):
    book_dir = os.path.join(e2.fixture_dir(BOOK), 'book')
    cases = e2.load_cases(BOOK)
    problems = e2.validate_cases(cases, book_dir)
    if problems:
        raise ValueError('e2-carol fixtures: ' + '; '.join(problems))
    case_flags, control_flags = e2.run_detector(BOOK, e2.DETECTORS[DETECTOR], ctx.work_dir, cases)
    result = e2.score(cases, case_flags, control_flags, e2.reading_order(book_dir))
    gates = [Gate(f'recall_{code}', result['by_code'].get(code, {}).get('recall_code_match', 0.0),
                  '>=', e2.RECALL_GATE) for code in e2.GATED_CODES]
    gates.append(Gate('precision', e2.precision_gate_value(result['metrics']), '>=', e2.PRECISION_GATE))
    missed = sorted(cid for cid, hit in result['detected'].items() if not hit)
    flagged = result['metrics']['flags_true'] + result['metrics']['flags_false']
    notes = [f'detector: {DETECTOR}',
             'a detection is a new flag on the case\'s scenes with the case\'s code; it may '
             'still not be about the injected error (see evals/fixtures/e2-carol/README.md)',
             f'missed {len(missed)} of {result["metrics"]["cases"]}: {", ".join(missed)}']
    if flagged < e2.MIN_FLAGS_FOR_PRECISION:
        notes.append(f'{flagged} distinct flag(s), fewer than {e2.MIN_FLAGS_FOR_PRECISION}: '
                     'the precision gate counts precision as 0')
    return SuiteOutput(metrics=result['metrics'], by_code=result['by_code'], gates=gates, notes=notes)


SUITE = Suite('e2-carol', 'Detection of labelled errors injected into A Christmas Carol', run)

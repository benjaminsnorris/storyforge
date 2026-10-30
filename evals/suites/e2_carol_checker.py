"""E2 on A Christmas Carol with the gate's checker (``storyforge.checker``):
the same injected errors as ``e2-carol``, the Phase 3 detector in place of
the drift check (rethink plan §5 Phase 3: E2 precision >= 0.8)."""

import os

import e2
from harness import Gate, Suite, SuiteOutput

BOOK = 'carol'


def run(ctx):
    book_dir = os.path.join(e2.fixture_dir(BOOK), 'book')
    cases = e2.load_cases(BOOK)
    problems = e2.validate_cases(cases, book_dir)
    if problems:
        raise ValueError('e2-carol fixtures: ' + '; '.join(problems))
    detector = e2.GateChecker()
    case_flags, control_flags = e2.run_detector(BOOK, detector, ctx.work_dir, cases)
    result = e2.score(cases, case_flags, control_flags, e2.reading_order(book_dir))
    gates = [Gate(f'recall_{code}', result['by_code'].get(code, {}).get('recall_code_match', 0.0),
                  '>=', e2.RECALL_GATE) for code in e2.GATED_CODES]
    gates.append(Gate('precision', e2.precision_gate_value(result['metrics']), '>=', e2.PRECISION_GATE))
    missed = sorted(cid for cid, hit in result['detected'].items() if not hit)
    notes = ['detector: the gate checker (contradictions; no brief promises)',
             f'missed {len(missed)} of {result["metrics"]["cases"]}: {", ".join(missed)}',
             f'{len(detector.unverified)} unverified finding(s) (quotes not in the text '
             'they name) not counted as flags; the gate blocks on them' + (': ' + '; '.join(detector.unverified[:10])
                                      if detector.unverified else '')]
    notes.append(f'{result["metrics"]["control_flags"]} flag(s) on unedited controls; '
                 f'{result["metrics"]["benign_flagged"]} benign case(s) flagged')
    return SuiteOutput(metrics=result['metrics'], by_code=result['by_code'], gates=gates, notes=notes)


SUITE = Suite('e2-carol-checker', 'The gate checker on errors injected into A Christmas Carol', run)

"""E1 corpus health: format, size, and holdout — no API calls, no repos needed.

This measures the gold set, not Storyforge. The suites that score Storyforge
against E1 (E2, E3, E8) read the same cases; this one fails loudly when the
corpus itself is malformed, too small to support the plan's gates, or missing
its holdout.
"""

from e1 import ERROR_CODES, load_cases, load_holdout, stats, validate_corpus
from harness import Gate, Suite, SuiteOutput

MIN_PROSE_CASES = 100


def run(ctx):
    cases = load_cases()
    problems = validate_corpus(cases)
    holdout = load_holdout()
    s = stats(cases, holdout)
    by_code = {code: {'prose_cases': n} for code, n in s['by_code'].items() if code in ERROR_CODES}
    held_fraction = s['holdout'] / s['cases'] if s['cases'] else 0.0
    return SuiteOutput(
        metrics={'cases': s['cases'], 'prose_cases': s['prose_cases'],
                 'format_problems': len(problems), 'holdout_fraction': round(held_fraction, 3),
                 **{f'subset.{k}': v for k, v in s['by_subset'].items()}},
        by_code=by_code,
        gates=[Gate('format_problems', len(problems), '==', 0),
               Gate('prose_cases', s['prose_cases'], '>=', MIN_PROSE_CASES),
               Gate('holdout_fraction', held_fraction, '>=', 0.19)],
        notes=problems[:20],
    )


SUITE = Suite('e1-corpus', 'E1 gold-set health: format, 100+ prose cases, 20% holdout', run)

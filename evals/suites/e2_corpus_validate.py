"""E2 on the E1 corpus with the deterministic continuity checks (free).
See ``evals/e2/corpus.py``."""

from e2 import corpus
from harness import Suite


def run(ctx):
    cases, excluded = corpus.select()
    flags = corpus.run(cases, corpus.validate_detector, ctx.work_dir)
    return corpus.suite_output('validate (continuity checks)', cases, excluded, *flags)


SUITE = Suite('e2-corpus-validate', 'Deterministic continuity checks vs real E1 errors', run)

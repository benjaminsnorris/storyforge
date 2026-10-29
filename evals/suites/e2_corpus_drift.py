"""E2 on the E1 corpus with the timeline drift check, after reading every
scene's time cues (API calls, recorded). See ``evals/e2/corpus.py``."""

import e2
from e2 import corpus
from harness import Suite


def run(ctx):
    cases, excluded = corpus.select()
    flags = corpus.run(cases, e2.drift_check, ctx.work_dir, prepare_tree=corpus.bootstrap_cues)
    return corpus.suite_output('drift-check (timeline)', cases, excluded, *flags)


SUITE = Suite('e2-corpus-drift', 'Timeline drift check vs real E1 errors', run)

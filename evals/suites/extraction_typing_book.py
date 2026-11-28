"""Extraction typing on real scenes where gear was typed fixed (#788):
private, like the gate set. See `evals/extraction_typing`."""

from __future__ import annotations

import os

import extraction_typing
from harness import Suite

NAME = 'extraction-typing-book'

#: The recorded values, each held exactly (#488); None until recorded
FLOORS: dict[str, float | None] = {
    'state_right': None,
    'fixed_right': None,
    'missing': None,
}


def run(ctx):
    scenes = extraction_typing.book_scenes(ctx.work_dir)
    extracted = {s['id']: extraction_typing.read(s['id'], s['prose'], s['prompt'],
                                                 os.path.join(ctx.work_dir, 'logs', s['id']))
                 for s in scenes}
    # the labels quote the book: notes name them by number
    metrics, notes = extraction_typing.score(scenes, extracted, quote_labels=False)
    return extraction_typing.output(metrics, notes, FLOORS)


def _cassettes(run: str) -> str:
    return os.path.join(extraction_typing.set_dir(), 'cassettes', *([run] if run else []), NAME)


SUITE = Suite(NAME, 'Extraction types gear as state on real scenes where it slipped (private; '
              '#788)', run, cassettes=_cassettes)

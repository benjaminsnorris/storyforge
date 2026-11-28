"""Extraction typing on invented scenes (#788): see `evals/extraction_typing`."""

from __future__ import annotations

import json
import os

import extraction_typing
from harness import EVALS_DIR, Suite

NAME = 'extraction-typing'
CASES_FILE = os.path.join(EVALS_DIR, 'fixtures', 'extraction-typing', 'cases.json')

#: The recorded values, each held exactly (#488); None until recorded
FLOORS: dict[str, float | None] = {
    'state_right': None,
    'fixed_right': None,
    'missing': None,
}


def _registries(cases: dict) -> str:
    return '## Characters\n' + '\n'.join(f'- {c["id"]}: {c["name"]}'
                                         for c in cases['characters'])


def run(ctx):
    from storyforge.extract import build_commitments_prompt
    with open(CASES_FILE, encoding='utf-8') as f:
        cases = json.load(f)
    extracted = {}
    for scene in cases['scenes']:
        details = {k: scene[k] for k in ('title', 'pov', 'location')}
        prompt = build_commitments_prompt(scene['id'], scene['prose'], details,
                                          registries_text=_registries(cases),
                                          known=[], recorded=[])
        extracted[scene['id']] = extraction_typing.read(
            scene['id'], scene['prose'], prompt, os.path.join(ctx.work_dir, 'logs'))
    metrics, notes = extraction_typing.score(cases['scenes'], extracted)
    return extraction_typing.output(metrics, notes, FLOORS)


SUITE = Suite(NAME, 'Extraction types worn, carried and held gear as state, traits as fixed: '
              'invented scenes (#788)', run)

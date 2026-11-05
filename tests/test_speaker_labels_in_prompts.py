"""#513: the prompts that write a brief's scripted lines ask for the
speaker label the gate's speaker check reads (`Name: "line"`, #511), so a
wrong-speaker tag goes to the fixer instead of the author."""

import os

from storyforge import prompts_elaborate as pe
from storyforge.extract import build_brief_parallel_prompt

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_extraction_asks_for_labelled_lines():
    p = build_brief_parallel_prompt('s', 'Text.', {}, {}, {})
    line = next(x for x in p.splitlines() if x.startswith('- key_dialogue'))
    assert '`Name: "line"`' in line and 'no possessive' in line


def test_the_briefs_stage_asks_for_labelled_lines(project_dir):
    p = pe.build_briefs_prompt(project_dir, PLUGIN)
    line = next(x for x in p.splitlines() if x.startswith('- **key_dialogue**'))
    assert '`Name: "line"`' in line and 'repeated after each `;`' in line

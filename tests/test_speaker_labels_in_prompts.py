"""#513: every prompt that writes a brief's scripted lines asks for the
speaker label the gate's speaker check reads (`Name: "line"`, #511), in one
wording (`speaker_labels.LABEL_RULE`), so a wrong-speaker tag goes to the
fixer instead of the author; the prompts that read those lines into prose
say what the label means (`speaker_labels.LABEL_READING`)."""

import os

from storyforge import gate, hone
from storyforge import prompts_elaborate as pe
from storyforge.speaker_labels import LABEL_READING, LABEL_RULE

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _set_dialogue(project_dir, scene_id, value):
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    header = lines[0].split('|')
    col = header.index('key_dialogue')
    for i, line in enumerate(lines):
        cells = line.split('|')
        if cells[0] == scene_id:
            cells[col] = value
            lines[i] = '|'.join(cells)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


# -- the prompts that write scripted lines ----------------------------------

def test_extraction_phase_3_asks_for_labelled_lines():
    from storyforge.extract import build_brief_parallel_prompt
    p = build_brief_parallel_prompt('s', 'Text.', {}, {}, {})
    line = next(x for x in p.splitlines() if x.startswith('- key_dialogue'))
    assert LABEL_RULE in line


def test_the_briefs_stage_asks_for_labelled_lines(project_dir):
    p = pe.build_briefs_prompt(project_dir, PLUGIN)
    line = next(x for x in p.splitlines() if x.startswith('- **key_dialogue**'))
    assert LABEL_RULE in line


def test_enrich_asks_for_labelled_lines(project_dir):
    from storyforge.enrich import build_enrich_prompt
    p = build_enrich_prompt('act1-sc01', project_dir, fields=['key_dialogue'], force=True)
    line = next(x for x in p.splitlines() if 'KEY_DIALOGUE:' in x)
    assert LABEL_RULE in line


def test_hone_brief_rewrites_ask_for_labelled_lines():
    values = {'key_actions': 'Reviews maps;Finds anomaly;Consults Tessa;Files it'}
    assert LABEL_RULE in hone.build_concretize_prompt('s', ['key_actions'], values)
    assert LABEL_RULE in hone.build_trim_prompt(
        's', [{'field': 'key_actions', 'issue': 'overspecified'}], values, 1600)
    assert LABEL_RULE in hone.build_evaluation_fix_prompt(
        's', ['key_actions'], values, 'Too abstract')


# revise's source-drift fix: tests/test_source_range.py
# (TestRange.test_revise_fix_refuses_an_out_of_range_scene)


# -- the prompts that read them ----------------------------------------------

def test_the_drafting_prompt_says_what_a_label_means(project_dir):
    from storyforge.prompts import build_scene_prompt_from_briefs
    p = build_scene_prompt_from_briefs('act1-sc01', project_dir, PLUGIN, 'full')
    checklist = p.split('**Key dialogue checklist', 1)[1]
    assert LABEL_READING in checklist.split('\n', 1)[0]
    assert '- [ ] Dorren privately: "Acceptable is not the same as explained"' in checklist


def test_the_revision_prompt_says_what_a_label_means(project_dir):
    from storyforge.revision import build_revision_prompt
    p = build_revision_prompt('prose-tightening', 'Tighten prose', 'act1-sc01', project_dir)
    section = p.split('## Intent-Beat Protection', 1)[1]
    assert LABEL_READING in section.split('**act1-sc01:**', 1)[0]


# -- what the prompts ask for is what the gate reads -------------------------

def test_a_line_in_the_taught_form_parses_to_its_speaker(project_dir):
    """The form LABEL_RULE teaches, `Name: "line"` with the name as in
    characters.csv and the label repeated after each `;`, is read by
    `gate._brief_lines` as that character's line, for a full name, a
    one-word alias and the same speaker twice."""
    assert 'Name: "line"' in LABEL_RULE
    _set_dialogue(project_dir, 'act1-sc01',
                  'Dorren Hayle: "The eastern readings are within acceptable variance";'
                  'Tessa: "Then why are you still looking at them?";'
                  'Dorren Hayle: "Acceptable is not the same as explained"')
    lines = [(s.text, s.speaker) for s in gate._brief_lines(project_dir, 'act1-sc01')]
    assert lines == [
        ('The eastern readings are within acceptable variance', 'dorren-hayle'),
        ('Then why are you still looking at them?', 'tessa-merrin'),
        ('Acceptable is not the same as explained', 'dorren-hayle'),
    ]


def test_an_unlabelled_line_has_no_speaker(project_dir):
    """The rule's "leave the label off" case: matched, speaker not checked."""
    _set_dialogue(project_dir, 'act1-sc01',
                  'Tessa: "Then why are you still looking at them?";'
                  '"The eastern readings are within acceptable variance"')
    labelled, unlabelled = gate._brief_lines(project_dir, 'act1-sc01')
    assert labelled.speaker == 'tessa-merrin'
    assert unlabelled.speaker is None and unlabelled.why == gate._NO_LABEL

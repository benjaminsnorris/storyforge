"""#513: every prompt that writes a brief's scripted lines asks for the
speaker label the gate's speaker check reads (`Name: "line"`, #511), in one
wording (`speaker_labels`), so a wrong-speaker tag goes to the fixer instead
of the author; the prompts that read those lines into prose say what the
label means. Prose books only: a graphic novel's key_dialogue is matched
verbatim in the panel script."""

import os
import re
import unicodedata

import pytest

from storyforge import gate, hone, speaker_labels
from storyforge import prompts_elaborate as pe
from storyforge.speaker_labels import LABEL_KEEP, LABEL_READING, LABEL_RULE

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(PLUGIN, 'scripts', 'lib', 'python', 'storyforge')


def _set_brief(project_dir, scene_id, **cols):
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    header = lines[0].split('|')
    for i, line in enumerate(lines):
        cells = line.split('|')
        if cells[0] == scene_id:
            for col, value in cols.items():
                cells[header.index(col)] = value
            lines[i] = '|'.join(cells)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _set_dialogue(project_dir, scene_id, value):
    _set_brief(project_dir, scene_id, key_dialogue=value)


def _add_characters(project_dir, *rows):
    path = os.path.join(project_dir, 'reference', 'characters.csv')
    with open(path, 'a', encoding='utf-8') as f:
        for row in rows:
            f.write(row + '\n')


def _graphic_novel(monkeypatch):
    from storyforge import common
    monkeypatch.setattr(common, 'get_medium', lambda project_dir: 'graphic-novel')


# -- the wording -------------------------------------------------------------

def test_the_rule_names_what_the_gate_reads():
    """P-1: the label starts with a name, id or alias exactly as the
    registry writes it (a registry name with a title keeps it), nothing
    added before it; one character per label."""
    assert 'Name: "line"' in LABEL_RULE
    assert "name, id or one of its aliases exactly as characters.csv writes it" in LABEL_RULE
    assert 'nothing added before it, no possessive' in LABEL_RULE
    assert 'no title' not in LABEL_RULE


def test_the_reading_note_says_the_label_is_not_prose():
    """P-3: "it" can't be read as the line."""
    assert 'write the line as their speech' in LABEL_READING
    assert 'never write the `Name:` label itself into the prose' in LABEL_READING


def test_the_keep_rule_never_guesses():
    """P-2: a rewrite keeps a label and adds one only from the text it has."""
    assert 'exactly as it is' in LABEL_KEEP and 'never guess a speaker' in LABEL_KEEP


def test_has_label():
    assert speaker_labels.has_label('Dorren privately: "Acceptable is not explained"')
    assert speaker_labels.has_label('"Hold the line" — Tessa')
    assert not speaker_labels.has_label('"The eastern readings are within variance"')
    assert not speaker_labels.has_label('Reviews maps;Finds anomaly')


def test_the_cast_list(project_dir):
    cast = speaker_labels.cast_list(project_dir)
    assert '- dorren-hayle: Dorren Hayle (aliases: Dorren; Dr. Hayle; Hayle)' in cast
    assert '- pell: Pell' in cast


# -- the prompts that write scripted lines from the text or plan --------------

def test_extraction_phase_3_asks_for_labelled_lines():
    from storyforge.extract import build_brief_parallel_prompt
    p = build_brief_parallel_prompt('s', 'Text.', {}, {}, {})
    line = next(x for x in p.splitlines() if x.startswith('- key_dialogue'))
    assert LABEL_RULE in line


def test_the_briefs_stage_asks_for_labelled_lines(project_dir):
    p = pe.build_briefs_prompt(project_dir, PLUGIN)
    line = next(x for x in p.splitlines() if x.startswith('- **key_dialogue**'))
    assert LABEL_RULE in line


@pytest.mark.parametrize('field', ['key_dialogue', 'key_actions'])
def test_enrich_asks_for_labelled_lines(project_dir, field):
    """P-5: either field can hold a quoted line; the rule is said once."""
    from storyforge.enrich import build_enrich_prompt
    p = build_enrich_prompt('act1-sc01', project_dir, fields=[field], force=True)
    assert p.count(LABEL_RULE) == 1
    both = build_enrich_prompt('act1-sc01', project_dir,
                               fields=['key_dialogue', 'key_actions'], force=True)
    assert both.count(LABEL_RULE) == 1


def test_enrich_without_those_fields_has_no_rule(project_dir):
    from storyforge.enrich import build_enrich_prompt
    p = build_enrich_prompt('act1-sc01', project_dir, fields=['goal', 'outcome'], force=True)
    assert LABEL_RULE not in p


# -- the prompts that rewrite a brief without the text to tell who speaks ----

def test_hone_brief_rewrites_keep_labels_with_the_cast(project_dir):
    """P-2: the cast and LABEL_KEEP, never LABEL_RULE (no prose to judge
    from)."""
    labels = speaker_labels.keep_section(project_dir)
    values = {'key_actions': 'Reviews maps;Finds anomaly;Consults Tessa;Files it'}
    for p in (hone.build_concretize_prompt('s', ['key_actions'], values, labels=labels),
              hone.build_trim_prompt('s', [{'field': 'key_actions', 'issue': 'overspecified'}],
                                     values, 1600, labels=labels),
              hone.build_evaluation_fix_prompt('s', ['key_actions'], values, 'Too abstract',
                                               labels=labels)):
        assert LABEL_KEEP in p and LABEL_RULE not in p
        assert '## Cast (characters.csv)' in p and '- tessa-merrin: Tessa Merrin' in p


def _hone_prompts(project_dir, tmp_path, monkeypatch):
    """The prompts hone --domain briefs sends for an evaluation finding on
    act1-sc01's key_dialogue."""
    from storyforge import api
    sent = []
    monkeypatch.setattr(api, 'invoke_to_file', lambda prompt, *a, **k: sent.append(prompt))
    monkeypatch.setattr(api, 'extract_text_from_file', lambda *a, **k: '')
    findings = tmp_path / 'findings.csv'
    findings.write_text('scene_id|target_file|fields|guidance\n'
                        'act1-sc01|scene-briefs.csv|key_dialogue|Sharpen the lines\n')
    hone.hone_briefs(os.path.join(project_dir, 'reference'), project_dir,
                     scene_ids=['act1-sc01'], model='m', log_dir=str(tmp_path / 'logs'),
                     findings_file=str(findings))
    return sent


def test_hone_briefs_sends_the_cast(project_dir, tmp_path, monkeypatch):
    sent = _hone_prompts(project_dir, tmp_path, monkeypatch)
    assert sent and all(LABEL_KEEP in p and '## Cast (characters.csv)' in p for p in sent)


def test_hone_briefs_on_a_graphic_novel_has_no_labels(project_dir, tmp_path, monkeypatch):
    """GN-1: the script check matches key_dialogue verbatim."""
    _graphic_novel(monkeypatch)
    sent = _hone_prompts(project_dir, tmp_path, monkeypatch)
    assert sent and not any(LABEL_KEEP in p or '## Cast' in p for p in sent)


def test_enrich_on_a_graphic_novel_has_no_rule(project_dir, monkeypatch):
    """GN-1."""
    from storyforge.enrich import build_enrich_prompt
    _graphic_novel(monkeypatch)
    p = build_enrich_prompt('act1-sc01', project_dir, fields=['key_dialogue'], force=True)
    assert p and LABEL_RULE not in p


def test_keep_section_is_empty_for_a_graphic_novel(project_dir, monkeypatch):
    _graphic_novel(monkeypatch)
    assert speaker_labels.keep_section(project_dir) == ''


# revise's source-drift fix: tests/test_source_range.py
# (TestFidelity.test_revise_fix_refuses_an_out_of_range_scene)


# -- no prompt that writes these fields can miss the rule ---------------------

#: Every module that names key_dialogue or key_actions, by what it does with
#: them. A new module naming either fails `test_every_module_is_classified`
#: until it is put here, so a new prompt can't miss the rule unseen.
WRITES = {   # builds a prompt whose model writes or rewrites the fields
    'prompts_elaborate.py', 'extract.py', 'enrich.py', 'hone.py', 'cmd_revise.py',
}
READS_INTO_PROSE = {'prompts.py', 'revision.py'}
GRAPHIC_NOVEL = {   # key_dialogue is matched verbatim in the panel script
    'cmd_extract_gn.py', 'prompts_gn.py', 'prompts_elaborate_gn.py',
    'prompts_page_prompt.py', 'script_format.py',
}
NO_PROMPT_WRITES = {   # data, checks, scoring, or source text shown as context
    'checker.py', 'brief_names.py', 'cmd_check.py', 'cmd_enrich.py', 'elaborate.py', 'gate.py',
    'must.py',
    'prompts_source.py', 'schema.py', 'scoring_boundary.py', 'scoring.py',
    'scoring_story_power.py', 'source_fidelity.py', 'speaker_labels.py', 'structural.py',
    'scoring/brief-fidelity.md', 'scoring/source-fidelity.md',
}


def _naming_modules():
    found = set()
    for base, rel in ((PKG, ''), (os.path.join(PLUGIN, 'scripts', 'prompts'), None)):
        for dirpath, _, files in os.walk(base):
            for name in files:
                if not name.endswith(('.py', '.md')):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding='utf-8') as f:
                    if re.search(r'key_(dialogue|actions)', f.read(), re.I):
                        found.add(os.path.relpath(path, base))
    return found


def test_every_module_is_classified():
    """P-5's guard: every module naming key_dialogue or key_actions is in
    one of the lists above."""
    known = WRITES | READS_INTO_PROSE | GRAPHIC_NOVEL | NO_PROMPT_WRITES
    assert _naming_modules() - known == set()


@pytest.mark.parametrize('module', sorted(WRITES))
def test_every_writer_carries_the_rule(module):
    with open(os.path.join(PKG, module), encoding='utf-8') as f:
        text = f.read()
    assert re.search(r'\b(LABEL_RULE|keep_section)\b', text), module


@pytest.mark.parametrize('module', sorted(READS_INTO_PROSE))
def test_every_reader_carries_the_reading(module):
    with open(os.path.join(PKG, module), encoding='utf-8') as f:
        assert 'LABEL_READING' in f.read(), module


@pytest.mark.parametrize('module', sorted(GRAPHIC_NOVEL))
def test_no_graphic_novel_prompt_carries_it(module):
    with open(os.path.join(PKG, module), encoding='utf-8') as f:
        assert not re.search(r'LABEL_(RULE|KEEP|READING)|speaker_labels', f.read()), module


# -- the prompts that read them -----------------------------------------------

def test_the_drafting_prompt_says_what_a_label_means(project_dir):
    from storyforge.prompts import build_scene_prompt_from_briefs
    p = build_scene_prompt_from_briefs('act1-sc01', project_dir, PLUGIN, 'full')
    checklist = p.split('**Key dialogue checklist', 1)[1]
    assert LABEL_READING in checklist.split('\n', 1)[0]
    assert '- [ ] Dorren privately: "Acceptable is not the same as explained"' in checklist


def test_a_label_in_key_actions_alone_gets_the_note(project_dir):
    """P-4: a labelled quote in key_actions, with no key_dialogue."""
    from storyforge.prompts import build_scene_prompt_from_briefs
    _set_brief(project_dir, 'act1-sc01', key_dialogue='',
               key_actions='Reviews maps;Tessa: "You filed it as error?";Makes a note')
    p = build_scene_prompt_from_briefs('act1-sc01', project_dir, PLUGIN, 'full')
    assert LABEL_READING in p and '**Key dialogue checklist' not in p


def test_no_label_no_note(project_dir):
    from storyforge.prompts import build_scene_prompt_from_briefs
    p = build_scene_prompt_from_briefs('act1-sc02', project_dir, PLUGIN, 'full')
    assert '**Key dialogue checklist' in p and LABEL_READING not in p


def test_the_revision_prompt_says_what_a_label_means(project_dir):
    from storyforge.revision import build_revision_prompt
    p = build_revision_prompt('prose-tightening', 'Tighten prose', 'act1-sc01', project_dir)
    section = p.split('## Intent-Beat Protection', 1)[1]
    assert LABEL_READING in section.split('**act1-sc01:**', 1)[0]
    unlabelled = build_revision_prompt('prose-tightening', 'Tighten prose', 'act1-sc02',
                                       project_dir)
    assert LABEL_READING not in unlabelled


# -- what the prompts ask for is what the gate reads ---------------------------

def _speakers(project_dir, value):
    _set_dialogue(project_dir, 'act1-sc01', value)
    return [(s.text, s.speaker) for s in gate._brief_lines(project_dir, 'act1-sc01')]


def test_a_line_in_the_taught_form_parses_to_its_speaker(project_dir):
    """`Name: "line"`, the label repeated after each `;`: a full name, a
    one-word alias and the same speaker twice."""
    assert _speakers(project_dir,
                     'Dorren Hayle: "The eastern readings are within acceptable variance";'
                     'Tessa: "Then why are you still looking at them?";'
                     'Dorren Hayle: "Acceptable is not the same as explained"') == [
        ('The eastern readings are within acceptable variance', 'dorren-hayle'),
        ('Then why are you still looking at them?', 'tessa-merrin'),
        ('Acceptable is not the same as explained', 'dorren-hayle'),
    ]


def test_a_titled_registry_name_and_an_alias_parse(project_dir):
    """P-1: a registry name with a title, written as the registry writes it,
    is that character; the bare surname is the character whose alias it is,
    and a titled alias (`Dr. Hayle`) is its character's."""
    _add_characters(project_dir, 'mr-carver|Mr. Carver||minor|',
                    'june-carver|June Carver|Carver|supporting|')
    assert _speakers(project_dir,
                     'Mr. Carver: "Sit down and open the ledger";'
                     'Carver: "I would rather stand, thank you";'
                     'Dr. Hayle: "The readings are within variance"') == [
        ('Sit down and open the ledger', 'mr-carver'),
        ('I would rather stand, thank you', 'june-carver'),
        ('The readings are within variance', 'dorren-hayle'),
    ]


def test_a_label_after_and_names_its_speaker(project_dir):
    """G-2: `— and Croy: "b"` is Croy's."""
    assert _speakers(project_dir,
                     'Dorren: "The readings are within variance" — and Tessa: '
                     '"Then why are you still looking?"') == [
        ('The readings are within variance', 'dorren-hayle'),
        ('Then why are you still looking?', 'tessa-merrin'),
    ]


def test_a_name_of_any_length(project_dir):
    """G-3: e2-carol's `Ghost of Christmas Past`, in a label and a tag."""
    _add_characters(project_dir,
                    'ghost-past|Ghost of Christmas Past|the Ghost of Christmas Past|supporting|')
    assert _speakers(project_dir, 'Ghost of Christmas Past: "Rise and walk with me"') == [
        ('Rise and walk with me', 'ghost-past')]
    cast = gate._cast(project_dir)
    assert gate._tag_speaker('said the Ghost of Christmas Past', cast.names) \
        == 'the ghost of christmas past'


def test_a_label_naming_no_one_in_the_cast_says_so(project_dir):
    """G-4/SF-4: not "the brief names no speaker"."""
    _set_dialogue(project_dir, 'act1-sc01',
                  'Council: "We appreciate your diligence, Cartographer."')
    [line] = gate._brief_lines(project_dir, 'act1-sc01')
    assert line.speaker is None
    assert line.why == 'the brief\'s label "Council" names no one in characters.csv'


def test_an_unlabelled_line_has_no_speaker(project_dir):
    """The rule's "leave the label off" case: matched, speaker not checked."""
    _set_dialogue(project_dir, 'act1-sc01',
                  'Tessa: "Then why are you still looking at them?";'
                  '"The eastern readings are within acceptable variance"')
    labelled, unlabelled = gate._brief_lines(project_dir, 'act1-sc01')
    assert labelled.speaker == 'tessa-merrin'
    assert unlabelled.speaker is None and unlabelled.why == gate._NO_LABEL


def test_an_unquoted_line_loses_its_label(project_dir):
    """G-1: `Dorren: words` matches prose that says the words; still no
    speaker (an unquoted line's boundary is a guess)."""
    _set_dialogue(project_dir, 'act1-sc01', 'Dorren: Acceptable is not the same as explained;'
                                            'Council: we appreciate your diligence')
    lines = gate._brief_lines(project_dir, 'act1-sc01')
    assert [(x.text, x.speaker) for x in lines] == [
        ('Acceptable is not the same as explained', None),
        ('Council: we appreciate your diligence', None)]


def test_a_decomposed_name_matches(project_dir):
    """NFC: a label typed with a combining accent is the composed name's."""
    _add_characters(project_dir, unicodedata.normalize('NFC', 'jose|José Ortega|José|minor|'))
    label = unicodedata.normalize('NFD', 'José')
    assert _speakers(project_dir, f'{label}: "Bring the lamp down here"') == [
        ('Bring the lamp down here', 'jose')]

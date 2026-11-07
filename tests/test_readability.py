"""Reading level (Flesch-Kincaid) in score, and key decisions in every
revision prompt.

Found on the Telemachy pilot (storyforge-evals F-170): its key decisions set
grade 5-7, the draft measured 3.4 by hand, and nothing in Storyforge could
measure it; and revise's passes, unlike drafting (#596), never read the key
decisions that set it.
"""

import os

import pytest

from storyforge import readability as rd
from storyforge.common import get_plugin_dir

KD_MARK = 'KD-001: Magic System'          # the fixture's key decisions


# --- the measure ---

@pytest.mark.parametrize('word,n', [
    ('the', 1), ('cat', 1), ('table', 2), ('settled', 2), ('fire', 1),
    ('everyone', 3), ('Ithaca', 3), ('assembly', 3), ('wide-winged', 2),
    ("don't", 1), ('', 0), ('123', 0),
])
def test_count_syllables(word, n):
    assert rd.count_syllables(word) == n


def test_sentences_end_at_punctuation_quotes_and_paragraphs():
    text = ('# Chapter One\n\n"Go home," he said. She went!\n\n'
            'A paragraph with no stop\n\n* * *\n\nIs it *done*? "Yes."')
    assert rd.split_sentences(text) == [
        '"Go home," he said.', 'She went!', 'A paragraph with no stop',
        'Is it done?', '"Yes."']


def test_grade_is_flesch_kincaid():
    m = rd.measure('The cat sat on the mat. The dog ran.')
    assert (m.words, m.sentences, m.syllables) == (9, 2, 9)
    assert m.grade == pytest.approx(0.39 * 4.5 + 11.8 * 1.0 - 15.59)


def test_no_words_has_no_grade():
    assert rd.measure('').grade is None
    assert rd.measure('* * *').grade is None


def test_narration_leaves_out_quoted_dialogue():
    s = rd.measure_scene('x', '"Extraordinarily unacceptable circumstances," he said. He sat.')
    assert s.all.words == 7
    assert s.narration.words == 4


def test_book_totals_pool_counts_not_grades():
    a = rd.SceneReadability('a', rd.Readability(10, 1, 10), rd.EMPTY)
    b = rd.SceneReadability('b', rd.Readability(30, 3, 45), rd.EMPTY)
    total, _ = rd.book_totals([a, b])
    assert total == rd.Readability(40, 4, 55)


# --- the target ---

@pytest.mark.parametrize('value,target', [
    ('', None), ('6', (6.0, 6.0)), ('5-7', (5.0, 7.0)), ('5–7', (5.0, 7.0)),
    ('grade 5 to 7', (5.0, 7.0)), ('7-5', (5.0, 7.0)), ('6.5', (6.5, 6.5)),
])
def test_parse_target(value, target):
    assert rd.parse_target(value) == target


@pytest.mark.parametrize('value', ['teen', '5-7-9', 'grade five', 'YA'])
def test_parse_target_rejects_what_is_not_a_grade(value):
    with pytest.raises(ValueError, match='project.reading_level'):
        rd.parse_target(value)


@pytest.mark.parametrize('grade,v', [(4.9, 'below'), (5.0, 'within'), (7.0, 'within'),
                                     (7.1, 'above'), (None, '')])
def test_verdict(grade, v):
    assert rd.verdict(grade, (5.0, 7.0)) == v
    assert rd.verdict(grade, None) == ''


def test_summary_names_scenes_off_target():
    low = rd.SceneReadability('low', rd.measure('The cat sat. The dog ran.'), rd.EMPTY)
    lines = rd.summary_lines([low], (5.0, 7.0))
    assert 'target grade 5-7: below' in lines[0]
    assert '1 scene(s) below the target: low' in lines[1]
    assert 'no target' in rd.summary_lines([low], None)[0]


def test_write_csv_has_a_book_row(tmp_path):
    rows = [rd.measure_scene('a', 'The cat sat on the mat.'),
            rd.measure_scene('b', 'Extraordinary circumstances necessitate deliberation.')]
    path = tmp_path / 'readability.csv'
    rd.write_csv(str(path), rows, (5.0, 7.0))
    lines = path.read_text().splitlines()
    assert lines[0] == rd.CSV_HEADER
    assert [l.split('|')[0] for l in lines[1:]] == ['a', 'b', 'BOOK']
    assert lines[3].split('|')[1] == '10'   # pooled words (6 + 4)


# --- score ---

def _set_target(project_dir, value):
    path = os.path.join(project_dir, 'storyforge.yaml')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    text = text.replace('project:\n', f'project:\n  reading_level: "{value}"\n', 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def test_score_readability_prints_without_writing(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _set_target(project_dir, '5-7')
    before = set(os.listdir(os.path.join(project_dir, 'working')))
    cmd_score.main(['--readability'])
    out = capsys.readouterr().out
    assert 'act1-sc01' in out
    assert 'Reading level: Flesch-Kincaid grade' in out and 'target grade 5-7' in out
    assert set(os.listdir(os.path.join(project_dir, 'working'))) == before


def test_score_bad_reading_level_is_an_error(project_dir, monkeypatch):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _set_target(project_dir, 'teen')
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--readability'])
    assert e.value.code == 1


def test_scoring_cycle_writes_readability_csv(project_dir, plugin_dir, monkeypatch):
    from storyforge import cmd_score
    monkeypatch.setenv('STORYFORGE_PLUGIN_DIR', plugin_dir)
    monkeypatch.chdir(project_dir)
    for name in ('create_branch', 'ensure_branch_pushed', 'commit_and_push'):
        monkeypatch.setattr(f'storyforge.cmd_score.{name}', lambda *a, **k: None)
    cmd_score.main(['--deterministic'])
    scores = os.path.join(project_dir, 'working', 'scores')
    cycle = sorted(d for d in os.listdir(scores) if d.startswith('cycle-'))[-1]
    with open(os.path.join(scores, cycle, 'readability.csv')) as f:
        lines = f.read().splitlines()
    assert lines[0] == rd.CSV_HEADER
    assert lines[-1].startswith('BOOK|')
    # a measure, not a principle: never a scene-scores column
    with open(os.path.join(scores, cycle, 'scene-scores.csv')) as f:
        assert 'grade' not in f.readline()


# --- key decisions in the revision prompts ---

def _revision_prompt(project_dir, **kw):
    from storyforge.revision import build_revision_prompt
    return build_revision_prompt('prose-tightening', 'Tighten the prose.', 'act1-sc01',
                                 project_dir, **kw)


@pytest.mark.parametrize('kw', [{}, {'api_mode': True},
                                {'api_mode': True, 'system_context': True}])
def test_revision_pass_prompt_carries_key_decisions(project_dir, kw):
    prompt = _revision_prompt(project_dir, **kw)
    assert '## Key Decisions' in prompt and KD_MARK in prompt
    assert prompt.index('## Purpose') < prompt.index('## Key Decisions')


def test_revision_pass_prompt_leaves_out_template_key_decisions(project_dir):
    with open(os.path.join(get_plugin_dir(), 'templates', 'reference', 'key-decisions.md'),
              encoding='utf-8') as f:
        template = f.read()
    with open(os.path.join(project_dir, 'reference', 'key-decisions.md'), 'w',
              encoding='utf-8') as f:
        f.write(template)
    assert '## Key Decisions' not in _revision_prompt(project_dir, api_mode=True)
    os.remove(os.path.join(project_dir, 'reference', 'key-decisions.md'))
    assert '## Key Decisions' not in _revision_prompt(project_dir, api_mode=True)


def test_gn_revision_prompt_carries_key_decisions():
    from storyforge.prompts_gn import build_revision_prompt
    kw = dict(scene_id='s', scene_row={}, intent_row={}, brief_row={}, script_text='x',
              character_visuals='', location_visuals='', voice_profile_text='',
              score_findings=[], eval_findings=[])
    assert '# Key decisions' not in build_revision_prompt(**kw)
    assert 'Grade 5 to 7.' in build_revision_prompt(**kw, key_decisions='Grade 5 to 7.')

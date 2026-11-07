"""Reading level (Flesch-Kincaid) in score, and key decisions in every
revision prompt.

Found on the Telemachy pilot (storyforge-evals F-170): its key decisions set
grade 5-7, the draft measured 3.4 by hand, and nothing in Storyforge could
measure it; and revise's passes, unlike drafting (#596), never read the key
decisions that set it. Finding ids (T-, SF-, TD-, C-, CR-) are #616's review.
"""

import os

import pytest

from storyforge import readability as rd
from storyforge.common import get_plugin_dir

KD_MARK = 'KD-001: Magic System'          # the fixture's key decisions
#: the fixture's act1-sc01 still has legacy frontmatter; the others are prose
SCENE = 'act1-sc02'


# --- the measure ---

@pytest.mark.parametrize('word,n', [
    ('the', 1), ('cat', 1), ('table', 2), ('settled', 2), ('fire', 1),
    ('everyone', 3), ('Ithaca', 3), ('assembly', 3), ('wide-winged', 2),
    ("don't", 1), ('', 0), ('123', 0),
    # C-1/C-5: spoken endings are syllables, silent ones aren't
    ('wanted', 2), ('ended', 2), ('boxes', 2), ('wishes', 2), ('faces', 2),
    ('pages', 2), ('named', 1), ('hoped', 1), ('loved', 1),
])
def test_count_syllables(word, n):
    assert rd.count_syllables(word) == n


def test_sentences_end_at_punctuation_quotes_and_paragraphs():
    text = ('# Chapter One\n\n"Go home," he said. She went!\n\n'
            'A paragraph with no stop\n\n* * *\n\nIs it *done*? "Yes."')
    assert rd.split_sentences(text) == [
        '"Go home," he said.', 'She went!', 'A paragraph with no stop',
        'Is it done?', '"Yes."']


def test_crlf_and_bom_read_as_lf(tmp_path):
    # T-11: a BOM'd heading is still a heading; CRLF paragraphs still split
    text = '﻿# Chapter\r\n\r\nThe cat sat.\r\n\r\n* * *\r\n\r\nThe dog ran.'
    assert rd.split_sentences(text) == ['The cat sat.', 'The dog ran.']


def test_grade_is_flesch_kincaid():
    m = rd.measure('The cat sat on the mat. The dog ran.')
    assert (m.words, m.sentences, m.syllables) == (9, 2, 9)
    assert m.grade == pytest.approx(0.39 * 4.5 + 11.8 * 1.0 - 15.59)


def test_no_words_has_no_grade_or_rates():
    for text in ('', '* * *'):
        m = rd.measure(text)
        assert m.grade is None and m.words_per_sentence is None
        assert m.syllables_per_word is None


def test_narration_leaves_out_quoted_dialogue():
    s = rd.measure_scene('x', '"Extraordinarily unacceptable circumstances," he said. He sat.')
    assert s.whole.words == 7
    assert s.narration.words == 4


def test_a_quote_that_ends_its_sentence_leaves_the_break():
    # C-4: the narration either side isn't read as one long sentence
    narration = rd.measure(rd.narration_text('He turned. "Go now." Then he left.'))
    assert narration.sentences == 2


def test_pooled_counts_not_grades():
    a = rd.SceneReadability('a', rd.Readability(10, 1, 10), rd.EMPTY)
    b = rd.SceneReadability('b', rd.Readability(30, 3, 45), rd.EMPTY)
    whole, _ = rd.pooled([a, b])
    assert whole == rd.Readability(40, 4, 55)


def test_adding_something_else_is_a_type_error():
    with pytest.raises(TypeError):
        rd.EMPTY + 1   # TD-1


# --- the target ---

@pytest.mark.parametrize('value,target', [
    ('', None), ('null', None), ('~', None), ('NULL', None),   # SF-7
    ('6', (6.0, 6.0)), ('6th', (6.0, 6.0)), ('grade 6', (6.0, 6.0)),
    ('5-7', (5.0, 7.0)), ('5–7', (5.0, 7.0)), ('grade 5 to 7', (5.0, 7.0)),
    ('7-5', (5.0, 7.0)), ('6.5', (6.5, 6.5)), ('5th-7th', (5.0, 7.0)),
])
def test_parse_target(value, target):
    assert rd.parse_target(value) == target


@pytest.mark.parametrize('value', ['teen', '5-7-9', 'grade five', 'YA', '5 6', '-5',
                                   'toto 6'])
def test_parse_target_rejects_what_is_not_a_grade(value):
    with pytest.raises(ValueError, match='project.reading_level'):
        rd.parse_target(value)


@pytest.mark.parametrize('grade,v', [(4.9, 'below'), (5.0, 'within'), (7.0, 'within'),
                                     (7.1, 'above'), (None, '')])
def test_verdict(grade, v):
    assert rd.verdict(grade, rd.ReadingTarget(5.0, 7.0)) == v
    assert rd.verdict(grade, None) == ''


def test_target_names_itself():
    assert str(rd.ReadingTarget(5.0, 7.0)) == 'grade 5-7'
    assert str(rd.ReadingTarget(6.0, 6.0)) == 'grade 6'


def _measured(*texts, unmeasured=None):
    rows = [rd.measure_scene(f's{i}', t) for i, t in enumerate(texts)]
    return rd.Measured(rows, unmeasured or {})


def test_summary_names_scenes_off_target():
    lines = rd.summary_lines(_measured('The cat sat. The dog ran.'), rd.ReadingTarget(5, 7))
    assert 'target grade 5-7: below' in lines[0]
    assert '1 scene(s) below the target: s0' in lines[1]
    assert 'no target' in rd.summary_lines(_measured('The cat sat.'), None)[0]


def test_summary_names_scenes_it_could_not_measure():
    # SF-4: silence would read as "measured and fine"
    lines = rd.summary_lines(_measured('The cat sat.', unmeasured={'gone': 'no prose'}),
                             rd.ReadingTarget(5, 7))
    assert lines[-1] == 'WARNING: reading level not measured for 1 scene(s): gone (no prose)'


def test_write_csv(tmp_path):
    rows = [rd.measure_scene('a', 'The cat sat on the mat.'),
            rd.measure_scene('b', 'Extraordinary circumstances necessitate deliberation.')]
    path = tmp_path / 'readability.csv'
    rd.write_csv(str(path), rows, rd.ReadingTarget(5.0, 7.0))
    raw = path.read_bytes()
    assert b'\r' not in raw
    lines = raw.decode().splitlines()
    assert lines[0] == rd.CSV_HEADER
    cells = [l.split('|') for l in lines[1:]]
    assert [c[0] for c in cells] == ['a', 'b', 'ALL']
    assert cells[2][1] == '10'                      # pooled words (6 + 4)
    assert cells[0][-1] == 'below' and cells[1][-1] == 'above'   # T-15
    rd.write_csv(str(path), rows, None)
    assert all(l.endswith('|') for l in path.read_text().splitlines()[1:])


# --- measure_scenes: what it can't measure, it names ---

def _scene(project_dir, sid):
    return os.path.join(project_dir, 'scenes', f'{sid}.md')


def test_measure_scenes_names_missing_unreadable_and_empty(project_dir):
    with open(_scene(project_dir, 'act1-sc01'), 'wb') as f:
        f.write(b'\xff\xfe not utf-8')
    with open(_scene(project_dir, 'act2-sc01'), 'w') as f:
        f.write('# Heading only\n\n* * *\n')
    m = rd.measure_scenes([SCENE, 'act1-sc01', 'act2-sc01', 'no-such'], project_dir)
    assert [r.scene_id for r in m.rows] == [SCENE]
    assert m.unmeasured == {'act1-sc01': "can't be read (UnicodeDecodeError)",
                            'act2-sc01': 'no prose', 'no-such': 'no scene file'}


def test_illustration_markers_are_not_counted(project_dir):
    # T-6: the interior-illustration invariant
    before = rd.measure_scenes([SCENE], project_dir).rows[0]
    with open(_scene(project_dir, SCENE), 'a', encoding='utf-8') as f:
        f.write('\n\n![[illus:the-long-road]]\n')
    assert rd.measure_scenes([SCENE], project_dir).rows[0] == before


# --- score ---

def _set_target(project_dir, value):
    path = os.path.join(project_dir, 'storyforge.yaml')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    assert 'project:\n' in text
    text = text.replace('project:\n', f'project:\n  reading_level: "{value}"\n', 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _tree(root):
    return {os.path.join(d, n): os.path.getmtime(os.path.join(d, n))
            for d, _, files in os.walk(root) if '.git' not in d for n in files}


def _forbid_spending(monkeypatch):
    """Branches, commits and API calls fail the test."""
    def boom(*a, **k):
        raise AssertionError('nothing may be spent or written')
    for name in ('create_branch', 'ensure_branch_pushed', 'commit_and_push'):
        monkeypatch.setattr(f'storyforge.cmd_score.{name}', boom)
    from storyforge import api
    for name in ('invoke_to_file', 'invoke_api', 'submit_batch'):
        if hasattr(api, name):
            monkeypatch.setattr(api, name, boom)


def test_score_readability_prints_without_writing(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _set_target(project_dir, '5-7')
    _forbid_spending(monkeypatch)
    before = _tree(project_dir)
    cmd_score.main(['--readability'])
    out = capsys.readouterr().out
    assert SCENE in out
    assert 'Reading level: Flesch-Kincaid grade' in out and 'target grade 5-7' in out
    # T-4/SF-6: scenes with no file are named, as having no file
    assert 'act2-sc02 (no scene file)' in out
    assert _tree(project_dir) == before   # T-7: nothing written anywhere


def test_score_readability_takes_scene_filters(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    cmd_score.main(['--readability', '--scenes', SCENE])   # T-5
    out = capsys.readouterr().out
    assert 'in 1 scene(s)' in out and 'act2-sc01' not in out


@pytest.mark.parametrize('flag', [['--deterministic'], ['--principles', 'avoid_passive'],
                                  ['--direct'], ['--no-apply']])
def test_score_readability_refuses_other_modes(project_dir, monkeypatch, flag):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--readability'] + flag)   # SF-8
    assert e.value.code == 1


def test_score_readability_stops_on_an_unreadable_scene(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    with open(_scene(project_dir, SCENE), 'wb') as f:
        f.write(b'\xff\xfe')
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--readability'])   # SF-5
    assert e.value.code == 1
    assert f"{SCENE} (can't be read" in capsys.readouterr().out


def test_score_readability_with_nothing_drafted(project_dir, monkeypatch):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--readability', '--scenes', 'act2-sc02'])
    assert e.value.code == 1


@pytest.mark.parametrize('argv', [['--readability'], [], ['--deterministic']])
def test_bad_reading_level_stops_before_anything_is_spent(project_dir, monkeypatch, argv):
    # T-1: a real cycle, not only --readability
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _set_target(project_dir, 'teen')
    _forbid_spending(monkeypatch)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(argv)
    assert e.value.code == 1
    scores = os.path.join(project_dir, 'working', 'scores')
    assert not os.path.isdir(scores) or not any(
        d.startswith('cycle-') for d in os.listdir(scores))


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
    assert lines[-1].startswith('ALL|')
    # a measure, not a principle: never a scene-scores column
    with open(os.path.join(scores, cycle, 'scene-scores.csv')) as f:
        header = set(f.readline().strip().split('|'))
    assert not header & set(rd.CSV_HEADER.split('|')[1:])


def test_polish_loop_cycles_write_readability(project_dir, plugin_dir, monkeypatch):
    # CR-3: revise --polish --loop's deterministic cycles measure it too
    from storyforge import cmd_revise
    monkeypatch.setenv('STORYFORGE_PLUGIN_DIR', plugin_dir)
    cycle_dir, _ = cmd_revise._run_deterministic_score(project_dir, [SCENE])
    with open(os.path.join(cycle_dir, 'readability.csv')) as f:
        assert f.read().splitlines()[1].startswith(f'{SCENE}|')


def test_gn_score_readability_is_an_error(project_dir_gn, monkeypatch, capsys):
    # SF-9/CR-4: said, not argparse's "unrecognized arguments"
    from storyforge import cmd_score_gn
    monkeypatch.chdir(project_dir_gn)
    with pytest.raises(SystemExit) as e:
        cmd_score_gn.main(['--readability'])
    assert e.value.code == 1
    out = capsys.readouterr()
    assert 'graphic-novel project has no reading level' in out.out + out.err


# --- key decisions in the revision prompts ---

def _revision_prompt(project_dir, **kw):
    from storyforge.revision import build_revision_prompt
    return build_revision_prompt('prose-tightening', 'Tighten the prose.', 'act1-sc01',
                                 project_dir, **kw)


def _template_key_decisions(project_dir):
    with open(os.path.join(get_plugin_dir(), 'templates', 'reference', 'key-decisions.md'),
              encoding='utf-8') as f:
        template = f.read()
    with open(os.path.join(project_dir, 'reference', 'key-decisions.md'), 'w',
              encoding='utf-8') as f:
        f.write(template)


@pytest.mark.parametrize('kw', [{}, {'api_mode': True},
                                {'api_mode': True, 'system_context': True}])
def test_revision_pass_prompt_carries_key_decisions(project_dir, kw):
    prompt = _revision_prompt(project_dir, **kw)
    assert '## Key Decisions' in prompt and KD_MARK in prompt
    assert prompt.index('## Purpose') < prompt.index('## Key Decisions')


def test_revision_pass_prompt_leaves_out_template_key_decisions(project_dir):
    _template_key_decisions(project_dir)
    assert '## Key Decisions' not in _revision_prompt(project_dir, api_mode=True)
    os.remove(os.path.join(project_dir, 'reference', 'key-decisions.md'))
    assert '## Key Decisions' not in _revision_prompt(project_dir, api_mode=True)


def test_build_prompt_cli_reports_unreadable_key_decisions(project_dir):
    # SF-3/T-9: an ERROR line and exit 1, not a traceback
    import subprocess
    import sys
    with open(os.path.join(project_dir, 'reference', 'key-decisions.md'), 'wb') as f:
        f.write(b'\xff\xfe not utf-8')
    env = dict(os.environ, PYTHONPATH=os.path.join(get_plugin_dir(), 'scripts', 'lib', 'python'))
    r = subprocess.run([sys.executable, '-m', 'storyforge.revision', 'build-prompt',
                        'prose', 'Tighten', 'act1-sc01', project_dir, '--api-mode'],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert r.stderr.startswith('ERROR:') and 'key-decisions.md' in r.stderr
    assert 'Traceback' not in r.stderr


def test_gn_revision_prompt_carries_key_decisions():
    from storyforge.prompts_gn import build_revision_prompt
    kw = dict(scene_id='s', scene_row={}, intent_row={}, brief_row={}, script_text='x',
              character_visuals='', location_visuals='', voice_profile_text='',
              score_findings=[], eval_findings=[])
    assert '# Key decisions' not in build_revision_prompt(**kw, key_decisions='')
    assert 'Grade 5 to 7.' in build_revision_prompt(**kw, key_decisions='Grade 5 to 7.')
    with pytest.raises(TypeError):
        build_revision_prompt(**kw)   # TD-6: required, never left out by omission

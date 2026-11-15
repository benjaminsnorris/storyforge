"""The author's marks, and `revise --marks` (#655: revision by reaction)."""

import json
import os

import pytest

from storyforge import marks

FILE = """# My marks

## act1-sc01
> Dorren Hayle pressed the brass calipers
> against the vellum
more like this

> held her breath
cut: a tic

## act1-sc02
> She did not look up.
"""


def test_parse_marks():
    scenes = marks.parse_marks(FILE)
    assert [s.scene_id for s in scenes] == ['act1-sc01', 'act1-sc02']
    assert scenes[0].marks == [
        ('Dorren Hayle pressed the brass calipers against the vellum', 'more like this'),
        ('held her breath', 'cut: a tic')]
    assert scenes[1].marks == [('She did not look up.', 'keep')]


@pytest.mark.parametrize('text, why', [
    ('> words\nnote\n', 'before any'),
    ('## a\n> x\n## a\n> y\n', 'given twice'),
])
def test_a_marks_file_that_cant_be_used(text, why):
    with pytest.raises(marks.MarksError, match=why):
        marks.parse_marks(text)


@pytest.fixture
def run(project_dir, monkeypatch):
    from storyforge import api, cmd_revise
    sent = []

    def fake(prompt, model, tokens, **k):
        sent.append(prompt)
        return {'content': [{'type': 'text', 'text': json.dumps({
            'edits': [{'flag': 2, 'find': 'held her breath', 'replace': 'breathed out'}],
            'kept': [{'flag': 1, 'why': 'the author likes it'}]})}], 'stop_reason': 'end_turn'}
    monkeypatch.setattr(api, 'invoke', fake)
    monkeypatch.setattr(cmd_revise, 'select_model', lambda t: 'm')
    gated = []
    from storyforge import cmd_write, git
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene',
                        lambda pd, sid, path, cmd, ld, **k: gated.append((sid, cmd)) or (True, ''))
    commits = []
    monkeypatch.setattr(git, 'commit_or_raise', lambda pd, msg, paths: commits.append(msg))

    def go(text):
        path = os.path.join(project_dir, 'working', 'marks.md')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)
        return cmd_revise._revise_marks(project_dir, path,
                                        os.path.join(project_dir, 'working', 'logs'), False)
    go.sent, go.gated, go.commits = sent, gated, commits
    return go


def test_marks_rewrite_only_the_marked_lines_then_gate_and_commit(project_dir, run, capsys):
    code = run('## act1-sc01\n> Dorren Hayle pressed the brass calipers\nmore like this\n\n'
               '> held her breath\ncut\n\n> words that are not there\nx\n')
    with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md')) as f:
        assert 'breathed out' in f.read()
    assert code == 0 and run.gated == [('act1-sc01', 'revise')]
    assert run.commits == ["Revise act1-sc01 from the author's marks"]
    assert "the author's note" in run.sent[0] and 'Her heart pounded' not in run.sent[0]
    assert 'marked words not in the scene, left out' in capsys.readouterr().out


def test_a_scene_with_no_prose_fails_the_run(project_dir, run, capsys):
    assert run('## no-such-scene\n> x\ny\n') == 1
    assert 'has no prose' in capsys.readouterr().out

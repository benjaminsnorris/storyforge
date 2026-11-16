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

> the master survey

## act1-sc02
> She did not look up.
"""


def test_parse_marks():
    scenes = marks.parse_marks(FILE)
    assert [s.scene_id for s in scenes] == ['act1-sc01', 'act1-sc02']
    assert [m[:2] for m in scenes[0].marks] == [
        ('Dorren Hayle pressed the brass calipers against the vellum', 'more like this'),
        ('held her breath', 'cut: a tic'),
        ('the master survey', 'keep')]
    assert [m.quote for m in scenes[0].keeps] == [
        'Dorren Hayle pressed the brass calipers against the vellum', 'the master survey']
    assert [m.quote for m in scenes[0].changes] == ['held her breath']
    assert [m[:2] for m in scenes[1].marks] == [('She did not look up.', 'keep')]
    assert {m.comment_id for s in scenes for m in s.marks} == {0}


def test_a_blank_line_ends_a_quote():
    scenes = marks.parse_marks('## s1\n> A one.\n\n> B two.\ncut\n')
    assert [m[:2] for m in scenes[0].marks] == [('A one.', 'keep'), ('B two.', 'cut')]


@pytest.mark.parametrize('text, why', [
    ('> words\nnote\n', 'before any'),
    ('## a\n> x\n## a\n> y\n', 'given twice'),
    ('## a b\n> x\n', 'alone'),
    ('## a\n### b\n', 'alone'),
    ('## a\nA note with nothing quoted.\n', 'no `>` quoted line'),
    ('## a\n>\n', 'quotes nothing'),
])
def test_a_marks_file_that_cant_be_used(text, why):
    with pytest.raises(marks.MarksError, match=why):
        marks.parse_marks(text)


@pytest.fixture
def run(project_dir, monkeypatch):
    from storyforge import api, cmd_revise, cmd_write, gate, git
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test')
    sent = []
    reply = {'edits': [{'flag': 1, 'find': 'held her breath', 'replace': 'breathed out'}],
             'kept': []}

    def fake(prompt, model, tokens, **k):
        sent.append(prompt)
        return {'content': [{'type': 'text', 'text': json.dumps(reply)}],
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    monkeypatch.setattr(api, 'invoke', fake)
    monkeypatch.setattr(cmd_revise, 'select_model', lambda t: 'claude-opus-5-5')
    branches = []
    monkeypatch.setattr(cmd_revise, 'create_branch', lambda cmd, pd: branches.append(cmd))
    monkeypatch.setattr(gate, 'snapshot', lambda pd: 'SNAP')
    state = {'gate': (True, ''), 'provisional': False}
    gated = []
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene',
                        lambda pd, sid, path, cmd, ld, **k: gated.append((sid, cmd, k['before']))
                        or state['gate'])
    monkeypatch.setattr(cmd_write, 'is_provisional', lambda pd, sid: state['provisional'])
    monkeypatch.setattr(cmd_revise, '_recheck_after', lambda *a, **k: None)
    commits = []
    monkeypatch.setattr(git, 'commit_or_raise',
                        lambda pd, msg, paths: commits.append((msg, list(paths))))

    def go(text, dry_run=False):
        path = os.path.join(project_dir, 'working', 'marks.md')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)
        return cmd_revise._revise_marks(project_dir, path,
                                        os.path.join(project_dir, 'working', 'logs'), dry_run)
    go.sent, go.gated, go.commits, go.state, go.branches = sent, gated, commits, state, branches
    go.reply = reply
    return go


def _scene(project_dir):
    with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md')) as f:
        return f.read()


MARKS = ('## act1-sc01\n> She had worked here for nineteen years\n\n'
         '> held her breath\ncut\n\n> words that are not there\nx\n')


def test_marks_rewrite_only_the_marked_lines_then_gate_and_commit(project_dir, run, capsys):
    code = run(MARKS)
    assert 'breathed out' in _scene(project_dir)
    assert code == 0 and run.gated == [('act1-sc01', 'revise', 'SNAP')]
    assert run.branches == ['revise']
    msg, paths = run.commits[0]
    assert msg == "Revise act1-sc01 from the author's marks"
    assert 'scenes/act1-sc01.md' in paths and 'working/' not in paths
    prompt = run.sent[0]
    assert "the author's note" in prompt and 'Her heart pounded' not in prompt
    assert 'marked as working' in prompt and 'worked here for nineteen years' in prompt
    assert 'marked words not in the scene, left out' in capsys.readouterr().out


def test_illustration_markers_survive_a_marks_revision(project_dir, run):
    path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(path) as f:
        text = f.read()
    marker = '<!-- illustration: map-room -->'
    with open(path, 'w') as f:
        f.write(text.replace('Dorren Hayle pressed', f'{marker}\n\nDorren Hayle pressed', 1))
    run(MARKS)
    assert marker in _scene(project_dir) and 'breathed out' in _scene(project_dir)


def test_a_revision_the_gate_rejects_is_rolled_back(project_dir, run, capsys):
    before = _scene(project_dir)
    run.state['gate'] = (False, 'a contradiction')
    assert run(MARKS) == 1
    assert _scene(project_dir) == before
    msg, paths = run.commits[0]
    assert 'rolled-back' in msg and 'scenes/act1-sc01.md' not in paths
    assert 'rolled back' in capsys.readouterr().out


def test_a_provisional_revision_is_committed_and_fails_the_run(project_dir, run):
    run.state.update(gate=(False, 'a contradiction'), provisional=True)
    assert run(MARKS) == 1
    assert 'provisionally' in run.commits[0][0]


def test_nothing_rewritten_still_commits_the_record(project_dir, run):
    run.reply.update(edits=[], kept=[{'flag': 1, 'why': 'it works'}])
    assert run(MARKS) == 0 and run.gated == []
    msg, paths = run.commits[0]
    assert 'nothing rewritten' in msg and paths == ['working/voice-reviews/']


def test_a_dry_run_spends_and_writes_nothing(project_dir, run, capsys):
    before = _scene(project_dir)
    assert run(MARKS, dry_run=True) == 0
    assert run.sent == [] and run.commits == [] and run.branches == []
    assert _scene(project_dir) == before
    assert 'act1-sc01: 1 line(s) to revise, 1 kept as examples' in capsys.readouterr().out


def test_a_scene_with_no_prose_fails_the_run(project_dir, run, capsys):
    assert run('## no-such-scene\n> x\ny\n') == 1
    assert 'has no prose' in capsys.readouterr().out


def test_no_key_no_run(project_dir, run, monkeypatch, capsys):
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    assert run(MARKS) == 1 and run.branches == []
    assert 'ANTHROPIC_API_KEY not set' in capsys.readouterr().out

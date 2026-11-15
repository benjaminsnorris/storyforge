"""The author's marks on drafted scenes, read from the scenes' PR
(`revise --marks-from-pr`, #691). `pr_marks.fetch` reads canned API pages:
no network."""

import json
import os
import subprocess

import pytest

from storyforge import marks, pr_marks, pr_scene_marks as psm

SID = 'pr-sc01'
PATH = f'scenes/{SID}.md'
P1 = 'Kael crossed the yard in the grey before dawn. The coolest thing he had felt all day was the iron of the gate.'
P2 = 'He had come all the way down from the house to say it. Andromache did not smile.'
P3 = 'The dogs were quiet. Somewhere a door shut.'
P4 = 'He went in.'
SCENE = f'{P1}\n\n{P2}\n\n![[illus:gate]]\n\n{P3}\n\n{P4}\n'
# file lines: 1 P1, 3 P2, 5 marker, 7 P3, 9 P4

ME = {'login': 'ben', 'type': 'User'}
BOT = {'login': 'review-bot[bot]', 'type': 'Bot'}


def _c(cid, line, body, text, user=ME, path=PATH, start=None, outdated=False,
       created='2026-11-15T10:00:00Z'):
    item = {'id': cid, 'user': user, 'path': path, 'body': body, 'created_at': created,
            'diff_hunk': f'@@ -0,0 +1,9 @@\n+{text}', 'side': 'RIGHT'}
    if outdated:
        item.update(line=None, original_line=line)
    else:
        item.update(line=line, start_line=start)
    return item


COMMENTS = [
    _c(1, 1, '"The coolest thing he had felt all day" reeks of AI', P1),   # quoted phrase
    _c(2, 3, 'too neat', P2),                                             # no quote: paragraph
    _c(3, 7, 'keep', P3),                                                 # a keep
    _c(4, 9, '```suggestion\nHe went in without knocking.\n```', P4),      # suggestion
    _c(5, 9, 'and slow it down', P4),                                     # on a suggested line
    _c(6, 3, 'old note', 'Something it used to say.', outdated=True),     # outdated
    _c(7, 3, 'stale', 'A line it no longer says.'),                       # line text moved
    _c(8, 2, 'not a scene', 'x', path='reference/scenes.csv'),            # not a scene file
    _c(9, 1, 'lint: long line', P1, user=BOT),                            # a bot
]


def _pages(comments=COMMENTS, head='abc123'):
    return {
        'repos/{owner}/{repo}/pulls/12': {'user': ME, 'head': {'sha': head,
                                                               'ref': 'storyforge/write-x'}},
        'repos/{owner}/{repo}/pulls/12/files': [{'filename': PATH}],
        'repos/{owner}/{repo}/pulls/12/comments': comments,
        'repos/{owner}/{repo}/pulls/12/reviews': [
            {'user': ME, 'body': 'Better than the last draft.',
             'submitted_at': '2026-11-15T11:00:00Z'}],
        'repos/{owner}/{repo}/issues/12/comments': [],
    }


def _fake_gh(monkeypatch, pages):
    def run(args, **k):
        path = args[3] if args[2] == '--paginate' else args[2]
        out = pages.get(path, [])
        text = json.dumps(out) if isinstance(out, dict) else '\n'.join(
            json.dumps(x) for x in out)
        return subprocess.CompletedProcess(args, 0, text, '')
    monkeypatch.setattr(pr_marks.subprocess, 'run', run)


def _mapped(monkeypatch, comments=COMMENTS, skip=frozenset(), since='', scene=SCENE):
    _fake_gh(monkeypatch, _pages(comments))
    prs = pr_marks.fetch(12, '.')
    return psm.map_comments(prs, lambda sid: scene if sid == SID else None,
                            skip_ids=skip, since=since)


def test_the_mapping(monkeypatch):
    m = _mapped(monkeypatch)
    sm = m.scenes[0]
    assert sm.scene_id == SID
    assert [(x.quote, x.note) for x in sm.changes] == [
        ('The coolest thing he had felt all day', 'reeks of AI'),
        (P2, 'too neat')]
    assert [x.quote for x in sm.keeps] == [P3, 'He went in without knocking.']
    assert m.suggestions == [psm.Suggestion(SID, 9, 9, 'He went in without knocking.', '', 4)]
    assert m.change_ids == {SID: [1, 2]}
    why = ' | '.join(m.left_out)
    assert 'outdated' in why and 'no longer says' in why and 'not on a scene file' in why
    assert "suggestion, applied as written" in why            # comment 5
    assert 'lint' not in why and m.general == ['Better than the last draft.']
    assert len(m.left_out) == 4


def test_a_multi_line_comment_marks_every_line(monkeypatch):
    m = _mapped(monkeypatch, [_c(1, 3, 'both of these drag', P2, start=1)])
    assert m.scenes[0].changes[0].quote == f'{P1}\n\n{P2}'


def test_a_comment_over_the_marker_reads_only_prose(monkeypatch):
    m = _mapped(monkeypatch, [_c(1, 7, 'cut', P3, start=5)])
    assert m.scenes[0].changes[0].quote == P3
    m = _mapped(monkeypatch, [_c(1, 5, 'cut', '![[illus:gate]]')])
    assert m.scenes == [] and 'illustration marker' in m.left_out[0]


@pytest.mark.parametrize('body, quote, note', [
    ('> did not smile\nflat', 'did not smile', 'flat'),
    ('> words not there\nflat', P2, 'flat (the comment quoted "words not there")'),
    ('cut “all the way down”', 'all the way down', 'cut'),
    ('change "say it" to "tell her"', P2, 'change "say it" to "tell her"'),
    ('> Andromache did not smile.', 'Andromache did not smile.', ''),
])
def test_split_body(body, quote, note):
    assert psm.split_body(body, P2) == (quote, note)


def test_a_quote_with_no_note_is_a_keep(monkeypatch):
    m = _mapped(monkeypatch, [_c(1, 3, '> Andromache did not smile.', P2)])
    assert [k.quote for k in m.scenes[0].keeps] == ['Andromache did not smile.']
    assert m.change_ids == {} and not m.has_work


def test_an_empty_suggestion_cuts_the_line(monkeypatch):
    m = _mapped(monkeypatch, [_c(1, 7, '```suggestion\n```', P3)])
    assert m.suggestions[0].text == '' and m.scenes == []
    assert psm.apply_suggestions(SCENE, m.suggestions) == \
        f'{P1}\n\n{P2}\n\n![[illus:gate]]\n\n{P4}\n'


def test_a_suggestion_over_lines_replaces_them_all():
    s = psm.Suggestion(SID, 1, 3, 'One paragraph now.')
    assert psm.apply_suggestions(SCENE, [s]).startswith('One paragraph now.\n\n![[illus')
    crlf = SCENE.replace('\n', '\r\n')
    assert psm.apply_suggestions(crlf, [psm.Suggestion(SID, 9, 9, 'Out.')]).endswith(
        'Out.\r\n')


def test_two_suggestions_and_overlapping_ones(monkeypatch):
    m = _mapped(monkeypatch, [_c(1, 3, '```suggestion\nA.\n```\n```suggestion\nB.\n```', P2),
                              _c(2, 7, '```suggestion\nC.\n```', P3),
                              _c(3, 7, '```suggestion\nD.\n```', P3)])
    assert [s.text for s in m.suggestions] == ['C.']
    why = ' | '.join(m.left_out)
    assert '2 suggestions in one comment' in why and 'overlapping an earlier one' in why


def test_comments_already_used_or_before_since_are_counted(monkeypatch):
    m = _mapped(monkeypatch, skip={1, 2}, since='2026-11-15T09:00:00Z')
    assert m.already_used == 2 and m.change_ids == {}
    m = _mapped(monkeypatch, since='2026-11-16T00:00:00Z')
    assert m.before_since == 7 and m.scenes == []


def test_a_book_in_a_subfolder(monkeypatch):
    _fake_gh(monkeypatch, _pages([_c(1, 3, 'too neat', P2, path=f'book/{PATH}')]))
    m = psm.map_comments(pr_marks.fetch(12, '.'), lambda sid: SCENE, prefix='book/')
    assert m.scenes[0].changes[0].quote == P2


def test_used_notes_carry_forward(tmp_path):
    d = tmp_path / 'working' / 'voice-reviews'
    d.mkdir(parents=True)
    (d / f'{SID}.md').write_text('# Voice review\n\nNOTE: Comments used from PR #12: 4\n')
    assert psm.used_notes(str(tmp_path), SID, 12, [1, 2]) == [
        'Comments used from PR #12: 1, 2, 4']
    assert psm.used_notes(str(tmp_path), SID) == ['Comments used from PR #12: 4']
    assert psm.used_comment_ids(str(tmp_path), 12) == {4}
    assert psm.used_comment_ids(str(tmp_path), 13) == set()


# ============================================================================
# The command
# ============================================================================

@pytest.fixture
def run(project_dir, monkeypatch):
    from storyforge import api, cmd_revise, cmd_write, gate, git
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test')
    with open(os.path.join(project_dir, 'scenes', f'{SID}.md'), 'w') as f:
        f.write(SCENE)
    sent = []
    reply = {'edits': [{'flag': 2, 'find': 'He had come all the way down from the house to '
                                           'say it.',
                        'replace': 'He had walked down to say it.'}], 'kept': []}

    def fake(prompt, model, tokens, **k):
        sent.append(prompt)
        return {'content': [{'type': 'text', 'text': json.dumps(reply)}],
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    monkeypatch.setattr(api, 'invoke', fake)
    monkeypatch.setattr(cmd_revise, 'select_model', lambda t: 'claude-opus-5-5')
    branches = []
    monkeypatch.setattr(cmd_revise, 'create_branch', lambda cmd, pd: branches.append(cmd))
    state = {'branch': 'storyforge/write-x', 'head': 'abc123', 'dirty': ''}
    monkeypatch.setattr(cmd_revise, 'current_branch', lambda pd: state['branch'])

    def fake_git(pd, *args, check=True):
        out = {'rev-parse': state['head'] if 'HEAD' in args else '',
               'status': state['dirty']}.get(args[0], '')
        return subprocess.CompletedProcess(args, 0, out, '')
    monkeypatch.setattr(cmd_revise, '_git', fake_git)
    monkeypatch.setattr(gate, 'snapshot', lambda pd: 'SNAP')
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene', lambda *a, **k: (True, ''))
    monkeypatch.setattr(cmd_write, 'is_provisional', lambda pd, sid: False)
    monkeypatch.setattr(cmd_revise, '_recheck_after', lambda *a, **k: None)
    commits = []
    monkeypatch.setattr(git, 'commit_or_raise',
                        lambda pd, msg, paths: commits.append((msg, list(paths))))
    pages = _pages()
    _fake_gh(monkeypatch, pages)

    def go(dry_run=False, since=''):
        return cmd_revise._revise_marks_from_pr(
            project_dir, 12, since, os.path.join(project_dir, 'working', 'logs'), dry_run)
    go.sent, go.commits, go.state, go.branches, go.pages = sent, commits, state, branches, pages
    return go


def _scene(project_dir):
    with open(os.path.join(project_dir, 'scenes', f'{SID}.md')) as f:
        return f.read()


def test_a_dry_run_lists_the_marks_and_spends_nothing(project_dir, run, capsys):
    assert run(dry_run=True) == 0
    out = capsys.readouterr().out
    assert run.sent == [] and run.commits == [] and run.branches == []
    assert _scene(project_dir) == SCENE
    assert 'suggestion on line 9, applied as written: "He went in without knocking."' in out
    assert 'change: "The coolest thing he had felt all day" -- reeks of AI' in out
    assert f'keep: "{P3}"' in out
    assert 'Left out: ' in out and 'outdated' in out and 'not on a scene file' in out
    assert 'General comment' in out and 'Better than the last draft.' in out
    assert 'review-bot[bot]' in out
    assert f'{SID}: 2 line(s) to revise, 1 kept as examples' in out
    assert 'WARNING' not in out


def test_a_run_applies_suggestions_then_revises_and_a_second_run_skips_them(
        project_dir, run, capsys):
    assert run() == 0
    text = _scene(project_dir)
    assert 'He went in without knocking.' in text and 'He had walked down to say it.' in text
    assert run.commits[0][0] == f"Apply the author's suggestions on {SID} (PR #12)"
    assert run.commits[1][0] == f"Revise {SID} from the author's marks"
    assert run.branches == ['revise']
    prompt = run.sent[0]
    assert 'reeks of AI' in prompt and 'He went in without knocking.' in prompt   # a keep
    with open(os.path.join(project_dir, 'working', 'voice-reviews', f'{SID}.md')) as f:
        record = f.read()
    assert 'NOTE: Comments used from PR #12: 1, 2, 4' in record
    assert 'From the author\'s marks (PR #12).' in record
    # the second run: the PR moved on (its head is the pushed revision)
    capsys.readouterr()
    run.pages['repos/{owner}/{repo}/pulls/12']['head']['sha'] = 'def456'
    run.state['head'] = 'def456'
    assert run(dry_run=True) == 1
    out = capsys.readouterr().out
    assert '3 comment(s) an earlier run on PR #12 acted on, left out' in out
    assert 'nothing left to send' in out


def test_a_rolled_back_revision_doesnt_use_up_its_comments(project_dir, run, monkeypatch):
    from storyforge import cmd_write
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene', lambda *a, **k: (False, 'no'))
    assert run() == 1
    assert psm.used_comment_ids(project_dir, 12) == {4}   # the suggestion only


@pytest.mark.parametrize('key, value, why', [
    ('branch', 'main', "not PR #12's branch"),
    ('head', 'zzz999', 'pull (or push) first'),
    ('dirty', ' M scenes/pr-sc01.md', 'not committed'),
])
def test_the_checkout_must_be_the_prs_head(project_dir, run, capsys, key, value, why):
    run.state[key] = value
    assert run(dry_run=True) == 1
    assert why in capsys.readouterr().out and run.sent == []


def test_nothing_but_keeps_is_nothing_to_send(project_dir, run, capsys):
    run.pages['repos/{owner}/{repo}/pulls/12/comments'] = [_c(3, 7, 'keep', P3)]
    assert run(dry_run=True) == 1
    assert 'nothing left to send' in capsys.readouterr().out


def test_marks_and_marks_from_pr_together_are_refused(project_dir, monkeypatch, capsys):
    from storyforge import cmd_revise
    monkeypatch.setattr(cmd_revise, 'detect_project_root', lambda: project_dir)
    with pytest.raises(SystemExit) as e:
        cmd_revise._main(['--marks', 'x.md', '--marks-from-pr', '12'])
    assert e.value.code == 1 and 'give one' in capsys.readouterr().out


def test_comment_ids_are_parsed():
    c = pr_marks.parse_comment({'id': 77, 'path': 'f', 'line': 2, 'body': 'x',
                                'created_at': '2026-11-15T00:00:00Z'})
    assert (c.id, c.created_at) == (77, '2026-11-15T00:00:00Z')
    assert isinstance(marks.Mark('a', 'b'), tuple)

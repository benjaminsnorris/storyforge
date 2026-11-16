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
    assert [x.comment_id for x in sm.changes] == [1, 2]
    assert [x.quote for x in sm.keeps] == [P3]    # the suggestion's: only once applied
    assert [x.quote for x in psm.with_suggestion_keeps(m)[0].keeps] == [
        P3, 'He went in without knocking.']
    assert [x.quote for x in sm.keeps] == [P3]    # not changed by it
    assert m.suggestions == [psm.Suggestion(SID, 9, 9, 'He went in without knocking.', '', 4)]
    assert m.left_out == [
        f'{PATH}:3: outdated (its line has changed since the comment)',
        f'{PATH}:3: the line no longer says what it said when marked',
        'reference/scenes.csv:2: not on a scene file',
        f"{PATH}:9: its line has the author's suggestion, applied as written"]
    assert m.general == ['Better than the last draft.']


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
    assert not m.has_work


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
    assert m.already_used == 2 and m.scenes[0].changes == []
    assert f'{PATH}:1: an earlier run acted on it (comment 1)' in m.left_out
    m = _mapped(monkeypatch, since='2026-11-16T00:00:00Z')
    assert m.before_since == 7 and m.scenes == []
    assert f'{PATH}:1: made before --since (2026-11-15T10:00:00Z)' in m.left_out


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
    # the reviser rewrote flag 2 and didn't answer flag 1: comment 1 isn't used up
    assert 'NOTE: Comments used from PR #12: 2, 4' in record
    assert 'From the author\'s marks (PR #12).' in record
    # the second run: the PR moved on (its head is the pushed revision)
    capsys.readouterr()
    run.pages['repos/{owner}/{repo}/pulls/12']['head']['sha'] = 'def456'
    run.state['head'] = 'def456'
    assert run(dry_run=True) == 0
    out = capsys.readouterr().out
    assert '2 comment(s) an earlier run on PR #12 acted on, left out' in out
    assert 'change: "The coolest thing he had felt all day" -- reeks of AI' in out


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


# ============================================================================
# The review's fixes (PR #692)
# ============================================================================

def test_a_suggestion_that_would_remove_a_marker_is_left_out(monkeypatch):
    for c in (_c(1, 7, '```suggestion\nNew.\n```', P3, start=3),
              _c(1, 5, '```suggestion\n```', '![[illus:gate]]')):
        m = _mapped(monkeypatch, [c])
        assert m.suggestions == [] and 'illustration marker(s) gate' in m.left_out[0]
    keeps = _c(1, 7, '```suggestion\nNew.\n\n![[illus:gate]]\n\nP3.\n```', P3, start=3)
    assert len(_mapped(monkeypatch, [keeps]).suggestions) == 1


def test_a_quote_found_twice_marks_the_paragraph(monkeypatch):
    # a line that occurs twice, alone in its paragraph: no edit could be placed
    scene = f'{P1}\n\nHe went in.\n\n{P4}\n'
    m = _mapped(monkeypatch, [_c(1, 3, '> He went in.\ncut', 'He went in.')], scene=scene)
    assert m.scenes == [] and 'occurs more than once in the scene' in m.left_out[0]
    # a keep needs only to be the first occurrence
    m = _mapped(monkeypatch, [_c(1, 3, 'keep', 'He went in.')], scene=scene)
    assert m.scenes[0].keeps[0].quote == 'He went in.'
    m = _mapped(monkeypatch, [_c(1, 1, '"the gate" flat', P1)],
                scene=f'{P1}\n\nAt the gate he stopped.\n')
    mark = m.scenes[0].changes[0]
    assert mark.quote == P1 and 'occurs more than once' in mark.note


def test_reasons_for_odd_comments(monkeypatch):
    m = _mapped(monkeypatch, [_c(1, 1, 'x', P1, path='scenes/gone.md'),
                              _c(2, 1, 'x', P1, start=3)])
    assert m.left_out == ['scenes/gone.md:1: there is no scene file gone.md here',
                          f'{PATH}:1: its lines run backwards (from 3)']


def test_cutting_the_first_line_leaves_no_blank_line():
    assert psm.apply_suggestions('A\n\nB\n', [psm.Suggestion('a', 1, 1, '')]) == 'B\n'


def test_bad_suggestions_are_refused():
    with pytest.raises(ValueError):
        psm.Suggestion('a', 3, 1, '')
    with pytest.raises(ValueError, match='overlaps'):
        psm.apply_suggestions(SCENE, [psm.Suggestion(SID, 1, 3, 'x'),
                                      psm.Suggestion(SID, 3, 3, 'y')])
    with pytest.raises(ValueError, match='past the file'):
        psm.apply_suggestions('A\n', [psm.Suggestion(SID, 5, 5, 'x')])


def test_a_refused_edit_doesnt_use_up_its_comment(project_dir, run):
    # the reviser's edit for flag 2 reaches outside its sentence: refused
    run.pages['repos/{owner}/{repo}/pulls/12/comments'] = [COMMENTS[1]]
    from storyforge import api
    api_invoke = api.invoke

    def refuse(prompt, model, tokens, **k):
        run.sent.append(prompt)
        return {'content': [{'type': 'text', 'text': json.dumps(
            {'edits': [{'flag': 1, 'find': 'The dogs were quiet.', 'replace': 'x'}],
             'kept': []})}], 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 1, 'output_tokens': 1}}
    api.invoke = refuse
    try:
        assert run() == 0
    finally:
        api.invoke = api_invoke
    assert psm.used_comment_ids(project_dir, 12) == set()


def test_a_reviser_failure_uses_up_nothing_but_the_suggestion(project_dir, run, monkeypatch,
                                                             capsys):
    from storyforge import api

    def boom(*a, **k):
        raise RuntimeError('overloaded')
    monkeypatch.setattr(api, 'invoke', boom)
    assert run() == 1
    assert psm.used_comment_ids(project_dir, 12) == {4}
    assert [m for m, _ in run.commits] == [f"Apply the author's suggestions on {SID} (PR #12)"]


def test_a_rolled_back_revision_with_no_earlier_record(project_dir, run, monkeypatch):
    from storyforge import cmd_write
    run.pages['repos/{owner}/{repo}/pulls/12/comments'] = COMMENTS[:2]
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene', lambda *a, **k: (False, 'no'))
    assert run() == 1
    assert psm.used_comment_ids(project_dir, 12) == set()
    with open(os.path.join(project_dir, 'working', 'voice-reviews', f'{SID}.md')) as f:
        assert 'Rolled back: the revision did not pass the gate (no)' in f.read()


def test_an_empty_suggestion_end_to_end(project_dir, run):
    run.pages['repos/{owner}/{repo}/pulls/12/comments'] = [_c(1, 7, '```suggestion\n```', P3)]
    assert run() == 0
    assert _scene(project_dir) == f'{P1}\n\n{P2}\n\n![[illus:gate]]\n\n{P4}\n'
    assert run.sent == [] and len(run.commits) == 1
    assert psm.used_comment_ids(project_dir, 12) == {1}


def test_a_multi_line_suggestion_end_to_end_on_a_crlf_scene(project_dir, run, capsys):
    with open(os.path.join(project_dir, 'scenes', f'{SID}.md'), 'w', newline='') as f:
        f.write(SCENE.replace('\n', '\r\n'))
    run.pages['repos/{owner}/{repo}/pulls/12/comments'] = [
        _c(1, 3, '```suggestion\nOne paragraph.\n```', P2, start=1)]
    assert run(dry_run=True) == 0
    assert 'suggestion on lines 1-3' in capsys.readouterr().out
    assert run() == 0
    with open(os.path.join(project_dir, 'scenes', f'{SID}.md'), newline='') as f:
        assert f.read().startswith('One paragraph.\r\n\r\n![[illus:gate]]\r\n')


def test_a_failed_suggestion_commit_says_what_happened(project_dir, run, monkeypatch, capsys):
    from storyforge import git
    from storyforge.git import CommitError

    def fail(*a):
        raise CommitError('the commit failed: disk full')
    monkeypatch.setattr(git, 'commit_or_raise', fail)
    assert run() == 1
    out = capsys.readouterr().out
    assert 'disk full' in out and 'The reviser did not run' in out and run.sent == []


def test_a_marks_file_run_keeps_the_pr_ids(project_dir, run):
    from storyforge import cmd_revise
    d = os.path.join(project_dir, 'working', 'voice-reviews')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f'{SID}.md'), 'w') as f:
        f.write('# Voice review\n\nNOTE: Comments used from PR #12: 1, 2\n')
    path = os.path.join(project_dir, 'working', 'marks.md')
    with open(path, 'w') as f:
        f.write(f'## {SID}\n> He had come all the way down from the house to say it.\ncut\n')
    assert cmd_revise._revise_marks(project_dir, path,
                                    os.path.join(project_dir, 'working', 'logs'), False) == 0
    assert psm.used_comment_ids(project_dir, 12) == {1, 2}


def test_pr_errors_are_said(project_dir, run, monkeypatch, capsys):
    monkeypatch.setattr(pr_marks.subprocess, 'run', lambda args, **k:
                        subprocess.CompletedProcess(args, 1, '', 'HTTP 404'))
    assert run(dry_run=True) == 1
    assert 'ERROR: PR #12: gh api' in capsys.readouterr().out
    _fake_gh(monkeypatch, run.pages)
    run.pages['repos/{owner}/{repo}/pulls/12']['user'] = {}
    assert run(dry_run=True) == 1
    assert "author can't be told" in capsys.readouterr().out


@pytest.mark.parametrize('given, utc', [
    ('2026-11-15T09:00:00Z', '2026-11-15T09:00:00Z'),
    ('2026-11-15T09:00:00-07:00', '2026-11-15T16:00:00Z'),
    ('2026-11-15T09:00+02:00', '2026-11-15T07:00:00Z'),
])
def test_since_is_made_utc(given, utc):
    from storyforge import cmd_revise
    assert cmd_revise._utc_time(given) == utc


@pytest.mark.parametrize('argv, why', [
    (['--since', '2026-11-15T09:00:00Z'], '--since goes with --marks-from-pr'),
    (['--marks-from-pr', '12', '--since', 'yesterday'], "isn't a time"),
])
def test_since_on_the_command_line(project_dir, monkeypatch, capsys, argv, why):
    from storyforge import cmd_revise
    monkeypatch.setattr(cmd_revise, 'detect_project_root', lambda: project_dir)
    with pytest.raises(SystemExit) as e:
        cmd_revise._main(argv)
    assert e.value.code == 1 and why in capsys.readouterr().out


def test_since_reaches_the_run(project_dir, monkeypatch):
    from storyforge import cmd_revise
    monkeypatch.setattr(cmd_revise, 'detect_project_root', lambda: project_dir)
    got = []
    monkeypatch.setattr(cmd_revise, '_revise_marks_from_pr',
                        lambda pd, pr, since, ld, dry: got.append((pr, since, dry)) or 0)
    with pytest.raises(SystemExit):
        cmd_revise._main(['--marks-from-pr', '12', '--since', '2026-11-15T09:00:00-07:00',
                          '--dry-run'])
    assert got == [(12, '2026-11-15T16:00:00Z', True)]


def test_a_reply_in_a_thread_is_not_a_mark(monkeypatch):
    # iliad-adult PR #18: "Applied in 22e7a6d" replies, posted with the author's login,
    # became marks; the one under a comment asking for a change became a second change
    reply = dict(_c(10, 3, 'Rewritten in 22e7a6d.', P2), in_reply_to_id=2)
    m = _mapped(monkeypatch, [COMMENTS[1], reply])
    assert [x.note for x in m.scenes[0].changes] == ['too neat']
    file_reply = {'id': 11, 'user': ME, 'path': PATH, 'subject_type': 'file',
                  'body': 'Applied in 22e7a6d.', 'in_reply_to_id': 3}
    _fake_gh(monkeypatch, _pages([COMMENTS[1], reply, file_reply]))
    prs = pr_marks.fetch(12, '.')
    assert prs.general == ['Better than the last draft.']   # not "On ... as a whole"
    assert any(f'2 repl(ies) in comment threads, left out' in n and f'{PATH}:3' in n
               for n in prs.notes)


def test_a_reply_with_a_suggestion_is_a_mark(monkeypatch):
    reply = dict(_c(10, 7, '```suggestion\nThe dogs slept.\n```', P3), in_reply_to_id=3)
    m = _mapped(monkeypatch, [reply])
    assert [s.text for s in m.suggestions] == ['The dogs slept.']


def test_a_repeated_sentence_line_takes_in_its_neighbour(monkeypatch):
    """H1: a scene is a sentence per line, and short sentences repeat. A
    mark on the second "No." must not land on the first."""
    scene = '"No."\nShe turned.\n\nHe waited.\n"No."\nThe door shut.\n'
    m = _mapped(monkeypatch, [_c(1, 5, 'harder', '"No."')], scene=scene)
    mark = m.scenes[0].changes[0]
    assert mark.quote == 'He waited.\n"No."' and 'line next to it' in mark.note
    # a keep is never edited: its widening isn't noted, and it stays a keep
    m = _mapped(monkeypatch, [_c(1, 5, 'keep', '"No."')], scene=scene)
    assert m.scenes[0].keeps[0].quote == 'He waited.\n"No."'
    # a repeated quoted phrase on a keep stays a keep (it used to become a change)
    m = _mapped(monkeypatch, [_c(1, 4, '"He waited" keep', 'He waited.')],
                scene='He waited. He waited.\n\nThen.\nHe waited.\n')
    assert m.scenes[0].keeps and not m.scenes[0].changes


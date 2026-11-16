"""Blind voice sample rounds (#654)."""

import json
import os
import random
import subprocess

import pytest

from storyforge import pr_marks, voice_sample as vs
from storyforge.blocking import check_blocking as REAL_CHECK_BLOCKING

SCENE = 'act1-sc01'
RF = 'working/voice-samples/round-1.md'


def test_one_per_line_and_back():
    text = 'She ran. He saw her! "Stop," he said.\n\nThe gate was open.'
    lines = vs.one_per_line(text)
    assert lines == 'She ran.\nHe saw her!\n"Stop," he said.\n\nThe gate was open.'
    assert vs.join_lines(lines) == 'She ran. He saw her! "Stop," he said.\n\nThe gate was open.'


ROUND = vs.render_round('Voice samples, round 1: s', 'Intro.',
                        [('A', 'She ran. He saw her.'), ('B', 'The gate shook.\n\nHe waited.')])
LINES = ROUND.split('\n')


def _at(text):
    return LINES.index(text) + 1


def test_a_round_parses_back_with_each_sentences_line():
    samples = vs.parse_round(ROUND)
    assert list(samples) == ['A', 'B']
    for s in samples.values():
        for n, sentence in s.lines.items():
            assert LINES[n - 1].strip() == sentence
        assert all(LINES[n - 1].startswith(('## ', '*')) for n in s.head_lines)
    assert vs.join_lines(samples['B'].text) == 'The gate shook.\n\nHe waited.'
    assert '*5 words*' in ROUND


def test_a_take_heading_named_like_a_sample_keeps_its_name():
    text = vs.render_round('t', 'i', [('Sample size', 'X.'), ('present tense', 'Y.')])
    assert list(vs.parse_round(text)) == ['Sample size', 'present tense']


def test_two_samples_with_one_label_are_refused():
    with pytest.raises(vs.SampleError, match='two samples'):
        vs.parse_round('## Sample A\nX.\n## Sample A\nY.\n')


def _c(line, body='', suggestions=(), text=None, **k):
    return pr_marks.Comment(RF, line, body, tuple(suggestions),
                            line_text=LINES[line - 1].strip() if text is None else text, **k)


def test_marks_map_to_the_sample_and_sentence():
    prs = pr_marks.PrMarks(lines=[
        _c(_at('He saw her.'), 'keep'),
        _c(_at('The gate shook.'), suggestions=('The gate held.',)),
        _c(_at('He waited.'), suggestions=('',)),                  # a cut
        _c(_at('## Sample B'), 'too slow overall'),               # the whole sample
        pr_marks.Comment('working/costs/ledger.csv', 3, 'not this file')],
        general=['More like B.'])
    samples = vs.parse_round(ROUND)
    marks, notes = vs.marks_for_round(prs, samples, RF)
    assert marks['A'].marks == [vs.Mark('He saw her.', 'keep')]
    assert marks['B'].marks[0] == vs.Mark('The gate shook.', '', 'The gate held.')
    assert marks['B'].marks[1] == vs.Mark('He waited.', '', '')
    assert marks['B'].whole == ['too slow overall']
    assert any('other files' in n for n in notes)
    key = vs.RoundKey(1, 's', tried={'A': 'close past'})
    text = vs.describe_marks(samples, marks, key, prs.general)
    assert 'it tried: close past' in text and 'the author\'s wording: "The gate held."' in text
    assert '"He waited.": cut it' in text and 'too slow overall' in text
    assert 'More like B.' in text


def test_a_comment_whose_line_changed_is_left_out_not_misplaced():
    prs = pr_marks.PrMarks(lines=[_c(_at('He saw her.'), 'cut', text='Something else.')])
    marks, notes = vs.marks_for_round(prs, vs.parse_round(ROUND), RF)
    assert marks['A'].marks == [] and any('changed since' in n for n in notes)


def test_a_multi_line_comment_quotes_every_sentence():
    prs = pr_marks.PrMarks(lines=[_c(_at('He saw her.'), 'both', start_line=_at('She ran.'))])
    marks, _ = vs.marks_for_round(prs, vs.parse_round(ROUND), RF)
    assert marks['A'].marks[0].sentence == 'She ran. He saw her.'


# --- reading the PR ---

def test_parse_comment():
    c = pr_marks.parse_comment({'path': 'f.md', 'line': None, 'original_line': 12,
                                'diff_hunk': '@@ -1 +1 @@\n+He held it.',
                                'body': 'Better:\r\n```suggestion\r\nHe held.\r\n```\r\n'
                                        '```suggestion\nHe kept it.\n```'})
    assert (c.line, c.outdated, c.body) == (12, True, 'Better:')
    assert c.suggestions == ('He held.', 'He kept it.') and c.line_text == 'He held it.'
    cut = pr_marks.parse_comment({'path': 'f', 'line': 3, 'body': '```suggestion\n```'})
    assert cut.suggestions == ('',)
    assert pr_marks.parse_comment({'path': 'f', 'subject_type': 'file', 'body': 'x'}) is None
    assert pr_marks.parse_comment({'path': 'f', 'line': 2, 'side': 'LEFT', 'body': 'x'}) is None


def _fake_gh(monkeypatch, pages):
    def run(args, **k):
        path = args[3] if args[2] == '--paginate' else args[2]
        out = pages.get(path.split('/', 4)[-1] if False else path, [])
        if isinstance(out, dict):
            text = json.dumps(out)
        else:
            text = '\n'.join(json.dumps(x) for x in out)
        return subprocess.CompletedProcess(args, 0, text, '')
    monkeypatch.setattr(pr_marks.subprocess, 'run', run)


def test_fetch_keeps_only_the_authors_comments_since_the_round(monkeypatch):
    me, bot = {'login': 'ben', 'type': 'User'}, {'login': 'ci[bot]', 'type': 'Bot'}
    _fake_gh(monkeypatch, {
        'repos/{owner}/{repo}/pulls/7': {'user': me, 'head': {'sha': 'abc'}},
        'repos/{owner}/{repo}/pulls/7/files': [{'filename': RF}],
        'repos/{owner}/{repo}/pulls/7/comments': [
            {'user': me, 'path': RF, 'line': 9, 'body': '```suggestion\n```'},
            {'user': me, 'path': RF, 'subject_type': 'file', 'body': 'All too long.',
             'created_at': '2026-11-15T01:00:00Z'},
            {'user': bot, 'path': RF, 'line': 9, 'body': 'lint'},
            {'user': {'login': 'amy', 'type': 'User'}, 'path': RF, 'line': 9, 'body': 'hm'}],
        'repos/{owner}/{repo}/pulls/7/reviews': [
            {'user': me, 'body': 'Old reaction', 'submitted_at': '2026-11-01T00:00:00Z'},
            {'user': me, 'body': 'More like B.', 'submitted_at': '2026-11-15T02:00:00Z'}],
        'repos/{owner}/{repo}/issues/7/comments': [
            {'user': bot, 'body': 'CI passed', 'created_at': '2026-11-15T03:00:00Z'}],
    })
    m = pr_marks.fetch(7, '.', since='2026-11-14T00:00:00Z')
    assert [c.suggestions for c in m.lines] == [('',)]
    assert m.general == [f'On {RF} as a whole: All too long.', 'More like B.']
    assert any('ci[bot]' in n and 'amy' in n for n in m.notes)
    assert any('before this round' in n for n in m.notes)


def test_gh_failures_are_errors(monkeypatch):
    monkeypatch.setattr(pr_marks.subprocess, 'run', lambda *a, **k:
                        subprocess.CompletedProcess(a, 1, '', 'HTTP 404'))
    with pytest.raises(pr_marks.PrMarksError, match='HTTP 404'):
        pr_marks.fetch(7, '.', author='ben')
    monkeypatch.setattr(pr_marks.subprocess, 'run', lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, 'not json\n', ''))
    with pytest.raises(pr_marks.PrMarksError, match="isn't JSON"):
        pr_marks.fetch(7, '.', author='ben')


# --- writing rounds ---

@pytest.fixture
def calls(monkeypatch, tmp_path):
    """`api.invoke` answering a round with as many versions as asked (or
    `calls.reply`), a review and a revision by schema; the blocking read
    finds nothing; keys go under tmp_path."""
    import re as _re
    from storyforge import api, blocking
    class Seen(list):
        reply = None

    seen = Seen()
    seen.blocking = []

    def fake(prompt, model, tokens, **k):
        seen.append(prompt)
        props = k['output_schema']['properties']
        if 'variants' in props:
            if seen.reply is not None:
                text = {'variants': seen.reply}
            else:
                n = int(_re.search(r'Write exactly (\d+)', prompt).group(1))
                names = _re.search(r'exactly one of: (.+)\.$', prompt.strip())
                tried = (names.group(1).split('; ') if names else
                         [f'try {i}' for i in range(n)])
                text = {'variants': [{'tried': t, 'text': f'Version {i} ran. It stopped.'}
                                     for i, t in enumerate(tried[:n])]}
        elif 'findings' in props:   # the blocking read, when it isn't stubbed
            seen.blocking.append(prompt)
            text = {'findings': []}
        elif 'flags' in props:
            text = {'flags': []}
        else:
            text = {'edits': [], 'kept': []}
        return {'content': [{'type': 'text', 'text': json.dumps(text)}],
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    monkeypatch.setattr(api, 'invoke', fake)
    monkeypatch.setattr(blocking, 'check_blocking',
                        lambda *a, **k: blocking.BlockingResult(SCENE))
    monkeypatch.setattr(vs, 'KEYS_ROOT', str(tmp_path / 'keys'))
    return seen


def test_a_round_is_written_shuffled_checked_and_keyed(project_dir, calls, tmp_path):
    rnd = vs.write_round(project_dir, SCENE, variants=5, vary=['tense'], influences='Renault',
                         model='m', log_dir=str(tmp_path / 'logs'), rng=random.Random(1))
    assert rnd.number == 1 and rnd.text.count('## Sample ') == 5
    assert 'try ' not in rnd.text                                  # blind
    samples = vs.parse_round(rnd.text)
    for label, tried in rnd.key.tried.items():                     # the key fits its label
        i = tried.split()[-1]
        assert f'Version {i} ran.' in vs.join_lines(samples[label].text)
    assert 'Renault' in calls[0] and 'The Finest Cartographer' in calls[0]
    assert 'Her heart pounded' in calls[1] and 'Her heart pounded' not in calls[0]
    vs.save_key(project_dir, rnd.key)
    assert vs.load_key(project_dir, 1) == rnd.key
    assert rnd.key.digest == vs.samples_digest(samples)


@pytest.mark.parametrize('reply', [
    [{'tried': f't{i}', 'text': 'X.'} for i in range(5)],          # more than asked
    [{'tried': 't', 'text': 'X.'}],                                 # fewer
    [{'tried': 't', 'text': ''}, {'tried': 'u', 'text': 'Y.'}, {'tried': 'v', 'text': 'Z.'}],
])
def test_a_round_needs_exactly_the_versions_asked_for(project_dir, calls, tmp_path, reply):
    calls.reply = reply
    with pytest.raises(vs.SampleError, match='were asked for'):
        vs.write_round(project_dir, SCENE, variants=3, vary=['tense'], influences='',
                       model='m', log_dir=str(tmp_path))


def test_a_later_round_writes_toward_the_keeps(project_dir, calls, tmp_path):
    vs.write_round(project_dir, SCENE, variants=3, vary=['tense'], influences='', model='m',
                   log_dir=str(tmp_path), marked='## The last round, as the author marked it')
    assert 'Write toward what the author kept' in calls[0]


def test_a_take_matches_versions_by_name_and_carries_the_blend(project_dir, calls, tmp_path):
    calls.reply = [{'tried': 'past tense', 'text': 'He ran.'},
                   {'tried': 'present tense', 'text': 'He runs.'}]
    prev = vs.RoundKey(1, SCENE, ('tense', 'distance'), 'Renault', {'A': 'x'})
    rnd = vs.write_take(project_dir, SCENE, sample='B', marked='MARKED', model='m',
                        versions=['present tense', 'past tense'], log_dir=str(tmp_path),
                        previous=prev)
    samples = vs.parse_round(rnd.text)
    assert vs.join_lines(samples['present tense'].text) == 'He runs.'
    assert vs.join_lines(samples['past tense'].text) == 'He ran.'
    assert (rnd.key.influences, rnd.key.vary, rnd.key.take) == ('Renault',
                                                                ('tense', 'distance'), 'B')
    calls.reply = [{'tried': 'present tense', 'text': 'A.'},
                   {'tried': 'present tense', 'text': 'B.'}]
    with pytest.raises(vs.SampleError, match='once each'):
        vs.write_take(project_dir, SCENE, sample='B', marked='M', model='m',
                      versions=['present tense', 'past tense'], log_dir=str(tmp_path))
    with pytest.raises(vs.SampleError, match='twice'):
        vs.write_take(project_dir, SCENE, sample='B', marked='M', model='m',
                      versions=['a', 'A'], log_dir=str(tmp_path))


def test_a_slip_found_before_publishing_is_fixed_and_said(project_dir, monkeypatch, tmp_path):
    from storyforge import api, blocking
    from storyforge.checker import Finding

    def fake(prompt, model, tokens, **k):
        props = k['output_schema']['properties']
        text = ({'flags': []} if 'flags' in props else
                {'edits': [{'flag': 1, 'find': ' with both hands full', 'replace': ''}],
                 'kept': []})
        return {'content': [{'type': 'text', 'text': json.dumps(text)}],
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    monkeypatch.setattr(api, 'invoke', fake)
    slip = Finding('contradiction', 'BLK', 'waved with both hands full', SCENE, '', '',
                   'his hands are full')
    gone = Finding('contradiction', 'BLK', 'not in the text', SCENE, '', '', 'x')
    monkeypatch.setattr(blocking, 'check_blocking',
                        lambda *a, **k: blocking.BlockingResult(SCENE, findings=[slip, gone]))
    texts, notes = vs.check_samples(project_dir, SCENE,
                                    {'A': 'He waved with both hands full. She went.'},
                                    model='m', log_dir=str(tmp_path))
    assert texts['A'] == 'He waved. She went.'
    assert any("aren't in the sample, left out" in n for n in notes)
    assert 'flagged before you saw it' in notes[-1]


def test_a_check_that_fails_is_said_and_the_sample_kept(project_dir, monkeypatch, tmp_path):
    from storyforge import blocking
    monkeypatch.setattr(blocking, 'check_blocking', lambda *a, **k: (_ for _ in ()).throw(
        blocking.BlockingError('refused')))
    from storyforge import voice_review
    monkeypatch.setattr(voice_review, 'review', lambda *a, **k: (_ for _ in ()).throw(
        voice_review.VoiceReviewError('cut off')))
    texts, notes = vs.check_samples(project_dir, SCENE, {'A': 'X.'}, model='m',
                                    log_dir=str(tmp_path))
    assert texts == {'A': 'X.'}
    assert any("physical check didn't finish" in n for n in notes)
    assert any("voice review didn't finish" in n for n in notes)


# --- the key ---

def test_a_corrupt_key_is_an_error_a_missing_one_is_none(project_dir, monkeypatch, tmp_path):
    monkeypatch.setattr(vs, 'KEYS_ROOT', str(tmp_path))
    assert vs.load_key(project_dir, 1) is None
    path = vs.key_path(project_dir, 1)
    os.makedirs(os.path.dirname(path))
    with open(path, 'w') as f:
        f.write('[1, 2]')
    with pytest.raises(vs.SampleError, match="isn't a round key"):
        vs.load_key(project_dir, 1)
    with open(path, 'w') as f:
        f.write('{not json')
    with pytest.raises(vs.SampleError, match="can't be read"):
        vs.load_key(project_dir, 1)


def test_the_key_is_outside_the_book(project_dir):
    assert not os.path.realpath(vs.key_path(project_dir, 1)).startswith(
        os.path.realpath(project_dir))


# --- the winner ---

def _round_file(project_dir, text=ROUND):
    path = os.path.join(project_dir, RF)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def test_promote_saves_the_sample_as_edited_with_its_header(project_dir):
    _round_file(project_dir, ROUND.replace('He saw her.', 'He saw her first.'))   # a hand edit
    rel = vs.promote(project_dir, RF, 'A', 'gate-run', kind='intimate', tense='past',
                     pov='Hector')
    from storyforge import voice_book
    a = [x for x in voice_book.read_folder(project_dir).anchors if x.name == 'gate-run'][0]
    assert (a.kind, a.tense, a.pov, a.text) == (('intimate',), 'past', 'Hector',
                                                'She ran. He saw her first.')
    with pytest.raises(vs.SampleError, match='there already'):
        vs.promote(project_dir, RF, 'A', 'gate-run')
    with pytest.raises(vs.SampleError, match='no sample'):
        vs.promote(project_dir, RF, 'Z', 'other')
    with pytest.raises(vs.SampleError, match='--tense'):
        vs.promote(project_dir, RF, 'A', 'x', tense='future')
    assert rel.endswith('gate-run.md')


def test_promote_checks_before_it_writes(project_dir):
    _round_file(project_dir, '## Sample A\n*0 words*\n\n')
    dest = os.path.join(project_dir, 'reference', 'voice', 'anchors',
                        'dorren-at-the-survey.md')
    before = open(dest).read()
    with pytest.raises(vs.SampleError, match="isn't an anchor"):
        vs.promote(project_dir, RF, 'A', 'dorren-at-the-survey', force=True)
    assert open(dest).read() == before


def test_promote_dry_run_writes_nothing(project_dir):
    _round_file(project_dir)
    rel = vs.promote(project_dir, RF, 'A', 'gate-run', dry_run=True)
    assert not os.path.exists(os.path.join(project_dir, rel))


# --- the command ---

@pytest.fixture
def cli(project_dir, monkeypatch, calls):
    """`voice sample` with git, gh and the PR helpers recorded."""
    from storyforge import cmd_voice, common, git
    monkeypatch.setattr(common, 'detect_project_root', lambda: project_dir)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test')
    monkeypatch.setattr(common, 'select_model', lambda t: 'm')
    state = {'branch': 'main', 'commits': [], 'prs': [], 'pr_ok': True, 'branch_ok': True,
             'prefix': ''}
    monkeypatch.setattr(git, 'current_branch', lambda pd: state['branch'])
    monkeypatch.setattr(git, 'create_branch',
                        lambda cmd, pd: 'storyforge/x' if state['branch_ok'] else '')
    monkeypatch.setattr(git, 'commit_and_push',
                        lambda pd, msg, paths: state['commits'].append((msg, paths)) or True)
    monkeypatch.setattr(git, 'create_draft_pr', lambda title, body, pd, *a: (
        state['prs'].append(body) or '9') if state['pr_ok'] else '')
    monkeypatch.setattr(cmd_voice, '_git_out', lambda pd, *a: state['prefix']
                        if a[:2] == ('rev-parse', '--show-prefix') else '')

    def run(*argv):
        return cmd_voice.main(['sample', *argv])
    run.state, run.calls = state, calls
    return run


def test_a_full_round_through_the_command(project_dir, cli):
    assert cli('--scene', SCENE, '--variants', '3') == 0
    (msg, paths), = cli.state['commits']
    assert paths == [RF] and 'round 1' in msg
    assert '--from-pr <this PR>' in cli.state['prs'][0]
    assert vs.load_key(project_dir, 1).scene == SCENE


@pytest.mark.parametrize('fail, why', [('branch_ok', 'no branch could be made'),
                                       ('pr_ok', 'no PR was opened')])
def test_a_failed_branch_or_pr_fails_the_run(project_dir, cli, capsys, fail, why):
    cli.state[fail] = False
    assert cli('--scene', SCENE, '--variants', '2') == 1
    assert why in capsys.readouterr().out


def _from_pr(project_dir, monkeypatch, cli, comments, head_text=None, prefix=''):
    _round_file(project_dir)
    rnd_key = vs.RoundKey(1, SCENE, ('tense',), 'Renault', {'A': 'close', 'B': 'far'}, '',
                          None, vs.samples_digest(vs.parse_round(ROUND)))
    vs.save_key(project_dir, rnd_key)
    cli.state['prefix'] = prefix
    monkeypatch.setattr(pr_marks, 'pr_info', lambda pr, d: {
        'author': 'ben', 'head_sha': 'abc', 'paths': [prefix + RF]})
    monkeypatch.setattr(pr_marks, 'file_at', lambda d, p, ref: head_text or ROUND)
    monkeypatch.setattr(pr_marks, 'fetch', lambda pr, d, since='': pr_marks.PrMarks(
        lines=comments, general=[]))


def test_from_pr_writes_the_next_round_toward_the_marks(project_dir, monkeypatch, cli):
    _from_pr(project_dir, monkeypatch, cli, [_c(_at('He saw her.'), 'keep')])
    assert cli('--from-pr', '7', '--variants', '2') == 0
    prompt = cli.calls[0]
    assert '"He saw her.": keep' in prompt and 'it tried: close' in prompt
    assert 'Renault' in prompt                                     # carried from the key


def test_from_pr_works_for_a_book_in_a_subfolder(project_dir, monkeypatch, cli):
    c = pr_marks.Comment('books/wrath/' + RF, _at('He saw her.'), 'keep',
                         line_text='He saw her.')
    _from_pr(project_dir, monkeypatch, cli, [c], prefix='books/wrath/')
    assert cli('--from-pr', '7', '--variants', '2') == 0
    assert '"He saw her.": keep' in cli.calls[0]


def test_from_pr_refuses_a_stale_local_round(project_dir, monkeypatch, cli, capsys):
    _from_pr(project_dir, monkeypatch, cli, [], head_text=ROUND + '\nEdited on GitHub.\n')
    assert cli('--from-pr', '7') == 1
    assert 'pull the branch first' in capsys.readouterr().out


def test_from_pr_refuses_a_round_with_no_marks(project_dir, monkeypatch, cli, capsys):
    _from_pr(project_dir, monkeypatch, cli, [])
    assert cli('--from-pr', '7') == 1
    assert 'unsubmitted review' in capsys.readouterr().out
    assert cli('--from-pr', '7', '--variants', '2', '--allow-unmarked') == 0


def test_from_pr_must_hold_the_latest_round(project_dir, monkeypatch, cli, capsys):
    _from_pr(project_dir, monkeypatch, cli, [])
    monkeypatch.setattr(pr_marks, 'pr_info', lambda pr, d: {
        'author': 'ben', 'head_sha': 'abc', 'paths': ['working/voice-samples/round-9.md']})
    assert cli('--from-pr', '7') == 1
    assert "doesn't change working/voice-samples/round-1.md" in capsys.readouterr().out


@pytest.mark.parametrize('argv, why', [
    (['--take', 'B'], '--from-pr'),
    (['--promote', 'x.md'], '--sample and --name'),
    ([], 'name the scene'),
])
def test_the_cli_says_what_is_missing(project_dir, cli, capsys, argv, why):
    assert cli(*argv) == 1
    assert why in capsys.readouterr().out


def test_a_take_needs_versions_before_anything_is_spent(project_dir, monkeypatch, cli, capsys):
    _from_pr(project_dir, monkeypatch, cli, [_c(_at('He saw her.'), 'keep')])
    assert cli('--from-pr', '7', '--take', 'A') == 1
    assert cli.calls == [] and '--take needs --versions' in capsys.readouterr().out


def test_promote_through_the_command_is_on_a_branch(project_dir, monkeypatch, cli):
    from storyforge import git
    _round_file(project_dir)
    made = []
    monkeypatch.setattr(git, 'ensure_on_branch', lambda cmd, pd: made.append(cmd) or 'b')
    assert cli('--promote', RF, '--sample', 'A', '--name', 'gate-run') == 0
    assert made == ['voice-anchor'] and cli.state['commits']


def test_a_dry_run_round_spends_nothing(project_dir, cli, capsys):
    assert cli('--scene', SCENE, '--dry-run') == 0
    assert cli.calls == [] and 'Round 1: act1-sc01, 5 versions' in capsys.readouterr().out


# --- a moment, before the scene map (#656) ---

MOMENT = 'Dorren finds the village missing from the survey sheet.'


def test_a_round_of_a_moment_needs_no_scene(project_dir, calls, tmp_path):
    with open(os.path.join(project_dir, 'reference', 'story-summary.md'), 'w') as f:
        f.write('## Logline\nA mapmaker.\n\n## Synopsis\nSYNOPSIS MARK. She draws.\n')
    rnd = vs.write_round(project_dir, '', variants=2, vary=['narrator stance'], influences='',
                         model='m', log_dir=str(tmp_path / 'logs'), moment=MOMENT)
    assert MOMENT in calls[0] and 'SYNOPSIS MARK' in calls[0]
    assert 'no scene map yet' in calls[0]
    assert 'The Finest Cartographer' not in calls[0]          # no scene's plan
    assert rnd.text.startswith('# Voice samples, round 1: a moment (Dorren finds')
    assert (rnd.key.scene, rnd.key.moment) == ('', MOMENT)
    vs.save_key(project_dir, rnd.key)
    assert vs.load_key(project_dir, 1) == rnd.key
    take = vs.write_take(project_dir, '', sample='A', marked='M', model='m',
                         versions=['try 0', 'try 1'], log_dir=str(tmp_path / 'logs'),
                         previous=rnd.key, moment=MOMENT)
    assert take.key.moment == MOMENT
    assert any(MOMENT in c and 'differ only in this' in c for c in calls)


def test_a_key_from_before_moments_still_loads():
    key = vs.RoundKey.from_json({'round': 1, 'scene': SCENE, 'tried': {}}, 'k')
    assert (key.scene, key.moment, key.subject) == (SCENE, '', SCENE)


def test_a_moment_title_is_one_short_line():
    title = vs.moment_title('One\n two ' + 'word ' * 30)
    assert title.startswith('a moment (One two word') and title.endswith('…)')
    assert '\n' not in title


def test_a_moment_or_a_scene_not_both(project_dir, calls, tmp_path):
    with pytest.raises(vs.SampleError, match='not both'):
        vs.write_round(project_dir, SCENE, variants=2, vary=['tense'], influences='',
                       model='m', log_dir=str(tmp_path), moment=MOMENT)
    with pytest.raises(vs.SampleError, match='empty'):
        vs._moment_context(project_dir, '  ')


def test_a_round_of_a_moment_through_the_command(project_dir, cli):
    assert cli('--moment', MOMENT, '--variants', '2') == 0
    (msg, paths), = cli.state['commits']
    assert 'samples of a moment (Dorren finds' in msg
    assert vs.load_key(project_dir, 1).moment == MOMENT


@pytest.mark.parametrize('argv, why', [
    (['--scene', SCENE, '--moment', MOMENT], 'not both'),
    (['--moment', ' '], '--moment is empty'),
    ([], 'or before the scene map a moment'),
])
def test_the_cli_refuses_a_moment_it_cant_use(project_dir, cli, capsys, argv, why):
    assert cli(*argv) == 1
    assert cli.calls == [] and why in capsys.readouterr().out


def test_from_pr_carries_the_moment(project_dir, monkeypatch, cli):
    _from_pr(project_dir, monkeypatch, cli, [_c(_at('He saw her.'), 'keep')])
    vs.save_key(project_dir, vs.RoundKey(1, '', ('tense',), '', {'A': 'close', 'B': 'far'},
                                         '', None, vs.samples_digest(vs.parse_round(ROUND)),
                                         MOMENT))
    assert cli('--from-pr', '7', '--variants', '2') == 0
    assert MOMENT in cli.calls[0]
    assert vs.load_key(project_dir, 2).moment == MOMENT


# --- the #656 review ---

def _summary(project_dir, synopsis):
    with open(os.path.join(project_dir, 'reference', 'story-summary.md'), 'w',
              encoding='utf-8') as f:
        f.write(f'## Logline\nA mapmaker.\n\n## Synopsis\n{synopsis}\n')


def test_a_moment_round_never_sends_the_template_synopsis(project_dir, calls, tmp_path):
    # SF-4: init's template text isn't the book
    from storyforge.common import get_plugin_dir, parse_story_summary
    template = parse_story_summary(os.path.join(get_plugin_dir(), 'templates'))['synopsis']
    assert 'Opens with a hook' in template
    _summary(project_dir, template)
    rnd = vs.write_round(project_dir, '', variants=2, vary=['tense'], influences='',
                         model='m', log_dir=str(tmp_path), moment=MOMENT)
    assert 'Opens with a hook' not in calls[0]
    assert any("synopsis is still init's template: the round had only the moment's words"
               in n for n in rnd.notes)


def test_a_moment_round_without_a_synopsis_says_so(project_dir, calls, tmp_path):
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    if os.path.exists(path):
        os.remove(path)
    rnd = vs.write_round(project_dir, '', variants=2, vary=['tense'], influences='',
                         model='m', log_dir=str(tmp_path), moment=MOMENT)
    assert any('story-summary.md is missing: the round had only' in n for n in rnd.notes)
    _summary(project_dir, '')
    rnd = vs.write_round(project_dir, '', variants=2, vary=['tense'], influences='',
                         model='m', log_dir=str(tmp_path), moment=MOMENT)
    assert any('has no synopsis' in n for n in rnd.notes)


def test_a_story_summary_it_cant_read_is_an_error_not_a_traceback(project_dir, cli, capsys):
    # SF-L
    with open(os.path.join(project_dir, 'reference', 'story-summary.md'), 'wb') as f:
        f.write(b'## Synopsis\n\xff\n')
    assert cli('--moment', MOMENT, '--variants', '2') == 1
    assert "ERROR: reference/story-summary.md can't be read" in capsys.readouterr().out


def test_a_moment_round_runs_the_real_physical_check_with_no_pov(project_dir, calls, tmp_path,
                                                                 monkeypatch):
    # T-2: the blocking read on a moment, which has no scenes.csv row
    from storyforge import blocking
    monkeypatch.setattr(blocking, 'check_blocking', REAL_CHECK_BLOCKING)
    os.remove(os.path.join(project_dir, 'reference', 'scenes.csv'))   # no map yet
    rnd = vs.write_round(project_dir, '', variants=2, vary=['tense'], influences='',
                         model='m', log_dir=str(tmp_path), moment=MOMENT)
    assert len(calls.blocking) == 2                                # one reading a sample
    assert all('voice-moment' in p for p in calls.blocking)
    assert vs.MOMENT_CHECK_NOTE in rnd.notes
    assert not any("physical check didn't finish" in n for n in rnd.notes)


@pytest.mark.parametrize('kwargs, why', [
    ({'scene': 's', 'moment': 'm'}, 'not both'),
    ({'scene': ''}, 'has neither'),
    ({'scene': '', 'moment': '  '}, 'has neither'),
])
def test_a_round_key_names_a_scene_or_a_moment(kwargs, why):
    # TD-2
    with pytest.raises(ValueError, match=why):
        vs.RoundKey(1, **kwargs)
    with pytest.raises(vs.SampleError, match=why):
        vs.RoundKey.from_json({'round': 1, 'tried': {}, **kwargs}, 'k')


def test_a_key_saved_with_a_null_scene_loads_as_its_moment():
    key = vs.RoundKey.from_json({'round': 1, 'scene': None, 'moment': MOMENT}, 'k')
    assert (key.scene, key.moment) == ('', MOMENT)


@pytest.mark.parametrize('argv, said', [
    (['--scene', 'act1-sc02'], '--scene act1-sc02 is not what round 1 marked (act1-sc01)'),
    (['--moment', MOMENT], '--moment is not what round 1 marked (act1-sc01)'),
])
def test_from_pr_says_when_the_round_asked_for_isnt_the_one_marked(project_dir, monkeypatch,
                                                                   cli, capsys, argv, said):
    # T-3
    _from_pr(project_dir, monkeypatch, cli, [_c(_at('He saw her.'), 'keep')])
    assert cli('--from-pr', '7', '--variants', '2', *argv) == 0
    assert f'NOTE: {said}' in capsys.readouterr().out

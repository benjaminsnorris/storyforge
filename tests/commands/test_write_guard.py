"""A reply that is refused, cut off at max_tokens, or ends mid-sentence never
becomes a scene: `write` skips that scene, drafts the rest, and exits 1 naming
it. Before this a cut-off draft passed the 100-word floor and was committed as
drafted, and batch mode could not tell at all (its saved response had no
stop_reason)."""

import json
import os

import pytest

from storyforge.cmd_write import main

GOOD = ' '.join(['word'] * 200) + '.'
CUT_OFF = ' '.join(['word'] * 200) + ' and then she'


def _pending(project_dir, *scene_ids):
    from storyforge.csv_cli import update_field
    meta = os.path.join(project_dir, 'reference', 'scenes.csv')
    for sid in scene_ids:
        update_field(meta, sid, 'status', 'briefed')
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if os.path.isfile(path):
            os.remove(path)


def _status(project_dir, sid):
    from storyforge.csv_cli import get_field
    return get_field(os.path.join(project_dir, 'reference', 'scenes.csv'), sid, 'status')


def _scene(project_dir, sid):
    path = os.path.join(project_dir, 'scenes', f'{sid}.md')
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return f.read()


def _reply(text, stop_reason='end_turn', **extra):
    return {'content': [{'type': 'text', 'text': text}], 'stop_reason': stop_reason,
            'usage': {'input_tokens': 100, 'output_tokens': 50}, **extra}


@pytest.fixture
def setup(mock_api, mock_git, mock_costs, project_dir, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_write.detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.cmd_write.time.sleep', lambda s: None)
    _pending(project_dir, 'act1-sc01', 'act1-sc02')
    return project_dir


def _direct_replies(monkeypatch, replies):
    """Serve ``replies[scene_id]`` from invoke_to_file, raising RefusalError
    after logging a refusal, as api.invoke_to_file does."""
    from storyforge.api import RefusalError

    def fake(prompt, model, log_file, max_tokens=4096, label='', timeout=600,
             system=None, output_schema=None):
        sid = label.split()[-1]
        response = replies[sid]
        with open(log_file, 'w') as f:
            json.dump(response, f)
        if response.get('stop_reason') == 'refusal':
            raise RefusalError(response)
        return response
    monkeypatch.setattr('storyforge.cmd_write.invoke_to_file', fake)


class TestDirectMode:
    @pytest.mark.parametrize('bad, reason', [
        (_reply(GOOD, 'max_tokens'), 'cut off at max_tokens'),
        (_reply(CUT_OFF), 'mid-sentence'),
        (_reply('', 'refusal', stop_details={'type': 'refusal', 'category': 'cyber'}),
         'refused (cyber)'),
    ])
    def test_bad_reply_skips_scene_and_drafts_the_rest(self, setup, monkeypatch,
                                                       capsys, bad, reason):
        _direct_replies(monkeypatch, {'act1-sc01': bad, 'act1-sc02': _reply(GOOD)})
        with pytest.raises(SystemExit) as exc:
            main(['--direct', '--scenes', 'act1-sc01,act1-sc02'])
        assert exc.value.code == 1
        assert _scene(setup, 'act1-sc01') is None
        assert _status(setup, 'act1-sc01') == 'briefed'
        assert _scene(setup, 'act1-sc02').strip() == GOOD
        assert _status(setup, 'act1-sc02') == 'drafted'
        out = capsys.readouterr().out
        assert 'not drafted' in out and reason in out

    def test_cut_off_redraft_keeps_existing_prose(self, setup, monkeypatch):
        old = ' '.join(['original'] * 300) + '.'
        with open(os.path.join(setup, 'scenes', 'act1-sc01.md'), 'w') as f:
            f.write(old)
        _direct_replies(monkeypatch, {'act1-sc01': _reply(CUT_OFF)})
        with pytest.raises(SystemExit):
            main(['--direct', '--force', '--scenes', 'act1-sc01'])
        assert _scene(setup, 'act1-sc01') == old

    def test_clean_run_does_not_exit(self, setup, monkeypatch):
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD), 'act1-sc02': _reply(GOOD)})
        main(['--direct', '--scenes', 'act1-sc01,act1-sc02'])
        assert _status(setup, 'act1-sc01') == 'drafted'


class TestBatchMode:
    def test_cut_off_batch_reply_is_not_written(self, setup, mock_api, monkeypatch, capsys):
        """Batch results now carry stop_reason, so a cut-off reply is caught."""
        replies = {'act1-sc01': _reply(GOOD, 'max_tokens'), 'act1-sc02': _reply(GOOD)}

        def fake_download(results_url, output_dir, log_dir):
            for sid, response in replies.items():
                with open(os.path.join(output_dir, f'.status-{sid}'), 'w') as f:
                    f.write('ok')
                with open(os.path.join(log_dir, f'{sid}.json'), 'w') as f:
                    json.dump(response, f)
            return list(replies)
        monkeypatch.setattr('storyforge.cmd_write.download_batch_results', fake_download)

        with pytest.raises(SystemExit) as exc:
            main(['--scenes', 'act1-sc01,act1-sc02'])
        assert exc.value.code == 1
        assert _scene(setup, 'act1-sc01') is None
        assert _scene(setup, 'act1-sc02').strip() == GOOD
        assert 'cut off at max_tokens' in capsys.readouterr().out


class TestReviseRedraftFromBriefs:
    def test_unwritten_redraft_halts_after_committing_the_rest(
            self, mock_api, mock_git, project_dir, monkeypatch):
        from storyforge import cmd_revise
        old = _scene(project_dir, 'act1-sc01')
        replies = iter([_reply(CUT_OFF), _reply(GOOD)])

        def fake(prompt, model, log_file, max_tokens=4096, label='', timeout=600,
                 system=None, output_schema=None):
            with open(log_file, 'w') as f:
                json.dump(next(replies), f)
        monkeypatch.setattr('storyforge.api.invoke_to_file', fake)
        monkeypatch.setattr('storyforge.cmd_write._build_prompt',
                            lambda *a, **k: 'prompt')
        with pytest.raises(SystemExit) as exc:
            cmd_revise._redraft_from_briefs(
                project_dir, ['act1-sc01', 'act1-sc02'], 'm',
                os.path.join(project_dir, 'working', 'logs'), system=[])
        assert exc.value.code == 1
        assert _scene(project_dir, 'act1-sc01') == old
        assert _scene(project_dir, 'act1-sc02').strip() == GOOD
        commits = [c for c in mock_git.calls if c[0] == 'commit_and_push']
        assert commits  # the good redraft is committed before the halt

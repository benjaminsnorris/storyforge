"""A reply that is refused, cut off at max_tokens, or ends mid-sentence never
becomes a scene: `write` skips that scene, drafts the rest, and exits 1 naming
it. Before this a cut-off draft passed the 100-word floor and was committed as
drafted, and batch mode could not tell at all (its saved response had no
stop_reason). Also covers coach/strict replies (saved to working/coaching/,
never over prose) and revise's redraft from briefs, which shares the guard."""

import json
import os
import re

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
    # --coaching sets STORYFORGE_COACHING in os.environ; keep it to this test
    # (setenv records the original so teardown restores it; delenv alone
    # does not when the variable was absent)
    monkeypatch.setenv('STORYFORGE_COACHING', 'full')
    monkeypatch.delenv('STORYFORGE_COACHING')
    monkeypatch.setattr('storyforge.cmd_write.time.sleep', lambda s: None)
    _pending(project_dir, 'act1-sc01', 'act1-sc02')
    return project_dir


def _direct_replies(monkeypatch, replies):
    """Serve ``replies[scene_id]`` from invoke_to_file, raising RefusalError
    after logging a refusal, as api.invoke_to_file does. Returns the list of
    (scene_id, fallback) calls."""
    from storyforge.api import RefusalError
    calls = []

    def fake(prompt, model, log_file, max_tokens=4096, label='', timeout=600,
             system=None, output_schema=None, fallback=False):
        sid = label.split()[-1]
        calls.append((sid, fallback))
        response = replies[sid]
        with open(log_file, 'w') as f:
            json.dump(response, f)
        if response.get('stop_reason') == 'refusal':
            raise RefusalError(response)
        return response
    monkeypatch.setattr('storyforge.cmd_write.invoke_to_file', fake)
    return calls


# What the API returns when the refusal fallback wrote the reply.
def _fallback_reply(text, model='claude-opus-5'):
    reply = _reply(text, model=model)
    reply['usage']['iterations'] = [{'type': 'message', 'model': None},
                                    {'type': 'fallback_message', 'model': model}]
    return reply


class TestDirectMode:
    @pytest.mark.parametrize('bad, reason', [
        (_reply(GOOD, 'max_tokens'), 'cut off at max_tokens'),
        (_reply(CUT_OFF), 'mid-sentence'),
        (_reply('', 'refusal', stop_details={'type': 'refusal', 'category': 'cyber'}),
         'refused the request (cyber)'),
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

    def test_empty_reply_is_not_written(self, setup, monkeypatch, capsys):
        _direct_replies(monkeypatch, {'act1-sc01': _reply('')})
        with pytest.raises(SystemExit):
            main(['--direct', '--scenes', 'act1-sc01'])
        assert _scene(setup, 'act1-sc01') is None
        assert 'the API response is empty' in capsys.readouterr().out

    def test_collapsed_redraft_keeps_existing_prose(self, setup, monkeypatch, capsys):
        """Before this guard, --force replaced a scene with any reply over
        100 words."""
        old = ' '.join(['original'] * 1000) + '.'
        with open(os.path.join(setup, 'scenes', 'act1-sc01.md'), 'w') as f:
            f.write(old)
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        with pytest.raises(SystemExit):
            main(['--direct', '--force', '--scenes', 'act1-sc01'])
        assert _scene(setup, 'act1-sc01') == old
        assert 'collapsed' in capsys.readouterr().out

    def test_literary_ending_is_written(self, setup, monkeypatch):
        ending = ' '.join(['word'] * 200) + ', and she was gone\u2026\n\n* * *'
        _direct_replies(monkeypatch, {'act1-sc01': _reply(ending)})
        main(['--direct', '--scenes', 'act1-sc01'])
        assert _status(setup, 'act1-sc01') == 'drafted'

    def test_unwritten_reply_is_still_costed(self, setup, monkeypatch, mock_costs):
        """A refused or cut-off reply is paid for, so it is logged."""
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD, 'max_tokens')})
        with pytest.raises(SystemExit):
            main(['--direct', '--scenes', 'act1-sc01'])
        assert [op['target'] for op in mock_costs.operations] == ['act1-sc01']

    def test_drafts_opt_into_the_refusal_fallback(self, setup, monkeypatch):
        calls = _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD)})
        main(['--direct', '--scenes', 'act1-sc01'])
        assert calls == [('act1-sc01', True)]

    def test_fallback_draft_is_costed_as_the_model_that_wrote_it(
            self, setup, monkeypatch, mock_costs):
        _direct_replies(monkeypatch, {'act1-sc01': _fallback_reply(GOOD)})
        main(['--direct', '--scenes', 'act1-sc01'])
        assert _status(setup, 'act1-sc01') == 'drafted'
        assert [op['model'] for op in mock_costs.operations if 'model' in op
                and op['operation'] == 'draft'] == ['claude-opus-5']

    def test_fallback_draft_is_named_in_commit_and_summary(
            self, setup, monkeypatch, mock_git, capsys):
        """H1: a scene another model wrote is recorded, not just warned about
        mid-run."""
        from storyforge import api
        calls = _direct_replies(monkeypatch, {'act1-sc01': _fallback_reply(GOOD)})
        # the fake bypasses api._send, which records each fallback reply
        api._fallback_replies.append(('drafting act1-sc01', 'claude-opus-5-5',
                                      'claude-opus-5'))
        main(['--direct', '--scenes', 'act1-sc01'])
        assert calls
        commits = [c[1] for c in mock_git.calls if c[0] == 'commit_and_push']
        assert 'Draft scene act1-sc01 (refusal fallback: written by claude-opus-5)' in commits
        out = capsys.readouterr().out
        assert 'WARNING: 1 reply was written by another model' in out
        assert 'drafting act1-sc01: claude-opus-5 in place of claude-opus-5-5' in out

    def test_clean_run_does_not_exit(self, setup, monkeypatch):
        _direct_replies(monkeypatch, {'act1-sc01': _reply(GOOD), 'act1-sc02': _reply(GOOD)})
        main(['--direct', '--scenes', 'act1-sc01,act1-sc02'])
        assert _status(setup, 'act1-sc01') == 'drafted'


class TestBatchMode:
    """Batch results now carry stop_reason, so batch mode is guarded too."""

    REFUSAL = _reply('', 'refusal', stop_details={'type': 'refusal', 'category': 'cyber'})

    def _run(self, monkeypatch, results, code=1):
        """``results[scene_id]`` is a reply dict, 'errored' (the batch request
        failed) or None (status ok but no response file)."""
        def fake_download(results_url, output_dir, log_dir, keep_incomplete=False):
            assert keep_incomplete  # write retries refusals itself
            for sid, response in results.items():
                with open(os.path.join(output_dir, f'.status-{sid}'), 'w') as f:
                    f.write('fail' if response == 'errored' else 'ok')
                if isinstance(response, dict):
                    with open(os.path.join(log_dir, f'{sid}.json'), 'w') as f:
                        json.dump(response, f)
            return [sid for sid, r in results.items() if r != 'errored']
        monkeypatch.setattr('storyforge.cmd_write.download_batch_results', fake_download)
        if code is None:
            main(['--scenes', ','.join(results)])
            return
        with pytest.raises(SystemExit) as exc:
            main(['--scenes', ','.join(results)])
        assert exc.value.code == code

    @pytest.mark.parametrize('bad, reason', [
        (_reply(GOOD, 'max_tokens'), 'cut off at max_tokens'),
        ('errored', 'batch request failed'),
        (None, 'no response'),
    ])
    def test_bad_result_skips_scene(self, setup, monkeypatch, capsys, bad, reason):
        self._run(monkeypatch, {'act1-sc01': bad, 'act1-sc02': _reply(GOOD)})
        assert _scene(setup, 'act1-sc01') is None
        assert _scene(setup, 'act1-sc02').strip() == GOOD
        assert reason in capsys.readouterr().out

    def test_failed_reply_is_kept_for_the_author(self, setup, monkeypatch, capsys):
        """I2: the batch directory is removed; the paid reply is not."""
        self._run(monkeypatch, {'act1-sc01': _reply(CUT_OFF), 'act1-sc02': _reply(GOOD)})
        kept = os.path.join(setup, 'working', 'logs', 'drafting-act1-sc01.json')
        with open(kept) as f:
            assert json.load(f)['content'][0]['text'] == CUT_OFF
        assert kept in capsys.readouterr().out

    def test_refused_scene_is_retried_directly_with_the_fallback(
            self, setup, monkeypatch, capsys, mock_costs, mock_git):
        """The Batches API rejects the fallback, so a refused scene gets one
        direct call with it. Both calls are paid for and costed."""
        calls = _direct_replies(monkeypatch, {'act1-sc01': _fallback_reply(GOOD)})
        self._run(monkeypatch, {'act1-sc01': self.REFUSAL, 'act1-sc02': _reply(GOOD)},
                  code=None)
        assert calls == [('act1-sc01', True)]
        assert _scene(setup, 'act1-sc01').strip() == GOOD
        assert _status(setup, 'act1-sc01') == 'drafted'
        assert 'retrying it directly' in capsys.readouterr().out
        models = [op['model'] for op in mock_costs.operations
                  if op.get('target') == 'act1-sc01']
        assert len(models) == 2 and models[1] == 'claude-opus-5'
        commits = [c[1] for c in mock_git.calls if c[0] == 'commit_and_push']
        assert 'Draft scene act1-sc01 (refusal fallback: written by claude-opus-5)' in commits

    def test_refused_again_skips_the_scene(self, setup, monkeypatch, capsys):
        retry = dict(self.REFUSAL, id='the-retry')
        _direct_replies(monkeypatch, {'act1-sc01': retry})
        self._run(monkeypatch, {'act1-sc01': self.REFUSAL, 'act1-sc02': _reply(GOOD)})
        assert _scene(setup, 'act1-sc01') is None
        assert _scene(setup, 'act1-sc02').strip() == GOOD
        assert 'refused the request (cyber)' in capsys.readouterr().out
        with open(os.path.join(setup, 'working', 'logs', 'drafting-act1-sc01.json')) as f:
            assert json.load(f)['id'] == 'the-retry'  # the kept log is the retry's

    def test_failed_retry_skips_the_scene(self, setup, monkeypatch, capsys):
        def boom(*a, **k):
            raise RuntimeError('HTTP 529')
        monkeypatch.setattr('storyforge.cmd_write.invoke_to_file', boom)
        self._run(monkeypatch, {'act1-sc01': self.REFUSAL, 'act1-sc02': _reply(GOOD)})
        assert _scene(setup, 'act1-sc01') is None
        assert _scene(setup, 'act1-sc02').strip() == GOOD
        assert 'the retry failed: HTTP 529' in capsys.readouterr().out


class TestReviseRedraftFromBriefs:
    def _run(self, project_dir, monkeypatch, replies):
        from storyforge import cmd_revise
        from storyforge.api import RefusalError
        replies = iter(replies)

        def fake(prompt, model, log_file, max_tokens=4096, label='', timeout=600,
                 system=None, output_schema=None, fallback=False):
            assert fallback, 'a redraft is prose; it opts into the refusal fallback'
            response = next(replies)
            with open(log_file, 'w') as f:
                json.dump(response, f)
            if response.get('stop_reason') == 'refusal':
                raise RefusalError(response)
        monkeypatch.setattr('storyforge.api.invoke_to_file', fake)
        monkeypatch.setattr('storyforge.cmd_write._build_prompt',
                            lambda *a, **k: 'prompt')
        cmd_revise._redraft_from_briefs(
            project_dir, ['act1-sc01', 'act1-sc02'], 'm',
            os.path.join(project_dir, 'working', 'logs'), system=[])

    @pytest.mark.parametrize('bad, reason', [
        (_reply(CUT_OFF), 'mid-sentence'),
        (_reply('', 'refusal', stop_details={'type': 'refusal', 'category': 'cyber'}),
         'refused the request (cyber)'),
    ])
    def test_unwritten_redraft_raises_after_committing_the_rest(
            self, mock_api, mock_git, project_dir, monkeypatch, bad, reason):
        from storyforge.cmd_revise import RedraftError
        old = _scene(project_dir, 'act1-sc01')
        with pytest.raises(RedraftError, match=re.escape(reason)):
            self._run(project_dir, monkeypatch, [bad, _reply(GOOD)])
        assert _scene(project_dir, 'act1-sc01') == old
        assert _scene(project_dir, 'act1-sc02').strip() == GOOD
        commits = [c[1] for c in mock_git.calls if c[0] == 'commit_and_push']
        assert commits == ['Revision: redraft 1 scenes from corrected briefs']

    def test_scene_without_a_prompt_is_a_failure(self, mock_api, mock_git,
                                                  project_dir, monkeypatch):
        from storyforge.cmd_revise import RedraftError
        monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda *a, **k: '')
        with pytest.raises(RedraftError, match='no prompt'):
            from storyforge import cmd_revise
            cmd_revise._redraft_from_briefs(
                project_dir, ['act1-sc01'], 'm',
                os.path.join(project_dir, 'working', 'logs'), system=[])

    def test_deferred_redraft_failure_finishes_the_run_then_exits_1(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        """H3: the passes are already completed when the deferred redraft
        runs, so revise reports the failure after its summary, exits 1, does
        not advance the phase, and points at `write`, not at re-running revise."""
        from storyforge import cmd_revise
        from storyforge.cmd_revise import RedraftError, _write_csv_plan
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_revise.detect_project_root', lambda: project_dir)

        def hone(**k):  # rewrite a brief, as hone would
            with open(os.path.join(project_dir, 'reference', 'scene-briefs.csv'), 'a') as f:
                f.write('\n')
            return {'fields_rewritten': 1, 'scenes_rewritten': 1}
        monkeypatch.setattr('storyforge.hone.hone_briefs', hone)

        def failing(*a, **k):
            raise RedraftError('1 scene(s) not re-drafted: act1-sc01 (no prompt)')
        monkeypatch.setattr(cmd_revise, '_redraft_from_briefs', failing)
        plans = os.path.join(project_dir, 'working', 'plans')
        os.makedirs(plans, exist_ok=True)
        _write_csv_plan(os.path.join(plans, 'revision-plan.csv'), [{
            'pass': '1', 'name': 'brief-fix', 'purpose': 'p', 'scope': 'targeted',
            'targets': 'act1-sc01', 'guidance': 'g', 'protection': '', 'findings': '',
            'status': 'pending', 'model_tier': 'opus', 'fix_location': 'brief'}])

        with pytest.raises(SystemExit) as exc:
            cmd_revise.main([])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert 'Batch Redraft' in out  # the deferred path, the one revise takes
        assert 'Revision session complete' in out
        assert 'write --force --coaching full --scenes' in out
        assert 'All revision passes are done!' not in out


class TestEveryUndraftedSceneIsListed:
    """H2: `write` must not exit 0 while a scene went undrafted."""

    def test_short_complete_reply_is_not_written(self, setup, monkeypatch, capsys):
        _direct_replies(monkeypatch, {'act1-sc01': _reply('I cannot write this scene.'),
                                      'act1-sc02': _reply(GOOD)})
        with pytest.raises(SystemExit) as exc:
            main(['--direct', '--scenes', 'act1-sc01,act1-sc02'])
        assert exc.value.code == 1
        assert _scene(setup, 'act1-sc01') is None
        assert 'only 5 words' in capsys.readouterr().out

    def test_api_failure_lists_the_scene_and_every_later_one(self, setup, monkeypatch,
                                                            capsys):
        def boom(*a, **k):
            raise RuntimeError('overloaded')
        monkeypatch.setattr('storyforge.cmd_write.invoke_to_file', boom)
        with pytest.raises(SystemExit) as exc:
            main(['--direct', '--scenes', 'act1-sc01,act1-sc02'])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert '2 scene(s) not drafted' in out
        assert 'act1-sc02 (not attempted: the run stopped at act1-sc01)' in out


class TestCoachingReplies:
    """H1: a coach or strict reply is a brief, not prose. It goes to
    working/coaching/ and never over the scene file."""

    @pytest.mark.parametrize('level, name', [('coach', 'brief'), ('strict', 'constraints')])
    def test_brief_goes_to_coaching_file(self, setup, monkeypatch, level, name):
        prose = ' '.join(['original'] * 300) + '.'
        with open(os.path.join(setup, 'scenes', 'act1-sc01.md'), 'w') as f:
            f.write(prose)
        brief = '## Brief\n\n- Open on the map room\n- End on the missing village:'
        _direct_replies(monkeypatch, {'act1-sc01': _reply(brief)})
        main(['--direct', '--force', '--coaching', level, '--scenes', 'act1-sc01'])
        assert _scene(setup, 'act1-sc01') == prose
        with open(os.path.join(setup, 'working', 'coaching', f'{name}-act1-sc01.md')) as f:
            assert f.read() == brief

    def test_cut_off_brief_is_not_written(self, setup, monkeypatch):
        _direct_replies(monkeypatch, {'act1-sc01': _reply('## Brief\n- Open', 'max_tokens')})
        with pytest.raises(SystemExit):
            main(['--direct', '--coaching', 'coach', '--scenes', 'act1-sc01'])
        assert not os.path.exists(
            os.path.join(setup, 'working', 'coaching', 'brief-act1-sc01.md'))

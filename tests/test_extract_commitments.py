"""Extract phase 4: commitments by the reader-noticeable rubric (plan
decision 5) into the ledger."""

import json
import os

import pytest

from storyforge import ledger
from storyforge.extract import (COMMITMENT_RUBRIC, build_commitments_prompt,
                                parse_commitments_response)


def _reply(*items):
    return json.dumps({'commitments': [
        dict({'type': 'trait', 'subject': '', 'statement': 's', 'quote': '',
              'mutable': 'fixed', 'supersedes': ''}, **i) for i in items]})


class TestPrompt:
    def test_carries_the_rubric_the_scene_and_known_commitments(self):
        prompt = build_commitments_prompt(
            'sc1', 'Fred is Scrooge\'s nephew.', {'title': 'T', 'pov': 'scrooge'},
            registries_text='## Characters\n- fred', known=[
                {'id': 'k1', 'type': 'physical', 'subject': 'fred',
                 'statement': 'Fred has a cold.'}])
        assert COMMITMENT_RUBRIC in prompt
        assert "Fred is Scrooge's nephew." in prompt
        assert '- k1 [physical] fred: Fred has a cold.' in prompt
        assert 'There is no cap' in prompt

    def test_says_when_nothing_is_known(self):
        assert '(none yet)' in build_commitments_prompt('sc1', 'x', {})


class TestParse:
    def test_reads_each_commitment(self):
        got = parse_commitments_response(_reply(
            {'statement': 'Fred is the nephew.', 'subject': ' fred ', 'type': 'relationship'},
            {'statement': ''}), 'sc1')
        assert got == [{'type': 'relationship', 'subject': 'fred',
                        'statement': 'Fred is the nephew.', 'quote': '',
                        'mutable': 'fixed', 'supersedes': ''}]

    def test_an_unreadable_reply_raises(self):
        with pytest.raises(ValueError):
            parse_commitments_response('not json', 'sc1')


class TestViews:
    def test_the_views_leave_the_rubric_pass_rows_out_and_alone(self, project_dir):
        """Briefs reference registry facts by id; a commitment isn't one, and
        a view write must not drop it as "gone"."""
        ref = os.path.join(project_dir, 'reference')
        rows = ledger.load(project_dir)
        rows.append(dict({c: '' for c in ledger.COLUMNS}, id='c-1', type='physical',
                         subject='tessa-merrin', statement='Tessa holds the key.',
                         origin='prose', status='binding', mutable='state',
                         introduced_by=ledger.COMMITMENTS_PASS, scene_id='act1-sc01'))
        ledger.save(project_dir, rows)
        assert 'c-1' not in {r['id'] for r in ledger.read_view(ref, 'physical')}
        ledger.write_view(ref, 'physical', ledger.read_view(ref, 'physical'),
                          origin='prose', introduced_by='hone')
        assert 'c-1' in {r['id'] for r in ledger.load(project_dir)}
        with pytest.raises(ValueError, match='c-1'):
            ledger.write_view(ref, 'physical',
                              ledger.read_view(ref, 'physical') + [{'id': 'c-1'}],
                              origin='prose', introduced_by='hone')


class TestPhase4:
    def _run(self, project_dir, monkeypatch, replies, force=False):
        from storyforge import cmd_extract
        calls = []

        def invoke_to_file(prompt, model, log_file, max_tokens, **kw):
            sid = os.path.basename(log_file)[len('extract-commitments-'):-len('.json')]
            calls.append((sid, prompt))
            response = {'content': [{'type': 'text', 'text': replies.get(sid, _reply())}],
                        'stop_reason': 'end_turn',
                        'usage': {'input_tokens': 1, 'output_tokens': 1}}
            with open(log_file, 'w') as f:
                json.dump(response, f)
            return response
        monkeypatch.setattr(cmd_extract, 'invoke_to_file', invoke_to_file)
        monkeypatch.setattr(cmd_extract, 'commit_and_push', lambda *a, **k: True)
        ref = os.path.join(project_dir, 'reference')
        scenes = os.path.join(project_dir, 'scenes')
        order = cmd_extract._build_sorted_scene_ids(scenes, ref)
        log_dir = os.path.join(project_dir, 'working', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        cmd_extract._run_phase_4(order, project_dir, scenes, ref, log_dir, force, False)
        return order, calls

    def _mine(self, project_dir):
        return [r for r in ledger.load(project_dir)
                if r['introduced_by'] == ledger.COMMITMENTS_PASS]

    def test_writes_each_commitment_with_its_scene_and_quote(
            self, project_dir, monkeypatch, capsys):
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        first = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[0]
        with open(os.path.join(project_dir, 'scenes', f'{first}.md')) as f:
            words = ' '.join(f.read().split()[:6])
        before = [r for r in ledger.load(project_dir)]
        self._run(project_dir, monkeypatch, {first: _reply(
            {'statement': 'Dorren keeps the archive key.', 'subject': 'Dorren',
             'type': 'physical', 'mutable': 'state', 'quote': words},
            {'statement': 'The vault is three floors down.', 'subject': 'nowhere',
             'type': 'world', 'quote': 'not in the scene'})})
        mine = self._mine(project_dir)
        assert [(r['scene_id'], r['type'], r['subject'], r['status'], r['origin'])
                for r in mine] == [(first, 'physical', 'dorren-hayle', 'binding', 'prose'),
                                   (first, 'world', 'nowhere', 'binding', 'prose')]
        assert mine[0]['quote'] == words and mine[0]['id'].startswith(f'{first}--')
        # The registry rows are untouched
        assert [r for r in ledger.load(project_dir) if r not in mine] == before
        out = capsys.readouterr().out
        assert '1 quote(s) not found verbatim' in out
        assert "1 subject(s) not in the registries" in out

    def test_later_scenes_are_offered_earlier_commitments_and_supersede_them(
            self, project_dir, monkeypatch):
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        a, b = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[:2]
        self._run(project_dir, monkeypatch, {a: _reply(
            {'statement': 'Dorren keeps the key.', 'mutable': 'state', 'type': 'physical'})})
        key = self._mine(project_dir)[0]['id']
        # Forced, so scene a is re-extracted (same reply) and b supersedes
        order, calls = self._run(project_dir, monkeypatch, {
            a: _reply({'statement': 'Dorren keeps the key.', 'mutable': 'state',
                       'type': 'physical'}),
            b: _reply({'statement': 'Tessa now has the key.', 'mutable': 'state',
                       'type': 'physical', 'supersedes': key},
                      {'statement': 'x', 'supersedes': 'ghost'})}, force=True)
        prompt_b = dict(calls)[b]
        assert f'- {key} [physical]' in prompt_b
        assert f'- {key} [physical]' not in dict(calls)[a]
        mine = self._mine(project_dir)
        assert len([r for r in mine if r['scene_id'] == a]) == 1  # replaced, not doubled
        assert [r['supersedes'] for r in mine if r['scene_id'] == b] == [key, '']

    def test_a_scene_already_extracted_is_skipped_without_force(
            self, project_dir, monkeypatch):
        _, calls = self._run(project_dir, monkeypatch, {})
        scenes = {sid for sid, _ in calls}
        rows = ledger.load(project_dir)
        rows.append(dict({c: '' for c in ledger.COLUMNS}, id='done-1', type='trait',
                         statement='x', origin='prose', status='binding', mutable='fixed',
                         introduced_by=ledger.COMMITMENTS_PASS, scene_id=sorted(scenes)[0]))
        ledger.save(project_dir, rows)
        _, again = self._run(project_dir, monkeypatch, {})
        assert sorted(scenes)[0] not in {sid for sid, _ in again}

    def test_an_unreadable_reply_stops_the_chain(self, project_dir, monkeypatch):
        from storyforge.cmd_extract import _build_sorted_scene_ids
        ref = os.path.join(project_dir, 'reference')
        first = _build_sorted_scene_ids(os.path.join(project_dir, 'scenes'), ref)[0]
        with pytest.raises(SystemExit):
            self._run(project_dir, monkeypatch, {first: 'garbage'})
        assert self._mine(project_dir) == []

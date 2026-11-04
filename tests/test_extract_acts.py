"""Extraction decides the book's acts once, for the whole book (F-160).

Phase 1 asked each scene for its act on its own, and on every evals book
the act stepped backwards somewhere as seq rose (Quintus 14 times,
Middlemarch 33). The upper tiers copied those acts, so spine events and
architecture anchors landed in the wrong act.
"""

import json
import os

import pytest

from storyforge import api
from storyforge.elaborate import _read_csv, validate_structure
from storyforge.extract_acts import (
    ActsProblems, assign, backward_steps, build_acts_prompt, fit_votes,
    parse_acts, run_acts,
)
from storyforge.scoring_levels import score_architecture, score_scene_map, score_spine

COLUMNS = ['id', 'seq', 'title', 'summary', 'part', 'act', 'pov', 'status', 'word_count']


def _scenes(acts, extra=None):
    return [{'id': f's{i:02d}', 'seq': str(i), 'title': f'Scene {i}', 'summary': '',
             'part': '', 'act': a, 'pov': 'Ann', 'status': 'drafted', 'word_count': '100',
             **(extra or {})}
            for i, a in enumerate(acts, 1)]


def _write(path, rows, columns=COLUMNS):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(columns) + '\n')
        for r in rows:
            f.write('|'.join(r.get(c, '') for c in columns) + '\n')


@pytest.fixture
def book(tmp_path):
    """A 9-scene book whose per-scene acts flip back and forth, as phase 1 left them."""
    ref, scenes, logs = tmp_path / 'reference', tmp_path / 'scenes', tmp_path / 'logs'
    scenes.mkdir()
    logs.mkdir()
    rows = _scenes(['1', '2', '1', '2', '3', '2', '2', '3', '3'])
    _write(str(ref / 'scenes.csv'), rows)
    for r in rows:
        (scenes / f'{r["id"]}.md').write_text(f'The opening of {r["id"]}. ' * 30)
    return tmp_path


def _reply(acts):
    return {'content': [{'type': 'text', 'text': json.dumps({'acts': acts})}],
            'stop_reason': 'end_turn',
            'usage': {'input_tokens': 10, 'output_tokens': 10}}


def _act(first, last='', title='t', reason='r'):
    return {'first_scene': first, 'last_scene': last, 'title': title, 'reason': reason}


def _acts(*starts, n=9):
    """A consistent answer: each act ends right before the next begins."""
    nums = [int(s[1:]) for s in starts] + [n + 1]
    return [_act(s, f's{nums[i + 1] - 1:02d}') for i, s in enumerate(starts)]


class TestBackwardSteps:
    def test_finds_every_step_back(self):
        assert backward_steps(_scenes(['1', '2', '1', '2', '3', '2'])) == [
            ('s02', 's03'), ('s05', 's06')]

    def test_ordered_acts_have_none(self):
        assert backward_steps(_scenes(['1', '1', '2', '3', '3'])) == []

    def test_reads_seq_order_not_file_order(self):
        rows = _scenes(['1', '2', '3'])
        assert backward_steps(list(reversed(rows))) == []

    def test_skips_scenes_with_no_act(self):
        assert backward_steps(_scenes(['1', '', '2', '', '3'])) == []


class TestFitVotes:
    def test_contiguous_and_closest_to_the_votes(self):
        acts = fit_votes(['1', '1', '2', '1', '2', '2', '3', '2', '3', '3'])
        assert acts == sorted(acts)
        agree = sum(1 for v, a in zip(['1', '1', '2', '1', '2', '2', '3', '2', '3', '3'], acts)
                    if v == str(a))
        assert agree == 8     # the most any contiguous split gets (several tie)

    def test_every_act_gets_a_scene(self):
        assert sorted(set(fit_votes(['2'] * 6))) == [1, 2, 3]

    def test_fewer_scenes_than_acts(self):
        assert fit_votes(['3', '1']) == [1, 2]
        assert fit_votes([]) == []


class TestParseActs:
    rows = _scenes(['1'] * 6)

    def test_reads_the_first_scenes(self):
        reply = json.dumps({'acts': _acts('s01', 's03', 's05', n=6)})
        assert parse_acts(reply, self.rows) == ['s01', 's03', 's05']

    @pytest.mark.parametrize('acts, problem', [
        ([('s01', 's03'), ('s04', 's06')], 'expected exactly 3'),
        ([('s01', 's03'), ('s04', 's04'), ('nope', 's06')], 'not in the list'),
        ([('s02', 's03'), ('s04', 's04'), ('s05', 's06')], 'must begin with the first scene'),
        ([('s01', 's03'), ('s04', 's04'), ('s05', 's05')], 'must end with the last scene'),
        ([('s01', 's04'), ('s05', 's03'), ('s04', 's06')], 'ends .* before it begins'),
        ([('s01', 's04'), ('s04', 's04'), ('s05', 's06')], 'right after the previous act ends'),
    ])
    def test_unusable_answers_are_named(self, acts, problem):
        reply = json.dumps({'acts': [_act(f, l) for f, l in acts]})
        with pytest.raises(ActsProblems, match=problem):
            parse_acts(reply, self.rows)

    def test_a_gap_between_acts_is_sent_back(self):
        # Five Weeks (2026-11-03): act 2's reason was the launch, but its
        # first_scene was 75 scenes later; act 1 named the launch as its end
        reply = json.dumps({'acts': [_act('s01', 's02'), _act('s05', 's05'),
                                     _act('s06', 's06')]})
        with pytest.raises(ActsProblems, match=r'act 1 ends at s02 \(seq 2\) but act 2 '
                                               r'begins at s05 \(seq 5\)'):
            parse_acts(reply, self.rows)

    def test_assign_fills_runs(self):
        assert assign(self.rows, ['s01', 's03', 's05']) == [1, 1, 2, 2, 3, 3]


class TestPrompt:
    def test_lists_every_scene_in_order_with_summary_or_opening(self, book):
        rows = _read_csv(str(book / 'reference' / 'scenes.csv'))
        rows[1]['summary'] = 'Ann finds the letter.'
        prompt = build_acts_prompt({'central_conflict': 'Ann vs the town'}, rows,
                                   str(book / 'scenes'))
        assert prompt.index('1. s01') < prompt.index('2. s02') < prompt.index('9. s09')
        assert 'Ann finds the letter.' in prompt
        assert 'opens: The opening of s01.' in prompt
        assert 'Ann vs the town' in prompt
        assert 'exactly 3' in prompt

    def test_retry_carries_the_problems(self, book):
        rows = _read_csv(str(book / 'reference' / 'scenes.csv'))
        prompt = build_acts_prompt({}, rows, str(book / 'scenes'), ['acts has 2 entries'])
        assert 'acts has 2 entries' in prompt


class TestRunActs:
    def _run(self, book, monkeypatch, replies):
        calls = []

        def fake(prompt, model, log_file, max_tokens=4096, **kw):
            calls.append(prompt)
            reply = replies[len(calls) - 1]
            if isinstance(reply, Exception):
                raise reply
            with open(log_file, 'w') as f:
                json.dump(reply, f)
            return reply
        monkeypatch.setattr(api, 'invoke_to_file', fake)
        usage = []
        result = run_acts(str(book / 'reference'), str(book / 'scenes'), str(book / 'logs'),
                          {}, 'claude-sonnet-5-5',
                          on_usage=lambda f, op, t, m: usage.append(op))
        return result, calls, usage

    def test_writes_contiguous_acts_from_the_answer(self, book, monkeypatch):
        result, calls, usage = self._run(
            book, monkeypatch, [_reply(_acts('s01', 's04', 's08'))])
        rows = _read_csv(str(book / 'reference' / 'scenes.csv'))
        assert [r['act'] for r in rows] == ['1', '1', '1', '2', '2', '2', '2', '3', '3']
        assert backward_steps(rows) == []
        assert result.source == 'model' and result.starts == ['s01', 's04', 's08']
        assert len(calls) == 1 and usage == ['extract-acts']

    def test_keeps_every_other_column_and_the_column_order(self, book, monkeypatch):
        before = _read_csv(str(book / 'reference' / 'scenes.csv'))
        self._run(book, monkeypatch, [_reply(_acts('s01', 's04', 's08'))])
        with open(book / 'reference' / 'scenes.csv') as f:
            assert f.readline().strip() == '|'.join(COLUMNS)
        after = _read_csv(str(book / 'reference' / 'scenes.csv'))
        for b, a in zip(before, after):
            assert {k: v for k, v in b.items() if k != 'act'} == \
                {k: v for k, v in a.items() if k != 'act'}

    def test_asks_once_more_with_the_problems(self, book, monkeypatch):
        result, calls, _ = self._run(book, monkeypatch, [
            _reply(_acts('s01', 's04')),
            _reply(_acts('s01', 's04', 's08'))])
        assert len(calls) == 2 and 'expected exactly 3' in calls[1]
        assert result.source == 'model'

    def test_falls_back_to_the_closest_contiguous_split(self, book, monkeypatch):
        result, _, _ = self._run(book, monkeypatch, [RuntimeError('HTTP 529')])
        rows = _read_csv(str(book / 'reference' / 'scenes.csv'))
        assert result.source == 'votes' and 'HTTP 529' in result.note
        assert backward_steps(rows) == []
        assert {r['act'] for r in rows} == {'1', '2', '3'}

    def test_a_second_unusable_answer_falls_back(self, book, monkeypatch):
        bad = _reply(_acts('s01', 's04'))
        result, calls, _ = self._run(book, monkeypatch, [bad, bad])
        assert len(calls) == 2 and result.source == 'votes'
        assert backward_steps(_read_csv(str(book / 'reference' / 'scenes.csv'))) == []

    def test_a_cut_off_reply_falls_back(self, book, monkeypatch):
        cut = dict(_reply(_acts('s01', 's04', 's08')), stop_reason='max_tokens')
        result, _, _ = self._run(book, monkeypatch, [cut])
        assert result.source == 'votes'


class TestReviewEdges:
    def _fake(self, monkeypatch, reply):
        def fake(prompt, model, log_file, max_tokens=4096, **kw):
            if isinstance(reply, Exception):
                raise reply
            fake.prompt = prompt
            with open(log_file, 'w') as f:
                json.dump(reply, f)
            return reply
        monkeypatch.setattr(api, 'invoke_to_file', fake)
        return fake

    def test_no_votes_and_a_failed_call_leaves_the_acts_alone(self, book, monkeypatch):
        path = str(book / 'reference' / 'scenes.csv')
        _write(path, _scenes([''] * 9))
        before = open(path).read()
        self._fake(monkeypatch, RuntimeError('HTTP 500'))
        result = run_acts(str(book / 'reference'), str(book / 'scenes'), str(book / 'logs'),
                          {}, 'm')
        assert result.source == 'none' and open(path).read() == before

    def test_a_programming_error_is_not_swallowed(self, book, monkeypatch):
        self._fake(monkeypatch, KeyError('bug'))
        with pytest.raises(KeyError):
            run_acts(str(book / 'reference'), str(book / 'scenes'), str(book / 'logs'), {}, 'm')

    def test_cut_and_merged_scenes_are_left_out(self, book, monkeypatch):
        path = str(book / 'reference' / 'scenes.csv')
        rows = _scenes(['1', '1', '2', '2', '3', '3', '3'])
        rows[0]['status'] = 'cut'
        rows[3]['status'] = 'merged'
        _write(path, rows)
        fake = self._fake(monkeypatch, _reply([_act('s02', 's02'), _act('s03', 's03'), _act('s05', 's07')]))
        result = run_acts(str(book / 'reference'), str(book / 'scenes'), str(book / 'logs'),
                          {}, 'm')
        assert result.source == 'model'
        assert '1. s01' not in fake.prompt and 's04' not in fake.prompt
        acts = {r['id']: r['act'] for r in _read_csv(path)}
        assert acts['s01'] == '1' and acts['s04'] == '2'     # untouched
        assert [acts[s] for s in ('s02', 's03', 's05', 's06', 's07')] == ['1', '2', '3', '3', '3']

    def test_a_scene_with_no_seq_sorts_last(self):
        rows = _scenes(['1', '2', '3'])
        rows[0]['seq'] = ''
        assert backward_steps(rows) == [('s03', 's01')]


class TestChecksReportActsOutOfOrder:
    def _project(self, tmp_path, acts):
        ref = tmp_path / 'reference'
        _write(str(ref / 'scenes.csv'), _scenes(acts, {'status': 'mapped'}))
        _write(str(ref / 'spine.csv'),
               [{'id': f'e{i}', 'seq': str(i), 'title': 't', 'summary': 's', 'function': 'f',
                 'act': a} for i, a in enumerate(['1', '2', '1', '3'], 1)],
               ['id', 'seq', 'title', 'summary', 'function', 'act'])
        return tmp_path

    def _check(self, result):
        return next(c for c in result['checks'] if c['check'].startswith('acts run in order'))

    def test_floor_checks_fail_on_a_step_back(self, tmp_path):
        p = self._project(tmp_path, ['1', '2', '1', '3'])
        assert not self._check(score_scene_map(str(p)))['passed']
        spine = self._check(score_spine(str(p)))
        assert not spine['passed'] and 'e2 -> e3' in spine['detail']

    def test_floor_checks_pass_in_order(self, tmp_path):
        p = self._project(tmp_path, ['1', '1', '2', '3'])
        assert self._check(score_scene_map(str(p)))['passed']

    def test_architecture_floor_check(self, tmp_path):
        p = self._project(tmp_path, ['1'])
        _write(str(p / 'reference' / 'architecture.csv'),
               [{'id': 'a', 'seq': '1', 'act': '2'}, {'id': 'b', 'seq': '5', 'act': '1'}],
               ['id', 'seq', 'act'])
        assert not self._check(score_architecture(str(p)))['passed']

    def test_validate_reports_it_as_advisory(self, tmp_path):
        p = self._project(tmp_path, ['1', '2', '1', '3'])
        result = validate_structure(str(p / 'reference'))
        check = next(c for c in result['checks'] if c['check'] == 'acts-in-order')
        assert not check['passed'] and check['severity'] == 'advisory'
        assert 'extract --acts' in check['message']


class TestExtractActsCommand:
    def test_extract_acts_redraws_the_acts_and_commits_them(self, book, monkeypatch):
        from storyforge import cmd_extract, ledger
        (book / 'working' / 'logs').mkdir(parents=True)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test')
        monkeypatch.setattr(cmd_extract, 'detect_project_root', lambda: str(book))
        monkeypatch.setattr(ledger, 'exit_if_not_migrated', lambda d: None)
        for name in ('create_branch', 'ensure_branch_pushed', 'create_draft_pr',
                     'print_summary', 'build_shared_context'):
            monkeypatch.setattr(cmd_extract, name, lambda *a, **k: None)
        commits = []
        monkeypatch.setattr(cmd_extract, 'commit_and_push',
                            lambda d, msg, paths: commits.append((msg, paths)))

        def fake(prompt, model, log_file, max_tokens=4096, **kw):
            reply = _reply(_acts('s01', 's04', 's08'))
            with open(log_file, 'w') as f:
                json.dump(reply, f)
            return reply
        monkeypatch.setattr(api, 'invoke_to_file', fake)
        monkeypatch.setattr(cmd_extract, '_log_api_usage', lambda *a: None)
        monkeypatch.setattr(cmd_extract, '_run_phase_0',
                            lambda *a, **k: pytest.fail('--acts ran phase 0'))

        cmd_extract.main(['--acts'])

        rows = _read_csv(str(book / 'reference' / 'scenes.csv'))
        assert [r['act'] for r in rows] == ['1', '1', '1', '2', '2', '2', '2', '3', '3']
        assert commits == [('Extract: acts (scenes.csv)', ['reference/scenes.csv', 'working/'])]


class TestSpineEventSpansActs:
    """A spine event's anchors in two acts (Eighty Days, 2026-11-03:
    fix-names-fogg-robber is act 1 in the spine, its row 14 anchor act 2)."""

    def _check(self, tmp_path, rows):
        _write(str(tmp_path / 'reference' / 'architecture.csv'), rows,
               ['id', 'seq', 'act', 'spine_event'])
        result = score_architecture(str(tmp_path))
        return next(c for c in result['checks'] if c['check'].startswith('each spine event'))

    def test_an_event_across_an_act_break_is_reported(self, tmp_path):
        check = self._check(tmp_path, [
            {'id': 'a', 'seq': '1', 'act': '1', 'spine_event': 'wager'},
            {'id': 'b', 'seq': '5', 'act': '1', 'spine_event': 'fix'},
            {'id': 'c', 'seq': '14', 'act': '2', 'spine_event': 'fix'}])
        assert not check['passed'] and check['severity'] == 'low'
        assert 'fix (acts 1, 2)' in check['detail']

    def test_events_within_one_act_pass(self, tmp_path):
        check = self._check(tmp_path, [
            {'id': 'a', 'seq': '1', 'act': '1', 'spine_event': 'wager'},
            {'id': 'b', 'seq': '5', 'act': '2', 'spine_event': 'fix'},
            {'id': 'c', 'seq': '14', 'act': '2', 'spine_event': 'fix'}])
        assert check['passed']

"""The gate set (#677): building it from E8's recorded judge calls, its roles,
validation and scoring, and the suite's plumbing, on small synthetic data
written here (the real set is private prose and never enters this repo).
The gate itself is stubbed at `runner.gate_one`; what it does is measured by
the gate's own tests."""

import gzip
import json
import os
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import blocking_set  # noqa: E402
import gate_set  # noqa: E402
import harness  # noqa: E402
from gate_set import build, runner  # noqa: E402

SUITES_DIR = PLUGIN_DIR / 'evals' / 'suites'

# An invented case and its replays
CASE = {'id': 'tale-001', 'repo': 'tale', 'code': 'TIM', 'level': 'prose',
        'subsets': ['tool-introduced'], 'summary': 'the voyage takes three days',
        'introduced_by': {'pass': 'redraft from brief', 'commit': 'abc1234'},
        'established': [{'scene': 'harbour', 'path': 'scenes/harbour.md',
                         'quote': 'three days to the island'}],
        'contradicted': [{'scene': 'island', 'path': 'scenes/island.md',
                          'quote': 'after a week at sea'}]}
OTHER = {**CASE, 'id': 'tale-002', 'summary': 'Ann is the eldest'}
WRONG = 'They landed after a week at sea. Tom tied the boat to the post.'
WRONG_2 = 'A week at sea had worn them thin. The island was green.'
RIGHT = 'They landed after three days at sea. Tom tied the boat to the post.'
SILENT = 'They landed. Tom tied the boat to the post.'


def _item(prose, verdict, evidence, case='tale-001', **kw):
    return {'id': gate_set.item_id(case, prose), 'case': case,
            'family': 'redraft-from-brief', 'code': 'TIM', 'verdict': verdict,
            'evidence': evidence, 'recording': 'cassettes', 'prose': prose, **kw}


def _items():
    items = [_item(WRONG, 'reintroduced', 'They landed after a week at sea.'),
             _item(WRONG_2, 'reintroduced', 'A week at sea had worn them thin.'),
             _item(RIGHT, 'consistent', 'They landed after three days at sea.'),
             _item(SILENT, 'not_present', '')]
    gate_set.assign_roles(items)
    return items


def _record(d, name, prompt, reply):
    os.makedirs(d, exist_ok=True)
    with gzip.open(os.path.join(d, f'{name}.json.gz'), 'wt', encoding='utf-8') as f:
        json.dump({'request': {'body': {'messages': [{'role': 'user', 'content': prompt}]}},
                   'response': {'content': [{'type': 'text', 'text': reply}]}}, f)


class TestBuild:
    def test_reads_each_judged_replay_and_its_case_from_the_prompt(self, tmp_path):
        from e8 import judge_prompt
        d = str(tmp_path / 'e8')
        _record(d, 'a', judge_prompt(CASE, WRONG),
                '{"verdict": "reintroduced", "evidence": "They landed after a week at sea."}')
        _record(d, 'b', judge_prompt(OTHER, RIGHT), '{"verdict": "consistent", "evidence": "x"}')
        _record(d, 'c', 'Extract every commitment the scene makes', '{}')
        _record(d, 'd', 'You are checking what a novel-writing tool wrote into a book', '{}')
        items, skipped = build.read_recordings({'cassettes': d}, [CASE, OTHER])
        assert [(i['case'], i['prose'], i['verdict']) for i in items] == sorted(
            [('tale-001', WRONG, 'reintroduced'), ('tale-002', RIGHT, 'consistent')])
        assert skipped['other calls'] == 1 and skipped['data-family judge calls'] == 1
        assert skipped['unmatched'] == [] and skipped['unparsed verdict'] == []

    def test_the_same_prose_in_two_recordings_is_one_item(self, tmp_path):
        from e8 import judge_prompt
        for run in ('r1', 'r2'):
            _record(str(tmp_path / run), 'a', judge_prompt(CASE, WRONG),
                    '{"verdict": "reintroduced", "evidence": "a week at sea"}')
        items, skipped = build.read_recordings(
            {'cassettes': str(tmp_path / 'r1'), 'run2': str(tmp_path / 'r2')}, [CASE])
        assert len(items) == 1 and skipped['duplicates'] == 1

    def test_a_judge_call_no_case_frames_is_named_and_nothing_is_written(self, tmp_path,
                                                                       monkeypatch, capsys):
        from e8 import judge_prompt
        d = str(tmp_path / 'e8')
        _record(d, 'a', judge_prompt({**CASE, 'summary': 'renamed since'}, WRONG),
                '{"verdict": "reintroduced", "evidence": "a week at sea"}')
        monkeypatch.setattr(build, 'RECORDINGS', {'cassettes': d})
        monkeypatch.setattr('e1.load_cases', lambda: [CASE])
        out = tmp_path / 'set'
        assert build.main(['--out', str(out)]) == 1
        assert 'unmatched' in capsys.readouterr().err
        assert not out.exists()

    def test_an_unparsable_verdict_is_named_never_guessed(self, tmp_path):
        from e8 import judge_prompt
        d = str(tmp_path / 'e8')
        _record(d, 'a', judge_prompt(CASE, WRONG), 'I think it is fine')
        items, skipped = build.read_recordings({'cassettes': d}, [CASE])
        assert items == [] and len(skipped['unparsed verdict']) == 1


class TestRoles:
    def test_positives_controls_and_spares(self):
        roles = {i['prose']: i['role'] for i in _items()}
        assert roles == {WRONG: 'positive', WRONG_2: 'positive', RIGHT: 'control',
                         SILENT: 'spare'}

    def test_one_control_per_positive_of_the_same_case(self):
        items = [_item(WRONG, 'reintroduced', 'a week at sea'),
                 _item(RIGHT, 'consistent', 'three days at sea'),
                 _item(RIGHT + ' Again.', 'consistent', 'three days at sea'),
                 _item(RIGHT, 'consistent', 'three days at sea', case='tale-002')]
        gate_set.assign_roles(items)
        assert items[0]['role'] == 'positive'
        # one of tale-001's two consistent replays (the first by id), none of tale-002's
        first = min(items[1:3], key=lambda i: i['id'])
        assert [i['role'] for i in items[1:3]] == [
            'control' if i is first else 'spare' for i in items[1:3]]
        assert items[3]['role'] == 'spare'

    def test_evidence_not_in_the_prose_is_no_positive(self):
        items = [_item(WRONG, 'reintroduced', 'they sailed for a month')]
        gate_set.assign_roles(items)
        assert items[0]['role'] == 'spare'

    def test_a_case_e8_excludes_is_all_spare(self, monkeypatch):
        """#614's audit: its pre-pass book already has the error, so the gate
        is right to pass it, and e8.prepare refuses it."""
        import e8
        monkeypatch.setitem(e8.EXCLUDED_CASES, 'tale-001', 'already in the book')
        assert {i['role'] for i in _items()} == {'spare'}


class TestValidate:
    def test_a_sound_set_has_no_problems(self):
        assert gate_set.validate(_items()) == []

    def test_changed_prose_is_named_by_id_never_quoted(self):
        items = _items()
        items[0]['prose'] = 'Something else entirely.'
        problems = gate_set.validate(items)
        assert f'{items[0]["id"]}: its prose is not the prose it was built from' in problems
        assert not any('Something else' in p for p in problems)

    @pytest.mark.parametrize('field,value,expected', [
        ('role', 'maybe', 'role must be one of'),
        ('verdict', 'unsure', 'verdict must be one of'),
        ('family', 'hone-physical-states', 'family must be one of'),
        ('evidence', 'not in the prose', 'its evidence is not in its prose'),
        ('prose', '', 'no prose'),
    ])
    def test_malformed_item(self, field, value, expected):
        items = _items()
        items[0][field] = value
        problems = gate_set.validate(items)
        assert any(expected in p for p in problems), problems

    def test_a_positive_must_be_reintroduced(self):
        items = _items()
        control = next(i for i in items if i['role'] == 'control')
        control['role'] = 'positive'
        assert f'{control["id"]}: a positive must be reintroduced' in gate_set.validate(items)


def _result(*, blocking=(), inherited=(), passed=None):
    """A real `GateResult` with verified findings at `blocking` (scene quotes)
    and `inherited` ones at `inherited`."""
    from storyforge.checker import CheckResult, Finding
    from storyforge.gate import GateResult

    def finding(q):
        return Finding('contradiction', 'TIM', q, 'harbour', 'three days to the island',
                       'C-1', 'the voyage')
    inh = [finding(q) for q in inherited]
    result = GateResult('island', check=CheckResult('island', findings=[finding(q) for q in blocking]
                                                    + inh))
    result.inherited = inh
    if passed is False and not blocking:
        result.halts = ['stand-in halt']
    return result


class TestScore:
    def test_caught_is_a_blocking_finding_on_the_evidence(self):
        items = _items()
        pos = [i for i in items if i['role'] == 'positive']
        ctl = next(i for i in items if i['role'] == 'control')
        outcomes = {pos[0]['id']: gate_set.outcome(pos[0], _result(blocking=['after a week at sea'])),
                    # stopped, but by a finding elsewhere: not caught
                    pos[1]['id']: gate_set.outcome(pos[1], _result(blocking=['The island was green'])),
                    ctl['id']: gate_set.outcome(ctl, _result())}
        metrics, by_code = gate_set.score(items, outcomes)
        assert metrics['caught'] == 1 and metrics['recall'] == 0.5
        assert metrics['stopped_positive'] == 2 and metrics['stop_rate_positive'] == 1.0
        assert metrics['cases'] == 1 and metrics['cases_caught'] == 1
        assert metrics['recall_per_case'] == 0.5
        assert metrics['false_alarm_on_fact'] == 0 and metrics['stopped_control'] == 0
        assert by_code == {'TIM': {'positives': 2, 'caught': 1, 'recall': 0.5}}

    def test_a_finding_on_a_controls_correct_statement_is_a_false_alarm_on_the_fact(self):
        items = _items()
        outcomes = {i['id']: gate_set.outcome(i, _result()) for i in items
                    if i['role'] != 'spare'}
        ctl = next(i for i in items if i['role'] == 'control')
        outcomes[ctl['id']] = gate_set.outcome(ctl, _result(blocking=['three days at sea']))
        metrics, _ = gate_set.score(items, outcomes)
        assert metrics['false_alarm_on_fact'] == 1 and metrics['stop_rate_control'] == 1.0

    def test_an_inherited_finding_on_the_evidence_is_seen_but_not_caught(self):
        item = _items()[0]
        out = gate_set.outcome(item, _result(inherited=['after a week at sea']))
        assert out['inherited_on'] and not out['caught'] and not out['stopped']

    def test_a_gate_that_could_not_finish_stops_and_catches_nothing(self):
        out = gate_set.outcome(_items()[0], None)
        assert out == {'id': out['id'], 'finished': False, 'stopped': True, 'caught': False,
                       'inherited_on': False, 'findings': 0}

    def test_an_item_with_no_outcome_raises_never_reads_as_passed(self):
        items = _items()
        with pytest.raises(ValueError, match='no outcome'):
            gate_set.score(items, {})


def _write_set(root, items, recorded=('gate-set', 'gate-set-questions')):
    """The set, with a stand-in recording for each suite in `recorded` (the
    gate is stubbed, so nothing replays it; it marks the suite recorded)."""
    path = root / gate_set.SET_NAME
    (path / 'prose').mkdir(parents=True)
    for name in recorded:
        _record(str(path / 'cassettes' / name), 'stand-in', 'unused', '{}')
    for i in items:
        (path / 'prose' / f'{i["id"]}.md').write_text(i['prose'])
    (path / 'cases.json').write_text(json.dumps(
        {'items': [{k: v for k, v in i.items() if k != 'prose'} for i in items]}))
    return path


def _suite(name='gate-set'):
    return next(s for s in harness.discover(str(SUITES_DIR)) if s.name == name)


class TestSuite:
    @pytest.mark.parametrize('name,method', [('gate-set', 'open'),
                                             ('gate-set-questions', 'questions')])
    def test_gates_each_run_item_with_its_method_then_restores_it(self, tmp_path, monkeypatch,
                                                                 name, method):
        from storyforge import gate
        items = _items()
        path = _write_set(tmp_path, items)
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path))
        seen = []

        def fake_gate(item, work_dir):
            seen.append((item['role'], gate.GATE_CHECK_METHOD))
            return _result(blocking=['after a week at sea'] if item['prose'] == WRONG else [])
        monkeypatch.setattr(runner, 'gate_one', fake_gate)
        before = gate.GATE_CHECK_METHOD
        result = harness.run_suite(_suite(name), 'replay', str(tmp_path / 'c'))
        assert gate.GATE_CHECK_METHOD == before
        assert sorted(seen) == [('control', method), ('positive', method), ('positive', method)]
        assert result['metrics']['recall'] == 0.5
        # no floor recorded yet: every floor gate fails until the baseline
        assert result['status'] == 'fail'
        assert any('no floor recorded' in n for n in result['notes'])
        outcomes = json.loads((path / 'results' / runner.OUTCOMES[method]).read_text())
        assert len(outcomes['items']) == 3
        # notes carry ids, never the prose
        assert not any(WRONG in n or 'a week at sea' in n for n in result['notes'])

    def test_the_gate_raising_errors_the_suite_naming_ids_not_prose(self, tmp_path, monkeypatch):
        _write_set(tmp_path, _items())
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path))

        def boom(item, work_dir):
            raise RuntimeError(f'reply quoted {item["prose"]}')
        monkeypatch.setattr(runner, 'gate_one', boom)
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'error'
        assert 'the gate raised on 3 item(s)' in result['error']
        assert WRONG not in result['error']

    def test_not_recorded_yet_is_unavailable_never_an_error(self, tmp_path, monkeypatch):
        """Left unrecorded on purpose until a decision needs it (#677): a
        replay says so and how to record it, and never fails a full run or
        refuses --baseline as the harness's no-recordings error would."""
        _write_set(tmp_path, _items(), recorded=())
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path))
        monkeypatch.setattr(runner, 'gate_one', lambda *a: pytest.fail('gated'))
        for mode in ('replay', 'auto', 'record'):   # frozen: all three replay
            result = harness.run_suite(_suite(), mode, str(tmp_path / 'c'))
            assert result['status'] == 'stale' and result['unavailable'] is True, result
            assert 'not recorded yet' in result['stale']
            assert '--mode record --suite gate-set --runs 3' in result['stale']

    def test_no_private_set_is_unavailable_naming_where_it_goes(self, tmp_path, monkeypatch):
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path / 'nowhere'))
        result = harness.run_suite(_suite(), 'replay', str(tmp_path / 'c'))
        assert result['status'] == 'stale' and result['unavailable'] is True
        assert 'storyforge-evals' in result['stale'] and 'build.py' in result['stale']

    def test_records_beside_the_set_never_in_this_repo(self, tmp_path, monkeypatch):
        _write_set(tmp_path, _items())
        monkeypatch.setenv(blocking_set.PRIVATE_ENV, str(tmp_path))
        for name in ('gate-set', 'gate-set-questions'):
            assert _suite(name).cassettes('run2') == os.path.join(
                str(tmp_path), gate_set.SET_NAME, 'cassettes', 'run2', name)
            assert not (PLUGIN_DIR / 'evals' / 'fixtures' / 'cassettes' / name).exists()

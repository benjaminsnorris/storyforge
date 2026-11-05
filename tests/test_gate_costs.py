"""F-151: the gate's model calls go to the cost ledger, and `write`'s
forecast and summary count them.

Drafting Quintus Book VIII forecast $0.45 and logged $1.71 of `draft` rows;
the gate's extraction, persistence check, both check readings and fixes
cost $6.69 more, and none of it was in `working/costs/ledger.csv`."""

import json
import os
from unittest.mock import patch

from storyforge import api, gate
from storyforge.costs import print_summary

from test_gate import SCENE, _commitment, _gate, _pure_prose_scenes, _text  # noqa: F401 (autouse)


def _ledger_rows(project_dir):
    path = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        lines = f.read().splitlines()
    header = lines[0].split('|')
    return [dict(zip(header, line.split('|'))) for line in lines[1:] if line]


class TestMeter:
    def test_records_every_send_and_converse_reply_while_open(self):
        reply = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'x'}],
                 'usage': {'input_tokens': 10, 'output_tokens': 3,
                           'cache_read_input_tokens': 5}}
        with patch('storyforge.api._api_request', return_value=reply):
            api.invoke('p', 'claude-opus-5-5')          # before: not recorded
            with api.metered() as outer:
                api.invoke('p', 'claude-opus-5-5')
                with api.metered() as inner:
                    api.converse('p', 'claude-sonnet-5-5', [], {})
            api.invoke('p', 'claude-opus-5-5')          # after: not recorded
        assert [m for m, _ in outer.replies] == ['claude-opus-5-5', 'claude-sonnet-5-5']
        assert [m for m, _ in inner.replies] == ['claude-sonnet-5-5']
        assert outer.by_model()['claude-opus-5-5'] == {
            'input_tokens': 10, 'output_tokens': 3, 'cache_read': 5, 'cache_create': 0}

    def test_log_writes_one_row_per_model(self, tmp_path):
        meter = api.SpendMeter()
        meter.replies += [('claude-opus-5-5', api.extract_usage({'usage': {
            'input_tokens': 1000, 'output_tokens': 100}}))] * 2
        meter.replies.append(('claude-sonnet-5-5', api.extract_usage({'usage': {
            'input_tokens': 7, 'output_tokens': 1}})))
        total = meter.log(str(tmp_path), 'gate', 'sc-1')
        rows = _ledger_rows(str(tmp_path))
        assert [(r['operation'], r['target'], r['model'], r['input_tokens'])
                for r in rows] == [('gate', 'sc-1', 'claude-opus-5-5', '2000'),
                                   ('gate', 'sc-1', 'claude-sonnet-5-5', '7')]
        assert total > 0 and abs(total - sum(float(r['cost_usd']) for r in rows)) < 1e-5


class TestGateLogsItsSpend:
    def test_a_gate_run_is_one_ledger_row_counting_every_call(self, project_dir, tmp_path):
        calls = []
        real = api._meter
        with patch('storyforge.api._meter', side_effect=lambda r, m: calls.append(r) or real(r, m)):
            result = _gate(project_dir, tmp_path, commitments=[_commitment()])
        assert result.passed
        rows = [r for r in _ledger_rows(project_dir) if r['operation'] == 'gate']
        assert len(rows) == 1 and rows[0]['target'] == SCENE
        # every reply the gate got (extraction, persistence, the check's
        # readings), 1 token each
        assert len(calls) >= 3 and int(rows[0]['input_tokens']) == len(calls)

    def test_a_gate_run_that_fails_still_logs_what_it_spent(self, project_dir, tmp_path):
        def fake(path, body, **k):
            if 'tools' in body:
                raise RuntimeError('API down')
            return _text({'commitments': [_commitment()]})
        from test_gate import _with_persistence
        with patch('storyforge.api._api_request', side_effect=_with_persistence(fake)):
            try:
                gate.gate_scene(project_dir, SCENE, command='draft',
                                log_dir=str(tmp_path / 'logs'), extract_model='m',
                                check_model='m')
            except (gate.GateError, RuntimeError):
                pass
        rows = [r for r in _ledger_rows(project_dir) if r['operation'] == 'gate']
        assert len(rows) == 1 and rows[0]['input_tokens'] == '2'

    def test_a_fix_is_logged_as_gate_fix(self, project_dir, tmp_path, monkeypatch):
        fail = gate.GateResult(SCENE)
        monkeypatch.setattr(gate, 'problems_to_fix', lambda r: ['x'] if r is fail else [])
        passed = gate.GateResult(SCENE)
        monkeypatch.setattr(gate.GateResult, 'passed', property(lambda r: r is passed))
        runs = iter([fail, passed])
        monkeypatch.setattr(gate, 'gate_scene', lambda *a, **k: next(runs))
        monkeypatch.setattr(gate, '_brief_phrases', lambda *a: [])
        reply = _text({'edits': [{'find': 'a', 'replace': 'b'}]})
        reply['usage'] = {'input_tokens': 40, 'output_tokens': 4}
        with patch('storyforge.api._api_request', return_value=reply):
            gate.gate_and_fix(project_dir, SCENE, command='draft', prose='a scene',
                              log_dir=str(tmp_path / 'logs'), fix_model='claude-opus-5-5')
        rows = [r for r in _ledger_rows(project_dir) if r['operation'] == 'gate-fix']
        assert [(r['target'], r['input_tokens']) for r in rows] == [(SCENE, '40')]


class TestWriteCountsTheGate:
    def test_summary_takes_several_operations(self, tmp_path, capsys):
        from storyforge.costs import log_operation
        for op, cost in (('draft', 1.0), ('gate', 3.0), ('gate-fix', 0.5), ('revise', 9.0)):
            log_operation(str(tmp_path), op, 'claude-opus-5-5', 1, 1, cost)
        print_summary(str(tmp_path), ('draft', 'gate', 'gate-fix'))
        out = capsys.readouterr().out
        assert '4.5' in out and '13.5' not in out
        assert 'draft, gate, gate-fix' in out

    def test_forecast_includes_the_gate(self, project_dir, monkeypatch, capsys):
        from storyforge import cmd_write
        logged = []
        monkeypatch.setattr(cmd_write, 'log', lambda m: logged.append(m))
        monkeypatch.setattr(cmd_write, 'check_threshold', lambda c: False)  # stop there
        monkeypatch.setattr(cmd_write, '_exit_if_gate_pending', lambda *a, **k: None)
        monkeypatch.setattr(cmd_write, 'detect_project_root', lambda: project_dir)
        try:
            cmd_write.main(['--force', '--coaching', 'full', '--scenes', SCENE])
        except SystemExit:
            pass
        forecast = [m for m in logged if m.startswith('Cost forecast')]
        assert forecast, logged
        assert 'of it the gate' in forecast[0]
        gate_part = float(forecast[0].split('~$')[2].split(' ')[0])
        assert gate_part == round(gate.WRITE_GATE_COST_PER_SCENE, 2)


class TestSpendLoggingEdges:
    def test_a_failed_fix_still_logs_its_spend(self, project_dir, tmp_path, monkeypatch):
        fail = gate.GateResult(SCENE)
        monkeypatch.setattr(gate, 'problems_to_fix', lambda r: ['x'])
        monkeypatch.setattr(gate.GateResult, 'passed', property(lambda r: False))
        monkeypatch.setattr(gate, 'gate_scene', lambda *a, **k: fail)
        monkeypatch.setattr(gate, '_brief_phrases', lambda *a: [])
        reply = _text({'not': 'the schema'})
        reply['usage'] = {'input_tokens': 9, 'output_tokens': 1}
        with patch('storyforge.api._api_request', return_value=reply):
            try:
                gate.gate_and_fix(project_dir, SCENE, command='draft', prose='a scene',
                                  log_dir=str(tmp_path / 'logs'), fix_model='claude-opus-5-5')
            except gate.GateError:
                pass
        rows = [r for r in _ledger_rows(project_dir) if r['operation'] == 'gate-fix']
        assert [r['input_tokens'] for r in rows] == ['9']

    def test_a_failed_ledger_write_never_hides_the_gate_error(self, project_dir, tmp_path,
                                                              monkeypatch):
        def broken(self, *a, **k):
            raise OSError('disk full')
        monkeypatch.setattr(api.SpendMeter, 'log', broken)
        monkeypatch.setattr(gate, '_gate_scene',
                            lambda *a, **k: (_ for _ in ()).throw(gate.GateError('the real one')))
        try:
            gate.gate_scene(project_dir, SCENE, command='draft', log_dir=str(tmp_path))
        except gate.GateError as e:
            assert 'the real one' in str(e)
        else:
            raise AssertionError('no GateError')

    def test_an_empty_filter_shows_every_operation(self, tmp_path, capsys):
        from storyforge.costs import log_operation
        log_operation(str(tmp_path), 'draft', 'claude-opus-5-5', 1, 1, 2.0)
        print_summary(str(tmp_path), '')
        assert 'all operations' in capsys.readouterr().out

    def test_revise_counts_the_gate(self):
        import inspect
        from storyforge import cmd_revise
        src = inspect.getsource(cmd_revise)
        assert "print_summary(project_dir, ('revise', 'gate', 'gate-fix')" in src
        assert 'for the gate on each' in src

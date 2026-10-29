import json
import os
import sys
import textwrap

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402
import run as eval_run  # noqa: E402

PASSING = '''
    from harness import Gate, Suite, SuiteOutput

    def run(ctx):
        return SuiteOutput(metrics={'recall': 0.95},
                           by_code={'PHY': {'recall': 0.9}},
                           gates=[Gate('recall', 0.95, '>=', 0.9)])

    SUITE = Suite('{name}', 'a passing suite', run)
'''
FAILING = '''
    from harness import Gate, Suite, SuiteOutput

    def run(ctx):
        return SuiteOutput(metrics={'recall': 0.5}, gates=[Gate('recall', 0.5, '>=', 0.9)])

    SUITE = Suite('{name}', 'a failing suite', run)
'''
ERRORING = '''
    from harness import Suite

    def run(ctx):
        raise ValueError('no fixtures')

    SUITE = Suite('{name}', 'an erroring suite', run)
'''
CALLS_API = '''
    from harness import Gate, Suite, SuiteOutput
    from storyforge import api

    def run(ctx):
        text = api.invoke_api('hi', 'claude-sonnet-4-6', max_tokens=10)
        return SuiteOutput(metrics={'chars': len(text)}, gates=[Gate('chars', len(text), '>=', 0)])

    SUITE = Suite('{name}', 'calls the API', run)
'''


SWALLOWS_MISS = '''
    from harness import Gate, Suite, SuiteOutput
    from storyforge import api

    def run(ctx):
        scored = 0
        try:  # what cmd_score does: an API failure becomes a skipped scene
            api.invoke('hi', 'claude-sonnet-4-6', max_tokens=10)
            scored = 1
        except Exception:
            pass
        return SuiteOutput(metrics={'scored': scored}, gates=[Gate('scored', scored, '>=', 0)])

    SUITE = Suite('{name}', 'swallows API errors', run)
'''
NO_GATES = '''
    from harness import Suite, SuiteOutput

    def run(ctx):
        return SuiteOutput(metrics={'recall': 1.0})

    SUITE = Suite('{name}', 'no gates', run)
'''
EXITS = '''
    import sys
    from harness import Suite

    def run(ctx):
        sys.exit(3)

    SUITE = Suite('{name}', 'calls sys.exit', run)
'''
BAD_LOG = '''
    import os
    from harness import Gate, Suite, SuiteOutput

    def run(ctx):
        with open(os.environ['STORYFORGE_CASSETTE_LOG'], 'a') as f:
            f.write('{"model": "claude-x", "usage": null}\\n{truncated\\n')
        return SuiteOutput(gates=[Gate('g', 1, '>=', 0)])

    SUITE = Suite('{name}', 'writes a bad log line', run)
'''


def _suite(dir_, filename, body, name):
    dir_.mkdir(exist_ok=True)
    (dir_ / filename).write_text(textwrap.dedent(body.replace('{name}', name)))


def _run(tmp_path, *extra):
    return eval_run.main([
        '--suites-dir', str(tmp_path / 'suites'),
        '--cassettes-dir', str(tmp_path / 'cassettes'),
        '--results-file', str(tmp_path / 'results' / 'latest.json'),
        '--baseline-file', str(tmp_path / 'baseline.json'),
        *extra,
    ])


def _report(tmp_path):
    with open(tmp_path / 'results' / 'latest.json') as f:
        return json.load(f)


def test_empty_suite_runs_and_passes(tmp_path, capsys):
    (tmp_path / 'suites').mkdir()
    assert _run(tmp_path) == 0
    report = _report(tmp_path)
    assert report['suite_count'] == 0 and report['status'] == 'pass'
    assert report['schema_version'] == harness.SCHEMA_VERSION
    assert report['storyforge_version']
    assert 'No suites found' in capsys.readouterr().out


def test_the_real_suites_dir_loads():
    harness.discover(eval_run.SUITES_DIR)


def test_status_and_exit_codes(tmp_path):
    _suite(tmp_path / 'suites', 'a.py', PASSING, 'a')
    assert _run(tmp_path) == 0
    _suite(tmp_path / 'suites', 'b.py', FAILING, 'b')
    assert _run(tmp_path) == 1
    _suite(tmp_path / 'suites', 'c.py', ERRORING, 'c')
    assert _run(tmp_path) == 2
    by_name = {r['suite']: r for r in _report(tmp_path)['results']}
    assert [by_name[n]['status'] for n in 'abc'] == ['pass', 'fail', 'error']
    assert by_name['c']['error'] == 'ValueError: no fixtures'
    assert by_name['a']['by_code'] == {'PHY': {'recall': 0.9}}


def test_suite_filter(tmp_path):
    _suite(tmp_path / 'suites', 'a.py', PASSING, 'a')
    _suite(tmp_path / 'suites', 'b.py', FAILING, 'b')
    assert _run(tmp_path, '--suite', 'a') == 0
    assert [r['suite'] for r in _report(tmp_path)['results']] == ['a']
    assert _run(tmp_path, '--suite', 'nope') == 2


def test_baseline_written_and_compared(tmp_path, capsys):
    _suite(tmp_path / 'suites', 'a.py', FAILING, 'a')
    assert _run(tmp_path, '--baseline') == 1
    assert (tmp_path / 'baseline.json').exists()
    _suite(tmp_path / 'suites', 'a.py', PASSING, 'a')
    assert _run(tmp_path) == 0
    comparison = _report(tmp_path)['baseline_comparison']['a']
    assert comparison['recall'] == {'baseline': 0.5, 'current': 0.95, 'delta': 0.45}
    assert comparison['PHY.recall'] == {'baseline': None, 'current': 0.9, 'delta': None}
    assert 'recall: 0.5 -> 0.95 (+0.45)' in capsys.readouterr().out


def test_baseline_refused_over_an_error(tmp_path):
    _suite(tmp_path / 'suites', 'c.py', ERRORING, 'c')
    assert _run(tmp_path, '--baseline') == 2
    assert not (tmp_path / 'baseline.json').exists()


def test_baseline_refused_for_a_subset(tmp_path):
    _suite(tmp_path / 'suites', 'a.py', PASSING, 'a')
    assert _run(tmp_path, '--baseline', '--suite', 'a') == 2
    assert not (tmp_path / 'baseline.json').exists()


def test_api_calls_record_replay_and_cost(tmp_path, monkeypatch):
    from storyforge import api
    calls = []
    monkeypatch.setattr(api, '_live_request', lambda *a: calls.append(a) or {
        'content': [{'type': 'text', 'text': 'hello'}],
        'usage': {'input_tokens': 1_000_000, 'output_tokens': 0}})
    monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
    _suite(tmp_path / 'suites', 'a.py', CALLS_API, 'a')

    assert _run(tmp_path) == 2  # replay with no recording: an error, never a live call
    assert 'CassetteMiss' in _report(tmp_path)['results'][0]['error']
    assert calls == []

    assert _run(tmp_path, '--mode', 'record') == 0
    recorded = _report(tmp_path)['cost']
    assert len(calls) == 1 and recorded['usd_spent'] > 0

    assert _run(tmp_path) == 0
    replayed = _report(tmp_path)['cost']
    assert len(calls) == 1
    assert replayed['usd_spent'] == 0 and replayed['usd_if_live'] == recorded['usd_spent']
    assert 'STORYFORGE_CASSETTE' not in os.environ  # restored after the suite


def test_a_swallowed_replay_miss_still_errors_the_suite(tmp_path, monkeypatch):
    from storyforge import api
    monkeypatch.setattr(api, '_live_request', lambda *a: pytest.fail('went live'))
    _suite(tmp_path / 'suites', 'a.py', SWALLOWS_MISS, 'a')
    assert _run(tmp_path) == 2
    result = _report(tmp_path)['results'][0]
    assert result['status'] == 'error' and 'CassetteMiss' in result['error']
    assert result['metrics'] == {'scored': 0}


def test_a_suite_with_no_gates_is_an_error(tmp_path):
    _suite(tmp_path / 'suites', 'a.py', NO_GATES, 'a')
    assert _run(tmp_path) == 2
    assert 'no gates' in _report(tmp_path)['results'][0]['error']


def test_sys_exit_in_a_suite_is_an_error_and_env_is_restored(tmp_path, monkeypatch):
    monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
    _suite(tmp_path / 'suites', 'a.py', EXITS, 'a')
    _suite(tmp_path / 'suites', 'b.py', PASSING, 'b')
    assert _run(tmp_path) == 2
    by_name = {r['suite']: r['status'] for r in _report(tmp_path)['results']}
    assert by_name == {'a': 'error', 'b': 'pass'}
    assert 'STORYFORGE_CASSETTE' not in os.environ


def test_a_bad_cassette_log_errors_without_leaking_env(tmp_path, monkeypatch):
    monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
    _suite(tmp_path / 'suites', 'a.py', BAD_LOG, 'a')
    assert _run(tmp_path) == 2
    result = _report(tmp_path)['results'][0]
    assert result['cassette_failures'] == ['cassette log line 2 is not JSON']
    assert result['cost']['calls'] == 1 and result['cost']['unpriced_calls'] == 1
    assert 'STORYFORGE_CASSETTE' not in os.environ


def test_a_suite_only_in_the_baseline_is_reported(tmp_path, capsys):
    _suite(tmp_path / 'suites', 'a.py', PASSING, 'a')
    _suite(tmp_path / 'suites', 'b.py', FAILING, 'b')
    _run(tmp_path, '--baseline')
    (tmp_path / 'suites' / 'b.py').unlink()
    _run(tmp_path)
    assert _report(tmp_path)['baseline_comparison']['b']['recall'] == {
        'baseline': 0.5, 'current': None, 'delta': None}
    assert '[MISSING] b' in capsys.readouterr().out


def test_infrastructure_failures_exit_2_not_1(tmp_path, capsys):
    assert _run(tmp_path) == 2  # suites dir missing
    (tmp_path / 'suites').mkdir()
    (tmp_path / 'suites' / 'broken.py').write_text('import nonexistent_module\n')
    assert _run(tmp_path) == 2
    (tmp_path / 'suites' / 'broken.py').unlink()
    (tmp_path / 'baseline.json').write_text('{not json')
    assert _run(tmp_path) == 2
    assert 'ERROR' in capsys.readouterr().err


def test_a_crashed_run_leaves_no_stale_report(tmp_path):
    (tmp_path / 'suites').mkdir()
    assert _run(tmp_path) == 0
    (tmp_path / 'baseline.json').write_text('{not json')
    assert _run(tmp_path) == 2
    assert not (tmp_path / 'results' / 'latest.json').exists()


def test_python_floor(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'version_info', (3, 9, 6))
    assert eval_run.main([]) == 2
    assert 'needs Python 3.10' in capsys.readouterr().err


def test_list(tmp_path, capsys):
    _suite(tmp_path / 'suites', 'a.py', PASSING, 'a')
    assert _run(tmp_path, '--list') == 0
    assert 'a: a passing suite' in capsys.readouterr().out


def test_unknown_error_code_rejected():
    with pytest.raises(ValueError, match='unknown error codes'):
        harness.SuiteOutput(by_code={'XYZ': {}})


def test_unknown_gate_op_rejected():
    with pytest.raises(ValueError):
        harness.Gate('g', 1, '=>', 1)


def test_suite_module_without_suite_is_an_error(tmp_path):
    (tmp_path / 'x.py').write_text('X = 1\n')
    with pytest.raises(RuntimeError, match='no SUITE'):
        harness.discover(str(tmp_path))


def test_a_catalog_call_is_free_and_not_unpriced(tmp_path):
    """Model resolution's GET /v1/models has no model and no usage; it costs
    nothing and must not be counted as an unpriced call."""
    import harness
    log = tmp_path / 'log.jsonl'
    log.write_text('{"key": "k", "model": "", "usage": {}, "replayed": false}\n'
                   '{"key": "k2", "model": "claude-haiku-5-5", '
                   '"usage": {"input_tokens": 1000000, "output_tokens": 0}, "replayed": false}\n')
    totals, failures = harness.read_cassette_log(str(log))
    assert failures == []
    assert totals['calls'] == 2 and totals['unpriced_calls'] == 0
    assert totals['usd_spent'] == 0.5  # over 100K prompt tokens: Haiku 5.5's higher rate

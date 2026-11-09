"""Frozen suites (stale, never recorded by default) and the monthly eval
budget (#645)."""

import json
import os
import sys
import textwrap
from datetime import datetime, timezone

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import e6  # noqa: E402
import harness  # noqa: E402
import run as eval_run  # noqa: E402
from storyforge import api, cassette, eval_spend  # noqa: E402

# Two calls, each $3 live (1M sonnet-4-6 input tokens)
CALLS_API = '''
    from harness import Gate, Suite, SuiteOutput
    from storyforge import api

    def run(ctx):
        text = api.invoke_api('{prompt}', 'claude-sonnet-4-6', max_tokens=10)
        text += api.invoke_api('{prompt} again', 'claude-sonnet-4-6', max_tokens=10)
        return SuiteOutput(metrics={'chars': len(text)}, gates=[Gate('chars', len(text), '>=', 0)])

    SUITE = Suite('{name}', 'calls the API', run, frozen={frozen})
'''
PASSING = '''
    from harness import Gate, Suite, SuiteOutput

    def run(ctx):
        return SuiteOutput(metrics={'recall': 1.0}, gates=[Gate('recall', 1.0, '>=', 0.9)])

    SUITE = Suite('{name}', 'passes', run, frozen={frozen})
'''
FAILING = PASSING.replace("Gate('recall', 1.0, '>=', 0.9)", "Gate('recall', 1.0, '>=', 2)")
RAISES = '''
    from harness import Suite

    def run(ctx):
        raise ValueError('fixture missing')

    SUITE = Suite('{name}', 'raises', run, frozen=True)
'''
# Swallows a miss on its first call (as command code does), then something else
AFTER_MISS = '''
    from harness import Gate, Suite, SuiteOutput
    from storyforge import api, cassette

    def run(ctx):
        try:
            api.invoke_api('{prompt}', 'claude-sonnet-4-6', max_tokens=10)
        except Exception:
            pass  # a skipped scene
        {then}

    SUITE = Suite('{name}', 'swallows a miss', run, frozen=True)
'''
CALL_USD = 3.0


@pytest.fixture
def live(monkeypatch):
    calls = []
    monkeypatch.setattr(api, '_live_request', lambda *a: calls.append(a) or {
        'content': [{'type': 'text', 'text': 'hello'}],
        'usage': {'input_tokens': 1_000_000, 'output_tokens': 0}})
    monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
    monkeypatch.setattr(cassette, '_recorded_here', set())
    return calls


def _suite(tmp_path, name, body=CALLS_API, frozen=False, prompt='hi'):
    d = tmp_path / 'suites'
    d.mkdir(exist_ok=True)
    (d / f'{name.replace("-", "_")}.py').write_text(textwrap.dedent(
        body.replace('{name}', name).replace('{frozen}', str(frozen))
        .replace('{prompt}', prompt)))


def _run(tmp_path, *extra):
    return eval_run.main([
        '--suites-dir', str(tmp_path / 'suites'),
        '--cassettes-dir', str(tmp_path / 'cassettes'),
        '--runs-dir', str(tmp_path / 'e6'),
        '--results-file', str(tmp_path / 'results' / 'latest.json'),
        '--baseline-file', str(tmp_path / 'baseline.json'),
        '--config-file', str(tmp_path / 'config.json'),
        '--spend-log', str(tmp_path / 'spend.jsonl'),
        *extra,
    ])


def _report(tmp_path):
    with open(tmp_path / 'results' / 'latest.json') as f:
        return json.load(f)


def _result(tmp_path, name):
    return next(r for r in _report(tmp_path)['results'] if r['suite'] == name)


def _ledger(tmp_path):
    path = tmp_path / 'spend.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _spent(tmp_path, usd, month=None):
    at = f'{month or eval_spend.current_month()}-01T00:00:00+00:00'
    with open(tmp_path / 'spend.jsonl', 'a') as f:
        f.write(json.dumps({'at': at, 'suite': 'x', 'model': 'm', 'usd': usd}) + '\n')


def _record_frozen(tmp_path, name='e4'):
    """Record a frozen suite's three runs (over budget, as Ben would approve)."""
    assert _run(tmp_path, '--mode', 'record', '--suite', name, '--runs', '3',
                '--over-budget', 'test setup') == 0


def _record_frozen_any(tmp_path, name='e4'):
    """Record a frozen suite's three runs whatever their verdict."""
    assert _run(tmp_path, '--mode', 'record', '--suite', name, '--runs', '3',
                '--over-budget', 'test setup') in (0, 1, 2)


# --- frozen suites -----------------------------------------------------------

def test_the_real_e4_and_e8_are_frozen_and_nothing_else():
    frozen = {s.name for s in harness.discover(eval_run.SUITES_DIR) if s.frozen}
    assert frozen == {'e4-generation', 'e8-revision-safety'}


def test_a_prompt_change_makes_a_frozen_suite_stale_spends_nothing_and_exits_0(
        tmp_path, live, capsys):
    _suite(tmp_path, 'e4', frozen=True)
    _record_frozen(tmp_path)
    recorded = len(live)
    _suite(tmp_path, 'e4', frozen=True, prompt='a changed prompt')
    for mode in ('replay', 'auto', 'record'):
        assert _run(tmp_path, '--mode', mode) == 0, mode
        result = _result(tmp_path, 'e4')
        assert result['status'] == 'stale' and result['error'] is None, mode
        assert 'stale' in result['stale'] and '--runs 3' in result['stale']
        assert result['metrics'] == {} and result['gates'] == []
        assert result['cost']['usd_spent'] == 0
        assert _report(tmp_path)['status'] == 'stale'
    assert len(live) == recorded  # never went live
    assert 'frozen suite: replayed, not run in record mode' in _result(tmp_path, 'e4')['notes'][0]
    out = capsys.readouterr().out
    assert '[STALE] e4' in out and 'stale (frozen, not re-recorded' in out


def test_a_frozen_suite_that_replays_is_measured(tmp_path, live):
    _suite(tmp_path, 'e4', frozen=True)
    _record_frozen(tmp_path)
    assert _run(tmp_path, '--mode', 'auto') == 0
    assert _result(tmp_path, 'e4')['status'] == 'pass'


def test_a_non_frozen_miss_is_still_an_error(tmp_path, live):
    _suite(tmp_path, 'e3')
    assert _run(tmp_path) == 2
    assert _result(tmp_path, 'e3')['status'] == 'error'


def test_a_frozen_suite_that_fails_without_a_miss_is_an_error(tmp_path, live):
    _suite(tmp_path, 'e8', RAISES, frozen=True)
    assert _run(tmp_path) == 2
    assert _result(tmp_path, 'e8')['error'] == 'ValueError: fixture missing'


def test_stale_ranks_below_fail_and_error(tmp_path, live):
    _suite(tmp_path, 'e4', frozen=True)
    _record_frozen(tmp_path)
    _suite(tmp_path, 'e4', frozen=True, prompt='a changed prompt')
    _suite(tmp_path, 'ok', PASSING)
    assert _run(tmp_path) == 0
    assert _report(tmp_path)['status'] == 'stale'
    _suite(tmp_path, 'bad', FAILING)
    assert _run(tmp_path) == 1
    _suite(tmp_path, 'e3')
    assert _run(tmp_path) == 2
    assert harness.overall_status(['pass', 'stale']) == 'stale'
    assert harness.overall_status([]) == 'pass'


def test_a_frozen_suite_is_recorded_only_by_name_and_as_three_runs(tmp_path, live, capsys):
    _suite(tmp_path, 'e4', frozen=True)
    over = ('--over-budget', 'test')
    assert _run(tmp_path, '--mode', 'record', '--suite', 'e4', *over) == 2
    assert 'recorded only as --runs 3' in capsys.readouterr().err
    assert _run(tmp_path, '--mode', 'record', '--suite', 'e4', '--runs', '2', *over) == 2
    assert live == []

    assert _run(tmp_path, '--mode', 'record', '--suite', 'e4', '--runs', '3', *over) == 0
    assert len(live) == 6  # two calls, three runs
    for root in ('cassettes', 'e6/run2', 'e6/run3'):
        assert (tmp_path / root / 'e4').is_dir(), root
    report = _report(tmp_path)
    assert set(report['extra_runs']) == {'run2', 'run3'}
    assert 'evals/consistency.py --suite e4' in capsys.readouterr().out

    _suite(tmp_path, 'e4', frozen=True, prompt='a changed prompt')
    assert _run(tmp_path, '--mode', 'record', '--runs', '3', *over) == 0  # not named
    assert len(live) == 6 and _result(tmp_path, 'e4')['status'] == 'stale'


def test_runs_needs_record_mode_and_no_baseline(tmp_path, live):
    _suite(tmp_path, 'ok', PASSING)
    assert _run(tmp_path, '--runs', '3') == 2
    assert _run(tmp_path, '--mode', 'auto', '--runs', '3') == 2
    assert _run(tmp_path, '--mode', 'record', '--runs', '0') == 2
    assert _run(tmp_path, '--mode', 'record', '--runs', '3', '--baseline') == 2


def test_a_baseline_keeps_a_stale_suites_last_measurement(tmp_path, live):
    _suite(tmp_path, 'e4', frozen=True)
    _suite(tmp_path, 'ok', PASSING)
    _record_frozen(tmp_path)
    assert _run(tmp_path, '--baseline') == 0
    old = json.loads((tmp_path / 'baseline.json').read_text())
    old_e4 = next(r for r in old['results'] if r['suite'] == 'e4')

    _suite(tmp_path, 'e4', frozen=True, prompt='a changed prompt')
    assert _run(tmp_path, '--baseline') == 0
    new = json.loads((tmp_path / 'baseline.json').read_text())
    new_e4 = next(r for r in new['results'] if r['suite'] == 'e4')
    assert new_e4 == {**old_e4, 'carried_over': True}
    assert new['status'] == 'pass'
    # a stale suite's metrics are not "missing" against the baseline
    assert _report(tmp_path)['baseline_comparison'].get('e4') is None


def test_a_baseline_with_no_measurement_of_a_stale_suite_is_refused(tmp_path, live, capsys):
    _suite(tmp_path, 'e4', frozen=True)
    _record_frozen(tmp_path)
    _suite(tmp_path, 'e4', frozen=True, prompt='a changed prompt')
    assert _run(tmp_path, '--baseline') == 2
    assert 'no measurement of it to keep' in capsys.readouterr().err
    assert not (tmp_path / 'baseline.json').exists()


def test_a_frozen_suite_with_no_recordings_is_an_error_not_stale(tmp_path, live, capsys):
    """CR-1 / SF-1: a missing cassette directory is a missing fixture, not
    a prompt change, and a re-record can't be what fixes it."""
    _suite(tmp_path, 'e4', frozen=True)
    assert _run(tmp_path) == 2
    result = _result(tmp_path, 'e4')
    assert result['status'] == 'error' and 'has no recordings' in result['error']
    _record_frozen(tmp_path)
    assert _run(tmp_path, '--cassettes-dir', str(tmp_path / 'nowhere')) == 2
    assert _result(tmp_path, 'e4')['status'] == 'error'


def test_the_stale_line_names_the_first_miss(tmp_path, live, capsys):
    _suite(tmp_path, 'e4', frozen=True)
    _record_frozen(tmp_path)
    _suite(tmp_path, 'e4', frozen=True, prompt='a changed prompt')
    capsys.readouterr()
    assert _run(tmp_path) == 0
    out = capsys.readouterr().out
    assert 'first miss: CassetteMiss' in out and 'a changed prompt' in out


def test_an_exception_after_a_miss_is_kept_on_the_stale_result(tmp_path, live, capsys):
    """C1 / CR-2 / SF-2 / TD3: still stale, but the exception isn't lost."""
    then = "raise KeyError('a metric bug')"
    _suite(tmp_path, 'e4', AFTER_MISS.replace('{then}', then))
    _record_frozen_any(tmp_path)  # records the call; the KeyError errors that run
    _suite(tmp_path, 'e4', AFTER_MISS.replace('{then}', then), prompt='a changed prompt')
    capsys.readouterr()
    assert _run(tmp_path) == 0
    result = _result(tmp_path, 'e4')
    assert result['status'] == 'stale' and result['error'] is None
    assert result['stale_exception'] == "KeyError: 'a metric bug'"
    assert 'a metric bug' in result['stale_traceback']
    assert 'raised after the miss' in capsys.readouterr().out


def test_a_miss_mixed_with_another_cassette_failure_is_an_error(tmp_path, live):
    """T7: stale only when every logged failure is a miss."""
    then = ("try:\n"
            "            cassette.request('POST', 'messages/batches', {}, lambda: {})\n"
            "        except Exception:\n"
            "            pass\n"
            "        return SuiteOutput(gates=[Gate('x', 1, '>=', 0)])")
    _suite(tmp_path, 'e4', AFTER_MISS.replace('{then}', then))
    _record_frozen_any(tmp_path)
    _suite(tmp_path, 'e4', AFTER_MISS.replace('{then}', then), prompt='a changed prompt')
    assert _run(tmp_path) == 2
    result = _result(tmp_path, 'e4')
    assert result['status'] == 'error' and len(result['cassette_failures']) == 2


def test_e6_counts_a_stale_run_as_no_spread():
    stale = {'suite': 'e4', 'status': 'stale', 'metrics': {}, 'by_code': {},
             'error': None, 'stale': '3 cassette miss(es): ...'}
    ok = {'suite': 'e4', 'status': 'pass', 'metrics': {'x': 1}, 'by_code': {}, 'error': None}
    summary = e6.summarize({'run1': {'results': [ok]}, 'run2': {'results': [stale]}})
    assert summary['errored'] == {'e4': {'run2': '3 cassette miss(es): ...'}}
    assert summary['suites'] == {}


# --- the monthly budget ------------------------------------------------------

def test_record_is_refused_when_the_forecast_would_pass_the_budget(tmp_path, live, capsys):
    _suite(tmp_path, 'e3')
    (tmp_path / 'baseline.json').write_text(json.dumps({'results': [
        {'suite': 'e3', 'status': 'pass', 'metrics': {}, 'cost': {'usd_if_live': 6.0}}]}))
    _spent(tmp_path, 20.0)
    _spent(tmp_path, 500.0, month='2020-01')  # another month: not counted
    assert _run(tmp_path, '--mode', 'record') == 2
    err = capsys.readouterr().err
    assert 'monthly eval budget would be passed' in err and '$6.00' in err
    assert live == []

    (tmp_path / 'config.json').write_text('{"monthly_budget_usd": 30}')
    assert _run(tmp_path, '--mode', 'record') == 0
    assert len(live) == 2
    budget = _report(tmp_path)['budget']
    assert budget['spent_before_usd'] == 20.0 and budget['spent_after_usd'] == 26.0
    assert budget['forecast_usd'] == 6.0 and budget['over_budget'] is None
    assert [e['suite'] for e in _ledger(tmp_path)][-2:] == ['e3', 'e3']


def test_over_budget_is_explicit_and_logged(tmp_path, live, capsys):
    _suite(tmp_path, 'e3')
    _spent(tmp_path, 25.0)
    assert _run(tmp_path, '--mode', 'auto') == 2
    assert live == []
    assert _run(tmp_path, '--mode', 'auto', '--over-budget', 'Ben approved in #999') == 0
    assert len(live) == 2
    captured = capsys.readouterr()
    assert 'WARNING: --over-budget' in captured.err and 'Ben approved in #999' in captured.err
    assert _report(tmp_path)['budget']['over_budget'] == 'Ben approved in #999'
    assert [e.get('over_budget') for e in _ledger(tmp_path)[-2:]] == ['Ben approved in #999'] * 2


def test_the_cassette_stops_live_calls_once_the_budget_is_reached(tmp_path, live):
    """auto starts under budget; the first call takes the month to the
    budget, so the second is refused and the suite errors."""
    _suite(tmp_path, 'e3')
    _spent(tmp_path, 22.0)
    assert _run(tmp_path, '--mode', 'auto') == 2
    assert len(live) == 1
    result = _result(tmp_path, 'e3')
    assert 'BudgetRefused' in result['error'] and 'monthly eval budget is spent' in result['error']
    assert eval_spend.month_spend(str(tmp_path / 'spend.jsonl')) == 25.0
    # what was recorded replays for free on the next run
    assert _run(tmp_path, '--mode', 'auto', '--over-budget', 'finish') == 0
    assert len(live) == 2


def test_replay_needs_no_budget(tmp_path, live):
    _suite(tmp_path, 'ok', PASSING)
    _spent(tmp_path, 1000.0)
    assert _run(tmp_path) == 0
    assert 'budget' not in _report(tmp_path)


def test_an_unreadable_ledger_or_config_refuses(tmp_path, live, capsys):
    _suite(tmp_path, 'e3')
    (tmp_path / 'spend.jsonl').write_text('{broken\n')
    assert _run(tmp_path, '--mode', 'auto') == 2
    assert 'line 1 can\'t be read' in capsys.readouterr().err
    (tmp_path / 'spend.jsonl').unlink()
    for bad in ('{}', '{"monthly_budget_usd": "25"}', '{"monthly_budget_usd": -1}', 'nope'):
        (tmp_path / 'config.json').write_text(bad)
        assert _run(tmp_path, '--mode', 'auto') == 2, bad
        assert 'monthly_budget_usd unreadable' in capsys.readouterr().err
    assert live == []


def test_the_default_budget_is_25_and_the_repo_config_says_so(tmp_path):
    assert eval_run.monthly_budget(str(tmp_path / 'absent.json')) == 25.0
    assert eval_run.monthly_budget(eval_run.CONFIG_FILE) == 25.0


def test_the_ledger_defaults_outside_the_repo(monkeypatch):
    monkeypatch.delenv(eval_spend.LEDGER_ENV)
    assert eval_spend.default_ledger() == os.path.expanduser('~/.storyforge/eval-spend.jsonl')


# --- the cassette's guard, unit level ----------------------------------------

BODY = {'model': 'claude-sonnet-4-6', 'max_tokens': 10,
        'messages': [{'role': 'user', 'content': 'hi'}]}


@pytest.fixture
def tape(tmp_path, monkeypatch, live):
    monkeypatch.setenv('STORYFORGE_CASSETTE', str(tmp_path / 'tape' / 'e2-carol'))
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    monkeypatch.setenv('STORYFORGE_CASSETTE_LOG', str(tmp_path / 'log.jsonl'))
    monkeypatch.setenv(eval_spend.LEDGER_ENV, str(tmp_path / 'spend.jsonl'))
    return tmp_path


def test_cassette_records_each_live_call_in_the_ledger(tape):
    api._api_request('messages', BODY, method='POST')
    [entry] = _ledger(tape)
    assert entry['suite'] == 'e2-carol' and entry['model'] == 'claude-sonnet-4-6'
    assert entry['usd'] == CALL_USD and 'over_budget' not in entry
    assert entry['at'].startswith(datetime.now(timezone.utc).strftime('%Y-%m'))


def test_cassette_refuses_at_the_budget_unless_overridden(tape, monkeypatch, live):
    monkeypatch.setenv(eval_spend.BUDGET_ENV, '3')
    _spent(tape, 3.0)
    with pytest.raises(cassette.BudgetRefused):
        api._api_request('messages', BODY, method='POST')
    assert live == []
    monkeypatch.setenv(eval_spend.OVERRIDE_ENV, 'approved')
    api._api_request('messages', BODY, method='POST')
    assert len(live) == 1 and _ledger(tape)[-1]['over_budget'] == 'approved'


@pytest.mark.parametrize('raw', ['lots', 'nan', 'inf', '-1'])
def test_cassette_refuses_on_a_budget_that_is_not_a_number(tape, monkeypatch, live, raw):
    """SF-3: NaN would make every `spent >= budget` False."""
    monkeypatch.setenv(eval_spend.BUDGET_ENV, raw)
    with pytest.raises(cassette.BudgetRefused, match='not a non-negative number'):
        api._api_request('messages', BODY, method='POST')
    assert live == []


def test_replays_never_touch_the_ledger(tape, monkeypatch):
    api._api_request('messages', BODY, method='POST')
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'replay')
    monkeypatch.setenv(eval_spend.BUDGET_ENV, '0')
    api._api_request('messages', BODY, method='POST')  # budget spent, but a replay is free
    assert len(_ledger(tape)) == 1


def test_month_spend_reads_only_this_month_and_rejects_bad_lines(tmp_path):
    path = tmp_path / 'spend.jsonl'
    assert eval_spend.month_spend(str(path)) == 0.0
    _spent(tmp_path, 1.5)
    _spent(tmp_path, 2.0, month='2001-01')
    assert eval_spend.month_spend(str(path)) == 1.5
    assert eval_spend.month_spend(str(path), month='2001-01') == 2.0
    with open(path, 'a') as f:
        f.write('{"at": "2026-11-01", "usd": "3"}\n')
    with pytest.raises(eval_spend.SpendLedgerError, match='line 3'):
        eval_spend.month_spend(str(path))


# --- run.py's exit code and refusals (PR #661 review) ------------------------

def test_a_carried_over_fail_does_not_change_the_exit_code(tmp_path, live):
    """TD1: --baseline exits on what this run measured, not on an old entry."""
    _suite(tmp_path, 'e4', frozen=True)
    _suite(tmp_path, 'ok', PASSING)
    _record_frozen(tmp_path)
    _suite(tmp_path, 'e4', frozen=True, prompt='a changed prompt')
    old_e4 = {'suite': 'e4', 'status': 'fail', 'metrics': {'x': 0.1}, 'by_code': {},
              'gates': [], 'cost': {'usd_if_live': 6.0}, 'error': None}
    (tmp_path / 'baseline.json').write_text(json.dumps({'results': [old_e4]}))
    assert _run(tmp_path, '--baseline') == 0
    assert _report(tmp_path)['status'] == 'stale'
    new = json.loads((tmp_path / 'baseline.json').read_text())
    assert new['status'] == 'fail'  # the baseline records the carried measurement


@pytest.mark.parametrize('old_status', ['error', 'stale'])
def test_a_baseline_wont_carry_an_old_entry_that_measured_nothing(tmp_path, live, capsys,
                                                                   old_status):
    """T9"""
    _suite(tmp_path, 'e4', frozen=True)
    _record_frozen(tmp_path)
    _suite(tmp_path, 'e4', frozen=True, prompt='a changed prompt')
    (tmp_path / 'baseline.json').write_text(json.dumps({'results': [
        {'suite': 'e4', 'status': old_status, 'metrics': {}, 'by_code': {}}]}))
    assert _run(tmp_path, '--baseline') == 2
    assert 'no measurement of it to keep' in capsys.readouterr().err


def test_an_unreadable_old_baseline_is_named_when_carrying(tmp_path):
    """SF-8: the read error, not 'no measurement'."""
    report = {'results': [{'suite': 'e4', 'status': 'stale'}]}
    baseline = str(tmp_path / 'baseline.json')
    assert 'has no measurement' in eval_run._carry_stale(report, baseline)  # absent
    (tmp_path / 'baseline.json').write_text('{not json')
    refused = eval_run._carry_stale(report, baseline)
    assert "can't be read" in refused and 'JSONDecodeError' in refused


def test_auto_naming_a_frozen_suite_is_refused(tmp_path, live, capsys):
    """C2: auto would only replay it, which looks like a re-record that wasn't."""
    _suite(tmp_path, 'e4', frozen=True)
    assert _run(tmp_path, '--mode', 'auto', '--suite', 'e4', '--over-budget', 'x') == 2
    assert 'auto would only replay it' in capsys.readouterr().err
    assert live == []


COUNTED = '''
    from harness import Gate, Suite, SuiteOutput
    from storyforge import api

    def run(ctx):
        import os
        counter = {counter!r}
        n = int(open(counter).read()) + 1 if os.path.exists(counter) else 1
        open(counter, 'w').write(str(n))
        if n == 2:
            raise RuntimeError('run 2 broke')
        api.invoke_api('hi', 'claude-sonnet-4-6', max_tokens=10)
        return SuiteOutput(gates=[Gate('x', 1, '>=', 0)])

    SUITE = Suite('{name}', 'breaks on its second run', run, frozen=True)
'''


def test_an_errored_extra_run_errors_the_whole_recording(tmp_path, live, capsys):
    """T4 / TD4: run 1 passes, run 2 raises: exit 2, and the cassettes it
    may have left mixed are named."""
    _suite(tmp_path, 'e4', COUNTED.replace('{counter!r}', repr(str(tmp_path / 'n'))))
    assert _run(tmp_path, '--mode', 'record', '--suite', 'e4', '--runs', '3',
                '--over-budget', 'test') == 2
    report = _report(tmp_path)
    assert report['status'] == 'error'
    assert report['results'][0]['status'] == 'pass'
    assert report['extra_runs']['run2']['results'][0]['status'] == 'error'
    assert report['extra_runs']['run3']['results'][0]['status'] == 'pass'
    err = capsys.readouterr().err
    assert 'frozen recording errored' in err and str(tmp_path / 'e6' / 'run2' / 'e4') in err


# --- the ledger and the budget fail closed (PR #661 review) ------------------

@pytest.mark.parametrize('line', [
    '{"at": "11/05/2026", "usd": 40}',                       # T1: not ISO
    '{"at": "2026-11", "usd": 40}',
    '{"at": "2026-11-01T00:00:00+00:00", "usd": NaN}',       # T2 / CR-3
    '{"at": "2026-11-01T00:00:00+00:00", "usd": Infinity}',
    '{"at": "2026-11-01T00:00:00+00:00", "usd": -30}',
    '{"at": "2026-11-01T00:00:00+00:00", "usd": true}',
    '5', '[]', 'null',
])
def test_month_spend_rejects_a_line_it_cannot_count(tmp_path, line):
    path = tmp_path / 'spend.jsonl'
    path.write_text(line + '\n')
    with pytest.raises(eval_spend.SpendLedgerError, match='line 1'):
        eval_spend.month_spend(str(path))
    assert eval_spend.refusal(str(path), 25.0)  # and the budget refuses on it


def test_month_spend_refuses_a_ledger_path_that_is_not_a_file(tmp_path):
    """SF-4: only 'nothing there' is $0."""
    (tmp_path / 'dir').mkdir()
    with pytest.raises(eval_spend.SpendLedgerError, match="can't be read"):
        eval_spend.month_spend(str(tmp_path / 'dir'))
    (tmp_path / 'dangling').symlink_to(tmp_path / 'gone')
    with pytest.raises(eval_spend.SpendLedgerError):
        eval_spend.month_spend(str(tmp_path / 'dangling'))
    assert eval_spend.month_spend(str(tmp_path / 'absent')) == 0.0


def test_a_ledger_that_turns_unreadable_mid_run_is_a_refusal(tmp_path, monkeypatch):
    """SF-6: an OSError reaches the cassette as a BudgetRefused (through
    _fail and the log), not a bare exception command code may swallow."""
    path = tmp_path / 'spend.jsonl'
    path.write_text('')
    monkeypatch.setattr('builtins.open', _raising_open(str(path)))
    assert "can't be read" in eval_spend.refusal(str(path), 25.0)


def _raising_open(target):
    real = open

    def fake(file, *a, **k):
        if str(file) == target:
            raise PermissionError('denied')
        return real(file, *a, **k)
    return fake


def test_record_starts_a_new_line_after_a_cut_off_one(tmp_path):
    """CR-4: an entry is never glued to a truncated last line."""
    path = tmp_path / 'spend.jsonl'
    path.write_text('{"at": "2026-11-01T00:0')
    eval_spend.record(str(path), suite='e3', model='m', usd=1.0)
    lines = path.read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])['suite'] == 'e3'
    eval_spend.record(str(path), suite='e3', model='m', usd=1.0)
    assert len(path.read_text().splitlines()) == 3


@pytest.mark.parametrize('bad', ['{"monthly_budget_usd": NaN}', '{"monthly_budget_usd": Infinity}'])
def test_a_budget_that_is_not_finite_refuses(tmp_path, bad):
    """SF-3"""
    (tmp_path / 'config.json').write_text(bad)
    with pytest.raises(eval_run.Refused, match='unreadable'):
        eval_run.monthly_budget(str(tmp_path / 'config.json'))


def test_a_config_path_that_is_not_a_file_refuses_and_the_default_is_named(tmp_path, live,
                                                                            capsys):
    """SF-7"""
    (tmp_path / 'cfgdir').mkdir()
    with pytest.raises(eval_run.Refused):
        eval_run.monthly_budget(str(tmp_path / 'cfgdir'))
    _suite(tmp_path, 'ok', PASSING)
    assert _run(tmp_path, '--mode', 'auto') == 0
    assert 'default; ' in capsys.readouterr().out


def test_cassette_warns_when_neither_the_ledger_nor_the_log_can_be_written(
        tape, monkeypatch, capsys):
    """SF-9"""
    monkeypatch.setattr(eval_spend, 'record', _oserror)
    monkeypatch.setattr(cassette, '_append_log', _oserror)
    monkeypatch.setattr(cassette, '_log_call', lambda *a, **k: None)
    api._api_request('messages', BODY, method='POST')
    assert 'eval spend ledger not written' in capsys.readouterr().err


def _oserror(*a, **k):
    raise OSError('disk gone')


def test_record_with_an_unreadable_baseline_is_refused(tmp_path, live, capsys):
    """SF-5 / CR-5: the forecast can't be made, so it isn't guessed as $0."""
    _suite(tmp_path, 'e3')
    (tmp_path / 'baseline.json').write_text('{not json')
    assert _run(tmp_path, '--mode', 'record') == 2
    assert "can't be read for the forecast" in capsys.readouterr().err
    assert live == []


def test_one_bad_baseline_entry_blanks_only_its_own_suite(tmp_path):
    (tmp_path / 'baseline.json').write_text(json.dumps({'results': [
        {'suite': 'a', 'cost': {'usd_if_live': 2.0}},
        {'suite': 'b', 'cost': {}},
        {'suite': 'c', 'cost': {'usd_if_live': 'x'}}]}))
    suites = [harness.Suite(n, '', None) for n in 'abc']
    assert eval_run._forecast(suites, str(tmp_path / 'baseline.json'), 2) == (4.0, ['b', 'c'])


def test_a_suite_with_no_baseline_figure_is_a_lower_bound_warning(tmp_path, live, capsys):
    """T10 / TD5 / C5: recorded, with a WARNING; the per-call check stops it."""
    _suite(tmp_path, 'e3')
    _spent(tmp_path, 22.0)
    assert _run(tmp_path, '--mode', 'record') == 2  # forecast $0 passes; the cassette stops call 2
    captured = capsys.readouterr()
    assert 'no figure for e3' in captured.out and 'lower bound' in captured.err
    assert len(live) == 1 and 'BudgetRefused' in _result(tmp_path, 'e3')['error']


def test_a_frozen_recording_with_no_baseline_figure_is_refused(tmp_path, live, capsys):
    """SF-5: a cut-off three-run recording would leave its cassettes mixed."""
    _suite(tmp_path, 'e4', frozen=True)
    assert _run(tmp_path, '--mode', 'record', '--suite', 'e4', '--runs', '3') == 2
    assert "can't be forecast" in capsys.readouterr().err
    assert live == []


def test_the_forecast_multiplies_by_runs_and_skips_unnamed_frozen_suites(tmp_path, live, capsys):
    """T5"""
    _suite(tmp_path, 'e4', frozen=True)
    (tmp_path / 'baseline.json').write_text(json.dumps({'results': [
        {'suite': 'e4', 'status': 'pass', 'metrics': {}, 'cost': {'usd_if_live': 5.0}}]}))
    _spent(tmp_path, 11.0)
    assert _run(tmp_path, '--mode', 'record', '--suite', 'e4', '--runs', '3') == 2
    assert 'forecasts $15.00' in capsys.readouterr().err
    assert live == []
    _record_frozen(tmp_path)
    (tmp_path / 'config.json').write_text('{"monthly_budget_usd": 100}')
    capsys.readouterr()
    assert _run(tmp_path, '--mode', 'record') == 0  # e4 not named: replayed, forecast $0
    assert '$0.00 if every call goes live' in capsys.readouterr().out


def test_record_exactly_at_the_budget_is_allowed_and_blank_over_budget_is_no_override(
        tmp_path, live):
    """T8: the record guard is `>`; --over-budget '   ' strips to nothing."""
    _suite(tmp_path, 'e3')
    (tmp_path / 'baseline.json').write_text(json.dumps({'results': [
        {'suite': 'e3', 'status': 'pass', 'metrics': {}, 'cost': {'usd_if_live': 6.0}}]}))
    _spent(tmp_path, 19.0)
    assert _run(tmp_path, '--mode', 'record') == 0
    assert _run(tmp_path, '--mode', 'auto', '--over-budget', '   ') == 2  # $25 spent
    assert not (tmp_path / 'results' / 'latest.json').exists()


def test_auto_is_refused_once_the_month_is_spent(tmp_path, live, capsys):
    """C (gap): the `spent >= budget` branch, without --over-budget."""
    _suite(tmp_path, 'e3')
    _spent(tmp_path, 25.0)
    assert _run(tmp_path, '--mode', 'auto') == 2
    assert 'monthly eval budget would be passed' in capsys.readouterr().err
    assert live == []


def test_an_unreadable_ledger_with_over_budget_runs_and_says_so(tmp_path, live, capsys):
    """T6"""
    _suite(tmp_path, 'e3')
    (tmp_path / 'spend.jsonl').write_text('{broken\n')
    assert _run(tmp_path, '--mode', 'auto', '--over-budget', 'Ben, ledger repair') == 0
    err = capsys.readouterr().err
    assert err.count("line 1 can't be read") == 2  # before and after
    budget = _report(tmp_path)['budget']
    assert budget['spent_before_usd'] is None and budget['spent_after_usd'] is None
    assert len(live) == 2

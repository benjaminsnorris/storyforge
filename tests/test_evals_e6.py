import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402,F401
import e6  # noqa: E402


def _result(suite, metrics, by_code=None, status='pass', error=None):
    return {'suite': suite, 'metrics': metrics, 'by_code': by_code or {},
            'status': status, 'error': error}


def _report(*results):
    return {'results': list(results)}


def test_spread_of_three_runs():
    row = e6.spread([1, 2, 3])
    assert row['mean'] == 2
    assert row['sd'] == 1
    assert (row['min'], row['max'], row['range']) == (1, 3, 2)


def test_a_single_value_has_no_spread():
    assert e6.spread([5])['sd'] == 0.0


def test_flatten_keeps_numbers_and_codes_and_drops_the_rest():
    flat = e6.flatten(_result('s', {'recall': 0.5, 'flag': True, 'note': 'x'},
                              {'TIM': {'recall': 0.2}}))
    assert flat == {'recall': 0.5, 'TIM.recall': 0.2}


def test_summarize_spreads_each_metric_across_runs():
    summary = e6.summarize({
        'run1': _report(_result('e3', {'recall': 0.2})),
        'run2': _report(_result('e3', {'recall': 0.3})),
        'run3': _report(_result('e3', {'recall': 0.25})),
    })
    assert summary['suites']['e3']['recall']['values'] == [0.2, 0.3, 0.25]
    assert summary['suites']['e3']['recall']['range'] == pytest.approx(0.1)
    assert summary['errored'] == {}


def test_a_suite_that_errored_in_any_run_gets_no_spread():
    summary = e6.summarize({
        'run1': _report(_result('e4', {'cp10k': 16})),
        'run2': _report(_result('e4', {}, status='error', error='CassetteMiss: x')),
    })
    assert 'e4' not in summary['suites']
    assert summary['errored']['e4'] == {'run2': 'CassetteMiss: x'}


def test_a_suite_absent_from_a_run_is_named_not_spread():
    summary = e6.summarize({
        'run1': _report(_result('e4', {'cp10k': 16})),
        'run2': _report(),
    })
    assert summary['errored']['e4'] == {'run2': 'suite not in this run'}


def test_a_metric_missing_from_a_run_is_named():
    summary = e6.summarize({
        'run1': _report(_result('e4', {}, {'TIM': {'contradictions': 2}})),
        'run2': _report(_result('e4', {})),
    })
    row = summary['suites']['e4']['TIM.contradictions']
    assert row['values'] == [2]
    assert row['missing_in'] == ['run2']


def test_a_claim_smaller_than_the_range_is_within_noise():
    summary = e6.summarize({
        'run1': _report(_result('e3', {'recall': 0.2})),
        'run2': _report(_result('e3', {'recall': 0.3})),
    })
    assert e6.exceeds(summary, 'e3', 'recall', 0.05)['within_noise'] is True
    assert e6.exceeds(summary, 'e3', 'recall', -0.05)['within_noise'] is True
    assert e6.exceeds(summary, 'e3', 'recall', 0.2)['within_noise'] is False


def test_a_claim_gets_no_verdict_without_every_run():
    summary = e6.summarize({
        'run1': _report(_result('e4', {}, {'TIM': {'contradictions': 2}})),
        'run2': _report(_result('e4', {}), _result('e8', {}, status='error', error='x')),
    })
    partial = e6.exceeds(summary, 'e4', 'TIM.contradictions', 1)
    assert partial['within_noise'] is None
    assert partial['why'] == 'metric not measured in every run'
    errored = e6.exceeds(summary, 'e8', 'reintroduced', 1)
    assert errored['within_noise'] is None
    assert errored['why'] == 'suite errored or not run'

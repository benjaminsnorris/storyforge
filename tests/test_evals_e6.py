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


def test_a_claim_equal_to_the_range_is_within_noise():
    """Two real claims sit exactly on their range (3 of 51 drift cases)."""
    summary = e6.summarize({
        'run1': _report(_result('d', {'recall': 4 / 51})),
        'run2': _report(_result('d', {'recall': 1 / 51})),
    })
    assert e6.exceeds(summary, 'd', 'recall', 3 / 51)['within_noise'] is True


def test_a_metric_no_run_measured_is_named_as_such():
    summary = e6.summarize({'run1': _report(_result('d', {'recall': 0.1}))})
    assert e6.exceeds(summary, 'd', 'recal', 0.1)['why'] == 'no run measured this metric'


def test_an_errored_suite_without_a_message_says_so():
    summary = e6.summarize({'run1': _report(_result('d', {}, status='error', error=None))})
    assert summary['errored']['d'] == {'run1': 'errored (no message)'}


def test_case_outcomes_reads_each_case_per_run():
    def e8(*notes):
        return _report({**_result('e8-revision-safety', {}), 'notes': list(notes)})
    out = e6.case_outcomes({
        'run1': e8('excluded 2: holdout (a-1, a-2)', 'gov-016 (scene-x): reintroduced — "quote"'),
        'run2': e8('gov-016 (scene-x): consistent'),
    })
    assert out == {'gov-016': {'run1': 'reintroduced', 'run2': 'consistent'}}


def test_every_claim_names_a_measured_metric():
    """A typo in CLAIMS would otherwise read as 'no verdict'."""
    import json
    sys.path.insert(0, str(PLUGIN_DIR / 'evals'))
    import consistency
    with open(PLUGIN_DIR / 'evals' / 'e6' / 'spread.json') as f:
        spread = json.load(f)
    for suite, metric, _delta, _claim in consistency.CLAIMS:
        assert metric in spread['suites'][suite], (suite, metric)


def test_a_rounded_range_still_meets_an_exact_delta_it_equals():
    """E3 with partial: 0.7551 - 0.6939 = 0.0612, the claim 3/49 = 0.061224."""
    summary = e6.summarize({
        'run1': _report(_result('e3', {'recall_with_partial': 0.7551})),
        'run2': _report(_result('e3', {'recall_with_partial': 0.6939})),
    })
    assert e6.exceeds(summary, 'e3', 'recall_with_partial', 3 / 49)['within_noise'] is True

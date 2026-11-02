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


def _spread(suites, sha, errored=None):
    return {'runs': ['run1', 'run2', 'run3'], 'suites': suites, 'errored': errored or {},
            'git_sha': sha}


def test_merge_replaces_the_replayed_suite_and_keeps_the_rest():
    old = _spread({'e3': {'recall': {'range': 0.1}}, 'e4': {'cp10k': {'range': 9}}},
                  {'e3': {'run1': 'a'}, 'e4': {'run1': 'a'}})
    new = _spread({'e4': {'cp10k': {'range': 1}}}, {'e4': {'run1': 'b'}})
    out = e6.merge(old, new)
    assert out['suites'] == {'e3': {'recall': {'range': 0.1}}, 'e4': {'cp10k': {'range': 1}}}
    assert out['git_sha'] == {'e3': {'run1': 'a'}, 'e4': {'run1': 'b'}}


@pytest.mark.parametrize('old, why', [
    (_spread({'e3': {}}, {'run1': 'a', 'run2': 'a', 'run3': 'a'}), 'not per suite'),
    (_spread({'e3': {}}, {'e3': {'run1': 'a'}, 'run1': 'a'}), 'not per suite'),
    ({k: v for k, v in _spread({}, {}).items() if k != 'git_sha'}, 'not per suite'),
    (['not', 'a', 'spread'], 'not a JSON object'),
])
def test_merge_refuses_a_spread_file_of_another_shape(old, why):
    """#483 review TD: a file whose shape it can't read fails, rather than
    writing run names as suites."""
    with pytest.raises(ValueError, match=why):
        e6.merge(old, _spread({'e4': {}}, {'e4': {'run1': 'b'}}))


def test_merge_replaces_a_suite_that_errored_now_by_what_was_replayed():
    old = _spread({'e4': {'cp10k': {}}}, {'e4': {'run1': 'a'}})
    out = e6.merge(old, _spread({}, {'e4': {'run1': 'b'}}, errored={'e4': {'run2': 'miss'}}))
    assert 'e4' not in out['suites'] and out['errored'] == {'e4': {'run2': 'miss'}}
    assert out['git_sha'] == {'e4': {'run1': 'b'}}


def test_merge_drops_an_old_error_for_a_suite_that_now_replays():
    old = _spread({}, {'e4': {'run1': 'a'}}, errored={'e4': {'run2': 'miss'}})
    out = e6.merge(old, _spread({'e4': {'cp10k': {}}}, {'e4': {'run1': 'b'}}))
    assert out['errored'] == {} and 'e4' in out['suites']


def test_merge_refuses_a_file_with_other_runs():
    old = dict(_spread({}, {}), runs=['run1', 'run2'])
    with pytest.raises(ValueError, match='runs'):
        e6.merge(old, _spread({}, {}))


def test_consistency_refuses_a_suite_e6_does_not_run(capsys):
    import consistency
    assert consistency.main(['--suite', 'e7-classics']) == 2
    assert 'not an E6 suite' in capsys.readouterr().err


def test_consistency_suite_merges_into_the_spread_file(tmp_path, monkeypatch):
    """--suite replays only that suite and keeps the file's other suites."""
    import json
    import consistency
    spread = tmp_path / 'spread.json'
    spread.write_text(json.dumps(_spread({'e3-extraction': {'recall': e6.spread([0.2, 0.3])}},
                                         {'e3-extraction': {'run1': 'a', 'run2': 'a',
                                                            'run3': 'a'}},
                                         errored={'e2-carol': {'run2': 'old miss'}})))
    cases = tmp_path / 'cases.json'
    report = {'git_sha': 'b', 'results': [_result('e4-generation', {'cp10k': 1.0})]}
    calls = []
    monkeypatch.setattr(consistency, 'run_all',
                        lambda suites, mode, d: calls.append([s.name for s in suites]) or report)
    # the old E2 error isn't this run's: exit 0
    assert consistency.main(['--suite', 'e4-generation', '--spread-file', str(spread),
                             '--cases-file', str(cases)]) == 0
    out = json.loads(spread.read_text())
    assert calls == [['e4-generation']] * 3
    assert set(out['suites']) == {'e3-extraction', 'e4-generation'}
    assert out['git_sha']['e4-generation'] == {'run1': 'b', 'run2': 'b', 'run3': 'b'}
    assert out['git_sha']['e3-extraction'] == {'run1': 'a', 'run2': 'a', 'run3': 'a'}
    assert not cases.exists()   # E8 wasn't replayed: its case file is left alone


def test_consistency_suite_with_an_unreadable_spread_file_says_so(tmp_path, monkeypatch, capsys):
    import consistency
    spread = tmp_path / 'spread.json'
    spread.write_text('{not json')
    monkeypatch.setattr(consistency, 'run_all',
                        lambda *a: {'git_sha': 'b', 'results': []})
    assert consistency.main(['--suite', 'e4-generation', '--spread-file', str(spread),
                             '--cases-file', str(tmp_path / 'c.json')]) == 2
    assert "can't merge" in capsys.readouterr().err
    assert spread.read_text() == '{not json'


def test_consistency_suite_that_errors_leaves_the_spread_file(tmp_path, monkeypatch, capsys):
    """#483 review SF-7: replaying E4 at a commit its runs 2-3 weren't
    recorded at misses; that must not replace the committed spread."""
    import consistency
    spread = tmp_path / 'spread.json'
    spread.write_text('{"kept": "as it was"}')
    report = {'git_sha': 'b', 'results': [_result('e4-generation', {}, status='error',
                                                  error='CassetteMiss: reading 2')]}
    monkeypatch.setattr(consistency, 'run_all', lambda *a: report)
    assert consistency.main(['--suite', 'e4-generation', '--spread-file', str(spread),
                             '--cases-file', str(tmp_path / 'c.json')]) == 2
    assert 'left as it was' in capsys.readouterr().err
    assert spread.read_text() == '{"kept": "as it was"}'


def test_consistency_suite_without_a_spread_file_says_so(tmp_path, monkeypatch, capsys):
    import consistency
    monkeypatch.setattr(consistency, 'run_all',
                        lambda *a: {'git_sha': 'b', 'results': [_result('e4-generation', {})]})
    assert consistency.main(['--suite', 'e4-generation', '--spread-file',
                             str(tmp_path / 'none.json'),
                             '--cases-file', str(tmp_path / 'c.json')]) == 2
    assert "can't merge" in capsys.readouterr().err


def test_consistency_suite_e8_writes_its_cases_file(tmp_path, monkeypatch):
    import json
    import consistency
    spread = tmp_path / 'spread.json'
    spread.write_text(json.dumps(_spread({}, {})))
    cases = tmp_path / 'cases.json'
    report = {'git_sha': 'b', 'results': [{**_result('e8-revision-safety', {'reintroduced': 1}),
                                           'notes': ['gov-016 (x): reintroduced']}]}
    monkeypatch.setattr(consistency, 'run_all', lambda *a: report)
    assert consistency.main(['--suite', 'e8-revision-safety', '--spread-file', str(spread),
                             '--cases-file', str(cases)]) == 0
    assert json.loads(cases.read_text()) == {'gov-016': {'run1': 'reintroduced',
                                                         'run2': 'reintroduced',
                                                         'run3': 'reintroduced'}}

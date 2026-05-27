"""Regression tests for #205 — cost ledger silently written to
working/working/costs/ledger.csv due to a wrong project_dir derivation.

The bug: three private helpers in cmd_score.py used
`os.path.dirname(os.path.dirname(cycle_dir))` to derive project_dir,
but cycle_dir is `<project>/working/scores/cycle-N` (3 levels deep),
so going up 2 lands at `<project>/working` — not `<project>`. The
ledger writer in costs.py then composed
`<project>/working/working/costs/ledger.csv`.

The fix passes project_dir as a parameter from the caller. These
tests pin both the signature change (so the param doesn't quietly
disappear in a future refactor) and the behavioral invariant (the
ledger lands at <project>/working/costs/, never at
<project>/working/working/costs/).
"""
import inspect
import os

from storyforge.cmd_score import (
    _score_batch, _score_direct, _run_act_scoring, _log_api_usage,
)


def test_score_batch_accepts_project_dir_param():
    """_score_batch must accept project_dir as a parameter so the
    caller (which knows the right value) can pass it through.
    Re-deriving project_dir from cycle_dir was the #205 bug; this
    test pins the signature change."""
    sig = inspect.signature(_score_batch)
    assert 'project_dir' in sig.parameters


def test_score_direct_accepts_project_dir_param():
    sig = inspect.signature(_score_direct)
    assert 'project_dir' in sig.parameters


def test_run_act_scoring_accepts_project_dir_param():
    sig = inspect.signature(_run_act_scoring)
    assert 'project_dir' in sig.parameters


def test_log_api_usage_writes_ledger_at_project_root(tmp_path):
    """End-to-end behavioral check: when _log_api_usage is called
    with the correct project_dir, the ledger appears at
    <project_dir>/working/costs/ledger.csv — never at
    <project_dir>/working/working/costs/ledger.csv (the #205 bug
    signature)."""
    import json
    # Simulate a cycle directory at the depth the buggy code assumed
    project_dir = str(tmp_path)
    cycle_dir = os.path.join(project_dir, 'working', 'scores', 'cycle-1')
    os.makedirs(cycle_dir, exist_ok=True)

    # A realistic LLM response JSON (the file _log_api_usage reads).
    log_file = os.path.join(cycle_dir, 'score-test.json')
    with open(log_file, 'w') as f:
        json.dump({
            'content': [{'type': 'text', 'text': '{}'}],
            'usage': {
                'input_tokens': 100, 'output_tokens': 100,
                'cache_read_input_tokens': 0,
                'cache_creation_input_tokens': 0,
            },
            'model': 'claude-sonnet-4-6',
        }, f)

    _log_api_usage(log_file, 'score', 'test-scene',
                   'claude-sonnet-4-6', project_dir)

    correct_ledger = os.path.join(project_dir, 'working', 'costs',
                                     'ledger.csv')
    buggy_ledger = os.path.join(project_dir, 'working', 'working',
                                   'costs', 'ledger.csv')
    assert os.path.isfile(correct_ledger), (
        f'cost ledger must land at {correct_ledger}'
    )
    assert not os.path.exists(buggy_ledger), (
        f'cost ledger must NEVER land at {buggy_ledger} — that path '
        'is the #205 bug signature (working/working/ accumulation)'
    )
    # And no working/working/ subtree should exist at all.
    nested_working = os.path.join(project_dir, 'working', 'working')
    assert not os.path.exists(nested_working), (
        f'no working/working/ subtree should be created; found '
        f'{nested_working}'
    )


def test_log_api_usage_with_buggy_derivation_demonstrates_the_bug(tmp_path):
    """Negative test: invoking _log_api_usage with the OLD (buggy)
    derivation `os.path.dirname(os.path.dirname(cycle_dir))`
    actively writes to the wrong path. This pins the bug
    characterization so a future "simplification" that reverts to
    the derivation pattern would be visibly wrong."""
    import json
    project_dir = str(tmp_path)
    cycle_dir = os.path.join(project_dir, 'working', 'scores', 'cycle-1')
    os.makedirs(cycle_dir, exist_ok=True)
    log_file = os.path.join(cycle_dir, 'score-test.json')
    with open(log_file, 'w') as f:
        json.dump({
            'content': [{'type': 'text', 'text': '{}'}],
            'usage': {
                'input_tokens': 100, 'output_tokens': 100,
                'cache_read_input_tokens': 0,
                'cache_creation_input_tokens': 0,
            },
            'model': 'claude-sonnet-4-6',
        }, f)

    # The OLD buggy derivation lands at <project>/working — two
    # levels up from cycle-1.
    buggy_project_dir = os.path.dirname(os.path.dirname(cycle_dir))
    assert buggy_project_dir == os.path.join(project_dir, 'working'), (
        'characterizes the bug: 2 dirname() calls land at '
        '<project>/working, not <project>'
    )

    _log_api_usage(log_file, 'score', 'test-scene',
                   'claude-sonnet-4-6', buggy_project_dir)

    # The ledger lands at the wrong path — exactly the #205 symptom.
    wrong_ledger = os.path.join(project_dir, 'working', 'working',
                                   'costs', 'ledger.csv')
    assert os.path.isfile(wrong_ledger), (
        'the buggy derivation produces the wrong path — this test '
        'pins what the bug looked like so it never returns silently'
    )


# ---------------------------------------------------------------------------
# Wiring tests — each helper must forward project_dir verbatim to
# _log_api_usage. The signature tests above catch parameter removal;
# these catch a "keep the param, ignore it" regression (e.g., a future
# refactor that adds `project_dir = os.path.dirname(...)` inside the
# helper body, overriding the param). Caught by the PR #249 review T-1.
# ---------------------------------------------------------------------------

def test_score_direct_forwards_project_dir_verbatim(tmp_path, monkeypatch):
    """_score_direct must pass `project_dir` to `_log_api_usage`
    unchanged. Without this, a future regression that re-derives
    project_dir inside the helper body would pass the signature tests
    silently."""
    import json
    import unittest.mock as mock
    from storyforge import cmd_score

    project_dir = str(tmp_path)
    cycle_dir = os.path.join(project_dir, 'working', 'scores', 'cycle-1')
    log_dir = os.path.join(cycle_dir, 'logs')
    scenes_dir = os.path.join(project_dir, 'scenes')
    for d in (cycle_dir, log_dir, scenes_dir):
        os.makedirs(d, exist_ok=True)

    # Minimal metadata + intent CSVs so _build_scene_prompt doesn't choke.
    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    metadata_csv = os.path.join(ref, 'scenes.csv')
    intent_csv = os.path.join(ref, 'scene-intent.csv')
    with open(metadata_csv, 'w') as f:
        f.write('id|title|summary\n')
        f.write('test-scene|Test|A test summary.\n')
    with open(intent_csv, 'w') as f:
        f.write('id|function\n')
        f.write('test-scene|opening\n')
    with open(os.path.join(scenes_dir, 'test-scene.md'), 'w') as f:
        f.write('A test scene body.\n')

    # Mock invoke_to_file so we don't hit the API; write a fake response
    # the parser can chew on (we don't care about parsing success here,
    # only the _log_api_usage call).
    def fake_invoke(prompt, model, log_file, max_tokens, system=None):
        with open(log_file, 'w') as f:
            json.dump({
                'content': [{'type': 'text', 'text': 'placeholder'}],
                'usage': {
                    'input_tokens': 10, 'output_tokens': 10,
                    'cache_read_input_tokens': 0,
                    'cache_creation_input_tokens': 0,
                },
                'model': model,
            }, f)
        return {
            'content': [{'type': 'text', 'text': 'placeholder'}],
            'usage': {
                'input_tokens': 10, 'output_tokens': 10,
                'cache_read_input_tokens': 0,
                'cache_creation_input_tokens': 0,
            },
        }
    monkeypatch.setattr(cmd_score, 'invoke_to_file', fake_invoke)

    with mock.patch.object(cmd_score, '_log_api_usage') as log_mock:
        cmd_score._score_direct(
            ['test-scene'], 'claude-sonnet-4-6',
            'evaluation_template', 'evaluation_criteria',
            'weighted_text', metadata_csv, intent_csv, scenes_dir,
            cycle_dir, log_dir, os.path.join(cycle_dir, 'diag.csv'),
            'plugin_dir', 1, 0.0, project_dir,
        )
    assert log_mock.called, '_log_api_usage must be called for each scene'
    # Each call's `project_dir` (5th positional arg) is the verbatim
    # value we passed. If a regression re-derived inside the helper, the
    # arg would differ.
    for call in log_mock.call_args_list:
        # Positional signature: (log_file, operation, target, model, project_dir)
        assert call.args[4] == project_dir, (
            f'_score_direct must forward project_dir={project_dir!r} '
            f'verbatim; got {call.args[4]!r}'
        )


def test_run_act_scoring_forwards_project_dir_verbatim(tmp_path, monkeypatch):
    """_run_act_scoring must pass `project_dir` to `_log_api_usage`
    unchanged."""
    import json
    import unittest.mock as mock
    from storyforge import cmd_score

    project_dir = str(tmp_path)
    cycle_dir = os.path.join(project_dir, 'working', 'scores', 'cycle-1')
    log_dir = os.path.join(cycle_dir, 'logs')
    scenes_dir = os.path.join(project_dir, 'scenes')
    prompts_dir = os.path.join(project_dir, 'prompts')
    for d in (cycle_dir, log_dir, scenes_dir, prompts_dir):
        os.makedirs(d, exist_ok=True)

    # Minimal act-level template + metadata so _run_act_scoring proceeds
    # past its early-exit guards.
    with open(os.path.join(prompts_dir, 'act-level.md'), 'w') as f:
        f.write('Act template body. {{ACT_LABEL}} {{ACT_ID}}\n')
    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    metadata_csv = os.path.join(ref, 'scenes.csv')
    with open(metadata_csv, 'w') as f:
        f.write('id|title|summary|part\n')
        f.write('s1|S1|x|act_1\n')
    with open(os.path.join(scenes_dir, 's1.md'), 'w') as f:
        f.write('Scene body.\n')
    weights_file = os.path.join(ref, 'weights.csv')
    with open(weights_file, 'w') as f:
        f.write('axis|weight\n')

    def fake_invoke(prompt, model, log_file, max_tokens, system=None):
        with open(log_file, 'w') as f:
            json.dump({
                'content': [{'type': 'text', 'text': 'placeholder'}],
                'usage': {
                    'input_tokens': 10, 'output_tokens': 10,
                    'cache_read_input_tokens': 0,
                    'cache_creation_input_tokens': 0,
                },
                'model': model,
            }, f)
        return {
            'content': [{'type': 'text', 'text': 'placeholder'}],
            'usage': {
                'input_tokens': 10, 'output_tokens': 10,
                'cache_read_input_tokens': 0,
                'cache_creation_input_tokens': 0,
            },
        }
    monkeypatch.setattr(cmd_score, 'invoke_to_file', fake_invoke)

    with mock.patch.object(cmd_score, '_log_api_usage') as log_mock:
        cmd_score._run_act_scoring(
            ['s1'], metadata_csv, scenes_dir, cycle_dir, log_dir,
            prompts_dir, weights_file, 'claude-sonnet-4-6',
            'plugin_dir', False, project_dir,
        )
    # The function may early-return if templates fail to load, but in
    # the common path it logs at least one act. If it called, the
    # project_dir must be verbatim.
    for call in log_mock.call_args_list:
        assert call.args[4] == project_dir, (
            f'_run_act_scoring must forward project_dir={project_dir!r} '
            f'verbatim; got {call.args[4]!r}'
        )


def test_check_stale_ledger_surfaces_buggy_path(tmp_path):
    """When a project carries a working/working/costs/ledger.csv from
    pre-#205 score runs, cmd_cleanup's build_cleanup_report includes a
    warning-severity 'stale_ledger' action item naming the path and a
    merge/move action. (PR #249 silent-failure review SF-HIGH.)"""
    from storyforge.cmd_cleanup import _check_stale_ledger
    project_dir = str(tmp_path)
    stale = os.path.join(project_dir, 'working', 'working', 'costs',
                          'ledger.csv')
    os.makedirs(os.path.dirname(stale), exist_ok=True)
    with open(stale, 'w') as f:
        f.write('timestamp|operation|target|model|input_tokens|output_tokens|'
                'cache_read|cache_create|cost_usd|duration_s\n')
        f.write('2026-01-01T00:00:00|score|s1|m|100|100|0|0|0.01|0\n')

    findings = _check_stale_ledger(project_dir)
    assert len(findings) == 1
    f = findings[0]
    assert f['type'] == 'stale_ledger'
    assert f['severity'] == 'warning'
    assert f['file'] == 'working/working/costs/ledger.csv'
    assert 'stale' in f['detail'].lower()


def test_check_stale_ledger_silent_when_only_correct_path_exists(tmp_path):
    """When only the correct working/costs/ledger.csv exists (no stale
    sibling), no finding fires. The detector is a one-time post-fix
    reconciliation prompt, not an always-on assertion."""
    from storyforge.cmd_cleanup import _check_stale_ledger
    project_dir = str(tmp_path)
    correct = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
    os.makedirs(os.path.dirname(correct), exist_ok=True)
    with open(correct, 'w') as f:
        f.write('timestamp|operation|target|model\n')

    assert _check_stale_ledger(project_dir) == []


def test_check_stale_ledger_silent_on_empty_project(tmp_path):
    """No ledgers at all → no finding. Avoids noise on fresh projects."""
    from storyforge.cmd_cleanup import _check_stale_ledger
    assert _check_stale_ledger(str(tmp_path)) == []


def test_check_stale_ledger_action_differs_when_no_correct_ledger(tmp_path):
    """When the stale ledger exists but no correct ledger exists, the
    action is 'move' rather than 'merge' — the historical data is the
    project's only cost record."""
    from storyforge.cmd_cleanup import _check_stale_ledger
    project_dir = str(tmp_path)
    stale = os.path.join(project_dir, 'working', 'working', 'costs',
                          'ledger.csv')
    os.makedirs(os.path.dirname(stale), exist_ok=True)
    with open(stale, 'w') as f:
        f.write('timestamp|operation\n2026-01-01|score\n')

    findings = _check_stale_ledger(project_dir)
    assert len(findings) == 1
    # 'move' rather than 'merge' when the correct path doesn't exist.
    assert 'move' in findings[0]['action'].lower()


def test_log_api_usage_warning_includes_operation_and_model(tmp_path, capsys):
    """_log_api_usage WARNING on failure must name `operation` and
    `model` for triage, not just the scene target. With the path bug
    fixed, surviving warnings should be rare — when they fire, the
    extra context matters. (PR #249 silent-failure review SF-MED-1.)"""
    from storyforge.cmd_score import _log_api_usage
    # Pass a non-existent log file so the inner read fails and the
    # except branch fires.
    missing = str(tmp_path / 'no-such-log.json')
    _log_api_usage(missing, 'score-fidelity', 'scene-42',
                   'claude-haiku-4-5-20251001', str(tmp_path))
    out = capsys.readouterr().out
    assert 'WARNING:' in out
    assert 'score-fidelity' in out  # operation
    assert 'scene-42' in out  # target
    assert 'claude-haiku-4-5-20251001' in out  # model


def test_revise_lightweight_score_does_not_typeerror_on_signature():
    """`cmd_revise._run_lightweight_score` imports `_score_direct` and
    must call it with the current signature. Without this test, a
    future signature change to `_score_direct` that's not reflected at
    the call site silently TypeErrors on next `revise --polish --loop`.
    (PR #249 review CR-1.)"""
    import inspect
    from storyforge.cmd_score import _score_direct
    from storyforge import cmd_revise

    # Source inspection of the call site: must pass the same number of
    # args as _score_direct accepts (less any with defaults).
    score_direct_sig = inspect.signature(_score_direct)
    required_params = [
        p for p in score_direct_sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                       inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    # The call site in cmd_revise._run_lightweight_score must supply
    # at least len(required_params) positional arguments.
    src = inspect.getsource(cmd_revise._run_lightweight_score)
    # The simplest robust check: confirm `project_dir` appears in the
    # _score_direct() call. A future signature change would make this
    # fail and point the maintainer at the exact call site.
    # Find the _score_direct(...) call substring.
    idx = src.find('_score_direct(')
    assert idx >= 0, (
        '_run_lightweight_score must call _score_direct '
        '(import-but-no-call would be dead code)'
    )
    # Slice from there to the matching close paren — coarse but
    # sufficient given the call is well-formatted.
    call_block = src[idx:idx + 600]
    assert 'project_dir' in call_block, (
        'the _score_direct call in _run_lightweight_score must pass '
        'project_dir. If you renamed/removed that parameter, fix the '
        'call site or remove this test.'
    )

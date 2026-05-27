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

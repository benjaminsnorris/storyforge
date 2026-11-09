"""Evaluate: a report cut off at max_tokens is asked again (#635).

On the whole Iliad two panel reports stopped mid-sentence at 24,192 output
tokens (8,192 asked for + the 16,000 thinking allowance, which thinking and
the report share), were saved partial with no retry, and the warning named
"the 8192-token limit". Reports now get a larger budget; a reply still cut
off is retried once with the model's whole output (`api.max_output_tokens`),
and the retry's report is the one saved. The warning names the real limit.
"""

import glob
import json
import os

import pytest

from storyforge.api import THINKING_ALLOWANCE, max_output_tokens, request_max_tokens
from storyforge.cmd_evaluate import (
    CORE_EVALUATORS, REPORT_ANSWER_TOKENS, main, report_budget,
)

from commands.conftest import TESTS_DIR

PLUGIN_DIR = os.path.dirname(TESTS_DIR)

SYNTH_FULL = ('--- BEGIN synthesis.md ---\n## Consensus\nWhole synthesis.\n'
              '--- END synthesis.md ---\n--- BEGIN findings.yaml ---\n'
              'findings: []\n--- END findings.yaml ---\n')


def _setup(project_dir, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_evaluate.detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.cmd_evaluate.get_plugin_dir', lambda: PLUGIN_DIR)
    monkeypatch.setattr('storyforge.cmd_evaluate.get_api_key', lambda: 'test-key')
    with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md'), 'w') as f:
        f.write('Dorren studied the map. The eastern sector readings were wrong.')


def _reply(text, stop):
    return {'content': [{'type': 'text', 'text': text}], 'stop_reason': stop,
            'usage': {'input_tokens': 100, 'output_tokens': 50}}


class FakeInvoke:
    """invoke_to_file: replies cut off at the first budget (or always, with
    ``always_cut``), whole at the model's whole output."""

    def __init__(self, always_cut=False, fail_retry=False):
        self.calls = []
        self.always_cut = always_cut
        self.fail_retry = fail_retry

    def __call__(self, prompt, model, log_file, max_tokens=4096, label='',
                 timeout=600, system=None, output_schema=None, fallback=False):
        self.calls.append({'log_file': log_file, 'model': model,
                           'max_tokens': max_tokens, 'timeout': timeout})
        first = max_tokens == REPORT_ANSWER_TOKENS
        if not first and self.fail_retry:
            raise RuntimeError('API request timed out')
        synth = 'reconciling' in prompt.lower()
        if first or self.always_cut:
            text = 'PARTIAL synthesis' if synth else 'PARTIAL report, stopped mid-sen'
            response = _reply(text, 'max_tokens')
        else:
            response = _reply(SYNTH_FULL if synth else '## Report\nWHOLE report.', 'end_turn')
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response


def _eval_dir(project_dir):
    dirs = glob.glob(os.path.join(project_dir, 'working', 'evaluations', 'eval-2*'))
    assert len(dirs) == 1
    return dirs[0]


def _read(path):
    with open(path) as f:
        return f.read()


def test_a_cut_off_report_is_retried_once_and_the_retry_is_saved(
        mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
    _setup(project_dir, monkeypatch)
    fake = FakeInvoke()
    monkeypatch.setattr('storyforge.cmd_evaluate.invoke_to_file', fake)

    main(['--direct', '--scene', 'act1-sc01', '--evaluator', 'line-editor'])

    assert len(fake.calls) == 2
    first, retry = fake.calls
    model = first['model']
    assert first['max_tokens'] == REPORT_ANSWER_TOKENS
    assert retry['max_tokens'] == max_output_tokens(model)
    assert request_max_tokens(model, retry['max_tokens']) > \
        request_max_tokens(model, first['max_tokens'])
    # each request has time to write its whole budget
    assert retry['timeout'] == report_budget(model, whole=True)[1] > first['timeout'] >= 600

    report = _read(os.path.join(_eval_dir(project_dir), 'line-editor.md'))
    assert 'WHOLE report.' in report
    assert 'PARTIAL' not in report and '**Cut off:**' not in report

    out = capsys.readouterr().out
    # the warning names the real limit, thinking allowance included
    total = request_max_tokens(model, REPORT_ANSWER_TOKENS)
    assert (f'WARNING: evaluator line-editor hit the {total:,}-token output limit '
            f'({REPORT_ANSWER_TOKENS:,} for the report + {THINKING_ALLOWANCE:,} '
            f'thinking allowance') in out
    assert "retrying once with the model's whole output" in out
    assert '8192' not in out
    # the cut-off attempt's log is kept beside the retry's, and both are costed
    assert os.path.isfile(first['log_file'] + '.cut-off')
    assert len([op for op in mock_costs.operations if op.get('target') == 'line-editor']) == 2


def test_a_retry_still_cut_off_is_kept_marked(
        mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
    _setup(project_dir, monkeypatch)
    fake = FakeInvoke(always_cut=True)
    monkeypatch.setattr('storyforge.cmd_evaluate.invoke_to_file', fake)

    main(['--direct', '--scene', 'act1-sc01', '--evaluator', 'line-editor'])

    assert len(fake.calls) == 2  # one retry only
    report = _read(os.path.join(_eval_dir(project_dir), 'line-editor.md'))
    assert '**Cut off:**' in report
    out = capsys.readouterr().out
    assert "hit the model's whole output" in out and 'on the retry too' in out


def test_a_failed_retry_keeps_the_cut_off_report(
        mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
    _setup(project_dir, monkeypatch)
    fake = FakeInvoke(fail_retry=True)
    monkeypatch.setattr('storyforge.cmd_evaluate.invoke_to_file', fake)

    main(['--direct', '--scene', 'act1-sc01', '--evaluator', 'line-editor'])

    report = _read(os.path.join(_eval_dir(project_dir), 'line-editor.md'))
    assert 'PARTIAL report' in report and '**Cut off:**' in report
    assert 'the retry of evaluator line-editor failed' in capsys.readouterr().out


def test_every_direct_call_site_retries_a_cut_off(
        mock_api, mock_git, mock_costs, project_dir, monkeypatch):
    """The six evaluators and the synthesis (and the assessment, when it
    runs) each retry once, and save the retry's reply."""
    _setup(project_dir, monkeypatch)
    fake = FakeInvoke()
    monkeypatch.setattr('storyforge.cmd_evaluate.invoke_to_file', fake)

    try:
        main(['--direct', '--scene', 'act1-sc01'])
    except SystemExit:
        pass

    by_log = {}
    for c in fake.calls:
        by_log.setdefault(os.path.basename(c['log_file']), []).append(c['max_tokens'])
    for name in CORE_EVALUATORS:
        assert by_log[f'eval-{name}.log'][0] == REPORT_ANSWER_TOKENS
        assert len(by_log[f'eval-{name}.log']) == 2
    assert len(by_log['eval-synthesis.log']) == 2
    if 'eval-assessment.log' in by_log:
        assert len(by_log['eval-assessment.log']) == 2

    eval_dir = _eval_dir(project_dir)
    for name in CORE_EVALUATORS:
        assert 'WHOLE report.' in _read(os.path.join(eval_dir, f'{name}.md'))
    synth = _read(os.path.join(eval_dir, 'synthesis.md'))
    assert 'Whole synthesis.' in synth and '**Cut off:**' not in synth


def test_batch_retries_a_cut_off_report_directly(
        mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
    _setup(project_dir, monkeypatch)
    cut = CORE_EVALUATORS[0]

    def fake_download(results_url, output_dir, log_dir, keep_incomplete=False):
        for name in CORE_EVALUATORS:
            stop = 'max_tokens' if name == cut else 'end_turn'
            text = 'PARTIAL batch report' if name == cut else f'## {name}\nGood.'
            with open(os.path.join(output_dir, f'.status-{name}'), 'w') as f:
                f.write('ok')
            with open(os.path.join(log_dir, f'{name}.txt'), 'w') as f:
                f.write(text)
            with open(os.path.join(log_dir, f'{name}.json'), 'w') as f:
                json.dump(_reply(text, stop), f)
        return list(CORE_EVALUATORS)

    monkeypatch.setattr('storyforge.cmd_evaluate.download_batch_results', fake_download)
    fake = FakeInvoke()
    monkeypatch.setattr('storyforge.cmd_evaluate.invoke_to_file', fake)
    try:
        main(['--scene', 'act1-sc01'])
    except SystemExit:
        pass

    batch, = mock_api.calls_for('submit_batch')
    for req in batch['requests']:
        model = req['params']['model']
        assert req['params']['max_tokens'] == request_max_tokens(model, REPORT_ANSWER_TOKENS)
    retries = [c for c in fake.calls if c['log_file'].endswith(f'eval-{cut}-retry.log')]
    assert len(retries) == 1
    assert retries[0]['max_tokens'] == max_output_tokens(retries[0]['model'])
    report = _read(os.path.join(_eval_dir(project_dir), f'{cut}.md'))
    assert 'WHOLE report.' in report and '**Cut off:**' not in report
    assert f'SUCCESS: {cut}' in capsys.readouterr().out


def test_no_retry_when_the_first_request_had_the_whole_output(monkeypatch, capsys):
    """A model whose whole output is under the first budget has nothing
    larger to retry with: the cut-off reply is kept, and says so."""
    from storyforge import cmd_evaluate
    monkeypatch.setattr(cmd_evaluate, 'max_output_tokens', lambda m: 32768)
    monkeypatch.setattr(cmd_evaluate, 'request_max_tokens',
                        lambda m, t: min(t + THINKING_ALLOWANCE, 32768))
    called = []
    monkeypatch.setattr(cmd_evaluate, 'invoke_to_file', lambda *a, **k: called.append(1))
    reply = _reply('PARTIAL', 'max_tokens')
    final, retried = cmd_evaluate._retry_cut_off(
        '/nonexistent', 'p', 'm', None, reply, REPORT_ANSWER_TOKENS, '/tmp/x.log',
        'synthesis', 'synthesize', 'synthesis')
    assert final is reply and not retried and not called
    assert "synthesis hit the model's whole output (32,768 tokens" in capsys.readouterr().out

"""A stage reply cut off at max_tokens is reported as that, and applies nothing.

On the Gawain novel the map stage's reply spent 29k of its 32k output tokens
thinking and stopped mid-table; the stage said only that the reply had "no
source-map-csv block" and "no output blocks" (G-018). The map and briefs
stages got a larger answer budget and a longer timeout; at 32,000 the map
of the whole Iliad (239 source scenes) still spent 47,424 of 48,000 tokens
thinking (#627), so they now ask for the model's whole output."""

import os

import pytest

from storyforge.cmd_elaborate import main, stage_budget
from storyforge.elaborate import _read_csv

PARTIAL = (
    '```scenes-csv\n'
    'id|seq|title|act|pov|location|timeline_day|time_mode|time_of_day|duration|status\n'
    'knight-offers-game|1|The Game|1|gawain|camelot|1|scene|noon|1 hour|mapped\n'
    'gawain-strikes-bl'
)


@pytest.fixture
def novel(project_dir, monkeypatch, mock_git, mock_costs):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: project_dir)
    return project_dir


def _run(mock_api, stage, response):
    mock_api.set_response_dict(response)
    try:
        main(['--stage', stage])
    except SystemExit as e:
        return e.code
    return 0


def test_a_truncated_map_reply_is_named_and_not_applied(novel, mock_api, capsys):
    before = open(os.path.join(novel, 'reference', 'scenes.csv')).read()
    code = _run(mock_api, 'map', {
        'content': [{'type': 'text', 'text': PARTIAL}],
        'stop_reason': 'max_tokens',
        'usage': {'input_tokens': 100, 'output_tokens': 32384,
                  'output_tokens_details': {'thinking_tokens': 29387}},
    })
    out = capsys.readouterr().out
    assert code == 1
    assert 'stopped at its output limit (32384 tokens, 29387 of them thinking)' in out
    assert open(os.path.join(novel, 'reference', 'scenes.csv')).read() == before
    assert 'knight-offers-game' not in {r['id'] for r in
                                        _read_csv(os.path.join(novel, 'reference', 'scenes.csv'))}


def test_map_asks_for_the_models_whole_output_and_time_to_write_it(novel, mock_api):
    """#627: the request carries the model's own output limit (not a fixed
    budget) and a timeout sized to it."""
    from storyforge.api import max_output_tokens
    _run(mock_api, 'map', {'content': [{'type': 'text', 'text': 'nothing'}],
                           'stop_reason': 'end_turn', 'usage': {}})
    call = [c for c in mock_api.calls if c['fn'] == 'invoke_to_file'][0]
    assert call['max_tokens'] == max_output_tokens(call['model'])
    assert call['timeout'] == stage_budget('map', call['model'])[1] > 600


@pytest.mark.parametrize('stage', ['map', 'briefs'])
def test_whole_output_stages_follow_each_models_limit(stage):
    """A 64k model gets 64k, a 128k model 128k: nothing pins one model's cap."""
    from storyforge.api import API_TIMEOUT, max_output_tokens
    for model in ('claude-opus-5-5', 'claude-haiku-4-5-20251001'):
        tokens, wait = stage_budget(stage, model)
        assert tokens == max_output_tokens(model)
        assert wait >= API_TIMEOUT and wait * 50 >= tokens


def test_other_stages_keep_the_default_budget():
    assert stage_budget('spine', 'claude-opus-5-5') == (16384, None)
    assert stage_budget('architecture', 'claude-opus-5-5') == (16384, None)


def test_request_max_tokens_clamps_to_the_models_limit():
    """The whole-output request is never over a model's limit (HTTP 400)."""
    from storyforge.api import max_output_tokens, request_max_tokens
    for model in ('claude-opus-5-5', 'claude-haiku-4-5-20251001'):
        cap = max_output_tokens(model)
        assert request_max_tokens(model, cap) == cap
        assert request_max_tokens(model, 1000) == min(1000 + 16000, cap)


def test_a_truncated_map_says_what_to_do(novel, mock_api, capsys):
    """Review (#627): the map already had the whole output, so its error
    names what is left to try."""
    _run(mock_api, 'map', {
        'content': [{'type': 'text', 'text': PARTIAL}], 'stop_reason': 'max_tokens',
        'usage': {'input_tokens': 100, 'output_tokens': 128000,
                  'output_tokens_details': {'thinking_tokens': 127000}},
    })
    out = capsys.readouterr().out
    assert "already had the model's whole output" in out
    assert 'range' in out


def test_a_cost_that_cannot_be_logged_is_warned(novel, mock_api, monkeypatch, capsys):
    """Review (#627): a failed cost log was swallowed by `except: pass`."""
    def boom(*a, **k):
        raise OSError('ledger is read-only')
    monkeypatch.setattr('storyforge.costs.log_operation', boom)
    _run(mock_api, 'map', {'content': [{'type': 'text', 'text': 'nothing'}],
                           'stop_reason': 'end_turn', 'usage': {}})
    out = capsys.readouterr().out
    assert "WARNING: the map call's cost was not logged (ledger is read-only)" in out

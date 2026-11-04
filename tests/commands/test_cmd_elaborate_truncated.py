"""A stage reply cut off at max_tokens is reported as that, and applies nothing.

On the Gawain novel the map stage's reply spent 29k of its 32k output tokens
thinking and stopped mid-table; the stage said only that the reply had "no
source-map-csv block" and "no output blocks" (G-018). The map and briefs
stages now get a larger answer budget and a longer timeout."""

import os

import pytest

from storyforge.cmd_elaborate import STAGE_ANSWER_TOKENS, STAGE_TIMEOUT, main
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


def test_map_and_briefs_get_the_larger_budget_and_timeout(novel, mock_api):
    _run(mock_api, 'map', {'content': [{'type': 'text', 'text': 'nothing'}],
                           'stop_reason': 'end_turn', 'usage': {}})
    call = [c for c in mock_api.calls if c['fn'] == 'invoke_to_file'][0]
    assert call['max_tokens'] == STAGE_ANSWER_TOKENS['map'] > 16384
    assert STAGE_TIMEOUT['briefs'] > 600 and STAGE_ANSWER_TOKENS['briefs'] > 16384

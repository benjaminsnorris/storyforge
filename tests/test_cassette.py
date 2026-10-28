import json
import os

import pytest

from storyforge import api, cassette

BODY = {'model': 'claude-sonnet-4-6', 'max_tokens': 10,
        'messages': [{'role': 'user', 'content': 'hi'}]}
RESPONSE = {'content': [{'type': 'text', 'text': 'hello'}],
            'usage': {'input_tokens': 5, 'output_tokens': 2}}


@pytest.fixture
def live_calls(monkeypatch):
    calls = []

    def fake_live(path, body, method, timeout):
        calls.append((path, body, method))
        return RESPONSE

    monkeypatch.setattr(api, '_live_request', fake_live)
    return calls


@pytest.fixture
def tape(tmp_path, monkeypatch):
    monkeypatch.setenv('STORYFORGE_CASSETTE', str(tmp_path / 'tape'))
    monkeypatch.setenv('STORYFORGE_CASSETTE_LOG', str(tmp_path / 'log.jsonl'))
    return tmp_path


def _log(tape):
    with open(tape / 'log.jsonl') as f:
        return [json.loads(line) for line in f]


def test_inert_without_cassette(monkeypatch, live_calls):
    monkeypatch.delenv('STORYFORGE_CASSETTE', raising=False)
    assert api._api_request('messages', BODY, method='POST') == RESPONSE
    assert len(live_calls) == 1


def test_replay_miss_raises_and_never_goes_live(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'replay')
    with pytest.raises(cassette.CassetteMiss):
        api._api_request('messages', BODY, method='POST')
    assert live_calls == []


def test_record_then_replay(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    assert api._api_request('messages', BODY, method='POST') == RESPONSE
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'replay')
    assert api._api_request('messages', BODY, method='POST') == RESPONSE
    assert len(live_calls) == 1
    assert [e['replayed'] for e in _log(tape)] == [False, True]
    assert _log(tape)[1]['usage'] == RESPONSE['usage']


def test_record_overwrites_existing(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    api._api_request('messages', BODY, method='POST')
    api._api_request('messages', BODY, method='POST')
    assert len(live_calls) == 2


def test_auto_records_only_misses(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'auto')
    api._api_request('messages', BODY, method='POST')
    api._api_request('messages', BODY, method='POST')
    api._api_request('messages', {**BODY, 'max_tokens': 11}, method='POST')
    assert len(live_calls) == 2


def test_key_depends_on_body_not_dict_order():
    reordered = dict(reversed(list(BODY.items())))
    assert cassette.request_key('POST', 'messages', BODY) == \
        cassette.request_key('POST', 'messages', reordered)
    assert cassette.request_key('POST', 'messages', BODY) != \
        cassette.request_key('POST', 'messages', {**BODY, 'max_tokens': 11})


def test_batch_api_refused(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'auto')
    with pytest.raises(RuntimeError, match='Batch API'):
        api._api_request('messages/batches', {'requests': []}, method='POST')
    assert live_calls == []


def test_unknown_mode_refused(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'replay-ish')
    with pytest.raises(RuntimeError, match='not one of'):
        api._api_request('messages', BODY, method='POST')


def test_recording_holds_request_for_debugging(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    api._api_request('messages', BODY, method='POST')
    key = cassette.request_key('POST', 'messages', BODY)
    with open(cassette.recording_path(os.environ['STORYFORGE_CASSETTE'], key)) as f:
        assert json.load(f)['request']['body'] == BODY

import gzip
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
    monkeypatch.setattr(cassette, '_recorded_here', set())
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


def test_record_overwrites_a_recording_from_an_earlier_run(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    api._api_request('messages', BODY, method='POST')
    # A new run: a fresh process and log
    monkeypatch.setattr(cassette, '_recorded_here', set())
    monkeypatch.setenv('STORYFORGE_CASSETTE_LOG', str(tape / 'log2.jsonl'))
    api._api_request('messages', BODY, method='POST')
    assert len(live_calls) == 2


def test_record_replays_a_request_this_run_already_recorded(tape, monkeypatch, live_calls):
    """E6 (2026-10-30): two E3 cases share one scene, so they send the same
    extraction request. Recording called it live twice; the second reply
    overwrote the first, and the first case's judge prompt, built from the
    first reply, could never replay."""
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    replies = iter([RESPONSE, {**RESPONSE, 'content': [{'type': 'text', 'text': 'other'}]}])
    monkeypatch.setattr(api, '_live_request', lambda *a: next(replies))
    first = api._api_request('messages', BODY, method='POST')
    assert api._api_request('messages', BODY, method='POST') == first
    assert [e['replayed'] for e in _log(tape)] == [False, True]


def test_a_second_run_in_the_same_process_records_again(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    api._api_request('messages', BODY, method='POST')
    monkeypatch.setenv('STORYFORGE_CASSETTE_LOG', str(tape / 'log2.jsonl'))  # the next run
    api._api_request('messages', BODY, method='POST')
    assert len(live_calls) == 2


def test_a_replayed_log_entry_is_not_a_recording(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'auto')
    api._api_request('messages', BODY, method='POST')     # recorded
    monkeypatch.setattr(cassette, '_recorded_here', set())
    monkeypatch.setenv('STORYFORGE_CASSETTE_LOG', str(tape / 'log2.jsonl'))
    api._api_request('messages', BODY, method='POST')     # replayed in the new run
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    api._api_request('messages', BODY, method='POST')     # still goes live
    assert len(live_calls) == 2


def test_a_recording_that_cant_be_saved_is_logged_and_raised(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    def fail(*a, **k):
        raise OSError('disk full')
    monkeypatch.setattr(cassette.tempfile, 'mkstemp', fail)
    with pytest.raises(cassette.CassetteError, match='disk full'):
        api._api_request('messages', BODY, method='POST')
    log = _log(tape)
    assert log[0]['replayed'] is False and log[0]['usage'] == RESPONSE['usage']
    assert 'disk full' in log[1]['error']


def test_a_subprocess_sharing_the_runs_log_replays_it_too(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    api._api_request('messages', BODY, method='POST')
    monkeypatch.setattr(cassette, '_recorded_here', set())  # another process, same log
    api._api_request('messages', BODY, method='POST')
    assert len(live_calls) == 1


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
    with pytest.raises(cassette.CassetteError, match='Batch API'):
        api._api_request('messages/batches', {'requests': []}, method='POST')
    assert live_calls == []


def test_unknown_mode_refused(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'replay-ish')
    with pytest.raises(cassette.CassetteError, match='not one of'):
        api._api_request('messages', BODY, method='POST')
    assert 'not one of' in _log(tape)[0]['error']


def test_every_failure_is_logged_for_the_harness(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'replay')
    with pytest.raises(cassette.CassetteMiss, match='Prompt starts: "hi"'):
        api._api_request('messages', BODY, method='POST')
    with pytest.raises(cassette.CassetteError):
        api._api_request('messages/batches', {}, method='POST')
    assert [e['error'].split(':')[0] for e in _log(tape)] == ['CassetteMiss', 'CassetteError']


@pytest.mark.parametrize('content', [b'{truncated', b'not gzip at all', gzip.compress(b'{"request": {}}', mtime=0), gzip.compress(b'[]', mtime=0),
                                     gzip.compress(b'{"x": 1', mtime=0)[:-6]])
def test_unreadable_recording_is_an_error_not_an_answer(tape, monkeypatch, live_calls, content):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'replay')
    target = cassette.recording_path(os.environ['STORYFORGE_CASSETTE'],
                                     cassette.request_key('POST', 'messages', {
                                         **BODY, 'max_tokens': api.request_max_tokens(BODY['model'], 10)}))
    os.makedirs(os.path.dirname(target))
    with open(target, 'wb') as f:
        f.write(content)
    with pytest.raises(cassette.CassetteError, match='Unreadable recording'):
        api.invoke_api('hi', BODY['model'], max_tokens=10)
    assert live_calls == []


def test_invoke_api_reraises_every_cassette_error(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'bogus')
    with pytest.raises(cassette.CassetteError):
        api.invoke_api('hi', BODY['model'], max_tokens=10)


def test_recording_holds_request_for_debugging(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    api._api_request('messages', BODY, method='POST')
    key = cassette.request_key('POST', 'messages', BODY)
    with gzip.open(cassette.recording_path(os.environ['STORYFORGE_CASSETTE'], key), 'rt') as f:
        assert json.load(f)['request']['body'] == BODY


def test_a_plain_json_recording_from_before_compression_still_replays(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'replay')
    gz = cassette.recording_path(os.environ['STORYFORGE_CASSETTE'],
                                 cassette.request_key('POST', 'messages', BODY))
    os.makedirs(os.path.dirname(gz))
    with open(gz[:-3], 'w') as f:
        json.dump({'request': {}, 'response': RESPONSE}, f)
    assert api._api_request('messages', BODY, method='POST') == RESPONSE
    assert live_calls == []


def test_re_recording_replaces_the_plain_original(tape, monkeypatch, live_calls):
    gz = cassette.recording_path(os.environ['STORYFORGE_CASSETTE'],
                                 cassette.request_key('POST', 'messages', BODY))
    os.makedirs(os.path.dirname(gz))
    with open(gz[:-3], 'w') as f:
        json.dump({'request': {}, 'response': {}}, f)
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    api._api_request('messages', BODY, method='POST')
    assert os.path.isfile(gz) and not os.path.exists(gz[:-3])


def test_recordings_are_byte_stable(tape, monkeypatch, live_calls):
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
    path = cassette.recording_path(os.environ['STORYFORGE_CASSETTE'],
                                   cassette.request_key('POST', 'messages', BODY))
    api._api_request('messages', BODY, method='POST')
    first = open(path, 'rb').read()
    api._api_request('messages', BODY, method='POST')
    assert open(path, 'rb').read() == first  # gzip mtime pinned: no churn on re-record


def test_a_failed_live_call_is_logged_for_the_harness(tape, monkeypatch):
    """Review of #341: command code swallows API errors into a skipped
    scene, so a live failure in record or auto mode must reach the log."""
    def failing_live(path, body, method, timeout):
        raise ConnectionError('connection reset')

    monkeypatch.setattr(api, '_live_request', failing_live)
    monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'auto')
    with pytest.raises(Exception):
        api._api_request('messages', BODY, method='POST')
    assert any('live call failed: ConnectionError' in e.get('error', '') for e in _log(tape))

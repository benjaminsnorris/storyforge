"""A long API call that times out is not retried (#627 review).

The map, briefs and revision passes wait up to an hour. A timeout there has
already waited the whole time; the old retry waited as long again, and the
server may bill both attempts."""

import pytest

from storyforge import api


@pytest.fixture
def timing_out(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(timeout)
        raise TimeoutError('timed out')
    monkeypatch.setattr(api, 'urlopen', fake_urlopen)
    monkeypatch.setattr(api.time, 'sleep', lambda s: None)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    return calls


def test_a_long_call_that_times_out_is_not_retried(timing_out):
    with pytest.raises(RuntimeError, match='timed out after 3200s; not retried'):
        api._api_request('messages', {'model': 'm'}, method='POST', timeout=3200)
    assert timing_out == [3200]


def test_a_normal_call_that_times_out_is_retried(timing_out):
    with pytest.raises(RuntimeError, match='failed after'):
        api._api_request('messages', {'model': 'm'}, method='POST', timeout=api.API_TIMEOUT)
    assert len(timing_out) == api.API_RETRIES

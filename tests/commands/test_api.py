"""Command-level tests for storyforge.api module.

Tests extract_text, extract_usage, invoke_api error handling,
invoke_to_file, extract_text_from_file, calculate_cost_from_usage,
heartbeat, get_api_key, and retry logic (mocked urllib).
"""

import json
import os
import threading

import pytest

from storyforge.api import (
    extract_text,
    extract_text_from_file,
    extract_usage,
    calculate_cost_from_usage,
    get_api_key,
    invoke_api,
    invoke_to_file,
    invoke,
    _Heartbeat,
    API_RETRIES,
    API_TIMEOUT,
    REVISION_TIMEOUT,
)


# ============================================================================
# extract_text
# ============================================================================

class TestExtractText:
    def test_single_text_block(self):
        response = {'content': [{'type': 'text', 'text': 'hello world'}]}
        assert extract_text(response) == 'hello world'

    def test_multiple_text_blocks(self):
        response = {'content': [
            {'type': 'text', 'text': 'line 1'},
            {'type': 'text', 'text': 'line 2'},
        ]}
        assert extract_text(response) == 'line 1\nline 2'

    def test_empty_content(self):
        assert extract_text({'content': []}) == ''

    def test_no_content_key(self):
        assert extract_text({}) == ''

    def test_non_text_blocks_ignored(self):
        response = {'content': [
            {'type': 'image', 'source': '...'},
            {'type': 'text', 'text': 'hello'},
        ]}
        assert extract_text(response) == 'hello'


# ============================================================================
# extract_text_from_file
# ============================================================================

class TestExtractTextFromFile:
    def test_valid_json_file(self, tmp_path):
        f = tmp_path / 'resp.json'
        f.write_text(json.dumps({
            'content': [{'type': 'text', 'text': 'from file'}],
        }))
        assert extract_text_from_file(str(f)) == 'from file'

    def test_missing_file(self, tmp_path):
        assert extract_text_from_file(str(tmp_path / 'nope.json')) == ''

    def test_invalid_json(self, tmp_path):
        f = tmp_path / 'bad.json'
        f.write_text('not json{{{')
        assert extract_text_from_file(str(f)) == ''


# ============================================================================
# extract_usage
# ============================================================================

class TestExtractUsage:
    def test_normal_usage(self):
        response = {'usage': {
            'input_tokens': 1000,
            'output_tokens': 500,
            'cache_read_input_tokens': 200,
            'cache_creation_input_tokens': 100,
        }}
        usage = extract_usage(response)
        assert usage['input_tokens'] == 1000
        assert usage['output_tokens'] == 500
        assert usage['cache_read'] == 200
        assert usage['cache_create'] == 100

    def test_missing_usage(self):
        usage = extract_usage({})
        assert usage['input_tokens'] == 0
        assert usage['output_tokens'] == 0
        assert usage['cache_read'] == 0
        assert usage['cache_create'] == 0

    def test_partial_usage(self):
        response = {'usage': {'input_tokens': 42}}
        usage = extract_usage(response)
        assert usage['input_tokens'] == 42
        assert usage['output_tokens'] == 0


# ============================================================================
# calculate_cost_from_usage
# ============================================================================

class TestCalculateCostFromUsage:
    def test_opus_cost(self):
        usage = {'input_tokens': 1_000_000, 'output_tokens': 0, 'cache_read': 0, 'cache_create': 0}
        cost = calculate_cost_from_usage(usage, 'claude-opus-4-6')
        # Opus input is $15 per million
        assert abs(cost - 15.0) < 0.01

    def test_sonnet_cost(self):
        usage = {'input_tokens': 1_000_000, 'output_tokens': 0, 'cache_read': 0, 'cache_create': 0}
        cost = calculate_cost_from_usage(usage, 'claude-sonnet-4-6')
        # Sonnet input is $3 per million
        assert abs(cost - 3.0) < 0.01

    def test_zero_tokens(self):
        usage = {'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0, 'cache_create': 0}
        cost = calculate_cost_from_usage(usage, 'claude-opus-4-6')
        assert cost == 0.0


# ============================================================================
# get_api_key
# ============================================================================

class TestGetApiKey:
    def test_key_from_env(self, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test-key')
        assert get_api_key() == 'sk-test-key'

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        with pytest.raises(RuntimeError, match='ANTHROPIC_API_KEY not set'):
            get_api_key()


# ============================================================================
# invoke_api (with mock_api fixture)
# ============================================================================

class TestInvokeApi:
    def test_returns_text(self, mock_api):
        mock_api.set_response('hello world')
        result = invoke_api('prompt', 'model')
        assert result == 'hello world'

    def test_records_calls(self, mock_api):
        mock_api.set_response('result')
        invoke_api('my prompt', 'test-model')
        assert len(mock_api.calls) >= 1
        assert mock_api.calls[0]['prompt'] == 'my prompt'

    def test_empty_on_exception(self, monkeypatch):
        """invoke_api should return '' on failure."""
        def fake_invoke(*args, **kwargs):
            raise RuntimeError('API exploded')
        monkeypatch.setattr('storyforge.api.invoke', fake_invoke)
        result = invoke_api('prompt', 'model')
        assert result == ''


# ============================================================================
# invoke_to_file (with mock_api fixture)
# ============================================================================

class TestInvokeToFile:
    def test_writes_json_file(self, mock_api, tmp_path):
        mock_api.set_response('file output')
        log_file = str(tmp_path / 'response.json')
        result = invoke_to_file('prompt', 'model', log_file)
        assert os.path.isfile(log_file)
        with open(log_file) as f:
            data = json.load(f)
        assert data['content'][0]['text'] == 'file output'

    def test_returns_response_dict(self, mock_api, tmp_path):
        mock_api.set_response('test text')
        log_file = str(tmp_path / 'resp.json')
        result = invoke_to_file('p', 'm', log_file)
        assert 'content' in result
        assert 'usage' in result


# ============================================================================
# Heartbeat
# ============================================================================

class TestHeartbeat:
    def test_start_and_stop(self):
        hb = _Heartbeat(label='test')
        hb.start()
        assert hb._thread is not None
        assert hb._thread.is_alive()
        hb.stop()
        assert not hb._thread.is_alive()

    def test_stop_is_idempotent(self):
        hb = _Heartbeat(label='test')
        hb.start()
        hb.stop()
        hb.stop()  # Should not raise


# ============================================================================
# Constants
# ============================================================================

class TestConstants:
    def test_api_timeout_reasonable(self):
        assert API_TIMEOUT >= 60  # At least 1 minute
        assert API_TIMEOUT <= 3600  # At most 1 hour

    def test_revision_timeout_larger(self):
        assert REVISION_TIMEOUT >= API_TIMEOUT

    def test_api_retries_at_least_one(self):
        assert API_RETRIES >= 1

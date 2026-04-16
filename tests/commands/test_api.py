"""Tests for storyforge.api infrastructure module.

Tests the API layer itself (invoke, extract, batch) by mocking urllib
at the transport layer. Does NOT use the mock_api fixture — that fixture
is for testing command modules that *call* the API.
"""

import io
import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_single_text_block(self):
        from storyforge.api import extract_text
        response = {
            'content': [{'type': 'text', 'text': 'Hello world'}],
        }
        assert extract_text(response) == 'Hello world'

    def test_multiple_text_blocks_joined_with_newline(self):
        from storyforge.api import extract_text
        response = {
            'content': [
                {'type': 'text', 'text': 'Part A'},
                {'type': 'text', 'text': 'Part B'},
                {'type': 'text', 'text': 'Part C'},
            ],
        }
        assert extract_text(response) == 'Part A\nPart B\nPart C'

    def test_empty_content_list(self):
        from storyforge.api import extract_text
        response = {'content': []}
        assert extract_text(response) == ''

    def test_no_text_blocks(self):
        """Content blocks exist but none are type 'text'."""
        from storyforge.api import extract_text
        response = {
            'content': [{'type': 'tool_use', 'name': 'foo', 'input': {}}],
        }
        assert extract_text(response) == ''

    def test_missing_content_key(self):
        from storyforge.api import extract_text
        response = {'usage': {'input_tokens': 10, 'output_tokens': 5}}
        assert extract_text(response) == ''

    def test_mixed_block_types(self):
        """Only text blocks are extracted, others ignored."""
        from storyforge.api import extract_text
        response = {
            'content': [
                {'type': 'text', 'text': 'prose'},
                {'type': 'tool_use', 'name': 'foo', 'input': {}},
                {'type': 'text', 'text': 'more prose'},
            ],
        }
        assert extract_text(response) == 'prose\nmore prose'

    def test_text_block_with_empty_string(self):
        from storyforge.api import extract_text
        response = {
            'content': [{'type': 'text', 'text': ''}],
        }
        assert extract_text(response) == ''


# ---------------------------------------------------------------------------
# extract_text_from_file
# ---------------------------------------------------------------------------

class TestExtractTextFromFile:
    def test_reads_valid_json(self, tmp_path):
        from storyforge.api import extract_text_from_file
        f = tmp_path / 'response.json'
        f.write_text(json.dumps({
            'content': [{'type': 'text', 'text': 'Hello from file'}],
        }))
        assert extract_text_from_file(str(f)) == 'Hello from file'

    def test_returns_empty_for_missing_file(self, tmp_path):
        from storyforge.api import extract_text_from_file
        result = extract_text_from_file(str(tmp_path / 'nonexistent.json'))
        assert result == ''

    def test_handles_malformed_json(self, tmp_path):
        from storyforge.api import extract_text_from_file
        f = tmp_path / 'bad.json'
        f.write_text('not valid json {{{')
        assert extract_text_from_file(str(f)) == ''

    def test_multi_block_from_file(self, tmp_path):
        from storyforge.api import extract_text_from_file
        f = tmp_path / 'multi.json'
        f.write_text(json.dumps({
            'content': [
                {'type': 'text', 'text': 'First'},
                {'type': 'text', 'text': 'Second'},
            ],
        }))
        result = extract_text_from_file(str(f))
        assert 'First' in result
        assert 'Second' in result


# ---------------------------------------------------------------------------
# extract_usage
# ---------------------------------------------------------------------------

class TestExtractUsage:
    def test_all_fields(self):
        from storyforge.api import extract_usage
        response = {
            'usage': {
                'input_tokens': 200,
                'output_tokens': 100,
                'cache_read_input_tokens': 50,
                'cache_creation_input_tokens': 25,
            },
        }
        u = extract_usage(response)
        assert u['input_tokens'] == 200
        assert u['output_tokens'] == 100
        assert u['cache_read'] == 50
        assert u['cache_create'] == 25

    def test_defaults_to_zero(self):
        from storyforge.api import extract_usage
        response = {'usage': {}}
        u = extract_usage(response)
        assert u['input_tokens'] == 0
        assert u['output_tokens'] == 0
        assert u['cache_read'] == 0
        assert u['cache_create'] == 0

    def test_missing_usage_key(self):
        from storyforge.api import extract_usage
        response = {}
        u = extract_usage(response)
        assert u['input_tokens'] == 0


# ---------------------------------------------------------------------------
# max_output_tokens
# ---------------------------------------------------------------------------

class TestMaxOutputTokens:
    def test_known_model(self):
        from storyforge.api import max_output_tokens
        assert max_output_tokens('claude-opus-4-6') == 128000

    def test_unknown_model_returns_default(self):
        from storyforge.api import max_output_tokens, _DEFAULT_MAX_OUTPUT
        assert max_output_tokens('claude-unknown-99') == _DEFAULT_MAX_OUTPUT


# ---------------------------------------------------------------------------
# invoke (mocking _api_request)
# ---------------------------------------------------------------------------

class TestInvoke:
    def test_constructs_correct_body(self, monkeypatch):
        from storyforge import api

        captured = {}

        def mock_api_request(path, body=None, method='GET', timeout=600):
            captured['path'] = path
            captured['body'] = body
            captured['method'] = method
            return {
                'content': [{'type': 'text', 'text': 'response'}],
                'usage': {'input_tokens': 10, 'output_tokens': 5},
            }

        monkeypatch.setattr(api, '_api_request', mock_api_request)

        result = api.invoke('Hello', 'claude-sonnet-4-6', max_tokens=2048)

        assert captured['path'] == 'messages'
        assert captured['method'] == 'POST'
        assert captured['body']['model'] == 'claude-sonnet-4-6'
        assert captured['body']['max_tokens'] == 2048
        assert captured['body']['messages'] == [{'role': 'user', 'content': 'Hello'}]
        assert result['content'][0]['text'] == 'response'

    def test_passes_timeout_to_api_request(self, monkeypatch):
        from storyforge import api

        captured = {}

        def mock_api_request(path, body=None, method='GET', timeout=600):
            captured['timeout'] = timeout
            return {'content': [], 'usage': {}}

        monkeypatch.setattr(api, '_api_request', mock_api_request)
        api.invoke('test', 'claude-sonnet-4-6', timeout=1200)
        assert captured['timeout'] == 1200

    def test_propagates_runtime_error(self, monkeypatch):
        from storyforge import api

        def mock_api_request(path, body=None, method='GET', timeout=600):
            raise RuntimeError('API returned HTTP 500: server error')

        monkeypatch.setattr(api, '_api_request', mock_api_request)

        with pytest.raises(RuntimeError, match='HTTP 500'):
            api.invoke('test', 'claude-sonnet-4-6')


# ---------------------------------------------------------------------------
# invoke_api (convenience wrapper)
# ---------------------------------------------------------------------------

class TestInvokeApi:
    def test_returns_text_on_success(self, monkeypatch):
        from storyforge import api

        def mock_invoke(prompt, model, max_tokens=4096, label='', timeout=600, system=None):
            return {
                'content': [{'type': 'text', 'text': 'Success text'}],
                'usage': {'input_tokens': 10, 'output_tokens': 5},
            }

        monkeypatch.setattr(api, 'invoke', mock_invoke)
        result = api.invoke_api('test prompt', 'claude-sonnet-4-6')
        assert result == 'Success text'

    def test_returns_empty_string_on_failure(self, monkeypatch):
        from storyforge import api

        def mock_invoke(prompt, model, max_tokens=4096, label='', timeout=600, system=None):
            raise RuntimeError('network down')

        monkeypatch.setattr(api, 'invoke', mock_invoke)
        result = api.invoke_api('test prompt', 'claude-sonnet-4-6')
        assert result == ''

    def test_passes_label_and_timeout(self, monkeypatch):
        from storyforge import api

        captured = {}

        def mock_invoke(prompt, model, max_tokens=4096, label='', timeout=600, system=None):
            captured['label'] = label
            captured['timeout'] = timeout
            return {'content': [{'type': 'text', 'text': 'ok'}], 'usage': {}}

        monkeypatch.setattr(api, 'invoke', mock_invoke)
        api.invoke_api('test', 'claude-sonnet-4-6', label='scoring', timeout=1800)
        assert captured['label'] == 'scoring'
        assert captured['timeout'] == 1800


# ---------------------------------------------------------------------------
# invoke_to_file
# ---------------------------------------------------------------------------

class TestInvokeToFile:
    def test_writes_response_to_file(self, tmp_path, monkeypatch):
        from storyforge import api

        fake_response = {
            'content': [{'type': 'text', 'text': 'file output'}],
            'usage': {'input_tokens': 10, 'output_tokens': 5},
        }

        def mock_invoke(prompt, model, max_tokens=4096, label='', timeout=600, system=None):
            return fake_response

        monkeypatch.setattr(api, 'invoke', mock_invoke)

        log_file = str(tmp_path / 'output.json')
        result = api.invoke_to_file('prompt', 'claude-sonnet-4-6', log_file)

        assert result == fake_response
        assert os.path.isfile(log_file)
        with open(log_file) as f:
            written = json.load(f)
        assert written['content'][0]['text'] == 'file output'

    def test_creates_parent_directories(self, tmp_path, monkeypatch):
        from storyforge import api

        def mock_invoke(prompt, model, max_tokens=4096, label='', timeout=600, system=None):
            return {'content': [], 'usage': {}}

        monkeypatch.setattr(api, 'invoke', mock_invoke)

        log_file = str(tmp_path / 'deep' / 'nested' / 'dir' / 'output.json')
        api.invoke_to_file('prompt', 'claude-sonnet-4-6', log_file)
        assert os.path.isfile(log_file)

    def test_returns_response_dict(self, tmp_path, monkeypatch):
        from storyforge import api

        expected = {
            'content': [{'type': 'text', 'text': 'hello'}],
            'usage': {'input_tokens': 5, 'output_tokens': 3},
        }

        def mock_invoke(prompt, model, max_tokens=4096, label='', timeout=600, system=None):
            return expected

        monkeypatch.setattr(api, 'invoke', mock_invoke)

        result = api.invoke_to_file('p', 'm', str(tmp_path / 'out.json'))
        assert result == expected


# ---------------------------------------------------------------------------
# _api_request (mocking urlopen)
# ---------------------------------------------------------------------------

class TestApiRequest:
    def test_successful_request(self, monkeypatch):
        from storyforge import api

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key-123')

        response_data = {'id': 'msg_1', 'content': [{'type': 'text', 'text': 'hi'}]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('storyforge.api.urlopen', return_value=mock_resp) as mock_url:
            result = api._api_request('messages', {'model': 'test'}, method='POST')

        assert result == response_data
        call_args = mock_url.call_args
        req = call_args[0][0]
        assert req.full_url == f'{api.API_BASE}/messages'
        assert req.get_header('X-api-key') == 'test-key-123'
        assert req.get_header('Anthropic-version') == api.API_VERSION

    def test_retries_on_500(self, monkeypatch):
        from storyforge import api
        from urllib.error import HTTPError

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        # Patch time.sleep to avoid delays in tests
        monkeypatch.setattr('storyforge.api.time.sleep', lambda _: None)

        success_resp = MagicMock()
        success_resp.read.return_value = json.dumps({'ok': True}).encode()
        success_resp.__enter__ = MagicMock(return_value=success_resp)
        success_resp.__exit__ = MagicMock(return_value=False)

        error = HTTPError(
            'http://example.com', 500, 'Server Error',
            {}, io.BytesIO(b'internal error'),
        )

        call_count = {'n': 0}

        def mock_urlopen(req, timeout=None):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise error
            return success_resp

        with patch('storyforge.api.urlopen', side_effect=mock_urlopen):
            result = api._api_request('messages')

        assert result == {'ok': True}
        assert call_count['n'] == 2

    def test_raises_on_4xx_without_retry(self, monkeypatch):
        from storyforge import api
        from urllib.error import HTTPError

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        error = HTTPError(
            'http://example.com', 400, 'Bad Request',
            {}, io.BytesIO(b'invalid request'),
        )

        with patch('storyforge.api.urlopen', side_effect=error):
            with pytest.raises(RuntimeError, match='HTTP 400'):
                api._api_request('messages')

    def test_raises_on_connection_error_after_retries(self, monkeypatch):
        from storyforge import api
        from urllib.error import URLError

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.api.time.sleep', lambda _: None)

        error = URLError('Connection refused')

        with patch('storyforge.api.urlopen', side_effect=error):
            with pytest.raises(RuntimeError, match='failed after'):
                api._api_request('messages')

    def test_timeout_error_retries(self, monkeypatch):
        from storyforge import api

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.api.time.sleep', lambda _: None)

        success_resp = MagicMock()
        success_resp.read.return_value = json.dumps({'ok': True}).encode()
        success_resp.__enter__ = MagicMock(return_value=success_resp)
        success_resp.__exit__ = MagicMock(return_value=False)

        call_count = {'n': 0}

        def mock_urlopen(req, timeout=None):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise TimeoutError('timed out')
            return success_resp

        with patch('storyforge.api.urlopen', side_effect=mock_urlopen):
            result = api._api_request('messages')

        assert result == {'ok': True}
        assert call_count['n'] == 2


# ---------------------------------------------------------------------------
# get_api_key
# ---------------------------------------------------------------------------

class TestGetApiKey:
    def test_returns_key_from_env(self, monkeypatch):
        from storyforge.api import get_api_key
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test-key')
        assert get_api_key() == 'sk-test-key'

    def test_raises_when_not_set(self, monkeypatch):
        from storyforge.api import get_api_key
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        with pytest.raises(RuntimeError, match='ANTHROPIC_API_KEY not set'):
            get_api_key()


# ---------------------------------------------------------------------------
# Batch API: submit_batch
# ---------------------------------------------------------------------------

class TestSubmitBatch:
    def test_returns_batch_id(self, tmp_path, monkeypatch):
        from storyforge import api

        # Write a JSONL batch file
        batch_file = str(tmp_path / 'batch.jsonl')
        with open(batch_file, 'w') as f:
            f.write(json.dumps({'custom_id': 'req-1', 'params': {'model': 'test'}}) + '\n')
            f.write(json.dumps({'custom_id': 'req-2', 'params': {'model': 'test'}}) + '\n')

        def mock_api_request(path, body=None, method='GET', timeout=600):
            assert path == 'messages/batches'
            assert method == 'POST'
            assert len(body['requests']) == 2
            return {'id': 'batch_abc123'}

        monkeypatch.setattr(api, '_api_request', mock_api_request)
        batch_id = api.submit_batch(batch_file)
        assert batch_id == 'batch_abc123'

    def test_raises_when_no_id_returned(self, tmp_path, monkeypatch):
        from storyforge import api

        batch_file = str(tmp_path / 'batch.jsonl')
        with open(batch_file, 'w') as f:
            f.write(json.dumps({'custom_id': 'req-1'}) + '\n')

        def mock_api_request(path, body=None, method='GET', timeout=600):
            return {'error': 'something went wrong'}

        monkeypatch.setattr(api, '_api_request', mock_api_request)
        with pytest.raises(RuntimeError, match='No batch ID returned'):
            api.submit_batch(batch_file)

    def test_skips_blank_lines(self, tmp_path, monkeypatch):
        from storyforge import api

        batch_file = str(tmp_path / 'batch.jsonl')
        with open(batch_file, 'w') as f:
            f.write(json.dumps({'custom_id': 'req-1'}) + '\n')
            f.write('\n')  # blank line
            f.write(json.dumps({'custom_id': 'req-2'}) + '\n')

        captured = {}

        def mock_api_request(path, body=None, method='GET', timeout=600):
            captured['count'] = len(body['requests'])
            return {'id': 'batch_xyz'}

        monkeypatch.setattr(api, '_api_request', mock_api_request)
        api.submit_batch(batch_file)
        assert captured['count'] == 2


# ---------------------------------------------------------------------------
# Batch API: poll_batch
# ---------------------------------------------------------------------------

class TestPollBatch:
    def test_returns_results_url_when_ended(self, monkeypatch):
        from storyforge import api

        monkeypatch.setattr('storyforge.api.time.sleep', lambda _: None)

        call_count = {'n': 0}

        def mock_api_request(path, body=None, method='GET', timeout=600):
            call_count['n'] += 1
            if call_count['n'] == 1:
                return {
                    'processing_status': 'in_progress',
                    'request_counts': {'succeeded': 0, 'errored': 0},
                }
            return {
                'processing_status': 'ended',
                'request_counts': {'succeeded': 5, 'errored': 0},
                'results_url': 'https://api.anthropic.com/results/batch_123',
            }

        monkeypatch.setattr(api, '_api_request', mock_api_request)
        url = api.poll_batch('batch_123')
        assert url == 'https://api.anthropic.com/results/batch_123'
        assert call_count['n'] == 2

    def test_calls_log_fn(self, monkeypatch):
        from storyforge import api

        monkeypatch.setattr('storyforge.api.time.sleep', lambda _: None)

        logged = []

        def mock_api_request(path, body=None, method='GET', timeout=600):
            return {
                'processing_status': 'ended',
                'request_counts': {'succeeded': 3, 'errored': 0},
                'results_url': 'https://example.com/results',
            }

        monkeypatch.setattr(api, '_api_request', mock_api_request)
        api.poll_batch('batch_abc', log_fn=logged.append)
        assert len(logged) == 1
        assert 'ended' in logged[0]


# ---------------------------------------------------------------------------
# Batch API: download_batch_results
# ---------------------------------------------------------------------------

class TestDownloadBatchResults:
    def test_processes_succeeded_items(self, tmp_path, monkeypatch):
        from storyforge import api

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        output_dir = str(tmp_path / 'output')
        log_dir = str(tmp_path / 'logs')

        # Build a fake JSONL response
        lines = [
            json.dumps({
                'custom_id': 'scene-alpha',
                'result': {
                    'type': 'succeeded',
                    'message': {
                        'content': [{'type': 'text', 'text': 'Alpha prose'}],
                        'usage': {'input_tokens': 100, 'output_tokens': 50},
                    },
                },
            }),
            json.dumps({
                'custom_id': 'scene-beta',
                'result': {
                    'type': 'errored',
                    'error': {'message': 'overloaded'},
                },
            }),
        ]
        body = '\n'.join(lines).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('storyforge.api.urlopen', return_value=mock_resp):
            succeeded = api.download_batch_results('https://example.com/results', output_dir, log_dir)

        assert succeeded == ['scene-alpha']

        # Check status files
        assert open(os.path.join(output_dir, '.status-scene-alpha')).read() == 'ok'
        assert open(os.path.join(output_dir, '.status-scene-beta')).read() == 'fail'

        # Check text output
        assert open(os.path.join(log_dir, 'scene-alpha.txt')).read() == 'Alpha prose'

        # Check JSON log
        with open(os.path.join(log_dir, 'scene-alpha.json')) as f:
            data = json.load(f)
        assert data['usage']['input_tokens'] == 100

    def test_creates_output_directories(self, tmp_path, monkeypatch):
        from storyforge import api

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        output_dir = str(tmp_path / 'a' / 'b' / 'output')
        log_dir = str(tmp_path / 'c' / 'd' / 'logs')

        mock_resp = MagicMock()
        mock_resp.read.return_value = b''
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('storyforge.api.urlopen', return_value=mock_resp):
            succeeded = api.download_batch_results('https://example.com/r', output_dir, log_dir)

        assert succeeded == []
        assert os.path.isdir(output_dir)
        assert os.path.isdir(log_dir)

    def test_skips_malformed_lines(self, tmp_path, monkeypatch):
        from storyforge import api

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        output_dir = str(tmp_path / 'output')
        log_dir = str(tmp_path / 'logs')

        lines = [
            'not json at all',
            '',
            json.dumps({
                'custom_id': 'good-one',
                'result': {
                    'type': 'succeeded',
                    'message': {
                        'content': [{'type': 'text', 'text': 'Good'}],
                        'usage': {'input_tokens': 10, 'output_tokens': 5},
                    },
                },
            }),
        ]
        body = '\n'.join(lines).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('storyforge.api.urlopen', return_value=mock_resp):
            succeeded = api.download_batch_results('https://example.com/r', output_dir, log_dir)

        assert succeeded == ['good-one']


# ---------------------------------------------------------------------------
# extract_response (alias)
# ---------------------------------------------------------------------------

class TestExtractResponse:
    def test_is_alias_for_extract_text_from_file(self, tmp_path):
        from storyforge.api import extract_response
        f = tmp_path / 'resp.json'
        f.write_text(json.dumps({
            'content': [{'type': 'text', 'text': 'alias test'}],
        }))
        assert extract_response(str(f)) == 'alias test'


# ---------------------------------------------------------------------------
# calculate_cost_from_usage
# ---------------------------------------------------------------------------

class TestCalculateCostFromUsage:
    def test_returns_float(self):
        from storyforge.api import calculate_cost_from_usage
        usage = {
            'input_tokens': 1000,
            'output_tokens': 500,
            'cache_read': 0,
            'cache_create': 0,
        }
        cost = calculate_cost_from_usage(usage, 'claude-sonnet-4-6')
        assert isinstance(cost, float)
        assert cost > 0

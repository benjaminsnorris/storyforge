"""Tests for API helper functions (migrated from test-api.sh)."""

import json
import os
from unittest.mock import patch, MagicMock


class TestExtractApiResponse:
    def test_extracts_text(self, tmp_path):
        from storyforge.api import extract_text_from_file
        f = str(tmp_path / 'response.json')
        with open(f, 'w') as fp:
            json.dump({
                'content': [{'type': 'text', 'text': 'Hello world'}],
                'usage': {'input_tokens': 10, 'output_tokens': 5}
            }, fp)
        assert extract_text_from_file(f) == 'Hello world'

    def test_multi_block(self, tmp_path):
        from storyforge.api import extract_text_from_file
        f = str(tmp_path / 'multi.json')
        with open(f, 'w') as fp:
            json.dump({
                'content': [
                    {'type': 'text', 'text': 'Part 1'},
                    {'type': 'text', 'text': 'Part 2'}
                ],
                'usage': {'input_tokens': 10, 'output_tokens': 5}
            }, fp)
        result = extract_text_from_file(f)
        assert 'Part 1' in result
        assert 'Part 2' in result

    def test_missing_file(self, tmp_path):
        from storyforge.api import extract_text_from_file
        # Missing file returns empty/None rather than raising
        result = extract_text_from_file(str(tmp_path / 'nonexistent.json'))
        assert not result


class TestExtractApiUsage:
    def test_all_fields(self):
        from storyforge.api import extract_usage
        response = {
            'content': [{'type': 'text', 'text': 'test'}],
            'usage': {
                'input_tokens': 100, 'output_tokens': 50,
                'cache_read_input_tokens': 25, 'cache_creation_input_tokens': 10
            }
        }
        result = extract_usage(response)
        assert result['input_tokens'] == 100
        assert result['output_tokens'] == 50

    def test_missing_cache_defaults(self):
        from storyforge.api import extract_usage
        response = {
            'content': [{'type': 'text', 'text': 'test'}],
            'usage': {'input_tokens': 100, 'output_tokens': 50}
        }
        result = extract_usage(response)
        assert result.get('cache_read_input_tokens', 0) == 0
        assert result.get('cache_creation_input_tokens', 0) == 0


class TestInvokeSystemParam:
    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_invoke_without_system_omits_key(self, mock_key, mock_req):
        from storyforge.api import invoke
        mock_req.return_value = {
            'content': [{'type': 'text', 'text': 'ok'}],
            'usage': {'input_tokens': 10, 'output_tokens': 5},
        }
        invoke('hello', 'claude-sonnet-4-6', max_tokens=100)
        body = mock_req.call_args[0][1]
        assert 'system' not in body
        assert body['messages'] == [{'role': 'user', 'content': 'hello'}]

    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_invoke_with_system_includes_key(self, mock_key, mock_req):
        from storyforge.api import invoke
        mock_req.return_value = {
            'content': [{'type': 'text', 'text': 'ok'}],
            'usage': {'input_tokens': 10, 'output_tokens': 5},
        }
        system_blocks = [
            {'type': 'text', 'text': 'You are helpful.'},
            {'type': 'text', 'text': 'Reference material here.',
             'cache_control': {'type': 'ephemeral'}},
        ]
        invoke('hello', 'claude-sonnet-4-6', max_tokens=100, system=system_blocks)
        body = mock_req.call_args[0][1]
        assert body['system'] == system_blocks
        assert body['messages'] == [{'role': 'user', 'content': 'hello'}]


class TestInvokeOutputSchema:
    SCHEMA = {'type': 'object', 'properties': {'a': {'type': 'string'}},
              'required': ['a'], 'additionalProperties': False}

    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_schema_becomes_output_config_format(self, mock_key, mock_req, tmp_path):
        from storyforge.api import invoke, invoke_to_file
        mock_req.return_value = {'content': [{'type': 'text', 'text': '{"a": "x"}'}],
                                 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        invoke('hello', 'claude-sonnet-5-5', max_tokens=100, output_schema=self.SCHEMA)
        assert mock_req.call_args[0][1]['output_config'] == {
            'format': {'type': 'json_schema', 'schema': self.SCHEMA}}
        invoke_to_file('hello', 'claude-sonnet-5-5', str(tmp_path / 'r.json'),
                       output_schema=self.SCHEMA)
        assert mock_req.call_args[0][1]['output_config']['format']['schema'] == self.SCHEMA

    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_no_schema_sends_no_output_config(self, mock_key, mock_req):
        from storyforge.api import invoke
        mock_req.return_value = {'content': [{'type': 'text', 'text': 'ok'}],
                                 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        invoke('hello', 'claude-sonnet-5-5', max_tokens=100)
        assert 'output_config' not in mock_req.call_args[0][1]


class TestInvokeApiConsecutiveFailures:
    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_single_failure_returns_empty(self, mock_key, mock_req):
        import storyforge.api as api_mod
        api_mod._invoke_api_consecutive_failures = 0
        mock_req.side_effect = RuntimeError('API error')
        result = api_mod.invoke_api('hello', 'claude-sonnet-4-6')
        assert result == ''

    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_consecutive_failures_raise(self, mock_key, mock_req):
        import storyforge.api as api_mod
        api_mod._invoke_api_consecutive_failures = 0
        mock_req.side_effect = RuntimeError('API error')
        for _ in range(4):
            result = api_mod.invoke_api('hello', 'claude-sonnet-4-6')
            assert result == ''
        # 5th consecutive failure should raise
        import pytest
        with pytest.raises(RuntimeError, match='consecutively'):
            api_mod.invoke_api('hello', 'claude-sonnet-4-6')

    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_success_resets_counter(self, mock_key, mock_req):
        import storyforge.api as api_mod
        api_mod._invoke_api_consecutive_failures = 0
        # Fail 3 times, succeed, fail 3 more — should NOT raise
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 4:  # 4th call succeeds
                return {'content': [{'type': 'text', 'text': 'ok'}],
                        'usage': {'input_tokens': 10, 'output_tokens': 5}}
            raise RuntimeError('API error')
        mock_req.side_effect = side_effect
        for _ in range(3):
            api_mod.invoke_api('hello', 'claude-sonnet-4-6')
        result = api_mod.invoke_api('hello', 'claude-sonnet-4-6')
        assert result == 'ok'
        assert api_mod._invoke_api_consecutive_failures == 0
        # 3 more failures should not raise (counter was reset)
        mock_req.side_effect = RuntimeError('API error')
        for _ in range(3):
            api_mod.invoke_api('hello', 'claude-sonnet-4-6')


class TestLogApiUsage:
    def test_creates_ledger(self, tmp_path):
        from storyforge.api import log_operation, calculate_cost_from_usage
        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working', 'costs'))

        usage = {'input_tokens': 1000, 'output_tokens': 500,
                 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        cost = calculate_cost_from_usage(usage, 'claude-sonnet-4-6')
        log_operation(
            project_dir=project_dir,
            operation='test-op',
            model='claude-sonnet-4-6',
            input_tokens=1000,
            output_tokens=500,
            cost=cost,
            target='test-target',
        )

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        assert os.path.isfile(ledger)

        with open(ledger) as fp:
            lines = fp.readlines()
        assert len(lines) == 2
        assert 'test-op' in lines[-1]
        assert 'claude-sonnet-4-6' in lines[-1]
        assert '1000' in lines[-1]


class TestRefusal:
    """A refusal's text is empty or cut off, never an answer (Sonnet 5.5
    refused every timeline batch on Pride and Prejudice, category
    reasoning_extraction, and the empty text was read as no calendar)."""

    REFUSAL = {'stop_reason': 'refusal', 'content': [],
               'stop_details': {'type': 'refusal', 'category': 'reasoning_extraction'}}

    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_invoke_raises(self, mock_key, mock_req):
        import pytest
        from storyforge.api import invoke, RefusalError
        mock_req.return_value = self.REFUSAL
        with pytest.raises(RefusalError, match='reasoning_extraction'):
            invoke('p', 'claude-sonnet-5-5')

    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_invoke_to_file_logs_then_raises(self, mock_key, mock_req, tmp_path):
        import json
        import pytest
        from storyforge.api import invoke_to_file, RefusalError
        mock_req.return_value = self.REFUSAL
        log = tmp_path / 'r.json'
        with pytest.raises(RefusalError):
            invoke_to_file('p', 'claude-sonnet-5-5', str(log))
        assert json.loads(log.read_text())['stop_reason'] == 'refusal'

    @patch('storyforge.api._api_request')
    @patch('storyforge.api.get_api_key', return_value='test-key')
    def test_normal_reply_returned(self, mock_key, mock_req):
        from storyforge.api import invoke
        mock_req.return_value = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'ok'}]}
        assert invoke('p', 'm')['stop_reason'] == 'end_turn'


class TestRefusalFallback:
    """Prose calls opt into the server-side refusal fallback (Ben, 2026-10-29):
    a false-positive refusal should not leave a scene undrafted, and a reply
    another model wrote is named in a WARNING."""

    SERVED = {'model': 'claude-opus-5', 'stop_reason': 'end_turn',
              'content': [{'type': 'text', 'text': 'prose'}],
              'usage': {'input_tokens': 1, 'output_tokens': 1,
                        'iterations': [{'type': 'message', 'model': None},
                                       {'type': 'fallback_message', 'model': 'claude-opus-5'}]}}

    @patch('storyforge.api._api_request')
    def test_opt_in_sends_the_parameter_and_beta(self, mock_req):
        from storyforge.api import invoke, FALLBACK_BETA
        mock_req.return_value = {'stop_reason': 'end_turn', 'content': []}
        invoke('p', 'claude-opus-5-5', fallback=True)
        assert mock_req.call_args[0][1]['fallbacks'] == 'default'
        assert mock_req.call_args[1]['betas'] == [FALLBACK_BETA]

    @patch('storyforge.api._api_request')
    def test_off_by_default(self, mock_req):
        from storyforge.api import invoke
        mock_req.return_value = {'stop_reason': 'end_turn', 'content': []}
        invoke('p', 'claude-opus-5-5')
        assert 'fallbacks' not in mock_req.call_args[0][1]
        assert 'betas' not in mock_req.call_args[1]

    def test_beta_becomes_a_header(self, monkeypatch):
        from storyforge import api
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'k')
        sent = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{}'

        def fake_urlopen(req, timeout):
            sent.update({k.lower(): v for k, v in req.header_items()})
            return Resp()
        monkeypatch.setattr(api, 'urlopen', fake_urlopen)
        api._live_request('messages', {}, 'POST', 5, betas=['a', 'b'])
        assert sent['anthropic-beta'] == 'a,b'

    def test_fallback_model(self):
        from storyforge.api import fallback_model
        assert fallback_model(self.SERVED) == 'claude-opus-5'
        assert fallback_model({'model': 'claude-opus-5-5', 'stop_reason': 'end_turn',
                               'usage': {'iterations': [{'type': 'message'}]}}) == ''
        refused = dict(self.SERVED, stop_reason='refusal')
        assert fallback_model(refused) == ''  # the fallback refused too
        assert fallback_model(None) == ''

    @patch('storyforge.api._api_request')
    def test_served_reply_warns_naming_label_and_model(self, mock_req, capsys):
        from storyforge.api import invoke
        mock_req.return_value = self.SERVED
        invoke('p', 'claude-opus-5-5', label='drafting waking-hank', fallback=True)
        out = capsys.readouterr()
        text = out.out + out.err
        assert 'WARNING' in text and 'drafting waking-hank' in text
        assert 'claude-opus-5 wrote this reply' in text

    def test_text_after_the_fallback_block_only(self):
        from storyforge.api import extract_text
        response = {'content': [
            {'type': 'text', 'text': 'partial from the refused model'},
            {'type': 'fallback', 'from': {'model': 'a'}, 'to': {'model': 'b'}},
            {'type': 'text', 'text': 'the reply'}]}
        assert extract_text(response) == 'the reply'

    def test_cassette_key_ignores_the_fallback(self):
        """Recordings made without it still replay; evals measure the
        requested model."""
        from storyforge.cassette import request_key
        body = {'model': 'm', 'messages': []}
        assert request_key('POST', 'messages', dict(body, fallbacks='default')) == \
            request_key('POST', 'messages', body)

"""Tests for API helper functions (migrated from test-api.sh)."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest


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
    PLAIN = {'model': 'claude-opus-5-5', 'stop_reason': 'end_turn',
             'content': [{'type': 'text', 'text': 'prose'}], 'usage': {}}

    @pytest.mark.parametrize('call', [
        lambda tmp: __import__('storyforge.api').api.invoke('p', 'm', fallback=True),
        lambda tmp: __import__('storyforge.api').api.invoke_to_file(
            'p', 'm', str(tmp / 'r.json'), fallback=True),
        lambda tmp: __import__('storyforge.api').api.invoke_api('p', 'm', fallback=True),
    ], ids=['invoke', 'invoke_to_file', 'invoke_api'])
    @patch('storyforge.api._api_request')
    def test_opt_in_reaches_the_request(self, mock_req, call, tmp_path):
        mock_req.return_value = self.PLAIN
        call(tmp_path)
        assert mock_req.call_args[0][1]['fallbacks'] == 'default'

    @patch('storyforge.api._api_request')
    def test_off_by_default(self, mock_req):
        from storyforge.api import invoke
        mock_req.return_value = self.PLAIN
        invoke('p', 'claude-opus-5-5')
        assert 'fallbacks' not in mock_req.call_args[0][1]

    def _sent_headers(self, monkeypatch, body):
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
        api._live_request('messages', body, 'POST', 5)
        return sent

    def test_the_body_turns_on_the_beta_header(self, monkeypatch):
        from storyforge.api import FALLBACK_BETA
        assert self._sent_headers(monkeypatch, {'fallbacks': 'default'})[
            'anthropic-beta'] == FALLBACK_BETA
        assert 'anthropic-beta' not in self._sent_headers(monkeypatch, {'model': 'm'})

    def test_cassette_strips_the_fallback(self, monkeypatch, tmp_path):
        """A recording is always the requested model's reply, so evals
        measure that model, and older recordings still replay."""
        from storyforge import api
        monkeypatch.setenv('STORYFORGE_CASSETTE', str(tmp_path))
        monkeypatch.setenv('STORYFORGE_CASSETTE_MODE', 'record')
        sent = []
        monkeypatch.setattr(api, '_live_request',
                            lambda path, body, method, timeout: sent.append(body) or self.PLAIN)
        api.invoke('p', 'claude-opus-5-5', fallback=True)
        assert sent and 'fallbacks' not in sent[0]

    def test_fallback_model(self):
        from storyforge.api import fallback_model
        assert fallback_model(self.SERVED) == 'claude-opus-5'
        assert fallback_model({'model': 'claude-opus-5-5', 'stop_reason': 'end_turn',
                               'usage': {'iterations': [{'type': 'message'}]}}) == ''
        refused = dict(self.SERVED, stop_reason='refusal')
        assert fallback_model(refused) == ''  # the fallback refused too
        nameless = {k: v for k, v in self.SERVED.items() if k != 'model'}
        assert fallback_model(nameless) == ''  # never a placeholder priced as a model
        assert fallback_model(None) == ''

    @patch('storyforge.api._api_request')
    def test_served_reply_warns_naming_label_and_model(self, mock_req, capsys):
        from storyforge.api import invoke
        mock_req.return_value = self.SERVED
        invoke('p', 'claude-opus-5-5', label='drafting waking-hank', fallback=True)
        out = capsys.readouterr()
        text = out.out + out.err
        assert 'WARNING: claude-opus-5 wrote the reply to drafting waking-hank' in text
        assert 'in place of claude-opus-5-5' in text

    @pytest.mark.parametrize('reply', ['plain', 'refused'])
    @patch('storyforge.api._api_request')
    def test_no_warning_unless_a_fallback_wrote_it(self, mock_req, reply, capsys):
        from storyforge.api import invoke, RefusalError
        mock_req.return_value = (self.PLAIN if reply == 'plain'
                                 else dict(self.SERVED, stop_reason='refusal', content=[]))
        try:
            invoke('p', 'claude-opus-5-5', label='x', fallback=True)
        except RefusalError:
            pass
        out = capsys.readouterr()
        assert 'WARNING' not in out.out + out.err

    def test_refusal_names_the_recommended_retry(self):
        """The fallback could not run (e.g. rate-limited): say a retry may
        work, unlike a second refusal."""
        from storyforge.api import RefusalError
        e = RefusalError({'stop_reason': 'refusal', 'stop_details': {
            'category': 'cyber', 'recommended_model': 'claude-opus-4-8'}})
        assert 'cyber' in str(e) and 'retrying on claude-opus-4-8' in str(e)
        assert 'retrying' not in str(RefusalError({'stop_details': {'category': 'cyber'}}))

    FALLBACK_CONTENT = {'content': [
        {'type': 'text', 'text': '=== SCENE: a ===\npartial\n=== END SCENE: a ==='},
        {'type': 'fallback', 'from': {'model': 'x'}, 'to': {'model': 'y'}},
        {'type': 'text', 'text': 'the reply'}]}

    def test_text_after_the_fallback_block_only(self, tmp_path):
        """api.extract_text and parsing.extract_api_response (which revise
        passes read) agree."""
        from storyforge.api import extract_text
        from storyforge.parsing import extract_api_response
        log = tmp_path / 'r.json'
        log.write_text(json.dumps(self.FALLBACK_CONTENT))
        assert extract_text(self.FALLBACK_CONTENT) == 'the reply'
        assert extract_api_response(str(log)) == 'the reply'
        assert extract_text({'content': self.FALLBACK_CONTENT['content'][:2]}) == ''


class TestFallbackRecord:
    """H1: every reply the fallback wrote is kept for the end-of-run summary
    and commit messages."""

    @patch('storyforge.api._api_request')
    def test_recorded_noted_and_reported(self, mock_req, capsys):
        from storyforge import api
        mock_req.return_value = TestRefusalFallback.SERVED
        assert api.fallback_note() == ''
        api.invoke('p', 'claude-opus-5-5', label='redraft a', fallback=True)
        assert api.fallback_replies() == [('redraft a', 'claude-opus-5-5', 'claude-opus-5')]
        assert api.fallback_note() == ' (refusal fallback: written by claude-opus-5)'
        assert api.fallback_note(since=1) == ''
        capsys.readouterr()
        api.report_fallback_replies()
        out = capsys.readouterr()
        assert 'redraft a: claude-opus-5 in place of claude-opus-5-5' in out.out + out.err

    def test_silent_without_fallback_replies(self, capsys):
        from storyforge import api
        api.report_fallback_replies()
        out = capsys.readouterr()
        assert out.out + out.err == ''


class TestConverse:
    """api.converse: the tool-use loop the gate's checker runs on."""
    TOOLS = [{'name': 'lookup', 'description': 'Look a word up.',
              'input_schema': {'type': 'object', 'properties': {'word': {'type': 'string'}},
                               'required': ['word'], 'additionalProperties': False}}]

    @staticmethod
    def _tool_reply(*calls):
        return {'stop_reason': 'tool_use',
                'content': [{'type': 'thinking', 'thinking': '', 'signature': 'sig'}]
                + [{'type': 'tool_use', 'id': f'tu{n}', 'name': name, 'input': args}
                   for n, (name, args) in enumerate(calls)],
                'usage': {'input_tokens': 10, 'output_tokens': 2}}

    ANSWER = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '{"a": 1}'}],
              'usage': {'input_tokens': 5, 'output_tokens': 3, 'cache_read_input_tokens': 7}}

    @patch('storyforge.api._api_request')
    def test_runs_tools_until_the_model_answers(self, mock_req, tmp_path):
        from storyforge.api import converse
        replies = [self._tool_reply(('lookup', {'word': 'fog'}), ('lookup', {'word': 'bell'})),
                   self.ANSWER]
        bodies = []
        mock_req.side_effect = lambda path, body, **k: (bodies.append(body), replies.pop(0))[1]
        log = str(tmp_path / 'log.json')
        run = converse('q', 'claude-opus-5-5', self.TOOLS,
                       {'lookup': lambda args: f'{args["word"]}!'}, log_file=log)
        assert run.response == self.ANSWER
        assert [c[:2] for c in run.calls] == [('lookup', {'word': 'fog'}),
                                              ('lookup', {'word': 'bell'})]
        # The second request replays the first reply unchanged (thinking
        # block included) and both results in one user message
        second = bodies[1]['messages']
        assert second[1]['content'][0]['type'] == 'thinking'
        assert [r['content'] for r in second[2]['content']] == ['fog!', 'bell!']
        assert all(t['strict'] for t in bodies[0]['tools'])
        assert run.usage['input_tokens'] == 15 and run.usage['cache_read_input_tokens'] == 7
        with open(log) as f:
            assert len(json.load(f)) == 2

    @patch('storyforge.api._api_request')
    def test_a_tool_input_error_goes_back_to_the_model(self, mock_req):
        from storyforge.api import ToolInputError, converse
        replies = [self._tool_reply(('lookup', {'word': 'x'})), self.ANSWER]
        bodies = []
        mock_req.side_effect = lambda path, body, **k: (bodies.append(body), replies.pop(0))[1]

        def lookup(args):
            raise ToolInputError('no such word')
        run = converse('q', 'claude-opus-5-5', self.TOOLS, {'lookup': lookup})
        result = bodies[1]['messages'][2]['content'][0]
        assert result['is_error'] is True and result['content'] == 'no such word'
        assert run.calls == [('lookup', {'word': 'x'}, True)]

    @patch('storyforge.api._api_request')
    def test_any_other_handler_exception_propagates(self, mock_req):
        from storyforge.api import converse
        mock_req.return_value = self._tool_reply(('lookup', {'word': 'x'}))

        def lookup(args):
            raise KeyError('bug')
        with pytest.raises(KeyError):
            converse('q', 'claude-opus-5-5', self.TOOLS, {'lookup': lookup})

    @patch('storyforge.api._api_request')
    def test_too_many_turns_raises(self, mock_req):
        from storyforge.api import ToolLoopError, converse
        mock_req.return_value = self._tool_reply(('lookup', {'word': 'x'}))
        with pytest.raises(ToolLoopError, match='after 3 requests'):
            converse('q', 'claude-opus-5-5', self.TOOLS, {'lookup': lambda a: ''}, max_turns=3)
        assert mock_req.call_count == 3

    @patch('storyforge.api._api_request')
    def test_a_refusal_raises(self, mock_req):
        from storyforge.api import RefusalError, converse
        mock_req.return_value = {'stop_reason': 'refusal', 'content': [], 'usage': {}}
        with pytest.raises(RefusalError):
            converse('q', 'claude-opus-5-5', self.TOOLS, {'lookup': lambda a: ''})

    def test_every_tool_needs_a_handler(self):
        from storyforge.api import converse
        with pytest.raises(ValueError, match='no handler for tool'):
            converse('q', 'claude-opus-5-5', self.TOOLS, {})

    @patch('storyforge.api._api_request')
    def test_schema_becomes_output_config(self, mock_req):
        from storyforge.api import converse
        mock_req.return_value = self.ANSWER
        schema = TestInvokeOutputSchema.SCHEMA
        converse('q', 'claude-opus-5-5', self.TOOLS, {'lookup': lambda a: ''},
                 output_schema=schema)
        assert mock_req.call_args[0][1]['output_config']['format']['schema'] == schema

"""Tests for prompt caching infrastructure."""

import json


class TestBuildBatchRequest:
    def test_without_system(self):
        from storyforge.api import build_batch_request
        result = build_batch_request('scene-1', 'Write a scene.', 'claude-opus-4-6', 8192)
        assert result['custom_id'] == 'scene-1'
        assert result['params']['model'] == 'claude-opus-4-6'
        assert result['params']['max_tokens'] == 8192
        assert result['params']['messages'] == [{'role': 'user', 'content': 'Write a scene.'}]
        assert 'system' not in result['params']

    def test_with_system(self):
        from storyforge.api import build_batch_request
        system = [
            {'type': 'text', 'text': 'Craft engine content here.'},
            {'type': 'text', 'text': 'Voice guide here.',
             'cache_control': {'type': 'ephemeral'}},
        ]
        result = build_batch_request('scene-1', 'Write a scene.', 'claude-opus-4-6', 8192,
                                     system=system)
        assert result['params']['system'] == system
        assert result['params']['messages'] == [{'role': 'user', 'content': 'Write a scene.'}]

    def test_serializes_to_valid_jsonl(self):
        from storyforge.api import build_batch_request
        system = [{'type': 'text', 'text': 'Context.',
                   'cache_control': {'type': 'ephemeral'}}]
        result = build_batch_request('s1', 'prompt', 'claude-sonnet-4-6', 4096, system=system)
        line = json.dumps(result)
        parsed = json.loads(line)
        assert parsed['custom_id'] == 's1'
        assert parsed['params']['system'][0]['cache_control']['type'] == 'ephemeral'

    def test_default_max_tokens(self):
        from storyforge.api import build_batch_request
        result = build_batch_request('s1', 'prompt', 'claude-sonnet-4-6')
        assert result['params']['max_tokens'] == 4096

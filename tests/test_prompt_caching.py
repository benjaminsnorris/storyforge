"""Tests for prompt caching infrastructure."""

import json
import os


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


class TestBuildSharedContext:
    def test_returns_list_of_dicts(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context, _shared_context_cache
        _shared_context_cache.clear()
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        assert isinstance(result, list)
        assert len(result) > 0
        for block in result:
            assert block['type'] == 'text'
            assert 'text' in block

    def test_tier1_blocks_come_first(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context, _shared_context_cache
        _shared_context_cache.clear()
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        texts = [b['text'] for b in result]
        # Craft engine is tier 1, character bible is tier 2
        craft_idx = next((i for i, t in enumerate(texts) if 'Craft Engine' in t), None)
        bible_idx = next((i for i, t in enumerate(texts) if 'Character Bible' in t), None)
        assert craft_idx is not None
        assert bible_idx is not None
        assert craft_idx < bible_idx

    def test_has_cache_control_breakpoints(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context, _shared_context_cache
        _shared_context_cache.clear()
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        blocks_with_cc = [b for b in result if 'cache_control' in b]
        assert len(blocks_with_cc) >= 1

    def test_skips_missing_files(self, tmp_path):
        from storyforge.common import build_shared_context, _shared_context_cache
        _shared_context_cache.clear()
        project_dir = str(tmp_path / 'empty')
        os.makedirs(os.path.join(project_dir, 'reference'), exist_ok=True)
        result = build_shared_context(project_dir, model='claude-sonnet-4-6')
        assert isinstance(result, list)

    def test_in_process_cache(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context, _shared_context_cache
        _shared_context_cache.clear()
        result1 = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        result2 = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        assert result1 is result2

    def test_includes_project_references(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context, _shared_context_cache
        _shared_context_cache.clear()
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        all_text = ' '.join(b['text'] for b in result)
        assert 'Voice Guide' in all_text
        assert 'Character Bible' in all_text

    def test_includes_registries(self, fixture_dir, plugin_dir):
        from storyforge.common import build_shared_context, _shared_context_cache
        _shared_context_cache.clear()
        result = build_shared_context(fixture_dir, model='claude-sonnet-4-6')
        all_text = ' '.join(b['text'] for b in result)
        assert 'Character Registry' in all_text
        assert 'Location Registry' in all_text

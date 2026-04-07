"""Tests for API helper functions (migrated from test-api.sh)."""

import json
import os


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
        import pytest
        with pytest.raises(Exception):
            extract_text_from_file(str(tmp_path / 'nonexistent.json'))


class TestExtractApiUsage:
    def test_all_fields(self, tmp_path):
        from storyforge.api import extract_usage_from_file
        f = str(tmp_path / 'usage.json')
        with open(f, 'w') as fp:
            json.dump({
                'content': [{'type': 'text', 'text': 'test'}],
                'usage': {
                    'input_tokens': 100, 'output_tokens': 50,
                    'cache_read_input_tokens': 25, 'cache_creation_input_tokens': 10
                }
            }, fp)
        result = extract_usage_from_file(f)
        assert result == {'input_tokens': 100, 'output_tokens': 50,
                          'cache_read': 25, 'cache_create': 10}

    def test_missing_cache_defaults(self, tmp_path):
        from storyforge.api import extract_usage_from_file
        f = str(tmp_path / 'no-cache.json')
        with open(f, 'w') as fp:
            json.dump({
                'content': [{'type': 'text', 'text': 'test'}],
                'usage': {'input_tokens': 100, 'output_tokens': 50}
            }, fp)
        result = extract_usage_from_file(f)
        assert result['cache_read'] == 0
        assert result['cache_create'] == 0


class TestLogApiUsage:
    def test_creates_ledger(self, tmp_path):
        from storyforge.api import log_usage as api_log_usage
        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working', 'costs'))

        f = str(tmp_path / 'api-log.json')
        with open(f, 'w') as fp:
            json.dump({
                'content': [{'type': 'text', 'text': 'test'}],
                'usage': {
                    'input_tokens': 1000, 'output_tokens': 500,
                    'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0
                }
            }, fp)

        api_log_usage(f, 'test-op', 'test-target', 'claude-sonnet-4-6',
                      project_dir=project_dir)

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        assert os.path.isfile(ledger)

        with open(ledger) as fp:
            lines = fp.readlines()
        assert len(lines) == 2
        assert 'test-op|test-target|claude-sonnet-4-6|1000|500' in lines[-1]

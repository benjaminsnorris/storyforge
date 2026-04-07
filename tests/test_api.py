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

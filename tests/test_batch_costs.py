"""Tests for batch API cost logging."""

import os
import json
import pytest


class TestBatchDiscount:
    def test_calculate_cost_standard(self):
        from storyforge.costs import calculate_cost

        # Sonnet: $3/M input, $15/M output
        cost = calculate_cost('claude-sonnet-4-6', 1_000_000, 1_000_000)
        assert abs(cost - 18.0) < 0.01

    def test_calculate_cost_batch(self):
        from storyforge.costs import calculate_cost

        # Batch: 50% of standard
        cost = calculate_cost('claude-sonnet-4-6', 1_000_000, 1_000_000, batch=True)
        assert abs(cost - 9.0) < 0.01

    def test_batch_flag_default_false(self):
        from storyforge.costs import calculate_cost

        standard = calculate_cost('claude-sonnet-4-6', 100_000, 100_000)
        explicit_false = calculate_cost('claude-sonnet-4-6', 100_000, 100_000, batch=False)
        assert standard == explicit_false

    def test_calculate_cost_from_usage_batch(self):
        from storyforge.api import calculate_cost_from_usage

        usage = {'input_tokens': 1_000_000, 'output_tokens': 1_000_000,
                 'cache_read': 0, 'cache_create': 0}

        standard = calculate_cost_from_usage(usage, 'claude-sonnet-4-6')
        batch = calculate_cost_from_usage(usage, 'claude-sonnet-4-6', batch=True)

        assert abs(batch - standard * 0.5) < 0.01


class TestLogApiUsageBatch:
    def test_logs_with_batch_discount(self, tmp_path):
        from storyforge.cmd_score import _log_api_usage
        from storyforge.costs import LEDGER_HEADER

        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working', 'costs'))

        # Create a fake API response JSON
        json_file = str(tmp_path / 'response.json')
        with open(json_file, 'w') as f:
            json.dump({
                'usage': {
                    'input_tokens': 10000,
                    'output_tokens': 1000,
                    'cache_read_input_tokens': 0,
                    'cache_creation_input_tokens': 0,
                }
            }, f)

        _log_api_usage(json_file, 'score', 'test-scene', 'claude-sonnet-4-6',
                       project_dir, batch=True)

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        assert os.path.isfile(ledger)

        with open(ledger) as f:
            lines = f.readlines()

        # Header + 1 data row
        assert len(lines) == 2
        row = lines[1].strip().split('|')
        cost = float(row[8])  # cost_usd column

        # Standard: (10000 * 3 + 1000 * 15) / 1M = 0.045
        # Batch (50%): 0.0225
        assert abs(cost - 0.0225) < 0.001

    def test_logs_without_batch_at_standard_rate(self, tmp_path):
        from storyforge.cmd_score import _log_api_usage

        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working', 'costs'))

        json_file = str(tmp_path / 'response.json')
        with open(json_file, 'w') as f:
            json.dump({
                'usage': {
                    'input_tokens': 10000,
                    'output_tokens': 1000,
                    'cache_read_input_tokens': 0,
                    'cache_creation_input_tokens': 0,
                }
            }, f)

        _log_api_usage(json_file, 'score', 'test-scene', 'claude-sonnet-4-6',
                       project_dir, batch=False)

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        with open(ledger) as f:
            lines = f.readlines()

        row = lines[1].strip().split('|')
        cost = float(row[8])

        # Standard: 0.045
        assert abs(cost - 0.045) < 0.001

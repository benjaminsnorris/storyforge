"""Tests for costs infrastructure module."""

import os
import pytest
from storyforge.costs import (
    calculate_cost, estimate_cost, check_threshold, log_operation,
    print_summary, _detect_tier, _get_price,
    PRICING, LEDGER_HEADER, _OUTPUT_PER_ITEM,
)


class TestPricingConstants:
    """PRICING dict has correct structure and values."""

    def test_tiers_present(self):
        assert 'opus' in PRICING
        assert 'sonnet' in PRICING
        assert 'haiku' in PRICING

    def test_all_tiers_have_required_keys(self):
        required = {'input', 'output', 'cache_read', 'cache_create'}
        for tier in PRICING:
            assert required.issubset(PRICING[tier].keys()), f'{tier} missing keys'

    def test_opus_most_expensive(self):
        assert PRICING['opus']['input'] > PRICING['sonnet']['input']
        assert PRICING['opus']['output'] > PRICING['sonnet']['output']

    def test_haiku_least_expensive(self):
        assert PRICING['haiku']['input'] < PRICING['sonnet']['input']
        assert PRICING['haiku']['output'] < PRICING['sonnet']['output']

    def test_cache_read_cheaper_than_input(self):
        for tier in PRICING:
            assert PRICING[tier]['cache_read'] < PRICING[tier]['input']


class TestDetectTier:
    """_detect_tier maps model names to pricing tiers."""

    def test_opus_model(self):
        assert _detect_tier('claude-opus-4-6') == 'opus'

    def test_sonnet_model(self):
        assert _detect_tier('claude-sonnet-4-6') == 'sonnet'

    def test_haiku_model(self):
        assert _detect_tier('claude-3-haiku-20241022') == 'haiku'

    def test_default_to_sonnet(self):
        assert _detect_tier('unknown-model') == 'sonnet'

    def test_case_insensitive(self):
        assert _detect_tier('CLAUDE-OPUS-4') == 'opus'


class TestGetPrice:
    """_get_price returns correct prices with env override support."""

    def test_opus_input_price(self):
        assert _get_price('claude-opus-4', 'input') == 15.00

    def test_sonnet_output_price(self):
        assert _get_price('claude-sonnet-4', 'output') == 15.00

    def test_haiku_cache_read_price(self):
        assert _get_price('claude-3-haiku', 'cache_read') == 0.08

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv('PRICING_OPUS_INPUT', '20.00')
        assert _get_price('claude-opus-4', 'input') == 20.00


class TestCalculateCost:
    """calculate_cost computes USD from token counts."""

    def test_input_only(self):
        cost = calculate_cost('claude-sonnet-4', 1_000_000, 0)
        assert abs(cost - 3.00) < 0.01

    def test_output_only(self):
        cost = calculate_cost('claude-sonnet-4', 0, 1_000_000)
        assert abs(cost - 15.00) < 0.01

    def test_mixed_tokens(self):
        cost = calculate_cost('claude-sonnet-4', 500_000, 100_000)
        expected = 500_000 * 3.0 / 1e6 + 100_000 * 15.0 / 1e6
        assert abs(cost - expected) < 0.001

    def test_with_cache_tokens(self):
        cost = calculate_cost('claude-sonnet-4', 100_000, 50_000,
                              cache_read=200_000, cache_create=50_000)
        expected = (
            100_000 * 3.0 / 1e6 +
            50_000 * 15.0 / 1e6 +
            200_000 * 0.30 / 1e6 +
            50_000 * 3.75 / 1e6
        )
        assert abs(cost - expected) < 0.001

    def test_zero_tokens(self):
        assert calculate_cost('claude-sonnet-4', 0, 0) == 0.0

    def test_opus_is_expensive(self):
        opus_cost = calculate_cost('claude-opus-4', 1000, 1000)
        sonnet_cost = calculate_cost('claude-sonnet-4', 1000, 1000)
        assert opus_cost > sonnet_cost

    def test_haiku_is_cheap(self):
        haiku_cost = calculate_cost('claude-3-haiku', 1000, 1000)
        sonnet_cost = calculate_cost('claude-sonnet-4', 1000, 1000)
        assert haiku_cost < sonnet_cost


class TestEstimateCost:
    """estimate_cost forecasts cost for an operation."""

    def test_zero_scope(self):
        assert estimate_cost('draft', 0, 2000, 'claude-sonnet-4') == 0.0

    def test_positive_scope(self):
        cost = estimate_cost('draft', 10, 2000, 'claude-sonnet-4')
        assert cost > 0

    def test_draft_higher_than_score(self):
        """Draft has higher output per item, so should cost more."""
        draft_cost = estimate_cost('draft', 10, 2000, 'claude-sonnet-4')
        score_cost = estimate_cost('score', 10, 2000, 'claude-sonnet-4')
        assert draft_cost > score_cost

    def test_opus_more_expensive(self):
        opus_cost = estimate_cost('draft', 10, 2000, 'claude-opus-4')
        sonnet_cost = estimate_cost('draft', 10, 2000, 'claude-sonnet-4')
        assert opus_cost > sonnet_cost

    def test_scales_with_scope(self):
        cost_10 = estimate_cost('evaluate', 10, 2000, 'claude-sonnet-4')
        cost_20 = estimate_cost('evaluate', 20, 2000, 'claude-sonnet-4')
        assert abs(cost_20 - 2 * cost_10) < 0.01

    def test_unknown_operation_uses_default(self):
        cost = estimate_cost('unknown_op', 5, 1000, 'claude-sonnet-4')
        assert cost > 0


class TestCheckThreshold:
    """check_threshold validates cost against limit."""

    def test_under_threshold(self):
        assert check_threshold(5.0) is True

    def test_at_threshold(self):
        assert check_threshold(100.0) is True

    def test_over_threshold(self):
        assert check_threshold(101.0) is False

    def test_custom_threshold(self):
        assert check_threshold(5.0, threshold=3.0) is False

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '10.0')
        assert check_threshold(5.0) is True
        assert check_threshold(15.0) is False

    def test_zero_cost(self):
        assert check_threshold(0.0) is True


class TestLogOperation:
    """log_operation appends rows to the ledger CSV."""

    def test_creates_ledger(self, tmp_path):
        project = tmp_path
        log_operation(str(project), 'test-op', 'claude-sonnet-4',
                      1000, 500, 0.01)
        ledger = project / 'working' / 'costs' / 'ledger.csv'
        assert ledger.exists()

    def test_creates_header(self, tmp_path):
        project = tmp_path
        log_operation(str(project), 'test-op', 'claude-sonnet-4',
                      1000, 500, 0.01)
        ledger = project / 'working' / 'costs' / 'ledger.csv'
        header = ledger.read_text().splitlines()[0]
        assert header == LEDGER_HEADER

    def test_appends_row(self, tmp_path):
        project = tmp_path
        log_operation(str(project), 'op1', 'claude-sonnet-4', 1000, 500, 0.01)
        log_operation(str(project), 'op2', 'claude-opus-4', 2000, 1000, 0.05)
        ledger = project / 'working' / 'costs' / 'ledger.csv'
        lines = ledger.read_text().strip().splitlines()
        assert len(lines) == 3  # header + 2 rows

    def test_row_format(self, tmp_path):
        project = tmp_path
        log_operation(str(project), 'score', 'claude-sonnet-4',
                      5000, 2000, 0.123456, duration_s=42, target='scene-1',
                      cache_read=100, cache_create=50)
        ledger = project / 'working' / 'costs' / 'ledger.csv'
        data_line = ledger.read_text().strip().splitlines()[1]
        parts = data_line.split('|')
        assert len(parts) == 10
        assert parts[1] == 'score'
        assert parts[2] == 'scene-1'
        assert parts[3] == 'claude-sonnet-4'
        assert parts[4] == '5000'
        assert parts[5] == '2000'
        assert parts[6] == '100'
        assert parts[7] == '50'
        assert parts[8] == '0.123456'
        assert parts[9] == '42'


class TestPrintSummary:
    """print_summary reads ledger and outputs totals."""

    def test_no_ledger_file(self, tmp_path, capsys):
        print_summary(str(tmp_path))
        out = capsys.readouterr().out
        assert 'No cost data' in out

    def test_with_data(self, tmp_path, capsys):
        project = tmp_path
        log_operation(str(project), 'test', 'claude-sonnet-4',
                      1000, 500, 0.01, duration_s=5)
        print_summary(str(project))
        out = capsys.readouterr().out
        assert 'Invocations:' in out
        assert '1' in out

    def test_filtered_by_operation(self, tmp_path, capsys):
        project = tmp_path
        log_operation(str(project), 'op-a', 'claude-sonnet-4', 1000, 500, 0.01)
        log_operation(str(project), 'op-b', 'claude-sonnet-4', 2000, 1000, 0.02)
        print_summary(str(project), 'op-a')
        out = capsys.readouterr().out
        assert 'op-a' in out
        assert 'Invocations:   1' in out

    def test_no_matching_operation(self, tmp_path, capsys):
        project = tmp_path
        log_operation(str(project), 'op-a', 'claude-sonnet-4', 1000, 500, 0.01)
        print_summary(str(project), 'nonexistent')
        out = capsys.readouterr().out
        assert 'No cost data' in out

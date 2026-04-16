"""Tests for storyforge.costs — cost tracking, estimation, and thresholds.

Tests the real functions directly (not mocked). Covers calculate_cost,
estimate_cost, check_threshold, log_operation, print_summary, pricing
tier detection, and env var overrides.
"""

import os

import pytest

from storyforge.costs import (
    calculate_cost, estimate_cost, check_threshold, log_operation,
    print_summary, _detect_tier, _get_price, PRICING, LEDGER_HEADER,
)


# ---------------------------------------------------------------------------
# Clear env vars that affect pricing/thresholds so tests use defaults
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_cost_env(monkeypatch):
    """Ensure pricing and threshold env vars don't leak from developer shell."""
    for var in [
        'STORYFORGE_COST_THRESHOLD',
        'PRICING_OPUS_INPUT', 'PRICING_OPUS_OUTPUT',
        'PRICING_OPUS_CACHE_READ', 'PRICING_OPUS_CACHE_CREATE',
        'PRICING_SONNET_INPUT', 'PRICING_SONNET_OUTPUT',
        'PRICING_SONNET_CACHE_READ', 'PRICING_SONNET_CACHE_CREATE',
        'PRICING_HAIKU_INPUT', 'PRICING_HAIKU_OUTPUT',
        'PRICING_HAIKU_CACHE_READ', 'PRICING_HAIKU_CACHE_CREATE',
    ]:
        monkeypatch.delenv(var, raising=False)


# ============================================================================
# _detect_tier
# ============================================================================


class TestDetectTier:
    """Test pricing tier detection from model names."""

    def test_opus_model(self):
        assert _detect_tier('claude-opus-4-6-20250514') == 'opus'

    def test_sonnet_model(self):
        assert _detect_tier('claude-sonnet-4-6-20250514') == 'sonnet'

    def test_haiku_model(self):
        assert _detect_tier('claude-haiku-4-5-20251001') == 'haiku'

    def test_case_insensitive(self):
        assert _detect_tier('Claude-Opus-4-6') == 'opus'

    def test_unknown_defaults_to_sonnet(self):
        assert _detect_tier('some-unknown-model') == 'sonnet'

    def test_opus_in_string(self):
        assert _detect_tier('my-opus-variant') == 'opus'

    def test_haiku_in_string(self):
        assert _detect_tier('my-haiku-variant') == 'haiku'


# ============================================================================
# calculate_cost
# ============================================================================


class TestCalculateCost:
    """Test cost calculation for different models and token counts."""

    def test_opus_cost(self):
        cost = calculate_cost('claude-opus-4-6-20250514',
                              input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(PRICING['opus']['input'])

    def test_sonnet_cost(self):
        cost = calculate_cost('claude-sonnet-4-6-20250514',
                              input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(PRICING['sonnet']['input'])

    def test_haiku_cost(self):
        cost = calculate_cost('claude-haiku-4-5-20251001',
                              input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(PRICING['haiku']['input'])

    def test_output_tokens_cost(self):
        cost = calculate_cost('claude-opus-4-6-20250514',
                              input_tokens=0, output_tokens=1_000_000)
        assert cost == pytest.approx(PRICING['opus']['output'])

    def test_combined_input_output(self):
        cost = calculate_cost('claude-sonnet-4-6-20250514',
                              input_tokens=1000, output_tokens=500)
        expected = (1000 * 3.00 / 1_000_000) + (500 * 15.00 / 1_000_000)
        assert cost == pytest.approx(expected)

    def test_zero_tokens(self):
        cost = calculate_cost('claude-opus-4-6-20250514',
                              input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_cache_read_tokens(self):
        cost = calculate_cost('claude-opus-4-6-20250514',
                              input_tokens=0, output_tokens=0,
                              cache_read=1_000_000)
        assert cost == pytest.approx(PRICING['opus']['cache_read'])

    def test_cache_create_tokens(self):
        cost = calculate_cost('claude-opus-4-6-20250514',
                              input_tokens=0, output_tokens=0,
                              cache_create=1_000_000)
        assert cost == pytest.approx(PRICING['opus']['cache_create'])

    def test_all_token_types(self):
        cost = calculate_cost('claude-sonnet-4-6-20250514',
                              input_tokens=1000, output_tokens=500,
                              cache_read=2000, cache_create=300)
        expected = (
            1000 * 3.00 / 1_000_000
            + 500 * 15.00 / 1_000_000
            + 2000 * 0.30 / 1_000_000
            + 300 * 3.75 / 1_000_000
        )
        assert cost == pytest.approx(expected)

    def test_env_override_input_price(self, monkeypatch):
        monkeypatch.setenv('PRICING_OPUS_INPUT', '20.00')
        cost = calculate_cost('claude-opus-4-6-20250514',
                              input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(20.00)

    def test_env_override_output_price(self, monkeypatch):
        monkeypatch.setenv('PRICING_SONNET_OUTPUT', '25.00')
        cost = calculate_cost('claude-sonnet-4-6-20250514',
                              input_tokens=0, output_tokens=1_000_000)
        assert cost == pytest.approx(25.00)


# ============================================================================
# estimate_cost
# ============================================================================


class TestEstimateCost:
    """Test cost estimation for different operations."""

    def test_draft_operation(self):
        cost = estimate_cost('draft', scope_count=10, avg_words=2000,
                             model='claude-opus-4-6-20250514')
        assert cost > 0

    def test_evaluate_operation(self):
        cost = estimate_cost('evaluate', scope_count=5, avg_words=3000,
                             model='claude-sonnet-4-6-20250514')
        assert cost > 0

    def test_revise_operation(self):
        cost = estimate_cost('revise', scope_count=3, avg_words=2500,
                             model='claude-opus-4-6-20250514')
        assert cost > 0

    def test_score_operation(self):
        cost = estimate_cost('score', scope_count=20, avg_words=2000,
                             model='claude-sonnet-4-6-20250514')
        assert cost > 0

    def test_unknown_operation_uses_default(self):
        cost = estimate_cost('custom-op', scope_count=5, avg_words=2000,
                             model='claude-sonnet-4-6-20250514')
        assert cost > 0

    def test_zero_scope_returns_zero(self):
        cost = estimate_cost('draft', scope_count=0, avg_words=2000,
                             model='claude-opus-4-6-20250514')
        assert cost == 0.0

    def test_scales_with_scope_count(self):
        cost_5 = estimate_cost('draft', scope_count=5, avg_words=2000,
                               model='claude-opus-4-6-20250514')
        cost_10 = estimate_cost('draft', scope_count=10, avg_words=2000,
                                model='claude-opus-4-6-20250514')
        assert cost_10 == pytest.approx(cost_5 * 2)

    def test_opus_more_expensive_than_sonnet(self):
        opus_cost = estimate_cost('draft', scope_count=10, avg_words=2000,
                                  model='claude-opus-4-6-20250514')
        sonnet_cost = estimate_cost('draft', scope_count=10, avg_words=2000,
                                    model='claude-sonnet-4-6-20250514')
        assert opus_cost > sonnet_cost


# ============================================================================
# check_threshold
# ============================================================================


class TestCheckThreshold:
    """Test threshold checking with defaults and env overrides."""

    def test_under_threshold_returns_true(self):
        assert check_threshold(50.0) is True

    def test_equal_threshold_returns_true(self):
        assert check_threshold(100.0) is True

    def test_over_threshold_returns_false(self):
        assert check_threshold(150.0) is False

    def test_custom_threshold(self):
        assert check_threshold(25.0, threshold=20.0) is False
        assert check_threshold(15.0, threshold=20.0) is True

    def test_env_override_threshold(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '10.0')
        assert check_threshold(5.0) is True
        assert check_threshold(15.0) is False

    def test_env_overrides_argument(self, monkeypatch):
        """Env var takes priority over the threshold argument."""
        monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '5.0')
        # The function argument says 100 but env says 5
        assert check_threshold(10.0, threshold=100.0) is False

    def test_zero_cost(self):
        assert check_threshold(0.0) is True


# ============================================================================
# log_operation
# ============================================================================


class TestLogOperation:
    """Test ledger CSV writing."""

    def test_creates_ledger_with_header(self, tmp_path):
        project_dir = str(tmp_path)
        os.makedirs(os.path.join(project_dir, 'working', 'costs'), exist_ok=True)
        log_operation(project_dir, 'draft', 'claude-opus-4-6-20250514',
                      input_tokens=1000, output_tokens=500, cost=0.05)

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        assert os.path.isfile(ledger)
        with open(ledger) as f:
            lines = f.read().strip().splitlines()
        assert lines[0] == LEDGER_HEADER
        assert len(lines) == 2

    def test_appends_to_existing_ledger(self, tmp_path):
        project_dir = str(tmp_path)
        log_operation(project_dir, 'draft', 'opus', 100, 50, 0.01)
        log_operation(project_dir, 'evaluate', 'sonnet', 200, 100, 0.02)

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        with open(ledger) as f:
            lines = f.read().strip().splitlines()
        assert len(lines) == 3  # header + 2 rows

    def test_row_format(self, tmp_path):
        project_dir = str(tmp_path)
        log_operation(project_dir, 'score', 'claude-sonnet-4-6',
                      input_tokens=5000, output_tokens=2000, cost=1.234567,
                      duration_s=45, target='act1-sc01',
                      cache_read=100, cache_create=50)

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        with open(ledger) as f:
            lines = f.read().strip().splitlines()
        row = lines[1]
        parts = row.split('|')
        assert len(parts) == 10
        # timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s
        assert parts[1] == 'score'
        assert parts[2] == 'act1-sc01'
        assert parts[3] == 'claude-sonnet-4-6'
        assert parts[4] == '5000'
        assert parts[5] == '2000'
        assert parts[6] == '100'
        assert parts[7] == '50'
        assert parts[8] == '1.234567'
        assert parts[9] == '45'

    def test_creates_directories(self, tmp_path):
        """log_operation creates working/costs/ if it doesn't exist."""
        project_dir = str(tmp_path / 'new-project')
        # Directory doesn't exist yet
        log_operation(project_dir, 'draft', 'opus', 100, 50, 0.01)
        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        assert os.path.isfile(ledger)

    def test_default_duration_and_target(self, tmp_path):
        project_dir = str(tmp_path)
        log_operation(project_dir, 'draft', 'opus', 100, 50, 0.01)

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        with open(ledger) as f:
            lines = f.read().strip().splitlines()
        parts = lines[1].split('|')
        assert parts[2] == ''    # target default
        assert parts[9] == '0'   # duration_s default


# ============================================================================
# print_summary
# ============================================================================


class TestPrintSummary:
    """Test cost summary printing."""

    def test_no_ledger_file(self, tmp_path, capsys):
        print_summary(str(tmp_path))
        captured = capsys.readouterr()
        assert 'No cost data available' in captured.out

    def test_empty_ledger(self, tmp_path, capsys):
        ledger = os.path.join(str(tmp_path), 'working', 'costs', 'ledger.csv')
        os.makedirs(os.path.dirname(ledger), exist_ok=True)
        with open(ledger, 'w') as f:
            f.write('')
        print_summary(str(tmp_path))
        captured = capsys.readouterr()
        assert 'No cost data available' in captured.out

    def test_summary_all_operations(self, tmp_path, capsys):
        project_dir = str(tmp_path)
        log_operation(project_dir, 'draft', 'opus', 1000, 500, 0.50, duration_s=10)
        log_operation(project_dir, 'evaluate', 'sonnet', 2000, 1000, 0.25, duration_s=5)

        print_summary(project_dir)
        captured = capsys.readouterr()
        assert 'Invocations:   2' in captured.out
        assert 'Input tokens:  3,000' in captured.out
        assert 'Output tokens: 1,500' in captured.out
        assert '$0.7500' in captured.out
        assert '15s' in captured.out
        assert 'all operations' in captured.out

    def test_summary_filtered_by_operation(self, tmp_path, capsys):
        project_dir = str(tmp_path)
        log_operation(project_dir, 'draft', 'opus', 1000, 500, 0.50)
        log_operation(project_dir, 'evaluate', 'sonnet', 2000, 1000, 0.25)

        print_summary(project_dir, operation='draft')
        captured = capsys.readouterr()
        assert 'Invocations:   1' in captured.out
        assert 'Input tokens:  1,000' in captured.out
        assert 'draft' in captured.out

    def test_no_matching_operation(self, tmp_path, capsys):
        project_dir = str(tmp_path)
        log_operation(project_dir, 'draft', 'opus', 1000, 500, 0.50)

        print_summary(project_dir, operation='nonexistent')
        captured = capsys.readouterr()
        assert 'No cost data for operation: nonexistent' in captured.out

    def test_summary_includes_cache_totals(self, tmp_path, capsys):
        project_dir = str(tmp_path)
        log_operation(project_dir, 'draft', 'opus', 1000, 500, 0.50,
                      cache_read=300, cache_create=100)

        print_summary(project_dir)
        captured = capsys.readouterr()
        assert 'Cache read:    300' in captured.out
        assert 'Cache create:  100' in captured.out


# ============================================================================
# _get_price env overrides
# ============================================================================


class TestGetPrice:
    """Test env var price overrides."""

    def test_default_opus_input_price(self):
        price = _get_price('claude-opus-4-6', 'input')
        assert price == PRICING['opus']['input']

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv('PRICING_HAIKU_OUTPUT', '10.0')
        price = _get_price('claude-haiku-4-5', 'output')
        assert price == 10.0

    def test_env_not_set_uses_default(self, monkeypatch):
        monkeypatch.delenv('PRICING_SONNET_INPUT', raising=False)
        price = _get_price('claude-sonnet-4-6', 'input')
        assert price == PRICING['sonnet']['input']

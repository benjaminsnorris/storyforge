"""Tests for cost calculation (migrated from test-costs.sh)."""

from storyforge.costs import calculate_cost, estimate_cost, get_model_pricing


class TestGetModelPricing:
    def test_opus_input(self):
        assert get_model_pricing('claude-opus-4', 'input') == 15.00

    def test_opus_output(self):
        assert get_model_pricing('claude-opus-4', 'output') == 75.00

    def test_opus_cache_read(self):
        assert get_model_pricing('claude-opus-4', 'cache_read') == 1.50

    def test_opus_cache_create(self):
        assert get_model_pricing('claude-opus-4', 'cache_create') == 18.75

    def test_sonnet_input(self):
        assert get_model_pricing('claude-sonnet-4', 'input') == 3.00

    def test_sonnet_output(self):
        assert get_model_pricing('claude-sonnet-4', 'output') == 15.00

    def test_sonnet_cache_read(self):
        assert get_model_pricing('claude-sonnet-4', 'cache_read') == 0.30

    def test_sonnet_cache_create(self):
        assert get_model_pricing('claude-sonnet-4', 'cache_create') == 3.75

    def test_unknown_model_defaults(self):
        assert get_model_pricing('some-model', 'input') == 3.00

    def test_unknown_token_type(self):
        assert get_model_pricing('claude-opus-4', 'unknown_type') == 0.00

    def test_haiku_input(self):
        assert get_model_pricing('claude-haiku-4-5', 'input') == 0.80

    def test_haiku_output(self):
        assert get_model_pricing('claude-haiku-4-5', 'output') == 4.00

    def test_haiku_cache_read(self):
        assert get_model_pricing('claude-haiku-4-5', 'cache_read') == 0.08

    def test_haiku_cache_create(self):
        assert get_model_pricing('claude-haiku-4-5', 'cache_create') == 1.00


class TestEstimateCost:
    def test_zero_scope(self):
        result = estimate_cost('draft', 0, 2000, 'claude-sonnet-4')
        assert result == 0.00


class TestCalculateCost:
    def test_sonnet_input(self):
        result = calculate_cost('claude-sonnet-4-6', 1000000, 0)
        assert f'{result:.2f}' == '3.00'

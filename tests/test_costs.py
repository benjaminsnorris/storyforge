"""Tests for cost calculation (migrated from test-costs.sh)."""

from storyforge.costs import calculate_cost, estimate_cost, format_duration, PRICING


class TestPricing:
    def test_opus_input(self):
        assert PRICING['opus']['input'] == 15.00

    def test_opus_output(self):
        assert PRICING['opus']['output'] == 75.00

    def test_opus_cache_read(self):
        assert PRICING['opus']['cache_read'] == 1.50

    def test_opus_cache_create(self):
        assert PRICING['opus']['cache_create'] == 18.75

    def test_sonnet_input(self):
        assert PRICING['sonnet']['input'] == 3.00

    def test_sonnet_output(self):
        assert PRICING['sonnet']['output'] == 15.00

    def test_sonnet_cache_read(self):
        assert PRICING['sonnet']['cache_read'] == 0.30

    def test_sonnet_cache_create(self):
        assert PRICING['sonnet']['cache_create'] == 3.75

    def test_haiku_input(self):
        assert PRICING['haiku']['input'] == 0.80

    def test_haiku_output(self):
        assert PRICING['haiku']['output'] == 4.00

    def test_haiku_cache_read(self):
        assert PRICING['haiku']['cache_read'] == 0.08

    def test_haiku_cache_create(self):
        assert PRICING['haiku']['cache_create'] == 1.00


class TestCalculateCost:
    def test_sonnet_input(self):
        result = calculate_cost('claude-sonnet-4-6', 1000000, 0)
        assert f'{result:.2f}' == '3.00'


class TestEstimateCost:
    def test_zero_scope(self):
        result = estimate_cost('draft', 0, 2000, 'claude-sonnet-4')
        assert result == 0.00


class TestFormatDuration:
    def test_zero(self):
        assert format_duration(0) == '0s'

    def test_seconds_only(self):
        assert format_duration(45) == '45s'

    def test_minutes_and_seconds(self):
        assert format_duration(180) == '3m 0s'

    def test_minutes_and_nonzero_seconds(self):
        assert format_duration(185) == '3m 5s'

    def test_hours_minutes_seconds(self):
        assert format_duration(3661) == '1h 1m 1s'

    def test_large_duration(self):
        assert format_duration(27888) == '7h 44m 48s'

    def test_exact_hour(self):
        assert format_duration(3600) == '1h 0m 0s'

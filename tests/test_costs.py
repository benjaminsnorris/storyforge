"""Tests for cost calculation (migrated from test-costs.sh)."""

import os
from storyforge.costs import calculate_cost, estimate_cost, format_duration, log_operation, print_summary, PRICING, LEDGER_HEADER


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


class TestSessionScopedSummary:
    def _make_ledger(self, project_dir, rows):
        """Write a ledger with the given rows (list of pipe-delimited strings)."""
        ledger_dir = os.path.join(project_dir, 'working', 'costs')
        os.makedirs(ledger_dir, exist_ok=True)
        with open(os.path.join(ledger_dir, 'ledger.csv'), 'w') as f:
            f.write(LEDGER_HEADER + '\n')
            for row in rows:
                f.write(row + '\n')

    def test_no_session_start_shows_cumulative_only(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-01T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|300',
            '2026-04-15T10:00:00|revise|scene-2|claude-opus-4-6|100000|10000|0|0|5.250000|300',
        ])
        print_summary(project_dir, 'revise')
        out = capsys.readouterr().out
        assert 'This session' not in out
        assert 'Project total' not in out
        assert '--- Cost Summary: revise ---' in out
        assert 'Invocations:   2' in out

    def test_session_start_shows_both_sections(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-01T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|300',
            '2026-04-15T10:00:00|revise|scene-2|claude-opus-4-6|200000|20000|0|0|10.500000|600',
            '2026-04-15T11:00:00|revise|scene-3|claude-opus-4-6|200000|20000|0|0|10.500000|600',
        ])
        print_summary(project_dir, 'revise', session_start='2026-04-15T09:00:00')
        out = capsys.readouterr().out
        assert '--- This session: revise (2 invocations) ---' in out
        assert '--- Project total: revise (3 invocations) ---' in out

    def test_session_filters_by_timestamp(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-01T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|300',
            '2026-04-15T14:00:00|revise|scene-2|claude-opus-4-6|200000|20000|0|0|10.500000|600',
        ])
        print_summary(project_dir, 'revise', session_start='2026-04-15T00:00:00')
        out = capsys.readouterr().out
        assert '1 invocation)' in out  # singular

    def test_session_with_no_matching_rows(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-01T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|300',
        ])
        print_summary(project_dir, 'revise', session_start='2026-04-15T00:00:00')
        out = capsys.readouterr().out
        assert 'Project total' in out
        assert 'This session' not in out

    def test_duration_uses_format_duration(self, tmp_path, capsys):
        project_dir = str(tmp_path / 'proj')
        self._make_ledger(project_dir, [
            '2026-04-15T10:00:00|revise|scene-1|claude-opus-4-6|100000|10000|0|0|5.250000|3661',
        ])
        print_summary(project_dir, 'revise')
        out = capsys.readouterr().out
        assert '1h 1m 1s' in out
        assert '3661s' not in out

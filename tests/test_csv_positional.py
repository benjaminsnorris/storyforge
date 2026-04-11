"""Regression tests for positional CSV column access.

Verify that csv_cli.list_ids() and costs.print_summary() work correctly
when CSV columns are in a non-standard order.
"""

import os

import storyforge.csv_cli as csv_cli
from storyforge.costs import log_operation, print_summary


class TestListIdsColumnOrder:
    """list_ids must use the header to find the key column, not assume index 0."""

    def test_id_not_first_column(self, tmp_path):
        """When 'id' is not the first column, list_ids should still return IDs."""
        csv_path = str(tmp_path / 'reordered.csv')
        with open(csv_path, 'w') as f:
            f.write('title|seq|id|status\n')
            f.write('Scene A|1|scene-a|draft\n')
            f.write('Scene B|2|scene-b|final\n')
            f.write('Scene C|3|scene-c|draft\n')

        result = csv_cli.list_ids(csv_path)
        assert result == ['scene-a', 'scene-b', 'scene-c']

    def test_id_last_column(self, tmp_path):
        """When 'id' is the last column, list_ids should still work."""
        csv_path = str(tmp_path / 'reordered.csv')
        with open(csv_path, 'w') as f:
            f.write('title|status|seq|id\n')
            f.write('Scene A|draft|1|alpha\n')
            f.write('Scene B|final|2|beta\n')

        result = csv_cli.list_ids(csv_path)
        assert result == ['alpha', 'beta']

    def test_custom_key_column_reordered(self, tmp_path):
        """list_ids with a custom key_col finds the right column regardless of position."""
        csv_path = str(tmp_path / 'keyed.csv')
        with open(csv_path, 'w') as f:
            f.write('name|score|principle\n')
            f.write('Alice|5|tension\n')
            f.write('Bob|3|voice\n')

        result = csv_cli.list_ids(csv_path, key_col='principle')
        assert result == ['tension', 'voice']

    def test_id_first_column_still_works(self, tmp_path):
        """Normal order (id first) should still work after the fix."""
        csv_path = str(tmp_path / 'normal.csv')
        with open(csv_path, 'w') as f:
            f.write('id|title|status\n')
            f.write('one|Title 1|draft\n')
            f.write('two|Title 2|final\n')

        result = csv_cli.list_ids(csv_path)
        assert result == ['one', 'two']

    def test_fallback_when_key_col_missing(self, tmp_path):
        """When the key column name is not in the header, fall back to column 0."""
        csv_path = str(tmp_path / 'no_id.csv')
        with open(csv_path, 'w') as f:
            f.write('name|value\n')
            f.write('alice|10\n')
            f.write('bob|20\n')

        # Default key_col='id' is not in headers, should fall back to column 0
        result = csv_cli.list_ids(csv_path)
        assert result == ['alice', 'bob']

    def test_empty_file(self, tmp_path):
        """Empty file returns empty list."""
        csv_path = str(tmp_path / 'empty.csv')
        with open(csv_path, 'w') as f:
            pass
        result = csv_cli.list_ids(csv_path)
        assert result == []

    def test_header_only(self, tmp_path):
        """File with only a header returns empty list."""
        csv_path = str(tmp_path / 'header_only.csv')
        with open(csv_path, 'w') as f:
            f.write('id|title|status\n')
        result = csv_cli.list_ids(csv_path)
        assert result == []


class TestPrintSummaryColumnOrder:
    """print_summary must use the header to find columns, not positional indices."""

    def _make_ledger(self, project_dir, header, rows):
        """Create a ledger CSV with the given header and rows."""
        ledger_dir = os.path.join(project_dir, 'working', 'costs')
        os.makedirs(ledger_dir, exist_ok=True)
        ledger_file = os.path.join(ledger_dir, 'ledger.csv')
        with open(ledger_file, 'w') as f:
            f.write(header + '\n')
            for row in rows:
                f.write(row + '\n')
        return ledger_file

    def test_reordered_columns(self, tmp_path, capsys):
        """print_summary works when columns are in a different order than LEDGER_HEADER."""
        project_dir = str(tmp_path)
        # Reorder: put cost_usd first, operation last, etc.
        header = 'cost_usd|input_tokens|duration_s|model|output_tokens|cache_read|cache_create|timestamp|target|operation'
        # Values matching the reordered header
        row = '0.500000|1000|30|sonnet|500|100|50|2026-01-01T00:00:00|scene-a|evaluate'
        self._make_ledger(project_dir, header, [row])

        print_summary(project_dir)
        captured = capsys.readouterr()
        assert 'Input tokens:  1000' in captured.out
        assert 'Output tokens: 500' in captured.out
        assert 'Cache read:    100' in captured.out
        assert 'Cache create:  50' in captured.out
        assert '$0.5000' in captured.out
        assert '30s' in captured.out

    def test_reordered_with_operation_filter(self, tmp_path, capsys):
        """Filtering by operation works with reordered columns."""
        project_dir = str(tmp_path)
        header = 'cost_usd|operation|input_tokens|output_tokens|cache_read|cache_create|duration_s|timestamp|target|model'
        rows = [
            '0.100000|evaluate|500|200|0|0|10|2026-01-01T00:00:00|scene-a|sonnet',
            '0.200000|score|300|100|0|0|5|2026-01-01T00:01:00|scene-a|sonnet',
            '0.300000|evaluate|700|400|0|0|20|2026-01-01T00:02:00|scene-b|sonnet',
        ]
        self._make_ledger(project_dir, header, rows)

        print_summary(project_dir, 'evaluate')
        captured = capsys.readouterr()
        assert 'Invocations:   2' in captured.out
        assert 'Input tokens:  1200' in captured.out
        assert 'Output tokens: 600' in captured.out

    def test_standard_order_still_works(self, tmp_path, capsys):
        """Normal column order (matching LEDGER_HEADER) still works after the fix."""
        project_dir = str(tmp_path)
        header = 'timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s'
        row = '2026-01-01T00:00:00|draft|scene-a|opus|2000|1000|200|100|1.000000|60'
        self._make_ledger(project_dir, header, [row])

        print_summary(project_dir)
        captured = capsys.readouterr()
        assert 'Input tokens:  2000' in captured.out
        assert 'Output tokens: 1000' in captured.out
        assert 'Cache read:    200' in captured.out
        assert 'Cache create:  100' in captured.out
        assert '$1.0000' in captured.out
        assert '60s' in captured.out

    def test_missing_optional_columns(self, tmp_path, capsys):
        """Ledger with fewer columns (e.g., no cache columns) still produces a summary."""
        project_dir = str(tmp_path)
        # Old-style format without cache columns
        header = 'timestamp|operation|model|input_tokens|output_tokens|cost_usd|duration_s'
        row = '2026-01-01T00:00:00|draft|opus|1000|500|0.500000|30'
        self._make_ledger(project_dir, header, rows=[row])

        print_summary(project_dir)
        captured = capsys.readouterr()
        assert 'Invocations:   1' in captured.out
        assert 'Input tokens:  1000' in captured.out
        assert 'Output tokens: 500' in captured.out
        assert 'Cache read:    0' in captured.out  # Missing columns default to 0
        assert '$0.5000' in captured.out

    def test_log_then_summary_roundtrip(self, tmp_path, capsys):
        """log_operation writes data that print_summary can read back correctly."""
        project_dir = str(tmp_path)
        log_operation(project_dir, 'evaluate', 'sonnet', 5000, 2000, 0.45,
                      duration_s=15, target='scene-x', cache_read=100, cache_create=50)
        log_operation(project_dir, 'evaluate', 'opus', 3000, 1000, 0.30,
                      duration_s=10, target='scene-y')

        print_summary(project_dir, 'evaluate')
        captured = capsys.readouterr()
        assert 'Invocations:   2' in captured.out
        assert 'Input tokens:  8000' in captured.out
        assert 'Output tokens: 3000' in captured.out
        assert 'Cache read:    100' in captured.out
        assert 'Cache create:  50' in captured.out

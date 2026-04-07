"""Tests for CSV functions (migrated from test-csv.sh).

The csv_cli functions print to stdout (they are CLI functions).
We use a helper to capture their output.
"""

import io
import os
import shutil
import sys

import storyforge.csv_cli as csv_cli


def _capture(fn, *args, **kwargs):
    """Call a csv_cli function and return its stdout output, stripped."""
    old = sys.stdout
    sys.stdout = buf = io.StringIO()
    try:
        fn(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue().rstrip('\n')


class TestGetCsvField:
    def test_title(self, meta_csv):
        assert _capture(csv_cli.get_field, meta_csv, 'act1-sc01', 'title') == 'The Finest Cartographer'

    def test_word_count(self, meta_csv):
        assert _capture(csv_cli.get_field, meta_csv, 'act1-sc01', 'word_count') == '0'

    def test_status(self, meta_csv):
        assert _capture(csv_cli.get_field, meta_csv, 'act2-sc01', 'status') == 'architecture'

    def test_pov(self, meta_csv):
        assert _capture(csv_cli.get_field, meta_csv, 'act1-sc02', 'pov') == 'Dorren Hayle'

    def test_type(self, meta_csv):
        assert _capture(csv_cli.get_field, meta_csv, 'new-x1', 'type') == 'revelation'

    def test_nonexistent_id(self, meta_csv):
        assert _capture(csv_cli.get_field, meta_csv, 'no-such-id', 'title') == ''

    def test_nonexistent_field(self, meta_csv):
        assert _capture(csv_cli.get_field, meta_csv, 'act1-sc01', 'nonexistent') == ''

    def test_missing_file(self, tmp_path):
        assert _capture(csv_cli.get_field, str(tmp_path / 'nonexistent.csv'), 'act1-sc01', 'title') == ''


class TestGetCsvRow:
    def test_contains_id(self, meta_csv):
        row = _capture(csv_cli.get_row, meta_csv, 'act1-sc01')
        assert 'act1-sc01' in row

    def test_contains_title(self, meta_csv):
        row = _capture(csv_cli.get_row, meta_csv, 'act1-sc01')
        assert 'The Finest Cartographer' in row

    def test_contains_target_words(self, meta_csv):
        row = _capture(csv_cli.get_row, meta_csv, 'act1-sc01')
        assert '2500' in row

    def test_act2_pov(self, meta_csv):
        row = _capture(csv_cli.get_row, meta_csv, 'act2-sc01')
        assert 'Tessa Merrin' in row

    def test_nonexistent_id(self, meta_csv):
        assert _capture(csv_cli.get_row, meta_csv, 'no-such-id') == ''

    def test_missing_file(self, tmp_path):
        assert _capture(csv_cli.get_row, str(tmp_path / 'nonexistent.csv'), 'act1-sc01') == ''


class TestGetCsvColumn:
    def test_id_column(self, meta_csv):
        col = _capture(csv_cli.get_column, meta_csv, 'id')
        assert 'act1-sc01' in col
        assert 'act2-sc01' in col

    def test_status_column(self, meta_csv):
        col = _capture(csv_cli.get_column, meta_csv, 'status')
        assert 'briefed' in col
        assert 'architecture' in col

    def test_title_column_count(self, meta_csv):
        col = _capture(csv_cli.get_column, meta_csv, 'title')
        lines = [l for l in col.strip().split('\n') if l.strip()]
        assert len(lines) == 6

    def test_nonexistent_column(self, meta_csv):
        assert _capture(csv_cli.get_column, meta_csv, 'nonexistent') == ''

    def test_missing_file(self, tmp_path):
        assert _capture(csv_cli.get_column, str(tmp_path / 'nonexistent.csv'), 'title') == ''


class TestListCsvIds:
    def test_contains_ids(self, meta_csv):
        result = _capture(csv_cli.list_ids, meta_csv)
        assert 'act1-sc01' in result
        assert 'new-x1' in result
        assert 'act2-sc01' in result

    def test_count(self, meta_csv):
        result = _capture(csv_cli.list_ids, meta_csv)
        lines = [l for l in result.strip().split('\n') if l.strip()]
        assert len(lines) == 6

    def test_first_id(self, meta_csv):
        result = _capture(csv_cli.list_ids, meta_csv)
        first = result.strip().split('\n')[0].strip()
        assert first == 'act1-sc01'

    def test_missing_file(self, tmp_path):
        assert _capture(csv_cli.list_ids, str(tmp_path / 'nonexistent.csv')) == ''


class TestUpdateCsvField:
    def test_update_word_count(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.update_field(tmp_csv, 'act1-sc02', 'word_count', '2800')
        assert _capture(csv_cli.get_field, tmp_csv, 'act1-sc02', 'word_count') == '2800'

    def test_other_rows_untouched(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.update_field(tmp_csv, 'act1-sc02', 'word_count', '2800')
        assert _capture(csv_cli.get_field, tmp_csv, 'act1-sc01', 'word_count') == '0'

    def test_update_status(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.update_field(tmp_csv, 'act2-sc01', 'status', 'drafted')
        assert _capture(csv_cli.get_field, tmp_csv, 'act2-sc01', 'status') == 'drafted'

    def test_header_preserved(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.update_field(tmp_csv, 'act2-sc01', 'status', 'drafted')
        with open(tmp_csv) as f:
            header = f.readline()
        assert 'id|seq|title' in header

    def test_missing_file_noop(self, tmp_path):
        # Should not raise
        csv_cli.update_field(str(tmp_path / 'nonexistent.csv'), 'act1-sc01', 'word_count', '999')


class TestAppendCsvRow:
    def test_new_row_readable(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.append_row(tmp_csv, 'act3-sc01|5|The Final Descent|3|Dorren Hayle|The Chasm|5|night||plot|planned|0|3000')
        assert _capture(csv_cli.get_field, tmp_csv, 'act3-sc01', 'title') == 'The Final Descent'
        assert _capture(csv_cli.get_field, tmp_csv, 'act3-sc01', 'status') == 'planned'

    def test_id_count_increased(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.append_row(tmp_csv, 'act3-sc01|5|The Final Descent|3|Dorren Hayle|The Chasm|5|night||plot|planned|0|3000')
        ids = _capture(csv_cli.list_ids, tmp_csv)
        lines = [l for l in ids.strip().split('\n') if l.strip()]
        assert len(lines) == 7

    def test_existing_rows_untouched(self, meta_csv, tmp_path):
        tmp_csv = str(tmp_path / 'scenes.csv')
        shutil.copy(meta_csv, tmp_csv)

        csv_cli.append_row(tmp_csv, 'act3-sc01|5|The Final Descent|3|Dorren Hayle|The Chasm|5|night||plot|planned|0|3000')
        assert _capture(csv_cli.get_field, tmp_csv, 'act1-sc01', 'title') == 'The Finest Cartographer'

    def test_missing_file_noop(self, tmp_path):
        csv_cli.append_row(str(tmp_path / 'nonexistent.csv'), 'test|row')


class TestCrossFileIntent:
    def test_function_field(self, intent_csv):
        result = _capture(csv_cli.get_field, intent_csv, 'act1-sc01', 'function')
        assert 'Establishes Dorren as institutional gatekeeper' in result

    def test_emotional_arc(self, intent_csv):
        result = _capture(csv_cli.get_field, intent_csv, 'new-x1', 'emotional_arc')
        assert result == 'Scholarly calm to urgent alarm'

    def test_id_count(self, intent_csv):
        ids = _capture(csv_cli.list_ids, intent_csv)
        lines = [l for l in ids.strip().split('\n') if l.strip()]
        assert len(lines) == 6


class TestRenumberScenes:
    def test_renumber(self, tmp_path):
        csv_path = str(tmp_path / 'renumber.csv')
        with open(csv_path, 'w') as f:
            f.write('id|seq|title|pov\n')
            f.write('scene-a|5|Scene A|Alice\n')
            f.write('scene-b|10|Scene B|Bob\n')
            f.write('scene-c|2|Scene C|Carol\n')

        csv_cli.renumber_seq(csv_path)

        assert _capture(csv_cli.get_field, csv_path, 'scene-c', 'seq') == '1'
        assert _capture(csv_cli.get_field, csv_path, 'scene-a', 'seq') == '2'
        assert _capture(csv_cli.get_field, csv_path, 'scene-b', 'seq') == '3'
        # Other columns preserved
        assert _capture(csv_cli.get_field, csv_path, 'scene-a', 'title') == 'Scene A'

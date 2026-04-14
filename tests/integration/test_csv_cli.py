"""Tests for storyforge.csv_cli — pipe-delimited CSV operations.

Covers: get_field, get_row, get_column, list_ids, update_field, append_row,
renumber_seq, _read_lines, _write_lines — all with pipe-delimited format,
edge cases (missing file, missing field, empty CSV, CRLF normalization).
"""

import os

import pytest

from storyforge.csv_cli import (
    get_field,
    get_row,
    get_column,
    list_ids,
    update_field,
    append_row,
    renumber_seq,
    _read_lines,
    _write_lines,
    DELIMITER,
)


@pytest.fixture
def sample_csv(tmp_path):
    """Create a sample pipe-delimited CSV file and return its path."""
    path = str(tmp_path / 'test.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('id|name|role|score\n')
        f.write('char-1|Alice|protagonist|85\n')
        f.write('char-2|Bob|supporting|72\n')
        f.write('char-3|Charlie|minor|60\n')
    return path


@pytest.fixture
def empty_csv(tmp_path):
    """Create an empty CSV file (no header, no data)."""
    path = str(tmp_path / 'empty.csv')
    with open(path, 'w', encoding='utf-8') as f:
        pass
    return path


@pytest.fixture
def header_only_csv(tmp_path):
    """Create a CSV with only a header row."""
    path = str(tmp_path / 'header-only.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('id|name|role\n')
    return path


# ============================================================================
# DELIMITER
# ============================================================================

def test_delimiter_is_pipe():
    assert DELIMITER == '|'


# ============================================================================
# _read_lines / _write_lines
# ============================================================================

class TestReadWriteLines:
    def test_read_lines_basic(self, sample_csv):
        lines = _read_lines(sample_csv)
        assert len(lines) == 4
        assert lines[0] == 'id|name|role|score'
        assert lines[1] == 'char-1|Alice|protagonist|85'

    def test_read_lines_normalizes_crlf(self, tmp_path):
        path = str(tmp_path / 'crlf.csv')
        with open(path, 'wb') as f:
            f.write(b'id|name\r\nrow-1|Alice\r\nrow-2|Bob\r\n')
        lines = _read_lines(path)
        assert len(lines) == 3
        assert 'id|name' in lines[0]
        assert '\r' not in lines[0]

    def test_write_lines_atomic(self, tmp_path):
        path = str(tmp_path / 'output.csv')
        _write_lines(path, ['id|name', 'row-1|Alice'])
        lines = _read_lines(path)
        assert len(lines) == 2
        assert lines[0] == 'id|name'

    def test_write_lines_overwrites_existing(self, sample_csv):
        _write_lines(sample_csv, ['id|name', 'new-1|Zara'])
        lines = _read_lines(sample_csv)
        assert len(lines) == 2
        assert lines[1] == 'new-1|Zara'


# ============================================================================
# get_field
# ============================================================================

class TestGetField:
    def test_basic_lookup(self, sample_csv):
        assert get_field(sample_csv, 'char-1', 'name') == 'Alice'
        assert get_field(sample_csv, 'char-2', 'role') == 'supporting'
        assert get_field(sample_csv, 'char-3', 'score') == '60'

    def test_missing_row(self, sample_csv):
        assert get_field(sample_csv, 'nonexistent', 'name') == ''

    def test_missing_field(self, sample_csv):
        assert get_field(sample_csv, 'char-1', 'nonexistent') == ''

    def test_missing_file(self):
        assert get_field('/nonexistent/file.csv', 'char-1', 'name') == ''

    def test_empty_file(self, empty_csv):
        assert get_field(empty_csv, 'char-1', 'name') == ''

    def test_header_only(self, header_only_csv):
        assert get_field(header_only_csv, 'char-1', 'name') == ''

    def test_custom_key_column(self, tmp_path):
        path = str(tmp_path / 'custom-key.csv')
        with open(path, 'w') as f:
            f.write('slug|display_name|type\n')
            f.write('hero|The Hero|protagonist\n')
        assert get_field(path, 'hero', 'display_name', key_col='slug') == 'The Hero'

    def test_fixture_csv(self, meta_csv):
        """Test against the real fixture CSV."""
        result = get_field(meta_csv, 'act1-sc01', 'title')
        assert result == 'The Finest Cartographer'

    def test_fixture_csv_pov(self, meta_csv):
        result = get_field(meta_csv, 'act1-sc02', 'pov')
        assert result == 'Dorren Hayle'


# ============================================================================
# get_row
# ============================================================================

class TestGetRow:
    def test_basic_row(self, sample_csv):
        row = get_row(sample_csv, 'char-1')
        assert row == 'char-1|Alice|protagonist|85'

    def test_missing_row(self, sample_csv):
        assert get_row(sample_csv, 'nonexistent') == ''

    def test_missing_file(self):
        assert get_row('/nonexistent/file.csv', 'char-1') == ''

    def test_empty_file(self, empty_csv):
        assert get_row(empty_csv, 'char-1') == ''

    def test_custom_key_column(self, tmp_path):
        path = str(tmp_path / 'custom-key.csv')
        with open(path, 'w') as f:
            f.write('slug|display_name\n')
            f.write('hero|The Hero\n')
        result = get_row(path, 'hero', key_col='slug')
        assert result == 'hero|The Hero'


# ============================================================================
# get_column
# ============================================================================

class TestGetColumn:
    def test_basic_column(self, sample_csv):
        names = get_column(sample_csv, 'name')
        assert names == ['Alice', 'Bob', 'Charlie']

    def test_id_column(self, sample_csv):
        ids = get_column(sample_csv, 'id')
        assert ids == ['char-1', 'char-2', 'char-3']

    def test_missing_column(self, sample_csv):
        assert get_column(sample_csv, 'nonexistent') == []

    def test_missing_file(self):
        assert get_column('/nonexistent/file.csv', 'name') == []

    def test_empty_file(self, empty_csv):
        assert get_column(empty_csv, 'name') == []

    def test_fixture_csv(self, meta_csv):
        povs = get_column(meta_csv, 'pov')
        assert 'Dorren Hayle' in povs


# ============================================================================
# list_ids
# ============================================================================

class TestListIds:
    def test_basic_ids(self, sample_csv):
        ids = list_ids(sample_csv)
        assert ids == ['char-1', 'char-2', 'char-3']

    def test_missing_file(self):
        assert list_ids('/nonexistent/file.csv') == []

    def test_empty_file(self, empty_csv):
        assert list_ids(empty_csv) == []

    def test_fallback_to_first_column(self, tmp_path):
        """When key_col is not found, should fall back to first column."""
        path = str(tmp_path / 'no-id.csv')
        with open(path, 'w') as f:
            f.write('slug|name\n')
            f.write('hero|Alice\n')
            f.write('sidekick|Bob\n')
        # 'id' column does not exist, falls back to column 0 ('slug')
        ids = list_ids(path)
        assert ids == ['hero', 'sidekick']

    def test_fixture_csv(self, meta_csv):
        ids = list_ids(meta_csv)
        assert 'act1-sc01' in ids
        assert 'act1-sc02' in ids


# ============================================================================
# update_field
# ============================================================================

class TestUpdateField:
    def test_basic_update(self, sample_csv):
        update_field(sample_csv, 'char-1', 'name', 'Alicia')
        assert get_field(sample_csv, 'char-1', 'name') == 'Alicia'

    def test_other_rows_unchanged(self, sample_csv):
        update_field(sample_csv, 'char-1', 'name', 'Alicia')
        assert get_field(sample_csv, 'char-2', 'name') == 'Bob'
        assert get_field(sample_csv, 'char-3', 'name') == 'Charlie'

    def test_update_score(self, sample_csv):
        update_field(sample_csv, 'char-2', 'score', '99')
        assert get_field(sample_csv, 'char-2', 'score') == '99'

    def test_missing_file_noop(self, tmp_path):
        """Updating a nonexistent file should be a no-op."""
        path = str(tmp_path / 'nonexistent.csv')
        update_field(path, 'char-1', 'name', 'test')
        assert not os.path.exists(path)

    def test_missing_field_noop(self, sample_csv):
        """Updating a nonexistent field should be a no-op."""
        original = get_row(sample_csv, 'char-1')
        update_field(sample_csv, 'char-1', 'nonexistent', 'test')
        assert get_row(sample_csv, 'char-1') == original

    def test_missing_row_preserves_file(self, sample_csv):
        """Updating a nonexistent row should not corrupt the file."""
        update_field(sample_csv, 'nonexistent', 'name', 'test')
        assert get_field(sample_csv, 'char-1', 'name') == 'Alice'

    def test_extends_short_row(self, tmp_path):
        """When a row has fewer fields than the target column, extend it."""
        path = str(tmp_path / 'short.csv')
        with open(path, 'w') as f:
            f.write('id|name|role|extra\n')
            f.write('row-1|Alice\n')  # only 2 fields, but header has 4
        update_field(path, 'row-1', 'extra', 'new-value')
        assert get_field(path, 'row-1', 'extra') == 'new-value'


# ============================================================================
# append_row
# ============================================================================

class TestAppendRow:
    def test_basic_append(self, sample_csv):
        append_row(sample_csv, 'char-4|Diana|antagonist|90')
        ids = list_ids(sample_csv)
        assert 'char-4' in ids
        assert get_field(sample_csv, 'char-4', 'name') == 'Diana'

    def test_append_to_header_only(self, header_only_csv):
        append_row(header_only_csv, 'new-1|Zara|minor')
        ids = list_ids(header_only_csv)
        assert ids == ['new-1']

    def test_append_preserves_existing(self, sample_csv):
        append_row(sample_csv, 'char-4|Diana|antagonist|90')
        assert get_field(sample_csv, 'char-1', 'name') == 'Alice'
        assert get_field(sample_csv, 'char-2', 'name') == 'Bob'


# ============================================================================
# renumber_seq
# ============================================================================

class TestRenumberSeq:
    def test_basic_renumbering(self, tmp_path):
        path = str(tmp_path / 'seq.csv')
        with open(path, 'w') as f:
            f.write('id|seq|title\n')
            f.write('c|5|Third\n')
            f.write('a|1|First\n')
            f.write('b|3|Second\n')
        renumber_seq(path)
        lines = _read_lines(path)
        # After renumber, rows should be sorted by original seq and renumbered 1,2,3
        assert len(lines) == 4  # header + 3 rows
        # Check the seq values
        for line in lines[1:]:
            fields = line.split('|')
            seq = int(fields[1])
            assert seq in (1, 2, 3)

    def test_no_seq_column_noop(self, sample_csv):
        """File without seq column should be unchanged."""
        original = _read_lines(sample_csv)
        renumber_seq(sample_csv)
        after = _read_lines(sample_csv)
        assert original == after

    def test_empty_file_noop(self, empty_csv):
        renumber_seq(empty_csv)
        # Should not crash

    def test_renumber_fixture(self, project_dir):
        """Renumbering the fixture scenes.csv should produce sequential seq values."""
        path = os.path.join(project_dir, 'reference', 'scenes.csv')
        renumber_seq(path)
        seqs = get_column(path, 'seq')
        for i, seq in enumerate(seqs, 1):
            assert int(seq) == i

"""Regression tests for CRLF line-ending handling in CSV readers.

Verifies that all CSV reading functions correctly handle:
  1. Pure CRLF files (\\r\\n line endings)
  2. Stray \\r embedded mid-field (from awk-based CSV edits on CRLF files)
  3. Mixed line endings (\\r\\n and \\n)

See GitHub issue #136: Hone/elaborate awk appends break on CRLF line endings.
"""

import os


# ============================================================================
# Helper: write CRLF content to a temp file
# ============================================================================

def _write_crlf(tmp_path, filename, content_bytes):
    """Write raw bytes to a file, returning the path."""
    path = str(tmp_path / filename)
    with open(path, 'wb') as f:
        f.write(content_bytes)
    return path


# ============================================================================
# Pure CRLF line endings
# ============================================================================

CRLF_SCENES = (
    b'id|seq|title|pov|status|word_count|target_words\r\n'
    b'sc-01|1|Opening|Alice|drafted|500|2000\r\n'
    b'sc-02|2|Midpoint|Bob|briefed|0|2500\r\n'
)

CRLF_INTENT = (
    b'id|function|action_sequel|emotional_arc|value_at_stake|'
    b'value_shift|turning_point|characters|on_stage|mice_threads\r\n'
    b'sc-01|Setup|action|calm to tense|trust|+to-|yes|Alice;Bob|Alice|thread-a;thread-b\r\n'
    b'sc-02|Rising|sequel|tense to resolve|loyalty|neutral|no|Bob|Bob|thread-b\r\n'
)

CRLF_BRIEFS = (
    b'id|goal|conflict|outcome\r\n'
    b'sc-01|Establish setting|Internal doubt|Tentative hope\r\n'
    b'sc-02|Raise stakes|External threat|Cliffhanger\r\n'
)


class TestCsvCliCrlf:
    """csv_cli functions handle CRLF files."""

    def test_get_field_crlf(self, tmp_path):
        from storyforge.csv_cli import get_field
        path = _write_crlf(tmp_path, 'scenes.csv', CRLF_SCENES)
        assert get_field(path, 'sc-01', 'title') == 'Opening'
        assert get_field(path, 'sc-02', 'status') == 'briefed'
        # Last field should NOT have \r
        assert get_field(path, 'sc-01', 'target_words') == '2000'

    def test_get_column_crlf(self, tmp_path):
        from storyforge.csv_cli import get_column
        path = _write_crlf(tmp_path, 'scenes.csv', CRLF_SCENES)
        titles = get_column(path, 'title')
        assert titles == ['Opening', 'Midpoint']
        # No \r in any value
        for t in titles:
            assert '\r' not in t

    def test_list_ids_crlf(self, tmp_path):
        from storyforge.csv_cli import list_ids
        path = _write_crlf(tmp_path, 'scenes.csv', CRLF_SCENES)
        ids = list_ids(path)
        assert ids == ['sc-01', 'sc-02']

    def test_update_field_crlf(self, tmp_path):
        from storyforge.csv_cli import get_field, update_field
        path = _write_crlf(tmp_path, 'scenes.csv', CRLF_SCENES)
        update_field(path, 'sc-01', 'word_count', '999')
        assert get_field(path, 'sc-01', 'word_count') == '999'
        # File should now be LF-only (our writers use \n)
        with open(path, 'rb') as f:
            assert b'\r' not in f.read()


class TestElaborateCrlf:
    """elaborate._read_csv and _read_csv_as_map handle CRLF files."""

    def test_read_csv_crlf(self, tmp_path):
        from storyforge.elaborate import _read_csv
        path = _write_crlf(tmp_path, 'scenes.csv', CRLF_SCENES)
        rows = _read_csv(path)
        assert len(rows) == 2
        assert rows[0]['id'] == 'sc-01'
        assert rows[0]['target_words'] == '2000'
        assert rows[1]['status'] == 'briefed'
        # No \r in any value
        for row in rows:
            for v in row.values():
                assert '\r' not in v

    def test_read_csv_as_map_crlf(self, tmp_path):
        from storyforge.elaborate import _read_csv_as_map
        path = _write_crlf(tmp_path, 'intent.csv', CRLF_INTENT)
        m = _read_csv_as_map(path)
        assert 'sc-01' in m
        assert m['sc-01']['mice_threads'] == 'thread-a;thread-b'
        assert '\r' not in m['sc-01']['mice_threads']

    def test_read_csv_as_map_no_cr_in_keys(self, tmp_path):
        from storyforge.elaborate import _read_csv_as_map
        path = _write_crlf(tmp_path, 'scenes.csv', CRLF_SCENES)
        m = _read_csv_as_map(path)
        for row in m.values():
            for k in row:
                assert '\r' not in k


class TestScoringCrlf:
    """scoring._read_csv handles CRLF files."""

    def test_read_csv_crlf(self, tmp_path):
        from storyforge.scoring import _read_csv
        csv_data = (
            b'id|pacing|voice\r\n'
            b'sc-01|7|8\r\n'
            b'sc-02|5|6\r\n'
        )
        path = _write_crlf(tmp_path, 'scores.csv', csv_data)
        header, rows = _read_csv(path)
        assert header == ['id', 'pacing', 'voice']
        assert len(rows) == 2
        assert rows[0] == ['sc-01', '7', '8']
        assert rows[1] == ['sc-02', '5', '6']
        # No \r anywhere
        for field in header:
            assert '\r' not in field
        for row in rows:
            for field in row:
                assert '\r' not in field


class TestVisualizeCrlf:
    """visualize.csv_to_records handles CRLF files."""

    def test_csv_to_records_crlf(self, tmp_path):
        from storyforge.visualize import csv_to_records
        path = _write_crlf(tmp_path, 'scenes.csv', CRLF_SCENES)
        records = csv_to_records(path)
        assert len(records) == 2
        assert records[0]['title'] == 'Opening'
        assert records[1]['target_words'] == '2500'
        for rec in records:
            for v in rec.values():
                assert '\r' not in v


class TestSceneFilterCrlf:
    """scene_filter._read_csv_rows handles CRLF files."""

    def test_read_csv_rows_crlf(self, tmp_path):
        from storyforge.scene_filter import _read_csv_rows
        path = _write_crlf(tmp_path, 'scenes.csv', CRLF_SCENES)
        rows = _read_csv_rows(path)
        assert len(rows) == 2
        assert rows[0]['target_words'] == '2000'
        for row in rows:
            for v in row.values():
                assert '\r' not in v


class TestPromptsCrlf:
    """prompts._read_csv_header_and_rows handles CRLF files."""

    def test_read_csv_header_and_rows_crlf(self, tmp_path):
        from storyforge.prompts import _read_csv_header_and_rows
        path = _write_crlf(tmp_path, 'scores.csv',
                           b'id|pacing|voice\r\nsc-01|7|8\r\nsc-02|5|6\r\n')
        header, rows = _read_csv_header_and_rows(path)
        assert header == ['id', 'pacing', 'voice']
        assert rows[0] == ['sc-01', '7', '8']
        for field in header:
            assert '\r' not in field
        for row in rows:
            for field in row:
                assert '\r' not in field


class TestHistoryCrlf:
    """history.read_history handles CRLF files."""

    def test_read_history_crlf(self, tmp_path):
        from storyforge.history import read_history
        history_dir = tmp_path / 'working' / 'scores'
        history_dir.mkdir(parents=True)
        history_csv = str(history_dir / 'score-history.csv')
        with open(history_csv, 'wb') as f:
            f.write(b'cycle|scene_id|principle|score\r\n')
            f.write(b'1|sc-01|pacing|7\r\n')
            f.write(b'1|sc-02|pacing|5\r\n')
        rows = read_history(str(tmp_path))
        assert len(rows) == 2
        assert rows[0]['score'] == '7'
        assert rows[1]['scene_id'] == 'sc-02'
        for row in rows:
            for v in row.values():
                assert '\r' not in v


class TestRevisionCrlf:
    """revision._read_pipe_csv handles CRLF files."""

    def test_read_pipe_csv_crlf(self, tmp_path):
        from storyforge.revision import _read_pipe_csv
        path = _write_crlf(tmp_path, 'briefs.csv', CRLF_BRIEFS)
        rows = _read_pipe_csv(path)
        assert len(rows) == 2
        assert rows[0]['outcome'] == 'Tentative hope'
        assert rows[1]['conflict'] == 'External threat'
        for row in rows:
            for v in row.values():
                assert '\r' not in v


# ============================================================================
# Embedded \r (awk-induced corruption)
# ============================================================================

# Simulates what happens when awk appends to the last field of a CRLF file:
# the \r ends up INSIDE the field value, not at the line ending.
AWK_CORRUPTED_INTENT = (
    b'id|function|mice_threads\n'
    b'sc-01|Setup|thread-a\r;thread-b\n'  # \r embedded mid-field by awk
    b'sc-02|Rising|thread-c\n'
)


class TestEmbeddedCr:
    """All readers handle stray \\r embedded mid-field (awk corruption)."""

    def test_elaborate_read_csv_embedded_cr(self, tmp_path):
        from storyforge.elaborate import _read_csv
        path = _write_crlf(tmp_path, 'intent.csv', AWK_CORRUPTED_INTENT)
        rows = _read_csv(path)
        assert len(rows) == 2
        # The \r should be stripped, preserving both thread entries
        mice = rows[0]['mice_threads']
        assert '\r' not in mice
        assert 'thread-a' in mice
        assert 'thread-b' in mice

    def test_elaborate_read_csv_as_map_embedded_cr(self, tmp_path):
        from storyforge.elaborate import _read_csv_as_map
        path = _write_crlf(tmp_path, 'intent.csv', AWK_CORRUPTED_INTENT)
        m = _read_csv_as_map(path)
        assert 'sc-01' in m
        mice = m['sc-01']['mice_threads']
        assert '\r' not in mice
        # Both thread entries preserved
        entries = [e.strip() for e in mice.split(';') if e.strip()]
        assert 'thread-a' in entries
        assert 'thread-b' in entries

    def test_csv_cli_embedded_cr(self, tmp_path):
        from storyforge.csv_cli import get_field
        path = _write_crlf(tmp_path, 'intent.csv', AWK_CORRUPTED_INTENT)
        mice = get_field(path, 'sc-01', 'mice_threads')
        assert '\r' not in mice
        assert 'thread-a' in mice
        assert 'thread-b' in mice

    def test_scoring_embedded_cr(self, tmp_path):
        from storyforge.scoring import _read_csv
        data = (
            b'id|pacing|voice\n'
            b'sc-01|7|8\r extra\n'  # \r embedded mid-field
            b'sc-02|5|6\n'
        )
        path = _write_crlf(tmp_path, 'scores.csv', data)
        header, rows = _read_csv(path)
        # After fix: \r is stripped, so "8\r extra" becomes "8 extra"
        assert len(rows) == 2
        assert rows[0] == ['sc-01', '7', '8 extra']
        assert rows[1] == ['sc-02', '5', '6']
        for row in rows:
            for field in row:
                assert '\r' not in field

    def test_visualize_embedded_cr(self, tmp_path):
        from storyforge.visualize import csv_to_records
        path = _write_crlf(tmp_path, 'intent.csv', AWK_CORRUPTED_INTENT)
        records = csv_to_records(path)
        assert len(records) == 2
        mice = records[0]['mice_threads']
        assert '\r' not in mice
        assert 'thread-a' in mice
        assert 'thread-b' in mice


# ============================================================================
# Mixed line endings
# ============================================================================

MIXED_ENDINGS = (
    b'id|title|status\r\n'   # CRLF
    b'sc-01|Opening|drafted\n'  # LF
    b'sc-02|Midpoint|briefed\r\n'  # CRLF
)


class TestMixedLineEndings:
    """Readers handle files with mixed \\r\\n and \\n line endings."""

    def test_elaborate_mixed(self, tmp_path):
        from storyforge.elaborate import _read_csv
        path = _write_crlf(tmp_path, 'scenes.csv', MIXED_ENDINGS)
        rows = _read_csv(path)
        assert len(rows) == 2
        assert rows[0]['title'] == 'Opening'
        assert rows[1]['status'] == 'briefed'
        for row in rows:
            for v in row.values():
                assert '\r' not in v

    def test_csv_cli_mixed(self, tmp_path):
        from storyforge.csv_cli import get_field
        path = _write_crlf(tmp_path, 'scenes.csv', MIXED_ENDINGS)
        assert get_field(path, 'sc-01', 'status') == 'drafted'
        assert get_field(path, 'sc-02', 'status') == 'briefed'

    def test_scoring_mixed(self, tmp_path):
        from storyforge.scoring import _read_csv
        data = b'id|score\r\nsc-01|7\nsc-02|5\r\n'
        path = _write_crlf(tmp_path, 'scores.csv', data)
        header, rows = _read_csv(path)
        assert header == ['id', 'score']
        assert rows == [['sc-01', '7'], ['sc-02', '5']]

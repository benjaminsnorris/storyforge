"""Integration tests for storyforge.scene_filter — scene list building and filtering.

Tests build_scene_list (ordering, status filtering, word-count thresholds) and
apply_scene_filter (all/scenes/single/act/from_seq/range modes) against real
fixture CSV data and purpose-built temp files.
"""

import os

import pytest

from storyforge.scene_filter import build_scene_list, apply_scene_filter, _read_csv_rows


# ---------------------------------------------------------------------------
# _read_csv_rows helper
# ---------------------------------------------------------------------------

class TestReadCsvRows:
    """Low-level CSV reader used by the filter module."""

    def test_reads_pipe_delimited_csv(self, meta_csv):
        rows = _read_csv_rows(meta_csv)
        assert len(rows) > 0
        assert 'id' in rows[0]
        assert 'seq' in rows[0]

    def test_missing_file_returns_empty(self, tmp_path):
        rows = _read_csv_rows(str(tmp_path / 'nonexistent.csv'))
        assert rows == []

    def test_empty_file_returns_empty(self, tmp_path):
        csv = tmp_path / 'empty.csv'
        csv.write_text('')
        assert _read_csv_rows(str(csv)) == []

    def test_header_only_returns_empty(self, tmp_path):
        csv = tmp_path / 'header.csv'
        csv.write_text('id|seq|title\n')
        assert _read_csv_rows(str(csv)) == []

    def test_strips_crlf(self, tmp_path):
        csv = tmp_path / 'crlf.csv'
        csv.write_bytes(b'id|name\r\nalpha|Alpha Name\r\n')
        rows = _read_csv_rows(str(csv))
        assert rows[0]['name'] == 'Alpha Name'


# ---------------------------------------------------------------------------
# build_scene_list
# ---------------------------------------------------------------------------

class TestBuildSceneList:
    """Verify scene list ordering and filtering logic."""

    def test_returns_scenes_sorted_by_seq(self, meta_csv):
        result = build_scene_list(meta_csv)
        # The fixture has seq 1-6: act1-sc01 through act2-sc03
        assert result[0] == 'act1-sc01'
        assert result[1] == 'act1-sc02'
        # act2-sc01 has seq=4, comes after new-x1 (seq=3)
        assert result.index('new-x1') < result.index('act2-sc01')

    def test_excludes_cut_scenes(self, tmp_path):
        csv = tmp_path / 'scenes.csv'
        csv.write_text(
            'id|seq|title|status|word_count\n'
            'sc-a|1|Alpha|draft|500\n'
            'sc-b|2|Beta|cut|600\n'
            'sc-c|3|Gamma|draft|700\n'
        )
        result = build_scene_list(str(csv))
        assert 'sc-b' not in result
        assert result == ['sc-a', 'sc-c']

    def test_excludes_merged_scenes(self, tmp_path):
        csv = tmp_path / 'scenes.csv'
        csv.write_text(
            'id|seq|title|status|word_count\n'
            'sc-a|1|Alpha|draft|500\n'
            'sc-b|2|Beta|merged|600\n'
        )
        result = build_scene_list(str(csv))
        assert result == ['sc-a']

    def test_excludes_scenes_below_min_word_count(self, tmp_path, monkeypatch):
        monkeypatch.setattr('storyforge.scene_filter.MIN_SCENE_WORDS', 100)
        csv = tmp_path / 'scenes.csv'
        csv.write_text(
            'id|seq|title|status|word_count\n'
            'sc-a|1|Alpha|draft|500\n'
            'sc-b|2|Beta|draft|30\n'
        )
        result = build_scene_list(str(csv))
        assert result == ['sc-a']

    def test_includes_scenes_with_zero_word_count(self, tmp_path, monkeypatch):
        """word_count=0 means not-yet-counted, should be included."""
        monkeypatch.setattr('storyforge.scene_filter.MIN_SCENE_WORDS', 50)
        csv = tmp_path / 'scenes.csv'
        csv.write_text(
            'id|seq|title|status|word_count\n'
            'sc-a|1|Alpha|draft|0\n'
        )
        result = build_scene_list(str(csv))
        assert result == ['sc-a']

    def test_includes_scenes_with_empty_word_count(self, tmp_path):
        csv = tmp_path / 'scenes.csv'
        csv.write_text(
            'id|seq|title|status|word_count\n'
            'sc-a|1|Alpha|draft|\n'
        )
        result = build_scene_list(str(csv))
        assert result == ['sc-a']

    def test_missing_csv_raises_system_exit(self, tmp_path):
        with pytest.raises(SystemExit):
            build_scene_list(str(tmp_path / 'missing.csv'))

    def test_empty_result_raises_system_exit(self, tmp_path):
        csv = tmp_path / 'scenes.csv'
        csv.write_text(
            'id|seq|title|status|word_count\n'
            'sc-a|1|Alpha|cut|500\n'
        )
        with pytest.raises(SystemExit):
            build_scene_list(str(csv))

    def test_handles_missing_seq_column_gracefully(self, tmp_path):
        """Scenes with empty seq default to 0 and sort first."""
        csv = tmp_path / 'scenes.csv'
        csv.write_text(
            'id|seq|title|status|word_count\n'
            'sc-a||Alpha|draft|500\n'
            'sc-b|2|Beta|draft|600\n'
        )
        result = build_scene_list(str(csv))
        assert result == ['sc-a', 'sc-b']


# ---------------------------------------------------------------------------
# apply_scene_filter — mode: all
# ---------------------------------------------------------------------------

class TestFilterAll:

    def test_all_returns_full_list(self):
        ids = ['a', 'b', 'c']
        assert apply_scene_filter('unused.csv', ids, 'all') == ['a', 'b', 'c']

    def test_all_returns_copy(self):
        ids = ['a', 'b']
        result = apply_scene_filter('unused.csv', ids, 'all')
        result.append('c')
        assert len(ids) == 2  # original unchanged


# ---------------------------------------------------------------------------
# apply_scene_filter — mode: scenes
# ---------------------------------------------------------------------------

class TestFilterScenes:

    def test_filters_to_requested_scenes(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        result = apply_scene_filter(meta_csv, all_ids, 'scenes', 'act1-sc01,act2-sc01')
        assert result == ['act1-sc01', 'act2-sc01']

    def test_skips_invalid_scene_ids(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        result = apply_scene_filter(meta_csv, all_ids, 'scenes', 'act1-sc01,nonexistent')
        assert result == ['act1-sc01']

    def test_all_invalid_raises_system_exit(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        with pytest.raises(SystemExit):
            apply_scene_filter(meta_csv, all_ids, 'scenes', 'nope,nothing')


# ---------------------------------------------------------------------------
# apply_scene_filter — mode: single
# ---------------------------------------------------------------------------

class TestFilterSingle:

    def test_single_valid_scene(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        result = apply_scene_filter(meta_csv, all_ids, 'single', 'act1-sc02')
        assert result == ['act1-sc02']

    def test_single_invalid_raises_system_exit(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        with pytest.raises(SystemExit):
            apply_scene_filter(meta_csv, all_ids, 'single', 'nonexistent')


# ---------------------------------------------------------------------------
# apply_scene_filter — mode: act
# ---------------------------------------------------------------------------

class TestFilterAct:

    def test_filters_by_part(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        result = apply_scene_filter(meta_csv, all_ids, 'act', '1')
        # Part 1 scenes: act1-sc01, act1-sc02, new-x1
        assert 'act1-sc01' in result
        assert 'act1-sc02' in result
        assert 'new-x1' in result
        # Part 2 scenes should not be included
        assert 'act2-sc01' not in result

    def test_nonexistent_part_raises_system_exit(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        with pytest.raises(SystemExit):
            apply_scene_filter(meta_csv, all_ids, 'act', '99')


# ---------------------------------------------------------------------------
# apply_scene_filter — mode: from_seq
# ---------------------------------------------------------------------------

class TestFilterFromSeq:

    def test_from_seq_single_value(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        # seq >= 4 should include act2-sc01 (4), act2-sc02 (5), act2-sc03 (6)
        result = apply_scene_filter(meta_csv, all_ids, 'from_seq', '4')
        assert 'act2-sc01' in result
        assert 'act1-sc01' not in result

    def test_from_seq_range(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        # seq 2-4 should include act1-sc02 (2), new-x1 (3), act2-sc01 (4)
        result = apply_scene_filter(meta_csv, all_ids, 'from_seq', '2-4')
        assert 'act1-sc02' in result
        assert 'new-x1' in result
        assert 'act2-sc01' in result
        assert 'act1-sc01' not in result
        assert 'act2-sc02' not in result

    def test_from_seq_no_match_raises_system_exit(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        with pytest.raises(SystemExit):
            apply_scene_filter(meta_csv, all_ids, 'from_seq', '100')


# ---------------------------------------------------------------------------
# apply_scene_filter — mode: range
# ---------------------------------------------------------------------------

class TestFilterRange:

    def test_range_inclusive(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        result = apply_scene_filter(meta_csv, all_ids, 'range', 'act1-sc02', 'act2-sc01')
        assert result[0] == 'act1-sc02'
        assert 'new-x1' in result
        assert result[-1] == 'act2-sc01'

    def test_range_not_found_raises_system_exit(self, meta_csv):
        all_ids = build_scene_list(meta_csv)
        with pytest.raises(SystemExit):
            apply_scene_filter(meta_csv, all_ids, 'range', 'nonexistent', 'also-nonexistent')


# ---------------------------------------------------------------------------
# apply_scene_filter — unknown mode
# ---------------------------------------------------------------------------

class TestFilterUnknown:

    def test_unknown_mode_raises_system_exit(self, meta_csv):
        with pytest.raises(SystemExit):
            apply_scene_filter(meta_csv, ['a'], 'banana', 'x')

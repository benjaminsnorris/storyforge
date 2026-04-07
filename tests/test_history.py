"""Tests for history.py — cross-cycle score tracking."""

import csv
import os


DELIMITER = '|'


def _write_scores_csv(path, rows, header):
    """Write a pipe-delimited scores CSV for testing."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header, delimiter=DELIMITER)
        writer.writeheader()
        writer.writerows(rows)


def _read_history_csv(path):
    """Read the history CSV and return list of row dicts."""
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=DELIMITER)
        return list(reader)


class TestIsPrincipleColumn:
    def test_id_not_principle(self):
        from storyforge.history import _is_principle_column
        assert _is_principle_column('id') is False

    def test_rationale_not_principle(self):
        from storyforge.history import _is_principle_column
        assert _is_principle_column('prose_naturalness_rationale') is False
        assert _is_principle_column('voice_consistency_rationale') is False

    def test_score_column_is_principle(self):
        from storyforge.history import _is_principle_column
        assert _is_principle_column('prose_naturalness') is True
        assert _is_principle_column('voice_consistency') is True
        assert _is_principle_column('showing_telling') is True


class TestHistoryPath:
    def test_returns_correct_path(self, tmp_path):
        from storyforge.history import _history_path
        result = _history_path(str(tmp_path))
        expected = os.path.join(str(tmp_path), 'working', 'scores', 'score-history.csv')
        assert result == expected


class TestReadHistory:
    def test_returns_empty_when_no_file(self, tmp_path):
        from storyforge.history import _read_history
        result = _read_history(str(tmp_path))
        assert result == []

    def test_reads_existing_file(self, tmp_path):
        from storyforge.history import _history_path, _read_history
        path = _history_path(str(tmp_path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', newline='', encoding='utf-8') as f:
            f.write('cycle|scene_id|principle|score\n')
            f.write('1|scene-a|prose_naturalness|4\n')
        result = _read_history(str(tmp_path))
        assert len(result) == 1
        assert result[0]['scene_id'] == 'scene-a'
        assert result[0]['score'] == '4'

    def test_coerces_none_to_empty_string(self, tmp_path):
        from storyforge.history import _history_path, _read_history
        path = _history_path(str(tmp_path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Write a row with fewer fields than header (causes None in DictReader)
        with open(path, 'w', newline='', encoding='utf-8') as f:
            f.write('cycle|scene_id|principle|score\n')
            f.write('1|scene-a|prose_naturalness\n')  # missing score
        result = _read_history(str(tmp_path))
        assert result[0]['score'] == ''


class TestAppendCycle:
    def _make_scores_dir(self, tmp_path, rows, header=None):
        """Create a scores directory with scene-scores.csv."""
        scores_dir = tmp_path / 'scores'
        scores_dir.mkdir(parents=True)
        if header is None:
            header = ['id', 'prose_naturalness', 'prose_naturalness_rationale',
                      'voice_consistency', 'voice_consistency_rationale']
        _write_scores_csv(
            str(scores_dir / 'scene-scores.csv'),
            rows,
            header,
        )
        return str(scores_dir)

    def test_creates_file_if_not_exists(self, tmp_path):
        from storyforge.history import append_cycle, _history_path
        scores_dir = self._make_scores_dir(tmp_path, [
            {'id': 'scene-a', 'prose_naturalness': '4',
             'prose_naturalness_rationale': 'Good',
             'voice_consistency': '3', 'voice_consistency_rationale': 'OK'},
        ])
        project_dir = str(tmp_path)
        count = append_cycle(scores_dir, 1, project_dir)
        assert count == 2  # 2 principles × 1 scene
        path = _history_path(project_dir)
        assert os.path.exists(path)
        rows = _read_history_csv(path)
        assert len(rows) == 2

    def test_file_has_correct_header(self, tmp_path):
        from storyforge.history import append_cycle, _history_path
        scores_dir = self._make_scores_dir(tmp_path, [
            {'id': 'scene-a', 'prose_naturalness': '4',
             'prose_naturalness_rationale': 'x',
             'voice_consistency': '3', 'voice_consistency_rationale': 'y'},
        ])
        append_cycle(scores_dir, 1, str(tmp_path))
        path = _history_path(str(tmp_path))
        with open(path) as f:
            header_line = f.readline().strip()
        assert header_line == 'cycle|scene_id|principle|score'

    def test_appends_to_existing_file(self, tmp_path):
        from storyforge.history import append_cycle, _history_path
        scores_dir = self._make_scores_dir(tmp_path, [
            {'id': 'scene-a', 'prose_naturalness': '4',
             'prose_naturalness_rationale': 'x',
             'voice_consistency': '3', 'voice_consistency_rationale': 'y'},
        ])
        project_dir = str(tmp_path)
        append_cycle(scores_dir, 1, project_dir)
        # Second call with cycle 2
        _write_scores_csv(
            os.path.join(scores_dir, 'scene-scores.csv'),
            [{'id': 'scene-a', 'prose_naturalness': '5',
              'prose_naturalness_rationale': 'Better',
              'voice_consistency': '4', 'voice_consistency_rationale': 'Improved'}],
            ['id', 'prose_naturalness', 'prose_naturalness_rationale',
             'voice_consistency', 'voice_consistency_rationale'],
        )
        count2 = append_cycle(scores_dir, 2, project_dir)
        rows = _read_history_csv(_history_path(project_dir))
        assert len(rows) == 4  # 2 cycles × 2 principles × 1 scene
        cycles = [r['cycle'] for r in rows]
        assert '1' in cycles
        assert '2' in cycles

    def test_skips_non_principle_columns(self, tmp_path):
        from storyforge.history import append_cycle
        scores_dir = self._make_scores_dir(tmp_path, [
            {'id': 'scene-a', 'prose_naturalness': '4',
             'prose_naturalness_rationale': 'x',
             'voice_consistency': '3', 'voice_consistency_rationale': 'y'},
        ])
        count = append_cycle(scores_dir, 1, str(tmp_path))
        # Should only count prose_naturalness and voice_consistency, not id or rationale
        assert count == 2

    def test_skips_id_column(self, tmp_path):
        from storyforge.history import append_cycle, _history_path
        scores_dir = self._make_scores_dir(tmp_path, [
            {'id': 'scene-a', 'prose_naturalness': '4',
             'prose_naturalness_rationale': 'x',
             'voice_consistency': '3', 'voice_consistency_rationale': 'y'},
        ])
        append_cycle(scores_dir, 1, str(tmp_path))
        rows = _read_history_csv(_history_path(str(tmp_path)))
        principles = [r['principle'] for r in rows]
        assert 'id' not in principles
        assert 'prose_naturalness_rationale' not in principles

    def test_multiple_scenes(self, tmp_path):
        from storyforge.history import append_cycle
        scores_dir = self._make_scores_dir(tmp_path, [
            {'id': 'scene-a', 'prose_naturalness': '4',
             'prose_naturalness_rationale': 'x',
             'voice_consistency': '3', 'voice_consistency_rationale': 'y'},
            {'id': 'scene-b', 'prose_naturalness': '2',
             'prose_naturalness_rationale': 'weak',
             'voice_consistency': '5', 'voice_consistency_rationale': 'great'},
        ])
        count = append_cycle(scores_dir, 1, str(tmp_path))
        assert count == 4  # 2 scenes × 2 principles

    def test_returns_zero_when_no_scores_file(self, tmp_path):
        from storyforge.history import append_cycle
        scores_dir = str(tmp_path / 'nonexistent')
        os.makedirs(scores_dir)
        count = append_cycle(scores_dir, 1, str(tmp_path))
        assert count == 0

    def test_creates_intermediate_directories(self, tmp_path):
        from storyforge.history import append_cycle, _history_path
        scores_dir = self._make_scores_dir(tmp_path, [
            {'id': 'scene-a', 'prose_naturalness': '4',
             'prose_naturalness_rationale': 'x',
             'voice_consistency': '3', 'voice_consistency_rationale': 'y'},
        ])
        # project_dir without working/scores existing
        project_dir = str(tmp_path / 'new-project')
        os.makedirs(project_dir)
        append_cycle(scores_dir, 1, project_dir)
        assert os.path.exists(_history_path(project_dir))


class TestGetSceneHistory:
    def _setup_history(self, project_dir, rows):
        """Write rows to score-history.csv."""
        from storyforge.history import _history_path, HISTORY_HEADER
        path = _history_path(project_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=HISTORY_HEADER, delimiter=DELIMITER)
            writer.writeheader()
            writer.writerows(rows)

    def test_returns_empty_when_no_file(self, tmp_path):
        from storyforge.history import get_scene_history
        result = get_scene_history(str(tmp_path), 'scene-a', 'prose_naturalness')
        assert result == []

    def test_returns_tuples_for_scene_principle(self, tmp_path):
        from storyforge.history import get_scene_history
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '3'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
        ])
        result = get_scene_history(str(tmp_path), 'scene-a', 'prose_naturalness')
        assert result == [(1, 3.0), (2, 4.0)]

    def test_filters_by_scene_id(self, tmp_path):
        from storyforge.history import get_scene_history
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '3'},
            {'cycle': '1', 'scene_id': 'scene-b', 'principle': 'prose_naturalness', 'score': '5'},
        ])
        result = get_scene_history(str(tmp_path), 'scene-a', 'prose_naturalness')
        assert len(result) == 1
        assert result[0] == (1, 3.0)

    def test_filters_by_principle(self, tmp_path):
        from storyforge.history import get_scene_history
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '3'},
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'voice_consistency', 'score': '5'},
        ])
        result = get_scene_history(str(tmp_path), 'scene-a', 'prose_naturalness')
        assert len(result) == 1
        assert result[0] == (1, 3.0)

    def test_sorted_by_cycle(self, tmp_path):
        from storyforge.history import get_scene_history
        # Write out of order
        self._setup_history(str(tmp_path), [
            {'cycle': '3', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '5'},
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '3'},
        ])
        result = get_scene_history(str(tmp_path), 'scene-a', 'prose_naturalness')
        cycles = [c for c, s in result]
        assert cycles == [1, 2, 3]

    def test_returns_empty_for_unknown_scene(self, tmp_path):
        from storyforge.history import get_scene_history
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '3'},
        ])
        result = get_scene_history(str(tmp_path), 'scene-z', 'prose_naturalness')
        assert result == []


class TestDetectStalls:
    def _setup_history(self, project_dir, rows):
        from storyforge.history import _history_path, HISTORY_HEADER
        path = _history_path(project_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=HISTORY_HEADER, delimiter=DELIMITER)
            writer.writeheader()
            writer.writerows(rows)

    def test_returns_empty_when_no_history(self, tmp_path):
        from storyforge.history import detect_stalls
        result = detect_stalls(str(tmp_path), 'prose_naturalness')
        assert result == []

    def test_detects_scene_stuck_at_low_score(self, tmp_path):
        from storyforge.history import detect_stalls
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
        ])
        result = detect_stalls(str(tmp_path), 'prose_naturalness', min_cycles=2, max_score=3.0)
        assert len(result) == 1
        assert result[0]['scene_id'] == 'scene-a'
        assert result[0]['cycles_stalled'] == 2

    def test_no_stall_when_improved(self, tmp_path):
        from storyforge.history import detect_stalls
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
        ])
        result = detect_stalls(str(tmp_path), 'prose_naturalness', min_cycles=2, max_score=3.0)
        assert result == []

    def test_no_stall_when_above_max_score(self, tmp_path):
        from storyforge.history import detect_stalls
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
        ])
        result = detect_stalls(str(tmp_path), 'prose_naturalness', min_cycles=2, max_score=3.0)
        assert result == []

    def test_no_stall_when_fewer_than_min_cycles(self, tmp_path):
        from storyforge.history import detect_stalls
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
        ])
        result = detect_stalls(str(tmp_path), 'prose_naturalness', min_cycles=2, max_score=3.0)
        assert result == []

    def test_stall_uses_most_recent_cycles(self, tmp_path):
        """If old cycles were low but recent ones improved, no stall."""
        from storyforge.history import detect_stalls
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '3', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '5'},
        ])
        result = detect_stalls(str(tmp_path), 'prose_naturalness', min_cycles=2, max_score=3.0)
        assert result == []

    def test_stall_result_has_scores(self, tmp_path):
        from storyforge.history import detect_stalls
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '3'},
        ])
        result = detect_stalls(str(tmp_path), 'prose_naturalness', min_cycles=2, max_score=3.0)
        assert len(result) == 1
        assert 'scores' in result[0]
        assert result[0]['scores'] == [(1, 2.0), (2, 3.0)]

    def test_multiple_scenes_mixed_stall(self, tmp_path):
        from storyforge.history import detect_stalls
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '1', 'scene_id': 'scene-b', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '2', 'scene_id': 'scene-b', 'principle': 'prose_naturalness', 'score': '5'},
        ])
        result = detect_stalls(str(tmp_path), 'prose_naturalness', min_cycles=2, max_score=3.0)
        assert len(result) == 1
        assert result[0]['scene_id'] == 'scene-a'

    def test_filters_by_principle(self, tmp_path):
        from storyforge.history import detect_stalls
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'voice_consistency', 'score': '2'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'voice_consistency', 'score': '2'},
        ])
        result = detect_stalls(str(tmp_path), 'prose_naturalness', min_cycles=2, max_score=3.0)
        # Should only check prose_naturalness
        assert len(result) == 1


class TestDetectRegressions:
    def _setup_history(self, project_dir, rows):
        from storyforge.history import _history_path, HISTORY_HEADER
        path = _history_path(project_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=HISTORY_HEADER, delimiter=DELIMITER)
            writer.writeheader()
            writer.writerows(rows)

    def test_returns_empty_when_no_history(self, tmp_path):
        from storyforge.history import detect_regressions
        result = detect_regressions(str(tmp_path), 'prose_naturalness')
        assert result == []

    def test_detects_score_drop(self, tmp_path):
        from storyforge.history import detect_regressions
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
        ])
        result = detect_regressions(str(tmp_path), 'prose_naturalness', threshold=-0.5)
        assert len(result) == 1
        r = result[0]
        assert r['scene_id'] == 'scene-a'
        assert r['from_cycle'] == 1
        assert r['to_cycle'] == 2
        assert r['from_score'] == 4.0
        assert r['to_score'] == 2.0
        assert r['delta'] == -2.0

    def test_ignores_stable_scores(self, tmp_path):
        from storyforge.history import detect_regressions
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
        ])
        result = detect_regressions(str(tmp_path), 'prose_naturalness', threshold=-0.5)
        assert result == []

    def test_ignores_improving_scores(self, tmp_path):
        from storyforge.history import detect_regressions
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '3'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '5'},
        ])
        result = detect_regressions(str(tmp_path), 'prose_naturalness', threshold=-0.5)
        assert result == []

    def test_ignores_small_drop_within_threshold(self, tmp_path):
        from storyforge.history import detect_regressions
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '3.7'},
        ])
        result = detect_regressions(str(tmp_path), 'prose_naturalness', threshold=-0.5)
        assert result == []

    def test_filters_by_principle(self, tmp_path):
        from storyforge.history import detect_regressions
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'voice_consistency', 'score': '4'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'voice_consistency', 'score': '2'},
        ])
        result = detect_regressions(str(tmp_path), 'prose_naturalness', threshold=-0.5)
        assert len(result) == 1

    def test_multiple_scenes(self, tmp_path):
        from storyforge.history import detect_regressions
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
            {'cycle': '2', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '2'},
            {'cycle': '1', 'scene_id': 'scene-b', 'principle': 'prose_naturalness', 'score': '3'},
            {'cycle': '2', 'scene_id': 'scene-b', 'principle': 'prose_naturalness', 'score': '4'},
        ])
        result = detect_regressions(str(tmp_path), 'prose_naturalness', threshold=-0.5)
        assert len(result) == 1
        assert result[0]['scene_id'] == 'scene-a'

    def test_returns_empty_with_single_cycle(self, tmp_path):
        from storyforge.history import detect_regressions
        self._setup_history(str(tmp_path), [
            {'cycle': '1', 'scene_id': 'scene-a', 'principle': 'prose_naturalness', 'score': '4'},
        ])
        result = detect_regressions(str(tmp_path), 'prose_naturalness')
        assert result == []

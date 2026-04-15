"""Tests for evaluation staleness detection."""

import os
import pytest


class TestIsFullLlmCycle:
    def test_deterministic_only_returns_false(self, tmp_path):
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-1')
        os.makedirs(cycle_dir)
        with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
            f.write('scene_id|principle|score\n')
            f.write('s01|avoid_passive|3.5\n')
            f.write('s01|avoid_adverbs|4.0\n')
            f.write('s01|economy_clarity|3.8\n')
            f.write('s01|prose_repetition|4.2\n')
            f.write('s01|no_weather_dreams|5.0\n')
            f.write('s01|sentence_as_thought|3.9\n')

        assert is_full_llm_cycle(cycle_dir) is False

    def test_full_llm_returns_true(self, tmp_path):
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-2')
        os.makedirs(cycle_dir)
        with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
            f.write('scene_id|principle|score\n')
            f.write('s01|avoid_passive|3.5\n')
            f.write('s01|prose_naturalness|2.8\n')
            f.write('s01|dialogue_authenticity|3.2\n')

        assert is_full_llm_cycle(cycle_dir) is True

    def test_missing_scores_file_returns_false(self, tmp_path):
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-3')
        os.makedirs(cycle_dir)
        assert is_full_llm_cycle(cycle_dir) is False

    def test_empty_scores_file_returns_false(self, tmp_path):
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-4')
        os.makedirs(cycle_dir)
        with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
            f.write('scene_id|principle|score\n')

        assert is_full_llm_cycle(cycle_dir) is False


class TestWordCountSnapshot:
    def test_write_snapshot(self, tmp_path):
        from storyforge.cmd_evaluate import _write_word_count_snapshot

        eval_dir = str(tmp_path / 'eval-20260415')
        os.makedirs(eval_dir)
        ref_dir = str(tmp_path / 'reference')
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|First|1|Alice|drafted|2847|3000\n')
            f.write('s02|2|Second|1|Bob|drafted|3102|3000\n')

        _write_word_count_snapshot(eval_dir, str(tmp_path))

        snapshot = os.path.join(eval_dir, 'word-counts.csv')
        assert os.path.isfile(snapshot)

        with open(snapshot) as f:
            content = f.read()
        assert 'id|word_count' in content
        assert 's01|2847' in content
        assert 's02|3102' in content

    def test_write_snapshot_skips_zero_wordcount(self, tmp_path):
        from storyforge.cmd_evaluate import _write_word_count_snapshot

        eval_dir = str(tmp_path / 'eval-20260415')
        os.makedirs(eval_dir)
        ref_dir = str(tmp_path / 'reference')
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|First|1|Alice|drafted|2847|3000\n')
            f.write('s02|2|Second|1|Bob|outline|0|3000\n')

        _write_word_count_snapshot(eval_dir, str(tmp_path))

        with open(os.path.join(eval_dir, 'word-counts.csv')) as f:
            content = f.read()
        assert 's01|2847' in content
        assert 's02' not in content

    def test_write_snapshot_no_scenes_csv(self, tmp_path):
        from storyforge.cmd_evaluate import _write_word_count_snapshot

        eval_dir = str(tmp_path / 'eval-20260415')
        os.makedirs(eval_dir)

        _write_word_count_snapshot(eval_dir, str(tmp_path))
        assert not os.path.isfile(os.path.join(eval_dir, 'word-counts.csv'))

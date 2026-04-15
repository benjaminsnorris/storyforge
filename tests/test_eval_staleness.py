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

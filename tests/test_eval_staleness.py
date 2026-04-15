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

    def test_wide_format_full_llm(self, tmp_path):
        """Wide format: principles as column headers, not a 'principle' column."""
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-5')
        os.makedirs(cycle_dir)
        with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
            f.write('id|avoid_passive|prose_naturalness|dialogue_authenticity\n')
            f.write('s01|3.5|2.8|3.2\n')

        assert is_full_llm_cycle(cycle_dir) is True

    def test_wide_format_deterministic_only(self, tmp_path):
        from storyforge.scoring import is_full_llm_cycle

        cycle_dir = str(tmp_path / 'cycle-6')
        os.makedirs(cycle_dir)
        with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
            f.write('id|avoid_passive|avoid_adverbs|economy_clarity|prose_repetition|no_weather_dreams|sentence_as_thought\n')
            f.write('s01|3.5|4.0|3.8|4.2|5.0|3.9\n')

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


class TestCheckEvalStaleness:
    def _setup_project(self, tmp_path, eval_date='20260408-120000',
                       snapshot_words=None, current_words=None,
                       full_cycles_after_eval=0, det_cycles_after_eval=0):
        """Build a minimal project with eval dir and scoring cycles."""
        project_dir = str(tmp_path / 'project')
        eval_base = os.path.join(project_dir, 'working', 'evaluations')
        scores_base = os.path.join(project_dir, 'working', 'scores')
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(eval_base)
        os.makedirs(scores_base)
        os.makedirs(ref_dir)

        # Create eval dir with optional word count snapshot
        eval_dir = os.path.join(eval_base, f'eval-{eval_date}')
        os.makedirs(eval_dir)
        with open(os.path.join(eval_dir, 'synthesis.md'), 'w') as f:
            f.write('Evaluation summary')

        if snapshot_words:
            with open(os.path.join(eval_dir, 'word-counts.csv'), 'w') as f:
                f.write('id|word_count\n')
                for sid, wc in snapshot_words.items():
                    f.write(f'{sid}|{wc}\n')

        # Create current scenes.csv
        words = current_words or snapshot_words or {'s01': 3000}
        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            for i, (sid, wc) in enumerate(words.items(), 1):
                f.write(f'{sid}|{i}|Scene {i}|1|Alice|drafted|{wc}|3000\n')

        # Create scoring cycles (deterministic-only)
        for c in range(1, det_cycles_after_eval + 1):
            cycle_dir = os.path.join(scores_base, f'cycle-{c}')
            os.makedirs(cycle_dir)
            with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
                f.write('scene_id|principle|score\n')
                f.write('s01|avoid_passive|3.5\n')

        # Create full LLM cycles (numbered after deterministic)
        offset = det_cycles_after_eval
        for c in range(1, full_cycles_after_eval + 1):
            cycle_dir = os.path.join(scores_base, f'cycle-{offset + c}')
            os.makedirs(cycle_dir)
            with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
                f.write('scene_id|principle|score\n')
                f.write('s01|avoid_passive|3.5\n')
                f.write('s01|prose_naturalness|2.8\n')

        # storyforge.yaml
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        return project_dir

    def test_no_eval_is_stale(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working', 'evaluations'))
        result = check_eval_staleness(project_dir)
        assert result['stale'] is True
        assert 'no evaluation found' in result['reasons']

    def test_fresh_eval_no_changes(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        words = {'s01': 3000, 's02': 2500}
        project_dir = self._setup_project(tmp_path,
            snapshot_words=words, current_words=words)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is False
        assert result['word_delta_pct'] == 0.0
        assert result['score_runs_since'] == 0

    def test_stale_by_word_delta(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        snapshot = {'s01': 3000, 's02': 2500, 's03': 2000}  # total 7500
        current = {'s01': 4000, 's02': 3500, 's03': 2000}   # delta=2000, 26.7%
        project_dir = self._setup_project(tmp_path,
            snapshot_words=snapshot, current_words=current)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is True
        assert result['word_delta_pct'] > 0.20
        assert any('word delta' in r for r in result['reasons'])

    def test_not_stale_below_word_threshold(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        snapshot = {'s01': 3000, 's02': 2500}  # total 5500
        current = {'s01': 3200, 's02': 2600}   # delta=300, 5.5%
        project_dir = self._setup_project(tmp_path,
            snapshot_words=snapshot, current_words=current)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is False
        assert result['word_delta_pct'] < 0.20

    def test_stale_by_full_score_runs(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        words = {'s01': 3000}
        project_dir = self._setup_project(tmp_path,
            snapshot_words=words, current_words=words,
            full_cycles_after_eval=2)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is True
        assert result['score_runs_since'] >= 2
        assert any('score runs' in r for r in result['reasons'])

    def test_deterministic_cycles_dont_count(self, tmp_path):
        from storyforge.scoring import check_eval_staleness

        words = {'s01': 3000}
        project_dir = self._setup_project(tmp_path,
            snapshot_words=words, current_words=words,
            det_cycles_after_eval=5, full_cycles_after_eval=1)
        result = check_eval_staleness(project_dir)
        assert result['stale'] is False
        assert result['score_runs_since'] == 1

    def test_no_snapshot_still_works(self, tmp_path):
        """Old evals without word-counts.csv should not crash."""
        from storyforge.scoring import check_eval_staleness

        project_dir = self._setup_project(tmp_path,
            snapshot_words=None, current_words={'s01': 3000})
        result = check_eval_staleness(project_dir)
        assert result['word_delta_pct'] == 0.0
        assert result['stale'] is False

    def test_nonstandard_eval_name_picks_most_recent(self, tmp_path):
        """Non-standard eval names (eval-manual-*) should not break sorting."""
        from storyforge.scoring import check_eval_staleness
        import time

        project_dir = str(tmp_path / 'project')
        eval_base = os.path.join(project_dir, 'working', 'evaluations')
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(eval_base)
        os.makedirs(os.path.join(project_dir, 'working', 'scores'))
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|drafted|3000|3000\n')

        # Create an older standard eval
        older = os.path.join(eval_base, 'eval-20260408-190141')
        os.makedirs(older)
        with open(os.path.join(older, 'synthesis.md'), 'w') as f:
            f.write('older')

        # Small delay to ensure different mtime
        time.sleep(0.05)

        # Create a newer non-standard eval (lexicographically after the standard one)
        newer = os.path.join(eval_base, 'eval-manual-line-editor-20260331')
        os.makedirs(newer)
        with open(os.path.join(newer, 'synthesis.md'), 'w') as f:
            f.write('newer')

        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        result = check_eval_staleness(project_dir)
        # Should pick the newer one by mtime, not the lexicographically last one
        assert result['eval_dir'] == newer

    def test_nonstandard_eval_name_extracts_date_from_mtime(self, tmp_path):
        """Eval names without a YYYYMMDD prefix should get date from mtime."""
        from storyforge.scoring import check_eval_staleness

        project_dir = str(tmp_path / 'project')
        eval_base = os.path.join(project_dir, 'working', 'evaluations')
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(eval_base)
        os.makedirs(os.path.join(project_dir, 'working', 'scores'))
        os.makedirs(ref_dir)

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|drafted|3000|3000\n')

        eval_dir = os.path.join(eval_base, 'eval-manual-custom-name')
        os.makedirs(eval_dir)
        with open(os.path.join(eval_dir, 'synthesis.md'), 'w') as f:
            f.write('test')

        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        result = check_eval_staleness(project_dir)
        # Date should be extracted from mtime, should be 8 digits
        assert result['eval_date'] is not None
        assert len(result['eval_date']) == 8
        assert result['eval_date'].isdigit()

    def test_wide_format_cycles_detected(self, tmp_path):
        """Full LLM cycles in wide format (principles as columns) should be counted."""
        from storyforge.scoring import check_eval_staleness

        words = {'s01': 3000}
        project_dir = str(tmp_path / 'project')
        eval_base = os.path.join(project_dir, 'working', 'evaluations')
        scores_base = os.path.join(project_dir, 'working', 'scores')
        ref_dir = os.path.join(project_dir, 'reference')
        os.makedirs(eval_base)
        os.makedirs(scores_base)
        os.makedirs(ref_dir)

        # Create eval with snapshot
        eval_dir = os.path.join(eval_base, 'eval-20260408-120000')
        os.makedirs(eval_dir)
        with open(os.path.join(eval_dir, 'synthesis.md'), 'w') as f:
            f.write('Eval')
        with open(os.path.join(eval_dir, 'word-counts.csv'), 'w') as f:
            f.write('id|word_count\ns01|3000\n')

        with open(os.path.join(ref_dir, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|drafted|3000|3000\n')

        # Create 2 full LLM cycles in wide format
        for c in (1, 2):
            cycle_dir = os.path.join(scores_base, f'cycle-{c}')
            os.makedirs(cycle_dir)
            with open(os.path.join(cycle_dir, 'scene-scores.csv'), 'w') as f:
                f.write('id|avoid_passive|prose_naturalness|dialogue_authenticity\n')
                f.write('s01|3.5|2.8|3.2\n')

        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')

        result = check_eval_staleness(project_dir)
        assert result['score_runs_since'] == 2
        assert result['stale'] is True

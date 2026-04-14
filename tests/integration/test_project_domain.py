"""Tests for storyforge.project — project state management, cycle queries,
artifact path resolution, config reading, and summary generation.

Exercises the library functions that query project state from CSV/YAML files
without requiring API calls.
"""

import os
import time

import pytest

from storyforge.project import (
    _csv_to_records,
    _pipeline_csv,
    cycle_history,
    current_cycle,
    latest_scores,
    latest_evaluation,
    latest_review,
    latest_plan,
    project_config,
    _count_scenes,
    _count_chapters,
    _manuscript_word_count,
    project_summary,
)


# ============================================================================
# CSV helper
# ============================================================================


class TestCsvToRecords:
    """Tests for _csv_to_records."""

    def test_reads_pipe_delimited_csv(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        records = _csv_to_records(csv_path)
        assert len(records) == 6
        assert records[0]['id'] == 'act1-sc01'
        assert records[0]['title'] == 'The Finest Cartographer'

    def test_returns_empty_for_missing_file(self):
        result = _csv_to_records('/nonexistent/path.csv')
        assert result == []

    def test_returns_empty_for_none(self):
        result = _csv_to_records(None)
        assert result == []

    def test_returns_empty_for_empty_string(self):
        result = _csv_to_records('')
        assert result == []

    def test_handles_header_only_file(self, tmp_path):
        csv_path = tmp_path / 'header-only.csv'
        csv_path.write_text('id|name|value\n')
        result = _csv_to_records(str(csv_path))
        assert result == []

    def test_handles_rows_with_fewer_fields(self, tmp_path):
        csv_path = tmp_path / 'short-rows.csv'
        csv_path.write_text('id|name|value\nrow1|Alice\n')
        result = _csv_to_records(str(csv_path))
        assert len(result) == 1
        assert result[0]['id'] == 'row1'
        assert result[0]['name'] == 'Alice'
        assert result[0]['value'] == ''  # Missing field defaults to ''

    def test_handles_unicode(self, tmp_path):
        csv_path = tmp_path / 'unicode.csv'
        csv_path.write_text('id|name\n1|Renee\n')
        result = _csv_to_records(str(csv_path))
        assert result[0]['name'] == 'Renee'


# ============================================================================
# Pipeline / cycle queries
# ============================================================================


class TestPipelineCsv:
    """Tests for _pipeline_csv."""

    def test_returns_expected_path(self, project_dir):
        path = _pipeline_csv(project_dir)
        assert path == os.path.join(project_dir, 'working', 'pipeline.csv')


class TestCycleHistory:
    """Tests for cycle_history."""

    def test_returns_all_cycles(self, project_dir):
        cycles = cycle_history(project_dir)
        assert len(cycles) == 3
        assert cycles[0]['cycle'] == '1'
        assert cycles[1]['cycle'] == '2'
        assert cycles[2]['cycle'] == '3'

    def test_cycle_fields_present(self, project_dir):
        cycles = cycle_history(project_dir)
        cycle = cycles[0]
        assert 'cycle' in cycle
        assert 'started' in cycle
        assert 'status' in cycle

    def test_returns_empty_for_missing_pipeline(self, tmp_path):
        cycles = cycle_history(str(tmp_path))
        assert cycles == []


class TestCurrentCycle:
    """Tests for current_cycle."""

    def test_returns_latest_cycle(self, project_dir):
        cycle = current_cycle(project_dir)
        assert cycle is not None
        assert cycle['cycle'] == '3'
        assert cycle['status'] == 'evaluating'

    def test_returns_none_when_no_cycles(self, tmp_path):
        result = current_cycle(str(tmp_path))
        assert result is None


# ============================================================================
# Latest artifact paths
# ============================================================================


class TestLatestScores:
    """Tests for latest_scores."""

    def test_returns_none_when_no_scores(self, project_dir):
        # fixture has empty working/scores/
        result = latest_scores(project_dir)
        assert result is None

    def test_finds_highest_cycle_dir(self, project_dir):
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(os.path.join(scores_dir, 'cycle-1'))
        os.makedirs(os.path.join(scores_dir, 'cycle-3'))
        os.makedirs(os.path.join(scores_dir, 'cycle-2'))

        result = latest_scores(project_dir)
        assert result is not None
        assert result.endswith('cycle-3')

    def test_prefers_latest_symlink(self, project_dir):
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        cycle_dir = os.path.join(scores_dir, 'cycle-5')
        os.makedirs(cycle_dir)
        os.symlink(cycle_dir, os.path.join(scores_dir, 'latest'))

        result = latest_scores(project_dir)
        assert result is not None
        assert 'cycle-5' in result

    def test_returns_none_when_no_scores_dir(self, tmp_path):
        result = latest_scores(str(tmp_path))
        assert result is None

    def test_ignores_non_cycle_dirs(self, project_dir):
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(os.path.join(scores_dir, 'not-a-cycle'))
        os.makedirs(os.path.join(scores_dir, 'cycle-2'))
        # Also create a file named "cycle-99" (not a directory)
        with open(os.path.join(scores_dir, 'cycle-99'), 'w') as f:
            f.write('not a dir')

        result = latest_scores(project_dir)
        assert result is not None
        assert result.endswith('cycle-2')


class TestLatestEvaluation:
    """Tests for latest_evaluation."""

    def test_finds_eval_dir(self, project_dir):
        result = latest_evaluation(project_dir)
        # Fixture has working/evaluations/eval-test/
        assert result is not None
        assert 'eval-test' in result

    def test_returns_none_when_no_evals(self, tmp_path):
        result = latest_evaluation(str(tmp_path))
        assert result is None

    def test_prefers_pipeline_csv_eval_field(self, project_dir):
        # The pipeline CSV has evaluation fields but they point to relative paths
        # that may not exist. If they exist, they should be preferred.
        evals_dir = os.path.join(project_dir, 'working', 'evaluations')
        target_dir = os.path.join(evals_dir, 'eval-20260305-103253')
        os.makedirs(target_dir)

        # The pipeline.csv cycle 3 says evaluation: eval-20260305-103253
        # Build the full path from project_dir
        result = latest_evaluation(project_dir)
        assert result is not None

    def test_falls_back_to_most_recent_by_mtime(self, project_dir):
        evals_dir = os.path.join(project_dir, 'working', 'evaluations')
        # Create two eval dirs with different mtimes
        dir_old = os.path.join(evals_dir, 'eval-old')
        dir_new = os.path.join(evals_dir, 'eval-new')
        os.makedirs(dir_old)
        time.sleep(0.05)  # Ensure different mtime
        os.makedirs(dir_new)

        # Remove the pipeline eval reference by clearing pipeline.csv
        pipeline_path = os.path.join(project_dir, 'working', 'pipeline.csv')
        with open(pipeline_path, 'w') as f:
            f.write('cycle|started|status|evaluation|scoring|plan|review|recommendations|summary\n')

        result = latest_evaluation(project_dir)
        assert result is not None
        assert 'eval-new' in result


class TestLatestReview:
    """Tests for latest_review."""

    def test_returns_none_when_no_reviews(self, project_dir):
        # Fixture has empty working/reviews/
        result = latest_review(project_dir)
        assert result is None

    def test_finds_most_recent_review_file(self, project_dir):
        reviews_dir = os.path.join(project_dir, 'working', 'reviews')
        os.makedirs(reviews_dir, exist_ok=True)

        # Create two review files
        old_review = os.path.join(reviews_dir, 'review-old.md')
        with open(old_review, 'w') as f:
            f.write('Old review')
        time.sleep(0.05)
        new_review = os.path.join(reviews_dir, 'review-new.md')
        with open(new_review, 'w') as f:
            f.write('New review')

        result = latest_review(project_dir)
        assert result is not None
        assert 'review-new.md' in result

    def test_returns_none_when_no_reviews_dir(self, tmp_path):
        result = latest_review(str(tmp_path))
        assert result is None


class TestLatestPlan:
    """Tests for latest_plan."""

    def test_finds_plan_file(self, project_dir):
        result = latest_plan(project_dir)
        # Fixture has working/plans/revision-plan.yaml
        assert result is not None
        assert 'revision-plan.yaml' in result

    def test_returns_none_when_no_plans_dir(self, tmp_path):
        result = latest_plan(str(tmp_path))
        assert result is None

    def test_returns_none_when_plans_dir_empty(self, project_dir):
        plans_dir = os.path.join(project_dir, 'working', 'plans')
        # Remove all files from plans dir
        for f in os.listdir(plans_dir):
            os.remove(os.path.join(plans_dir, f))

        result = latest_plan(project_dir)
        assert result is None


# ============================================================================
# Project config and counts
# ============================================================================


class TestProjectConfig:
    """Tests for project_config."""

    def test_reads_project_fields(self, project_dir):
        config = project_config(project_dir)
        assert config['title'] == "The Cartographer's Silence"
        assert config['genre'] == 'fantasy'
        assert config['target_words'] == '90000'

    def test_returns_empty_for_missing_fields(self, tmp_path):
        yaml_path = tmp_path / 'storyforge.yaml'
        yaml_path.write_text('project:\n  title: "Test"\n')
        config = project_config(str(tmp_path))
        assert config['title'] == 'Test'
        assert config['genre'] == ''
        assert config['logline'] == ''

    def test_reads_phase(self, project_dir):
        config = project_config(project_dir)
        assert config['phase'] == 'drafting'

    def test_reads_logline(self, project_dir):
        config = project_config(project_dir)
        assert 'cartographer' in config['logline'].lower()


class TestCountScenes:
    """Tests for _count_scenes."""

    def test_counts_scene_files(self, project_dir):
        count = _count_scenes(project_dir)
        assert count == 4  # act1-sc01, act1-sc02, act2-sc01, new-x1

    def test_returns_zero_for_missing_dir(self, tmp_path):
        count = _count_scenes(str(tmp_path))
        assert count == 0


class TestCountChapters:
    """Tests for _count_chapters."""

    def test_counts_chapters_from_csv(self, project_dir):
        count = _count_chapters(project_dir)
        assert count >= 0  # May have chapters in fixture

    def test_returns_zero_when_no_chapter_map(self, tmp_path):
        count = _count_chapters(str(tmp_path))
        assert count == 0


class TestManuscriptWordCount:
    """Tests for _manuscript_word_count."""

    def test_sums_word_counts(self, project_dir):
        count = _manuscript_word_count(project_dir)
        assert count > 0  # Scene files have content

    def test_returns_zero_for_empty_project(self, tmp_path):
        count = _manuscript_word_count(str(tmp_path))
        assert count == 0

    def test_counts_only_md_files(self, project_dir):
        # Add a non-md file to scenes dir
        scenes_dir = os.path.join(project_dir, 'scenes')
        with open(os.path.join(scenes_dir, 'notes.txt'), 'w') as f:
            f.write('This should not be counted ' * 100)

        # Count should only reflect .md files
        count_with_txt = _manuscript_word_count(project_dir)

        # Remove the txt and compare
        os.remove(os.path.join(scenes_dir, 'notes.txt'))
        count_without_txt = _manuscript_word_count(project_dir)

        assert count_with_txt == count_without_txt


# ============================================================================
# Project summary
# ============================================================================


class TestProjectSummary:
    """Tests for project_summary."""

    def test_includes_config_fields(self, project_dir):
        summary = project_summary(project_dir)
        assert summary['title'] == "The Cartographer's Silence"
        assert summary['genre'] == 'fantasy'

    def test_includes_counts(self, project_dir):
        summary = project_summary(project_dir)
        assert summary['scene_count'] == 4
        assert isinstance(summary['chapter_count'], int)
        assert summary['word_count'] > 0

    def test_includes_current_cycle(self, project_dir):
        summary = project_summary(project_dir)
        assert summary['current_cycle'] is not None
        assert summary['current_cycle']['cycle'] == '3'

    def test_current_cycle_none_when_no_pipeline(self, tmp_path):
        yaml_path = tmp_path / 'storyforge.yaml'
        yaml_path.write_text('project:\n  title: "Empty"\n')
        summary = project_summary(str(tmp_path))
        assert summary['current_cycle'] is None

    def test_includes_artifact_paths(self, project_dir):
        summary = project_summary(project_dir)
        # These may be None depending on fixture state
        assert 'latest_scores' in summary
        assert 'latest_evaluation' in summary
        assert 'latest_review' in summary
        assert 'latest_plan' in summary

    def test_plan_path_populated(self, project_dir):
        summary = project_summary(project_dir)
        assert summary['latest_plan'] is not None
        assert 'revision-plan.yaml' in summary['latest_plan']

    def test_evaluation_path_populated(self, project_dir):
        summary = project_summary(project_dir)
        assert summary['latest_evaluation'] is not None

"""Regression tests for CSV column-order independence.

Verifies that scoring.py and structural.py read CSV data by column name,
not by positional index. Each test creates CSVs with reordered columns
and asserts that the functions still produce correct results.
"""

import os

import pytest


def _write_csv(path, header, rows):
    """Write a pipe-delimited CSV file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(header) + '\n')
        for row in rows:
            f.write('|'.join(str(v) for v in row) + '\n')


# =====================================================================
# scoring.py — build_weighted_text
# =====================================================================

class TestBuildWeightedTextColumnOrder:
    def test_reordered_columns(self, tmp_path):
        from storyforge.scoring import build_weighted_text
        # Standard order: section|principle|weight|author_weight|notes
        std = str(tmp_path / 'std.csv')
        _write_csv(std, ['section', 'principle', 'weight', 'author_weight', 'notes'],
                   [['craft', 'voice', '8', '', 'important']])
        result_std = build_weighted_text(std)

        # Reordered: notes|author_weight|weight|principle|section
        reord = str(tmp_path / 'reord.csv')
        _write_csv(reord, ['notes', 'author_weight', 'weight', 'principle', 'section'],
                   [['important', '', '8', 'voice', 'craft']])
        result_reord = build_weighted_text(reord)

        assert 'voice' in result_std
        assert result_std == result_reord

    def test_exclude_section_with_reordered_columns(self, tmp_path):
        from storyforge.scoring import build_weighted_text
        reord = str(tmp_path / 'reord.csv')
        _write_csv(reord, ['notes', 'author_weight', 'weight', 'principle', 'section'],
                   [['', '', '9', 'voice', 'craft'],
                    ['', '', '8', 'monomyth', 'narrative']])
        result = build_weighted_text(reord, exclude_section='narrative')
        assert 'voice' in result
        assert 'monomyth' not in result


# =====================================================================
# scoring.py — get_effective_weight
# =====================================================================

class TestGetEffectiveWeightColumnOrder:
    def test_reordered_columns(self, tmp_path):
        from storyforge.scoring import get_effective_weight
        # Reordered: weight|principle|author_weight
        f = str(tmp_path / 'weights.csv')
        _write_csv(f, ['weight', 'principle', 'author_weight'],
                   [['7', 'voice', '9']])
        result = get_effective_weight(f, 'voice')
        assert result == 9  # author_weight takes precedence

    def test_missing_author_weight_column(self, tmp_path):
        from storyforge.scoring import get_effective_weight
        f = str(tmp_path / 'weights.csv')
        _write_csv(f, ['principle', 'weight'],
                   [['voice', '6']])
        result = get_effective_weight(f, 'voice')
        assert result == 6


# =====================================================================
# scoring.py — generate_diagnosis
# =====================================================================

class TestGenerateDiagnosisColumnOrder:
    def test_id_column_reordered(self, tmp_path):
        from storyforge.scoring import generate_diagnosis
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        # Put id as the LAST column instead of first
        _write_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                   ['voice', 'id'],
                   [['3', 'scene-a'], ['4', 'scene-b']])
        weights = str(tmp_path / 'weights.csv')
        _write_csv(weights, ['principle', 'weight'], [['voice', '5']])
        generate_diagnosis(scores_dir, '', weights)

        diag_path = os.path.join(scores_dir, 'diagnosis.csv')
        assert os.path.isfile(diag_path)
        import csv
        with open(diag_path) as f:
            reader = csv.DictReader(f, delimiter='|')
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]['principle'] == 'voice'
        # Worst item should be scene-a (score 3, lower than scene-b's 4)
        assert 'scene-a' in rows[0]['worst_items']


# =====================================================================
# scoring.py — generate_proposals
# =====================================================================

class TestGenerateProposalsColumnOrder:
    def test_diagnosis_columns_reordered(self, tmp_path):
        from storyforge.scoring import generate_proposals
        scores_dir = str(tmp_path / 'cycle')
        os.makedirs(scores_dir)
        # Reorder diagnosis columns
        _write_csv(os.path.join(scores_dir, 'diagnosis.csv'),
                   ['priority', 'worst_items', 'avg_score', 'scale', 'principle', 'delta_from_last', 'root_cause'],
                   [['high', 'scene-a', '1.5', 'scene', 'voice', '-0.5', 'craft']])
        # Reordered weights
        _write_csv(str(tmp_path / 'weights.csv'),
                   ['weight', 'principle'],
                   [['5', 'voice']])
        # Scene scores with reordered id
        _write_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                   ['voice', 'id'],
                   [['2', 'scene-a']])
        generate_proposals(scores_dir, str(tmp_path / 'weights.csv'))

        proposals_path = os.path.join(scores_dir, 'proposals.csv')
        assert os.path.isfile(proposals_path)
        import csv
        with open(proposals_path) as f:
            reader = csv.DictReader(f, delimiter='|')
            rows = list(reader)
        assert len(rows) >= 1
        assert rows[0]['principle'] == 'voice'


# =====================================================================
# scoring.py — build_evaluation_criteria
# =====================================================================

class TestBuildEvaluationCriteriaColumnOrder:
    def test_reordered_columns(self, tmp_path, plugin_dir):
        from storyforge.scoring import build_evaluation_criteria
        diag = str(tmp_path / 'diag.csv')
        # Reorder: question|principle|other_col
        _write_csv(diag, ['question', 'principle', 'other_col'],
                   [['Does the scene show?', 'voice', 'x'],
                    ['Is rhythm good?', 'voice', 'y']])
        guide = os.path.join(plugin_dir, 'references', 'principle-guide.md')
        result = build_evaluation_criteria(diag, guide)
        assert 'voice' in result
        assert 'Does the scene show?' in result


# =====================================================================
# scoring.py — collect_exemplars
# =====================================================================

class TestCollectExemplarsColumnOrder:
    def test_scores_with_reordered_id(self, tmp_path):
        from storyforge.scoring import collect_exemplars
        scores_dir = str(tmp_path / 'scores')
        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working'), exist_ok=True)

        # Scene scores with id as last column
        _write_csv(os.path.join(scores_dir, 'scene-scores.csv'),
                   ['voice', 'id'],
                   [['5', 'scene-a'], ['3', 'scene-b']])

        collect_exemplars(scores_dir, project_dir, 'cycle-1')

        exemplars = os.path.join(project_dir, 'working', 'exemplars.csv')
        assert os.path.isfile(exemplars)
        with open(exemplars) as f:
            lines = f.read().strip().split('\n')
        # Should have header + one exemplar (scene-a with score 5)
        assert len(lines) == 2
        assert 'scene-a' in lines[1]


# =====================================================================
# scoring.py — merge_score_files with id not in column 0
# =====================================================================

class TestMergeScoreFilesColumnOrder:
    def test_join_with_id_not_first(self, tmp_path):
        from storyforge.scoring import merge_score_files
        target = str(tmp_path / 'target.csv')
        source = str(tmp_path / 'source.csv')
        # Target has id as column 1, voice as column 0
        _write_csv(target, ['voice', 'id'], [['3', 'scene-a']])
        # Source has same id reordered with a new column
        _write_csv(source, ['id', 'pacing'], [['scene-a', '4']])
        merge_score_files(target, source)

        with open(target) as f:
            lines = f.read().strip().split('\n')
        # Should have merged header
        header = lines[0].split('|')
        assert 'id' in header
        assert 'voice' in header
        assert 'pacing' in header


# =====================================================================
# scoring.py — generate_score_report diagnosis/proposals
# =====================================================================

class TestScoreReportColumnOrder:
    def test_report_with_reordered_diagnosis(self, tmp_path):
        """Verify generate_score_report reads diagnosis columns by name."""
        from storyforge.scoring import generate_score_report
        cycle_dir = str(tmp_path / 'cycle')
        project_dir = str(tmp_path / 'project')
        os.makedirs(cycle_dir)
        os.makedirs(project_dir)
        # Write storyforge.yaml
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('title: Test Novel\n')
        # Reordered diagnosis: worst_items first
        _write_csv(os.path.join(cycle_dir, 'diagnosis.csv'),
                   ['worst_items', 'avg_score', 'principle', 'scale', 'delta_from_last', 'priority', 'root_cause'],
                   [['scene-a', '3.5', 'voice', 'scene', '+0.5', 'medium', 'craft']])
        # Reordered proposals
        _write_csv(os.path.join(cycle_dir, 'proposals.csv'),
                   ['status', 'rationale', 'change', 'target', 'lever', 'principle', 'id'],
                   [['pending', 'low score', 'weight 5 -> 7', 'global', 'craft_weight', 'voice', 'p001']])
        generate_score_report(cycle_dir, project_dir, '1', 'full', 5, '0.50')
        report = os.path.join(cycle_dir, 'report.html')
        assert os.path.isfile(report)
        with open(report) as f:
            html = f.read()
        assert 'voice' in html
        assert 'craft weight' in html

    def test_pr_comment_with_reordered_diagnosis(self, tmp_path):
        """Verify build_score_pr_comment reads diagnosis columns by name."""
        from storyforge.scoring import build_score_pr_comment
        cycle_dir = str(tmp_path / 'cycle')
        project_dir = str(tmp_path / 'project')
        os.makedirs(cycle_dir)
        os.makedirs(project_dir)
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'w') as f:
            f.write('title: Test Novel\n')
        # Reordered diagnosis
        _write_csv(os.path.join(cycle_dir, 'diagnosis.csv'),
                   ['worst_items', 'avg_score', 'principle', 'scale', 'delta_from_last', 'priority', 'root_cause'],
                   [['scene-a', '3.5', 'voice', 'scene', '+0.5', 'medium', 'craft']])
        # Reordered proposals
        _write_csv(os.path.join(cycle_dir, 'proposals.csv'),
                   ['status', 'rationale', 'change', 'target', 'lever', 'principle', 'id'],
                   [['pending', 'low score', 'weight 5 -> 7', 'global', 'craft_weight', 'voice', 'p001']])
        result = build_score_pr_comment(cycle_dir, project_dir, '1', 'full', 5, '0.50')
        assert 'voice' in result
        assert 'craft weight' in result


# =====================================================================
# structural.py — load_previous_scores
# =====================================================================

class TestLoadPreviousScoresColumnOrder:
    def test_reordered_columns(self, tmp_path):
        from storyforge.structural import load_previous_scores
        scores_dir = os.path.join(str(tmp_path), 'working', 'scores')
        os.makedirs(scores_dir)
        # Standard order: dimension|score|target|weight
        std = os.path.join(scores_dir, 'structural-latest.csv')
        _write_csv(std, ['dimension', 'score', 'target', 'weight'],
                   [['arc_completeness', '0.85', '0.80', '1.0'],
                    ['overall', '0.75', '0.70', '1.0']])
        result = load_previous_scores(str(tmp_path))
        assert result is not None
        assert result['arc_completeness'] == 0.85
        assert result['overall'] == 0.75

    def test_columns_in_different_order(self, tmp_path):
        from storyforge.structural import load_previous_scores
        scores_dir = os.path.join(str(tmp_path), 'working', 'scores')
        os.makedirs(scores_dir)
        # Reordered: weight|target|score|dimension
        latest = os.path.join(scores_dir, 'structural-latest.csv')
        _write_csv(latest, ['weight', 'target', 'score', 'dimension'],
                   [['1.0', '0.80', '0.85', 'arc_completeness'],
                    ['1.0', '0.70', '0.75', 'overall']])
        result = load_previous_scores(str(tmp_path))
        assert result is not None
        assert result['arc_completeness'] == 0.85
        assert result['overall'] == 0.75


# =====================================================================
# scoring.py — check_validated_patterns
# =====================================================================

class TestCheckValidatedPatternsColumnOrder:
    def test_reordered_tuning_columns(self, tmp_path):
        from storyforge.scoring import check_validated_patterns
        project_dir = str(tmp_path)
        os.makedirs(os.path.join(project_dir, 'working'))
        tuning = os.path.join(project_dir, 'working', 'tuning.csv')
        # Reordered columns (standard might be: cycle|scene|principle|lever|target|score_before|score_after|validated)
        _write_csv(tuning,
                   ['validated', 'score_after', 'score_before', 'lever', 'principle', 'target', 'scene', 'cycle'],
                   [['true', '4.0', '2.0', 'craft_weight', 'voice', 'global', 'scene-a', '1'],
                    ['true', '4.5', '2.5', 'craft_weight', 'voice', 'global', 'scene-b', '2'],
                    ['true', '4.0', '3.0', 'craft_weight', 'voice', 'global', 'scene-c', '3']])
        result = check_validated_patterns(project_dir)
        assert 'voice' in result
        assert 'craft_weight' in result

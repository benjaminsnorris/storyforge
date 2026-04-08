"""Command-level tests for storyforge.cmd_revise module.

Tests parse_args, CSV plan reading/writing, auto-generated plans
(polish, naturalness, structural), scope resolution, and diagnosis
summarization.
"""

import csv
import os

import pytest

from storyforge.cmd_revise import (
    parse_args,
    CSV_PLAN_FIELDS,
    _read_csv_plan,
    _write_csv_plan,
    _count_passes,
    _read_pass_field,
    _update_pass_field,
    _generate_polish_plan,
    _generate_naturalness_plan,
    _summarize_diagnosis,
    _read_diagnosis,
    _detect_upstream_scenes,
)


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    def test_default_args(self):
        args = parse_args([])
        assert args.dry_run is False
        assert args.polish is False
        assert args.naturalness is False
        assert args.structural is False
        assert args.loop is False
        assert args.pass_num == 0
        assert args.max_loops == 5

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_polish(self):
        args = parse_args(['--polish'])
        assert args.polish is True

    def test_naturalness(self):
        args = parse_args(['--naturalness'])
        assert args.naturalness is True

    def test_structural(self):
        args = parse_args(['--structural'])
        assert args.structural is True

    def test_loop(self):
        args = parse_args(['--loop'])
        assert args.loop is True

    def test_max_loops(self):
        args = parse_args(['--max-loops', '10'])
        assert args.max_loops == 10

    def test_pass_num_positional(self):
        args = parse_args(['3'])
        assert args.pass_num == 3

    def test_coaching_override(self):
        args = parse_args(['--coaching', 'strict'])
        assert args.coaching == 'strict'

    def test_interactive(self):
        args = parse_args(['-i'])
        assert args.interactive is True

    def test_skip_initial_score(self):
        args = parse_args(['--skip-initial-score'])
        assert args.skip_initial_score is True


# ============================================================================
# CSV plan helpers
# ============================================================================

class TestCsvPlanHelpers:
    def test_csv_plan_fields_has_expected_columns(self):
        assert 'pass' in CSV_PLAN_FIELDS
        assert 'name' in CSV_PLAN_FIELDS
        assert 'status' in CSV_PLAN_FIELDS
        assert 'fix_location' in CSV_PLAN_FIELDS
        assert len(CSV_PLAN_FIELDS) == 11

    def test_write_and_read_csv_plan(self, tmp_path):
        plan_file = str(tmp_path / 'plan.csv')
        rows = [
            {'pass': '1', 'name': 'test-pass', 'purpose': 'testing',
             'scope': 'full', 'targets': '', 'guidance': 'be good',
             'protection': 'voice', 'findings': '', 'status': 'pending',
             'model_tier': 'opus', 'fix_location': 'craft'},
        ]
        _write_csv_plan(plan_file, rows)
        assert os.path.isfile(plan_file)

        read_back = _read_csv_plan(plan_file)
        assert len(read_back) == 1
        assert read_back[0]['name'] == 'test-pass'
        assert read_back[0]['status'] == 'pending'

    def test_read_nonexistent_plan(self, tmp_path):
        result = _read_csv_plan(str(tmp_path / 'nope.csv'))
        assert result == []

    def test_count_passes(self):
        rows = [{'pass': '1'}, {'pass': '2'}, {'pass': '3'}]
        assert _count_passes(rows) == 3

    def test_read_pass_field(self):
        rows = [
            {'pass': '1', 'name': 'first', 'status': 'done'},
            {'pass': '2', 'name': 'second', 'status': 'pending'},
        ]
        assert _read_pass_field(rows, 1, 'name') == 'first'
        assert _read_pass_field(rows, 2, 'status') == 'pending'

    def test_read_pass_field_out_of_range(self):
        rows = [{'pass': '1', 'name': 'only'}]
        assert _read_pass_field(rows, 5, 'name') == ''

    def test_update_pass_field(self, tmp_path):
        plan_file = str(tmp_path / 'plan.csv')
        rows = [
            {'pass': '1', 'name': 'first', 'purpose': '', 'scope': '',
             'targets': '', 'guidance': '', 'protection': '',
             'findings': '', 'status': 'pending', 'model_tier': '',
             'fix_location': ''},
        ]
        _write_csv_plan(plan_file, rows)
        _update_pass_field(rows, 1, 'status', 'complete', plan_file)
        assert rows[0]['status'] == 'complete'

        # Verify it's persisted
        read_back = _read_csv_plan(plan_file)
        assert read_back[0]['status'] == 'complete'


# ============================================================================
# Auto-generated plans
# ============================================================================

class TestGeneratePolishPlan:
    def test_creates_single_pass(self, tmp_path):
        plan_file = str(tmp_path / 'plans' / 'plan.csv')
        rows = _generate_polish_plan(plan_file)
        assert len(rows) == 1
        assert rows[0]['name'] == 'prose-polish'
        assert rows[0]['status'] == 'pending'
        assert rows[0]['fix_location'] == 'craft'
        assert os.path.isfile(plan_file)

    def test_plan_has_all_fields(self, tmp_path):
        plan_file = str(tmp_path / 'plans' / 'plan.csv')
        rows = _generate_polish_plan(plan_file)
        for field in CSV_PLAN_FIELDS:
            assert field in rows[0]


class TestGenerateNaturalnessPlan:
    def test_creates_three_passes(self, tmp_path):
        plan_file = str(tmp_path / 'plans' / 'plan.csv')
        rows = _generate_naturalness_plan(plan_file)
        assert len(rows) == 3

    def test_pass_names(self, tmp_path):
        plan_file = str(tmp_path / 'plans' / 'plan.csv')
        rows = _generate_naturalness_plan(plan_file)
        names = [r['name'] for r in rows]
        assert 'tricolon-parallelism' in names
        assert 'em-dash-antithesis' in names
        assert 'ai-vocabulary-hedging' in names

    def test_all_pending(self, tmp_path):
        plan_file = str(tmp_path / 'plans' / 'plan.csv')
        rows = _generate_naturalness_plan(plan_file)
        for row in rows:
            assert row['status'] == 'pending'

    def test_all_craft_location(self, tmp_path):
        plan_file = str(tmp_path / 'plans' / 'plan.csv')
        rows = _generate_naturalness_plan(plan_file)
        for row in rows:
            assert row['fix_location'] == 'craft'

    def test_file_is_readable(self, tmp_path):
        plan_file = str(tmp_path / 'plans' / 'plan.csv')
        _generate_naturalness_plan(plan_file)
        read_back = _read_csv_plan(plan_file)
        assert len(read_back) == 3


# ============================================================================
# Diagnosis summarization
# ============================================================================

class TestSummarizeDiagnosis:
    def test_empty_diagnosis(self):
        result = _summarize_diagnosis([])
        assert result['high_count'] == 0
        assert result['medium_count'] == 0
        assert result['overall_avg'] == 0.0

    def test_counts_by_priority(self):
        rows = [
            {'priority': 'high', 'scale': 'scene', 'principle': 'voice',
             'avg_score': '5.0', 'worst_items': 'sc1'},
            {'priority': 'medium', 'scale': 'scene', 'principle': 'prose',
             'avg_score': '6.0', 'worst_items': 'sc2'},
            {'priority': 'low', 'scale': 'scene', 'principle': 'dialogue',
             'avg_score': '7.0', 'worst_items': 'sc3'},
        ]
        result = _summarize_diagnosis(rows)
        assert result['high_count'] == 1
        assert result['medium_count'] == 1
        assert 'voice' in result['high_principles']
        assert 'prose' in result['medium_principles']

    def test_overall_avg(self):
        rows = [
            {'priority': 'high', 'scale': 'scene', 'principle': 'a',
             'avg_score': '4.0', 'worst_items': ''},
            {'priority': 'high', 'scale': 'scene', 'principle': 'b',
             'avg_score': '6.0', 'worst_items': ''},
        ]
        result = _summarize_diagnosis(rows)
        assert abs(result['overall_avg'] - 5.0) < 0.01

    def test_ignores_non_scene_scale(self):
        rows = [
            {'priority': 'high', 'scale': 'act', 'principle': 'pacing',
             'avg_score': '3.0', 'worst_items': ''},
        ]
        result = _summarize_diagnosis(rows)
        assert result['high_count'] == 0


# ============================================================================
# _read_diagnosis
# ============================================================================

class TestReadDiagnosis:
    def test_missing_file(self, tmp_path):
        result = _read_diagnosis(str(tmp_path))
        assert result == []

    def test_with_file(self, tmp_path):
        diag_file = tmp_path / 'diagnosis.csv'
        diag_file.write_text(
            'principle|scale|priority|avg_score|worst_items\n'
            'voice|scene|high|4.5|sc1;sc2\n'
        )
        result = _read_diagnosis(str(tmp_path))
        assert len(result) == 1
        assert result[0]['principle'] == 'voice'


# ============================================================================
# _detect_upstream_scenes
# ============================================================================

class TestDetectUpstreamScenes:
    def test_empty_diagnosis(self):
        result = _detect_upstream_scenes('/fake', [])
        assert result == []

    def test_finds_brief_root_cause(self):
        rows = [
            {'root_cause': 'brief', 'worst_items': 'sc1;sc2', 'priority': 'high'},
            {'root_cause': 'craft', 'worst_items': 'sc3', 'priority': 'high'},
        ]
        result = _detect_upstream_scenes('/fake', rows)
        assert 'sc1' in result
        assert 'sc2' in result
        assert 'sc3' not in result

    def test_deduplicates_scenes(self):
        rows = [
            {'root_cause': 'brief', 'worst_items': 'sc1;sc2'},
            {'root_cause': 'brief', 'worst_items': 'sc1;sc3'},
        ]
        result = _detect_upstream_scenes('/fake', rows)
        assert sorted(result) == ['sc1', 'sc2', 'sc3']

    def test_ignores_empty_worst_items(self):
        rows = [{'root_cause': 'brief', 'worst_items': ''}]
        result = _detect_upstream_scenes('/fake', rows)
        assert result == []

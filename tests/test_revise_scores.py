"""Tests for revise --scores mode."""

import os
import pytest


class TestScoresFlag:
    def test_parse_scores_flag(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--scores'])
        assert args.scores is True

    def test_scores_default_false(self):
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish'])
        assert args.scores is False

    def test_scores_mutually_exclusive_with_polish(self):
        from storyforge.cmd_revise import main
        with pytest.raises(SystemExit):
            main(['--scores', '--polish'])

    def test_scores_mutually_exclusive_with_structural(self):
        from storyforge.cmd_revise import main
        with pytest.raises(SystemExit):
            main(['--scores', '--structural'])


class TestGenerateScoresPlan:
    def test_generates_brief_pass_from_diagnosis(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01;s03;s05', 'priority': 'high', 'root_cause': 'brief'},
            {'principle': 'economy_clarity', 'scale': 'scene', 'avg_score': '2.5',
             'worst_items': 's01;s02', 'priority': 'high', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        assert len(rows) >= 1
        brief_passes = [r for r in rows if r['fix_location'] == 'brief']
        assert len(brief_passes) >= 1
        all_targets = ';'.join(r['targets'] for r in brief_passes)
        assert 's01' in all_targets

    def test_generates_craft_pass_for_craft_root_cause(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high', 'root_cause': 'craft'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        craft_passes = [r for r in rows if r['fix_location'] == 'craft']
        assert len(craft_passes) >= 1

    def test_brief_passes_come_before_craft(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '2.1',
             'worst_items': 's01', 'priority': 'high', 'root_cause': 'brief'},
            {'principle': 'dialogue_authenticity', 'scale': 'scene', 'avg_score': '2.5',
             'worst_items': 's02', 'priority': 'high', 'root_cause': 'craft'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        brief_idx = next(i for i, r in enumerate(rows) if r['fix_location'] == 'brief')
        craft_idx = next(i for i, r in enumerate(rows) if r['fix_location'] == 'craft')
        assert brief_idx < craft_idx

    def test_no_actionable_items_returns_empty(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'prose_naturalness', 'scale': 'scene', 'avg_score': '4.5',
             'worst_items': '', 'priority': 'low', 'root_cause': 'craft'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        assert rows == []

    def test_scenes_ranked_by_frequency(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'p1', 'scale': 'scene', 'avg_score': '2.0',
             'worst_items': 's01;s02;s03', 'priority': 'high', 'root_cause': 'brief'},
            {'principle': 'p2', 'scale': 'scene', 'avg_score': '2.0',
             'worst_items': 's01;s03', 'priority': 'high', 'root_cause': 'brief'},
            {'principle': 'p3', 'scale': 'scene', 'avg_score': '2.0',
             'worst_items': 's01', 'priority': 'medium', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        brief_passes = [r for r in rows if r['fix_location'] == 'brief']
        all_targets = ';'.join(r['targets'] for r in brief_passes)
        assert 's01' in all_targets

    def test_excludes_act_scale(self, tmp_path):
        from storyforge.cmd_revise import _generate_scores_plan

        plan_file = str(tmp_path / 'revision-plan.csv')
        diag_rows = [
            {'principle': 'genre_contract', 'scale': 'act', 'avg_score': '1.5',
             'worst_items': '', 'priority': 'high', 'root_cause': 'brief'},
        ]

        rows = _generate_scores_plan(plan_file, diag_rows)
        assert rows == []

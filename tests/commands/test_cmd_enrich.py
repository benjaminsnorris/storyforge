"""Tests for storyforge enrich -- metadata enrichment from prose.

Covers parse_args, main orchestration with mocked API/git/costs,
batch/direct/interactive mode, dry-run mode, scene filtering,
force mode, free enrichment (word count, time_of_day), and error handling.
"""

import json
import os
import subprocess

import pytest

from storyforge.cmd_enrich import (
    parse_args,
    main,
    ALL_FIELDS,
    METADATA_FIELDS,
    INTENT_FIELDS,
    BRIEFS_FIELDS,
    MIN_WORDS,
    _csv_for_field,
    _infer_time_of_day,
    _word_count,
    _apply_scene_filter,
)


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Test CLI argument parsing for the enrich command."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.direct
        assert not args.interactive
        assert not args.force
        assert not args.dry_run
        assert not args.skip_timeline
        assert not args.skip_dashboard
        assert args.scenes is None
        assert args.act is None
        assert args.from_seq is None
        assert args.parallel is None
        assert args.fields == ALL_FIELDS

    def test_direct_flag(self):
        args = parse_args(['--direct'])
        assert args.direct

    def test_interactive_long(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_force_flag(self):
        args = parse_args(['--force'])
        assert args.force

    def test_dry_run_flag(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_scenes_flag(self):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        assert args.scenes == 'act1-sc01,act1-sc02'

    def test_act_flag(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_from_seq_flag(self):
        args = parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'

    def test_from_seq_range(self):
        args = parse_args(['--from-seq', '3-7'])
        assert args.from_seq == '3-7'

    def test_parallel_flag(self):
        args = parse_args(['--parallel', '8'])
        assert args.parallel == 8

    def test_fields_flag(self):
        args = parse_args(['--fields', 'type,location,pov'])
        assert args.fields == 'type,location,pov'

    def test_skip_timeline_flag(self):
        args = parse_args(['--skip-timeline'])
        assert args.skip_timeline

    def test_skip_dashboard_flag(self):
        args = parse_args(['--skip-dashboard'])
        assert args.skip_dashboard

    def test_combined_flags(self):
        args = parse_args([
            '--direct', '--force', '--scenes', 'act1-sc01',
            '--fields', 'pov,location', '--parallel', '4',
            '--skip-timeline', '--skip-dashboard',
        ])
        assert args.direct
        assert args.force
        assert args.scenes == 'act1-sc01'
        assert args.fields == 'pov,location'
        assert args.parallel == 4
        assert args.skip_timeline
        assert args.skip_dashboard


# ============================================================================
# Constants
# ============================================================================


class TestConstants:
    """Test field set constants."""

    def test_metadata_fields_subset(self):
        all_field_set = set(ALL_FIELDS.split(','))
        assert METADATA_FIELDS.issubset(all_field_set)

    def test_intent_fields_subset(self):
        all_field_set = set(ALL_FIELDS.split(','))
        assert INTENT_FIELDS.issubset(all_field_set)

    def test_briefs_fields_subset(self):
        all_field_set = set(ALL_FIELDS.split(','))
        assert BRIEFS_FIELDS.issubset(all_field_set)

    def test_no_overlap_metadata_intent(self):
        assert METADATA_FIELDS.isdisjoint(INTENT_FIELDS)

    def test_no_overlap_metadata_briefs(self):
        assert METADATA_FIELDS.isdisjoint(BRIEFS_FIELDS)

    def test_no_overlap_intent_briefs(self):
        assert INTENT_FIELDS.isdisjoint(BRIEFS_FIELDS)

    def test_min_words_positive(self):
        assert MIN_WORDS > 0


# ============================================================================
# _csv_for_field
# ============================================================================


class TestCsvForField:
    """Test CSV path routing for fields."""

    def test_metadata_field(self, project_dir):
        path = _csv_for_field('pov', project_dir)
        assert path.endswith('scenes.csv')

    def test_intent_field(self, project_dir):
        path = _csv_for_field('emotional_arc', project_dir)
        assert path.endswith('scene-intent.csv')

    def test_briefs_field(self, project_dir):
        path = _csv_for_field('goal', project_dir)
        assert path.endswith('scene-briefs.csv')

    def test_unknown_field(self, project_dir):
        path = _csv_for_field('nonexistent_field', project_dir)
        assert path == ''


# ============================================================================
# _infer_time_of_day
# ============================================================================


class TestInferTimeOfDay:
    """Test heuristic time_of_day inference from text."""

    def test_dawn(self):
        assert _infer_time_of_day('The first light of dawn crept over the hills') == 'dawn'

    def test_sunrise(self):
        assert _infer_time_of_day('At sunrise they gathered') == 'dawn'

    def test_morning(self):
        assert _infer_time_of_day('She had breakfast at the kitchen table') == 'morning'

    def test_afternoon(self):
        assert _infer_time_of_day('After lunch they walked through the park') == 'afternoon'

    def test_dusk(self):
        assert _infer_time_of_day('The sunset painted the sky orange') == 'dusk'

    def test_evening(self):
        assert _infer_time_of_day('They sat down to dinner in the great hall') == 'evening'

    def test_night(self):
        assert _infer_time_of_day('The moonlight streamed through the window') == 'night'

    def test_midnight(self):
        assert _infer_time_of_day('It was well past midnight when she arrived') == 'night'

    def test_no_time_cues(self):
        assert _infer_time_of_day('The map showed the eastern territories') == ''

    def test_empty_string(self):
        assert _infer_time_of_day('') == ''


# ============================================================================
# _word_count
# ============================================================================


class TestWordCount:
    """Test word count helper."""

    def test_counts_words(self, tmp_path):
        f = str(tmp_path / 'test.md')
        with open(f, 'w') as fh:
            fh.write('one two three four five')
        assert _word_count(f) == 5

    def test_empty_file(self, tmp_path):
        f = str(tmp_path / 'empty.md')
        with open(f, 'w') as fh:
            fh.write('')
        assert _word_count(f) == 0


# ============================================================================
# _apply_scene_filter
# ============================================================================


class TestApplySceneFilter:
    """Test scene filter application."""

    def test_all_mode(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        result = _apply_scene_filter(meta, 'all', '', project_dir)
        # Should return all non-cut scenes
        assert len(result) >= 1
        assert 'act1-sc01' in result

    def test_scenes_mode(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        result = _apply_scene_filter(meta, 'scenes', 'act1-sc01,act1-sc02', project_dir)
        assert 'act1-sc01' in result
        assert 'act1-sc02' in result

    def test_act_mode(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        result = _apply_scene_filter(meta, 'act', '2', project_dir)
        for sid in result:
            assert sid.startswith('act2')

    def test_from_seq_mode(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        result = _apply_scene_filter(meta, 'from_seq', '3', project_dir)
        # seq 3+ should include new-x1 (seq=3), act2-sc01 (seq=4), etc.
        assert len(result) >= 1

    def test_from_seq_range(self, project_dir):
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        result = _apply_scene_filter(meta, 'from_seq', '2-3', project_dir)
        assert len(result) >= 1


# ============================================================================
# main -- dry run
# ============================================================================


class TestMainDryRun:
    """Test main() in dry-run mode."""

    def test_dry_run_no_api_calls(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run'])
        assert mock_api.call_count == 0

    def test_dry_run_no_branch(self, mock_api, mock_git, mock_costs,
                                project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run'])
        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0

    def test_dry_run_does_not_need_api_key(self, mock_api, mock_git, mock_costs,
                                            project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        # Should NOT raise SystemExit
        main(['--dry-run'])
        assert mock_api.call_count == 0

    def test_dry_run_with_scenes_filter(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--scenes', 'act1-sc01'])
        assert mock_api.call_count == 0


# ============================================================================
# main -- error handling
# ============================================================================


class TestErrorHandling:
    """Test error cases and edge conditions."""

    def test_no_api_key_exits(self, mock_api, mock_git, mock_costs,
                              project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        with pytest.raises(SystemExit):
            main([])

    def test_missing_metadata_csv_exits(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        # Remove the metadata CSV
        os.remove(os.path.join(project_dir, 'reference', 'scenes.csv'))

        with pytest.raises(SystemExit):
            main([])

    def test_missing_intent_csv_exits(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        # Remove the intent CSV
        os.remove(os.path.join(project_dir, 'reference', 'scene-intent.csv'))

        with pytest.raises(SystemExit):
            main([])

    def test_invalid_field_exits(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        with pytest.raises(SystemExit):
            main(['--fields', 'nonexistent_field_xyz'])

    def test_interactive_mode_does_not_need_api_key(self, mock_api, mock_git,
                                                      mock_costs, project_dir,
                                                      monkeypatch):
        """Interactive mode uses claude -p and should not check ANTHROPIC_API_KEY."""
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        # Mock subprocess to prevent actual claude invocation.
        # The function should get past the API key check but may fail
        # later due to fully populated fields -- that's fine, we're
        # testing the API key check only.
        monkeypatch.setattr('storyforge.cmd_enrich.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))
        monkeypatch.setattr('storyforge.cmd_enrich.subprocess.Popen',
                            lambda *a, **kw: type('P', (), {
                                'wait': lambda s: None, 'returncode': 0,
                                'stdout': None, 'stderr': None,
                            })())

        # Force mode + interactive to ensure scenes need enrichment
        # Since we don't know if any scenes need enrichment (all fields
        # may already be populated), we just verify no SystemExit from
        # the API key check specifically.
        try:
            main(['-i', '--force', '--scenes', 'act1-sc01',
                  '--skip-timeline', '--skip-dashboard'])
        except SystemExit as e:
            # If it exits, it must NOT be the API key error (code 1 with 'api' reason)
            # Other exits (e.g., no enrichment needed) are acceptable
            assert e.code != 1 or mock_api.call_count > 0, \
                "Interactive mode should not exit due to missing ANTHROPIC_API_KEY"

        # No batch API calls should have been made (wrong mode)
        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) == 0


# ============================================================================
# main -- batch mode
# ============================================================================


class TestMainBatchMode:
    """Test main() in default batch mode."""

    def test_batch_creates_branch(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        # Mock subprocess for build-prompt, apply-response, and alias loading
        monkeypatch.setattr('storyforge.cmd_enrich.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='{}', stderr=''))

        mock_api.set_response('TYPE|scene\nLOCATION|Library\nPOV|Dorren')

        # Force to ensure enrichment happens
        main(['--force', '--scenes', 'act1-sc01', '--fields', 'type',
              '--skip-timeline', '--skip-dashboard'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1

    def test_batch_submits_batch_api(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_enrich.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='{}', stderr=''))

        mock_api.set_response('TYPE|scene')

        main(['--force', '--scenes', 'act1-sc01', '--fields', 'type',
              '--skip-timeline', '--skip-dashboard'])

        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) >= 1

    def test_batch_polls_and_downloads(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_enrich.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='{}', stderr=''))

        mock_api.set_response('TYPE|scene')

        main(['--force', '--scenes', 'act1-sc01', '--fields', 'type',
              '--skip-timeline', '--skip-dashboard'])

        poll_calls = mock_api.calls_for('poll_batch')
        assert len(poll_calls) >= 1

        dl_calls = mock_api.calls_for('download_batch_results')
        assert len(dl_calls) >= 1

    def test_batch_commits_results(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_enrich.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='{}', stderr=''))

        mock_api.set_response('TYPE|scene')

        main(['--force', '--scenes', 'act1-sc01', '--fields', 'type',
              '--skip-timeline', '--skip-dashboard'])

        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) >= 1


# ============================================================================
# main -- cost threshold
# ============================================================================


class TestCostThreshold:
    """Test cost threshold checking."""

    def test_cost_threshold_declined_aborts(self, mock_api, mock_git,
                                             mock_costs, project_dir,
                                             monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_enrich.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='{}', stderr=''))

        mock_costs.threshold_ok = False

        with pytest.raises(SystemExit):
            main(['--force', '--scenes', 'act1-sc01', '--fields', 'type',
                  '--skip-timeline', '--skip-dashboard'])

        # API should not have been called
        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) == 0


# ============================================================================
# main -- no scenes need enrichment
# ============================================================================


class TestNoEnrichmentNeeded:
    """Test behavior when all fields are already populated."""

    def test_all_populated_returns_early(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        """When all requested fields are populated, exits without API calls."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)

        # The fixture has pov populated for act1-sc01 in scenes.csv
        # so requesting only that field should find nothing to do.
        main(['--scenes', 'act1-sc01', '--fields', 'pov'])

        # No batch submission should occur
        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) == 0

        # No branch should be created
        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0


# ============================================================================
# main -- free enrichment
# ============================================================================


class TestFreeEnrichment:
    """Test the free enrichment phase (word count + time_of_day)."""

    def test_word_count_updated(self, mock_api, mock_git, mock_costs,
                                 project_dir, monkeypatch):
        """Free enrichment should update word_count from scene files."""
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_enrich.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_enrich.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='{}', stderr=''))
        mock_api.set_response('TYPE|scene')

        # Force enrichment on a scene that has word_count=0
        main(['--force', '--scenes', 'act1-sc01', '--fields', 'type',
              '--skip-timeline', '--skip-dashboard'])

        # Check that word_count was updated in the CSV
        from storyforge.csv_cli import get_field
        meta = os.path.join(project_dir, 'reference', 'scenes.csv')
        wc = get_field(meta, 'act1-sc01', 'word_count')
        # Should now have a non-zero word count (from the scene file)
        assert wc != '' and wc != '0'

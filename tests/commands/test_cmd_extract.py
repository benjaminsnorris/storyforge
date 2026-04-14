"""Tests for storyforge extract -- structural data extraction from prose.

Covers parse_args, main orchestration with mocked API/git/costs,
extraction phases (0-3), --force mode, --cleanup-only, --expand,
dry-run mode, scene sorting, and error handling.
"""

import json
import os
import subprocess

import pytest

from storyforge.cmd_extract import (
    parse_args,
    main,
    _build_sorted_scene_ids,
    _load_profile,
    _safe_remove,
    _safe_rmdir,
)


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Test CLI argument parsing for the extract command."""

    def test_defaults(self):
        args = parse_args([])
        assert args.phase is None
        assert not args.cleanup
        assert not args.cleanup_only
        assert not args.force
        assert not args.expand
        assert not args.dry_run

    def test_phase_0(self):
        args = parse_args(['--phase', '0'])
        assert args.phase == 0

    def test_phase_1(self):
        args = parse_args(['--phase', '1'])
        assert args.phase == 1

    def test_phase_2(self):
        args = parse_args(['--phase', '2'])
        assert args.phase == 2

    def test_phase_3(self):
        args = parse_args(['--phase', '3'])
        assert args.phase == 3

    def test_cleanup_flag(self):
        args = parse_args(['--cleanup'])
        assert args.cleanup

    def test_cleanup_only_flag(self):
        args = parse_args(['--cleanup-only'])
        assert args.cleanup_only

    def test_force_flag(self):
        args = parse_args(['--force'])
        assert args.force

    def test_expand_flag(self):
        args = parse_args(['--expand'])
        assert args.expand

    def test_dry_run_flag(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_combined_flags(self):
        args = parse_args(['--phase', '1', '--force', '--dry-run'])
        assert args.phase == 1
        assert args.force
        assert args.dry_run

    def test_cleanup_and_expand(self):
        args = parse_args(['--cleanup', '--expand'])
        assert args.cleanup
        assert args.expand


# ============================================================================
# _build_sorted_scene_ids
# ============================================================================


class TestBuildSortedSceneIds:
    """Test scene ID sorting from files and CSV seq values."""

    def test_returns_all_scene_ids(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        result = _build_sorted_scene_ids(scenes_dir, ref_dir)
        # Fixture has act1-sc01, act1-sc02, act2-sc01, new-x1
        assert len(result) == 4
        assert 'act1-sc01' in result
        assert 'act1-sc02' in result

    def test_sorted_by_seq(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        result = _build_sorted_scene_ids(scenes_dir, ref_dir)
        # act1-sc01 has seq=1, act1-sc02 has seq=2, etc.
        assert result.index('act1-sc01') < result.index('act1-sc02')

    def test_falls_back_to_alpha_sort_without_csv(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        # Remove the scenes.csv to force alphabetical sorting
        csv_path = os.path.join(ref_dir, 'scenes.csv')
        os.remove(csv_path)
        result = _build_sorted_scene_ids(scenes_dir, ref_dir)
        assert result == sorted(result)

    def test_empty_scenes_dir(self, project_dir):
        scenes_dir = os.path.join(project_dir, 'scenes')
        ref_dir = os.path.join(project_dir, 'reference')
        # Remove all scene files
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))
        result = _build_sorted_scene_ids(scenes_dir, ref_dir)
        assert result == []


# ============================================================================
# _load_profile
# ============================================================================


class TestLoadProfile:
    """Test extraction profile loading."""

    def test_loads_existing_profile(self, tmp_path):
        profile_file = str(tmp_path / 'profile.json')
        data = {'genre': 'fantasy', 'pov_style': 'third-limited'}
        with open(profile_file, 'w') as f:
            json.dump(data, f)
        result = _load_profile(profile_file)
        assert result == data

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        result = _load_profile(str(tmp_path / 'nonexistent.json'))
        assert result == {}


# ============================================================================
# _safe_remove / _safe_rmdir
# ============================================================================


class TestSafeRemove:
    """Test safe file/directory removal helpers."""

    def test_safe_remove_existing_file(self, tmp_path):
        f = str(tmp_path / 'test.txt')
        with open(f, 'w') as fh:
            fh.write('test')
        _safe_remove(f)
        assert not os.path.exists(f)

    def test_safe_remove_nonexistent(self, tmp_path):
        # Should not raise
        _safe_remove(str(tmp_path / 'nonexistent.txt'))

    def test_safe_remove_empty_string(self):
        # Should not raise
        _safe_remove('')

    def test_safe_rmdir_existing(self, tmp_path):
        d = str(tmp_path / 'subdir')
        os.makedirs(d)
        with open(os.path.join(d, 'file.txt'), 'w') as f:
            f.write('test')
        _safe_rmdir(d)
        assert not os.path.exists(d)

    def test_safe_rmdir_nonexistent(self, tmp_path):
        _safe_rmdir(str(tmp_path / 'nonexistent'))

    def test_safe_rmdir_empty_string(self):
        _safe_rmdir('')


# ============================================================================
# main -- dry run
# ============================================================================


class TestMainDryRun:
    """Test main() in dry-run mode."""

    def test_dry_run_no_api_calls(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run'])
        assert mock_api.call_count == 0

    def test_dry_run_no_branch(self, mock_api, mock_git, mock_costs,
                                project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run'])
        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) == 0

    def test_dry_run_no_pr(self, mock_api, mock_git, mock_costs,
                            project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run'])
        pr_calls = mock_git.calls_for('create_draft_pr')
        assert len(pr_calls) == 0

    def test_dry_run_phase_0_prints(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--phase', '0'])
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out

    def test_dry_run_phase_1_prints(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--phase', '1'])
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out

    def test_dry_run_does_not_need_api_key(self, mock_api, mock_git, mock_costs,
                                            project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        # Should NOT raise SystemExit
        main(['--dry-run'])
        assert mock_api.call_count == 0


# ============================================================================
# main -- error handling
# ============================================================================


class TestErrorHandling:
    """Test error cases and edge conditions."""

    def test_no_api_key_exits(self, mock_api, mock_git, mock_costs,
                              project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        with pytest.raises(SystemExit):
            main([])

    def test_no_scene_files_exits(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        # Remove all scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        with pytest.raises(SystemExit):
            main([])

    def test_cleanup_only_does_not_need_api_key(self, mock_api, mock_git,
                                                  mock_costs, project_dir,
                                                  monkeypatch):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        # Patch the cleanup and validation to not fail
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True,
            'failures': [],
            'checks': ['check1'],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        # Patch run_cleanup to succeed
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        # Should NOT raise SystemExit
        main(['--cleanup-only'])


# ============================================================================
# main -- phase execution
# ============================================================================


class TestPhaseExecution:
    """Test individual phase execution through main."""

    def test_phase_0_invokes_api(self, mock_api, mock_git, mock_costs,
                                  project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)

        # Provide characterize response
        mock_api.set_response('genre: fantasy\npov_style: third-limited\ntone: literary')

        # Patch validate_structure
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '0'])

        # Should have called invoke_to_file for characterization
        api_calls = mock_api.calls_for('invoke_to_file')
        assert len(api_calls) >= 1

    def test_phase_0_creates_branch(self, mock_api, mock_git, mock_costs,
                                     project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        mock_api.set_response('genre: fantasy')

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '0'])

        branch_calls = mock_git.calls_for('create_branch')
        assert len(branch_calls) >= 1
        assert branch_calls[0][1] == 'extract'

    def test_phase_1_submits_batch(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)

        # Mock _run_hone to avoid it calling detect_project_root in cmd_hone
        monkeypatch.setattr('storyforge.cmd_extract._run_hone',
                            lambda plugin_dir, phase: None)

        mock_api.set_response(
            'id|seq|title|part|pov|location\n'
            'act1-sc01|1|Test|1|Dorren|Office\n'
        )

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '1'])

        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) >= 1

    def test_all_phases_run_when_no_phase_flag(self, mock_api, mock_git,
                                                 mock_costs, project_dir,
                                                 monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)

        # Mock _run_hone to avoid calling detect_project_root in cmd_hone
        monkeypatch.setattr('storyforge.cmd_extract._run_hone',
                            lambda plugin_dir, phase: None)

        mock_api.set_response('id|seq|title\nact1-sc01|1|Test\n')

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main([])

        # Should have submitted batches for phases 1, 2, and 3a at minimum
        batch_calls = mock_api.calls_for('submit_batch')
        assert len(batch_calls) >= 3

    def test_commits_after_each_phase(self, mock_api, mock_git, mock_costs,
                                       project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_extract.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))

        mock_api.set_response('genre: fantasy')

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '0'])

        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) >= 1


# ============================================================================
# main -- force mode
# ============================================================================


class TestForceMode:
    """Test --force flag behavior."""

    def test_force_flag_passed_through(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        # Dry-run with force should work without API key
        main(['--dry-run', '--force'])
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out


# ============================================================================
# main -- review phase
# ============================================================================


class TestReviewPhase:
    """Test that review phase is called at the end."""

    def test_review_phase_runs(self, mock_api, mock_git, mock_costs,
                                project_dir, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)

        mock_api.set_response('genre: fantasy')

        # Patch validate/cleanup
        monkeypatch.setattr('storyforge.elaborate.validate_structure', lambda ref_dir: {
            'passed': True, 'failures': [], 'checks': [],
        })
        monkeypatch.setattr('storyforge.cmd_extract.get_coaching_level',
                            lambda pd: 'full')
        monkeypatch.setattr('storyforge.extract.run_cleanup', lambda ref_dir: {
            'total_fixes': 0,
        })

        main(['--phase', '0'])

        review_calls = mock_git.calls_for('run_review_phase')
        assert len(review_calls) >= 1
        assert review_calls[0][1] == 'extraction'


# ============================================================================
# main -- expand mode
# ============================================================================


class TestExpandMode:
    """Test --expand flag behavior."""

    def test_expand_dry_run_no_expansion(self, mock_api, mock_git, mock_costs,
                                          project_dir, monkeypatch):
        """In dry-run mode, expansion should not run."""
        monkeypatch.setattr('storyforge.cmd_extract.detect_project_root',
                            lambda: project_dir)
        main(['--dry-run', '--expand'])
        assert mock_api.call_count == 0

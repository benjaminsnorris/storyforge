"""Tests for storyforge.cmd_timeline — timeline day assignment for scenes.

Covers: parse_args (all flags), dry-run mode, cost estimation, scene filtering,
branch/PR workflow, embedded mode, phase control (phase1-only, skip-phase1),
API key validation, and error handling.
"""

import json
import os
import sys

import pytest

from storyforge.cmd_timeline import parse_args, main


# ============================================================================
# Helpers
# ============================================================================

def _ensure_scene_files(project_dir, scene_ids=None):
    """Create scene prose files so word counting works."""
    if scene_ids is None:
        scene_ids = ['act1-sc01', 'act1-sc02', 'new-x1', 'act2-sc01',
                     'act2-sc02', 'act2-sc03']
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    for sid in scene_ids:
        path = os.path.join(scenes_dir, f'{sid}.md')
        if not os.path.isfile(path):
            with open(path, 'w') as f:
                f.write(f'Prose content for scene {sid}. ' * 100 + '\n')


def _patch_interactive(monkeypatch):
    """Patch interactive functions that are not in common mocks."""
    monkeypatch.setattr('storyforge.cmd_timeline.show_interactive_banner', lambda *a, **kw: None)
    monkeypatch.setattr('storyforge.cmd_timeline.offer_interactive', lambda *a, **kw: False)
    monkeypatch.setattr('storyforge.cmd_timeline.build_interactive_system_prompt', lambda *a, **kw: '')
    monkeypatch.setattr('storyforge.cmd_timeline.is_shutting_down', lambda: False)


def _patch_pass(monkeypatch):
    """Stub the timeline pass; returns the calls made to it."""
    calls = {'cues': [], 'assign': []}
    monkeypatch.setattr('storyforge.cmd_timeline.extract_cues',
                        lambda project_dir, ids, model, log_dir, **kw: calls['cues'].append(ids) or {})
    monkeypatch.setattr('storyforge.cmd_timeline.run_assignment',
                        lambda project_dir, model, log_dir, force: calls['assign'].append(force) or
                        {'assigned': 0, 'proposed': 0, 'unplaced': 0, 'findings': 0})
    return calls


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    """Tests for parse_args."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.interactive
        assert not args.direct
        assert args.parallel is None
        assert not args.force
        assert not args.dry_run
        assert not args.skip_phase1
        assert not args.phase1_only
        assert not args.embedded

    def test_interactive_flag(self):
        args = parse_args(['--interactive'])
        assert args.interactive

    def test_interactive_short(self):
        args = parse_args(['-i'])
        assert args.interactive

    def test_direct_flag(self):
        args = parse_args(['--direct'])
        assert args.direct

    def test_parallel_workers(self):
        args = parse_args(['--parallel', '4'])
        assert args.parallel == 4

    def test_force_flag(self):
        args = parse_args(['--force'])
        assert args.force

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_skip_phase1(self):
        args = parse_args(['--skip-phase1'])
        assert args.skip_phase1

    def test_phase1_only(self):
        args = parse_args(['--phase1-only'])
        assert args.phase1_only

    def test_embedded(self):
        args = parse_args(['--embedded'])
        assert args.embedded

    def test_scene_filter_scenes(self):
        args = parse_args(['--scenes', 'sc1,sc2'])
        assert args.scenes == 'sc1,sc2'

    def test_scene_filter_act(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_scene_filter_from_seq(self):
        args = parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'

    def test_combined_flags(self):
        args = parse_args(['--dry-run', '--force', '--embedded', '--direct'])
        assert args.dry_run
        assert args.force
        assert args.embedded
        assert args.direct


# ============================================================================
# main — dry run
# ============================================================================

class TestMainDryRun:
    """Tests for main() in dry-run mode."""

    def test_dry_run_no_api_calls(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run'])
        assert exc_info.value.code == 0
        assert mock_api.call_count == 0

    def test_dry_run_lists_scenes(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run'])
        assert exc_info.value.code == 0
        # stdout should mention scene IDs or dry run
        output = capsys.readouterr()
        # log() writes to stdout
        assert 'DRY RUN' in output.out

    def test_dry_run_no_git_operations(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run'])
        assert exc_info.value.code == 0
        assert mock_git.call_count == 0

    def test_dry_run_with_skip_phase1(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run', '--skip-phase1'])
        assert exc_info.value.code == 0
        output = capsys.readouterr()
        assert 'SKIPPED' in output.out

    def test_dry_run_with_phase1_only(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run', '--phase1-only'])
        assert exc_info.value.code == 0
        output = capsys.readouterr()
        assert 'DEFERRED' in output.out


# ============================================================================
# main — API key check
# ============================================================================

class TestMainApiKeyCheck:
    """Tests for API key validation in autonomous mode."""

    def test_no_api_key_exits_in_autonomous_mode(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_interactive_mode_still_needs_a_key(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """Interactive only adds checkpoints; the pass calls the API."""
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        with pytest.raises(SystemExit) as exc_info:
            main(['--interactive'])
        assert exc_info.value.code == 1
        assert mock_git.calls_for('create_branch') == []

    def test_no_api_key_ok_in_embedded_mode(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """Embedded mode does not require ANTHROPIC_API_KEY."""
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        _ensure_scene_files(project_dir)
        calls = _patch_pass(monkeypatch)
        # Should not exit with API key error (embedded mode skips check)
        main(['--embedded', '--direct'])
        assert mock_api.call_count >= 0


# ============================================================================
# main — cost threshold
# ============================================================================

class TestMainCostThreshold:
    """Tests for cost threshold checks."""

    def test_cost_threshold_exceeded_exits(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        mock_costs.threshold_ok = False
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1


# ============================================================================
# main — embedded mode
# ============================================================================

class TestMainEmbedded:
    """Tests for embedded mode (no branch/PR/commit)."""

    def test_embedded_skips_branch_and_pr(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        calls = _patch_pass(monkeypatch)
        main(['--embedded', '--direct'])
        branch_calls = mock_git.calls_for('create_branch')
        pr_calls = mock_git.calls_for('create_draft_pr')
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(branch_calls) == 0
        assert len(pr_calls) == 0
        assert len(commit_calls) == 0

    def test_embedded_runs_both_steps_without_force(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        calls = _patch_pass(monkeypatch)
        main(['--embedded', '--direct'])
        assert len(calls['cues']) == 1 and calls['assign'] == [False]


# ============================================================================
# main — standalone mode
# ============================================================================

class TestMainStandalone:
    """Tests for standalone mode (branch/PR/commit workflow)."""

    def test_creates_branch_and_pr(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        calls = _patch_pass(monkeypatch)
        main(['--direct'])
        branch_calls = mock_git.calls_for('create_branch')
        pr_calls = mock_git.calls_for('create_draft_pr')
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(branch_calls) == 1
        assert len(pr_calls) == 1
        assert len(commit_calls) == 1

    def test_commits_scenes_csv_and_logs(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        calls = _patch_pass(monkeypatch)
        main(['--direct'])
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 1
        committed_paths = commit_calls[0][2]
        assert 'reference/scenes.csv' in committed_paths


# ============================================================================
# main — phase1-only
# ============================================================================

class TestMainPhase1Only:
    """Tests for --phase1-only mode."""

    def test_phase1_only_exits_after_phase1(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        calls = _patch_pass(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main(['--phase1-only', '--direct'])
        assert exc_info.value.code == 0

    def test_phase1_only_reads_cues_and_assigns_nothing(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        calls = _patch_pass(monkeypatch)
        with pytest.raises(SystemExit):
            main(['--phase1-only', '--direct'])
        assert len(calls['cues']) == 1 and calls['assign'] == []


class TestMainCheck:
    """--check compares prose with the calendar and changes nothing."""

    def test_check_reads_cues_and_never_assigns(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        calls = _patch_pass(monkeypatch)
        before = open(os.path.join(project_dir, 'reference', 'scenes.csv')).read()
        main(['--check', '--scenes', 'act1-sc01'])
        assert calls['cues'] == [['act1-sc01']] and calls['assign'] == []
        assert mock_git.calls_for('create_branch') == []
        assert open(os.path.join(project_dir, 'reference', 'scenes.csv')).read() == before

    def test_check_leaves_stored_cues_alone(self, mock_api, mock_git, mock_costs, project_dir,
                                             monkeypatch, capsys):
        """The Age of Innocence: --check logged "read-only" but overwrote
        working/timeline-cues.csv, the cues the calendar was built from."""
        import storyforge.timeline as tl
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        tl.write_cues(project_dir, {'act1-sc01': {'relation': 'later', 'gap': 'a week'}})
        cues_file = os.path.join(project_dir, tl.CUES_FILE)
        before = open(cues_file).read()
        monkeypatch.setattr('storyforge.api.invoke_to_file', lambda *a, **k: {})
        monkeypatch.setattr('storyforge.api.extract_text',
                            lambda r: 'TIME_RELATION: earlier\nTIME_GAP: three days\n')
        main(['--check', '--scenes', 'act1-sc01'])
        assert open(cues_file).read() == before

    def test_force_is_passed_through(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        _ensure_scene_files(project_dir)
        calls = _patch_pass(monkeypatch)
        main(['--embedded', '--direct', '--force'])
        assert calls['assign'] == [True]


# ============================================================================
# main — empty scenes
# ============================================================================

class TestMainEmptyScenes:
    """Tests for handling when no scenes match filters."""

    def test_no_scenes_exits(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        """When scene filter matches nothing, exit without running API calls."""
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: project_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        # Filter to a non-existent scene
        with pytest.raises(SystemExit):
            main(['--scenes', 'nonexistent-scene-id'])
        assert mock_api.call_count == 0


# ============================================================================
# main — missing metadata
# ============================================================================

class TestMainMissingMetadata:
    """Tests for error handling with missing project files."""

    def test_missing_scenes_csv_exits(self, mock_api, mock_git, mock_costs, tmp_path, monkeypatch):
        empty_dir = str(tmp_path / 'empty-project')
        os.makedirs(os.path.join(empty_dir, 'reference'), exist_ok=True)
        with open(os.path.join(empty_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')
        monkeypatch.setattr('storyforge.cmd_timeline.detect_project_root', lambda: empty_dir)
        _patch_interactive(monkeypatch)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

"""Tests for storyforge.cmd_visualize — manuscript visualization dashboard.

Covers: parse_args, template finding/loading, data injection, dry-run mode,
main flow, dashboard file creation, git workflow, and error handling.
"""

import json
import os
import subprocess
import sys

import pytest

from storyforge.cmd_visualize import (
    parse_args,
    main,
    _find_template,
    _load_template,
    _build_data_injection,
    _inject_data,
)


# ============================================================================
# parse_args
# ============================================================================

class TestParseArgs:
    """Tests for parse_args."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.open
        assert not args.dry_run

    def test_open_flag(self):
        args = parse_args(['--open'])
        assert args.open

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_combined_flags(self):
        args = parse_args(['--open', '--dry-run'])
        assert args.open
        assert args.dry_run


# ============================================================================
# _find_template
# ============================================================================

class TestFindTemplate:
    """Tests for _find_template."""

    def test_returns_path_when_template_exists(self, monkeypatch, tmp_path):
        plugin_dir = str(tmp_path / 'plugin')
        templates_dir = os.path.join(plugin_dir, 'templates')
        os.makedirs(templates_dir)
        template = os.path.join(templates_dir, 'dashboard.html')
        with open(template, 'w') as f:
            f.write('<html></html>')
        monkeypatch.setattr('storyforge.cmd_visualize.get_plugin_dir', lambda: plugin_dir)
        result = _find_template()
        assert result == template

    def test_returns_none_when_missing(self, monkeypatch, tmp_path):
        plugin_dir = str(tmp_path / 'no-templates')
        os.makedirs(plugin_dir)
        monkeypatch.setattr('storyforge.cmd_visualize.get_plugin_dir', lambda: plugin_dir)
        result = _find_template()
        assert result is None


# ============================================================================
# _load_template
# ============================================================================

class TestLoadTemplate:
    """Tests for _load_template."""

    def test_loads_existing_template(self, monkeypatch, tmp_path):
        plugin_dir = str(tmp_path / 'plugin')
        templates_dir = os.path.join(plugin_dir, 'templates')
        os.makedirs(templates_dir)
        template = os.path.join(templates_dir, 'dashboard.html')
        with open(template, 'w') as f:
            f.write('<html>test</html>')
        monkeypatch.setattr('storyforge.cmd_visualize.get_plugin_dir', lambda: plugin_dir)
        result = _load_template()
        assert result == '<html>test</html>'

    def test_exits_when_template_not_found(self, monkeypatch, tmp_path):
        plugin_dir = str(tmp_path / 'empty')
        os.makedirs(plugin_dir)
        monkeypatch.setattr('storyforge.cmd_visualize.get_plugin_dir', lambda: plugin_dir)
        with pytest.raises(SystemExit) as exc_info:
            _load_template()
        assert exc_info.value.code == 1


# ============================================================================
# _build_data_injection / _inject_data
# ============================================================================

class TestDataInjection:
    """Tests for data injection into the HTML template."""

    def test_build_data_injection_contains_scenes(self):
        data = {'scenes': [{'id': 'sc1'}], 'intents': [], 'characters': [],
                'motif_taxonomy': [], 'locations': [], 'scores': [],
                'weights': [], 'narrative_scores': [], 'project': {},
                'scene_rationales': [], 'act_scores': [], 'act_rationales': [],
                'character_scores': [], 'character_rationales': [],
                'genre_scores': [], 'genre_rationales': [],
                'narrative_rationales': []}
        result = _build_data_injection(json.dumps(data))
        assert 'const SCENES = _DATA.scenes;' in result
        assert 'const _DATA =' in result

    def test_inject_data_replaces_marker(self):
        template = '<html><script>// DATA_INJECTION_POINT\n</script></html>'
        data_json = '{"scenes": []}'
        result = _inject_data(template, data_json)
        assert '// DATA_INJECTION_POINT' not in result
        assert 'const _DATA =' in result

    def test_inject_data_exits_on_no_marker(self, monkeypatch):
        template = '<html><script>// nothing here</script></html>'
        with pytest.raises(SystemExit) as exc_info:
            _inject_data(template, '{}')
        assert exc_info.value.code == 1


# ============================================================================
# main — dry run
# ============================================================================

class TestMainDryRun:
    """Tests for main() in dry-run mode."""

    def test_dry_run_no_api_calls(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: project_dir)
        main(['--dry-run'])
        assert mock_api.call_count == 0

    def test_dry_run_no_git_commits(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: project_dir)
        main(['--dry-run'])
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 0

    def test_dry_run_no_file_written(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: project_dir)
        dashboard_file = os.path.join(project_dir, 'working', 'dashboard.html')
        # Remove any pre-existing dashboard from the fixture copy
        if os.path.isfile(dashboard_file):
            os.remove(dashboard_file)
        main(['--dry-run'])
        # Dry-run should not write the dashboard file
        assert not os.path.isfile(dashboard_file)

    def test_dry_run_exits_missing_metadata(self, mock_api, mock_git, mock_costs, tmp_path, monkeypatch):
        """dry-run exits with error if reference/scenes.csv is missing."""
        empty_dir = str(tmp_path / 'empty')
        os.makedirs(os.path.join(empty_dir, 'reference'), exist_ok=True)
        # No scenes.csv
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: empty_dir)
        with pytest.raises(SystemExit) as exc_info:
            main(['--dry-run'])
        assert exc_info.value.code == 1


# ============================================================================
# main — full generation
# ============================================================================

class TestMainGenerate:
    """Tests for main() full generation flow."""

    def _setup_template(self, monkeypatch, tmp_path):
        """Create a minimal dashboard template and patch get_plugin_dir."""
        plugin_dir = str(tmp_path / 'plugin')
        templates_dir = os.path.join(plugin_dir, 'templates')
        os.makedirs(templates_dir)
        template = os.path.join(templates_dir, 'dashboard.html')
        with open(template, 'w') as f:
            f.write('<html><script>// DATA_INJECTION_POINT\n</script></html>')
        monkeypatch.setattr('storyforge.cmd_visualize.get_plugin_dir', lambda: plugin_dir)

    def _mock_visualize(self, monkeypatch):
        """Mock the load_dashboard_data call so we don't need the full module."""
        mock_data = {
            'scenes': [], 'intents': [], 'characters': [],
            'motif_taxonomy': [], 'locations': [], 'scores': [],
            'weights': [], 'narrative_scores': [], 'project': {},
            'scene_rationales': [], 'act_scores': [], 'act_rationales': [],
            'character_scores': [], 'character_rationales': [],
            'genre_scores': [], 'genre_rationales': [],
            'narrative_rationales': [], 'values': [], 'mice_threads': [],
            'knowledge': [], 'briefs': [], 'fidelity_scores': [],
            'fidelity_rationales': [], 'structural_scores': [],
            'repetition_scores': [], 'brief_quality': [],
        }
        monkeypatch.setattr(
            'storyforge.visualize.load_dashboard_data',
            lambda pd: mock_data,
        )

    def test_generates_dashboard_file(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, tmp_path):
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: project_dir)
        self._setup_template(monkeypatch, tmp_path)
        self._mock_visualize(monkeypatch)
        main([])
        dashboard = os.path.join(project_dir, 'working', 'dashboard.html')
        assert os.path.isfile(dashboard)
        with open(dashboard) as f:
            content = f.read()
        assert 'const _DATA =' in content

    def test_commits_dashboard(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, tmp_path):
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: project_dir)
        self._setup_template(monkeypatch, tmp_path)
        self._mock_visualize(monkeypatch)
        main([])
        commits = mock_git.calls_for('commit_and_push')
        assert len(commits) == 1
        assert 'dashboard' in commits[0][1].lower()

    def test_open_flag_calls_subprocess(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, tmp_path):
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: project_dir)
        self._setup_template(monkeypatch, tmp_path)
        self._mock_visualize(monkeypatch)

        opened = []
        monkeypatch.setattr(
            'storyforge.cmd_visualize.subprocess.run',
            lambda cmd, check=False: opened.append(cmd),
        )
        main(['--open'])
        assert len(opened) == 1
        # The command should reference the dashboard file
        assert any('dashboard.html' in str(arg) for arg in opened[0])

    def test_ensures_on_branch(self, mock_api, mock_git, mock_costs, project_dir, monkeypatch, tmp_path):
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: project_dir)
        self._setup_template(monkeypatch, tmp_path)
        self._mock_visualize(monkeypatch)
        main([])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 1


# ============================================================================
# main — error paths
# ============================================================================

class TestMainErrors:
    """Tests for error handling in main()."""

    def test_missing_scenes_csv_exits(self, mock_api, mock_git, mock_costs, tmp_path, monkeypatch):
        empty_dir = str(tmp_path / 'bad-project')
        os.makedirs(os.path.join(empty_dir, 'reference'), exist_ok=True)
        # Create storyforge.yaml but no scenes.csv
        with open(os.path.join(empty_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n')
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: empty_dir)
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_missing_intent_csv_exits(self, mock_api, mock_git, mock_costs, tmp_path, monkeypatch):
        proj = str(tmp_path / 'no-intent')
        os.makedirs(os.path.join(proj, 'reference'), exist_ok=True)
        with open(os.path.join(proj, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test\n  genre: fantasy\n')
        # Create scenes.csv but not scene-intent.csv
        with open(os.path.join(proj, 'reference', 'scenes.csv'), 'w') as f:
            f.write('id|seq|title\nsc1|1|Test Scene\n')
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: proj)
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

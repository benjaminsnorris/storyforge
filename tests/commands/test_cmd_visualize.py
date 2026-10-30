"""Tests for storyforge.cmd_visualize — writes the dashboard's data.

Bookshelf renders the dashboard (#371); visualize writes the data publish
sends to working/dashboard-data.json.
"""

import json
import os

import pytest

from storyforge.cmd_visualize import main, parse_args


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert not args.dry_run and not args.open

    def test_open_is_still_accepted(self):
        assert parse_args(['--open']).open


class TestMain:
    def _run(self, project_dir, monkeypatch, argv):
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: project_dir)
        main(argv)
        return os.path.join(project_dir, 'working', 'dashboard-data.json')

    def test_writes_the_data_publish_sends(self, mock_api, mock_git, mock_costs,
                                           project_dir, monkeypatch, capsys):
        from storyforge.visualize import load_dashboard_data
        path = self._run(project_dir, monkeypatch, [])
        with open(path) as f:
            written = json.load(f)
        expected = load_dashboard_data(project_dir)
        written['project'].pop('generated'), expected['project'].pop('generated')
        assert written == expected
        assert written['schema_version'] == 1
        assert 'Bookshelf renders the dashboard' in capsys.readouterr().out

    def test_renders_no_html_and_commits_nothing(self, mock_api, mock_git, mock_costs,
                                                 project_dir, monkeypatch):
        self._run(project_dir, monkeypatch, ['--open'])
        assert not os.path.exists(os.path.join(project_dir, 'working', 'dashboard.html'))
        assert mock_git.calls_for('commit_and_push') == []
        assert mock_api.call_count == 0

    def test_dry_run_writes_nothing(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch, capsys):
        path = self._run(project_dir, monkeypatch, ['--dry-run'])
        assert not os.path.exists(path)
        assert 'DRY RUN' in capsys.readouterr().out

    def test_missing_scenes_csv_exits(self, mock_api, mock_git, mock_costs, tmp_path,
                                      monkeypatch):
        empty_dir = str(tmp_path / 'bad-project')
        os.makedirs(os.path.join(empty_dir, 'reference'))
        monkeypatch.setattr('storyforge.cmd_visualize.detect_project_root', lambda: empty_dir)
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1


def test_storyforge_ships_no_dashboard_html():
    """#371 acceptance: Storyforge contains no dashboard HTML."""
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    assert not os.path.exists(os.path.join(root, 'templates', 'dashboard.html'))

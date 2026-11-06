"""Tests for fixture_helpers.copy_fixture and the tmp-retention settings (#296).

A checkout's gitignored leftovers in tests/fixtures/test-project (6.7 MB of
old working/logs output) were copied for every project_dir test: ~18 GB of
temp per full run.
"""

import os
import subprocess

from conftest import FIXTURE_DIR, FIXTURE_DIR_GN
from fixture_helpers import copy_fixture, fixture_files


def _write(path, text='x\n'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def _git(cwd, *args):
    subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, env={
        **os.environ,
        'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@test.com',
        'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@test.com',
    })


def _listing(root):
    return sorted(os.path.relpath(os.path.join(d, f), root)
                  for d, _, files in os.walk(root) for f in files)


def _repo_with_fixture(tmp_path):
    """A git repo whose `fixture/` mirrors test-project's situation:
    working/ is gitignored, one working/ file is force-added, and a
    leftover log sits ignored in working/logs."""
    repo = tmp_path / 'repo'
    fixture = repo / 'fixture'
    _write(str(repo / '.gitignore'), 'working/\n')
    _write(str(fixture / 'storyforge.yaml'), 'project:\n  title: T\n')
    _write(str(fixture / 'scenes' / 'a.md'), 'Prose.\n')
    _write(str(fixture / 'working' / 'pipeline.csv'), 'cycle|status\n')
    _git(str(repo), 'init', '-b', 'main')
    _git(str(repo), 'add', '.gitignore', 'fixture/storyforge.yaml', 'fixture/scenes/a.md')
    _git(str(repo), 'add', '-f', 'fixture/working/pipeline.csv')
    _git(str(repo), 'commit', '-m', 'fixture')
    _write(str(fixture / 'working' / 'logs' / 'drafting-log.txt'), 'log line\n' * 1000)
    return fixture


class TestCopyFixture:
    def test_leaves_out_gitignored_leftovers(self, tmp_path):
        fixture = _repo_with_fixture(tmp_path)
        dest = copy_fixture(fixture, tmp_path / 'copy')
        assert _listing(dest) == ['scenes/a.md', 'storyforge.yaml', 'working/pipeline.csv']

    def test_copies_untracked_unignored_files(self, tmp_path):
        """A fixture file being added is copied before it is staged."""
        fixture = _repo_with_fixture(tmp_path)
        _write(str(fixture / 'reference' / 'new.csv'), 'id\n')
        dest = copy_fixture(fixture, tmp_path / 'copy')
        assert 'reference/new.csv' in _listing(dest)

    def test_skips_tracked_file_deleted_from_disk(self, tmp_path):
        fixture = _repo_with_fixture(tmp_path)
        os.remove(fixture / 'scenes' / 'a.md')
        dest = copy_fixture(fixture, tmp_path / 'copy')
        assert 'scenes/a.md' not in _listing(dest)

    def test_copies_content(self, tmp_path):
        fixture = _repo_with_fixture(tmp_path)
        dest = copy_fixture(fixture, tmp_path / 'copy')
        with open(os.path.join(dest, 'storyforge.yaml')) as f:
            assert f.read() == 'project:\n  title: T\n'

    def test_outside_git_copies_everything(self, tmp_path):
        src = tmp_path / 'plain'
        _write(str(src / 'storyforge.yaml'))
        _write(str(src / 'working' / 'logs' / 'drafting-log.txt'))
        assert fixture_files(str(src)) is None
        dest = copy_fixture(src, tmp_path / 'copy')
        assert _listing(dest) == ['storyforge.yaml', 'working/logs/drafting-log.txt']


class TestProjectDirFixtures:
    def test_project_dir_is_the_committed_fixture(self, project_dir):
        assert _listing(project_dir) == list(fixture_files(str(FIXTURE_DIR)))

    def test_project_dir_gn_is_the_committed_fixture(self, project_dir_gn):
        assert _listing(project_dir_gn) == list(fixture_files(str(FIXTURE_DIR_GN)))

    def test_fixture_stays_small(self):
        """The copied tree is what every project_dir test pays for."""
        for root in (FIXTURE_DIR, FIXTURE_DIR_GN):
            size = sum(os.path.getsize(os.path.join(root, f)) for f in fixture_files(str(root)))
            assert size < 500_000, f'{root} copies {size} bytes per test'

    def test_writes_to_project_dir_do_not_reach_the_fixture(self, project_dir):
        yaml_path = os.path.join(project_dir, 'storyforge.yaml')
        with open(yaml_path, 'a') as f:
            f.write('# mutated by test\n')
        with open(FIXTURE_DIR / 'storyforge.yaml') as f:
            assert '# mutated by test' not in f.read()


def test_tmp_retention_is_capped(pytestconfig):
    """Passing tests' tmp dirs are deleted; one failing run is kept."""
    assert pytestconfig.getini('tmp_path_retention_policy') == 'failed'
    assert int(pytestconfig.getini('tmp_path_retention_count')) == 1

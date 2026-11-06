"""Tests for fixture_helpers and the tmp-retention settings (#296).

A checkout's gitignored leftovers in tests/fixtures/test-project (6.7 MB of
old working/logs output) were copied for every project_dir test: ~18 GB of
temp per full run.
"""

import os
import subprocess

import pytest

import fixture_helpers
from fixture_helpers import (
    FIXTURE_DIR, FIXTURE_DIR_GN, assert_committed_copy, committable_files,
    copy_fixture, ignored_sentinel,
)


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


COMMITTED = ['scenes/a.md', 'storyforge.yaml', 'working/pipeline.csv']


def _repo_with_fixture(tmp_path, gitignore='working/\n*.log\n'):
    """A git repo whose `fixture/` mirrors test-project's situation:
    working/ is gitignored, one working/ file is force-added, and a
    leftover log sits ignored in working/logs."""
    repo = tmp_path / 'repo'
    fixture = repo / 'fixture'
    _write(str(repo / '.gitignore'), gitignore)
    _write(str(fixture / 'storyforge.yaml'), 'project:\n  title: T\n')
    _write(str(fixture / 'scenes' / 'a.md'), 'Prose.\n')
    _write(str(fixture / 'working' / 'pipeline.csv'), 'cycle|status\n')
    _git(str(repo), 'init', '-b', 'main')
    _git(str(repo), 'add', '-f', '.')
    _git(str(repo), 'commit', '-m', 'fixture')
    _write(str(fixture / 'working' / 'logs' / 'drafting-log.txt'), 'log line\n' * 1000)
    return fixture


@pytest.fixture
def no_repo_above(tmp_path, monkeypatch):
    """git doesn't look above tmp_path, even when the tmp dir sits inside
    a repository."""
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path))


class TestCopyFixture:
    def test_leaves_out_gitignored_leftovers(self, tmp_path):
        fixture = _repo_with_fixture(tmp_path)
        assert _listing(copy_fixture(fixture, tmp_path / 'copy')) == COMMITTED

    def test_copies_untracked_unignored_files(self, tmp_path):
        """A fixture file being added is copied before it is staged."""
        fixture = _repo_with_fixture(tmp_path)
        _write(str(fixture / 'reference' / 'new.csv'), 'id\n')
        assert 'reference/new.csv' in _listing(copy_fixture(fixture, tmp_path / 'copy'))

    def test_skips_tracked_file_deleted_from_disk(self, tmp_path):
        fixture = _repo_with_fixture(tmp_path)
        os.remove(fixture / 'scenes' / 'a.md')
        assert 'scenes/a.md' not in _listing(copy_fixture(fixture, tmp_path / 'copy'))

    def test_reports_a_tracked_entry_that_is_not_a_file(self, tmp_path):
        """SF-4: a broken symlink (or submodule) is reported, not silently
        dropped."""
        fixture = _repo_with_fixture(tmp_path)
        os.symlink('missing-target', fixture / 'scenes' / 'link.md')
        _git(str(fixture.parent), 'add', 'fixture/scenes/link.md')
        with pytest.warns(UserWarning, match=r'not regular files.*scenes/link\.md'):
            dest = copy_fixture(fixture, tmp_path / 'copy')
        assert _listing(dest) == COMMITTED

    def test_copies_content(self, tmp_path):
        fixture = _repo_with_fixture(tmp_path)
        dest = copy_fixture(fixture, tmp_path / 'copy')
        with open(os.path.join(dest, 'storyforge.yaml')) as f:
            assert f.read() == 'project:\n  title: T\n'


class TestGitEnvironment:
    """SF-2: git inside a hook or `rebase --exec` has GIT_DIR / GIT_INDEX_FILE
    set for the outer repository."""

    def test_git_dir_of_another_repo_is_ignored(self, tmp_path, monkeypatch):
        fixture = _repo_with_fixture(tmp_path)
        other = tmp_path / 'other'
        _write(str(other / 'unrelated.txt'))
        _git(str(other), 'init', '-b', 'main')
        monkeypatch.setenv('GIT_DIR', str(other / '.git'))
        monkeypatch.setenv('GIT_WORK_TREE', str(other))
        assert _listing(copy_fixture(fixture, tmp_path / 'copy')) == COMMITTED

    def test_another_index_file_is_ignored(self, tmp_path, monkeypatch):
        fixture = _repo_with_fixture(tmp_path)
        monkeypatch.setenv('GIT_INDEX_FILE', str(tmp_path / 'empty-index'))
        assert _listing(copy_fixture(fixture, tmp_path / 'copy')) == COMMITTED


class TestGitFailures:
    def test_gitignored_fixture_raises(self, tmp_path):
        """SF-3: an enclosing .gitignore covering the fixture would make an
        empty copy."""
        repo = tmp_path / 'repo'
        _write(str(repo / '.gitignore'), 'fixture/\n')
        _write(str(repo / 'fixture' / 'storyforge.yaml'))
        _git(str(repo), 'init', '-b', 'main')
        with pytest.raises(RuntimeError, match='0 committable files.*no storyforge.yaml'):
            copy_fixture(repo / 'fixture', tmp_path / 'copy')

    def test_fixture_without_storyforge_yaml_raises(self, tmp_path):
        fixture = _repo_with_fixture(tmp_path)
        with pytest.raises(RuntimeError, match='no storyforge.yaml'):
            committable_files(fixture / 'scenes')

    def test_other_git_failure_raises_with_stderr(self, tmp_path, monkeypatch):
        """SF-1: e.g. a safe.directory refusal is not "outside git"."""
        fixture = _repo_with_fixture(tmp_path)
        refused = subprocess.CompletedProcess(
            [], 128, b'', b'fatal: detected dubious ownership in repository')
        monkeypatch.setattr(fixture_helpers, '_git', lambda *a, **k: refused)
        with pytest.raises(RuntimeError, match='dubious ownership'):
            copy_fixture(fixture, tmp_path / 'copy')
        monkeypatch.undo()
        # SF-5: the failure isn't cached.
        assert _listing(copy_fixture(fixture, tmp_path / 'copy2')) == COMMITTED

    def test_outside_git_copies_everything_with_a_warning(self, tmp_path, no_repo_above):
        src = tmp_path / 'plain'
        _write(str(src / 'storyforge.yaml'))
        _write(str(src / 'working' / 'logs' / 'drafting-log.txt'))
        with pytest.warns(UserWarning, match='not in a git work tree'):
            dest = copy_fixture(src, tmp_path / 'copy')
        assert _listing(dest) == ['storyforge.yaml', 'working/logs/drafting-log.txt']
        # SF-5: "outside git" isn't cached either.
        _git(str(src), 'init', '-b', 'main')
        _write(str(src / '.gitignore'), 'working/\n')
        assert committable_files(src) == ('.gitignore', 'storyforge.yaml')

    def test_git_not_installed_copies_everything_with_a_warning(self, tmp_path, monkeypatch):
        src = tmp_path / 'plain'
        _write(str(src / 'storyforge.yaml'))

        def missing(*a, **k):
            raise FileNotFoundError('git')
        monkeypatch.setattr(subprocess, 'run', missing)
        with pytest.warns(UserWarning, match='git is not installed'):
            assert committable_files(src) is None

    def test_cache_key_is_the_real_path(self, tmp_path):
        """TD-3"""
        fixture = _repo_with_fixture(tmp_path)
        link = tmp_path / 'link'
        os.symlink(fixture, link)
        assert committable_files(link) is committable_files(fixture)


class TestProjectFixtures:
    """T-1 / T-2: the conftest fixtures themselves leave out gitignored
    files. tests/commands and tests/integration have their own copies of
    this guard for their conftests."""

    @pytest.mark.parametrize('name, src', [
        ('project_dir', FIXTURE_DIR), ('project_dir_gn', FIXTURE_DIR_GN),
    ])
    def test_copy_leaves_out_gitignored_files(self, request, name, src):
        with ignored_sentinel(src) as sentinel:
            project = request.getfixturevalue(name)
        assert_committed_copy(project, sentinel)

    def test_project_dir_is_the_committed_fixture(self, project_dir):
        assert _listing(project_dir) == list(committable_files(FIXTURE_DIR))

    def test_writes_to_project_dir_do_not_reach_the_fixture(self, project_dir):
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'a') as f:
            f.write('# mutated by test\n')
        with open(FIXTURE_DIR / 'storyforge.yaml') as f:
            assert '# mutated by test' not in f.read()


def test_tmp_retention_is_capped(pytestconfig):
    """Passing tests' tmp dirs are deleted; one failing run is kept."""
    assert pytestconfig.getini('tmp_path_retention_policy') == 'failed'
    assert int(pytestconfig.getini('tmp_path_retention_count')) == 1

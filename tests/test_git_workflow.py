"""Tests for git branch and PR workflow functions (migrated from test-git-workflow.sh).

The git workflow tests rely on bash functions (create_branch, ensure_branch_pushed,
select_model, etc.) from common.sh. We test what is available in Python.
"""

import pytest


@pytest.mark.skip(reason="Git workflow tests are bash-only (create_branch, ensure_branch_pushed, etc.). No Python equivalent.")
def test_git_workflow_placeholder():
    pass


class TestCommitAndPushUpstream:
    """A new branch's commits stayed local: `git push` with no upstream
    failed and the result was ignored (migrate's branch, 2026-10-30)."""

    def _repos(self, tmp_path):
        import subprocess
        remote = tmp_path / 'remote.git'
        work = tmp_path / 'work'
        run = lambda *a, cwd=None: subprocess.run(a, cwd=cwd, check=True,
                                                  capture_output=True)
        run('git', 'init', '-q', '--bare', str(remote))
        run('git', 'init', '-q', '-b', 'main', str(work))
        for k, v in (('user.email', 't@e.st'), ('user.name', 'T')):
            run('git', 'config', k, v, cwd=work)
        (work / 'a.txt').write_text('a\n')
        run('git', 'add', '.', cwd=work)
        run('git', 'commit', '-qm', 'init', cwd=work)
        run('git', 'remote', 'add', 'origin', str(remote), cwd=work)
        run('git', 'push', '-qu', 'origin', 'main', cwd=work)
        run('git', 'checkout', '-qb', 'storyforge/new', cwd=work)
        return remote, work

    def test_a_branch_with_no_upstream_is_pushed_with_one(self, tmp_path):
        import subprocess
        from storyforge.git import commit_and_push
        remote, work = self._repos(tmp_path)
        (work / 'b.txt').write_text('b\n')
        assert commit_and_push(str(work), 'Add b')
        branches = subprocess.run(['git', '-C', str(remote), 'branch'],
                                  capture_output=True, text=True).stdout
        assert 'storyforge/new' in branches

    def test_a_push_that_fails_is_named(self, tmp_path, capsys):
        import shutil
        from storyforge.git import commit_and_push
        remote, work = self._repos(tmp_path)
        shutil.rmtree(remote)
        (work / 'b.txt').write_text('b\n')
        assert commit_and_push(str(work), 'Add b')  # the commit itself happened
        assert 'WARNING: could not push storyforge/new' in capsys.readouterr().out

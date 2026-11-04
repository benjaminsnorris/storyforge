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
        from storyforge import git
        assert 'storyforge/new' in git.unpushed   # for the command's closing summary


class TestAFailedCommit:
    """SF-1/SF-3/SF-4/T-6 (#503's review): a failed commit said nothing and
    left what it staged in the index, so the next commit (the review
    phase's) swept the scene in under its own message."""

    _repos = TestCommitAndPushUpstream._repos

    @staticmethod
    def _git(work, *a):
        import subprocess
        return subprocess.run(['git', '-C', str(work), *a], capture_output=True,
                              text=True).stdout

    def _rejecting(self, tmp_path):
        remote, work = self._repos(tmp_path)
        hook = work / '.git' / 'hooks' / 'pre-commit'
        hook.write_text('#!/bin/sh\necho "hook says no" >&2\nexit 1\n')
        hook.chmod(0o755)
        return work

    def test_it_says_why_and_unstages_what_it_staged(self, tmp_path, capsys):
        from storyforge import git
        work = self._rejecting(tmp_path)
        (work / 'b.txt').write_text('b\n')
        assert git.commit_and_push(str(work), 'Add b', ['b.txt']) is False
        assert 'hook says no' in git.last_commit_error
        assert 'WARNING: git commit "Add b" failed: hook says no' in capsys.readouterr().out
        assert self._git(work, 'diff', '--cached', '--name-only').strip() == ''

    def test_commit_or_raise_carries_gits_reason(self, tmp_path):
        from storyforge import git
        work = self._rejecting(tmp_path)
        (work / 'b.txt').write_text('b\n')
        with pytest.raises(git.CommitError, match='the commit "Add b" failed: hook says no'):
            git.commit_or_raise(str(work), 'Add b', ['b.txt'])

    def test_nothing_to_commit_in_a_real_repo_is_not_a_failure(self, tmp_path, capsys):
        from storyforge import git
        remote, work = self._repos(tmp_path)
        before = self._git(work, 'rev-parse', 'HEAD')
        git.commit_or_raise(str(work), 'Nothing', ['a.txt'])     # no raise
        assert git.commit_and_push(str(work), 'Nothing', ['a.txt']) is False
        assert git.last_commit_error == git.NOTHING_TO_COMMIT
        assert 'WARNING' not in capsys.readouterr().out
        assert self._git(work, 'rev-parse', 'HEAD') == before

    def test_write_skips_a_rechecks_empty_commit_in_a_real_repo(self, tmp_path):
        """The real write path: a re-check that ran nothing commits nothing."""
        from storyforge import cmd_write
        remote, work = self._repos(tmp_path)
        (work / 'reference').mkdir()
        (work / 'reference' / 'x.csv').write_text('id\n')
        self._git(work, 'add', '.')
        self._git(work, 'commit', '-qm', 'ref')
        before = self._git(work, 'rev-parse', 'HEAD')
        cmd_write._commit(str(work), 'Re-check after x: 0 passed',
                          ['reference/', 'working/logs/', 'working/gate-pending.csv'])
        assert self._git(work, 'rev-parse', 'HEAD') == before


class TestCommitOnlyThePaths:
    """#509 CR-1: `git add <paths>` then a bare `git commit` took the whole
    index, so a file the author had staged rode along in the command's
    commit under its message."""

    _repos = TestCommitAndPushUpstream._repos
    _git = staticmethod(TestAFailedCommit._git)

    def _committed(self, work):
        return self._git(work, 'show', '--name-only', '--no-renames', '--format=',
                         'HEAD').split()

    def test_a_pre_staged_file_stays_staged_and_out(self, tmp_path):
        from storyforge import git
        remote, work = self._repos(tmp_path)
        (work / 'reference').mkdir()
        (work / 'reference' / 'scenes.csv').write_text('id|seq\n')
        (work / 'storyforge.yaml').write_text('project: x\n')
        self._git(work, 'add', 'storyforge.yaml')
        assert git.commit_and_push(str(work), 'Renumber', ['reference/scenes.csv'])
        assert self._committed(work) == ['reference/scenes.csv']
        assert self._git(work, 'diff', '--cached', '--name-only').split() == ['storyforge.yaml']

    def test_directories_missing_and_ignored_paths(self, tmp_path):
        """A directory takes in new, changed, deleted and renamed files
        under it; a listed path that doesn't exist or is ignored doesn't
        fail the commit (a pathspec git doesn't know would)."""
        from storyforge import git
        remote, work = self._repos(tmp_path)
        (work / 'scenes').mkdir()
        for name in ('gone', 'old', 'kept'):
            (work / 'scenes' / f'{name}.md').write_text(f'{name}\n' * 20)
        (work / '.gitignore').write_text('ignored.csv\n')
        self._git(work, 'add', '.')
        self._git(work, 'commit', '-qm', 'scenes')
        (work / 'scenes' / 'gone.md').unlink()
        self._git(work, 'mv', 'scenes/old.md', 'scenes/new.md')
        (work / 'scenes' / 'kept.md').write_text('changed\n')
        (work / 'scenes' / 'added.md').write_text('added\n')
        (work / 'ignored.csv').write_text('x\n')
        (work / 'a.txt').write_text('outside\n')
        assert git.commit_and_push(str(work), 'Scenes',
                                   ['scenes/', 'missing.csv', 'ignored.csv'])
        assert sorted(self._committed(work)) == [
            'scenes/added.md', 'scenes/gone.md', 'scenes/kept.md',
            'scenes/new.md', 'scenes/old.md']
        assert self._git(work, 'status', '--porcelain', '--', 'a.txt').strip() == 'M a.txt'

    def test_only_other_files_staged_is_nothing_to_commit(self, tmp_path):
        from storyforge import git
        remote, work = self._repos(tmp_path)
        before = self._git(work, 'rev-parse', 'HEAD')
        (work / 'storyforge.yaml').write_text('project: x\n')
        self._git(work, 'add', 'storyforge.yaml')
        assert git.commit_and_push(str(work), 'Nothing', ['a.txt']) is False
        assert git.last_commit_error == git.NOTHING_TO_COMMIT
        assert self._git(work, 'rev-parse', 'HEAD') == before

    def test_a_filename_with_pathspec_magic_is_taken_literally(self, tmp_path):
        from storyforge import git
        remote, work = self._repos(tmp_path)
        (work / 'x[1].md').write_text('x\n')
        (work / 'x1.md').write_text('decoy\n')
        assert git.commit_and_push(str(work), 'Literal', ['x[1].md'])
        assert self._committed(work) == ['x[1].md']


class TestCommitInASubfolder:
    """A project in a subfolder of its repo (every storyforge-evals book is
    `projects/<book>/`): `git diff --cached --name-only` printed the staged
    files relative to the repo root, and `git commit -- files`, run in the
    project, read them against the project folder, so every commit with
    paths failed ("pathspec 'projects/telemachy-teen/reference/source/...'
    did not match", `source import`, 2026-11-03)."""

    _git = staticmethod(TestAFailedCommit._git)

    def _repos(self, tmp_path, prefix):
        """The upstream repos, with the project at `prefix` inside the work
        tree ('' for the repo root) and a sibling project beside it."""
        remote, work = TestCommitAndPushUpstream._repos(self, tmp_path)
        project = work / prefix if prefix else work
        sibling = work / 'projects' / 'other'
        for d in (project / 'scenes', sibling):
            d.mkdir(parents=True, exist_ok=True)
        for name in ('gone', 'old', 'kept', 'two words', 'café'):
            (project / 'scenes' / f'{name}.md').write_text(f'{name}\n' * 20)
        (sibling / 'notes.md').write_text('sibling\n')
        self._git(work, 'add', '.')
        self._git(work, 'commit', '-qm', 'projects')
        return work, project

    def _committed(self, work):
        return sorted(self._git(work, 'show', '--name-only', '--no-renames', '-z',
                                '--format=', 'HEAD').strip('\0\n').split('\0'))

    @pytest.mark.parametrize('prefix', ['projects/book', ''])
    def test_new_changed_deleted_renamed_and_oddly_named_files(self, tmp_path, prefix):
        from storyforge import git
        work, project = self._repos(tmp_path, prefix)
        top = f'{prefix}/' if prefix else ''
        (project / 'scenes' / 'gone.md').unlink()
        self._git(project, 'mv', 'scenes/old.md', 'scenes/new.md')
        (project / 'scenes' / 'kept.md').write_text('changed\n')
        (project / 'scenes' / 'two words.md').write_text('changed\n')
        (project / 'scenes' / 'café.md').write_text('changed\n')
        (project / 'scenes' / 'añadido.md').write_text('added\n')
        (work / 'projects' / 'other' / 'notes.md').write_text('sibling edit\n')
        self._git(work, 'add', 'projects/other/notes.md')   # staged, not ours
        assert git.commit_and_push(str(project), 'Scenes', ['scenes/', 'missing.csv']), \
            git.last_commit_error
        assert self._committed(work) == sorted(
            f'{top}scenes/{n}.md' for n in
            ('añadido', 'café', 'gone', 'kept', 'new', 'old', 'two words'))
        assert self._git(work, 'diff', '--cached', '--name-only').split() == \
            ['projects/other/notes.md']

    def test_a_subfolder_project_commits_only_its_paths(self, tmp_path):
        """The real failure: `source import` in `projects/telemachy-teen`."""
        from storyforge import git
        work, project = self._repos(tmp_path, 'projects/telemachy-teen')
        src = project / 'reference' / 'source' / 'odyssey'
        src.mkdir(parents=True)
        (src / 'architecture.csv').write_text('id|summary\n')
        (project / 'storyforge.yaml').write_text('project: x\n')
        assert git.commit_and_push(str(project), 'Source: import odyssey',
                                   ['reference/source/odyssey']), git.last_commit_error
        assert self._committed(work) == [
            'projects/telemachy-teen/reference/source/odyssey/architecture.csv']
        assert self._git(work, 'status', '--porcelain', '--',
                         'projects/telemachy-teen/storyforge.yaml').strip() == \
            '?? projects/telemachy-teen/storyforge.yaml'

    def test_with_no_paths_a_sibling_project_is_not_swept_in(self, tmp_path):
        """`git add -A` with no pathspec stages the whole work tree wherever
        it is run, so a subfolder project's commit took a sibling project's
        unstaged edits under its own message."""
        from storyforge import git
        work, project = self._repos(tmp_path, 'projects/book')
        (project / 'scenes' / 'kept.md').write_text('changed\n')
        (work / 'projects' / 'other' / 'notes.md').write_text('sibling edit\n')
        assert git.commit_and_push(str(project), 'Elaborate'), git.last_commit_error
        assert self._committed(work) == ['projects/book/scenes/kept.md']
        assert self._git(work, 'status', '--porcelain', '--',
                         'projects/other').strip() == 'M projects/other/notes.md'

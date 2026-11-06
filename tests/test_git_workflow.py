"""Tests for git branch and PR workflow functions (migrated from test-git-workflow.sh).

The git workflow tests rely on bash functions (create_branch, ensure_branch_pushed,
select_model, etc.) from common.sh. We test what is available in Python.
"""

import os

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
        tree ('' for the repo root) and another project at `projects/other`
        (beside it in a subfolder, inside it at the repo root)."""
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

    def test_with_no_paths_a_file_already_staged_elsewhere_goes_in(self, tmp_path):
        """Documented, not a guarantee: no paths commits the whole index,
        which cleanup's `git rm --cached` sweep needs (`commit -- .` would
        drop its removals)."""
        from storyforge import git
        work, project = self._repos(tmp_path, 'projects/book')
        (project / 'scenes' / 'kept.md').write_text('changed\n')
        (work / 'projects' / 'other' / 'notes.md').write_text('sibling edit\n')
        self._git(work, 'add', 'projects/other/notes.md')
        (project / 'working.log').write_text('log\n')
        self._git(work, 'add', 'projects/book/working.log')
        self._git(work, 'commit', '-qm', 'log', '--', 'projects/book/working.log')
        (project / '.gitignore').write_text('working.log\n')
        self._git(project, 'rm', '--cached', '-q', 'working.log')
        assert git.commit_and_push(str(project), 'Cleanup'), git.last_commit_error
        assert self._committed(work) == [
            'projects/book/.gitignore', 'projects/book/scenes/kept.md',
            'projects/book/working.log', 'projects/other/notes.md']
        assert 'working.log' not in self._git(project, 'ls-files')

    @pytest.mark.parametrize('outside', ['../other/notes.md', '../../a.txt', 'ABS'])
    def test_a_path_outside_the_project_is_refused_and_nothing_staged(
            self, tmp_path, capsys, outside):
        """`--relative` can't list a path outside project_dir, so it was
        staged, left out, and reported as nothing to commit."""
        from storyforge import git
        work, project = self._repos(tmp_path, 'projects/book')
        if outside == 'ABS':
            outside = str(work / 'projects' / 'other' / 'notes.md')
        (work / 'projects' / 'other' / 'notes.md').write_text('sibling edit\n')
        (work / 'a.txt').write_text('root edit\n')
        (project / 'scenes' / 'kept.md').write_text('changed\n')
        before = self._git(work, 'rev-parse', 'HEAD')
        assert git.commit_and_push(str(project), 'Mixed', ['scenes/', outside]) is False
        assert git.last_commit_error.startswith('outside the project folder')
        assert 'WARNING: git commit "Mixed" failed: outside the project folder' in \
            capsys.readouterr().out
        assert self._git(work, 'rev-parse', 'HEAD') == before
        assert self._git(work, 'diff', '--cached', '--name-only').strip() == ''
        with pytest.raises(git.CommitError, match='outside the project folder'):
            git.commit_or_raise(str(project), 'Mixed', [outside])

    def test_an_absolute_path_inside_the_project_is_committed(self, tmp_path):
        """cmd_revise passes `os.path.join(project_dir, ...)`."""
        from storyforge import git
        work, project = self._repos(tmp_path, 'projects/book')
        (project / 'scenes' / 'kept.md').write_text('changed\n')
        assert git.commit_and_push(str(project), 'Abs',
                                   [str(project / 'scenes' / 'kept.md')])
        assert self._committed(work) == ['projects/book/scenes/kept.md']

    @pytest.mark.skipif(not hasattr(os, 'geteuid') or os.geteuid() == 0,
                        reason='root reads an unreadable file')
    @pytest.mark.parametrize('paths', [['scenes/'], None])
    def test_a_failed_add_is_a_failure_not_nothing_to_commit(self, tmp_path, capsys, paths):
        """`git add` exited 128 on an unreadable file, staged nothing, and the
        empty listing (or commit's "no changes added") read as nothing to
        commit, so `commit_or_raise` called it success."""
        from storyforge import git
        work, project = self._repos(tmp_path, 'projects/book')
        (project / 'scenes' / 'kept.md').write_text('changed\n')
        locked = project / 'scenes' / 'locked.md'
        locked.write_text('x\n')
        locked.chmod(0)
        try:
            assert git.commit_and_push(str(project), 'Add', paths) is False
            assert git.last_commit_error != git.NOTHING_TO_COMMIT
            assert 'WARNING: git commit "Add" failed: could not stage' in capsys.readouterr().out
            with pytest.raises(git.CommitError):
                git.commit_or_raise(str(project), 'Add', paths)
        finally:
            locked.chmod(0o644)
        assert self._git(work, 'diff', '--cached', '--name-only').strip() == ''

    def test_nothing_under_the_paths_with_a_sibling_staged(self, tmp_path):
        from storyforge import git
        work, project = self._repos(tmp_path, 'projects/book')
        before = self._git(work, 'rev-parse', 'HEAD')
        (work / 'projects' / 'other' / 'notes.md').write_text('sibling edit\n')
        self._git(work, 'add', 'projects/other/notes.md')
        assert git.commit_and_push(str(project), 'Nothing', ['scenes/']) is False
        assert git.last_commit_error == git.NOTHING_TO_COMMIT
        assert self._git(work, 'rev-parse', 'HEAD') == before
        assert self._git(work, 'diff', '--cached', '--name-only').split() == \
            ['projects/other/notes.md']

    @pytest.mark.parametrize('paths', [['scenes/'], None])
    def test_a_rejected_commit_unstages_only_its_own(self, tmp_path, capsys, paths):
        from storyforge import git
        work, project = self._repos(tmp_path, 'projects/book')
        hook = work / '.git' / 'hooks' / 'pre-commit'
        hook.write_text('#!/bin/sh\necho "hook says no" >&2\nexit 1\n')
        hook.chmod(0o755)
        (work / 'a.txt').write_text('root edit\n')
        self._git(work, 'add', 'a.txt')
        (project / 'scenes' / 'kept.md').write_text('changed\n')
        with pytest.raises(git.CommitError, match='hook says no'):
            git.commit_or_raise(str(project), 'Add', paths)
        assert 'WARNING: git commit "Add" failed: hook says no' in capsys.readouterr().out
        assert self._git(work, 'diff', '--cached', '--name-only').split() == ['a.txt']

    def test_source_import_in_a_subfolder_project(self, tmp_path, monkeypatch):
        """End to end: the command that failed (telemachy-teen, 2026-11-03)."""
        import subprocess
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from source_helpers import make_adaptation
        from storyforge import cmd_source
        work = tmp_path / 'evals'
        work.mkdir()
        project = make_adaptation(work / 'projects')
        for a in (('init', '-q', '-b', 'main'), ('config', 'user.email', 't@e.st'),
                  ('config', 'user.name', 'T'), ('add', '.'), ('commit', '-qm', 'init')):
            subprocess.run(['git', '-C', str(work), *a], check=True, capture_output=True)
        monkeypatch.chdir(project)
        assert cmd_source.main(['import']) == 0
        assert self._git(work, 'rev-parse', '--abbrev-ref', 'HEAD').startswith(
            'storyforge/source-import-')
        committed = self._committed(work)
        # the import, plus the empty registries it seeds from the source (B-013)
        seeded = {f'projects/telemachus/reference/{n}' for n in ('characters.csv', 'locations.csv')}
        assert committed and all(
            f.startswith('projects/telemachus/reference/source/odyssey/') or f in seeded
            for f in committed)
        assert seeded <= set(committed)
        assert self._git(work, 'status', '--porcelain', '--', 'projects/telemachus/reference/source') == ''


class TestWorkTreeProblem:
    """#520 review (SF-A, SF-B/TD-2): `in_work_tree` was a bool that lumped
    git missing, no repository, a refused (`safe.directory`) and a broken
    repository together and dropped git's message, so warnings named the
    wrong cause; and it was True inside any repository, even one that isn't
    the project's (a dotfiles repo in ~)."""

    @staticmethod
    def _run(cwd, *a):
        import subprocess
        subprocess.run(['git', '-C', str(cwd), *a], check=True, capture_output=True)

    def _ceiling(self, tmp_path, monkeypatch):
        monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path.parent))

    def test_no_repository(self, tmp_path, monkeypatch):
        from storyforge import git
        self._ceiling(tmp_path, monkeypatch)
        assert git.work_tree_problem(str(tmp_path)) == git.NOT_A_REPOSITORY
        assert git.in_work_tree(str(tmp_path)) is False

    def test_git_not_installed(self, tmp_path, monkeypatch):
        from storyforge import git
        empty = tmp_path / 'empty-path'
        empty.mkdir()
        monkeypatch.setenv('PATH', str(empty))
        assert git.work_tree_problem(str(tmp_path)) == 'git is not installed'

    def test_a_refused_repository_carries_gits_reason(self, tmp_path, monkeypatch):
        from storyforge import git
        self._ceiling(tmp_path, monkeypatch)
        self._run(tmp_path, 'init', '-q')
        monkeypatch.setenv('GIT_TEST_ASSUME_DIFFERENT_OWNER', '1')
        why = git.work_tree_problem(str(tmp_path))
        assert why != git.NOT_A_REPOSITORY and 'dubious ownership' in why

    def test_a_broken_git_file_is_not_no_repository(self, tmp_path, monkeypatch):
        from storyforge import git
        self._ceiling(tmp_path, monkeypatch)
        (tmp_path / '.git').write_text('gitdir: /nonexistent\n')
        why = git.work_tree_problem(str(tmp_path))
        assert why != git.NOT_A_REPOSITORY and '/nonexistent' in why

    def test_subfolder_and_worktree_projects(self, tmp_path):
        from storyforge import git
        work, project = TestCommitInASubfolder()._repos(tmp_path, 'projects/book')
        assert git.work_tree_problem(str(project)) == ''
        wt = tmp_path / 'wt'
        self._run(work, 'worktree', 'add', '-q', '-b', 'storyforge/wt', str(wt))
        assert git.work_tree_problem(str(wt)) == ''

    def _parent(self, tmp_path, ignore):
        root = tmp_path / 'home'
        book = root / 'Writing' / 'book'
        book.mkdir(parents=True)
        (book / 'storyforge.yaml').write_text('project: x\n')
        (root / '.zshrc').write_text('x\n')
        if ignore:
            (root / '.gitignore').write_text('Writing/\n')
        self._run(root, 'init', '-q')
        self._run(root, 'add', '.zshrc', *(['.gitignore'] if ignore else []))
        self._run(root, '-c', 'user.email=t@e.st', '-c', 'user.name=T',
                  'commit', '-qm', 'dotfiles')
        return root, book

    def test_an_unrelated_parent_repository_is_named(self, tmp_path):
        from storyforge import git
        root, book = self._parent(tmp_path, ignore=False)
        why = git.project_repo_problem(str(book))
        assert why == (f'the git repository at {os.path.realpath(root)} does not track '
                       f'this project (its storyforge.yaml is not committed there)')

    def test_a_parent_repository_that_ignores_the_project(self, tmp_path):
        from storyforge import git
        root, book = self._parent(tmp_path, ignore=True)
        assert git.project_repo_problem(str(book)) == \
            f'the git repository at {os.path.realpath(root)} ignores this project'

    def test_a_tracked_subfolder_project_and_a_new_projects_own_repo(self, tmp_path):
        from storyforge import git
        work, project = TestCommitInASubfolder()._repos(tmp_path, 'projects/book')
        (project / 'storyforge.yaml').write_text('project: x\n')
        self._run(work, 'add', '.')
        self._run(work, 'commit', '-qm', 'yaml')
        assert git.project_repo_problem(str(project)) == ''
        fresh = tmp_path / 'fresh'
        fresh.mkdir()
        (fresh / 'storyforge.yaml').write_text('project: x\n')
        self._run(fresh, 'init', '-q')
        assert git.project_repo_problem(str(fresh)) == ''


class TestAFailedCommitRestoresTheIndex:
    """#520 review (SF-C): on a failed commit, `reset -- paths` (or `-- .`)
    unstaged more than the call had staged: the author's own staged edits
    under the paths, and the `git rm --cached` removals cleanup had just
    made, while the WARNING said only its own files were unstaged."""

    _git = staticmethod(TestAFailedCommit._git)

    def _index(self, work):
        return self._git(work, 'ls-files', '-s')

    def _rejecting_subfolder(self, tmp_path):
        work, project = TestCommitInASubfolder()._repos(tmp_path, 'projects/book')
        hook = work / '.git' / 'hooks' / 'pre-commit'
        hook.write_text('#!/bin/sh\necho "hook says no" >&2\nexit 1\n')
        hook.chmod(0o755)
        return work, project

    def test_an_authors_staged_edit_under_the_paths_stays_staged(self, tmp_path, capsys):
        from storyforge import git
        work, project = self._rejecting_subfolder(tmp_path)
        (project / 'scenes' / 'kept.md').write_text('the author staged this\n')
        self._git(project, 'add', 'scenes/kept.md')
        (project / 'scenes' / 'kept.md').write_text('and kept editing\n')
        (project / 'scenes' / 'new.md').write_text('ours\n')
        before = self._index(work)
        assert git.commit_and_push(str(project), 'Scenes', ['scenes/']) is False
        assert self._index(work) == before
        assert 'the index is as it was before' in capsys.readouterr().out

    def test_cleanups_removals_survive_a_failed_commit(self, tmp_path):
        from storyforge import git
        work, project = self._rejecting_subfolder(tmp_path)
        self._git(project, 'rm', '--cached', '-q', 'scenes/gone.md')
        (project / 'scenes' / 'kept.md').write_text('cleaned\n')
        before = self._index(work)
        assert git.commit_and_push(str(project), 'Cleanup') is False
        assert self._index(work) == before
        assert 'projects/book/scenes/gone.md' not in self._git(work, 'ls-files')

    def test_a_sibling_projects_staged_file_stays_staged(self, tmp_path):
        from storyforge import git
        work, project = self._rejecting_subfolder(tmp_path)
        (work / 'projects' / 'other' / 'notes.md').write_text('sibling\n')
        self._git(work, 'add', 'projects/other/notes.md')
        (project / 'scenes' / 'kept.md').write_text('cleaned\n')
        before = self._index(work)
        assert git.commit_and_push(str(project), 'Cleanup') is False
        assert self._index(work) == before

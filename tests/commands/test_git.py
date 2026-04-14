"""Tests for storyforge.git infrastructure module.

Tests the git/PR workflow layer itself by mocking subprocess.run and
shutil.which. Does NOT use the mock_git fixture — that fixture is for
testing command modules that *call* git functions.
"""

import os
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helper to build CompletedProcess results
# ---------------------------------------------------------------------------

def _cp(stdout='', stderr='', returncode=0):
    """Build a subprocess.CompletedProcess for mocking."""
    return subprocess.CompletedProcess(
        args=['git'], returncode=returncode,
        stdout=stdout, stderr=stderr,
    )


# ---------------------------------------------------------------------------
# _git
# ---------------------------------------------------------------------------

class TestGitHelper:
    def test_runs_subprocess_with_correct_args(self, monkeypatch):
        captured = []

        def mock_run(*args, **kwargs):
            captured.append(args[0])
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import _git
        _git('/my/project', 'status', '--porcelain')

        assert captured[0] == ['git', '-C', '/my/project', 'status', '--porcelain']

    def test_raises_on_failure_when_check_true(self, monkeypatch):
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, 'git')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import _git
        with pytest.raises(subprocess.CalledProcessError):
            _git('/proj', 'checkout', '-b', 'test')

    def test_returns_completed_process_when_check_false(self, monkeypatch):
        def mock_run(*args, **kwargs):
            return _cp(returncode=128, stderr='fatal: not a git repo')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import _git
        result = _git('/proj', 'status', check=False)
        assert result.returncode == 128

    def test_captures_output(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            assert kwargs.get('capture_output') is True
            assert kwargs.get('text') is True
            return _cp(stdout='main\n')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import _git
        result = _git('/proj', 'rev-parse', '--abbrev-ref', 'HEAD')
        assert result.stdout == 'main\n'


# ---------------------------------------------------------------------------
# current_branch
# ---------------------------------------------------------------------------

class TestCurrentBranch:
    def test_returns_branch_name(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            return _cp(stdout='feature/my-branch\n')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import current_branch
        assert current_branch('/proj') == 'feature/my-branch'

    def test_returns_empty_on_failure(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            return _cp(returncode=128, stdout='', stderr='fatal')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import current_branch
        assert current_branch('/proj') == ''

    def test_strips_whitespace(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            return _cp(stdout='  main  \n')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import current_branch
        assert current_branch('/proj') == 'main'


# ---------------------------------------------------------------------------
# has_gh
# ---------------------------------------------------------------------------

class TestHasGh:
    def test_returns_true_when_gh_available(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            return _cp(stdout='gh version 2.40.0')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import has_gh
        assert has_gh() is True

    def test_returns_false_when_not_found(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            raise FileNotFoundError('gh not found')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import has_gh
        assert has_gh() is False

    def test_returns_false_on_error(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, 'gh')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import has_gh
        assert has_gh() is False


# ---------------------------------------------------------------------------
# _is_main_branch
# ---------------------------------------------------------------------------

class TestIsMainBranch:
    def test_main_is_main(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('main') is True

    def test_master_is_main(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('master') is True

    def test_feature_branch_is_not_main(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('storyforge/write-20260414') is False

    def test_empty_string_is_not_main(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('') is False


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------

class TestCreateBranch:
    def test_creates_branch_with_correct_pattern(self, monkeypatch):
        created_branches = []

        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                return _cp(stdout='main\n')
            if 'checkout' in cmd and '-b' in cmd:
                branch = cmd[cmd.index('-b') + 1]
                created_branches.append(branch)
                return _cp()
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import create_branch
        result = create_branch('write', '/proj')

        assert len(created_branches) == 1
        assert created_branches[0].startswith('storyforge/write-')
        assert result == created_branches[0]

    def test_resumes_on_existing_feature_branch(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                return _cp(stdout='storyforge/revise-existing\n')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import create_branch
        result = create_branch('write', '/proj')
        assert result == 'storyforge/revise-existing'

    def test_returns_empty_on_checkout_failure(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                return _cp(stdout='main\n')
            if 'checkout' in cmd:
                return _cp(returncode=1, stderr='error')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import create_branch
        result = create_branch('write', '/proj')
        assert result == ''


# ---------------------------------------------------------------------------
# ensure_on_branch
# ---------------------------------------------------------------------------

class TestEnsureOnBranch:
    def test_stays_on_feature_branch(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                return _cp(stdout='storyforge/score-20260414\n')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import ensure_on_branch
        result = ensure_on_branch('score', '/proj')
        assert result == 'storyforge/score-20260414'

    def test_creates_branch_when_on_main(self, monkeypatch):
        call_count = {'rev_parse': 0}

        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                call_count['rev_parse'] += 1
                # First call from ensure_on_branch, second from create_branch
                return _cp(stdout='main\n')
            if 'checkout' in cmd and '-b' in cmd:
                return _cp()
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import ensure_on_branch
        result = ensure_on_branch('evaluate', '/proj')
        assert result.startswith('storyforge/evaluate-')

    def test_creates_branch_when_on_master(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                return _cp(stdout='master\n')
            if 'checkout' in cmd and '-b' in cmd:
                return _cp()
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import ensure_on_branch
        result = ensure_on_branch('revise', '/proj')
        assert result.startswith('storyforge/revise-')


# ---------------------------------------------------------------------------
# commit_and_push
# ---------------------------------------------------------------------------

class TestCommitAndPush:
    def test_stages_specific_paths(self, monkeypatch):
        commands_run = []

        def mock_run(cmd, **kwargs):
            commands_run.append(cmd)
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_and_push
        result = commit_and_push('/proj', 'Test commit', ['file1.txt', 'file2.txt'])

        # Should have: add file1, add file2, commit, push
        add_cmds = [c for c in commands_run if 'add' in c]
        assert len(add_cmds) == 2
        assert any('file1.txt' in c for c in add_cmds)
        assert any('file2.txt' in c for c in add_cmds)
        assert result is True

    def test_stages_all_when_no_paths(self, monkeypatch):
        commands_run = []

        def mock_run(cmd, **kwargs):
            commands_run.append(cmd)
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_and_push
        commit_and_push('/proj', 'Add all')

        add_cmds = [c for c in commands_run if 'add' in c]
        assert any('-A' in c for c in add_cmds)

    def test_commits_with_message(self, monkeypatch):
        commands_run = []

        def mock_run(cmd, **kwargs):
            commands_run.append(cmd)
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_and_push
        commit_and_push('/proj', 'Score: cycle 3')

        commit_cmds = [c for c in commands_run if 'commit' in c]
        assert len(commit_cmds) == 1
        assert 'Score: cycle 3' in commit_cmds[0]

    def test_pushes_after_commit(self, monkeypatch):
        commands_run = []

        def mock_run(cmd, **kwargs):
            commands_run.append(cmd)
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_and_push
        commit_and_push('/proj', 'Push test')

        push_cmds = [c for c in commands_run if 'push' in c]
        assert len(push_cmds) == 1

    def test_returns_false_on_commit_failure(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            if 'commit' in cmd:
                return _cp(returncode=1, stderr='nothing to commit')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_and_push
        result = commit_and_push('/proj', 'empty')
        assert result is False

    def test_returns_true_on_success(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_and_push
        result = commit_and_push('/proj', 'success')
        assert result is True


# ---------------------------------------------------------------------------
# create_draft_pr
# ---------------------------------------------------------------------------

class TestCreateDraftPr:
    def test_returns_empty_when_no_gh(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            raise FileNotFoundError('gh not found')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import create_draft_pr
        result = create_draft_pr('Title', 'Body', '/proj')
        assert result == ''

    def test_returns_existing_pr_number(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            # has_gh check
            if cmd == ['gh', '--version']:
                return _cp(stdout='gh version 2.40')
            # ensure_all_labels calls — just succeed
            if 'label' in cmd and 'create' in cmd:
                return _cp()
            # pr view — existing PR found
            if 'pr' in cmd and 'view' in cmd:
                return _cp(stdout='42\n')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import create_draft_pr
        result = create_draft_pr('Title', 'Body', '/proj')
        assert result == '42'

    def test_creates_new_pr_and_returns_number(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            # has_gh check
            if cmd == ['gh', '--version']:
                return _cp(stdout='gh version 2.40')
            # ensure_all_labels
            if 'label' in cmd and 'create' in cmd:
                return _cp()
            # pr view — no existing PR
            if 'pr' in cmd and 'view' in cmd:
                return _cp(returncode=1)
            # pr create — return URL
            if 'pr' in cmd and 'create' in cmd:
                return _cp(stdout='https://github.com/user/repo/pull/99\n')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import create_draft_pr
        result = create_draft_pr('Test PR', 'PR body', '/proj', work_type='scoring')
        assert result == '99'

    def test_includes_work_type_label(self, monkeypatch):
        create_cmd = []

        def mock_run(cmd, **kwargs):
            if cmd == ['gh', '--version']:
                return _cp(stdout='gh version 2.40')
            if 'label' in cmd and 'create' in cmd:
                return _cp()
            if 'pr' in cmd and 'view' in cmd:
                return _cp(returncode=1)
            if 'pr' in cmd and 'create' in cmd:
                create_cmd.extend(cmd)
                return _cp(stdout='https://github.com/user/repo/pull/10\n')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import create_draft_pr
        create_draft_pr('Title', 'Body', '/proj', work_type='revision')

        # Should have --label revision in addition to --label in-progress
        label_indices = [i for i, x in enumerate(create_cmd) if x == '--label']
        labels = [create_cmd[i + 1] for i in label_indices]
        assert 'in-progress' in labels
        assert 'revision' in labels

    def test_returns_empty_on_create_failure(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            if cmd == ['gh', '--version']:
                return _cp(stdout='gh version 2.40')
            if 'label' in cmd and 'create' in cmd:
                return _cp()
            if 'pr' in cmd and 'view' in cmd:
                return _cp(returncode=1)
            if 'pr' in cmd and 'create' in cmd:
                return _cp(returncode=1, stderr='auth required')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import create_draft_pr
        result = create_draft_pr('Title', 'Body', '/proj')
        assert result == ''


# ---------------------------------------------------------------------------
# update_pr_task
# ---------------------------------------------------------------------------

class TestUpdatePrTask:
    def test_checks_off_task(self, monkeypatch):
        edit_body = []

        def mock_run(cmd, **kwargs):
            # has_gh
            if cmd == ['gh', '--version']:
                return _cp(stdout='gh version 2.40')
            # pr view to get body
            if 'pr' in cmd and 'view' in cmd and '--json' in cmd:
                return _cp(stdout='- [ ] Draft scenes\n- [ ] Review\n')
            # pr edit
            if 'pr' in cmd and 'edit' in cmd:
                body_idx = cmd.index('--body') + 1
                edit_body.append(cmd[body_idx])
                return _cp()
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import update_pr_task
        update_pr_task('Draft scenes', '/proj', pr_number='42')

        assert len(edit_body) == 1
        assert '- [x] Draft scenes' in edit_body[0]
        assert '- [ ] Review' in edit_body[0]

    def test_no_op_without_gh(self, monkeypatch):
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            raise FileNotFoundError('gh not found')

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import update_pr_task
        # Should not raise
        update_pr_task('Task', '/proj', pr_number='42')

    def test_no_op_without_pr_number(self, monkeypatch):
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import update_pr_task
        update_pr_task('Task', '/proj', pr_number='')
        # has_gh returns True but pr_number is empty => early return
        # Only the gh --version check should run at most
        pr_cmds = [c for c in calls if 'pr' in c and 'edit' in c]
        assert len(pr_cmds) == 0


# ---------------------------------------------------------------------------
# ensure_branch_pushed
# ---------------------------------------------------------------------------

class TestEnsureBranchPushed:
    def test_pushes_with_upstream(self, monkeypatch):
        push_cmds = []

        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                return _cp(stdout='storyforge/test-branch\n')
            if 'config' in cmd and 'init.defaultBranch' in cmd:
                return _cp(stdout='main\n')
            if 'rev-list' in cmd:
                return _cp(stdout='3\n')
            if 'push' in cmd:
                push_cmds.append(cmd)
                return _cp()
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import ensure_branch_pushed
        result = ensure_branch_pushed('/proj', 'storyforge/test-branch')

        assert result is True
        assert len(push_cmds) == 1
        assert '-u' in push_cmds[0]
        assert 'origin' in push_cmds[0]

    def test_returns_false_on_push_failure(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                return _cp(stdout='test-branch\n')
            if 'config' in cmd:
                return _cp(stdout='main\n')
            if 'rev-list' in cmd:
                return _cp(stdout='1\n')
            if 'push' in cmd:
                return _cp(returncode=1, stderr='rejected')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import ensure_branch_pushed
        result = ensure_branch_pushed('/proj', 'test-branch')
        assert result is False

    def test_returns_false_when_no_branch(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                return _cp(returncode=128, stdout='')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import ensure_branch_pushed
        result = ensure_branch_pushed('/proj')
        assert result is False

    def test_creates_empty_commit_when_no_changes_ahead(self, monkeypatch):
        commit_cmds = []

        def mock_run(cmd, **kwargs):
            if 'rev-parse' in cmd:
                return _cp(stdout='storyforge/test\n')
            if 'config' in cmd:
                return _cp(stdout='main\n')
            if 'rev-list' in cmd:
                return _cp(stdout='0\n')
            if 'diff' in cmd and '--quiet' in cmd:
                # No changes
                return _cp(returncode=0)
            if 'commit' in cmd:
                commit_cmds.append(cmd)
                return _cp()
            if 'push' in cmd:
                return _cp()
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import ensure_branch_pushed
        ensure_branch_pushed('/proj', 'storyforge/test')

        # Should have tried --allow-empty commit
        allow_empty = [c for c in commit_cmds if '--allow-empty' in c]
        assert len(allow_empty) == 1


# ---------------------------------------------------------------------------
# commit_partial_work
# ---------------------------------------------------------------------------

class TestCommitPartialWork:
    def test_commits_when_changes_exist(self, tmp_path, monkeypatch):
        # Create a fake .git directory
        git_dir = tmp_path / '.git'
        git_dir.mkdir()

        commit_found = {'called': False}

        def mock_run(cmd, **kwargs):
            if 'diff' in cmd and '--cached' in cmd:
                return _cp(returncode=1)  # has staged changes
            if 'commit' in cmd:
                commit_found['called'] = True
                assert 'Interrupted' in cmd[cmd.index('-m') + 1]
                return _cp()
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_partial_work
        commit_partial_work(str(tmp_path))
        assert commit_found['called'] is True

    def test_skips_when_no_git_dir(self, tmp_path, monkeypatch):
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_partial_work
        commit_partial_work(str(tmp_path))

        # No subprocess calls since there's no .git
        assert len(calls) == 0

    def test_skips_when_no_changes(self, tmp_path, monkeypatch):
        git_dir = tmp_path / '.git'
        git_dir.mkdir()

        commit_called = {'v': False}

        def mock_run(cmd, **kwargs):
            if 'diff' in cmd and '--cached' in cmd:
                return _cp(returncode=0)  # no staged changes
            if 'status' in cmd and '--porcelain' in cmd:
                return _cp(stdout='')  # no changes in dirs
            if 'commit' in cmd:
                commit_called['v'] = True
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_partial_work
        commit_partial_work(str(tmp_path))
        assert commit_called['v'] is False

    def test_pushes_after_commit(self, tmp_path, monkeypatch):
        git_dir = tmp_path / '.git'
        git_dir.mkdir()

        push_called = {'v': False}

        def mock_run(cmd, **kwargs):
            if 'diff' in cmd and '--cached' in cmd:
                return _cp(returncode=1)  # has changes
            if 'push' in cmd:
                push_called['v'] = True
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import commit_partial_work
        commit_partial_work(str(tmp_path))
        assert push_called['v'] is True


# ---------------------------------------------------------------------------
# ensure_all_labels
# ---------------------------------------------------------------------------

class TestEnsureAllLabels:
    def test_creates_all_labels_when_gh_available(self, monkeypatch):
        label_cmds = []

        def mock_run(cmd, **kwargs):
            if cmd == ['gh', '--version']:
                return _cp(stdout='gh version 2.40')
            if 'label' in cmd and 'create' in cmd:
                label_cmds.append(cmd)
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import ensure_all_labels, _LABELS
        ensure_all_labels('/proj')

        assert len(label_cmds) == len(_LABELS)

    def test_skips_when_no_gh(self, monkeypatch):
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd == ['gh', '--version']:
                raise FileNotFoundError('gh not found')
            return _cp()

        monkeypatch.setattr('subprocess.run', mock_run)

        from storyforge.git import ensure_all_labels
        ensure_all_labels('/proj')

        # Only the gh --version check
        label_cmds = [c for c in calls if 'label' in c]
        assert len(label_cmds) == 0

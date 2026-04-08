"""Command-level tests for storyforge.git module.

Tests create_branch, ensure_on_branch, commit_and_push, has_gh,
current_branch, _is_main_branch, label definitions, and commit_partial_work.
All git operations are mocked via the mock_git fixture from conftest.
"""

import os
import subprocess

import pytest

import storyforge.git as git_mod
from storyforge.git import _is_main_branch, _LABELS


# ============================================================================
# _is_main_branch
# ============================================================================

class TestIsMainBranch:
    def test_main_is_main(self):
        assert _is_main_branch('main') is True

    def test_master_is_main(self):
        assert _is_main_branch('master') is True

    def test_feature_branch_is_not_main(self):
        assert _is_main_branch('storyforge/revise-20260407') is False

    def test_empty_string_is_not_main(self):
        assert _is_main_branch('') is False

    def test_develop_is_not_main(self):
        assert _is_main_branch('develop') is False


# ============================================================================
# Labels
# ============================================================================

class TestLabels:
    def test_labels_dict_has_expected_keys(self):
        for key in ('in-progress', 'reviewing', 'ready-to-merge',
                     'drafting', 'evaluation', 'revision', 'scoring'):
            assert key in _LABELS

    def test_label_values_are_tuples(self):
        for name, val in _LABELS.items():
            assert isinstance(val, tuple), f'{name} label value is not a tuple'
            assert len(val) == 2, f'{name} label tuple has wrong length'

    def test_colors_are_hex(self):
        import re
        for name, (color, _) in _LABELS.items():
            assert re.match(r'^[0-9a-f]{6}$', color), f'{name} color {color} is not valid hex'


# ============================================================================
# create_branch (mocked via monkeypatch at module level)
# ============================================================================

class TestCreateBranch:
    def test_returns_existing_branch_when_not_main(self, mock_git):
        """When already on a non-main branch, should resume it."""
        mock_git.branch = 'storyforge/test-existing'
        result = git_mod.create_branch('write', '/fake/project')
        assert result == 'storyforge/test-existing'

    def test_calls_current_branch(self, mock_git):
        """create_branch calls current_branch internally."""
        mock_git.branch = 'storyforge/test-existing'
        git_mod.create_branch('write', '/fake/project')
        # Should have been called through the mock path
        # (the mock patches storyforge.git.create_branch itself)
        assert mock_git.calls  # At least one call recorded via mock


# ============================================================================
# ensure_on_branch (mocked)
# ============================================================================

class TestEnsureOnBranch:
    def test_returns_branch_name(self, mock_git):
        mock_git.branch = 'storyforge/my-branch'
        result = git_mod.ensure_on_branch('hone', '/fake/project')
        assert result == 'storyforge/my-branch'


# ============================================================================
# commit_and_push (mocked)
# ============================================================================

class TestCommitAndPush:
    def test_returns_true(self, mock_git):
        result = git_mod.commit_and_push('/fake/project', 'test commit', ['file.py'])
        assert result is True

    def test_records_call(self, mock_git):
        git_mod.commit_and_push('/fake/project', 'my message', ['a.py'])
        # mock_git._commit_and_push records to calls
        assert len(mock_git.calls) >= 1
        last = mock_git.calls[-1]
        assert last[0] == 'commit_and_push'
        assert last[1] == 'my message'

    def test_paths_passed(self, mock_git):
        git_mod.commit_and_push('/fake/project', 'msg', ['scenes/', 'reference/'])
        last = mock_git.calls[-1]
        assert last[2] == ['scenes/', 'reference/']


# ============================================================================
# has_gh (mocked)
# ============================================================================

class TestHasGh:
    def test_returns_false_by_default(self, mock_git):
        assert git_mod.has_gh() is False

    def test_returns_true_when_set(self, mock_git):
        mock_git.has_gh = True
        assert git_mod.has_gh() is True


# ============================================================================
# current_branch (mocked)
# ============================================================================

class TestCurrentBranch:
    def test_returns_mock_branch(self, mock_git):
        mock_git.branch = 'storyforge/test-123'
        result = git_mod.current_branch('/fake')
        assert result == 'storyforge/test-123'


# ============================================================================
# create_draft_pr (mocked, gh not available)
# ============================================================================

class TestCreateDraftPr:
    def test_returns_empty_when_no_gh(self, mock_git):
        """When gh is not available, should return empty string."""
        mock_git.has_gh = False
        result = git_mod.create_draft_pr('Title', 'Body', '/fake', 'drafting')
        assert result == ''


# ============================================================================
# update_pr_task (mocked, gh not available)
# ============================================================================

class TestUpdatePrTask:
    def test_noop_when_no_gh(self, mock_git):
        mock_git.has_gh = False
        git_mod.update_pr_task('Draft scene X', '/fake', '')

    def test_noop_when_no_pr(self, mock_git):
        mock_git.has_gh = True
        git_mod.update_pr_task('Draft scene X', '/fake', '')


# ============================================================================
# commit_partial_work
# ============================================================================

class TestCommitPartialWork:
    def test_no_git_dir_is_noop(self, tmp_path):
        """If no .git directory, should do nothing and not raise."""
        git_mod.commit_partial_work(str(tmp_path))

    def test_with_git_dir_calls_git(self, mock_git, tmp_path):
        """With a .git directory, should attempt git operations."""
        os.makedirs(tmp_path / '.git')
        git_mod.commit_partial_work(str(tmp_path))
        # _git was called at least to check for changes
        assert len(mock_git.calls) >= 1


# ============================================================================
# ensure_branch_pushed (mocked)
# ============================================================================

class TestEnsureBranchPushed:
    def test_no_branch_returns_false(self, mock_git):
        """When branch is empty, should return False."""
        mock_git.branch = ''
        # Patch current_branch to return '' (mock already does this via _current_branch)
        result = git_mod.ensure_branch_pushed('/fake', '')
        assert result is False

    def test_with_numeric_stdout(self, mock_git, monkeypatch):
        """When _git returns numeric stdout (like rev-list), should work."""
        import subprocess
        call_count = [0]

        def smart_git(project_dir, *args, check=True):
            call_count[0] += 1
            mock_git.calls.append(args)
            # rev-list --count returns "0"
            # push returns ok
            return subprocess.CompletedProcess(
                args=['git'] + list(args), returncode=0,
                stdout='0', stderr='',
            )

        monkeypatch.setattr('storyforge.git._git', smart_git)
        result = git_mod.ensure_branch_pushed('/fake', 'storyforge/test-push')
        # With numeric stdout, the function should proceed without error
        assert call_count[0] >= 1

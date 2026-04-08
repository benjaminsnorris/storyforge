"""Integration tests for the git branch/PR workflow (git.py).

Tests create_branch, ensure_on_branch, ensure_branch_pushed,
commit_and_push, create_draft_pr, and run_review_phase using
the git_project fixture (real git repo) and selective mocking.
"""

import os
import subprocess

import pytest


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------

class TestCreateBranch:
    """Test create_branch behavior in a real git repo."""

    def test_creates_branch_from_main(self, git_project):
        from storyforge.git import create_branch
        branch = create_branch('test-cmd', git_project)
        assert branch.startswith('storyforge/test-cmd-')
        # Verify we're on the new branch
        r = subprocess.run(
            ['git', '-C', git_project, 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True,
        )
        assert r.stdout.strip() == branch

    def test_resumes_on_feature_branch(self, git_project):
        """If already on a non-main branch, should resume, not create new."""
        from storyforge.git import create_branch
        # First create a branch
        subprocess.run(
            ['git', '-C', git_project, 'checkout', '-b', 'storyforge/existing-branch'],
            capture_output=True,
        )
        branch = create_branch('test-cmd', git_project)
        assert branch == 'storyforge/existing-branch'

    def test_branch_name_format(self, git_project):
        from storyforge.git import create_branch
        branch = create_branch('elaborate-spine', git_project)
        assert branch.startswith('storyforge/elaborate-spine-')
        # Should contain a timestamp-like suffix (YYYYMMDD-HHMM)
        suffix = branch.removeprefix('storyforge/elaborate-spine-')
        assert len(suffix) >= 9  # e.g., 20260407-1234


# ---------------------------------------------------------------------------
# ensure_on_branch
# ---------------------------------------------------------------------------

class TestEnsureOnBranch:
    """Test ensure_on_branch behavior."""

    def test_creates_branch_when_on_main(self, git_project):
        from storyforge.git import ensure_on_branch
        branch = ensure_on_branch('hone', git_project)
        assert branch.startswith('storyforge/hone-')

    def test_stays_on_feature_branch(self, git_project):
        from storyforge.git import ensure_on_branch
        subprocess.run(
            ['git', '-C', git_project, 'checkout', '-b', 'storyforge/my-feature'],
            capture_output=True,
        )
        branch = ensure_on_branch('hone', git_project)
        assert branch == 'storyforge/my-feature'


# ---------------------------------------------------------------------------
# current_branch
# ---------------------------------------------------------------------------

class TestCurrentBranch:
    """Test current_branch helper."""

    def test_returns_main(self, git_project):
        from storyforge.git import current_branch
        branch = current_branch(git_project)
        # git init may use 'main' or 'master' depending on config
        assert branch in ('main', 'master')

    def test_returns_feature_branch(self, git_project):
        from storyforge.git import current_branch
        subprocess.run(
            ['git', '-C', git_project, 'checkout', '-b', 'storyforge/test-feature'],
            capture_output=True,
        )
        branch = current_branch(git_project)
        assert branch == 'storyforge/test-feature'


# ---------------------------------------------------------------------------
# commit_and_push (with mocked push)
# ---------------------------------------------------------------------------

class TestCommitAndPush:
    """Test commit_and_push in a real git repo (push mocked)."""

    def test_commit_with_paths(self, git_project, monkeypatch):
        from storyforge.git import commit_and_push

        # Mock the push (no remote in test repo)
        def mock_git(project_dir, *args, check=True):
            if args[0] == 'push':
                return subprocess.CompletedProcess(
                    args=['git', 'push'], returncode=0, stdout='', stderr='',
                )
            return subprocess.run(
                ['git', '-C', project_dir, *args],
                capture_output=True, text=True, check=check,
            )
        monkeypatch.setattr('storyforge.git._git', mock_git)

        # Modify a file
        yaml_path = os.path.join(git_project, 'storyforge.yaml')
        with open(yaml_path, 'a') as f:
            f.write('\n# test addition\n')

        result = commit_and_push(git_project, 'Test commit', ['storyforge.yaml'])
        assert result is True

        # Verify the commit exists
        r = subprocess.run(
            ['git', '-C', git_project, 'log', '--oneline', '-1'],
            capture_output=True, text=True,
        )
        assert 'Test commit' in r.stdout

    def test_commit_no_changes_returns_false(self, git_project, monkeypatch):
        from storyforge.git import commit_and_push

        def mock_git(project_dir, *args, check=True):
            if args[0] == 'push':
                return subprocess.CompletedProcess(
                    args=['git', 'push'], returncode=0, stdout='', stderr='',
                )
            return subprocess.run(
                ['git', '-C', project_dir, *args],
                capture_output=True, text=True, check=check,
            )
        monkeypatch.setattr('storyforge.git._git', mock_git)

        # No changes to commit
        result = commit_and_push(git_project, 'Empty commit', ['storyforge.yaml'])
        assert result is False


# ---------------------------------------------------------------------------
# create_draft_pr (mocked gh)
# ---------------------------------------------------------------------------

class TestCreateDraftPR:
    """Test create_draft_pr with mocked gh CLI."""

    def test_no_gh_returns_empty(self, git_project, monkeypatch):
        """Without gh CLI, should return empty string."""
        from storyforge.git import create_draft_pr
        monkeypatch.setattr('storyforge.git.has_gh', lambda: False)

        result = create_draft_pr('Test PR', 'Body text', git_project, 'drafting')
        assert result == ''

    def test_existing_pr_returns_number(self, git_project, monkeypatch):
        """If a PR already exists, should return its number."""
        from storyforge.git import create_draft_pr
        monkeypatch.setattr('storyforge.git.has_gh', lambda: True)

        # Mock ensure_all_labels to no-op
        monkeypatch.setattr('storyforge.git.ensure_all_labels', lambda _: None)

        # Mock gh pr view to return existing PR
        orig_run = subprocess.run
        def mock_run(cmd, **kwargs):
            if cmd[0] == 'gh' and 'pr' in cmd and 'view' in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout='42', stderr='',
                )
            return orig_run(cmd, **kwargs)
        monkeypatch.setattr('subprocess.run', mock_run)

        result = create_draft_pr('Test PR', 'Body', git_project, 'drafting')
        assert result == '42'

    def test_creates_new_pr(self, git_project, monkeypatch):
        """Should create a new PR and return the number."""
        from storyforge.git import create_draft_pr
        monkeypatch.setattr('storyforge.git.has_gh', lambda: True)
        monkeypatch.setattr('storyforge.git.ensure_all_labels', lambda _: None)

        call_log = []
        orig_run = subprocess.run
        def mock_run(cmd, **kwargs):
            if cmd[0] == 'gh':
                call_log.append(cmd)
                if 'view' in cmd:
                    # No existing PR
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=1, stdout='', stderr='',
                    )
                if 'create' in cmd:
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0,
                        stdout='https://github.com/test/repo/pull/99',
                        stderr='',
                    )
            return orig_run(cmd, **kwargs)
        monkeypatch.setattr('subprocess.run', mock_run)

        result = create_draft_pr('Test PR', 'Body', git_project, 'drafting')
        assert result == '99'


# ---------------------------------------------------------------------------
# run_review_phase
# ---------------------------------------------------------------------------

class TestRunReviewPhase:
    """Test run_review_phase with mocked API and gh."""

    def test_review_phase_creates_review_file(self, git_project, mock_api, monkeypatch):
        monkeypatch.chdir(git_project)
        monkeypatch.setattr('storyforge.git.has_gh', lambda: False)

        # Mock commit_and_push
        commits = []
        def mock_commit(project_dir, message, paths=None):
            commits.append(message)
            return True
        monkeypatch.setattr('storyforge.git.commit_and_push', mock_commit)

        # Mock update_cycle_field to no-op
        monkeypatch.setattr('storyforge.common.get_current_cycle', lambda _: 1)
        try:
            monkeypatch.setattr('storyforge.common.update_cycle_field', lambda *a, **kw: None)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr('storyforge.common.get_cycle_plan_file', lambda _: '')
        except AttributeError:
            pass

        mock_api.set_response('## Review\n\nLooks good.\n\n## Fixable Items\n\nNone.')

        from storyforge.git import run_review_phase
        run_review_phase('drafting', git_project)

        # Should have created a review file
        review_dir = os.path.join(git_project, 'working', 'reviews')
        assert os.path.isdir(review_dir)
        review_files = [f for f in os.listdir(review_dir) if f.endswith('.md')]
        assert len(review_files) >= 1

    def test_review_phase_invokes_api(self, git_project, mock_api, monkeypatch):
        monkeypatch.chdir(git_project)
        monkeypatch.setattr('storyforge.git.has_gh', lambda: False)

        commits = []
        def mock_commit(project_dir, message, paths=None):
            commits.append(message)
            return True
        monkeypatch.setattr('storyforge.git.commit_and_push', mock_commit)
        monkeypatch.setattr('storyforge.common.get_current_cycle', lambda _: 0)
        try:
            monkeypatch.setattr('storyforge.common.update_cycle_field', lambda *a, **kw: None)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr('storyforge.common.get_cycle_plan_file', lambda _: '')
        except AttributeError:
            pass

        mock_api.set_response('## Review\n\nAll clear.')

        from storyforge.git import run_review_phase
        run_review_phase('evaluation', git_project)

        api_calls = [c for c in mock_api.calls if c['fn'] == 'invoke_api']
        assert len(api_calls) >= 1


# ---------------------------------------------------------------------------
# _is_main_branch helper
# ---------------------------------------------------------------------------

class TestIsMainBranch:
    """Test the _is_main_branch helper."""

    def test_main_is_main(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('main') is True

    def test_master_is_main(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('master') is True

    def test_feature_branch_is_not_main(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('storyforge/test-feature') is False

    def test_empty_is_not_main(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('') is False

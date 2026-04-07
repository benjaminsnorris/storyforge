"""Tests for git branch and PR workflow functions (migrated from test-git-workflow.sh).

The git workflow tests rely on bash functions (create_branch, ensure_branch_pushed,
select_model, etc.) from common.sh. We test what is available in Python.
"""

import pytest


@pytest.mark.skip(reason="Git workflow tests are bash-only (create_branch, ensure_branch_pushed, etc.). No Python equivalent.")
def test_git_workflow_placeholder():
    pass

"""This directory's project fixtures leave out the fixture's gitignored
files (#296; the root guard is tests/test_fixture_helpers.py)."""

import pytest

from fixture_helpers import FIXTURE_DIR, assert_committed_copy, ignored_sentinel


@pytest.mark.parametrize('name', ['project_dir', 'git_project'])
def test_project_fixture_leaves_out_gitignored_files(request, name):
    with ignored_sentinel(FIXTURE_DIR) as sentinel:
        project = request.getfixturevalue(name)
    assert_committed_copy(project, sentinel)

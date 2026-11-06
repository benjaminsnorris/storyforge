"""This directory's project_dir leaves out the fixture's gitignored files
(#296; the root guard is tests/test_fixture_helpers.py)."""

from fixture_helpers import FIXTURE_DIR, assert_committed_copy, ignored_sentinel


def test_project_dir_leaves_out_gitignored_files(request):
    with ignored_sentinel(FIXTURE_DIR) as sentinel:
        project = request.getfixturevalue('project_dir')
    assert_committed_copy(project, sentinel)

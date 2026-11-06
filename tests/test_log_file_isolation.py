"""Regression: a command's main() sets `common._log_file` inside its tmp
project, and tests outside tests/commands/ never had it reset, so a later
test's `log()` wrote into a deleted directory (seen as order-dependent
errors in test_extract.py after test_cmd_write_gn.py). Pytest runs these
two in file order: the first leaks a log file, the second must not see it."""

import shutil

import storyforge.common as common


def test_a_command_leaves_a_log_file(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    common.set_log_file(str(logs / 'run.log'))
    shutil.rmtree(logs)


def test_the_next_test_starts_with_no_log_file():
    assert common._log_file is None
    common.log('no stale log file to write into')

"""`cleanup`'s `storyforge.yaml` handling, asserted through `main()`.

#316 tests `migrate_storyforge_yaml` and `_check_yaml_scalars` as units. That is
the split #313 was reviewed for: the helper was tested and the wiring was not,
and the wiring was where the bug lived. Here the #315 half is genuinely wired —
removing `_check_yaml_scalars` from `build_cleanup_report` fails two of #316's
tests — but the #314 half was not asserted at command level anywhere:
`migrate_storyforge_yaml` is referenced only in `tests/test_cleanup_yaml.py`, and
the existing `main()` tests assert on branches, commits and the report only.

The fixture project is deliberately not a clean project for this purpose: a first
`main([])` legitimately adds four artifact entries and corrects one `exists`
flag. So "a real run leaves the file alone" has to be asserted on the *second*
run, which is also the assertion an author actually cares about — they run
`cleanup` repeatedly.
"""

import hashlib
import os
import subprocess

import pytest

from storyforge.cmd_cleanup import main


@pytest.fixture
def wired(project_dir, monkeypatch):
    """`main()` pointed at the fixture with git shelled out, per the pattern in
    `test_cmd_cleanup.py`."""
    monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                        lambda: project_dir)
    monkeypatch.setattr('storyforge.cmd_cleanup.subprocess.run',
                        lambda *a, **kw: subprocess.CompletedProcess(
                            a[0] if a else [], 0, stdout='', stderr=''))
    return project_dir


def yaml_path(project_dir):
    return os.path.join(project_dir, 'storyforge.yaml')


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


class TestARepeatedCleanupLeavesTheYamlAlone:

    def test_a_second_run_does_not_rewrite_storyforge_yaml(
            self, wired, mock_api, mock_git, mock_costs):
        """#314 at the level the author meets it.

        The unit test for this uses a hand-built complete file; this is a real
        `cleanup` over a real project, which is where the silent rewrite and the
        spurious git diff actually showed up. Asserted on mtime as well as bytes
        for the reason #316 gives — a byte comparison passes while the file is
        still rewritten every run, which was half the bug.
        """
        path = yaml_path(wired)
        main([])
        after_first, mtime = digest(path), os.stat(path).st_mtime_ns

        main([])

        assert digest(path) == after_first, 'the second run changed bytes'
        assert os.stat(path).st_mtime_ns == mtime, (
            'the second run rewrote storyforge.yaml')

    def test_a_cleanup_run_preserves_a_crlf_yaml_end_to_end(
            self, wired, mock_api, mock_git, mock_costs):
        """The endings policy, through the command rather than the function.

        `cleanup` is the command whose own remedy text used to send authors here,
        and it is the one that normalized the file. Nothing converts it now, so a
        whole run must leave a CRLF project on CRLF — and must not leave it mixed,
        which is worse than either policy applied consistently.
        """
        path = yaml_path(wired)
        with open(path, newline='') as f:
            text = f.read()
        with open(path, 'wb') as f:
            f.write(text.replace('\n', '\r\n').encode())

        main([])

        with open(path, 'rb') as f:
            raw = f.read()
        assert b'\r\n' in raw, 'a full cleanup run normalized CRLF away'
        assert raw.replace(b'\r\n', b'').count(b'\n') == 0, (
            'a full cleanup run left the file with mixed endings')

    def test_a_crlf_yaml_is_reported_rather_than_converted(
            self, wired, mock_api, mock_git, mock_costs):
        """The other half of the fix: removing a silent conversion without
        reporting what it hid just moves the silence. Asserted in the durable
        artifact `skills/forge/SKILL.md` scans, not in a log line."""
        path = yaml_path(wired)
        with open(path, newline='') as f:
            text = f.read()
        with open(path, 'wb') as f:
            f.write(text.replace('\n', '\r\n').encode())

        main([])

        report = open(os.path.join(wired, 'working',
                                   'cleanup-report.csv')).read()
        crlf_rows = [line for line in report.splitlines()
                     if 'crlf_line_endings' in line]
        assert crlf_rows, 'the CRLF yaml was neither converted nor reported'
        assert any('storyforge.yaml' in row for row in crlf_rows)


class TestAMisreadValueSurvivesToTheWrittenReport:

    def test_a_truncated_value_reaches_the_report_file_via_main(
            self, wired, mock_api, mock_git, mock_costs):
        """#316 asserts this through `build_cleanup_report`; this asserts it
        through the command, over a real project, in the file on disk."""
        path = yaml_path(wired)
        with open(path) as f:
            text = f.read()
        with open(path, 'w') as f:
            f.write(text + '\nvolume_note: Vol #2 | extra\n')

        main([])

        report_path = os.path.join(wired, 'working', 'cleanup-report.csv')
        with open(report_path) as f:
            header = f.readline().rstrip('\n').split('|')
            rows = [line.rstrip('\n').split('|')
                    for line in f if line.strip()]

        matching = [r for r in rows
                    if 'yaml_value_truncated_by_comment' in r]
        assert matching, 'the finding never reached the written report'
        assert all(len(r) == len(header) for r in rows), (
            'a stray pipe from the author value shifted a row, emptying the '
            'trailing status cell that forge scans for')

    def test_the_finding_is_actionable_in_the_written_report(
            self, wired, mock_api, mock_git, mock_costs):
        """`status=pending` is what `skills/forge/SKILL.md` greps. A warning that
        lands with an empty status is a row that silences its own finding."""
        path = yaml_path(wired)
        with open(path) as f:
            text = f.read()
        with open(path, 'w') as f:
            f.write(text + '\nvolume_note: Book #2\n')

        main([])

        report_path = os.path.join(wired, 'working', 'cleanup-report.csv')
        with open(report_path) as f:
            header = f.readline().rstrip('\n').split('|')
            rows = [dict(zip(header, line.rstrip('\n').split('|')))
                    for line in f if line.strip()]

        row = next(r for r in rows
                   if r.get('type') == 'yaml_value_truncated_by_comment')
        assert row.get('severity') == 'warning'
        assert row.get('status') == 'pending'

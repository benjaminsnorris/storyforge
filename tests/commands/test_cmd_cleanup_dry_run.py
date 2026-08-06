"""Does `storyforge cleanup --dry-run` describe what `storyforge cleanup` does?

Nothing asserted this before, which is why #314's under-report was invisible:
`--dry-run` previews by copying files into a sandbox and re-running the real
mutator against it, so the preview is only correct if it reproduces every piece
of state the mutator consults. There are 13 steps, each with its own bespoke
`if args.dry_run:` branch, so there are 13 independent chances to drift — and
the failure direction is the bad one. **Over-reporting is a nuisance; an
under-report tells an author "nothing to do" and then changes their file.**

The property under test is deliberately one-sided: dry-run must not *under*-report.
"""

import contextlib
import hashlib
import io
import os
import tempfile

import pytest

import storyforge.cmd_cleanup as cc


#: A project with nothing for the migration to do *except* the one artifact whose
#: directory an earlier step creates. Everything else is already present, so any
#: "would migrate" message can only be about that artifact — without this
#: isolation the two modes agree for incidental reasons and the test proves
#: nothing. (The shipped fixture is exactly that confounded case: its migration
#: reports a change anyway, because `reference/` CSVs need artifact entries.)
ONLY_THE_COMPOSED_CHANGE = (
    'project:\n  title: "X"\n'
    'artifacts:\n  manuscript:\n    exists: false\n    path: manuscript/\n'
    '    updated:\n'
    'scene_extensions: []\n\nevaluation:\n  custom_evaluators: []\n'
    '\nproduction:\n  author: Ben\n\nparts:\n  - number: 1\n'
)


def _project(text: str) -> str:
    root = os.path.join(tempfile.mkdtemp(), 'p')
    os.makedirs(root)
    with open(os.path.join(root, 'storyforge.yaml'), 'w') as f:
        f.write(text)
    return root


def _digest(root: str) -> str:
    with open(os.path.join(root, 'storyforge.yaml'), 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _run(argv: list[str], root: str, monkeypatch) -> str:
    """Run `main` against `root`, returning stdout."""
    monkeypatch.setattr(cc, 'detect_project_root', lambda: root)
    monkeypatch.setattr(cc, 'ensure_on_branch', lambda *a, **k: None)
    monkeypatch.setattr(cc, 'commit_and_push', lambda *a, **k: None)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cc.main(argv)
    return buf.getvalue()


class TestDryRunDoesNotUnderReportTheYamlMigration:

    def test_it_reports_a_migration_it_would_perform(self, mock_api, mock_git,
                                                     mock_costs, project_dir,
                                                     monkeypatch):
        """The half `disk_root` fixed: the sandbox's own missing files.

        The sandbox used to copy `reference/` but never `manuscript/`, so
        `exists:` resolved differently there than in the real run. Disk checks now
        resolve against the real project.
        """
        said = 'Would migrate storyforge.yaml' in _run(
            ['--dry-run'], project_dir, monkeypatch)

        assert said, 'dry-run must announce the migration it would perform'

    def test_the_real_run_performs_what_dry_run_announced(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        before = _digest(project_dir)
        _run([], project_dir, monkeypatch)

        assert _digest(project_dir) != before

    @pytest.mark.xfail(
        strict=True,
        reason='KNOWN GAP: `--dry-run` previews each step against the state at '
               'entry, while the real run\'s steps compose. Step 2 creates '
               '`manuscript/press-kit` (EXPECTED_DIRS), so in the real run step 3 '
               'sees `manuscript/` exist and flips its `exists:` flag — and no '
               'arrangement of the dry-run sandbox reproduces that, because '
               'dry-run deliberately does not create the directory. `disk_root` '
               'closed the sandbox-missing-files cause; this is the other one. '
               'The fix is a planner both modes consume rather than re-running '
               'the mutator against a copy, which is a refactor of all 13 steps '
               'and is tracked as #317. Flips to a failure when that lands.')
    def test_the_two_modes_agree_when_a_change_is_composed_across_steps(
            self, mock_api, mock_git, mock_costs, monkeypatch):
        dry = _project(ONLY_THE_COMPOSED_CHANGE)
        announced = 'Would migrate storyforge.yaml' in _run(
            ['--dry-run'], dry, monkeypatch)

        real = _project(ONLY_THE_COMPOSED_CHANGE)
        before = _digest(real)
        _run([], real, monkeypatch)
        performed = _digest(real) != before

        assert announced == performed, (
            f'dry-run announced={announced} but the real run '
            f'performed={performed}')

    def test_the_real_run_does_change_the_file_in_that_case(
            self, mock_api, mock_git, mock_costs, monkeypatch):
        """Half of the xfail above, asserted positively.

        Pinned separately so the xfail cannot start passing for the wrong reason —
        if the real run stopped flipping the flag, the two modes would agree by
        both doing nothing, and a strict xfail would flip to a pass while the
        actual capability had regressed.
        """
        real = _project(ONLY_THE_COMPOSED_CHANGE)
        before = _digest(real)
        _run([], real, monkeypatch)

        assert _digest(real) != before
        with open(os.path.join(real, 'storyforge.yaml')) as f:
            assert 'exists: true' in f.read()

    def test_dry_run_leaves_the_file_alone(self, mock_api, mock_git, mock_costs,
                                          monkeypatch):
        """Whatever it reports, it must not write. The mtime matters as well as
        the bytes — see #314's unconditional rewrite."""
        dry = _project(ONLY_THE_COMPOSED_CHANGE)
        path = os.path.join(dry, 'storyforge.yaml')
        before, mtime = _digest(dry), os.stat(path).st_mtime_ns

        _run(['--dry-run'], dry, monkeypatch)

        assert _digest(dry) == before
        assert os.stat(path).st_mtime_ns == mtime

    def test_dry_run_creates_nothing_except_the_report(self, mock_api, mock_git,
                                                       mock_costs, monkeypatch):
        """`working/cleanup-report.csv` is the one legitimate write — the report
        *is* the product, and `--dry-run` still produces it.

        Everything else must be untouched. This also guards against `disk_root`
        being wired to a writable sandbox path by mistake, which would put the
        migration's output somewhere nothing looks.
        """
        dry = _project(ONLY_THE_COMPOSED_CHANGE)

        _run(['--dry-run'], dry, monkeypatch)

        written = {
            os.path.relpath(os.path.join(root, name), dry)
            for root, _, names in os.walk(dry) for name in names
        }
        assert written == {'storyforge.yaml',
                           os.path.join('working', 'cleanup-report.csv')}

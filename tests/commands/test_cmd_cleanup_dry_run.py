"""Does `storyforge cleanup --dry-run` describe what `storyforge cleanup` does?

Nothing asserted this before, which is why #314's under-report was invisible:
`--dry-run` previewed by copying files into a sandbox and re-running the real
mutator against it, so the preview was only correct if it reproduced every
piece of state the mutator consults. There were 13 steps, each with its own
bespoke `if args.dry_run:` branch — 13 independent chances to drift, and the
failure direction is the bad one. **Over-reporting is a nuisance; an
under-report tells an author "nothing to do" and then changes their file.**

#317 replaced that with a planner both modes consume, so the per-step class of
test below is the one that matters: for every step, `plan.changes` is non-empty
exactly when applying it changes the project. The end-to-end tests further down
stay because they exercise `main`'s wiring — a planner nothing renders is as
silent as a preview that lies.
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


def _snapshot(root: str) -> dict[str, str]:
    """Every path under `root`, files digested. Directories count as state:
    creating an empty `manuscript/press-kit/` is a change even though no file
    changed, and a step that only removes an empty directory is the case
    `--dry-run` reported nothing at all about before #317."""
    out: dict[str, str] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        out[os.path.relpath(dirpath, root) + os.sep] = 'dir'
        for name in filenames:
            path = os.path.join(dirpath, name)
            with open(path, 'rb') as f:
                out[os.path.relpath(path, root)] = hashlib.sha256(
                    f.read()).hexdigest()
    return out


def _write(root: str, rel: str, text: str = 'x') -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def _bare(text: str = ONLY_THE_COMPOSED_CHANGE) -> str:
    return _project(text)


def _needs_gitignore() -> str:
    return _bare()


def _needs_pipeline_csv() -> str:
    root = _bare()
    _write(root, 'working/pipeline.csv', 'cycle|started\n1|2026-01-01\n')
    return root


def _needs_junk() -> str:
    root = _bare()
    _write(root, 'working/logs/run.log')
    _write(root, 'working/evaluations/e1/.status-running')
    _write(root, 'working/scores/s1/.markers-a')
    _write(root, 'working/scores/s1/.batch-requests.jsonl')
    os.makedirs(os.path.join(root, 'working', 'enrich'))
    return root


def _needs_legacy() -> str:
    root = _bare()
    _write(root, 'working/pipeline.yaml', 'cycle: 1\n')
    return root


def _needs_loose_files() -> str:
    root = _bare()
    _write(root, 'working/recommendations-2026-01-01.md', '# recs\n')
    return root


def _needs_dedup() -> str:
    root = _bare()
    _write(root, 'working/reviews/pipeline-review-20260101-a.md', 'a')
    _write(root, 'working/reviews/pipeline-review-20260101-b.md', 'b')
    return root


def _needs_scene_cleanup() -> str:
    root = _bare()
    _write(root, 'scenes/one.md', '# A Title\n\nThe prose.\n')
    return root


#: One arrangement per mutating step: the builder, and the title of the step it
#: is meant to give work to. Named so a failure says which step's preview lied.
ARRANGEMENTS = {
    'gitignore': (_needs_gitignore, 'Checking .gitignore...'),
    'directories': (_bare, 'Checking directories...'),
    'storyforge_yaml': (_bare, 'Checking storyforge.yaml...'),
    'pipeline_csv': (_needs_pipeline_csv, 'Checking pipeline.csv...'),
    'junk_files': (_needs_junk, 'Cleaning junk files...'),
    'legacy_files': (_needs_legacy, 'Checking legacy files...'),
    'loose_files': (_needs_loose_files, 'Reorganizing loose files...'),
    'pipeline_reviews': (_needs_dedup, 'Deduplicating pipeline reviews...'),
    'scene_files': (_needs_scene_cleanup, 'Cleaning scene files...'),
}


class TestEveryStepAnnouncesExactlyWhatItDoes:
    """The general property #317 asks for, asserted per step rather than for
    the yaml alone.

    `plan.changes` is what `--dry-run` prints and `plan.apply` is what the real
    run performs, so this is the whole agreement: a step that lists nothing
    must change nothing, and a step that changes something must have listed it.
    Applying the plans in order is deliberate — composition is the half no
    sandbox could reproduce, and a planner that ignored it would pass a
    step-in-isolation test and still under-report.
    """

    @pytest.mark.parametrize('name', sorted(ARRANGEMENTS))
    def test_the_arrangement_gives_its_step_work(self, name):
        """Without this the parametrization proves nothing.

        `changes == () and nothing mutated` satisfies the property below
        vacuously, so an arrangement that stopped reaching its step — a renamed
        title, a fixture that drifted clean — would leave that step untested
        while the suite stayed green. That is the shape #313 and #316 both
        found: a guard whose subject had quietly gone away.
        """
        builder, title = ARRANGEMENTS[name]
        plans = {p.title: p for p in cc.plan_cleanup(builder(), scenes=True)}

        assert title in plans, f'no step titled {title!r}'
        assert plans[title].changes, f'{name!r} gives {title!r} nothing to do'

    @pytest.mark.parametrize('name', sorted(ARRANGEMENTS))
    def test_changes_are_non_empty_exactly_when_the_step_mutates(self, name):
        root = ARRANGEMENTS[name][0]()

        for plan in cc.plan_cleanup(root, scenes=True):
            before = _snapshot(root)
            plan.apply()
            mutated = _snapshot(root) != before

            assert bool(plan.changes) == mutated, (
                f'{name!r} arrangement: step {plan.title!r} announced '
                f'{len(plan.changes)} change(s) but '
                f'{"changed" if mutated else "changed nothing"}')

    @pytest.mark.parametrize('name', sorted(ARRANGEMENTS))
    def test_a_second_run_plans_nothing(self, name):
        """Cleanup converges, and the planner says so.

        The strongest available check that the plans are complete rather than
        merely self-consistent: if a step's `apply` did something its `changes`
        did not cover, the next run finds work the first one should have done.
        """
        root = ARRANGEMENTS[name][0]()
        for plan in cc.plan_cleanup(root, scenes=True):
            plan.apply()

        residue = {p.title: [c.would for c in p.changes]
                   for p in cc.plan_cleanup(root, scenes=True) if p.changes}

        assert residue == {}


class TestDiskFacts:
    """The facts every planner reads the filesystem through."""

    def test_a_pending_directory_exists(self):
        disk = cc.DiskFacts('/nowhere', pending_dirs=('manuscript/press-kit',))

        assert disk.exists('manuscript/press-kit')

    def test_a_pending_descendant_makes_its_ancestor_exist(self):
        """#317's composed change in one line: nothing plans `manuscript/`
        itself, only `manuscript/press-kit` inside it, and the yaml migration
        asks about `manuscript/`."""
        disk = cc.DiskFacts('/nowhere', pending_dirs=('manuscript/press-kit',))

        assert disk.exists('manuscript/')
        assert disk.exists('manuscript')

    def test_an_unrelated_prefix_does_not_match(self):
        disk = cc.DiskFacts('/nowhere', pending_dirs=('manuscript/press-kit',))

        assert not disk.exists('manus')

    def test_a_pending_directory_is_not_a_file(self):
        disk = cc.DiskFacts('/nowhere', pending_dirs=('working/logs',))

        assert disk.exists('working/logs')
        assert not disk.isfile('working/logs')

    def test_a_pending_gitkeep_is_listed(self, tmp_path):
        """The junk step deletes `working/logs/.gitkeep` that the directory
        step created a moment earlier. A planner blind to it reported "0 log
        files" for a run that removes one."""
        disk = cc.DiskFacts(str(tmp_path),
                            pending_files=('working/logs/.gitkeep',))

        assert disk.list_files('working/logs') == ['working/logs/.gitkeep']

    def test_list_files_is_not_recursive_and_walk_files_is(self, tmp_path):
        _write(str(tmp_path), 'working/scores/s1/.markers-a')

        disk = cc.DiskFacts(str(tmp_path))

        assert disk.list_files('working/scores') == []
        assert disk.walk_files('working/scores') == [
            'working/scores/s1/.markers-a']

    def test_the_default_reports_the_disk_as_it_is(self, tmp_path):
        """No pending anything — what the standalone appliers pass, so that
        `clean_junk_files(project_dir)` keeps meaning what it meant."""
        disk = cc.DiskFacts(str(tmp_path))

        assert not disk.exists('manuscript/press-kit')


class TestPlanYamlMigrationIsPure:
    """`plan_yaml_migration(content, disk)` takes bytes and facts, returns
    bytes and reasons. No filesystem, which is what makes the migration
    testable without one — and what let `disk_root` be deleted rather than
    re-plumbed."""

    def test_it_flips_a_flag_for_a_directory_that_does_not_exist_yet(self):
        disk = cc.DiskFacts('/nowhere', pending_dirs=('manuscript/press-kit',))

        plan = cc.plan_yaml_migration(ONLY_THE_COMPOSED_CHANGE, disk)

        assert plan.changed
        assert 'exists: true' in plan.new_content
        assert 'correct artifact exists: flags' in plan.reasons

    def test_it_reports_no_change_when_there_is_none(self):
        disk = cc.DiskFacts('/nowhere', pending_dirs=('manuscript/press-kit',))
        settled = cc.plan_yaml_migration(ONLY_THE_COMPOSED_CHANGE,
                                         disk).new_content

        again = cc.plan_yaml_migration(settled, disk)

        assert not again.changed
        assert again.reasons == ()

    def test_changed_is_a_comparison_not_a_flag(self):
        """`reasons` is descriptive only. #314's bug was a flag set
        unconditionally beside the branches it claimed to summarise, so
        `changed` must never be derived from one."""
        disk = cc.DiskFacts('/nowhere')

        plan = cc.YamlMigrationPlan(original='a', new_content='a',
                                    reasons=('add parts',))

        assert not plan.changed
        assert cc.plan_yaml_migration('project:\n  title: X\n', disk).changed


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

    def test_the_two_modes_agree_when_a_change_is_composed_across_steps(
            self, mock_api, mock_git, mock_costs, monkeypatch):
        """The half the planner fixed (#317).

        Step 2 creates `manuscript/press-kit` (`EXPECTED_DIRS`), so in the real
        run step 3 sees `manuscript/` exist and flips its `exists:` flag. No
        arrangement of the old dry-run sandbox reproduced that, because
        `--dry-run` deliberately does not create the directory. `DiskFacts`
        answers for the filesystem the real run's *later* steps will see, so
        both modes now reach the same conclusion from the same computation.
        """
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

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
#:
#: **Every step in `plan_cleanup` needs an entry**, and
#: `test_every_step_has_an_arrangement` is what makes that true rather than
#: hoped-for. The vacuity guard below catches an arrangement that lost its step;
#: it cannot catch a *step* that never got an arrangement, because a guard
#: cannot notice a subject it was never told about. A 14th step whose branch
#: only fires on a project none of these builders produce is untested with the
#: whole suite green — #313's and #316's shape, one level up.
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


#: What each arrangement's named step actually *says*, verbatim.
#:
#: The property below asserts that a step speaks exactly when it acts. Nothing
#: asserted **what it says**, and the two are independent: a step can announce
#: another step's change, invert its two phrasings, miscount, or fall silent
#: about one of the several things it does, and `bool(plan.changes)` is
#: unmoved. Three of those were live bugs #317 fixed — the unannounced empty
#: directory in particular is in this table because it was reported nowhere at
#: all, and a boolean cannot tell that apart from a step with one thing to say.
TRANSCRIPTS = {
    'directories': [
        'Would create manuscript/press-kit/',
        'Would create working/logs/',
        'Would create working/evaluations/',
        'Would create working/plans/',
        'Would create working/recommendations/',
    ],
    'gitignore': ['Would update .gitignore with missing entries'],
    'junk_files': [
        'Would remove 1 .status-* files',
        'Would remove 1 .markers-* files',
        'Would remove 1 .batch-requests.jsonl files',
        'Would remove 1 log files',
        # Reported nowhere before #317. A count-only assertion would not have
        # noticed its absence, which is why the whole list is pinned.
        'Would remove empty working/enrich/',
    ],
    'legacy_files': ['Would delete working/pipeline.yaml'],
    'loose_files': [
        'Would move 1 recommendation files to working/recommendations/'],
    'pipeline_csv': ['Would add missing columns to pipeline.csv'],
    'pipeline_reviews': [
        'Would remove 1 duplicate pipeline review(s), keeping the latest per '
        'day'],
    'scene_files': ['Would clean: one.md'],
    'storyforge_yaml': [
        'Would migrate storyforge.yaml (correct artifact exists: flags)'],
}


def test_every_step_has_an_arrangement():
    """The direction the vacuity guard cannot cover.

    That guard starts from an arrangement and asserts its step exists and has
    work, so it catches a step that was renamed or removed. Adding a step is
    the other direction: `plan_cleanup` grows a 14th entry, no builder produces
    a project that gives it work, and it is untested with the suite green.
    CLAUDE.md tells the next author to add a `plan_*` function; this is what
    also makes them add a row to `ARRANGEMENTS`.
    """
    titles = {p.title for p in cc.plan_cleanup(_bare(), scenes=True)}

    assert titles == {title for _builder, title in ARRANGEMENTS.values()}


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
    def test_planning_writes_nothing(self, name):
        """`--dry-run` renders `plan.changes` and calls nothing else.

        So a planner that touches the disk *while planning* is a dry run that
        mutates the project — the whole failure this module exists to prevent,
        arrived at from the one direction the property below cannot see.
        `plan_cleanup` builds every plan before that test takes its first
        snapshot, and a step whose effect has already happened still mutates at
        `apply` time (it removes the `.gitkeep` step 2 created), so
        `bool(changes) == mutated` holds and convergence holds.

        `test_dry_run_creates_nothing_except_the_report` is the end-to-end
        version and runs on one project with nothing for any step to do — so
        every arrangement that gives a step work was exempt from it.
        """
        root = ARRANGEMENTS[name][0]()
        before = _snapshot(root)

        cc.plan_cleanup(root, scenes=True)

        assert _snapshot(root) == before, (
            f'{name!r}: planning mutated the project, so `--dry-run` would too')

    @pytest.mark.parametrize('name', sorted(ARRANGEMENTS))
    def test_the_step_says_exactly_what_it_will_do(self, name):
        """The other half of the property: not *whether* it speaks, but what.

        `bool(plan.changes)` is unmoved by a step that announces another step's
        change, miscounts, or omits one of the several things it does — and
        that last one was a shipped bug (`--dry-run` said nothing at all about
        the empty `working/enrich/` the real run removed).
        """
        builder, title = ARRANGEMENTS[name][0], ARRANGEMENTS[name][1]
        plans = {p.title: p for p in cc.plan_cleanup(builder(), scenes=True)}

        assert [c.would for c in plans[title].changes] == TRANSCRIPTS[name]

    @pytest.mark.parametrize('name', sorted(ARRANGEMENTS))
    def test_the_real_run_reports_the_same_changes_in_the_past_tense(self, name):
        """`PlannedChange` carries two strings so the modes can address the
        author differently. Nothing checked that they describe one change.

        Swapping them — `--dry-run` reporting completed work, a verbose real
        run reporting intent — leaves both lists the same length and every
        other assertion in this file satisfied.
        """
        builder, title = ARRANGEMENTS[name][0], ARRANGEMENTS[name][1]
        plans = {p.title: p for p in cc.plan_cleanup(builder(), scenes=True)}
        changes = plans[title].changes

        assert all(c.would.startswith('Would ') for c in changes)
        assert not any(c.did.startswith('Would ') for c in changes)
        assert len({c.would for c in changes}) == len(changes) == len(
            {c.did for c in changes})

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


class TestTheSceneStepReportsACleanResultOutLoud:
    """The one step with a `summary`, which renders whether or not there are
    changes — so it is the one step whose message can be wrong while
    `plan.changes` is right, in both directions."""

    def test_it_counts_the_files_it_would_clean(self):
        plan = cc.plan_scene_files(_needs_scene_cleanup())

        assert plan.summary.would == 'Would clean 1 scene file(s)'
        assert plan.summary.did == 'Cleaned 1 scene file(s)'

    def test_it_says_so_when_there_is_nothing_to_do(self):
        """An author who passed `--scenes` is owed an answer either way. A
        summary hardcoded to this string would satisfy every other assertion
        in this file, including the one above's sibling."""
        plan = cc.plan_scene_files(_bare())

        assert plan.changes == ()
        assert plan.summary.would == 'All scene files are clean.'


class TestTheGuardedReadsReportRatherThanRaise:
    """`cleanup`'s actual product is the read-only report, so an unreadable
    input file must not take the command down with it.

    Each of these returns an empty `StepPlan` whose `apply` is `_no_op`, which
    is indistinguishable from "nothing to do" in `plan.changes` alone — the
    WARNING is the only place the difference is stated, so the WARNING is what
    these assert.
    """

    def test_an_undecodable_gitignore_is_reported_and_skipped(self, tmp_path,
                                                              capsys):
        (tmp_path / '.gitignore').write_bytes(b'# caf\xe9\nworking/logs/\n')

        plan = cc.plan_gitignore(str(tmp_path))

        assert plan.changes == ()
        assert 'WARNING: could not read .gitignore' in capsys.readouterr().out
        plan.apply()  # `_no_op` — must not raise, and must not write
        assert (tmp_path / '.gitignore').read_bytes() == (
            b'# caf\xe9\nworking/logs/\n')

    def test_an_undecodable_pipeline_csv_is_reported_and_skipped(self, tmp_path,
                                                                 capsys):
        _write(str(tmp_path), 'working/pipeline.csv', 'x')
        (tmp_path / 'working' / 'pipeline.csv').write_bytes(b'cycle|caf\xe9\n')

        plan = cc.plan_pipeline_csv(str(tmp_path))

        assert plan.changes == ()
        assert ('WARNING: could not read working/pipeline.csv'
                in capsys.readouterr().out)
        plan.apply()
        assert (tmp_path / 'working' / 'pipeline.csv').read_bytes() == (
            b'cycle|caf\xe9\n')

    def test_an_empty_pipeline_csv_is_not_a_crash(self, tmp_path):
        """`_migrated_pipeline_lines` indexes `lines[0]`. Unguarded, a 0-byte
        `pipeline.csv` raises `IndexError` out of step 4 of 8 and takes the
        report — the thing cleanup is actually for — with it."""
        _write(str(tmp_path), 'working/pipeline.csv', '')

        assert cc.plan_pipeline_csv(str(tmp_path)).changes == ()

    def test_a_review_filename_without_a_date_is_left_alone(self, tmp_path):
        """`pipeline-review-*.md` is the glob; `pipeline-review-(\\d+)-` is the
        parse. A file matching the first and not the second must not be
        counted as a duplicate of whatever precedes it."""
        _write(str(tmp_path), 'working/reviews/pipeline-review-notes.md', 'a')
        _write(str(tmp_path), 'working/reviews/pipeline-review-20260101-a.md',
               'b')

        plan = cc.plan_pipeline_reviews(str(tmp_path))
        plan.apply()

        assert plan.changes == ()
        assert (tmp_path / 'working' / 'reviews'
                / 'pipeline-review-notes.md').exists()


class TestApplyYamlMigrationFailsSafe:
    """#276 was a silent truncation of this file. A plain `open(..., 'w')`
    truncates before it writes, so the temp-file-plus-`os.replace` is the guard
    against a half-written `storyforge.yaml` — and nothing exercised it."""

    def _plan(self, root):
        with open(os.path.join(root, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: X\n')
        return cc.read_and_plan_yaml_migration(root, cc.DiskFacts(root))

    def test_a_failed_write_leaves_the_original_intact(self, tmp_path,
                                                       monkeypatch, capsys):
        plan = self._plan(str(tmp_path))
        assert plan.changed

        def boom(_src, _dst):
            raise OSError('no space left on device')

        monkeypatch.setattr(cc.os, 'replace', boom)
        cc.apply_yaml_migration(str(tmp_path), plan)

        assert ('WARNING: could not write storyforge.yaml'
                in capsys.readouterr().out)
        assert (tmp_path / 'storyforge.yaml').read_text() == (
            'project:\n  title: X\n')

    def test_a_failed_write_leaves_no_temp_file_behind(self, tmp_path,
                                                       monkeypatch):
        """A stray `storyforge.yaml.tmp` is a file nothing reads and nothing
        cleans up, sitting beside the one the author edits by hand."""
        plan = self._plan(str(tmp_path))

        monkeypatch.setattr(cc.os, 'replace',
                            lambda _s, _d: (_ for _ in ()).throw(OSError('x')))
        cc.apply_yaml_migration(str(tmp_path), plan)

        assert not (tmp_path / 'storyforge.yaml.tmp').exists()

    def test_a_failure_to_clean_up_the_temp_file_is_survivable(self, tmp_path,
                                                               capsys):
        """The inner `except OSError: pass`. Reached by making the temp path
        undeletable — a directory — which also makes `open(tmp, 'w')` raise, so
        this is the one arrangement that exercises both handlers at once."""
        (tmp_path / 'storyforge.yaml.tmp').mkdir()
        plan = self._plan(str(tmp_path))

        cc.apply_yaml_migration(str(tmp_path), plan)

        assert ('WARNING: could not write storyforge.yaml'
                in capsys.readouterr().out)
        assert (tmp_path / 'storyforge.yaml').read_text() == (
            'project:\n  title: X\n')

    def test_it_writes_through_a_temp_path_rather_than_over_the_file(
            self, tmp_path, monkeypatch):
        """The atomicity itself, not just its failure modes: dropping the
        temp file for a direct write passes every other test in this suite."""
        plan = self._plan(str(tmp_path))
        replaced: list[tuple[str, str]] = []
        real = cc.os.replace
        monkeypatch.setattr(cc.os, 'replace',
                            lambda s, d: (replaced.append((s, d)), real(s, d)))

        cc.apply_yaml_migration(str(tmp_path), plan)

        assert replaced == [(str(tmp_path / 'storyforge.yaml.tmp'),
                             str(tmp_path / 'storyforge.yaml'))]


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

    def test_a_pending_file_is_a_file(self):
        """The positive half of `isfile`'s pending branch. The negative half
        has a test above; nothing asserted that a pending file answers True,
        so `isfile` could have consulted `pending_dirs` — or nothing — and the
        suite would not have said."""
        disk = cc.DiskFacts('/nowhere',
                            pending_files=('working/logs/.gitkeep',))

        assert disk.isfile('working/logs/.gitkeep')
        assert not disk.isfile('working/logs/absent')

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

    def test_an_artifact_block_with_no_path_is_left_alone(self):
        """`exists:` is decided by resolving `path:` against the disk, so a
        block carrying no path has nothing to decide from. Flipping it either
        way would be a guess written into the author's file."""
        content = ('artifacts:\n  mystery:\n    exists: true\n'
                   '    updated:\n'
                   'scene_extensions: []\n\nevaluation:\n'
                   '  custom_evaluators: []\n\nproduction:\n  author: Ben\n'
                   '\nparts:\n  - number: 1\n')

        plan = cc.plan_yaml_migration(content, cc.DiskFacts('/nowhere'))

        assert not plan.changed
        assert 'exists: true' in plan.new_content

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

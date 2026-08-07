"""Tests for storyforge cleanup — project structure cleanup and CSV integrity.

Covers: parse_args (all flags), gitignore updates, directory creation,
junk file cleanup, legacy file deletion, CSV schema reporting, CSV integrity
reporting, scene file artifact stripping, dry-run mode, --csv mode,
unexpected file reporting, full main orchestration, and error handling.
"""

import os
import shutil
import subprocess

import pytest

import storyforge.cmd_cleanup as cmd_cleanup
from storyforge.cmd_cleanup import (
    parse_args,
    main,
    update_gitignore,
    create_missing_dirs,
    clean_junk_files,
    delete_legacy_files,
    reorganize_loose_files,
    migrate_pipeline_csv,
    dedup_pipeline_reviews,
    report_csv_schema,
    report_csv_integrity,
    report_unexpected_files,
    clean_scene_files,
    build_cleanup_report,
    _classify_issue,
    _detect_rename_pairs,
    _matches_glob,
    EXPECTED_DIRS,
    EXPECTED_CSV_SCHEMAS,
    GITIGNORE_REQUIRED,
    PIPELINE_EXPECTED,
)


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Exhaustive tests for argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.dry_run
        assert not args.verbose
        assert not args.scenes
        assert not args.csv

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_verbose(self):
        args = parse_args(['--verbose'])
        assert args.verbose

    def test_scenes_flag(self):
        args = parse_args(['--scenes'])
        assert args.scenes

    def test_csv_flag(self):
        args = parse_args(['--csv'])
        assert args.csv

    def test_combined_flags(self):
        args = parse_args(['--dry-run', '--verbose', '--scenes'])
        assert args.dry_run
        assert args.verbose
        assert args.scenes

    def test_csv_with_dry_run(self):
        args = parse_args(['--csv', '--dry-run'])
        assert args.csv
        assert args.dry_run


# ============================================================================
# _matches_glob
# ============================================================================


class TestMatchesGlob:
    """Test the filename glob matcher."""

    def test_status_pattern(self):
        assert _matches_glob('.status-12345', '.status-*')

    def test_markers_pattern(self):
        assert _matches_glob('.markers-abc', '.markers-*')

    def test_no_match(self):
        assert not _matches_glob('scores.csv', '.status-*')

    def test_exact_match(self):
        assert _matches_glob('.batch-requests.jsonl', '.batch-requests.jsonl')


# ============================================================================
# update_gitignore
# ============================================================================


class TestUpdateGitignore:
    """Test .gitignore update logic."""

    def test_creates_gitignore_if_missing(self, tmp_path):
        update_gitignore(str(tmp_path))
        gitignore = tmp_path / '.gitignore'
        assert gitignore.exists()
        content = gitignore.read_text()
        assert '.DS_Store' in content

    def test_adds_missing_entries(self, tmp_path):
        gitignore = tmp_path / '.gitignore'
        gitignore.write_text('# My gitignore\n')
        update_gitignore(str(tmp_path))
        content = gitignore.read_text()
        assert 'working/logs/' in content
        assert 'working/scores/**/.batch-requests.jsonl' in content

    def test_preserves_existing_content(self, tmp_path):
        gitignore = tmp_path / '.gitignore'
        original = '# Custom\nmy-custom-ignore/\n'
        gitignore.write_text(original)
        update_gitignore(str(tmp_path))
        content = gitignore.read_text()
        assert 'my-custom-ignore/' in content

    def test_idempotent(self, tmp_path):
        gitignore = tmp_path / '.gitignore'
        gitignore.write_text('')
        update_gitignore(str(tmp_path))
        first = gitignore.read_text()
        update_gitignore(str(tmp_path))
        second = gitignore.read_text()
        assert first == second

    def test_adds_interactive_flag(self, tmp_path):
        gitignore = tmp_path / '.gitignore'
        gitignore.write_text('working/.autopilot\n')
        update_gitignore(str(tmp_path))
        content = gitignore.read_text()
        assert 'working/.interactive' in content

    def test_a_file_with_no_trailing_newline_does_not_lose_its_last_line(
            self, tmp_path):
        """Appending to a file whose last line is unterminated would splice
        the author's entry onto ours — `my-custom-ignore/` becomes
        `my-custom-ignore/# Logs …` and both stop matching."""
        (tmp_path / '.gitignore').write_text('my-custom-ignore/')

        update_gitignore(str(tmp_path))
        lines = (tmp_path / '.gitignore').read_text().splitlines()

        assert 'my-custom-ignore/' in lines
        assert 'working/logs/' in lines

    def test_every_required_entry_is_written(self, tmp_path):
        """Three of the six entries were asserted by the tests above, so
        deleting one of the other three from `_gitignore_with_required` left
        the whole suite green — on a function whose entire job is that list."""
        update_gitignore(str(tmp_path))
        content = (tmp_path / '.gitignore').read_text()

        for entry in ('.DS_Store',
                      'working/logs/',
                      'working/scores/**/.batch-requests.jsonl',
                      'working/evaluations/**/.status-*',
                      'working/scores/**/.markers-*',
                      'working/.autopilot',
                      'working/.interactive'):
            assert entry in content, f'{entry!r} missing'

    def test_a_complete_gitignore_with_no_final_newline_is_left_alone(
            self, tmp_path):
        """The trailing newline was appended before anything checked whether
        there was anything to append, so a complete `.gitignore` whose last
        line was unterminated got rewritten every run — announced as "missing
        entries", which it had none of. #314's shape on a different file."""
        complete = '\n'.join(GITIGNORE_REQUIRED)  # no trailing newline
        (tmp_path / '.gitignore').write_text(complete)

        plan = cmd_cleanup.plan_gitignore(str(tmp_path))
        update_gitignore(str(tmp_path))

        assert plan.changes == ()
        assert (tmp_path / '.gitignore').read_text() == complete

    def test_ds_store_reaches_an_existing_gitignore(self, tmp_path):
        """`.DS_Store` was in `GITIGNORE_REQUIRED` and in the seed written for
        a *missing* file, and in no branch that touched an existing one — so a
        project with a hand-written `.gitignore` never got it, and the constant
        was decorative outside this suite."""
        (tmp_path / '.gitignore').write_text('# Mine\nmy-thing/\n')

        update_gitignore(str(tmp_path))

        assert '.DS_Store' in (tmp_path / '.gitignore').read_text()

    def test_it_writes_what_the_planner_writes(self, tmp_path):
        """`update_gitignore` is the one applier that does not delegate to its
        planner — every other one is `plan_*(...).apply()`. So these tests
        exercise a code path `main` does not take, and the two implementations
        can drift apart with nothing to say so. Pinned rather than merged
        because the fork exists to skip `_untrack_newly_ignored`.
        """
        update_gitignore(str(tmp_path))
        by_applier = (tmp_path / '.gitignore').read_text()
        (tmp_path / '.gitignore').unlink()

        cmd_cleanup.plan_gitignore(str(tmp_path)).apply()

        assert (tmp_path / '.gitignore').read_text() == by_applier


class TestUntrackNewlyIgnored:
    """`git rm --cached` for files the freshly-written .gitignore now excludes.

    Untested until now, and it had never worked: `git ls-files -i` is fatal
    without `-o` or `-c` (git >= 2.32), `capture_output` swallowed the message,
    and nothing checked `returncode` — so the empty stdout read as "nothing is
    ignored-but-tracked" and the sweep silently did nothing.
    """

    def _repo(self, tmp_path):
        root = str(tmp_path)
        subprocess.run(['git', 'init', '-q', root], check=True)
        for k, v in (('user.email', 'a@b.c'), ('user.name', 'Test')):
            subprocess.run(['git', '-C', root, 'config', k, v], check=True)
        os.makedirs(os.path.join(root, 'working', 'logs'))
        with open(os.path.join(root, 'working', 'logs', 'run.log'), 'w') as f:
            f.write('x')
        with open(os.path.join(root, '.gitignore'), 'w') as f:
            f.write('working/logs/\n')
        subprocess.run(['git', '-C', root, 'add', '-Af'], check=True)
        subprocess.run(['git', '-C', root, 'commit', '-qm', 'seed'], check=True)
        return root

    def _tracked(self, root):
        r = subprocess.run(['git', '-C', root, 'ls-files'],
                           capture_output=True, text=True, check=True)
        return set(r.stdout.split())

    def test_it_untracks_a_file_the_gitignore_now_excludes(self, tmp_path):
        root = self._repo(tmp_path)
        assert 'working/logs/run.log' in self._tracked(root)

        cmd_cleanup._untrack_newly_ignored(root)

        assert 'working/logs/run.log' not in self._tracked(root)
        assert '.gitignore' in self._tracked(root), 'untracked too much'

    def test_it_leaves_the_file_on_disk(self, tmp_path):
        """`--cached` only. Cleanup removes `working/logs/*` at its junk step,
        deliberately and under its own announcement; this step must not delete
        anything on its own."""
        root = self._repo(tmp_path)

        cmd_cleanup._untrack_newly_ignored(root)

        assert os.path.isfile(os.path.join(root, 'working', 'logs', 'run.log'))

    def test_a_failing_git_is_reported_rather_than_read_as_nothing_to_do(
            self, tmp_path, monkeypatch, capsys):
        """The silent half of the bug, kept separate from the `-c` half: an
        empty stdout from a *failed* command must not be indistinguishable
        from an empty stdout from a successful one."""
        root = self._repo(tmp_path)
        real_run = subprocess.run

        def fail(cmd, *a, **k):
            if 'ls-files' in cmd:
                return subprocess.CompletedProcess(cmd, 128, '', 'fatal: nope')
            return real_run(cmd, *a, **k)

        monkeypatch.setattr(cmd_cleanup.subprocess, 'run', fail)
        cmd_cleanup._untrack_newly_ignored(root)

        out = capsys.readouterr().out
        assert 'WARNING: could not list ignored-but-tracked files' in out
        assert 'fatal: nope' in out

    def test_it_is_a_no_op_outside_a_git_repository(self, tmp_path):
        cmd_cleanup._untrack_newly_ignored(str(tmp_path))


# ============================================================================
# create_missing_dirs
# ============================================================================


class TestUntrackRunsOnEveryRealRun:
    """It is not a `StepPlan`, and it must not behave like one.

    For one commit it lived inside `plan_gitignore`'s `apply`, which is
    `_no_op` once the `.gitignore` has every required entry — so the sweep ran
    on the first cleanup of a project and never again, where it had always run
    on every real run. It was also the one place an `apply` did something its
    `changes` did not describe, and the per-step property test could not see it
    because a test project has no `.git`. Both halves are why it is called from
    `main` instead.
    """

    def _calls(self, project_dir, argv, monkeypatch):
        seen = []
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_cleanup._untrack_newly_ignored',
                            lambda root: seen.append(root))
        monkeypatch.setattr('storyforge.cmd_cleanup.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))
        main(argv)
        return seen

    def test_it_runs_again_when_the_gitignore_needs_no_update(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        first = self._calls(project_dir, [], monkeypatch)
        assert first == [project_dir]

        # The first run wrote every required entry, so step 1 now plans
        # nothing. The sweep must still happen.
        assert not cmd_cleanup.plan_gitignore(project_dir).changes, (
            'precondition: the gitignore step should have nothing left to do')

        assert self._calls(project_dir, [], monkeypatch) == [project_dir]

    def test_dry_run_never_touches_the_index(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        assert self._calls(project_dir, ['--dry-run'], monkeypatch) == []


class TestTheReportSurvivesAnUnreadableFile:
    """`cleanup`'s product is the report, so nothing optional may take it down.

    `plan_pipeline_csv` logs "the rest of cleanup still runs" when it cannot
    read `working/pipeline.csv` — and that was false, because the file is a
    registered schema and `report_csv_schema` opened it unguarded two steps
    later. A handler asserting survival over a crash is worse than no handler.
    `UnicodeDecodeError` is a `ValueError`, not an `OSError`; naming only the
    latter is the `ill.sha256_of` regression (#298).
    """

    def _latin1(self, project_dir, rel):
        path = os.path.join(project_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write('cycle|started\nMalm\xf6|2026-01-01\n'.encode('latin-1'))

    def test_a_registered_csv_that_is_not_utf8_becomes_a_finding(
            self, project_dir):
        self._latin1(project_dir, 'working/pipeline.csv')

        report = build_cleanup_report(project_dir)

        unreadable = [f for f in report['findings']
                      if f['type'] == 'unreadable_csv']
        assert [f['file'] for f in unreadable] == ['working/pipeline.csv']
        assert unreadable[0]['severity'] == 'error'

    def test_the_whole_report_still_gets_written(
            self, mock_api, mock_git, mock_costs, project_dir, monkeypatch):
        self._latin1(project_dir, 'working/pipeline.csv')
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)

        main(['--csv'])

        report_path = os.path.join(project_dir, 'working',
                                   'cleanup-report.csv')
        assert os.path.isfile(report_path), (
            'no report on disk — forge scans a stale one and reads the '
            'project as clean')
        with open(report_path) as f:
            assert 'unreadable_csv' in f.read()

    def test_an_unreadable_gitignore_is_a_finding_not_just_a_log_line(
            self, project_dir):
        """An empty `StepPlan` is indistinguishable from "nothing to do", so
        the WARNING `plan_gitignore` logs cannot be the only record."""
        with open(os.path.join(project_dir, '.gitignore'), 'wb') as f:
            f.write(b'# Malm\xf6\nworking/logs/\n')

        report = build_cleanup_report(project_dir)

        findings = [f for f in report['findings']
                    if f['type'] == 'unreadable_file'
                    and f['file'] == '.gitignore']
        assert len(findings) == 1
        assert '|' not in findings[0]['detail'], 'must go through csv_safe'


class TestAnUnreadableSceneFileIsSurvivable:
    """`plan_cleanup` builds every plan before the first one runs, so one
    unreadable file costs all nine steps rather than the tail of them — and
    the report with them. Before the planner, the run still created directories
    and migrated the yaml before dying.
    """

    def _bad_scene(self, project_dir):
        path = os.path.join(project_dir, 'scenes', 'bad.md')
        with open(path, 'wb') as f:
            f.write(b'# Malm\xf6\n\nThe prose.\n')

    def test_the_other_eight_steps_still_run(self, project_dir):
        self._bad_scene(project_dir)

        plans = cmd_cleanup.plan_cleanup(project_dir, scenes=True)

        assert len(plans) == 9
        assert any(p.changes for p in plans)

    def test_it_becomes_a_finding_rather_than_a_silent_skip(self, project_dir):
        """A `continue` alone would report the scene as checked and clean."""
        self._bad_scene(project_dir)

        report = build_cleanup_report(project_dir)

        findings = [f for f in report['findings']
                    if f['type'] == 'unreadable_scene']
        assert len(findings) == 1
        assert 'bad.md' in findings[0]['detail']
        assert '|' not in findings[0]['detail'], 'must go through csv_safe'


class TestCreateMissingDirs:
    """Test directory creation for expected directories."""

    def test_creates_missing_directories(self, tmp_path):
        created = create_missing_dirs(str(tmp_path))
        assert len(created) > 0
        for d in created:
            full = tmp_path / d
            assert full.is_dir()
            assert (full / '.gitkeep').exists()

    def test_returns_only_new_dirs(self, tmp_path):
        # Pre-create one directory
        (tmp_path / EXPECTED_DIRS[0]).mkdir(parents=True, exist_ok=True)
        created = create_missing_dirs(str(tmp_path))
        assert EXPECTED_DIRS[0] not in created

    def test_all_expected_dirs_created(self, tmp_path):
        create_missing_dirs(str(tmp_path))
        for d in EXPECTED_DIRS:
            assert (tmp_path / d).is_dir()


# ============================================================================
# clean_junk_files
# ============================================================================


class TestCleanJunkFiles:
    """Test transient file cleanup."""

    def test_removes_status_files(self, tmp_path):
        evals_dir = tmp_path / 'working' / 'evaluations'
        evals_dir.mkdir(parents=True)
        (evals_dir / '.status-12345').touch()
        (evals_dir / '.status-67890').touch()
        clean_junk_files(str(tmp_path))
        remaining = list(evals_dir.iterdir())
        assert len(remaining) == 0

    def test_removes_markers_files(self, tmp_path):
        scores_dir = tmp_path / 'working' / 'scores'
        scores_dir.mkdir(parents=True)
        (scores_dir / '.markers-abc').touch()
        clean_junk_files(str(tmp_path))
        assert not (scores_dir / '.markers-abc').exists()

    def test_removes_batch_request_files(self, tmp_path):
        scores_dir = tmp_path / 'working' / 'scores' / 'cycle-1'
        scores_dir.mkdir(parents=True)
        (scores_dir / '.batch-requests.jsonl').touch()
        clean_junk_files(str(tmp_path))
        assert not (scores_dir / '.batch-requests.jsonl').exists()

    def test_preserves_latest_batch_requests(self, tmp_path):
        latest_dir = tmp_path / 'working' / 'scores' / 'latest'
        latest_dir.mkdir(parents=True)
        batch_file = latest_dir / '.batch-requests.jsonl'
        batch_file.touch()
        clean_junk_files(str(tmp_path))
        assert batch_file.exists()

    def test_removes_log_files(self, tmp_path):
        logs_dir = tmp_path / 'working' / 'logs'
        logs_dir.mkdir(parents=True)
        (logs_dir / 'debug.log').touch()
        (logs_dir / 'review-log.txt').touch()
        clean_junk_files(str(tmp_path))
        remaining = [f for f in logs_dir.iterdir() if f.is_file()]
        assert len(remaining) == 0

    def test_removes_empty_optional_dirs(self, tmp_path):
        for d in ('enrich', 'coaching', 'backups', 'scenes-setup'):
            (tmp_path / 'working' / d).mkdir(parents=True)
        clean_junk_files(str(tmp_path))
        for d in ('enrich', 'coaching', 'backups', 'scenes-setup'):
            assert not (tmp_path / 'working' / d).exists()

    def test_keeps_nonempty_optional_dirs(self, tmp_path):
        coaching_dir = tmp_path / 'working' / 'coaching'
        coaching_dir.mkdir(parents=True)
        (coaching_dir / 'notes.md').touch()
        clean_junk_files(str(tmp_path))
        assert coaching_dir.exists()

    def test_handles_missing_directories(self, tmp_path):
        # Should not raise even if no working directories exist
        clean_junk_files(str(tmp_path))
        assert tmp_path.exists()  # directory itself is untouched


# ============================================================================
# delete_legacy_files
# ============================================================================


class TestDeleteLegacyFiles:
    """Test legacy file removal."""

    def test_removes_pipeline_yaml(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        legacy = working / 'pipeline.yaml'
        legacy.touch()
        delete_legacy_files(str(tmp_path))
        assert not legacy.exists()

    def test_removes_assemble_py(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        legacy = working / 'assemble.py'
        legacy.touch()
        delete_legacy_files(str(tmp_path))
        assert not legacy.exists()

    def test_handles_missing_files(self, tmp_path):
        # Should not raise even if files don't exist
        delete_legacy_files(str(tmp_path))
        assert tmp_path.exists()  # directory itself is untouched


# ============================================================================
# migrate_pipeline_csv
# ============================================================================


class TestMigratePipelineCsv:
    """Test pipeline.csv header migration."""

    def test_adds_missing_columns(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        csv_path = working / 'pipeline.csv'
        csv_path.write_text('cycle|started|status\n1|2026-01-01|done\n')
        migrate_pipeline_csv(str(tmp_path))
        with open(str(csv_path)) as f:
            header = f.readline().strip()
        assert header == PIPELINE_EXPECTED

    def test_preserves_existing_data(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        csv_path = working / 'pipeline.csv'
        csv_path.write_text('cycle|started|status\n1|2026-01-01|done\n')
        migrate_pipeline_csv(str(tmp_path))
        with open(str(csv_path)) as f:
            lines = f.readlines()
        # Data row should still have cycle=1 and started=2026-01-01
        parts = lines[1].strip().split('|')
        assert parts[0] == '1'
        assert parts[1] == '2026-01-01'

    def test_already_correct_noop(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        csv_path = working / 'pipeline.csv'
        content = PIPELINE_EXPECTED + '\n1|2026-01-01|done|||||||\n'
        csv_path.write_text(content)
        migrate_pipeline_csv(str(tmp_path))
        assert csv_path.read_text() == content

    def test_handles_missing_file(self, tmp_path):
        # Should not raise, and should not create a file
        migrate_pipeline_csv(str(tmp_path))
        assert not (tmp_path / 'working' / 'pipeline.csv').exists()


# ============================================================================
# report_csv_schema
# ============================================================================


class TestReportCsvSchema:
    """Test CSV schema checking."""

    def test_reports_missing_csv(self, tmp_path):
        issues = report_csv_schema(str(tmp_path))
        missing = [i for i in issues if i.startswith('MISSING_CSV:')]
        assert len(missing) > 0

    def test_reports_missing_columns(self, tmp_path):
        ref_dir = tmp_path / 'reference'
        ref_dir.mkdir()
        # Create scenes.csv with missing columns
        (ref_dir / 'scenes.csv').write_text('id|seq|title\n')
        issues = report_csv_schema(str(tmp_path))
        missing_cols = [i for i in issues if i.startswith('MISSING_COLUMN:reference/scenes.csv')]
        assert len(missing_cols) > 0

    def test_reports_extra_columns(self, tmp_path):
        ref_dir = tmp_path / 'reference'
        ref_dir.mkdir()
        expected = EXPECTED_CSV_SCHEMAS['reference/scenes.csv']
        header = '|'.join(expected) + '|extra_col'
        (ref_dir / 'scenes.csv').write_text(header + '\n')
        issues = report_csv_schema(str(tmp_path))
        extra = [i for i in issues if i.startswith('EXTRA_COLUMN:reference/scenes.csv:extra_col')]
        assert len(extra) == 1

    def test_no_issues_for_correct_schema(self, tmp_path):
        # Create all expected CSVs with correct headers
        for rel_path, expected_cols in EXPECTED_CSV_SCHEMAS.items():
            full_path = tmp_path / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text('|'.join(expected_cols) + '\n')
        issues = report_csv_schema(str(tmp_path))
        assert len(issues) == 0

    def test_reports_empty_csv(self, tmp_path):
        ref_dir = tmp_path / 'reference'
        ref_dir.mkdir()
        (ref_dir / 'scenes.csv').write_text('')
        issues = report_csv_schema(str(tmp_path))
        empty = [i for i in issues if i.startswith('EMPTY_CSV:reference/scenes.csv')]
        assert len(empty) == 1


# ============================================================================
# report_csv_integrity
# ============================================================================


class TestReportCsvIntegrity:
    """Test CSV cross-file integrity checking."""

    def test_detects_orphan_files(self, project_dir):
        # Create an orphan scene file not in metadata
        orphan_path = os.path.join(project_dir, 'scenes', 'orphan-scene.md')
        with open(orphan_path, 'w') as f:
            f.write('Some prose content.\n')
        issues = report_csv_integrity(project_dir)
        orphans = [i for i in issues if i == 'ORPHAN_FILE:orphan-scene']
        assert len(orphans) == 1

    def test_detects_orphan_metadata(self, project_dir):
        # Remove a scene file that has metadata
        scene_path = os.path.join(project_dir, 'scenes', 'act2-sc01.md')
        if os.path.isfile(scene_path):
            os.remove(scene_path)
        # But act2-sc01 has metadata — check if it's flagged
        issues = report_csv_integrity(project_dir)
        orphan_meta = [i for i in issues if 'ORPHAN_META:act2-sc01' in i]
        assert len(orphan_meta) == 1

    def test_detects_missing_intent(self, project_dir):
        # Add a scene to metadata that is not in intent
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        with open(meta_csv, 'a') as f:
            f.write('ghost-scene|99|Ghost|3|Nobody|Nowhere|9|night|1 hour|plot|briefed|0|1000\n')
        issues = report_csv_integrity(project_dir)
        missing_intent = [i for i in issues if i == 'MISSING_INTENT:ghost-scene']
        assert len(missing_intent) == 1

    def test_detects_sequence_gaps(self, tmp_path):
        ref_dir = tmp_path / 'reference'
        ref_dir.mkdir()
        scenes_dir = tmp_path / 'scenes'
        scenes_dir.mkdir()
        # seq 1, 3 (gap at 2)
        (ref_dir / 'scenes.csv').write_text(
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'sc1|1|A|1|X|Y|1|morning|1h|plot|done|100|100\n'
            'sc3|3|B|1|X|Y|1|morning|1h|plot|done|100|100\n'
        )
        (scenes_dir / 'sc1.md').touch()
        (scenes_dir / 'sc3.md').touch()
        issues = report_csv_integrity(str(tmp_path))
        renumber = [i for i in issues if i.startswith('SEQ_NEEDS_RENUMBER')]
        assert len(renumber) == 1

    def test_no_issues_for_clean_project(self, project_dir):
        """The fixture project should have mostly clean integrity."""
        issues = report_csv_integrity(project_dir)
        # Filter out orphan metadata issues for scenes that don't have files
        # (act2-sc02, act2-sc03 may not have scene files in fixture)
        critical = [i for i in issues
                    if not i.startswith('ORPHAN_META:')
                    and not i.startswith('ORPHAN_FILE:')
                    and not i.startswith('UNKNOWN_CHARACTER:')]
        # Fixture project should have no critical integrity issues
        # (orphan metadata and unknown characters are expected in the test fixture)
        assert critical == []


# ============================================================================
# report_unexpected_files
# ============================================================================


class TestReportUnexpectedFiles:
    """Test unexpected file/directory detection."""

    def test_detects_unexpected_top_level_dir(self, project_dir):
        unexpected_dir = os.path.join(project_dir, 'bogus-dir')
        os.makedirs(unexpected_dir)
        issues = report_unexpected_files(project_dir)
        assert 'UNEXPECTED_DIR:bogus-dir' in issues

    def test_detects_unexpected_top_level_file(self, project_dir):
        unexpected_file = os.path.join(project_dir, 'random.txt')
        with open(unexpected_file, 'w') as f:
            f.write('junk')
        issues = report_unexpected_files(project_dir)
        assert 'UNEXPECTED_FILE:random.txt' in issues

    def test_detects_unexpected_working_subdir(self, project_dir):
        unexpected = os.path.join(project_dir, 'working', 'foobar')
        os.makedirs(unexpected)
        issues = report_unexpected_files(project_dir)
        assert 'UNEXPECTED_DIR:working/foobar' in issues

    def test_detects_unexpected_working_file(self, project_dir):
        unexpected = os.path.join(project_dir, 'working', 'random.txt')
        with open(unexpected, 'w') as f:
            f.write('junk')
        issues = report_unexpected_files(project_dir)
        assert 'UNEXPECTED_FILE:working/random.txt' in issues


# ============================================================================
# clean_scene_files
# ============================================================================


class TestCleanSceneFiles:
    """Test writing-agent artifact stripping from scene files."""

    def test_strips_scene_markers(self, project_dir):
        scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        with open(scene_path, 'w') as f:
            f.write('=== SCENE: act1-sc01 ===\nSome prose.\n=== END SCENE: act1-sc01 ===\n')
        changed = clean_scene_files(project_dir)
        assert changed >= 1
        with open(scene_path) as f:
            content = f.read()
        assert '=== SCENE' not in content
        assert 'Some prose.' in content

    def test_dry_run_does_not_modify(self, project_dir):
        scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        with open(scene_path, 'w') as f:
            f.write('=== SCENE: act1-sc01 ===\nSome prose.\n=== END SCENE: act1-sc01 ===\n')
        original = open(scene_path).read()
        changed = clean_scene_files(project_dir, dry_run=True)
        assert changed >= 1
        with open(scene_path) as f:
            assert f.read() == original

    def test_returns_zero_for_clean_files(self, project_dir):
        # Write clean prose (no artifacts) to all scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            if f.endswith('.md'):
                with open(os.path.join(scenes_dir, f), 'w') as fh:
                    fh.write('Clean prose without artifacts.\n')
        changed = clean_scene_files(project_dir)
        assert changed == 0

    def test_handles_missing_scenes_dir(self, tmp_path):
        changed = clean_scene_files(str(tmp_path))
        assert changed == 0


# ============================================================================
# _classify_issue
# ============================================================================


class TestClassifyIssue:
    """Test issue classification into structured finding dicts."""

    def test_missing_csv_reference(self):
        result = _classify_issue('MISSING_CSV:reference/scenes.csv', {})
        assert result['type'] == 'missing_csv'
        assert result['severity'] == 'warning'

    def test_missing_csv_working(self):
        result = _classify_issue('MISSING_CSV:working/pipeline.csv', {})
        assert result['type'] == 'missing_csv'
        assert result['severity'] == 'info'

    def test_empty_csv(self):
        result = _classify_issue('EMPTY_CSV:reference/scenes.csv', {})
        assert result['type'] == 'empty_csv'
        assert result['severity'] == 'error'

    def test_missing_column(self):
        result = _classify_issue('MISSING_COLUMN:reference/scenes.csv:pov', {})
        assert result['type'] == 'missing_column'
        assert result['column'] == 'pov'

    def test_extra_column(self):
        result = _classify_issue('EXTRA_COLUMN:reference/scenes.csv:bogus', {})
        assert result['type'] == 'extra_column'
        assert result['column'] == 'bogus'
        assert result['severity'] == 'info'

    def test_rename_pair_detected(self):
        pairs = {'reference/scenes.csv': [('new_col', 'old_col')]}
        result = _classify_issue('MISSING_COLUMN:reference/scenes.csv:new_col', pairs)
        assert result['type'] == 'rename_column'
        assert result['rename_from'] == 'old_col'
        assert result['rename_to'] == 'new_col'

    def test_rename_suppresses_extra(self):
        pairs = {'reference/scenes.csv': [('new_col', 'old_col')]}
        result = _classify_issue('EXTRA_COLUMN:reference/scenes.csv:old_col', pairs)
        assert result is None

    def test_orphan_file(self):
        result = _classify_issue('ORPHAN_FILE:my-scene', {})
        assert result['type'] == 'orphan_file'
        assert result['scene_id'] == 'my-scene'

    def test_orphan_meta(self):
        result = _classify_issue('ORPHAN_META:my-scene', {})
        assert result['type'] == 'orphan_meta'

    def test_bad_chapter_ref(self):
        result = _classify_issue('BAD_CHAPTER_REF:missing-scene', {})
        assert result['type'] == 'bad_chapter_ref'
        assert result['severity'] == 'error'

    def test_seq_needs_renumber(self):
        result = _classify_issue('SEQ_NEEDS_RENUMBER:gaps found', {})
        assert result['type'] == 'seq_needs_renumber'

    def test_unknown_character(self):
        result = _classify_issue('UNKNOWN_CHARACTER:Bob', {})
        assert result['type'] == 'unknown_character'
        assert result['character'] == 'Bob'

    def test_unexpected_dir(self):
        result = _classify_issue('UNEXPECTED_DIR:weird', {})
        assert result['type'] == 'unexpected_dir'
        assert result['severity'] == 'info'

    def test_unexpected_file(self):
        result = _classify_issue('UNEXPECTED_FILE:junk.txt', {})
        assert result['type'] == 'unexpected_file'

    def test_unknown_issue(self):
        result = _classify_issue('SOMETHING_ELSE:detail', {})
        assert result['type'] == 'unknown'


# ============================================================================
# _detect_rename_pairs
# ============================================================================


class TestDetectRenamePairs:
    """Test rename pair detection from MISSING/EXTRA column issues."""

    def test_detects_matching_pair(self):
        issues = [
            'MISSING_COLUMN:reference/scenes.csv:new_name',
            'EXTRA_COLUMN:reference/scenes.csv:old_name',
        ]
        pairs = _detect_rename_pairs(issues)
        assert 'reference/scenes.csv' in pairs
        assert pairs['reference/scenes.csv'] == [('new_name', 'old_name')]

    def test_no_pairs_for_unbalanced(self):
        issues = [
            'MISSING_COLUMN:reference/scenes.csv:col_a',
            'MISSING_COLUMN:reference/scenes.csv:col_b',
            'EXTRA_COLUMN:reference/scenes.csv:old_col',
        ]
        pairs = _detect_rename_pairs(issues)
        assert 'reference/scenes.csv' not in pairs

    def test_empty_issues(self):
        pairs = _detect_rename_pairs([])
        assert pairs == {}


# ============================================================================
# build_cleanup_report
# ============================================================================


class TestBuildCleanupReport:
    """Test full cleanup report generation."""

    def test_returns_expected_keys(self, project_dir):
        report = build_cleanup_report(project_dir)
        assert 'findings' in report
        assert 'action_items' in report
        assert 'summary' in report

    def test_summary_counts(self, project_dir):
        report = build_cleanup_report(project_dir)
        summary = report['summary']
        assert 'total' in summary
        assert 'errors' in summary
        assert 'warnings' in summary
        assert 'info' in summary
        assert summary['total'] == summary['errors'] + summary['warnings'] + summary['info']

    def test_action_items_exclude_info(self, project_dir):
        report = build_cleanup_report(project_dir)
        for item in report['action_items']:
            assert item['severity'] != 'info'


# ============================================================================
# reorganize_loose_files
# ============================================================================


class TestReorganizeLooseFiles:
    """Test loose file reorganization."""

    def test_moves_recommendation_files(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        (working / 'recommendations-2026-01-01.md').write_text('rec')
        reorganize_loose_files(str(tmp_path))
        assert (working / 'recommendations' / 'recommendations-2026-01-01.md').exists()
        assert not (working / 'recommendations-2026-01-01.md').exists()

    def test_does_not_overwrite_existing(self, tmp_path):
        working = tmp_path / 'working'
        recs_dir = working / 'recommendations'
        recs_dir.mkdir(parents=True)
        (recs_dir / 'recommendations-old.md').write_text('existing')
        (working / 'recommendations-old.md').write_text('new')
        reorganize_loose_files(str(tmp_path))
        # Original should be preserved
        assert (recs_dir / 'recommendations-old.md').read_text() == 'existing'

    def test_it_creates_the_destination_only_when_something_moves(self,
                                                                  tmp_path):
        """Deliberate (#317): the count is of files that will actually move,
        so a step with nothing to move reports nothing *and does nothing*. It
        used to `makedirs` unconditionally, and restoring that is invisible to
        the per-step property test — `working/recommendations` is in
        `EXPECTED_DIRS`, so step 2 has already created it by the time this step
        runs, and the extra effect leaves no trace in composition.
        """
        (tmp_path / 'working').mkdir()

        reorganize_loose_files(str(tmp_path))

        assert not (tmp_path / 'working' / 'recommendations').exists()

    def test_it_skips_a_taken_destination_without_counting_it(self, tmp_path):
        """The over-report #317 names: `--dry-run` counted every glob match,
        including the ones the real run leaves alone. The count and the moves
        are now one list, and this pins the count rather than the outcome."""
        working = tmp_path / 'working'
        (working / 'recommendations').mkdir(parents=True)
        (working / 'recommendations' / 'recommendations-old.md').write_text('a')
        (working / 'recommendations-old.md').write_text('b')
        (working / 'recommendations-new.md').write_text('c')

        plan = cmd_cleanup.plan_loose_files(
            str(tmp_path), cmd_cleanup.DiskFacts(str(tmp_path)))

        assert [c.would for c in plan.changes] == [
            'Would move 1 recommendation files to working/recommendations/']


# ============================================================================
# dedup_pipeline_reviews
# ============================================================================


class TestDedupPipelineReviews:
    """Test pipeline review deduplication."""

    def test_removes_same_day_duplicates(self, tmp_path):
        reviews_dir = tmp_path / 'working' / 'reviews'
        reviews_dir.mkdir(parents=True)
        # Two reviews from same day
        (reviews_dir / 'pipeline-review-20260101-120000.md').write_text('first')
        (reviews_dir / 'pipeline-review-20260101-130000.md').write_text('second')
        # One from a different day
        (reviews_dir / 'pipeline-review-20260102-120000.md').write_text('third')
        dedup_pipeline_reviews(str(tmp_path))
        remaining = list(reviews_dir.iterdir())
        assert len(remaining) == 2

    def test_handles_missing_reviews_dir(self, tmp_path):
        # Should not raise, and should not create the dir
        dedup_pipeline_reviews(str(tmp_path))
        assert not (tmp_path / 'working' / 'reviews').exists()


# ============================================================================
# main — --csv mode
# ============================================================================


class TestMainCsvMode:
    """Test main() with --csv flag (report only, no modifications)."""

    def test_csv_mode_writes_report(self, mock_api, mock_git, mock_costs,
                                    project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        main(['--csv'])
        report_path = os.path.join(project_dir, 'working', 'cleanup-report.csv')
        assert os.path.isfile(report_path)

    def test_csv_mode_no_branch_creation(self, mock_api, mock_git, mock_costs,
                                         project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        main(['--csv'])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 0

    def test_csv_mode_no_commits(self, mock_api, mock_git, mock_costs,
                                 project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        main(['--csv'])
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 0


# ============================================================================
# main — dry run
# ============================================================================


class TestMainDryRun:
    """Test main() in dry-run mode."""

    def test_dry_run_no_commits(self, mock_api, mock_git, mock_costs,
                                project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_cleanup.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))
        main(['--dry-run'])
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 0

    def test_dry_run_no_branch_creation(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_cleanup.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))
        main(['--dry-run'])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 0

    def test_dry_run_prints_report(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_cleanup.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))
        main(['--dry-run'])
        output = capsys.readouterr().out
        assert 'DRY RUN' in output


# ============================================================================
# main — full run
# ============================================================================


class TestMainFullRun:
    """Test main() full cleanup path."""

    def test_creates_branch(self, mock_api, mock_git, mock_costs,
                            project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_cleanup.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))
        main([])
        branch_calls = mock_git.calls_for('ensure_on_branch')
        assert len(branch_calls) == 1

    def test_commits_when_changes_exist(self, mock_api, mock_git, mock_costs,
                                        project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        # Create .git directory so the commit path is reached
        os.makedirs(os.path.join(project_dir, '.git'), exist_ok=True)
        # Simulate git reporting changes to commit
        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and 'status' in cmd and '--porcelain' in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout='M .gitignore\n', stderr='')
            return subprocess.CompletedProcess(cmd if isinstance(cmd, list) else [cmd], 0,
                                               stdout='', stderr='')
        monkeypatch.setattr('storyforge.cmd_cleanup.subprocess.run', fake_subprocess_run)
        # Also need shutil.which to return something for the git check
        monkeypatch.setattr('storyforge.cmd_cleanup.shutil.which',
                            lambda x: '/usr/bin/git' if x == 'git' else None)
        main([])
        commit_calls = mock_git.calls_for('commit_and_push')
        assert len(commit_calls) == 1

    def test_scenes_flag_triggers_scene_cleanup(self, mock_api, mock_git,
                                                mock_costs, project_dir,
                                                monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_cleanup.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))
        main(['--scenes'])
        output = capsys.readouterr().out
        assert 'scene file' in output.lower()

    def test_writes_cleanup_report(self, mock_api, mock_git, mock_costs,
                                   project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_cleanup.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_cleanup.subprocess.run',
                            lambda *a, **kw: subprocess.CompletedProcess(
                                a[0] if a else [], 0, stdout='', stderr=''))
        main([])
        report_path = os.path.join(project_dir, 'working', 'cleanup-report.csv')
        assert os.path.isfile(report_path)
        # Verify report is pipe-delimited with expected header
        with open(report_path) as f:
            header = f.readline().strip()
        assert 'category' in header
        assert 'severity' in header

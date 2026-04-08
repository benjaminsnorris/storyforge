"""Tests for cmd_cleanup command module."""

import os
import pytest
from storyforge.cmd_cleanup import (
    parse_args, update_gitignore, create_missing_dirs, clean_junk_files,
    _matches_glob, delete_legacy_files, reorganize_loose_files,
    migrate_pipeline_csv, dedup_pipeline_reviews, report_csv_integrity,
    report_unexpected_files, migrate_storyforge_yaml,
    GITIGNORE_REQUIRED, EXPECTED_DIRS, PIPELINE_EXPECTED,
)


class TestParseArgs:
    """Argument parsing for storyforge cleanup."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.dry_run
        assert not args.verbose

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_verbose(self):
        args = parse_args(['--verbose'])
        assert args.verbose

    def test_both_flags(self):
        args = parse_args(['--dry-run', '--verbose'])
        assert args.dry_run
        assert args.verbose


class TestMatchesGlob:
    """Simple glob matching for filenames."""

    def test_status_match(self):
        assert _matches_glob('.status-abc', '.status-*')

    def test_status_no_match(self):
        assert not _matches_glob('data.csv', '.status-*')

    def test_markers_match(self):
        assert _matches_glob('.markers-xyz', '.markers-*')

    def test_exact_match(self):
        assert _matches_glob('.DS_Store', '.DS_Store')


class TestUpdateGitignore:
    """update_gitignore adds missing entries."""

    def test_creates_gitignore_if_missing(self, tmp_path):
        update_gitignore(str(tmp_path))
        gitignore = tmp_path / '.gitignore'
        assert gitignore.exists()
        content = gitignore.read_text()
        assert '.DS_Store' in content

    def test_adds_missing_entries(self, tmp_path):
        gitignore = tmp_path / '.gitignore'
        gitignore.write_text('# Existing\n.DS_Store\n')
        update_gitignore(str(tmp_path))
        content = gitignore.read_text()
        assert 'working/logs/' in content

    def test_idempotent(self, tmp_path):
        gitignore = tmp_path / '.gitignore'
        gitignore.write_text('')
        update_gitignore(str(tmp_path))
        first = gitignore.read_text()
        update_gitignore(str(tmp_path))
        second = gitignore.read_text()
        assert first == second


class TestCreateMissingDirs:
    """create_missing_dirs creates expected directories."""

    def test_creates_dirs(self, tmp_path):
        created = create_missing_dirs(str(tmp_path))
        assert len(created) == len(EXPECTED_DIRS)
        for d in EXPECTED_DIRS:
            assert (tmp_path / d).is_dir()

    def test_creates_gitkeep(self, tmp_path):
        create_missing_dirs(str(tmp_path))
        for d in EXPECTED_DIRS:
            assert (tmp_path / d / '.gitkeep').exists()

    def test_idempotent(self, tmp_path):
        create_missing_dirs(str(tmp_path))
        second = create_missing_dirs(str(tmp_path))
        assert len(second) == 0


class TestCleanJunkFiles:
    """clean_junk_files removes transient files."""

    def test_removes_status_files(self, tmp_path):
        evals_dir = tmp_path / 'working' / 'evaluations' / 'cycle1'
        evals_dir.mkdir(parents=True)
        (evals_dir / '.status-abc').write_text('ok')
        (evals_dir / 'data.csv').write_text('data')
        clean_junk_files(str(tmp_path))
        assert not (evals_dir / '.status-abc').exists()
        assert (evals_dir / 'data.csv').exists()

    def test_removes_markers_files(self, tmp_path):
        scores_dir = tmp_path / 'working' / 'scores' / 'cycle1'
        scores_dir.mkdir(parents=True)
        (scores_dir / '.markers-xyz').write_text('data')
        clean_junk_files(str(tmp_path))
        assert not (scores_dir / '.markers-xyz').exists()

    def test_removes_log_files(self, tmp_path):
        logs_dir = tmp_path / 'working' / 'logs'
        logs_dir.mkdir(parents=True)
        (logs_dir / 'debug.log').write_text('log data')
        clean_junk_files(str(tmp_path))
        assert not (logs_dir / 'debug.log').exists()


class TestDeleteLegacyFiles:
    """delete_legacy_files removes known legacy artifacts."""

    def test_removes_pipeline_yaml(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        (working / 'pipeline.yaml').write_text('old: data')
        delete_legacy_files(str(tmp_path))
        assert not (working / 'pipeline.yaml').exists()

    def test_removes_assemble_py(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        (working / 'assemble.py').write_text('old script')
        delete_legacy_files(str(tmp_path))
        assert not (working / 'assemble.py').exists()

    def test_ignores_missing(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        delete_legacy_files(str(tmp_path))  # should not raise


class TestMigratePipelineCsv:
    """migrate_pipeline_csv updates header columns."""

    def test_adds_missing_columns(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        csv_path = working / 'pipeline.csv'
        csv_path.write_text('cycle|started|status\n1|2025-01-01|done\n')
        migrate_pipeline_csv(str(tmp_path))
        header = csv_path.read_text().splitlines()[0]
        assert header == PIPELINE_EXPECTED

    def test_preserves_existing_data(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        csv_path = working / 'pipeline.csv'
        csv_path.write_text('cycle|started|status\n1|2025-01-01|done\n')
        migrate_pipeline_csv(str(tmp_path))
        lines = csv_path.read_text().strip().splitlines()
        row = lines[1].split('|')
        assert row[0] == '1'
        assert row[1] == '2025-01-01'
        assert row[2] == 'done'

    def test_noop_when_current(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        csv_path = working / 'pipeline.csv'
        csv_path.write_text(PIPELINE_EXPECTED + '\n1|2025|done|||||||\n')
        migrate_pipeline_csv(str(tmp_path))
        assert csv_path.read_text().startswith(PIPELINE_EXPECTED)

    def test_noop_when_missing(self, tmp_path):
        working = tmp_path / 'working'
        working.mkdir()
        migrate_pipeline_csv(str(tmp_path))  # should not raise


class TestDedupPipelineReviews:
    """dedup_pipeline_reviews keeps latest per day."""

    def test_removes_duplicates(self, tmp_path):
        reviews = tmp_path / 'working' / 'reviews'
        reviews.mkdir(parents=True)
        (reviews / 'pipeline-review-20250101-120000.md').write_text('old')
        (reviews / 'pipeline-review-20250101-140000.md').write_text('newer')
        (reviews / 'pipeline-review-20250102-100000.md').write_text('next day')
        dedup_pipeline_reviews(str(tmp_path))
        files = sorted(os.listdir(reviews))
        assert len(files) == 2
        # The newer file for 0101 should remain
        assert 'pipeline-review-20250101-140000.md' in files
        assert 'pipeline-review-20250102-100000.md' in files


class TestReportCsvIntegrity:
    """report_csv_integrity detects data issues."""

    def test_empty_project_no_crash(self, tmp_path):
        ref = tmp_path / 'reference'
        ref.mkdir()
        issues = report_csv_integrity(str(tmp_path))
        assert isinstance(issues, list)

    def test_orphan_scene_file(self, tmp_path):
        ref = tmp_path / 'reference'
        ref.mkdir()
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        (ref / 'scenes.csv').write_text('id|seq|title\nscene-a|1|Scene A\n')
        (scenes / 'scene-a.md').write_text('prose')
        (scenes / 'scene-b.md').write_text('orphan')
        issues = report_csv_integrity(str(tmp_path))
        assert any('ORPHAN_FILE:scene-b' in i for i in issues)

    def test_orphan_metadata(self, tmp_path):
        ref = tmp_path / 'reference'
        ref.mkdir()
        scenes = tmp_path / 'scenes'
        scenes.mkdir()
        (ref / 'scenes.csv').write_text('id|seq|title\nscene-a|1|A\nscene-b|2|B\n')
        (scenes / 'scene-a.md').write_text('prose')
        issues = report_csv_integrity(str(tmp_path))
        assert any('ORPHAN_META:scene-b' in i for i in issues)


class TestReportUnexpectedFiles:
    """report_unexpected_files detects unexpected files/dirs."""

    def test_unexpected_top_dir(self, tmp_path):
        (tmp_path / 'random_dir').mkdir()
        issues = report_unexpected_files(str(tmp_path))
        assert any('UNEXPECTED_DIR:random_dir' in i for i in issues)

    def test_expected_dirs_not_flagged(self, tmp_path):
        for d in ['scenes', 'reference', 'working', 'manuscript']:
            (tmp_path / d).mkdir(exist_ok=True)
        issues = report_unexpected_files(str(tmp_path))
        flagged_dirs = [i for i in issues if 'UNEXPECTED_DIR:scenes' in i
                        or 'UNEXPECTED_DIR:reference' in i
                        or 'UNEXPECTED_DIR:working' in i
                        or 'UNEXPECTED_DIR:manuscript' in i]
        assert len(flagged_dirs) == 0  # all four are in EXPECTED_TOP_DIRS

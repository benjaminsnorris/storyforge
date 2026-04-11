"""Tests for storyforge cleanup --csv schema validation and action formatting."""

import json
import os

from storyforge.cmd_cleanup import (
    EXPECTED_CSV_SCHEMAS,
    report_csv_schema,
    build_cleanup_report,
    _classify_issue,
    _detect_rename_pairs,
    _write_report,
)


def _write_csv(project_dir, rel_path, header, rows=None):
    """Write a CSV file with the given header and optional data rows."""
    path = os.path.join(project_dir, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(header + '\n')
        if rows:
            for row in rows:
                f.write(row + '\n')


class TestReportCsvSchema:
    """Tests for the report_csv_schema function."""

    def test_missing_csv_reported(self, tmp_path):
        """Missing CSV files are reported."""
        issues = report_csv_schema(str(tmp_path))
        missing = [i for i in issues if i.startswith('MISSING_CSV:')]
        assert len(missing) == len(EXPECTED_CSV_SCHEMAS)

    def test_all_present_no_issues(self, tmp_path):
        """All CSVs present with correct headers produce no issues."""
        for rel_path, cols in EXPECTED_CSV_SCHEMAS.items():
            _write_csv(str(tmp_path), rel_path, '|'.join(cols))

        issues = report_csv_schema(str(tmp_path))
        assert issues == []

    def test_missing_column_reported(self, tmp_path):
        """A CSV missing an expected column is reported."""
        # Write scenes.csv without 'target_words'
        cols = [c for c in EXPECTED_CSV_SCHEMAS['reference/scenes.csv']
                if c != 'target_words']
        _write_csv(str(tmp_path), 'reference/scenes.csv', '|'.join(cols))

        issues = report_csv_schema(str(tmp_path))
        missing_col = [i for i in issues
                       if i == 'MISSING_COLUMN:reference/scenes.csv:target_words']
        assert len(missing_col) == 1

    def test_extra_column_reported(self, tmp_path):
        """A CSV with an unexpected column is reported."""
        cols = EXPECTED_CSV_SCHEMAS['reference/locations.csv'] + ['extra_col']
        _write_csv(str(tmp_path), 'reference/locations.csv', '|'.join(cols))

        issues = report_csv_schema(str(tmp_path))
        extra = [i for i in issues
                 if i == 'EXTRA_COLUMN:reference/locations.csv:extra_col']
        assert len(extra) == 1

    def test_empty_csv_reported(self, tmp_path):
        """An empty CSV file is reported."""
        path = os.path.join(str(tmp_path), 'reference', 'scenes.csv')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('')

        issues = report_csv_schema(str(tmp_path))
        empty = [i for i in issues if i == 'EMPTY_CSV:reference/scenes.csv']
        assert len(empty) == 1

    def test_multiple_issues_per_file(self, tmp_path):
        """Multiple missing columns in one file are each reported."""
        # Write characters.csv with only id|name
        _write_csv(str(tmp_path), 'reference/characters.csv', 'id|name')

        issues = report_csv_schema(str(tmp_path))
        char_issues = [i for i in issues
                       if 'reference/characters.csv' in i]
        missing = [i for i in char_issues if i.startswith('MISSING_COLUMN:')]
        # Should be missing: aliases, role, death_scene
        assert len(missing) == 3

    def test_fixture_matches_schema(self, fixture_dir):
        """The test fixture project has all expected columns."""
        issues = report_csv_schema(fixture_dir)
        # Filter to only schema issues for reference/ CSVs that exist in fixture
        ref_issues = [i for i in issues
                      if not i.startswith('MISSING_CSV:working/')]
        assert ref_issues == [], f'Fixture schema issues: {ref_issues}'


class TestDetectRenamePairs:
    """Tests for rename pair detection."""

    def test_detects_rename(self):
        issues = [
            'MISSING_COLUMN:reference/chapter-map.csv:chapter',
            'EXTRA_COLUMN:reference/chapter-map.csv:seq',
        ]
        pairs = _detect_rename_pairs(issues)
        assert 'reference/chapter-map.csv' in pairs
        assert pairs['reference/chapter-map.csv'] == [('chapter', 'seq')]

    def test_no_rename_when_counts_differ(self):
        issues = [
            'MISSING_COLUMN:reference/scenes.csv:col_a',
            'MISSING_COLUMN:reference/scenes.csv:col_b',
            'EXTRA_COLUMN:reference/scenes.csv:col_x',
        ]
        pairs = _detect_rename_pairs(issues)
        assert 'reference/scenes.csv' not in pairs

    def test_empty_issues(self):
        assert _detect_rename_pairs([]) == {}


class TestClassifyIssue:
    """Tests for structured issue classification."""

    def test_missing_reference_csv(self):
        finding = _classify_issue('MISSING_CSV:reference/motif-taxonomy.csv', {})
        assert finding['type'] == 'missing_csv'
        assert finding['severity'] == 'warning'
        assert 'command' in finding

    def test_missing_working_csv(self):
        finding = _classify_issue('MISSING_CSV:working/pipeline.csv', {})
        assert finding['type'] == 'missing_csv'
        assert finding['severity'] == 'info'

    def test_missing_column_plain(self):
        finding = _classify_issue(
            'MISSING_COLUMN:reference/characters.csv:death_scene', {})
        assert finding['type'] == 'missing_column'
        assert finding['column'] == 'death_scene'
        assert 'death_scene' in finding['action']

    def test_missing_column_as_rename(self):
        pairs = {'reference/chapter-map.csv': [('chapter', 'seq')]}
        finding = _classify_issue(
            'MISSING_COLUMN:reference/chapter-map.csv:chapter', pairs)
        assert finding['type'] == 'rename_column'
        assert finding['rename_from'] == 'seq'
        assert finding['rename_to'] == 'chapter'

    def test_extra_column_suppressed_by_rename(self):
        pairs = {'reference/chapter-map.csv': [('chapter', 'seq')]}
        finding = _classify_issue(
            'EXTRA_COLUMN:reference/chapter-map.csv:seq', pairs)
        assert finding is None

    def test_orphan_file(self):
        finding = _classify_issue('ORPHAN_FILE:lost-scene', {})
        assert finding['type'] == 'orphan_file'
        assert finding['scene_id'] == 'lost-scene'
        assert 'storyforge extract' in finding['command']

    def test_orphan_meta(self):
        finding = _classify_issue('ORPHAN_META:ghost-row', {})
        assert finding['type'] == 'orphan_meta'
        assert 'remove' in finding['action'].lower() or 'create' in finding['action'].lower()

    def test_unknown_character(self):
        finding = _classify_issue('UNKNOWN_CHARACTER:Bob', {})
        assert finding['type'] == 'unknown_character'
        assert finding['character'] == 'Bob'
        assert 'storyforge hone' in finding['command']

    def test_seq_renumber(self):
        finding = _classify_issue('SEQ_NEEDS_RENUMBER:gaps found', {})
        assert finding['type'] == 'seq_needs_renumber'
        assert 'storyforge scenes-setup' in finding['command']

    def test_bad_chapter_ref(self):
        finding = _classify_issue('BAD_CHAPTER_REF:deleted-scene', {})
        assert finding['type'] == 'bad_chapter_ref'
        assert finding['severity'] == 'error'


class TestBuildCsvReport:
    """Tests for the full report builder."""

    def test_clean_project_no_actions(self, tmp_path):
        """A project with all correct CSVs has no action items."""
        for rel_path, cols in EXPECTED_CSV_SCHEMAS.items():
            _write_csv(str(tmp_path), rel_path, '|'.join(cols))
        # Need scenes dir for unexpected files check
        (tmp_path / 'scenes').mkdir()
        (tmp_path / 'reference').mkdir(exist_ok=True)
        (tmp_path / 'working').mkdir(exist_ok=True)
        (tmp_path / 'manuscript').mkdir()
        (tmp_path / 'storyforge.yaml').touch()
        (tmp_path / '.gitignore').touch()

        report = build_cleanup_report(str(tmp_path))
        assert report['summary']['errors'] == 0
        assert report['summary']['warnings'] == 0
        assert len(report['action_items']) == 0

    def test_report_has_action_items(self, tmp_path):
        """Missing columns show up as action items."""
        _write_csv(str(tmp_path), 'reference/scenes.csv', 'id|seq|title')

        report = build_cleanup_report(str(tmp_path))
        assert report['summary']['warnings'] > 0
        assert len(report['action_items']) > 0
        # Each action item should have required fields
        for item in report['action_items']:
            assert 'type' in item
            assert 'action' in item
            assert 'severity' in item


class TestWriteReport:
    """Tests for JSON report file output."""

    def test_writes_valid_json(self, tmp_path):
        report = {
            'findings': [{'type': 'test', 'detail': 'x', 'action': 'y',
                         'severity': 'info', 'category': 'schema'}],
            'action_items': [],
            'summary': {'total': 1, 'errors': 0, 'warnings': 0, 'info': 1},
        }
        path = _write_report(report, str(tmp_path))
        assert os.path.isfile(path)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded['summary']['total'] == 1

    def test_report_path(self, tmp_path):
        report = {'findings': [], 'action_items': [],
                  'summary': {'total': 0, 'errors': 0, 'warnings': 0, 'info': 0}}
        path = _write_report(report, str(tmp_path))
        assert path.endswith('working/cleanup-report.json')

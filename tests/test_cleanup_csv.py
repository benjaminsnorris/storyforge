"""Tests for storyforge cleanup --csv schema validation."""

import os

from storyforge.cmd_cleanup import (
    EXPECTED_CSV_SCHEMAS,
    report_csv_schema,
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

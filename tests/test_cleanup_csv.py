"""Tests for storyforge cleanup --csv schema validation and action formatting."""

import os

from storyforge.cmd_cleanup import (
    EXPECTED_CSV_SCHEMAS,
    REPORT_COLUMNS,
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
    """Tests for CSV report file output."""

    def test_writes_valid_csv(self, tmp_path):
        report = {
            'findings': [{'type': 'test', 'detail': 'x', 'action': 'y',
                         'severity': 'info', 'category': 'schema',
                         'file': 'ref.csv', 'command': ''}],
            'action_items': [],
            'summary': {'total': 1, 'errors': 0, 'warnings': 0, 'info': 1},
        }
        path = _write_report(report, str(tmp_path))
        assert os.path.isfile(path)
        with open(path) as f:
            lines = f.readlines()
        assert lines[0].strip() == '|'.join(REPORT_COLUMNS)
        assert len(lines) == 2  # header + 1 finding
        cols = lines[1].strip().split('|')
        assert len(cols) == len(REPORT_COLUMNS)
        assert cols[0] == 'schema'  # category
        assert cols[1] == 'test'    # type

    def test_report_path(self, tmp_path):
        report = {'findings': [], 'action_items': [],
                  'summary': {'total': 0, 'errors': 0, 'warnings': 0, 'info': 0}}
        path = _write_report(report, str(tmp_path))
        assert path.endswith('working/cleanup-report.csv')

    def test_missing_fields_default_empty(self, tmp_path):
        """Findings without optional fields get empty strings."""
        report = {
            'findings': [{'type': 'test', 'detail': 'x', 'action': 'y',
                         'severity': 'info', 'category': 'schema'}],
            'action_items': [],
            'summary': {'total': 1, 'errors': 0, 'warnings': 0, 'info': 1},
        }
        path = _write_report(report, str(tmp_path))
        with open(path) as f:
            lines = f.readlines()
        cols = lines[1].strip().split('|')
        # 'file' and 'command' should be empty
        file_idx = REPORT_COLUMNS.index('file')
        cmd_idx = REPORT_COLUMNS.index('command')
        assert cols[file_idx] == ''
        assert cols[cmd_idx] == ''


class TestPagesDirectory:
    """Cleanup integration for GN per-page files (issue #251)."""

    def test_pages_dir_not_flagged_unexpected_in_gn(self, tmp_path):
        """A pages/ directory in a GN project is recognized, not flagged."""
        from storyforge.cmd_cleanup import report_unexpected_files
        (tmp_path / 'pages').mkdir()
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        issues = report_unexpected_files(str(tmp_path))
        assert not any(i == 'UNEXPECTED_DIR:pages' for i in issues)

    def test_pages_dir_still_flagged_in_novel_mode(self, tmp_path):
        """pages/ in a prose-novel project remains UNEXPECTED — it has no
        meaning in novel mode and should be cleaned up."""
        from storyforge.cmd_cleanup import report_unexpected_files
        (tmp_path / 'pages').mkdir()
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: novel\n'
        )
        issues = report_unexpected_files(str(tmp_path))
        assert any(i == 'UNEXPECTED_DIR:pages' for i in issues)

    def test_invalid_page_file_surfaced_in_report(self, tmp_path):
        """A page file missing required frontmatter surfaces a finding in
        the structured report."""
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        (pages / 's01-p1.md').write_text('# No frontmatter\n')
        report = build_cleanup_report(str(tmp_path))
        page_findings = [f for f in report['findings']
                         if f.get('category') == 'pages']
        assert len(page_findings) >= 1
        assert any(f['type'] == 'page_no_frontmatter' for f in page_findings)

    def test_clean_page_file_no_findings(self, tmp_path):
        """A fully-populated v3 page file (## Page architecture +
        ## Image-generation workflow + ## Panel script) produces zero
        page-category findings."""
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        (pages / 's01-p1.md').write_text(
            "---\n"
            "page_id: s01-p1\n"
            "scene_id: s01-studio-finalization\n"
            "page_within_scene: 1\n"
            "total_pages_in_scene: 5\n"
            "panel_count: 2\n"
            "---\n\n"
            "## Page architecture\n\nIntent.\n\n"
            "## Panel script\n\n**Panel 1.** Wide.\n\n"
            "## Image-generation workflow\n\n"
            "**Approach:** Whole-page generation.\n"
        )
        report = build_cleanup_report(str(tmp_path))
        page_findings = [f for f in report['findings']
                         if f.get('category') == 'pages']
        assert page_findings == []

    def test_missing_field_finding_surfaced(self, tmp_path):
        """T-9: missing required field surfaces as page_missing_field."""
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        (pages / 's01-p1.md').write_text(
            "---\npage_id: s01-p1\nscene_id: s01\n"
            "total_pages_in_scene: 5\npanel_count: 2\n---\n"
        )
        report = build_cleanup_report(str(tmp_path))
        types = {f['type'] for f in report['findings']
                 if f.get('category') == 'pages'}
        assert 'page_missing_field' in types

    def test_render_orphan_finding_surfaced(self, tmp_path):
        """#261: a PNG in manuscript/pages/ with no matching page file
        surfaces as page_render_orphan; an unrendered page does NOT."""
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        (pages / 's01-p1.md').write_text(
            "---\npage_id: s01-p1\nscene_id: s01\npage_within_scene: 1\n"
            "total_pages_in_scene: 1\npanel_count: 1\n---\n\n"
            "## Page architecture\n\nx.\n\n## Image-generation workflow\n\nx.\n"
        )
        rdir = tmp_path / 'manuscript' / 'pages'
        rdir.mkdir(parents=True)
        (rdir / 's09-p9.png').write_bytes(b'\x89PNG')  # orphan
        # s01-p1 is intentionally NOT rendered (valid in-flight state)
        report = build_cleanup_report(str(tmp_path))
        page_findings = [f for f in report['findings']
                         if f.get('category') == 'pages']
        types = {f['type'] for f in page_findings}
        assert 'page_render_orphan' in types
        orphan = next(f for f in page_findings
                      if f['type'] == 'page_render_orphan')
        assert 's09-p9.png' in orphan['file']
        assert orphan['severity'] == 'warning'

    def test_unrendered_page_is_not_a_finding(self, tmp_path):
        """#261: a complete page file with no PNG is valid in-flight state."""
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        (pages / 's01-p1.md').write_text(
            "---\npage_id: s01-p1\nscene_id: s01\npage_within_scene: 1\n"
            "total_pages_in_scene: 1\npanel_count: 1\n---\n\n"
            "## Page architecture\n\nx.\n\n## Panel script\n\n**Panel 1.**\n\n"
            "## Image-generation workflow\n\nx.\n"
        )
        report = build_cleanup_report(str(tmp_path))
        types = {f['type'] for f in report['findings']
                 if f.get('category') == 'pages'}
        assert 'page_render_orphan' not in types

    def test_filename_mismatch_finding_surfaced(self, tmp_path):
        """T-9: filename != page_id surfaces as page_filename_mismatch."""
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        (pages / 's01-p7.md').write_text(
            "---\npage_id: s01-p1\nscene_id: s01\n"
            "page_within_scene: 1\ntotal_pages_in_scene: 5\npanel_count: 2\n"
            "---\n"
        )
        report = build_cleanup_report(str(tmp_path))
        types = {f['type'] for f in report['findings']
                 if f.get('category') == 'pages'}
        assert 'page_filename_mismatch' in types

    def test_out_of_range_finding_surfaced(self, tmp_path):
        """T-9: page_within_scene > total_pages_in_scene → page_out_of_range."""
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        (pages / 's01-p9.md').write_text(
            "---\npage_id: s01-p9\nscene_id: s01\n"
            "page_within_scene: 9\ntotal_pages_in_scene: 5\npanel_count: 2\n"
            "---\n"
        )
        report = build_cleanup_report(str(tmp_path))
        types = {f['type'] for f in report['findings']
                 if f.get('category') == 'pages'}
        assert 'page_out_of_range' in types

    def test_bad_integer_field_finding_surfaced(self, tmp_path):
        """bad_integer_field (introduced for CR-5/SF-3) surfaces in cleanup."""
        (tmp_path / 'storyforge.yaml').write_text(
            'project:\n  title: Test\n  medium: graphic-novel\n'
        )
        pages = tmp_path / 'pages'
        pages.mkdir()
        (pages / 's01-p1.md').write_text(
            "---\npage_id: s01-p1\nscene_id: s01\n"
            "page_within_scene: 1\ntotal_pages_in_scene: 1\n"
            "panel_count: bananas\n---\n"
        )
        report = build_cleanup_report(str(tmp_path))
        types = {f['type'] for f in report['findings']
                 if f.get('category') == 'pages'}
        assert 'page_bad_integer_field' in types

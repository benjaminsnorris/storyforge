"""The export bundle (plan §3.5): every table regenerates byte-for-byte, the
keys are pinned, and nothing it can't read is dropped silently. Changing a key
or a value's type must bump export.SCHEMA_VERSION in the same commit (and in
docs/agent-reference.md)."""

import glob
import json
import os
import shutil

import pytest

from storyforge import export, ledger
from storyforge.project import INCOMPLETE_MARKER
from storyforge.visualize import DASHBOARD_SCHEMA_VERSION

V1_KEYS = {'schema_version', 'storyforge_version', 'project', 'score_cycle',
           'tables', 'dashboard_data', 'warnings'}
PROJECT_KEYS = {'title', 'genre', 'medium', 'phase'}
TABLE_KEYS = {'kind', 'header', 'rows', 'line_ending', 'final_newline', 'bom'}


def _read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def _assert_round_trip(project_dir, bundle):
    """Every table regenerates the exact bytes on disk, and every reference CSV
    is a table."""
    texts = export.tables_from_bundle(bundle)
    for rel, text in texts.items():
        assert text.encode('utf-8') == _read_bytes(os.path.join(project_dir, rel)), rel
    refs = {os.path.relpath(p, project_dir)
            for p in glob.glob(os.path.join(project_dir, 'reference', '*.csv'))}
    assert refs and refs <= set(texts)


def _write(path, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


class TestShape:
    def test_v1_keys(self, project_dir):
        bundle = export.build_bundle(project_dir)
        assert export.SCHEMA_VERSION == 1 and bundle['schema_version'] == 1
        assert set(bundle) == V1_KEYS
        assert set(bundle['project']) == PROJECT_KEYS
        assert bundle['project']['title'] == "The Cartographer's Silence"
        assert bundle['project']['medium'] == 'novel'
        assert bundle['project']['phase'] == 'drafting'
        for table in bundle['tables'].values():
            assert set(table) == TABLE_KEYS

    def test_storyforge_version_is_the_plugins(self, project_dir, plugin_dir):
        with open(os.path.join(plugin_dir, '.claude-plugin', 'plugin.json')) as f:
            version = json.load(f)['version']
        assert export.build_bundle(project_dir)['storyforge_version'] == version

    def test_dashboard_data_folds_in_with_its_own_version(self, project_dir):
        bundle = export.build_bundle(project_dir)
        dashboard = bundle['dashboard_data']
        assert dashboard['schema_version'] == DASHBOARD_SCHEMA_VERSION
        assert len(dashboard['scenes']) > 0

    def test_ledger_and_registries_are_tables(self, project_dir):
        tables = export.build_bundle(project_dir)['tables']
        for name in ('scenes', 'scene-intent', 'scene-briefs', 'characters',
                     'locations', 'values', 'mice-threads', 'motif-taxonomy',
                     'commitments'):
            assert tables[f'reference/{name}.csv']['kind'] == 'reference'
        assert tables['reference/commitments.csv']['header'] == ledger.COLUMNS

    def test_clean_fixture_has_no_warnings(self, project_dir):
        assert export.build_bundle(project_dir)['warnings'] == []


class TestRoundTrip:
    def test_fixture_project(self, project_dir):
        bundle = export.build_bundle(project_dir)
        _assert_round_trip(project_dir, bundle)

    def test_gn_fixture(self, project_dir_gn):
        bundle = export.build_bundle(project_dir_gn)
        assert bundle['project']['medium'] == 'graphic-novel'
        _assert_round_trip(project_dir_gn, bundle)

    def test_through_json(self, project_dir):
        """The written file, read back, still regenerates every table."""
        path = os.path.join(project_dir, export.DEFAULT_OUTPUT)
        export.write_bundle(export.build_bundle(project_dir), path)
        with open(path, encoding='utf-8') as f:
            _assert_round_trip(project_dir, json.load(f))

    def test_crlf_file(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'values.csv')
        text = _read_bytes(path).decode('utf-8')
        _write(path, text.replace('\n', '\r\n').encode('utf-8'))
        bundle = export.build_bundle(project_dir)
        table = bundle['tables']['reference/values.csv']
        assert table['line_ending'] == '\r\n'
        assert not any('\r' in c for row in table['rows'] for c in row)
        assert bundle['warnings'] == []
        _assert_round_trip(project_dir, bundle)

    @pytest.mark.parametrize('data', [
        b'', b'\n', b'id|name', b'id|name\n\nx|y\n', b'id|name\r\nx|y',
        b'\xef\xbb\xbfid|name\nx|y\n', b'id| name |\nx||\n', b'a\r\nb\nc\n',
        b'a\rb\n', 'id|name\nx|café   “q”\n'.encode('utf-8'),
    ])
    def test_edge_cases_are_byte_identical(self, data):
        table = export.parse_table(data.decode('utf-8'))
        assert export.table_text(table).encode('utf-8') == data

    def test_bom_is_recorded(self):
        table = export.parse_table('﻿id|name\n')
        assert table['bom'] and table['header'] == ['id', 'name']

    def test_mixed_line_endings_are_kept_and_named(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'values.csv')
        _write(path, b'id|name\r\nx|y\nz|w\n')
        bundle = export.build_bundle(project_dir)
        assert any('reference/values.csv' in w and 'mixed line endings' in w
                   for w in bundle['warnings'])
        _assert_round_trip(project_dir, bundle)


class TestScoresTimelineAudit:
    def test_latest_complete_cycle(self, project_dir):
        scores = os.path.join(project_dir, 'working', 'scores')
        _write(os.path.join(scores, 'cycle-1', 'scene-scores.csv'), b'id|p\na|1\n')
        _write(os.path.join(scores, 'cycle-2', 'scene-scores.csv'), b'id|p\na|2\n')
        _write(os.path.join(scores, 'cycle-2', 'report.html'), b'<p>')
        _write(os.path.join(scores, 'cycle-3', 'scene-scores.csv'), b'id|p\na|3\n')
        _write(os.path.join(scores, 'cycle-3', INCOMPLETE_MARKER), b'')
        _write(os.path.join(scores, 'structural-latest.csv'), b'dimension|score\n')
        bundle = export.build_bundle(project_dir)
        assert bundle['score_cycle'] == 'working/scores/cycle-2'
        scored = {p for p, t in bundle['tables'].items() if t['kind'] == 'scores'}
        assert scored == {'working/scores/cycle-2/scene-scores.csv',
                          'working/scores/structural-latest.csv'}
        _assert_round_trip(project_dir, bundle)

    def test_latest_symlink(self, project_dir):
        scores = os.path.join(project_dir, 'working', 'scores')
        _write(os.path.join(scores, 'cycle-4', 'scene-scores.csv'), b'id|p\na|4\n')
        os.symlink('cycle-4', os.path.join(scores, 'latest'))
        bundle = export.build_bundle(project_dir)
        assert bundle['score_cycle'] == 'working/scores/cycle-4'
        assert 'working/scores/cycle-4/scene-scores.csv' in bundle['tables']
        _assert_round_trip(project_dir, bundle)

    def test_no_scores(self, project_dir):
        assert export.build_bundle(project_dir)['score_cycle'] is None

    def test_timeline_cues(self, project_dir):
        _write(os.path.join(project_dir, 'working', 'timeline-cues.csv'), b'id|gap\na|1d\n')
        bundle = export.build_bundle(project_dir)
        assert bundle['tables']['working/timeline-cues.csv']['kind'] == 'timeline'

    def test_audit_csvs_pass_through_and_other_files_are_named(self, project_dir):
        working = os.path.join(project_dir, 'working')
        _write(os.path.join(working, 'audit.csv'), b'id|note\n1|x\n')
        _write(os.path.join(working, 'audit', 'entries.csv'), b'id|note\r\n2|y\r\n')
        _write(os.path.join(working, 'audit', 'digest.md'), b'# digest\n')
        bundle = export.build_bundle(project_dir)
        audit = {p for p, t in bundle['tables'].items() if t['kind'] == 'audit'}
        assert audit == {'working/audit.csv', 'working/audit/entries.csv'}
        assert any('working/audit/digest.md' in w for w in bundle['warnings'])
        _assert_round_trip(project_dir, bundle)


class TestProblems:
    def test_unreadable_table_is_named_not_dropped_silently(self, project_dir):
        _write(os.path.join(project_dir, 'reference', 'themes.csv'), b'id|name\nx|\xff\n')
        bundle = export.build_bundle(project_dir)
        assert 'reference/themes.csv' not in bundle['tables']
        assert any(w.startswith('reference/themes.csv: not UTF-8') for w in bundle['warnings'])

    def test_dashboard_failure_is_named(self, project_dir, monkeypatch):
        def boom(_):
            raise ValueError('bad word_count')
        monkeypatch.setattr('storyforge.visualize.load_dashboard_data', boom)
        bundle = export.build_bundle(project_dir)
        assert bundle['dashboard_data'] is None
        assert any('dashboard_data could not be built' in w and 'bad word_count' in w
                   for w in bundle['warnings'])

    def test_unmigrated_project_raises(self, project_dir, fixture_dir):
        legacy = os.path.join(os.path.dirname(fixture_dir), 'legacy-registries')
        shutil.copy(os.path.join(legacy, 'knowledge.csv'),
                    os.path.join(project_dir, 'reference', 'knowledge.csv'))
        with pytest.raises(ledger.NotMigratedError, match='storyforge migrate'):
            export.build_bundle(project_dir)

    def test_malformed_ledger_raises(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'commitments.csv')
        with open(path, 'a', encoding='utf-8') as f:
            f.write('short|row\n')
        with pytest.raises(ledger.LedgerError):
            export.build_bundle(project_dir)


class TestStableJson:
    def test_sorted_lf_utf8(self, project_dir):
        bundle = export.build_bundle(project_dir)
        bundle['project']['title'] = 'Café'
        path = os.path.join(project_dir, 'out', 'b.json')
        export.write_bundle(bundle, path)
        raw = _read_bytes(path)
        assert b'\r' not in raw and 'Café'.encode('utf-8') in raw
        keys = list(json.loads(raw))
        assert keys == sorted(keys)

"""The audit log (`storyforge.audit`, `working/audit-log.csv`): written
centrally by every ledger write, and the writers that now log through it."""

import os
import shutil

import pytest

from storyforge import audit, ledger

LEGACY_FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'legacy-registries')


def _log(project_dir):
    return audit.read_log(str(project_dir))


def _ref(project_dir):
    return os.path.join(str(project_dir), 'reference')


def _clear_log(project_dir):
    path = audit.log_path(str(project_dir))
    if os.path.exists(path):
        os.remove(path)


def _fact(rid, **kw):
    row = {c: '' for c in ledger.COLUMNS}
    row.update(id=rid, type='knowledge', statement=f'{rid} statement',
               origin='prose', status='binding', mutable='state',
               introduced_by='extract')
    row.update(kw)
    return row


class TestDiffEntries:
    def test_added_changed_removed(self):
        old = [_fact('a'), _fact('b'), _fact('c')]
        new = [_fact('a'), _fact('b', statement='b moved'), _fact('d', introduced_by='')]
        entries = audit.diff_entries(old, new, command='hone', timestamp='T')
        assert [(e['fact_id'], e['change'], e['command'], e['columns'])
                for e in entries] == [
            ('b', 'changed', 'hone', 'statement'),
            ('d', 'added', 'hone', ''),      # no introduced_by: the writer
            ('c', 'removed', 'hone', ''),
        ]

    def test_added_row_names_its_introduced_by(self):
        entries = audit.diff_entries([], [_fact('a', introduced_by='redraft')],
                                     command='hone')
        assert entries[0]['command'] == 'redraft'

    def test_status_and_review_changes_have_their_own_kinds(self):
        old = [_fact('a'), _fact('b'), _fact('c')]
        new = [_fact('a', status='superseded'), _fact('b', status='rejected',
                                                      reviewed='rejected:2026-10-30'),
               _fact('c', reviewed='seen:2026-10-30')]
        kinds = [e['change'] for e in audit.diff_entries(old, new, command='audit')]
        assert kinds == ['superseded', 'rejected', 'reviewed']

    def test_unchanged_rows_give_nothing(self):
        rows = [_fact('a'), _fact('b')]
        assert audit.diff_entries(rows, [dict(r) for r in rows], command='x') == []


class TestSaveLogs:
    def test_save_to_appends_one_entry_per_change(self, project_dir):
        rows = ledger.load(project_dir)
        rows[0]['statement'] = 'A map anomaly exists | in two records\nreally'
        removed = rows.pop()
        ledger.save(project_dir, rows, command='hone')
        log = _log(project_dir)
        assert [(e['fact_id'], e['change'], e['command']) for e in log] == [
            (rows[0]['id'], 'changed', 'hone'), (removed['id'], 'removed', 'hone')]
        # Prose through csv_safe: one line, no extra cells
        assert log[0]['statement'] == 'A map anomaly exists / in two records really'

    def test_log_is_lf_with_the_header(self, project_dir):
        rows = ledger.load(project_dir)
        ledger.save(project_dir, rows + [_fact('new-fact')], command='test')
        with open(audit.log_path(str(project_dir)), 'rb') as f:
            data = f.read()
        assert b'\r' not in data
        lines = data.decode().splitlines()
        assert lines[0] == '|'.join(audit.COLUMNS)
        assert all(len(line.split('|')) == len(audit.COLUMNS) for line in lines)

    def test_appends_across_writes(self, project_dir):
        rows = ledger.load(project_dir)
        ledger.save(project_dir, rows + [_fact('one')], command='test')
        ledger.save(project_dir, ledger.load(project_dir) + [_fact('two')], command='test')
        assert [e['fact_id'] for e in _log(project_dir)] == ['one', 'two']

    def test_a_write_that_changes_nothing_logs_nothing(self, project_dir):
        ledger.save(project_dir, ledger.load(project_dir), command='test')
        assert not os.path.exists(audit.log_path(str(project_dir)))

    def test_write_view_logs_under_introduced_by_or_command(self, project_dir):
        ref = _ref(project_dir)
        view = ledger.read_view(ref, 'knowledge')
        view[0]['name'] = 'Reworded'
        ledger.write_view(ref, 'knowledge', view, origin='prose', introduced_by='extract')
        view[0]['name'] = 'Reworded again'
        ledger.write_view(ref, 'knowledge', view, origin='prose', introduced_by='extract',
                          command='revise')
        assert [e['command'] for e in _log(project_dir)] == ['extract', 'revise']

    def test_an_unwritable_log_keeps_the_ledger_write_and_warns(self, project_dir, capsys):
        # A directory where the log file should be: the append fails
        os.makedirs(audit.log_path(str(project_dir)))
        rows = ledger.load(project_dir)
        ledger.save(project_dir, rows + [_fact('kept')], command='test')
        assert 'kept' in {r['id'] for r in ledger.load(project_dir)}
        out = capsys.readouterr().out
        assert 'WARNING: working/audit-log.csv was not written' in out
        assert 'kept' in out

    def test_a_log_with_another_header_is_not_appended_to(self, project_dir, capsys):
        path = audit.log_path(str(project_dir))
        with open(path, 'w') as f:
            f.write('when|what\n')
        ledger.save(project_dir, ledger.load(project_dir) + [_fact('x')], command='test')
        with open(path) as f:
            assert f.read() == 'when|what\n'
        assert 'WARNING: working/audit-log.csv was not written' in capsys.readouterr().out


class TestWritersLog:
    """Regression: each existing ledger writer now leaves audit entries."""

    def test_hone_registry_write(self, project_dir):
        from storyforge.hone import write_registry
        ref = _ref(project_dir)
        view = ledger.read_view(ref, 'knowledge')
        view[0]['aliases'] = 'a new alias'
        write_registry(ref, 'knowledge', view)
        log = _log(project_dir)
        assert [(e['fact_id'], e['change'], e['command'], e['columns']) for e in log] == [
            (view[0]['id'], 'changed', 'hone', 'aliases')]

    def test_extract_physical_states(self, project_dir):
        from storyforge.cmd_extract import _record_physical_states
        ref = _ref(project_dir)
        _record_physical_states(ref, 'act1-sc02',
                                [{'id': 'cut-hand', 'character': 'Dorren Hayle',
                                  'description': 'Dorren cut her hand',
                                  'category': 'injury'}], [], {})
        log = _log(project_dir)
        assert [(e['fact_id'], e['change'], e['command'], e['scene_id'], e['type'])
                for e in log] == [('cut-hand', 'added', 'extract', 'act1-sc02', 'physical')]

    def test_extract_cleanup(self, project_dir):
        from storyforge.extract import cleanup_answer_formats
        ref = _ref(project_dir)
        rows = ledger.load_from(ref)
        phys = next(r for r in rows if r['type'] == 'physical')
        phys['action_gating'] = 'Yes — she cannot climb'
        ledger.save_to(ref, rows, command='test')
        _clear_log(project_dir)
        cleanup_answer_formats(ref)
        assert [(e['fact_id'], e['command'], e['columns']) for e in _log(project_dir)] == [
            (phys['id'], 'extract-cleanup', 'action_gating')]

    def test_migration_logs_one_summary_entry(self, project_dir):
        ref = _ref(project_dir)
        os.remove(os.path.join(ref, 'commitments.csv'))
        for name in ledger.LEGACY_FILES:
            shutil.copy(os.path.join(LEGACY_FIXTURE, name), ref)
        result = ledger.migrate_files(ref)
        assert result.status == 'done'
        log = _log(project_dir)
        assert len(log) == 1
        assert log[0]['change'] == 'migrated' and log[0]['command'] == 'migrate'
        assert f'{len(result.rows)} facts' in log[0]['statement']

    def test_migration_dry_run_logs_nothing(self, project_dir):
        ref = _ref(project_dir)
        os.remove(os.path.join(ref, 'commitments.csv'))
        for name in ledger.LEGACY_FILES:
            shutil.copy(os.path.join(LEGACY_FIXTURE, name), ref)
        assert ledger.migrate_files(ref, dry_run=True).status == 'dry-run'
        assert _log(project_dir) == []

    def test_save_requires_a_command(self, project_dir):
        with pytest.raises(TypeError):
            ledger.save(project_dir, ledger.load(project_dir))


class TestCleanupKnowsTheLog:
    def test_the_log_is_not_an_unexpected_working_file(self, project_dir):
        from storyforge.cmd_cleanup import EXPECTED_WORKING_FILES, EXPECTED_CSV_SCHEMAS
        assert audit.LOG_FILE in EXPECTED_WORKING_FILES
        assert EXPECTED_CSV_SCHEMAS[audit.LOG_PATH] == audit.COLUMNS


class TestSnapshot:
    def test_migration_starts_the_snapshot(self, project_dir):
        ref = _ref(project_dir)
        os.remove(os.path.join(ref, 'commitments.csv'))
        for name in ledger.LEGACY_FILES:
            shutil.copy(os.path.join(LEGACY_FIXTURE, name), ref)
        ledger.migrate_files(ref)
        assert audit.read_snapshot(str(project_dir)) == ledger.load_from(ref)

    def test_each_save_updates_the_snapshot(self, project_dir):
        rows = ledger.load(project_dir) + [_fact('snap')]
        ledger.save(project_dir, rows, command='test')
        assert audit.read_snapshot(str(project_dir)) == ledger.load(project_dir)

    def test_hand_edit_entries(self, project_dir):
        ledger.save(project_dir, ledger.load(project_dir) + [_fact('h')], command='test')
        rows = ledger.load(project_dir)
        rows[-1]['statement'] = 'edited'
        ledger.write_ledger(ledger.ledger_path(str(project_dir)), rows)   # by hand
        entries = audit.log_hand_edits(str(project_dir), ledger.load(project_dir))
        assert [(e['fact_id'], e['command']) for e in entries] == [('h', 'hand-edit')]
        assert audit.log_hand_edits(str(project_dir), ledger.load(project_dir)) == []

    def test_cleanup_expects_the_snapshot(self):
        from storyforge.cmd_cleanup import EXPECTED_WORKING_FILES
        assert audit.SNAPSHOT_FILE in EXPECTED_WORKING_FILES

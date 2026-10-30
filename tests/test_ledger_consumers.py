"""The consumers of the knowledge facts and physical states read and write
the commitments ledger (`reference/commitments.csv`), and stop while the old
knowledge.csv / physical-states.csv are still on disk."""

import os
import shutil

import pytest

from storyforge import ledger
from ledger_helpers import write_facts

LEGACY = os.path.join(os.path.dirname(__file__), 'fixtures', 'legacy-registries')


def _unmigrated(project_dir):
    ref = os.path.join(project_dir, 'reference')
    os.remove(os.path.join(ref, ledger.LEDGER_FILE))
    for name in ledger.LEGACY_FILES:
        shutil.copy(os.path.join(LEGACY, name), ref)
    return ref


# ============================================================================
# Old files, no ledger: every command that reads the facts stops
# ============================================================================

@pytest.mark.parametrize('module', [
    'cmd_validate', 'cmd_hone', 'cmd_extract', 'cmd_enrich', 'cmd_elaborate',
    'cmd_write', 'cmd_revise', 'cmd_score', 'cmd_visualize'])
def test_a_command_stops_on_the_old_files(module, project_dir, monkeypatch, capsys):
    import importlib
    mod = importlib.import_module(f'storyforge.{module}')
    _unmigrated(project_dir)
    monkeypatch.setattr(mod, 'detect_project_root', lambda *a, **k: project_dir)
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    with pytest.raises(SystemExit) as exc:
        mod.main(['--stage', 'briefs'] if module == 'cmd_elaborate' else [])
    assert exc.value.code == 1
    assert 'run `storyforge migrate`' in capsys.readouterr().out


def test_the_dispatcher_turns_a_late_error_into_a_plain_stop(project_dir, monkeypatch, capsys):
    """A command with no up-front check that reaches the registries exits 1
    with the message, not a traceback."""
    from storyforge import __main__ as dispatcher

    class Command:
        @staticmethod
        def main(argv):
            ledger.load(project_dir)
    _unmigrated(project_dir)
    with pytest.raises(SystemExit) as exc:
        dispatcher._dispatch(Command)
    assert exc.value.code == 1
    assert 'ERROR: reference/knowledge.csv and reference/physical-states.csv must move' \
        in capsys.readouterr().err


def test_neither_file_reads_as_empty_registries(project_dir):
    os.remove(os.path.join(project_dir, 'reference', ledger.LEDGER_FILE))
    from storyforge.enrich import format_registries_for_prompt, load_registry_alias_maps
    assert load_registry_alias_maps(project_dir)['knowledge'] == {}
    assert 'Knowledge Facts' not in format_registries_for_prompt(project_dir)
    ledger.exit_if_not_migrated(project_dir)   # no stop


def test_cleanup_reports_the_old_files(project_dir):
    from storyforge.cmd_cleanup import build_cleanup_report
    _unmigrated(project_dir)
    findings = [f for f in build_cleanup_report(project_dir)['action_items']
                if f['type'] == 'legacy_registry']
    assert sorted(f['file'] for f in findings) == ['reference/knowledge.csv',
                                                   'reference/physical-states.csv']
    assert all(f['severity'] == 'error' and f['command'] == 'storyforge migrate'
               for f in findings)


def test_cleanup_knows_the_ledger_and_pronouns(project_dir):
    from storyforge.cmd_cleanup import report_csv_schema
    chars = os.path.join(project_dir, 'reference', 'characters.csv')
    with open(chars) as f:
        lines = f.read().splitlines()
    issues = report_csv_schema(project_dir)
    assert not [i for i in issues if 'commitments.csv' in i or 'characters.csv' in i]
    # An author's pronouns column is known, not unexpected
    with open(chars, 'w') as f:
        f.write('\n'.join([lines[0] + '|pronouns'] + [l + '|' for l in lines[1:]]) + '\n')
    assert not [i for i in report_csv_schema(project_dir) if 'characters.csv' in i]


# ============================================================================
# Readers
# ============================================================================

def test_the_registries_prompt_lists_the_ledgers_knowledge_facts(project_dir):
    from storyforge.enrich import format_registries_for_prompt
    text = format_registries_for_prompt(project_dir)
    assert '### Knowledge Facts (reference/commitments.csv)\n' \
           '- map-anomaly-exists (A map anomaly exists in the pressure records)' in text
    assert 'Knowledge Facts' not in format_registries_for_prompt(project_dir,
                                                                 exclude=('knowledge',))


def test_knowledge_aliases_resolve_from_the_ledger(project_dir):
    from storyforge.enrich import load_registry_alias_maps
    assert load_registry_alias_maps(project_dir)['knowledge']['missing village'] == \
        'village-vanished'


def test_the_drafting_prompt_reads_states_from_the_ledger(project_dir, plugin_dir):
    """Characters show by name (the ledger holds the id); an unresolved
    character shows the name the migration kept in aliases."""
    from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP
    from storyforge.prompts import build_scene_prompt_from_briefs
    ref = os.path.join(project_dir, 'reference')
    rows = ledger.load_from(ref)
    scar = next(r for r in rows if r['id'] == 'scar-left-hand-kael')
    scar.update(subject='', aliases='Garren')
    ledger.save_to(ref, rows)
    briefs = os.path.join(ref, 'scene-briefs.csv')
    rows = _read_csv(briefs)
    rows[0]['physical_state_in'] = 'archive-key-dorren;scar-left-hand-kael'
    _write_csv(briefs, rows, _FILE_MAP['scene-briefs.csv'])
    prompt = build_scene_prompt_from_briefs(rows[0]['id'], project_dir, str(plugin_dir))
    assert '- **Dorren Hayle**: holds the restricted archive key *(action-gating)*' in prompt
    assert '- **Garren**: old scar across left palm from archive incident' in prompt


def test_validate_stops_on_a_ledger_it_cannot_read(project_dir, monkeypatch, capsys):
    from storyforge import cmd_validate
    path = ledger.ledger_path(project_dir)
    with open(path) as f:
        lines = f.read().splitlines()
    with open(path, 'w') as f:
        f.write('\n'.join(lines + [lines[1]]) + '\n')   # a duplicate id
    monkeypatch.setattr(cmd_validate, 'detect_project_root', lambda: project_dir)
    with pytest.raises(SystemExit) as exc:
        cmd_validate.main([])
    assert exc.value.code == 1
    assert "id 'map-anomaly-exists' is also on line 2" in capsys.readouterr().out


def test_elaborate_reports_a_gating_state_with_no_character(project_dir):
    from storyforge.elaborate import validate_structure
    ref = os.path.join(project_dir, 'reference')
    rows = ledger.load_from(ref)
    key = next(r for r in rows if r['id'] == 'archive-key-dorren')
    key.update(subject='', aliases='Garren')
    ledger.save_to(ref, rows)
    flags = [c for c in validate_structure(ref)['checks']
             if c.get('check') == 'state-owner-unknown']
    assert [c['message'] for c in flags] == [
        "Physical state 'archive-key-dorren' gates action but has no character id "
        "(written as 'Garren', not in characters.csv): its on-stage relevance is not checked"]


class TestSchemaAgainstTheLedger:
    def _brief(self, project_dir, **fields):
        from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP
        path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
        rows = _read_csv(path)
        rows[0].update(fields)
        _write_csv(path, rows, _FILE_MAP['scene-briefs.csv'])

    def _errors(self, project_dir, column):
        from storyforge.schema import validate_schema
        ref = os.path.join(project_dir, 'reference')
        return [e for e in validate_schema(ref, project_dir)['errors']
                if e['column'] == column]

    def test_knowledge_ids_resolve_only_against_knowledge_facts(self, project_dir):
        # A physical state's id is in the ledger, but is not a knowledge fact
        self._brief(project_dir, knowledge_in='archive-key-dorren;missing village')
        errors = self._errors(project_dir, 'knowledge_in')
        assert [e['unresolved'] for e in errors] == [['archive-key-dorren']]
        assert errors[0]['registry'] == 'commitments.csv (knowledge)'

    def test_physical_state_ids_are_now_checked(self, project_dir):
        """physical-states.csv had no name column, so its alias map was empty
        and physical_state_in/out were never checked."""
        self._brief(project_dir, physical_state_in='archive-key-dorren;no-such-state')
        errors = self._errors(project_dir, 'physical_state_in')
        assert [e['unresolved'] for e in errors] == [['no-such-state']]

    def test_the_ledgers_own_rules_are_checked(self, project_dir):
        from storyforge.schema import validate_schema
        ref = os.path.join(project_dir, 'reference')
        rows = ledger.load_from(ref)
        rows[0]['status'] = 'maybe'
        ledger.save_to(ref, rows)
        errors = [e for e in validate_schema(ref, project_dir)['errors']
                  if e['constraint'] == 'ledger']
        assert len(errors) == 1 and "status 'maybe'" in errors[0]['reason']


# ============================================================================
# Writers keep every other row
# ============================================================================

def test_hone_writes_change_only_their_type(project_dir):
    from storyforge.hone import read_registry, write_registry
    ref = os.path.join(project_dir, 'reference')
    rows = ledger.load_from(ref)
    rows.append({**rows[0], 'id': 'day-three', 'type': 'timeline', 'statement': 'Day 3'})
    rows[0]['quote'] = 'a quote hone never sees'
    ledger.save_to(ref, rows)
    knowledge = read_registry(ref, 'knowledge')
    knowledge[1]['aliases'] = 'gone village'
    write_registry(ref, 'knowledge', knowledge)
    after = ledger.load_from(ref)
    assert after[0]['quote'] == 'a quote hone never sees'
    assert after[1]['aliases'] == 'gone village'
    assert [r for r in after if r['type'] != 'knowledge'] == \
        [r for r in rows if r['type'] != 'knowledge']


def test_recording_physical_states_keeps_the_knowledge_facts(project_dir):
    from storyforge.cmd_extract import _record_physical_states
    ref = os.path.join(project_dir, 'reference')
    before = ledger.knowledge_view(ledger.load_from(ref))
    _record_physical_states(ref, 'act2-sc01', [
        {'id': 'cut-hand', 'character': 'Dorren', 'description': 'a cut hand',
         'category': 'injury'}], ['exhaustion-tessa'],
        {'dorren': 'dorren-hayle'})
    rows = ledger.load_from(ref)
    assert ledger.knowledge_view(rows) == before
    new = next(r for r in rows if r['id'] == 'cut-hand')
    assert (new['subject'], new['scene_id'], new['origin'], new['introduced_by']) == (
        'dorren-hayle', 'act2-sc01', 'prose', 'extract')


def test_propagation_with_no_states_reports_none_refused(project_dir):
    """With no physical states, propagate_physical_states returned no
    `refused`, which cmd_hone reads: a KeyError in `hone --domain gaps`."""
    from storyforge.hone import propagate_physical_states
    ref = os.path.join(project_dir, 'reference')
    write_facts(ref, 'physical-states.csv', 'id|character\n')
    assert propagate_physical_states(ref)['refused'] == []


def test_the_dashboard_lists_knowledge_in_the_old_shape(project_dir):
    from storyforge.visualize import load_dashboard_data
    data = load_dashboard_data(project_dir)
    assert data['knowledge'] == ledger.knowledge_view(ledger.load(project_dir))
    assert data['knowledge'][0]['id'] == 'map-anomaly-exists'

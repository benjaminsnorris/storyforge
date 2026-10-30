"""Tests for storyforge.ledger: commitments.csv, derived state, and the
migration from knowledge.csv and physical-states.csv."""

import os
import shutil

import pytest

from storyforge import ledger
from storyforge.ledger import (
    COLUMNS, active_states, drafting_slice, established_before, migrate_registries,
    read_ledger, regenerate_knowledge, regenerate_physical,
    round_trip_differences, scene_order, validate_ledger, write_ledger,
)


def _row(rid, **fields):
    row = {c: '' for c in COLUMNS}
    row.update(id=rid, type='physical', statement=f'{rid} holds', origin='prose',
               status='binding', mutable='state')
    row.update(fields)
    return row


ORDER = {'s1': 0, 's2': 1, 's3': 2, 's4': 3}


# ============================================================================
# Read and write
# ============================================================================

class TestReadWrite:
    def test_round_trip(self, tmp_path):
        path = str(tmp_path / 'reference' / 'commitments.csv')
        rows = [_row('a', scene_id='s1', subject='tessa'),
                _row('b', type='knowledge', aliases='x;y')]
        write_ledger(path, rows)
        assert read_ledger(path) == rows

    def test_writes_lf_with_the_header(self, tmp_path):
        path = str(tmp_path / 'commitments.csv')
        write_ledger(path, [_row('a')])
        raw = open(path, 'rb').read()
        assert b'\r' not in raw
        assert raw.decode().splitlines()[0] == '|'.join(COLUMNS)

    def test_prose_is_kept_on_one_line_with_no_pipe(self, tmp_path):
        path = str(tmp_path / 'commitments.csv')
        write_ledger(path, [_row('a', statement='one | two\nthree',
                                 quote='"Go," she said.\nHe went.')])
        row = read_ledger(path)[0]
        assert '|' not in row['statement'] and '\n' not in row['quote']
        assert row['id'] == 'a' and row['type'] == 'physical'

    def test_a_pipe_in_an_id_column_raises(self, tmp_path):
        with pytest.raises(ValueError, match='subject'):
            write_ledger(str(tmp_path / 'c.csv'), [_row('a', subject='x|y')])

    def test_a_missing_file_reads_as_empty(self, tmp_path):
        assert read_ledger(str(tmp_path / 'nope.csv')) == []

    def test_a_short_row_reads_with_every_column(self, tmp_path):
        path = tmp_path / 'c.csv'
        path.write_text('id|type\na|physical\n')
        row = read_ledger(str(path))[0]
        assert set(row) == set(COLUMNS) and row['statement'] == ''


# ============================================================================
# Validation
# ============================================================================

class TestValidate:
    def test_clean(self):
        rows = [_row('a', scene_id='s1', subject='tessa', resolves='never'),
                _row('b', scene_id='s2', subject='tessa', supersedes='a')]
        assert validate_ledger(rows, scene_ids=set(ORDER),
                               character_ids={'tessa'}) == []

    def test_reports_each_problem(self):
        rows = [_row('a', type='rumour', status='maybe', mutable='often',
                     origin='guess', statement='', action_gating='yes'),
                _row('a'), _row(''),
                _row('c', scene_id='s9', resolves='s8', subject='garren',
                     depends_on='ghost')]
        problems = '\n'.join(validate_ledger(rows, scene_ids=set(ORDER),
                                             character_ids={'tessa'}))
        for expected in ("type 'rumour'", "status 'maybe'", "mutable 'often'",
                         "origin 'guess'", 'no statement', "action_gating 'yes'",
                         'id also on line 2', 'no id', "scene_id 's9' is not a scene",
                         "resolves 's8'", "subject 'garren'",
                         "depends_on names 'ghost'"):
            assert expected in problems

    def test_scene_and_character_checks_only_run_when_given(self):
        rows = [_row('a', scene_id='nowhere', subject='nobody')]
        assert validate_ledger(rows) == []


# ============================================================================
# Derived state
# ============================================================================

class TestActiveStates:
    def test_a_state_holds_from_its_scene_until_it_resolves(self):
        rows = [_row('ankle', scene_id='s2', subject='tessa', resolves='s4')]
        held = {sid: bool(active_states(rows, sid, ORDER)) for sid in ORDER}
        assert held == {'s1': False, 's2': True, 's3': True, 's4': False}

    def test_entering_the_resolving_scene_the_state_still_holds(self):
        rows = [_row('ankle', scene_id='s2', subject='tessa', resolves='s4')]
        assert active_states(rows, 's4', ORDER, entering=True)
        assert not active_states(rows, 's2', ORDER, entering=True)

    def test_a_superseded_state_is_gone_once_the_new_one_is_established(self):
        rows = [_row('coat-on', scene_id='s1', subject='tessa'),
                _row('coat-off', scene_id='s3', subject='tessa', supersedes='coat-on')]
        assert [r['id'] for r in active_states(rows, 's2', ORDER)] == ['coat-on']
        assert [r['id'] for r in active_states(rows, 's3', ORDER)] == ['coat-off']

    def test_only_binding_state_facts_for_the_subject(self):
        rows = [_row('a', scene_id='s1', subject='tessa'),
                _row('b', scene_id='s1', subject='dorren'),
                _row('c', scene_id='s1', subject='tessa', status='pending'),
                _row('d', scene_id='s1', subject='tessa', mutable='fixed')]
        assert [r['id'] for r in active_states(rows, 's1', ORDER,
                                               subject='tessa')] == ['a']

    def test_a_fact_with_no_scene_holds_from_the_start(self):
        rows = [_row('scar', scene_id='', subject='tessa', resolves='never')]
        assert active_states(rows, 's1', ORDER, entering=True)


class TestEstablishedBefore:
    def test_only_facts_from_earlier_scenes_in_reading_order(self):
        """F-123: a forced re-extraction offered the whole registry, so a
        scene's knowledge_in named facts the book reveals only later."""
        rows = [_row('later', type='knowledge', scene_id='s3'),
                _row('here', type='knowledge', scene_id='s2'),
                _row('first', type='knowledge', scene_id='s1'),
                _row('backstory', type='knowledge', scene_id=''),
                _row('state', scene_id='s1')]
        found = established_before(rows, 's3', ORDER, type_='knowledge')
        assert [r['id'] for r in found] == ['first', 'here']


class TestDraftingSlice:
    @staticmethod
    def _ids(by_subject):
        return {k: [r['id'] for r in v] for k, v in by_subject.items()}

    def test_fixed_facts_before_the_scene_and_states_entering_it(self):
        rows = [_row('eyes', scene_id='s1', subject='tessa', mutable='fixed'),
                _row('sister', scene_id='', subject='tessa', mutable='fixed'),
                _row('later-fixed', scene_id='s4', subject='tessa', mutable='fixed'),
                _row('ankle', scene_id='s2', subject='tessa', resolves='s4'),
                _row('healed', scene_id='s1', subject='tessa', resolves='s2')]
        found = drafting_slice(rows, 's3', ORDER, ['tessa'])
        assert self._ids(found.fixed) == {'tessa': ['sister', 'eyes']}
        assert self._ids(found.states) == {'tessa': ['ankle']}
        assert found.scene == []

    def test_the_scenes_own_facts_are_kept_apart_once(self):
        """A redraft must keep what the scene itself established; those
        facts are not also a state entering it."""
        rows = [_row('coat', scene_id='s2', subject='tessa'),
                _row('name', scene_id='s2', subject='tessa', mutable='fixed'),
                _row('elsewhere', scene_id='s2', subject='nobody-here')]
        found = drafting_slice(rows, 's2', ORDER, ['tessa'])
        assert [r['id'] for r in found.scene] == ['coat', 'name', 'elsewhere']
        assert found.fixed == {} and found.states == {}

    def test_only_binding_facts_about_the_subjects(self):
        rows = [_row('a', scene_id='s1', subject='tessa', status='rejected'),
                _row('b', scene_id='s1', subject='tessa', status='pending'),
                _row('c', scene_id='s1', subject='dorren'),
                _row('d', scene_id='s1', subject='tessa', status='superseded')]
        found = drafting_slice(rows, 's2', ORDER, ['tessa'])
        assert found.fixed == {} and found.states == {}

    def test_knowledge_about_someone_off_stage_goes_to_who_knows_it(self):
        rows = [_row('secret', type='knowledge', scene_id='s1', subject='kael',
                     known_by='dorren;tessa'),
                _row('own', type='knowledge', scene_id='s1', subject='tessa',
                     known_by='dorren')]
        found = drafting_slice(rows, 's2', ORDER, ['tessa', 'dorren'])
        assert self._ids(found.states) == {'tessa': ['secret', 'own']}

    def test_a_superseded_fixed_fact_is_left_out(self):
        rows = [_row('old-name', scene_id='s1', subject='tessa', mutable='fixed'),
                _row('new-name', scene_id='s2', subject='tessa', mutable='fixed',
                     supersedes='old-name')]
        assert self._ids(drafting_slice(rows, 's3', ORDER, ['tessa']).fixed) == \
            {'tessa': ['new-name']}
        # superseded in the scene being drafted: the old one is gone there too
        found = drafting_slice(rows, 's2', ORDER, ['tessa'])
        assert found.fixed == {} and [r['id'] for r in found.scene] == ['new-name']
        # not yet superseded before it
        assert self._ids(drafting_slice(rows, 's1', ORDER, ['tessa']).fixed) == {}

    def test_a_state_the_scene_supersedes_still_holds_entering_it(self):
        rows = [_row('in-study', scene_id='s1', subject='tessa'),
                _row('in-hall', scene_id='s2', subject='tessa', supersedes='in-study')]
        found = drafting_slice(rows, 's2', ORDER, ['tessa'])
        assert self._ids(found.states) == {'tessa': ['in-study']}
        assert [r['id'] for r in found.scene] == ['in-hall']
        assert self._ids(drafting_slice(rows, 's3', ORDER, ['tessa']).states) == \
            {'tessa': ['in-hall']}

    def test_a_fact_from_a_scene_that_is_not_in_the_book_is_unplaced(self):
        """A renamed later scene must not read as backstory (F-123: no
        reading ahead); only a blank scene_id is backstory."""
        rows = [_row('renamed', scene_id='old-s9', subject='tessa', mutable='fixed'),
                _row('renamed-state', scene_id='old-s9', subject='tessa'),
                _row('backstory', scene_id='', subject='tessa', mutable='fixed')]
        found = drafting_slice(rows, 's1', ORDER, ['tessa'])
        assert self._ids(found.fixed) == {'tessa': ['backstory']}
        assert found.states == {}
        assert [r['id'] for r in found.unplaced] == ['renamed', 'renamed-state']

    def test_a_fact_about_an_on_stage_subject_is_filed_under_it_not_its_knowers(self):
        rows = [_row('loc', type='world', scene_id='s1', subject='study'),
                _row('k', type='knowledge', scene_id='s1', subject='dorren',
                     known_by='tessa')]
        found = drafting_slice(rows, 's2', ORDER, ['tessa', 'dorren', 'study'])
        assert self._ids(found.states) == {'study': ['loc'], 'dorren': ['k']}

    def test_an_unknown_scene_raises(self):
        with pytest.raises(KeyError):
            drafting_slice([], 'nope', ORDER, ['tessa'])


class TestSceneOrder:
    def test_orders_by_seq(self, tmp_path):
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'scenes.csv').write_text(
            'id|seq|title\nb|10|B\na|2|A\nc|2.5|C\n')
        assert scene_order(str(tmp_path)) == {'a': 0, 'c': 1, 'b': 2}

    def test_a_scene_with_no_seq_raises(self, tmp_path):
        (tmp_path / 'reference').mkdir()
        (tmp_path / 'reference' / 'scenes.csv').write_text('id|seq\na|\n')
        with pytest.raises(ValueError, match='a has no numeric seq'):
            scene_order(str(tmp_path))


# ============================================================================
# Migration
# ============================================================================

def _ref(tmp_path, knowledge=None, physical=None,
         characters='id|name|aliases\ntessa-merrin|Tessa Merrin|Tessa\n',
         scenes='id|seq\ns1|1\ns2|2\n'):
    ref = tmp_path / 'reference'
    ref.mkdir(exist_ok=True)
    (ref / 'scenes.csv').write_text(scenes)
    (ref / 'characters.csv').write_text(characters)
    if knowledge is not None:
        (ref / 'knowledge.csv').write_text(knowledge)
    if physical is not None:
        (ref / 'physical-states.csv').write_text(physical)
    return str(ref)


K_HEADER = 'id|name|aliases|category|origin\n'
P_HEADER = 'id|character|description|category|acquired|resolves|action_gating\n'


LEGACY_FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'legacy-registries')


def _legacy_ref(project_dir):
    """The fixture project as it was before the ledger: its knowledge.csv and
    physical-states.csv back, its commitments.csv gone."""
    ref = os.path.join(project_dir, 'reference')
    os.remove(os.path.join(ref, 'commitments.csv'))
    for name in ledger.LEGACY_FILES:
        shutil.copy(os.path.join(LEGACY_FIXTURE, name), ref)
    return ref


class TestMigrate:
    def test_the_fixture_ledger_is_the_legacy_files_migrated(self, project_dir):
        """The fixture's commitments.csv was generated by the migration; it
        must stay what the migration makes of the old files."""
        expected = read_ledger(os.path.join(project_dir, 'reference', 'commitments.csv'))
        assert migrate_registries(_legacy_ref(project_dir)).rows == expected

    def test_the_fixture_project_migrates_and_round_trips(self, project_dir):
        ref = _legacy_ref(project_dir)
        result = migrate_registries(ref)
        assert result.errors == []
        assert round_trip_differences(ref, result) == []
        types = {r['type'] for r in result.rows}
        assert types == {'knowledge', 'physical'}
        for row in result.rows:
            assert (row['origin'], row['introduced_by'], row['status'],
                    row['mutable']) == ('migrated', 'migration', 'binding', 'state')

    def test_maps_the_knowledge_columns(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1|A fact|a;b|identity|s1\n')
        row = migrate_registries(ref).rows[0]
        assert {k: row[k] for k in ('id', 'type', 'statement', 'aliases',
                                    'category', 'scene_id', 'subject')} == {
            'id': 'k1', 'type': 'knowledge', 'statement': 'A fact',
            'aliases': 'a;b', 'category': 'identity', 'scene_id': 's1', 'subject': ''}

    def test_maps_the_physical_columns(self, tmp_path):
        ref = _ref(tmp_path, physical=P_HEADER
                   + 'ankle|Tessa|ankle sprained|injury|s1|s2|true\n')
        result = migrate_registries(ref)
        row = result.rows[0]
        assert {k: row[k] for k in ('subject', 'statement', 'category', 'scene_id',
                                    'resolves', 'action_gating')} == {
            'subject': 'tessa-merrin', 'statement': 'ankle sprained',
            'category': 'injury', 'scene_id': 's1', 'resolves': 's2',
            'action_gating': 'true'}
        assert any(q.kind == 'character-id' and "'Tessa'" in q.detail
                   for q in result.quirks)
        assert round_trip_differences(ref, result) == []

    def test_an_unresolved_character_is_reported_and_subject_left_blank(self, tmp_path):
        ref = _ref(tmp_path, physical=P_HEADER + 'cut|Garren|a cut|injury|s1|never|false\n')
        result = migrate_registries(ref)
        assert result.rows[0]['subject'] == ''
        # The name is kept, in aliases, and comes back out of the round trip
        assert result.rows[0]['aliases'] == 'Garren'
        assert [q.kind for q in result.quirks] == ['unresolved-character']
        assert "'Garren'" in str(result.quirks[0])
        assert 'the name kept in aliases' in str(result.quirks[0])
        assert round_trip_differences(ref, result) == []
        assert ledger.physical_view(result.rows)[0]['character'] == 'Garren'

    def test_backstory_and_blank_origins_leave_scene_id_blank(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1|Old|||backstory\nk2|New|||\n')
        result = migrate_registries(ref)
        assert [r['scene_id'] for r in result.rows] == ['', '']
        assert [(q.kind, q.row_id) for q in result.quirks] == [
            ('no-scene', 'k1'), ('no-scene', 'k2')]
        assert round_trip_differences(ref, result) == []  # both explained

    def test_an_origin_that_is_not_a_scene_is_kept_and_reported(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1|Fact|||burnside\n')
        result = migrate_registries(ref)
        assert result.rows[0]['scene_id'] == 'burnside'
        assert result.quirks[0].kind == 'unknown-scene'

    def test_an_exact_duplicate_is_dropped_and_reported(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1|Fact|||s1\nk1|Fact|||s1\n')
        result = migrate_registries(ref)
        assert len(result.rows) == 1 and result.errors == []
        assert result.quirks[0].kind == 'duplicate'

    def test_a_duplicate_id_that_differs_is_an_error(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1|Fact|||s1\nk1|Other|||s2\n')
        assert "id 'k1' is on two rows that differ" in migrate_registries(ref).errors[0]

    def test_an_id_in_both_files_is_an_error(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'x|Fact|||s1\n',
                   physical=P_HEADER + 'x|Tessa|y|injury|s1|never|true\n')
        assert any("'x' is in both" in e for e in migrate_registries(ref).errors)

    def test_a_fact_column_supplies_the_statement(self, tmp_path):
        """lantern-folk."""
        ref = _ref(tmp_path, knowledge='id|fact|name|aliases|category|origin\n'
                   'k-nora|Nora hears a sound.||||\n')
        result = migrate_registries(ref)
        assert result.rows[0]['statement'] == 'Nora hears a sound.'
        assert any('`fact`' in q.detail for q in result.quirks)
        assert round_trip_differences(ref, result) == []

    def test_a_fact_file_with_a_name_too_is_an_error(self, tmp_path):
        ref = _ref(tmp_path, knowledge='id|fact|name|aliases|category|origin\n'
                   'k1|A fact.|Another wording|||\n')
        assert 'both `fact` and `name`' in migrate_registries(ref).errors[0]

    def test_slug_names_take_the_statement_from_the_first_alias(self, tmp_path):
        """understory: `name` is a slug, and its header has leading spaces."""
        ref = _ref(tmp_path, knowledge='    id|name|aliases|category|origin\n'
                   'k01|zara-has-the-sight|Zara has the Sight;synesthesia|identity|s1\n')
        result = migrate_registries(ref)
        row = result.rows[0]
        assert row['id'] == 'k01' and row['statement'] == 'Zara has the Sight'
        assert row['aliases'] == 'zara-has-the-sight;Zara has the Sight;synesthesia'
        assert {q.kind for q in result.quirks} == {'header', 'slug-names'}
        assert round_trip_differences(ref, result) == []

    def test_a_lost_value_in_a_non_standard_file_is_named(self, tmp_path):
        ref = _ref(tmp_path, knowledge='id|fact|name|aliases|category|origin\n'
                   'k1|Nora hears a sound.||a hum|identity|s1\n')
        result = migrate_registries(ref)
        assert round_trip_differences(ref, result) == []
        result.rows[0]['aliases'] = ''
        result.rows[0]['category'] = ''
        diffs = '\n'.join(round_trip_differences(ref, result))
        assert "aliases 'a hum' came back as ''" in diffs
        assert "category 'identity' came back as ''" in diffs

    def test_a_column_with_no_place_is_an_error(self, tmp_path):
        ref = _ref(tmp_path, knowledge='id|name|aliases|category|origin|notes\n'
                   'k1|F|||s1|keep me\n')
        assert 'notes' in migrate_registries(ref).errors[0]

    def test_missing_files_migrate_to_nothing(self, tmp_path):
        result = migrate_registries(_ref(tmp_path))
        assert (result.rows, result.quirks, result.errors) == ([], [], [])


class TestStrictness:
    """The round trip must not pass when data was lost or changed."""

    def test_a_cell_quirk_accepts_only_its_own_column(self, tmp_path):
        ref = _ref(tmp_path, physical=P_HEADER + 'a|Tessa|x|injury|s1|never|true\n')
        result = migrate_registries(ref)
        assert round_trip_differences(ref, result) == []  # Tessa → tessa-merrin
        result.rows[0]['statement'] = 'changed'
        assert any('description' in d for d in round_trip_differences(ref, result))

    def test_surrounding_whitespace_is_a_reported_change(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1| Fact |a|identity|s1\n')
        result = migrate_registries(ref)
        assert result.rows[0]['statement'] == 'Fact'
        assert [q.kind for q in result.quirks] == ['whitespace']
        assert round_trip_differences(ref, result) == []

    def test_a_row_with_more_cells_than_the_header_is_an_error(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1|Fact|a|identity|s1|extra\n')
        assert '6 cells' in migrate_registries(ref).errors[0]

    def test_a_line_separator_inside_a_cell_is_not_a_row_break(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1|Fact\u2028more|a|identity|s1\n')
        result = migrate_registries(ref)
        assert len(result.rows) == 1 and result.errors == []
        assert round_trip_differences(ref, result) == []

    def test_a_duplicate_with_an_extra_cell_is_not_exact(self, tmp_path):
        ref = _ref(tmp_path, knowledge='id|name|aliases|category|origin\n'
                   'k1|Fact|||s1\nk1|Fact||x|s1\n')
        assert migrate_registries(ref).errors

    def test_a_gained_row_and_a_new_order_are_named(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1|A|||s1\nk2|B|||s1\n')
        result = migrate_registries(ref)
        result.rows.reverse()
        result.rows.append(dict(result.rows[0], id='k3'))
        diffs = '\n'.join(round_trip_differences(ref, result))
        assert 'k3: in the ledger but not in the old file' in diffs
        assert 'different order' in diffs

    def test_crlf_is_a_reported_quirk(self, tmp_path):
        ref = _ref(tmp_path, knowledge=(K_HEADER + 'k1|Fact|||s1\n').replace('\n', '\r\n'))
        result = migrate_registries(ref)
        assert [q.kind for q in result.quirks] == ['crlf']
        assert round_trip_differences(ref, result) == []


class TestRoundTrip:
    def test_an_unexplained_change_is_named(self, tmp_path):
        ref = _ref(tmp_path, knowledge=K_HEADER + 'k1|Fact|a|identity|s1\n')
        result = migrate_registries(ref)
        result.rows[0]['statement'] = 'Changed'
        diffs = round_trip_differences(ref, result)
        assert len(diffs) == 1 and 'k1' in diffs[0]

    def test_a_lost_row_is_named(self, tmp_path):
        ref = _ref(tmp_path, physical=P_HEADER + 'a|Tessa|x|injury|s1|never|true\n')
        result = migrate_registries(ref)
        result.rows.clear()
        assert any('missing from the ledger' in d for d in round_trip_differences(ref, result))

    def test_regenerated_text(self):
        rows = [_row('k1', type='knowledge', statement='F', aliases='a',
                     category='c', scene_id='s1'),
                _row('p1', subject='t', statement='S', category='injury',
                     scene_id='s1', resolves='never', action_gating='true')]
        assert regenerate_knowledge(rows) == K_HEADER + 'k1|F|a|c|s1\n'
        assert regenerate_physical(rows) == P_HEADER + 'p1|t|S|injury|s1|never|true\n'


def test_ledger_path(tmp_path):
    assert ledger.ledger_path(str(tmp_path)) == str(tmp_path / 'reference' / 'commitments.csv')


# ============================================================================
# Loading, typed views and view writes (the consumers' API)
# ============================================================================

def _fixture_rows(project_dir):
    return ledger.load(project_dir)


class TestLoad:
    def test_no_ledger_and_no_old_files_is_empty(self, tmp_path):
        (tmp_path / 'reference').mkdir()
        assert ledger.load(str(tmp_path)) == []

    def test_old_files_without_a_ledger_stop_with_the_migrate_hint(self, tmp_path):
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'physical-states.csv').write_text('id|character\n')
        with pytest.raises(ledger.NotMigratedError, match='run `storyforge migrate`'):
            ledger.load(str(tmp_path))

    def test_old_files_beside_a_ledger_stop_too(self, project_dir):
        shutil.copy(os.path.join(LEGACY_FIXTURE, 'knowledge.csv'),
                    os.path.join(project_dir, 'reference'))
        with pytest.raises(ledger.NotMigratedError,
                           match='still present beside reference/commitments.csv'):
            ledger.load(project_dir)

    def test_exit_if_not_migrated(self, project_dir, capsys):
        ledger.exit_if_not_migrated(project_dir)   # migrated: no stop
        _legacy_ref(project_dir)
        with pytest.raises(SystemExit) as exc:
            ledger.exit_if_not_migrated(project_dir)
        assert exc.value.code == 1
        assert 'ERROR: reference/knowledge.csv and reference/physical-states.csv must ' \
               'move into reference/commitments.csv' in capsys.readouterr().out


class TestViews:
    def test_views_have_the_old_files_shapes(self, project_dir):
        rows = _fixture_rows(project_dir)
        k = ledger.knowledge_view(rows)
        p = ledger.physical_view(rows)
        assert [list(r) for r in k] == [ledger.KNOWLEDGE_COLUMNS] * 5
        assert k[0] == {'id': 'map-anomaly-exists',
                        'name': 'A map anomaly exists in the pressure records',
                        'aliases': 'anomaly in records;maps show anomaly',
                        'category': '', 'origin': ''}
        assert p[2] == {'id': 'exhaustion-tessa', 'character': 'tessa-merrin',
                        'description': 'physically exhausted from 4-hour eastern trek',
                        'category': 'fatigue', 'acquired': 'act1-sc02',
                        'resolves': 'act2-sc03', 'action_gating': 'false'}

    def test_alias_map(self, project_dir):
        rows = _fixture_rows(project_dir)
        k = ledger.alias_map(ledger.knowledge_view(rows))
        assert k['missing village'] == 'village-vanished'
        assert k['a village has vanished from the pressure maps'] == 'village-vanished'
        assert ledger.alias_map(ledger.physical_view(rows)) == {
            r['id']: r['id'] for r in ledger.physical_view(rows)}


class TestReplaceView:
    def _rows(self):
        return [_row('k1', type='knowledge', statement='K one', quote='q1', known_by='a'),
                _row('p1', scene_id='s1', subject='tessa'),
                _row('k2', type='knowledge', statement='K two'),
                _row('t1', type='timeline', statement='Day 3')]

    def test_other_types_are_kept_in_place(self):
        rows = self._rows()
        out = ledger.replace_view(rows, 'knowledge', [], origin='prose',
                                  introduced_by='extract')
        assert out == [rows[1], rows[3]]

    def test_an_updated_row_keeps_the_columns_the_view_does_not_carry(self):
        rows = self._rows()
        view = ledger.knowledge_view(rows)
        view[0]['name'] = 'K one, reworded'
        out = ledger.replace_view(rows, 'knowledge', view, origin='prose',
                                  introduced_by='extract')
        assert out[0] == {**rows[0], 'statement': 'K one, reworded'}
        assert out[1:] == rows[1:]

    def test_a_new_row_follows_its_types_last_row(self):
        rows = self._rows()
        view = ledger.knowledge_view(rows) + [
            {'id': 'k3', 'name': 'K three', 'origin': 'backstory'}]
        out = ledger.replace_view(rows, 'knowledge', view, origin='prose',
                                  introduced_by='extract')
        assert [r['id'] for r in out] == ['k1', 'p1', 'k2', 'k3', 't1']
        new = out[3]
        assert (new['type'], new['statement'], new['scene_id'], new['origin'],
                new['introduced_by'], new['status'], new['mutable']) == (
            'knowledge', 'K three', '', 'prose', 'extract', 'binding', 'state')

    def test_a_new_id_of_another_type_raises(self):
        with pytest.raises(ValueError, match='t1: already in commitments.csv'):
            ledger.replace_view(self._rows(), 'physical', [{'id': 't1'}],
                                origin='prose', introduced_by='extract')

    def test_write_view_writes_only_on_change(self, project_dir):
        ref = os.path.join(project_dir, 'reference')
        path = os.path.join(ref, 'commitments.csv')
        os.utime(path, (0, 0))
        ledger.write_view(ref, 'physical', ledger.read_view(ref, 'physical'),
                          origin='prose', introduced_by='extract')
        assert os.path.getmtime(path) == 0

    def test_write_view_round_trips_the_fixture(self, project_dir):
        ref = os.path.join(project_dir, 'reference')
        before = ledger.load_from(ref)
        for type_ in ('knowledge', 'physical'):
            ledger.write_view(ref, type_, ledger.read_view(ref, type_),
                              origin='prose', introduced_by='extract')
        assert ledger.load_from(ref) == before


class TestMigrateFiles:
    def test_skip_without_old_files(self, project_dir):
        assert ledger.migrate_files(os.path.join(project_dir, 'reference')).status == 'skip'

    def test_done_writes_the_ledger_and_removes_the_old_files(self, project_dir):
        expected = ledger.load(project_dir)
        ref = _legacy_ref(project_dir)
        result = ledger.migrate_files(ref)
        assert result.status == 'done' and result.removed == list(ledger.LEGACY_FILES)
        assert ledger.load_from(ref) == expected

    def test_errors_stop_and_change_nothing(self, project_dir):
        ref = _legacy_ref(project_dir)
        with open(os.path.join(ref, 'physical-states.csv'), 'a') as f:
            f.write('map-anomaly-exists|Kael Maren|x|injury|act1-sc01|never|false\n')
        result = ledger.migrate_files(ref)
        assert result.status == 'stopped'
        assert any('in both' in p for p in result.problems)
        assert not os.path.isfile(os.path.join(ref, 'commitments.csv'))
        assert ledger.legacy_files(ref) == list(ledger.LEGACY_FILES)

    def test_dry_run_changes_nothing(self, project_dir):
        ref = _legacy_ref(project_dir)
        result = ledger.migrate_files(ref, dry_run=True)
        assert result.status == 'dry-run' and len(result.rows) == 9
        assert not os.path.isfile(os.path.join(ref, 'commitments.csv'))
        assert ledger.legacy_files(ref) == list(ledger.LEGACY_FILES)


# ============================================================================
# A write changes only what the writer changed
# ============================================================================

def _ledger_text(project_dir):
    with open(os.path.join(project_dir, 'reference', 'commitments.csv'), newline='') as f:
        return f.read()


def _odd_ledger(project_dir):
    """The fixture ledger with the things a careless write-back would change:
    doubled spaces in a statement and a quote, a `backstory` scene_id, a
    timeline fact, and an unresolved character kept in aliases."""
    path = os.path.join(project_dir, 'reference', 'commitments.csv')
    rows = read_ledger(path)
    rows[0]['statement'] = 'A map  anomaly exists '
    rows[0]['quote'] = '"It was  there," she said.'
    rows[1]['scene_id'] = 'backstory'
    rows.append({**rows[5], 'id': 'garren-cut', 'subject': '', 'aliases': 'Garren'})
    rows.append({**rows[0], 'id': 'day-three', 'type': 'timeline', 'statement': 'Day  3'})
    write_ledger(path, rows)
    return _ledger_text(project_dir)


class TestUntouchedRowsAreByteIdentical:
    def test_read_and_write_back(self, project_dir):
        before = _odd_ledger(project_dir)
        ledger.save(project_dir, ledger.load(project_dir), command='test')
        assert _ledger_text(project_dir) == before

    @pytest.mark.parametrize('type_', ['knowledge', 'physical'])
    def test_an_unchanged_view_written_back(self, project_dir, type_):
        before = _odd_ledger(project_dir)
        ref = os.path.join(project_dir, 'reference')
        ledger.write_view(ref, type_, ledger.read_view(ref, type_), origin='prose',
                          introduced_by='extract')
        assert _ledger_text(project_dir) == before

    def test_a_changed_cell_changes_only_its_line(self, project_dir):
        before = _odd_ledger(project_dir).splitlines()
        ref = os.path.join(project_dir, 'reference')
        view = ledger.read_view(ref, 'physical')
        view[0]['resolves'] = 'act2-sc01'
        ledger.write_view(ref, 'physical', view, origin='prose', introduced_by='extract')
        after = _ledger_text(project_dir).splitlines()
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        assert len(after) == len(before) and changed == [6]
        assert after[6] == before[6].replace('|never|true', '|act2-sc01|true')

    def test_extract_hone_and_prune_writes_keep_other_rows(self, project_dir):
        from storyforge.cmd_extract import _prune_registries, _record_physical_states
        from storyforge.hone import read_registry, write_registry
        before = _odd_ledger(project_dir).splitlines()
        ref = os.path.join(project_dir, 'reference')
        _record_physical_states(ref, 'act2-sc01', [{'id': 'new-bruise',
                                'character': 'tessa-merrin', 'description': 'a bruise'}],
                                [], {})
        write_registry(ref, 'knowledge', read_registry(ref, 'knowledge'))
        write_registry(ref, 'physical-states', read_registry(ref, 'physical-states'))
        _prune_registries(ref, created_facts=set(), created_states={'new-bruise'})
        after = _ledger_text(project_dir).splitlines()
        # Every line nothing changed is still there as it was
        pruned = {'subsidence-not-natural', 'sprained-ankle-tessa',
                  'scar-left-hand-kael', 'garren-cut'}
        assert [l for l in before if l.split('|')[0] not in pruned] == \
            [l for l in after if not l.startswith('new-bruise|')]


    def test_a_padded_alias_on_a_blank_subject_stays_a_blank_subject(self, project_dir):
        """A writer that strips the view's `character` (shown from the kept
        alias) used to set subject to the name."""
        ref = os.path.join(project_dir, 'reference')
        rows = ledger.load(project_dir)
        rows.append(dict(rows[-1], id='padded-cut', subject='', aliases=' Garren ',
                         type='physical'))
        ledger.save(project_dir, rows, command='test')
        view = ledger.read_view(ref, 'physical')
        for row in view:
            row['character'] = row['character'].strip()
        ledger.write_view(ref, 'physical', view, origin='prose', introduced_by='hone')
        row = next(r for r in ledger.load(project_dir) if r['id'] == 'padded-cut')
        assert row['subject'] == '' and row['aliases'] == ' Garren '


class TestFileProblems:
    def _write(self, project_dir, text):
        path = os.path.join(project_dir, 'reference', 'commitments.csv')
        with open(path, 'w') as f:
            f.write(text)
        return path

    def _row(self, rid):
        return '|'.join([rid, '', 'knowledge', '', 'A fact', '', 'author', 'binding',
                         'state'] + [''] * 9)

    @pytest.mark.parametrize('body, needle', [
        ('{h}|notes\n', 'columns the ledger has no place for: notes'),
        ('{h}\n{a}\n{a}\n', "line 3: id 'a' is also on line 2"),
        ('{h}\n{blank}\n', 'line 2: no id'),
        ('{h}\n{a}|extra\n', 'line 2: 19 cells, the header has 18'),
        ('{h}\n{padded}\n', "line 2: id 'a ' has surrounding whitespace"),
    ])
    def test_load_refuses_rather_than_fixing(self, project_dir, body, needle):
        path = self._write(project_dir, body.format(h='|'.join(COLUMNS), a=self._row('a'),
                                                    blank=self._row(''),
                                                    padded=self._row('a ')))
        before = open(path).read()
        assert any(needle in p for p in ledger.file_problems(path))
        with pytest.raises(ledger.LedgerError, match=needle.replace('(', r'\(')):
            ledger.load(project_dir)
        with pytest.raises(SystemExit):
            ledger.exit_if_not_migrated(project_dir)
        assert open(path).read() == before

    def test_the_fixture_has_none(self, project_dir):
        assert ledger.file_problems(ledger.ledger_path(project_dir)) == []


class TestCommitmentsAndRegistry:
    """Gate rows are commitments by `introduced_by` (the design note,
    docs/plans/2026-10-30-gate-ledger-design.md)."""

    @pytest.mark.parametrize('writer', ledger.COMMITMENT_WRITERS)
    def test_commitment_writers_stay_out_of_the_views(self, writer):
        rows = [_row('k1', type='knowledge', introduced_by='hone'),
                _row('k2', type='knowledge', introduced_by=writer)]
        assert [r['id'] for r in ledger.knowledge_view(rows)] == ['k1']
        out = ledger.replace_view(rows, 'knowledge', [], origin='plan', introduced_by='hone')
        assert out == [rows[1]]

    def test_a_blank_introduced_by_is_a_registry_fact(self):
        assert not ledger.is_commitment(_row('k1', introduced_by=''))
        assert ledger.is_commitment(_row('k1', introduced_by=' draft '))


class TestFillQuote:
    def test_fills_a_blank_quote(self):
        rows = [_row('p1', introduced_by='migration')]
        assert ledger.fill_quote(rows, 'p1', 'He  limped\nhome.') is True
        assert rows[0]['quote'] == 'He limped home.'

    def test_never_replaces_a_quote(self):
        rows = [_row('p1', introduced_by='hone', quote='old')]
        assert ledger.fill_quote(rows, 'p1', 'new') is False
        assert rows[0]['quote'] == 'old'

    @pytest.mark.parametrize('rid, quote, needle', [
        ('nope', 'q', 'not in commitments.csv'),
        ('c1', 'q', 'a commitment'),
        ('p1', '  ', 'no quote'),
    ])
    def test_refuses(self, rid, quote, needle):
        rows = [_row('p1', introduced_by='hone'), _row('c1', introduced_by='draft')]
        with pytest.raises(ValueError, match=needle):
            ledger.fill_quote(rows, rid, quote)

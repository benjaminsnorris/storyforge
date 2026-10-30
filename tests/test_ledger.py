"""Tests for storyforge.ledger: commitments.csv, derived state, and the
migration from knowledge.csv and physical-states.csv."""

import os

import pytest

from storyforge import ledger
from storyforge.ledger import (
    COLUMNS, active_states, established_before, migrate_registries,
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


class TestMigrate:
    def test_the_fixture_project_migrates_and_round_trips(self, project_dir):
        ref = os.path.join(project_dir, 'reference')
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
        assert [q.kind for q in result.quirks] == ['unresolved-character']
        assert "'Garren'" in str(result.quirks[0])

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

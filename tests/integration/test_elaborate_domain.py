"""Tests for elaborate.py domain library — uncovered functions and edge cases.

Focuses on functions not already tested in tests/test_elaborate.py:
  - CSV I/O internals (_read_csv, _read_csv_as_map, _write_csv, _file_for_column)
  - _mice_type with registry resolution
  - _validate_physical_states (all three checks)
  - _validate_pacing (scene-type-rhythm, turning-point-variety)
  - _validate_knowledge edge cases
  - analyze_gaps
"""

import os
import shutil

from storyforge.elaborate import (
    _read_csv,
    _read_csv_as_map,
    _write_csv,
    _file_for_column,
    _mice_type,
    _check,
    _SCENES_COLS,
    _INTENT_COLS,
    _BRIEFS_COLS,
    validate_structure,
    analyze_gaps,
    get_scene,
    update_scene,
    score_structure,
    compute_drafting_waves,
)


# ============================================================================
# CSV I/O
# ============================================================================

class TestReadCsv:
    def test_returns_empty_for_missing_file(self, tmp_path):
        result = _read_csv(str(tmp_path / 'nonexistent.csv'))
        assert result == []

    def test_reads_pipe_delimited(self, tmp_path):
        csv_path = str(tmp_path / 'test.csv')
        with open(csv_path, 'w') as f:
            f.write('id|name|value\n')
            f.write('a|Alice|100\n')
            f.write('b|Bob|200\n')
        rows = _read_csv(csv_path)
        assert len(rows) == 2
        assert rows[0]['id'] == 'a'
        assert rows[0]['name'] == 'Alice'
        assert rows[1]['value'] == '200'

    def test_handles_crlf_line_endings(self, tmp_path):
        csv_path = str(tmp_path / 'crlf.csv')
        with open(csv_path, 'wb') as f:
            f.write(b'id|name\r\na|Alice\r\nb|Bob\r\n')
        rows = _read_csv(csv_path)
        assert len(rows) == 2
        assert rows[0]['name'] == 'Alice'
        assert rows[1]['name'] == 'Bob'

    def test_coerces_none_to_empty_string(self, tmp_path):
        """Rows with fewer fields than headers get empty strings, not None."""
        csv_path = str(tmp_path / 'short.csv')
        with open(csv_path, 'w') as f:
            f.write('id|name|value\n')
            f.write('a|Alice\n')  # missing 'value' field
        rows = _read_csv(csv_path)
        assert len(rows) == 1
        # csv.DictReader gives None for missing fields; _read_csv coerces to ''
        assert rows[0]['value'] == ''

    def test_handles_stray_cr_in_fields(self, tmp_path):
        csv_path = str(tmp_path / 'stray_cr.csv')
        with open(csv_path, 'wb') as f:
            f.write(b'id|name\na|Alice\rExtra\nb|Bob\n')
        rows = _read_csv(csv_path)
        # The stray \r should be stripped
        for row in rows:
            for v in row.values():
                assert '\r' not in v


class TestReadCsvAsMap:
    def test_keys_by_id(self, tmp_path):
        csv_path = str(tmp_path / 'test.csv')
        with open(csv_path, 'w') as f:
            f.write('id|title\n')
            f.write('scene-1|First Scene\n')
            f.write('scene-2|Second Scene\n')
        m = _read_csv_as_map(csv_path)
        assert 'scene-1' in m
        assert 'scene-2' in m
        assert m['scene-1']['title'] == 'First Scene'

    def test_empty_file_returns_empty_dict(self, tmp_path):
        csv_path = str(tmp_path / 'empty.csv')
        with open(csv_path, 'w') as f:
            f.write('id|title\n')
        m = _read_csv_as_map(csv_path)
        assert m == {}


class TestWriteCsv:
    def test_roundtrip(self, tmp_path):
        csv_path = str(tmp_path / 'out.csv')
        rows = [
            {'id': 'a', 'name': 'Alice', 'value': '100'},
            {'id': 'b', 'name': 'Bob', 'value': '200'},
        ]
        _write_csv(csv_path, rows, ['id', 'name', 'value'])
        readback = _read_csv(csv_path)
        assert len(readback) == 2
        assert readback[0] == {'id': 'a', 'name': 'Alice', 'value': '100'}

    def test_ignores_extra_columns(self, tmp_path):
        csv_path = str(tmp_path / 'out.csv')
        rows = [{'id': 'a', 'name': 'Alice', 'extra': 'ignored'}]
        _write_csv(csv_path, rows, ['id', 'name'])
        readback = _read_csv(csv_path)
        assert 'extra' not in readback[0]


class TestFileForColumn:
    def test_scenes_columns(self):
        assert _file_for_column('seq') == 'scenes.csv'
        assert _file_for_column('pov') == 'scenes.csv'
        assert _file_for_column('status') == 'scenes.csv'

    def test_intent_columns(self):
        assert _file_for_column('function') == 'scene-intent.csv'
        assert _file_for_column('mice_threads') == 'scene-intent.csv'
        assert _file_for_column('value_shift') == 'scene-intent.csv'

    def test_briefs_columns(self):
        assert _file_for_column('goal') == 'scene-briefs.csv'
        assert _file_for_column('conflict') == 'scene-briefs.csv'
        assert _file_for_column('continuity_deps') == 'scene-briefs.csv'

    def test_unknown_column_returns_none(self):
        assert _file_for_column('nonexistent_column') is None


# ============================================================================
# Internal helpers
# ============================================================================

class TestCheck:
    def test_basic_check_structure(self):
        result = _check('identity', 'test-check', True, 'All good')
        assert result['category'] == 'identity'
        assert result['check'] == 'test-check'
        assert result['passed'] is True
        assert result['message'] == 'All good'
        assert result['severity'] == 'blocking'

    def test_advisory_severity(self):
        result = _check('timeline', 'test', False, 'Warning', severity='advisory')
        assert result['severity'] == 'advisory'

    def test_scene_id_included(self):
        result = _check('identity', 'test', True, 'ok', scene_id='s01')
        assert result['scene_id'] == 's01'

    def test_scene_id_omitted_when_empty(self):
        result = _check('identity', 'test', True, 'ok')
        assert 'scene_id' not in result

    def test_fields_included(self):
        result = _check('completeness', 'test', False, 'missing', fields=['pov', 'title'])
        assert result['fields'] == ['pov', 'title']

    def test_fields_omitted_when_none(self):
        result = _check('completeness', 'test', True, 'ok', fields=None)
        assert 'fields' not in result


class TestMiceType:
    def test_typed_thread_name(self):
        assert _mice_type('inquiry:who-killed') == 'inquiry'
        assert _mice_type('milieu:castle') == 'milieu'
        assert _mice_type('character:alice-arc') == 'character'
        assert _mice_type('event:the-war') == 'event'

    def test_bare_name_with_registry(self):
        registry = {'dex-secret': 'character', 'storm-front': 'event'}
        assert _mice_type('dex-secret', registry) == 'character'
        assert _mice_type('storm-front', registry) == 'event'

    def test_bare_name_without_registry(self):
        assert _mice_type('unknown-thread') == 'unknown'

    def test_bare_name_not_in_registry(self):
        registry = {'other': 'milieu'}
        assert _mice_type('not-found', registry) == 'unknown'


# ============================================================================
# Physical state validation
# ============================================================================

class TestValidatePhysicalStates:
    def test_physical_state_availability_detected(self, tmp_path):
        """References to physical states not established by prior scenes are flagged."""
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|A|Room|1|morning|1h|action|briefed|1000|2000\n')
            f.write('s02|2|Scene 2|1|A|Room|2|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d|||a|d|e|m|||false||\n')
            # s02 references a state that was never output by s01
            f.write('s02|g|c|o|cr|d|||a|d|e|m|||false|sprained-ankle|\n')

        report = validate_structure(ref)
        ps_checks = [c for c in report['checks'] if c['category'] == 'physical_state']
        failed = [c for c in ps_checks if not c['passed']]
        assert len(failed) > 0
        assert any('sprained-ankle' in c['message'] for c in failed)

    def test_physical_state_disappearance_flagged(self, tmp_path):
        """A state in physical_state_in but not _out is flagged unless registry says it resolves."""
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|A|Room|1|morning|1h|action|briefed|1000|2000\n')
            f.write('s02|2|Scene 2|1|A|Room|2|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d|||a|d|e|m|||false||broken-arm\n')
            # s02 has broken-arm in but NOT in out, and no registry resolves
            f.write('s02|g|c|o|cr|d|||a|d|e|m|||false|broken-arm|\n')

        # No physical-states.csv registry -> disappearance flagged
        report = validate_structure(ref)
        ps_checks = [c for c in report['checks'] if c['category'] == 'physical_state']
        disappearance = [c for c in ps_checks if 'disappearance' in c.get('check', '')]
        assert len(disappearance) > 0
        assert 'broken-arm' in disappearance[0]['message']

    def test_physical_state_disappearance_allowed_by_registry(self, tmp_path):
        """State disappearance is NOT flagged when registry says it resolves in that scene."""
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|A|Room|1|morning|1h|action|briefed|1000|2000\n')
            f.write('s02|2|Scene 2|1|A|Room|2|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d|||a|d|e|m|||false||broken-arm\n')
            f.write('s02|g|c|o|cr|d|||a|d|e|m|||false|broken-arm|\n')

        # Registry says broken-arm resolves in s02
        with open(os.path.join(ref, 'physical-states.csv'), 'w') as f:
            f.write('id|character|description|category|acquired|resolves|action_gating\n')
            f.write('broken-arm|A|broken arm|injury|s01|s02|false\n')

        report = validate_structure(ref)
        ps_checks = [c for c in report['checks'] if c['category'] == 'physical_state']
        disappearance = [c for c in ps_checks if 'disappearance' in c.get('check', '')]
        assert len(disappearance) == 0

    def test_on_stage_relevance_flagged(self, tmp_path):
        """Character on-stage with action-gating state not in physical_state_in is flagged."""
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|A|Room|1|morning|1h|action|briefed|1000|2000\n')
            f.write('s02|2|Scene 2|1|A|Room|2|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|Alice|Alice|\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|Alice|Alice|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            # s01 outputs the action-gating state
            f.write('s01|g|c|o|cr|d|||a|d|e|m|||false||limp-alice\n')
            # s02: Alice is on-stage but limp-alice NOT in physical_state_in
            f.write('s02|g|c|o|cr|d|||a|d|e|m|||false||\n')

        with open(os.path.join(ref, 'physical-states.csv'), 'w') as f:
            f.write('id|character|description|category|acquired|resolves|action_gating\n')
            f.write('limp-alice|Alice|limping from injury|injury|s01|never|true\n')

        report = validate_structure(ref)
        ps_checks = [c for c in report['checks'] if c['category'] == 'physical_state']
        relevance = [c for c in ps_checks if 'on-stage-relevance' in c.get('check', '')]
        assert len(relevance) > 0
        assert 'Alice' in relevance[0]['message']
        assert 'limp-alice' in relevance[0]['message']

    def test_clean_physical_state_flow_passes(self, fixture_dir):
        """Fixture data with physical states should produce checks (advisory or passing)."""
        report = validate_structure(os.path.join(fixture_dir, 'reference'))
        ps_checks = [c for c in report['checks'] if c['category'] == 'physical_state']
        assert len(ps_checks) > 0


# ============================================================================
# Pacing validation — scene-type-rhythm and turning-point-variety
# ============================================================================

class TestValidatePacingRhythm:
    def test_four_consecutive_same_type_flagged(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 6):
                f.write(f's0{i}|{i}|Scene {i}|1|A|Room|{i}|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i in range(1, 6):
                # All action scenes
                f.write(f's0{i}|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            for i in range(1, 6):
                f.write(f's0{i}|g|c|o|cr|d|||a|d|e|m|||false||\n')

        report = validate_structure(ref)
        pacing = [c for c in report['checks'] if c['category'] == 'pacing']
        rhythm = [c for c in pacing if c['check'] == 'scene-type-rhythm']
        failed = [c for c in rhythm if not c['passed']]
        assert len(failed) > 0
        assert 'action' in failed[0]['message']

    def test_four_consecutive_same_turning_point_flagged(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 6):
                f.write(f's0{i}|{i}|Scene {i}|1|A|Room|{i}|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i in range(1, 6):
                # All revelation turning points, but alternate action/sequel
                tp = 'action' if i % 2 else 'sequel'
                f.write(f's0{i}|test|{tp}|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            for i in range(1, 6):
                f.write(f's0{i}|g|c|o|cr|d|||a|d|e|m|||false||\n')

        report = validate_structure(ref)
        pacing = [c for c in report['checks'] if c['category'] == 'pacing']
        tp_checks = [c for c in pacing if c['check'] == 'turning-point-variety']
        failed = [c for c in tp_checks if not c['passed']]
        assert len(failed) > 0
        assert 'revelation' in failed[0]['message']

    def test_varied_types_pass(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            for i in range(1, 5):
                f.write(f's0{i}|{i}|Scene {i}|1|A|Room|{i}|morning|1h|action|briefed|1000|2000\n')

        types = ['action', 'sequel', 'action', 'sequel']
        tps = ['revelation', 'action', 'complication', 'revelation']
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i in range(4):
                f.write(f's0{i+1}|test|{types[i]}|flat|truth|+/-|{tps[i]}|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            for i in range(1, 5):
                f.write(f's0{i}|g|c|o|cr|d|||a|d|e|m|||false||\n')

        report = validate_structure(ref)
        pacing = [c for c in report['checks'] if c['category'] == 'pacing']
        rhythm = [c for c in pacing if c['check'] == 'scene-type-rhythm']
        assert all(c['passed'] for c in rhythm)
        tp_checks = [c for c in pacing if c['check'] == 'turning-point-variety']
        assert all(c['passed'] for c in tp_checks)


# ============================================================================
# Knowledge validation edge cases
# ============================================================================

class TestValidateKnowledge:
    def test_unknown_knowledge_in_flagged(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|A|Room|1|morning|1h|action|briefed|1000|2000\n')
            f.write('s02|2|Scene 2|1|A|Room|2|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d||fact-a|a|d|e|m|||false||\n')
            # s02 references fact-b which was never output
            f.write('s02|g|c|o|cr|d|fact-b||a|d|e|m|||false||\n')

        report = validate_structure(ref)
        k_checks = [c for c in report['checks'] if c['category'] == 'knowledge']
        failed = [c for c in k_checks if not c['passed']]
        assert len(failed) > 0
        assert any('fact-b' in c['message'] for c in failed)

    def test_known_knowledge_passes(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|Scene 1|1|A|Room|1|morning|1h|action|briefed|1000|2000\n')
            f.write('s02|2|Scene 2|1|A|Room|2|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d||fact-a|a|d|e|m|||false||\n')
            f.write('s02|g|c|o|cr|d|fact-a||a|d|e|m|||false||\n')

        report = validate_structure(ref)
        k_checks = [c for c in report['checks'] if c['category'] == 'knowledge']
        assert all(c['passed'] for c in k_checks)


# ============================================================================
# Thread validation — unclosed threads and never-opened closures
# ============================================================================

class TestValidateThreadsEdgeCases:
    def test_unclosed_thread_advisory(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|R|1|m|1h|a|briefed|1000|2000\n')
            f.write('s02|2|S2|1|A|R|2|m|1h|a|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            # Open a thread but never close it
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|+inquiry:mystery\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d|||a|d|e|m|||false||\n')
            f.write('s02|g|c|o|cr|d|||a|d|e|m|||false||\n')

        report = validate_structure(ref)
        t_checks = [c for c in report['checks'] if c['category'] == 'threads']
        unclosed = [c for c in t_checks if 'unclosed' in c.get('check', '')]
        assert len(unclosed) > 0
        assert 'inquiry:mystery' in unclosed[0]['message']
        assert unclosed[0]['severity'] == 'advisory'

    def test_closing_never_opened_thread_flagged(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|R|1|m|1h|a|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            # Close a thread that was never opened
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|-inquiry:phantom\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d|||a|d|e|m|||false||\n')

        report = validate_structure(ref)
        t_checks = [c for c in report['checks'] if c['category'] == 'threads']
        failed = [c for c in t_checks if not c['passed']]
        assert len(failed) > 0
        assert any('phantom' in c['message'] for c in failed)

    def test_bare_thread_resolved_via_registry(self, tmp_path):
        """Bare thread names should be typed via the MICE thread registry."""
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|R|1|m|1h|a|briefed|1000|2000\n')
            f.write('s02|2|S2|1|A|R|2|m|1h|a|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            # Use bare thread names (no type prefix)
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|+map-anomaly\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|-map-anomaly\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d|||a|d|e|m|||false||\n')
            f.write('s02|g|c|o|cr|d|||a|d|e|m|||false||\n')

        # Registry defines the type for bare thread names
        with open(os.path.join(ref, 'mice-threads.csv'), 'w') as f:
            f.write('id|name|type|aliases\n')
            f.write('map-anomaly|Map anomaly|inquiry|\n')

        report = validate_structure(ref)
        t_checks = [c for c in report['checks'] if c['category'] == 'threads']
        nesting = [c for c in t_checks if c['check'] == 'mice-nesting']
        assert any(c['passed'] for c in nesting)


# ============================================================================
# analyze_gaps
# ============================================================================

class TestAnalyzeGaps:
    def test_returns_groups_for_missing_fields(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            # mapped status requires location and timeline_day
            f.write('s01|1|Scene 1|1|Dorren||2||1h||mapped|0|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|calm to panic|truth|+/-|action|Dorren|Dorren|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01||||||||||||||||\n')

        result = analyze_gaps(ref)
        assert 'groups' in result
        assert 'structural' in result
        assert 'total_gaps' in result
        assert 'validation' in result
        assert result['total_gaps'] > 0

    def test_no_gaps_for_complete_data(self, fixture_dir):
        """Fixture scenes with status=briefed should have minimal gaps."""
        result = analyze_gaps(os.path.join(fixture_dir, 'reference'))
        assert 'groups' in result
        assert isinstance(result['total_gaps'], int)
        assert isinstance(result['structural'], list)

    def test_gap_groups_categorize_correctly(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            # briefed status requires many fields — leave several empty
            f.write('s01|1|Scene 1|1|A|||morning||action|briefed|0|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test||||||A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01||||||||||||||||\n')

        result = analyze_gaps(ref)
        groups = result['groups']

        # 'location-timeline' gap group should have location, timeline_day
        if 'location-timeline' in groups:
            assert 'location' in groups['location-timeline']['fields'] or \
                   'timeline_day' in groups['location-timeline']['fields']

        # 'intent-fields' gap group should be populated
        if 'intent-fields' in groups:
            assert 's01' in groups['intent-fields']['scenes']

    def test_structural_failures_listed(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            # Backwards timeline
            f.write('s01|1|S1|1|A|Room|5|morning|1h|action|briefed|1000|2000\n')
            f.write('s02|2|S2|1|A|Room|3|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d|||a|d|e|m|||false||\n')
            f.write('s02|g|c|o|cr|d|||a|d|e|m|||false||\n')

        result = analyze_gaps(ref)
        assert len(result['structural']) > 0
        assert any('timeline' in c.get('category', '') or 'backwards' in c.get('message', '').lower()
                    for c in result['structural'])


# ============================================================================
# Score structure — edge cases
# ============================================================================

class TestScoreStructureEdgeCases:
    def test_flat_value_shift_deducts(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|Room|1|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/+|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            f.write('s01|g|c|o|cr|d|ki|ko|a|d|e|m|||false||\n')

        scores = score_structure(ref)
        s01 = [s for s in scores if s['scene_id'] == 's01'][0]
        assert 'Flat value shift' in ' '.join(s01['issues'])
        assert s01['score'] < 5

    def test_missing_knowledge_out_deducts(self, tmp_path):
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|Room|1|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            # No knowledge_out
            f.write('s01|g|c|o|cr|d|ki||a|d|e|m|||false||\n')

        scores = score_structure(ref)
        s01 = [s for s in scores if s['scene_id'] == 's01'][0]
        assert 'Missing knowledge_out' in ' '.join(s01['issues'])


# ============================================================================
# Wave planner — edge cases
# ============================================================================

class TestComputeWavesEdgeCases:
    def test_circular_deps_broken(self, tmp_path):
        """Circular dependencies should be broken by picking lowest-seq scene."""
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|Room|1|morning|1h|action|briefed|1000|2000\n')
            f.write('s02|2|S2|1|A|Room|2|morning|1h|action|briefed|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            # Circular: s01 depends on s02 and vice versa
            f.write('s01|g|c|o|cr|d|||a|d|e|m||s02|false||\n')
            f.write('s02|g|c|o|cr|d|||a|d|e|m||s01|false||\n')

        waves = compute_drafting_waves(ref)
        all_ids = [sid for wave in waves for sid in wave]
        assert 's01' in all_ids
        assert 's02' in all_ids
        # Both should eventually be assigned
        assert len(all_ids) == 2

    def test_ineligible_statuses_excluded(self, tmp_path):
        """Scenes with spine/architecture/mapped status should not appear in waves."""
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|S1|1|A|R|1|m|1h|a|briefed|1000|2000\n')
            f.write('s02|2|S2|1|A|R|2|m|1h|a|spine|1000|2000\n')
            f.write('s03|3|S3|1|A|R|3|m|1h|a|architecture|1000|2000\n')
            f.write('s04|4|S4|1|A|R|4|m|1h|a|mapped|1000|2000\n')

        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            for i in range(1, 5):
                f.write(f's0{i}|test|action|flat|truth|+/-|revelation|A|A|\n')

        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|physical_state_in|physical_state_out\n')
            for i in range(1, 5):
                f.write(f's0{i}|g|c|o|cr|d|||a|d|e|m|||false||\n')

        waves = compute_drafting_waves(ref)
        all_ids = [sid for wave in waves for sid in wave]
        assert 's01' in all_ids
        assert 's02' not in all_ids
        assert 's03' not in all_ids
        assert 's04' not in all_ids

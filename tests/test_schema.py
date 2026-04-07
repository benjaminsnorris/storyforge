"""Tests for CSV schema validation (migrated from test-schema.sh)."""

import json
import os
import shutil
import tempfile


class TestEnumValidation:
    def test_valid_values(self):
        from storyforge.schema import (
            _check_enum, VALID_TYPES, VALID_TIMES, VALID_ACTION_SEQUEL,
            VALID_OUTCOMES, VALID_STATUSES, VALID_VALUE_SHIFTS, VALID_TURNING_POINTS,
        )
        assert _check_enum('character', VALID_TYPES) is True
        assert _check_enum('morning', VALID_TIMES) is True
        assert _check_enum('action', VALID_ACTION_SEQUEL) is True
        assert _check_enum('yes-but', VALID_OUTCOMES) is True
        assert _check_enum('drafted', VALID_STATUSES) is True
        assert _check_enum('+/-', VALID_VALUE_SHIFTS) is True
        assert _check_enum('revelation', VALID_TURNING_POINTS) is True

    def test_invalid_values(self):
        from storyforge.schema import _check_enum, VALID_TYPES, VALID_ACTION_SEQUEL, VALID_OUTCOMES, VALID_VALUE_SHIFTS
        assert _check_enum('setup', VALID_TYPES) is False
        assert _check_enum('scene', VALID_ACTION_SEQUEL) is False
        assert _check_enum('maybe', VALID_OUTCOMES) is False
        assert _check_enum('positive', VALID_VALUE_SHIFTS) is False

    def test_case_insensitive(self):
        from storyforge.schema import _check_enum, VALID_TYPES
        assert _check_enum('CHARACTER', VALID_TYPES) is True
        assert _check_enum('Character', VALID_TYPES) is True

    def test_all_value_shift_patterns(self):
        from storyforge.schema import _check_enum, VALID_VALUE_SHIFTS
        for v in ['+/-', '-/+', '+/++', '-/--', '+/+', '-/-']:
            assert _check_enum(v, VALID_VALUE_SHIFTS) is True


class TestIntegerValidation:
    def test_integers(self):
        from storyforge.schema import _check_integer
        assert _check_integer('42') is True
        assert _check_integer('0') is True
        assert _check_integer('-1') is True
        assert _check_integer('hello') is False
        assert _check_integer('3.5') is False
        assert _check_integer('') is False


class TestBooleanValidation:
    def test_booleans(self):
        from storyforge.schema import _check_boolean
        assert _check_boolean('true') is True
        assert _check_boolean('false') is True
        assert _check_boolean('True') is True
        assert _check_boolean('') is True
        assert _check_boolean('yes') is False
        assert _check_boolean('1') is False


class TestRegistryValidation:
    def test_valid_entries(self, fixture_dir):
        from storyforge.schema import _check_registry
        from storyforge.enrich import load_alias_map
        chars_csv = os.path.join(fixture_dir, 'reference', 'characters.csv')
        amap = load_alias_map(chars_csv)

        assert _check_registry('dorren-hayle', amap, False) == []
        assert _check_registry('Dorren Hayle', amap, False) == []
        assert _check_registry('Dorren', amap, False) == []
        assert _check_registry('Nobody', amap, False) == ['Nobody']
        assert _check_registry('Dorren;Tessa;Pell', amap, True) == []
        assert _check_registry('Dorren;Nobody;Pell', amap, True) == ['Nobody']

    def test_empty_map_skips(self):
        from storyforge.schema import _check_registry
        assert _check_registry('anything', {}, False) == []


class TestValidateSchema:
    def test_fixtures_have_passes_and_fails(self, fixture_dir):
        from storyforge.schema import validate_schema
        report = validate_schema(os.path.join(fixture_dir, 'reference'), fixture_dir)
        assert report['passed'] > 0
        assert report['failed'] is not None
        assert report['skipped'] is not None

    def test_without_project_dir_skips_registry(self, fixture_dir):
        from storyforge.schema import validate_schema
        report = validate_schema(os.path.join(fixture_dir, 'reference'))
        errors = [e for e in report['errors'] if e['constraint'] == 'registry']
        assert len(errors) == 0

    def test_catches_bad_enum(self, tmp_path):
        from storyforge.schema import validate_schema
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('sc-1|1|Test|1||||||setup|drafted|1000|1000\n')
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('sc-1|test||||||||||\n')
        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            f.write('sc-1|||||||||||||\n')

        report = validate_schema(ref)
        enum_errors = [e for e in report['errors'] if e['constraint'] == 'enum']
        assert len(enum_errors) == 1
        assert enum_errors[0]['column'] == 'type'
        assert enum_errors[0]['value'] == 'setup'

    def test_catches_bad_integer(self, tmp_path):
        from storyforge.schema import validate_schema
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('sc-1|one|Test|||||||||1000|\n')
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('sc-1||||||||||\n')
        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            f.write('sc-1|||||||||||||\n')

        report = validate_schema(ref)
        int_errors = [e for e in report['errors'] if e['constraint'] == 'integer']
        assert len(int_errors) == 1
        assert int_errors[0]['column'] == 'seq'


class TestMiceValidation:
    def test_normalization(self, fixture_dir):
        from storyforge.enrich import load_mice_registry, normalize_mice_threads
        mice_csv = os.path.join(fixture_dir, 'reference', 'mice-threads.csv')
        alias_map, type_map = load_mice_registry(mice_csv)

        assert normalize_mice_threads('+inquiry:the map anomaly', alias_map, type_map) == '+map-anomaly'
        assert normalize_mice_threads('+milieu:map-anomaly', alias_map, type_map) == '+map-anomaly'

    def test_schema_validation(self, fixture_dir):
        from storyforge.schema import _check_mice
        from storyforge.enrich import load_mice_registry
        mice_csv = os.path.join(fixture_dir, 'reference', 'mice-threads.csv')
        alias_map, type_map = load_mice_registry(mice_csv)

        assert len(_check_mice('+inquiry:map-anomaly', alias_map, type_map)) == 0
        assert len(_check_mice('no-prefix:name', alias_map, type_map)) >= 1
        assert len(_check_mice('+quest:map-anomaly', alias_map, type_map)) >= 1

    def test_bare_name_format(self, tmp_path):
        from storyforge.schema import _check_mice
        from storyforge.enrich import load_mice_registry

        reg_path = str(tmp_path / 'mice-threads.csv')
        with open(reg_path, 'w') as f:
            f.write('id|name|type|aliases\n')
            f.write('map-anomaly|Map Anomaly|inquiry|\n')

        alias_map, type_map = load_mice_registry(reg_path)
        assert len(_check_mice('+map-anomaly', alias_map, type_map)) == 0
        assert len(_check_mice('+inquiry:map-anomaly', alias_map, type_map)) == 0
        assert len(_check_mice('+nonexistent', alias_map, type_map)) >= 1


class TestSceneIdsValidation:
    def test_fixture_deps_resolve(self, fixture_dir):
        from storyforge.schema import validate_schema
        report = validate_schema(os.path.join(fixture_dir, 'reference'), fixture_dir)
        dep_errors = [e for e in report['errors'] if e['constraint'] == 'scene_ids']
        assert len(dep_errors) == 0

    def test_catches_bad_dep(self, tmp_path):
        from storyforge.schema import validate_schema
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('sc-1|1|Test|||||||||1000|\n')
            f.write('sc-2|2|Test2|||||||||1000|\n')
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('sc-1||||||||||\n')
            f.write('sc-2||||||||||\n')
        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            f.write('sc-1||||||||||||sc-2|\n')
            f.write('sc-2||||||||||||sc-1;nonexistent-scene|\n')

        report = validate_schema(ref)
        dep_errors = [e for e in report['errors'] if e['constraint'] == 'scene_ids']
        assert len(dep_errors) == 1
        assert 'nonexistent-scene' in dep_errors[0]['unresolved']


class TestKnowledgeGranularity:
    def test_short_names_no_warnings(self, tmp_path):
        from storyforge.schema import validate_knowledge_granularity
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'knowledge.csv'), 'w') as f:
            f.write('id|name|aliases\n')
            f.write('fact-one|The map is old|old map\n')
            f.write('fact-two|A door opened|door\n')
        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            f.write('sc-1||||||fact-one|fact-one;fact-two|||||||\n')

        result = validate_knowledge_granularity(ref)
        long_names = [w for w in result['warnings'] if w['type'] == 'long_name']
        assert len(long_names) == 0
        assert result['total_facts'] == 2

    def test_long_name_flagged(self, tmp_path):
        from storyforge.schema import validate_knowledge_granularity
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'knowledge.csv'), 'w') as f:
            f.write('id|name|aliases\n')
            f.write('wordy-fact|This is a very long fact name that contains way too many words and should definitely be flagged by the validator as overly granular|too wordy\n')
        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            f.write('sc-1|||||||||||||||\n')

        result = validate_knowledge_granularity(ref)
        long_names = [w for w in result['warnings'] if w['type'] == 'long_name']
        assert len(long_names) == 1
        assert long_names[0]['id'] == 'wordy-fact'
        assert long_names[0]['word_count'] > 15

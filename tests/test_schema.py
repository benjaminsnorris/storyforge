"""Tests for CSV schema validation (migrated from test-schema.sh)."""

import json

import pytest
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


class TestRegistryFileValidation:
    """physical-states.csv columns are declared in COLUMN_SCHEMA but were never
    validated, so display names in its character column went unreported."""

    def _write(self, ref_dir, character, category='injury'):
        with open(os.path.join(ref_dir, 'physical-states.csv'), 'w') as f:
            f.write('id|character|description|category|acquired|resolves|action_gating\n'
                    f'bruise|{character}|a bruise|{category}|act1-sc01|never|false\n')

    def test_unknown_character_reported(self, project_dir):
        from storyforge.schema import validate_schema
        ref_dir = os.path.join(project_dir, 'reference')
        self._write(ref_dir, 'Somebody Unknown')
        errors = validate_schema(ref_dir, project_dir)['errors']
        assert any(e['file'] == 'physical-states.csv' and e['column'] == 'character'
                   for e in errors)

    def test_bad_category_reported(self, project_dir):
        from storyforge.schema import validate_schema
        ref_dir = os.path.join(project_dir, 'reference')
        self._write(ref_dir, '', category='bruising')
        errors = validate_schema(ref_dir, project_dir)['errors']
        assert any(e['file'] == 'physical-states.csv' and e['column'] == 'category'
                   for e in errors)


class TestSceneIdRule:
    """Scene ids are 3-5 word event slugs, never positional."""

    @pytest.mark.parametrize('sid', [
        'act1-sc03', 'scene-12', 'ch3-2', 'chapter-ix', 'scene-ch3-2', 'part-2-scene-4'])
    def test_positional_ids_flagged(self, sid):
        from storyforge.scenes import scene_id_problems
        assert 'positional' in scene_id_problems(sid)

    @pytest.mark.parametrize('sid', [
        'gatsby-reunites-with-daisy', 'valley-of-ashes', 'myrtle-buys-a-dog',
        'nick-says-goodbye-gatsby-house'])
    def test_event_slugs_pass(self, sid):
        from storyforge.scenes import scene_id_problems
        assert scene_id_problems(sid) == []

    def test_word_count_outside_range_flagged(self):
        from storyforge.scenes import scene_id_problems
        assert scene_id_problems('funeral') == ['1 words (want 3-5)']
        assert scene_id_problems('my-family-have-been-prominent-well-to-do') == ['8 words (want 3-5)']

    def test_validate_scene_ids_reports(self, project_dir):
        from storyforge.schema import validate_scene_ids
        report = validate_scene_ids(os.path.join(project_dir, 'reference'))
        flagged = {w['id'] for w in report['warnings']}
        assert 'act1-sc01' in flagged   # the fixture's own ids are positional

    @pytest.mark.parametrize('builder', [
        'build_spine_prompt', 'build_architecture_prompt', 'build_map_prompt'])
    def test_elaborate_prompts_carry_rule(self, builder, project_dir, plugin_dir):
        from storyforge import prompts_elaborate
        from storyforge.scenes import SCENE_ID_RULE
        prompt = getattr(prompts_elaborate, builder)(project_dir, plugin_dir)
        assert SCENE_ID_RULE in prompt


class TestMultipleLocations:
    """A scene can move (The Great Gatsby's drive from East Egg past the
    valley of ashes to the Plaza), so location is an ordered list of places;
    routes are never places."""

    def test_location_is_array(self):
        from storyforge.schema import COLUMN_SCHEMA
        assert COLUMN_SCHEMA['location']['array'] is True

    def test_multiple_known_locations_validate(self, project_dir):
        import csv as _csv
        from storyforge.schema import validate_schema
        ref_dir = os.path.join(project_dir, 'reference')
        path = os.path.join(ref_dir, 'scenes.csv')
        with open(path) as f:
            rows = list(_csv.DictReader(f, delimiter='|'))
            header = list(rows[0].keys())
        rows[0]['location'] = 'cartography-office;deep-archive'
        with open(path, 'w') as f:
            w = _csv.DictWriter(f, fieldnames=header, delimiter='|', lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
        errors = [e for e in validate_schema(ref_dir, project_dir)['errors']
                  if e['column'] == 'location' and e['row'] == rows[0]['id']]
        assert errors == []

    def test_extraction_asks_for_places_in_order(self):
        from storyforge.extract import build_skeleton_prompt
        prompt = build_skeleton_prompt('s1', 'Scene prose.', {})
        assert '- location (list):' in prompt and 'in order' in prompt
        assert 'never "X to Y" as one place' in prompt


class TestOutcomes:
    """Five outcomes: Bickham's scene disasters (yes, no, yes-but, no-and)
    plus no-but from Kowal's try/fail cycles. Hone produced no-but while the
    schema rejected it; every place now agrees."""

    def test_no_but_is_valid(self):
        from storyforge.schema import _check_enum, VALID_OUTCOMES
        assert _check_enum('no-but', VALID_OUTCOMES)

    def test_story_power_set_matches_schema(self):
        from storyforge.schema import VALID_OUTCOMES
        from storyforge.scoring_story_power import VALID_BRIEF_OUTCOMES
        assert set(VALID_BRIEF_OUTCOMES) == set(VALID_OUTCOMES)

    def test_hone_normalizes_into_schema_set(self):
        from storyforge.schema import VALID_OUTCOMES
        from storyforge.hone import _OUTCOME_ENUM
        assert set(_OUTCOME_ENUM) == set(VALID_OUTCOMES)

    def test_scorer_weights_every_outcome(self):
        from storyforge.schema import VALID_OUTCOMES
        from storyforge.structural import _OUTCOME_TENSION
        assert set(_OUTCOME_TENSION) == set(VALID_OUTCOMES)

    def test_guide_defines_every_outcome(self):
        from storyforge.schema import OUTCOME_GUIDE, VALID_OUTCOMES
        for outcome in VALID_OUTCOMES:
            assert f'{outcome} (' in OUTCOME_GUIDE

    def test_extraction_prompt_uses_guide(self):
        from storyforge.extract import build_brief_parallel_prompt
        from storyforge.schema import OUTCOME_GUIDE
        assert OUTCOME_GUIDE in build_brief_parallel_prompt('s1', 'Prose.', {}, {}, {})

    def test_enrich_and_elaborate_prompts_use_guide(self, project_dir, plugin_dir):
        from storyforge.enrich import _field_instruction
        from storyforge.prompts_elaborate import build_briefs_prompt
        from storyforge.schema import OUTCOME_GUIDE
        assert OUTCOME_GUIDE in _field_instruction('outcome')
        assert OUTCOME_GUIDE in build_briefs_prompt(project_dir, plugin_dir)

    def test_no_but_skips_shift_mismatch(self):
        from storyforge.hone import detect_value_shift_outcome_mismatch
        intent = {'s1': {'value_shift': '+/-'}}
        briefs = {'s1': {'outcome': 'no-but'}}
        assert detect_value_shift_outcome_mismatch(intent, briefs) == []


class TestOutcomePhrasing:
    """Review #3: "No, but ..." was stored as `no`, "yes, but" as `yes`."""

    @pytest.mark.parametrize('answer,expected', [
        ('no, but she finds the letter', 'no-but'),
        ('No but something goes right', 'no-but'),
        ('yes, but at a cost', 'yes-but'),
        ('no — and furthermore the judge knows', 'no-and'),
        ('[No, and] worse', 'no-and'),
        ('no', 'no'),
        ('Yes.', 'yes'),
    ])
    def test_both_normalizers(self, answer, expected):
        # extract's outcome is now a schema enum; _reduce_enums still reduces
        # a free-text answer (skeleton fields, hand-edited replies)
        from storyforge.extract import _reduce_enums
        from storyforge.hone import normalize_outcomes
        assert _reduce_enums({'outcome': answer})['outcome'] == expected
        assert normalize_outcomes(answer) == expected

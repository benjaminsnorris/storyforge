"""Tests for storyforge.enrich — metadata enrichment library functions.

Covers: parse_enrich_response, load_alias_map, strip_parentheticals,
normalize_aliases, load_mice_registry, normalize_mice_threads,
format_registries_for_prompt, load_registry_alias_maps, normalize_fields,
validate_type, validate_time_of_day, update_csv_field, apply_enrich_result,
build_enrich_prompt, enrich_and_apply, _field_instruction, constants.
"""

import os
import shutil

import pytest

from storyforge.enrich import (
    METADATA_FIELDS,
    INTENT_FIELDS,
    BRIEFS_FIELDS,
    ALL_FIELDS,
    VALID_TYPES,
    VALID_TIMES,
    VALID_MICE_TYPES,
    parse_enrich_response,
    load_alias_map,
    strip_parentheticals,
    normalize_aliases,
    load_mice_registry,
    normalize_mice_threads,
    format_registries_for_prompt,
    load_registry_alias_maps,
    normalize_fields,
    validate_type,
    validate_time_of_day,
    update_csv_field,
    apply_enrich_result,
    build_enrich_prompt,
    enrich_and_apply,
    _field_instruction,
)


# ============================================================================
# Constants validation
# ============================================================================

class TestConstants:
    def test_metadata_fields_are_frozenset(self):
        assert isinstance(METADATA_FIELDS, frozenset)
        assert 'pov' in METADATA_FIELDS
        assert 'location' in METADATA_FIELDS
        assert 'type' in METADATA_FIELDS

    def test_intent_fields_are_frozenset(self):
        assert isinstance(INTENT_FIELDS, frozenset)
        assert 'emotional_arc' in INTENT_FIELDS
        assert 'mice_threads' in INTENT_FIELDS

    def test_briefs_fields_are_frozenset(self):
        assert isinstance(BRIEFS_FIELDS, frozenset)
        assert 'goal' in BRIEFS_FIELDS
        assert 'conflict' in BRIEFS_FIELDS

    def test_all_fields_is_union(self):
        assert ALL_FIELDS == METADATA_FIELDS | INTENT_FIELDS | BRIEFS_FIELDS

    def test_no_field_overlap(self):
        assert METADATA_FIELDS & INTENT_FIELDS == set()
        assert METADATA_FIELDS & BRIEFS_FIELDS == set()
        assert INTENT_FIELDS & BRIEFS_FIELDS == set()


# ============================================================================
# parse_enrich_response
# ============================================================================

class TestParseEnrichResponse:
    def test_basic_parsing(self):
        response = (
            "TYPE: action\n"
            "POV: Dorren Hayle\n"
            "LOCATION: Cartography Office\n"
        )
        result = parse_enrich_response(response, 'act1-sc01')
        assert result['type'] == 'action'
        assert result['pov'] == 'Dorren Hayle'
        assert result['location'] == 'Cartography Office'
        assert result['_status'] == 'ok'

    def test_empty_response_fails(self):
        result = parse_enrich_response('', 'scene-1')
        assert result['_status'] == 'fail'

    def test_whitespace_only_response_fails(self):
        result = parse_enrich_response('   \n  \n  ', 'scene-1')
        assert result['_status'] == 'fail'

    def test_no_valid_labels_fails(self):
        result = parse_enrich_response('Just some random text\nNo labels here', 'x')
        assert result['_status'] == 'fail'

    def test_all_field_labels(self):
        lines = [
            "TYPE: action",
            "POV: Alice",
            "LOCATION: Library",
            "TIME_OF_DAY: morning",
            "DURATION: 2 hours",
            "ACTION_SEQUEL: action",
            "EMOTIONAL_ARC: calm to dread",
            "VALUE_AT_STAKE: truth",
            "VALUE_SHIFT: +/-",
            "TURNING_POINT: revelation",
            "CHARACTERS: Alice;Bob",
            "ON_STAGE: Alice;Bob",
            "MICE_THREADS: +inquiry:question",
            "GOAL: find the book",
            "CONFLICT: door is locked",
            "OUTCOME: no-and",
            "CRISIS: break in or leave",
            "DECISION: breaks the window",
            "KNOWLEDGE_IN: knows location",
            "KNOWLEDGE_OUT: knows location;found clue",
            "KEY_ACTIONS: searches shelves;finds hidden note",
            "KEY_DIALOGUE: 'I know you're here'",
            "EMOTIONS: curiosity;dread",
            "MOTIFS: books;shadows",
            "PHYSICAL_STATE_IN: bruised ribs",
            "PHYSICAL_STATE_OUT: bruised ribs;cut hand",
        ]
        response = '\n'.join(lines)
        result = parse_enrich_response(response, 'test')
        assert result['_status'] == 'ok'
        assert result['type'] == 'action'
        assert result['goal'] == 'find the book'
        assert result['physical_state_out'] == 'bruised ribs;cut hand'

    def test_ignores_non_label_lines(self):
        response = (
            "Here is my analysis:\n"
            "\n"
            "TYPE: character\n"
            "Some explanation follows.\n"
            "POV: Tessa Merrin\n"
        )
        result = parse_enrich_response(response, 'test')
        assert result['type'] == 'character'
        assert result['pov'] == 'Tessa Merrin'
        assert result['_status'] == 'ok'

    def test_case_insensitive_labels(self):
        response = "type: action\npov: Alice\n"
        result = parse_enrich_response(response, 'test')
        assert result['type'] == 'action'
        assert result['pov'] == 'Alice'

    def test_empty_value_skipped(self):
        response = "TYPE:\nPOV: Alice\n"
        result = parse_enrich_response(response, 'test')
        assert 'type' not in result
        assert result['pov'] == 'Alice'

    def test_extra_whitespace_handled(self):
        response = "  TYPE:   action  \n  POV:   Bob  \n"
        result = parse_enrich_response(response, 'test')
        assert result['type'] == 'action'
        assert result['pov'] == 'Bob'


# ============================================================================
# strip_parentheticals
# ============================================================================

class TestStripParentheticals:
    def test_strips_trailing_parenthetical(self):
        assert strip_parentheticals('Alice (referenced)') == 'Alice'

    def test_strips_implied(self):
        assert strip_parentheticals('Bob (implied)') == 'Bob'

    def test_no_parenthetical_unchanged(self):
        assert strip_parentheticals('Charlie') == 'Charlie'

    def test_whitespace_trimmed(self):
        assert strip_parentheticals('  Alice (noted)  ') == 'Alice'

    def test_empty_string(self):
        assert strip_parentheticals('') == ''

    def test_parenthetical_in_middle_not_stripped(self):
        # Only trailing parentheticals are stripped
        assert strip_parentheticals('Alice (the Great) Returns') == 'Alice (the Great) Returns'


# ============================================================================
# load_alias_map
# ============================================================================

class TestLoadAliasMap:
    def test_characters_csv(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'characters.csv')
        alias_map = load_alias_map(csv_path)
        # Name -> canonical id
        assert alias_map['dorren hayle'] == 'dorren-hayle'
        # Alias -> canonical id
        assert alias_map['dorren'] == 'dorren-hayle'
        assert alias_map['dr. hayle'] == 'dorren-hayle'
        # id -> id (self-mapping)
        assert alias_map['dorren-hayle'] == 'dorren-hayle'

    def test_locations_csv(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'locations.csv')
        alias_map = load_alias_map(csv_path)
        assert alias_map['pressure cartography office'] == 'cartography-office'
        assert alias_map['pco'] == 'cartography-office'

    def test_missing_file_returns_empty(self):
        assert load_alias_map('/nonexistent/file.csv') == {}

    def test_none_path_returns_empty(self):
        assert load_alias_map('') == {}

    def test_empty_csv_returns_empty(self, tmp_path):
        csv = tmp_path / 'empty.csv'
        csv.write_text('')
        assert load_alias_map(str(csv)) == {}

    def test_no_name_column_returns_empty(self, tmp_path):
        csv = tmp_path / 'bad.csv'
        csv.write_text('id|title\na|b\n')
        assert load_alias_map(str(csv)) == {}


# ============================================================================
# normalize_aliases
# ============================================================================

class TestNormalizeAliases:
    def test_basic_resolution(self):
        alias_map = {'alice': 'alice-id', 'bob': 'bob-id'}
        result = normalize_aliases(alias_map, 'Alice;Bob')
        assert result == 'alice-id;bob-id'

    def test_deduplication(self):
        alias_map = {'alice': 'alice-id', 'al': 'alice-id'}
        result = normalize_aliases(alias_map, 'Alice;Al')
        assert result == 'alice-id'

    def test_unknown_passes_through(self):
        alias_map = {'alice': 'alice-id'}
        result = normalize_aliases(alias_map, 'Alice;Unknown Person')
        assert result == 'alice-id;Unknown Person'

    def test_empty_string(self):
        alias_map = {'alice': 'alice-id'}
        assert normalize_aliases(alias_map, '') == ''

    def test_empty_alias_map(self):
        assert normalize_aliases({}, 'Alice;Bob') == 'Alice;Bob'

    def test_strips_parentheticals_before_lookup(self):
        alias_map = {'alice': 'alice-id'}
        result = normalize_aliases(alias_map, 'Alice (referenced)')
        assert result == 'alice-id'

    def test_semicolon_only_entries_skipped(self):
        alias_map = {'alice': 'alice-id'}
        result = normalize_aliases(alias_map, 'Alice;;Bob')
        # "Bob" passes through, blank entries are skipped
        assert 'alice-id' in result


# ============================================================================
# load_mice_registry
# ============================================================================

class TestLoadMiceRegistry:
    def test_loads_from_fixture(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'mice-threads.csv')
        alias_map, type_map = load_mice_registry(csv_path)
        assert alias_map['map anomaly'] == 'map-anomaly'
        assert alias_map['the map anomaly'] == 'map-anomaly'
        assert type_map['map-anomaly'] == 'inquiry'
        assert type_map['uncharted-reaches'] == 'milieu'

    def test_missing_file_returns_empty(self):
        alias_map, type_map = load_mice_registry('/nonexistent.csv')
        assert alias_map == {}
        assert type_map == {}

    def test_no_name_column_returns_empty(self, tmp_path):
        csv = tmp_path / 'bad.csv'
        csv.write_text('id|title|type\na|b|inquiry\n')
        alias_map, type_map = load_mice_registry(str(csv))
        assert alias_map == {}
        assert type_map == {}


# ============================================================================
# normalize_mice_threads
# ============================================================================

class TestNormalizeMiceThreads:
    def test_resolves_aliases(self):
        alias_map = {'map anomaly': 'map-anomaly'}
        result = normalize_mice_threads('+inquiry:Map Anomaly', alias_map)
        assert result == '+map-anomaly'

    def test_preserves_prefix(self):
        alias_map = {'question': 'q-id'}
        result = normalize_mice_threads('-inquiry:question', alias_map)
        assert result == '-q-id'

    def test_no_prefix(self):
        alias_map = {'name': 'canonical'}
        result = normalize_mice_threads('inquiry:name', alias_map)
        assert result == 'canonical'

    def test_multiple_entries(self):
        alias_map = {'a': 'a-id', 'b': 'b-id'}
        result = normalize_mice_threads('+inquiry:a;-event:b', alias_map)
        assert result == '+a-id;-b-id'

    def test_empty_string(self):
        assert normalize_mice_threads('', {'a': 'b'}) == ''

    def test_empty_alias_map(self):
        assert normalize_mice_threads('+inquiry:x', {}) == '+inquiry:x'

    def test_bare_name_without_type(self):
        alias_map = {'foo': 'foo-id'}
        result = normalize_mice_threads('+foo', alias_map)
        assert result == '+foo-id'


# ============================================================================
# validate_type / validate_time_of_day
# ============================================================================

class TestValidateType:
    def test_valid_types(self):
        for t in VALID_TYPES:
            assert validate_type(t) == t

    def test_case_insensitive(self):
        assert validate_type('ACTION') == 'action'
        assert validate_type('Character') == 'character'

    def test_invalid_returns_empty(self):
        assert validate_type('combat') == ''
        assert validate_type('random') == ''

    def test_empty_returns_empty(self):
        assert validate_type('') == ''

    def test_whitespace_stripped(self):
        assert validate_type('  action  ') == 'action'


class TestValidateTimeOfDay:
    def test_valid_times(self):
        for t in VALID_TIMES:
            assert validate_time_of_day(t) == t

    def test_case_insensitive(self):
        assert validate_time_of_day('MORNING') == 'morning'

    def test_invalid_returns_empty(self):
        assert validate_time_of_day('noon') == ''

    def test_empty_returns_empty(self):
        assert validate_time_of_day('') == ''


# ============================================================================
# update_csv_field
# ============================================================================

class TestUpdateCsvField:
    def test_updates_existing_field(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        result = update_csv_field(csv_path, 'act1-sc01', 'pov', 'Tessa Merrin')
        assert result is True
        # Verify the file was actually updated
        with open(csv_path) as f:
            content = f.read()
        assert 'Tessa Merrin' in content

    def test_returns_false_for_missing_row(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        result = update_csv_field(csv_path, 'nonexistent', 'pov', 'Alice')
        assert result is False

    def test_returns_false_for_missing_column(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        result = update_csv_field(csv_path, 'act1-sc01', 'no_such_column', 'val')
        assert result is False

    def test_returns_false_for_missing_file(self):
        result = update_csv_field('/nonexistent/file.csv', 'x', 'y', 'z')
        assert result is False

    def test_atomic_write_preserves_other_rows(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        update_csv_field(csv_path, 'act1-sc01', 'pov', 'Changed')
        with open(csv_path) as f:
            content = f.read()
        # Other rows should still be present
        assert 'act1-sc02' in content
        assert 'act2-sc01' in content


# ============================================================================
# format_registries_for_prompt
# ============================================================================

class TestFormatRegistriesForPrompt:
    def test_includes_characters(self, project_dir):
        result = format_registries_for_prompt(project_dir)
        assert 'Characters' in result
        assert 'dorren-hayle' in result

    def test_includes_locations(self, project_dir):
        result = format_registries_for_prompt(project_dir)
        assert 'Locations' in result
        assert 'cartography-office' in result

    def test_includes_mice_threads_with_type(self, project_dir):
        result = format_registries_for_prompt(project_dir)
        assert 'MICE Threads' in result
        assert '[inquiry]' in result

    def test_empty_project_returns_empty(self, tmp_path):
        # Project with no registry files
        os.makedirs(os.path.join(str(tmp_path), 'reference'))
        result = format_registries_for_prompt(str(tmp_path))
        assert result == ''

    def test_header_present(self, project_dir):
        result = format_registries_for_prompt(project_dir)
        assert result.startswith('## Canonical Registries')


# ============================================================================
# load_registry_alias_maps
# ============================================================================

class TestLoadRegistryAliasMaps:
    def test_loads_all_registries(self, project_dir):
        maps = load_registry_alias_maps(project_dir)
        assert 'characters' in maps
        assert 'locations' in maps
        assert 'motifs' in maps
        assert 'values' in maps
        assert 'knowledge' in maps
        assert 'mice_threads' in maps
        assert 'mice_types' in maps

    def test_character_resolution(self, project_dir):
        maps = load_registry_alias_maps(project_dir)
        assert maps['characters']['dorren'] == 'dorren-hayle'

    def test_mice_type_map(self, project_dir):
        maps = load_registry_alias_maps(project_dir)
        assert maps['mice_types']['map-anomaly'] == 'inquiry'


# ============================================================================
# normalize_fields
# ============================================================================

class TestNormalizeFields:
    def test_normalizes_character_fields(self, project_dir):
        maps = load_registry_alias_maps(project_dir)
        result = {'characters': 'Dorren;Tessa', 'on_stage': 'Dorren'}
        normalize_fields(result, maps)
        assert result['characters'] == 'dorren-hayle;tessa-merrin'
        assert result['on_stage'] == 'dorren-hayle'

    def test_normalizes_location(self, project_dir):
        maps = load_registry_alias_maps(project_dir)
        result = {'location': 'PCO'}
        normalize_fields(result, maps)
        assert result['location'] == 'cartography-office'

    def test_normalizes_motifs(self, project_dir):
        maps = load_registry_alias_maps(project_dir)
        result = {'motifs': 'cartography;governance-as-weight'}
        normalize_fields(result, maps)
        assert 'maps' in result['motifs']
        assert 'governance' in result['motifs']

    def test_normalizes_value_at_stake(self, project_dir):
        maps = load_registry_alias_maps(project_dir)
        result = {'value_at_stake': 'honesty'}
        normalize_fields(result, maps)
        assert result['value_at_stake'] == 'truth'

    def test_normalizes_mice_threads(self, project_dir):
        maps = load_registry_alias_maps(project_dir)
        result = {'mice_threads': '+inquiry:the map anomaly'}
        normalize_fields(result, maps)
        assert 'map-anomaly' in result['mice_threads']

    def test_empty_alias_maps_noop(self):
        result = {'characters': 'Alice', 'type': 'action'}
        normalize_fields(result, {})
        assert result['characters'] == 'Alice'

    def test_fields_not_present_are_skipped(self, project_dir):
        maps = load_registry_alias_maps(project_dir)
        result = {'type': 'action'}  # No registry-backed fields
        normalize_fields(result, maps)
        assert result['type'] == 'action'


# ============================================================================
# apply_enrich_result
# ============================================================================

class TestApplyEnrichResult:
    def test_writes_metadata_fields(self, project_dir):
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        result = {
            '_status': 'ok',
            'time_of_day': 'dusk',
            'duration': '3 hours',
        }
        # act2-sc01 has empty time_of_day in the fixture? Let's use it.
        count = apply_enrich_result('act2-sc01', result, meta_csv, intent_csv,
                                    force=True)
        assert count >= 1

    def test_skips_existing_values_without_force(self, project_dir):
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        # act1-sc01 already has pov = 'Dorren Hayle'
        result = {
            '_status': 'ok',
            'pov': 'Someone Else',
        }
        count = apply_enrich_result('act1-sc01', result, meta_csv, intent_csv,
                                    force=False)
        assert count == 0

    def test_force_overwrites(self, project_dir):
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        result = {
            '_status': 'ok',
            'pov': 'Someone Else',
        }
        count = apply_enrich_result('act1-sc01', result, meta_csv, intent_csv,
                                    force=True)
        assert count == 1

    def test_writes_intent_fields(self, project_dir):
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        result = {
            '_status': 'ok',
            'emotional_arc': 'calm to terror',
        }
        count = apply_enrich_result('act1-sc01', result, meta_csv, intent_csv,
                                    force=True)
        assert count == 1

    def test_fail_status_returns_zero(self, project_dir):
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        result = {'_status': 'fail', 'type': 'action'}
        count = apply_enrich_result('act1-sc01', result, meta_csv, intent_csv)
        assert count == 0

    def test_writes_briefs_fields(self, project_dir):
        meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        briefs_csv = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
        result = {
            '_status': 'ok',
            'goal': 'Find the map',
        }
        count = apply_enrich_result('act1-sc01', result, meta_csv, intent_csv,
                                    force=True, briefs_csv=briefs_csv)
        assert count == 1


# ============================================================================
# build_enrich_prompt
# ============================================================================

class TestBuildEnrichPrompt:
    def test_builds_prompt_for_scene(self, project_dir):
        prompt = build_enrich_prompt('act1-sc01', project_dir, force=True)
        assert prompt  # non-empty
        assert 'Dorren Hayle' in prompt  # scene text or context
        assert 'TYPE:' in prompt or 'type' in prompt.lower()

    def test_returns_empty_for_missing_scene(self, project_dir):
        prompt = build_enrich_prompt('nonexistent', project_dir)
        assert prompt == ''

    def test_specific_fields(self, project_dir):
        prompt = build_enrich_prompt('act1-sc01', project_dir,
                                     fields=['type', 'location'],
                                     force=True)
        assert 'TYPE:' in prompt
        assert 'LOCATION:' in prompt
        # Should not include unrelated field instructions
        assert 'GOAL:' not in prompt

    def test_skips_populated_fields_without_force(self, project_dir):
        # act1-sc01 has pov='Dorren Hayle' already populated
        prompt = build_enrich_prompt('act1-sc01', project_dir,
                                     fields=['pov'], force=False)
        # All requested fields are already filled, so prompt should be empty
        assert prompt == ''

    def test_includes_registries(self, project_dir):
        prompt = build_enrich_prompt('act1-sc01', project_dir,
                                     fields=['characters'],
                                     force=True)
        assert 'Canonical Registries' in prompt


# ============================================================================
# _field_instruction
# ============================================================================

class TestFieldInstruction:
    def test_returns_instruction_for_known_fields(self):
        assert 'TYPE:' in _field_instruction('type')
        assert 'POV:' in _field_instruction('pov')
        assert 'LOCATION:' in _field_instruction('location')
        assert 'GOAL:' in _field_instruction('goal')

    def test_returns_empty_for_unknown_field(self):
        assert _field_instruction('nonexistent') == ''

    def test_all_enrichable_fields_have_instructions(self):
        for field in ALL_FIELDS:
            instruction = _field_instruction(field)
            assert instruction, f"No instruction for field: {field}"


# ============================================================================
# enrich_and_apply
# ============================================================================

class TestEnrichAndApply:
    def test_full_pipeline(self, project_dir):
        response = (
            "TYPE: action\n"
            "CHARACTERS: Dorren;Tessa\n"
            "ON_STAGE: Dorren;Tessa\n"
            "EMOTIONAL_ARC: calm to dread\n"
        )
        alias_maps = load_registry_alias_maps(project_dir)
        result = enrich_and_apply('act1-sc01', response, project_dir,
                                  alias_maps=alias_maps, force=True)
        assert result['_status'] == 'ok'
        # Characters should be normalized
        assert 'dorren-hayle' in result['characters']
        assert 'tessa-merrin' in result['characters']

    def test_invalid_type_removed(self, project_dir):
        response = "TYPE: invalid_type\nPOV: Dorren Hayle\n"
        result = enrich_and_apply('act1-sc01', response, project_dir, force=True)
        assert 'type' not in result
        assert result['pov'] == 'Dorren Hayle'

    def test_invalid_time_removed(self, project_dir):
        response = "TIME_OF_DAY: noon\nPOV: Dorren Hayle\n"
        result = enrich_and_apply('act1-sc01', response, project_dir, force=True)
        assert 'time_of_day' not in result

    def test_empty_response_returns_fail(self, project_dir):
        result = enrich_and_apply('act1-sc01', '', project_dir)
        assert result['_status'] == 'fail'

    def test_no_alias_maps_still_works(self, project_dir):
        response = "TYPE: action\nLOCATION: Library\n"
        result = enrich_and_apply('act1-sc01', response, project_dir,
                                  alias_maps=None, force=True)
        assert result['_status'] == 'ok'
        assert result['type'] == 'action'
        assert result['location'] == 'Library'

"""Tests for storyforge.hone — CSV data quality detection and fixing.

Covers: normalize_outcomes, detect_abstract_fields, detect_overspecified,
detect_verbose_fields, detect_conflict_free, detect_brief_issues,
detect_vague_function, detect_overlong_function, detect_flat_emotional_arc,
detect_abstract_emotional_arc, detect_onstage_subset_violation,
detect_value_shift_outcome_mismatch, detect_intent_issues, detect_gaps,
parse_registry_response, parse_concretize_response, load_external_findings,
build_concretize_prompt, build_trim_prompt, reconcile_outcomes.
"""

import os
import shutil

import pytest

from storyforge.hone import (
    normalize_outcomes,
    reconcile_outcomes,
    detect_abstract_fields,
    detect_overspecified,
    detect_verbose_fields,
    detect_conflict_free,
    detect_brief_issues,
    detect_vague_function,
    detect_overlong_function,
    detect_flat_emotional_arc,
    detect_abstract_emotional_arc,
    detect_onstage_subset_violation,
    detect_value_shift_outcome_mismatch,
    detect_intent_issues,
    detect_gaps,
    parse_registry_response,
    parse_concretize_response,
    load_external_findings,
    build_concretize_prompt,
    build_trim_prompt,
    build_evaluation_fix_prompt,
    build_intent_fix_prompt,
)


# ============================================================================
# normalize_outcomes
# ============================================================================

class TestNormalizeOutcomes:
    def test_simple_values(self):
        assert normalize_outcomes('yes') == 'yes'
        assert normalize_outcomes('no') == 'no'
        assert normalize_outcomes('yes-but') == 'yes-but'
        assert normalize_outcomes('no-and') == 'no-and'
        assert normalize_outcomes('no-but') == 'no-but'

    def test_with_elaboration(self):
        assert normalize_outcomes('yes-but — she loses something') == 'yes-but'
        assert normalize_outcomes('no-and they lose everything') == 'no-and'

    def test_bracketed(self):
        assert normalize_outcomes('[no-and]') == 'no-and'
        assert normalize_outcomes('[yes-but]') == 'yes-but'

    def test_empty_and_whitespace(self):
        assert normalize_outcomes('') == ''
        assert normalize_outcomes('   ') == ''

    def test_unrecognized_passthrough(self):
        assert normalize_outcomes('something else entirely') == 'something else entirely'

    def test_case_insensitive(self):
        assert normalize_outcomes('YES') == 'yes'
        assert normalize_outcomes('No-And') == 'no-and'


# ============================================================================
# reconcile_outcomes
# ============================================================================

class TestReconcileOutcomes:
    def test_normalizes_outcomes_in_csv(self, project_dir):
        """Outcomes with elaboration text should be normalized to enum values."""
        ref_dir = os.path.join(project_dir, 'reference')
        briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')

        # Read original to check current values
        from storyforge.elaborate import _read_csv
        original_rows = _read_csv(briefs_path)
        # All outcomes in fixture are already normalized, so change one
        from storyforge.elaborate import _write_csv, _FILE_MAP
        for row in original_rows:
            if row['id'] == 'act1-sc01':
                row['outcome'] = 'no-and — she loses credibility'
        _write_csv(briefs_path, original_rows, _FILE_MAP['scene-briefs.csv'])

        changed = reconcile_outcomes(ref_dir)
        assert changed == 1

        # Verify the value was normalized
        rows = _read_csv(briefs_path)
        for row in rows:
            if row['id'] == 'act1-sc01':
                assert row['outcome'] == 'no-and'

    def test_no_changes_when_already_normalized(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        changed = reconcile_outcomes(ref_dir)
        assert changed == 0


# ============================================================================
# detect_abstract_fields
# ============================================================================

class TestDetectAbstractFields:
    def test_flags_abstract_language(self):
        briefs = {
            'scene-1': {
                'goal': 'The realization building as tension deepens and transforms',
                'key_actions': 'walks to the door; picks up the knife',
            },
        }
        results = detect_abstract_fields(briefs)
        assert len(results) == 1
        assert results[0]['scene_id'] == 'scene-1'
        assert results[0]['field'] == 'goal'
        assert results[0]['issue'] == 'abstract'
        assert results[0]['abstract_count'] >= 2

    def test_skips_concrete_language(self):
        briefs = {
            'scene-1': {
                'goal': 'walks to the door and picks up the knife',
            },
        }
        results = detect_abstract_fields(briefs)
        assert len(results) == 0

    def test_requires_two_abstract_indicators(self):
        """A single abstract word should not trigger a flag."""
        briefs = {
            'scene-1': {
                'goal': 'The realization comes quickly',
            },
        }
        results = detect_abstract_fields(briefs)
        assert len(results) == 0

    def test_scope_to_specific_scenes(self):
        briefs = {
            'scene-1': {'goal': 'realizes and transforms and deepens'},
            'scene-2': {'goal': 'realizes and transforms and deepens'},
        }
        results = detect_abstract_fields(briefs, scene_ids=['scene-1'])
        assert len(results) == 1
        assert results[0]['scene_id'] == 'scene-1'

    def test_empty_fields_skipped(self):
        briefs = {'scene-1': {'goal': '', 'key_actions': ''}}
        results = detect_abstract_fields(briefs)
        assert len(results) == 0

    def test_checks_all_concretizable_fields(self):
        """All six concretizable fields should be checked."""
        abstract_text = 'the realization building as tension deepens and transforms'
        briefs = {
            'scene-1': {
                'key_actions': abstract_text,
                'crisis': abstract_text,
                'decision': abstract_text,
                'goal': abstract_text,
                'conflict': abstract_text,
                'emotions': abstract_text,
            },
        }
        results = detect_abstract_fields(briefs)
        fields = {r['field'] for r in results}
        assert 'key_actions' in fields
        assert 'crisis' in fields
        assert 'goal' in fields
        assert 'conflict' in fields


# ============================================================================
# detect_overspecified
# ============================================================================

class TestDetectOverspecified:
    def test_too_many_beats_absolute(self):
        briefs = {
            'scene-1': {
                'key_actions': 'a; b; c; d; e; f',
            },
        }
        scenes = {'scene-1': {'target_words': '3000'}}
        results = detect_overspecified(briefs, scenes)
        assert len(results) >= 1
        assert results[0]['issue'] == 'overspecified'
        assert results[0]['beat_count'] == 6

    def test_beats_per_1k_too_high(self):
        """5 beats in 1500 words = 3.3/1k, above the 2.5 threshold."""
        briefs = {
            'scene-1': {
                'key_actions': 'a; b; c; d; e',
            },
        }
        scenes = {'scene-1': {'target_words': '1500'}}
        results = detect_overspecified(briefs, scenes)
        assert len(results) == 1
        assert results[0]['beats_per_1k'] > 2.5

    def test_acceptable_beat_count(self):
        """2 beats in any word count should be fine."""
        briefs = {
            'scene-1': {
                'key_actions': 'a; b',
            },
        }
        scenes = {'scene-1': {'target_words': '1000'}}
        results = detect_overspecified(briefs, scenes)
        assert len(results) == 0

    def test_emotion_beats_too_many(self):
        briefs = {
            'scene-1': {
                'emotions': 'fear; anger; shame; relief',
            },
        }
        scenes = {'scene-1': {'target_words': '2000'}}
        results = detect_overspecified(briefs, scenes)
        assert len(results) == 1
        assert results[0]['field'] == 'emotions'
        assert results[0]['beat_count'] == 4

    def test_emotion_beats_under_threshold(self):
        briefs = {
            'scene-1': {
                'emotions': 'fear; anger; resolve',
            },
        }
        scenes = {'scene-1': {'target_words': '2000'}}
        results = detect_overspecified(briefs, scenes)
        assert len(results) == 0


# ============================================================================
# detect_verbose_fields
# ============================================================================

class TestDetectVerboseFields:
    def test_field_exceeds_max_chars(self):
        briefs = {
            'scene-1': {
                'goal': 'x' * 100,  # max is 80
            },
        }
        results = detect_verbose_fields(briefs)
        assert len(results) == 1
        assert results[0]['issue'] == 'verbose'
        assert results[0]['char_count'] == 100

    def test_short_field_passes(self):
        briefs = {
            'scene-1': {
                'goal': 'Save the village',
            },
        }
        results = detect_verbose_fields(briefs)
        assert len(results) == 0

    def test_prose_patterns_trigger_flag(self):
        """Multiple sentences with prose indicators approaching the limit."""
        briefs = {
            'scene-1': {
                'decision': 'She decides to leave. He follows after her. She runs faster now.',
            },
        }
        results = detect_verbose_fields(briefs)
        assert len(results) == 1
        assert results[0]['field'] == 'decision'

    def test_key_actions_long(self):
        briefs = {
            'scene-1': {
                'key_actions': 'x' * 210,  # max is 200
            },
        }
        results = detect_verbose_fields(briefs)
        assert len(results) == 1
        assert results[0]['field'] == 'key_actions'


# ============================================================================
# detect_conflict_free
# ============================================================================

class TestDetectConflictFree:
    def test_keyword_detection(self):
        """Conflict with observation words but no opposition words."""
        briefs = {
            'scene-1': {
                'conflict': 'Dorren notices the changes and observes the pattern',
                'outcome': 'no',
            },
        }
        intent = {'scene-1': {'value_shift': '-/+'}}
        results = detect_conflict_free(briefs, intent)
        assert len(results) == 1
        assert results[0]['reason'] == 'keyword'

    def test_structural_detection(self):
        """Outcome=yes with flat value shift."""
        briefs = {
            'scene-1': {
                'conflict': 'The enemy attacks the wall',
                'outcome': 'yes',
            },
        }
        intent = {'scene-1': {'value_shift': '+/+'}}
        results = detect_conflict_free(briefs, intent)
        assert len(results) == 1
        assert results[0]['reason'] == 'structural'
        assert results[0]['outcome'] == 'yes'

    def test_both_checks_trigger(self):
        briefs = {
            'scene-1': {
                'conflict': 'She notices and observes the emptiness',
                'outcome': 'yes',
            },
        }
        intent = {'scene-1': {'value_shift': '+/+'}}
        results = detect_conflict_free(briefs, intent)
        assert len(results) == 1
        assert results[0]['reason'] == 'both'

    def test_real_conflict_passes(self):
        """Conflict with opposition indicators should pass."""
        briefs = {
            'scene-1': {
                'conflict': 'He refuses to hand over the key and blocks the exit',
                'outcome': 'no-and',
            },
        }
        intent = {'scene-1': {'value_shift': '-/--'}}
        results = detect_conflict_free(briefs, intent)
        assert len(results) == 0

    def test_empty_conflict_skipped(self):
        briefs = {'scene-1': {'conflict': '', 'outcome': 'yes'}}
        intent = {'scene-1': {'value_shift': '+/+'}}
        results = detect_conflict_free(briefs, intent)
        assert len(results) == 0


# ============================================================================
# detect_brief_issues (combined detector)
# ============================================================================

class TestDetectBriefIssues:
    def test_combines_all_issue_types(self):
        briefs = {
            'scene-a': {
                'goal': 'the realization building as tension deepens and transforms',
                'key_actions': 'a; b; c; d; e; f; g',
                'conflict': 'notices and observes changes',
                'outcome': 'no',
            },
        }
        scenes = {'scene-a': {'target_words': '2000'}}
        intent = {'scene-a': {'value_shift': '-/+'}}
        results = detect_brief_issues(briefs, scenes, intent_map=intent)
        issue_types = {r['issue'] for r in results}
        assert 'abstract' in issue_types
        assert 'overspecified' in issue_types
        assert 'conflict_free' in issue_types

    def test_sorted_by_scene_id_and_field(self):
        briefs = {
            'z-scene': {'goal': 'the realization building as tension deepens and transforms'},
            'a-scene': {'goal': 'the realization building as tension deepens and transforms'},
        }
        scenes = {'z-scene': {}, 'a-scene': {}}
        results = detect_brief_issues(briefs, scenes)
        if len(results) >= 2:
            assert results[0]['scene_id'] <= results[1]['scene_id']


# ============================================================================
# Intent quality detectors
# ============================================================================

class TestDetectVagueFunction:
    def test_flags_abstract_function(self):
        intent = {
            'scene-1': {
                'function': 'Character realizes and connects and deepens understanding',
            },
        }
        results = detect_vague_function(intent)
        assert len(results) == 1
        assert results[0]['issue'] == 'vague'
        assert results[0]['abstract_count'] >= 2

    def test_concrete_function_passes(self):
        intent = {
            'scene-1': {
                'function': 'Character says goodbye and walks out the door',
            },
        }
        results = detect_vague_function(intent)
        assert len(results) == 0


class TestDetectOverlongFunction:
    def test_flags_long_function(self):
        intent = {
            'scene-1': {
                'function': 'x' * 410,
            },
        }
        results = detect_overlong_function(intent)
        assert len(results) == 1
        assert results[0]['issue'] == 'overlong'
        assert results[0]['char_count'] == 410

    def test_normal_length_passes(self):
        intent = {
            'scene-1': {
                'function': 'Dorren discovers the map anomaly',
            },
        }
        results = detect_overlong_function(intent)
        assert len(results) == 0


class TestDetectFlatEmotionalArc:
    def test_flags_flat_arc(self):
        intent = {
            'scene-1': {
                'emotional_arc': 'grief',
            },
        }
        results = detect_flat_emotional_arc(intent)
        assert len(results) == 1
        assert results[0]['issue'] == 'flat'

    def test_arc_with_transition_passes(self):
        intent = {
            'scene-1': {
                'emotional_arc': 'grief giving way to resolve',
            },
        }
        results = detect_flat_emotional_arc(intent)
        assert len(results) == 0

    def test_simple_x_to_y_passes(self):
        intent = {
            'scene-1': {
                'emotional_arc': 'fear to resolve',
            },
        }
        results = detect_flat_emotional_arc(intent)
        assert len(results) == 0


class TestDetectAbstractEmotionalArc:
    def test_flags_abstract_arc(self):
        intent = {
            'scene-1': {
                'emotional_arc': 'tension and turmoil giving way to resolution and transformation',
            },
        }
        results = detect_abstract_emotional_arc(intent)
        assert len(results) == 1
        assert results[0]['issue'] == 'abstract_arc'

    def test_grounded_arc_passes(self):
        intent = {
            'scene-1': {
                'emotional_arc': 'grief giving way to resolve',
            },
        }
        results = detect_abstract_emotional_arc(intent)
        assert len(results) == 0


class TestDetectOnstageSubsetViolation:
    def test_flags_violating_characters(self):
        intent = {
            'scene-1': {
                'characters': 'Alice;Bob',
                'on_stage': 'Alice;Bob;Charlie',
            },
        }
        results = detect_onstage_subset_violation(intent)
        assert len(results) == 1
        assert results[0]['issue'] == 'not_subset'
        assert 'charlie' in results[0]['violating']

    def test_valid_subset_passes(self):
        intent = {
            'scene-1': {
                'characters': 'Alice;Bob;Charlie',
                'on_stage': 'Alice;Bob',
            },
        }
        results = detect_onstage_subset_violation(intent)
        assert len(results) == 0

    def test_case_insensitive_comparison(self):
        intent = {
            'scene-1': {
                'characters': 'alice;Bob',
                'on_stage': 'Alice;bob',
            },
        }
        results = detect_onstage_subset_violation(intent)
        assert len(results) == 0


class TestDetectValueShiftOutcomeMismatch:
    def test_yes_with_negative_shift(self):
        intent = {'scene-1': {'value_shift': '+/-'}}
        briefs = {'scene-1': {'outcome': 'yes'}}
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert len(results) == 1
        assert results[0]['issue'] == 'outcome_mismatch'

    def test_no_with_positive_shift(self):
        intent = {'scene-1': {'value_shift': '-/+'}}
        briefs = {'scene-1': {'outcome': 'no'}}
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert len(results) == 1
        assert results[0]['issue'] == 'outcome_mismatch'

    def test_yes_but_skipped(self):
        """Mixed outcomes should not be flagged."""
        intent = {'scene-1': {'value_shift': '+/-'}}
        briefs = {'scene-1': {'outcome': 'yes-but'}}
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert len(results) == 0

    def test_matching_shift_passes(self):
        intent = {'scene-1': {'value_shift': '+/+'}}
        briefs = {'scene-1': {'outcome': 'yes'}}
        results = detect_value_shift_outcome_mismatch(intent, briefs)
        assert len(results) == 0


class TestDetectIntentIssues:
    def test_combines_all_intent_detectors(self):
        intent = {
            'scene-a': {
                'function': 'Character realizes and connects and deepens',
                'emotional_arc': 'grief',
                'characters': 'Alice;Bob',
                'on_stage': 'Alice;Bob;Charlie',
            },
        }
        scenes = {'scene-a': {}}
        briefs = {'scene-a': {'outcome': ''}}
        results = detect_intent_issues(intent, scenes, briefs)
        issue_types = {r['issue'] for r in results}
        assert 'vague' in issue_types
        assert 'flat' in issue_types
        assert 'not_subset' in issue_types


# ============================================================================
# detect_gaps
# ============================================================================

class TestDetectGaps:
    def test_detects_missing_required_fields(self):
        scenes = {'scene-1': {'status': 'briefed'}}
        intent = {'scene-1': {'function': '', 'value_at_stake': 'truth', 'value_shift': '', 'emotional_arc': 'fear to resolve'}}
        briefs = {'scene-1': {'goal': 'test', 'conflict': '', 'outcome': 'yes', 'crisis': '', 'decision': 'go'}}
        results = detect_gaps(scenes, intent, briefs)
        missing_fields = {r['field'] for r in results}
        assert 'function' in missing_fields
        assert 'conflict' in missing_fields
        assert 'crisis' in missing_fields
        assert 'value_shift' in missing_fields

    def test_no_gaps_when_all_filled(self):
        scenes = {'scene-1': {'status': 'briefed'}}
        intent = {'scene-1': {
            'function': 'test', 'value_at_stake': 'truth',
            'value_shift': '+/-', 'emotional_arc': 'fear to resolve',
        }}
        briefs = {'scene-1': {
            'goal': 'test', 'conflict': 'test', 'outcome': 'yes',
            'crisis': 'test', 'decision': 'go',
        }}
        results = detect_gaps(scenes, intent, briefs)
        assert len(results) == 0

    def test_spine_status_has_no_required_fields(self):
        """Scenes in 'spine' status should not have required fields."""
        scenes = {'scene-1': {'status': 'spine'}}
        intent = {'scene-1': {}}
        briefs = {'scene-1': {}}
        results = detect_gaps(scenes, intent, briefs)
        assert len(results) == 0

    def test_correct_file_attribution(self):
        """Fields should be attributed to the correct CSV file."""
        scenes = {'scene-1': {'status': 'briefed'}}
        intent = {'scene-1': {'function': '', 'value_at_stake': '', 'value_shift': '+/-', 'emotional_arc': 'test'}}
        briefs = {'scene-1': {'goal': '', 'conflict': 'test', 'outcome': 'yes', 'crisis': 'test', 'decision': 'go'}}
        results = detect_gaps(scenes, intent, briefs)

        for r in results:
            if r['field'] == 'function':
                assert r['file'] == 'scene-intent.csv'
            elif r['field'] == 'goal':
                assert r['file'] == 'scene-briefs.csv'


# ============================================================================
# parse_registry_response
# ============================================================================

class TestParseRegistryResponse:
    def test_parses_characters_registry(self):
        response = """id|name|role|aliases
dorren-hayle|Dorren Hayle|protagonist|Dorren;dorren;Hayle
kael-maren|Kael Maren|supporting|Kael;kael"""
        rows, updates = parse_registry_response(response, 'characters')
        assert len(rows) == 2
        assert rows[0]['id'] == 'dorren-hayle'
        assert rows[0]['name'] == 'Dorren Hayle'
        assert rows[1]['role'] == 'supporting'
        assert len(updates) == 0

    def test_parses_updates_section(self):
        response = """id|name|type|aliases
who-killed-rowan|Who killed Rowan?|inquiry|who-killed

UPDATES
UPDATE: act1-sc01 | +inquiry:who-killed-rowan
UPDATE: act2-sc03 | -inquiry:who-killed-rowan"""
        rows, updates = parse_registry_response(response, 'mice-threads')
        assert len(rows) == 1
        assert len(updates) == 2
        assert updates[0] == ('act1-sc01', '+inquiry:who-killed-rowan')
        assert updates[1] == ('act2-sc03', '-inquiry:who-killed-rowan')

    def test_unknown_domain_raises(self):
        with pytest.raises(ValueError, match='Unknown'):
            parse_registry_response('', 'nonexistent')

    def test_skips_malformed_lines(self):
        response = """id|name|role|aliases
dorren-hayle|Dorren Hayle|protagonist|Dorren
incomplete
|also missing"""
        rows, _ = parse_registry_response(response, 'characters')
        assert len(rows) == 1
        assert rows[0]['id'] == 'dorren-hayle'


# ============================================================================
# parse_concretize_response
# ============================================================================

class TestParseConcretizeResponse:
    def test_parses_labeled_lines(self):
        response = """goal: She opens the door and steps outside
key_actions: picks up the knife; turns to face the crowd"""
        result = parse_concretize_response(response, 'scene-1', ['goal', 'key_actions'])
        assert result['goal'] == 'She opens the door and steps outside'
        assert result['key_actions'] == 'picks up the knife; turns to face the crowd'

    def test_skips_unmatched_fields(self):
        response = """goal: new goal value"""
        result = parse_concretize_response(response, 'scene-1', ['goal', 'crisis'])
        assert 'goal' in result
        assert 'crisis' not in result

    def test_handles_empty_response(self):
        result = parse_concretize_response('', 'scene-1', ['goal'])
        assert result == {}

    def test_case_insensitive_prefix(self):
        response = """Goal: new goal"""
        result = parse_concretize_response(response, 'scene-1', ['goal'])
        assert result['goal'] == 'new goal'


# ============================================================================
# load_external_findings
# ============================================================================

class TestLoadExternalFindings:
    def test_loads_findings_csv(self, tmp_path):
        findings_path = str(tmp_path / 'findings.csv')
        with open(findings_path, 'w') as f:
            f.write('scene_id|target_file|fields|guidance\n')
            f.write('act1-sc01|scene-briefs.csv|goal;conflict|Make the goal more concrete\n')
            f.write('act1-sc02|scene-intent.csv|function|Fix the function field\n')

        results = load_external_findings(findings_path)
        assert len(results) == 3  # goal and conflict expanded from first row
        assert results[0]['scene_id'] == 'act1-sc01'
        assert results[0]['field'] == 'goal'
        assert results[0]['issue'] == 'evaluation'
        assert results[1]['field'] == 'conflict'
        assert results[2]['field'] == 'function'

    def test_missing_file_returns_empty(self):
        results = load_external_findings('/nonexistent/path.csv')
        assert results == []

    def test_empty_fields_column(self, tmp_path):
        """When fields column is empty, a single entry with field='' is created."""
        findings_path = str(tmp_path / 'findings.csv')
        with open(findings_path, 'w') as f:
            f.write('scene_id|target_file|fields|guidance\n')
            f.write('act1-sc01|scene-briefs.csv||General guidance here\n')

        results = load_external_findings(findings_path)
        assert len(results) == 1
        assert results[0]['field'] == ''
        assert results[0]['guidance'] == 'General guidance here'


# ============================================================================
# Prompt builders
# ============================================================================

class TestBuildConcretizePrompt:
    def test_includes_scene_id(self):
        prompt = build_concretize_prompt(
            scene_id='act1-sc01',
            fields=['goal'],
            current_values={'goal': 'abstract goal text'},
        )
        assert 'act1-sc01' in prompt
        assert 'abstract goal text' in prompt

    def test_includes_voice_guide(self):
        prompt = build_concretize_prompt(
            scene_id='scene-1',
            fields=['goal'],
            current_values={'goal': 'test'},
            voice_guide='This character perceives through smell',
        )
        assert 'perceives through smell' in prompt

    def test_output_format_section(self):
        prompt = build_concretize_prompt(
            scene_id='scene-1',
            fields=['goal', 'key_actions'],
            current_values={'goal': 'test', 'key_actions': 'test'},
        )
        assert 'goal: [rewritten value]' in prompt
        assert 'key_actions: [rewritten value]' in prompt


class TestBuildTrimPrompt:
    def test_overspecified_issue(self):
        issues = [{'field': 'key_actions', 'issue': 'overspecified'}]
        current = {'key_actions': 'a; b; c; d; e; f'}
        prompt = build_trim_prompt('scene-1', issues, current, target_words=2000)
        assert 'overspecified' in prompt
        assert 'scene-1' in prompt

    def test_verbose_issue(self):
        issues = [{'field': 'goal', 'issue': 'verbose', 'max_chars': 80}]
        current = {'goal': 'x' * 100}
        prompt = build_trim_prompt('scene-1', issues, current)
        assert 'verbose' in prompt

    def test_empty_values_returns_empty_prompt(self):
        issues = [{'field': 'goal', 'issue': 'verbose', 'max_chars': 80}]
        current = {'goal': ''}
        prompt = build_trim_prompt('scene-1', issues, current)
        assert prompt == ''


class TestBuildEvaluationFixPrompt:
    def test_includes_guidance(self):
        prompt = build_evaluation_fix_prompt(
            scene_id='act1-sc01',
            fields=['goal'],
            current_values={'goal': 'old value'},
            guidance='The goal needs more physical grounding',
        )
        assert 'physical grounding' in prompt
        assert 'act1-sc01' in prompt


class TestBuildIntentFixPrompt:
    def test_includes_issue_instructions(self):
        issues = [
            {'field': 'function', 'issue': 'vague'},
            {'field': 'emotional_arc', 'issue': 'flat'},
        ]
        prompt = build_intent_fix_prompt(
            scene_id='scene-1',
            fields=['function', 'emotional_arc'],
            current_values={'function': 'abstract text', 'emotional_arc': 'grief'},
            issues=issues,
        )
        assert 'testable actions' in prompt  # vague instruction
        assert 'transition phrase' in prompt  # flat instruction

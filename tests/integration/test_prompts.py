"""Integration tests for storyforge.prompts — scene drafting prompt builders.

Tests the library functions directly, verifying they produce correct prompt
text containing expected scene data, CSV fields, voice profile integration,
coaching level variations, and brief-based prompt construction.
"""

import os
import shutil

import pytest

from storyforge.prompts import (
    read_yaml_field,
    _strip_yaml_value,
    load_ai_tell_words,
    build_ai_tell_constraint,
    load_voice_profile,
    merge_banned_words,
    _read_csv_header_and_rows,
    read_csv_field,
    _get_csv_row_dict,
    get_scene_metadata,
    get_scene_intent,
    get_previous_scene,
    list_reference_files,
    get_scene_status,
    build_weighted_directive,
    extract_craft_sections,
    build_scene_prompt,
    build_scene_prompt_from_briefs,
    _build_coach_steps,
    _build_strict_steps,
    _build_full_steps,
    _get_pov_restraint_level,
    _build_pov_restraint_block,
    _load_prose_exemplars,
)


# ============================================================================
# YAML reading
# ============================================================================

class TestReadYamlField:
    """Tests for the simple YAML reader that mirrors bash grep/sed."""

    def test_reads_nested_field(self, project_dir):
        yaml_file = os.path.join(project_dir, 'storyforge.yaml')
        result = read_yaml_field(yaml_file, 'project.title')
        assert result == "The Cartographer's Silence"

    def test_reads_nested_genre(self, project_dir):
        yaml_file = os.path.join(project_dir, 'storyforge.yaml')
        result = read_yaml_field(yaml_file, 'project.genre')
        assert result == 'fantasy'

    def test_reads_top_level_field(self, project_dir):
        yaml_file = os.path.join(project_dir, 'storyforge.yaml')
        result = read_yaml_field(yaml_file, 'phase')
        assert result == 'drafting'

    def test_missing_field_returns_empty(self, project_dir):
        yaml_file = os.path.join(project_dir, 'storyforge.yaml')
        result = read_yaml_field(yaml_file, 'nonexistent.field')
        assert result == ''

    def test_missing_file_returns_empty(self):
        result = read_yaml_field('/tmp/nonexistent-yaml-file.yaml', 'project.title')
        assert result == ''


class TestStripYamlValue:
    """Tests for quote-stripping helper."""

    def test_strips_double_quotes(self):
        assert _strip_yaml_value('"hello world"') == 'hello world'

    def test_strips_single_quotes(self):
        assert _strip_yaml_value("'hello world'") == 'hello world'

    def test_no_quotes_unchanged(self):
        assert _strip_yaml_value('bare value') == 'bare value'

    def test_strips_whitespace(self):
        assert _strip_yaml_value('  padded  ') == 'padded'


# ============================================================================
# AI-tell words
# ============================================================================

class TestLoadAiTellWords:
    """Tests for loading the AI-tell vocabulary list."""

    def test_loads_words_from_plugin(self, plugin_dir):
        words = load_ai_tell_words(plugin_dir)
        assert len(words) > 0
        # Every entry should have required keys
        for w in words:
            assert 'word' in w
            assert 'severity' in w

    def test_contains_known_high_severity_word(self, plugin_dir):
        words = load_ai_tell_words(plugin_dir)
        high_words = [w['word'] for w in words if w['severity'] == 'high']
        assert 'delve' in high_words

    def test_missing_plugin_dir_returns_empty(self):
        result = load_ai_tell_words('/tmp/nonexistent-plugin')
        assert result == []


class TestBuildAiTellConstraint:
    """Tests for building the vocabulary constraint block."""

    def test_high_severity_only(self):
        words = [
            {'word': 'delve', 'severity': 'high'},
            {'word': 'vibrant', 'severity': 'medium'},
            {'word': 'tapestry', 'severity': 'high'},
        ]
        result = build_ai_tell_constraint(words, severity='high')
        assert 'delve' in result
        assert 'tapestry' in result
        assert 'vibrant' not in result

    def test_medium_includes_both(self):
        words = [
            {'word': 'delve', 'severity': 'high'},
            {'word': 'vibrant', 'severity': 'medium'},
        ]
        result = build_ai_tell_constraint(words, severity='medium')
        assert 'delve' in result
        assert 'vibrant' in result

    def test_empty_words_returns_empty(self):
        assert build_ai_tell_constraint([]) == ''

    def test_constraint_has_vocabulary_header(self):
        words = [{'word': 'delve', 'severity': 'high'}]
        result = build_ai_tell_constraint(words)
        assert 'VOCABULARY CONSTRAINT' in result


# ============================================================================
# Voice profile
# ============================================================================

class TestLoadVoiceProfile:
    """Tests for loading voice-profile.csv."""

    def test_loads_project_row(self, project_dir):
        proj, chars = load_voice_profile(project_dir)
        # Project row should have banned_words from the _project row
        assert 'register' in proj
        assert 'literary' in proj['register']

    def test_loads_character_rows(self, project_dir):
        proj, chars = load_voice_profile(project_dir)
        assert 'dorren-hayle' in chars
        assert 'tessa-merrin' in chars

    def test_character_has_voice_data(self, project_dir):
        _, chars = load_voice_profile(project_dir)
        dorren = chars['dorren-hayle']
        assert 'preferred_words' in dorren
        assert 'calibrated' in dorren['preferred_words']

    def test_missing_file_returns_empty(self, tmp_path):
        proj, chars = load_voice_profile(str(tmp_path))
        assert proj == {}
        assert chars == {}


class TestMergeBannedWords:
    """Tests for merging project banned words with AI-tell words."""

    def test_merges_project_and_ai_tell(self):
        profile = {'banned_words': 'journey;beacon'}
        ai_words = [
            {'word': 'delve', 'severity': 'high'},
            {'word': 'vibrant', 'severity': 'medium'},
        ]
        result = merge_banned_words(profile, ai_words)
        assert 'journey' in result
        assert 'beacon' in result
        assert 'delve' in result
        # medium severity should NOT be included (only high)
        assert 'vibrant' not in result

    def test_deduplicates(self):
        profile = {'banned_words': 'delve'}
        ai_words = [{'word': 'delve', 'severity': 'high'}]
        result = merge_banned_words(profile, ai_words)
        assert result.count('delve') == 1

    def test_sorted_output(self):
        profile = {'banned_words': 'zebra;apple'}
        result = merge_banned_words(profile, [])
        assert result == ['apple', 'zebra']


# ============================================================================
# CSV helpers
# ============================================================================

class TestCsvHelpers:
    """Tests for pipe-delimited CSV reading."""

    def test_read_csv_field(self, meta_csv):
        result = read_csv_field(meta_csv, 'act1-sc01', 'title')
        assert result == 'The Finest Cartographer'

    def test_read_csv_field_missing_row(self, meta_csv):
        result = read_csv_field(meta_csv, 'nonexistent', 'title')
        assert result == ''

    def test_read_csv_field_missing_column(self, meta_csv):
        result = read_csv_field(meta_csv, 'act1-sc01', 'nonexistent_col')
        assert result == ''

    def test_get_csv_row_dict(self, meta_csv):
        row = _get_csv_row_dict(meta_csv, 'act1-sc01')
        assert row['title'] == 'The Finest Cartographer'
        assert row['pov'] == 'Dorren Hayle'
        assert row['part'] == '1'

    def test_csv_header_and_rows(self, meta_csv):
        header, rows = _read_csv_header_and_rows(meta_csv)
        assert 'id' in header
        assert 'title' in header
        assert len(rows) >= 2  # at least 2 scenes


# ============================================================================
# Scene metadata and intent
# ============================================================================

class TestSceneMetadata:
    """Tests for get_scene_metadata."""

    def test_returns_formatted_metadata(self, project_dir):
        result = get_scene_metadata('act1-sc01', project_dir)
        assert 'The Finest Cartographer' in result
        assert 'Dorren Hayle' in result
        assert 'morning' in result

    def test_includes_all_header_fields(self, project_dir):
        result = get_scene_metadata('act1-sc01', project_dir)
        for field in ['id', 'seq', 'title', 'part', 'pov', 'location']:
            assert f'{field}:' in result

    def test_missing_scene_returns_empty(self, project_dir):
        result = get_scene_metadata('nonexistent', project_dir)
        assert result == ''


class TestSceneIntent:
    """Tests for get_scene_intent."""

    def test_returns_intent_fields(self, project_dir):
        result = get_scene_intent('act1-sc01', project_dir)
        assert 'action' in result
        assert 'truth' in result

    def test_excludes_id_field(self, project_dir):
        result = get_scene_intent('act1-sc01', project_dir)
        # Should not have 'id: act1-sc01' since id is skipped
        lines = result.split('\n')
        id_lines = [l for l in lines if l.startswith('id:')]
        assert len(id_lines) == 0

    def test_missing_scene_returns_empty(self, project_dir):
        result = get_scene_intent('nonexistent', project_dir)
        assert result == ''


# ============================================================================
# Previous scene
# ============================================================================

class TestGetPreviousScene:
    """Tests for get_previous_scene."""

    def test_first_scene_has_no_previous(self, project_dir):
        result = get_previous_scene('act1-sc01', project_dir)
        assert result == ''

    def test_second_scene_previous_is_first(self, project_dir):
        result = get_previous_scene('act1-sc02', project_dir)
        assert result == 'act1-sc01'

    def test_missing_scene_returns_empty(self, project_dir):
        result = get_previous_scene('nonexistent', project_dir)
        assert result == ''


# ============================================================================
# Reference files
# ============================================================================

class TestListReferenceFiles:
    """Tests for list_reference_files."""

    def test_lists_csv_files(self, project_dir):
        refs = list_reference_files(project_dir)
        csv_refs = [r for r in refs if r.endswith('.csv')]
        assert len(csv_refs) > 0
        assert any('scenes.csv' in r for r in csv_refs)

    def test_lists_markdown_files(self, project_dir):
        refs = list_reference_files(project_dir)
        md_refs = [r for r in refs if r.endswith('.md')]
        assert len(md_refs) > 0

    def test_sorted_output(self, project_dir):
        refs = list_reference_files(project_dir)
        assert refs == sorted(refs)


# ============================================================================
# Scene status
# ============================================================================

class TestSceneStatus:
    """Tests for get_scene_status."""

    def test_briefed_status_from_csv(self, project_dir):
        result = get_scene_status('act1-sc01', project_dir)
        assert result == 'briefed'

    def test_mapped_status_from_csv(self, project_dir):
        result = get_scene_status('new-x1', project_dir)
        assert result == 'mapped'

    def test_missing_scene_returns_pending(self, project_dir):
        result = get_scene_status('nonexistent-scene', project_dir)
        assert result == 'pending'


# ============================================================================
# Weighted directive
# ============================================================================

class TestBuildWeightedDirective:
    """Tests for build_weighted_directive."""

    def test_returns_empty_when_no_weights_file(self, project_dir):
        result = build_weighted_directive(project_dir)
        # Fixture doesn't have craft-weights.csv in working/
        assert result == ''

    def test_builds_directive_with_weights_file(self, project_dir):
        # Create a craft-weights.csv for this test
        weights_dir = os.path.join(project_dir, 'working')
        os.makedirs(weights_dir, exist_ok=True)
        weights_file = os.path.join(weights_dir, 'craft-weights.csv')
        with open(weights_file, 'w') as f:
            f.write('principle|weight|author_weight\n')
            f.write('economy_clarity|8|\n')
            f.write('prose_naturalness|5|\n')
            f.write('fictive_dream|3|\n')
        result = build_weighted_directive(project_dir)
        assert 'Craft Priorities' in result
        assert 'economy clarity' in result
        # Weight 5 should be in medium tier
        assert 'prose naturalness' in result

    def test_author_weight_overrides_base_weight(self, project_dir):
        weights_dir = os.path.join(project_dir, 'working')
        os.makedirs(weights_dir, exist_ok=True)
        weights_file = os.path.join(weights_dir, 'craft-weights.csv')
        with open(weights_file, 'w') as f:
            f.write('principle|weight|author_weight\n')
            f.write('economy_clarity|3|9\n')  # base low, author high
        result = build_weighted_directive(project_dir)
        # Should be in high tier due to author_weight override
        assert 'economy clarity' in result
        assert 'priority: 9/10' in result


# ============================================================================
# Craft engine extraction
# ============================================================================

class TestExtractCraftSections:
    """Tests for extract_craft_sections."""

    def test_extracts_section(self, plugin_dir):
        result = extract_craft_sections(plugin_dir, 2)
        assert len(result) > 0
        assert '## 2.' in result

    def test_multiple_sections_joined(self, plugin_dir):
        result = extract_craft_sections(plugin_dir, 2, 3)
        assert '## 2.' in result
        assert '## 3.' in result
        assert '---' in result

    def test_missing_plugin_returns_empty(self):
        result = extract_craft_sections('/tmp/nonexistent-plugin', 2)
        assert result == ''


# ============================================================================
# Main prompt builder: build_scene_prompt
# ============================================================================

class TestBuildScenePrompt:
    """Tests for the main scene prompt builder."""

    def test_contains_scene_id(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'act1-sc01' in prompt

    def test_contains_project_title(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert "The Cartographer's Silence" in prompt

    def test_contains_genre(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'fantasy' in prompt

    def test_contains_scene_title(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'The Finest Cartographer' in prompt

    def test_contains_scene_metadata(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'Dorren Hayle' in prompt
        assert 'Pressure Cartography Office' in prompt

    def test_contains_scene_intent(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'truth' in prompt

    def test_first_scene_no_previous_scene_instruction(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'first scene' in prompt.lower()

    def test_second_scene_references_previous(self, project_dir):
        prompt = build_scene_prompt('act1-sc02', project_dir)
        assert 'act1-sc01' in prompt

    def test_contains_step_markers(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'STEP 1' in prompt
        assert 'STEP 2' in prompt
        assert 'STEP 3' in prompt

    def test_contains_reference_file_list(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'reference/' in prompt

    def test_voice_guide_mentioned(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'voice guide' in prompt.lower() or 'voice-guide' in prompt.lower()

    def test_character_voice_block_for_pov(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        # Dorren Hayle is POV, should have character voice constraints
        assert 'CHARACTER VOICE' in prompt
        assert 'Dorren Hayle' in prompt

    def test_character_preferred_words(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        # dorren-hayle has preferred_words containing "calibrated"
        assert 'calibrated' in prompt

    def test_banned_words_included(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        # Project-level banned words include journey, beacon, etc.
        assert 'VOCABULARY CONSTRAINT' in prompt
        assert 'journey' in prompt

    def test_register_included(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir)
        assert 'PROSE REGISTER' in prompt
        assert 'literary' in prompt


# ============================================================================
# Coaching level variations
# ============================================================================

class TestCoachingLevelVariations:
    """Tests for coaching level-specific prompt construction."""

    def test_full_mode_contains_draft_instruction(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir, coaching_level='full')
        assert 'DRAFT THE SCENE' in prompt or 'Write the complete scene' in prompt

    def test_coach_mode_contains_brief_instruction(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir, coaching_level='coach')
        assert 'COACH mode' in prompt
        assert 'Do NOT write prose' in prompt

    def test_strict_mode_contains_constraint_instruction(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir, coaching_level='strict')
        assert 'STRICT mode' in prompt
        assert 'Do NOT write prose' in prompt

    def test_full_api_mode_output_format(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
        assert '=== SCENE: act1-sc01 ===' in prompt
        assert '=== END SCENE: act1-sc01 ===' in prompt

    def test_full_cli_mode_git_commit(self, project_dir):
        prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=False)
        assert 'git commit' in prompt
        assert 'git push' in prompt


# ============================================================================
# Coach and strict step builders (unit-level)
# ============================================================================

class TestBuildCoachSteps:
    """Tests for _build_coach_steps."""

    def test_includes_coach_mode_notice(self):
        lines = _build_coach_steps('test-scene', 'Test Title', api_mode=False)
        text = '\n'.join(lines)
        assert 'COACH mode' in text

    def test_api_mode_outputs_markdown(self):
        lines = _build_coach_steps('test-scene', 'Test Title', api_mode=True)
        text = '\n'.join(lines)
        assert 'Output your scene brief directly as markdown' in text

    def test_cli_mode_saves_to_file(self):
        lines = _build_coach_steps('test-scene', 'Test Title', api_mode=False)
        text = '\n'.join(lines)
        assert 'working/coaching/brief-test-scene.md' in text


class TestBuildStrictSteps:
    """Tests for _build_strict_steps."""

    def test_includes_strict_mode_notice(self):
        lines = _build_strict_steps('test-scene', 'Test Title', api_mode=False)
        text = '\n'.join(lines)
        assert 'STRICT mode' in text

    def test_produces_constraint_list(self):
        lines = _build_strict_steps('test-scene', 'Test Title', api_mode=False)
        text = '\n'.join(lines)
        assert 'constraint list' in text.lower() or 'CONSTRAINT LIST' in text


class TestBuildFullSteps:
    """Tests for _build_full_steps."""

    def test_api_mode_drafts_scene(self):
        lines = _build_full_steps('test-scene', 'Test Title', 'reference/voice-guide.md', api_mode=True)
        text = '\n'.join(lines)
        assert 'DRAFT THE SCENE' in text

    def test_cli_mode_has_quality_review(self):
        lines = _build_full_steps('test-scene', 'Test Title', 'reference/voice-guide.md', api_mode=False)
        text = '\n'.join(lines)
        assert 'QUALITY REVIEW' in text

    def test_cli_mode_has_git_commit(self):
        lines = _build_full_steps('test-scene', 'Test Title', 'reference/voice-guide.md', api_mode=False)
        text = '\n'.join(lines)
        assert 'GIT COMMIT' in text


# ============================================================================
# POV restraint
# ============================================================================

class TestPovRestraint:
    """Tests for POV restraint level determination."""

    def test_protagonist_gets_maximum(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        level = _get_pov_restraint_level('Dorren Hayle', ref_dir)
        assert level == 'maximum'

    def test_supporting_gets_medium(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        level = _get_pov_restraint_level('Tessa Merrin', ref_dir)
        assert level == 'medium'

    def test_unknown_pov_gets_maximum(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        level = _get_pov_restraint_level('Unknown Character', ref_dir)
        assert level == 'maximum'

    def test_build_pov_restraint_block_protagonist(self, project_dir):
        ref_dir = os.path.join(project_dir, 'reference')
        block = _build_pov_restraint_block('Dorren Hayle', ref_dir)
        assert 'MAXIMUM' in block
        assert 'withholds' in block.lower() or 'sparse' in block.lower()


# ============================================================================
# Brief-aware prompt builder
# ============================================================================

class TestBuildScenePromptFromBriefs:
    """Tests for build_scene_prompt_from_briefs (elaboration pipeline)."""

    def test_contains_scene_brief_header(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
        assert '## Scene Brief: act1-sc01' in prompt

    def test_contains_project_title(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
        assert "The Cartographer's Silence" in prompt

    def test_contains_brief_data(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
        # From scene-briefs.csv: goal, conflict, etc.
        assert 'quarterly pressure audit' in prompt

    def test_full_coaching_has_task_block(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs(
            'act1-sc01', project_dir, plugin_dir, coaching_level='full')
        assert 'Write the complete prose' in prompt

    def test_coach_coaching_has_writing_guide(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs(
            'act1-sc01', project_dir, plugin_dir, coaching_level='coach')
        assert 'Do NOT write the prose' in prompt

    def test_strict_coaching_has_reference_format(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs(
            'act1-sc01', project_dir, plugin_dir, coaching_level='strict')
        assert 'Do NOT add creative interpretation' in prompt

    def test_dependency_scenes_included(self, project_dir, plugin_dir):
        # act2-sc03 depends on act1-sc02 and new-x1
        prompt = build_scene_prompt_from_briefs(
            'act2-sc03', project_dir, plugin_dir, dep_scenes=['act1-sc01'])
        assert 'Dependency Scenes' in prompt
        assert 'act1-sc01' in prompt

    def test_full_coaching_has_prohibition_block(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs(
            'act1-sc01', project_dir, plugin_dir, coaching_level='full')
        assert 'CRITICAL PROSE RULES' in prompt
        assert 'NO antithesis framing' in prompt

    def test_coach_coaching_no_prohibition_block(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs(
            'act1-sc01', project_dir, plugin_dir, coaching_level='coach')
        assert 'CRITICAL PROSE RULES' not in prompt

    def test_missing_scene_returns_error(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs(
            'nonexistent-scene', project_dir, plugin_dir)
        assert 'ERROR' in prompt

    def test_voice_guide_included(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
        assert 'Voice Guide' in prompt

    def test_character_voice_for_pov(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
        # Dorren Hayle is POV; should include character voice constraints
        assert 'CHARACTER VOICE' in prompt
        assert 'calibrated' in prompt

    def test_banned_words_included(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
        assert 'VOCABULARY CONSTRAINT' in prompt

    def test_physical_state_context(self, project_dir, plugin_dir):
        # act2-sc03 has physical_state_in = 'archive-key-dorren;exhaustion-tessa'
        prompt = build_scene_prompt_from_briefs('act2-sc03', project_dir, plugin_dir)
        assert 'Physical States' in prompt

    def test_key_dialogue_checklist(self, project_dir, plugin_dir):
        prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin_dir)
        # act1-sc01 has key_dialogue in briefs
        assert 'Key dialogue checklist' in prompt or 'key_dialogue' in prompt


# ============================================================================
# Prose exemplars
# ============================================================================

class TestLoadProseExemplars:
    """Tests for _load_prose_exemplars."""

    def test_returns_empty_when_no_files(self, project_dir):
        result = _load_prose_exemplars(project_dir, 'Dorren Hayle')
        assert result == ''

    def test_loads_flat_exemplars(self, project_dir):
        # Create a prose-exemplars.md file
        exemplars_dir = os.path.join(project_dir, 'reference')
        with open(os.path.join(exemplars_dir, 'prose-exemplars.md'), 'w') as f:
            f.write('The morning light cut across the desk.\n'
                    'She measured twice, wrote once.')
        result = _load_prose_exemplars(project_dir)
        assert 'Voice Calibration' in result
        assert 'morning light' in result

    def test_per_pov_exemplars_preferred(self, project_dir):
        # Create both flat and per-POV files
        exemplars_dir = os.path.join(project_dir, 'reference', 'exemplars')
        os.makedirs(exemplars_dir, exist_ok=True)
        with open(os.path.join(exemplars_dir, 'dorren-hayle.md'), 'w') as f:
            f.write('Dorren-specific exemplar text.')
        with open(os.path.join(project_dir, 'reference', 'prose-exemplars.md'), 'w') as f:
            f.write('Generic exemplar text.')
        result = _load_prose_exemplars(project_dir, 'Dorren Hayle')
        assert 'Dorren-specific' in result
        assert 'Generic' not in result

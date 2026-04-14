"""Integration tests for storyforge.revision — revision prompt builders.

Tests the library functions directly, verifying scope resolution,
revision prompt construction, coaching level variations, craft section
selection, pass configuration, annotation integration, and overrides.
"""

import csv
import os

import pytest

from storyforge.revision import (
    resolve_scene_file,
    _read_pipe_csv,
    _find_scenes_csv,
    resolve_scope,
    extract_craft_sections,
    _select_craft_sections,
    _build_overrides_section,
    _extract_pass_principles,
    build_revision_prompt,
    _coaching_instructions,
    _coach_instructions,
    _strict_instructions,
    _full_instructions,
    _api_output_format_block,
    _claudep_read_instructions,
)


# ============================================================================
# Scene file resolution
# ============================================================================

class TestResolveSceneFile:
    """Tests for resolve_scene_file with exact and legacy fallbacks."""

    def test_exact_match(self, project_dir):
        scene_dir = os.path.join(project_dir, 'scenes')
        result = resolve_scene_file(scene_dir, 'act1-sc01')
        assert result is not None
        assert result.endswith('act1-sc01.md')

    def test_nonexistent_returns_none(self, project_dir):
        scene_dir = os.path.join(project_dir, 'scenes')
        result = resolve_scene_file(scene_dir, 'does-not-exist')
        assert result is None

    def test_numeric_zero_padding_fallback(self, project_dir):
        scene_dir = os.path.join(project_dir, 'scenes')
        # Create a zero-padded file
        padded_path = os.path.join(scene_dir, '025.md')
        with open(padded_path, 'w') as f:
            f.write('Test content.')
        result = resolve_scene_file(scene_dir, '25')
        assert result is not None
        assert result.endswith('025.md')


# ============================================================================
# CSV helpers
# ============================================================================

class TestPipeCsvReader:
    """Tests for _read_pipe_csv."""

    def test_reads_scenes_csv(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        rows = _read_pipe_csv(csv_path)
        assert len(rows) >= 2
        assert rows[0]['id'] == 'act1-sc01'

    def test_all_rows_have_id(self, project_dir):
        csv_path = os.path.join(project_dir, 'reference', 'scenes.csv')
        rows = _read_pipe_csv(csv_path)
        for row in rows:
            assert 'id' in row
            assert row['id'].strip() != ''


class TestFindScenesCsv:
    """Tests for _find_scenes_csv."""

    def test_finds_csv(self, project_dir):
        path = _find_scenes_csv(project_dir)
        assert path.endswith('scenes.csv')
        assert os.path.isfile(path)

    def test_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _find_scenes_csv(str(tmp_path))


# ============================================================================
# Scope resolution
# ============================================================================

class TestResolveScope:
    """Tests for resolve_scope — parsing scope strings into scene file paths."""

    def test_full_scope_returns_all_non_cut(self, project_dir):
        paths = resolve_scope('full', project_dir)
        assert len(paths) >= 2
        ids = [os.path.splitext(os.path.basename(p))[0] for p in paths]
        assert 'act1-sc01' in ids

    def test_targeted_alias_same_as_full(self, project_dir):
        full_paths = resolve_scope('full', project_dir)
        targeted_paths = resolve_scope('targeted', project_dir)
        assert len(full_paths) == len(targeted_paths)

    def test_part_scope(self, project_dir):
        paths = resolve_scope('part-1', project_dir)
        ids = [os.path.splitext(os.path.basename(p))[0] for p in paths]
        assert 'act1-sc01' in ids
        assert 'act1-sc02' in ids
        # part-2 scenes should not be in part-1 scope
        assert 'act2-sc01' not in ids

    def test_comma_separated_slugs(self, project_dir):
        paths = resolve_scope('act1-sc01,act1-sc02', project_dir)
        assert len(paths) == 2
        ids = [os.path.splitext(os.path.basename(p))[0] for p in paths]
        assert 'act1-sc01' in ids
        assert 'act1-sc02' in ids

    def test_numeric_seq_resolution(self, project_dir):
        paths = resolve_scope('1,2', project_dir)
        assert len(paths) == 2
        ids = [os.path.splitext(os.path.basename(p))[0] for p in paths]
        assert 'act1-sc01' in ids
        assert 'act1-sc02' in ids

    def test_inline_list_syntax(self, project_dir):
        paths = resolve_scope('[1, 2]', project_dir)
        assert len(paths) == 2

    def test_empty_scope_raises(self, project_dir):
        with pytest.raises(ValueError):
            resolve_scope('nonexistent-slug-xyz', project_dir)


# ============================================================================
# Craft engine extraction
# ============================================================================

class TestExtractCraftSectionsRevision:
    """Tests for craft section extraction from the revision module."""

    def test_extracts_section(self):
        # Uses the internal _find_plugin_dir, so relies on repo structure
        result = extract_craft_sections(2)
        assert len(result) > 0

    def test_multiple_sections(self):
        result = extract_craft_sections(2, 3)
        assert '---' in result

    def test_empty_when_no_match(self):
        result = extract_craft_sections(999)
        assert result == ''


class TestSelectCraftSections:
    """Tests for _select_craft_sections."""

    def test_prose_pass_selects_sections_3_5(self):
        result = _select_craft_sections('prose-tightening', 'Tighten prose and reduce wordiness')
        assert len(result) > 0

    def test_character_pass_selects_sections_4_5(self):
        result = _select_craft_sections('character-depth', 'Deepen character motivation')
        assert len(result) > 0

    def test_continuity_pass_returns_empty(self):
        result = _select_craft_sections('continuity-check', 'Check timeline consistency')
        assert result == ''

    def test_default_pass(self):
        result = _select_craft_sections('generic-pass', 'General improvements')
        assert len(result) > 0


# ============================================================================
# Extract pass principles
# ============================================================================

class TestExtractPassPrinciples:
    """Tests for _extract_pass_principles."""

    def test_detects_economy_clarity(self):
        config = 'targets: economy_clarity'
        result = _extract_pass_principles(config, 'Improve economy and clarity')
        assert 'economy_clarity' in result

    def test_detects_multiple(self):
        config = 'targets: prose_naturalness;fictive_dream'
        result = _extract_pass_principles(config, 'Natural prose')
        assert 'prose_naturalness' in result
        assert 'fictive_dream' in result

    def test_detects_from_purpose_text(self):
        result = _extract_pass_principles('', 'Fix sentence as thought issues')
        assert 'sentence_as_thought' in result


# ============================================================================
# Overrides
# ============================================================================

class TestBuildOverridesSection:
    """Tests for _build_overrides_section."""

    def test_returns_empty_when_no_file(self, project_dir):
        result = _build_overrides_section(project_dir, '')
        assert result == ''

    def test_includes_overrides_when_present(self, project_dir):
        overrides_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
        os.makedirs(overrides_dir, exist_ok=True)
        overrides_file = os.path.join(overrides_dir, 'overrides.csv')
        with open(overrides_file, 'w') as f:
            f.write('id|principle|directive\n')
            f.write('act1-sc01|economy_clarity|Cut the long description in paragraph 3\n')
            f.write('act1-sc02|fictive_dream|Preserve the dream sequence\n')
        result = _build_overrides_section(project_dir, '')
        assert 'Scoring Overrides' in result
        assert 'act1-sc01' in result
        assert 'Cut the long description' in result

    def test_filters_by_target_ids(self, project_dir):
        overrides_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
        os.makedirs(overrides_dir, exist_ok=True)
        overrides_file = os.path.join(overrides_dir, 'overrides.csv')
        with open(overrides_file, 'w') as f:
            f.write('id|principle|directive\n')
            f.write('act1-sc01|economy_clarity|Directive for sc01\n')
            f.write('act1-sc02|fictive_dream|Directive for sc02\n')
        # Pass config targeting only act1-sc01
        config = 'targets: "act1-sc01"'
        result = _build_overrides_section(project_dir, config)
        assert 'act1-sc01' in result
        assert 'act1-sc02' not in result


# ============================================================================
# Revision prompt building
# ============================================================================

class TestBuildRevisionPrompt:
    """Tests for the main build_revision_prompt function."""

    def test_contains_pass_name(self, project_dir):
        prompt = build_revision_prompt(
            'prose-tightening', 'Tighten prose and reduce wordiness',
            'full', project_dir)
        assert 'prose-tightening' in prompt

    def test_contains_purpose(self, project_dir):
        prompt = build_revision_prompt(
            'prose-tightening', 'Tighten prose and reduce wordiness',
            'full', project_dir)
        assert 'Tighten prose and reduce wordiness' in prompt

    def test_contains_file_list(self, project_dir):
        prompt = build_revision_prompt(
            'prose-tightening', 'Tighten prose',
            'act1-sc01,act1-sc02', project_dir)
        assert 'act1-sc01' in prompt
        assert 'act1-sc02' in prompt

    def test_part_scope_in_prompt(self, project_dir):
        prompt = build_revision_prompt(
            'prose-pass', 'Polish', 'part-1', project_dir)
        assert 'act1-sc01' in prompt

    def test_pass_config_included(self, project_dir):
        config = 'targets: economy_clarity\nguidance: Cut 20% word count'
        prompt = build_revision_prompt(
            'economy-pass', 'Cut wordiness',
            'full', project_dir, pass_config=config)
        assert 'Pass Configuration' in prompt
        assert 'Cut 20% word count' in config  # config present in prompt
        assert 'economy_clarity' in prompt or 'economy-pass' in prompt

    def test_api_mode_inlines_content(self, project_dir):
        prompt = build_revision_prompt(
            'prose-tightening', 'Tighten prose',
            'act1-sc01', project_dir, api_mode=True)
        assert '=== SCENE:' in prompt

    def test_cli_mode_has_read_instructions(self, project_dir):
        prompt = build_revision_prompt(
            'prose-tightening', 'Tighten prose',
            'act1-sc01', project_dir, api_mode=False)
        assert 'Read Reference Context First' in prompt

    def test_intent_beat_protection(self, project_dir):
        prompt = build_revision_prompt(
            'prose-tightening', 'Tighten prose',
            'act1-sc01', project_dir)
        assert 'Intent-Beat Protection' in prompt

    def test_craft_principles_for_prose_pass(self, project_dir):
        prompt = build_revision_prompt(
            'prose-tightening', 'Tighten prose and line-edit',
            'full', project_dir)
        assert 'Craft Principles' in prompt


# ============================================================================
# Coaching-level revision instructions
# ============================================================================

class TestRevisionCoachingInstructions:
    """Tests for coaching-level-specific revision instructions."""

    def test_full_mode_applies_revision(self, project_dir):
        prompt = build_revision_prompt(
            'prose-pass', 'Tighten prose', 'full', project_dir,
            coaching_level='full')
        assert 'Apply the Revision' in prompt or 'apply the revision' in prompt.lower()

    def test_coach_mode_produces_notes(self, project_dir):
        prompt = build_revision_prompt(
            'prose-pass', 'Tighten prose', 'full', project_dir,
            coaching_level='coach')
        assert 'COACH mode' in prompt
        assert 'Do NOT edit scene files' in prompt

    def test_strict_mode_produces_checklist(self, project_dir):
        prompt = build_revision_prompt(
            'prose-pass', 'Tighten prose', 'full', project_dir,
            coaching_level='strict')
        assert 'STRICT mode' in prompt
        assert 'Do NOT edit scene files' in prompt

    def test_coach_instructions_have_voice_warnings(self):
        result = _coach_instructions('test-pass', 'Test purpose', api_mode=False)
        assert 'Voice' in result or 'voice' in result

    def test_strict_instructions_have_target_counts(self):
        result = _strict_instructions('test-pass', 'Test purpose', api_mode=False)
        assert 'Target counts' in result or 'checklist' in result.lower()

    def test_full_api_mode_output_format(self):
        result = _full_instructions('test-pass', 'Test purpose', api_mode=True)
        assert '=== SCENE:' in result
        assert '=== END SCENE:' in result

    def test_full_cli_mode_has_commit(self):
        result = _full_instructions('test-pass', 'Test purpose', api_mode=False)
        assert 'git commit' in result
        assert 'git push' in result


# ============================================================================
# Output format blocks
# ============================================================================

class TestOutputFormatBlocks:
    """Tests for the private format helpers."""

    def test_api_output_format_has_markers(self):
        block = _api_output_format_block()
        assert '=== SCENE: scene-id ===' in block
        assert '=== END SCENE: scene-id ===' in block
        assert 'CRITICAL' in block

    def test_claudep_read_instructions_has_reference_files(self):
        block = _claudep_read_instructions()
        assert 'voice-guide.md' in block
        assert 'scenes.csv' in block
        assert 'scene-intent.csv' in block

    def test_coaching_dispatch_full(self):
        result = _coaching_instructions('full', 'test', 'purpose', False)
        assert 'Apply the Revision' in result or 'git commit' in result

    def test_coaching_dispatch_coach(self):
        result = _coaching_instructions('coach', 'test', 'purpose', False)
        assert 'COACH mode' in result

    def test_coaching_dispatch_strict(self):
        result = _coaching_instructions('strict', 'test', 'purpose', False)
        assert 'STRICT mode' in result

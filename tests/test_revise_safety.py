"""Tests for revision safety improvements.

Covers: truncation guard, pre-write safety checks, max_output_tokens helper,
and rubric/exemplar loading.
"""

import csv
import json
import os


# ============================================================================
# max_output_tokens
# ============================================================================

class TestMaxOutputTokens:
    def test_opus_returns_128k(self):
        from storyforge.api import max_output_tokens
        assert max_output_tokens('claude-opus-4-6') == 128000

    def test_sonnet_returns_64k(self):
        from storyforge.api import max_output_tokens
        assert max_output_tokens('claude-sonnet-4-6') == 64000

    def test_haiku_returns_16k(self):
        from storyforge.api import max_output_tokens
        assert max_output_tokens('claude-haiku-4-5-20251001') == 16384

    def test_unknown_model_returns_default(self):
        from storyforge.api import max_output_tokens
        result = max_output_tokens('claude-unknown-99')
        assert result == 32768


# ============================================================================
# Truncation guard
# ============================================================================

class TestTruncationGuard:
    def test_truncated_response_discards_last_scene(self, tmp_path):
        """When stop_reason=max_tokens, the last scene without an end marker
        should be discarded to prevent writing truncated content."""
        from storyforge.parsing import extract_scenes_from_response

        response_text = (
            '=== SCENE: complete-scene ===\n'
            'This scene is complete.\n'
            '=== END SCENE: complete-scene ===\n\n'
            '=== SCENE: truncated-scene ===\n'
            'This scene was cut off mid-sent'
        )

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(
            response_text, scenes_dir, stop_reason='max_tokens'
        )

        # Complete scene should be written
        assert 'complete-scene' in result
        assert os.path.isfile(os.path.join(scenes_dir, 'complete-scene.md'))

        # Truncated scene should NOT be written
        assert 'truncated-scene' not in result
        assert not os.path.isfile(os.path.join(scenes_dir, 'truncated-scene.md'))

    def test_end_turn_writes_last_scene_normally(self, tmp_path):
        """When stop_reason=end_turn (default), the last scene without an end
        marker should still be written (backward-compatible behavior)."""
        from storyforge.parsing import extract_scenes_from_response

        response_text = (
            '=== SCENE: only-scene ===\n'
            'Content without end marker.\n'
        )

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(
            response_text, scenes_dir, stop_reason='end_turn'
        )

        assert 'only-scene' in result

    def test_default_stop_reason_is_end_turn(self, tmp_path):
        """Calling without stop_reason should behave like end_turn."""
        from storyforge.parsing import extract_scenes_from_response

        response_text = (
            '=== SCENE: my-scene ===\n'
            'Some content.\n'
        )

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(response_text, scenes_dir)

        assert 'my-scene' in result


# ============================================================================
# Pre-write safety checks
# ============================================================================

class TestPreWriteSafety:
    def test_rejects_mid_sentence_ending(self, tmp_path):
        """Scenes ending mid-sentence should be rejected."""
        from storyforge.parsing import extract_scenes_from_response

        response_text = (
            '=== SCENE: bad-scene ===\n'
            'She walked toward the\n'
            '=== END SCENE: bad-scene ===\n'
        )

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(response_text, scenes_dir)

        assert 'bad-scene' not in result
        assert not os.path.isfile(os.path.join(scenes_dir, 'bad-scene.md'))

    def test_accepts_sentence_ending_with_period(self, tmp_path):
        from storyforge.parsing import extract_scenes_from_response

        response_text = (
            '=== SCENE: good-scene ===\n'
            'She walked toward the door.\n'
            '=== END SCENE: good-scene ===\n'
        )

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(response_text, scenes_dir)

        assert 'good-scene' in result

    def test_accepts_sentence_ending_with_quote(self, tmp_path):
        from storyforge.parsing import extract_scenes_from_response

        response_text = (
            '=== SCENE: quote-scene ===\n'
            '"I\'m done."\n'
            '=== END SCENE: quote-scene ===\n'
        )

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(response_text, scenes_dir)

        assert 'quote-scene' in result

    def test_accepts_sentence_ending_with_em_dash(self, tmp_path):
        from storyforge.parsing import extract_scenes_from_response

        response_text = (
            '=== SCENE: dash-scene ===\n'
            'She turned away\u2014\n'
            '=== END SCENE: dash-scene ===\n'
        )

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(response_text, scenes_dir)

        assert 'dash-scene' in result

    def test_rejects_word_count_collapse(self, tmp_path):
        """If the new version is <60% of the original word count, reject it."""
        from storyforge.parsing import extract_scenes_from_response

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)

        # Write an existing scene with 200 words
        original = ' '.join(['word'] * 200) + '.'
        with open(os.path.join(scenes_dir, 'collapse-scene.md'), 'w') as f:
            f.write(original)

        # Try to overwrite with only 50 words (25% of original)
        short_content = ' '.join(['short'] * 50) + '.'
        response_text = (
            f'=== SCENE: collapse-scene ===\n'
            f'{short_content}\n'
            f'=== END SCENE: collapse-scene ===\n'
        )

        result = extract_scenes_from_response(response_text, scenes_dir)

        # Should be rejected
        assert 'collapse-scene' not in result
        # Original content should be preserved
        with open(os.path.join(scenes_dir, 'collapse-scene.md')) as f:
            assert f.read() == original

    def test_allows_moderate_word_count_reduction(self, tmp_path):
        """A 30% reduction (70% of original) should be allowed."""
        from storyforge.parsing import extract_scenes_from_response

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)

        original = ' '.join(['word'] * 200) + '.'
        with open(os.path.join(scenes_dir, 'trim-scene.md'), 'w') as f:
            f.write(original)

        # 140 words = 70% of 200 — should be allowed
        trimmed = ' '.join(['trimmed'] * 140) + '.'
        response_text = (
            f'=== SCENE: trim-scene ===\n'
            f'{trimmed}\n'
            f'=== END SCENE: trim-scene ===\n'
        )

        result = extract_scenes_from_response(response_text, scenes_dir)
        assert 'trim-scene' in result

    def test_allows_overwrite_of_short_scenes(self, tmp_path):
        """Scenes under 100 words should not trigger the collapse check."""
        from storyforge.parsing import extract_scenes_from_response

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)

        original = 'A very short scene.'
        with open(os.path.join(scenes_dir, 'short-scene.md'), 'w') as f:
            f.write(original)

        response_text = (
            '=== SCENE: short-scene ===\n'
            'Replaced.\n'
            '=== END SCENE: short-scene ===\n'
        )

        result = extract_scenes_from_response(response_text, scenes_dir)
        assert 'short-scene' in result


# ============================================================================
# Rubric loading
# ============================================================================

class TestRubricLoading:
    def test_loads_kill_darlings_rubric(self):
        from storyforge.revision import _load_rubric_sections
        result = _load_rubric_sections(['kill_darlings'])
        assert 'Kill Your Darlings' in result
        assert '5 (Masterful)' in result or '**5' in result
        assert '1 (Absent)' in result or '**1' in result

    def test_loads_multiple_principles(self):
        from storyforge.revision import _load_rubric_sections
        result = _load_rubric_sections(['economy_clarity', 'pacing_variety'])
        assert 'Economy and Clarity' in result
        assert 'Pacing' in result

    def test_returns_empty_for_unknown_principle(self):
        from storyforge.revision import _load_rubric_sections
        result = _load_rubric_sections(['nonexistent_principle_xyz'])
        assert result == ''

    def test_returns_empty_for_empty_list(self):
        from storyforge.revision import _load_rubric_sections
        result = _load_rubric_sections([])
        assert result == ''


class TestAuthorExemplars:
    def test_loads_matching_exemplars(self, tmp_path):
        from storyforge.revision import _load_author_exemplars

        exemplars = tmp_path / 'working' / 'exemplars.csv'
        exemplars.parent.mkdir(parents=True)
        with open(exemplars, 'w') as f:
            f.write('principle|scene_id|score|excerpt|cycle\n')
            f.write('economy_clarity|test-scene|5|The prose was lean.|3\n')
            f.write('kill_darlings|other-scene|4|Every word earned its place.|3\n')
            f.write('pacing_variety|third-scene|5|Unrelated exemplar.|3\n')

        result = _load_author_exemplars(str(tmp_path), ['economy_clarity'])
        assert 'The prose was lean' in result
        assert 'Every word earned' not in result

    def test_returns_empty_when_no_file(self, tmp_path):
        from storyforge.revision import _load_author_exemplars
        result = _load_author_exemplars(str(tmp_path), ['economy_clarity'])
        assert result == ''


class TestExtractPassPrinciples:
    def test_extracts_from_purpose(self):
        from storyforge.revision import _extract_pass_principles
        result = _extract_pass_principles('', 'Improve kill_darlings and economy_clarity')
        assert 'kill_darlings' in result
        assert 'economy_clarity' in result

    def test_extracts_from_config(self):
        from storyforge.revision import _extract_pass_principles
        config = 'targets: pacing_variety;show_dont_tell'
        result = _extract_pass_principles(config, '')
        assert 'pacing_variety' in result
        assert 'show_dont_tell' in result

    def test_returns_empty_for_no_match(self):
        from storyforge.revision import _extract_pass_principles
        result = _extract_pass_principles('', 'just some random text')
        assert result == []

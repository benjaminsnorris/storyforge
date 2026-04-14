"""Tests for storyforge.parsing — scene content extraction.

Covers: extract_scenes_from_response, extract_single_scene, extract_api_response,
clean_scene_content, _trim_blank_lines, _write_scene safety checks
(mid-sentence detection, word count collapse).
"""

import json
import os

import pytest

from storyforge.parsing import (
    extract_scenes_from_response,
    extract_single_scene,
    extract_api_response,
    clean_scene_content,
    _trim_blank_lines,
)


# ============================================================================
# extract_scenes_from_response
# ============================================================================

class TestExtractScenesFromResponse:
    def test_single_scene(self, tmp_path):
        scene_dir = str(tmp_path / 'scenes')
        os.makedirs(scene_dir)
        response = (
            '=== SCENE: test-scene ===\n'
            'The rain fell steadily on the cobblestones.\n'
            'She walked through the market square.\n'
            '=== END SCENE: test-scene ==='
        )
        written = extract_scenes_from_response(response, scene_dir)
        assert written == ['test-scene']
        content = open(os.path.join(scene_dir, 'test-scene.md')).read()
        assert 'rain fell steadily' in content

    def test_multiple_scenes(self, tmp_path):
        scene_dir = str(tmp_path / 'scenes')
        os.makedirs(scene_dir)
        response = (
            '=== SCENE: scene-one ===\n'
            'First scene content here.\n'
            '=== END SCENE: scene-one ===\n'
            '=== SCENE: scene-two ===\n'
            'Second scene content here.\n'
            '=== END SCENE: scene-two ==='
        )
        written = extract_scenes_from_response(response, scene_dir)
        assert len(written) == 2
        assert 'scene-one' in written
        assert 'scene-two' in written

    def test_discards_truncated_scene_on_max_tokens(self, tmp_path):
        """When stop_reason is max_tokens, the last scene without end marker
        should be discarded."""
        scene_dir = str(tmp_path / 'scenes')
        os.makedirs(scene_dir)
        response = (
            '=== SCENE: complete-scene ===\n'
            'Complete content here.\n'
            '=== END SCENE: complete-scene ===\n'
            '=== SCENE: truncated-scene ===\n'
            'This scene was cut off mid-'
        )
        written = extract_scenes_from_response(response, scene_dir, stop_reason='max_tokens')
        assert 'complete-scene' in written
        assert 'truncated-scene' not in written

    def test_writes_last_scene_without_end_marker_on_end_turn(self, tmp_path):
        """When stop_reason is end_turn, the last scene without end marker
        should still be written (if it passes safety checks)."""
        scene_dir = str(tmp_path / 'scenes')
        os.makedirs(scene_dir)
        response = (
            '=== SCENE: no-end-marker ===\n'
            'The content ends properly here.'
        )
        written = extract_scenes_from_response(response, scene_dir, stop_reason='end_turn')
        assert 'no-end-marker' in written

    def test_skips_parenthetical_ids(self, tmp_path):
        """Scene IDs with parenthetical suffixes should be skipped."""
        scene_dir = str(tmp_path / 'scenes')
        os.makedirs(scene_dir)
        response = (
            '=== SCENE: real-scene ===\n'
            'Real content.\n'
            '=== END SCENE: real-scene ===\n'
            '=== SCENE: note (revised note) ===\n'
            'This should be skipped.\n'
            '=== END SCENE: note (revised note) ==='
        )
        written = extract_scenes_from_response(response, scene_dir)
        assert 'real-scene' in written
        assert len(written) == 1

    def test_rejects_mid_sentence_ending(self, tmp_path):
        """A scene that appears to end mid-sentence should be skipped."""
        scene_dir = str(tmp_path / 'scenes')
        os.makedirs(scene_dir)
        response = (
            '=== SCENE: mid-sentence ===\n'
            'She walked to the\n'
            '=== END SCENE: mid-sentence ==='
        )
        written = extract_scenes_from_response(response, scene_dir)
        assert 'mid-sentence' not in written

    def test_rejects_word_count_collapse(self, tmp_path):
        """If new content is <60% of existing file's word count, reject it."""
        scene_dir = str(tmp_path / 'scenes')
        os.makedirs(scene_dir)
        # Create existing file with 200 words
        existing_content = ' '.join(['word'] * 200)
        with open(os.path.join(scene_dir, 'existing-scene.md'), 'w') as f:
            f.write(existing_content)

        # New content with only 50 words (25% of original)
        short_content = ' '.join(['short'] * 50) + '.'
        response = (
            '=== SCENE: existing-scene ===\n'
            f'{short_content}\n'
            '=== END SCENE: existing-scene ==='
        )
        written = extract_scenes_from_response(response, scene_dir)
        assert 'existing-scene' not in written

    def test_empty_content_skipped(self, tmp_path):
        scene_dir = str(tmp_path / 'scenes')
        os.makedirs(scene_dir)
        response = (
            '=== SCENE: empty-scene ===\n'
            '\n'
            '\n'
            '=== END SCENE: empty-scene ==='
        )
        written = extract_scenes_from_response(response, scene_dir)
        assert 'empty-scene' not in written

    def test_no_scenes_in_response(self, tmp_path):
        scene_dir = str(tmp_path / 'scenes')
        os.makedirs(scene_dir)
        response = 'Just some plain text with no scene markers.'
        written = extract_scenes_from_response(response, scene_dir)
        assert written == []


# ============================================================================
# extract_single_scene
# ============================================================================

class TestExtractSingleScene:
    def test_extracts_from_markers(self):
        response = (
            '=== SCENE: test-scene ===\n'
            'The rain fell.\n'
            'She walked home.\n'
            '=== END SCENE: test-scene ==='
        )
        result = extract_single_scene(response)
        assert result is not None
        assert 'The rain fell.' in result
        assert 'She walked home.' in result

    def test_returns_none_without_markers(self):
        response = 'Just plain text, no markers here.'
        result = extract_single_scene(response)
        assert result is None

    def test_trims_blank_lines(self):
        response = (
            '=== SCENE: test ===\n'
            '\n'
            'Content here.\n'
            '\n'
            '=== END SCENE: test ==='
        )
        result = extract_single_scene(response)
        assert result is not None
        assert result == 'Content here.'

    def test_returns_content_without_end_marker(self):
        """If there is a start marker but no end marker, return the content."""
        response = (
            '=== SCENE: test ===\n'
            'Content without end marker.'
        )
        result = extract_single_scene(response)
        assert result is not None
        assert 'Content without end marker.' in result


# ============================================================================
# extract_api_response
# ============================================================================

class TestExtractApiResponse:
    def test_extracts_text_from_json(self, tmp_path):
        log_file = str(tmp_path / 'response.json')
        data = {
            'content': [
                {'type': 'text', 'text': 'First block.'},
                {'type': 'text', 'text': 'Second block.'},
            ]
        }
        with open(log_file, 'w') as f:
            json.dump(data, f)
        result = extract_api_response(log_file)
        assert 'First block.' in result
        assert 'Second block.' in result

    def test_missing_file_returns_empty(self):
        result = extract_api_response('/nonexistent/response.json')
        assert result == ''

    def test_invalid_json_returns_empty(self, tmp_path):
        log_file = str(tmp_path / 'bad.json')
        with open(log_file, 'w') as f:
            f.write('not valid json')
        result = extract_api_response(log_file)
        assert result == ''

    def test_empty_content_array(self, tmp_path):
        log_file = str(tmp_path / 'empty.json')
        data = {'content': []}
        with open(log_file, 'w') as f:
            json.dump(data, f)
        result = extract_api_response(log_file)
        assert result == ''

    def test_non_text_blocks_ignored(self, tmp_path):
        log_file = str(tmp_path / 'mixed.json')
        data = {
            'content': [
                {'type': 'tool_use', 'name': 'foo'},
                {'type': 'text', 'text': 'Actual text.'},
            ]
        }
        with open(log_file, 'w') as f:
            json.dump(data, f)
        result = extract_api_response(log_file)
        assert result == 'Actual text.'


# ============================================================================
# clean_scene_content
# ============================================================================

class TestCleanSceneContent:
    def test_strips_h1_header(self):
        text = '# The Finest Cartographer\n\nThe rain fell steadily.'
        result = clean_scene_content(text)
        assert result == 'The rain fell steadily.\n'

    def test_strips_h2_header(self):
        text = '## Scene Title\n\nContent here.'
        result = clean_scene_content(text)
        assert result == 'Content here.\n'

    def test_strips_continuity_tracker(self):
        text = (
            'Scene prose here.\n'
            '\n'
            '---\n'
            '\n'
            '# Continuity Tracker Update\n'
            '\n'
            'Some tracking info.'
        )
        result = clean_scene_content(text)
        assert result == 'Scene prose here.\n'

    def test_strips_both_header_and_tracker(self):
        text = (
            '# Title\n'
            '\n'
            'Scene content.\n'
            '\n'
            '---\n'
            '\n'
            '## Continuity Tracker\n'
            '\n'
            'Tracker content.'
        )
        result = clean_scene_content(text)
        assert result == 'Scene content.\n'

    def test_preserves_clean_content(self):
        text = 'The rain fell on the cobblestones.\nShe walked home.\n'
        result = clean_scene_content(text)
        assert 'rain fell' in result
        assert 'walked home' in result

    def test_empty_string(self):
        assert clean_scene_content('') == ''
        assert clean_scene_content('   ') == '   '

    def test_continuity_tracker_without_separator(self):
        """When there is no --- separator, still strip from the header onward."""
        text = (
            'Scene prose here.\n'
            '\n'
            '## Continuity Tracker\n'
            '\n'
            'Some tracking info.'
        )
        result = clean_scene_content(text)
        assert result == 'Scene prose here.\n'

    def test_leading_blank_lines_before_header(self):
        text = '\n\n# Title\n\nContent here.'
        result = clean_scene_content(text)
        assert result == 'Content here.\n'


# ============================================================================
# _trim_blank_lines
# ============================================================================

class TestTrimBlankLines:
    def test_trims_leading_blanks(self):
        assert _trim_blank_lines('\n\nContent') == 'Content'

    def test_trims_trailing_blanks(self):
        assert _trim_blank_lines('Content\n\n') == 'Content'

    def test_trims_both(self):
        assert _trim_blank_lines('\n\nContent\n\n') == 'Content'

    def test_preserves_internal_blanks(self):
        result = _trim_blank_lines('\nPara 1\n\nPara 2\n')
        assert 'Para 1\n\nPara 2' == result

    def test_empty_string(self):
        assert _trim_blank_lines('') == ''
        assert _trim_blank_lines('\n\n') == ''

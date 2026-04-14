"""Tests for prose_analysis shared text utilities."""

import os

from storyforge.prose_analysis import (
    detect_passive_voice,
    extract_dialogue,
    detect_adverbs,
    detect_filler_phrases,
    load_ai_tell_words,
    detect_ai_tell_hits,
)


# ============================================================================
# Passive voice detection
# ============================================================================

class TestPassiveVoice:

    def test_basic_passive(self):
        hits = detect_passive_voice('The ball was thrown by the boy.')
        assert len(hits) == 1
        assert 'was thrown' in hits[0]['match']

    def test_irregular_participle(self):
        hits = detect_passive_voice('The door was broken by the wind.')
        assert len(hits) == 1
        assert 'was broken' in hits[0]['match']

    def test_multiple_passives(self):
        text = 'The cake was eaten. The window was broken. The letter was written.'
        hits = detect_passive_voice(text)
        assert len(hits) == 3

    def test_active_voice_not_flagged(self):
        text = 'She threw the ball. He opened the door. They ran quickly.'
        hits = detect_passive_voice(text)
        assert len(hits) == 0

    def test_past_tense_not_passive(self):
        """'was' followed by non-participle adjective should not flag."""
        hits = detect_passive_voice('She was happy about the result.')
        assert len(hits) == 0

    def test_ed_false_positive(self):
        """Words like 'naked', 'wicked' are not participles."""
        hits = detect_passive_voice('He was naked in the rain.')
        assert len(hits) == 0

    def test_being_passive(self):
        hits = detect_passive_voice('The house is being built.')
        assert len(hits) >= 1

    def test_empty_text(self):
        assert detect_passive_voice('') == []

    def test_position_tracking(self):
        hits = detect_passive_voice('The ball was thrown.')
        assert hits[0]['position'] >= 0


# ============================================================================
# Dialogue extraction
# ============================================================================

class TestDialogueExtraction:

    def test_basic_extraction(self):
        text = 'She said, "Hello there." He nodded.'
        dialogue, narration = extract_dialogue(text)
        assert 'Hello there.' in dialogue
        assert 'She said' in narration
        assert 'He nodded' in narration

    def test_smart_quotes(self):
        text = 'She said, \u201cHello there.\u201d He nodded.'
        dialogue, narration = extract_dialogue(text)
        assert 'Hello there.' in dialogue

    def test_no_dialogue(self):
        text = 'The sun rose over the mountains.'
        dialogue, narration = extract_dialogue(text)
        assert dialogue.strip() == ''
        assert 'sun rose' in narration

    def test_multiple_quotes(self):
        text = '"First line." She paused. "Second line."'
        dialogue, narration = extract_dialogue(text)
        assert 'First line.' in dialogue
        assert 'Second line.' in dialogue
        assert 'She paused' in narration

    def test_empty_text(self):
        dialogue, narration = extract_dialogue('')
        assert dialogue == ''
        assert narration == ''


# ============================================================================
# Adverb detection
# ============================================================================

class TestAdverbDetection:

    def test_dialogue_tag_adverb(self):
        hits = detect_adverbs('"Hello," she said softly.')
        assert len(hits) == 1
        assert hits[0]['category'] == 'dialogue_tag'
        assert 'said softly' in hits[0]['match']

    def test_weak_verb_adverb(self):
        hits = detect_adverbs('He walked slowly down the hall.')
        assert len(hits) == 1
        assert hits[0]['category'] == 'weak_verb'

    def test_redundant_adverb(self):
        hits = detect_adverbs('She whispered quietly to the child.')
        assert len(hits) >= 1
        categories = {h['category'] for h in hits}
        assert 'redundant' in categories or 'dialogue_tag' in categories

    def test_normal_adverb_not_flagged(self):
        """Adverbs that aren't in any problematic category pass through."""
        hits = detect_adverbs('The river flowed endlessly through the valley.')
        assert len(hits) == 0

    def test_multiple_adverbs(self):
        text = '"Go away," he said angrily. She walked quickly to the door.'
        hits = detect_adverbs(text)
        assert len(hits) >= 2

    def test_empty_text(self):
        assert detect_adverbs('') == []


# ============================================================================
# Filler phrase detection
# ============================================================================

class TestFillerPhrases:

    def test_began_to(self):
        hits = detect_filler_phrases('She began to walk toward the door.')
        assert len(hits) == 1
        assert 'began to' in hits[0]['match'].lower()

    def test_seemed_to(self):
        hits = detect_filler_phrases('He seemed to understand her meaning.')
        assert len(hits) == 1

    def test_the_fact_that(self):
        hits = detect_filler_phrases('Despite the fact that she was tired.')
        assert len(hits) == 1

    def test_filtering_verbs(self):
        text = 'He could see the distant mountains. She could hear the music.'
        hits = detect_filler_phrases(text)
        assert len(hits) == 2

    def test_clean_prose(self):
        text = 'She walked to the door and opened it.'
        hits = detect_filler_phrases(text)
        assert len(hits) == 0

    def test_empty_text(self):
        assert detect_filler_phrases('') == []

    def test_case_insensitive(self):
        hits = detect_filler_phrases('In Order To survive, she ran.')
        assert len(hits) == 1


# ============================================================================
# AI-tell vocabulary
# ============================================================================

class TestAiTellWords:

    def test_load_ai_tell_words(self, plugin_dir):
        words = load_ai_tell_words(plugin_dir)
        assert len(words) > 0
        assert all('word' in w for w in words)
        assert all('category' in w for w in words)
        assert all('severity' in w for w in words)

    def test_load_missing_file(self, tmp_path):
        words = load_ai_tell_words(str(tmp_path))
        assert words == []

    def test_detect_hits(self):
        words = [
            {'word': 'delve', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': 'investigate'},
            {'word': 'tapestry', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': 'use concrete image'},
        ]
        text = 'We must delve deeper into this rich tapestry of life. Let us delve.'
        hits = detect_ai_tell_hits(text, words)
        assert len(hits) == 2
        delve_hit = next(h for h in hits if h['word'] == 'delve')
        assert delve_hit['count'] == 2
        tapestry_hit = next(h for h in hits if h['word'] == 'tapestry')
        assert tapestry_hit['count'] == 1

    def test_no_hits(self):
        words = [
            {'word': 'delve', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': 'investigate'},
        ]
        text = 'The cat sat on the mat.'
        hits = detect_ai_tell_hits(text, words)
        assert hits == []

    def test_phrase_detection(self):
        words = [
            {'word': "it's worth noting", 'category': 'structural',
             'severity': 'high', 'replacement_hint': 'just state it'},
        ]
        text = "It's worth noting that the building was old."
        hits = detect_ai_tell_hits(text, words)
        assert len(hits) == 1
        assert hits[0]['count'] == 1

    def test_case_insensitive(self):
        words = [
            {'word': 'Delve', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': 'investigate'},
        ]
        text = 'They delve into the mystery.'
        hits = detect_ai_tell_hits(text, words)
        assert len(hits) == 1

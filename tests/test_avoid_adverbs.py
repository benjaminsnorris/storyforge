"""Tests for avoid_adverbs deterministic scorer."""

from storyforge.scoring_adverbs import score_avoid_adverbs


CLEAN_PROSE = """
She crossed the room and set down the glass. The ice shifted, clinking
against the sides. Outside, a car door slammed. Marcus looked up from
his newspaper but said nothing.

The phone rang. She let it go to the third ring before picking up.
"Hello?" A pause. "Yes, I understand." She hung up without another word.
"""

ADVERB_HEAVY = """
"I can't believe it," she said softly. He walked slowly to the door
and opened it carefully. "Please come in," he said quietly.

She whispered quietly to the child. He ran quickly down the stairs.
"Stop!" she shouted loudly. He completely destroyed the evidence.
She walked slowly back and said sadly, "It's over."
"""


class TestAvoidAdverbs:

    def test_clean_prose_scores_high(self):
        result = score_avoid_adverbs(CLEAN_PROSE)
        assert result['score'] >= 4

    def test_adverb_heavy_scores_low(self):
        result = score_avoid_adverbs(ADVERB_HEAVY)
        assert result['score'] <= 3

    def test_dialogue_tag_marker(self):
        result = score_avoid_adverbs(ADVERB_HEAVY)
        assert result['markers']['aa-1'] == 1

    def test_weak_verb_marker(self):
        result = score_avoid_adverbs(ADVERB_HEAVY)
        assert result['markers']['aa-2'] == 1

    def test_redundant_marker(self):
        # 'crept silently' is redundant (crept implies silence) and not a dialogue tag
        result = score_avoid_adverbs('He crept silently down the hall and tiptoed quietly past the door.')
        assert result['markers']['aa-3'] == 1

    def test_clean_no_markers(self):
        result = score_avoid_adverbs(CLEAN_PROSE)
        assert sum(result['markers'].values()) == 0

    def test_empty_text(self):
        result = score_avoid_adverbs('')
        assert result['score'] == 4

    def test_short_text(self):
        result = score_avoid_adverbs('Hello.')
        assert result['score'] == 4

    def test_returns_details(self):
        result = score_avoid_adverbs(ADVERB_HEAVY)
        assert '/1000 words' in result['details']

    def test_score_range(self):
        for text in [CLEAN_PROSE, ADVERB_HEAVY, '', 'A word.']:
            result = score_avoid_adverbs(text)
            assert 1 <= result['score'] <= 5

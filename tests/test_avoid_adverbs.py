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

    def test_score_4_moderate_adverbs(self):
        """2-3 adverbs per 1000 words -> score 4."""
        # ~200 words with 1 adverb hit -> ~5/1000 is too high;
        # need ~500 words with 1 hit -> ~2/1000
        filler = ' '.join(['The quick brown fox jumps over the lazy dog.'] * 50)
        text = f'"Watch out," he said softly. {filler}'
        result = score_avoid_adverbs(text)
        assert result['score'] == 4

    def test_score_3_several_adverbs(self):
        """4-6 adverbs per 1000 words -> score 3."""
        # ~200 words with 1 hit = ~5/1000 -> score 3
        filler = ' '.join(['She opened the door and stepped through it.'] * 24)
        text = (
            '"Go," she said softly. ' + filler
        )
        result = score_avoid_adverbs(text)
        assert result['score'] == 3

    def test_score_2_many_adverbs(self):
        """7-10 adverbs per 1000 words -> score 2."""
        # Short text (~100 words) with ~1 adverb hit -> 10/1000
        base = (
            '"Go," she said softly. He walked slowly to the door. '
            '"Stop," he said quietly. She walked slowly back. '
            '"No," he said angrily. She looked quickly at him. '
            'He walked slowly away. "Wait," she said sadly.'
        )
        # ~80 words, several hits -> high per-1000 rate
        result = score_avoid_adverbs(base)
        assert result['score'] <= 2

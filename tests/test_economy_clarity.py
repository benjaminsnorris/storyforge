"""Tests for economy_clarity deterministic scorer."""

from storyforge.scoring_economy import score_economy_clarity


CLEAN_PROSE = """
She crossed the room and set down the glass. The ice shifted, clinking
against the sides. Outside, a car door slammed. Marcus looked up from
his newspaper but said nothing.

The phone rang. She let it go to the third ring before picking up.
"Hello?" A pause. "Yes, I understand." She hung up without another word.
Marcus folded the paper and set it on the table. He waited.
"""

# Heavy on filler phrases, AI-tell words, and passive voice
BLOATED_PROSE = """
It seemed to be a vibrant tapestry of life that began to unfold before
her eyes. She started to notice that the unprecedented interplay of
forces was being fostered by something she couldn't quite delve into.
The fact that it was clear that the journey was transformative seemed
to resonate with her on a profound level.

He appeared to navigate the complex landscape with seamless precision.
It was compelling, in essence, and arguably one of the most pivotal
moments of their shared experience. From a broader perspective, he
could feel the dynamic shifting beneath his feet.
"""

# Moderate issues
MODERATE_PROSE = """
She began to understand what he meant. The letter was written carefully,
each word chosen to convey exactly what he needed to say. It seemed to
be an apology, though he never used the word.

Marcus walked slowly to the window. The garden stretched out below,
all orderly rows and quiet corners. He could see the bench where they
used to sit. The memory stung, but he pushed it aside.
"""


class TestEconomyClarity:

    def test_clean_prose_scores_high(self):
        result = score_economy_clarity(CLEAN_PROSE, ai_tell_words=[])
        assert result['score'] >= 4

    def test_bloated_prose_scores_low(self):
        ai_words = [
            {'word': 'tapestry', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': ''},
            {'word': 'vibrant', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'unprecedented', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'delve', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': ''},
            {'word': 'resonate', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'compelling', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'transformative', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': ''},
            {'word': 'navigate', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'seamless', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': ''},
            {'word': 'pivotal', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'dynamic', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'profound', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'in essence', 'category': 'structural', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'from a broader perspective', 'category': 'structural',
             'severity': 'high', 'replacement_hint': ''},
            {'word': 'arguably', 'category': 'hedging', 'severity': 'medium',
             'replacement_hint': ''},
            {'word': 'interplay', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': ''},
            {'word': 'foster', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': ''},
            {'word': 'journey', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
        ]
        result = score_economy_clarity(BLOATED_PROSE, ai_tell_words=ai_words)
        assert result['score'] <= 3

    def test_filler_marker(self):
        result = score_economy_clarity(BLOATED_PROSE, ai_tell_words=[])
        # Bloated prose has many fillers
        assert result['markers']['ec-1'] == 1

    def test_ai_tell_marker(self):
        ai_words = [
            {'word': 'tapestry', 'category': 'vocabulary', 'severity': 'high',
             'replacement_hint': ''},
            {'word': 'vibrant', 'category': 'vocabulary', 'severity': 'medium',
             'replacement_hint': ''},
        ]
        result = score_economy_clarity(BLOATED_PROSE, ai_tell_words=ai_words)
        assert result['markers']['ec-2'] == 1

    def test_clean_no_markers(self):
        result = score_economy_clarity(CLEAN_PROSE, ai_tell_words=[])
        # Clean prose should have minimal markers
        active = sum(result['markers'].values())
        assert active <= 1

    def test_empty_text(self):
        result = score_economy_clarity('', ai_tell_words=[])
        assert result['score'] == 4

    def test_short_text(self):
        result = score_economy_clarity('A few short words.', ai_tell_words=[])
        assert result['score'] == 4

    def test_returns_details(self):
        result = score_economy_clarity(MODERATE_PROSE, ai_tell_words=[])
        assert 'filler=' in result['details']
        assert 'passive=' in result['details']

    def test_score_range(self):
        for text in [CLEAN_PROSE, BLOATED_PROSE, MODERATE_PROSE, '']:
            result = score_economy_clarity(text, ai_tell_words=[])
            assert 1 <= result['score'] <= 5

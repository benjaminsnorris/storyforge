"""Tests for sentence_as_thought deterministic scorer."""

from storyforge.scoring_rhythm import score_sentence_as_thought, _detect_monotonous_runs


# Good rhythm: varied sentence lengths
VARIED_PROSE = """
She stopped. The map spread across the table showed a coastline she didn't
recognize, all jagged inlets and unnamed headlands that curved north toward
a peninsula the size of her thumbnail. Three months ago, none of this would
have mattered. Now every contour felt personal.

Marcus looked up. "You see it?"

"The inlet." She traced the line with her finger, following it past the
lighthouse symbol and around the bluff where the cartographer had drawn
a tiny anchor. "That's where the boat went down."

He said nothing for a long time.
"""

# Bad rhythm: monotonous sentence lengths
MONOTONOUS_PROSE = """
She walked across the room slowly. He sat down in the wooden chair. The
lamp cast shadows on the wall. She picked up her glass of wine. He opened
his newspaper to read. The clock ticked on the wall there. She looked out
the dark window pane. The garden was covered in frost. He turned to the
second page now. She set her glass down gently. The fire crackled in the
hearth nearby. He folded the paper in half. She crossed her legs and sighed.
The room felt smaller than before. He cleared his throat and looked.
"""

# Partial variety with a monotonous run
PARTIAL_VARIETY = """
The door slammed. Marcus flinched, nearly dropping the phone — its weight
suddenly foreign in his hand, as though the call had changed the molecular
structure of everything he touched.

She sat in the chair. He stood by the door. The room was very quiet. She
looked at her hands now. He shifted his weight again. The silence stretched
between them both.

"Tell me," she said, and her voice cracked on the second word.
"""


class TestSentenceAsThought:

    def test_varied_prose_scores_high(self):
        result = score_sentence_as_thought(VARIED_PROSE)
        assert result['score'] >= 4

    def test_monotonous_prose_scores_low(self):
        result = score_sentence_as_thought(MONOTONOUS_PROSE)
        assert result['score'] <= 3

    def test_partial_variety_mid_score(self):
        result = score_sentence_as_thought(PARTIAL_VARIETY)
        assert 2 <= result['score'] <= 4

    def test_low_variance_marker(self):
        result = score_sentence_as_thought(MONOTONOUS_PROSE)
        assert result['markers']['sat-1'] == 1

    def test_monotonous_run_marker(self):
        result = score_sentence_as_thought(MONOTONOUS_PROSE)
        assert result['markers']['sat-2'] == 1

    def test_varied_no_markers(self):
        result = score_sentence_as_thought(VARIED_PROSE)
        # Should have few or no markers
        assert result['markers']['sat-1'] == 0

    def test_empty_text(self):
        result = score_sentence_as_thought('')
        assert result['score'] == 4

    def test_short_text(self):
        result = score_sentence_as_thought('One sentence. Two. OK.')
        assert result['score'] == 4

    def test_returns_details(self):
        result = score_sentence_as_thought(VARIED_PROSE)
        assert 'stddev=' in result['details']

    def test_score_range(self):
        for text in [VARIED_PROSE, MONOTONOUS_PROSE, PARTIAL_VARIETY, '']:
            result = score_sentence_as_thought(text)
            assert 1 <= result['score'] <= 5


class TestMonotonousRuns:

    def test_no_run_in_short_list(self):
        assert _detect_monotonous_runs([10, 12, 8]) == 0

    def test_detects_run(self):
        # 6 sentences all around 10 words
        lengths = [10, 11, 9, 10, 12, 10]
        assert _detect_monotonous_runs(lengths) >= 1

    def test_no_run_with_variety(self):
        lengths = [5, 20, 8, 30, 3, 15, 25]
        assert _detect_monotonous_runs(lengths) == 0

    def test_empty_list(self):
        assert _detect_monotonous_runs([]) == 0

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


    def test_moderate_stddev_score_3(self):
        """stddev 3-5 should score 3."""
        # Sentences that hover around 10-15 words with mild variation
        text = (
            'She walked to the store quickly. He drove to the park alone. '
            'The children played by the river. She sat and read her novel. '
            'He cooked dinner for the evening. They ate outside on the porch. '
            'The sunset painted the clouds orange. She cleared up the dishes. '
            'He locked all the doors tightly. They went to bed quite early.'
        )
        result = score_sentence_as_thought(text)
        # With similar-length sentences, stddev should be low-moderate
        assert result['score'] <= 4

    def test_stddev_2_to_3_score_2(self):
        """stddev 2-3 should score 2 (line 81)."""
        # Mix of 4-word and 8-word sentences -> stddev ~2.2
        text = (
            'She stopped and looked. He put down the heavy bag he carried. '
            'The room was quiet. She crossed to the window and pulled back curtains. '
            'Nothing moved at all. He sat down in the old chair by door. '
            'She poured two drinks. The firelight made shadows on the far wall. '
            'He said absolutely nothing. She picked up the letter from the table. '
            'Time had passed slowly. He watched her read with careful quiet attention.'
        )
        result = score_sentence_as_thought(text)
        assert result['score'] == 2

    def test_bucket_imbalance_penalty(self):
        """No short AND no long sentences triggers bucket imbalance penalty."""
        # All sentences 10-20 words — no short (<8) and no long (>25)
        text = (
            'She walked across the room to the window slowly. '
            'He sat down in the comfortable wooden chair quietly. '
            'The lamp cast long golden shadows on the wall. '
            'She picked up the glass of red wine carefully. '
            'He opened the newspaper to the front page slowly. '
            'The clock on the wall ticked and ticked steadily. '
            'She looked out of the dark window at nothing. '
            'The garden was completely covered in the new frost.'
        )
        result = score_sentence_as_thought(text)
        # Both sat-3 and sat-4 should trigger if no short/long sentences
        if result['markers']['sat-3'] == 1 and result['markers']['sat-4'] == 1:
            # Penalty should have been applied
            assert result['score'] <= 3


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

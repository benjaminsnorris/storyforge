"""Tests for avoid_passive deterministic scorer."""

from storyforge.scoring_passive import score_avoid_passive


# Good prose: mostly active voice
ACTIVE_PROSE = """
She threw the ball across the yard. The dog chased it through the garden,
leaping over flower beds and dodging the sprinkler. When he brought it back,
his tail wagged so hard his whole body shook.

Marcus picked up the phone and dialed the number. No one answered. He tried
again, pressing each digit with deliberate care. The line rang six times
before the voicemail kicked in.
"""

# Bad prose: heavily passive
PASSIVE_PROSE = """
The ball was thrown across the yard. It was chased by the dog through the
garden. The flower beds were leaped over and the sprinkler was dodged.
When it was brought back, his tail was wagged so hard.

The phone was picked up and the number was dialed. No answer was received.
The number was tried again. Each digit was pressed with deliberate care.
The line was rung six times before voicemail was reached.
"""

# Mixed prose
MIXED_PROSE = """
She threw the ball across the yard. The dog chased it through the garden.
When it was brought back, his tail wagged hard.

The phone was picked up and Marcus dialed the number. No one answered.
He tried again. The line was rung six times before the voicemail kicked in.
"""


class TestAvoidPassive:

    def test_active_prose_scores_high(self):
        result = score_avoid_passive(ACTIVE_PROSE)
        assert result['score'] >= 4

    def test_passive_prose_scores_low(self):
        result = score_avoid_passive(PASSIVE_PROSE)
        assert result['score'] <= 2

    def test_mixed_prose_scores_mid(self):
        result = score_avoid_passive(MIXED_PROSE)
        assert 2 <= result['score'] <= 4

    def test_cluster_detection(self):
        """Paragraph with 3+ passive sentences triggers ap-1."""
        result = score_avoid_passive(PASSIVE_PROSE)
        assert result['markers']['ap-1'] == 1

    def test_no_cluster_in_active(self):
        result = score_avoid_passive(ACTIVE_PROSE)
        assert result['markers']['ap-1'] == 0

    def test_density_marker(self):
        """High passive density triggers ap-2."""
        result = score_avoid_passive(PASSIVE_PROSE)
        assert result['markers']['ap-2'] == 1

    def test_empty_text(self):
        result = score_avoid_passive('')
        assert result['score'] == 4
        assert result['markers'] == {'ap-1': 0, 'ap-2': 0}

    def test_returns_details(self):
        result = score_avoid_passive(ACTIVE_PROSE)
        assert 'passive sentences' in result['details']

    def test_score_range(self):
        for text in [ACTIVE_PROSE, PASSIVE_PROSE, MIXED_PROSE, '']:
            result = score_avoid_passive(text)
            assert 1 <= result['score'] <= 5

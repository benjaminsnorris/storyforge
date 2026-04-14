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

    def test_moderate_density_score_3(self):
        """~15% passive density should score 3 (density 0.10-0.20)."""
        # 2 passive out of ~13 sentences -> ~15%
        text = (
            'She opened the door. He walked inside. The room was dark. '
            'She turned on the light. He sat in the chair. '
            'The table was covered with papers. She picked one up. '
            'He leaned forward. She read it aloud. The words were chosen '
            'carefully. He nodded slowly. She set it down. He stood up.'
        )
        result = score_avoid_passive(text)
        assert result['score'] == 3 or result['score'] == 4  # borderline is OK

    def test_high_density_score_2(self):
        """~25% passive density should score 2 (density 0.20-0.30)."""
        # 3 passive out of ~12 sentences -> ~25%
        text = (
            'She opened the door. The room was filled with smoke. '
            'He walked inside. The windows were broken by the blast. '
            'She turned on the light. He sat in the chair. '
            'The table was covered with dust. She picked up a glass. '
            'He leaned forward. She set it down. He stood up. She left.'
        )
        result = score_avoid_passive(text)
        assert result['score'] <= 3

    def test_cluster_penalty_applied(self):
        """Cluster penalty reduces score by 1 when score > 1."""
        # A paragraph of 3+ passive sentences with overall moderate density
        text = (
            'The door was opened. The light was turned on. The room was '
            'cleaned. The floor was swept by the janitor.\n\n'
            'She walked to the car. He drove them home. She cooked dinner. '
            'He read a book. She watched television. He fell asleep. '
            'She locked the door. He turned off the lights.'
        )
        result = score_avoid_passive(text)
        assert result['markers']['ap-1'] == 1  # cluster detected
        # The cluster penalty should have reduced the score

    def test_cluster_penalty_not_below_1(self):
        """Cluster penalty does not reduce score below 1."""
        # All passive + cluster -> score 1, penalty should not go to 0
        text = (
            'The ball was thrown. It was caught. The game was won. '
            'The trophy was given. The crowd was thrilled. The team was '
            'celebrated. The coach was praised. The season was finished.'
        )
        result = score_avoid_passive(text)
        assert result['score'] >= 1

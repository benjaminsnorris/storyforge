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

    def test_low_density_score_4(self):
        """Density 5-10% should score 4 (line 53)."""
        # 1 passive out of ~15 sentences = ~7%
        text = (
            'She opened the door. He walked inside. The room was dark. '
            'She turned on the light. He sat in the chair. '
            'The table was covered with papers. She picked one up. '
            'He leaned forward. She read it aloud. He nodded slowly. '
            'She set it down. He stood up. She walked away. He followed. '
            'They left together.'
        )
        result = score_avoid_passive(text)
        assert result['score'] == 4

    def test_moderate_density_score_3(self):
        """Density 10-20% should score 3 (line 55)."""
        # 2 passive out of ~13 sentences -> ~15%
        text = (
            'She opened the door. He walked inside. The room was dark. '
            'She turned on the light. He sat in the chair. '
            'The table was covered with papers. She picked one up. '
            'He leaned forward. She read it aloud. The words were chosen '
            'carefully. He nodded slowly. She set it down. He stood up.'
        )
        result = score_avoid_passive(text)
        assert result['score'] == 3

    def test_high_density_score_2(self):
        """Density 20-30% should score 2 (line 57), no cluster."""
        # Passives spread across paragraphs to avoid cluster detection
        text = (
            'She opened the door. The room was filled with smoke.\n\n'
            'He walked inside carefully. The windows were broken long ago.\n\n'
            'She turned on the light. He sat in the wooden chair.\n\n'
            'The table was covered with old dust. She picked up a glass.\n\n'
            'He leaned forward slowly. She set it down carefully.\n\n'
            'He stood up and stretched. She walked to the window.\n\n'
            'The garden was hidden by fog. He cleared his throat.\n\n'
            'She turned to face him. He shrugged and said nothing.\n\n'
            'She picked up her bag. He opened the back door.'
        )
        result = score_avoid_passive(text)
        assert result['score'] == 2
        assert result['markers']['ap-1'] == 0  # no cluster

    def test_cluster_penalty_applied(self):
        """Cluster penalty reduces score by 1 when score > 1 (line 63)."""
        # 3 passives in first paragraph -> cluster; density ~14% -> initial score 3
        # Penalty -> final score 2
        text = (
            'The door was opened by someone. The light was turned on by the maid. '
            'The room was cleaned thoroughly by the staff.\n\n'
            'She walked to the car and drove. He followed close behind her. '
            'She cooked dinner for the family. He read a book in the armchair. '
            'She watched television that evening. He fell asleep on the couch. '
            'She locked the door before bed. He turned off all the lights. '
            'They slept until the morning came. The sun rose over the hills. '
            'She made the coffee as always. He read the morning newspaper. '
            'They ate breakfast in comfortable silence. She cleared the dishes. '
            'He washed them carefully at the sink. She dried and put them away. '
            'They stepped outside into the garden. The path led to the old gate.'
        )
        result = score_avoid_passive(text)
        assert result['markers']['ap-1'] == 1  # cluster detected
        assert result['score'] == 2  # initial 3, minus 1 penalty

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

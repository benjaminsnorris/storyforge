"""Tests for no_weather_dreams deterministic scorer."""

from storyforge.scoring_weather import score_no_weather_dreams


CLEAN_OPENING = """
Marcus set down his coffee and spread the map across the kitchen table.
The coastline traced a jagged line from north to south, dotted with names
he'd never heard of. Three months ago, he wouldn't have cared. Now every
inlet and headland felt like an accusation.
"""

WEATHER_OPENING = """
Rain hammered the windows as the storm rolled in from the coast. Dark
clouds massed on the horizon, and the wind picked up, rattling the
shutters. The temperature dropped ten degrees in as many minutes.
Marcus stood at the window and watched it all unfold.
"""

MILD_WEATHER_MENTION = """
Marcus set down his coffee and glanced out at the rain. The map was
already spread across the kitchen table. The coastline traced a jagged
line from north to south. Three months ago, he wouldn't have cared.
"""

DREAM_OPENING = """
In the dream, she was falling. Not the kind of falling that jolts you
awake — this was slow, deliberate, like sinking through warm water.
The darkness wrapped around her. She tried to scream but her mouth
filled with silence.
"""

WAKING_OPENING = """
She woke to the sound of breaking glass. For a moment she lay still,
eyes open, staring at the ceiling. The alarm clock read 3:17. She
rolled over and reached for the phone on the nightstand.
"""

WEATHER_LATER_IN_SCENE = """
Marcus spread the map across the kitchen table and studied the coastline.
Three months ago, he wouldn't have cared about any of this. Now every
inlet felt like an accusation. He picked up his coffee and took a sip.

Outside, rain began to fall. The drops hit the window in irregular
patterns, blurring the garden beyond. He barely noticed.
"""


class TestNoWeatherDreams:

    def test_clean_opening_scores_5(self):
        result = score_no_weather_dreams(CLEAN_OPENING)
        assert result['score'] == 5
        assert sum(result['markers'].values()) == 0

    def test_weather_opening_scores_low(self):
        result = score_no_weather_dreams(WEATHER_OPENING)
        assert result['score'] <= 2
        assert result['markers']['nwd-1'] == 1

    def test_dream_opening_detected(self):
        result = score_no_weather_dreams(DREAM_OPENING)
        assert result['markers']['nwd-2'] == 1
        assert result['score'] <= 2

    def test_waking_opening_detected(self):
        result = score_no_weather_dreams(WAKING_OPENING)
        assert result['markers']['nwd-3'] == 1
        assert result['score'] <= 2

    def test_weather_later_not_triggered(self):
        """Weather mentioned after the opening should not trigger."""
        result = score_no_weather_dreams(WEATHER_LATER_IN_SCENE)
        assert result['markers']['nwd-1'] == 0

    def test_mild_weather_reference(self):
        """A passing weather mention in the opening is less severe."""
        result = score_no_weather_dreams(MILD_WEATHER_MENTION)
        # Should either pass or score mildly — not a hard fail
        assert result['score'] >= 2

    def test_empty_text(self):
        result = score_no_weather_dreams('')
        assert result['score'] == 5

    def test_returns_details(self):
        result = score_no_weather_dreams(WEATHER_OPENING)
        assert 'weather' in result['details']

    def test_score_range(self):
        for text in [CLEAN_OPENING, WEATHER_OPENING, DREAM_OPENING,
                     WAKING_OPENING, '']:
            result = score_no_weather_dreams(text)
            assert 1 <= result['score'] <= 5

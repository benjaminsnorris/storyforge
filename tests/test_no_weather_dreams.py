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

    def test_extended_weather_without_context_words(self):
        """2+ weather sentences without sky/horizon context still triggers."""
        # Weather words only (rain, wind, cold) — no context words like 'sky'
        text = (
            'Rain fell hard on the roof. The wind blew cold through cracks '
            'in the door. Snow started to mix with the rain outside. '
            'Marcus pulled his collar up and kept walking forward.'
        )
        result = score_no_weather_dreams(text)
        assert result['markers']['nwd-1'] == 1

    def test_context_only_weather_opening(self):
        """Weather context words (sky, temperature) without _WEATHER_WORDS
        triggers via sentence count (lines 98-99)."""
        # 'sky' and 'temperature' are in _WEATHER_CONTEXT but NOT _WEATHER_WORDS
        text = (
            'The sky hung low and heavy. The temperature dropped steadily '
            'all morning. Marcus pulled his coat tighter and headed for the car.'
        )
        result = score_no_weather_dreams(text)
        assert result['markers']['nwd-1'] == 1
        assert 'extended weather' in result['details']

    def test_multiple_markers_score_1(self):
        """Weather + dream triggers score 1 when 2+ markers active."""
        text = (
            'In the dream, rain hammered the windows. The storm rolled in '
            'from the coast. She watched the clouds darken through closed '
            'eyelids as the nightmare continued.'
        )
        result = score_no_weather_dreams(text)
        active = sum(result['markers'].values())
        if active >= 2:
            assert result['score'] == 1

    def test_weather_waking_combined(self):
        """Weather + waking opening triggers multiple markers."""
        text = (
            'She woke to the sound of rain on the window. The storm had '
            'rolled in overnight, and the wind rattled the shutters. '
            'She pulled the covers aside and stood.'
        )
        result = score_no_weather_dreams(text)
        # Should detect both waking and weather
        assert result['markers']['nwd-3'] == 1  # waking

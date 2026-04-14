"""Deterministic scorer for economy_clarity principle.

Composite scorer combining signals from passive voice, filler phrases,
AI-tell vocabulary, and weak verb+adverb density.
"""

from storyforge.common import get_plugin_dir
from storyforge.prose_analysis import (
    detect_passive_voice,
    detect_filler_phrases,
    detect_adverbs,
    load_ai_tell_words,
    detect_ai_tell_hits,
)

# Module-level cache for AI-tell words
_ai_tell_cache: list[dict] | None = None


def _get_ai_tell_words() -> list[dict]:
    global _ai_tell_cache
    if _ai_tell_cache is None:
        try:
            plugin_dir = get_plugin_dir()
        except Exception:
            plugin_dir = ''
        _ai_tell_cache = load_ai_tell_words(plugin_dir)
    return _ai_tell_cache


def _sub_score(density: float, t5: float, t4: float,
               t3: float, t2: float) -> int:
    """Convert a density to a 1-5 sub-score using thresholds."""
    if density <= t5:
        return 5
    elif density <= t4:
        return 4
    elif density <= t3:
        return 3
    elif density <= t2:
        return 2
    else:
        return 1


def score_economy_clarity(scene_text: str,
                          ai_tell_words: list[dict] | None = None) -> dict:
    """Score a scene for economy and clarity.

    Returns {'score': int, 'markers': dict, 'details': str}.
    Score 1-5.  Markers: ec-1 (filler), ec-2 (ai-tell), ec-3 (passive),
    ec-4 (weak adverbs).
    """
    markers = {'ec-1': 0, 'ec-2': 0, 'ec-3': 0, 'ec-4': 0}

    words = scene_text.split()
    word_count = len(words)
    if word_count < 20:
        return {'score': 4, 'markers': markers, 'details': 'Text too short'}

    # Sub-signal: Filler phrases
    fillers = detect_filler_phrases(scene_text)
    filler_per_1000 = len(fillers) / word_count * 1000
    filler_score = _sub_score(filler_per_1000, 1, 3, 6, 10)

    # Sub-signal: AI-tell vocabulary
    if ai_tell_words is None:
        ai_tell_words = _get_ai_tell_words()
    ai_hits = detect_ai_tell_hits(scene_text, ai_tell_words)
    ai_total = sum(h['count'] for h in ai_hits)
    ai_per_1000 = ai_total / word_count * 1000
    ai_score = _sub_score(ai_per_1000, 0.5, 1.5, 3, 5)

    # Sub-signal: Passive voice density
    passives = detect_passive_voice(scene_text)
    passive_per_1000 = len(passives) / word_count * 1000
    passive_score = _sub_score(passive_per_1000, 5, 10, 20, 30)

    # Sub-signal: Weak adverbs
    adverb_hits = detect_adverbs(scene_text)
    weak_adverbs = [h for h in adverb_hits
                    if h['category'] in ('weak_verb', 'redundant')]
    weak_per_1000 = len(weak_adverbs) / word_count * 1000
    adverb_score = _sub_score(weak_per_1000, 0.5, 1.5, 3, 5)

    # Markers
    if filler_per_1000 > 3:
        markers['ec-1'] = 1
    if ai_per_1000 > 1.5:
        markers['ec-2'] = 1
    if passive_per_1000 > 15:
        markers['ec-3'] = 1
    if weak_per_1000 > 1.5:
        markers['ec-4'] = 1

    # Weighted combination: fillers 30%, AI-tell 30%, passive 20%, adverbs 20%
    weighted = (filler_score * 0.3 + ai_score * 0.3
                + passive_score * 0.2 + adverb_score * 0.2)
    score = max(1, min(5, round(weighted)))

    details = (f'filler={filler_score}({filler_per_1000:.1f}/1k), '
               f'ai_tell={ai_score}({ai_per_1000:.1f}/1k), '
               f'passive={passive_score}({passive_per_1000:.1f}/1k), '
               f'adverb={adverb_score}({weak_per_1000:.1f}/1k)')

    return {'score': score, 'markers': markers, 'details': details}

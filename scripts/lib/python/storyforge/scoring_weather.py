"""Deterministic scorer for no_weather_dreams principle.

Checks the opening of a scene for weather descriptions, dream sequences,
or waking-up openings — the three most common lazy scene openers.
"""

import re


_WEATHER_WORDS = frozenset({
    'rain', 'rained', 'raining', 'rainy',
    'sun', 'sunny', 'sunshine', 'sunlight',
    'wind', 'windy', 'winds', 'breeze', 'breezy',
    'cloud', 'clouds', 'cloudy', 'overcast',
    'storm', 'storms', 'stormy', 'thunder', 'lightning',
    'fog', 'foggy', 'mist', 'misty', 'haze', 'hazy',
    'snow', 'snowed', 'snowing', 'snowy', 'sleet',
    'drizzle', 'drizzling', 'downpour',
    'humid', 'humidity', 'muggy', 'sweltering',
    'frost', 'frosty', 'freezing',
})

_WEATHER_CONTEXT = frozenset({
    'sky', 'skies', 'horizon', 'temperature', 'degrees',
    'weather', 'forecast', 'barometer',
})

_DREAM_WORDS = frozenset({
    'dream', 'dreamed', 'dreaming', 'dreamt', 'dreams',
    'nightmare', 'nightmares',
})

_WAKING_PATTERNS = [
    re.compile(r'\bwoke\b', re.IGNORECASE),
    re.compile(r'\bwaking\b', re.IGNORECASE),
    re.compile(r'\bwoken\b', re.IGNORECASE),
    re.compile(r'\balarm\b', re.IGNORECASE),
    re.compile(r'\beyes\s+opened\b', re.IGNORECASE),
    re.compile(r'\bmorning\s+light\b', re.IGNORECASE),
    re.compile(r'\brolled\s+over\b', re.IGNORECASE),
    re.compile(r'\bcrawled\s+out\s+of\s+bed\b', re.IGNORECASE),
    re.compile(r'\bpulled\s+(the\s+)?covers\b', re.IGNORECASE),
]


def _get_opening(text: str, word_limit: int = 80) -> str:
    """Extract the opening of a scene (first ~80 words, ignoring headers)."""
    lines = [l for l in text.split('\n') if l.strip() and not l.strip().startswith('#')]
    opening = ' '.join(lines)
    words = opening.split()
    return ' '.join(words[:word_limit])


def _count_weather_sentences(text: str) -> int:
    """Count sentences in text that are primarily about weather."""
    # Simple sentence split
    sentences = re.split(r'[.!?]+', text)
    count = 0
    for sent in sentences:
        words = set(sent.lower().split())
        weather_hits = words & (_WEATHER_WORDS | _WEATHER_CONTEXT)
        if len(weather_hits) >= 2:
            count += 1
        elif len(weather_hits) == 1 and len(words) < 12:
            count += 1
    return count


def score_no_weather_dreams(scene_text: str) -> dict:
    """Score a scene for weather/dream/waking openings.

    Returns {'score': int, 'markers': dict, 'details': str}.
    Score 1-5.  Markers: nwd-1 (weather), nwd-2 (dream), nwd-3 (waking).
    """
    markers = {'nwd-1': 0, 'nwd-2': 0, 'nwd-3': 0}

    if not scene_text.strip():
        return {'score': 5, 'markers': markers, 'details': 'Empty scene'}

    opening = _get_opening(scene_text)
    opening_lower = opening.lower()
    # Strip punctuation from words for accurate matching
    opening_words = set(
        re.sub(r'[^\w\'-]', '', w) for w in opening_lower.split()
    ) - {''}  # remove empty strings from stripping

    findings = []

    # Weather check
    weather_hits = opening_words & _WEATHER_WORDS
    weather_context_hits = opening_words & _WEATHER_CONTEXT
    weather_sentence_count = _count_weather_sentences(opening)

    if weather_hits and (weather_context_hits or weather_sentence_count >= 2):
        markers['nwd-1'] = 1
        findings.append(f'weather opening ({", ".join(sorted(weather_hits))})')
    elif weather_sentence_count >= 2:
        markers['nwd-1'] = 1
        findings.append('extended weather description in opening')

    # Dream check
    dream_hits = opening_words & _DREAM_WORDS
    if dream_hits:
        markers['nwd-2'] = 1
        findings.append(f'dream opening ({", ".join(sorted(dream_hits))})')

    # Waking check
    for pattern in _WAKING_PATTERNS:
        if pattern.search(opening):
            markers['nwd-3'] = 1
            findings.append('waking-up opening')
            break

    # Score
    active_markers = sum(markers.values())
    if active_markers == 0:
        score = 5
    elif active_markers == 1:
        # Extended weather (2+ sentences) is worse than a mild reference
        if markers['nwd-1'] and weather_sentence_count >= 2:
            score = 1
        else:
            score = 2
    else:
        score = 1

    details = '; '.join(findings) if findings else 'clean opening'
    return {'score': score, 'markers': markers, 'details': details}

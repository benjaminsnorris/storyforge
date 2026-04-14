"""Deterministic scorer for sentence_as_thought principle.

Measures sentence length variance as a proxy for prose rhythm quality.
Reuses split_sentences() and compute_rhythm_signature() from exemplars.py.
"""

from storyforge.exemplars import split_sentences, compute_rhythm_signature


def _detect_monotonous_runs(sentence_lengths: list[int],
                            run_length: int = 5,
                            tolerance: int = 3) -> int:
    """Count monotonous runs: sequences of run_length+ sentences within
    +-tolerance words of each other.

    Returns the number of such runs.
    """
    if len(sentence_lengths) < run_length:
        return 0

    runs = 0
    i = 0
    while i <= len(sentence_lengths) - run_length:
        anchor = sentence_lengths[i]
        streak = 1
        for j in range(i + 1, len(sentence_lengths)):
            if abs(sentence_lengths[j] - anchor) <= tolerance:
                streak += 1
            else:
                break
        if streak >= run_length:
            runs += 1
            i += streak
        else:
            i += 1

    return runs


def score_sentence_as_thought(scene_text: str) -> dict:
    """Score a scene for sentence rhythm variety.

    Returns {'score': int, 'markers': dict, 'details': str}.
    Score 1-5.  Markers: sat-1 (low variance), sat-2 (monotonous run),
    sat-3 (no short sentences), sat-4 (no long sentences).
    """
    markers = {'sat-1': 0, 'sat-2': 0, 'sat-3': 0, 'sat-4': 0}

    sig = compute_rhythm_signature(scene_text)
    if sig is None:
        return {'score': 4, 'markers': markers,
                'details': 'Insufficient text for analysis'}

    stddev = sig['stddev_sentence_words']
    short_ratio = sig['short_ratio']
    long_ratio = sig['long_ratio']

    # Sentence lengths for run detection
    sentences = split_sentences(scene_text)
    lengths = [len(s.split()) for s in sentences]
    runs = _detect_monotonous_runs(lengths)

    # Markers
    if stddev < 5:
        markers['sat-1'] = 1
    if runs > 0:
        markers['sat-2'] = 1
    if short_ratio == 0:
        markers['sat-3'] = 1
    if long_ratio == 0:
        markers['sat-4'] = 1

    # Score based on stddev
    if stddev > 8:
        score = 5
    elif stddev > 5:
        score = 4
    elif stddev > 3:
        score = 3
    elif stddev > 2:
        score = 2
    else:
        score = 1

    # Run penalty
    if runs > 0 and score > 1:
        score -= 1

    # Bucket imbalance penalty (no short AND no long)
    if markers['sat-3'] and markers['sat-4'] and score > 1:
        score -= 1

    details = (f'stddev={stddev:.1f}, runs={runs}, '
               f'short_ratio={short_ratio:.2f}, long_ratio={long_ratio:.2f}')

    return {'score': score, 'markers': markers, 'details': details}

"""Deterministic scorer for avoid_adverbs principle.

Detects dialogue-tag adverbs, weak verb+adverb pairs, and redundant
adverbs.  Scores per 1000 words to normalize across scene lengths.
"""

from storyforge.prose_analysis import detect_adverbs


def score_avoid_adverbs(scene_text: str) -> dict:
    """Score a scene for problematic adverb usage.

    Returns {'score': int, 'markers': dict, 'details': str}.
    Score 1-5.  Markers: aa-1 (dialogue_tag), aa-2 (weak_verb), aa-3 (redundant).
    """
    markers = {'aa-1': 0, 'aa-2': 0, 'aa-3': 0}

    words = scene_text.split()
    word_count = len(words)
    if word_count < 10:
        return {'score': 4, 'markers': markers, 'details': 'Text too short'}

    hits = detect_adverbs(scene_text)

    # Categorize
    tag_count = sum(1 for h in hits if h['category'] == 'dialogue_tag')
    weak_count = sum(1 for h in hits if h['category'] == 'weak_verb')
    redundant_count = sum(1 for h in hits if h['category'] == 'redundant')

    if tag_count:
        markers['aa-1'] = 1
    if weak_count:
        markers['aa-2'] = 1
    if redundant_count:
        markers['aa-3'] = 1

    # Normalize to per-1000 words
    total_hits = len(hits)
    per_1000 = total_hits / word_count * 1000

    if per_1000 <= 1:
        score = 5
    elif per_1000 <= 3:
        score = 4
    elif per_1000 <= 6:
        score = 3
    elif per_1000 <= 10:
        score = 2
    else:
        score = 1

    details = (f'{total_hits} adverb issues ({per_1000:.1f}/1000 words): '
               f'tag={tag_count}, weak={weak_count}, redundant={redundant_count}')

    return {'score': score, 'markers': markers, 'details': details}

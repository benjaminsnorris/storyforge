"""Deterministic scorer for avoid_passive principle.

Detects passive voice density and clusters.  Isolated passives are fine;
clusters (3+ in a paragraph) indicate a problem.
"""

from storyforge.exemplars import split_sentences
from storyforge.prose_analysis import detect_passive_voice


def score_avoid_passive(scene_text: str) -> dict:
    """Score a scene for passive voice usage.

    Returns {'score': int, 'markers': dict, 'details': str}.
    Score 1-5.  Markers: ap-1 (cluster), ap-2 (density).
    """
    markers = {'ap-1': 0, 'ap-2': 0}

    sentences = split_sentences(scene_text)
    if not sentences:
        return {'score': 4, 'markers': markers, 'details': 'No sentences found'}

    # Count sentences containing passive voice
    passive_count = 0
    for sent in sentences:
        if detect_passive_voice(sent):
            passive_count += 1

    total = len(sentences)
    density = passive_count / total

    # Cluster detection: 3+ passive sentences in a paragraph
    paragraphs = [p.strip() for p in scene_text.split('\n\n') if p.strip()]
    has_cluster = False
    for para in paragraphs:
        para_sents = split_sentences(para)
        para_passive = sum(1 for s in para_sents if detect_passive_voice(s))
        if para_passive >= 3:
            has_cluster = True
            break

    if has_cluster:
        markers['ap-1'] = 1
    if density > 0.15:
        markers['ap-2'] = 1

    active_markers = sum(markers.values())

    # Score based on density
    if density < 0.05:
        score = 5
    elif density < 0.10:
        score = 4
    elif density < 0.20:
        score = 3
    elif density < 0.30:
        score = 2
    else:
        score = 1

    # Cluster penalty: reduce by 1 if cluster detected and score > 1
    if has_cluster and score > 1:
        score -= 1

    details = (f'{passive_count}/{total} passive sentences '
               f'({density:.0%}), cluster={has_cluster}')

    return {'score': score, 'markers': markers, 'details': details}

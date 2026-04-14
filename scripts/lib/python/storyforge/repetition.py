"""Cross-chapter repetition detection for Storyforge manuscripts.

Pure-stdlib n-gram scanner that detects repeated phrases across scenes.
No API calls -- runs in seconds on 100k-word manuscripts.
"""

import os
import re

from storyforge.elaborate import _read_csv


# ============================================================================
# Stop words
# ============================================================================

STOP_WORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can', 'it',
    'its', 'he', 'she', 'they', 'them', 'his', 'her', 'their', 'this',
    'that', 'these', 'those', 'not', 'no', 'so', 'if', 'then', 'than',
    'too', 'very', 'just', 'about', 'up', 'out', 'into',
})

THRESHOLDS = {4: 5, 5: 3, 6: 2, 7: 2}


# ============================================================================
# Categorization vocabulary
# ============================================================================

BODY_PARTS = frozenset({
    'eyes', 'eye', 'hands', 'hand', 'face', 'jaw', 'chest', 'throat',
    'neck', 'shoulder', 'shoulders', 'back', 'stomach', 'gut', 'fingers',
    'lips', 'mouth', 'head', 'heart', 'skin', 'arms', 'arm', 'legs',
    'leg', 'knees', 'knee', 'teeth', 'breath', 'fist', 'fists', 'palm',
    'palms', 'wrist', 'spine',
})

BLOCKING_VERBS = frozenset({
    'looked', 'turned', 'nodded', 'glanced', 'stepped', 'reached',
    'moved', 'shifted', 'leaned', 'shook', 'shrugged', 'stared',
    'gazed', 'watched',
})

STRUCTURAL_CUES = frozenset({
    'for the first time', 'the kind of', 'in a way that', 'the sort of',
    'there was something', 'it was the kind', 'for a long moment',
    'in that moment', 'at that moment',
})

SENSORY_WORDS = frozenset({
    'smell', 'smelled', 'taste', 'tasted', 'sound', 'sounded', 'cold',
    'warm', 'hot', 'wet', 'dry', 'sharp', 'soft', 'loud', 'quiet',
    'bright', 'dark', 'bitter', 'sweet', 'rough', 'smooth',
})


# ============================================================================
# Tokenizer
# ============================================================================

def tokenize_scene(text: str) -> list[str]:
    """Tokenize scene text into lowercase words.

    Handles em dashes as separators, preserves contractions.
    """
    text = text.replace('\u2014', ' ').replace('\u2013', ' ')  # em dash, en dash
    raw_tokens = text.split()
    tokens = []
    for t in raw_tokens:
        cleaned = re.sub(r"^[^\w']+|[^\w']+$", '', t.lower())
        if cleaned:
            tokens.append(cleaned)
    return tokens


# ============================================================================
# N-gram extraction
# ============================================================================

def extract_ngrams(tokens: list[str], n: int,
                   scene_id: str) -> dict[tuple, list[str]]:
    """Extract n-grams from tokens, tracking which scene they came from."""
    ngrams: dict[tuple, list[str]] = {}
    for i in range(len(tokens) - n + 1):
        gram = tuple(tokens[i:i + n])
        if gram not in ngrams:
            ngrams[gram] = []
        if not ngrams[gram] or ngrams[gram][-1] != scene_id:
            ngrams[gram].append(scene_id)
    return ngrams


# ============================================================================
# Categorization
# ============================================================================

def categorize_finding(phrase: str) -> str:
    """Categorize a repeated phrase by heuristic rules."""
    words = phrase.lower().split()
    word_set = set(words)

    if 'like' in words[1:]:
        return 'simile'
    if 'as if' in phrase.lower() or 'as though' in phrase.lower():
        return 'simile'

    if word_set & BODY_PARTS:
        return 'character_tell'

    if word_set & BLOCKING_VERBS:
        return 'blocking_tic'

    if word_set & SENSORY_WORDS:
        return 'sensory'

    for cue in STRUCTURAL_CUES:
        if cue in phrase.lower():
            return 'structural'

    return 'signature_phrase'


# ============================================================================
# Subphrase suppression
# ============================================================================

def suppress_subphrases(findings: list[dict]) -> list[dict]:
    """Suppress shorter phrases contained in longer ones with similar count."""
    if not findings:
        return findings

    sorted_findings = sorted(findings, key=lambda f: -len(f['phrase'].split()))
    kept = []
    suppressed_phrases = set()

    for finding in sorted_findings:
        phrase = finding['phrase']
        if phrase in suppressed_phrases:
            continue
        kept.append(finding)
        for other in sorted_findings:
            other_phrase = other['phrase']
            if other_phrase == phrase:
                continue
            if other_phrase in phrase and abs(other['count'] - finding['count']) <= 1:
                suppressed_phrases.add(other_phrase)

    return kept


# ============================================================================
# Main scanning functions
# ============================================================================

def scan_scenes(scene_texts: dict[str, str],
                min_occurrences: dict[int, int] | None = None) -> list[dict]:
    """Scan scene texts for repeated n-grams.

    Args:
        scene_texts: Dict mapping scene_id to prose text.
        min_occurrences: Override thresholds by n-gram length.

    Returns:
        List of finding dicts with: phrase, category, severity, count, scene_ids.
    """
    thresholds = min_occurrences or THRESHOLDS

    all_ngrams: dict[tuple, list[str]] = {}
    for scene_id, text in scene_texts.items():
        tokens = tokenize_scene(text)
        for n in thresholds:
            scene_ngrams = extract_ngrams(tokens, n, scene_id)
            for gram, scenes in scene_ngrams.items():
                if gram not in all_ngrams:
                    all_ngrams[gram] = []
                all_ngrams[gram].extend(scenes)

    findings = []
    for gram, scene_ids in all_ngrams.items():
        n = len(gram)
        threshold = thresholds.get(n, 2)

        unique_scenes = list(dict.fromkeys(scene_ids))
        if len(unique_scenes) < 2:
            continue
        if len(scene_ids) < threshold:
            continue

        if all(w in STOP_WORDS for w in gram):
            continue

        phrase = ' '.join(gram)
        category = categorize_finding(phrase)
        severity = 'high' if len(scene_ids) >= 4 else 'medium'

        findings.append({
            'phrase': phrase,
            'category': category,
            'severity': severity,
            'count': len(scene_ids),
            'scene_ids': unique_scenes,
        })

    findings = suppress_subphrases(findings)
    findings.sort(key=lambda f: -f['count'])
    return findings


def scan_manuscript(project_dir: str,
                    scene_ids: list[str] | None = None) -> list[dict]:
    """Scan a manuscript's scene files for repeated phrases.

    Args:
        project_dir: Path to the book project root.
        scene_ids: Optional list of scene IDs to scan. Defaults to all scenes.

    Returns:
        List of finding dicts.
    """
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return []

    if scene_ids is None:
        scene_ids = []
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        if os.path.isfile(scenes_csv):
            rows = _read_csv(scenes_csv)
            for row in rows:
                sid = row.get('id', '').strip()
                status = row.get('status', '').strip()
                if sid and status not in ('cut', 'merged', 'spine',
                                          'architecture', 'mapped'):
                    scene_ids.append(sid)
        else:
            for f in sorted(os.listdir(scenes_dir)):
                if f.endswith('.md'):
                    scene_ids.append(f[:-3])

    scene_texts = {}
    for sid in scene_ids:
        path = os.path.join(scenes_dir, f'{sid}.md')
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                scene_texts[sid] = f.read()

    return scan_scenes(scene_texts)

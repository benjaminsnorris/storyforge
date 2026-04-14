"""Shared text analysis utilities for deterministic scoring.

Provides passive voice detection, dialogue extraction, adverb detection,
filler phrase scanning, and AI-tell vocabulary matching.  Pure stdlib —
no API calls, no external dependencies.
"""

import os
import re


# ============================================================================
# Passive voice detection
# ============================================================================

# Common irregular past participles that don't end in -ed
_IRREGULAR_PARTICIPLES = frozenset({
    'been', 'born', 'broken', 'built', 'bought', 'caught', 'chosen',
    'cut', 'done', 'drawn', 'driven', 'eaten', 'fallen', 'felt',
    'found', 'forgotten', 'forgiven', 'frozen', 'given', 'gone',
    'grown', 'heard', 'held', 'hidden', 'hit', 'hung', 'hurt',
    'kept', 'known', 'laid', 'led', 'left', 'lent', 'let', 'lost',
    'made', 'meant', 'met', 'paid', 'put', 'read', 'rid', 'ridden',
    'risen', 'run', 'said', 'seen', 'sent', 'set', 'shaken', 'shed',
    'shot', 'shown', 'shut', 'slept', 'sold', 'sought', 'spoken',
    'spent', 'split', 'spread', 'stood', 'stolen', 'struck', 'stuck',
    'sung', 'sunk', 'swept', 'sworn', 'swum', 'swung', 'taken',
    'taught', 'thought', 'thrown', 'told', 'torn', 'understood',
    'upset', 'woken', 'won', 'worn', 'wound', 'written',
})

# Words ending in -ed that are NOT past participles (adjectives/nouns)
_ED_FALSE_POSITIVES = frozenset({
    'bed', 'fed', 'led', 'red', 'shed', 'sled', 'wed',
    'naked', 'wicked', 'sacred', 'aged', 'beloved', 'crooked',
    'jagged', 'learned', 'ragged', 'rugged',
})

_PASSIVE_AUX = re.compile(
    r'\b(was|were|been|being|is|are|am|get|gets|got|gotten)\s+'
    r'(\w+)\b',
    re.IGNORECASE,
)

# Progressive passive: is/are/was/were being + participle
_PROGRESSIVE_PASSIVE = re.compile(
    r'\b(is|are|was|were)\s+being\s+(\w+)\b',
    re.IGNORECASE,
)


def _is_past_participle(word: str) -> bool:
    """Heuristic check for past participle."""
    w = word.lower()
    if w in _ED_FALSE_POSITIVES:
        return False
    if w in _IRREGULAR_PARTICIPLES:
        return True
    return w.endswith('ed') and len(w) > 3


def detect_passive_voice(text: str) -> list[dict]:
    """Detect passive voice constructions in text.

    Returns list of {'match': str, 'position': int} dicts.
    """
    hits = []
    prog_positions = set()

    # Check progressive passive first (is being built, were being made)
    for m in _PROGRESSIVE_PASSIVE.finditer(text):
        candidate = m.group(2)
        if _is_past_participle(candidate):
            hits.append({'match': m.group(0), 'position': m.start()})
            prog_positions.add(m.start())

    # Standard passive (was thrown, is known)
    for m in _PASSIVE_AUX.finditer(text):
        if m.start() in prog_positions:
            continue
        candidate = m.group(2)
        if _is_past_participle(candidate):
            hits.append({'match': m.group(0), 'position': m.start()})
    return hits


# ============================================================================
# Dialogue extraction
# ============================================================================

_DIALOGUE_RE = re.compile(
    r'[""\u201c](.*?)[""\u201d]',
    re.DOTALL,
)


def extract_dialogue(text: str) -> tuple[str, str]:
    """Split text into dialogue and narration.

    Returns (dialogue_text, narration_text).
    """
    dialogue_parts = []
    narration = text
    for m in _DIALOGUE_RE.finditer(text):
        dialogue_parts.append(m.group(1))
    narration = _DIALOGUE_RE.sub('', text)
    return ' '.join(dialogue_parts), narration


# ============================================================================
# Adverb detection
# ============================================================================

_DIALOGUE_TAG_VERBS = frozenset({
    'said', 'whispered', 'shouted', 'murmured', 'muttered', 'yelled',
    'called', 'cried', 'screamed', 'asked', 'replied', 'answered',
    'demanded', 'exclaimed', 'snapped', 'hissed', 'growled',
    'snarled', 'sighed', 'groaned', 'moaned', 'rasped',
})

_WEAK_VERB_ADVERB_PAIRS = {
    # verb -> adverbs that signal a stronger verb should be used
    'walked': {'slowly', 'quickly', 'heavily', 'quietly', 'softly', 'briskly'},
    'ran': {'quickly', 'fast', 'rapidly'},
    'looked': {'quickly', 'slowly', 'carefully', 'intently', 'closely'},
    'moved': {'slowly', 'quickly', 'quietly', 'carefully'},
    'said': {'quietly', 'softly', 'loudly', 'angrily', 'sadly', 'happily'},
    'went': {'quickly', 'slowly'},
    'came': {'quickly', 'slowly'},
    'got': {'quickly', 'slowly'},
    'put': {'carefully', 'gently', 'quickly'},
    'sat': {'quietly', 'heavily'},
    'stood': {'quietly', 'silently'},
    'ate': {'quickly', 'slowly', 'hungrily', 'greedily'},
    'drank': {'quickly', 'slowly', 'deeply', 'greedily'},
}

_REDUNDANT_ADVERB_PAIRS = {
    # verb -> adverbs that are redundant (verb already implies them)
    'whispered': {'quietly', 'softly'},
    'shouted': {'loudly'},
    'screamed': {'loudly'},
    'yelled': {'loudly'},
    'tiptoed': {'quietly', 'softly'},
    'sprinted': {'quickly', 'fast'},
    'rushed': {'quickly'},
    'crept': {'quietly', 'slowly', 'silently'},
    'strolled': {'slowly', 'leisurely'},
    'demolished': {'completely', 'totally', 'utterly'},
    'destroyed': {'completely', 'totally', 'utterly'},
    'annihilated': {'completely', 'totally', 'utterly'},
    'sobbed': {'sadly'},
    'wept': {'sadly'},
    'beamed': {'happily'},
    'grinned': {'happily'},
}

_TAG_ADVERB_RE = re.compile(
    r'\b(' + '|'.join(_DIALOGUE_TAG_VERBS) + r')\s+(\w+ly)\b',
    re.IGNORECASE,
)

_VERB_ADVERB_RE = re.compile(
    r'\b(\w+)\s+(\w+ly)\b',
    re.IGNORECASE,
)


def detect_adverbs(text: str) -> list[dict]:
    """Detect problematic adverbs in text.

    Returns list of {'match': str, 'category': str, 'position': int} dicts.
    Categories: 'dialogue_tag', 'weak_verb', 'redundant'
    """
    hits = []
    seen_positions = set()

    # 1. Dialogue-tag adverbs
    for m in _TAG_ADVERB_RE.finditer(text):
        verb = m.group(1).lower()
        adverb = m.group(2).lower()
        if verb in _DIALOGUE_TAG_VERBS and adverb.endswith('ly'):
            hits.append({
                'match': m.group(0),
                'category': 'dialogue_tag',
                'position': m.start(),
            })
            seen_positions.add(m.start())

    # 2. Redundant adverbs (check before weak verb to avoid double counting)
    for m in _VERB_ADVERB_RE.finditer(text):
        if m.start() in seen_positions:
            continue
        verb = m.group(1).lower()
        adverb = m.group(2).lower()
        if verb in _REDUNDANT_ADVERB_PAIRS:
            if adverb in _REDUNDANT_ADVERB_PAIRS[verb]:
                hits.append({
                    'match': m.group(0),
                    'category': 'redundant',
                    'position': m.start(),
                })
                seen_positions.add(m.start())

    # 3. Weak verb+adverb pairs
    for m in _VERB_ADVERB_RE.finditer(text):
        if m.start() in seen_positions:
            continue
        verb = m.group(1).lower()
        adverb = m.group(2).lower()
        if verb in _WEAK_VERB_ADVERB_PAIRS:
            if adverb in _WEAK_VERB_ADVERB_PAIRS[verb]:
                hits.append({
                    'match': m.group(0),
                    'category': 'weak_verb',
                    'position': m.start(),
                })
                seen_positions.add(m.start())

    return hits


# ============================================================================
# Filler phrase detection
# ============================================================================

_FILLER_PHRASES = [
    'began to', 'started to', 'seemed to', 'appeared to',
    'managed to', 'attempted to', 'proceeded to', 'continued to',
    'in order to', 'the fact that', 'it was clear that',
    'it was obvious that', 'it was evident that',
    'there was a', 'there were', 'there is a', 'there are',
    'he realized that', 'she realized that', 'they realized that',
    'he noticed that', 'she noticed that', 'they noticed that',
    'he could see', 'she could see', 'they could see',
    'he could hear', 'she could hear', 'they could hear',
    'he could feel', 'she could feel', 'they could feel',
    'a little', 'a bit', 'sort of', 'kind of',
    'that being said', 'needless to say',
]

_FILLER_RE = re.compile(
    r'\b(' + '|'.join(re.escape(p) for p in _FILLER_PHRASES) + r')\b',
    re.IGNORECASE,
)


def detect_filler_phrases(text: str) -> list[dict]:
    """Detect filler/wordy phrases that weaken prose.

    Returns list of {'match': str, 'position': int} dicts.
    """
    return [
        {'match': m.group(0), 'position': m.start()}
        for m in _FILLER_RE.finditer(text)
    ]


# ============================================================================
# AI-tell vocabulary
# ============================================================================

def load_ai_tell_words(plugin_dir: str) -> list[dict]:
    """Load AI-tell vocabulary from references/ai-tell-words.csv.

    Returns list of {'word': str, 'category': str, 'severity': str,
                     'replacement_hint': str}.
    """
    path = os.path.join(plugin_dir, 'references', 'ai-tell-words.csv')
    if not os.path.isfile(path):
        return []
    entries = []
    with open(path, encoding='utf-8') as f:
        header = f.readline()  # skip header
        for line in f:
            fields = line.strip().split('|')
            if len(fields) >= 4:
                entries.append({
                    'word': fields[0].strip(),
                    'category': fields[1].strip(),
                    'severity': fields[2].strip(),
                    'replacement_hint': fields[3].strip(),
                })
    return entries


def detect_ai_tell_hits(text: str, ai_tell_words: list[dict]) -> list[dict]:
    """Detect AI-tell vocabulary in text.

    Returns list of {'word': str, 'category': str, 'severity': str, 'count': int}.
    """
    text_lower = text.lower()
    hits = []
    for entry in ai_tell_words:
        word = entry['word'].lower()
        # Use word boundary matching for single words, substring for phrases
        if ' ' in word:
            count = text_lower.count(word)
        else:
            count = len(re.findall(r'\b' + re.escape(word) + r'\b', text_lower))
        if count > 0:
            hits.append({
                'word': entry['word'],
                'category': entry['category'],
                'severity': entry['severity'],
                'count': count,
            })
    return hits

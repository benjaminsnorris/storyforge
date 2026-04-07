"""Prose exemplar validation and rhythm signature extraction.

Validates exemplar quality (sentence variety, prohibited patterns, length)
and extracts rhythm signatures for injection into drafting prompts.
"""

import os
import re
from typing import Optional


# ============================================================================
# Sentence splitting
# ============================================================================

# Split on sentence boundaries: period/exclamation/question followed by space
# and capital letter, or end of string. Handles common abbreviations.
_SENTENCE_RE = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z"])|(?<=[.!?])\s*$'
)

_ABBREVS = {'mr.', 'mrs.', 'ms.', 'dr.', 'st.', 'vs.', 'etc.', 'e.g.', 'i.e.'}


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, handling common edge cases."""
    # Pre-filter: remove markdown headers and empty lines
    lines = [l for l in text.split('\n') if l.strip() and not l.strip().startswith('#')]
    text = ' '.join(lines)

    # Split on sentence boundaries
    raw = _SENTENCE_RE.split(text)
    sentences = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        # Skip if it's just a markdown artifact or too short to be a sentence
        if len(s) < 5:
            continue
        # Skip abbreviations that look like sentence ends
        lower = s.lower()
        if any(lower.endswith(abbr) for abbr in _ABBREVS):
            if sentences:
                sentences[-1] = sentences[-1] + ' ' + s
            continue
        sentences.append(s)
    return sentences


def word_count(text: str) -> int:
    """Count words in text."""
    return len(text.split())


# ============================================================================
# Rhythm signature
# ============================================================================

def compute_rhythm_signature(exemplar_text: str) -> Optional[dict]:
    """Compute rhythm metrics from exemplar text.

    Returns dict with:
        sentence_count: total sentences
        word_count: total words
        mean_sentence_words: average words per sentence
        stddev_sentence_words: standard deviation
        min_sentence_words: shortest sentence
        max_sentence_words: longest sentence
        buckets: dict of word-count ranges to percentages
            'short' (<8), 'medium' (8-15), 'standard' (15-25),
            'long' (25-35), 'very_long' (35+)
        paragraph_lengths: list of sentence counts per paragraph
        short_ratio: fraction of sentences <8 words
        long_ratio: fraction of sentences >25 words

    Returns None if insufficient text (<3 sentences).
    """
    sentences = split_sentences(exemplar_text)
    if len(sentences) < 3:
        return None

    lengths = [len(s.split()) for s in sentences]
    n = len(lengths)
    mean = sum(lengths) / n
    variance = sum((l - mean) ** 2 for l in lengths) / n
    stddev = variance ** 0.5

    # Bucket distribution
    short = sum(1 for l in lengths if l < 8)
    medium = sum(1 for l in lengths if 8 <= l < 15)
    standard = sum(1 for l in lengths if 15 <= l < 25)
    long = sum(1 for l in lengths if 25 <= l < 35)
    very_long = sum(1 for l in lengths if l >= 35)

    # Paragraph lengths (split on double newline or markdown headers)
    paragraphs = re.split(r'\n\s*\n|^###?\s', exemplar_text, flags=re.MULTILINE)
    para_lengths = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        sents = split_sentences(p)
        if sents:
            para_lengths.append(len(sents))

    return {
        'sentence_count': n,
        'word_count': sum(lengths),
        'mean_sentence_words': round(mean, 1),
        'stddev_sentence_words': round(stddev, 1),
        'min_sentence_words': min(lengths),
        'max_sentence_words': max(lengths),
        'buckets': {
            'short': round(short / n * 100),
            'medium': round(medium / n * 100),
            'standard': round(standard / n * 100),
            'long': round(long / n * 100),
            'very_long': round(very_long / n * 100),
        },
        'paragraph_lengths': para_lengths,
        'short_ratio': round(short / n, 2),
        'long_ratio': round(long / n + very_long / n, 2),
    }


def format_rhythm_for_prompt(sig: dict) -> str:
    """Format a rhythm signature as a drafting constraint block.

    Gives the drafter concrete targets instead of vague "vary sentence length."
    """
    b = sig['buckets']
    return (
        "## Rhythm Target (from your exemplars)\n\n"
        f"Sentence length distribution: "
        f"{b['short']}% under 8 words, "
        f"{b['medium']}% between 8-15, "
        f"{b['standard']}% between 15-25, "
        f"{b['long'] + b['very_long']}% over 25.\n"
        f"Range: {sig['min_sentence_words']}-{sig['max_sentence_words']} words "
        f"(mean {sig['mean_sentence_words']}, stddev {sig['stddev_sentence_words']}).\n"
        "Match this distribution. If your sentences cluster in the 15-25 range, "
        "you're too uniform — add short punchy beats and longer flowing ones."
    )


# ============================================================================
# Validation
# ============================================================================

# Prohibited patterns — exemplars should NOT demonstrate these
_PROHIBITED_PATTERNS = {
    'antithesis': re.compile(
        r'\bnot\b[^.]{5,40}\bbut\b', re.IGNORECASE
    ),
    'tricolon': re.compile(
        r'(?:[^,;]+[,;]\s*){2}and\s+[^.]+\.', re.IGNORECASE
    ),
    'metaphor_restatement': re.compile(
        r'like\s+\w+[^.]{10,}—\s*[a-z]', re.IGNORECASE
    ),
    'interpretive_tag': re.compile(
        r'(?:It was (?:a gesture|her way|his way|their way)|as though|as if to say)',
        re.IGNORECASE
    ),
}


def validate_exemplars(exemplar_text: str) -> dict:
    """Validate exemplar quality.

    Returns dict with:
        valid: bool — overall pass/fail
        issues: list of issue strings
        stats: rhythm signature (or None)
        word_count: total words
    """
    issues = []
    wc = word_count(exemplar_text)

    # Length checks
    if wc < 200:
        issues.append(f'Too short ({wc} words, minimum 200). Add more passages.')
    elif wc > 3000:
        issues.append(f'Too long ({wc} words, maximum 3000). Trim to 3-5 best passages — more dilutes the signal.')

    # Rhythm analysis
    sig = compute_rhythm_signature(exemplar_text)
    if sig:
        # Check sentence length variety
        if sig['stddev_sentence_words'] < 5:
            issues.append(
                f"Low sentence length variety (stddev {sig['stddev_sentence_words']}). "
                "Exemplars should demonstrate varied rhythm — mix short punchy "
                "sentences with longer flowing ones."
            )

        # Check clustering in 15-25 range
        standard_pct = sig['buckets']['standard']
        if standard_pct > 70:
            issues.append(
                f"{standard_pct}% of sentences fall in the 15-25 word range. "
                "This is the AI-default rhythm. Choose exemplars that break this pattern."
            )

        # Check for any short sentences
        if sig['short_ratio'] < 0.1:
            issues.append(
                "No short sentences (<8 words) in exemplars. "
                "Short beats are crucial for rhythm variety."
            )

    # Prohibited pattern scanning
    for name, pattern in _PROHIBITED_PATTERNS.items():
        matches = pattern.findall(exemplar_text)
        if matches:
            label = name.replace('_', ' ')
            issues.append(
                f"Exemplar contains {label} pattern ({len(matches)} instance(s)). "
                "Exemplars should demonstrate the absence of prohibited patterns."
            )

    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'stats': sig,
        'word_count': wc,
    }


def validate_project_exemplars(project_dir: str) -> dict:
    """Validate all exemplar files in a project.

    Returns dict with:
        files: list of {path, pov, validation} dicts
        missing_povs: list of POV names without exemplars
        has_any: bool
    """
    ref_dir = os.path.join(project_dir, 'reference')
    results = {'files': [], 'missing_povs': [], 'has_any': False}

    # Collect POV characters from scenes.csv
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    povs = set()
    if os.path.isfile(scenes_path):
        with open(scenes_path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        if len(lines) > 1:
            headers = lines[0].split('|')
            pov_idx = headers.index('pov') if 'pov' in headers else -1
            if pov_idx >= 0:
                for line in lines[1:]:
                    fields = line.split('|')
                    if pov_idx < len(fields) and fields[pov_idx].strip():
                        povs.add(fields[pov_idx].strip())

    # Check per-POV exemplar files
    exemplars_dir = os.path.join(ref_dir, 'exemplars')
    for pov in sorted(povs):
        pov_slug = pov.lower().replace(' ', '-')
        pov_path = os.path.join(exemplars_dir, f'{pov_slug}.md')
        if os.path.isfile(pov_path):
            with open(pov_path, encoding='utf-8') as f:
                content = f.read()
            validation = validate_exemplars(content)
            results['files'].append({
                'path': pov_path,
                'pov': pov,
                'validation': validation,
            })
            results['has_any'] = True
        else:
            results['missing_povs'].append(pov)

    # Check flat file fallback
    flat_path = os.path.join(ref_dir, 'prose-exemplars.md')
    if os.path.isfile(flat_path):
        with open(flat_path, encoding='utf-8') as f:
            content = f.read()
        validation = validate_exemplars(content)
        results['files'].append({
            'path': flat_path,
            'pov': '(all)',
            'validation': validation,
        })
        results['has_any'] = True
    elif not results['has_any']:
        # No exemplars at all
        results['missing_povs'] = sorted(povs) if povs else ['(no POV data)']

    return results

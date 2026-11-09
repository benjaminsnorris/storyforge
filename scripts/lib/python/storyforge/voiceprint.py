"""The voiceprint fingerprint (plan B2, #650): a writer's measurable habits.

Deterministic and free (no model calls), pure stdlib. A fingerprint is
computed from a corpus of texts and compared with another fingerprint or a
text, measure by measure.

The measures, in groups (`GROUPS`):

- **sentences**: words per sentence (mean, spread, median, 90th percentile),
  the shares of short and long sentences, and words per clause (how far a
  sentence runs between commas, semicolons, colons and dashes);
- **paragraphs**: words and sentences per paragraph, one-sentence
  paragraphs;
- **function_words**: the rate of each of `FUNCTION_WORDS` per 1000 words,
  the classic stylometric signal;
- **punctuation**: commas, semicolons, colons, dashes, parentheses,
  questions, exclamations, ellipses, double quotes and contractions, each
  per 1000 words;
- **readability**: Flesch-Kincaid grade (`readability.count_syllables`'s
  syllables, sentences split here), syllables per word, the share of words
  of three syllables or more, letters per word;
- **vocabulary**: Latinate words (by suffix) per 1000 words, the share of
  one-syllable content words (an Anglo-Saxon proxy), the moving-average
  type-token ratio over 500-word windows, adverbs (`-ly`) and adjectives (a
  suffix heuristic plus a closed list of common adjectives) per 1000 words.
  The Latinate, adverb and adjective counts are heuristics, not a
  part-of-speech tagger: they're consistent, so compare like with like;
- **openings**: how paragraphs open and close, kept apart (paragraphs of
  two sentences or more): the first and last sentences' lengths, the share
  opening on dialogue, a pronoun, an article or a conjunction, the share
  closing on a question, an exclamation or a closing quote.

Outside the distance, a fingerprint also keeps the sentence-length
distribution (`sentence_lengths`), the words paragraphs open on
(`first_words`), the first and last sentences of each piece (`pieces`), and
the phrases the writer uses more often than the general baseline does
(`ngrams`: two- and three-word n-grams, names left out).

**Chunks.** A corpus is cut into chunks of `CHUNK_WORDS` words (at paragraph
breaks) and every measure is taken on each chunk: a measure's `center` is
its median over the chunks, `spread` a robust standard deviation, `p10` /
`p90` the writer's typical range (`Stat`). `value` is the measure over the
whole corpus.

**The distance.** Cosine Delta (Smith and Aldridge 2011, the strongest of
the Delta family for authorship): each measure becomes a z score against the
general baseline's population of writers (`Baseline`: each measure's mean
and standard deviation over 336 chunks of 28 public-domain books by other
writers, `references/voiceprints/baseline.json`), and the distance is one
minus the cosine of the two profiles, function words weighing 1 and every
other measure `OTHER_WEIGHT`. 0 is the same profile; unrelated writers sit
near 1. A comparison also gives each measure's signed z (how many population
standard deviations it sits from the fingerprint's center) and each group's
mean |z|, which say where a difference lies. Distances are on the chunk
scale: a text much longer than a chunk varies less than a chunk does.

API: `fingerprint(texts)` -> `Fingerprint` (`save` / `load`, `to_dict` /
`from_dict`); `profile(chunk_values)` -> a `Fingerprint`'s measures from
chunks already measured; `compare(fp, other)` -> `Comparison` (`other` a
`Fingerprint` or a text; `.distance`, `.groups`, `.measures` of
`MeasureDistance`, `.furthest(n)`); `compare_values(fp, values)`;
`same_voice(a, b)` -> `VoiceMatch`; `consistency(pieces)` -> `Consistency`
(the pieces in another voice, named); `measure(text)` -> every measure's
value; `chunks(text)` -> the text cut as a fingerprint cuts it;
`load_baseline()`, `build_baseline(texts)`, `population_text(raw)`.
`SAME_VOICE_MAX`, `OUTLIER_SEPARATION` and `MIN_CORPUS_WORDS` are calibrated
by `tests/test_voiceprint_reference.py` on the Austen reference voiceprint
(`references/voiceprints/austen/`) and the Verne pair; the measured numbers
are in `references/voiceprints/README.md`.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Mapping, Sequence

from storyforge.illustrations import strip_markers
from storyforge.readability import count_syllables
from storyforge.register import fold

#: bump when a measure's definition changes: a stored fingerprint of another
#: version can't be compared (`Fingerprint.from_dict` refuses it)
FINGERPRINT_VERSION = 1
#: words per chunk, the unit every measure's center and range are taken over
CHUNK_WORDS = 2000
#: fewer chunks than this give no spread worth the name
MIN_CHUNKS = 3
#: a |z| beyond this counts as this (one wild measure can't swamp a profile)
Z_CAP = 6.0
#: the window of the moving-average type-token ratio
MATTR_WINDOW = 500

#: two fingerprints further apart than this don't share a voice. Measured:
#: Austen's three novels 0.21-0.23 apart, the two Verne translations 0.382,
#: Austen and her nearest other author (Middlemarch) 0.61
SAME_VOICE_MAX = 0.30
#: in `consistency`, a minority of pieces is in another voice when its typical
#: piece sits further than this from the rest's. Measured: pure Austen
#: corpora 0.60-0.63; Austen seeded with 20% of another author 0.77-1.50
#: (18 of 21 above it)
OUTLIER_SEPARATION = 0.85
#: the least corpus whose fingerprint is stable: two disjoint samples of
#: this size from the same writer always share a voice (Austen: 10k words
#: up to 0.351 apart, 25k up to 0.221). `voice import`'s minimum-corpus
#: warning (#652)
MIN_CORPUS_WORDS = 25000

GROUPS = ('sentences', 'paragraphs', 'function_words', 'punctuation',
          'readability', 'vocabulary', 'openings')

#: the function words whose rates are measured, most of them the classic
#: stylometric set; the pronouns stay in (person and gender of narration
#: are part of a voice)
FUNCTION_WORDS = (
    'the', 'and', 'of', 'to', 'a', 'in', 'that', 'it', 'was', 'he', 'she', 'i',
    'her', 'his', 'you', 'not', 'be', 'as', 'with', 'had', 'for', 'is', 'but',
    'at', 'on', 'have', 'by', 'which', 'so', 'all', 'my', 'this', 'were',
    'from', 'they', 'would', 'no', 'or', 'could', 'been', 'me', 'him', 'there',
    'an', 'very', 'what', 'them', 'if', 'one', 'their', 'much', 'will', 'more',
    'when', 'we', 'do', 'such', 'must', 'any', 'should', 'might', 'than',
    'only', 'then', 'now', 'its', 'our', 'your', 'who', 'some', 'can', 'upon',
    'into', 'out', 'up', 'though', 'yet', 'every', 'nothing', 'even', 'too',
    'being', 'own', 'how', 'where', 'before', 'after', 'am', 'are', 'shall',
    'did', 'may', 'never', 'most', 'little', 'well', 'about', 'other', 'over',
    'again', 'still', 'ever', 'indeed', 'quite', 'rather', 'perhaps', 'however',
)
_FUNCTION_SET = frozenset(FUNCTION_WORDS)

#: sentence-length buckets of the stored distribution (upper bounds, words)
_LENGTH_BUCKETS = ((5, '1-5'), (10, '6-10'), (15, '11-15'), (20, '16-20'),
                   (30, '21-30'), (40, '31-40'), (60, '41-60'), (None, '61+'))
SHORT_SENTENCE = 8
LONG_SENTENCE = 30

_PRONOUNS = frozenset({'i', 'you', 'he', 'she', 'it', 'we', 'they', 'his', 'her',
                       'my', 'your', 'our', 'their', 'its', 'me', 'him', 'us', 'them'})
_ARTICLES = frozenset({'the', 'a', 'an'})
_CONJUNCTIONS = frozenset({'and', 'but', 'or', 'yet', 'so', 'for', 'nor'})
#: abbreviations whose full stop doesn't end a sentence
_ABBREVIATIONS = frozenset({
    'mr', 'mrs', 'ms', 'dr', 'st', 'messrs', 'mme', 'mlle', 'mm', 'col', 'capt',
    'gen', 'lieut', 'lt', 'rev', 'esq', 'sr', 'jr', 'prof', 'hon', 'sgt', 'vol',
    'ch', 'vs', 'viz', 'cf', 'ft', 'mt', 'gov', 'sen', 'rep', 'maj', 'cmdr',
})
#: contractions spelled without n't/'ll/'re/'ve/'m/'d
_CONTRACTION_WORDS = frozenset({"it's", "that's", "there's", "he's", "she's",
                                "what's", "who's", "here's", "where's", "let's",
                                "how's", "tis", "twas"})
_CONTRACTION_RE = re.compile(r"(?:n't|'ll|'re|'ve|'m|'d)$")
#: Latinate suffixes, each with the shortest word it counts in (shorter
#: words ending so are mostly native: "went", "late", "pure")
_LATINATE_SUFFIXES = (
    ('tion', 5), ('sion', 5), ('ment', 6), ('ity', 5), ('ence', 6), ('ance', 6),
    ('ency', 6), ('ancy', 6), ('ous', 6), ('ive', 6), ('ible', 6), ('able', 6),
    ('ate', 7), ('ent', 7), ('ant', 7), ('ure', 7), ('ial', 6), ('ual', 6),
    ('ism', 6), ('ize', 6), ('ise', 7), ('ify', 6),
)
#: -ly words that aren't adverbs (or aren't -ly adverbs worth the name)
_NOT_ADVERBS = frozenset({
    'only', 'family', 'early', 'holy', 'ugly', 'lovely', 'friendly', 'lonely',
    'daily', 'reply', 'supply', 'fly', 'july', 'italy', 'apply', 'ally', 'belly',
    'bully', 'jelly', 'rely', 'silly', 'folly', 'lily', 'sally', 'kelly', 'emily',
    'molly', 'polly', 'billy', 'jolly', 'hilly', 'chilly', 'woolly', 'curly',
    'likely', 'unlikely', 'elderly', 'orderly', 'costly', 'deadly', 'manly',
    'womanly', 'kindly', 'sickly', 'stately', 'comely', 'homely', 'lowly',
    'gentlemanly', 'brotherly', 'sisterly', 'motherly', 'fatherly', 'worldly',
    'heavenly', 'ghostly', 'beastly', 'cowardly', 'scholarly', 'courtly',
    'monthly', 'weekly', 'yearly', 'hourly', 'nightly', 'butterfly', 'anomaly',
    'assembly', 'monopoly', 'melancholy', 'rally', 'tally', 'gully', 'dolly',
    'wily', 'oily', 'surly', 'burly', 'ally', 'imply', 'comply', 'multiply',
})
_ADJECTIVE_SUFFIXES = (('ous', 5), ('ful', 5), ('less', 6), ('able', 6), ('ible', 6),
                       ('ive', 5), ('ical', 6), ('ish', 6), ('ic', 5), ('ary', 6),
                       ('ent', 7), ('ant', 7), ('al', 6))
#: common adjectives no suffix marks
_ADJECTIVES = frozenset({
    'good', 'great', 'little', 'old', 'young', 'small', 'large', 'long', 'high',
    'new', 'poor', 'rich', 'happy', 'dear', 'pretty', 'fine', 'whole', 'true',
    'sure', 'best', 'better', 'worse', 'worst', 'bad', 'big', 'short', 'low',
    'kind', 'strong', 'weak', 'dark', 'light', 'bright', 'black', 'white',
    'red', 'green', 'blue', 'cold', 'warm', 'hot', 'wide', 'deep', 'quiet',
    'loud', 'sweet', 'bitter', 'proud', 'glad', 'sorry', 'angry', 'easy',
    'hard', 'soft', 'clear', 'clean', 'free', 'full', 'empty', 'wild', 'calm',
    'strange', 'real', 'wrong', 'right', 'certain', 'sad', 'ill', 'handsome',
    'agreeable', 'amiable', 'civil', 'polite', 'clever', 'silly', 'foolish',
    'wise', 'sensible', 'eager', 'gentle', 'grand', 'plain', 'odd', 'rare',
    'safe', 'quick', 'slow', 'thin', 'thick', 'heavy', 'grave', 'serious',
    'pleasant', 'charming', 'lovely', 'ugly', 'stupid', 'dull', 'brave',
})
#: a word: letters (any script), joined by apostrophes or hyphens
_WORD_RE = re.compile(r"[^\W\d_]+(?:['\-][^\W\d_]+)*")
#: a candidate sentence end: . ! ? (any closing quotes or brackets), then
#: space and an opening quote, bracket, capital or digit
_BOUNDARY_RE = re.compile(r'[.!?]+["\')\]]*(?=\s+["\'(\[]*[^\W_a-z])')
#: a chapter's number: roman, arabic, or spelled ("the Third", "FORTY-FOURTH")
_NUMBER = (r'(?:[ivxlcdm]+|\d+|(?:the\s+)?(?:(?:twenty|thirty|forty|fifty|sixty|seventy|'
           r'eighty|ninety)-?)?(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|'
           r'twelve|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|'
           r'eleventh|twelfth|[a-z]+teen(?:th)?|twenty|thirty|forty|fifty|[a-z]+ieth))')
#: a markdown heading, a scene break, a bare chapter heading ("CHAPTER IV.",
#: "Part Two: The Return", "XIV.") but not prose that opens on such a word
#: ("Part of me wanted to go.")
_NON_PROSE_RE = re.compile(
    r'^\s*(?:#.*|[*\-_=~](?:\s*[*\-_=~]){2,}'
    r'|(?:chapter|book|volume|vol\.|part|stave|canto|letter|section)\s+' + _NUMBER
    + r'\b[.:]?(?:\s*[.:\-—]?\s+[^.!?]{0,60}[.]?)?'
    r'|[ivxlcdm]+\.?|\d+\.?|the end\.?|finis\.?)\s*$',
    re.IGNORECASE)
_ILLUSTRATION_RE = re.compile(r'\[Illustration[^\]]*\]', re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r'!?\[([^\]]*)\]\([^)]*\)')
_CLAUSE_RE = re.compile(r'[,;:—()]')


class VoiceprintError(Exception):
    """A fingerprint that can't be made or read; the message says why."""


# ============================================================================
# Text
# ============================================================================

@lru_cache(maxsize=200_000)
def _syllables(word: str) -> int:
    return count_syllables(word)


def paragraphs(text: str) -> list[str]:
    """The prose paragraphs of `text`, one line each: blank lines separate
    paragraphs; headings, scene breaks, bare chapter headings and
    illustration markers are dropped; curly quotes are folded straight,
    `--` and spaced en dashes become em dashes, emphasis marks and link
    syntax go."""
    text = strip_markers(text.lstrip('﻿').replace('\r\n', '\n').replace('\r', '\n'))
    text = _ILLUSTRATION_RE.sub('', fold(text))
    text = _LINK_RE.sub(r'\1', text)
    text = text.replace('--', '—').replace(' – ', ' — ').replace('…', '...')
    out = []
    for block in re.split(r'\n\s*\n', text):
        para = ' '.join(line.strip() for line in block.split('\n') if line.strip())
        if not para or _NON_PROSE_RE.match(para):
            continue
        para = re.sub(r'[*_]+', '', para).strip()
        if _WORD_RE.search(para):
            out.append(para)
    return out


def split_sentences(paragraph: str) -> list[str]:
    """One paragraph's sentences. A sentence ends at . ! or ? (and any
    closing quotes) before a capital, digit or opening quote, so "Oh! single"
    and '"Why?" said he' run on; a full stop after a title ("Mr.") or a
    single capital (an initial) doesn't end one."""
    out, start = [], 0
    for m in _BOUNDARY_RE.finditer(paragraph):
        if m.group(0)[0] == '.' and m.group(0).count('.') == 1:
            before = re.search(r'([^\W\d_]+)$', paragraph[start:m.start()])
            token = before.group(1) if before else ''
            if token.lower() in _ABBREVIATIONS or (len(token) == 1 and token.isupper()
                                                   and token not in 'IA'):
                continue
        sent = paragraph[start:m.end()].strip()
        if _WORD_RE.search(sent):
            out.append(sent)
        start = m.end()
    tail = paragraph[start:].strip()
    if _WORD_RE.search(tail):
        out.append(tail)
    return out


def words(text: str) -> list[str]:
    """The words of `text` as written (case kept)."""
    return _WORD_RE.findall(text)


@dataclass(frozen=True)
class _Para:
    sentences: tuple[tuple[str, ...], ...]   # each sentence's words, as written
    text: str

    @property
    def n_words(self) -> int:
        return sum(len(s) for s in self.sentences)


def _parse(paras: Iterable[str]) -> list[_Para]:
    out = []
    for p in paras:
        sents = tuple(tuple(words(s)) for s in split_sentences(p))
        sents = tuple(s for s in sents if s)
        if sents:
            out.append(_Para(sents, p))
    return out


def _chunk_paras(paras: Sequence[_Para], size: int = CHUNK_WORDS) -> list[list[_Para]]:
    """Consecutive runs of paragraphs of at least `size` words; a last run
    under half that is dropped (too short to measure on the chunk scale)."""
    out, cur, n = [], [], 0
    for p in paras:
        cur.append(p)
        n += p.n_words
        if n >= size:
            out.append(cur)
            cur, n = [], 0
    if cur and n >= size / 2:
        out.append(cur)
    return out


def chunks(text: str, size: int = CHUNK_WORDS) -> list[str]:
    """`text` cut as a fingerprint cuts it: runs of whole paragraphs of at
    least `size` words, a short last run dropped, each run's paragraphs
    joined by blank lines."""
    return ['\n\n'.join(p.text for p in run)
            for run in _chunk_paras(_parse(paragraphs(text)), size)]


# ============================================================================
# Measures
# ============================================================================

def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _per_k(count: float, n: int) -> float:
    return 1000.0 * count / n if n else 0.0


def _share(count: float, n: int) -> float:
    return count / n if n else 0.0


def _mattr(lower: Sequence[str], window: int = MATTR_WINDOW) -> float:
    """Moving-average type-token ratio; the plain ratio under one window."""
    if not lower:
        return 0.0
    if len(lower) <= window:
        return len(set(lower)) / len(lower)
    counts = Counter(lower[:window])
    total = len(counts)
    for i in range(window, len(lower)):
        out_w, in_w = lower[i - window], lower[i]
        counts[out_w] -= 1
        if not counts[out_w]:
            del counts[out_w]
        counts[in_w] += 1
        total += len(counts)
    return total / (len(lower) - window + 1) / window


def _is_latinate(w: str) -> bool:
    return any(w.endswith(s) and len(w) >= n for s, n in _LATINATE_SUFFIXES)


def _is_adverb(w: str) -> bool:
    return w.endswith('ly') and len(w) >= 5 and w not in _NOT_ADVERBS


def _is_adjective(w: str) -> bool:
    if w in _ADJECTIVES:
        return True
    if w in _FUNCTION_SET or _is_adverb(w):
        return False
    return any(w.endswith(s) and len(w) >= n for s, n in _ADJECTIVE_SUFFIXES)


def _is_contraction(w: str) -> bool:
    return bool(_CONTRACTION_RE.search(w)) or w in _CONTRACTION_WORDS


def _measures(paras: Sequence[_Para]) -> dict[str, float]:
    """Every measure, by name, for a run of paragraphs."""
    sent_lens = [len(s) for p in paras for s in p.sentences]
    all_words = [w for p in paras for s in p.sentences for w in s]
    lower = [w.lower() for w in all_words]
    n = len(lower)
    m: dict[str, float] = {}
    if not n:
        return {name: 0.0 for name in measure_names()}
    lens_sorted = sorted(sent_lens)
    mean_len = statistics.fmean(sent_lens)
    sd_len = statistics.pstdev(sent_lens)
    text = '\n'.join(p.text for p in paras)
    clauses = [c for p in paras for c in _CLAUSE_RE.split(p.text) if _WORD_RE.search(c)]

    # sentences
    m['sentence_mean'] = mean_len
    m['sentence_sd'] = sd_len
    m['sentence_cv'] = sd_len / mean_len if mean_len else 0.0
    m['sentence_median'] = _quantile(lens_sorted, 0.5)
    m['sentence_p90'] = _quantile(lens_sorted, 0.9)
    m['short_sentence_share'] = _share(sum(1 for x in sent_lens if x <= SHORT_SENTENCE),
                                       len(sent_lens))
    m['long_sentence_share'] = _share(sum(1 for x in sent_lens if x >= LONG_SENTENCE),
                                      len(sent_lens))
    m['clause_mean'] = n / len(clauses) if clauses else float(n)

    # paragraphs
    para_lens = [p.n_words for p in paras]
    m['paragraph_mean'] = statistics.fmean(para_lens)
    m['paragraph_sd'] = statistics.pstdev(para_lens)
    m['paragraph_median'] = _quantile(sorted(para_lens), 0.5)
    m['sentences_per_paragraph'] = statistics.fmean(len(p.sentences) for p in paras)
    m['one_sentence_paragraph_share'] = _share(
        sum(1 for p in paras if len(p.sentences) == 1), len(paras))

    # function words
    counts = Counter(lower)
    for fw in FUNCTION_WORDS:
        m[f'fw_{fw}'] = _per_k(counts[fw], n)

    # punctuation
    for name, ch in (('comma', ','), ('semicolon', ';'), ('colon', ':'), ('dash', '—'),
                     ('parenthesis', '('), ('question', '?'), ('exclamation', '!'),
                     ('double_quote', '"')):
        m[f'{name}_rate'] = _per_k(text.count(ch), n)
    m['ellipsis_rate'] = _per_k(text.count('...'), n)
    m['contraction_rate'] = _per_k(sum(1 for w in lower if _is_contraction(w)), n)

    # readability
    syll = [_syllables(w) for w in lower]
    m['fk_grade'] = 0.39 * n / len(sent_lens) + 11.8 * sum(syll) / n - 15.59
    m['syllables_per_word'] = sum(syll) / n
    m['long_word_share'] = _share(sum(1 for s in syll if s >= 3), n)
    m['letters_per_word'] = sum(len(w.replace("'", '').replace('-', '')) for w in lower) / n

    # vocabulary
    content = [(w, s) for w, s in zip(lower, syll) if w not in _FUNCTION_SET]
    m['latinate_rate'] = _per_k(sum(1 for w in lower if _is_latinate(w)), n)
    m['monosyllable_content_share'] = _share(sum(1 for _, s in content if s == 1),
                                             len(content))
    m['mattr'] = _mattr(lower)
    m['adverb_rate'] = _per_k(sum(1 for w in lower if _is_adverb(w)), n)
    m['adjective_rate'] = _per_k(sum(1 for w in lower if _is_adjective(w)), n)

    # openings and closings (paragraphs of two sentences or more)
    multi = [p for p in paras if len(p.sentences) >= 2]
    firsts = [p.sentences[0] for p in multi]
    lasts = [p.sentences[-1] for p in multi]
    k = len(multi)
    m['opening_sentence_mean'] = statistics.fmean(len(s) for s in firsts) if k else 0.0
    m['closing_sentence_mean'] = statistics.fmean(len(s) for s in lasts) if k else 0.0
    m['opening_dialogue_share'] = _share(sum(1 for p in paras if p.text[:1] in '"\''),
                                         len(paras))
    m['opening_pronoun_share'] = _share(sum(1 for s in firsts if s[0].lower() in _PRONOUNS), k)
    m['opening_article_share'] = _share(sum(1 for s in firsts if s[0].lower() in _ARTICLES), k)
    m['opening_conjunction_share'] = _share(
        sum(1 for s in firsts if s[0].lower() in _CONJUNCTIONS), k)
    last_texts = [split_sentences(p.text)[-1] for p in multi]
    m['closing_question_share'] = _share(
        sum(1 for t in last_texts if '?' in t.rstrip('"\')] ')[-1:]), k)
    m['closing_exclamation_share'] = _share(
        sum(1 for t in last_texts if '!' in t.rstrip('"\')] ')[-1:]), k)
    m['closing_quote_share'] = _share(sum(1 for t in last_texts if t.rstrip()[-1:] in '"\''), k)
    return m


@lru_cache(maxsize=1)
def _names_and_groups() -> tuple[tuple[str, str], ...]:
    sample = _Para(((('A', 'b'),) * 2), 'A b. A b.')
    names = list(_measures([sample]))
    out = []
    for name in names:
        if name.startswith('fw_'):
            g = 'function_words'
        elif name.startswith(('sentence_', 'short_sentence', 'long_sentence', 'clause_')):
            g = 'sentences'
        elif name.startswith(('paragraph_', 'sentences_per', 'one_sentence')):
            g = 'paragraphs'
        elif name.endswith('_rate') and name not in ('latinate_rate', 'adverb_rate',
                                                     'adjective_rate'):
            g = 'punctuation'
        elif name in ('fk_grade', 'syllables_per_word', 'long_word_share', 'letters_per_word'):
            g = 'readability'
        elif name.startswith(('opening_', 'closing_')):
            g = 'openings'
        else:
            g = 'vocabulary'
        out.append((name, g))
    return tuple(out)


def measure_names() -> tuple[str, ...]:
    """Every measure's name, in a fixed order."""
    return tuple(n for n, _ in _names_and_groups())


def measure_group(name: str) -> str:
    """The group (`GROUPS`) a measure belongs to."""
    return dict(_names_and_groups())[name]


def measure(text: str) -> dict[str, float]:
    """Every measure's value for `text`, by name (all 0.0 for a text with no
    prose)."""
    return _measures(_parse(paragraphs(text)))


# ============================================================================
# The general baseline: the population's spread, and its n-gram rates
# ============================================================================

BASELINE_REL = os.path.join('references', 'voiceprints', 'baseline.json')
NGRAM_SIZES = (2, 3)
#: an n-gram counts only when it occurs this often in the corpus
NGRAM_MIN_COUNT = 5
#: per million n-grams, added to both sides of the ratio (smoothing)
NGRAM_SMOOTHING = 20.0
NGRAM_KEEP = 40


def _is_rate(name: str) -> bool:
    """A measure counted per 1000 words (a function word, a punctuation mark,
    a kind of word)."""
    return name.startswith('fw_') or name.endswith('_rate')


def _noise_floor(name: str, center: float) -> float:
    """The least spread a measure can have on the chunk scale: for a rate per
    1000 words, a chunk's counting noise (Poisson: a rare word's count of 1
    or 3 in a chunk is chance, not voice); else 1% of the scale (shares) or
    5% of the center."""
    if _is_rate(name):
        unit = 1000.0 / CHUNK_WORDS
        return math.sqrt(max(center, unit) * unit)
    return max(0.05 * abs(center), 0.01)


def _spread(values: Sequence[float], center: float, name: str) -> float:
    """A robust standard deviation (1.4826 x the median absolute deviation),
    floored at half the plain standard deviation (a measure most chunks
    score 0 on, exclamations, still has a spread) and at `_noise_floor`."""
    mad = statistics.median(abs(v - center) for v in values)
    sd = statistics.pstdev(values) if len(values) > 1 else 0.0
    return max(1.4826 * mad, 0.5 * sd, _noise_floor(name, center))


def _proper_words(paras: Sequence[_Para]) -> frozenset[str]:
    """Lower-cased words written with a capital in most of their occurrences
    away from a sentence's start: names, which say what a book is about, not
    how its writer writes."""
    caps: Counter = Counter()
    seen: Counter = Counter()
    for p in paras:
        for s in p.sentences:
            for w in s[1:]:
                lw = w.lower()
                seen[lw] += 1
                if w[:1].isupper():
                    caps[lw] += 1
    return frozenset(w for w, c in caps.items() if w != 'i' and c * 2 > seen[w])


def _ngram_counts(paras: Sequence[_Para], n: int, proper: frozenset[str]) -> Counter:
    out: Counter = Counter()
    for p in paras:
        for s in p.sentences:
            low = [w.lower() for w in s]
            for i in range(len(low) - n + 1):
                gram = low[i:i + n]
                if not any(g in proper for g in gram):
                    out[' '.join(gram)] += 1
    return out


@dataclass(frozen=True)
class Baseline:
    """The general baseline: each measure's `mean` and `sd` over the chunks
    of a population of writers (the distance's scale, as Burrows' Delta
    standardizes by the population), and the population's n-gram rates per
    million (`ngrams[n]`, names left out; `ngram_floor[n]` stands in for an
    n-gram the table doesn't hold)."""
    mean: dict[str, float]
    sd: dict[str, float]
    ngrams: dict[int, dict[str, float]]
    ngram_floor: dict[int, float]
    sources: tuple[str, ...] = ()


def build_baseline(texts: Mapping[str, str], chunks_per_text: int = 12,
                   keep: int = 4000) -> dict:
    """The general baseline's data (what `baseline.json` holds) from a
    population of texts by name: each measure's mean and sd over up to
    `chunks_per_text` chunks of each text, spaced evenly through it, and
    the `keep` most frequent n-grams of each size over the whole texts.
    Every measure's sd is floored at its noise floor."""
    chunk_values, paras_all, sources = [], [], []
    for name, text in texts.items():
        paras = _parse(paragraphs(text))
        runs = _chunk_paras(paras)
        if not runs:
            raise VoiceprintError(f'baseline text {name} has no chunk of {CHUNK_WORDS} words')
        step = max(1, len(runs) // chunks_per_text)
        picked = runs[::step][:chunks_per_text]
        chunk_values += [_measures(r) for r in picked]
        paras_all += paras
        sources.append({'name': name, 'words': sum(p.n_words for p in paras),
                        'chunks': len(picked)})
    measures = {}
    for mname in measure_names():
        vals = [c[mname] for c in chunk_values]
        mean = statistics.fmean(vals)
        sd = max(statistics.pstdev(vals), _noise_floor(mname, mean))
        measures[mname] = [_round(mean), _round(sd)]
    proper = _proper_words(paras_all)
    grams = {}
    for n in NGRAM_SIZES:
        counts = _ngram_counts(paras_all, n, proper)
        total = sum(counts.values())
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:keep]
        grams[str(n)] = {'total': total, 'rates': {g: _round(1e6 * c / total) for g, c in top}}
    return {'version': FINGERPRINT_VERSION, 'chunk_words': CHUNK_WORDS,
            'sources': sources, 'measures': measures, 'ngrams': grams}


#: of a Gutenberg text's paragraphs, the shares dropped from the front (title
#: page, contents, preface) and the back (notes, advertisements)
POPULATION_TRIM = (0.04, 0.02)


def population_text(raw: str) -> str:
    """A raw Project Gutenberg download as a baseline population text, with
    no per-book config: the header and licence stripped
    (`gutenberg.strip_boilerplate`), then the first and last
    `POPULATION_TRIM` of its paragraphs dropped. Good enough for population
    figures; a corpus text wants its front matter cut exactly."""
    from storyforge.gutenberg import strip_boilerplate
    body = '\n'.join(strip_boilerplate(raw.replace('\r\n', '\n').split('\n')))
    paras = paragraphs(body)
    front, back = (int(len(paras) * share) for share in POPULATION_TRIM)
    return '\n\n'.join(paras[front:len(paras) - back])


_BASELINE_CACHE: dict[str, Baseline] = {}


def load_baseline(path: str | None = None) -> Baseline:
    """The general baseline (`BASELINE_REL` in the plugin by default).
    Raises VoiceprintError when it can't be read or doesn't fit this
    Storyforge's measures."""
    if path is None:
        from storyforge.common import get_plugin_dir
        path = os.path.join(get_plugin_dir(), BASELINE_REL)
    if path in _BASELINE_CACHE:
        return _BASELINE_CACHE[path]
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise VoiceprintError(f'the voiceprint baseline {path} could not be read: {e}') from e
    if data.get('version') != FINGERPRINT_VERSION or data.get('chunk_words') != CHUNK_WORDS:
        raise VoiceprintError(f'the voiceprint baseline {path} was built for another '
                              f'version or chunk size; build it again')
    measures = data.get('measures', {})
    missing = [n for n in measure_names() if n not in measures]
    if missing:
        raise VoiceprintError(f'the voiceprint baseline {path} has no figures for '
                              f'{", ".join(missing[:5])}; build it again')
    grams = data.get('ngrams', {})
    if not all(str(n) in grams for n in NGRAM_SIZES):
        raise VoiceprintError(f'the voiceprint baseline {path} has no n-gram table for '
                              f'each of n = {NGRAM_SIZES}; build it again')
    tables = {n: grams[str(n)]['rates'] for n in NGRAM_SIZES}
    base = Baseline({n: measures[n][0] for n in measure_names()},
                    {n: measures[n][1] for n in measure_names()},
                    tables, {n: min(t.values()) if t else 0.0 for n, t in tables.items()},
                    tuple(s.get('name', '') for s in data.get('sources', [])))
    _BASELINE_CACHE[path] = base
    return base


def _overrepresented(paras: Sequence[_Para], baseline: Baseline) -> dict[str, list]:
    """Each size's n-grams the corpus uses more than the baseline does, most
    over-represented first (ratio weighted by the square root of the count):
    `[ngram, count, ratio]`."""
    proper = _proper_words(paras)
    out = {}
    for n in NGRAM_SIZES:
        counts = _ngram_counts(paras, n, proper)
        total = sum(counts.values()) or 1
        table, floor = baseline.ngrams[n], baseline.ngram_floor[n]
        scored = []
        for gram, c in counts.items():
            if c < NGRAM_MIN_COUNT:
                continue
            rate = 1e6 * c / total
            ratio = (rate + NGRAM_SMOOTHING) / (table.get(gram, floor) + NGRAM_SMOOTHING)
            if ratio > 1:
                scored.append((gram, c, _round(ratio)))
        scored.sort(key=lambda x: (-x[2] * math.sqrt(x[1]), x[0]))
        out[str(n)] = [list(x) for x in scored[:NGRAM_KEEP]]
    return out


# ============================================================================
# Fingerprint
# ============================================================================

def _round(x: float) -> float:
    return float(f'{x:.6g}')


@dataclass(frozen=True)
class Stat:
    """One measure over a corpus: `value` over the whole corpus; `center`
    (median), `spread` (robust, `_spread`), `p10` and `p90` over its chunks.
    `p10`..`p90` is the writer's typical range."""
    value: float
    center: float
    spread: float
    p10: float
    p90: float

    def to_list(self) -> list[float]:
        return [self.value, self.center, self.spread, self.p10, self.p90]


@dataclass(frozen=True)
class Fingerprint:
    words: int
    sentences: int
    paragraphs: int
    chunks: int
    stats: dict[str, Stat]
    sentence_lengths: dict[str, float] = field(default_factory=dict)
    first_words: dict[str, float] = field(default_factory=dict)
    pieces: list[dict] = field(default_factory=list)
    ngrams: dict[str, list] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'version': FINGERPRINT_VERSION,
            'chunk_words': CHUNK_WORDS,
            'words': self.words,
            'sentences': self.sentences,
            'paragraphs': self.paragraphs,
            'chunks': self.chunks,
            'stat_fields': ['value', 'center', 'spread', 'p10', 'p90'],
            'measures': {name: {'group': measure_group(name),
                                'stat': [_round(x) for x in s.to_list()]}
                         for name, s in self.stats.items()},
            'sentence_lengths': self.sentence_lengths,
            'first_words': self.first_words,
            'pieces': self.pieces,
            'ngrams': self.ngrams,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Fingerprint':
        """Raises VoiceprintError for another version, chunk size or measure
        set (a fingerprint made by another Storyforge: compute it again)."""
        if data.get('version') != FINGERPRINT_VERSION:
            raise VoiceprintError(
                f'fingerprint version {data.get("version")!r} is not this Storyforge\'s '
                f'({FINGERPRINT_VERSION}); compute it again')
        if data.get('chunk_words') != CHUNK_WORDS:
            raise VoiceprintError(f'fingerprint chunks of {data.get("chunk_words")!r} words, '
                                  f'not {CHUNK_WORDS}; compute it again')
        names = set(measure_names())
        got = set(data.get('measures', {}))
        if got != names:
            missing, extra = sorted(names - got), sorted(got - names)
            raise VoiceprintError(f'fingerprint measures differ from this Storyforge\'s '
                                  f'(missing {missing[:5]}, unknown {extra[:5]}); '
                                  f'compute it again')
        stats = {n: Stat(*data['measures'][n]['stat']) for n in measure_names()}
        return cls(data['words'], data['sentences'], data['paragraphs'], data['chunks'],
                   stats, data.get('sentence_lengths', {}), data.get('first_words', {}),
                   data.get('pieces', []), data.get('ngrams', {}))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=1, ensure_ascii=False) + '\n'

    def save(self, path: str) -> None:
        """Write `fingerprint.json` (LF, UTF-8)."""
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> 'Fingerprint':
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise VoiceprintError(f'{path} could not be read: {e}') from e
        return cls.from_dict(data)


def _stats(per_chunk: Sequence[Mapping[str, float]],
           whole: Mapping[str, float] | None = None) -> dict[str, Stat]:
    stats = {}
    for name in measure_names():
        vals = sorted(c[name] for c in per_chunk)
        center = statistics.median(vals)
        stats[name] = Stat(whole[name] if whole is not None else center, center,
                           _spread(vals, center, name),
                           _quantile(vals, 0.1), _quantile(vals, 0.9))
    return stats


def profile(chunk_values: Sequence[Mapping[str, float]]) -> Fingerprint:
    """A fingerprint's measures from chunks already measured (`measure` of
    each of `chunks(text)`), for comparing without measuring a text twice:
    its stats are the ones `fingerprint` would give those chunks (`value` is
    the center), its counts and descriptive fields empty. Raises
    VoiceprintError under `MIN_CHUNKS` chunks."""
    if len(chunk_values) < MIN_CHUNKS:
        raise VoiceprintError(f'{len(chunk_values)} chunks: a fingerprint needs at least '
                              f'{MIN_CHUNKS}')
    return Fingerprint(0, 0, 0, len(chunk_values), _stats(chunk_values))


def _as_pieces(texts: Mapping[str, str] | Sequence[str] | str) -> list[tuple[str, str]]:
    if isinstance(texts, str):
        return [('text', texts)]
    if isinstance(texts, Mapping):
        return list(texts.items())
    return [(f'text-{i + 1}', t) for i, t in enumerate(texts)]


def fingerprint(texts: Mapping[str, str] | Sequence[str] | str,
                baseline: Baseline | None = None, ngrams: bool = True) -> Fingerprint:
    """The fingerprint of a corpus: `texts` by name (a mapping keeps the
    names, in order), a list, or one text. Raises VoiceprintError for a
    corpus under `MIN_CHUNKS` chunks of `CHUNK_WORDS` words, or (with
    `ngrams`) when the baseline can't be read. `ngrams=False` leaves the
    phrase list empty (the distance never uses it)."""
    pieces = _as_pieces(texts)
    parsed = [(name, _parse(paragraphs(t))) for name, t in pieces]
    paras = [p for _, ps in parsed for p in ps]
    runs = _chunk_paras(paras)
    n_words = sum(p.n_words for p in paras)
    if len(runs) < MIN_CHUNKS:
        raise VoiceprintError(
            f'the corpus has {n_words} words of prose: a fingerprint needs at least '
            f'{MIN_CHUNKS} chunks of {CHUNK_WORDS} words ({MIN_CHUNKS * CHUNK_WORDS} words)')
    stats = _stats([_measures(run) for run in runs], _measures(paras))
    sent_lens = [len(s) for p in paras for s in p.sentences]
    buckets: Counter = Counter()
    for x in sent_lens:
        buckets[next(label for bound, label in _LENGTH_BUCKETS
                     if bound is None or x <= bound)] += 1
    lengths = {label: _round(_share(buckets[label], len(sent_lens)))
               for _, label in _LENGTH_BUCKETS}
    first = Counter(p.sentences[0][0].lower() for p in paras)
    first_words = {w: _round(_share(c, len(paras)))
                   for w, c in sorted(first.items(), key=lambda kv: (-kv[1], kv[0]))[:15]}
    piece_info = []
    for name, ps in parsed:
        if not ps:
            piece_info.append({'name': name, 'words': 0})
            continue
        sents = [s for p in ps for s in split_sentences(p.text)]
        piece_info.append({'name': name, 'words': sum(p.n_words for p in ps),
                           'first_sentence': sents[0], 'last_sentence': sents[-1]})
    grams = _overrepresented(paras, baseline or load_baseline()) if ngrams else {}
    return Fingerprint(n_words, len(sent_lens), len(paras), len(runs), stats,
                       lengths, first_words, piece_info, grams)


# ============================================================================
# Comparison
# ============================================================================

#: in the distance, each measure outside the function words weighs this much
#: of a function word (the function words are the steadiest signal of who
#: wrote a text; the rest add a little)
OTHER_WEIGHT = 0.25


@dataclass(frozen=True)
class MeasureDistance:
    """How far one measure sits from the fingerprint's center, in population
    standard deviations (`scale`, the baseline's): `z`, signed (positive:
    more than the fingerprint's center) and capped at `Z_CAP`. `typical`
    when `value` is inside the fingerprint's p10..p90 (always False
    comparing two fingerprints, where `value` is the other's center)."""
    name: str
    group: str
    value: float
    center: float
    scale: float
    z: float
    typical: bool


@dataclass(frozen=True)
class Comparison:
    """`distance`: the cosine distance (0 the same profile, 1 unrelated, 2
    opposite) between the two profiles, each measure standardized by the
    population (Cosine Delta; `_cosine_distance`); `groups`: the mean |z| of
    each group's measures, to say where a difference lies; `measures`:
    every measure's."""
    distance: float
    groups: dict[str, float]
    measures: tuple[MeasureDistance, ...]

    def furthest(self, n: int = 10) -> list[MeasureDistance]:
        """The `n` measures furthest from the fingerprint."""
        return sorted(self.measures, key=lambda m: (-abs(m.z), m.name))[:n]


def _cap(z: float) -> float:
    return max(-Z_CAP, min(Z_CAP, z))


@lru_cache(maxsize=1)
def _weights() -> tuple[float, ...]:
    return tuple(1.0 if measure_group(n) == 'function_words' else OTHER_WEIGHT
                 for n in measure_names())


def _cosine_distance(a: Mapping[str, float], b: Mapping[str, float], base: Baseline) -> float:
    """Cosine Delta (Smith and Aldridge 2011): each measure as population z
    scores (capped at `Z_CAP`), then 1 minus the weighted cosine of the two
    profiles. It reads the shape of a profile (which habits run above or
    below the population, and together), so it holds up where Burrows' Delta,
    the mean |z| difference, lets noisy measures swamp it."""
    dot = na = nb = 0.0
    for name, w in zip(measure_names(), _weights()):
        za = _cap((a[name] - base.mean[name]) / base.sd[name])
        zb = _cap((b[name] - base.mean[name]) / base.sd[name])
        dot += w * za * zb
        na += w * za * za
        nb += w * zb * zb
    if not na or not nb:
        return 1.0
    return 1.0 - dot / math.sqrt(na * nb)


def _rows(center: Mapping[str, float], values: Mapping[str, float], base: Baseline,
          ranges: Mapping[str, Stat] | None) -> Comparison:
    rows = []
    for name in measure_names():
        c, x, scale = center[name], values[name], base.sd[name]
        typical = bool(ranges) and ranges[name].p10 <= x <= ranges[name].p90
        rows.append(MeasureDistance(name, measure_group(name), x, c, scale,
                                    _cap((x - c) / scale), typical))
    by_group: dict[str, list[float]] = {g: [] for g in GROUPS}
    for r in rows:
        by_group[r.group].append(abs(r.z))
    groups = {g: statistics.fmean(v) for g, v in by_group.items() if v}
    return Comparison(_cosine_distance(center, values, base), groups, tuple(rows))


def _centers(fp: Fingerprint) -> dict[str, float]:
    return {n: s.center for n, s in fp.stats.items()}


def compare_values(fp: Fingerprint, values: Mapping[str, float],
                   baseline: Baseline | None = None) -> Comparison:
    """Measure values (`measure`) against a fingerprint."""
    return _rows(_centers(fp), values, baseline or load_baseline(), fp.stats)


def compare(fp: Fingerprint, other: Fingerprint | str,
            baseline: Baseline | None = None) -> Comparison:
    """`other` (a fingerprint, or a text) against `fp`, on the baseline's
    scale. A text is measured whole against the fingerprint's chunk
    centers; two fingerprints compare their chunk centers (symmetric in
    `distance`). Raises VoiceprintError for a text with no prose, or when
    the baseline can't be read."""
    base = baseline or load_baseline()
    if isinstance(other, Fingerprint):
        return _rows(_centers(fp), _centers(other), base, None)
    paras = _parse(paragraphs(other))
    if not paras:
        raise VoiceprintError('the text has no prose to measure')
    return _rows(_centers(fp), _measures(paras), base, fp.stats)


@dataclass(frozen=True)
class VoiceMatch:
    same: bool
    comparison: Comparison


def same_voice(a: Fingerprint, b: Fingerprint,
               baseline: Baseline | None = None) -> VoiceMatch:
    """Whether two fingerprints share a voice: their distance is at most
    `SAME_VOICE_MAX`."""
    c = compare(a, b, baseline)
    return VoiceMatch(c.distance <= SAME_VOICE_MAX, c)


@dataclass(frozen=True)
class Consistency:
    """A corpus's pieces measured against each other. `distances`: each
    piece's distance from the corpus's typical piece (every measure's median
    over the pieces), in the order given; `outliers`: the pieces in another
    voice, furthest first, or () when the corpus holds one voice;
    `separation`: how far the outlying group's typical piece sits from the
    rest's (0.0 when there was no group to test)."""
    distances: dict[str, float]
    outliers: tuple[str, ...]
    separation: float

    @property
    def consistent(self) -> bool:
        return not self.outliers


#: a piece shorter than this is too noisy to judge
MIN_PIECE_WORDS = 1000
#: consistency needs at least this many pieces to find a typical one
MIN_PIECES = 5


def _median_profile(values: Sequence[Mapping[str, float]]) -> dict[str, float]:
    return {m: statistics.median(v[m] for v in values) for m in measure_names()}


def _minority(values: Sequence[Mapping[str, float]], base: Baseline) -> tuple[set[int], float]:
    """Two groups by their profiles (2-medoids-like, deterministic): the
    piece furthest from the typical piece starts the second group, then each
    piece joins the group whose median profile it is nearer, until nothing
    moves. The second group stays a minority (a move that would make it the
    majority stops the search). Returns its indexes and the distance between
    the two groups' median profiles."""
    center = _median_profile(values)
    first = max(range(len(values)), key=lambda i: (_cosine_distance(center, values[i], base), -i))
    group = {first}
    for _ in range(20):
        rest = _median_profile([v for i, v in enumerate(values) if i not in group])
        mine = _median_profile([values[i] for i in sorted(group)])
        moved = {i for i, v in enumerate(values)
                 if _cosine_distance(mine, v, base) < _cosine_distance(rest, v, base)}
        if not moved or moved == group or len(moved) * 2 > len(values):
            break
        group = moved
    rest = _median_profile([v for i, v in enumerate(values) if i not in group])
    mine = _median_profile([values[i] for i in sorted(group)])
    return group, _cosine_distance(rest, mine, base)


def consistency(pieces: Mapping[str, str] | Sequence[str],
                baseline: Baseline | None = None) -> Consistency:
    """Whether a corpus's pieces share one voice. The pieces are split into
    the main group and a minority (`_minority`); when the two groups' typical
    pieces are further apart than `OUTLIER_SEPARATION`, the minority is the
    outlying pieces, named. A minority in another voice can't hide by
    pulling the average its way: each group is read by its median. Pieces
    should be about a chunk long (`CHUNK_WORDS`; `chunks` cuts a long text).
    Raises VoiceprintError for fewer than `MIN_PIECES` pieces or a piece
    under `MIN_PIECE_WORDS` words (named)."""
    base = baseline or load_baseline()
    items = _as_pieces(pieces)
    if len(items) < MIN_PIECES:
        raise VoiceprintError(f'consistency needs at least {MIN_PIECES} pieces, '
                              f'not {len(items)}')
    parsed = [(name, _parse(paragraphs(t))) for name, t in items]
    short = [name for name, ps in parsed if sum(p.n_words for p in ps) < MIN_PIECE_WORDS]
    if short:
        raise VoiceprintError(f'pieces under {MIN_PIECE_WORDS} words can\'t be judged: '
                              f'{", ".join(short[:10])}')
    names = [name for name, _ in parsed]
    values = [_measures(ps) for _, ps in parsed]
    center = _median_profile(values)
    distances = {n: _cosine_distance(center, v, base) for n, v in zip(names, values)}
    group, separation = _minority(values, base)
    out: tuple[str, ...] = ()
    if separation > OUTLIER_SEPARATION:
        out = tuple(sorted((names[i] for i in group), key=lambda n: (-distances[n], n)))
    return Consistency(distances, out, separation)

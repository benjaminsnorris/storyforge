"""The voice meter (plan B6, #653): prose against an author's fingerprint.

Free and deterministic: no model calls. `storyforge score --voice` prints
it. It reports **drift**, how far prose sits from the fingerprint and where.
It can't tell good prose from bad, and it is never an optimisation target
for an automatic rewrite loop: a loop that rewrites until this number falls
learns to game a few function words, not to write in the voice.

What it reports, for the prose in scope pooled (a book's scenes, or any
files):

- **the distance** (`voiceprint.compare`, Cosine Delta on the chunk scale),
  read against `CLOSE_LIMITS`: the furthest the reference author's own
  held-out writing reached at that length, and the nearest other writers
  came. Shorter prose is noisier, so the limit loosens as the words fall,
  and under 2,000 words another writer can come as near as the author's own
  prose: there the reading is `unclear`, not `close`. The limits were
  measured on Austen (`Source.calibrated` says whether the fingerprint is
  hers); for another writer they are a scale, not a verdict. Under
  `voiceprint.MIN_COMPARE_WORDS` the prose is too short to measure, and the
  meter says so (`TooShort`);
- **each measure's distance** (signed z in population standard deviations,
  and whether the prose sits inside the writer's p10..p90), each group's
  mean |z|;
- **each piece's distance**, for the pieces long enough to measure alone
  (the rest are named: they count only in the pool);
- **the sentences furthest from the corpus** (`sentence_surprise`): how
  improbable each sentence's length and its counts of the punctuation and
  word kinds in `SENTENCE_RATES` are under the writer's own rates (Poisson
  upper tails, a floor for what the writer never does);
- **constructions the prose uses far more than the reference**
  (`constructions`): two- to four-word phrases built mostly of function
  words (so a construction, not a topic: "he didn't", "the edge of the",
  not "the lantern"), used `CONSTRUCTION_MIN_COUNT`+ times in the prose at
  `CONSTRUCTION_MIN_RATIO`x the reference's rate or more. With the corpus at
  hand (`load_source(voice_repo=...)`) its own rates are the reference; with
  only a fingerprint, the general baseline's (2- and 3-word phrases only),
  leaving out the writer's own favoured phrases, and the report says which.
  Under 10,000 words of prose only all-closed-class phrases can qualify
  (see `TOPIC_RATE`).

API: `load_source(fingerprint_path=, voice_repo=)` -> `Source`;
`meter(source, pieces, top=)` -> `Report` (raises `TooShort` or
`MeterError`); `report_lines(report)`; `close_limit(words)`,
`reading(distance, words)`; `sentence_surprise(fp, sentence)`;
`constructions(source, pieces, keep=)`.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from functools import cached_property
from itertools import zip_longest
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping

from storyforge import voiceprint as vp

#: for prose of at least `least` words: `limit`, how far it can sit from the
#: fingerprint and still read as the writer (the furthest held-out sample
#: of Austen, *Emma* and *Persuasion* in contiguous runs of whole
#: paragraphs, measured against her *Pride and Prejudice* fingerprint,
#: rounded up), and `nearest_other`, the nearest the seven other authors'
#: samples of that length came (rounded down; None when none came inside
#: the limit). Measured 2026-11-09 (`tests/test_voiceprint_meter.py` holds
#: every step): Austen's furthest at 1,000 words 0.78, 1,500 0.73, 2,000
#: 0.63, 5,000 0.51, 10,000 0.44, 20,000 0.32, the whole novels 0.21 and
#: 0.23; the others' nearest at 1,000 words 0.59, 1,500 0.64, 2,000 0.64,
#: 5,000 0.61, 10,000 0.59, 20,000 0.56. So from 5,000 words the two never
#: meet, but under 2,000 the others' nearest sit inside Austen's own spread
#: (16 of 131 samples of 1,000 words): a distance between `nearest_other`
#: and `limit` is `unclear`, not `close`. Calibrated on one writer: for
#: another, read it as a scale, not a verdict (`Source.calibrated`)
CLOSE_LIMITS = ((40000, vp.SAME_VOICE_MAX, None), (20000, 0.33, None), (10000, 0.45, None),
                (5000, 0.52, None), (2000, 0.65, 0.63), (vp.MIN_COMPARE_WORDS, 0.80, 0.59))

#: the readings of a distance (`reading`): within the limit and nearer than
#: any other writer came; within the limit, but where another writer came
#: too; beyond the limit
CLOSE, UNCLEAR, FAR = 'close', 'unclear', 'far'

#: the voice `CLOSE_LIMITS` was measured on
REFERENCE_VOICE = os.path.join('references', 'voiceprints', 'austen')

#: the measures counted per sentence (each a rate per 1000 words in the
#: fingerprint), with how one is named
SENTENCE_RATES = {
    'comma_rate': 'comma', 'semicolon_rate': 'semicolon', 'colon_rate': 'colon',
    'dash_rate': 'dash', 'parenthesis_rate': 'parenthesis',
    'question_rate': 'question mark', 'exclamation_rate': 'exclamation mark',
    'ellipsis_rate': 'ellipsis', 'contraction_rate': 'contraction',
    'latinate_rate': 'Latinate word', 'adverb_rate': '-ly adverb',
    'adjective_rate': 'adjective',
}
#: per 1000 words: the least rate a sentence is judged against, so what the
#: writer never does is improbable, not impossible (about one in 10,000 words)
RATE_FLOOR = 0.1
#: the most one feature adds to a sentence's surprise (one unheard-of mark
#: can't outweigh everything else)
SURPRISE_CAP = 8.0
#: the least share a sentence-length bucket is judged at
LENGTH_SHARE_FLOOR = 0.001
#: of the sentences listed, at most this many led by the same reason
SAME_REASON_MAX = 2

#: a construction's sizes, in words
CONSTRUCTION_SIZES = (2, 3, 4)
#: a phrase counts only when the prose uses it this often
CONSTRUCTION_MIN_COUNT = 5
#: ... and this many times more often than the reference does (rates per
#: million phrases, `voiceprint.NGRAM_SMOOTHING` added to both sides)
CONSTRUCTION_MIN_RATIO = 8.0
#: how many constructions are listed
CONSTRUCTION_KEEP = 12
#: a content word used this often per 1000 words of the prose is what the
#: prose is about (a topic: "lantern", "harbour"), so its phrases are left out.
#: A phrase needs `CONSTRUCTION_MIN_COUNT` uses, so its open word has at
#: least 5, which is 0.5 per 1,000 whenever the prose is under 10,000 words:
#: there every open word in a construction is a topic, and only phrases
#: built wholly of closed-class words can qualify
TOPIC_RATE = 0.5
#: closed-class words outside `voiceprint.FUNCTION_WORDS` that a
#: construction may be built of (contractions count too)
CLOSED_EXTRA = frozenset("""
    about above across after again against along among around away
    because before behind below beneath beside between beyond both can
    cannot did does doing done down each either even ever every few here how
    into just like many may near neither never nor nothing off once onto
    only out over own same something anything everything still then these
    those though through too toward towards under until up upon why within
    without yet where while who whom whose
""".split())

#: shown on every report (the `--voice` help says the same): what the
#: number is for
DRIFT_NOTE = ('This reports drift from the fingerprint. It can\'t tell good prose from bad, '
              'and it is never a target for an automatic rewrite loop.')


class MeterError(Exception):
    """The meter can't read against its source: the fingerprint, the corpus
    or the baseline can't be read, or the corpus isn't what was
    fingerprinted. The message says why. Fatal for any prose."""


class TooShort(Exception):
    """The prose in scope is under `voiceprint.MIN_COMPARE_WORDS` words:
    expected for one short scene, so not a `MeterError` (a caller metering
    scene by scene can go on). `words`: the prose counted; `empty`: the
    pieces with no prose."""

    def __init__(self, words: int, empty: tuple[str, ...] = ()):
        self.words = words
        self.empty = tuple(empty)
        super().__init__(f'too short to measure: {words:,} words of prose; the meter needs at '
                         f'least {vp.MIN_COMPARE_WORDS:,}')


# ============================================================================
# The fingerprint to measure against
# ============================================================================

@dataclass(frozen=True)
class Source:
    """What prose is measured against: the fingerprint, the fingerprinted
    corpus by piece name when it's at hand (read-only; None with only a
    fingerprint.json), a label saying where it came from, and whether it is
    the voice `CLOSE_LIMITS` was measured on (`calibrated`; otherwise the
    limits are a scale for this writer, not a verdict)."""
    fingerprint: vp.Fingerprint
    corpus: Mapping[str, str] | None
    label: str
    calibrated: bool = False

    @cached_property
    def corpus_counts(self) -> tuple[frozenset[str], dict[int, Counter]] | None:
        """The corpus's names and its phrase counts by size, names left out
        (`CONSTRUCTION_SIZES`), parsed once per source; None without the
        corpus."""
        if not self.corpus:
            return None
        text = '\n\n'.join(self.corpus.values())
        names = vp.proper_words(text)
        return names, {n: vp.ngram_counts(text, n, names) for n in CONSTRUCTION_SIZES}


def _is_reference(path: str) -> bool:
    from storyforge.common import get_plugin_dir
    reference = os.path.join(get_plugin_dir(), REFERENCE_VOICE)
    return os.path.realpath(path) == os.path.realpath(reference)


def _check_corpus(fp: vp.Fingerprint, texts: Mapping[str, str], fp_label: str) -> None:
    """Raise MeterError unless each corpus piece holds the words the
    fingerprint recorded for it: an emptied, cut or swapped file would
    otherwise be the reference for the constructions without a word."""
    for piece in fp.pieces:
        name, recorded = piece.get('name', ''), piece.get('words')
        if name not in texts or not isinstance(recorded, int):
            continue
        now = _prose_words(texts[name])
        if now != recorded:
            raise MeterError(f'{name} has {now:,} words of prose; {fp_label} was made from '
                             f'{recorded:,}. The corpus changed since it was fingerprinted: '
                             f'compute the fingerprint again')


def load_source(fingerprint_path: str | None = None,
                voice_repo: str | None = None) -> Source:
    """The fingerprint from exactly one of a `fingerprint.json` path or an
    author voice repo (`voiceprint_proposals.load_voice`: its fingerprint
    and the corpus pieces it names, so constructions are measured against
    the corpus itself). Raises MeterError naming what's wrong. A book's
    `voice.author` is a third way in: `score --voice` resolves it to a voice
    repo (`voice_repo.voice_ref`) and passes that."""
    if bool(fingerprint_path) == bool(voice_repo):
        raise MeterError('give the fingerprint one way: a fingerprint.json path or an author '
                         'voice repo')
    if voice_repo:
        from storyforge import voiceprint_proposals as vpp
        path = os.path.abspath(voice_repo)
        try:
            voice = vpp.load_voice(path)
        except vpp.ProposalError as e:
            raise MeterError(str(e)) from e
        _check_corpus(voice.fingerprint, voice.texts, f'{path}/{vpp.FINGERPRINT_FILE}')
        who = f'{voice.author}\'s voice repo' if voice.author else 'the voice repo'
        return Source(voice.fingerprint, MappingProxyType(dict(voice.texts)), f'{who} ({path})',
                      _is_reference(path))
    path = os.path.abspath(fingerprint_path)
    try:
        fp = vp.Fingerprint.load(path)
    except vp.VoiceprintError as e:
        raise MeterError(str(e)) from e
    return Source(fp, None, path, _is_reference(os.path.dirname(path)))


def _step(words: int) -> tuple[int, float, float | None] | None:
    return next((step for step in CLOSE_LIMITS if words >= step[0]), None)


def close_limit(words: int) -> float | None:
    """The `CLOSE_LIMITS` distance for prose of `words` words, or None
    under `voiceprint.MIN_COMPARE_WORDS` (too short to measure)."""
    step = _step(words)
    return step[1] if step else None


def reading(distance: float, words: int) -> str:
    """`CLOSE`, `UNCLEAR` or `FAR` for prose of `words` words at `distance`
    (`CLOSE_LIMITS`). Raises ValueError under `voiceprint.MIN_COMPARE_WORDS`."""
    step = _step(words)
    if step is None:
        raise ValueError(f'{words} words is too short to read')
    _, limit, nearest_other = step
    if distance > limit:
        return FAR
    return UNCLEAR if nearest_other is not None and distance >= nearest_other else CLOSE


# ============================================================================
# Sentences
# ============================================================================

def _poisson_surprise(k: int, lam: float) -> float:
    """-ln P(X >= k) for X ~ Poisson(lam), capped at `SURPRISE_CAP`; 0 when
    `k` isn't above `lam` (using a thing as often as expected, or less, is
    no surprise)."""
    if k <= lam:
        return 0.0
    log_term = -lam + k * math.log(lam) - math.lgamma(k + 1)
    total, i, term = 0.0, k, math.exp(log_term)
    while term > 1e-300 and i < k + 200:
        total += term
        i += 1
        term *= lam / i
        if term < total * 1e-12:
            break
    if total <= 0.0:
        return SURPRISE_CAP
    return min(SURPRISE_CAP, -math.log(total))


@dataclass(frozen=True)
class Reason:
    """One part of a sentence's surprise: `kind`, what it is about
    ('length', or a `SENTENCE_RATES` measure such as 'colon_rate'); its
    surprise; the sentence's count (of words, for 'length'); the writer's
    rate per 1,000 words (for 'length', the share of the writer's sentences
    in that length's bucket); and `text`, how it is shown."""
    kind: str
    surprise: float
    count: int
    writer_rate: float
    text: str


@dataclass(frozen=True)
class Sentence:
    """One sentence of the prose: the piece it's in, its text as written,
    its surprise under the writer's habits, and the reasons (largest
    first)."""
    piece: str
    text: str
    surprise: float
    reasons: tuple[Reason, ...]


def _rate(fp: vp.Fingerprint, name: str) -> float:
    st = fp.stats[name]
    return max(st.value, st.center, RATE_FLOOR)


def sentence_surprise(fp: vp.Fingerprint, sentence: str) -> tuple[float, list[Reason]]:
    """How improbable `sentence` is under the writer's habits: its length's
    rarity in `Fingerprint.sentence_lengths` (0 for the commonest bucket),
    plus, for each of `SENTENCE_RATES`, the Poisson surprise of its count
    against the writer's rate (the corpus's or its chunks' median, the
    larger, floored at `RATE_FLOOR` per 1000 words) times its length. Returns
    the total and its parts (largest first). Raises VoiceprintError for a
    sentence with no prose (`voiceprint.measure`)."""
    values = vp.measure(sentence)
    n = len(vp.words(sentence))
    parts: list[Reason] = []
    if fp.sentence_lengths:
        bucket = vp.length_bucket(n)
        share = fp.sentence_lengths.get(bucket, 0.0)
        top = max(fp.sentence_lengths.values())
        s = math.log(top / max(share, LENGTH_SHARE_FLOOR)) if top > 0 else 0.0
        if s > 0:
            parts.append(Reason('length', s, n, share,
                                f'{n} word{"" if n == 1 else "s"} (the writer: {share:.0%} of '
                                f'sentences are {bucket} words)'))
    for name, label in SENTENCE_RATES.items():
        k = round(values[name] * n / 1000)
        rate = _rate(fp, name)
        s = _poisson_surprise(k, rate * n / 1000)
        if s > 0:
            parts.append(Reason(name, s, k, rate,
                                f'{label} x{k} (the writer: {rate:.2g} per 1,000 words)'))
    parts.sort(key=lambda p: -p.surprise)
    return sum(p.surprise for p in parts), parts


def _sentences(fp: vp.Fingerprint, pieces: Mapping[str, str],
               top: int) -> tuple[list[Sentence], int]:
    """The `top` sentences furthest from the writer, and how many sentences
    couldn't be measured alone."""
    scored, unmeasured = [], 0
    for name, text in pieces.items():
        for para in vp.paragraphs(text):
            for sent in vp.split_sentences(para):
                try:
                    total, parts = sentence_surprise(fp, sent)
                except vp.VoiceprintError:
                    unmeasured += 1
                    continue
                if total > 0:
                    scored.append(Sentence(name, sent, total, tuple(parts[:3])))
    scored.sort(key=lambda s: -s.surprise)   # stable: ties keep the prose's order
    # no more than `SAME_REASON_MAX` led by the same kind of thing, so one
    # habit (say, contractions) doesn't fill the list
    picked, led = [], Counter()
    for s in scored:
        lead = s.reasons[0].kind
        if led[lead] >= SAME_REASON_MAX:
            continue
        led[lead] += 1
        picked.append(s)
        if len(picked) >= top:
            break
    return picked, unmeasured


# ============================================================================
# Constructions
# ============================================================================

@dataclass(frozen=True)
class Construction:
    """A phrase the prose uses far more than the reference: how often in
    the prose, in the corpus (None measured against the baseline), the ratio
    of their rates, and the first sentence using it ('' when every use spans
    punctuation the sentence search can't cross, which the report says)."""
    phrase: str
    count: int
    corpus_count: int | None
    ratio: float
    piece: str
    example: str


_CLOSED = frozenset(vp.FUNCTION_WORDS) | CLOSED_EXTRA


def _closed(word: str) -> bool:
    return word in _CLOSED or vp.is_contraction(word)


def _construction_shape(phrase: str, topical: set[str]) -> bool:
    """Built mostly of closed-class words: none open in a two-word phrase,
    at most one in a longer one, and never a topic word."""
    open_words = [w for w in phrase.split() if not _closed(w)]
    allowed = 0 if len(phrase.split()) == 2 else 1
    return len(open_words) <= allowed and not any(w in topical for w in open_words)


def _word_pattern(word: str) -> str:
    return '[\'\u2019]'.join(re.escape(part) for part in word.split("'"))


def _example(pieces: Mapping[str, str], phrase: str) -> tuple[str, str]:
    # the phrase list counts across commas and dashes, so the words may be
    # parted by any run of non-word characters
    pattern = re.compile(r'(?<![\w\'\u2019-])'
                         + r'[\W_]+'.join(_word_pattern(w) for w in phrase.split())
                         + r'(?![\w\'\u2019-])', re.IGNORECASE)
    for name, text in pieces.items():
        for para in vp.paragraphs(text):
            for sent in vp.split_sentences(para):
                if pattern.search(sent):
                    return name, sent
    return '', ''


def _overlaps(a: str, b: str) -> bool:
    """One phrase inside the other, or the two the same phrase shifted by
    a word ("in the middle of", "the middle of the")."""
    if f' {a} ' in f' {b} ' or f' {b} ' in f' {a} ':
        return True
    wa, wb = a.split(), b.split()
    k = min(len(wa), len(wb)) - 1
    return k >= 2 and (wa[-k:] == wb[:k] or wb[-k:] == wa[:k])


#: what constructions were measured against (`constructions`)
Basis = Literal['corpus', 'baseline']


def constructions(source: Source, pieces: Mapping[str, str],
                  keep: int = CONSTRUCTION_KEEP) -> tuple[list[Construction], Basis]:
    """The phrases the prose uses far more than the reference (see the
    module doc): the sizes in turn, each size's most telling first (ratio
    times the square root of the count), none overlapping another listed
    (`_overlaps`). Returns them and the reference: 'corpus' (every size in
    `CONSTRUCTION_SIZES`) or 'baseline' (only `voiceprint.NGRAM_SIZES`, the
    writer's own phrases in `Fingerprint.ngrams` left out). Names, in the
    prose or the corpus, are left out of both sides."""
    fp = source.fingerprint
    counted = source.corpus_counts
    pooled = '\n\n'.join(pieces.values())
    names = vp.proper_words(pooled)
    unigrams = vp.ngram_counts(pooled, 1, frozenset())
    n_words = sum(unigrams.values()) or 1
    topical = {w for w, c in unigrams.items()
               if not _closed(w) and 1000 * c / n_words >= TOPIC_RATE}
    if counted:
        corpus_names, ref_counts = counted
        names = names | corpus_names
    baseline = None if counted else vp.load_baseline()
    own = {g for grams in fp.ngrams.values() for g, *_ in grams}
    sizes = CONSTRUCTION_SIZES if counted else tuple(n for n in CONSTRUCTION_SIZES
                                                     if n in vp.NGRAM_SIZES)
    found = []
    for n in sizes:
        counts = vp.ngram_counts(pooled, n, names)
        total = sum(counts.values()) or 1
        if counted:
            ref = ref_counts[n]
            ref_total = sum(ref.values()) or 1
        for gram, c in counts.items():
            if c < CONSTRUCTION_MIN_COUNT or not _construction_shape(gram, topical):
                continue
            rate = 1e6 * c / total
            if counted:
                ref_count = ref.get(gram, 0)
                ref_rate = 1e6 * ref_count / ref_total
            else:
                if gram in own:
                    continue
                ref_count = None
                ref_rate = baseline.ngrams[n].get(gram, baseline.ngram_floor[n])
            ratio = (rate + vp.NGRAM_SMOOTHING) / (ref_rate + vp.NGRAM_SMOOTHING)
            if ratio >= CONSTRUCTION_MIN_RATIO:
                found.append((ratio * math.sqrt(c), gram, c, ref_count, ratio))
    # the sizes in turn, each its most telling first, so the frequent pairs
    # don't crowd out the longer phrases
    by_size = [sorted((f for f in found if len(f[1].split()) == n), key=lambda x: (-x[0], x[1]))
               for n in sizes]
    ranked = [f for row in zip_longest(*by_size) for f in row if f is not None]
    out: list[Construction] = []
    for _, gram, c, ref_count, ratio in ranked:
        if any(_overlaps(gram, k.phrase) for k in out):
            continue
        piece, example = _example(pieces, gram)
        out.append(Construction(gram, c, ref_count, ratio, piece, example))
        if len(out) >= keep:
            break
    return out, ('corpus' if counted else 'baseline')


# ============================================================================
# The meter
# ============================================================================

@dataclass(frozen=True)
class PieceDistance:
    """One piece measured alone: its words, distance, `CLOSE_LIMITS` limit
    and `reading` (`CLOSE`, `UNCLEAR` or `FAR`)."""
    name: str
    words: int
    distance: float
    limit: float
    reading: str

    @property
    def close(self) -> bool:
        return self.reading == CLOSE


@dataclass(frozen=True)
class Report:
    """The meter's reading (`meter`). `reading` is `CLOSE`, `UNCLEAR` or
    `FAR` against `limit`; when `source.calibrated` is False the limits were
    measured on another writer, so it is a scale, not a verdict. `short`
    names the pieces under `voiceprint.MIN_COMPARE_WORDS` (in the pool, not
    measured alone) and `empty` those with no prose. `top`: how many
    measures, pieces and sentences are listed. `warnings` are printed as
    they are."""
    source: Source
    words: int
    comparison: vp.Comparison
    limit: float
    reading: str
    pieces: tuple[PieceDistance, ...]
    short: tuple[str, ...]
    empty: tuple[str, ...]
    sentences: tuple[Sentence, ...]
    unmeasured_sentences: int
    constructions: tuple[Construction, ...]
    construction_basis: Basis
    top: int = 10
    warnings: tuple[str, ...] = field(default=())

    @property
    def distance(self) -> float:
        return self.comparison.distance

    @property
    def close(self) -> bool:
        return self.reading == CLOSE


def _prose_words(text: str) -> int:
    return sum(len(vp.words(p)) for p in vp.paragraphs(text))


def meter(source: Source, pieces: Mapping[str, str], top: int = 10) -> Report:
    """Measure `pieces` (name -> prose, in order; a book's scenes or any
    files) against `source`'s fingerprint, listing `top` measures, pieces
    and sentences. Raises TooShort when they hold under
    `voiceprint.MIN_COMPARE_WORDS` words of prose together, and MeterError
    when the baseline can't be read."""
    fp = source.fingerprint
    words_by_piece = {name: _prose_words(text) for name, text in pieces.items()}
    empty = tuple(name for name, n in words_by_piece.items() if not n)
    prose = {name: text for name, text in pieces.items() if words_by_piece[name]}
    total = sum(words_by_piece.values())
    if total < vp.MIN_COMPARE_WORDS:
        raise TooShort(total, empty)
    try:
        comparison = vp.compare(fp, '\n\n'.join(prose.values()))
        measured = []
        for name, text in prose.items():
            if words_by_piece[name] >= vp.MIN_COMPARE_WORDS:
                n = words_by_piece[name]
                d = vp.compare(fp, text).distance
                measured.append(PieceDistance(name, n, d, close_limit(n), reading(d, n)))
        found, basis = constructions(source, prose)
    except vp.VoiceprintError as e:
        # the word counts above are `compare`'s, so this is the baseline
        raise MeterError(str(e)) from e
    short = tuple(name for name in prose if words_by_piece[name] < vp.MIN_COMPARE_WORDS)
    measured.sort(key=lambda p: (-p.distance, p.name))
    sentences, unmeasured = _sentences(fp, prose, top)
    warnings = []
    if fp.below_minimum_corpus:
        warnings.append(f'WARNING: the fingerprint was made from {fp.words:,} words, under the '
                        f'{vp.MIN_CORPUS_WORDS:,} a stable one needs; its distances move with '
                        f'the corpus')
    if not fp.sentence_lengths:
        warnings.append('WARNING: the fingerprint holds no sentence-length distribution, so '
                        'sentence length isn\'t judged in the sentences below')
    if unmeasured:
        warnings.append(f'WARNING: {unmeasured} sentence(s) couldn\'t be measured alone '
                        f'(capitals or heading-like), and aren\'t ranked')
    if basis == 'baseline' and not fp.ngrams:
        warnings.append('WARNING: the fingerprint holds no phrase list, so the writer\'s own '
                        'favoured phrases can\'t be left out of the constructions; some listed '
                        'may be the writer\'s habits (--voice-repo measures against the corpus)')
    return Report(source, total, comparison, close_limit(total),
                  reading(comparison.distance, total), tuple(measured), short, empty,
                  tuple(sentences), unmeasured, tuple(found), basis, top, tuple(warnings))


# ============================================================================
# The report
# ============================================================================

def _quote(text: str, width: int = 220) -> str:
    text = ' '.join(text.split())
    return text if len(text) <= width else text[:width - 3].rstrip() + '...'


def _names(names: tuple[str, ...], most: int = 10) -> str:
    shown = ', '.join(names[:most])
    return shown + (f' (and {len(names) - most} more)' if len(names) > most else '')


#: how the constructions' reference is shown, by `Report.construction_basis`
_BASIS_TEXT = {
    'corpus': 'the corpus itself',
    'baseline': ('the general baseline, 2- and 3-word phrases only (it holds no 4-word '
                 'rates), leaving out the writer\'s own favoured phrases (the corpus isn\'t '
                 'at hand with a fingerprint alone; --voice-repo reads it)'),
}


def _distance_line(report: Report) -> str:
    step = _step(report.words)
    nearest_other = step[2] if step else None
    said = {
        CLOSE: 'close',
        UNCLEAR: (f'unclear: inside the limit, but at this length another writer\'s prose '
                  f'came as near ({nearest_other:.2f}), so the meter can\'t tell them apart'),
        FAR: 'far',
    }[report.reading]
    scale = ('' if report.source.calibrated else
             ' This fingerprint isn\'t that reference, so read the limit as a scale for this '
             'writer, not a verdict.')
    return (f'Distance: {report.distance:.3f}, {said}. Austen\'s own held-out prose of this '
            f'length stays within {report.limit:.2f} (`CLOSE_LIMITS`, measured on the Austen '
            f'reference voiceprint; 0 is the same profile, and the other writers measured sit '
            f'beyond the limit from 2,000 words).{scale}')


def report_lines(report: Report) -> list[str]:
    """The report as printed by `score --voice` (`report.top` of each
    list)."""
    fp = report.source.fingerprint
    top = report.top
    lines = [
        f'# Voice drift against {report.source.label}',
        '',
        DRIFT_NOTE,
        '',
        f'Fingerprint: {fp.words:,} words of corpus. Measured: {report.words:,} words of prose'
        f' in {len(report.pieces) + len(report.short)} piece(s).',
        _distance_line(report),
        '',
        '## By group (mean |z|, in population standard deviations)',
        '',
    ]
    for group, z in sorted(report.comparison.groups.items(), key=lambda kv: -kv[1]):
        lines.append(f'  {group:<16} {z:.2f}')
    lines += ['', f'## The {top} measures furthest from the fingerprint', '',
              f'  {"measure":<30} {"prose":>9} {"writer":>9} {"writer p10-p90":>19} {"z":>6}']
    for m in report.comparison.furthest(top):
        st = fp.stats[m.name]
        flag = '' if m.typical else '  outside'
        lines.append(f'  {m.name:<30} {m.value:>9.3g} {m.center:>9.3g} '
                     f'{f"{st.p10:.3g}-{st.p90:.3g}":>19} {m.z:>+6.2f}{flag}')
    lines += ['', '## Pieces furthest from the fingerprint (each measured alone)', '']
    if report.pieces:
        far = sum(1 for p in report.pieces if p.reading == FAR)
        unclear = sum(1 for p in report.pieces if p.reading == UNCLEAR)
        lines.append(f'{far} of {len(report.pieces)} measured alone are beyond the limit for '
                     f'their length' + (f'; {unclear} unclear (inside it, where another '
                                        f'writer came as near).' if unclear else '.'))
        for p in report.pieces[:top]:
            lines.append(f'  {p.name}: {p.distance:.3f} ({p.words:,} words; limit '
                         f'{p.limit:.2f}, {p.reading})')
    else:
        lines.append('None is long enough to measure alone.')
    if report.short:
        lines.append(f'Too short to measure alone (under {vp.MIN_COMPARE_WORDS:,} words), so '
                     f'counted only in the pool: {_names(report.short)}.')
    if report.empty:
        lines.append(f'No prose to measure: {_names(report.empty)}.')
    lines += ['', '## Sentences furthest from the corpus', '']
    if report.sentences:
        for i, s in enumerate(report.sentences, 1):
            lines.append(f'{i}. [{s.piece}] "{_quote(s.text)}"')
            lines.append(f'   {"; ".join(r.text for r in s.reasons)}')
    else:
        lines.append('None stands out.')
    lines += ['', '## Constructions the prose uses far more than the reference', '',
              f'Measured against {_BASIS_TEXT[report.construction_basis]}.', '']
    if report.constructions:
        for c in report.constructions:
            where = (f'the corpus: {c.corpus_count}; {c.ratio:.0f}x its rate'
                     if c.corpus_count is not None else f'{c.ratio:.0f}x the baseline\'s rate')
            lines.append(f'  "{c.phrase}": {c.count} times ({where})')
            if c.example:
                lines.append(f'     e.g. [{c.piece}] "{_quote(c.example, 160)}"')
            else:
                lines.append('     (no example: no sentence holds it as written)')
    else:
        lines.append(f'None used {CONSTRUCTION_MIN_COUNT}+ times at {CONSTRUCTION_MIN_RATIO:.0f}x '
                     f'the reference\'s rate.')
    if report.warnings:
        lines.append('')
        lines += list(report.warnings)
    return lines

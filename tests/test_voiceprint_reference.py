"""The voiceprint's reference tests (plan B7 tests 1-3, #650).

Free and deterministic, on every commit. The Austen reference voiceprint
(`references/voiceprints/austen/`) is fingerprinted from *Pride and
Prejudice*; *Emma* and *Persuasion* are held out. The other authors are ten
2,000-word excerpts each from the evals' books
(`tests/fixtures/voiceprint/others/`), the Verne pair is two translations by
different translators (`tests/fixtures/voiceprint/verne/`).

Each floor sits below the measured result with a margin; the measured
numbers are in the comment beside it and in
`references/voiceprints/README.md`. A change to the fingerprint that lowers
a result below its floor fails here: the fingerprint would no longer find a
known voice as well as it did.
"""

import os
import statistics

import pytest

from storyforge import voiceprint as vp

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUSTEN = os.path.join(PLUGIN, 'references', 'voiceprints', 'austen')
FIX = os.path.join(PLUGIN, 'tests', 'fixtures', 'voiceprint')
OTHERS = ('age-of-innocence', 'brimming-cup', 'christmas-carol', 'gatsby',
          'middlemarch', 'plastic-age', 'self-control')

# Test 1, attribution (measured 2026-11-08)
#: held-out Austen chunks nearest Austen among the eight authors (1.000, 117/117)
ATTRIBUTION_FLOOR = 0.95
#: each other author's chunk, left out of its author's fingerprint, nearest
#: its own author (0.886, 62/70) ...
OTHERS_ATTRIBUTION_FLOOR = 0.8
#: ... or nearest Austen (1 of 70, a Middlemarch chunk)
OTHERS_TO_AUSTEN_MAX = 2
#: ranked by distance from Austen alone, held-out Austen chunks ahead of the
#: other authors' (AUC 1.000), and ahead of Brunton's, her contemporary (1.000)
RANKING_AUC_FLOOR = 0.97
BRUNTON_AUC_FLOOR = 0.95

# Test 3, mixed voices
#: of the 21 seeded corpora (16 Austen chunks + 4 of one other author's), the
#: share reported inconsistent (18/21) ...
SEEDED_FLAGGED_FLOOR = 0.75
#: ... the seeded chunks named among all seeded chunks (63/84 = 0.750) ...
SEEDED_RECALL_FLOOR = 0.6
#: ... and no Austen chunk named (0)
SEEDED_FALSE_MAX = 0


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _novel(slug):
    return _read(os.path.join(AUSTEN, 'corpus', f'{slug}.md'))


@pytest.fixture(scope='module')
def texts():
    out = {slug: _novel(slug) for slug in ('pride-and-prejudice', 'emma', 'persuasion')}
    for slug in ('around-the-world', 'five-weeks-in-a-balloon'):
        out[slug] = _read(os.path.join(FIX, 'verne', f'{slug}.md'))
    return out


@pytest.fixture(scope='module')
def chunk_values(texts):
    """Every source's chunks, measured once: {source: [measures, ...]}."""
    out = {slug: [vp.measure(c) for c in vp.chunks(t)] for slug, t in texts.items()}
    for author in OTHERS:
        d = os.path.join(FIX, 'others', author)
        out[author] = [vp.measure(_read(os.path.join(d, f))) for f in sorted(os.listdir(d))]
    return out


@pytest.fixture(scope='module')
def austen(texts):
    """The reference fingerprint, from Pride and Prejudice alone."""
    return vp.fingerprint({'pride-and-prejudice': texts['pride-and-prejudice']}, ngrams=False)


def _auc(near, far):
    return sum((a < b) + 0.5 * (a == b) for a in near for b in far) / (len(near) * len(far))


# ============================================================================
# The reference voiceprint itself
# ============================================================================

def test_reference_fingerprint_is_current():
    """fingerprint.json is what the code computes from the corpus it names:
    a change to a measure or the baseline must recompute it."""
    stored = _read(os.path.join(AUSTEN, 'fingerprint.json'))
    fp = vp.fingerprint({'corpus/pride-and-prejudice.md': _novel('pride-and-prejudice')})
    assert fp.to_json() == stored, (
        'references/voiceprints/austen/fingerprint.json is stale: recompute it with '
        'voiceprint.fingerprint({"corpus/pride-and-prejudice.md": text}).save(path)')


def test_reference_fingerprint_loads_and_names_her_phrases():
    fp = vp.Fingerprint.load(os.path.join(AUSTEN, 'fingerprint.json'))
    assert fp.words > 100_000 and fp.chunks >= 50
    bigrams = [g for g, _, _ in fp.ngrams['2']]
    # names are left out of the phrases: no Darcy, no Bennet
    assert not any(w in g.split() for g in bigrams for w in ('darcy', 'bennet', 'elizabeth'))
    assert fp.pieces[0]['first_sentence'].startswith('It is a truth universally acknowledged')


# ============================================================================
# Test 1: attribution
# ============================================================================

def test_attribution_held_out_austen_is_nearest_austen(chunk_values, austen):
    """Each 2,000-word chunk of Emma and Persuasion is nearest Austen's
    fingerprint (from Pride and Prejudice) among eight authors'; the others
    are fingerprinted from their ten chunks (20,000 words)."""
    candidates = {'austen': austen}
    candidates.update({a: vp.profile(chunk_values[a]) for a in OTHERS})
    held = chunk_values['emma'] + chunk_values['persuasion']
    wins, missed = 0, []
    for v in held:
        d = {a: vp.compare_values(fp, v).distance for a, fp in candidates.items()}
        best = min(d, key=d.get)
        wins += best == 'austen'
        if best != 'austen':
            missed.append(best)
    accuracy = wins / len(held)
    print(f'attribution: {wins}/{len(held)} = {accuracy:.3f}; missed to {missed}')
    assert len(held) > 100
    assert accuracy >= ATTRIBUTION_FLOOR, missed

    # the converse: each other author's chunk, left out of its author's
    # fingerprint, goes to its own author, and almost never to Austen
    right = to_austen = total = 0
    for a in OTHERS:
        for i, v in enumerate(chunk_values[a]):
            own = vp.profile(chunk_values[a][:i] + chunk_values[a][i + 1:])
            d = {k: vp.compare_values(own if k == a else fp, v).distance
                 for k, fp in candidates.items()}
            best = min(d, key=d.get)
            total += 1
            right += best == a
            to_austen += best == 'austen'
    print(f'others: {right}/{total} to their own author, {to_austen} to Austen')
    assert right / total >= OTHERS_ATTRIBUTION_FLOOR
    assert to_austen <= OTHERS_TO_AUSTEN_MAX


def test_attribution_ranking_against_austen_alone(chunk_values, austen):
    """Ranked by distance from Austen's fingerprint alone, the held-out
    chunks come ahead of every other author's, Brunton's (1811) included."""
    near = [vp.compare_values(austen, v).distance
            for v in chunk_values['emma'] + chunk_values['persuasion']]
    far = [vp.compare_values(austen, v).distance for a in OTHERS for v in chunk_values[a]]
    brunton = [vp.compare_values(austen, v).distance for v in chunk_values['self-control']]
    auc, auc_b = _auc(near, far), _auc(near, brunton)
    print(f'ranking AUC {auc:.3f}, against Brunton {auc_b:.3f}; median distance '
          f'Austen {statistics.median(near):.3f}, others {statistics.median(far):.3f}')
    assert auc >= RANKING_AUC_FLOOR
    assert auc_b >= BRUNTON_AUC_FLOOR


# ============================================================================
# Test 2: stability
# ============================================================================

def test_stability_halves_agree(chunk_values):
    """Pride and Prejudice's two halves give fingerprints that share a voice
    (0.168 apart, against SAME_VOICE_MAX)."""
    cs = chunk_values['pride-and-prejudice']
    half = len(cs) // 2
    m = vp.same_voice(vp.profile(cs[:half]), vp.profile(cs[half:]))
    print(f'halves: {m.comparison.distance:.3f}')
    assert m.same


def _sample_pairs(pool, words, windows=6):
    """Pairs of disjoint samples of `words` words: in each of `windows`
    windows spaced through the pool, the even chunks against the odd."""
    k = -(-words // vp.CHUNK_WORDS)
    span = 2 * k
    step = max(1, (len(pool) - span) // (windows - 1))
    out = []
    for start in range(0, len(pool) - span + 1, step)[:windows]:
        window = pool[start:start + span]
        out.append((window[0::2], window[1::2]))
    return out


def test_stability_sets_the_minimum_corpus(chunk_values):
    """Samples of 10k, 25k and 50k words from the whole Austen corpus (her
    three novels, so drift between books counts), paired with disjoint
    samples of the same size: the smallest size at which every pair shares a
    voice is `MIN_CORPUS_WORDS`, `voice import`'s minimum-corpus warning.
    Measured: 10k pairs up to 0.351 apart (median 0.274), 25k up to 0.221
    (0.165), 50k up to 0.121 (0.090), against SAME_VOICE_MAX 0.30."""
    pool = (chunk_values['pride-and-prejudice'] + chunk_values['emma']
            + chunk_values['persuasion'])
    worst, medians, enough = {}, {}, None
    for words in (10_000, 25_000, 50_000):
        ds = [vp.compare(vp.profile(a), vp.profile(b)).distance
              for a, b in _sample_pairs(pool, words)]
        worst[words], medians[words] = max(ds), statistics.median(ds)
        if enough is None and worst[words] <= vp.SAME_VOICE_MAX:
            enough = words
    print(f'worst pair by size {worst}; medians {medians}')
    assert enough == vp.MIN_CORPUS_WORDS
    # more corpus, steadier fingerprint
    assert medians[10_000] > medians[25_000] > medians[50_000]


# ============================================================================
# Test 3: mixed voices
# ============================================================================

def test_mixed_voices_verne_translations_dont_share_a_voice(chunk_values):
    """Around the World in Eighty Days (George M. Towle's translation, 1873)
    and Five Weeks in a Balloon ("William Lackland"'s, 1869) are both Verne,
    but what the fingerprint reads is the English: it reports two voices
    (0.368 apart), while Austen's three novels pair as one (0.21-0.24) and
    each translation's halves agree (0.17, 0.19)."""
    fps = {s: vp.profile(chunk_values[s]) for s in
           ('pride-and-prejudice', 'emma', 'persuasion', 'around-the-world',
            'five-weeks-in-a-balloon')}
    verne = vp.same_voice(fps['around-the-world'], fps['five-weeks-in-a-balloon'])
    print(f'verne pair: {verne.comparison.distance:.3f}')
    assert not verne.same
    for a, b in (('pride-and-prejudice', 'emma'), ('pride-and-prejudice', 'persuasion'),
                 ('emma', 'persuasion')):
        m = vp.same_voice(fps[a], fps[b])
        print(f'{a} / {b}: {m.comparison.distance:.3f}')
        assert m.same, (a, b, m.comparison.distance)
    for s in ('around-the-world', 'five-weeks-in-a-balloon'):
        cs = chunk_values[s]
        half = len(cs) // 2
        assert vp.same_voice(vp.profile(cs[:half]), vp.profile(cs[half:])).same, s


def _seeded_cases(chunk_values):
    bases = {'emma': chunk_values['emma'][::4][:16],
             'pride-and-prejudice': chunk_values['pride-and-prejudice'][::3][:16],
             'persuasion': chunk_values['persuasion'][::2][:16]}
    for base, chunks in bases.items():
        assert len(chunks) == 16
        for author in OTHERS:
            yield base, author, chunks, chunk_values[author][:4]


def test_mixed_voices_seeded_corpus_is_inconsistent(texts, chunk_values):
    """A corpus of 16 Austen chunks seeded with 4 of another author's (20%)
    is reported inconsistent, with the seeded chunks named, across the seven
    other authors and three Austen novels; a pure Austen corpus is
    consistent (separations 0.59-0.62, against OUTLIER_SEPARATION 0.85).
    The 21 cases run on measured chunks through the split `consistency`
    uses (`_minority`); one case runs `consistency` itself on the texts."""
    base = vp.load_baseline()
    flagged = caught = false = 0
    cases = list(_seeded_cases(chunk_values))
    for name, author, austen_chunks, seeded in cases:
        values = austen_chunks + seeded
        group, separation = vp._minority(values, base)
        if separation > vp.OUTLIER_SEPARATION:
            flagged += 1
            caught += sum(1 for i in group if i >= 16)
            false += sum(1 for i in group if i < 16)
    total = len(cases)
    print(f'seeded: {flagged}/{total} flagged, {caught}/{4 * total} seeded chunks named, '
          f'{false} Austen chunks named')
    assert flagged / total >= SEEDED_FLAGGED_FLOOR
    assert caught / (4 * total) >= SEEDED_RECALL_FLOOR
    assert false <= SEEDED_FALSE_MAX

    # pure Austen corpora are consistent
    for slug, step in (('emma', 3), ('pride-and-prejudice', 3), ('persuasion', 2)):
        values = chunk_values[slug][::step][:20]
        group, separation = vp._minority(values, base)
        print(f'pure {slug}: separation {separation:.3f}')
        assert separation <= vp.OUTLIER_SEPARATION, slug

    # end to end on texts: Persuasion seeded with Gatsby, the pieces named
    pieces = {f'persuasion-{i:02d}': c
              for i, c in enumerate(vp.chunks(texts['persuasion'])[::2][:16])}
    gatsby_dir = os.path.join(FIX, 'others', 'gatsby')
    for f in sorted(os.listdir(gatsby_dir))[:4]:
        pieces[f'gatsby-{f}'] = _read(os.path.join(gatsby_dir, f))
    result = vp.consistency(pieces)
    assert not result.consistent
    assert sorted(result.outliers) == sorted(k for k in pieces if k.startswith('gatsby'))

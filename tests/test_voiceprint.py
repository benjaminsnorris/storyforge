"""The voiceprint fingerprint's units (#650): text handling, measures,
fingerprints, comparison and consistency on small synthetic texts. The
reference tests on real authors are in test_voiceprint_reference.py."""

import json
import os

import pytest

from storyforge import voiceprint as vp

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _prose(seed: int, paragraphs: int = 60, contractions: bool = False) -> str:
    """Deterministic filler prose of about 25 words a paragraph."""
    words = ['the', 'house', 'stood', 'quietly', 'beside', 'a', 'river', 'and', 'she',
             'thought', 'of', 'her', 'mother', 'very', 'often', 'in', 'winter', 'it',
             'was', 'not', 'easy', 'to', 'say', 'which', 'he', 'loved']
    out = []
    for p in range(paragraphs):
        sents = []
        for s in range(3):
            n = 6 + (seed * 7 + p * 3 + s * 5) % 9
            ws = [words[(seed + p * 11 + s * 13 + i * 3) % len(words)] for i in range(n)]
            if contractions and s == 1:
                ws[1] = "didn't"
            sents.append(ws[0].capitalize() + ' ' + ' '.join(ws[1:]) + ('?' if s == 2 and p % 4 == 0 else '.'))
        out.append(' '.join(sents))
    return '\n\n'.join(out)


# ============================================================================
# Text
# ============================================================================

def test_paragraphs_drop_headings_breaks_and_markers():
    text = ('# Chapter I\n\nCHAPTER II.\n\nIt was a fine day.\nShe walked out.\n\n'
            '* * *\n\n[Illustration: a lady]\n\nXIV.\n\n“Curly,” she said -- _quite_ so.\n\n'
            'See [the page](http://x.y) now.')
    assert vp.paragraphs(text) == [
        'It was a fine day. She walked out.',
        '"Curly," she said — quite so.',
        'See the page now.',
    ]


@pytest.mark.parametrize('heading', [
    'CHAPTER IV.', 'Chapter the Third', 'CHAPTER FORTY-FOURTH.', 'Part Two: The Return',
    'PART II', 'XIV.', "STAVE I: MARLEY'S GHOST", 'Letter 12', 'THE END.'])
def test_paragraphs_drop_bare_headings(heading):
    assert vp.paragraphs(f'{heading}\n\nShe went home.') == ['She went home.']


@pytest.mark.parametrize('prose', [
    'Part of me wanted to go.', 'Book in hand, she left.', 'Chapter and verse, he said.',
    'Volume after volume fell.', 'Letter by letter it came.'])
def test_paragraphs_keep_prose_that_opens_on_a_heading_word(prose):
    assert vp.paragraphs(prose) == [prose]


def test_split_sentences_titles_initials_and_run_ons():
    assert vp.split_sentences('Mr. Darcy bowed. Mrs. Bennet did not. J. Smith came.') == [
        'Mr. Darcy bowed.', 'Mrs. Bennet did not.', 'J. Smith came.']
    # an exclamation or question before a lower-case word runs on
    assert vp.split_sentences('"Oh! single, my dear." "Why?" said he. Then she left.') == [
        '"Oh! single, my dear."', '"Why?" said he.', 'Then she left.']
    assert vp.split_sentences('It ended. "Then?" "Yes."') == ['It ended.', '"Then?"', '"Yes."']


def test_chunks_cut_at_paragraph_breaks_and_drop_a_short_tail():
    text = _prose(1, paragraphs=200)
    cs = vp.chunks(text, size=1000)
    assert cs, 'no chunks'
    assert all(len(vp.words(c)) >= 1000 for c in cs[:-1])
    assert len(vp.words(cs[-1])) >= 500   # a last run of half a chunk or more stays
    total = len(vp.words(text))
    kept = sum(len(vp.words(c)) for c in cs)
    assert total - kept < 500   # only a tail under half a chunk is dropped
    # each chunk is whole paragraphs of the text
    paras = set(vp.paragraphs(text))
    assert all(p in paras for c in cs for p in c.split('\n\n'))


# ============================================================================
# Measures
# ============================================================================

def test_measures_count_what_they_say():
    text = ("I can't go; she won't. It's late, isn't it? Yes!\n\n"
            "The man (an old one) walked slowly — very slowly — home.")
    m = vp.measure(text)
    n = 20   # words
    assert len(vp.words(text)) == n
    assert m['contraction_rate'] == pytest.approx(1000 * 4 / n)   # can't won't it's isn't
    assert m['semicolon_rate'] == pytest.approx(1000 / n)
    assert m['question_rate'] == pytest.approx(1000 / n)
    assert m['exclamation_rate'] == pytest.approx(1000 / n)
    assert m['dash_rate'] == pytest.approx(2000 / n)
    assert m['parenthesis_rate'] == pytest.approx(1000 / n)
    assert m['fw_the'] == pytest.approx(1000 / n)
    assert m['fw_very'] == pytest.approx(1000 / n)
    assert m['adverb_rate'] == pytest.approx(2000 / n)            # slowly x2
    assert m['paragraph_mean'] == pytest.approx(10)
    assert m['opening_pronoun_share'] == pytest.approx(1.0)       # "I can't go..."
    assert m['closing_exclamation_share'] == pytest.approx(1.0)   # "Yes!"


def test_every_measure_has_a_group_and_no_prose_gives_zeros():
    names = vp.measure_names()
    assert len(names) == len(set(names))
    assert {vp.measure_group(n) for n in names} == set(vp.GROUPS)
    assert all(f'fw_{w}' in names for w in vp.FUNCTION_WORDS)
    assert vp.measure('# Only a heading\n\n* * *') == {n: 0.0 for n in names}


def test_latinate_and_adjective_heuristics():
    m = vp.measure('The administration showed considerable determination. '
                   'A big dog ran home.')
    assert m['latinate_rate'] > 0
    assert m['adjective_rate'] > 0
    assert vp.measure('A big dog ran home.')['latinate_rate'] == 0


# ============================================================================
# Fingerprint
# ============================================================================

def test_fingerprint_refuses_a_small_corpus():
    with pytest.raises(vp.VoiceprintError, match='at least 3 chunks'):
        vp.fingerprint(_prose(1, paragraphs=100), ngrams=False)   # ~2,500 words


def test_profile_refuses_too_few_chunks():
    with pytest.raises(vp.VoiceprintError, match='at least 3'):
        vp.profile([vp.measure(_prose(1))] * 2)


def test_fingerprint_roundtrips_through_json(tmp_path):
    fp = vp.fingerprint({'a.md': _prose(1, 300), 'b.md': _prose(2, 300)})
    path = tmp_path / 'fingerprint.json'
    fp.save(str(path))
    back = vp.Fingerprint.load(str(path))
    assert back.to_json() == fp.to_json()
    assert [p['name'] for p in back.pieces] == ['a.md', 'b.md']
    assert back.chunks == fp.chunks >= 3
    assert path.read_bytes().count(b'\r') == 0


def test_fingerprint_matches_profile_of_its_chunks():
    text = _prose(3, 400)
    fp = vp.fingerprint(text, ngrams=False)
    prof = vp.profile([vp.measure(c) for c in vp.chunks(text)])
    for name in vp.measure_names():
        assert fp.stats[name].center == pytest.approx(prof.stats[name].center)
        assert fp.stats[name].spread == pytest.approx(prof.stats[name].spread)


@pytest.mark.parametrize('change, match', [
    (lambda d: d.update(version=99), 'version'),
    (lambda d: d.update(chunk_words=500), 'chunks of 500'),
    (lambda d: d['measures'].pop('fw_the'), 'missing'),
])
def test_fingerprint_from_another_storyforge_is_refused(change, match):
    data = vp.fingerprint(_prose(4, 300), ngrams=False).to_dict()
    change(data)
    with pytest.raises(vp.VoiceprintError, match=match):
        vp.Fingerprint.from_dict(data)


def test_load_of_an_unreadable_fingerprint_says_so(tmp_path):
    bad = tmp_path / 'fingerprint.json'
    bad.write_text('{not json')
    with pytest.raises(vp.VoiceprintError, match='could not be read'):
        vp.Fingerprint.load(str(bad))


def test_ngrams_leave_names_out():
    para = ('Mr Fairfax said that by no means could she go. Fairfax laughed and '
            'said by no means. ')
    text = '\n\n'.join([para] * 400)
    fp = vp.fingerprint(text)
    grams = [g for g, _, _ in fp.ngrams['3']]
    assert 'by no means' in grams
    assert not any('fairfax' in g for g in grams)


# ============================================================================
# Comparison
# ============================================================================

def test_compare_a_fingerprint_with_itself_is_zero():
    fp = vp.fingerprint(_prose(5, 400), ngrams=False)
    c = vp.compare(fp, fp)
    assert c.distance == pytest.approx(0.0, abs=1e-9)
    assert all(m.z == 0 for m in c.measures)
    assert set(c.groups) == set(vp.GROUPS)


def test_compare_text_names_the_measures_that_moved():
    fp = vp.fingerprint(_prose(6, 400), ngrams=False)
    same = vp.compare(fp, vp.chunks(_prose(6, 400))[0])
    other = vp.compare(fp, _prose(6, 80, contractions=True))
    assert other.distance > same.distance
    top = other.furthest(3)
    assert 'contraction_rate' in [m.name for m in top]
    moved = next(m for m in other.measures if m.name == 'contraction_rate')
    assert moved.z > 0 and not moved.typical
    assert len(other.measures) == len(vp.measure_names())


def test_compare_text_with_no_prose_is_refused():
    fp = vp.fingerprint(_prose(7, 400), ngrams=False)
    with pytest.raises(vp.VoiceprintError, match='no prose'):
        vp.compare(fp, '# heading only')


def test_same_voice_uses_the_threshold():
    fp = vp.fingerprint(_prose(8, 400), ngrams=False)
    assert vp.same_voice(fp, fp).same


def test_baseline_covers_every_measure_and_says_where_it_came_from():
    base = vp.load_baseline()
    assert set(base.sd) == set(vp.measure_names())
    assert all(sd > 0 for sd in base.sd.values())
    assert len(base.sources) >= 20
    assert all(base.ngrams[n] for n in vp.NGRAM_SIZES)


def test_unreadable_or_stale_baseline_says_so(tmp_path):
    missing = tmp_path / 'none.json'
    with pytest.raises(vp.VoiceprintError, match='could not be read'):
        vp.load_baseline(str(missing))
    with open(os.path.join(PLUGIN, vp.BASELINE_REL), encoding='utf-8') as f:
        data = json.load(f)
    data['measures'].pop('fw_the')
    stale = tmp_path / 'stale.json'
    stale.write_text(json.dumps(data))
    with pytest.raises(vp.VoiceprintError, match='fw_the'):
        vp.load_baseline(str(stale))


def test_population_text_strips_gutenberg_boilerplate():
    body = '\n\n'.join(f'Paragraph {i} of the story goes on here.' for i in range(100))
    raw = ('The Project Gutenberg eBook of X\n\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\n\n'
           + body + '\n\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\n\nLicence text.\n')
    out = vp.population_text(raw)
    assert 'Gutenberg' not in out and 'Licence' not in out
    paras = out.split('\n\n')
    assert paras[0].startswith('Paragraph 4 ') and paras[-1].startswith('Paragraph 97 ')


# ============================================================================
# Consistency
# ============================================================================

def test_consistency_refuses_too_few_or_too_short_pieces():
    with pytest.raises(vp.VoiceprintError, match='at least 5 pieces'):
        vp.consistency([_prose(1)] * 4)
    pieces = {f'p{i}': _prose(i, 60) for i in range(5)}
    pieces['tiny'] = 'Too short to judge.'
    with pytest.raises(vp.VoiceprintError, match='tiny'):
        vp.consistency(pieces)


def test_consistency_of_one_voice_names_nothing():
    pieces = {f'p{i}': _prose(i, 60) for i in range(8)}
    result = vp.consistency(pieces)
    assert result.consistent and result.outliers == ()
    assert list(result.distances) == list(pieces)

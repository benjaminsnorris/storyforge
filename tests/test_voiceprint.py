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
    'PART II', 'XIV.', "STAVE I: MARLEY'S GHOST", 'Letter 12', 'THE END.',
    'CHAPTER XII. THE BALL', 'Book One of the Trilogy', 'Chapter 3 — in which she leaves',
    'iv.'])
def test_paragraphs_drop_bare_headings(heading):
    assert vp.paragraphs(f'{heading}\n\nShe went home.') == ['She went home.']


@pytest.mark.parametrize('prose', [
    'Part of me wanted to go.', 'Book in hand, she left.', 'Chapter and verse, he said.',
    'Volume after volume fell.', 'Letter by letter it came.',
    # a heading word and a number, then a sentence (#662 review C1, SF2)
    'Part two of the plan failed badly.', 'Book one was the best of them.',
    'Letter three came on Tuesday.', 'Chapter one ended badly.',
    'Section four was closed, so we went home.', 'Book in hand, she left.',
    # one-word paragraphs spelled in roman-numeral letters aren't numerals
    'Mild.', 'Civil.', 'Did.', 'Vivid.', '"NO!"'])
def test_paragraphs_keep_prose_that_opens_on_a_heading_word(prose):
    assert vp.paragraphs(prose) == [prose]


@pytest.mark.parametrize('caption', [
    'PRELUDE', 'BEFORE THE DAWN', 'WILLIAM COLLINS.',
    '[1] A somewhat remarkable eccentricity of the translator.'])
def test_paragraphs_drop_capital_captions_and_footnotes(caption):
    """A line set in capitals or a footnote isn't the writer's running prose
    (#662 review CR-8)."""
    assert vp.paragraphs(f'{caption}\n\nShe went home.') == ['She went home.']


def test_build_baseline_spaces_its_chunks_through_each_text():
    """The population chunks run from the start of a text to its end, not
    the first `chunks_per_text` of a short step (#662 review C3)."""
    assert vp._spaced(23, 12) == [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]
    assert vp._spaced(30, 12)[-1] == 29 and vp._spaced(30, 12)[0] == 0
    assert vp._spaced(5, 12) == [0, 1, 2, 3, 4]
    assert vp._spaced(9, 1) == [0]


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


def test_every_measure_has_a_group_and_no_prose_is_refused():
    names = vp.measure_names()
    assert len(names) == len(set(names))
    assert {vp.measure_group(n) for n in names} == set(vp.GROUPS)
    assert all(f'fw_{w}' in names for w in vp.FUNCTION_WORDS)
    # all zeros would read as a profile (#662 review SF4)
    with pytest.raises(vp.VoiceprintError, match='no prose'):
        vp.measure('# Only a heading\n\n* * *')


def test_curly_quotes_measure_as_straight_ones():
    """Typographic apostrophes and quotes are folded before words are read:
    without it, "didn’t" splits in two and a modern manuscript has no
    contractions (#662 review T5)."""
    curly = vp.measure('She didn’t go. “Why?” he asked. It’s late.')
    straight = vp.measure('She didn\'t go. "Why?" he asked. It\'s late.')
    assert curly == straight
    n = len(vp.words('She didn\'t go. "Why?" he asked. It\'s late.'))
    assert n == 8
    assert curly['contraction_rate'] == pytest.approx(1000 * 2 / n)
    assert curly['double_quote_rate'] == pytest.approx(1000 * 2 / n)


def test_a_text_of_one_sentence_paragraphs_has_no_openings():
    """Openings and closings are read over paragraphs of two sentences or
    more; with none, they are 0 (#662 review T8)."""
    m = vp.measure('She went home.\n\nHe stayed.\n\n"Why?"')
    assert m['one_sentence_paragraph_share'] == 1.0
    assert m['opening_pronoun_share'] == 0.0 and m['opening_sentence_mean'] == 0.0
    assert m['opening_dialogue_share'] == pytest.approx(1 / 3)   # over every paragraph


def test_measures_match_the_recorded_golden_values():
    """A change to any measure's definition shows here first (#662 review
    TD-1). When it is meant: bump FINGERPRINT_VERSION if a fingerprint of
    the old version has shipped, rebuild baseline.json and the reference
    fingerprint.json (references/voiceprints/README.md), and re-record
    tests/fixtures/voiceprint/golden-measures.json."""
    with open(os.path.join(PLUGIN, 'tests', 'fixtures', 'voiceprint', 'golden-measures.json'),
              encoding='utf-8') as f:
        golden = json.load(f)
    with open(os.path.join(PLUGIN, 'references', 'voiceprints', 'austen', 'corpus',
                           'pride-and-prejudice.md'), encoding='utf-8') as f:
        chunk = vp.chunks(f.read())[0]
    got = {k: vp._round(v) for k, v in vp.measure(chunk).items()}
    changed = sorted(k for k in set(got) | set(golden['measures'])
                     if got.get(k) != golden['measures'].get(k))
    assert golden['fingerprint_version'] == vp.FINGERPRINT_VERSION
    assert not changed, (f'measures changed: {changed[:10]}; see this test\'s docstring')


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
    with pytest.raises(vp.VoiceprintError, match='at least 3 chunks \\(about 5000 words\\)'):
        vp.fingerprint(_prose(1, paragraphs=100), ngrams=False)   # ~2,500 words


def test_fingerprint_refuses_a_piece_with_no_prose():
    """An empty corpus file is named, not skipped: the fingerprint would
    silently stand for less of the corpus (#662 review SF5)."""
    with pytest.raises(vp.VoiceprintError, match='no prose: empty.md'):
        vp.fingerprint({'a.md': _prose(1, 300), 'empty.md': '# Chapter 1\n\n'}, ngrams=False)


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


@pytest.fixture(scope='module')
def fp_dict():
    return vp.fingerprint(_prose(4, 300), ngrams=False).to_dict()


def _stat(d, name='fw_the'):
    return d['measures'][name]['stat']


@pytest.mark.parametrize('change, match', [
    (lambda d: d.pop('words'), 'words None is not a count'),
    (lambda d: d.update(words='many'), 'words'),
    (lambda d: d.update(chunks=True), 'chunks'),
    (lambda d: d.update(words=0), 'not a corpus'),
    (lambda d: d.update(chunks=2), 'not a corpus'),
    (lambda d: _stat(d).pop(), 'fw_the: stat'),
    (lambda d: _stat(d).__setitem__(0, 'a'), 'fw_the: stat'),
    (lambda d: _stat(d).__setitem__(1, float('nan')), 'fw_the: stat'),
    (lambda d: d['measures'].__setitem__('fw_the', [1, 2, 3, 4, 5]), 'fw_the: stat'),
    (lambda d: d.update(stat_fields=['center', 'value', 'spread', 'p10', 'p90']), 'stat_fields'),
    (lambda d: d.pop('stat_fields'), 'stat_fields'),
    (lambda d: d.update(pieces={}), 'pieces'),
    (lambda d: d.update(ngrams=[]), 'ngrams'),
])
def test_malformed_fingerprint_is_refused_naming_the_field(fp_dict, change, match):
    """A hand-edited or truncated fingerprint.json is a VoiceprintError that
    names the field, never a traceback or a silent wrong verdict (#662
    review SF1, TD-2, TD-3, TD-4)."""
    data = json.loads(json.dumps(fp_dict))
    change(data)
    with pytest.raises(vp.VoiceprintError, match=match):
        vp.Fingerprint.from_dict(data)


def test_fingerprint_that_is_not_an_object_is_refused():
    with pytest.raises(vp.VoiceprintError, match='JSON object'):
        vp.Fingerprint.from_dict([1, 2])


def test_load_refuses_nan_and_names_the_file(tmp_path, fp_dict):
    text = json.dumps(fp_dict).replace(json.dumps(_stat(fp_dict)), '[NaN, 1, 1, 1, 1]', 1)
    bad = tmp_path / 'fingerprint.json'
    bad.write_text(text)
    with pytest.raises(vp.VoiceprintError, match='could not be read.*NaN'):
        vp.Fingerprint.load(str(bad))
    data = json.loads(json.dumps(fp_dict))
    data['words'] = -1
    bad.write_text(json.dumps(data))
    with pytest.raises(vp.VoiceprintError, match=f'{bad}: fingerprint words -1'):
        vp.Fingerprint.load(str(bad))


def test_fingerprint_needs_every_measure():
    fp = vp.fingerprint(_prose(4, 300), ngrams=False)
    stats = dict(fp.stats)
    stats.pop('fw_the')
    with pytest.raises(vp.VoiceprintError, match='fw_the'):
        vp.Fingerprint(1, 1, 1, 3, stats)
    with pytest.raises(vp.VoiceprintError, match='Stat'):
        vp.Fingerprint(1, 1, 1, 3, {n: 1.0 for n in vp.measure_names()})


def test_a_profile_cannot_be_saved(tmp_path):
    """A profile has measures but no corpus counts: saved, it would read as a
    fingerprint of 0 words (#662 review TD-4)."""
    prof = vp.profile([vp.measure(c) for c in vp.chunks(_prose(3, 400))])
    with pytest.raises(vp.VoiceprintError, match='profile'):
        prof.save(str(tmp_path / 'fingerprint.json'))
    assert not (tmp_path / 'fingerprint.json').exists()


def test_below_minimum_corpus():
    small = vp.fingerprint(_prose(4, 300), ngrams=False)
    assert small.words < vp.MIN_CORPUS_WORDS and small.below_minimum_corpus


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
    # two fingerprints have no single value to place in a range (#662 TD-6)
    assert all(m.typical is None for m in c.measures)


def test_compare_text_names_the_measures_that_moved():
    fp = vp.fingerprint(_prose(6, 400), ngrams=False)
    same = vp.compare(fp, vp.chunks(_prose(6, 400))[0])
    other = vp.compare(fp, _prose(6, 80, contractions=True))
    assert other.distance > same.distance
    top = other.furthest(3)
    assert 'contraction_rate' in [m.name for m in top]
    moved = next(m for m in other.measures if m.name == 'contraction_rate')
    assert moved.z > 0 and moved.typical is False
    assert len(other.measures) == len(vp.measure_names())


def test_compare_text_with_no_prose_is_refused():
    fp = vp.fingerprint(_prose(7, 400), ngrams=False)
    with pytest.raises(vp.VoiceprintError, match='no prose'):
        vp.compare(fp, '# heading only')


def test_compare_refuses_a_text_too_short_for_the_chunk_scale():
    """A five-word text measured against chunk centers is noise, not a
    verdict (#662 review SF3); `compare_values` stays open to the caller."""
    fp = vp.fingerprint(_prose(7, 400), ngrams=False)
    with pytest.raises(vp.VoiceprintError, match=f'at least {vp.MIN_COMPARE_WORDS}'):
        vp.compare(fp, 'She smiled. He went home.')
    assert vp.compare_values(fp, vp.measure('She smiled. He went home.')).distance > 0


def test_same_voice_uses_the_threshold(monkeypatch):
    fp = vp.fingerprint(_prose(8, 400), ngrams=False)
    assert vp.same_voice(fp, fp).same
    # at the threshold the same voice, just past it not (#662 review T6)
    for d, same in ((vp.SAME_VOICE_MAX, True), (vp.SAME_VOICE_MAX + 1e-9, False)):
        monkeypatch.setattr(vp, 'compare', lambda a, b, base=None, d=d: vp.Comparison(d, {}, ()))
        assert vp.same_voice(fp, fp).same is same


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


@pytest.mark.parametrize('change, match', [
    (lambda d: d['measures'].__setitem__('fw_the', [1.0, 0.0]), 'sd > 0.*fw_the'),
    (lambda d: d['measures'].__setitem__('fw_the', [1.0]), 'fw_the'),
    (lambda d: d['ngrams']['2'].pop('rates'), 'n = 2'),
    (lambda d: d['ngrams'].pop('3'), 'n = 3'),
])
def test_malformed_baseline_is_refused(tmp_path, change, match):
    """A baseline with a zero sd or no n-gram rates is a VoiceprintError,
    not a ZeroDivisionError or KeyError later (#662 review SF6)."""
    with open(os.path.join(PLUGIN, vp.BASELINE_REL), encoding='utf-8') as f:
        data = json.load(f)
    change(data)
    bad = tmp_path / 'baseline.json'
    bad.write_text(json.dumps(data))
    with pytest.raises(vp.VoiceprintError, match=match):
        vp.load_baseline(str(bad))
    bad.write_text('[]')
    with pytest.raises(vp.VoiceprintError, match='JSON object'):
        vp.load_baseline(str(bad))


def test_build_baseline_round_trips_through_load_baseline(tmp_path):
    """The baseline builder's output loads, every sd is positive (floored at
    the noise floor), and a text under a chunk is refused (#662 review T7)."""
    texts = {f'Book {i}': _prose(i, 400) for i in range(1, 4)}
    data = vp.build_baseline(texts, chunks_per_text=4)
    assert [s['chunks'] for s in data['sources']] == [4, 4, 4]
    path = tmp_path / 'baseline.json'
    path.write_text(json.dumps(data))
    base = vp.load_baseline(str(path))
    assert base.sources == tuple(texts)
    assert all(sd > 0 for sd in base.sd.values())
    # a measure every chunk scores the same still has its noise floor
    assert base.sd['parenthesis_rate'] == pytest.approx(vp._noise_floor('parenthesis_rate', 0.0))
    with pytest.raises(vp.VoiceprintError, match='Short'):
        vp.build_baseline({'Short': _prose(1, 10)})


def test_cosine_distance_of_a_profile_at_the_population_mean_is_one():
    """A profile with every z at 0 has no direction: the distance is 1, not
    a division by zero (#662 review T8)."""
    base = vp.load_baseline()
    other = vp.measure(_prose(1, 100))
    assert vp._cosine_distance(dict(base.mean), other, base) == 1.0


def test_build_baseline_refuses_no_texts():
    with pytest.raises(vp.VoiceprintError, match='at least one'):
        vp.build_baseline({})


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


def test_consistency_values_refuses_mismatched_or_too_few():
    v = vp.measure(_prose(1, 60))
    with pytest.raises(vp.VoiceprintError, match='names for'):
        vp.consistency_values(['a', 'b'], [v] * 5)
    with pytest.raises(vp.VoiceprintError, match='at least 5'):
        vp.consistency_values(list('abcd'), [v] * 4)
    with pytest.raises(vp.VoiceprintError, match='named once'):
        vp.consistency_values(list('aabcd'), [v] * 5)


def test_consistency_of_one_voice_names_nothing():
    pieces = {f'p{i}': _prose(i, 60) for i in range(8)}
    result = vp.consistency(pieces)
    assert result.consistent and result.outliers == ()
    assert list(result.distances) == list(pieces)

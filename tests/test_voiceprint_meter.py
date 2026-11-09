"""The voice meter (plan B6, #653): `storyforge score --voice`.

Free and deterministic. The reference case is the issue's "Done when":
Austen's held-out novels (*Emma*, *Persuasion*) score close to her
*Pride and Prejudice* fingerprint, and modern prose scores far. Wrath
Like Smoke's draft (Ben's unpublished book) isn't in the repo; its reading
is in the PR. Here the modern prose is a synthetic draft written for this
test (`tests/fixtures/voiceprint/modern-draft.md`) and the *Gatsby*
excerpts the fingerprint tests already use.
"""

import dataclasses
import glob
import json
import math
import os
import shutil

import pytest

from storyforge import voiceprint as vp
from storyforge import voiceprint_meter as meter

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUSTEN = os.path.join(PLUGIN, 'references', 'voiceprints', 'austen')
AUSTEN_FP = os.path.join(AUSTEN, 'fingerprint.json')
FIX = os.path.join(PLUGIN, 'tests', 'fixtures', 'voiceprint')
MODERN = os.path.join(FIX, 'modern-draft.md')
OTHERS = ('age-of-innocence', 'brimming-cup', 'christmas-carol', 'gatsby',
          'middlemarch', 'plastic-age', 'self-control')

#: Emma 0.214, Persuasion 0.225 (measured 2026-11-09), against the 40,000+
#: word limit, `SAME_VOICE_MAX` (0.30)
HELD_OUT_MAX = 0.30
#: Gatsby's ten excerpts pooled (19,757 words) 1.473, the synthetic draft
#: (1,277 words) 1.300; Wrath's draft (144,426 words) measured 1.380
MODERN_MIN = 1.0


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _other(slug):
    return '\n\n'.join(_read(p) for p in sorted(glob.glob(os.path.join(FIX, 'others', slug,
                                                                        '*'))))


@pytest.fixture(scope='module')
def repo():
    return meter.load_source(voice_repo=AUSTEN)


@pytest.fixture(scope='module')
def fp_only():
    return meter.load_source(fingerprint_path=AUSTEN_FP)


@pytest.fixture(scope='module')
def held_out(repo):
    return {slug: meter.meter(repo, {slug: _read(os.path.join(AUSTEN, 'corpus', f'{slug}.md'))})
            for slug in ('emma', 'persuasion')}


# ============================================================================
# Done when: Austen's held-out novels close, modern prose far
# ============================================================================

@pytest.mark.parametrize('slug', ['emma', 'persuasion'])
def test_held_out_austen_scores_close(held_out, slug):
    report = held_out[slug]
    assert report.distance <= HELD_OUT_MAX
    assert report.reading == meter.CLOSE and report.limit == vp.SAME_VOICE_MAX


def test_held_out_austen_shows_almost_no_constructions(held_out):
    # measured: Emma 1 ("and only"), Persuasion 1 ("there had been")
    for report in held_out.values():
        assert len(report.constructions) <= 2
        assert report.construction_basis == 'corpus'


def test_modern_prose_scores_far(repo):
    gatsby = meter.meter(repo, {'gatsby': _other('gatsby')})
    draft = meter.meter(repo, {'draft': _read(MODERN)})
    for report in (gatsby, draft):
        assert report.distance >= MODERN_MIN
        assert not report.close


def test_austens_contemporary_reads_far_at_length(repo):
    # Brunton's Self-Control (1811), the fingerprint tests' hard case: 0.636
    # over 21,333 words, against the 20,000-word limit 0.33
    report = meter.meter(repo, {'self-control': _other('self-control')})
    assert not report.close


def test_synthetic_draft_lists_its_constructions_and_sentences(repo):
    report = meter.meter(repo, {'draft': _read(MODERN)})
    phrases = {c.phrase: c for c in report.constructions}
    assert "he didn't" in phrases and phrases["he didn't"].corpus_count == 0
    assert phrases["he didn't"].example and phrases["he didn't"].piece == 'draft'
    assert len(report.constructions) <= meter.CONSTRUCTION_KEEP
    # no listed phrase sits inside another listed one
    for a in phrases:
        for b in phrases:
            assert a == b or not meter._overlaps(a, b)
    assert report.sentences
    top = report.sentences[0]
    assert top.piece == 'draft' and top.surprise > 0 and top.reasons
    # the colons and contractions Austen's narration doesn't use are there
    kinds = {r.kind for s in report.sentences for r in s.reasons}
    assert {'colon_rate', 'contraction_rate'} <= kinds


def test_fingerprint_alone_measures_constructions_against_the_baseline(fp_only):
    report = meter.meter(fp_only, {'draft': _read(MODERN)})
    assert report.construction_basis == 'baseline'
    assert all(c.corpus_count is None for c in report.constructions)
    assert "he didn't" in {c.phrase for c in report.constructions}
    # the baseline holds no 4-word rates, and the report says so (TD-1)
    assert all(len(c.phrase.split()) <= 3 for c in report.constructions)
    assert '2- and 3-word phrases only' in '\n'.join(meter.report_lines(report))
    # the writer's own favoured phrases are never listed
    own = {g for grams in fp_only.fingerprint.ngrams.values() for g, *_ in grams}
    assert not own & {c.phrase for c in report.constructions}


def test_the_writers_own_phrases_are_left_out_against_the_baseline(fp_only):
    # T1: a phrase the draft overuses is dropped once the fingerprint
    # records it as the writer's own
    fp = fp_only.fingerprint
    grams = {k: list(v) for k, v in fp.ngrams.items()}
    grams['2'] = grams['2'] + [["he didn't", 10, 20.0]]
    own = dataclasses.replace(fp_only, fingerprint=dataclasses.replace(fp, ngrams=grams))
    report = meter.meter(own, {'draft': _read(MODERN)})
    assert "he didn't" not in {c.phrase for c in report.constructions}
    assert not report.warnings or 'phrase list' not in ' '.join(report.warnings)


def test_a_fingerprint_with_no_phrase_list_says_so(fp_only):
    # SF-2: nothing to leave out, so the report can't claim it did
    bare = dataclasses.replace(fp_only, fingerprint=dataclasses.replace(fp_only.fingerprint,
                                                                         ngrams={}))
    report = meter.meter(bare, {'draft': _read(MODERN)})
    assert any('holds no phrase list' in w for w in report.warnings)
    assert any('holds no phrase list' in line for line in meter.report_lines(report))


def test_modern_prose_at_length_lists_real_constructions(repo):
    # T2/T4: real modern prose (Gatsby, 19,757 words), not only the
    # synthetic draft; past 10,000 words a phrase with one open word can
    # qualify ("with an effort": 5 uses, none in the corpus)
    report = meter.meter(repo, {'gatsby': _other('gatsby')})
    phrases = {c.phrase: c for c in report.constructions}
    assert {"i don't", "i didn't"} <= set(phrases)
    assert phrases["i didn't"].corpus_count == 0
    assert any(sum(1 for w in p.split() if not meter._closed(w)) == 1 for p in phrases)
    assert all(c.example for c in report.constructions)


# ============================================================================
# CLOSE_LIMITS: Austen's held-out samples within, others beyond
# ============================================================================

def _samples(text, size):
    out, cur, n = [], [], 0
    for p in vp.paragraphs(text):
        cur.append(p)
        n += len(vp.words(p))
        if n >= size:
            out.append('\n\n'.join(cur))
            cur, n = [], 0
    return out


@pytest.mark.parametrize('size', [1000, 1500, 2000, 5000, 10000, 20000])
def test_close_limits_hold_on_the_reference(repo, size):
    """A calibration pin, not an independent check (T5): `CLOSE_LIMITS`
    was set from these same samples, so the Austen half holds the limits
    where they were measured. The other authors' half is the real test."""
    fp = repo.fingerprint
    austen = [s for slug in ('emma', 'persuasion')
              for s in _samples(_read(os.path.join(AUSTEN, 'corpus', f'{slug}.md')), size)]
    others = [s for slug in OTHERS for s in _samples(_other(slug), size)]
    read = lambda s: meter.reading(vp.compare(fp, s).distance, size)
    # no held-out Austen sample reads far (1,000 words: furthest 0.78;
    # 2,000: 0.63; 10,000: 0.44) ...
    assert all(read(s) != meter.FAR for s in austen)
    # ... no other author's reads close: under 2,000 words some come inside
    # Austen's spread (16 of 131 at 1,000), and those read unclear (CR-2) ...
    readings = [read(s) for s in others]
    assert meter.CLOSE not in readings
    # ... and from 2,000 words nearly all are beyond the limit
    if size >= 2000:
        assert readings.count(meter.FAR) / len(readings) >= 0.95


@pytest.mark.parametrize('distance,words,expected', [
    (0.50, 1000, 'close'), (0.70, 1500, 'unclear'), (0.85, 1999, 'far'),
    (0.64, 2000, 'unclear'), (0.60, 2000, 'close'), (0.66, 2000, 'far'),
    (0.52, 5000, 'close'), (0.53, 5000, 'far'), (0.30, 150000, 'close'),
])
def test_reading(distance, words, expected):
    assert meter.reading(distance, words) == expected
    with pytest.raises(ValueError):
        meter.reading(0.1, vp.MIN_COMPARE_WORDS - 1)


def test_an_unclear_reading_is_said(repo):
    report = meter.meter(repo, {'draft': _read(MODERN)})
    unclear = dataclasses.replace(report, words=1500, limit=0.80, reading=meter.UNCLEAR)
    line = next(l for l in meter.report_lines(unclear) if l.startswith('Distance: '))
    assert 'unclear' in line and "can't tell them apart" in line and '0.59' in line


def test_close_limit_loosens_as_prose_shortens():
    assert meter.close_limit(vp.MIN_COMPARE_WORDS - 1) is None
    assert meter.close_limit(vp.MIN_COMPARE_WORDS) == 0.80
    assert meter.close_limit(1999) == 0.80 and meter.close_limit(2000) == 0.65
    assert meter.close_limit(150000) == vp.SAME_VOICE_MAX
    limits = [meter.close_limit(n) for n in (1000, 2000, 5000, 10000, 20000, 40000)]
    assert limits == sorted(limits, reverse=True)


# ============================================================================
# The meter's pieces
# ============================================================================

def test_too_short_is_a_finding_not_a_zero(repo):
    with pytest.raises(meter.TooShort) as e:
        meter.meter(repo, {'a': 'She went out. ' * 100, 'b': '# Heading only'})
    assert e.value.words == 300 and e.value.empty == ('b',)
    assert 'too short to measure' in str(e.value)
    # expected for a short scene, so not the fatal MeterError (TD-2)
    assert not isinstance(e.value, meter.MeterError)


def test_word_count_matches_compares(repo):
    # the meter counts as `compare` does: exactly the minimum measures,
    # one word fewer is too short (never compare's own refusal)
    words = vp.words(' '.join(vp.paragraphs(_read(MODERN))))
    sentence = lambda ws: ' '.join(ws) + '.'
    enough = meter.meter(repo, {'a': sentence(words[:vp.MIN_COMPARE_WORDS])})
    assert enough.words == vp.MIN_COMPARE_WORDS
    with pytest.raises(meter.TooShort):
        meter.meter(repo, {'a': sentence(words[:vp.MIN_COMPARE_WORDS - 1])})


def test_a_baseline_that_cant_be_read_is_a_meter_error(repo, monkeypatch):
    def broken(path=None):
        raise vp.VoiceprintError('the voiceprint baseline is missing')
    monkeypatch.setattr(vp, 'load_baseline', broken)
    with pytest.raises(meter.MeterError, match='baseline'):
        meter.meter(repo, {'draft': _read(MODERN)})


def test_pieces_under_the_minimum_count_only_in_the_pool(repo):
    draft = _read(MODERN)
    paras = vp.paragraphs(draft)
    report = meter.meter(repo, {'whole': draft, 'snip': paras[1], 'blank': '# Heading only'})
    assert [p.name for p in report.pieces] == ['whole']
    assert report.short == ('snip',)
    assert report.empty == ('blank',)
    lines = '\n'.join(meter.report_lines(report))
    assert 'counted only in the pool: snip' in lines
    assert 'No prose to measure: blank' in lines


def test_short_pieces_pool_to_a_reading(repo):
    # scenes under 1,000 words each still give the pool a distance
    paras = vp.paragraphs(_read(MODERN))
    pieces = {f's{i}': '\n\n'.join(paras[i:i + 10]) for i in range(0, len(paras), 10)}
    assert all(len(vp.words(t)) < vp.MIN_COMPARE_WORDS for t in pieces.values())
    report = meter.meter(repo, pieces)
    assert not report.pieces and len(report.short) == len(pieces)
    assert report.words >= vp.MIN_COMPARE_WORDS and not report.close


def test_report_says_it_is_not_a_target(repo):
    report = meter.meter(repo, {'draft': _read(MODERN)})
    lines = meter.report_lines(report)
    assert meter.DRIFT_NOTE in lines
    assert 'never a target for an automatic rewrite loop' in meter.DRIFT_NOTE
    text = '\n'.join(lines)
    for heading in ('## By group', 'measures furthest from the fingerprint',
                    '## Sentences furthest from the corpus',
                    '## Constructions the prose uses far more than the reference'):
        assert heading in text


def test_report_keeps_its_own_top(repo):
    # TD-8: the lists and their headings follow the meter's `top`
    report = meter.meter(repo, {'draft': _read(MODERN)}, top=3)
    text = '\n'.join(meter.report_lines(report))
    assert report.top == 3 and 'The 3 measures furthest' in text
    assert len(report.sentences) <= 3


def test_report_renders_its_warnings(repo):
    # T3: a small corpus and a fingerprint without sentence lengths are
    # said in the report, and length isn't judged
    fp = dataclasses.replace(repo.fingerprint, words=20000, sentence_lengths={})
    report = meter.meter(dataclasses.replace(repo, fingerprint=fp), {'draft': _read(MODERN)})
    lines = meter.report_lines(report)
    assert any(l.startswith('WARNING: the fingerprint was made from 20,000 words') for l in lines)
    assert any('no sentence-length distribution' in l for l in lines)
    assert all(r.kind != 'length' for s in report.sentences for r in s.reasons)


def test_report_says_when_a_list_is_empty(repo):
    # T7: the "says so" branches
    report = meter.meter(repo, {'draft': _read(MODERN)})
    bare = dataclasses.replace(report, pieces=(), sentences=(), constructions=())
    text = '\n'.join(meter.report_lines(bare))
    assert 'None is long enough to measure alone.' in text
    assert 'None stands out.' in text
    assert 'None used 5+ times at 8x' in text


def test_poisson_surprise():
    assert meter._poisson_surprise(0, 0.5) == 0
    assert meter._poisson_surprise(1, 2.0) == 0          # less than expected: none
    one = meter._poisson_surprise(1, 0.01)
    assert one == pytest.approx(-math.log(1 - math.exp(-0.01)), rel=1e-6)
    assert meter._poisson_surprise(2, 0.01) > one
    assert meter._poisson_surprise(50, 0.001) == meter.SURPRISE_CAP


def test_sentence_surprise_reads_the_writers_habits(repo):
    fp = repo.fingerprint
    austen, _ = meter.sentence_surprise(
        fp, 'She was very much obliged to him, and could not but feel it.')
    modern, parts = meter.sentence_surprise(
        fp, "He didn't look back: he'd seen enough.")
    assert modern > austen
    kinds = {r.kind for r in parts}
    assert {'colon_rate', 'contraction_rate'} <= kinds
    colon = next(r for r in parts if r.kind == 'colon_rate')
    assert colon.count == 1 and colon.writer_rate > 0 and colon.text.startswith('colon x1')


def test_sentence_list_is_not_one_habit_over_and_over(repo):
    report = meter.meter(repo, {'draft': _read(MODERN)})
    kinds = [s.reasons[0].kind for s in report.sentences]
    assert max(kinds.count(k) for k in kinds) <= meter.SAME_REASON_MAX


@pytest.mark.parametrize('a,b,overlap', [
    ('the edge of', 'the edge of the', True), ('in the middle of', 'the middle of the', True),
    ('at the edge of', 'the edge of the', True), ('off the', 'toward the', False),
    ("he didn't", "she didn't", False), ('all of it', 'out of him', False),
])
def test_overlaps(a, b, overlap):
    assert meter._overlaps(a, b) is overlap and meter._overlaps(b, a) is overlap


def test_a_length_reason_is_kind_length(repo):
    # TD-3: the kind is data, never parsed back out of the shown text
    _, parts = meter.sentence_surprise(repo.fingerprint, 'Gone.')
    length = next(r for r in parts if r.kind == 'length')
    assert length.count == 1 and length.text.startswith('1 word ')


def test_example_spans_punctuation():
    # CR-4: the phrase list counts across commas and dashes
    pieces = {'a': 'He said, and then he left. She didn\u2019t look up.'}
    assert meter._example(pieces, 'said and then') == ('a', 'He said, and then he left.')
    assert meter._example(pieces, "she didn't")[1].startswith('She didn')
    assert meter._example(pieces, 'and then she') == ('', '')


def test_a_construction_without_an_example_says_so(repo):
    report = meter.meter(repo, {'draft': _read(MODERN)})
    lone = meter.Construction('and so on', 5, 0, 9.0, '', '')
    lines = meter.report_lines(dataclasses.replace(report, constructions=(lone,)))
    assert any('(no example' in l for l in lines)


def test_constructions_leave_corpus_names_out_of_the_prose_too(repo, monkeypatch):
    # T9: a word written as a name in the corpus ("miss", "lady") is left
    # out of the prose's phrases as well as the corpus's
    seen = []
    real = vp.ngram_counts

    def spy(text, n, names=None):
        seen.append((n, names))
        return real(text, n, names)
    monkeypatch.setattr(vp, 'ngram_counts', spy)
    meter.constructions(repo, {'draft': _read(MODERN)})
    corpus_names, _ = repo.corpus_counts
    assert {'miss', 'lady'} <= corpus_names
    assert all(corpus_names <= names for n, names in seen if n > 1)


@pytest.mark.parametrize('phrase,ok', [
    ("he didn't", True), ('the ships', False), ('the edge of', True),
    ('in the middle of', True), ('the old man', False), ('the spear', False),
])
def test_construction_shape(phrase, ok):
    assert meter._construction_shape(phrase, topical={'spear'}) is ok


def test_topic_words_never_make_constructions(repo):
    # a word used this often is what the prose is about, not how it's written
    base = _read(MODERN)
    extra = '\n\n'.join(['The spear was by the door. He took the spear and went out.'] * 20)
    report = meter.meter(repo, {'draft': base + '\n\n' + extra})
    assert not any('spear' in c.phrase for c in report.constructions)


# ============================================================================
# load_source
# ============================================================================

def test_load_source_needs_exactly_one_way(tmp_path):
    with pytest.raises(meter.MeterError):
        meter.load_source()
    with pytest.raises(meter.MeterError):
        meter.load_source(AUSTEN_FP, AUSTEN)


def test_load_source_from_a_voice_repo_reads_the_corpus(repo, fp_only):
    assert repo.corpus and list(repo.corpus) == ['corpus/pride-and-prejudice.md']
    assert "Jane Austen's voice repo" in repo.label
    assert fp_only.corpus is None and fp_only.label == AUSTEN_FP
    # TD-5/TD-6: the corpus is read-only, and parsed once per source
    with pytest.raises(TypeError):
        repo.corpus['x'] = 'y'
    assert repo.corpus_counts is repo.corpus_counts
    assert fp_only.corpus_counts is None


def test_only_the_reference_voice_is_calibrated(repo, fp_only, tmp_path):
    # CR-3/TD-4: the limits were measured on Austen; for anyone else the
    # report says they are a scale
    assert repo.calibrated and fp_only.calibrated
    shutil.copy(AUSTEN_FP, tmp_path / 'fingerprint.json')
    other = meter.load_source(fingerprint_path=str(tmp_path / 'fingerprint.json'))
    assert not other.calibrated
    line = next(l for l in meter.report_lines(meter.meter(other, {'d': _read(MODERN)}))
                if l.startswith('Distance: '))
    assert 'a scale for this writer, not a verdict' in line
    line = next(l for l in meter.report_lines(meter.meter(fp_only, {'d': _read(MODERN)}))
                if l.startswith('Distance: '))
    assert 'not a verdict' not in line


def test_a_corpus_that_changed_since_the_fingerprint_is_an_error(tmp_path):
    # SF-1: an emptied or cut corpus file must not become the reference
    voice = tmp_path / 'voice'
    os.makedirs(voice / 'corpus')
    for name in ('voice.yaml', 'fingerprint.json'):
        shutil.copy(os.path.join(AUSTEN, name), voice / name)
    text = _read(os.path.join(AUSTEN, 'corpus', 'pride-and-prejudice.md'))
    (voice / 'corpus' / 'pride-and-prejudice.md').write_text(text[:len(text) // 2],
                                                            encoding='utf-8')
    with pytest.raises(meter.MeterError, match='compute the fingerprint again'):
        meter.load_source(voice_repo=str(voice))


@pytest.mark.parametrize('field,value', [
    ('ngrams', {'2': [5, 6]}), ('ngrams', {'2': 'abc'}),
    ('sentence_lengths', {'1-5': 'x'}), ('sentence_lengths', {'tiny': 0.5}),
])
def test_a_malformed_fingerprint_entry_is_named(tmp_path, field, value):
    # SF-3: the meter iterates these, so a bad entry is refused on load
    data = json.loads(_read(AUSTEN_FP))
    data[field] = value
    path = tmp_path / 'fingerprint.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(meter.MeterError, match=field):
        meter.load_source(fingerprint_path=str(path))


def test_load_source_errors_name_the_problem(tmp_path, project_dir):
    with pytest.raises(meter.MeterError, match='fingerprint'):
        meter.load_source(fingerprint_path=str(tmp_path / 'missing.json'))
    with pytest.raises(meter.MeterError, match='voice.yaml'):
        meter.load_source(voice_repo=str(tmp_path))
    with pytest.raises(meter.MeterError, match='is a book'):
        meter.load_source(voice_repo=project_dir)


# ============================================================================
# storyforge score --voice
# ============================================================================

SCENE = 'act1-sc01'


def _tree(root):
    return {os.path.join(d, n): os.path.getmtime(os.path.join(d, n))
            for d, _, files in os.walk(root) if '.git' not in d for n in files}


def _forbid_spending(monkeypatch):
    def boom(*a, **k):
        raise AssertionError('nothing may be spent or written')
    for name in ('create_branch', 'ensure_branch_pushed', 'commit_and_push'):
        monkeypatch.setattr(f'storyforge.cmd_score.{name}', boom)
    from storyforge import api
    for name in ('invoke_to_file', 'invoke_api', 'submit_batch', 'invoke'):
        if hasattr(api, name):
            monkeypatch.setattr(api, name, boom)


def _draft_scene(project_dir):
    with open(os.path.join(project_dir, 'scenes', f'{SCENE}.md'), 'w', encoding='utf-8') as f:
        f.write(_read(MODERN))


def test_score_voice_prints_the_meter_without_writing(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _draft_scene(project_dir)
    _forbid_spending(monkeypatch)
    before = _tree(project_dir)
    cmd_score.main(['--voice', '--fingerprint', AUSTEN_FP])
    out = capsys.readouterr()
    assert meter.DRIFT_NOTE in out.out
    assert 'Distance: ' in out.out and ', far.' in out.out
    assert f'{SCENE}: ' in out.out                       # measured alone
    assert 'counted only in the pool' in out.out         # the fixture's short scenes
    # scenes in scope with no file are named, not skipped silently
    log = out.out + out.err
    assert 'have no scene file' in log and 'act2-sc02' in log
    assert _tree(project_dir) == before


def test_score_voice_takes_scene_filters_and_top(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _draft_scene(project_dir)
    cmd_score.main(['--voice', '--voice-repo', AUSTEN, '--scenes', SCENE, '--top', '3'])
    out = capsys.readouterr().out
    assert 'in 1 piece(s)' in out and 'act1-sc02' not in out
    assert 'Measured against the corpus itself.' in out
    assert 'The 3 measures furthest' in out
    sentences = out.split('## Sentences furthest from the corpus')[1].split('##')[0]
    assert '3. [' in sentences and '4. [' not in sentences


def test_score_voice_too_short_is_said_and_exits_1(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--voice', '--fingerprint', AUSTEN_FP])   # 566 words drafted
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert 'Too short to measure' in out and 'Distance' not in out


def test_score_voice_too_short_names_empty_scenes(project_dir, monkeypatch, capsys):
    # SF-4: an empty scene file is why the pool is short, so it is named
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    with open(os.path.join(project_dir, 'scenes', 'act1-sc02.md'), 'w') as f:
        f.write('# Heading only\n')
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--voice', '--fingerprint', AUSTEN_FP])
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert 'Too short to measure' in out and 'No prose to measure: act1-sc02' in out


def test_score_voice_names_an_unreadable_scene_and_exits_1(project_dir, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _draft_scene(project_dir)
    with open(os.path.join(project_dir, 'scenes', 'act1-sc02.md'), 'wb') as f:
        f.write(b'\xff\xfe not utf-8 \x80')
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--voice', '--fingerprint', AUSTEN_FP])
    assert e.value.code == 1
    out = capsys.readouterr()
    assert 'Distance: ' in out.out                       # the report, then the error
    assert "act1-sc02 can't be read" in out.out + out.err


def test_score_voice_prose_files_outside_a_project(tmp_path, monkeypatch, capsys):
    # through the dispatcher, which used to exit outside a project
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv', ['storyforge', 'score', '--voice', '--fingerprint',
                                     AUSTEN_FP, '--prose', MODERN])
    from storyforge.__main__ import main as dispatch_main
    dispatch_main()
    out = capsys.readouterr().out
    assert f'[{MODERN}]' in out and ', far.' in out


def test_score_voice_prose_file_that_cant_be_read(tmp_path, monkeypatch, capsys):
    from storyforge import cmd_score
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--voice', '--fingerprint', AUSTEN_FP, '--prose', MODERN,
                        str(tmp_path / 'missing.md')])
    assert e.value.code == 1
    out = capsys.readouterr()
    assert "missing.md can't be read" in out.out + out.err
    assert 'No such file' in out.out + out.err                     # SF-5: why, not just what


def test_score_voice_none_readable_says_so(tmp_path, monkeypatch, capsys):
    # T6: the cause leads, not "too short: 0 words"
    from storyforge import cmd_score
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--voice', '--fingerprint', AUSTEN_FP, '--prose', 'nope.md'])
    assert e.value.code == 1
    out = capsys.readouterr()
    assert 'none of the files in scope could be read' in out.out + out.err
    assert 'Too short' not in out.out + out.err


def test_score_voice_measures_a_file_named_twice_once(tmp_path, monkeypatch, capsys):
    # CR-5: two spellings of one path would count it twice in the pool
    from storyforge import cmd_score
    monkeypatch.chdir(FIX)
    cmd_score.main(['--voice', '--fingerprint', AUSTEN_FP, '--prose', MODERN,
                    'modern-draft.md'])
    out = capsys.readouterr()
    assert 'in 1 piece(s)' in out.out and 'measured once' in out.out + out.err


def test_score_voice_meter_error_at_the_cli(project_dir, monkeypatch, capsys):
    # T7: a baseline that can't be read stops with ERROR, never a report
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _draft_scene(project_dir)

    def broken(path=None):
        raise vp.VoiceprintError('the voiceprint baseline is missing')
    monkeypatch.setattr(vp, 'load_baseline', broken)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(['--voice', '--fingerprint', AUSTEN_FP])
    assert e.value.code == 1
    out = capsys.readouterr()
    assert 'ERROR: the voiceprint baseline is missing' in out.out + out.err
    assert 'Distance' not in out.out


@pytest.mark.parametrize('argv', [
    ['--voice'],                                                   # no fingerprint
    ['--voice', '--fingerprint', AUSTEN_FP, '--voice-repo', AUSTEN],
    ['--voice', '--fingerprint', AUSTEN_FP, '--register'],
    ['--voice', '--fingerprint', AUSTEN_FP, '--readability'],
    ['--readability', '--voice'],
    ['--voice', '--fingerprint', AUSTEN_FP, '--deterministic'],
    ['--voice', '--fingerprint', AUSTEN_FP, '--direct'],
    ['--voice', '--fingerprint', AUSTEN_FP, '--level', '3'],
    ['--voice', '--fingerprint', AUSTEN_FP, '--prose', MODERN, '--scenes', SCENE],
    ['--voice', '--fingerprint', AUSTEN_FP, '--top', '0'],
    ['--voice', '--fingerprint', '/nonexistent/fingerprint.json'],
    ['--fingerprint', AUSTEN_FP],                                  # without --voice
    ['--deterministic', '--voice-repo', AUSTEN],
    ['--prose', MODERN],
    ['--voice', '--fingerprint', AUSTEN_FP, '--scenes', 'no-such-scene'],
    # CR-1: --complete-cycle refuses the free meter instead of spending
    ['--complete-cycle', '--voice', '--fingerprint', AUSTEN_FP],
    ['--complete-cycle', '--top', '5'],
])
def test_score_voice_refusals(project_dir, monkeypatch, capsys, argv):
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _forbid_spending(monkeypatch)
    before = _tree(project_dir)
    with pytest.raises(SystemExit) as e:
        cmd_score.main(argv)
    assert e.value.code == 1
    out = capsys.readouterr()
    assert 'ERROR' in out.out + out.err
    assert _tree(project_dir) == before


@pytest.mark.parametrize('argv,named', [
    (['--complete-cycle', '--voice', '--fingerprint', AUSTEN_FP], '--voice, --fingerprint'),
    (['--complete-cycle', '--top', '5'], '--top'),
])
def test_complete_cycle_refuses_the_meters_flags(project_dir, monkeypatch, capsys, argv, named):
    # CR-1: refused by name before any cycle is looked for, never dropped
    from storyforge import cmd_score
    monkeypatch.chdir(project_dir)
    _forbid_spending(monkeypatch)
    monkeypatch.setattr(cmd_score, '_find_incomplete_cycle',
                        lambda *a: pytest.fail('looked for a cycle to re-score'))
    with pytest.raises(SystemExit) as e:
        cmd_score.main(argv)
    assert e.value.code == 1
    out = capsys.readouterr()
    assert f"--complete-cycle fills in what a cycle is missing; it can't be combined with " \
        f'{named}' in out.out + out.err


def test_gn_score_voice_is_an_error(project_dir_gn, monkeypatch, capsys):
    from storyforge import cmd_score_gn
    monkeypatch.chdir(project_dir_gn)
    with pytest.raises(SystemExit) as e:
        cmd_score_gn.main(['--voice', '--fingerprint', AUSTEN_FP])
    assert e.value.code == 1
    out = capsys.readouterr()
    assert 'graphic-novel project has none to measure' in out.out + out.err


def test_find_project_root(tmp_path, project_dir):
    from storyforge.common import find_project_root
    assert find_project_root(str(tmp_path)) is None
    os.makedirs(os.path.join(project_dir, 'scenes', 'deep'), exist_ok=True)
    assert find_project_root(os.path.join(project_dir, 'scenes', 'deep')) == \
        os.path.realpath(project_dir)


def test_score_outside_a_project_still_says_so(tmp_path, monkeypatch, capsys):
    # SF-6: the dispatcher no longer exits outside a project (for --prose),
    # so plain `storyforge score` must still stop with the project ERROR
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv', ['storyforge', 'score', '--deterministic'])
    _forbid_spending(monkeypatch)
    from storyforge.__main__ import main as dispatch_main
    with pytest.raises(SystemExit) as e:
        dispatch_main()
    assert e.value.code == 1
    out = capsys.readouterr()
    assert 'storyforge.yaml' in out.out + out.err

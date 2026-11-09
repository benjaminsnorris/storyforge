"""The voice meter (plan B6, #653): `storyforge score --voice`.

Free and deterministic. The reference case is the issue's "Done when":
Austen's held-out novels (*Emma*, *Persuasion*) score close to her
*Pride and Prejudice* fingerprint, and modern prose scores far. Wrath
Like Smoke's draft (Ben's unpublished book) isn't in the repo; its reading
is in the PR. Here the modern prose is a synthetic draft written for this
test (`tests/fixtures/voiceprint/modern-draft.md`) and the *Gatsby*
excerpts the fingerprint tests already use.
"""

import glob
import math
import os

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
    assert report.close and report.limit == vp.SAME_VOICE_MAX


def test_held_out_austen_shows_almost_no_constructions(held_out):
    # measured: Emma 1 ("and only"), Persuasion 1 ("there had been")
    for report in held_out.values():
        assert len(report.constructions) <= 2
        assert report.construction_basis == 'the corpus itself'


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
    reasons = ' '.join(r for s in report.sentences for r in s.reasons)
    assert 'colon' in reasons and 'contraction' in reasons


def test_fingerprint_alone_measures_constructions_against_the_baseline(fp_only):
    report = meter.meter(fp_only, {'draft': _read(MODERN)})
    assert 'general baseline' in report.construction_basis
    assert all(c.corpus_count is None for c in report.constructions)
    assert "he didn't" in {c.phrase for c in report.constructions}
    # the writer's own favoured phrases are never listed
    own = {g for grams in fp_only.fingerprint.ngrams.values() for g, *_ in grams}
    assert not own & {c.phrase for c in report.constructions}


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


@pytest.mark.parametrize('size', [2000, 10000])
def test_close_limits_hold_on_the_reference(repo, size):
    fp = repo.fingerprint
    austen = [s for slug in ('emma', 'persuasion')
              for s in _samples(_read(os.path.join(AUSTEN, 'corpus', f'{slug}.md')), size)]
    others = [s for slug in OTHERS for s in _samples(_other(slug), size)]
    limit = meter.close_limit(size)
    # every held-out Austen sample reads close (2,000 words: furthest 0.63;
    # 10,000: 0.44) ...
    assert all(vp.compare(fp, s).distance <= limit for s in austen)
    # ... and nearly every other author's far (2,000: all 138 beyond 0.65;
    # 10,000: all 25 beyond 0.45)
    beyond = sum(1 for s in others if vp.compare(fp, s).distance > limit)
    assert beyond / len(others) >= 0.95


def test_close_limit_loosens_as_prose_shortens():
    assert meter.close_limit(vp.MIN_COMPARE_WORDS - 1) is None
    assert meter.close_limit(vp.MIN_COMPARE_WORDS) == 0.80
    assert meter.close_limit(150000) == vp.SAME_VOICE_MAX
    limits = [meter.close_limit(n) for n in (1000, 2000, 5000, 10000, 20000, 40000)]
    assert limits == sorted(limits, reverse=True)


# ============================================================================
# The meter's pieces
# ============================================================================

def test_too_short_is_a_finding_not_a_zero(repo):
    with pytest.raises(meter.TooShort) as e:
        meter.meter(repo, {'a': 'She went out. ' * 100})
    assert e.value.words == 300
    assert 'too short to measure' in str(e.value)


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
                    "## Constructions the prose uses that the corpus doesn't"):
        assert heading in text


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
    kinds = {meter._reason_kind(r) for _, r in parts}
    assert {'colon', 'contraction'} <= kinds


def test_sentence_list_is_not_one_habit_over_and_over(repo):
    report = meter.meter(repo, {'draft': _read(MODERN)})
    kinds = [meter._reason_kind(s.reasons[0]) for s in report.sentences]
    assert max(kinds.count(k) for k in kinds) <= meter.SAME_REASON_MAX


@pytest.mark.parametrize('a,b,overlap', [
    ('the edge of', 'the edge of the', True), ('in the middle of', 'the middle of the', True),
    ('at the edge of', 'the edge of the', True), ('off the', 'toward the', False),
    ("he didn't", "she didn't", False), ('all of it', 'out of him', False),
])
def test_overlaps(a, b, overlap):
    assert meter._overlaps(a, b) is overlap and meter._overlaps(b, a) is overlap


def test_reason_kind():
    assert meter._reason_kind('colon x1 (the writer: 0.33 per 1,000 words)') == 'colon'
    assert meter._reason_kind('1 word (the writer: 8% of sentences are 1-5 words)') == 'length'
    assert meter._reason_kind('45 words (the writer: ...)') == 'length'


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
    assert find_project_root(str(tmp_path / 'nowhere')) is None or \
        find_project_root(str(tmp_path)) is None
    os.makedirs(os.path.join(project_dir, 'scenes', 'deep'), exist_ok=True)
    assert find_project_root(os.path.join(project_dir, 'scenes', 'deep')) == \
        os.path.realpath(project_dir)

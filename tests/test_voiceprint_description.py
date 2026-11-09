"""The voiceprint's reference tests 4 and 5 (plan B7, #651), on the Austen
reference voiceprint (`references/voiceprints/austen/`).

**Test 4, the description (recorded once, then frozen).** `voice propose`'s
claims for Austen (`proposals/description-claims.csv`, recorded once with a
real model call) are checked against a fixed list of claims a critic would
make or reject (`AFFIRM`, `REJECT`). The list was fixed before the
recording. The recording is frozen in the committed cassette
(`tests/fixtures/voiceprint/cassette/`, the repo's cassette format): the
request and reply of each call. `test_recording_is_the_committed_proposals`
parses the recorded replies against the recorded sample (#645's policy:
frozen inputs, evaluated free) and fails when the prompts, schemas or system
block wording the code would send have changed (`stale`), which is the time
to re-record on purpose
(`references/voiceprints/README.md`, "Re-recording"). A change to the
fingerprint or the sampling doesn't invalidate it: the recording is what
the model said to the sample it was shown.

**Test 5, the exemplar shortlist (free).** The shortlisted passages sit
inside the fingerprint's typical range (`PassageRange`, against the
corpus's own passages of their size), and they span the jobs.

The reference has no author to mark claims or pick passages, so its
`description.md` keeps the claims the critic's list doesn't reject
(`reference_mark`), and its `exemplars/` are the shortlist's `auto_picks`;
both are checked here to be exactly what `voice accept` makes of the
committed proposals.
"""

import filecmp
import os
import re

import pytest

from storyforge import voiceprint as vp
from storyforge import voiceprint_proposals as vpp

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUSTEN = os.path.join(PLUGIN, 'references', 'voiceprints', 'austen')
CASSETTE = os.path.join(PLUGIN, 'tests', 'fixtures', 'voiceprint', 'cassette')
#: the model the recording was made with (`common.select_model('synthesis')`
#: on 2026-11-08)
RECORDED_MODEL = 'claude-opus-5-5'

# ============================================================================
# Test 4's answer key: what a critic says of Austen's narrative voice
# ============================================================================
# Each item is a list of patterns, any of which counts, matched
# case-insensitively against a claim's text. A match preceded closely by a
# negation ("rather than", "never", "not") doesn't count as asserting it.
# Fixed before the recording was made (2026-11-08); changing it to fit the
# recording would make the test say nothing.

_DESCRIPTION_WORDS = (r'(physical|visual|sensory|landscapes?|scenery|settings?|appearances?|'
                      r'descri\w*|imagery|nature|rooms?|clothes|faces?)')

#: (name, patterns, required): some claim of the voice's positive sections
#: (every section but `never`) must assert it
AFFIRM = (
    ('an ironic narrator', [r'\biron(y|ic|ically|ies)\b'], True),
    ('free indirect discourse', [
        r'free[- ]indirect',
        r"\b(characters?|heroines?|speakers?|someone|people)('s|s')?\s+(own\s+)?(thoughts?|minds?|idiom|voices?|words|language|views?|perspectives?|consciousness|feelings)\b.{0,80}\b(without|unmarked|no quotation|narrat)",
        r'\bnarrat\w*\b.{0,60}\b(takes? on|borrows?|adopts?|slips? into|slides? into|absorbs?|ventriloqui\w+|blends? with|merges? with|inhabits?)\b.{0,40}\b(characters?|heroines?|thoughts?|idiom|voices?|minds?)',
    ], True),
    ('balanced, periodic or antithetical sentences', [
        r'\bbalanc', r'\bperiodic', r'\bantithe', r'\bparallel', r'\bsymmetr',
        r'\bpaired\b', r'\bpairs? of (clauses|phrases|terms|words|adjectives|nouns)'], True),
    ('aphoristic generalisation', [
        r'\baphor', r'\bepigram', r'\bmaxim', r'\bgenerali[sz]', r'\bsententi',
        r'\b(universal|general) (truths?|statements?|observations?|reflections?|propositions?)'],
     False),
    ('wit, comedy or satire', [r'\bwit\b', r'\bwitty\b', r'\bsatir', r'\bcomed', r'\bcomic',
                               r'\bmock'], False),
    ('abstract, evaluative vocabulary', [
        r'\babstract', r'\blatinate', r'\bevaluative',
        r'\bmoral (vocabulary|terms|language|words|judg\w+|qualities)',
        r'\bjudg(e)?ments? (of|on|about) (character|conduct|behaviou?r)'], False),
)

#: little physical description: a positive claim saying description is
#: sparse, or a `never` claim about description
SPARSE_DESCRIPTION = (
    'little physical description',
    [r'\b(little|sparse|spare|scant|scanty|minimal|rarely|seldom|few|brief|not much|'
     r'sparing\w*|withholds?|skimps?)\b.{0,50}\b' + _DESCRIPTION_WORDS],
    [r'\b' + _DESCRIPTION_WORDS])

#: (name, patterns): no claim of a positive section may assert it
REJECT = (
    ('plain, short sentences', [
        r'\b(plain|simple|terse|clipped|spare|stripped|minimalist?|unadorned)\b[^.;]{0,30}'
        r'\b(sentences?|prose|style|syntax|diction)\b',
        r'\b(mostly|mainly|chiefly|predominantly|largely)\s+short\b']),
    ('lush description', [
        r'\b(lush|lavish|ornate|florid|vivid|rich|sensuous|sensory|detailed|elaborate|'
        r'painterly|lyrical)\b[^.;]{0,30}\b(descriptions?|imagery|scenery|landscapes?|'
        r'settings?|detail)\b']),
    ('stream of consciousness', [r'stream[- ]of[- ]consciousness', r'\binterior monologue']),
)

#: test 4's gate: every required item, at least this many of AFFIRM and
#: SPARSE_DESCRIPTION's 7, and no REJECT
AFFIRM_FLOOR = 5

_NEGATION = re.compile(r"\b(not|never|no|nor|rather than|instead of|avoids?|without|seldom|"
                       r"rarely|nothing|neither|hardly|isn't|doesn't|won't)\b[^.;]{0,25}$",
                       re.IGNORECASE)


def asserts(patterns, text):
    """Whether `text` asserts any of `patterns`: a match not preceded
    closely by a negation."""
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            if not _NEGATION.search(text[max(0, m.start() - 40):m.start()]):
                return True
    return False


def mentions(patterns, text):
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def score(claims):
    """{'affirmed': [names], 'missing': [names], 'rejected': [(name, claim id)]}."""
    positive = [c for c in claims if c.positive]
    never = [c for c in claims if not c.positive]
    affirmed, missing = [], []
    for name, pats, _ in AFFIRM:
        (affirmed if any(asserts(pats, c.claim) for c in positive) else missing).append(name)
    name, pos_pats, never_pats = SPARSE_DESCRIPTION
    found = (any(asserts(pos_pats, c.claim) for c in positive)
             or any(mentions(never_pats, c.claim) for c in never))
    (affirmed if found else missing).append(name)
    rejected = [(name, c.id) for name, pats in REJECT for c in positive
                if asserts(pats, c.claim)]
    return {'affirmed': affirmed, 'missing': missing, 'rejected': rejected}


def reference_mark(claim):
    """The reference's stand-in for the author's mark: `no` for a claim
    the critic's list rejects, `yes` for the rest."""
    if claim.positive and any(asserts(pats, claim.claim) for _, pats in REJECT):
        return 'no'
    return 'yes'


# ---------------------------------------------------------------------------
# The answer key itself, on made-up claims
# ---------------------------------------------------------------------------

def _c(section, text, cid='c01'):
    return vpp.Claim(cid, section, text)


def test_answer_key_reads_assertions_not_negations():
    assert asserts(REJECT[0][1], 'Sentences are plain and simple in their syntax.')
    assert not asserts(REJECT[0][1], 'Its sentences are never plain or simple prose.')
    assert not asserts(REJECT[0][1], 'Prefers long periodic sentences rather than plain sentences.')
    assert asserts(AFFIRM[1][1], 'The narration slips into a character\'s idiom mid-sentence.')
    assert asserts(AFFIRM[1][1], 'Uses free indirect style throughout.')
    assert not asserts(AFFIRM[0][1], 'Is earnest throughout.')


def test_answer_key_scores_a_good_and_a_bad_description():
    good = [_c('does', 'An ironic narrator comments on the characters.', 'c01'),
            _c('does', 'Free indirect discourse carries a heroine\'s thoughts.', 'c02'),
            _c('rhythm', 'Sentences are balanced on paired clauses.', 'c03'),
            _c('does', 'Opens with a general truth stated as a maxim.', 'c04'),
            _c('humour', 'Its wit is dry.', 'c05'),
            _c('never', 'Never dwells on landscape or physical appearance.', 'c06')]
    s = score(good)
    assert s['rejected'] == [] and len(s['affirmed']) == 6
    bad = [_c('does', 'Writes in short, plain sentences.', 'c01'),
           _c('does', 'Lush description of every room.', 'c02'),
           _c('does', 'Uses stream of consciousness.', 'c03')]
    s = score(bad)
    assert {n for n, _ in s['rejected']} == {name for name, _ in REJECT}
    assert s['affirmed'] == []


# ============================================================================
# Test 4 on the recording
# ============================================================================

@pytest.fixture(scope='module')
def claims():
    return vpp.read_claims(AUSTEN)


def test_description_matches_the_critics(claims):
    s = score(claims)
    required = [name for name, _, req in AFFIRM if req]
    assert not [n for n in required if n in s['missing']], s
    assert len(s['affirmed']) >= AFFIRM_FLOOR, s
    assert s['rejected'] == [], s


def test_description_covers_every_section_and_names_no_one(claims):
    assert {c.section for c in claims} == set(vpp.SECTIONS)
    for c in claims:
        assert not re.search(r'austen|pride and prejudice', c.claim, re.IGNORECASE), c


def test_reference_marks_follow_the_critics_list(claims):
    assert [c.mark for c in claims] == [reference_mark(c) for c in claims]


def test_reference_description_is_what_accept_writes(claims, tmp_path):
    with open(os.path.join(AUSTEN, vpp.DESCRIPTION_FILE), encoding='utf-8') as f:
        assert f.read() == vpp.render_description(claims, 'Jane Austen')


# ============================================================================
# Test 5: the shortlist
# ============================================================================

#: test 5's gates, fixed before the recording: the shortlist's size is the
#: plan's; at least this share of it typical ...
TYPICAL_FLOOR = 0.75
#: ... at least this many of the six jobs, none over this share
JOBS_FLOOR = 5
JOB_SHARE_MAX = 0.4


@pytest.fixture(scope='module')
def voice():
    return vpp.load_voice(AUSTEN)


@pytest.fixture(scope='module')
def shortlist():
    return vpp.read_shortlist(AUSTEN)


@pytest.fixture(scope='module')
def judged(voice, shortlist):
    rng = vpp.passage_range(voice.fingerprint, voice.texts)
    return [rng.judge(p) for p in shortlist]


def test_shortlist_size_and_lengths(shortlist):
    assert vpp.SHORTLIST_MIN <= len(shortlist) <= vpp.SHORTLIST_MAX
    for p in shortlist:
        assert vpp.PASSAGE_MIN <= p.words <= vpp.PASSAGE_MAX, p.id


def test_shortlist_passages_are_the_corpus_as_written(voice, shortlist):
    for p in shortlist:
        paras = vpp.prose_paragraphs(voice.texts[p.source])
        first, last = (int(x) for x in p.paragraphs.split('-'))
        assert p.text == '\n\n'.join(paras[first - 1:last]), p.id


def test_shortlist_sits_inside_the_typical_range(judged, shortlist):
    typical = [p for p in judged if p.typical]
    assert len(typical) / len(judged) >= TYPICAL_FLOOR, [
        (p.id, p.distance, p.limit) for p in judged if not p.typical]
    # the committed figures are today's (after a fingerprint change: `storyforge voice judge`,
    # then `voice accept --only exemplars --auto-pick --force`, both free); the
    # 4-decimal figures within a rounding step, across platforms and Pythons
    assert [p.typical for p in judged] == [p.typical for p in shortlist]
    for now, committed in zip(judged, shortlist):
        assert now.distance == pytest.approx(committed.distance, abs=1e-3), now.id
        assert now.limit == pytest.approx(committed.limit, abs=1e-3), now.id


def test_shortlist_spans_the_jobs(shortlist):
    counts = {j: sum(1 for p in shortlist if p.job == j) for j in vpp.JOBS}
    assert sum(1 for n in counts.values() if n) >= JOBS_FLOOR, counts
    assert max(counts.values()) / len(shortlist) <= JOB_SHARE_MAX, counts


def test_typical_range_tells_austen_from_others(voice):
    """The range means something: held-out Austen passages (Emma) fall
    inside it far more often than other authors' (the test fixtures'
    excerpts), in every band: passages are grown to each band's lower
    bound in turn (100, 150, 200, 300 words)."""
    rng = vpp.passage_range(voice.fingerprint, voice.texts)

    def share(text):
        paras = vpp.prose_paragraphs(text)
        hits = n = 0
        for t, i in enumerate(range(0, len(paras), 9)):
            target = vpp.PASSAGE_BANDS[t % len(vpp.PASSAGE_BANDS)]
            words, j = 0, i
            while j < len(paras) and words < target:
                words += len(vp.words(paras[j]))
                j += 1
            if vpp.PASSAGE_MIN <= words <= vpp.PASSAGE_MAX:
                n += 1
                hits += rng.distance('\n\n'.join(paras[i:j])) <= rng.limit(words)
        return hits / n

    with open(os.path.join(AUSTEN, 'corpus', 'emma.md'), encoding='utf-8') as f:
        emma = share(f.read())
    others_dir = os.path.join(PLUGIN, 'tests', 'fixtures', 'voiceprint', 'others')
    texts = []
    for author in sorted(os.listdir(others_dir)):
        d = os.path.join(others_dir, author)
        for name in sorted(os.listdir(d)):
            with open(os.path.join(d, name), encoding='utf-8') as f:
                texts.append(f.read())
    others = share('\n\n'.join(texts))
    # measured 2026-11-09 (the bands' runs spread across each band): Emma
    # 0.831, the others 0.086
    assert emma >= 0.8 and others <= 0.3, (emma, others)


def test_reference_exemplars_are_the_auto_picks(shortlist):
    picks = vpp.auto_picks(shortlist)
    assert [p.id for p in shortlist if p.pick == 'yes'] == picks
    index = vpp._read_rows(os.path.join(AUSTEN, vpp.EXEMPLARS_INDEX), vpp.EXEMPLAR_COLUMNS)
    assert [r['id'] for r in index] == picks
    for pid in picks:
        assert filecmp.cmp(os.path.join(AUSTEN, vpp.SHORTLIST_DIR, f'{pid}.md'),
                           os.path.join(AUSTEN, vpp.EXEMPLARS_DIR, f'{pid}.md'), shallow=False)
    files = {n[:-3] for n in os.listdir(os.path.join(AUSTEN, vpp.EXEMPLARS_DIR))
             if n.endswith('.md')}
    assert files == set(picks)


# ============================================================================
# The recording replays
# ============================================================================

def _recordings():
    """The cassette's recordings, {'description': (body, reply text, response),
    'shortlist': ...}, told apart by their schema."""
    import gzip
    import json
    from storyforge import api
    out = {}
    for root, _, files in os.walk(CASSETTE):
        for name in files:
            with gzip.open(os.path.join(root, name), 'rt', encoding='utf-8') as f:
                rec = json.load(f)
            body = rec['request']['body']
            schema = body['output_config']['format']['schema']
            kind = 'description' if 'claims' in schema['properties'] else 'shortlist'
            assert kind not in out, f'two {kind} recordings in {CASSETTE}'
            out[kind] = (body, api.extract_text(rec['response']), rec['response'])
    return out


_NUMBER = re.compile(r'[-+]?\d[\d,.]*')


def _fingerprint_shape(section):
    """The fingerprint section's wording with its figures and contents
    masked: the header, the headings and each line's form, but not which
    measures, words or phrases the fingerprint holds (a fingerprint change
    doesn't invalidate the recording)."""
    shapes = set()
    lines = [ln for ln in section.split('\n') if ln.strip()]
    for i, line in enumerate(lines):
        masked = _NUMBER.sub('#', line)
        if i == 0 or line.startswith('### '):
            shapes.add(masked)
        elif line.startswith('- '):
            shapes.add(re.sub(r'^- [^:]+:', '- NAME:', masked))
        else:
            shapes.add('<list>')
    return shapes


def stale(recs, voice):
    """What the code would send differently from the recording, by name
    ([] when nothing has changed): the prompts, the schemas, and the system
    block's fixed wording (everything before the fingerprint's figures,
    rebuilt from the recorded sample, must match it byte for byte; the
    fingerprint section's wording with its figures masked)."""
    out = []
    for kind, prompt, schema in (('description', vpp.description_prompt(), vpp.CLAIMS_SCHEMA),
                                 ('shortlist', vpp.shortlist_prompt(), vpp.SHORTLIST_SCHEMA)):
        body = recs[kind][0]
        if body['messages'][0]['content'] != prompt:
            out.append(f'the {kind} prompt')
        if body['output_config']['format']['schema'] != schema:
            out.append(f'the {kind} schema')
    if recs['shortlist'][0]['system'] != recs['description'][0]['system']:
        out.append('the two calls\' system blocks differ')
    recorded = recs['description'][0]['system'][0]['text']
    now = vpp.system_blocks(voice, vpp.recorded_sample(recorded, voice.texts))[0]['text']
    rec_head, _, rec_fp = recorded.partition('# The fingerprint')
    now_head, _, now_fp = now.partition('# The fingerprint')
    if rec_head != now_head:
        out.append('the system block before the fingerprint (SYSTEM_PREAMBLE, the sample\'s '
                   'instructions, render_sample)')
    if _fingerprint_shape(rec_fp) != _fingerprint_shape(now_fp):
        out.append('the fingerprint section\'s wording (render_fingerprint)')
    return out


def test_recording_is_the_committed_proposals(voice):
    """The recorded replies, parsed against the recorded sample, are the
    committed proposals (before the reference's marks, picks and today's
    judgments). Fails when a prompt, a schema or the system block's wording
    changed since the recording (`stale`): re-record on purpose
    (references/voiceprints/README.md, "Re-recording")."""
    recs = _recordings()
    assert set(recs) == {'description', 'shortlist'}
    changed = stale(recs, voice)
    assert changed == [], (f'{", ".join(changed)} changed since the recording: re-record on '
                           f'purpose (references/voiceprints/README.md)')
    for kind in recs:
        body, _, response = recs[kind]
        assert body['model'] == RECORDED_MODEL and response.get('stop_reason') == 'end_turn'
    system_text = recs['description'][0]['system'][0]['text']
    sample = vpp.recorded_sample(system_text, voice.texts)
    assert sample.windows == vpp.SAMPLE_WINDOWS

    claims, problems = vpp.parse_claims(recs['description'][1], sample)
    assert problems == []
    want = vpp.read_claims(AUSTEN)
    assert [(c.id, c.section, c.claim, c.example) for c in claims] == [
        (c.id, c.section, c.claim, c.example) for c in want]

    passages, refused = vpp.parse_shortlist(recs['shortlist'][1], sample)
    assert refused == []
    fields = ('id', 'job', 'source', 'paragraphs', 'words', 'text', 'why')
    assert [tuple(getattr(p, f) for f in fields) for p in passages] == [
        tuple(getattr(p, f) for f in fields) for p in vpp.read_shortlist(AUSTEN)]


def _reword(fn, old, new):
    def wrapped(*a, **k):
        out = fn(*a, **k)
        assert old in out, old
        return out.replace(old, new)
    return wrapped


@pytest.mark.parametrize('change,named', [
    (lambda m: m.setattr(vpp, 'DESCRIPTION_PROMPT', vpp.DESCRIPTION_PROMPT + ' More.'),
     'the description prompt'),
    (lambda m: m.setattr(vpp, 'SHORTLIST_ASK', 25), 'the shortlist prompt'),
    (lambda m: m.setattr(vpp, 'SHORTLIST_SCHEMA', {**vpp.SHORTLIST_SCHEMA, 'title': 'x'}),
     'the shortlist schema'),
    (lambda m: m.setattr(vpp, 'SYSTEM_PREAMBLE', 'You help a writer.'),
     'the system block before the fingerprint'),
    (lambda m: m.setattr(vpp, 'render_sample',
                         _reword(vpp.render_sample, ' words] ', ' w] ')),
     'the system block before the fingerprint'),
    (lambda m: m.setattr(vpp, 'render_fingerprint',
                         _reword(vpp.render_fingerprint, 'z is how many', 'z counts')),
     'the fingerprint section'),
    (lambda m: m.setattr(vpp, 'render_fingerprint',
                         _reword(vpp.render_fingerprint, '; z ', '; zscore ')),
     'the fingerprint section'),
])
def test_stale_names_each_change_to_what_would_be_sent(voice, monkeypatch, change, named):
    """T2: the re-record trigger trips on each part of the request."""
    recs = _recordings()
    assert stale(recs, voice) == []
    change(monkeypatch)
    changed = stale(recs, voice)
    assert len(changed) == 1 and changed[0].startswith(named), changed


def test_recorded_model_is_todays_synthesis_model():
    """T9: a note (not a failure) when the synthesis model has moved on
    since the recording, so the reference's age is visible."""
    import warnings
    from storyforge.common import select_model
    today = select_model(vpp.MODEL_TASK)
    if today != RECORDED_MODEL:
        warnings.warn(f'the Austen description was recorded on {RECORDED_MODEL}; the '
                      f'synthesis model is now {today} (re-record when it matters)')

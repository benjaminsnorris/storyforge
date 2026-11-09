"""The voiceprint's proposals and their acceptance (#651, plan B3/B4):
`storyforge.voiceprint_proposals` and `storyforge voice propose / accept`,
with the model faked. The reference tests on the Austen recording are in
test_voiceprint_description.py."""

import json
import os
import shutil

import pytest

from storyforge import voiceprint as vp
from storyforge import voiceprint_proposals as vpp

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSUASION = os.path.join(PLUGIN, 'references', 'voiceprints', 'austen', 'corpus',
                          'persuasion.md')


def _head(words: int) -> str:
    """The opening of Persuasion, whole paragraphs, about `words` words."""
    with open(PERSUASION, encoding='utf-8') as f:
        blocks = f.read().split('\n\n')
    out, n = [], 0
    for b in blocks:
        out.append(b)
        n += len(vp.words(b))
        if n >= words:
            break
    return '\n\n'.join(out) + '\n'


@pytest.fixture(scope='module')
def voice_template(tmp_path_factory):
    d = tmp_path_factory.mktemp('voice')
    os.makedirs(d / 'corpus')
    text = _head(24000)
    (d / 'corpus' / 'persuasion.md').write_text(text, encoding='utf-8')
    (d / 'voice.yaml').write_text('author: Test Author\ncorpus:\n  - file: corpus/persuasion.md\n',
                                  encoding='utf-8')
    vp.fingerprint({'corpus/persuasion.md': text}, ngrams=False).save(str(d / 'fingerprint.json'))
    return d


@pytest.fixture
def voice_dir(voice_template, tmp_path):
    d = tmp_path / 'voice'
    shutil.copytree(voice_template, d)
    return str(d)


def _reply(obj) -> dict:
    return {'content': [{'type': 'text', 'text': json.dumps(obj)}], 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 10, 'output_tokens': 10}}


GOOD_CLAIMS = {'claims': [
    {'section': 'rhythm', 'claim': 'Long sentences | then short.', 'example': ''},
    {'section': 'does', 'claim': 'Uses irony.', 'example': '"It was so," said she.'},
    {'section': 'never', 'claim': 'Never uses slang.', 'example': ''},
    {'section': 'stance', 'claim': 'Sits above the characters.', 'example': ''},
    {'section': 'humour', 'claim': 'Dry.', 'example': ''},
    {'section': 'does', 'claim': '  Generalises\nfreely. ', 'example': ''},
]}


#: a sample holding GOOD_CLAIMS' one example
SAMPLE = vpp.Sample((vpp.Paragraph(1, 'c.md', 1, 1, '"It was so," said she, and left.', 7),), 1)


def _runs_of(sample, words_lo=120, words_hi=380):
    """Paragraph runs inside one window, within the length, not overlapping."""
    out, used = [], set()
    for p in sample.paragraphs:
        n, last = 0, p.number
        while True:
            q = sample.get(last)
            if q is None or q.window != p.window:
                break
            n += q.words
            if n >= words_lo:
                break
            last += 1
        span = set(range(p.number, last + 1))
        if words_lo <= n <= words_hi and not span & used and sample.get(last):
            out.append((p.number, last))
            used |= span
    return out


def _shortlist_reply(sample, k=24):
    runs = _runs_of(sample)[:k]
    return {'passages': [{'first': a, 'last': b, 'job': vpp.JOBS[i % len(vpp.JOBS)],
                          'why': f'shows {i}'} for i, (a, b) in enumerate(runs)]}


# ============================================================================
# The sample
# ============================================================================

def test_prose_paragraphs_keep_text_as_written_and_drop_headings():
    text = ('# Chapter 1\n\n"DEAR SIR,\n\nShe said _no_,\nquite firmly.\n\n* * *\n\n'
            '42\n\nHe left.')
    # its own rule: a letter's salutation stays (the fingerprint's filter drops it)
    assert vpp.prose_paragraphs(text) == ['"DEAR SIR,', 'She said _no_, quite firmly.',
                                          'He left.']


def test_recorded_sample_is_found_again_in_the_corpus(voice_dir):
    voice = vpp.load_voice(voice_dir)
    sample = vpp.build_sample(voice.texts, windows=4)
    text = vpp.system_blocks(voice, sample)[0]['text']
    assert vpp.recorded_sample(text, voice.texts) == sample
    changed = {k: v.replace(sample.paragraphs[3].text, 'Something else entirely.')
               for k, v in voice.texts.items()}
    with pytest.raises(vpp.ProposalError, match='corpus changed'):
        vpp.recorded_sample(text, changed)
    with pytest.raises(vpp.ProposalError, match="isn't in the corpus"):
        vpp.recorded_sample(text, {'other.md': 'x'})
    with pytest.raises(vpp.ProposalError, match='no sample'):
        vpp.recorded_sample('nothing here', voice.texts)


def test_sample_is_evenly_spaced_numbered_and_within_pieces():
    a = '\n\n'.join(f'Para {i} of the first book, with some words to count here.'
                    for i in range(1500))
    b = '\n\n'.join(f'Para {i} of the second book, with some words to count here.'
                    for i in range(1500))
    s = vpp.build_sample({'a.md': a, 'b.md': b}, windows=4, size=1000)
    assert s.windows == 4
    assert [p.number for p in s.paragraphs] == list(range(1, len(s.paragraphs) + 1))
    by_window = {}
    for p in s.paragraphs:
        by_window.setdefault(p.window, set()).add(p.source)
    assert all(len(v) == 1 for v in by_window.values())     # no run crosses pieces
    assert {p.source for p in s.paragraphs} == {'a.md', 'b.md'}
    firsts = [next(p.index for p in s.paragraphs if p.window == w) for w in range(1, 5)]
    assert firsts[0] > 1                                      # centred, not the start


def test_sample_takes_every_run_of_a_small_corpus():
    text = '\n\n'.join('A sentence of about ten words is written here now.' for _ in range(500))
    s = vpp.build_sample({'a.md': text}, windows=15)
    assert s.windows == len(vpp._runs(vpp.prose_paragraphs(text), vp.CHUNK_WORDS))


def test_sample_of_no_prose_is_an_error():
    with pytest.raises(vpp.ProposalError, match='no prose'):
        vpp.build_sample({'a.md': '# Heading\n\n* * *\n'})


def test_system_block_names_no_author_or_path_and_is_deterministic(voice_dir):
    voice = vpp.load_voice(voice_dir)
    sample = vpp.build_sample(voice.texts)
    blocks = vpp.system_blocks(voice, sample)
    assert blocks == vpp.system_blocks(vpp.load_voice(voice_dir), sample)
    text = blocks[0]['text']
    assert 'Test Author' not in text and voice_dir not in text
    assert 'cache_control' not in blocks[0]
    assert '[1, ' in text and '# The fingerprint' in text
    assert 'semicolon_rate' in text


# ============================================================================
# The voice repo
# ============================================================================

def test_load_voice_refuses_a_book_a_missing_fingerprint_and_a_missing_piece(voice_dir, tmp_path):
    with open(os.path.join(voice_dir, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  title: x\n')
    with pytest.raises(vpp.ProposalError, match='is a book'):
        vpp.load_voice(voice_dir)
    os.remove(os.path.join(voice_dir, 'storyforge.yaml'))
    os.remove(os.path.join(voice_dir, 'corpus', 'persuasion.md'))
    with pytest.raises(vpp.ProposalError, match='corpus/persuasion.md'):
        vpp.load_voice(voice_dir)
    os.remove(os.path.join(voice_dir, 'fingerprint.json'))
    with pytest.raises(vpp.ProposalError, match='no fingerprint.json'):
        vpp.load_voice(voice_dir)
    with pytest.raises(vpp.ProposalError, match='no voice.yaml'):
        vpp.load_voice(str(tmp_path))


# ============================================================================
# Parsing
# ============================================================================

def test_parse_claims_numbers_by_section_and_names_problems():
    reply = dict(GOOD_CLAIMS)
    reply['claims'] = GOOD_CLAIMS['claims'] + [{'section': 'does', 'claim': '  ', 'example': ''},
                                               {'section': 'tone', 'claim': 'x', 'example': ''}]
    claims, problems = vpp.parse_claims(json.dumps(reply), SAMPLE)
    assert [(c.id, c.section) for c in claims] == [
        ('c01', 'does'), ('c02', 'does'), ('c03', 'never'), ('c04', 'stance'),
        ('c05', 'humour'), ('c06', 'rhythm')]
    assert claims[1].claim == 'Generalises freely.'
    assert 'empty' in problems[0] and 'no known section' in problems[1]
    # SF-3: every section is short of what was asked; the example is in the sample
    assert '`does` has 2 claims; 6 to 10 were asked for' in problems[2]
    assert len(problems) == 2 + len(vpp.SECTIONS)
    assert not claims[2].positive and claims[0].positive


def test_parse_claims_names_an_empty_section_and_refuses_bad_replies():
    claims, problems = vpp.parse_claims(json.dumps(
        {'claims': [{'section': 'does', 'claim': 'x', 'example': ''}]}), SAMPLE)
    assert [p for p in problems if 'never' in p]
    for bad in ('not json', '[]', '{"claims": 3}', '{"claims": []}'):
        with pytest.raises(vpp.ProposalError):
            vpp.parse_claims(bad, SAMPLE)


def test_parse_shortlist_cuts_text_and_refuses_bad_runs(voice_dir):
    voice = vpp.load_voice(voice_dir)
    sample = vpp.build_sample(voice.texts)
    (a, b), (c, d) = _runs_of(sample)[:2]
    w1_last = max(p.number for p in sample.paragraphs if p.window == 1)
    n = len(sample.paragraphs)
    reply = {'passages': [
        {'first': a, 'last': b, 'job': 'humour', 'why': 'good'},
        {'first': a, 'last': b, 'job': 'quiet', 'why': 'overlap'},
        {'first': d, 'last': c - 1, 'job': 'quiet', 'why': 'backwards'},
        {'first': w1_last, 'last': w1_last + 1, 'job': 'quiet', 'why': 'crosses'},
        {'first': n, 'last': n + 5, 'job': 'quiet', 'why': 'outside'},
        {'first': c, 'last': c, 'job': 'quiet', 'why': 'short'},
        {'first': c, 'last': d, 'job': 'singing', 'why': 'job'},
        {'first': 'x', 'last': d, 'job': 'quiet', 'why': 'numbers'},
        {'first': True, 'last': d, 'job': 'quiet', 'why': 'a bool is no number'},
        'a string',
    ]}
    assert c > 1
    passages, refused = vpp.parse_shortlist(json.dumps(reply), sample)
    assert [p.id for p in passages] == [
        f'persuasion-{sample.get(a).index}-{sample.get(b).index}']
    p = passages[0]
    assert p.text == '\n\n'.join(sample.get(i).text for i in range(a, b + 1))
    assert p.paragraphs == f'{sample.get(a).index}-{sample.get(b).index}'
    assert p.source == 'corpus/persuasion.md' and p.why == 'good'
    assert len(refused) == 9
    joined = ' '.join(refused)
    for word in ('overlaps', 'ends before it starts', 'outside the sample', 'crosses',
                 'words, not', 'unknown job', 'no paragraph numbers', 'not an object'):
        assert word in joined, word
    with pytest.raises(vpp.ProposalError):
        vpp.parse_shortlist('{"x": 1}', sample)


# ============================================================================
# The typical range and the picking rule
# ============================================================================

def test_band_of():
    assert vpp.band_of(50) == 100 and vpp.band_of(149) == 100 and vpp.band_of(150) == 150
    assert vpp.band_of(299) == 200 and vpp.band_of(400) == 300


def test_passage_range_is_deterministic_and_judges(voice_dir):
    voice = vpp.load_voice(voice_dir)
    r1 = vpp.passage_range(voice.fingerprint, voice.texts)
    r2 = vpp.passage_range(voice.fingerprint, voice.texts)
    assert r1.limits == r2.limits and set(r1.limits) == set(vpp.PASSAGE_BANDS)
    assert all(n >= vpp.RANGE_MIN_WINDOWS for n in r1.counts.values())
    sample = vpp.build_sample(voice.texts)
    passages, _ = vpp.parse_shortlist(json.dumps(_shortlist_reply(sample, 3)), sample)
    judged = r1.judge(passages[0])
    assert judged.limit == round(r1.limit(judged.words), 4)
    assert judged.typical == (r1.distance(judged.text) <= r1.limit(judged.words))


def test_passage_range_refuses_a_corpus_too_small(voice_dir):
    voice = vpp.load_voice(voice_dir)
    with pytest.raises(vpp.ProposalError, match='too few passages of any length'):
        vpp.passage_range(voice.fingerprint, {'x': _head(600)})


def _long_paragraphs(text, size=210):
    """`text`'s paragraphs merged into paragraphs of at least `size` words."""
    out, cur = [], []
    for para in vpp.prose_paragraphs(text):
        cur.append(para)
        if len(vp.words(' '.join(cur))) >= size:
            out.append(' '.join(cur))
            cur = []
    return '\n\n'.join(out) + '\n'


def test_passage_range_leaves_a_thin_band_unjudged(voice_dir):
    """CR-1/SF-1: a corpus of long paragraphs has no run of 100-149 words.
    That band gets no limit and a passage in it isn't judged; it doesn't
    stop the range."""
    voice = vpp.load_voice(voice_dir)
    rng = vpp.passage_range(voice.fingerprint, {'x': _long_paragraphs(_head(24000))})
    assert 100 in rng.thin and rng.counts[100] < vpp.RANGE_MIN_WINDOWS
    assert 200 in rng.limits
    assert '100-149 words' in rng.thin_warning()
    p = vpp.Passage('x-1-1', 'quiet', 'x', '1-1', 120, _head(130))
    assert rng.judge(p).typical is None and rng.judge(p).distance is None
    assert rng.limit(120) is None


def _p(pid, typical, distance=0.5, limit=0.8, job='quiet'):
    if typical is None:
        distance = limit = None
    return vpp.Passage(pid, job, 'c.md', '1-2', 150, 'text', '', distance, limit, typical)


def test_auto_picks_takes_the_typical_and_tops_up_by_nearness():
    ps = [_p(f's{i:02d}', i % 2 == 0, distance=0.8 + i / 100) for i in range(1, 31)]
    typical = [p.id for p in ps if p.typical]
    assert len(typical) == 15
    picks = vpp.auto_picks(ps)
    assert len(picks) == 20 and set(typical) <= set(picks)
    extra = [x for x in picks if x not in typical]
    assert extra == ['s01', 's03', 's05', 's07', 's09']        # the nearest of the rest
    assert picks == [p.id for p in ps if p.id in set(picks)]     # shortlist order
    many = [_p(f's{i:02d}', True) for i in range(1, 26)]
    assert len(vpp.auto_picks(many)) == 25
    with pytest.raises(vpp.ProposalError, match='judged'):
        vpp.auto_picks([_p('s01', None)])


# ============================================================================
# Files and accepting
# ============================================================================

def test_claims_round_trip_with_a_pipe_and_a_newline(voice_dir):
    claims, _ = vpp.parse_claims(json.dumps(GOOD_CLAIMS), SAMPLE)
    vpp.write_claims(voice_dir, claims)
    back = vpp.read_claims(voice_dir)
    assert [c.claim for c in back][-1] == 'Long sentences / then short.'
    assert [c.id for c in back] == [c.id for c in claims]
    with open(os.path.join(voice_dir, vpp.CLAIMS_FILE), 'rb') as f:
        assert b'\r' not in f.read()


@pytest.mark.parametrize('content,match', [
    ('id|claim\n', 'header'),
    ('id|section|claim|example|mark\nc01|does|a|b\n', 'cells'),
    ('id|section|claim|example|mark\nc01|does|a||\nc01|does|b||\n', 'repeated id'),
    ('id|section|claim|example|mark\nc01|tone|a||\n', 'section'),
])
def test_read_claims_refuses_a_broken_file(voice_dir, content, match):
    path = os.path.join(voice_dir, vpp.CLAIMS_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    with pytest.raises(vpp.ProposalError, match=match):
        vpp.read_claims(voice_dir)


def test_read_claims_of_a_missing_file(voice_dir):
    with pytest.raises(vpp.ProposalError, match="doesn't exist"):
        vpp.read_claims(voice_dir)


def _marked(voice_dir, marks):
    claims, _ = vpp.parse_claims(json.dumps(GOOD_CLAIMS), SAMPLE)
    vpp.write_claims(voice_dir, [vpp.Claim(c.id, c.section, c.claim, c.example, m)
                                 for c, m in zip(claims, marks)])


def test_accept_description_refuses_unmarked_and_bad_marks(voice_dir):
    out = os.path.join(voice_dir, vpp.DESCRIPTION_FILE)
    _marked(voice_dir, ['yes', '', 'maybe', 'no', 'yes', 'yes'])
    with pytest.raises(vpp.ProposalError) as e:
        vpp.accept_description(voice_dir)
    assert 'unmarked: c02' in str(e.value) and "c03 ('maybe')" in str(e.value)
    assert not os.path.exists(out)
    _marked(voice_dir, ['no'] * 6)
    with pytest.raises(vpp.ProposalError, match='no claim is marked yes'):
        vpp.accept_description(voice_dir)
    assert not os.path.exists(out)


def test_accept_description_writes_the_kept_claims_by_section(voice_dir):
    _marked(voice_dir, ['yes', 'YES', 'no', 'yes', 'no', 'yes'])
    done = vpp.accept_description(voice_dir)
    assert (done.kept, done.total) == (4, 6)
    with open(done.path, encoding='utf-8') as f:
        text = f.read()
    assert text.startswith('# The described voice: Test Author\n')
    assert '## What the voice does\n\n- Uses irony.\n- Generalises freely.' in text
    assert 'What it never does' not in text and 'Its humour' not in text
    assert text.index('Its stance') < text.index('Its rhythm')


def _shortlisted(voice_dir, k=24, judge=True):
    voice = vpp.load_voice(voice_dir)
    sample = vpp.build_sample(voice.texts)
    passages, refused = vpp.parse_shortlist(json.dumps(_shortlist_reply(sample, k)), sample)
    assert not refused
    if judge:
        rng = vpp.passage_range(voice.fingerprint, voice.texts)
        passages = [rng.judge(p) for p in passages]
    vpp.write_shortlist(voice_dir, passages)
    return passages


def test_shortlist_round_trip_and_stale_passage_files_go(voice_dir):
    passages = _shortlisted(voice_dir, k=22)
    back = vpp.read_shortlist(voice_dir)
    assert [(p.id, p.text, p.words, p.typical, p.distance) for p in back] == [
        (p.id, p.text, p.words, p.typical, p.distance) for p in passages]
    twenty = _shortlisted(voice_dir, k=20)
    files = sorted(os.listdir(os.path.join(voice_dir, vpp.SHORTLIST_DIR)))
    assert files == sorted(f'{p.id}.md' for p in twenty)


def test_accept_exemplars_copies_the_picks_and_counts_trimmed_words(voice_dir):
    passages = _shortlisted(voice_dir, k=24)
    ids = [p.id for p in passages[:21]]
    vpp.set_picks(voice_dir, ids)
    trimmed = os.path.join(voice_dir, vpp.SHORTLIST_DIR, f'{ids[0]}.md')
    with open(trimmed, encoding='utf-8') as f:
        words = f.read().split()
    with open(trimmed, 'w', encoding='utf-8') as f:
        f.write(' '.join(words[:110]) + '\n')
    done = vpp.accept_exemplars(voice_dir)
    assert done.kept == 21 and done.total == 24
    index = vpp._read_rows(os.path.join(voice_dir, vpp.EXEMPLARS_INDEX), vpp.EXEMPLAR_COLUMNS)
    assert [r['id'] for r in index] == ids
    assert index[0]['words'] == str(len(vp.words(' '.join(words[:110]))))
    with open(os.path.join(voice_dir, vpp.EXEMPLARS_DIR, f'{ids[0]}.md'),
              encoding='utf-8') as f:
        assert f.read().split() == words[:110]
    assert not done.notes


def test_accept_exemplars_refuses_bad_picks_and_lengths(voice_dir):
    passages = _shortlisted(voice_dir, k=22)
    with pytest.raises(vpp.ProposalError, match='no passage has'):
        vpp.accept_exemplars(voice_dir)
    vpp.set_picks(voice_dir, [passages[0].id])
    with open(os.path.join(voice_dir, vpp.SHORTLIST_DIR, f'{passages[0].id}.md'), 'w') as f:
        f.write('Too short now.\n')
    with pytest.raises(vpp.ProposalError, match=passages[0].id):
        vpp.accept_exemplars(voice_dir)
    path = os.path.join(voice_dir, vpp.SHORTLIST_FILE)
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('|yes\n', '|keep\n'))
    with pytest.raises(vpp.ProposalError, match="'keep'"):
        vpp.accept_exemplars(voice_dir)
    assert not os.path.exists(os.path.join(voice_dir, vpp.EXEMPLARS_DIR))


def test_accept_exemplars_replaces_its_own_files_and_notes_others(voice_dir):
    passages = _shortlisted(voice_dir, k=22)
    vpp.set_picks(voice_dir, [p.id for p in passages[:3]])
    done = vpp.accept_exemplars(voice_dir)
    assert any('WARNING: the bank holds 3 exemplars' in n for n in done.notes)
    assert any('no exemplar for the job(s)' in n for n in done.notes)
    hand = os.path.join(voice_dir, vpp.EXEMPLARS_DIR, 'mine.md')
    with open(hand, 'w') as f:
        f.write('My own.\n')
    vpp.set_picks(voice_dir, [p.id for p in passages[1:22]])
    done = vpp.accept_exemplars(voice_dir)
    folder = os.path.join(voice_dir, vpp.EXEMPLARS_DIR)
    assert not os.path.exists(os.path.join(folder, f'{passages[0].id}.md'))
    assert os.path.exists(hand)
    assert any('mine.md' in n for n in done.notes)
    assert not any('WARNING' in n for n in done.notes)


# ============================================================================
# The calls and the command
# ============================================================================

@pytest.fixture
def fake_api(monkeypatch):
    """Answers the description and shortlist calls; records each call."""
    import storyforge.api as api
    calls = []
    state = {'shortlist': None, 'description': GOOD_CLAIMS}

    def invoke(prompt, model, max_tokens=4096, label='', timeout=0, system=None,
               output_schema=None, fallback=False):
        calls.append({'prompt': prompt, 'model': model, 'label': label, 'system': system,
                      'schema': output_schema, 'max_tokens': max_tokens})
        if output_schema is vpp.CLAIMS_SCHEMA:
            return _reply(state['description'])
        return _reply(state['shortlist'])

    monkeypatch.setattr(api, 'invoke', invoke)
    return calls, state


def test_propose_calls_send_the_prompts_and_save_the_reply(voice_dir, fake_api, tmp_path):
    calls, state = fake_api
    voice = vpp.load_voice(voice_dir)
    sample = vpp.build_sample(voice.texts)
    system = vpp.system_blocks(voice, sample)
    reply_file = str(tmp_path / 'r' / 'description.json')
    claims, _ = vpp.propose_description(system, sample, 'claude-opus-5-5', reply_file)
    assert len(claims) == 6 and os.path.isfile(reply_file)
    assert calls[0]['prompt'] == vpp.DESCRIPTION_PROMPT and calls[0]['system'] == system
    state['shortlist'] = _shortlist_reply(sample, 21)
    passages, refused = vpp.propose_shortlist(system, sample, 'claude-opus-5-5')
    assert len(passages) == 21 and not refused
    assert '30 exemplar passages' in calls[1]['prompt']


def test_propose_refuses_a_cut_off_reply(voice_dir, monkeypatch, tmp_path):
    import storyforge.api as api
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: {
        'content': [{'type': 'text', 'text': '{"claims": ['}], 'stop_reason': 'max_tokens'})
    voice = vpp.load_voice(voice_dir)
    sample = vpp.build_sample(voice.texts)
    system = vpp.system_blocks(voice, sample)
    reply_file = str(tmp_path / 'd.json')
    with pytest.raises(vpp.ProposalError, match='cut off'):
        vpp.propose_description(system, sample, 'claude-opus-5-5', reply_file)
    assert os.path.isfile(reply_file)          # the paid reply is kept


def test_forecast_counts_each_call_in_full(voice_dir):
    voice = vpp.load_voice(voice_dir)
    system = vpp.system_blocks(voice, vpp.build_sample(voice.texts))
    one = vpp.forecast(system, 'claude-opus-5-5', ['description'])
    both = vpp.forecast(system, 'claude-opus-5-5')
    assert 0 < one < both
    assert both - one > one * 0.8       # the second call pays for the sample again


def test_cmd_propose_writes_both_and_guards_the_authors_marks(voice_dir, fake_api):
    from storyforge import cmd_voice
    calls, state = fake_api
    voice = vpp.load_voice(voice_dir)
    state['shortlist'] = _shortlist_reply(vpp.build_sample(voice.texts), 22)
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5']) == 0
    assert len(calls) == 2
    assert len(vpp.read_claims(voice_dir)) == 6
    shortlist = vpp.read_shortlist(voice_dir)
    assert len(shortlist) == 22 and all(p.typical is not None for p in shortlist)
    assert os.path.isfile(os.path.join(voice_dir, vpp.REPLIES_DIR, 'shortlist.json'))
    # the author marks a claim: a second propose won't throw it away
    claims = vpp.read_claims(voice_dir)
    vpp.write_claims(voice_dir, [vpp.Claim(c.id, c.section, c.claim, c.example, 'yes')
                                 for c in claims])
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--only', 'description']) == 1
    assert len(calls) == 2
    # the shortlist alone may still be proposed again
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--only', 'shortlist']) == 0
    assert len(calls) == 3
    assert all(c.mark == 'yes' for c in vpp.read_claims(voice_dir))
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--only', 'description', '--force']) == 0
    assert all(c.mark == '' for c in vpp.read_claims(voice_dir))


def test_cmd_propose_short_shortlist_is_an_error_after_writing(voice_dir, fake_api):
    from storyforge import cmd_voice
    calls, state = fake_api
    voice = vpp.load_voice(voice_dir)
    state['shortlist'] = _shortlist_reply(vpp.build_sample(voice.texts), 5)
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--only', 'shortlist']) == 1
    assert len(vpp.read_shortlist(voice_dir)) == 5


def test_cmd_propose_dry_run_and_threshold_make_no_call(voice_dir, fake_api, monkeypatch, capsys):
    from storyforge import cmd_voice
    calls, _ = fake_api
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--dry-run']) == 0
    assert 'Forecast: $' in capsys.readouterr().out
    monkeypatch.setenv('STORYFORGE_COST_THRESHOLD', '0.01')
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5']) == 1
    assert 'over the cost threshold' in capsys.readouterr().out
    assert calls == []
    assert not os.path.exists(os.path.join(voice_dir, vpp.PROPOSALS_DIR))


def test_cmd_refuses_a_book(voice_dir, fake_api, capsys):
    from storyforge import cmd_voice
    with open(os.path.join(voice_dir, 'storyforge.yaml'), 'w') as f:
        f.write('project:\n  title: x\n')
    assert cmd_voice.main(['accept', '--dir', voice_dir]) == 1
    assert 'is a book' in capsys.readouterr().out


def test_cmd_accept_auto_pick(voice_dir, capsys):
    from storyforge import cmd_voice
    passages = _shortlisted(voice_dir, k=24)
    _marked(voice_dir, ['yes'] * 6)
    assert cmd_voice.main(['accept', '--dir', voice_dir, '--auto-pick']) == 0
    picks = vpp.auto_picks(passages)
    assert [p.id for p in vpp.read_shortlist(voice_dir) if p.pick == 'yes'] == picks
    index = vpp._read_rows(os.path.join(voice_dir, vpp.EXEMPLARS_INDEX), vpp.EXEMPLAR_COLUMNS)
    assert [r['id'] for r in index] == picks
    assert os.path.isfile(os.path.join(voice_dir, vpp.DESCRIPTION_FILE))


def test_cmd_accept_reports_each_failure(voice_dir, capsys):
    from storyforge import cmd_voice
    _marked(voice_dir, [''] * 6)
    assert cmd_voice.main(['accept', '--dir', voice_dir]) == 1
    out = capsys.readouterr().out
    assert 'unmarked' in out and "shortlist.csv doesn't exist" in out


def test_rejudge_rewrites_the_figures_and_keeps_picks(voice_dir, capsys):
    from storyforge import cmd_voice
    passages = _shortlisted(voice_dir, k=21, judge=False)
    vpp.set_picks(voice_dir, [passages[0].id])
    assert all(p.typical is None for p in vpp.read_shortlist(voice_dir))
    with pytest.raises(vpp.ProposalError, match='judged'):
        vpp.auto_picks(vpp.read_shortlist(voice_dir))
    assert cmd_voice.main(['judge', '--dir', voice_dir]) == 0
    back = vpp.read_shortlist(voice_dir)
    assert all(p.typical is not None and p.limit for p in back)
    assert [p.pick for p in back][:2] == ['yes', '']
    assert 'inside the fingerprint' in capsys.readouterr().out


def test_voice_is_a_registered_command():
    from storyforge.__main__ import COMMANDS
    assert COMMANDS['voice'] == 'storyforge.cmd_voice'


# ============================================================================
# Review fixes (#665): paying before failing, failed calls, the bank
# ============================================================================

def test_cmd_propose_fails_before_paying_when_no_band_has_a_range(voice_dir, fake_api,
                                                                   monkeypatch, capsys):
    """CR-1/SF-1: the typical range is measured before the paid calls."""
    from storyforge import cmd_voice
    calls, _ = fake_api

    def no_range(fp, texts, baseline=None):
        raise vpp.ProposalError('the corpus gives too few passages of any length')
    monkeypatch.setattr(vpp, 'passage_range', no_range)
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--dry-run']) == 1
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5']) == 1
    assert calls == [] and 'too few passages' in capsys.readouterr().out
    # the description alone needs no range
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--only', 'description']) == 0
    assert len(calls) == 1


def test_cmd_propose_warns_of_a_thin_band_before_paying(voice_dir, fake_api, monkeypatch,
                                                        capsys):
    from storyforge import cmd_voice
    real = vpp.passage_range

    def thin(fp, texts, baseline=None):
        r = real(fp, texts, baseline)
        return vpp.PassageRange(r.fingerprint, {b: v for b, v in r.limits.items() if b != 100},
                                {**r.counts, 100: 3}, r.baseline)
    monkeypatch.setattr(vpp, 'passage_range', thin)
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--dry-run']) == 0
    assert '100-149 words (3)' in capsys.readouterr().out


@pytest.mark.parametrize('failure', ['refusal', 'http'])
def test_cmd_propose_reports_a_failed_call_and_the_spend(voice_dir, fake_api, monkeypatch,
                                                         capsys, failure):
    """SF-2/CR-4/T6: the shortlist call refused or failed after the claims
    were written: exit 1, no traceback, what was written, the spend."""
    import storyforge.api as api
    from storyforge import cmd_voice
    calls, state = fake_api
    answer = api.invoke

    def invoke(prompt, model, **kw):
        if kw.get('output_schema') is vpp.SHORTLIST_SCHEMA:
            if failure == 'refusal':
                raise api.RefusalError({'stop_reason': 'refusal', 'content': [],
                                        'stop_details': {'category': 'cyber'}})
            raise RuntimeError('API returned HTTP 529: overloaded')
        return answer(prompt, model, **kw)
    monkeypatch.setattr(api, 'invoke', invoke)
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5']) == 1
    out = capsys.readouterr().out
    assert 'ERROR: the shortlist call failed' in out
    assert 'Not written (left as they were): proposals/shortlist.csv' in out
    assert 'Spent $' in out
    assert len(vpp.read_claims(voice_dir)) == 6
    saved = os.path.join(voice_dir, vpp.REPLIES_DIR, 'shortlist.json')
    assert os.path.isfile(saved) == (failure == 'refusal')


def test_cmd_propose_names_a_shortlist_too_long_or_short_of_the_ask(voice_dir, fake_api,
                                                                    capsys):
    """SF-5: a reply naming more than SHORTLIST_MAX is an ERROR like one under
    SHORTLIST_MIN; one naming fewer than asked is a WARNING."""
    from storyforge import cmd_voice
    calls, state = fake_api
    sample = vpp.build_sample(vpp.load_voice(voice_dir).texts)
    state['shortlist'] = _shortlist_reply(sample, 24)
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--only', 'shortlist']) == 0
    assert 'asked for 30 passages; the reply named 24' in capsys.readouterr().out
    many = _runs_of(sample)
    assert len(many) > vpp.SHORTLIST_MAX
    state['shortlist'] = {'passages': [{'first': a, 'last': b, 'job': 'quiet', 'why': ''}
                                       for a, b in many[:vpp.SHORTLIST_MAX + 1]]}
    assert cmd_voice.main(['propose', '--dir', voice_dir, '--model', 'claude-opus-5-5',
                           '--only', 'shortlist', '--force']) == 1
    assert f'{vpp.SHORTLIST_MAX + 1} usable passages' in capsys.readouterr().out


def test_accept_exemplars_keeps_an_exemplar_the_author_added(voice_dir):
    """TD1: an index row accept didn't write survives an accept."""
    passages = _shortlisted(voice_dir, k=22)
    folder = os.path.join(voice_dir, vpp.EXEMPLARS_DIR)
    os.makedirs(folder)
    with open(os.path.join(folder, 'mine.md'), 'w') as f:
        f.write('My own passage.\n')
    with open(os.path.join(voice_dir, vpp.EXEMPLARS_INDEX), 'w') as f:
        f.write('id|job|source|paragraphs|words|why\nmine|quiet|corpus/x.md|1-2|200|mine\n')
    done = vpp.accept_exemplars(voice_dir, [p.id for p in passages[:21]])
    index = vpp._read_rows(os.path.join(voice_dir, vpp.EXEMPLARS_INDEX), vpp.EXEMPLAR_COLUMNS)
    assert index[0] == {'id': 'mine', 'job': 'quiet', 'source': 'corpus/x.md',
                        'paragraphs': '1-2', 'words': '200', 'why': 'mine'}
    assert [r['id'] for r in index[1:]] == [p.id for p in passages[:21]]
    assert os.path.isfile(os.path.join(folder, 'mine.md'))
    assert any('kept 1 exemplar' in n for n in done.notes)
    # unpicking a shortlisted passage takes it out; the author's row stays
    vpp.accept_exemplars(voice_dir, [p.id for p in passages[1:21]])
    index = vpp._read_rows(os.path.join(voice_dir, vpp.EXEMPLARS_INDEX), vpp.EXEMPLAR_COLUMNS)
    assert index[0]['id'] == 'mine' and passages[0].id not in {r['id'] for r in index}
    assert not os.path.exists(os.path.join(folder, f'{passages[0].id}.md'))


def test_accept_exemplars_refuses_to_overwrite_a_file_the_index_doesnt_name(voice_dir):
    """TD2: a picked id whose file is already in exemplars/, unindexed."""
    passages = _shortlisted(voice_dir, k=22)
    folder = os.path.join(voice_dir, vpp.EXEMPLARS_DIR)
    os.makedirs(folder)
    theirs = os.path.join(folder, f'{passages[0].id}.md')
    with open(theirs, 'w') as f:
        f.write('Written by hand.\n')
    with pytest.raises(vpp.ProposalError, match='index doesn.t name'):
        vpp.accept_exemplars(voice_dir, [p.id for p in passages[:21]])
    with open(theirs) as f:
        assert f.read() == 'Written by hand.\n'
    assert not os.path.exists(os.path.join(voice_dir, vpp.EXEMPLARS_INDEX))
    assert not any(p.pick for p in vpp.read_shortlist(voice_dir))   # picks not written


def test_accept_exemplars_with_picks_writes_the_column_only_on_success(voice_dir):
    """CR-5/SF-8: a refused accept leaves the author's picks as they were."""
    passages = _shortlisted(voice_dir, k=22)
    vpp.set_picks(voice_dir, [passages[0].id])
    with open(os.path.join(voice_dir, vpp.SHORTLIST_DIR, f'{passages[1].id}.md'), 'w') as f:
        f.write('Too short now.\n')
    with pytest.raises(vpp.ProposalError, match='Nothing written'):
        vpp.accept_exemplars(voice_dir, [p.id for p in passages[:3]])
    assert [p.id for p in vpp.read_shortlist(voice_dir) if p.pick] == [passages[0].id]
    with pytest.raises(vpp.ProposalError, match='holds no passage nope'):
        vpp.accept_exemplars(voice_dir, ['nope'])


def test_cmd_accept_auto_pick_guards_the_authors_picks(voice_dir, capsys):
    """T7: --auto-pick won't replace picks without --force, and means nothing
    with --only description."""
    from storyforge import cmd_voice
    passages = _shortlisted(voice_dir, k=24)
    vpp.set_picks(voice_dir, [passages[0].id])
    assert cmd_voice.main(['accept', '--dir', voice_dir, '--only', 'exemplars',
                           '--auto-pick']) == 1
    assert 'already holds picks' in capsys.readouterr().out
    assert [p.id for p in vpp.read_shortlist(voice_dir) if p.pick] == [passages[0].id]
    assert cmd_voice.main(['accept', '--dir', voice_dir, '--only', 'exemplars',
                           '--auto-pick', '--force']) == 0
    assert [p.id for p in vpp.read_shortlist(voice_dir) if p.pick] == vpp.auto_picks(passages)
    assert cmd_voice.main(['accept', '--dir', voice_dir, '--only', 'description',
                           '--auto-pick']) == 1
    assert 'does nothing with --only description' in capsys.readouterr().out


def test_writes_go_through_a_temporary_file(voice_dir, monkeypatch):
    """SF-9: an interrupted write leaves the old file whole and no temp file."""
    path = os.path.join(voice_dir, 'description.md')
    vpp._write_text(path, 'old\n')

    def boom(src, dst):
        raise OSError('disk full')
    monkeypatch.setattr(vpp.os, 'replace', boom)
    with pytest.raises(OSError):
        vpp._write_text(path, 'new\n')
    with open(path) as f:
        assert f.read() == 'old\n'
    assert not os.path.exists(path + '.tmp')


# ============================================================================
# Review fixes (#665): the types and their files
# ============================================================================

def test_passage_id_is_where_the_passage_is():
    """TD5: an id names the same prose after another proposal."""
    assert vpp.passage_id('corpus/pride-and-prejudice.md', '67-68') == 'pride-and-prejudice-67-68'
    assert vpp.passage_id('posts/2024/On Writing.md', '3-5') == 'posts-2024-on-writing-3-5'


def test_parse_shortlist_refuses_two_passages_with_one_id():
    text = ' '.join(['word'] * 150)
    sample = vpp.Sample((vpp.Paragraph(1, 'corpus/a-b.md', 1, 1, text, 150),
                         vpp.Paragraph(2, 'corpus/a b.md', 1, 2, text, 150)), 2)
    reply = {'passages': [{'first': 1, 'last': 1, 'job': 'quiet', 'why': ''},
                          {'first': 2, 'last': 2, 'job': 'quiet', 'why': ''}]}
    passages, refused = vpp.parse_shortlist(json.dumps(reply), sample)
    assert [p.id for p in passages] == ['a-b-1-1'] and "another passage's" in refused[0]


def test_passage_judgement_is_all_or_nothing():
    """TD4."""
    with pytest.raises(ValueError):
        vpp.Passage('x', 'quiet', 'c.md', '1-2', 150, 't', '', 0.5, None, True)


@pytest.mark.parametrize('edit,match', [
    (lambda row: row[:7] + ['maybe'] + row[8:], "typical 'maybe'"),       # SF-6
    (lambda row: row[:5] + [''] + row[6:], 'some of distance'),            # TD4
    (lambda row: row[:4] + ['many'] + row[5:], "words, distance or limit"),
])
def test_read_shortlist_refuses_a_broken_judgement(voice_dir, edit, match):
    _shortlisted(voice_dir, k=21)
    path = os.path.join(voice_dir, vpp.SHORTLIST_FILE)
    with open(path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    lines[1] = '|'.join(edit(lines[1].split('|')))
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    with pytest.raises(vpp.ProposalError, match=match):
        vpp.read_shortlist(voice_dir)


def test_a_trimmed_passage_is_read_unjudged_until_judged_again(voice_dir):
    """TD3: its figures were measured on the text before the trim."""
    passages = _shortlisted(voice_dir, k=21)
    path = os.path.join(voice_dir, vpp.SHORTLIST_DIR, f'{passages[0].id}.md')
    with open(path, encoding='utf-8') as f:
        words = f.read().split()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(' '.join(words[:105]) + '\n')
    back = vpp.read_shortlist(voice_dir)
    assert back[0].typical is None and back[0].distance is None
    assert all(p.typical is not None for p in back[1:])
    with pytest.raises(vpp.ProposalError, match=f'not judged: {passages[0].id}'):
        vpp.auto_picks(back)
    _, judged = vpp.rejudge(voice_dir)
    assert judged[0].typical is not None and judged[0].words == len(vp.words(' '.join(words[:105])))
    assert vpp.read_shortlist(voice_dir)[0].typical is not None


def test_parse_replies_dont_turn_nulls_into_text():
    """T5: a null claim is empty, not the claim "None"; a null example is
    named and left out."""
    reply = {'claims': [{'section': 'does', 'claim': None, 'example': ''},
                        {'section': 'does', 'claim': 'Real.', 'example': None},
                        {'section': 'never', 'claim': 'Never.', 'example': ''}]}
    claims, problems = vpp.parse_claims(json.dumps(reply), SAMPLE)
    assert [c.claim for c in claims] == ['Real.', 'Never.'] and claims[0].example == ''
    assert any('claim 1 (does) is empty' in p for p in problems)
    assert any("example that isn't text" in p for p in problems)


def test_description_provenance_is_a_comment_the_reader_leaves_out(voice_dir):
    """TD8/C1: description.md's provenance line is an HTML comment that
    claims no author, and read_description drops it."""
    _marked(voice_dir, ['yes'] * 6)
    vpp.accept_description(voice_dir)
    with open(os.path.join(voice_dir, vpp.DESCRIPTION_FILE), encoding='utf-8') as f:
        raw = f.read()
    assert '<!-- Written by `storyforge voice accept`' in raw and 'the author marked' not in raw
    text = vpp.read_description(voice_dir)
    assert 'storyforge voice accept' not in text and '<!--' not in text
    assert text.startswith('# The described voice: Test Author\n\n## What the voice does')
    os.remove(os.path.join(voice_dir, vpp.DESCRIPTION_FILE))
    with pytest.raises(vpp.ProposalError, match="doesn't exist"):
        vpp.read_description(voice_dir)


def test_load_exemplars_reads_the_bank_and_names_what_it_cant(voice_dir):
    """TD6: one reader of the bank for drafting (#652, #655)."""
    passages = _shortlisted(voice_dir, k=21)
    vpp.accept_exemplars(voice_dir, [p.id for p in passages])
    folder = os.path.join(voice_dir, vpp.EXEMPLARS_DIR)
    with open(os.path.join(folder, 'stray.md'), 'w') as f:
        f.write('x\n')
    bank = vpp.load_exemplars(voice_dir)
    assert [e.id for e in bank.exemplars] == [p.id for p in passages]
    first = bank.exemplars[0]
    assert (first.job, first.why, first.text) == (passages[0].job, passages[0].why,
                                                  passages[0].text.strip())
    assert bank.unlisted == ('stray.md',)
    os.remove(os.path.join(folder, f'{passages[1].id}.md'))
    with pytest.raises(vpp.ProposalError, match=passages[1].id):
        vpp.load_exemplars(voice_dir)


# ============================================================================
# Review fixes (#665): what a reply or an edit can't silently get past
# ============================================================================

def test_parse_claims_names_an_example_not_in_the_sample():
    """SF-4: an example the sample doesn't hold is kept but named. Curly
    quotes, a dash, an ellipsis and the quotation marks around an excerpt
    don't count as differences."""
    text = 'She said, "It was--I think--so," and left the room; nobody followed.'
    sample = vpp.Sample((vpp.Paragraph(1, 'c.md', 1, 1, text, 13),), 1)

    def problems_for(example):
        reply = {'claims': [{'section': s, 'claim': f'Claim {i}.', 'example': ''}
                            for s, (_, lo, _) in vpp.SECTION_ASK.items() for i in range(lo)]}
        reply['claims'][0]['example'] = example
        return vpp.parse_claims(json.dumps(reply), sample)[1]
    assert problems_for('\u201cIt was\u2014I think\u2014so,\u201d and left') == []
    assert problems_for('"It was--I think . . . so,"') != []
    assert problems_for('"It was...so," and left the room') == []
    found = problems_for('She said it was so and left.')
    assert len(found) == 1 and "c01's example isn't in the sample" in found[0]


def test_description_prompt_is_written_from_the_section_table():
    """SF-3: one table for the prompt's counts and the check."""
    for s, (what, lo, hi) in vpp.SECTION_ASK.items():
        assert f'- {s}: {what} ({lo} to {hi} claims)' in vpp.DESCRIPTION_PROMPT


def test_accept_exemplars_warns_of_a_passage_edited_beyond_a_trim(voice_dir):
    """SF-7: a trim is fine; a reworded passage's source and paragraphs no
    longer say where it's from."""
    passages = _shortlisted(voice_dir, k=21)
    folder = os.path.join(voice_dir, vpp.SHORTLIST_DIR)
    with open(os.path.join(folder, f'{passages[0].id}.md'), encoding='utf-8') as f:
        words = f.read().split()
    with open(os.path.join(folder, f'{passages[0].id}.md'), 'w', encoding='utf-8') as f:
        f.write(' '.join(words[1:-1]) + '\n')                  # trimmed at both ends
    with open(os.path.join(folder, f'{passages[1].id}.md'), 'w', encoding='utf-8') as f:
        f.write('Reworded entirely. ' * 60 + '\n')
    done = vpp.accept_exemplars(voice_dir, [p.id for p in passages])
    edited = [n for n in done.notes if 'edited, not only trimmed' in n]
    assert len(edited) == 1 and passages[1].id in edited[0]

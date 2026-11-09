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
    text = '# Chapter 1\n\nCHAPTER II.\n\nShe said _no_,\nquite firmly.\n\n* * *\n\nHe left.'
    assert vpp.prose_paragraphs(text) == ['She said _no_, quite firmly.', 'He left.']


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
    claims, problems = vpp.parse_claims(json.dumps(reply))
    assert [(c.id, c.section) for c in claims] == [
        ('c01', 'does'), ('c02', 'does'), ('c03', 'never'), ('c04', 'stance'),
        ('c05', 'humour'), ('c06', 'rhythm')]
    assert claims[1].claim == 'Generalises freely.'
    assert len(problems) == 2 and 'empty' in problems[0] and 'no known section' in problems[1]
    assert not claims[2].positive and claims[0].positive


def test_parse_claims_names_an_empty_section_and_refuses_bad_replies():
    claims, problems = vpp.parse_claims(json.dumps(
        {'claims': [{'section': 'does', 'claim': 'x', 'example': ''}]}))
    assert [p for p in problems if 'never' in p]
    for bad in ('not json', '[]', '{"claims": 3}', '{"claims": []}'):
        with pytest.raises(vpp.ProposalError):
            vpp.parse_claims(bad)


def test_parse_shortlist_cuts_text_and_refuses_bad_runs(voice_dir):
    voice = vpp.load_voice(voice_dir)
    sample = vpp.build_sample(voice.texts)
    (a, b), (c, d) = _runs_of(sample)[:2]
    w1_last = max(p.number for p in sample.paragraphs if p.window == 1)
    n = len(sample.paragraphs)
    reply = {'passages': [
        {'first': a, 'last': b, 'job': 'humour', 'why': 'good'},
        {'first': a, 'last': b, 'job': 'quiet', 'why': 'overlap'},
        {'first': b, 'last': a - 1 if a > 1 else 0, 'job': 'quiet', 'why': 'backwards'},
        {'first': w1_last, 'last': w1_last + 1, 'job': 'quiet', 'why': 'crosses'},
        {'first': n, 'last': n + 5, 'job': 'quiet', 'why': 'outside'},
        {'first': c, 'last': c, 'job': 'quiet', 'why': 'short'},
        {'first': c, 'last': d, 'job': 'singing', 'why': 'job'},
        {'first': 'x', 'last': d, 'job': 'quiet', 'why': 'numbers'},
    ]}
    passages, refused = vpp.parse_shortlist(json.dumps(reply), sample)
    assert [p.id for p in passages] == ['s01']
    p = passages[0]
    assert p.text == '\n\n'.join(sample.get(i).text for i in range(a, b + 1))
    assert p.paragraphs == f'{sample.get(a).index}-{sample.get(b).index}'
    assert p.source == 'corpus/persuasion.md' and p.why == 'good'
    assert len(refused) == 7
    joined = ' '.join(refused)
    for word in ('overlaps', 'outside the sample', 'crosses', 'words, not', 'unknown job',
                 'no paragraph numbers'):
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
    with pytest.raises(vpp.ProposalError, match='too few'):
        vpp.passage_range(voice.fingerprint, {'x': _head(3000)})


def _p(pid, typical, distance=0.5, limit=0.8, job='quiet'):
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
    claims, _ = vpp.parse_claims(json.dumps(GOOD_CLAIMS))
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
    claims, _ = vpp.parse_claims(json.dumps(GOOD_CLAIMS))
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
    _shortlisted(voice_dir, k=20)
    files = sorted(os.listdir(os.path.join(voice_dir, vpp.SHORTLIST_DIR)))
    assert files == [f's{i:02d}.md' for i in range(1, 21)]


def test_accept_exemplars_copies_the_picks_and_counts_trimmed_words(voice_dir):
    passages = _shortlisted(voice_dir, k=24)
    ids = [p.id for p in passages[:21]]
    vpp.set_picks(voice_dir, ids)
    trimmed = os.path.join(voice_dir, vpp.SHORTLIST_DIR, 's01.md')
    with open(trimmed, encoding='utf-8') as f:
        words = f.read().split()
    with open(trimmed, 'w', encoding='utf-8') as f:
        f.write(' '.join(words[:110]) + '\n')
    done = vpp.accept_exemplars(voice_dir)
    assert done.kept == 21 and done.total == 24
    index = vpp._read_rows(os.path.join(voice_dir, vpp.EXEMPLARS_INDEX), vpp.EXEMPLAR_COLUMNS)
    assert [r['id'] for r in index] == ids
    assert index[0]['words'] == str(len(vp.words(' '.join(words[:110]))))
    with open(os.path.join(voice_dir, vpp.EXEMPLARS_DIR, 's01.md'), encoding='utf-8') as f:
        assert f.read().split() == words[:110]
    assert not done.notes


def test_accept_exemplars_refuses_bad_picks_and_lengths(voice_dir):
    passages = _shortlisted(voice_dir, k=22)
    with pytest.raises(vpp.ProposalError, match='no passage has'):
        vpp.accept_exemplars(voice_dir)
    vpp.set_picks(voice_dir, [passages[0].id])
    with open(os.path.join(voice_dir, vpp.SHORTLIST_DIR, 's01.md'), 'w') as f:
        f.write('Too short now.\n')
    with pytest.raises(vpp.ProposalError, match='s01'):
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
    assert any('WARNING: 3 exemplars' in n for n in done.notes)
    assert any('no exemplar for the job(s)' in n for n in done.notes)
    hand = os.path.join(voice_dir, vpp.EXEMPLARS_DIR, 'mine.md')
    with open(hand, 'w') as f:
        f.write('My own.\n')
    vpp.set_picks(voice_dir, [p.id for p in passages[1:22]])
    done = vpp.accept_exemplars(voice_dir)
    folder = os.path.join(voice_dir, vpp.EXEMPLARS_DIR)
    assert not os.path.exists(os.path.join(folder, 's01.md'))
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
    claims, _ = vpp.propose_description(system, 'claude-opus-5-5', reply_file)
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
    system = vpp.system_blocks(voice, vpp.build_sample(voice.texts))
    reply_file = str(tmp_path / 'd.json')
    with pytest.raises(vpp.ProposalError, match='cut off'):
        vpp.propose_description(system, 'claude-opus-5-5', reply_file)
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


def test_voice_is_a_registered_command():
    from storyforge.__main__ import COMMANDS
    assert COMMANDS['voice'] == 'storyforge.cmd_voice'

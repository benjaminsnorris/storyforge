"""The voice-austen suite's free parts (#654, plan B7 test 6): the fixture
book, the voice check, the draft's guards, the judge's orders and samples,
the meter and the metrics. The API is faked at `storyforge.api.invoke`; the
suite's paid calls are frozen recordings
(`evals/fixtures/cassettes/voice-austen`), never asserted to pass here."""

import glob
import os
import re
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402
from suites import voice_austen as va  # noqa: E402
from suites import voice_austen_control as vc  # noqa: E402

#: names in the samples as their authors wrote them (a judge that sees them
#: knows the book: #689 review SF-1)
KNOWN_NAMES = ('Musgrove', 'Elliot', 'Anne', 'Charles', 'Henrietta', 'Benwick', 'Harville',
               'Russell', 'Kellynch', 'Montreville', 'Hargrave', 'Laura', 'Casaubon', 'Brooke',
               'Ladislaw', 'Cadwallader', 'Middlemarch', 'Scrooge', 'Marley')


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _chunk(path_parts, i=3):
    from storyforge import voiceprint as vp
    return vp.chunks(_read(os.path.join(*path_parts)))[i]


def _response(text, stop='end_turn', model='claude-opus-5-5'):
    return {'content': [{'type': 'text', 'text': text}], 'stop_reason': stop, 'model': model}


@pytest.fixture
def opus(monkeypatch):
    monkeypatch.setenv('STORYFORGE_MODEL', 'claude-opus-5-5')


@pytest.fixture
def no_spend(monkeypatch):
    import storyforge.api as api
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: pytest.fail('a paid call was made'))


# ============================================================================
# The fixture book and its voice
# ============================================================================

def test_project_points_the_voice_block_at_the_austen_reference(tmp_path):
    from storyforge import voice_repo
    proj = va.project(str(tmp_path))
    ref = voice_repo.voice_ref(proj)
    assert ref is not None and os.path.samefile(ref.author_dir, va.AUSTEN)


def test_project_refuses_a_fixture_without_the_placeholder(tmp_path, monkeypatch):
    import shutil
    fixture = tmp_path / 'fixture'
    shutil.copytree(va.FIXTURE, fixture)
    yaml = fixture / 'storyforge.yaml'
    yaml.write_text(yaml.read_text().replace('AUTHOR_REPO', va.AUSTEN))
    monkeypatch.setattr(va, 'FIXTURE', str(fixture))
    with pytest.raises(RuntimeError, match='AUTHOR_REPO'):
        va.project(str(tmp_path / 'work'))


def test_prompt_and_shared_context_carry_the_whole_voice_and_the_brief(tmp_path):
    from storyforge.cmd_write import _build_prompt
    from storyforge.common import build_shared_context
    proj = va.project(str(tmp_path))
    system = build_shared_context(proj, model='claude-opus-5-5')
    lines = va.check_voice(proj, system)
    assert lines and '25 exemplar(s)' in lines[0]
    prompt = _build_prompt(va.SCENE, proj, 'full', use_briefs=True, system_context=True)
    assert 'Six thousand, my dear' in prompt and '~2000 words' in prompt


def test_check_voice_refuses_a_book_without_the_voice_block(tmp_path):
    proj = va.project(str(tmp_path))
    yaml = os.path.join(proj, 'storyforge.yaml')
    text = _read(yaml)
    with open(yaml, 'w', encoding='utf-8') as f:
        f.write(text[:text.index('voice:')])
    with pytest.raises(RuntimeError, match='no voice: block'):
        va.check_voice(proj, [])


def test_check_voice_refuses_a_context_missing_an_exemplar(tmp_path):
    from storyforge.common import build_shared_context
    proj = va.project(str(tmp_path))
    system = build_shared_context(proj, model='claude-opus-5-5')
    from storyforge import voice_repo
    first = voice_repo.book_voice(proj).exemplars.exemplars[0].text.strip()
    cut = [dict(b, text=b['text'].replace(first, '')) for b in system]
    with pytest.raises(RuntimeError, match='1 of 25 exemplars missing'):
        va.check_voice(proj, cut)
    with pytest.raises(RuntimeError, match='voice whole'):
        va.check_voice(proj, [b for b in system if '=== The Voice ===' not in b['text']])


# ============================================================================
# The draft
# ============================================================================

def test_draft_refuses_before_spending_without_the_voice(tmp_path, opus, no_spend):
    proj = va.project(str(tmp_path))
    yaml = os.path.join(proj, 'storyforge.yaml')
    text = _read(yaml)
    with open(yaml, 'w', encoding='utf-8') as f:
        f.write(text[:text.index('voice:')])
    with pytest.raises(RuntimeError, match='no voice: block'):
        va.draft(proj)


@pytest.mark.parametrize('response, match', [
    (_response('Word ' * 1500 + 'end.', stop='max_tokens'), 'cut off'),
    (_response('Word ' * 1500 + 'and then she'), 'mid-sentence|ends'),
    (_response('Word ' * 200 + 'end.'), '201 words; the meter needs 1000'),
    (_response(''), 'empty'),
])
def test_draft_refuses_a_reply_the_meter_shouldnt_read(tmp_path, opus, monkeypatch,
                                                        response, match):
    import storyforge.api as api
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: response)
    with pytest.raises(RuntimeError, match=match):
        va.draft(va.project(str(tmp_path)))


def test_draft_sends_the_voice_and_notes_the_model(tmp_path, opus, monkeypatch):
    import storyforge.api as api
    seen = {}

    def fake(prompt, model, **kw):
        seen.update(kw)
        return _response('She played her card. ' * 300, model='claude-opus-5-5-recorded')

    monkeypatch.setattr(api, 'invoke', fake)
    prose, notes = va.draft(va.project(str(tmp_path)))
    assert len(prose.split()) == 1200
    assert seen['max_tokens'] == va.DRAFT_MAX_TOKENS
    assert any('=== The Voice ===' in b['text'] for b in seen['system'])
    assert notes[0].startswith('Voice: ')
    assert 'draft model: claude-opus-5-5-recorded' in notes[-1]
    assert 'no scene markers' in notes[-1]


def test_control_project_has_no_voice_block(tmp_path):
    from storyforge import voice_repo
    proj = va.project(str(tmp_path), voiced=False)
    assert voice_repo.voice_ref(proj) is None
    text = _read(os.path.join(proj, 'storyforge.yaml'))
    assert 'voice:' not in text and 'AUTHOR_REPO' not in text
    assert 'title: "The Lodge at Hartwell"' in text


def test_control_sends_the_same_request_less_the_voice(tmp_path, opus, monkeypatch):
    """The control differs from the voiced draft only by the voice block."""
    import storyforge.api as api
    seen = []

    def fake(prompt, model, **kw):
        seen.append((prompt, model, kw))
        return _response('She played her card. ' * 300)

    monkeypatch.setattr(api, 'invoke', fake)
    va.draft(va.project(str(tmp_path / 'v')))
    prose, notes = va.draft(va.project(str(tmp_path / 'c'), voiced=False), voiced=False)
    (vp_, vm, vkw), (cp, cm, ckw) = seen
    assert (cp, cm, ckw['max_tokens']) == (vp_, vm, vkw['max_tokens'])
    voiced = [b['text'] for b in vkw['system']]
    control = [b['text'] for b in ckw['system']]
    assert [x for x in voiced if '=== The Voice ===' not in x] == control
    assert len(voiced) == len(control) + 1
    assert notes[0].startswith('Voice: none (the control')


def test_control_refuses_a_context_that_carries_a_voice(tmp_path, opus, monkeypatch):
    import storyforge.api as api
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: pytest.fail('a paid call was made'))
    with pytest.raises(RuntimeError, match='control\'s shared context carries a voice'):
        va.draft(va.project(str(tmp_path)), voiced=False)


# ============================================================================
# The judge
# ============================================================================

def test_orders_put_each_candidate_in_each_place_once():
    orders = va.orders()
    n = len(va.CANDIDATES)
    assert len(orders) == n and all(sorted(o) == list(range(n)) for o in orders)
    for place in range(n):
        assert sorted(o[place] for o in orders) == list(range(n))
    assert [o.index(0) for o in orders] == list(range(n))
    assert va.CANDIDATES[0][0] == va.AUSTEN_NAME and len(va.LETTERS) == n


def test_judge_maps_each_pick_to_the_author_shown_there(monkeypatch, opus):
    """Austen is at A, B, C and D in turn; every prompt shows all four
    samples; a pick names whoever is shown at that letter."""
    import storyforge.api as api
    prompts = []
    picks_given = iter('BBAD')

    def fake(prompt, model, **kw):
        prompts.append(prompt)
        return _response(f'{{"pick": "{next(picks_given)}", "reason": "r"}}')

    monkeypatch.setattr(api, 'invoke', fake)
    texts = va.samples()
    picks = va.judge('Some prose.')
    assert [p['austen_at'] for p in picks] == list('ABCD')
    for p, prompt in zip(picks, prompts):
        shown = []
        for c in 'ABCD':
            body = prompt.split(f'## Sample {c}\n\n', 1)[1]
            shown.append(next(i for i, s in enumerate(texts) if body.startswith(s)))
        assert sorted(shown) == [0, 1, 2, 3]
        assert shown['ABCD'.index(p['austen_at'])] == 0
        assert p['author'] == va.CANDIDATES[shown['ABCD'.index(p['pick'])]][0]
    # B, B, A, D against Austen at A, B, C, D: she is named in asks 2 and 4
    assert [p['author'] == va.AUSTEN_NAME for p in picks] == [False, True, False, True]


def test_judge_names_the_ask_it_couldnt_read(monkeypatch, opus):
    import storyforge.api as api
    replies = iter([_response('{"pick": "A", "reason": "r"}'),
                    _response('{"pick": "A", "rea', stop='max_tokens')])
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: next(replies))
    with pytest.raises(RuntimeError, match=r'judge ask 2 \(Austen at B\): .*cut off'):
        va.judge('Some prose.')


def test_samples_are_whole_paragraphs_from_mid_text_with_names_replaced():
    texts = va.samples()
    exemplars = [_read(f) for f in glob.glob(os.path.join(va.AUSTEN, 'exemplars', '*.md'))]
    for (_, (kind, slug)), text in zip(va.CANDIDATES, texts):
        words = len(text.split())
        assert va.SAMPLE_WORDS <= words < 3 * va.SAMPLE_WORDS, slug
        assert not any(line.startswith('#') for line in text.splitlines())
        for name in KNOWN_NAMES:
            assert not re.search(rf'\b{name}\b', text), (slug, name)
        if kind == 'austen':
            # held out: not one of the exemplars the writer saw
            assert not any(text.split('\n\n')[1][:200] in e for e in exemplars)
    # no invented name stands for two people: each sample's names are its own
    used = [set(re.findall('|'.join(va.NEUTRAL), t)) for t in texts]
    for i in range(len(used)):
        for j in range(i + 1, len(used)):
            assert not used[i] & used[j], (i, j, used[i] & used[j])


def test_neutral_names_keeps_titles_and_replaces_possessives():
    out, = va.neutral_names(['"Ask Mr. Scrooge," said Bob. "Bob\'s right. Scrooge\'s office '
                             'is shut," Bob said again.'])
    assert 'Scrooge' not in out and 'Bob' not in out and 'Mr. ' in out
    assert re.search(r"\b[A-Z][a-z]+'s office", out)


def test_sample_refuses_an_unknown_source():
    with pytest.raises(RuntimeError, match='unknown sample source'):
        va.sample(('elsewhere', 'x'))


# ============================================================================
# The meter and the metrics
# ============================================================================

def test_meter_puts_held_out_austen_nearest_her():
    m = va.meter(_chunk((va.AUSTEN, 'corpus', 'persuasion.md')))
    assert next(iter(m['distances'])) == 'austen'
    assert len(m['distances']) == 1 + len(va.OTHERS)
    assert m['held_out_median'] < m['held_out_max']


def _run(tmp_path, monkeypatch, prose, austen_named):
    picks = [{'austen_at': c, 'pick': c, 'model': 'm', 'reason': 'r',
              'author': va.AUSTEN_NAME if i < austen_named else 'George Eliot'}
             for i, c in enumerate('ABCD')]
    monkeypatch.setattr(va, 'draft', lambda proj, voiced=True: (prose, ['Voice: Jane Austen']))
    monkeypatch.setattr(va, 'judge', lambda prose: picks)
    ctx = harness.SuiteContext('voice-austen', 'replay', str(tmp_path / 'c'),
                               str(tmp_path / 'w'))
    return va.run(ctx)


def test_run_metrics_and_gates_when_austen_is_nearest(tmp_path, monkeypatch):
    prose = _chunk((va.AUSTEN, 'corpus', 'persuasion.md'))
    out = _run(tmp_path, monkeypatch, prose, austen_named=3)
    dist = va.meter(prose)['distances']
    m = out.metrics
    assert m['meter_rank'] == 1 and m['meter_margin'] > 0
    assert m['meter_margin'] == round(min(v for a, v in dist.items() if a != 'austen')
                                      - dist['austen'], 4)
    assert (m['judge_austen'], m['judge_asked']) == (3, 4)
    gates = {g.name: g for g in out.gates}
    assert (gates['meter_rank'].op, gates['meter_rank'].threshold) == ('<=', va.RECORDED_RANK)
    assert gates['meter_rank'].passed
    assert (gates['judge_austen'].op, gates['judge_austen'].threshold) == (
        '>=', va.RECORDED_JUDGE)
    assert not gates['judge_austen'].passed
    assert _read(tmp_path / 'w' / 'voice-austen' / 'scenes' / f'{va.SCENE}.md') == prose
    assert out.notes[0] == 'Voice: Jane Austen'


def test_run_metrics_when_another_author_is_nearer(tmp_path, monkeypatch):
    prose = _read(os.path.join(va.OTHERS_DIR, 'christmas-carol', '05.md'))
    out = _run(tmp_path, monkeypatch, prose, austen_named=4)
    assert out.metrics['meter_rank'] > 1 and out.metrics['meter_margin'] < 0
    assert not {g.name: g for g in out.gates}['meter_rank'].passed
    assert any('further from her than any of her own chunks' in n for n in out.notes)


def test_control_run_gates_hold_the_recorded_values_in_the_comparison_direction(
        tmp_path, monkeypatch):
    prose = _read(os.path.join(va.OTHERS_DIR, 'christmas-carol', '05.md'))
    seen = []
    monkeypatch.setattr(va, 'draft', lambda proj, voiced=True: (
        seen.append((proj, voiced)) or (prose, ['Voice: none (the control)'])))
    monkeypatch.setattr(va, 'judge', lambda prose: [
        {'austen_at': c, 'pick': c, 'model': 'm', 'reason': 'r', 'author': 'George Eliot'}
        for c in 'ABCD'])
    ctx = harness.SuiteContext('voice-austen-control', 'replay', str(tmp_path / 'c'),
                               str(tmp_path / 'w'))
    out = vc.run(ctx)
    assert seen[0][1] is False
    from storyforge import voice_repo
    assert voice_repo.voice_ref(seen[0][0]) is None
    gates = {g.name: g for g in out.gates}
    assert (gates['meter_rank'].op, gates['meter_rank'].threshold) == ('>=', vc.RECORDED_RANK)
    assert (gates['judge_austen'].op, gates['judge_austen'].threshold) == (
        '<=', vc.RECORDED_JUDGE)
    assert out.metrics['judge_austen'] == 0 and out.metrics['meter_rank'] > 1

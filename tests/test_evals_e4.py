import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402,F401
import e4  # noqa: E402


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_parse_judgment():
    text = ('ok {"contradictions": [{"code": "TIM", "fact": "f", "quote": "a", "against": "b"}], '
            '"broken_promises": [{"field": "outcome", "promise": "p", "why": "w"}]}')
    judged = e4.parse_judgment(text)
    assert judged['contradictions'][0]['code'] == 'TIM'
    assert judged['broken_promises'][0]['field'] == 'outcome'
    assert e4.parse_judgment('{"contradictions": [], "broken_promises": []}') == {
        'contradictions': [], 'broken_promises': []}


@pytest.mark.parametrize('text', [
    'none',
    '{"contradictions": []}',
    '{"contradictions": [{"code": "VOI"}], "broken_promises": []}',
    '{"contradictions": [], "broken_promises": [{"field": "emotions"}]}',
])
def test_unreadable_answers_raise(text):
    with pytest.raises(ValueError):
        e4.parse_judgment(text)


def test_act_scenes_in_reading_order_and_act_wins_over_part(tmp_path):
    _write(tmp_path / 'reference' / 'scenes.csv',
           'id|seq|act|part\nc|3||1\na|1||1\nb|2|2|1\nd|4||2\n')
    assert [r['id'] for r in e4.act_scenes(str(tmp_path))] == ['a', 'c']


def test_clear_prose_removes_the_files_and_keeps_the_text(tmp_path):
    _write(tmp_path / 'scenes' / 'a.md', 'author prose')
    assert e4.clear_prose(str(tmp_path), ['a', 'missing']) == {'a': 'author prose'}
    assert not (tmp_path / 'scenes' / 'a.md').exists()


def test_brief_block_lists_promise_fields_only(tmp_path):
    _write(tmp_path / 'reference' / 'scene-briefs.csv',
           'id|goal|outcome|emotions|key_dialogue\na|find it|no-and|dread|"Your turn"\n')
    block = e4.brief_block(str(tmp_path), 'a')
    assert 'goal: find it' in block and 'Your turn' in block
    assert 'dread' not in block


def test_judge_prompt_marks_the_first_scene():
    assert '(none: this is the first scene)' in e4.judge_prompt([], 'goal: g', 'a', 'prose')
    assert '<scene id="a">' in e4.judge_prompt([('a', 'earlier')], 'goal: g', 'b', 'prose')


def test_length_drift_and_rate():
    rows = [{'id': 'a', 'target_words': '100'}, {'id': 'b', 'target_words': '200'},
            {'id': 'c', 'target_words': ''}]
    drafts = {'a': 'w ' * 150, 'b': 'w ' * 100, 'c': 'w ' * 10}
    assert e4.length_drift(rows, drafts) == 0.5
    assert e4.per_10k(3, 20000) == 1.5
    assert e4.per_10k(3, 0) == 0.0


def test_the_e4_suite_loads():
    names = {s.name for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert 'e4-generation' in names


def test_a_refused_scene_is_recorded_and_drafting_goes_on(monkeypatch, tmp_path):
    from storyforge import api
    (tmp_path / 'scenes').mkdir()
    (tmp_path / 'reference').mkdir()
    (tmp_path / 'reference' / 'scenes.csv').write_text('id|seq|word_count|status\na|1||\nb|2||\n')
    monkeypatch.setattr('storyforge.common.build_shared_context', lambda p, model='': [])
    monkeypatch.setattr('storyforge.common.select_model', lambda t: 'm')
    monkeypatch.setattr('storyforge.cmd_write._build_prompt', lambda sid, *a, **k: sid)

    def fake_invoke(prompt, model, **kw):
        if prompt == 'a':
            raise api.RefusalError({'stop_reason': 'refusal', 'stop_details': {'category': 'cyber'}})
        return {'content': [{'type': 'text', 'text': 'Prose. ' * 120}]}
    monkeypatch.setattr('storyforge.api.invoke', fake_invoke)
    drafts, refused = e4.draft(str(tmp_path), ['a', 'b'])
    assert list(drafts) == ['b'] and 'cyber' in refused['a']


def test_each_draft_is_gated_before_the_next_and_a_failure_drafts_on(monkeypatch, tmp_path):
    from storyforge import gate
    from storyforge.checker import CheckResult, Finding
    (tmp_path / 'scenes').mkdir()
    (tmp_path / 'reference').mkdir()
    (tmp_path / 'reference' / 'scenes.csv').write_text('id|seq|word_count|status\na|1||\nb|2||\n')
    monkeypatch.setattr('storyforge.common.build_shared_context', lambda p, model='': [])
    monkeypatch.setattr('storyforge.common.select_model', lambda t: 'm')
    order = []

    def prompt(sid, *a, **k):
        order.append(('prompt', sid))
        return sid
    monkeypatch.setattr('storyforge.cmd_write._build_prompt', prompt)
    monkeypatch.setattr('storyforge.api.invoke',
                        lambda p, m, **k: {'content': [{'type': 'text', 'text': 'Prose. ' * 120}]})
    bad = Finding('contradiction', 'TIM', 'x', 'y', 'z', '', 'why')

    def fake_gate(project_dir, sid, *, command, prose, log_dir, **k):
        order.append(('gate', sid))
        result = gate.GateResult(sid, check=CheckResult(sid, findings=[bad] if sid == 'a' else []))
        return gate.GatedScene(prose + ' Fixed.', result, result, fixed=True)
    monkeypatch.setattr(gate, 'gate_and_fix', fake_gate)
    gated = {}
    drafts, _ = e4.draft(str(tmp_path), ['a', 'b'], gated=gated, log_dir=str(tmp_path / 'g'))
    assert order == [('prompt', 'a'), ('gate', 'a'), ('prompt', 'b'), ('gate', 'b')]
    assert drafts['a'].endswith('Fixed.') and not gated['a'].result.passed
    assert (tmp_path / 'scenes' / 'a.md').read_text().endswith('Fixed.')


def _judged(contradictions=0, promises=0):
    return {'contradictions': [{'code': 'TIM'}] * contradictions,
            'broken_promises': [{'field': 'outcome'}] * promises}


def test_gate_measure_headline_stops_at_the_first_gate_failure():
    ids = ['a', 'b', 'c', 'd', 'e']
    drafts = {s: 'word ' * 1000 for s in ids if s != 'b'}  # b refused
    judged = {'a': _judged(1, 1), 'c': _judged(2), 'd': _judged(0, 1), 'e': _judged(3, 2)}
    out = e4.gate_measure(ids, drafts, judged, failed={'c', 'd'})
    m = out['metrics']
    assert out['headline'] == ['a']   # write stops at b's refusal
    assert (m['contradictions'], m['words'], m['cp10k']) == (1, 1000, 10.0)
    assert (m['broken_promises'], m['bps']) == (1, 1.0)
    assert (m['contradictions_all'], m['words_all'], m['broken_promises_all']) == (6, 4000, 4)
    # passed: a and e, wherever they fall
    assert (m['scenes_passed'], m['contradictions_passed'], m['cp10k_passed']) == (2, 4, 20.0)
    assert m['contradictions_in_failed'] == 2
    assert out['labels'] == {'a': 'missed', 'c': 'caught', 'd': 'false_alarm', 'e': 'missed'}
    assert (m['gate_caught'], m['gate_missed'], m['gate_false_alarm']) == (1, 2, 1)
    assert m['gate_catch_rate'] == 0.333


def test_gate_measure_with_no_failure_counts_every_drafted_scene():
    drafts = {'a': 'w ' * 500, 'b': 'w ' * 500}
    out = e4.gate_measure(['a', 'b'], drafts, {'a': _judged(), 'b': _judged(1)}, failed=set())
    assert out['headline'] == ['a', 'b']
    assert out['metrics']['cp10k'] == out['metrics']['cp10k_all'] == 10.0
    assert out['labels'] == {'a': 'clean', 'b': 'missed'}
    assert out['metrics']['gate_catch_rate'] is None or out['metrics']['gate_catch_rate'] == 0.0


@pytest.mark.parametrize('failed, headline', [
    ({'a'}, ['a']),                    # the first scene fails
    ({'c'}, ['a', 'b', 'c']),          # the last scene fails
    (set(), ['a', 'b', 'c']),
])
def test_gate_measure_headline_ends_where_write_stops(failed, headline):
    drafts = {s: 'w ' * 100 for s in 'abc'}
    judged = {s: _judged() for s in 'abc'}
    out = e4.gate_measure(list('abc'), drafts, judged, failed=failed)
    assert out['headline'] == headline
    assert out['metrics']['gate_catch_rate'] is None   # nothing to catch


def test_gate_measure_with_nothing_drafted():
    out = e4.gate_measure(['a'], {}, {}, failed=set())
    assert out['headline'] == [] and out['metrics']['cp10k'] == 0.0

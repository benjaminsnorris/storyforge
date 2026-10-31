import copy
import os
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402,F401
import recheck  # noqa: E402
from test_evals_e1 import CASE, SPAN  # noqa: E402

from storyforge import ledger  # noqa: E402


def _case(established, contradicted):
    case = copy.deepcopy(CASE)
    case['established'] = [{**SPAN, 'path': f'scenes/{established}.md', 'quote': 'Three hours.'}]
    case['contradicted'] = [{**SPAN, 'path': f'scenes/{s}.md'} for s in contradicted]
    return case


def _fact(fid, scene, subject, type_='physical', statement='x'):
    return {'id': fid, 'scene_id': scene, 'type': type_, 'subject': subject,
            'statement': statement, 'quote': '', 'origin': 'prose', 'status': 'binding',
            'mutable': 'state', 'introduced_by': ledger.COMMITMENTS_PASS}


@pytest.mark.parametrize('text, verdict', [
    ('{"verdict": "captured", "ids": ["a"]}', 'captured'),
    ('here:\n{"verdict": "missing", "ids": []}', 'missing'),
])
def test_parse_verdict(text, verdict):
    assert recheck.parse_verdict(text, {'a'})['verdict'] == verdict


@pytest.mark.parametrize('text', [
    'nope',
    '{"verdict": "yes", "ids": []}',
    '{"verdict": "captured", "ids": ["zzz"]}',      # a row it wasn't offered
    '{"verdict": "captured", "ids": []}',           # captured with nothing
    '{"verdict": "missing", "ids": ["a"]}',
    '{"verdict": "partial", "ids": "a"}',
])
def test_unreadable_verdict_raises(text):
    with pytest.raises(ValueError):
        recheck.parse_verdict(text, {'a'})


def test_place_finds_the_scenes_and_spaces_the_controls(project_dir):
    order = ledger.scene_order(project_dir)
    for sid in order:   # every scene drafted
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if not os.path.isfile(path):
            with open(path, 'w') as f:
                f.write('Prose.\n')
    last = max(order, key=order.get)
    first = min(order, key=order.get)
    item = recheck.place(_case(first, [last]), project_dir, order)
    assert item.established == first and item.contradicted == [last]
    between = [s for s in sorted(order, key=order.get) if s not in (first, last)]
    assert len(item.controls) == min(recheck.CONTROLS, len(between))
    assert set(item.controls) <= set(between)
    if len(between) > recheck.CONTROLS:
        assert item.controls[0] == between[0] and item.controls[-1] == between[-1]


def test_place_excludes_a_contradiction_before_the_establishing_scene(project_dir):
    order = ledger.scene_order(project_dir)
    reason = recheck.place(_case('act1-sc02', ['act1-sc01']), project_dir, order)
    assert 'before the establishing scene' in reason


def test_place_excludes_a_scene_not_in_the_book(project_dir):
    order = ledger.scene_order(project_dir)
    assert 'not in scenes.csv' in recheck.place(_case('gone', ['act2-sc01']), project_dir, order)


def test_recheck_set_lists_the_later_scene_about_the_same_subject(project_dir):
    rows = ledger.load(project_dir) + [
        _fact('dorren-hurt', 'act1-sc01', 'lamp-z'),
        _fact('dorren-fine', 'act2-sc01', 'lamp-z'),
        _fact('kael-tired', 'new-x1', 'kael-maren')]
    scenes, unrelated = recheck.recheck_set(project_dir, rows, ['dorren-hurt'])
    assert scenes == ['act2-sc01'] and unrelated == []


def test_recheck_set_reports_a_fact_it_cant_trace(project_dir):
    rows = ledger.load(project_dir) + [_fact('nameless', 'act1-sc01', '', type_='knowledge')]
    scenes, unrelated = recheck.recheck_set(project_dir, rows, ['nameless'])
    assert unrelated and unrelated[0].startswith('nameless: ')


def test_judge_offers_only_the_establishing_scenes_binding_rows(monkeypatch, project_dir):
    from storyforge import api
    seen = {}
    monkeypatch.setattr(api, 'invoke', lambda p, m, **k: seen.setdefault('p', p) and {
        'content': [{'type': 'text', 'text': '{"verdict": "captured", "ids": ["mine"]}'}]})
    rejected = {**_fact('old', 'act1-sc01', 'dorren-hayle'), 'status': 'rejected'}
    rows = [_fact('mine', 'act1-sc01', 'dorren-hayle', statement='drove three hours'),
            _fact('other', 'act1-sc02', 'dorren-hayle', statement='OTHER SCENE'), rejected]
    item = recheck.Item(_case('act1-sc01', ['act2-sc01']), 'abc1234', 'act1-sc01', ['act2-sc01'])
    assert recheck.judge(item, rows)['ids'] == ['mine']
    assert 'drove three hours' in seen['p'] and 'Three hours.' in seen['p']
    assert 'OTHER SCENE' not in seen['p'] and '\nold |' not in seen['p']


def test_judge_with_no_rows_is_missing_without_a_call(monkeypatch, project_dir):
    from storyforge import api
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: pytest.fail('no call expected'))
    item = recheck.Item(_case('act1-sc01', ['act2-sc01']), 'abc1234', 'act1-sc01', ['act2-sc01'])
    assert recheck.judge(item, []) == {'verdict': 'missing', 'ids': []}


def test_select_reports_exclusions(monkeypatch, tmp_path):
    import e1
    same = _case('44', ['44'])
    same['id'] = 'book-002'
    held = copy.deepcopy(CASE)
    held['id'] = 'book-003'
    monkeypatch.setattr(e1, 'load_cases', lambda: [_case('44', ['45']), same, held])
    monkeypatch.setattr(e1, 'load_holdout', lambda: ['book-003'])
    cases, excluded = recheck.select(str(tmp_path))
    assert cases == []
    assert excluded == {'book not cloned': ['book-001'],
                        'contradicted only in the establishing scene': ['book-002'],
                        'holdout': ['book-003']}


def test_the_recheck_suite_loads():
    names = {s.name for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert 'recheck-set' in names

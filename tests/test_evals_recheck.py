import copy
import importlib
import os
import subprocess
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402,F401
import recheck  # noqa: E402
from test_evals_e1 import CASE, SPAN  # noqa: E402

from storyforge import ledger  # noqa: E402

# The fixture's reading order: act1-sc01, act1-sc02, new-x1, act2-sc01,
# act2-sc02, act2-sc03 (the last two have no prose as shipped)


def _case(established, contradicted, cid='book-001', code='TIM'):
    case = copy.deepcopy(CASE)
    case.update(id=cid, code=code)
    case['established'] = [{**SPAN, 'path': f'scenes/{established}.md', 'quote': 'Three hours.'}]
    case['contradicted'] = [{**SPAN, 'path': f'scenes/{s}.md'} for s in contradicted]
    return case


def _fact(fid, scene, subject, type_='physical', statement='x'):
    return {'id': fid, 'scene_id': scene, 'type': type_, 'subject': subject,
            'statement': statement, 'quote': '', 'origin': 'prose', 'status': 'binding',
            'mutable': 'state', 'introduced_by': ledger.COMMITMENTS_PASS}


def _draft_all(project_dir):
    for sid in ledger.scene_order(project_dir):
        path = os.path.join(project_dir, 'scenes', f'{sid}.md')
        if not os.path.isfile(path):
            with open(path, 'w') as f:
                f.write('Prose.\n')


def _place(project_dir, established, contradicted):
    return recheck.place(_case(established, contradicted), project_dir,
                         ledger.scene_order(project_dir))


def _item(established='act1-sc01', contradicted=('act2-sc01',)):
    return recheck.Item(_case(established, list(contradicted)), 'abc1234', established,
                        'Three hours.', tuple(contradicted), ())


# --- parse_verdict, format_rows ---------------------------------------------

@pytest.mark.parametrize('text, verdict', [
    ('{"verdict": "captured", "ids": ["a"]}', 'captured'),
    ('{"verdict": "partial", "ids": ["a"]}', 'partial'),
    ('here:\n{"verdict": "missing", "ids": []}', 'missing'),
])
def test_parse_verdict(text, verdict):
    assert recheck.parse_verdict(text, {'a'})['verdict'] == verdict


def test_parse_verdict_keeps_only_the_verdict_and_ids():
    assert recheck.parse_verdict('{"verdict": "captured", "ids": ["a"], "why": "x"}', {'a'}) \
        == {'verdict': 'captured', 'ids': ['a']}


@pytest.mark.parametrize('text', [
    'nope',
    '{"verdict": "yes", "ids": []}',
    '{"verdict": "captured", "ids": ["zzz"]}',      # a row it wasn't offered
    '{"verdict": "captured", "ids": []}',           # captured with nothing
    '{"verdict": "missing", "ids": ["a"]}',
    '{"verdict": "partial", "ids": "a"}',
    '{"verdict": "missing", "ids": []} {"verdict": "missing", "ids": []}',  # two objects
])
def test_unreadable_verdict_raises(text):
    with pytest.raises(ValueError):
        recheck.parse_verdict(text, {'a'})


def test_format_rows_puts_each_row_on_one_line():
    rows = [{'id': 'a', 'type': 'world', 'subject': None, 'statement': 'two\nlines', 'quote': ' q '}]
    assert recheck.format_rows(rows) == 'a | world |  | two lines | q'


# --- place -------------------------------------------------------------------

def test_place_finds_the_scenes_and_puts_the_controls_next_to_each_side(project_dir):
    _draft_all(project_dir)
    item = _place(project_dir, 'act1-sc01', ['act2-sc03'])
    assert item.established == 'act1-sc01' and item.contradicted == ('act2-sc03',)
    assert item.quote == 'Three hours.'
    assert item.controls == ('act1-sc02', 'act2-sc02')


@pytest.mark.parametrize('contradicted, controls', [
    (['new-x1'], ('act1-sc02',)),           # fewer between than CONTROLS: all of them
    (['act1-sc02'], ()),                    # adjacent: none
    (['act2-sc01', 'new-x1'], ('act1-sc02',)),  # bounded by the first contradicting scene
])
def test_place_controls(project_dir, contradicted, controls):
    assert _place(project_dir, 'act1-sc01', contradicted).controls == controls


def test_place_leaves_out_scenes_the_reject_flow_would_never_list(project_dir):
    """act2-sc02/03 have no prose as shipped; a blank file counts as none."""
    with open(os.path.join(project_dir, 'scenes', 'new-x1.md'), 'w') as f:
        f.write('  \n')
    item = _place(project_dir, 'act1-sc01', ['act2-sc03', 'act2-sc01', 'new-x1'])
    assert item.contradicted == ('act2-sc01',)
    assert item.controls == ('act1-sc02',)
    assert set(item.dropped) == {'act2-sc03: no prose in its tree', 'new-x1: no prose in its tree'}


def test_place_ignores_contradicted_spans_that_arent_prose(project_dir):
    case = _case('act1-sc01', ['act2-sc01'])
    case['contradicted'].append({**SPAN, 'path': 'scenes/new-x1.md', 'source': 'csv'})
    item = recheck.place(case, project_dir, ledger.scene_order(project_dir))
    assert item.contradicted == ('act2-sc01',)


def test_place_excludes_a_contradiction_before_the_establishing_scene(project_dir):
    assert _place(project_dir, 'act1-sc02', ['act1-sc01']) == recheck.BEFORE


def test_place_names_an_unusable_contradicting_scene_rather_than_calling_it_earlier(project_dir):
    reason = _place(project_dir, 'act1-sc02', ['act2-sc02', 'act1-sc01', 'gone'])
    assert reason.startswith('no usable contradicting scene')
    assert 'act2-sc02: no prose in its tree' in reason and 'gone: not in scenes.csv' in reason


def test_place_excludes_a_cut_contradicting_scene(project_dir):
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    with open(path) as f:
        text = f.read()
    with open(path, 'w') as f:
        f.write(text.replace('|architecture|', '|cut|'))
    assert 'act2-sc01: cut or merged' in _place(project_dir, 'act1-sc01', ['act2-sc01'])


@pytest.mark.parametrize('scene, fragment', [
    ('gone', 'establishing scene not in scenes.csv'),
    ('act2-sc02', 'establishing scene no prose in its tree'),
])
def test_place_excludes_an_unusable_establishing_scene(project_dir, scene, fragment):
    assert _place(project_dir, scene, ['act2-sc03']) == fragment


# --- recheck_set -------------------------------------------------------------

def test_recheck_set_lists_the_later_scene_about_the_same_subject(project_dir):
    order = ledger.scene_order(project_dir)
    rows = ledger.load(project_dir) + [
        _fact('hurt', 'act1-sc01', 'lamp-z'),
        _fact('fine', 'act2-sc01', 'lamp-z'),
        _fact('tired', 'new-x1', 'kael-maren')]
    found = recheck.recheck_set(project_dir, rows, ['hurt'], order)
    assert found.scenes == ('act2-sc01',) and found.unrelated == ()


def test_recheck_set_joins_several_facts_in_reading_order(project_dir):
    order = ledger.scene_order(project_dir)
    rows = ledger.load(project_dir) + [
        _fact('a', 'act1-sc01', 'lamp-z'), _fact('b', 'act1-sc01', 'wolf-z'),
        _fact('a2', 'act2-sc01', 'lamp-z'), _fact('b2', 'new-x1', 'wolf-z'),
        _fact('b3', 'act2-sc01', 'wolf-z')]
    assert recheck.recheck_set(project_dir, rows, ['a', 'b'], order).scenes == ('new-x1', 'act2-sc01')


def test_recheck_set_lists_now_when_the_establishing_scene_has_no_prose(project_dir):
    """act2-sc02 has no prose, so its dependents are listed for a re-check now."""
    order = ledger.scene_order(project_dir)
    with open(os.path.join(project_dir, 'scenes', 'act2-sc03.md'), 'w') as f:
        f.write('Prose.\n')
    rows = ledger.load(project_dir) + [_fact('a', 'act2-sc02', 'lamp-z'),
                                       _fact('a2', 'act2-sc03', 'lamp-z')]
    assert recheck.recheck_set(project_dir, rows, ['a'], order).scenes == ('act2-sc03',)


def test_recheck_set_counts_brief_named_scenes(project_dir, monkeypatch):
    """The gate lists the scenes whose brief names a rejected fact after
    its revision passes, as `_reject_recheck`'s `later` says."""
    from storyforge import audit
    order = ledger.scene_order(project_dir)
    rows = ledger.load(project_dir) + [_fact('a', 'act1-sc01', 'lamp-z')]
    monkeypatch.setattr(audit, 'leaning_scenes', lambda p, ids: {'a': ['act2-sc01']})
    assert recheck.recheck_set(project_dir, rows, ['a'], order).scenes == ('act2-sc01',)


def test_recheck_set_reports_a_fact_it_cant_trace(project_dir):
    order = ledger.scene_order(project_dir)
    rows = ledger.load(project_dir) + [_fact('nameless', 'act1-sc01', '', type_='knowledge')]
    found = recheck.recheck_set(project_dir, rows, ['nameless'], order)
    assert found.unrelated and found.unrelated[0].startswith('nameless: ')


def test_later_usable_counts_scenes_with_prose_not_cut(project_dir):
    order = ledger.scene_order(project_dir)
    assert recheck.later_usable(project_dir, 'act1-sc01', order, set()) == 3
    assert recheck.later_usable(project_dir, 'act1-sc01', order, {'new-x1'}) == 2


# --- judge -------------------------------------------------------------------

def _reply(text, stop='end_turn'):
    return {'content': [{'type': 'text', 'text': text}], 'stop_reason': stop}


def test_judge_offers_only_the_establishing_scenes_binding_rows(monkeypatch):
    from storyforge import api
    seen = {}
    monkeypatch.setattr(api, 'invoke', lambda p, m, **k: seen.setdefault('p', p) and _reply(
        '{"verdict": "captured", "ids": ["mine"]}'))
    rejected = {**_fact('old', 'act1-sc01', 'dorren-hayle'), 'status': 'rejected'}
    rows = [_fact('mine', 'act1-sc01', 'dorren-hayle', statement='drove three hours'),
            _fact('other', 'act1-sc02', 'dorren-hayle', statement='OTHER SCENE'), rejected]
    assert recheck.judge(_item(), rows)['ids'] == ['mine']
    assert 'drove three hours' in seen['p'] and 'Three hours.' in seen['p']
    assert CASE['summary'] in seen['p']
    assert 'OTHER SCENE' not in seen['p'] and '\nold |' not in seen['p']


def test_judge_with_no_rows_says_so_without_a_call(monkeypatch):
    from storyforge import api
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: pytest.fail('no call expected'))
    assert recheck.judge(_item(), []) == {'verdict': recheck.NO_ROWS, 'ids': []}


def test_a_truncated_judge_reply_raises(monkeypatch):
    from storyforge import api
    monkeypatch.setattr(api, 'invoke', lambda *a, **k: _reply('{"verdict": "capt', 'max_tokens'))
    with pytest.raises(ValueError, match='max_tokens'):
        recheck.judge(_item(), [_fact('mine', 'act1-sc01', 'x')])


# --- commit_subset, check_migrated --------------------------------------------

def test_commit_subset_runs_phase_4_on_the_subset_without_committing(project_dir, monkeypatch):
    from storyforge import cmd_extract
    seen = {}

    def phase_4(ids, project, scenes_dir, ref_dir, log_dir, **kwargs):
        seen['ids'] = ids
        cmd_extract.commit_and_push(project, 'x', [])
        for sid in ids:
            open(os.path.join(log_dir, f'extract-commitments-{sid}.json'), 'w').close()

    def no_commit(*a, **k):
        raise AssertionError('committed')
    monkeypatch.setattr(cmd_extract, '_run_phase_4', phase_4)
    monkeypatch.setattr(cmd_extract, 'commit_and_push', no_commit)
    recheck.commit_subset(project_dir, ['act1-sc01', 'act2-sc01'])
    assert seen['ids'] == ['act1-sc01', 'act2-sc01']


def test_commit_subset_raises_on_a_scene_phase_4_skipped(project_dir, monkeypatch):
    from storyforge import cmd_extract
    monkeypatch.setattr(cmd_extract, '_run_phase_4', lambda *a, **k: None)
    with pytest.raises(RuntimeError, match='skipped act1-sc01'):
        recheck.commit_subset(project_dir, ['act1-sc01'])


def test_commit_subset_refuses_scenes_that_already_have_commitments(project_dir, monkeypatch):
    from storyforge import cmd_extract
    ledger.save(project_dir, ledger.load(project_dir) + [_fact('a', 'act1-sc01', 'x')],
                command='test')
    monkeypatch.setattr(cmd_extract, '_run_phase_4', lambda *a, **k: pytest.fail('ran'))
    with pytest.raises(RuntimeError, match='already have commitments'):
        recheck.commit_subset(project_dir, ['act1-sc01'])


def test_commit_subset_turns_a_halted_chain_into_an_error(project_dir, monkeypatch):
    from storyforge import cmd_extract

    def halt(*a, **k):
        raise SystemExit(1)
    monkeypatch.setattr(cmd_extract, '_run_phase_4', halt)
    with pytest.raises(RuntimeError, match='phase 4 stopped'):
        recheck.commit_subset(project_dir, ['act1-sc01'])


def test_check_migrated_raises_when_old_registries_are_left(project_dir):
    recheck.check_migrated(project_dir)
    open(os.path.join(project_dir, 'reference', 'knowledge.csv'), 'w').close()
    with pytest.raises(RuntimeError, match='migration stopped'):
        recheck.check_migrated(project_dir)


# --- select ------------------------------------------------------------------

def test_select_reports_exclusions(monkeypatch, tmp_path):
    import e1
    same = _case('44', ['44'], cid='book-002')
    held = _case('44', ['45'], cid='book-003')
    no_con = _case('44', ['45'], cid='book-004')
    no_con['contradicted'][0]['source'] = 'csv'
    no_est = _case('44', ['45'], cid='book-005')
    no_est['established'][0]['source'] = 'reference'
    csv_level = {**_case('44', ['45'], cid='book-006'), 'level': 'csv'}
    monkeypatch.setattr(e1, 'load_cases', lambda: [_case('44', ['45']), same, held, no_con,
                                                   no_est, csv_level])
    monkeypatch.setattr(e1, 'load_holdout', lambda: ['book-003'])
    cases, excluded = recheck.select(str(tmp_path))
    assert cases == []
    assert excluded == {'book not cloned': ['book-001'],
                        'contradicted only in the establishing scene': ['book-002'],
                        'holdout': ['book-003'],
                        'no prose contradicted span': ['book-004'],
                        'no prose established span': ['book-005']}


def test_select_picks_a_case_whose_tree_has_scenes_csv(monkeypatch, tmp_path):
    import e1
    repo = tmp_path / 'book'
    repo.mkdir()

    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git('init', '-q')
    git('config', 'user.email', 't@t')
    git('config', 'user.name', 't')
    (repo / 'README').write_text('x')
    git('add', '.')
    git('commit', '-qm', 'before')
    before = git('rev-parse', 'HEAD')
    (repo / 'reference').mkdir()
    (repo / 'reference' / 'scenes.csv').write_text('id|seq\n')
    git('add', '.')
    git('commit', '-qm', 'after')
    after = git('rev-parse', 'HEAD')
    ok = _case('44', ['45'])
    ok['established'][0]['commit'] = after
    old = _case('44', ['45'], cid='book-002')
    old['established'][0]['commit'] = before
    monkeypatch.setattr(e1, 'load_cases', lambda: [ok, old])
    monkeypatch.setattr(e1, 'load_holdout', lambda: [])
    cases, excluded = recheck.select(str(tmp_path))
    assert [c['id'] for c in cases] == ['book-001']
    assert excluded == {'tree predates reference/scenes.csv': ['book-002']}


# --- the suite's run() --------------------------------------------------------

def _run_suite(monkeypatch, tmp_path, project_dir, cases, verdicts, facts):
    suite = importlib.import_module('suites.recheck_set')
    calls = []

    def commit_subset(project, scenes):
        calls.append(list(scenes))
        ledger.save(project, ledger.load(project) + facts, command='test')
    monkeypatch.setattr(recheck, 'select', lambda: (cases, {'holdout': ['book-099']}))
    monkeypatch.setattr(recheck, 'project_for', lambda *a, **k: project_dir)
    monkeypatch.setattr(recheck, 'commit_subset', commit_subset)
    monkeypatch.setattr(recheck, 'judge', lambda item, rows: verdicts[item.case['id']])
    return suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})()), calls


def test_the_suite_counts_captured_partial_and_missing_apart(monkeypatch, tmp_path, project_dir):
    _draft_all(project_dir)
    cases = [_case('act1-sc01', ['act2-sc01'], cid='book-001'),   # captured, hit
             _case('act1-sc01', ['new-x1'], cid='book-002'),      # captured, miss
             _case('act1-sc02', ['act2-sc01'], cid='book-003'),   # partial, hit
             _case('act1-sc01', ['act2-sc01'], cid='book-004'),   # missing
             _case('act2-sc01', ['act1-sc01'], cid='book-005')]   # backward: excluded
    facts = [_fact('lamp', 'act1-sc01', 'lamp-z'), _fact('lamp-later', 'act2-sc01', 'lamp-z'),
             _fact('wolf', 'act1-sc01', 'wolf-z'),
             _fact('moth', 'act1-sc02', 'moth-z'), _fact('moth-later', 'act2-sc01', 'moth-z')]
    verdicts = {'book-001': {'verdict': 'captured', 'ids': ['lamp']},
                'book-002': {'verdict': 'captured', 'ids': ['wolf']},
                'book-003': {'verdict': 'partial', 'ids': ['moth']},
                'book-004': {'verdict': 'missing', 'ids': []}}
    out, calls = _run_suite(monkeypatch, tmp_path, project_dir, cases, verdicts, facts)
    assert calls == [['act1-sc01', 'act1-sc02', 'new-x1', 'act2-sc01']]   # once per tree
    m = out.metrics
    assert (m['cases'], m['captured'], m['partial'], m['missing'], m['no_rows']) == (4, 2, 1, 1, 0)
    assert m['recall'] == 0.5
    assert m['recall_with_partial'] == round(2 / 3, 4)
    assert m['recall_end_to_end'] == 0.25
    assert m['controls'] == 3          # the captured cases' only: 2 + 1
    assert m['set_size_mean'] == 0.5
    assert m['excluded'] == 2
    assert out.by_code['TIM'] == {'cases': 4, 'captured': 2, 'recall': 0.5}
    assert f'excluded 1: {recheck.BEFORE}' in out.notes and 'excluded 1: holdout' in out.notes
    assert any(n.startswith('book-004 ') and n.endswith('fact not in the ledger') for n in out.notes)
    assert {g.name: g.passed for g in out.gates} == {'captured': False, 'recall': False}


def test_the_suite_with_every_case_excluded_runs_no_extraction(monkeypatch, tmp_path, project_dir):
    out, calls = _run_suite(monkeypatch, tmp_path, project_dir,
                            [_case('act1-sc02', ['act1-sc01'])], {}, [])
    assert calls == []
    assert out.metrics['cases'] == 0 and out.metrics['recall'] == 0.0
    assert out.by_code == {}


def test_the_recheck_suite_loads():
    names = {s.name for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert 'recheck-set' in names

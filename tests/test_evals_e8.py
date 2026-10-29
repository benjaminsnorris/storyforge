import copy
import subprocess
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import e8  # noqa: E402
from test_evals_e1 import CASE  # noqa: E402


def _tool_case(**changes):
    case = copy.deepcopy(CASE)
    case.update(subsets=['tool-introduced'],
                introduced_by={'kind': 'tool', 'pass': 'redraft-from-corrected-briefs',
                               'commit': 'abc1234'})
    case.update(changes)
    return case


@pytest.mark.parametrize('name, expected', [
    ('redraft-from-corrected-briefs', 'redraft-from-brief'),
    ('write (04-07 full redraft)', 'redraft-from-brief'),
    ('naturalness-craft-polish', 'revision-plan'),
    ('continuity-audit', 'revision-plan'),
])
def test_family(name, expected):
    assert e8.family(_tool_case(introduced_by={'kind': 'tool', 'pass': name})) == expected


def test_select_reports_every_exclusion():
    cases = [
        _tool_case(id='book-001'),
        _tool_case(id='book-002'),
        _tool_case(id='book-003', level='csv'),
        _tool_case(id='book-004', introduced_by={'kind': 'tool', 'pass': 'hone (registries)'}),
        _tool_case(id='book-005', introduced_by={'kind': 'tool', 'pass': 'redraft', 'commit': ''}),
        copy.deepcopy(CASE),  # not tool-introduced: not E8's at all
    ]
    sel = e8.select(cases, holdout=['book-002'])
    assert [c['id'] for c in sel.cases] == ['book-001']
    assert sel.excluded == {
        'holdout': ['book-002'],
        'csv-level (no prose to redraft)': ['book-003'],
        'pass not replayable yet: hone (registries)': ['book-004'],
        'no introducing commit recorded': ['book-005'],
    }


@pytest.mark.parametrize('text, verdict', [
    ('{"verdict": "reintroduced", "evidence": "Five hours."}', 'reintroduced'),
    ('Sure.\n{"verdict": "not_present", "evidence": ""}', 'not_present'),
])
def test_parse_verdict(text, verdict):
    assert e8.parse_verdict(text)['verdict'] == verdict


@pytest.mark.parametrize('text', ['no json here', '{"verdict": "maybe"}', '{"verdict": '])
def test_unreadable_verdict_raises_never_counts_as_safe(text):
    with pytest.raises(ValueError):
        e8.parse_verdict(text)


def test_judge_prompt_carries_both_sides():
    prompt = e8.judge_prompt(CASE, 'NEW PROSE')
    assert 'Three hours. Bend to Portland.' in prompt
    assert '"Five hours," he said.' in prompt and 'NEW PROSE' in prompt
    absent = e8.judge_prompt({**CASE, 'established': [], 'established_by_absence': 'never told'}, 'x')
    assert 'never told' in absent


@pytest.fixture(params=[True])
def book(tmp_path, request):
    repo = tmp_path / 'corpus' / 'book'
    (repo / 'scenes').mkdir(parents=True)
    (repo / 'reference').mkdir()
    git = ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'scenes' / 'phone-call.md').write_text('Three hours.\n')
    (repo / 'reference' / 'scene-briefs.csv').write_text('id|goal\nphone-call|x\n')
    if request.param:
        (repo / 'reference' / 'scenes.csv').write_text('id|seq\nphone-call|1\n')
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'before'], check=True)
    (repo / 'scenes' / 'phone-call.md').write_text('"Five hours," he said.\n')
    subprocess.run(git + ['commit', '-qam', 'redraft'], check=True)
    sha = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    return tmp_path / 'corpus', sha


def test_prepare_materializes_the_pre_pass_tree(book, tmp_path):
    root, sha = book
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': 'redraft', 'commit': sha})
    project, scene = e8.prepare(case, str(tmp_path / 'work'), str(root))
    assert scene == 'phone-call'
    with open(f'{project}/scenes/phone-call.md') as f:
        assert f.read() == 'Three hours.\n'  # the state the pass saw, not its output


def test_prepare_refuses_when_the_commit_did_not_touch_the_scene(book, tmp_path):
    root, sha = book
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': 'redraft', 'commit': sha},
                      contradicted=[{**CASE['contradicted'][0], 'scene': 'other', 'path': 'scenes/other.md'}])
    with pytest.raises(LookupError, match='changed none'):
        e8.prepare(case, str(tmp_path / 'work'), str(root))


def test_the_e8_suite_loads():
    import harness
    names = {s.name for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert 'e8-revision-safety' in names


@pytest.mark.parametrize('name, expected', [
    ('naturalness (upstream brief fixes)', 'naturalness-upstream'),
    ('stakes-and-history', 'revision-plan'),
    ('hone (registries/physical-states)', ''),
    ('illustrate --state', ''),
])
def test_more_families(name, expected):
    assert e8.family(_tool_case(introduced_by={'kind': 'tool', 'pass': name})) == expected


def test_pass_block_mirrors_cmd_revise():
    row = {'name': 'p', 'purpose': 'u', 'scope': 'scene-level', 'targets': 'a;b',
           'guidance': 'g', 'protection': '', 'findings': 'scores'}
    assert e8._pass_block(row) == ('- name: p\n    purpose: u\n    scope: scene-level'
                                   '\n    targets: a;b\n    guidance: g\n    findings: scores')


def test_plan_row_prefers_the_newest_plan(tmp_path):
    plans = tmp_path / 'working' / 'plans'
    plans.mkdir(parents=True)
    header = 'pass|name|purpose|scope|targets|guidance|protection|findings|status|model_tier|fix_location\n'
    (plans / 'revision-plan-2.csv').write_text(header + '1|polish|old|full||||||opus|craft\n')
    (plans / 'revision-plan-10.csv').write_text(header + '1|polish|new|full||||||opus|craft\n')
    assert e8.plan_row(str(tmp_path), 'polish')['purpose'] == 'new'
    with pytest.raises(LookupError, match='no CSV plan'):
        e8.plan_row(str(tmp_path), 'missing')


@pytest.mark.parametrize('book', [False], indirect=True)
def test_prepare_refuses_a_project_older_than_scenes_csv(book, tmp_path):
    root, sha = book
    case = _tool_case(introduced_by={'kind': 'tool', 'pass': 'redraft', 'commit': sha})
    with pytest.raises(LookupError, match='predates reference/scenes.csv'):
        e8.prepare(case, str(tmp_path / 'work'), str(root))

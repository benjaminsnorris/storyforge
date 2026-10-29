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
    ('naturalness-craft-polish', ''),
    ('continuity-audit', ''),
])
def test_family(name, expected):
    assert e8.family(_tool_case(introduced_by={'kind': 'tool', 'pass': name})) == expected


def test_select_reports_every_exclusion():
    cases = [
        _tool_case(id='book-001'),
        _tool_case(id='book-002'),
        _tool_case(id='book-003', level='csv'),
        _tool_case(id='book-004', introduced_by={'kind': 'tool', 'pass': 'naturalness'}),
        _tool_case(id='book-005', introduced_by={'kind': 'tool', 'pass': 'redraft', 'commit': ''}),
        copy.deepcopy(CASE),  # not tool-introduced: not E8's at all
    ]
    sel = e8.select(cases, holdout=['book-002'])
    assert [c['id'] for c in sel.cases] == ['book-001']
    assert sel.excluded == {
        'holdout': ['book-002'],
        'csv-level (no prose to redraft)': ['book-003'],
        'pass not replayable yet: naturalness': ['book-004'],
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


@pytest.fixture
def book(tmp_path):
    repo = tmp_path / 'corpus' / 'book'
    (repo / 'scenes').mkdir(parents=True)
    (repo / 'reference').mkdir()
    git = ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'scenes' / 'phone-call.md').write_text('Three hours.\n')
    (repo / 'reference' / 'scene-briefs.csv').write_text('id|goal\nphone-call|x\n')
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

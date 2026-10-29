import copy
import json
import subprocess
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import e1  # noqa: E402
from e1 import cli  # noqa: E402

SPAN = {'scene': 'phone-call', 'path': 'scenes/90.md', 'commit': 'abc1234',
        'quote': '"Five hours," he said.'}
CASE = {
    'id': 'book-001', 'repo': 'book', 'level': 'prose', 'code': 'TIM',
    'secondary_codes': [], 'summary': 'Drive is three hours, then five.',
    'established': [{**SPAN, 'scene': 'no-response', 'path': 'scenes/44.md',
                     'quote': 'Three hours. Bend to Portland.'}],
    'established_by_absence': '',
    'contradicted': [SPAN],
    'fix': {'status': 'fixed', 'commit': 'def5678',
            'after': [{**SPAN, 'commit': 'def5678', 'quote': '"Three hours," he said.'}]},
    'introduced_by': {'kind': 'plan', 'pass': '', 'commit': ''},
    'regressed_by': [], 'subsets': ['author-labeled'],
    'label_source': 'notes p.12', 'confidence': 'high', 'notes': '',
}


def _case(**changes):
    case = copy.deepcopy(CASE)
    case.update(changes)
    return case


def test_valid_case_has_no_problems():
    assert e1.validate_case(CASE) == []


@pytest.mark.parametrize('changes, fragment', [
    ({'id': 'book-1'}, 'id must look like'),
    ({'id': 'other-001'}, 'start with the repo'),
    ({'code': 'XYZ'}, 'code must be'),
    ({'level': 'scene'}, 'level must be'),
    ({'established': []}, 'established_by_absence'),
    ({'contradicted': []}, 'at least one span'),
    ({'contradicted': [{**SPAN, 'commit': 'abc1234~1'}]}, 'is not a sha'),
    ({'contradicted': [{**SPAN, 'quote': ' '}]}, 'missing quote'),
    ({'fix': {'status': 'fixed', 'commit': ''}}, 'needs fix.commit'),
    ({'subsets': ['author-labeled'], 'label_source': ''}, 'needs label_source'),
    ({'subsets': ['tool-introduced']}, 'must agree'),
    ({'introduced_by': {'kind': 'tool', 'pass': 'redraft'}}, 'must agree'),
    ({'introduced_by': {'kind': 'tool', 'pass': ''},
      'subsets': ['tool-introduced', 'author-labeled']}, 'must name the pass'),
    ({'subsets': ['unfixed-at-head']}, 'must agree'),
    ({'regressed_by': ['HEAD']}, 'regressed_by'),
    ({'confidence': 'sure'}, 'confidence'),
    ({'fix': {'status': 'fixed', 'commit': 'def5678', 'after': []}}, 'must set fix.rewrite'),
    ({'fix': {'status': 'fixed', 'commit': 'def5678', 'after': [], 'rewrite': 'yes'}}, 'true or false'),
    ({'related_cases': 'book-002'}, 'related_cases must be'),
])
def test_each_rule(changes, fragment):
    problems = e1.validate_case(_case(**changes))
    assert any(fragment in p for p in problems), problems


def test_absence_case_is_valid():
    assert e1.validate_case(_case(established=[], established_by_absence='never told')) == []


def test_rewrite_fix_needs_no_after_spans():
    assert e1.validate_case(_case(fix={'status': 'fixed', 'commit': 'def5678',
                                       'after': [], 'rewrite': True})) == []


def test_related_case_must_exist():
    problems = e1.validate_corpus([_case(related_cases=['book-009'])])
    assert any("'book-009' does not exist" in p for p in problems)


def test_duplicate_ids_reported():
    assert any('duplicate id' in p for p in e1.validate_corpus([CASE, CASE]))


def test_load_cases_checks_repo_name(tmp_path):
    (tmp_path / 'book.json').write_text(json.dumps({'repo': 'other', 'cases': []}))
    with pytest.raises(ValueError, match='expected'):
        e1.load_cases(str(tmp_path))


def _cases(repo, n):
    return [_case(id=f'{repo}-{i:03d}', repo=repo) for i in range(1, n + 1)]


def test_holdout_is_stratified_and_frozen():
    cases = _cases('a', 10) + _cases('b', 5)
    first = e1.assign_holdout(cases, [])
    assert sum(i.startswith('a-') for i in first) == 2
    assert sum(i.startswith('b-') for i in first) == 1
    grown = e1.assign_holdout(cases + _cases('a', 20)[10:], first)
    assert set(first) <= set(grown)
    assert sum(i.startswith('a-') for i in grown) == 4
    shrunk = e1.assign_holdout(cases[:1], first)
    assert set(shrunk) <= {'a-001'} and not set(shrunk) - {c['id'] for c in cases[:1]}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'corpus'
    book = root / 'book'
    (book / 'scenes').mkdir(parents=True)
    (book / 'scenes' / '90.md').write_text('He sat.\n“Five hours,” he   said.\n')
    git = ['git', '-C', str(book), '-c', 'user.email=t@t', '-c', 'user.name=t']
    subprocess.run(['git', 'init', '-q', str(book)], check=True)
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'x'], check=True)
    sha = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    return root, sha


def test_verify_quotes(repo):
    root, sha = repo
    span = {**SPAN, 'commit': sha}
    good = _case(established=[], established_by_absence='x', contradicted=[span],
                 fix={'status': 'unfixed'}, subsets=['unfixed-at-head'])
    assert e1.verify_quotes([good], str(root)) == []  # curly quotes and spacing normalized
    wrong = _case(**{**good, 'contradicted': [{**span, 'quote': 'Six hours'}]})
    missing = _case(**{**good, 'contradicted': [{**span, 'path': 'scenes/91.md'}]})
    assert 'quote not found' in e1.verify_quotes([wrong], str(root))[0]
    assert 'does not exist' in e1.verify_quotes([missing], str(root))[0]
    ghost = _case(**{**good, 'regressed_by': ['deadbee']})
    assert 'deadbee does not exist' in e1.verify_quotes([ghost], str(root))[0]
    assert 'not cloned' in e1.verify_quotes([_case(repo='gone', id='gone-001')], str(root))[0]


def test_cli_holdout_refuses_a_malformed_corpus(tmp_path):
    cases_dir = tmp_path / 'cases'
    cases_dir.mkdir()
    (cases_dir / 'book.json').write_text(json.dumps({'repo': 'book', 'cases': [_case(code='X')]}))
    holdout = tmp_path / 'holdout.json'
    assert cli.main(['holdout', '--cases-dir', str(cases_dir), '--holdout-file', str(holdout)]) == 1
    assert not holdout.exists()
    (cases_dir / 'book.json').write_text(json.dumps({'repo': 'book', 'cases': _cases('book', 5)}))
    assert cli.main(['holdout', '--cases-dir', str(cases_dir), '--holdout-file', str(holdout)]) == 0
    assert json.loads(holdout.read_text())['ids'] == e1.assign_holdout(_cases('book', 5), [])


def test_the_e1_suite_loads_and_reports():
    import harness
    suites = {s.name: s for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert 'e1-corpus' in suites

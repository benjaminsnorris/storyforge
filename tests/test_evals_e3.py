import copy
import sys

import pytest

from conftest import PLUGIN_DIR

sys.path.insert(0, str(PLUGIN_DIR / 'evals'))

import harness  # noqa: E402,F401
import e3  # noqa: E402
from test_evals_e1 import CASE  # noqa: E402


@pytest.mark.parametrize('text, verdict', [
    ('{"verdict": "captured", "evidence": "x"}', 'captured'),
    ('ok\n{"verdict": "partial", "evidence": ""}', 'partial'),
])
def test_parse_verdict(text, verdict):
    assert e3.parse_verdict(text)['verdict'] == verdict


@pytest.mark.parametrize('text', ['nope', '{"verdict": "yes"}'])
def test_unreadable_verdict_raises(text):
    with pytest.raises(ValueError):
        e3.parse_verdict(text)


def test_judge_prompt_carries_the_fact_and_all_three_extractions(monkeypatch):
    from storyforge import api
    seen = {}
    monkeypatch.setattr(api, 'invoke', lambda p, m, **k: seen.setdefault('p', p) and {
        'content': [{'type': 'text', 'text': '{"verdict": "missing", "evidence": ""}'}]})
    item = {'case': CASE, 'span': CASE['established'][0], 'scene': '44'}
    assert e3.judge(item, 'KNOWLEDGE OUT', 'PHYS OUT', 'COMMIT OUT')['verdict'] == 'missing'
    assert 'Three hours. Bend to Portland.' in seen['p']
    assert all(out in seen['p'] for out in ('KNOWLEDGE OUT', 'PHYS OUT', 'COMMIT OUT'))


def test_select_reports_exclusions(monkeypatch, tmp_path):
    import e1
    no_prose = copy.deepcopy(CASE)
    no_prose.update(id='book-002', established=[{**CASE['established'][0], 'source': 'reference'}])
    held = copy.deepcopy(CASE)
    held.update(id='book-003')
    monkeypatch.setattr(e1, 'load_cases', lambda: [CASE, no_prose, held])
    monkeypatch.setattr(e1, 'load_holdout', lambda: ['book-003'])
    items, excluded = e3.select(str(tmp_path))
    assert items == []
    assert excluded == {'book not cloned': ['book-001'], 'no prose established span': ['book-002'],
                        'holdout': ['book-003']}


def test_the_e3_suite_loads():
    names = {s.name for s in harness.discover(str(PLUGIN_DIR / 'evals' / 'suites'))}
    assert 'e3-extraction' in names


def test_the_commitments_call_thinks_as_the_gate_extraction_does(monkeypatch, project_dir):
    """#743: E3 measures the gate's extraction setting (`gate.EXTRACT_THINK`)
    on the commitments call; the knowledge and physical-state calls keep
    the default."""
    from storyforge import api, gate, persistence
    sent = {}

    def fake(prompt, model, **k):
        kind = k['label'].split()[1]
        sent[kind] = k.get('think', True)
        text = '{"commitments": []}' if kind == 'commitments' else '{}'
        return {'content': [{'type': 'text', 'text': text}]}
    monkeypatch.setattr(api, 'invoke', fake)
    monkeypatch.setattr(persistence, 'judge',
                        lambda *a, **k: persistence.Verdict(kept=[], dropped=[]))
    e3.extract(project_dir, 'act1-sc01')
    assert sent == {'knowledge': True, 'physical': True, 'commitments': True}
    monkeypatch.setattr(gate, 'EXTRACT_THINK', False)
    e3.extract(project_dir, 'act1-sc01')
    assert sent == {'knowledge': True, 'physical': True, 'commitments': False}

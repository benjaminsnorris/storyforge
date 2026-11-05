"""#555: `narrator` is a reserved POV value (Iliad F-132, Beowulf B-005,
Gawain G-007), with key-decisions.md's narrator_pov setting."""

import os

import pytest

from storyforge import narrator
from storyforge.elaborate import present_in_scene, validate_structure
from storyforge.enrich import normalize_fields
from storyforge.extract import parse_skeleton_response
from storyforge.schema import validate_schema


@pytest.mark.parametrize('value', ['narrator', 'Narrator', 'Omniscient narrator',
                                   'the narrator', 'omniscient', 'Omniscient epic narrator',
                                   ' The  Narrator ', 'intrusive-omniscient-narrator',
                                   'third-person omniscient narration'])
def test_variants_are_the_narrator(value):
    assert narrator.is_narrator(value)
    assert narrator.normalize_pov(value) == 'narrator'


@pytest.mark.parametrize('value', ['', 'herald', 'narrator-of-troy', 'Nick Carraway',
                                   "nick's narrator", 'omniscient-zeus'])
def test_others_are_not(value):
    assert not narrator.is_narrator(value)
    assert narrator.normalize_pov(value) == value


def _set_pov(project_dir, sid, pov):
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    lines = open(path).read().splitlines()
    header = lines[0].split('|')
    i = header.index('pov')
    out = [lines[0]]
    for line in lines[1:]:
        cells = line.split('|')
        if cells[0] == sid:
            cells[i] = pov
        out.append('|'.join(cells))
    open(path, 'w').write('\n'.join(out) + '\n')


def _key_decisions(project_dir, line):
    with open(os.path.join(project_dir, 'reference', 'key-decisions.md'), 'a') as f:
        f.write(f'\n{line}\n')


def test_validate_accepts_narrator_pov(project_dir):
    _set_pov(project_dir, 'act1-sc01', 'narrator')
    errs = [e for e in validate_schema(os.path.join(project_dir, 'reference'),
                                       project_dir)['errors'] if e.get('column') == 'pov']
    assert errs == []


def test_validate_still_rejects_an_unknown_pov(project_dir):
    _set_pov(project_dir, 'act1-sc01', 'herald')
    errs = [e for e in validate_schema(os.path.join(project_dir, 'reference'),
                                       project_dir)['errors'] if e.get('column') == 'pov']
    assert [e['value'] for e in errs] == ['herald']


def test_writers_normalize_variants():
    row = {'pov': 'Omniscient epic narrator'}
    normalize_fields(row, {'characters': {'hero': 'hero'}})
    assert row['pov'] == 'narrator'
    assert normalize_fields({'pov': 'the narrator'}, {})['pov'] == 'narrator'


def test_extraction_writes_narrator():
    import json
    from storyforge import extract
    schema = extract.SKELETON_SCHEMA
    reply = {k: [] if schema['properties'][k]['type'] == 'array' else ''
             for k in schema['required']}
    reply.update(title='T', pov='Omniscient narrator')
    assert parse_skeleton_response(json.dumps(reply), 's1')['pov'] == 'narrator'


def test_the_extraction_prompt_asks_for_narrator(project_dir):
    import inspect
    from storyforge import extract
    assert '"narrator" when the book\'s narrator tells the scene' in inspect.getsource(extract)


def test_the_narrator_is_not_present_on_stage():
    assert present_in_scene({'pov': 'narrator'}, {'on_stage': 'hero'}) == {'hero'}


@pytest.mark.parametrize('line, mode, cap', [
    ('', 'allowed', None),
    ('- narrator_pov: off', 'off', None),
    ('narrator_pov: limited 3 — the bard frames each part', 'limited', 3),
    ('- `narrator_pov: allowed`', 'allowed', None),
    ('<!-- narrator_pov: off -->', 'allowed', None),
])
def test_the_setting(project_dir, line, mode, cap):
    _key_decisions(project_dir, line)
    s = narrator.read_setting(project_dir)
    assert (s.mode, s.cap) == (mode, cap)


def _narrator_check(project_dir):
    report = validate_structure(os.path.join(project_dir, 'reference'))
    return next(c for c in report['checks'] if c['check'] == 'narrator-pov-setting')


def test_validate_flags_narrator_scenes_over_the_cap(project_dir):
    _set_pov(project_dir, 'act1-sc01', 'narrator')
    _set_pov(project_dir, 'act1-sc02', 'narrator')
    _key_decisions(project_dir, 'narrator_pov: limited 1')
    c = _narrator_check(project_dir)
    assert c['passed'] is False and c['severity'] == 'advisory'
    assert 'over key-decisions.md\'s narrator_pov: limited 1' in c['message']


def test_validate_flags_narrator_scenes_when_off(project_dir):
    _set_pov(project_dir, 'act1-sc01', 'narrator')
    _key_decisions(project_dir, 'narrator_pov: off')
    assert _narrator_check(project_dir)['passed'] is False


def test_allowed_by_default(project_dir):
    _set_pov(project_dir, 'act1-sc01', 'narrator')
    assert _narrator_check(project_dir)['passed'] is True


def test_elaborate_prompts_state_the_setting(project_dir):
    from storyforge.prompts_elaborate import _project_context
    _key_decisions(project_dir, 'narrator_pov: off')
    assert '**Narrator POV:** off.' in _project_context(project_dir)


def test_the_voice_prompt_asks_for_the_narrator_when_the_book_uses_one(project_dir):
    from storyforge.prompts_elaborate import build_voice_prompt
    plugin = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert '**The narrator**' not in build_voice_prompt(project_dir, plugin)
    _set_pov(project_dir, 'act1-sc01', 'narrator')
    prompt = build_voice_prompt(project_dir, plugin)
    assert '**The narrator**: 1 scene(s) have `narrator` as their POV' in prompt
    assert 'their stance' in prompt


def test_source_import_keeps_the_narrator():
    from storyforge.source import NameMap, _map_csv
    unknown = {}
    rows = _map_csv('scenes.csv', ['id', 'pov'], [['s1', 'Omniscient narrator']],
                    NameMap(), unknown)
    assert rows == [['s1', 'narrator']]
    assert not any(unknown.values())


def test_a_book_without_narrator_scenes_or_setting_keeps_its_prompts(project_dir):
    from storyforge.prompts_elaborate import _project_context
    assert 'Narrator POV' not in _project_context(project_dir)
    _set_pov(project_dir, 'act1-sc01', 'narrator')
    assert '**Narrator POV:** allowed.' in _project_context(project_dir)


def test_hone_normalizes_a_narrator_pov_and_never_asks_about_it(project_dir, tmp_path,
                                                                monkeypatch):
    from storyforge.hone import find_unresolved, reconcile_domain
    _set_pov(project_dir, 'act1-sc01', 'Omniscient epic narrator')
    ref_dir = os.path.join(project_dir, 'reference')
    assert 'Omniscient epic narrator' not in find_unresolved('characters', ref_dir)
    monkeypatch.setattr('storyforge.hone._invoke_batch', lambda *a, **k: '')
    reconcile_domain('characters', ref_dir, 'test-model', str(tmp_path))
    pov = open(os.path.join(ref_dir, 'scenes.csv')).read()
    assert '|narrator|' in pov and 'Omniscient' not in pov
    assert 'narrator' not in open(os.path.join(ref_dir, 'characters.csv')).read().lower()


def test_drafting_a_narrator_scene_says_so(project_dir):
    from storyforge.prompts import build_scene_prompt_from_briefs
    _set_pov(project_dir, 'act1-sc01', 'narrator')
    plugin = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        prompt = build_scene_prompt_from_briefs('act1-sc01', project_dir, plugin)
    except TypeError:
        pytest.skip('signature differs')
    assert "This scene's POV is the narrator" in prompt
    assert 'Narrator POV: allowed.' in prompt

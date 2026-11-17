"""The shared fixture as an illustrated project, and one walk through it (#288).

`tests/fixtures/test-project` carries a canon tier, a two-row illustration
plan, and a visual-state log. Every illustration suite builds on it, so these
tests hold it coherent: ids that match the registries, scenes the chapter map
positions, evidence and search terms the prose really contains, and no finding
on the unmodified fixture. The failure #288 is about is the search terms going
quietly wrong: when no tracked entity is named where the audit looks, its
candidate set is empty, and every test that believes it is exercising the model
path takes the no-call branch and still passes.

Then one end-to-end run, canon -> plan -> state -> prompts -> packet, on the
fixture as it ships, with the API mocked at `cmd_illustrate._invoke` as the
other illustration suites mock it.
"""

import json
import os

import pytest

from illustration_helpers import (
    BOOK_LEVEL_CANON, ENTITY_CANON, FIXTURE_APPEARANCES, FIXTURE_DISPLAY_NAMES,
    FIXTURE_PLAN_IDS, fixture_anchors, unstate_entity, write_canon_file,
)
from fixture_helpers import FIXTURE_DIR
from storyforge import canon, cmd_illustrate, packet
from storyforge import illustrations as ill
from storyforge import visual_state as vs
from storyforge.cmd_cleanup import report_canon_files


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)


def _positioned_drafted_scenes(project_dir):
    """scene_id -> normalized prose for every scene with a reading position."""
    prose = {}
    for scene_id in ill._scene_order(project_dir):
        text = ill.read_scene_raw(project_dir, scene_id)
        if text is not None:
            prose[scene_id] = vs._scene_haystack(text)
    return prose


# ============================================================================
# The canon tier
# ============================================================================

def test_the_fixture_copy_carries_the_canon_tree_and_the_plan(project_dir):
    """`copy_fixture` copies only files git would commit, so an uncommitted
    fixture file is absent from every test's copy."""
    for canon_id in (*BOOK_LEVEL_CANON, *ENTITY_CANON):
        assert canon.resolve_canon_path(project_dir, canon_id), canon_id
    assert os.path.isfile(ill.plan_path(project_dir))
    assert os.path.isfile(vs.state_path(project_dir))


def test_the_canon_files_carry_what_the_helpers_say(project_dir):
    """`illustration_helpers` documents the anchors tests compare against."""
    assert canon.anchor_texts(project_dir) == fixture_anchors()
    for canon_id, (_type, body) in BOOK_LEVEL_CANON.items():
        path = canon.resolve_canon_path(project_dir, canon_id)
        assert canon.embeddable_block_text(path).strip() == body


def test_every_canon_file_is_exactly_what_write_canon_file_makes(tmp_path):
    """Byte for byte, from the constants. The fixture files were written by
    `write_canon_file`, so a hand edit to either side shows up here rather
    than as a test elsewhere comparing against a constant the file no longer
    matches."""
    specs = {cid: ('', ctype, body)
             for cid, (ctype, body) in BOOK_LEVEL_CANON.items()}
    specs.update(ENTITY_CANON)
    assert set(FIXTURE_APPEARANCES) == set(specs)
    assert set(FIXTURE_DISPLAY_NAMES) <= set(ENTITY_CANON)
    for canon_id, (subdir, canon_type, body) in specs.items():
        appears_in, first = FIXTURE_APPEARANCES[canon_id]
        made = write_canon_file(
            str(tmp_path), canon_id=canon_id, canon_type=canon_type,
            body=body, subdir=subdir, appears_in=appears_in,
            first_appearance=first,
            display_name=FIXTURE_DISPLAY_NAMES.get(canon_id, ''))
        shipped = FIXTURE_DIR / os.path.relpath(made, str(tmp_path))
        assert shipped.read_bytes() == open(made, 'rb').read(), canon_id
    shipped_files = {
        os.path.relpath(os.path.join(d, name),
                        FIXTURE_DIR / 'reference' / 'canon')
        for d, _dirs, names in os.walk(FIXTURE_DIR / 'reference' / 'canon')
        for name in names}
    assert len(shipped_files) == len(specs), sorted(shipped_files)


def test_the_reference_tier_is_complete(project_dir):
    assert ill.missing_reference_sections(project_dir) == []
    assert ill.has_reference_tier(project_dir)


def test_every_canon_file_is_clean_and_matches_a_registry_row(project_dir):
    """No missing frontmatter key, and every entity id is a registry id
    (`canon_missing_registry_entry` otherwise)."""
    assert report_canon_files(project_dir) == []


# ============================================================================
# The plan
# ============================================================================

def test_the_plan_rows_are_in_reading_order(project_dir):
    assert tuple(r['id'] for r in ill.read_plan(project_dir)) == \
        FIXTURE_PLAN_IDS


def test_the_plan_carries_a_register_and_a_state_override(project_dir):
    rows = ill.read_plan(project_dir)
    assert {r['register'] for r in rows} == {'brightest', 'darkest'}
    overrides = [r for r in rows if r['state_override']]
    assert overrides
    for row in overrides:
        parsed = vs.parse_state_override(row['state_override'])
        assert parsed.applied and not parsed.skipped and not parsed.prose_keys


def test_every_plan_row_is_positioned_anchored_and_its_refs_have_canon(
        project_dir):
    order = ill._scene_order(project_dir)
    anchors = fixture_anchors()
    for row in ill.read_plan(project_dir):
        assert row['scene_id'] in order, row['id']
        prose = ill.strip_markers(
            ill.read_scene_raw(project_dir, row['scene_id']))
        assert ill.find_anchor(prose, row['anchor'])['count'] == 1, row['id']
        for ref in ill._split_array(row['canon_refs']):
            assert ref in anchors, (row['id'], ref)


# ============================================================================
# The visual-state log
# ============================================================================

def test_every_transition_evidence_is_verbatim_in_its_scene(project_dir):
    for transition in vs.read_transitions(project_dir):
        prose = ill.strip_markers(
            ill.read_scene_raw(project_dir, transition['from_scene']))
        assert ill.find_anchor(prose, transition['evidence']) is not None, \
            transition


def test_every_tracked_entity_is_named_by_the_prose(project_dir):
    """Each entity's search terms appear in some positioned, drafted scene —
    the prose the audit reads. This is necessary, not sufficient, for the
    entity to make a scene a candidate: the audit also needs the mention at or
    after its first transition and outside its own transition scenes, which
    `test_the_entities_that_can_make_a_candidate` pins."""
    prose = _positioned_drafted_scenes(project_dir)
    terms = vs.prepass(project_dir)['search_terms']
    assert set(terms) == {t['entity'] for t in vs.read_transitions(project_dir)}
    for entity, entity_terms in terms.items():
        assert any(vs._mentions(text, term)
                   for text in prose.values() for term in entity_terms), \
            f'{entity}: none of {entity_terms} appears in {sorted(prose)}'


def test_the_unmodified_fixture_has_no_illustration_finding(project_dir):
    """A coherent project: anything a suite asserts about a finding, it
    arranged itself."""
    assert vs.prepass(project_dir)['findings'] == []
    assert ill.validate_plan(project_dir) == []


def test_the_audit_has_candidates_on_the_fixture(project_dir):
    """Non-empty, or the contradiction pass is never exercised by default."""
    assert vs.prepass(project_dir)['candidate_scenes'] == ['act1-sc02']


def test_the_entities_that_can_make_a_candidate(project_dir):
    """Under the audit's own rule: named in a positioned scene at or after
    the entity's first transition, and not one of its transition scenes.

    Only two qualify, and `dorren-hayle` only through act1-sc02's frontmatter
    `pov:` line. The other three are named in prose, but only at or before
    their own transition, so they never add a candidate. Pinned rather than
    extended: widening it means new prose in act2-sc01, which some forty test
    files read."""
    order = ill._scene_order(project_dir)
    prose = _positioned_drafted_scenes(project_dir)
    transitions = vs.read_transitions(project_dir)
    able = set()
    for entity, terms in vs.prepass(project_dir)['search_terms'].items():
        own = {order[t['from_scene']] for t in transitions
               if t['entity'] == entity}
        if any(order[sid] >= min(own) and order[sid] not in own
               and any(vs._mentions(text, term) for term in terms)
               for sid, text in prose.items()):
            able.add(entity)
    assert able == {'village', 'dorren-hayle'}


def test_unstate_entity_refuses_an_entity_the_log_does_not_have(project_dir):
    """A typo would leave the state in place, and the test asserting its
    absence would be testing nothing."""
    with pytest.raises(ValueError):
        unstate_entity(project_dir, 'cartography-ofice')


def test_the_fixture_keeps_scenes_the_chapter_map_omits(project_dir):
    """Six scenes in scenes.csv, three in the chapter map: the skew is kept on
    purpose (#288's comment), and the packet's grid must name the rest."""
    assert packet.state_grid(project_dir)['unpositioned'] == [
        'act2-sc02', 'act2-sc03', 'new-x1']


# ============================================================================
# End to end: canon -> plan -> state -> prompts -> packet
# ============================================================================

_PROMPT_BODY = ('### Scene\n\nA long drafting hall at morning.\n\n'
                '### Subject\n\nOne figure at a slanted table.\n')


def test_canon_plan_state_prompts_packet_end_to_end(project_dir, monkeypatch,
                                                    capsys):
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    calls: dict[str, list[tuple[str, str]]] = {}

    def _invoke(_project_dir, prompt, operation, **kwargs):
        calls.setdefault(operation, []).append(
            (kwargs.get('target', ''), prompt))
        if operation == 'illustrate-audit':
            return json.dumps({'contradictions': []})
        if operation == 'illustrate-prompt':
            return _PROMPT_BODY
        raise AssertionError(f'unexpected model call: {operation}')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _invoke)
    log_before = open(vs.state_path(project_dir), 'rb').read()
    assert any('never been run' in g
               for g in packet.resolve(project_dir)['gaps'])

    # State: the audit reads the candidate scene against the log, and the
    # model is actually called — the path the fixture exists to exercise.
    assert cmd_illustrate.main(['--audit']) == 0
    assert len(calls.get('illustrate-audit', [])) == 1
    audit_prompt = calls['illustrate-audit'][0][1]
    # Only in act1-sc02's prose, not in any log cell: the scene was read.
    assert 'Not even a contour line' in audit_prompt
    # act2-sc01 is no candidate, so its prose is not paid for.
    assert 'She checked her compass' not in audit_prompt
    assert open(vs.state_path(project_dir), 'rb').read() == log_before
    assert not any('never been run' in g
                   for g in packet.resolve(project_dir)['gaps'])

    # Prompts: one request per plan row, each carrying its canon anchors and
    # the state at its scene, with the row's override overlaid.
    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    requests = dict(calls['illustrate-prompt'])
    assert set(requests) == set(FIXTURE_PLAN_IDS)
    anchors = fixture_anchors()
    first, second = (requests[i] for i in FIXTURE_PLAN_IDS)
    assert anchors['dorren-hayle'] in first
    assert anchors['cartography-office'] in first
    assert 'black waistcoat, sleeves buttoned' in first
    assert anchors['maps'] in second
    assert 'paperweight' in second
    assert 'the new survey sheet under the overlays' not in second
    plan = ill.read_plan_as_map(project_dir)
    for illus_id in FIXTURE_PLAN_IDS:
        prompt_file = plan[illus_id]['prompt_file']
        assert prompt_file
        with open(os.path.join(project_dir, prompt_file),
                  encoding='utf-8') as f:
            assert 'A long drafting hall at morning' in f.read()

    # Packet: assembly only, every anchor byte-identical, one prompt per row,
    # and nothing stale or drifted afterwards.
    def _no_call(*a, **k):
        raise AssertionError('--package makes no API call')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _no_call)
    assert cmd_illustrate.main(['--package']) == 0
    with open(packet.packet_file(project_dir, 'canon.md'),
              encoding='utf-8') as f:
        canon_md = f.read()
    for text in anchors.values():
        assert text in canon_md
    assert sorted(os.listdir(packet.image_prompts_dir(project_dir))) == \
        sorted(f'{i}.md' for i in FIXTURE_PLAN_IDS)
    with open(packet.image_prompt_file(project_dir, 'the-blank-page'),
              encoding='utf-8') as f:
        assert 'paperweight' in f.read()
    assert packet.packet_stale(project_dir) == []
    assert packet.anchor_copy_drift(project_dir) == []
    assert ill.validate_plan(project_dir) == []

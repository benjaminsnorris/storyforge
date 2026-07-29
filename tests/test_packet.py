"""Tests for `storyforge.packet` — what goes in the handoff packet (#278 ph3).

Two properties matter more than the rest and are asserted first: an anchor
copied into the packet is byte-identical to its canon source, and a gap in the
data is *recorded* rather than filtered away.

`packet_project` seeds canon files, a plan, and state transitions into a copy
of the fixture. The shared fixture deliberately has none of those (it carries
only phase 2's visual-state.csv), and seeding them there would change what
every cleanup/validate/canon test sees.
"""

import os

import pytest

from storyforge import canon, packet
from storyforge import illustrations as ill
from illustration_helpers import seed_packet_project


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)


@pytest.fixture
def packet_project(project_dir):
    seed_packet_project(project_dir)
    return project_dir


# ============================================================================
# The byte-identity invariant
# ============================================================================

def test_anchors_are_copied_byte_identically(packet_project):
    """The whole mechanism is that every prompt sends the same bytes."""
    src = canon.anchor_texts(packet_project)
    assert src, 'fixture needs at least one entity canon file'
    got = packet.resolve(packet_project)['anchors']
    for canon_id, text in src.items():
        assert got[canon_id] == text, f'{canon_id} was altered in the packet'


def test_every_canon_anchor_reaches_the_packet(packet_project):
    """Presence as well as fidelity: a dropped anchor is not "identical"."""
    src = canon.anchor_texts(packet_project)
    assert set(packet.resolve(packet_project)['anchors']) == set(src)


# ============================================================================
# Gaps — the coverage record
# ============================================================================

def test_a_missing_book_level_file_is_recorded_as_a_gap(packet_project):
    from storyforge.prompts_illustrate import CANON_PLAN
    cid = CANON_PLAN[0][0]
    path = canon.resolve_canon_path(packet_project, cid)
    assert path, 'the seeded project should have this canon file'
    os.remove(path)
    gaps = packet.resolve(packet_project)['gaps']
    assert any(cid in g for g in gaps), f'{cid} absence must be a recorded gap'


def test_an_unfilled_book_level_file_is_a_different_gap(packet_project):
    """Absent and scaffolded need different fixes, so they read differently."""
    from storyforge.prompts_illustrate import CANON_PLAN
    cid = CANON_PLAN[1][0]
    path = canon.resolve_canon_path(packet_project, cid)
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(
            'Warm lamplight and umber for the office; cold slate blue for the '
            'blank places on the map. Camera at standing eye height.',
            'TODO — write this'))
    gap = next(g for g in packet.resolve(packet_project)['gaps'] if cid in g)
    assert 'scaffold' in gap
    assert 'has no file' not in gap


def test_an_unresolvable_canon_ref_is_a_gap_not_a_silent_drop(packet_project):
    rows = ill.read_plan(packet_project)
    assert rows, 'the seeded project should have plan rows'
    rows[0]['canon_refs'] = 'nobody-by-that-name'
    ill.write_plan(packet_project, rows)
    gaps = packet.resolve(packet_project)['gaps']
    assert any('nobody-by-that-name' in g for g in gaps)


def test_an_empty_beat_is_a_gap_and_the_entry_says_so(packet_project):
    rows = ill.read_plan(packet_project)
    rows[0]['beat'] = ''
    ill.write_plan(packet_project, rows)
    contents = packet.resolve(packet_project)
    assert any(rows[0]['id'] in g and 'beat' in g for g in contents['gaps'])
    entry = next(e for e in contents['entries'] if e['id'] == rows[0]['id'])
    assert entry['beat'] == packet.NOT_RECORDED


def test_an_empty_subject_is_a_gap(packet_project):
    rows = ill.read_plan(packet_project)
    rows[0]['subject'] = ''
    ill.write_plan(packet_project, rows)
    gaps = packet.resolve(packet_project)['gaps']
    assert any(rows[0]['id'] in g and 'in frame' in g for g in gaps)


def test_an_entity_with_no_state_at_its_scene_is_a_gap(packet_project):
    """`cartography-office` has a canon file and no transition, on purpose."""
    gaps = packet.resolve(packet_project)['gaps']
    assert any('cartography-office' in g and 'visual state' in g
               for g in gaps)


def test_an_unpositioned_scene_is_reported_as_such(packet_project):
    """`new-x1` is active in scenes.csv but absent from the chapter map, so no
    state resolves for it — which is a different problem from an unstated
    entity and must not be reported as one."""
    rows = ill.read_plan(packet_project)
    rows[0]['scene_id'] = 'new-x1'
    ill.write_plan(packet_project, rows)
    gaps = packet.resolve(packet_project)['gaps']
    assert any('new-x1' in g and 'reading position' in g for g in gaps)


def test_a_scene_that_does_not_exist_is_reported(packet_project):
    rows = ill.read_plan(packet_project)
    rows[0]['scene_id'] = 'no-such-scene'
    ill.write_plan(packet_project, rows)
    gaps = packet.resolve(packet_project)['gaps']
    assert any('no-such-scene' in g and 'active scene' in g for g in gaps)


def test_a_never_run_audit_is_a_gap(packet_project):
    gaps = packet.resolve(packet_project)['gaps']
    assert any('audit' in g and 'never been run' in g for g in gaps)


def test_a_stale_audit_is_a_gap(packet_project):
    from storyforge import visual_state as vs
    vs.write_provenance(packet_project, [
        {'scene_id': 'act1-sc01', 'digest': 'deadbeef',
         'audited_at': '2026-07-01'},
    ])
    gaps = packet.resolve(packet_project)['gaps']
    assert any('audit' in g and 'stale' in g and 'act1-sc01' in g
               for g in gaps)
    assert not any('never been run' in g for g in gaps)


def test_an_empty_plan_is_a_gap(project_dir):
    """No plan means the packet describes no illustrations — say so."""
    from illustration_helpers import seed_canon
    seed_canon(project_dir)
    gaps = packet.resolve(project_dir)['gaps']
    assert any('no rows' in g for g in gaps)


def test_no_populated_anchor_is_a_gap(project_dir):
    from illustration_helpers import seed_illustration_plan
    seed_illustration_plan(project_dir)
    gaps = packet.resolve(project_dir)['gaps']
    assert any('continuity anchor' in g for g in gaps)


def test_a_superseded_row_gets_no_entry(packet_project):
    rows = ill.read_plan(packet_project)
    rows[0]['status'] = 'superseded'
    ill.write_plan(packet_project, rows)
    ids = [e['id'] for e in packet.resolve(packet_project)['entries']]
    assert rows[0]['id'] not in ids
    assert rows[1]['id'] in ids


# ============================================================================
# Entry shape
# ============================================================================

def test_entries_are_in_reading_order(packet_project):
    entries = packet.resolve(packet_project)['entries']
    assert [e['id'] for e in entries] == ['the-finest-cartographer',
                                          'the-blank-page']


def test_state_resolves_the_matrix_and_overlays_the_override(packet_project):
    entries = {e['id']: e for e in packet.resolve(packet_project)['entries']}
    # act1-sc02 resolves maps -> "the new survey blank…", which the row's
    # state_override then replaces for this image only.
    assert 'paperweight' in entries['the-blank-page']['state']
    assert 'blank where the village was' not in \
        entries['the-blank-page']['state']
    # And the earlier illustration is unaffected by that override.
    assert 'paperweight' not in entries['the-finest-cartographer']['state']


def test_state_lists_only_the_entities_the_row_names(packet_project):
    """Sending the whole cast invites the model to draw people who are not
    in the frame. `village` and `master-survey` are tracked in the fixture
    matrix and named by no plan row."""
    entries = {e['id']: e for e in packet.resolve(packet_project)['entries']}
    assert 'master-survey' not in entries['the-blank-page']['state']
    assert 'village' not in entries['the-blank-page']['state'].lower()


def test_state_uses_display_names_not_slugs(packet_project):
    entries = {e['id']: e for e in packet.resolve(packet_project)['entries']}
    assert 'Dorren Hayle' in entries['the-finest-cartographer']['state']


def test_aspect_comes_from_the_layout_then_the_composition(packet_project):
    rows = ill.read_plan(packet_project)
    rows[0]['layout'] = 'double_page'
    ill.write_plan(packet_project, rows)
    entries = {e['id']: e for e in packet.resolve(packet_project)['entries']}
    assert entries['the-finest-cartographer']['aspect'] == 'landscape'
    # The second row says "square" in its composition and has no spread layout.
    assert entries['the-blank-page']['aspect'] == 'square'


def test_contrast_names_the_register_and_the_preceding_illustration(
        packet_project):
    entries = {e['id']: e for e in packet.resolve(packet_project)['entries']}
    assert 'brightest' in entries['the-finest-cartographer']['contrast']
    assert 'darkest' in entries['the-blank-page']['contrast']
    assert 'the-finest-cartographer' in entries['the-blank-page']['contrast']


def test_an_author_absent_column_is_carried_into_the_entry(packet_project):
    """`absent` is an author-added column (write_plan preserves extras). It is
    one of the two deliberate exceptions to positive framing."""
    rows = ill.read_plan(packet_project)
    rows[0]['absent'] = 'Tessa Merrin. A second master survey.'
    ill.write_plan(packet_project, rows)
    entries = {e['id']: e for e in packet.resolve(packet_project)['entries']}
    assert entries['the-finest-cartographer']['absent'] == \
        'Tessa Merrin. A second master survey.'
    assert entries['the-blank-page']['absent'] == ''


def test_the_composition_note_becomes_the_image_specific_note(packet_project):
    entries = {e['id']: e for e in packet.resolve(packet_project)['entries']}
    assert 'lamp behind her' in entries['the-finest-cartographer']['notes']


# ============================================================================
# The dense state view
# ============================================================================

def test_state_grid_walks_the_log_forward(packet_project):
    grid = packet.state_grid(packet_project)
    # Chapter map order: act1-sc01, act1-sc02, act2-sc01. new-x1 is unmapped.
    assert grid['scenes'] == ['act1-sc01', 'act1-sc02', 'act2-sc01']
    assert 'dorren-hayle' in grid['entities']
    # dorren-hayle transitions at act1-sc01 and persists forward.
    assert grid['cells']['act2-sc01']['dorren-hayle'] == \
        grid['cells']['act1-sc01']['dorren-hayle']
    # maps transitions at act1-sc02, so it is absent before that.
    assert 'maps' not in grid['cells']['act1-sc01']
    assert 'maps' in grid['cells']['act1-sc02']


def test_state_grid_names_scenes_it_cannot_position(packet_project):
    """A grid that silently omitted a drafted scene would read as coverage.

    The fixture's scenes.csv has six active scenes and its chapter map lists
    three, so three are unpositioned — checked against the file, not assumed.
    """
    assert packet.state_grid(packet_project)['unpositioned'] == [
        'act2-sc02', 'act2-sc03', 'new-x1']


# ============================================================================
# Determinism
# ============================================================================

def test_resolve_is_deterministic(packet_project):
    assert packet.resolve(packet_project) == packet.resolve(packet_project)


def test_resolve_on_a_bare_project_does_not_raise(project_dir):
    contents = packet.resolve(project_dir)
    assert contents['entries'] == []
    assert contents['gaps']


# ============================================================================
# The written packet, checked against its sources
# ============================================================================
#
# These exercise the *file-reading* half of the byte-identity invariant, which
# `--package` (task 3) then drives end to end. The helper writes the anchor
# copies through `packet.anchor_block` — the same function the renderer uses —
# so the marker format has exactly one definition.

def _write_packet(project_dir, *, anchors=None):
    """Write a stand-in packet: six files, with anchor copies in canon.md."""
    src = canon.anchor_texts(project_dir) if anchors is None else anchors
    labels = canon.anchor_display_names(project_dir)
    body = '\n\n'.join(
        packet.anchor_block(cid, text,
                            labels[cid]['label'] if cid in labels else cid)
        for cid, text in src.items())
    os.makedirs(packet.packet_dir(project_dir), exist_ok=True)
    for name in packet.PACKET_FILES:
        with open(packet.packet_file(project_dir, name), 'w',
                  encoding='utf-8') as f:
            f.write(f'# {name}\n\n' + (body if name == 'canon.md' else 'x\n'))


def test_a_hand_edited_anchor_in_the_packet_is_reported(packet_project):
    _write_packet(packet_project)
    path = packet.packet_file(packet_project, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    src = canon.anchor_texts(packet_project)
    cid, original = next(iter(src.items()))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(original, original.replace('.', '!', 1)))

    findings = packet.anchor_copy_drift(packet_project)
    assert {f['kind'] for f in findings} == {'anchor_copy_drift'}
    assert any(f.get('id') == cid for f in findings)


def test_cosmetic_whitespace_is_not_drift(packet_project):
    _write_packet(packet_project)
    path = packet.packet_file(packet_project, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('\n\n', '\n\n\n'))
    assert packet.anchor_copy_drift(packet_project) == []


def test_a_fresh_packet_has_no_drift(packet_project):
    _write_packet(packet_project)
    assert packet.anchor_copy_drift(packet_project) == []


def test_no_packet_means_no_drift_findings(packet_project):
    """An unbuilt packet is in-flight state, not a finding."""
    assert packet.anchor_copy_drift(packet_project) == []


def test_an_anchor_copy_for_a_deleted_canon_file_is_reported(packet_project):
    """The packet directs art from an anchor that no longer exists."""
    _write_packet(packet_project)
    os.remove(canon.resolve_canon_path(packet_project, 'maps'))
    findings = packet.anchor_copy_drift(packet_project)
    assert any(f.get('id') == 'maps' and 'no longer resolves' in f['detail']
               for f in findings)


def test_an_unclosed_anchor_marker_is_reported(packet_project):
    """An unchecked copy must not read as a verified one."""
    _write_packet(packet_project)
    path = packet.packet_file(packet_project, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('<!-- /canon-embed -->', '', 1))
    findings = packet.anchor_copy_drift(packet_project)
    assert any('no closing marker' in f['detail'] for f in findings)


def test_an_invalid_anchor_marker_id_is_reported(packet_project):
    _write_packet(packet_project)
    path = packet.packet_file(packet_project, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('canon-embed: dorren-hayle',
                             'canon-embed: Dorren_Hayle', 1))
    findings = packet.anchor_copy_drift(packet_project)
    assert any('not a valid canon id' in f['detail'] for f in findings)


def test_an_unreadable_packet_file_is_reported_not_skipped(packet_project):
    _write_packet(packet_project)
    with open(packet.packet_file(packet_project, 'illustrations.md'),
              'wb') as f:
        f.write(b'\xff\xfe\x00broken')
    findings = packet.anchor_copy_drift(packet_project)
    assert any('could not read' in f['detail'] for f in findings)


# ============================================================================
# Staleness
# ============================================================================

def test_a_fresh_packet_is_not_stale(packet_project):
    _write_packet(packet_project)
    assert packet.packet_stale(packet_project) == []


def test_a_packet_older_than_the_plan_is_stale(packet_project):
    _write_packet(packet_project)
    future = os.path.getmtime(
        packet.packet_file(packet_project, 'README.md')) + 60
    plan = ill.plan_path(packet_project)
    os.utime(plan, (future, future))
    findings = packet.packet_stale(packet_project)
    assert [f['kind'] for f in findings] == ['packet_stale']
    assert 'illustration-plan.csv' in findings[0]['detail']


def test_a_packet_older_than_a_canon_file_is_stale(packet_project):
    _write_packet(packet_project)
    future = os.path.getmtime(
        packet.packet_file(packet_project, 'README.md')) + 60
    path = canon.resolve_canon_path(packet_project, 'dorren-hayle')
    os.utime(path, (future, future))
    findings = packet.packet_stale(packet_project)
    assert findings and 'dorren-hayle.md' in findings[0]['detail']


def test_a_packet_older_than_the_state_log_is_stale(packet_project):
    from storyforge import visual_state as vs
    _write_packet(packet_project)
    future = os.path.getmtime(
        packet.packet_file(packet_project, 'README.md')) + 60
    os.utime(vs.state_path(packet_project), (future, future))
    assert 'visual-state.csv' in packet.packet_stale(packet_project)[0]['detail']


def test_a_half_written_packet_is_not_reported_as_stale(packet_project):
    """`is_built` is all six or none — a partial packet is a different
    problem, and `--package` writes the set."""
    _write_packet(packet_project)
    os.remove(packet.packet_file(packet_project, 'acceptance.md'))
    future = os.path.getmtime(
        packet.packet_file(packet_project, 'README.md')) + 60
    os.utime(ill.plan_path(packet_project), (future, future))
    assert packet.packet_stale(packet_project) == []
    assert not packet.is_built(packet_project)


def test_no_packet_is_not_stale(packet_project):
    assert packet.packet_stale(packet_project) == []


# ============================================================================
# Severity and wiring
# ============================================================================

@pytest.mark.parametrize('kind,expected', [
    ('packet_stale', 'warning'), ('anchor_copy_drift', 'warning')])
def test_new_kinds_have_the_intended_severity(kind, expected):
    assert ill.severity_of(kind) == expected


def test_validate_plan_folds_in_the_packet_checks(packet_project):
    _write_packet(packet_project)
    future = os.path.getmtime(
        packet.packet_file(packet_project, 'README.md')) + 60
    os.utime(ill.plan_path(packet_project), (future, future))
    path = packet.packet_file(packet_project, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    src = canon.anchor_texts(packet_project)
    _cid, original = next(iter(src.items()))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(original, original.replace('.', '!', 1)))

    kinds = {f['kind'] for f in ill.validate_plan(packet_project)}
    assert 'packet_stale' in kinds
    assert 'anchor_copy_drift' in kinds


def test_cleanup_has_remediation_for_the_new_kinds():
    """A kind with no action falls back to 'Review the illustration plan',
    which tells an author nothing about a packet."""
    from storyforge.cmd_cleanup import _ILLUSTRATION_ACTIONS
    for kind in ('packet_stale', 'anchor_copy_drift'):
        assert kind in _ILLUSTRATION_ACTIONS
        assert 'packet' in _ILLUSTRATION_ACTIONS[kind]

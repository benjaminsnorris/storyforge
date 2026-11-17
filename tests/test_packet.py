"""Tests for `storyforge.packet` — what goes in the handoff packet (#278 ph3).

Two properties matter more than the rest and are asserted first: an anchor
copied into the packet is byte-identical to its canon source, and a gap in the
data is *recorded* rather than filtered away.

The shared fixture is the illustrated project the packet is assembled from:
canon files, a two-row plan, and a visual-state log (#288; see
`illustration_helpers`). A test that needs less removes it explicitly.
"""

import os

import pytest

from storyforge import canon, packet
from storyforge import illustrations as ill
from illustration_helpers import (
    remove_canon, remove_illustration_seed, remove_plan, unstate_entity,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)


# ============================================================================
# The byte-identity invariant
# ============================================================================

def test_anchors_are_copied_byte_identically(project_dir):
    """The whole mechanism is that every prompt sends the same bytes."""
    src = canon.anchor_texts(project_dir)
    assert src, 'fixture needs at least one entity canon file'
    got = packet.resolve(project_dir)['anchors']
    for canon_id, text in src.items():
        assert got[canon_id] == text, f'{canon_id} was altered in the packet'


def test_every_canon_anchor_reaches_the_packet(project_dir):
    """Presence as well as fidelity: a dropped anchor is not "identical"."""
    src = canon.anchor_texts(project_dir)
    assert set(packet.resolve(project_dir)['anchors']) == set(src)


# ============================================================================
# Gaps — the coverage record
# ============================================================================

def test_a_missing_book_level_file_is_recorded_as_a_gap(project_dir):
    from storyforge.prompts_illustrate import CANON_PLAN
    cid = CANON_PLAN[0][0]
    path = canon.resolve_canon_path(project_dir, cid)
    assert path, 'the fixture should have this canon file'
    os.remove(path)
    gaps = packet.resolve(project_dir)['gaps']
    assert any(cid in g for g in gaps), f'{cid} absence must be a recorded gap'


def test_an_unfilled_book_level_file_is_a_different_gap(project_dir):
    """Absent and scaffolded need different fixes, so they read differently."""
    from storyforge.prompts_illustrate import CANON_PLAN
    cid = CANON_PLAN[1][0]
    path = canon.resolve_canon_path(project_dir, cid)
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(
            'Warm lamplight and umber for the office; cold slate blue for the '
            'blank places on the map. Camera at standing eye height.',
            'TODO — write this'))
    gap = next(g for g in packet.resolve(project_dir)['gaps'] if cid in g)
    assert 'scaffold' in gap
    assert 'has no file' not in gap


def test_an_unresolvable_canon_ref_is_a_gap_not_a_silent_drop(project_dir):
    rows = ill.read_plan(project_dir)
    assert rows, 'the fixture should have plan rows'
    rows[0]['canon_refs'] = 'nobody-by-that-name'
    ill.write_plan(project_dir, rows)
    gaps = packet.resolve(project_dir)['gaps']
    assert any('nobody-by-that-name' in g for g in gaps)


def test_an_empty_beat_is_a_gap_and_the_entry_says_so(project_dir):
    rows = ill.read_plan(project_dir)
    rows[0]['beat'] = ''
    ill.write_plan(project_dir, rows)
    contents = packet.resolve(project_dir)
    assert any(rows[0]['id'] in g and 'beat' in g for g in contents['gaps'])
    entry = next(e for e in contents['entries'] if e['id'] == rows[0]['id'])
    assert entry['beat'] == packet.NOT_RECORDED


def test_an_empty_subject_is_a_gap(project_dir):
    rows = ill.read_plan(project_dir)
    rows[0]['subject'] = ''
    ill.write_plan(project_dir, rows)
    gaps = packet.resolve(project_dir)['gaps']
    assert any(rows[0]['id'] in g and 'in frame' in g for g in gaps)


def test_an_entity_with_no_state_at_its_scene_is_a_gap(project_dir):
    """`cartography-office` has a canon file; here it has no transition."""
    unstate_entity(project_dir, 'cartography-office')
    gaps = packet.resolve(project_dir)['gaps']
    assert any('cartography-office' in g and 'visual state' in g
               for g in gaps)


def test_a_blank_state_cell_is_a_gap_not_a_suppressed_one(project_dir):
    """Half-filling the matrix is strictly worse than not filling it: an empty
    `state` cell *matches*, so it silences the "nobody stated this" gap and then
    renders as nothing."""
    from storyforge import visual_state as vs
    unstate_entity(project_dir, 'cartography-office')
    rows = vs.read_transitions(project_dir)
    rows.append({'entity': 'cartography-office', 'from_scene': 'act1-sc01',
                 'state': '', 'evidence': 'held her breath'})
    vs.write_transitions(project_dir, rows)
    contents = packet.resolve(project_dir)
    gaps = contents['gaps']
    assert any('cartography-office' in g and 'empty `state` cell' in g
               for g in gaps)
    # And the old gap no longer fires for it, which is exactly why the new one
    # has to.
    assert not any('cartography-office' in g and 'no transition states' in g
                   for g in gaps)
    entry = next(e for e in contents['entries']
                 if e['id'] == 'the-finest-cartographer')
    assert 'cartography-office' not in entry['state']


def test_an_unpositioned_scene_is_reported_as_such(project_dir):
    """`new-x1` is active in scenes.csv but absent from the chapter map, so no
    state resolves for it — which is a different problem from an unstated
    entity and must not be reported as one."""
    rows = ill.read_plan(project_dir)
    rows[0]['scene_id'] = 'new-x1'
    ill.write_plan(project_dir, rows)
    gaps = packet.resolve(project_dir)['gaps']
    assert any('new-x1' in g and 'reading position' in g for g in gaps)


def test_a_scene_that_does_not_exist_is_reported(project_dir):
    rows = ill.read_plan(project_dir)
    rows[0]['scene_id'] = 'no-such-scene'
    ill.write_plan(project_dir, rows)
    gaps = packet.resolve(project_dir)['gaps']
    assert any('no-such-scene' in g and 'active scene' in g for g in gaps)


def test_a_never_run_audit_is_a_gap(project_dir):
    gaps = packet.resolve(project_dir)['gaps']
    assert any('audit' in g and 'never been run' in g for g in gaps)


def test_a_stale_audit_is_a_gap(project_dir):
    from storyforge import visual_state as vs
    vs.write_provenance(project_dir, [
        {'scene_id': 'act1-sc01', 'digest': 'deadbeef',
         'audited_at': '2026-07-01'},
    ])
    gaps = packet.resolve(project_dir)['gaps']
    assert any('audit' in g and 'stale' in g and 'act1-sc01' in g
               for g in gaps)
    assert not any('never been run' in g for g in gaps)


def test_an_empty_plan_is_a_gap(project_dir):
    """No plan means the packet describes no illustrations — say so."""
    remove_plan(project_dir)
    gaps = packet.resolve(project_dir)['gaps']
    assert any('no rows' in g for g in gaps)


def test_no_populated_anchor_is_a_gap(project_dir):
    remove_canon(project_dir)
    gaps = packet.resolve(project_dir)['gaps']
    assert any('continuity anchor' in g for g in gaps)


def test_a_superseded_row_gets_no_entry(project_dir):
    rows = ill.read_plan(project_dir)
    rows[0]['status'] = 'superseded'
    ill.write_plan(project_dir, rows)
    ids = [e['id'] for e in packet.resolve(project_dir)['entries']]
    assert rows[0]['id'] not in ids
    assert rows[1]['id'] in ids


# ============================================================================
# Entry shape
# ============================================================================

def test_entries_are_in_reading_order(project_dir):
    entries = packet.resolve(project_dir)['entries']
    assert [e['id'] for e in entries] == ['the-finest-cartographer',
                                          'the-blank-page']


def test_state_resolves_the_matrix_and_overlays_the_override(project_dir):
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    # act1-sc02 resolves maps -> "the new survey blank…", which the row's
    # state_override then replaces for this image only.
    assert 'paperweight' in entries['the-blank-page']['state']
    assert 'blank where the village was' not in \
        entries['the-blank-page']['state']
    # And the earlier illustration is unaffected by that override.
    assert 'paperweight' not in entries['the-finest-cartographer']['state']


def test_state_lists_only_the_entities_the_row_names(project_dir):
    """Sending the whole cast invites the model to draw people who are not
    in the frame. `village` and `master-survey` are tracked in the fixture
    matrix and named by no plan row."""
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    assert 'master-survey' not in entries['the-blank-page']['state']
    assert 'village' not in entries['the-blank-page']['state'].lower()


def test_state_uses_display_names_not_slugs(project_dir):
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    assert 'Dorren Hayle' in entries['the-finest-cartographer']['state']


def test_aspect_comes_from_the_layout_then_the_composition(project_dir):
    rows = ill.read_plan(project_dir)
    rows[0]['layout'] = 'double_page'
    ill.write_plan(project_dir, rows)
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    assert entries['the-finest-cartographer']['aspect'] == 'landscape'
    # The second row says "square" in its composition and has no spread layout.
    assert entries['the-blank-page']['aspect'] == 'square'


def test_contrast_names_the_register_and_the_preceding_illustration(
        project_dir):
    """The register reaches both forms; the predecessor's **id** only the
    author's (#305).

    The model-facing half says "the illustration immediately before it" — it
    cannot name `the-finest-cartographer`, because the upload has no paste
    boundary and the model cannot see that image.
    """
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    assert 'brightest' in entries['the-finest-cartographer']['contrast']

    blank = entries['the-blank-page']
    assert 'darkest' in blank['contrast']
    assert 'the-finest-cartographer' not in blank['contrast']
    assert 'immediately before it' in blank['contrast']
    # The author-facing form names the file to go and open. Read from the
    # derivation, not from `Entry` — the packet does not carry it, because its
    # one consumer is the source prompt file's `## Accept only if`.
    context = packet.state_context(project_dir)
    row = next(r for r in ill.read_plan(project_dir)
               if r['id'].strip() == 'the-blank-page')
    assert 'the-finest-cartographer' in packet.contrast_for_row(
        row, context=context).for_author


def test_an_author_absent_column_is_carried_into_the_entry(project_dir):
    """`absent` is an author-added column (write_plan preserves extras). It is
    one of the two deliberate exceptions to positive framing."""
    rows = ill.read_plan(project_dir)
    rows[0]['absent'] = 'Tessa Merrin. A second master survey.'
    ill.write_plan(project_dir, rows)
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    assert entries['the-finest-cartographer']['absent'] == \
        'Tessa Merrin. A second master survey.'
    assert entries['the-blank-page']['absent'] == ''


def test_an_author_contrast_note_is_appended_not_replaced(project_dir):
    rows = ill.read_plan(project_dir)
    rows[1]['contrast'] = 'Much wider than the one before it.'
    ill.write_plan(project_dir, rows)
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    contrast = entries['the-blank-page']['contrast']
    assert 'Much wider than the one before it.' in contrast
    assert 'darkest' in contrast


def test_a_row_with_no_scene_id_is_reported_not_silently_stateless(
        project_dir):
    rows = ill.read_plan(project_dir)
    rows[0]['scene_id'] = ''
    ill.write_plan(project_dir, rows)
    gaps = packet.resolve(project_dir)['gaps']
    assert any('no scene_id' in g and rows[0]['id'] in g for g in gaps)


def test_an_override_for_an_unnamed_entity_still_reaches_the_entry(
        project_dir):
    """An override is written for one image specifically. Dropping it because
    `canon_refs` does not repeat the entity would be the silent filtering the
    gaps list exists to prevent."""
    rows = ill.read_plan(project_dir)
    rows[1]['state_override'] = 'village:half its roofs already gone'
    ill.write_plan(project_dir, rows)
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    assert 'half its roofs already gone' in entries['the-blank-page']['state']


def test_an_aspect_track_is_labeled_with_its_aspect(project_dir):
    """`{canon_id}-{aspect}` is the granularity convention — one track per
    independently-changing aspect. It should not read as a slug."""
    from storyforge import visual_state as vs
    rows = vs.read_transitions(project_dir)
    rows.append({'entity': 'dorren-hayle-clothing', 'from_scene': 'act1-sc01',
                 'state': 'a mourning band on her left sleeve',
                 'evidence': 'held her breath'})
    vs.write_transitions(project_dir, rows)
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    state = entries['the-finest-cartographer']['state']
    assert 'Dorren Hayle (clothing): a mourning band' in state


def test_the_composition_note_becomes_the_image_specific_note(project_dir):
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    assert 'lamp behind her' in entries['the-finest-cartographer']['notes']


# ============================================================================
# The dense state view
# ============================================================================

def test_state_grid_walks_the_log_forward(project_dir):
    grid = packet.state_grid(project_dir)
    # Chapter map order: act1-sc01, act1-sc02, act2-sc01. new-x1 is unmapped.
    assert grid['scenes'] == ['act1-sc01', 'act1-sc02', 'act2-sc01']
    assert 'dorren-hayle' in grid['entities']
    # dorren-hayle transitions at act1-sc01 and persists forward.
    assert grid['cells']['act2-sc01']['dorren-hayle'] == \
        grid['cells']['act1-sc01']['dorren-hayle']
    # maps transitions at act1-sc02, so it is absent before that.
    assert 'maps' not in grid['cells']['act1-sc01']
    assert 'maps' in grid['cells']['act1-sc02']


def test_state_grid_names_scenes_it_cannot_position(project_dir):
    """A grid that silently omitted a drafted scene would read as coverage.

    The fixture's scenes.csv has six active scenes and its chapter map lists
    three, so three are unpositioned — checked against the file, not assumed.
    """
    assert packet.state_grid(project_dir)['unpositioned'] == [
        'act2-sc02', 'act2-sc03', 'new-x1']


# ============================================================================
# Determinism
# ============================================================================

def test_resolve_is_deterministic(project_dir):
    assert packet.resolve(project_dir) == packet.resolve(project_dir)


def test_resolve_on_a_bare_project_does_not_raise(project_dir):
    remove_illustration_seed(project_dir)
    contents = packet.resolve(project_dir)
    assert contents['entries'] == []
    assert contents['gaps']


# ============================================================================
# One unresolvable canon_refs is one gap (#290 item 1)
# ============================================================================

def test_an_unresolvable_canon_ref_produces_exactly_one_gap(project_dir):
    """Both the anchor check and the state-coverage check used to report it."""
    rows = ill.read_plan(project_dir)
    rows[0]['canon_refs'] = 'nobody-at-all'
    ill.write_plan(project_dir, rows)
    gaps = [g for g in packet.resolve(project_dir)['gaps']
            if 'nobody-at-all' in g]
    assert len(gaps) == 1, gaps
    assert 'resolves to no populated canon file' in gaps[0]
    # Nothing is lost by suppressing the other one: the survivor states the
    # second consequence *and* keeps the remedy the suppressed gap carried.
    assert 'no transition states its visual state' in gaps[0]
    assert 'reference/visual-state.csv' in gaps[0]
    assert 'illustrate --direction' in gaps[0]


def test_an_unanchored_ref_whose_state_resolves_is_not_told_it_has_none(
        project_dir):
    """The gap used to assert "no visual state is reported for it either"
    unconditionally, while the suppression was conditional on nothing resolving.
    For a state-only entity with a transition that is simply false — the entry
    shows the state — and the sentence after it condemned the row that
    produced it."""
    from storyforge import visual_state as vs
    transitions = vs.read_transitions(project_dir)
    transitions.append({'entity': 'village-lights', 'from_scene': 'act1-sc01',
                        'state': 'nine still lit',
                        'evidence': 'held her breath'})
    vs.write_transitions(project_dir, transitions)
    rows = ill.read_plan(project_dir)
    rows[0]['canon_refs'] = 'village-lights'
    ill.write_plan(project_dir, rows)

    contents = packet.resolve(project_dir)
    entry = {e['id']: e for e in contents['entries']}['the-finest-cartographer']
    assert 'nine still lit' in entry['state'], 'the state does resolve'
    gaps = [g for g in contents['gaps'] if 'village-lights' in g]
    assert len(gaps) == 1, gaps
    assert 'no transition states its visual state' not in gaps[0]
    assert 'Its visual state does resolve' in gaps[0]


def test_an_unanchored_state_only_entity_keeps_the_transition_remedy(
        project_dir):
    """`visual_state.prepass` does not consult anchors, so `state_unspecified`
    still fires for this row telling the author to add a transition. A gap
    saying a transition row "states a change to a design nothing has stated"
    put two opposite instructions in one --diagnose."""
    rows = ill.read_plan(project_dir)
    rows[0]['canon_refs'] = 'village-lights'
    ill.write_plan(project_dir, rows)
    gaps = [g for g in packet.resolve(project_dir)['gaps']
            if 'village-lights' in g]
    assert len(gaps) == 1, gaps
    assert 'state-only entity' in gaps[0]
    # Both remedies, since which one applies depends on the entity.
    assert 'reference/visual-state.csv' in gaps[0]
    assert 'illustrate --direction' in gaps[0]
    # And it does not contradict `state_unspecified`'s advice.
    assert 'nothing has stated' not in gaps[0]


def test_an_anchored_ref_with_no_transition_still_gets_its_state_gap(
        project_dir):
    """The suppression is keyed on the *anchor*, not on "any missing state" —
    `cartography-office` has a canon file; here it has no transition."""
    unstate_entity(project_dir, 'cartography-office')
    gaps = [g for g in packet.resolve(project_dir)['gaps']
            if 'cartography-office' in g]
    assert any('no transition states its visual state' in g for g in gaps)


# ============================================================================
# Canon-stale art is not finished art (#300)
# ============================================================================

def _ingest_rows(project_dir, **cells):
    """Mark every plan row ingested with a real file, and return the ids."""
    from illustration_helpers import make_png
    rows = ill.read_plan(project_dir)
    for row in rows:
        rel = ill.default_asset_rel(row['id'].strip())
        make_png(os.path.join(project_dir, rel), 8, 12)
        row.update({'status': 'ingested', 'asset_file': rel})
        row.update(cells)
    ill.write_plan(project_dir, rows)
    return [row['id'].strip() for row in rows]


def test_needs_render_names_a_canon_stale_ingested_row_and_why(project_dir):
    """The fixture canon is `canon_updated: 2026-07-28`."""
    ids = _ingest_rows(project_dir, ingested_at='2026-01-01')
    needs = packet.needs_render(project_dir)
    assert sorted(needs) == sorted(ids)
    for reason in needs.values():
        assert 'before the canon was last updated 2026-07-28' in reason


def test_an_empty_ingested_at_counts_as_pre_canon(project_dir):
    """The column postdates the plan schema, so "unknown" means the render
    predates even the bookkeeping — the shape the real book was in."""
    _ingest_rows(project_dir, ingested_at='')
    needs = packet.needs_render(project_dir)
    assert all('`ingested_at` is empty' in r for r in needs.values())


def test_an_unparseable_ingested_at_counts_as_pre_canon(project_dir):
    _ingest_rows(project_dir, ingested_at='last Tuesday')
    assert all('not an ISO date' in r
               for r in packet.needs_render(project_dir).values())


def test_a_row_ingested_from_the_current_canon_needs_nothing(project_dir):
    _ingest_rows(project_dir, ingested_at='2026-07-28')
    assert packet.needs_render(project_dir) == {}


def test_a_pending_row_needs_a_render_with_no_reason(project_dir):
    """'' and a reason are different answers: one is "no art yet", the other is
    "art that no longer follows the canon", and they read differently."""
    needs = packet.needs_render(project_dir)
    assert set(needs) == {'the-finest-cartographer', 'the-blank-page'}
    assert set(needs.values()) == {''}


def test_a_rendered_status_is_never_judged_canon_stale(project_dir):
    """`rendered` means a file exists Storyforge has never seen, so it carries
    no `ingested_at` and there is no date to judge. It still needs ingesting,
    so it is in the mapping — with no reason."""
    rows = ill.read_plan(project_dir)
    rows[0]['status'] = 'rendered'
    ill.write_plan(project_dir, rows)
    assert packet.needs_render(project_dir)['the-finest-cartographer'] == ''


def test_nothing_is_stale_without_a_parseable_canon_cutoff(project_dir):
    """No canon tree at all: nothing can be judged, so nothing is claimed."""
    remove_canon(project_dir)
    _ingest_rows(project_dir, ingested_at='')
    assert packet.needs_render(project_dir) == {}


def test_the_predicate_owns_the_empty_cutoff_check(project_dir):
    """`_references_for` used to guard the call with its own `if canon_cutoff:`.
    Harmless, but a caller-side copy reads as this caller having a different rule
    from the other consumers — the divergence one shared predicate exists to make
    impossible. Asserted on the predicate so the guard cannot come back as
    behaviour."""
    row = ill.read_plan(project_dir)[0]
    row['status'] = 'ingested'
    row['ingested_at'] = ''
    assert ill.stale_render_reason(row, '') == ''
    assert ill.stale_render_reason(row, '2026-07-28') != ''


def test_references_for_excludes_a_stale_render_without_a_caller_side_guard(
        project_dir, monkeypatch):
    """The behavioural half: the reference list still drops a pre-canon render,
    and an empty cutoff still excludes nothing."""
    from illustration_helpers import make_png
    from storyforge import cmd_illustrate
    monkeypatch.chdir(project_dir)
    rel = ill.default_asset_rel('the-blank-page')
    make_png(os.path.join(project_dir, rel), 8, 12)
    rows = ill.read_plan(project_dir)
    rows[1].update({'status': 'ingested', 'asset_file': rel,
                    'ingested_at': '2026-01-01'})
    ill.write_plan(project_dir, rows)

    stale_cut = cmd_illustrate._references_for(
        project_dir, 'the-finest-cartographer', plan=rows,
        canon_cutoff='2026-07-28')
    assert not any(rel in path for path, _label in stale_cut)

    no_cut = cmd_illustrate._references_for(
        project_dir, 'the-finest-cartographer', plan=rows, canon_cutoff='')
    assert any(rel in path for path, _label in no_cut)


def test_a_superseded_row_is_not_something_that_needs_rendering(project_dir):
    _ingest_rows(project_dir, ingested_at='')
    rows = ill.read_plan(project_dir)
    rows[1]['status'] = 'superseded'
    ill.write_plan(project_dir, rows)
    assert 'the-blank-page' not in packet.needs_render(project_dir)


def test_render_state_is_the_one_place_in_versus_get_is_decided(project_dir):
    """Three states over two levels: `needs.get(id)` read as "done" collapses
    *pending* into *done*, which is #300 at the go/no-go call site."""
    needs = {'pending-one': '', 'stale-one': 'because reasons'}
    assert packet.render_state(needs, 'pending-one') == 'pending'
    assert packet.render_state(needs, 'stale-one') == 'stale'
    assert packet.render_state(needs, 'not-in-there') == 'done'


def test_ids_in_state_dedupes_within_a_narrowed_subset(project_dir):
    """The anchor batch's darkest and brightest can be one illustration, and a
    naive list names it twice."""
    needs = {'a': 'stale', 'b': ''}
    assert packet.ids_in_state(needs, 'stale', ['a', 'a', 'b']) == ['a']
    assert packet.ids_in_state(needs, 'pending', ['a', 'b', 'b']) == ['b']
    assert packet.ids_in_state(needs, 'done', ['a', 'b', 'z']) == ['z']


def test_next_to_render_names_a_canon_stale_row(project_dir):
    """As a bare status check this returned '' for a fully-ingested pre-canon
    book, so `--diagnose` printed no "next to render" line and then said N
    illustrations needed re-rendering — #300's contradiction inside #300's fix."""
    _ingest_rows(project_dir, ingested_at='2026-01-01')
    assert ill.next_to_render(project_dir) != ''
    report = ill.plan_report(project_dir)
    assert report['next_unrendered'] != ''
    assert sorted(report['awaiting_render']) == ['the-blank-page',
                                                 'the-finest-cartographer']
    # `ingested` stays a literal count of the column — it is what publishing
    # gates on, so it must not start meaning "done".
    assert len(report['ingested']) == 2


def test_next_to_render_is_empty_when_the_set_is_genuinely_current(
        project_dir):
    _ingest_rows(project_dir, ingested_at='2026-07-28')
    assert ill.next_to_render(project_dir) == ''
    assert ill.plan_report(project_dir)['awaiting_render'] == []


def test_stale_render_findings_name_each_row(project_dir):
    """The signal has to reach `validate` and `cleanup`, not only --diagnose:
    `working/cleanup-report.csv` is the durable artifact forge scans."""
    ids = _ingest_rows(project_dir, ingested_at='2026-01-01')
    findings = ill.validate_plan(project_dir)
    stale = [f for f in findings if f['kind'] == 'canon_stale_render']
    assert sorted(f['id'] for f in stale) == sorted(ids)
    assert all(ill.severity_of(f['kind']) == 'warning' for f in stale)
    assert all('never demote' in f['detail'] or 'rather than demoting'
               in f['detail'] for f in stale)


def test_an_undatable_canon_is_reported_rather_than_read_as_current(
        project_dir):
    """The #300-shaped silence: with no parseable `canon_updated`, every render
    reads as current because nothing can show otherwise."""
    import re
    canon_dir = os.path.join(project_dir, 'reference', 'canon')
    for root, _dirs, files in os.walk(canon_dir):
        for name in files:
            if name.endswith('.md'):
                path = os.path.join(root, name)
                with open(path, encoding='utf-8') as f:
                    text = f.read()
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(re.sub(r'canon_updated: .*', 'canon_updated: TODO',
                                   text))
    _ingest_rows(project_dir, ingested_at='')

    assert packet.needs_render(project_dir) == {}, 'nothing is judgeable'
    kinds = [f['kind'] for f in ill.validate_plan(project_dir)]
    assert 'canon_staleness_unchecked' in kinds
    assert kinds.count('canon_staleness_unchecked') == 1
    gaps = packet.resolve(project_dir)['gaps']
    assert any('not because it was checked' in g for g in gaps)


def test_a_project_with_no_canon_at_all_is_not_warned(project_dir):
    """Never having run `--direction` is in-flight state, not a failure — the
    guard `cmd_cleanup.report_canon_files` already applies."""
    remove_canon(project_dir)
    _ingest_rows(project_dir, ingested_at='')
    kinds = [f['kind'] for f in ill.validate_plan(project_dir)]
    assert 'canon_staleness_unchecked' not in kinds


def test_a_book_with_no_ingested_art_is_not_warned_about_the_cutoff(
        project_dir):
    """Nothing filed means nothing that could be stale, so an undatable canon
    costs this project nothing and warning would fire on every new project."""
    assert ill.staleness_unchecked_finding(
        project_dir, ill.read_plan(project_dir), '') == []


def test_the_packet_states_stale_rows_outside_the_anchor_batch(project_dir):
    """A stale row was marked in its own entry and, if it filled a slot, in the
    batch table. On a twenty-row book that put seventeen of them nowhere in
    README.md while the author was told to work top to bottom."""
    _ingest_rows(project_dir, ingested_at='2026-01-01')
    gaps = packet.resolve(project_dir)['gaps']
    aggregate = [g for g in gaps if 'predates the canon now governing' in g]
    assert len(aggregate) == 1, aggregate
    assert '2 of 2 illustration(s)' in aggregate[0]
    assert 'the-finest-cartographer' in aggregate[0]


def test_an_entry_carries_the_stale_reason(project_dir):
    """`prompts_packet` reads this to decide what the entry *instructs*, so it
    has to reach the entry rather than being recomputed at render time."""
    _ingest_rows(project_dir, ingested_at='2026-01-01')
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    assert all(e['stale_reason'] for e in entries.values())


def test_a_current_entry_carries_no_stale_reason(project_dir):
    _ingest_rows(project_dir, ingested_at='2026-07-28')
    entries = packet.resolve(project_dir)['entries']
    assert all(e['stale_reason'] == '' for e in entries)


# ============================================================================
# The anchor batch
# ============================================================================

def test_the_establisher_is_the_visual_key(project_dir):
    key = next((s['id'] for s in ill.render_order(project_dir)
                if s['is_visual_key']), None)
    assert key, 'the fixture plan should have a visual key'
    assert packet.anchor_batch(project_dir)['establisher'] == key


def test_all_four_slots_when_register_is_populated(project_dir):
    """The fixture plan marks both extremes and needs one later-state row."""
    from storyforge import visual_state as vs
    rows = vs.read_transitions(project_dir)
    rows.append({'entity': 'maps', 'from_scene': 'act1-sc01',
                 'state': 'ruled, inked, and clean',
                 'evidence': 'held her breath'})
    vs.write_transitions(project_dir, rows)
    plan = ill.read_plan(project_dir)
    plan[1]['canon_refs'] = 'maps'
    ill.write_plan(project_dir, plan)

    batch = packet.anchor_batch(project_dir)
    assert batch['establisher'] == 'the-finest-cartographer'
    assert batch['brightest'] == 'the-finest-cartographer'
    assert batch['darkest'] == 'the-blank-page'
    # maps transitions at act1-sc01 and again at act1-sc02, so the second
    # illustration shows it in a state later than its first.
    assert batch['later_state'] == 'the-blank-page'
    assert batch['fallback'] == []


def test_the_fallback_is_reported_when_register_is_empty(project_dir):
    rows = ill.read_plan(project_dir)
    for row in rows:
        row['register'] = ''
    ill.write_plan(project_dir, rows)
    batch = packet.anchor_batch(project_dir)
    assert batch['fallback'], 'a guessed darkest/brightest must be disclosed'
    assert any('register=darkest' in note for note in batch['fallback'])
    # Still filled, so the batch is renderable — it is the guess that is
    # disclosed, not the slot that is dropped.
    assert batch['darkest'] == 'the-finest-cartographer'
    assert batch['brightest'] == 'the-blank-page'


def test_every_batch_slot_is_declared():
    """`BatchSlot` and `BATCH_SLOTS` are one vocabulary in two declarations, and
    the whole point of the Literal is that nothing can add to one and not the
    other. Same shape as the `SplitCause` / `StaleKind` totality tests."""
    from typing import get_args
    assert {slot for slot, _label in packet.BATCH_SLOTS} == \
        set(get_args(packet.BatchSlot))


def test_slots_by_id_promotes_in_slot_order():
    filled: packet.AnchorBatch = {
        'establisher': 'e', 'darkest': 'd', 'brightest': 'b',
        'later_state': 'l', 'fallback': [], 'guessed': [],
    }
    assert list(packet.slots_by_id(filled)) == ['e', 'd', 'b', 'l']


def test_slots_by_id_keeps_the_first_slot_when_one_row_fills_two():
    """The common configuration, not an edge case: with no `register` cells on a
    one-row plan, darkest and brightest resolve to the same illustration — which
    `anchor_batch` discloses as "the batch brackets nothing". It must occupy one
    reference and be named once."""
    doubled: packet.AnchorBatch = {
        'establisher': '', 'darkest': 'x', 'brightest': 'x',
        'later_state': 'y', 'fallback': [], 'guessed': [],
    }
    assert packet.slots_by_id(doubled) == {'x': 'darkest', 'y': 'later_state'}


def test_a_guessed_slot_is_reported_structurally_not_only_in_prose(
        project_dir):
    """`fallback` is prose, so no consumer can ask "was this slot guessed?" —
    and #311's reference labels have to, since a prompt file carries neither the
    batch table nor the fallback notes (#311 review, CR-H1)."""
    rows = ill.read_plan(project_dir)
    rows[0]['register'] = ''            # was brightest
    ill.write_plan(project_dir, rows)
    batch = packet.anchor_batch(project_dir)
    assert batch['guessed'] == ['brightest']


def test_a_chosen_register_slot_is_not_reported_as_guessed(project_dir):
    """The fixture plan marks both extremes by hand."""
    assert packet.anchor_batch(project_dir)['guessed'] == []


def test_an_unfilled_slot_is_not_a_guessed_one(project_dir):
    """Empty and guessed are different answers: the fixture plan has no
    later-state exemplar, and nothing was guessed in its place."""
    batch = packet.anchor_batch(project_dir)
    assert batch['later_state'] == ''
    assert 'later_state' not in batch['guessed']


def test_only_the_missing_register_slot_is_disclosed(project_dir):
    rows = ill.read_plan(project_dir)
    rows[0]['register'] = ''  # was brightest
    ill.write_plan(project_dir, rows)
    batch = packet.anchor_batch(project_dir)
    assert any('brightest slot is a guess' in n for n in batch['fallback'])
    assert not any('darkest slot is a guess' in n for n in batch['fallback'])


def test_a_batch_that_brackets_nothing_says_so(project_dir):
    """The realistic collision: the author marks only the *last* illustration
    as darkest, and the brightest guess is also the last one."""
    rows = ill.read_plan(project_dir)
    rows[0]['register'] = ''
    rows[1]['register'] = 'darkest'
    ill.write_plan(project_dir, rows)
    batch = packet.anchor_batch(project_dir)
    assert batch['darkest'] == batch['brightest'] == 'the-blank-page'
    assert any('brackets nothing' in n for n in batch['fallback'])


def test_a_missing_later_state_exemplar_is_disclosed(project_dir):
    """Every fixture transition is its entity's first, so nothing qualifies."""
    batch = packet.anchor_batch(project_dir)
    assert batch['later_state'] == ''
    assert any('later-state exemplar' in n for n in batch['fallback'])


def test_an_entity_the_row_does_not_show_cannot_make_it_the_exemplar(
        project_dir):
    """An image can only lock a changed wardrobe if the wardrobe is in it."""
    from storyforge import visual_state as vs
    rows = vs.read_transitions(project_dir)
    rows.append({'entity': 'village', 'from_scene': 'act1-sc02',
                 'state': 'gone from the sheet', 'evidence': 'Blank parchment'})
    vs.write_transitions(project_dir, rows)
    # `the-blank-page` names only `maps`, so the later village state is not
    # something it shows.
    assert packet.anchor_batch(project_dir)['later_state'] == ''


def test_a_missing_establisher_is_disclosed(project_dir):
    rows = ill.read_plan(project_dir)
    for row in rows:
        row['canon_refs'] = ''
    ill.write_plan(project_dir, rows)
    batch = packet.anchor_batch(project_dir)
    assert batch['establisher'] == ''
    notes = batch['fallback']
    assert any('no visual key' in n for n in notes)
    # No row names an anchor, so the plain statement is true and is what is said.
    assert any('no illustration names a continuity anchor' in n for n in notes)
    assert not any('in reading order names a continuity anchor' in n
                   for n in notes)


def _anchors_only_outside_the_horizon(project_dir):
    """Nine rows: six unanchored early, three anchored late. Horizon is 3.

    Ids are chosen so `(position, id)` puts every unanchored row first — the
    plan shape #290 item 3 describes, and the only one where the batch's
    original wording is false.
    """
    rows = []
    for index in range(1, 7):
        row = ill.blank_row(f'a-{index:02}')
        row.update({'scene_id': 'act1-sc01', 'placement': 'scene_open',
                    'beat': 'b', 'subject': 's'})
        rows.append(row)
    for index in range(1, 4):
        row = ill.blank_row(f'z-{index:02}')
        row.update({'scene_id': 'act2-sc01', 'placement': 'scene_open',
                    'canon_refs': 'maps', 'beat': 'b', 'subject': 's'})
        rows.append(row)
    ill.write_plan(project_dir, rows)
    return rows


def test_an_empty_establisher_names_the_horizon_when_later_rows_have_anchors(
        project_dir):
    """#290 item 3: with anchors only outside the visual-key horizon, "no
    illustration names a continuity anchor in `canon_refs`" is flatly false."""
    _anchors_only_outside_the_horizon(project_dir)

    batch = packet.anchor_batch(project_dir)
    assert batch['establisher'] == ''
    note = next(n for n in batch['fallback'] if 'establisher' in n)
    assert 'none of the first 3 illustration(s)' in note
    assert '3 later illustration(s) do name anchors' in note
    assert '`z-01`' in note
    # The false claim is gone.
    assert not note.startswith('no illustration names a continuity anchor')


def test_the_horizon_the_batch_names_is_the_one_render_order_uses(
        project_dir):
    """Two computations of the horizon would let the disclosure name a number the
    selection does not use. Asserted by comparing the two *lists* the horizon is
    sliced from — `max(3, n // 3)` is flat at 3 for every n <= 11, so comparing
    the numbers alone would pass even after the lists diverged."""
    _anchors_only_outside_the_horizon(project_dir)
    reading_order = [r['id'].strip() for r in
                     packet.rows_in_reading_order(project_dir)]
    render_sequence = [s['id'] for s in ill.render_order(project_dir)]
    # render_order hoists the visual key; with none, the two must be identical.
    assert not any(s['is_visual_key'] for s in ill.render_order(project_dir))
    assert render_sequence == reading_order

    note = next(n for n in packet.anchor_batch(project_dir)['fallback']
                if 'establisher' in n)
    assert f'first {ill.visual_key_horizon(len(reading_order))} illustration(s)' \
        in note


def test_the_later_anchored_rows_are_summarised_not_enumerated(project_dir):
    """The shape is not rare: on a twenty-row book the horizon is six, so
    filling `canon_refs` from the middle outward leaves fourteen ids to name.
    Fourteen backticked ids mid-sentence is what makes a `fallback` note
    skippable, and these notes are the only disclosure channel for a guessed or
    unfillable slot."""
    rows = []
    for index in range(1, 7):          # six unanchored, inside the horizon
        row = ill.blank_row(f'a-{index:02}')
        row.update({'scene_id': 'act1-sc01', 'placement': 'scene_open',
                    'beat': 'b', 'subject': 's'})
        rows.append(row)
    for index in range(1, 15):         # fourteen anchored, outside it
        row = ill.blank_row(f'z-{index:02}')
        row.update({'scene_id': 'act2-sc01', 'placement': 'scene_open',
                    'canon_refs': 'maps', 'beat': 'b', 'subject': 's'})
        rows.append(row)
    ill.write_plan(project_dir, rows)
    assert ill.visual_key_horizon(len(rows)) == 6

    note = next(n for n in packet.anchor_batch(project_dir)['fallback']
                if 'establisher' in n)
    # The count is still exact — it is the *enumeration* that is bounded.
    assert '14 later illustration(s) do name anchors' in note
    assert '`z-01`, `z-02`, `z-03`, and 11 more' in note
    assert '`z-04`' not in note
    assert note.count('`z-') == 3


def test_a_short_later_list_is_named_in_full(project_dir):
    """The cap must not turn three ids into "and 0 more"."""
    _anchors_only_outside_the_horizon(project_dir)  # three later rows
    note = next(n for n in packet.anchor_batch(project_dir)['fallback']
                if 'establisher' in n)
    assert '`z-01`, `z-02`, `z-03`' in note
    assert 'more' not in note


def test_an_anchor_exactly_at_the_horizon_boundary_is_not_the_key(
        project_dir):
    """The realistic near-miss: the only anchored row is the first one *outside*
    the window. `rows[horizon:]` must include it — off by one and the batch tells
    the author no illustration names an anchor while one does."""
    rows = []
    for index in range(1, 10):
        row = ill.blank_row(f'a-{index:02}')
        row.update({'scene_id': 'act1-sc01', 'placement': 'scene_open',
                    'beat': 'b', 'subject': 's'})
        rows.append(row)
    horizon = ill.visual_key_horizon(len(rows))
    rows[horizon]['canon_refs'] = 'maps'  # index 3, the first row outside
    ill.write_plan(project_dir, rows)

    batch = packet.anchor_batch(project_dir)
    assert batch['establisher'] == '', 'the boundary row is outside the window'
    note = next(n for n in batch['fallback'] if 'establisher' in n)
    assert f'none of the first {horizon} illustration(s)' in note
    assert '1 later illustration(s) do name anchors' in note
    assert f'`a-{horizon + 1:02}`' in note


def test_an_empty_plan_has_no_batch_and_says_why(project_dir):
    remove_plan(project_dir)
    batch = packet.anchor_batch(project_dir)
    assert batch['establisher'] == batch['darkest'] == ''
    assert any('no rows' in n for n in batch['fallback'])


def test_a_superseded_row_is_not_in_the_batch(project_dir):
    rows = ill.read_plan(project_dir)
    rows[1]['status'] = 'superseded'
    ill.write_plan(project_dir, rows)
    batch = packet.anchor_batch(project_dir)
    assert 'the-blank-page' not in batch.values()


def test_the_batch_ignores_what_it_cannot_position(project_dir):
    """A transition or an illustration the chapter map cannot place must be
    skipped rather than counted at position zero — which would make the last
    illustration in the book look like the earliest."""
    from storyforge import visual_state as vs
    rows = vs.read_transitions(project_dir)
    rows.extend([
        # Active in scenes.csv, absent from the chapter map: no position.
        {'entity': 'maps', 'from_scene': 'act2-sc02',
         'state': 'rolled and shelved', 'evidence': ''},
        # Later than the illustration that shows `maps`, so it must not govern.
        {'entity': 'maps', 'from_scene': 'act2-sc01',
         'state': 'annotated in red', 'evidence': ''},
    ])
    vs.write_transitions(project_dir, rows)
    plan = ill.read_plan(project_dir)
    plan[0]['scene_id'] = 'new-x1'  # active, unmapped
    ill.write_plan(project_dir, plan)

    batch = packet.anchor_batch(project_dir)
    assert batch['later_state'] == ''
    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    # The illustration at act1-sc02 still resolves against its own transition,
    # not the later one.
    assert 'annotated in red' not in entries['the-blank-page']['state']


def test_the_batch_is_derived_not_stored(project_dir):
    """It must not be possible for the batch to disagree with the plan."""
    before = packet.anchor_batch(project_dir)
    rows = ill.read_plan(project_dir)
    rows[0]['register'] = 'darkest'
    rows[1]['register'] = 'brightest'
    ill.write_plan(project_dir, rows)
    after = packet.anchor_batch(project_dir)
    assert before['darkest'] != after['darkest']
    assert after['darkest'] == 'the-finest-cartographer'


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


def test_a_hand_edited_anchor_in_the_packet_is_reported(project_dir):
    _write_packet(project_dir)
    path = packet.packet_file(project_dir, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    src = canon.anchor_texts(project_dir)
    cid, original = next(iter(src.items()))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(original, original.replace('.', '!', 1)))

    findings = packet.anchor_copy_drift(project_dir)
    assert {f['kind'] for f in findings} == {'anchor_copy_drift'}
    assert any(f.get('id') == cid for f in findings)


def test_cosmetic_whitespace_is_not_drift(project_dir):
    _write_packet(project_dir)
    path = packet.packet_file(project_dir, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('\n\n', '\n\n\n'))
    assert packet.anchor_copy_drift(project_dir) == []


def test_a_fresh_packet_has_no_drift(project_dir):
    _write_packet(project_dir)
    assert packet.anchor_copy_drift(project_dir) == []


def test_no_packet_means_no_drift_findings(project_dir):
    """An unbuilt packet is in-flight state, not a finding."""
    assert packet.anchor_copy_drift(project_dir) == []


def test_an_anchor_copy_for_a_deleted_canon_file_is_reported(project_dir):
    """The packet directs art from an anchor that no longer exists."""
    _write_packet(project_dir)
    os.remove(canon.resolve_canon_path(project_dir, 'maps'))
    findings = packet.anchor_copy_drift(project_dir)
    assert any(f.get('id') == 'maps' and 'no longer resolves' in f['detail']
               for f in findings)


def test_an_unclosed_anchor_marker_is_reported(project_dir):
    """An unchecked copy must not read as a verified one."""
    _write_packet(project_dir)
    path = packet.packet_file(project_dir, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('<!-- /canon-embed -->', '', 1))
    findings = packet.anchor_copy_drift(project_dir)
    assert any('no closing marker' in f['detail'] for f in findings)


def test_an_invalid_anchor_marker_id_is_reported(project_dir):
    _write_packet(project_dir)
    path = packet.packet_file(project_dir, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('canon-embed: dorren-hayle',
                             'canon-embed: Dorren_Hayle', 1))
    findings = packet.anchor_copy_drift(project_dir)
    assert any('not a valid canon id' in f['detail'] for f in findings)


def test_a_partial_packet_is_still_checked_for_drift(project_dir):
    """A missing file is skipped; the files that ARE there are still read."""
    _write_packet(project_dir)
    os.remove(packet.packet_file(project_dir, 'acceptance.md'))
    path = packet.packet_file(project_dir, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    original = next(iter(canon.anchor_texts(project_dir).values()))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(original, original.replace('.', '!', 1)))
    assert packet.anchor_copy_drift(project_dir)


def test_an_unreadable_packet_file_is_reported_not_skipped(project_dir):
    _write_packet(project_dir)
    with open(packet.packet_file(project_dir, 'illustrations.md'),
              'wb') as f:
        f.write(b'\xff\xfe\x00broken')
    findings = packet.anchor_copy_drift(project_dir)
    assert any('could not read' in f['detail'] for f in findings)


# ============================================================================
# Staleness
# ============================================================================

def test_a_fresh_packet_is_not_stale(project_dir):
    _write_packet(project_dir)
    assert packet.packet_stale(project_dir) == []


def test_a_packet_older_than_the_plan_is_stale(project_dir):
    _write_packet(project_dir)
    future = os.path.getmtime(
        packet.packet_file(project_dir, 'README.md')) + 60
    plan = ill.plan_path(project_dir)
    os.utime(plan, (future, future))
    findings = packet.packet_stale(project_dir)
    assert [f['kind'] for f in findings] == ['packet_stale']
    assert 'illustration-plan.csv' in findings[0]['detail']


def test_a_packet_older_than_a_canon_file_is_stale(project_dir):
    _write_packet(project_dir)
    future = os.path.getmtime(
        packet.packet_file(project_dir, 'README.md')) + 60
    path = canon.resolve_canon_path(project_dir, 'dorren-hayle')
    os.utime(path, (future, future))
    findings = packet.packet_stale(project_dir)
    assert findings and 'dorren-hayle.md' in findings[0]['detail']


def test_a_packet_older_than_the_state_log_is_stale(project_dir):
    from storyforge import visual_state as vs
    _write_packet(project_dir)
    future = os.path.getmtime(
        packet.packet_file(project_dir, 'README.md')) + 60
    os.utime(vs.state_path(project_dir), (future, future))
    assert 'visual-state.csv' in packet.packet_stale(project_dir)[0]['detail']


def test_a_half_written_packet_is_not_reported_as_stale(project_dir):
    """`is_built` is all six or none — a partial packet is a different
    problem, and `--package` writes the set."""
    _write_packet(project_dir)
    os.remove(packet.packet_file(project_dir, 'acceptance.md'))
    future = os.path.getmtime(
        packet.packet_file(project_dir, 'README.md')) + 60
    os.utime(ill.plan_path(project_dir), (future, future))
    assert packet.packet_stale(project_dir) == []
    assert not packet.is_built(project_dir)


def test_no_packet_is_not_stale(project_dir):
    assert packet.packet_stale(project_dir) == []


# ============================================================================
# Severity and wiring
# ============================================================================

@pytest.mark.parametrize('kind,expected', [
    ('packet_stale', 'warning'), ('anchor_copy_drift', 'warning')])
def test_new_kinds_have_the_intended_severity(kind, expected):
    assert ill.severity_of(kind) == expected


def test_validate_plan_folds_in_the_packet_checks(project_dir):
    _write_packet(project_dir)
    future = os.path.getmtime(
        packet.packet_file(project_dir, 'README.md')) + 60
    os.utime(ill.plan_path(project_dir), (future, future))
    path = packet.packet_file(project_dir, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    src = canon.anchor_texts(project_dir)
    _cid, original = next(iter(src.items()))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(original, original.replace('.', '!', 1)))

    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'packet_stale' in kinds
    assert 'anchor_copy_drift' in kinds


def test_truncated_canon_is_a_packet_gap(project_dir):
    """#293: a truncated block is neither absent nor a scaffold, so
    `missing_reference_sections` reports it clean while the packet copies only
    the text above the stray `##`. Silence there is exactly the coverage
    overclaim README.md exists not to make."""
    from illustration_helpers import write_canon_file
    write_canon_file(project_dir, canon_id='visual-vocabulary',
                     canon_type='vocabulary',
                     body='Palette: muted greens.\n\n## Camera\n\nChild height.')
    gaps = packet.resolve(project_dir)['gaps']
    hits = [g for g in gaps if 'visual-vocabulary' in g and '## Camera' in g]
    assert len(hits) == 1, gaps


def test_cleanup_has_remediation_for_the_new_kinds():
    """A kind with no action falls back to 'Review the illustration plan',
    which tells an author nothing about a packet."""
    from storyforge.cmd_cleanup import _ILLUSTRATION_ACTIONS
    for kind in ('packet_stale', 'anchor_copy_drift'):
        assert kind in _ILLUSTRATION_ACTIONS
        assert 'packet' in _ILLUSTRATION_ACTIONS[kind]


# ============================================================================
# #305 — closing the contrast mutants the first round left alive
# ============================================================================
#
# Every test below was written against a surviving mutant: the id-splitting and
# the two-audience derivation were unit-tested, but the *branches* were not, and
# a mutation campaign found seven ways to reintroduce #305 with the whole suite
# green. Each test names the mutation it kills, because that is the only durable
# record of why the assertion is shaped the way it is.


def test_contrast_with_no_register_capitalizes_the_neighbour_clause(
        project_dir):
    """The follows-only arm of `_assemble` — the arm nearly every real row takes.

    `register` is populated on neither of the fixture's two rows and, per
    CLAUDE.md, on almost no real project either, so this is the production path.
    It was also the *only* one of the three arms with no test: replacing its
    whole return with a constant left the suite green. That arm is where the
    `_assemble` refactor was riskiest, because it is the one doing the
    capitalization — `follows_model` starts lowercase precisely so the register
    variant can splice it mid-sentence as "it must not repeat…".
    """
    rows = ill.read_plan(project_dir)
    for row in rows:
        row['register'] = ''
    ill.write_plan(project_dir, rows)

    context = packet.state_context(project_dir)
    row = {r['id'].strip(): r for r in ill.read_plan(project_dir)}[
        'the-blank-page']
    contrast = packet.contrast_for_row(row, context=context)

    assert contrast.for_model.startswith('Must not repeat the staging'), \
        contrast.for_model
    assert 'the-finest-cartographer' not in contrast.for_model
    # The author-facing form takes the same arm and must still name the file.
    assert contrast.for_author.startswith('Follows `the-finest-cartographer`'), \
        contrast.for_author


def test_a_contrast_naming_a_superseded_illustration_is_withheld(
        project_dir):
    """`plan_ids` is not `set(predecessors)`, and this is why.

    `RowContext.plan_ids`' docstring states the distinction outright, and
    substituting one for the other survived the whole suite. `predecessors` comes
    from `rows_in_reading_order`, which drops `superseded` rows — so a contrast
    written against retired art would have sailed into the upload. Retiring an
    illustration is the documented flow (`status=superseded` then `--embed`), not
    an edge case.
    """
    rows = ill.read_plan(project_dir)
    retired = ill.blank_row('the-retired-sketch')
    retired.update({
        'scene_id': 'act1-sc01', 'anchor': 'held her breath',
        'placement': 'after_anchor', 'layout': 'half_page',
        'beat': 'An earlier attempt at the same moment',
        'status': 'superseded',
    })
    rows[1]['contrast'] = 'Warmer than the-retired-sketch. Keep it close.'
    ill.write_plan(project_dir, rows + [retired])

    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    blank = entries['the-blank-page']

    assert 'the-retired-sketch' not in blank['contrast']
    assert 'the-retired-sketch' in blank['contrast_withheld']
    assert 'Keep it close.' in blank['contrast'], \
        'the safe half must still reach the model'


def test_an_id_in_a_different_case_is_still_withheld(project_dir):
    """`re.IGNORECASE` removed survived the suite, and real books need it.

    *The Lantern Folk*'s ids are `LF-04`; an author typing prose writes `lf-04`.
    A case-sensitive match would have leaked exactly the book #305 was filed
    against.
    """
    rows = ill.read_plan(project_dir)
    upper = ill.blank_row('LF-04')
    upper.update({'scene_id': 'act1-sc01', 'anchor': 'held her breath',
                  'placement': 'after_anchor', 'layout': 'half_page',
                  'beat': 'The lantern on the sill'})
    rows[1]['contrast'] = 'Darker than lf-04. Keep the horizon low.'
    ill.write_plan(project_dir, rows + [upper])

    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    blank = entries['the-blank-page']

    assert 'lf-04' not in blank['contrast']
    assert 'lf-04' in blank['contrast_withheld']
    assert 'Keep the horizon low.' in blank['contrast']


def test_the_author_facing_form_keeps_the_authors_own_words(project_dir):
    """`for_author` dropping the author's half survived: the append test only
    ever checked `for_model`. An id is exactly right for a human checking a
    render, and so is the sentence the author wrote around it.

    Asserted on `contrast_for_row` rather than on an entry field, because
    `Entry` deliberately no longer carries the author form — its only consumer is
    the source prompt file, which is never uploaded.
    """
    rows = ill.read_plan(project_dir)
    rows[1]['contrast'] = 'Much wider than the one before it.'
    ill.write_plan(project_dir, rows)

    context = packet.state_context(project_dir)
    row = {r['id'].strip(): r for r in ill.read_plan(project_dir)}[
        'the-blank-page']

    assert 'Much wider than the one before it.' in \
        packet.contrast_for_row(row, context=context).for_author


# ---------------------------------------------------------------------------
# The id matcher's two deliberate asymmetries
# ---------------------------------------------------------------------------
#
# `_id_pattern` chose a lookbehind and *no* lookahead on purpose, and dropped a
# backticked-token fallback. All three are judgements with a stated rationale and
# no test, which is how a later "tidy-up" reverts one without noticing.

def test_a_suffix_of_a_longer_token_is_not_an_id_match(project_dir):
    """The lookbehind's job: `XLF-07` is a different token, not a reference.

    Without it the matcher fires inside any word ending in a plan id, which
    withholds legitimate direction and tells the author it named another
    illustration.
    """
    rows = ill.read_plan(project_dir)
    other = ill.blank_row('LF-07')
    other.update({'scene_id': 'act1-sc01', 'anchor': 'held her breath',
                  'placement': 'after_anchor', 'layout': 'half_page',
                  'beat': 'A lantern'})
    rows[1]['contrast'] = 'Use the XLF-07 stock instead.'
    ill.write_plan(project_dir, rows + [other])

    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    assert 'Use the XLF-07 stock instead.' in entries['the-blank-page'][
        'contrast']
    assert entries['the-blank-page']['contrast_withheld'] == ''


def test_the_matcher_over_withholds_rather_than_missing_an_id(project_dir):
    """There is deliberately no lookahead, and the asymmetry is the point.

    `LF-071` matching a check for `LF-07` over-withholds — disclosed to the
    author under **Check against its neighbours** — where a miss puts an id in
    front of the image model. Pinned because it looks like a bug to a reader who
    does not know it was chosen: the obvious "fix" is to add a lookahead, which
    reintroduces the `LF-07s` and `_LF-07_` leaks.
    """
    rows = ill.read_plan(project_dir)
    other = ill.blank_row('LF-07')
    other.update({'scene_id': 'act1-sc01', 'anchor': 'held her breath',
                  'placement': 'after_anchor', 'layout': 'half_page',
                  'beat': 'A lantern'})
    rows[1]['contrast'] = 'Read against LF-071 for scale.'
    ill.write_plan(project_dir, rows + [other])

    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    blank = entries['the-blank-page']
    assert blank['contrast_withheld'] == 'Read against LF-071 for scale.'
    assert 'LF-071' not in blank['contrast']


def test_a_backticked_field_name_is_not_treated_as_an_illustration(
        project_dir):
    """The backticked-token fallback was removed on purpose, and this pins why.

    It withheld `Keep the `half_page` gutter clear.` from the model's copy and
    told the author it named another illustration. A backticked non-id is far
    more often a field name than an illustration, so the plan's own ids are the
    only signal.
    """
    rows = ill.read_plan(project_dir)
    rows[1]['contrast'] = 'Keep the `half_page` gutter clear.'
    ill.write_plan(project_dir, rows)

    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    blank = entries['the-blank-page']
    assert 'Keep the `half_page` gutter clear.' in blank['contrast']
    assert blank['contrast_withheld'] == ''


def test_an_id_absent_from_the_plan_is_still_withheld(project_dir):
    """A contrast against a **cut** row still names an illustration.

    This was the one residual #305 leak after the backtick fallback was dropped:
    `Colder than `LF-04`.` where `LF-04` has since left the plan reached the image
    model, because `plan_ids` cannot know about a cut row by definition.
    `_backticked_ids` covers it — restricted to plan-id shape and excluding this
    domain's own vocabulary, which is what the first fallback got wrong.
    """
    rows = ill.read_plan(project_dir)
    rows[1]['contrast'] = 'Colder than `LF-04`. Keep the horizon low.'
    ill.write_plan(project_dir, rows)

    entries = {e['id']: e for e in packet.resolve(project_dir)['entries']}
    entry = entries['the-blank-page']

    assert 'LF-04' not in entry['contrast']
    assert 'LF-04' in entry['contrast_withheld']
    assert 'Keep the horizon low.' in entry['contrast']


@pytest.mark.parametrize('token', [
    'half_page', 'full_page', 'scene_open', 'after_anchor', 'darkest', 'palette',
])
def test_this_domains_own_vocabulary_is_not_mistaken_for_an_illustration(
        project_dir, token):
    """The reason the first fallback was wrong: these share the plan-id shape.

    Withholding is disclosed and so was never dangerous, but it was explained as
    "it names another illustration", which is false — and a disclosure channel that
    explains a drop wrongly is worse than the drop.
    """
    kept, withheld = packet._split_author_contrast(
        f'Keep the `{token}` treatment.', {'the-finest-cartographer'})

    assert kept == f'Keep the `{token}` treatment.'
    assert withheld == ''


def test_every_illustration_vocabulary_is_excluded():
    """A new vocabulary in `illustrations` cannot silently be withheld as an id.

    `_schema_vocabulary`'s *values* are derived, but its list of **sources** was
    hand-written — and it drifted immediately: `VALID_PLAN_STATUSES` was missing,
    so `ingested`, `planned` and `superseded` were withheld from the model's copy
    under the false claim that they named another illustration.

    Introspection rather than a second hand-written list, which would drift the
    same way. Anything in `illustrations` named `VALID_*` or `*_COLUMNS` is a
    vocabulary an author may reasonably backtick, so it belongs in the exclusion
    set; adding one without adding it there fails here.
    """
    vocab = packet._schema_vocabulary()
    sources = [n for n in dir(ill)
               if n.startswith('VALID_') or n.endswith('_COLUMNS')]

    assert sources, 'introspection found nothing — has the naming changed?'
    missing = {
        name: sorted(str(v).lower().lstrip('.') for v in getattr(ill, name)
                     if str(v).lower().lstrip('.') not in vocab)
        for name in sources
    }
    assert not any(missing.values()), (
        f'not excluded from _backticked_ids: '
        f'{ {k: v for k, v in missing.items() if v} }')


@pytest.mark.parametrize('token', ['ingested', 'planned', 'superseded'])
def test_a_plan_status_is_not_mistaken_for_an_illustration(project_dir,
                                                           token):
    """The drift this caught, pinned by value as well as by introspection."""
    kept, withheld = packet._split_author_contrast(
        f'Match the `{token}` rows.', {'the-finest-cartographer'})

    assert kept == f'Match the `{token}` rows.'
    assert withheld == ''

"""Tests for the visual-state transition log (#278 phase 2).

The fixture project's reading order comes from its chapter map:
`act1-sc01` -> `act1-sc02` -> `act2-sc01`. The rows below use those ids and
evidence quotes that really appear in those scene files, because the pre-pass
checks the evidence against the prose.
"""

import os

import pytest

from storyforge import visual_state as vs

ROWS = [
    # entity, from_scene, state, evidence
    ('dorren-clothing', 'act1-sc01', 'office dress, brass calipers in hand',
     'held her breath'),
    ('dorren-clothing', 'act2-sc01', 'travel coat, boots, compass on a cord',
     'She checked her compass'),
    ('master-survey', 'act1-sc02', 'blank where the village should be',
     'Blank parchment'),
]


def _write_state(project_dir, rows=ROWS):
    path = os.path.join(project_dir, 'reference', 'visual-state.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('|'.join(vs.STATE_COLUMNS) + '\n')
        for row in rows:
            f.write('|'.join(row) + '\n')
    return path


# ============================================================================
# Resolution
# ============================================================================

def test_state_at_walks_forward_from_the_last_transition(project_dir):
    _write_state(project_dir)
    # act1-sc02 is after act1-sc01 and before act2-sc01
    at = vs.state_at(project_dir, 'act1-sc02')
    assert at['dorren-clothing'] == 'office dress, brass calipers in hand'
    assert at['master-survey'] == 'blank where the village should be'


def test_state_at_the_transition_scene_uses_the_new_state(project_dir):
    """The boundary: a transition takes effect AT its own scene, not after it."""
    _write_state(project_dir)
    at = vs.state_at(project_dir, 'act2-sc01')
    assert at['dorren-clothing'] == 'travel coat, boots, compass on a cord'


def test_an_entity_with_no_transition_yet_is_absent(project_dir):
    _write_state(project_dir)
    at = vs.state_at(project_dir, 'act1-sc01')
    assert 'master-survey' not in at, 'master-survey first changes at act1-sc02'


def test_the_later_row_wins_when_two_transitions_share_a_scene(project_dir):
    _write_state(project_dir, [
        ('great-lamp', 'act1-sc01', 'first row', 'held her breath'),
        ('great-lamp', 'act1-sc01', 'second row', 'held her breath'),
    ])
    assert vs.state_at(project_dir, 'act1-sc01')['great-lamp'] == 'second row'


def test_a_scene_with_no_reading_position_resolves_empty(project_dir, capsys):
    """new-x1 exists in scenes.csv but not in the chapter map, which wins."""
    _write_state(project_dir)
    assert vs.state_at(project_dir, 'new-x1') == {}
    assert 'no reading position' in capsys.readouterr().out


def test_entities_lists_every_distinct_entity_sorted(project_dir):
    _write_state(project_dir)
    assert vs.entities(project_dir) == ['dorren-clothing', 'master-survey']


def test_a_row_with_no_entity_is_skipped_loudly(project_dir, capsys):
    _write_state(project_dir, [('', 'act1-sc01', 'orphaned state', '')])
    assert vs.read_transitions(project_dir) == []
    assert 'no entity' in capsys.readouterr().out


def test_no_state_file_is_empty_not_an_error(project_dir):
    os.remove(os.path.join(project_dir, 'reference', 'visual-state.csv'))
    assert vs.read_transitions(project_dir) == []
    assert vs.state_at(project_dir, 'act1-sc01') == {}
    assert vs.entities(project_dir) == []


def test_write_transitions_emits_lf_only(project_dir):
    vs.write_transitions(project_dir, [
        {'entity': 'x', 'from_scene': 'act1-sc01', 'state': 'y',
         'evidence': 'z'},
    ])
    with open(os.path.join(project_dir, 'reference', 'visual-state.csv'),
              'rb') as f:
        assert b'\r' not in f.read()


def test_write_transitions_round_trips(project_dir):
    rows = [{'entity': e, 'from_scene': s, 'state': st, 'evidence': ev}
            for e, s, st, ev in ROWS]
    vs.write_transitions(project_dir, rows)
    assert vs.read_transitions(project_dir) == rows


# ============================================================================
# state_override and the new plan columns
# ============================================================================

def test_parse_state_override_splits_on_the_first_colon_only():
    from storyforge.visual_state import parse_state_override
    got = parse_state_override('nora-face:tear-streaked;leo-hands:muddy, gripping')
    assert got.applied == {'nora-face': 'tear-streaked',
                           'leo-hands': 'muddy, gripping'}
    # a state containing a colon survives
    assert parse_state_override('x:a:b').applied == {'x': 'a:b'}
    assert parse_state_override('').applied == {}
    assert parse_state_override('malformed').applied == {}


def test_parse_state_override_returns_what_it_skipped(capsys):
    """Returned, not logged (#309).

    Two WARNING lines competing with seventeen reference-exclusion warnings on
    the same run were invisible in practice — and they were on the wrong gate,
    since `--diagnose` and `validate` reported nothing. `prepass` turns these
    into findings instead.
    """
    from storyforge.visual_state import parse_state_override
    got = parse_state_override('no-colon-here;x:ok')

    assert got.applied == {'x': 'ok'}
    assert got.skipped == ['no-colon-here']
    assert capsys.readouterr().out == '', 'the parser must not log'


def test_parse_state_override_skips_an_empty_half():
    from storyforge.visual_state import parse_state_override
    got = parse_state_override('x:;:y')
    assert got.applied == {}
    assert got.skipped == ['x:', ':y']


def test_parse_state_override_flags_a_sentence_as_the_entity_key():
    """The clause that survives a prose cell keeps a sentence as its key, and
    `state_for_row` then hands it to the image model as an authoritative state
    line under that label."""
    from storyforge.visual_state import parse_state_override
    got = parse_state_override(
        'The instant AFTER extinction, which a10 does not describe: '
        'the Great Lamp dark and cold; the line of light gone entirely; '
        'EXACTLY FIVE Folk lanterns still dimly alive')

    # The reported shape of the real failure: 3 clauses, 1 applied, 2 dropped.
    assert len(got.applied) == 1
    assert len(got.skipped) == 2
    assert got.clause_count == 3
    assert got.prose_keys == list(got.applied)
    # And the facts that mattered are gone from what reaches the prompt.
    assert 'EXACTLY FIVE' not in ' '.join(got.applied.values())


def test_a_short_entity_like_key_is_not_called_prose():
    """`Great Lamp` means an entity; it should get the untracked-entity finding
    rather than a prose complaint."""
    from storyforge.visual_state import parse_state_override
    assert parse_state_override('Great Lamp:dark').prose_keys == []
    assert parse_state_override('nora-clothing:coat').prose_keys == []


def test_new_plan_columns_are_optional():
    from storyforge.illustrations import PLAN_COLUMNS, OPTIONAL_PLAN_COLUMNS
    for col in ('state_override', 'register', 'scene_digest'):
        assert col in PLAN_COLUMNS
        assert col in OPTIONAL_PLAN_COLUMNS, (
            f'{col} must be optional or every legacy plan becomes an error')


def test_valid_registers_are_the_two_lighting_extremes():
    from storyforge.illustrations import VALID_REGISTERS
    assert VALID_REGISTERS == frozenset({'darkest', 'brightest'})


# ============================================================================
# The deterministic pre-pass
# ============================================================================

def _plan(project_dir, **overrides):
    """Write a one-row plan and return the row. The fixture ships no plan."""
    from storyforge import illustrations as ill
    row = ill.blank_row('lantern-vigil')
    row.update({'scene_id': 'act1-sc01', 'placement': 'scene_open',
                'layout': 'full_page', 'status': 'planned'})
    row.update(overrides)
    ill.write_plan(project_dir, [row])
    return row


def test_a_from_scene_that_exists_nowhere_is_an_error(project_dir):
    """Cut, renamed, or mistyped: the author must fix the log."""
    from storyforge import illustrations as ill
    _write_state(project_dir, ROWS + [
        ('master-survey', 'scene-that-was-cut', 'burned', 'held her breath'),
    ])
    found = [f for f in vs.prepass(project_dir)['findings']
             if f['kind'] == 'state_unknown_scene']
    assert len(found) == 1
    assert found[0]['file'] == vs.STATE_FILE
    assert ill.severity_of('state_unknown_scene') == 'error'


def test_a_blank_from_scene_is_the_same_error(project_dir):
    _write_state(project_dir, [('master-survey', '', 'burned', '')])
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert kinds == {'state_unknown_scene'}


def test_a_scene_the_chapter_map_omits_is_a_warning_not_an_error(project_dir):
    """new-x1 is in scenes.csv and not in the fixture's chapter map. The
    transition row is well-formed; the map is what is incomplete. Flagging it as
    an error would push the author to delete a good row."""
    from storyforge import illustrations as ill
    _write_state(project_dir, [('master-survey', 'new-x1', 'burned', '')])
    findings = vs.prepass(project_dir)['findings']
    kinds = {f['kind'] for f in findings}
    assert kinds == {'state_unmapped_scene'}
    assert ill.severity_of('state_unmapped_scene') == 'warning'
    assert 'state_unknown_scene' not in kinds


def test_the_unmapped_warning_points_at_the_chapter_map(project_dir):
    _write_state(project_dir, [('master-survey', 'new-x1', 'burned', '')])
    finding = vs.prepass(project_dir)['findings'][0]
    assert finding['file'] == os.path.join('reference', 'chapter-map.csv')
    assert finding['scene_id'] == 'new-x1'
    assert 'the row is fine' in finding['detail']


def test_a_cut_scene_stays_an_error_even_though_scenes_csv_lists_it(project_dir):
    """check_chapter_map_freshness excludes cut/merged/archived scenes, which is
    exactly right: a transition keyed to a cut scene must not read as a mere
    chapter-map gap."""
    path = os.path.join(project_dir, 'reference', 'scenes.csv')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('new-x1|3|The Archivist\'s Warning|1|Kael Maren|'
                             'The Deep Archive|2|afternoon|30 minutes|'
                             'revelation|mapped',
                             'new-x1|3|The Archivist\'s Warning|1|Kael Maren|'
                             'The Deep Archive|2|afternoon|30 minutes|'
                             'revelation|cut'))
    _write_state(project_dir, [('master-survey', 'new-x1', 'burned', '')])
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert kinds == {'state_unknown_scene'}


def test_evidence_absent_from_the_prose_is_reported(project_dir):
    _write_state(project_dir, [
        ('master-survey', 'act1-sc01', 'lit',
         'a phrase that is not in this scene'),
    ])
    found = [x for x in vs.prepass(project_dir)['findings']
             if x['kind'] == 'evidence_not_found']
    assert len(found) == 1
    assert found[0]['id'] == 'master-survey'
    assert found[0]['scene_id'] == 'act1-sc01'
    assert found[0]['file'] == vs.STATE_FILE


def test_evidence_survives_reflowed_prose(project_dir):
    """find_anchor is whitespace-tolerant, so a quote broken across lines matches."""
    _write_state(project_dir, [
        ('x', 'act1-sc01', 'y', 'held\nher\nbreath'),
    ])
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'evidence_not_found' not in kinds


def test_a_transition_with_no_evidence_is_not_a_finding(project_dir):
    _write_state(project_dir, [('x', 'act1-sc01', 'y', '')])
    assert vs.prepass(project_dir)['findings'] == []


def test_an_undrafted_from_scene_is_logged_not_flagged(project_dir, capsys):
    """A transition on a scene that has a reading position but no prose yet is
    normal in-flight state, so the evidence check is skipped and says so."""
    os.remove(os.path.join(project_dir, 'scenes', 'act2-sc01.md'))
    _write_state(project_dir, [('x', 'act2-sc01', 'y', 'some quote')])
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'evidence_not_found' not in kinds
    assert 'cannot check the evidence' in capsys.readouterr().out


def test_an_illustration_naming_an_unstated_entity_is_reported(project_dir):
    _write_state(project_dir, ROWS)
    _plan(project_dir, canon_refs='murkwolves')
    found = [x for x in vs.prepass(project_dir)['findings']
             if x['kind'] == 'state_unspecified']
    assert len(found) == 1
    assert found[0]['id'] == 'lantern-vigil'


def test_an_aspect_track_satisfies_its_bare_canon_id(project_dir):
    """canon_refs says `dorren`; the log tracks `dorren-clothing`. That counts."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, canon_refs='dorren')
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'state_unspecified' not in kinds


def test_an_exact_entity_id_satisfies_the_check(project_dir):
    _write_state(project_dir, ROWS)
    _plan(project_dir, canon_refs='dorren-clothing')
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'state_unspecified' not in kinds


def test_an_entity_whose_first_transition_is_later_is_unstated(project_dir):
    """master-survey first changes at act1-sc02, so at act1-sc01 it is unstated —
    absent, not blank."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act1-sc01', canon_refs='master-survey')
    found = [x for x in vs.prepass(project_dir)['findings']
             if x['kind'] == 'state_unspecified']
    assert len(found) == 1


def test_a_state_override_satisfies_the_check(project_dir):
    _write_state(project_dir, ROWS)
    _plan(project_dir, canon_refs='murkwolves',
          state_override='murkwolves:dissolving into fog')
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'state_unspecified' not in kinds


def test_a_superseded_illustration_states_nothing(project_dir):
    _write_state(project_dir, ROWS)
    _plan(project_dir, canon_refs='murkwolves', status='superseded')
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'state_unspecified' not in kinds


def test_an_unresolvable_illustration_scene_is_logged_not_double_reported(
        project_dir, capsys):
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='nowhere', canon_refs='murkwolves')
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert 'state_unspecified' not in kinds
    assert 'no resolvable scene_id' in capsys.readouterr().out


def test_clean_log_yields_no_findings(project_dir):
    _write_state(project_dir)
    assert vs.prepass(project_dir)['findings'] == []


# ============================================================================
# Check 5 — a scene_close image over a state that changes mid-scene (#308)
# ============================================================================

def _mid_scene_findings(project_dir):
    return [f for f in vs.prepass(project_dir)['findings']
            if f['kind'] == 'state_mid_scene_change']


def test_a_scene_close_image_over_a_changing_entity_is_reported(project_dir):
    """#308's LF-13. The Great Lamp goes out during the scene; the log holds
    one value for the whole scene, which is the state going *in*, and the
    illustration's whole subject was the state coming out."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_close',
          canon_refs='dorren-clothing')

    found = _mid_scene_findings(project_dir)
    assert len(found) == 1
    assert found[0]['id'] == 'lantern-vigil'
    assert found[0]['scene_id'] == 'act2-sc01'
    assert 'state_override' in found[0]['detail']
    assert 'dorren-clothing' in found[0]['detail']


def test_a_bare_canon_ref_matches_the_changing_aspect_track(project_dir):
    """canon_refs says `dorren`; the transition is on `dorren-clothing`."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_close',
          canon_refs='dorren')
    assert len(_mid_scene_findings(project_dir)) == 1


def test_a_state_override_answers_the_mid_scene_question(project_dir):
    """The author has said what is true in this image, so there is nothing to
    ask — the same suppression check 3 honours."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_close',
          canon_refs='dorren-clothing',
          state_override='dorren-clothing:travel coat, hood up')
    assert _mid_scene_findings(project_dir) == []


def test_a_scene_open_image_is_ambiguous_the_same_way(project_dir):
    """The symmetric case, and the one the first cut wrongly excluded.

    Under `<=` a transition takes effect at its own scene, so a `scene_open`
    image — which precedes all of that scene's prose — resolves to a changed
    state the reader has not reached yet. The original rationale ("every other
    placement now has a resolvable position inside the scene") was wrong twice:
    a reading position is never fed into state resolution at all.
    """
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_open',
          canon_refs='dorren-clothing')

    found = _mid_scene_findings(project_dir)
    assert len(found) == 1
    assert 'at the open of' in found[0]['detail']


@pytest.mark.parametrize('placement', ['before_anchor', 'after_anchor'])
def test_an_anchored_image_is_not_reported(project_dir, placement):
    """An anchor names a phrase, which is at least evidence about where in the
    scene the image sits."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement=placement,
          anchor='She checked her compass', canon_refs='dorren-clothing')
    assert _mid_scene_findings(project_dir) == []


def test_the_detail_does_not_claim_the_log_holds_the_pre_change_state(project_dir):
    """`_resolve` uses `<=`, so the resolved value IS the transition's declared
    state. Saying "usually the state going in" described a value the resolution
    cannot return, and invited a maintainer to 'fix' a boundary that has a test
    on it."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_close',
          canon_refs='dorren-clothing')
    detail = _mid_scene_findings(project_dir)[0]['detail']
    assert 'going in' not in detail
    assert 'which side of that change' in detail


def test_an_entity_that_does_not_change_in_that_scene_is_not_reported(project_dir):
    """master-survey changes at act1-sc02, not act2-sc01. Resolving forward to a
    state set in an earlier scene is exactly what the log is for."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_close',
          canon_refs='master-survey')
    assert _mid_scene_findings(project_dir) == []


def test_the_mid_scene_finding_reaches_validate_plan(project_dir):
    """The kind is only worth declaring if the gates see it."""
    from storyforge import illustrations as ill
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_close',
          canon_refs='dorren-clothing')
    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'state_mid_scene_change' in kinds


def test_one_row_can_report_both_state_kinds_for_different_refs(project_dir):
    """`dorren-clothing` changes in the scene; `murkwolves` is stated nowhere.
    Two refs, two different problems, both worth saying."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_close',
          canon_refs='dorren-clothing;murkwolves')
    kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}
    assert {'state_mid_scene_change', 'state_unspecified'} <= kinds


def test_a_superseded_row_reports_neither(project_dir):
    """Inherited from check 3's guard — retired art resolves no state to be
    wrong about."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_close',
          canon_refs='dorren-clothing', status='superseded')
    assert _mid_scene_findings(project_dir) == []


def test_a_bare_state_override_does_not_suppress_an_aspect_ref(project_dir):
    """Documents an asymmetry that is pre-existing and shared with check 3: the
    remedy says "set state_override", and an author who types the bare entity
    name for an aspect-tracked ref gets the finding again."""
    _write_state(project_dir, ROWS)
    _plan(project_dir, scene_id='act2-sc01', placement='scene_close',
          canon_refs='dorren-clothing', state_override='dorren:hood up')
    assert len(_mid_scene_findings(project_dir)) == 1


def test_the_mid_scene_finding_leaves_a_publishable_book():
    """A warning, not a block. The art is fine to ship; it is the *next* render
    that wants the answer."""
    from storyforge import illustrations as ill
    assert ill.severity_of('state_mid_scene_change') == 'warning'
    assert 'state_mid_scene_change' not in ill.BLOCKING_FINDINGS


def test_the_shipped_fixture_log_is_clean(fixture_dir):
    """The fixture's own visual-state.csv must not make every other suite that
    validates the plan report findings."""
    assert vs.prepass(fixture_dir)['findings'] == []


# ============================================================================
# candidate_scenes — the narrowed set the LLM reads
# ============================================================================

def test_candidate_scenes_selects_a_scene_that_mentions_a_tracked_entity(
        project_dir):
    # `master-survey` first changes at act1-sc02; act2-sc01 is after it and its
    # prose says "the mapped world", not "master survey" — so track something
    # act2-sc01 actually names.
    _write_state(project_dir, [
        ('compass', 'act1-sc01', 'brass, needle steady', 'held her breath'),
    ])
    assert vs.prepass(project_dir)['candidate_scenes'] == ['act2-sc01']


def test_candidate_scenes_excludes_scenes_before_the_first_transition(
        project_dir):
    _write_state(project_dir, [
        ('compass', 'act2-sc01', 'brass, needle steady',
         'She checked her compass'),
    ])
    # act2-sc01 is the transition scene itself, already pinned by its evidence.
    assert vs.prepass(project_dir)['candidate_scenes'] == []


def test_candidate_scenes_is_empty_with_no_log(project_dir):
    os.remove(os.path.join(project_dir, 'reference', 'visual-state.csv'))
    assert vs.prepass(project_dir)['candidate_scenes'] == []


def test_prepass_returns_the_denominators_the_caller_needs(project_dir):
    """The narrowing count is the caller's to report, so prepass hands back both
    sides of it rather than logging — validate and cleanup also call prepass and
    are not auditing anything."""
    _write_state(project_dir, [
        ('compass', 'act1-sc01', 'brass', 'held her breath'),
    ])
    result = vs.prepass(project_dir)
    assert result['candidate_scenes'] == ['act2-sc01']
    assert result['scene_count'] == 3
    assert result['tracked_entities'] == ['compass']
    assert result['undrafted_scenes'] == []


def test_prepass_does_not_log_the_narrowing(project_dir, capsys):
    _write_state(project_dir, [
        ('compass', 'act1-sc01', 'brass', 'held her breath'),
    ])
    vs.prepass(project_dir)
    assert 'candidate' not in capsys.readouterr().out.lower()


def test_undrafted_scenes_are_named_not_counted(project_dir):
    os.remove(os.path.join(project_dir, 'scenes', 'act2-sc01.md'))
    _write_state(project_dir, [
        ('compass', 'act1-sc01', 'brass', 'held her breath'),
    ])
    result = vs.prepass(project_dir)
    assert result['undrafted_scenes'] == ['act2-sc01']
    assert result['scene_count'] == 3


def test_an_aspect_track_is_not_shortened_without_a_canon_file(project_dir):
    """The correction to the obvious heuristic. Guessing that the last segment is
    the aspect would search for `dorren`, and state-only entities — a lantern
    count, a lamp's lit/dark state — are systematically the ones with no canon
    file, so `village-lights` would degenerate to `village` and make nearly every
    scene of a village-set book a candidate."""
    _write_state(project_dir, [
        ('dorren-clothing', 'act1-sc01', 'office dress', 'held her breath'),
    ])
    result = vs.prepass(project_dir)
    assert result['search_terms'] == {'dorren-clothing': ['dorren clothing']}
    assert result['candidate_scenes'] == []


def test_village_lights_does_not_degenerate_to_village(project_dir):
    """The spec's own example row, and the case that motivated the fix."""
    terms = vs._entity_search_terms('village-lights', {})
    assert terms == {'village lights'}
    assert 'village' not in terms


def test_search_terms_come_back_for_the_caller_to_log(project_dir):
    """A wide or empty narrowing has to be diagnosable, and prepass is silent."""
    _write_state(project_dir, [
        ('compass', 'act1-sc01', 'brass', 'held her breath'),
    ])
    assert vs.prepass(project_dir)['search_terms'] == {'compass': ['compass']}


def test_a_marker_does_not_make_a_scene_mention_an_entity(project_dir):
    from storyforge import illustrations as ill
    path = os.path.join(project_dir, 'scenes', 'act1-sc02.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text + '\n' + ill.marker_for('murkwolves') + '\n')
    _write_state(project_dir, [
        ('murkwolves', 'act1-sc01', 'grey shapes', 'held her breath'),
    ])
    assert 'act1-sc02' not in vs.prepass(project_dir)['candidate_scenes']


# ============================================================================
# Wiring
# ============================================================================

def test_validate_plan_folds_in_the_state_findings(project_dir):
    from storyforge import illustrations as ill
    _write_state(project_dir, [
        ('master-survey', 'scene-that-was-cut', 'burned', ''),
    ])
    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'state_unknown_scene' in kinds


def test_validate_plan_reports_state_findings_with_no_plan_at_all(project_dir):
    """A log can be wrong before a single illustration is planned."""
    from storyforge import illustrations as ill
    assert ill.read_plan(project_dir) == []
    _write_state(project_dir, [('x', 'gone', 'y', '')])
    kinds = {f['kind'] for f in ill.validate_plan(project_dir)}
    assert 'state_unknown_scene' in kinds


def test_cleanup_renders_the_state_kinds_singly_prefixed(project_dir):
    from storyforge.cmd_cleanup import _check_illustrations
    _write_state(project_dir, [('x', 'gone', 'y', '')])
    types = {f['type'] for f in _check_illustrations(project_dir)}
    assert 'illus_state_unknown_scene' in types
    assert not any(t.startswith('illus_illus_') for t in types)


def test_the_canon_display_name_is_a_search_term(project_dir):
    """The prose calls her "Dorren Hayle"; the log tracks `dorren-hayle-clothing`.
    Without the canon display name, neither the id nor its `{canon_id}` portion
    would be the phrase the prose actually uses."""
    from test_canon_files import write_canon
    write_canon(project_dir, 'characters/dorren-hayle.md', 'dorren-hayle',
                canon_type='character',
                frontmatter=(
                    '---\n'
                    'canon_id: dorren-hayle\n'
                    'canon_type: character\n'
                    'display_name: Dorren Hayle\n'
                    'canon_updated: 2026-07-28\n'
                    'embeds_as: Dorren Hayle\n'
                    '---\n'
                ))
    _write_state(project_dir, [
        ('dorren-hayle-clothing', 'act1-sc01', 'office dress',
         'held her breath'),
    ])
    terms = vs._entity_search_terms(
        'dorren-hayle-clothing', vs._display_names(project_dir))
    assert 'dorren hayle' in terms
    assert 'act1-sc02' in vs.prepass(project_dir)['candidate_scenes']


# ============================================================================
# #309 — a malformed state_override reaches the gates authors read
# ============================================================================

class TestMalformedStateOverrideIsReported:
    """Before #309 the only signal was two WARNING lines, and they were on the
    wrong gate: `--diagnose` and `validate` reported nothing at all, so a
    malformed override survived both clean."""

    @pytest.fixture(autouse=True)
    def _seeded(self, project_dir):
        from illustration_helpers import seed_packet_project
        seed_packet_project(project_dir)
        _write_state(project_dir)

    def _plan_with_override(self, project_dir, cell):
        from storyforge import illustrations as ill
        rows = ill.read_plan(project_dir)
        rows[0]['state_override'] = cell
        ill.write_plan(project_dir, rows)
        return rows[0]['id'].strip()

    def test_a_dropped_clause_is_a_finding(self, project_dir):
        from storyforge import visual_state as vs
        rid = self._plan_with_override(project_dir,
                                       'no-colon-here;nora-face:tear-streaked')

        kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}

        assert 'state_override_unparsed' in kinds

    def test_a_sentence_key_is_a_different_finding(self, project_dir):
        """The fixes differ: a dropped clause needs a colon, a prose key means
        the whole cell was written as a sentence."""
        from storyforge import visual_state as vs
        self._plan_with_override(
            project_dir,
            'The instant AFTER extinction which a10 omits: the Lamp dark')

        findings = vs.prepass(project_dir)['findings']
        kinds = {f['kind'] for f in findings}

        assert 'state_override_prose_key' in kinds
        assert 'state_override_unparsed' not in kinds

    def test_a_typo_entity_is_reported(self, project_dir):
        """Legitimate for a one-off entity, a typo otherwise — and a typo is
        applied silently, so the author has to be told which it might be."""
        from storyforge import visual_state as vs
        self._plan_with_override(project_dir, 'nora-fce:tear-streaked')

        kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}

        assert 'state_override_unmatched_entity' in kinds

    def test_a_well_formed_override_is_silent(self, project_dir):
        from storyforge import visual_state as vs
        from storyforge import illustrations as ill
        rows = ill.read_plan(project_dir)
        refs = ill._split_array(rows[0].get('canon_refs', ''))
        assert refs, 'fixture row needs canon_refs for this to be meaningful'
        rows[0]['state_override'] = f'{refs[0]}:lit from below'
        ill.write_plan(project_dir, rows)

        kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}

        assert not any(k.startswith('state_override_') for k in kinds)

    def test_the_findings_carry_the_plan_as_their_file(self,
                                                      project_dir):
        """The fix is an edit to the plan row, not to the transition log."""
        from storyforge import visual_state as vs
        self._plan_with_override(project_dir, 'no-colon-here')

        for finding in vs.prepass(project_dir)['findings']:
            if finding['kind'].startswith('state_override_'):
                assert 'illustration-plan' in finding['file']

    def test_the_detail_is_csv_safe(self, project_dir):
        """The findings interpolate author prose into the unquoted pipe-delimited
        cleanup report, where a `|` shifts every later column."""
        from storyforge import visual_state as vs
        self._plan_with_override(project_dir,
                                 'a | b with a pipe;x:ok')

        for finding in vs.prepass(project_dir)['findings']:
            assert '|' not in finding['detail']

    def test_a_row_with_no_canon_refs_is_still_checked(self, project_dir):
        """The case that produced zero findings, and the worst one to miss.

        The checks were emitted below `prepass`'s `canon_refs` and `scene_id`
        guards, so a row with empty `canon_refs` reported nothing while
        `state_for_row` still applied the override and shipped the fabricated
        state to the image model. And a row without `canon_refs` is *exactly* the
        documented-legitimate case for an override, so "one placement buys
        validate, cleanup and --diagnose" held only where `canon_refs` happened to
        be populated.
        """
        from storyforge import illustrations as ill
        from storyforge import visual_state as vs
        rows = ill.read_plan(project_dir)
        rows[0]['canon_refs'] = ''
        rows[0]['state_override'] = 'no-colon-here;a-sentence with four words:x'
        ill.write_plan(project_dir, rows)

        kinds = {f['kind'] for f in vs.prepass(project_dir)['findings']}

        assert 'state_override_unparsed' in kinds
        assert 'state_override_prose_key' in kinds

    def test_a_collapsed_duplicate_entity_is_reported(self, project_dir):
        """`clause_count` used to be derived from `len(applied) + len(skipped)`,
        so two clauses naming one entity collapsed to a count of one — losing a
        clause in the very number whose job is saying how many were lost."""
        from storyforge import illustrations as ill
        from storyforge import visual_state as vs
        rows = ill.read_plan(project_dir)
        rows[0]['state_override'] = 'nora-clothing:coat;nora-clothing:hood'
        ill.write_plan(project_dir, rows)

        details = [f['detail'] for f in vs.prepass(project_dir)['findings']
                   if f['kind'] == 'state_override_unparsed']

        assert any('overwrote an earlier one' in d for d in details), details

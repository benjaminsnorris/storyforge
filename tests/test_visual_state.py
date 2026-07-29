"""Tests for the visual-state transition log (#278 phase 2).

The fixture project's reading order comes from its chapter map:
`act1-sc01` -> `act1-sc02` -> `act2-sc01`. The rows below use those ids and
evidence quotes that really appear in those scene files, because the pre-pass
checks the evidence against the prose.
"""

import os

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
    assert got == {'nora-face': 'tear-streaked', 'leo-hands': 'muddy, gripping'}
    # a state containing a colon survives
    assert parse_state_override('x:a:b') == {'x': 'a:b'}
    assert parse_state_override('') == {}
    assert parse_state_override('malformed') == {}


def test_parse_state_override_reports_what_it_skipped(capsys):
    from storyforge.visual_state import parse_state_override
    assert parse_state_override('no-colon-here;x:ok') == {'x': 'ok'}
    assert 'no-colon-here' in capsys.readouterr().out


def test_parse_state_override_skips_an_empty_half(capsys):
    from storyforge.visual_state import parse_state_override
    assert parse_state_override('x:;:y') == {}
    assert 'empty entity or' in capsys.readouterr().out


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


def test_unresolvable_from_scene_is_an_error(project_dir):
    _write_state(project_dir, ROWS + [
        ('master-survey', 'scene-that-was-cut', 'burned', 'held her breath'),
    ])
    findings = vs.prepass(project_dir)['findings']
    kinds = {f['kind'] for f in findings}
    assert 'state_unknown_scene' in kinds
    from storyforge import illustrations as ill
    assert ill.severity_of('state_unknown_scene') == 'error'


def test_a_blank_from_scene_is_the_same_error(project_dir):
    _write_state(project_dir, [('master-survey', '', 'burned', '')])
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
    assert 'no file in scenes/' in capsys.readouterr().out


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


def test_candidate_narrowing_is_logged_with_both_counts(project_dir, capsys):
    _write_state(project_dir, [
        ('compass', 'act1-sc01', 'brass', 'held her breath'),
    ])
    vs.prepass(project_dir)
    out = capsys.readouterr().out
    assert ('visual-state pre-pass: selected 1 of 3 scenes as audit candidates '
            'across 1 tracked entities') in out


def test_a_run_that_selects_nothing_says_so(project_dir, capsys):
    _write_state(project_dir, [
        ('nothing-in-the-prose', 'act1-sc01', 'x', 'held her breath'),
    ])
    assert vs.prepass(project_dir)['candidate_scenes'] == []
    assert 'selected 0 of 3 scenes' in capsys.readouterr().out


def test_an_aspect_track_searches_for_its_canon_portion(project_dir):
    """`dorren-clothing` is not a phrase any prose uses; `dorren` is."""
    _write_state(project_dir, [
        ('dorren-clothing', 'act1-sc01', 'office dress', 'held her breath'),
    ])
    assert 'act1-sc02' in vs.prepass(project_dir)['candidate_scenes']


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

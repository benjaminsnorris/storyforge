"""Tests for `storyforge illustrate --package` — the handoff packet (#278 ph3).

The packet is assembly: it must make no API call, produce identical bytes on a
re-run over unchanged sources, carry every continuity anchor byte-identically,
and state its own gaps rather than reading as coverage it does not have.

`in_project` seeds canon files, a plan, and state transitions into a copy of the
fixture — the shared fixture has none of those (checked, not assumed).
"""

import os

import pytest

from storyforge import canon, cmd_illustrate, packet
from storyforge import illustrations as ill
from storyforge import prompts_packet as pp
from illustration_helpers import seed_packet_project


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)


@pytest.fixture
def in_project(project_dir, monkeypatch):
    seed_packet_project(project_dir)
    monkeypatch.chdir(project_dir)
    return project_dir


def _read(project_dir, name):
    with open(packet.packet_file(project_dir, name), encoding='utf-8') as f:
        return f.read()


def _read_all(project_dir):
    return {name: _read(project_dir, name) for name in packet.PACKET_FILES}


# ============================================================================
# The six files
# ============================================================================

def test_package_writes_all_six_files(in_project):
    assert cmd_illustrate.main(['--package']) == 0
    for name in ('README.md', 'canon.md', 'visual-state.md',
                 'illustrations.md', 'reference-images.md', 'acceptance.md'):
        assert os.path.isfile(os.path.join(in_project, packet.PACKET_DIR, name))


def test_package_makes_no_api_call(in_project, monkeypatch):
    """Set the key so the missing-key guard cannot make this pass vacuously."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('--package is assembly, not generation')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    assert cmd_illustrate.main(['--package']) == 0


def test_dry_run_writes_nothing(in_project, capsys):
    assert cmd_illustrate.main(['--package', '--dry-run']) == 0
    assert not os.path.isdir(packet.packet_dir(in_project))
    out = capsys.readouterr().out
    assert 'illustrations.md' in out


def test_regeneration_is_idempotent(in_project):
    cmd_illustrate.main(['--package'])
    first = _read_all(in_project)
    cmd_illustrate.main(['--package'])
    assert _read_all(in_project) == first


def test_a_regenerated_packet_is_not_stale_or_drifted(in_project):
    cmd_illustrate.main(['--package'])
    assert packet.packet_stale(in_project) == []
    assert packet.anchor_copy_drift(in_project) == []


# ============================================================================
# The byte-identity invariant, on the rendering path
# ============================================================================

def test_anchors_in_the_written_packet_are_byte_identical(in_project):
    """Distinct from the `resolve`-level check in test_packet.py: this is the
    only one that would catch a renderer wrapping or re-indenting an anchor."""
    cmd_illustrate.main(['--package'])
    written = _read(in_project, 'canon.md')
    src = canon.anchor_texts(in_project)
    assert src
    for text in src.values():
        assert text in written, 'anchor text was altered on the way in'


def test_a_long_anchor_is_not_rewrapped(in_project):
    """The failure mode the file-level check exists for: a renderer that tidies
    a long line. Byte comparison catches it; a keyword check would not."""
    from illustration_helpers import write_canon_file
    long_anchor = (
        'Kael Maren: sixty-two, stooped from four decades of archive work, a '
        'grey wool coat worn shiny at the elbows, half-moon spectacles pushed '
        'up on his forehead, and ink under every fingernail of his left hand.')
    write_canon_file(in_project, canon_id='kael-maren',
                     canon_type='character', body=long_anchor,
                     subdir='characters')
    cmd_illustrate.main(['--package'])
    assert long_anchor in _read(in_project, 'canon.md')


def test_the_packet_names_its_anchors_by_display_name(in_project):
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'canon.md')
    assert '### Dorren Hayle' in body
    assert '<!-- canon-embed: dorren-hayle -->' in body


# ============================================================================
# Coverage honesty
# ============================================================================

def test_the_packet_states_its_own_gaps(in_project):
    """A thin entry is named IN the packet, not in a log line."""
    rows = ill.read_plan(in_project)
    rows[0]['beat'] = ''
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert rows[0]['id'] in _read(in_project, 'README.md')


def test_a_thin_entry_reads_as_thin(in_project):
    rows = ill.read_plan(in_project)
    rows[0]['beat'] = ''
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert packet.NOT_RECORDED in _read(in_project, 'illustrations.md')


def test_gaps_are_logged_loudly_as_well(in_project, capsys):
    cmd_illustrate.main(['--package'])
    out = capsys.readouterr().out
    # The fixture has never had an audit run, which is one of the gaps.
    assert 'WARNING' in out
    assert 'audit' in out


def test_a_never_run_audit_is_named_in_the_readme(in_project):
    cmd_illustrate.main(['--package'])
    assert 'never been run' in _read(in_project, 'README.md')


def test_a_missing_book_level_section_says_so_in_canon_md(in_project):
    os.remove(canon.resolve_canon_path(in_project, 'visual-vocabulary'))
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'canon.md')
    assert 'Visual vocabulary' in body
    assert pp._MISSING in body


def test_an_untracked_book_says_so_rather_than_rendering_an_empty_table(
        in_project):
    from storyforge import visual_state as vs
    vs.write_transitions(in_project, [])
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'visual-state.md')
    assert pp._NONE_TRACKED in body
    assert '--state' in body


def test_unpositioned_scenes_are_named_in_the_state_view(in_project):
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'visual-state.md')
    assert 'chapter-map.csv' in body
    assert 'new-x1' in body


# ============================================================================
# What lives where
# ============================================================================

def test_the_set_wide_checks_live_in_acceptance_not_in_the_entries(in_project):
    cmd_illustrate.main(['--package'])
    acceptance = _read(in_project, 'acceptance.md')
    entries = _read(in_project, 'illustrations.md')
    assert 'PORTRAIT orientation' in acceptance
    assert 'no text, no letters' in acceptance.lower()
    assert 'orientation' not in entries.lower()
    assert 'no letters' not in entries.lower()


def test_the_entries_do_not_restate_the_reference_tier(in_project):
    """A per-illustration entry that carried the anchors and the house style
    would not be a thin entry."""
    cmd_illustrate.main(['--package'])
    entries = _read(in_project, 'illustrations.md')
    for text in canon.anchor_texts(in_project).values():
        assert text not in entries
    assert 'Camera at standing eye height' not in entries


def test_entries_stay_within_the_word_budget(in_project):
    """80–120 words is the point of the packet: the shared sections carry the
    rest. This guards the renderer's own overhead, on plan cells that are
    already short."""
    cmd_illustrate.main(['--package'])
    for entry in packet.resolve(in_project)['entries']:
        assert len(pp.render_entry(entry).split()) <= 120


def test_state_appears_in_the_entry_because_it_resolves_the_matrix(in_project):
    cmd_illustrate.main(['--package'])
    entries = _read(in_project, 'illustrations.md')
    assert '**State.**' in entries
    assert 'Dorren Hayle: black waistcoat' in entries


def test_reference_images_are_pathed_not_copied(in_project):
    from illustration_helpers import make_png
    cover = os.path.join('manuscript', 'assets', 'cover-illustration.png')
    make_png(os.path.join(in_project, cover), 8, 12)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'reference-images.md')
    assert cover in body
    # Nothing was copied in beside the markdown.
    assert sorted(os.listdir(packet.packet_dir(in_project))) == \
        sorted(packet.PACKET_FILES)


def test_the_sequence_rules_are_in_the_packet(in_project):
    """Source-report item 2: independent calls converge on the same staging."""
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'acceptance.md')
    assert 'adjacent' in body
    assert 'camera distance' in body


# ============================================================================
# The anchor batch, where the author reads it
# ============================================================================

def test_the_readme_names_the_batch_and_its_render_state(in_project):
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')
    batch = packet.anchor_batch(in_project)
    assert f'`{batch["establisher"]}`' in body
    assert 'establisher' in body
    assert 'not yet' in body  # nothing is ingested in the fixture


def test_a_guessed_batch_slot_is_disclosed_in_the_packet(in_project):
    """The whole point: a guess must not read as a choice."""
    rows = ill.read_plan(in_project)
    for row in rows:
        row['register'] = ''
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')
    assert 'Read this before rendering the batch' in body
    assert 'register=darkest' in body


def test_a_guessed_batch_slot_is_a_warning_in_the_log(in_project, capsys):
    rows = ill.read_plan(in_project)
    for row in rows:
        row['register'] = ''
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'is a guess' in out


def test_an_unfilled_slot_reads_as_unfilled_not_as_the_first_row(in_project):
    cmd_illustrate.main(['--package'])
    # The seeded project has no later-state exemplar.
    body = _read(in_project, 'README.md')
    assert 'later-state exemplar | _unfilled' in body


def test_diagnose_reports_the_anchor_batch(in_project, capsys):
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Anchor batch' in out
    assert 'the-finest-cartographer' in out


def test_an_ingested_batch_row_is_marked_as_such(in_project):
    from illustration_helpers import make_png
    rows = ill.read_plan(in_project)
    rel = ill.default_asset_rel('the-finest-cartographer')
    make_png(os.path.join(in_project, rel), 8, 12)
    rows[0]['status'] = 'ingested'
    rows[0]['asset_file'] = rel
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')
    line = next(l for l in body.splitlines()
                if '`the-finest-cartographer`' in l and '|' in l)
    assert line.strip().endswith('| yes |')


# ============================================================================
# The renderers, driven directly
# ============================================================================

def test_a_clean_readme_claims_only_what_it_can(in_project):
    """With no gaps the README must still not promise the art will be right."""
    contents = packet.resolve(in_project)
    contents['gaps'] = []
    body = pp.render_readme(title='T', contents=contents, entry_count=2,
                            batch=packet.anchor_batch(in_project),
                            unrendered=[])
    assert 'Nothing was missing' in body
    assert 'not a promise that' in body


def test_canon_md_keeps_an_author_added_section(in_project):
    body = pp.render_canon(
        book_level={'Visual foundation': 'A', 'House rules': 'B'},
        anchors={}, labels={})
    assert '## House rules' in body


def test_canon_md_says_so_when_no_anchor_is_populated(in_project):
    body = pp.render_canon(book_level={}, anchors={}, labels={})
    assert body.count(pp._MISSING) == 4  # three book-level, plus the anchors


def test_illustrations_md_says_so_when_nothing_is_planned():
    assert 'No illustrations are planned' in pp.render_illustrations(entries=[])


# ============================================================================
# --sequence — compositional variety
# ============================================================================

def _sequence_response(*pairs):
    import json
    return json.dumps({'treatments': [{'id': i, 'treatment': t}
                                      for i, t in pairs]})


@pytest.fixture
def staged(monkeypatch):
    """Patch `cmd_illustrate._invoke` (never storyforge.api) with a canned reply."""
    def _install(body):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: body)
    return _install


def test_sequence_assigns_a_distinct_treatment_per_row(in_project, staged):
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night'),
        ('the-blank-page', 'overhead, flat, object fills the frame, daylight')))
    assert cmd_illustrate.main(['--sequence']) == 0
    plan = ill.read_plan_as_map(in_project)
    assert 'close' in plan['the-finest-cartographer']['treatment']
    assert 'overhead' in plan['the-blank-page']['treatment']


def test_sequence_never_overwrites_an_author_treatment(in_project, staged):
    rows = ill.read_plan(in_project)
    rows[0]['treatment'] = 'wide, high, environmental, dusk'
    ill.write_plan(in_project, rows)
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night'),
        ('the-blank-page', 'overhead, flat, daylight')))
    assert cmd_illustrate.main(['--sequence']) == 0
    plan = ill.read_plan_as_map(in_project)
    assert plan['the-finest-cartographer']['treatment'] == \
        'wide, high, environmental, dusk'


def test_a_kept_author_treatment_is_reported(in_project, staged, capsys):
    rows = ill.read_plan(in_project)
    rows[0]['treatment'] = 'wide, high, environmental, dusk'
    ill.write_plan(in_project, rows)
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night')))
    cmd_illustrate.main(['--sequence'])
    out = capsys.readouterr().out
    assert 'keeping the author treatment' in out
    assert 'already carry an author treatment' in out


def test_a_repeated_treatment_across_rows_is_reported(in_project, staged,
                                                     capsys):
    """The point of the pass is variety — identical treatments defeat it."""
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night'),
        ('the-blank-page', 'Close, low, interior, night')))
    assert cmd_illustrate.main(['--sequence']) == 0
    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'share one treatment' in out
    assert 'the-blank-page' in out
    assert 'the-finest-cartographer' in out


def test_a_row_the_model_skipped_is_reported_as_unstaged(in_project, staged,
                                                         capsys):
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night')))
    cmd_illustrate.main(['--sequence'])
    out = capsys.readouterr().out
    assert 'stay unstaged' in out
    assert 'the-blank-page' in out


def test_a_treatment_for_an_unknown_id_is_dropped_and_reported(in_project,
                                                               staged, capsys):
    staged(_sequence_response(('nobody', 'close, low')))
    cmd_illustrate.main(['--sequence'])
    out = capsys.readouterr().out
    assert 'name no plan row' in out
    assert 'nobody' in out
    assert 'treatment' not in ill.read_plan_as_map(in_project).get(
        'nobody', {'treatment': ''})['treatment']


def test_an_unparseable_response_writes_nothing(in_project, staged, capsys):
    staged('I would rather describe the images in prose.')
    assert cmd_illustrate.main(['--sequence']) == 1
    out = capsys.readouterr().out
    assert 'no_json' in out
    assert 'Nothing was written' in out
    assert not ill.read_plan_as_map(in_project)[
        'the-finest-cartographer']['treatment']


def test_a_json_response_with_no_treatments_key_is_reported(in_project, staged,
                                                            capsys):
    staged('{"proposals": []}')
    assert cmd_illustrate.main(['--sequence']) == 1
    assert 'no_treatments_key' in capsys.readouterr().out


def test_an_empty_response_is_an_error(in_project, staged):
    staged('')
    assert cmd_illustrate.main(['--sequence']) == 1


def test_a_fenced_response_is_parsed(in_project, staged):
    """The common shape: a model wrapping its JSON in a code fence."""
    staged('Here you go:\n\n```json\n'
           + _sequence_response(('the-blank-page', 'overhead, flat, daylight'))
           + '\n```\n')
    assert cmd_illustrate.main(['--sequence']) == 0
    assert ill.read_plan_as_map(in_project)['the-blank-page']['treatment'] == \
        'overhead, flat, daylight'


def test_a_top_level_array_is_reported_not_guessed_at(in_project, staged,
                                                      capsys):
    staged('[{"id": "the-blank-page", "treatment": "overhead"}]')
    assert cmd_illustrate.main(['--sequence']) == 1
    assert 'no_treatments_key' in capsys.readouterr().out


def test_sequence_makes_no_api_call_under_strict_coaching(in_project,
                                                          monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('strict coaching proposes nothing')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    assert cmd_illustrate.main(['--sequence', '--coaching', 'strict']) == 0
    path = os.path.join(in_project, 'working', 'coaching',
                        'illustration-sequence-checklist.md')
    with open(path, encoding='utf-8') as f:
        body = f.read()
    assert 'camera distance' in body
    assert '_(fill in)_' in body
    assert not ill.read_plan_as_map(in_project)[
        'the-finest-cartographer']['treatment']


def test_coach_coaching_writes_a_brief_and_not_the_plan(in_project, staged):
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night')))
    assert cmd_illustrate.main(['--sequence', '--coaching', 'coach']) == 0
    path = os.path.join(in_project, 'working', 'coaching',
                        'illustration-sequence-brief.md')
    with open(path, encoding='utf-8') as f:
        assert 'close, low, interior, night' in f.read()
    assert not ill.read_plan_as_map(in_project)[
        'the-finest-cartographer']['treatment']


def test_sequence_dry_run_calls_nothing_and_writes_nothing(in_project,
                                                           monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert cmd_illustrate.main(['--sequence', '--dry-run']) == 0
    assert not ill.read_plan_as_map(in_project)[
        'the-finest-cartographer']['treatment']


def test_sequence_without_a_key_is_an_error(in_project, capsys):
    assert cmd_illustrate.main(['--sequence']) == 1
    assert 'ANTHROPIC_API_KEY' in capsys.readouterr().out


def test_sequence_on_an_empty_plan_says_so(project_dir, monkeypatch, capsys):
    monkeypatch.chdir(project_dir)
    assert cmd_illustrate.main(['--sequence']) == 0
    assert 'No illustration plan rows to stage' in capsys.readouterr().out


def test_the_request_carries_beats_but_not_scene_prose(in_project):
    rows = ill.read_plan(in_project)
    prompt = pp.build_sequence_request(rows=rows, story_context='ctx')
    assert 'The village is gone from the new survey' in prompt
    # act1-sc02's prose, which this pass must not be paying for.
    assert 'Blank parchment. Not even a contour line' not in prompt
    assert 'camera distance' in prompt


def test_the_treatment_reaches_the_packet_entry(in_project, staged):
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night')))
    cmd_illustrate.main(['--sequence'])
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'illustrations.md')
    assert '**Treatment.** close, low, interior, night' in body


def test_the_treatment_reaches_the_art_direction_request(in_project):
    from storyforge import prompts_illustrate as pi
    row = ill.read_plan(in_project)[0]
    row['treatment'] = 'close, low, interior, night'
    prompt = pi.build_art_direction_request(
        row=row, scene_excerpt='x', character_anchors={}, canon_context='y')
    assert 'close, low, interior, night' in prompt
    assert 'Staging assigned to this image' in prompt


def test_no_staging_section_when_there_is_no_treatment(in_project):
    from storyforge import prompts_illustrate as pi
    row = ill.read_plan(in_project)[0]
    prompt = pi.build_art_direction_request(
        row=row, scene_excerpt='x', character_anchors={}, canon_context='y')
    assert 'Staging assigned to this image' not in prompt


def test_treatment_is_an_optional_plan_column(in_project):
    """A plan CSV written before the sequence pass must stay valid."""
    assert 'treatment' in ill.PLAN_COLUMNS
    assert 'treatment' in ill.OPTIONAL_PLAN_COLUMNS


def test_a_plan_without_the_treatment_column_still_validates(in_project):
    path = ill.plan_path(in_project)
    columns = [c for c in ill.PLAN_COLUMNS if c != 'treatment']
    with open(path, 'w', encoding='utf-8') as f:
        f.write('|'.join(columns) + '\n')
        f.write('|'.join('the-finest-cartographer' if c == 'id'
                         else 'act1-sc01' if c == 'scene_id'
                         else 'scene_open' if c == 'placement'
                         else 'planned' if c == 'status' else ''
                         for c in columns) + '\n')
    kinds = {f['kind'] for f in ill.validate_plan(in_project)}
    assert 'shattered_row' not in kinds
    assert cmd_illustrate.main(['--package']) == 0


# ============================================================================
# Dispatch
# ============================================================================

def test_package_is_listed_when_no_phase_is_given(in_project, capsys):
    assert cmd_illustrate.main([]) == 1
    assert '--package' in capsys.readouterr().out


def test_package_is_refused_for_graphic_novel_projects(project_dir_gn,
                                                       monkeypatch):
    monkeypatch.chdir(project_dir_gn)
    assert cmd_illustrate.main(['--package']) == 1
    assert not os.path.isdir(packet.packet_dir(project_dir_gn))

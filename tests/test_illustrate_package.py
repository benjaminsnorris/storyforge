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


#: The spec's own worked example, `lamp-relit`, as plan cells. Every field the
#: renderer can emit is populated, at the length the spec shows — which is the
#: only way the 80–120 word budget is actually tested. Against the fixture's
#: short cells an entry renders around 60 words and the assertion cannot fail.
_SPEC_EXAMPLE = {
    'beat': 'The Great Lamp catches and the light drives outward through the '
            'woods.',
    'subject': 'Wide elevated view of the village. The Lamp blowing out the '
               'centre of the frame as the light source. Gold visibly '
               'travelling between the trunks. Both children small and '
               'together, arms up against the glare.',
    'composition': 'Faces and Lamp clear of the centre gutter.',
    'layout': 'double_page',
    'register': 'brightest',
    'canon_refs': 'dorren-hayle;maps',
    'absent': 'Ember. A second Great Lamp.',
    'treatment': 'very wide, high, environmental, night, subjects small in '
                 'frame',
    'state_override': 'dorren-hayle:filthy moss-green cardigan, brown ankle '
                      'boots;maps:erupting, gold',
}


def test_entries_stay_within_the_word_budget(in_project):
    """80–120 words of *derived* content is this phase's stated design
    constraint: thin entries are the whole reason the packet exists. Asserted
    against the spec's own worked example with every derived field populated,
    including a treatment — and then swept across every entry, which costs one
    line and catches a future long field on some other row."""
    rows = ill.read_plan(in_project)
    rows[1].update(_SPEC_EXAMPLE)
    ill.write_plan(in_project, rows)
    entries = {e['id']: e for e in packet.resolve(in_project)['entries']}

    maximal = pp.render_entry(entries['the-blank-page'])
    words = len(maximal.split())
    assert words <= 120, f'{words} words:\n{maximal}'

    for entry in entries.values():
        body = pp.render_entry(entry)
        assert len(body.split()) <= 120, body


def test_an_author_column_may_exceed_the_budget(in_project):
    """`absent` and `contrast` are the author's words, and SKILL.md invites
    them. The budget guards the renderer's overhead, not the author's choice —
    so this documents that it is allowed rather than pretending it cannot
    happen."""
    rows = ill.read_plan(in_project)
    rows[1].update(_SPEC_EXAMPLE)
    rows[1]['contrast'] = ' '.join(['deliberately verbose'] * 20)
    ill.write_plan(in_project, rows)
    entries = {e['id']: e for e in packet.resolve(in_project)['entries']}
    assert len(pp.render_entry(entries['the-blank-page']).split()) > 120


def test_the_rendered_marker_costs_only_the_marker(in_project):
    """The budget governs what a generation session is asked to read and act on.
    A rendered entry is the opposite — it exists to be skipped — so its marker
    is allowed to push the count past 120, but only by the marker: it must add
    no other prose, and every body line must be byte-identical."""
    rows = ill.read_plan(in_project)
    rows[1].update(_SPEC_EXAMPLE)
    ill.write_plan(in_project, rows)
    pending = pp.render_entry(
        {e['id']: e for e in packet.resolve(in_project)['entries']}
        ['the-blank-page'])
    _ingest(in_project, 1)
    rendered = pp.render_entry(
        {e['id']: e for e in packet.resolve(in_project)['entries']}
        ['the-blank-page'])

    cost = len(rendered.split()) - len(pending.split())
    assert cost <= 10, f'the rendered marker costs {cost} words'
    # The marker touches the heading and the metadata line and nothing else:
    # every content line below them is byte-identical.
    assert rendered.split('\n')[3:] == pending.split('\n')[3:]


def test_contrast_is_one_derived_sentence(in_project):
    """Three stacked sentences spent a tenth of the budget restating two facts."""
    rows = ill.read_plan(in_project)
    rows[1]['contrast'] = 'Much wider than the one before it.'
    ill.write_plan(in_project, rows)
    entries = {e['id']: e for e in packet.resolve(in_project)['entries']}
    contrast = entries['the-blank-page']['contrast']
    derived = contrast.replace('Much wider than the one before it.', '').strip()
    assert derived.count('.') == 1, derived
    assert 'darkest' in derived and 'the-finest-cartographer' in derived
    assert 'Much wider than the one before it.' in contrast


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


def _ingest(project_dir, index, **cells):
    """Mark a seeded row ingested with a real file on disk."""
    from illustration_helpers import make_png
    rows = ill.read_plan(project_dir)
    rel = ill.default_asset_rel(rows[index]['id'].strip())
    make_png(os.path.join(project_dir, rel), 8, 12)
    rows[index].update({'status': 'ingested', 'asset_file': rel,
                        'ingested_at': '2026-07-28'})
    rows[index].update(cells)
    ill.write_plan(project_dir, rows)
    return rows[index]['id'].strip()


def test_a_canon_excluded_render_is_named_in_reference_images(in_project):
    """The H1 case: every prior render excluded as pre-canon, and the list
    silently shrinks to the cover — which reads as "nothing is ingested yet"."""
    from illustration_helpers import make_png
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 12)
    # Ingested before the canon was last touched (canon_updated: 2026-07-28).
    _ingest(in_project, 0, ingested_at='2026-01-01')
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'reference-images.md')
    assert 'What is not in that list' in body
    assert 'the-finest-cartographer' in body
    assert 'before the canon was last updated' in body
    assert 'cover-only' in body


def test_a_cover_only_chain_with_ingested_art_is_a_readme_gap(in_project):
    from illustration_helpers import make_png
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 12)
    _ingest(in_project, 0, ingested_at='2026-01-01')
    cmd_illustrate.main(['--package'])
    readme = _read(in_project, 'README.md')
    assert 'cover-only or empty even though this book has ingested' in readme


def test_a_healthy_reference_list_has_no_exclusion_section(in_project):
    from illustration_helpers import make_png
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 12)
    _ingest(in_project, 0, ingested_at='2026-07-29')
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'reference-images.md')
    assert 'What is not in that list' not in body
    assert ill.default_asset_rel('the-finest-cartographer') in body


def test_a_missing_cover_is_disclosed(in_project):
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'reference-images.md')
    assert 'no cover artwork' in body


def test_the_four_image_cap_is_disclosed(in_project):
    """L4: the list stops at four with a silent `break` today."""
    from illustration_helpers import make_png
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 12)
    rows = ill.read_plan(in_project)
    for index in range(6):
        row = ill.blank_row(f'extra-{index}')
        rel = ill.default_asset_rel(row['id'])
        make_png(os.path.join(in_project, rel), 8, 12)
        row.update({'scene_id': 'act1-sc01', 'placement': 'scene_open',
                    'status': 'ingested', 'asset_file': rel,
                    'ingested_at': '2026-07-29', 'beat': 'b', 'subject': 's'})
        rows.append(row)
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'reference-images.md')
    assert 'the list stops at 4 images' in body


def test_an_excluded_render_past_the_cap_is_still_disclosed(in_project):
    """The exclusion check must run before the cap, or a stale render past the
    fourth reference is dropped under a cap that is not why it went."""
    from illustration_helpers import make_png
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 12)
    rows = ill.read_plan(in_project)
    for index in range(5):
        row = ill.blank_row(f'fresh-{index}')
        rel = ill.default_asset_rel(row['id'])
        make_png(os.path.join(in_project, rel), 8, 12)
        row.update({'scene_id': 'act1-sc01', 'placement': 'scene_open',
                    'status': 'ingested', 'asset_file': rel,
                    'ingested_at': '2026-07-29', 'beat': 'b', 'subject': 's'})
        rows.append(row)
    stale = ill.blank_row('stale-one')
    stale_rel = ill.default_asset_rel('stale-one')
    make_png(os.path.join(in_project, stale_rel), 8, 12)
    stale.update({'scene_id': 'act1-sc01', 'placement': 'scene_open',
                  'status': 'ingested', 'asset_file': stale_rel,
                  'ingested_at': '2026-01-01', 'beat': 'b', 'subject': 's'})
    rows.append(stale)
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'reference-images.md')
    assert 'stale-one' in body
    assert 'before the canon was last updated' in body


# ============================================================================
# Rendered entries must not look like pending ones (H2)
# ============================================================================

def test_an_ingested_entry_is_marked_as_already_rendered(in_project):
    _ingest(in_project, 0)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'illustrations.md')
    assert f'### the-finest-cartographer{pp.DONE_MARK}' in body
    assert 'ingested — do not regenerate' in body
    # The pending one is untouched.
    assert '### the-blank-page\n' in body


def test_a_prompted_entry_is_not_marked_as_rendered(in_project):
    rows = ill.read_plan(in_project)
    rows[0]['status'] = 'prompted'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert pp.DONE_MARK not in _read(in_project, 'illustrations.md')


def test_staging_before_the_render_is_not_a_gap(in_project):
    """The documented order — stage, prompt, render, ingest. On a 12-row book
    this fired 12 of 14 gaps before `treatment_at` existed, burying the real
    ones and training the author to skip the section."""
    _ingest(in_project, 0, treatment='wide, high, environmental, dusk',
            treatment_at='2026-07-01', ingested_at='2026-07-20')
    cmd_illustrate.main(['--package'])
    assert 'does not follow its treatment' not in _read(in_project, 'README.md')


def test_staging_after_the_render_is_a_gap_naming_both_dates(in_project):
    _ingest(in_project, 0, treatment='wide, high, environmental, dusk',
            treatment_at='2026-07-25', ingested_at='2026-07-20')
    cmd_illustrate.main(['--package'])
    readme = _read(in_project, 'README.md')
    assert 'does not follow its treatment' in readme
    assert '2026-07-25' in readme and '2026-07-20' in readme


def test_a_missing_stamp_says_nothing(in_project):
    """An unstamped legacy row, or a treatment the author wrote by hand (which
    `--sequence` never stamps, because it never overwrites one), is not
    evidence of a problem."""
    for cells in ({'treatment_at': '', 'ingested_at': '2026-07-20'},
                  {'treatment_at': '2026-07-25', 'ingested_at': ''},
                  {'treatment_at': 'whenever', 'ingested_at': '2026-07-20'}):
        _ingest(in_project, 0, treatment='wide, high, dusk', **cells)
        cmd_illustrate.main(['--package'])
        assert 'does not follow its treatment' not in \
            _read(in_project, 'README.md'), cells


def test_same_day_staging_is_not_a_gap(in_project):
    """Stage, prompt, render, ingest is an ordinary one-day loop, and date
    granularity cannot separate the two."""
    _ingest(in_project, 0, treatment='wide, high, dusk',
            treatment_at='2026-07-20', ingested_at='2026-07-20')
    cmd_illustrate.main(['--package'])
    assert 'does not follow its treatment' not in _read(in_project, 'README.md')


def test_a_treatment_on_pending_art_is_not_reported(in_project):
    rows = ill.read_plan(in_project)
    rows[0]['treatment'] = 'wide, high, environmental, dusk'
    rows[0]['treatment_at'] = '2026-07-25'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert 'does not follow its treatment' not in _read(in_project, 'README.md')


def test_sequence_stamps_when_it_staged_a_row(in_project, staged):
    from datetime import date
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night')))
    assert cmd_illustrate.main(['--sequence']) == 0
    plan = ill.read_plan_as_map(in_project)
    assert plan['the-finest-cartographer']['treatment_at'] == \
        date.today().isoformat()
    # A row it did not stage is not stamped.
    assert plan['the-blank-page']['treatment_at'] == ''


def test_an_author_treatment_is_never_stamped(in_project, staged):
    """`--sequence` skips the row entirely, so no stamp is invented for a
    treatment it did not write — which is what keeps the gap silent for it."""
    rows = ill.read_plan(in_project)
    rows[0]['treatment'] = 'wide, high, environmental, dusk'
    ill.write_plan(in_project, rows)
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night')))
    cmd_illustrate.main(['--sequence'])
    assert ill.read_plan_as_map(in_project)[
        'the-finest-cartographer']['treatment_at'] == ''


def test_an_unrecognized_status_errs_toward_being_read(in_project):
    """`validate_plan` gates the vocabulary, but if one slips through, marking
    an entry "already rendered — do not regenerate" would drop an illustration
    from the book. Falling toward pending costs a glance."""
    rows = ill.read_plan(in_project)
    rows[0]['status'] = 'rendring'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'illustrations.md')
    assert f'### the-finest-cartographer{pp.DONE_MARK}' not in body
    assert '### the-finest-cartographer\n' in body


def test_a_rendered_status_is_marked_as_well_as_ingested(in_project):
    rows = ill.read_plan(in_project)
    rows[0]['status'] = 'rendered'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert f'### the-finest-cartographer{pp.DONE_MARK}' in \
        _read(in_project, 'illustrations.md')


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


def test_the_disclosure_count_counts_notes_not_slots(in_project):
    """L3: `fallback` also carries the "brackets nothing" observation, which is
    about the batch as a whole and would overstate a slot count."""
    rows = ill.read_plan(in_project)
    rows[0]['register'] = ''
    rows[1]['register'] = 'darkest'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')
    batch = packet.anchor_batch(in_project)
    assert 'brackets nothing' in body
    assert f'{len(batch["fallback"])} note(s) on how it was chosen' in body
    assert 'slot(s) are guessed' not in body


def test_diagnose_reports_the_anchor_batch(in_project, capsys):
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Anchor batch' in out
    assert 'the-finest-cartographer' in out


def test_diagnose_reports_the_packet_rung(in_project, capsys):
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Packet: not built' in out
    assert 'Sequence staging: 0 of 2' in out

    cmd_illustrate.main(['--package'])
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Packet: built and current' in out
    # Two distinct rows fill three slots in the seeded plan; the fourth slot
    # (later-state exemplar) is unfilled and cannot be waited on.
    assert 'anchor batch: 2 row(s) not yet ingested' in out


def test_diagnose_reports_a_stale_packet(in_project, capsys):
    cmd_illustrate.main(['--package'])
    future = os.path.getmtime(
        packet.packet_file(in_project, 'README.md')) + 60
    os.utime(ill.plan_path(in_project), (future, future))
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Packet: built and stale' in out
    assert 'illustration-plan.csv' in out


def test_diagnose_reports_a_drifted_anchor_copy(in_project, capsys):
    cmd_illustrate.main(['--package'])
    path = packet.packet_file(in_project, 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    original = next(iter(canon.anchor_texts(in_project).values()))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace(original, original.replace('.', '!', 1)))
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'anchor copy problem' in out
    assert 'anchor_copy_drift' in out


def test_diagnose_says_when_the_packet_is_ready_to_hand_over(in_project,
                                                            capsys):
    """Every anchor-batch row ingested is the Churn rung."""
    from illustration_helpers import make_png
    rows = ill.read_plan(in_project)
    for row in rows:
        rel = ill.default_asset_rel(row['id'].strip())
        make_png(os.path.join(in_project, rel), 8, 12)
        row['status'] = 'ingested'
        row['asset_file'] = rel
        row['treatment'] = f'staging for {row["id"].strip()}'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'ready to hand over' in out
    assert 'all 2 illustration(s) carry a treatment' in out


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


def test_a_run_that_changes_nothing_does_not_touch_the_plan(in_project, staged):
    """L1: rewriting identical bytes bumps the mtime, and an existing packet
    then reports `packet_stale` over a run that changed nothing."""
    rows = ill.read_plan(in_project)
    for row in rows:
        row['treatment'] = 'wide, high, environmental, dusk'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    before = os.path.getmtime(ill.plan_path(in_project))

    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night')))
    assert cmd_illustrate.main(['--sequence']) == 0
    assert os.path.getmtime(ill.plan_path(in_project)) == before
    assert packet.packet_stale(in_project) == []


def test_coach_mode_still_reports_duplicate_treatments(in_project, staged,
                                                       capsys):
    """L2: the author is about to hand-copy these, and a repeat defeats the
    pass whichever hand writes it."""
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night'),
        ('the-blank-page', 'close, low, interior, night')))
    assert cmd_illustrate.main(['--sequence', '--coaching', 'coach']) == 0
    out = capsys.readouterr().out
    assert 'share one treatment in this brief' in out
    assert 'the-blank-page' in out


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
# The resolved visual state reaches --prompts (#297)
# ============================================================================
#
# Rebuilding all 20 prompts for a real book, two prompts straddling a costume
# changeover came back wrong in *opposite* directions: the night-one image in
# the night-two jacket, the night-two image in pajamas. The matrix was right in
# both cases — the packet's `**State.**` line said so — but
# `build_art_direction_request` never received it, so every costume in a
# generated prompt was the model's inference from anchor prose describing the
# whole book. Pinning the changeover to scene ids in the anchors fixed one row
# and not the other; setting `state_override` did nothing, because the column
# was not in the request either.
# ============================================================================

@pytest.fixture
def captured(monkeypatch):
    """Run `--prompts` and return {illus_id: art-direction request}."""
    def _run(*argv):
        requests = {}

        def _invoke(project_dir, prompt, operation, **kwargs):
            requests[kwargs.get('target') or operation] = prompt
            return '### Scene\n\nA room.\n'
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr(cmd_illustrate, '_invoke', _invoke)
        assert cmd_illustrate.main(['--prompts', '--coaching', 'full', *argv]) == 0
        return requests
    return _run


def _set_production(project_dir, key, value):
    """Append a key under the `production:` section of storyforge.yaml."""
    path = os.path.join(project_dir, 'storyforge.yaml')
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.startswith('production:'):
            out.append(f'  {key}: {value}\n')
            inserted = True
    if not inserted:
        out.append(f'production:\n  {key}: {value}\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(out)


def _backdate(path, iso_date):
    """Set a file's mtime to local midnight on an ISO date."""
    from datetime import datetime
    stamp = datetime.fromisoformat(f'{iso_date}T00:00:00').timestamp()
    os.utime(path, (stamp, stamp))


def _add_transition(project_dir, **cells):
    from storyforge import visual_state as vs
    rows = list(vs.read_transitions(project_dir))
    rows.append(cells)
    vs.write_transitions(project_dir, rows)


def _later_state_anchor(project_dir):
    """Re-anchor Dorren with an emphatic clause about her *later* wardrobe.

    This is the shape that actually bit: an anchor clause added after a sequence
    review ("it is how the reader finds her in a dark image") is exactly why a
    model reached for the later costume in an earlier scene.
    """
    from illustration_helpers import write_canon_file
    write_canon_file(
        project_dir, canon_id='dorren-hayle', canon_type='character',
        subdir='characters',
        body='Dorren Hayle: fifty-one, grey hair pinned flat. From act1-sc02 '
             'onward she wears a rust-red travelling coat, the one warm colour '
             'she carries, and it is how the reader finds her in a dark image.')


def _state_section(request):
    """Just the `## The visual state in THIS image` block of a request.

    Asserted against rather than the whole request, because an anchor
    necessarily describes the whole book — Dorren's fixture anchor contains the
    words "black wool waistcoat" — so a negative assertion over the full text
    cannot tell "the walk resolved wrongly" from "the anchor mentions it", which
    is the exact confusion #297 is about.
    """
    _, _, tail = request.partition('## The visual state in THIS image')
    return tail.partition('\n##')[0]


def test_the_resolved_state_reaches_the_art_direction_request(in_project,
                                                              captured):
    """The core regression: the row's scene resolves to the *early* state while
    the anchor describes the later one, emphatically."""
    _later_state_anchor(in_project)
    _add_transition(in_project, entity='dorren-hayle-clothing',
                    from_scene='act1-sc02',
                    state='rust-red travelling coat, hood back',
                    evidence='Blank parchment')
    _add_transition(in_project, entity='dorren-hayle-clothing',
                    from_scene='act1-sc01',
                    state='black wool waistcoat, sleeves buttoned to the wrist',
                    evidence='held her breath')

    request = captured()['the-finest-cartographer']
    state = _state_section(request)
    assert 'black wool waistcoat, sleeves buttoned to the wrist' in state
    assert 'rust-red travelling coat, hood back' not in state
    # Stated as a requirement that outranks the anchor, not as context — the
    # anchor is a paragraph of vivid prose and this is one line.
    assert 'The visual state in THIS image' in request
    assert 'requirement' in request
    assert 'outranks the character anchors' in request


def test_a_later_scene_row_gets_the_later_state_not_the_earlier(in_project,
                                                               captured):
    """The *other* half of the reported failure: LF-05 came back in pajamas.

    The sibling test above covers the first direction, but its row sits at the
    book's first scene, so the entity's earliest transition happens to be the
    right answer — the whole section passed with the forward walk stuck on the
    earliest transition per entity. This is the one that fails when it is.
    """
    _add_transition(in_project, entity='dorren-hayle-clothing',
                    from_scene='act1-sc01',
                    state='black wool waistcoat, sleeves buttoned',
                    evidence='held her breath')
    _add_transition(in_project, entity='dorren-hayle-clothing',
                    from_scene='act1-sc02',
                    state='rust-red travelling coat, hood back',
                    evidence='Blank parchment')
    rows = ill.read_plan(in_project)
    # the-blank-page is at act1-sc02; name Dorren so she resolves there too.
    rows[1].update({'canon_refs': 'maps;dorren-hayle', 'state_override': ''})
    ill.write_plan(in_project, rows)

    requests = captured()
    early = _state_section(requests['the-finest-cartographer'])
    late = _state_section(requests['the-blank-page'])
    # Qualified by track. The fixture also seeds a *bare* `dorren-hayle`
    # transition, which `canon_refs: dorren-hayle` matches too and which
    # correctly still reads its act1-sc01 value at the later scene — so an
    # unqualified assertion would fail on a working forward walk.
    assert 'Dorren Hayle (clothing): black wool waistcoat' in early
    assert 'Dorren Hayle (clothing): rust-red travelling coat' not in early
    assert 'Dorren Hayle (clothing): rust-red travelling coat, hood back' in late
    assert 'Dorren Hayle (clothing): black wool waistcoat' not in late


def test_state_override_beats_the_forward_walk_in_the_request(in_project,
                                                             captured):
    """`maps` has a transition at act1-sc02 and the row overrides it."""
    request = captured()['the-blank-page']
    assert 'one corner curled back under a paperweight' in request
    assert 'the new survey blank where the village was' not in request


def test_the_prompt_file_and_the_packet_entry_agree_about_the_state(in_project,
                                                                   captured):
    """Two disjoint renderings of one row is how they disagree; one resolution
    is how they cannot."""
    captured()
    cmd_illustrate.main(['--package'])
    entry = _read(in_project, 'illustrations.md')
    with open(os.path.join(in_project,
                           ill.default_prompt_rel('the-finest-cartographer')),
              encoding='utf-8') as f:
        prompt_file = f.read()
    state = {e['id']: e for e in packet.resolve(in_project)['entries']
             }['the-finest-cartographer']['state']
    assert state
    assert state in entry
    assert state in prompt_file


def test_the_prompt_file_carries_the_state_as_a_constraint(in_project, captured):
    """It appears twice by design, as the orientation directive does: a model
    that dropped it would leave a file whose costume is inference, and the
    working fix on the real book was hand-editing the body."""
    captured()
    with open(os.path.join(in_project,
                           ill.default_prompt_rel('the-finest-cartographer')),
              encoding='utf-8') as f:
        content = f.read()
    assert 'overrides any anchor detail that disagrees' in content
    assert '## Accept only if' in content
    assert 'The visual state matches: Dorren Hayle' in content


def test_absent_reaches_the_request_as_an_explicit_exclusion(in_project,
                                                             captured):
    rows = ill.read_plan(in_project)
    rows[0]['absent'] = 'the apprentice; any second lamp'
    ill.write_plan(in_project, rows)

    request = captured()['the-finest-cartographer']
    assert 'Must not appear in this image' in request
    assert 'the apprentice; any second lamp' in request
    assert 'only exceptions to the positive-framing rule' in request


def test_contrast_reaches_the_request_without_naming_other_illustrations(
        in_project, captured):
    request = captured()['the-blank-page']
    assert 'What must set this image apart' in request
    assert 'darkest image in the book' in request
    assert 'Do not name another illustration in the prompt body' in request


def test_no_state_block_when_the_row_resolves_to_nothing(in_project, captured):
    """A row with no canon_refs has no state, and the request must not carry an
    empty section header claiming otherwise.

    Asserts only about the state block. It also used to assert the *absent* block
    was missing, which would have passed on a build where that block was
    unconditional — `absent` was never populated on the row.
    """
    rows = ill.read_plan(in_project)
    rows[0].update({'canon_refs': '', 'state_override': '', 'register': ''})
    ill.write_plan(in_project, rows)

    request = captured('--ids', 'the-finest-cartographer'
                       )['the-finest-cartographer']
    assert 'The visual state in THIS image' not in request


def test_the_absent_block_disappears_when_the_cell_is_cleared(in_project,
                                                             captured):
    """The negative half of the `absent` test, on a row that *could* have had
    one — the sibling above cannot show this, because it never set `absent`."""
    rows = ill.read_plan(in_project)
    rows[0]['absent'] = ''
    ill.write_plan(in_project, rows)
    assert 'Must not appear in this image' not in \
        captured('--ids', 'the-finest-cartographer')['the-finest-cartographer']


def test_prompts_reports_an_entity_with_no_stated_visual_state(in_project,
                                                               captured,
                                                               capsys):
    """`cartography-office` is deliberately unstated in the seeded matrix, and
    the free moment to hear about it is before 20 calls go out."""
    captured()
    out = capsys.readouterr().out
    assert 'cartography-office' in out
    assert 'no transition states its visual state there' in out


def test_prompts_does_not_double_report_an_unanchored_canon_ref(in_project,
                                                               captured,
                                                               capsys):
    """`_warn_unanchored_rows` already names these; a second copy of the same
    finding trains an author to skim the log where the other gaps live."""
    rows = ill.read_plan(in_project)
    rows[0]['canon_refs'] = 'dorren-hayle;nobody-at-all'
    ill.write_plan(in_project, rows)

    captured()
    out = capsys.readouterr().out
    # Still reported, by the check that runs before the fan-out.
    assert 'name canon_refs with no continuity anchor' in out
    assert 'nobody-at-all' in out
    # But not a second time, in the packet's wording.
    assert 'resolves to no populated canon file' not in out


def test_a_declared_style_reference_reaches_the_packet(in_project):
    """The packet is what the author uploads from, so the declaration has to win
    here too — not only in --prompts."""
    from illustration_helpers import make_png
    assets = os.path.join(in_project, 'manuscript', 'assets')
    make_png(os.path.join(assets, 'cover-illustration.png'), 8, 8)  # superseded
    make_png(os.path.join(assets, 'selected-art.png'), 8, 8)
    _set_production(in_project, 'cover_artwork',
                    'manuscript/assets/selected-art.png')

    assert cmd_illustrate.main(['--package']) == 0
    body = _read(in_project, 'reference-images.md')
    assert 'selected-art.png' in body
    assert 'cover-illustration.png' not in body


def test_a_stale_style_reference_is_disclosed_in_the_packet(in_project, capsys):
    """It is never excluded, so the packet must say it is old — in README's gaps
    as well as reference-images.md, because run_package logs only `gaps`."""
    from illustration_helpers import make_png
    cover = make_png(os.path.join(in_project, 'manuscript', 'assets',
                                  'cover-illustration.png'), 8, 8)
    _backdate(cover, '2026-01-01')          # canon fixture is 2026-07-28

    assert cmd_illustrate.main(['--package']) == 0
    out = capsys.readouterr().out
    assert 'before the canon was last updated' in out
    assert 'before the canon was last updated' in _read(in_project, 'README.md')
    assert 'before the canon was last updated' in \
        _read(in_project, 'reference-images.md')


def test_the_positive_headline_never_reaches_the_packet(in_project):
    """The `describe_style_reference` / `style_reference_warnings` split exists
    for this: a resolution line under "What is not in that list" reads as an
    exclusion."""
    from illustration_helpers import make_png
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 8)
    cmd_illustrate.main(['--package'])
    assert 'Style reference:' not in _read(in_project, 'reference-images.md')


def test_a_missing_declaration_is_a_packet_gap_not_a_refusal(in_project):
    """--package is assembly and reports what it cannot tell you; only
    --prompts refuses, because only --prompts spends money on the wrong art."""
    from illustration_helpers import make_png
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 8)
    _set_production(in_project, 'cover_artwork', 'manuscript/assets/gone.png')

    assert cmd_illustrate.main(['--package']) == 0
    assert 'which does not exist' in _read(in_project, 'README.md')


def test_a_revived_superseded_row_is_not_treated_as_the_books_first(in_project,
                                                                   capsys):
    """`rows_in_reading_order` excludes `superseded` while `--prompts --ids`
    revives one, so a `.get(id, '')` default merged "not in the order I indexed"
    into "starts the book" — the prompt lost its contrast clause while the packet
    built after ingest had one."""
    rows = ill.read_plan(in_project)
    rows[1]['status'] = 'superseded'
    ill.write_plan(in_project, rows)

    context = packet.state_context(in_project, plan=ill.read_plan(in_project))
    assert rows[1]['id'] not in context['predecessors']
    contrast = packet.contrast_for_row(rows[1], context=context)
    assert 'follows' not in contrast
    assert 'not in the book' in capsys.readouterr().out


def test_state_context_and_the_packet_share_one_resolution(in_project):
    context = packet.state_context(in_project)
    rows = {r['id'].strip(): r for r in packet.rows_in_reading_order(in_project)}
    entries = {e['id']: e for e in packet.resolve(in_project)['entries']}
    for illus_id, row in rows.items():
        state, _gaps = packet.state_for_row(row, context=context)
        assert state == entries[illus_id]['state']
        assert packet.contrast_for_row(row, context=context) == \
            entries[illus_id]['contrast']


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

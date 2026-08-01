"""Tests for `storyforge illustrate --package` — the handoff packet (#278 ph3).

The packet is assembly: it must make no API call, produce identical bytes on a
re-run over unchanged sources, carry every continuity anchor byte-identically,
and state its own gaps rather than reading as coverage it does not have.

`in_project` seeds canon files, a plan, and state transitions into a copy of the
fixture — the shared fixture has none of those (checked, not assumed).
"""

import os
import re

import pytest

from storyforge import canon, cmd_illustrate, packet
from storyforge import illustrations as ill
from storyforge import prompts_illustrate as pi
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


def _read_prompt(project_dir, illus_id):
    with open(packet.image_prompt_file(project_dir, illus_id),
              encoding='utf-8') as f:
        return f.read()


def _read_all(project_dir):
    return {name: _read(project_dir, name) for name in packet.PACKET_FILES}


# ============================================================================
# The six files
# ============================================================================

def test_package_writes_every_root_file_and_one_prompt_per_illustration(
        in_project):
    assert cmd_illustrate.main(['--package']) == 0
    for name in ('README.md', 'canon.md', 'visual-state.md',
                 'illustrations.md', 'acceptance.md'):
        assert os.path.isfile(os.path.join(in_project, packet.PACKET_DIR, name))
    assert sorted(os.listdir(packet.image_prompts_dir(in_project))) == [
        'the-blank-page.md', 'the-finest-cartographer.md']


def test_reference_images_md_is_gone(in_project):
    """Its upload list and its exclusion notes moved into README, beside the
    runbook step they are about. A leftover file would be a second, stale answer
    to "what do I upload"."""
    cmd_illustrate.main(['--package'])
    assert 'reference-images.md' not in packet.PACKET_FILES
    assert not os.path.isfile(
        os.path.join(in_project, packet.PACKET_DIR, 'reference-images.md'))


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


def _art_cell(body, illus_id):
    """The `Art` cell for one row of `illustrations.md`'s index table."""
    for line in body.split('\n'):
        if line.startswith('|') and f'`{illus_id}`' in line:
            return [c.strip() for c in line.split('|')][5]
    raise AssertionError(f'{illus_id} has no row in the index table')


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


def test_an_image_prompt_carries_only_model_facing_sections(in_project):
    """The invariant the whole redesign rests on (#306).

    The author uploads this file, so every heading in it reaches the image
    model. Its predecessor marked a paste boundary and put four author-facing
    sections above it — on the real book, 9.5 KB of a 13.9 KB file. A regression
    here uploads seventeen paragraphs of canon-staleness prose to an image
    model, and nothing about the resulting image would look wrong.
    """
    from illustration_helpers import write_prompt_file
    rows = ill.read_plan(in_project)
    rows[1].update(_SPEC_EXAMPLE)
    ill.write_plan(in_project, rows)
    # A real prompt file on disk, not just the plan-row stand-in. Without one
    # every body comes from `_derived_body`, whose four headings ARE the
    # enumeration — so the assertion could not fail (#306 review, T-3).
    write_prompt_file(in_project, 'the-finest-cartographer')
    _ingest(in_project, 0, ingested_at='')      # stale: the loudest author-facing case
    cmd_illustrate.main(['--package'])

    for name in os.listdir(packet.image_prompts_dir(in_project)):
        text = _read_prompt(in_project, name[:-3])
        headings = re.findall(r'^#{2,6} (.+)$', text, re.MULTILINE)
        assert set(headings) <= set(pp.IMAGE_PROMPT_SECTIONS), \
            f'{name} carries a section the image model should not read: ' \
            f'{sorted(set(headings) - set(pp.IMAGE_PROMPT_SECTIONS))}'
        # A floor as well as a ceiling: a subset assertion passes over a body
        # that rendered nothing at all.
        assert 'Constraints' in headings
        assert len(headings) >= 4, f'{name} rendered almost nothing: {headings}'


@pytest.mark.parametrize('forbidden', [
    'Read this first',          # author-facing blockers
    'References to upload',     # the uploads are book-level now
    'About these reference images',
    'Accept only if',           # collapsed into acceptance.md
    'Staging assigned',         # the body already embodies the treatment
    'Where this came from',     # provenance; identical in every file
    'Paste everything below',   # there is no paste boundary in an upload
    'do NOT paste',
])
def test_the_retired_author_facing_sections_stay_out(in_project, forbidden):
    """Named individually, because the heading-set test above only catches a
    `##` heading — a regression could reintroduce any of these as bold prose.

    Five of these eight live in `render_prompt_file`'s output rather than in any
    packet renderer, and the only thing keeping them out of an upload is
    `parse_prompt_file`'s bounds. Without a real prompt file on disk they could
    not appear whatever the code did (#306 review, T-3).
    """
    from illustration_helpers import write_prompt_file
    write_prompt_file(in_project, 'the-finest-cartographer')
    _ingest(in_project, 0, ingested_at='')
    cmd_illustrate.main(['--package'])
    for name in os.listdir(packet.image_prompts_dir(in_project)):
        assert forbidden not in _read_prompt(in_project, name[:-3])


def test_the_author_facing_half_is_in_illustrations_md(in_project):
    """The other half of the invariant: removed from the upload, not dropped."""
    _ingest(in_project, 0, ingested_at='')
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'illustrations.md')
    assert '**Re-render.**' in body
    assert 'the-finest-cartographer' in body


def test_an_image_prompt_stays_small_enough_to_be_read_whole(in_project):
    """Size is a correctness property here, not tidiness: a small text file is
    read into context whole, and a summarized continuity anchor is a paraphrased
    one. The bound is generous — the point is that nothing book-level leaks back
    in, which is what took the export's file to 13.9 KB."""
    from illustration_helpers import write_prompt_file
    rows = ill.read_plan(in_project)
    rows[1].update(_SPEC_EXAMPLE)
    ill.write_plan(in_project, rows)
    write_prompt_file(in_project, 'the-finest-cartographer')
    cmd_illustrate.main(['--package'])
    for name in os.listdir(packet.image_prompts_dir(in_project)):
        size = len(_read_prompt(in_project, name[:-3]).encode('utf-8'))
        # 2,500 rather than 6,000: measured, the fixture's uploads are ~1.2-1.5
        # KB, and the whole author-facing corpus for both rows is 2.3 KB — so a
        # 6,000 bound could not fail even with every retired section re-added.
        # That is `_SPEC_EXAMPLE`'s own lesson about the retired word budget.
        assert size < 2500, f'{name} is {size} bytes'





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


def test_state_reaches_the_image_prompt_as_a_constraint(in_project):
    """The resolved matrix is what tells the model which night this is, and it
    outranks the anchors — so it goes to the model, in the file the model reads,
    rather than into an index line only the author sees."""
    cmd_illustrate.main(['--package'])
    prompt = _read_prompt(in_project, 'the-finest-cartographer')
    assert 'which overrides any anchor detail that disagrees' in prompt
    assert 'Dorren Hayle: black waistcoat' in prompt


def test_reference_images_are_pathed_not_copied(in_project):
    from illustration_helpers import make_png
    cover = os.path.join('manuscript', 'assets', 'cover-illustration.png')
    make_png(os.path.join(in_project, cover), 8, 12)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')
    assert cover in body
    # Nothing was copied in beside the markdown and the image-prompt directory.
    assert sorted(os.listdir(packet.packet_dir(in_project))) == \
        sorted([*packet.PACKET_FILES, packet.IMAGE_PROMPTS_SUBDIR])


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
    body = _read(in_project, 'README.md')
    assert 'Read this before you upload' in body
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
    body = _read(in_project, 'README.md')
    assert 'Read this before you upload' not in body
    assert ill.default_asset_rel('the-finest-cartographer') in body


def test_a_missing_cover_is_disclosed(in_project):
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')
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
    body = _read(in_project, 'README.md')
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
    body = _read(in_project, 'README.md')
    assert 'stale-one' in body
    assert 'before the canon was last updated' in body


# ============================================================================
# Rendered entries must not look like pending ones (H2)
# ============================================================================

def test_an_ingested_entry_is_marked_as_already_rendered(in_project):
    _ingest(in_project, 0)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'illustrations.md')
    assert _art_cell(body, 'the-finest-cartographer') == 'done'
    # The pending one is untouched.
    assert _art_cell(body, 'the-blank-page') == 'to render'


def test_a_prompted_entry_is_not_marked_as_rendered(in_project):
    rows = ill.read_plan(in_project)
    rows[0]['status'] = 'prompted'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert _art_cell(_read(in_project, 'illustrations.md'),
                     'the-finest-cartographer') == 'to render'


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
    assert _art_cell(_read(in_project, 'illustrations.md'),
                     'the-finest-cartographer') == 'to render'


def test_a_rendered_status_is_marked_as_well_as_ingested(in_project):
    rows = ill.read_plan(in_project)
    rows[0]['status'] = 'rendered'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert _art_cell(_read(in_project, 'illustrations.md'),
                     'the-finest-cartographer') == 'done'


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
    """Every anchor-batch row ingested *from the current canon* is the Churn
    rung. `ingested_at` matches the seeded `canon_updated`, which is what makes
    the art current — an empty one would report as needing a re-render (#300)."""
    from illustration_helpers import make_png
    rows = ill.read_plan(in_project)
    for row in rows:
        rel = ill.default_asset_rel(row['id'].strip())
        make_png(os.path.join(in_project, rel), 8, 12)
        row['status'] = 'ingested'
        row['asset_file'] = rel
        row['ingested_at'] = '2026-07-28'
        row['treatment'] = f'staging for {row["id"].strip()}'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'ready to hand over' in out
    assert 'all 2 illustration(s) carry a treatment' in out


def test_an_ingested_batch_row_is_marked_as_such(in_project):
    _ingest(in_project, 0)  # ingested_at == the seeded canon_updated
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')
    line = next(l for l in body.splitlines()
                if '`the-finest-cartographer`' in l and '|' in l)
    assert line.strip().endswith('| yes |')


# ============================================================================
# Canon-stale ingested art is not a finished handoff (#300)
# ============================================================================

def _four_stale_slots(project_dir):
    """A plan filling all four batch slots with four distinct rows, every one
    `ingested` with an empty `ingested_at` — *The Lantern Folk*'s shape.

    The seeded canon is `canon_updated: 2026-07-28`, so every row's art predates
    the canon governing it while `status` says the set is finished.
    """
    from illustration_helpers import make_png
    from storyforge import visual_state as vs

    # `maps` first transitions at act1-sc02 (seeded); a second, later one is
    # what lets an illustration show it in a state later than its first.
    transitions = vs.read_transitions(project_dir)
    transitions.append({'entity': 'maps', 'from_scene': 'act2-sc01',
                        'state': 'rolled and shelved', 'evidence': ''})
    vs.write_transitions(project_dir, transitions)

    spec = (
        # id, scene, canon_refs, register — two anchors puts the establisher in
        # the horizon; the registers are declared so neither slot is a guess.
        ('a-establisher', 'act1-sc01', 'dorren-hayle;cartography-office', ''),
        ('b-darkest', 'act1-sc01', '', 'darkest'),
        ('c-brightest', 'act1-sc02', '', 'brightest'),
        ('d-later-state', 'act2-sc01', 'maps', ''),
    )
    ids = _write_slot_rows(project_dir, spec, ingested_at='')
    # The guard lives in the helper, not in one caller: removing the `maps`
    # transition above silently emptied the later-state slot and five of this
    # helper's six tests went on passing while testing three slots.
    batch = packet.anchor_batch(project_dir)
    assert [batch[slot] for slot, _ in packet.BATCH_SLOTS] == ids, \
        'the fixture must fill all four slots with four distinct rows'
    return ids


def _write_slot_rows(project_dir, spec, *, ingested_at):
    """Write one ingested row per spec tuple, and return the ids in order."""
    from illustration_helpers import make_png
    rows = []
    for illus_id, scene_id, refs, register in spec:
        rel = ill.default_asset_rel(illus_id)
        full = os.path.join(project_dir, rel)
        make_png(full, 8, 12)
        row = ill.blank_row(illus_id)
        row.update({'scene_id': scene_id, 'placement': 'scene_open',
                    'beat': 'b', 'subject': 's', 'canon_refs': refs,
                    'register': register, 'status': 'ingested',
                    'asset_file': rel, 'ingested_at': ingested_at,
                    # A real digest, so the row is genuinely publishable and the
                    # no-demotion assertion is about status rather than about a
                    # row `manifest_assets` would have skipped anyway.
                    'sha256': ill.sha256_of(full), 'width': '8', 'height': '12'})
        rows.append(row)
    ill.write_plan(project_dir, rows)
    return [illus_id for illus_id, *_ in spec]


def test_four_canon_stale_batch_rows_all_report_as_needing_a_render(in_project):
    """The regression #300 names. Every slot filled, every row `ingested`, every
    render pre-canon: the table said `yes` four times and a session working the
    packet top to bottom skipped phase 1 entirely."""
    ids = _four_stale_slots(in_project)  # asserts all four slots are distinct
    assert cmd_illustrate.main(['--package']) == 0
    body = _read(in_project, 'README.md')
    for illus_id in ids:
        line = next(l for l in body.splitlines()
                    if f'`{illus_id}`' in l and l.startswith('|'))
        assert line.strip().endswith('| re-render |'), line
    assert '| yes |' not in body
    # And the reason, per row, because `status` still says ingested everywhere
    # else and an unexplained instruction reads as a packet defect.
    assert 'does not follow the canon in force now' in body
    assert body.count('`ingested_at` is empty') >= len(ids)


def test_a_canon_stale_batch_is_never_ready_to_hand_over(in_project, capsys):
    ids = _four_stale_slots(in_project)
    cmd_illustrate.main(['--package'])
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'ready to hand over' not in out
    assert 'predate the current canon' in out
    # The slot mark itself, which nothing asserted: deleting the whole stale
    # branch of `_report_anchor_batch` passed the entire suite, restoring
    # `[ingested]` on art the canon had outgrown — #300 on the stdout channel
    # the issue quotes.
    for illus_id in ids:
        assert f'{illus_id}  [ingested, but needs a re-render]' in out
    assert '  [ingested]\n' not in out
    # And the advice that keeps the author off the demotion workaround.
    assert 'Leave `status` alone' in out


def test_diagnose_names_every_canon_stale_render_with_its_reason(in_project,
                                                                capsys):
    """A book can have twenty stale renders and none of them in the batch, so
    the whole-plan line is what says how much of the set needs redoing."""
    ids = _four_stale_slots(in_project)
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert (f'{len(ids)} of {len(ids)} illustration(s) predate the current '
            f'canon') in out
    # One reason per row, in the findings list — and *only* there. Stating each
    # reason in the rung summary too said the same sentence five times.
    for illus_id in ids:
        assert f'[canon_stale_render] {illus_id}:' in out
    assert out.count('`ingested_at` is empty, so it predates') == len(ids)
    # And the render order marks them apart from art that is actually done.
    assert '~  1. a-establisher' in out
    # The batch's own warning names them once, aggregated, and says what the
    # real consequence is — not the drift the reference gate already prevents.
    assert 'no likeness reference beyond the cover' in out


def test_a_canon_stale_entry_does_not_say_do_not_regenerate(in_project):
    _four_stale_slots(in_project)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'illustrations.md')
    assert 'do not regenerate' not in body
    assert _art_cell(body, 'a-establisher') == '**re-render**'
    assert '### `a-establisher`' in body
    assert '**Re-render.**' in body
    assert '`ingested_at` is empty' in body


def test_the_batch_and_the_reference_list_cannot_disagree_in_one_run(in_project):
    """The sharp part of #300: one `--package` run held both that these images
    were too stale to reference and that they were done."""
    _four_stale_slots(in_project)
    cmd_illustrate.main(['--package'])
    excluded = _read(in_project, 'README.md')
    assert 'a-establisher' in excluded
    assert 'are **not** listed' in excluded
    assert '| yes |' not in excluded


def test_reporting_a_stale_render_does_not_demote_its_status(in_project):
    """The workaround this replaces: demoting to `prompted` dropped the row from
    the Bookshelf publish manifest while the epub, the PDF, and the web book kept
    shipping it, so the editions disagreed about art the author had retired."""
    ids = _four_stale_slots(in_project)
    cmd_illustrate.main(['--package'])
    cmd_illustrate.main(['--diagnose'])
    plan = ill.read_plan_as_map(in_project)
    assert all(plan[i]['status'] == 'ingested' for i in ids)
    assert {a['key'] for a in ill.manifest_assets(in_project)} == set(ids)


def test_the_demotion_penalty_is_the_one_the_warning_names(in_project):
    """The claim that motivates the whole design, pinned. It was stated as all
    four targets across five places including an author-facing WARNING; only
    Bookshelf actually gates on `ingested`, because `resolve_for_local` excludes
    only `superseded`. A design argument sized by a false penalty is one a
    maintainer discounts along with the text around it."""
    ids = _four_stale_slots(in_project)
    scene_text = '![[illus:a-establisher]]\n'
    assert {a['key'] for a in ill.manifest_assets(in_project)} == set(ids)
    assert 'a-establisher.png' in ill.resolve_for_local(in_project, scene_text)

    rows = ill.read_plan(in_project)
    rows[0]['status'] = 'prompted'
    ill.write_plan(in_project, rows)
    # Bookshelf drops it...
    assert 'a-establisher' not in {a['key'] for a in
                                   ill.manifest_assets(in_project)}
    # ...and the epub, the PDF, and the web book do not.
    assert 'a-establisher.png' in ill.resolve_for_local(in_project, scene_text)


def test_a_mixed_batch_reports_both_pending_and_stale(in_project, capsys):
    """Render the batch, ingest some, then edit canon — the *normal* mid-flight
    state, and the one where either message alone is a lie. Neither branch may
    suppress the other, and "ready to hand over" must stay away from both."""
    spec = (
        ('a-establisher', 'act1-sc01', 'dorren-hayle;cartography-office', ''),
        ('b-darkest', 'act1-sc01', '', 'darkest'),
        ('c-brightest', 'act1-sc02', '', 'brightest'),
        ('d-later-state', 'act2-sc01', 'maps', ''),
    )
    _write_slot_rows(in_project, spec, ingested_at='2026-07-28')  # all current
    rows = ill.read_plan(in_project)
    rows[0]['ingested_at'] = ''          # canon-stale
    rows[1]['status'] = 'planned'        # never rendered
    ill.write_plan(in_project, rows)

    cmd_illustrate.main(['--package'])
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'not yet ingested (b-darkest)' in out
    assert 'ingested but predate the current canon (a-establisher)' in out
    assert 'ready to hand over' not in out

    body = _read(in_project, 'README.md')
    assert '| re-render |' in body and '| not yet |' in body and '| yes |' in body
    # Singular, because exactly one slot is stale — the count and the verb agree.
    assert '**1 of these already has art' in body


def test_the_canon_tree_is_walked_once_per_run(in_project, capsys, monkeypatch):
    """An unparseable `canon_updated` logs a WARNING per *walk*, so five walks
    read as five broken files. `--package` did five and `--diagnose` two; the
    cutoff is now read once and threaded into every consumer."""
    from storyforge import canon as canon_mod
    path = os.path.join(in_project, 'reference', 'canon',
                        'visual-foundation.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('canon_updated: 2026-07-28',
                             'canon_updated: TBD'))
    # A second file still dates the canon, so this is about the WARNING only.
    assert canon_mod.newest_canon_updated(in_project) == '2026-07-28'

    walks = []
    real = canon_mod.newest_canon_updated
    monkeypatch.setattr(canon_mod, 'newest_canon_updated',
                        lambda pd: (walks.append(pd), real(pd))[1])
    for argv in (['--package'], ['--diagnose']):
        walks.clear()
        capsys.readouterr()
        cmd_illustrate.main(argv)
        out = capsys.readouterr().out
        assert len(walks) == 1, f'{argv}: {len(walks)} canon-tree walks'
        assert out.count('is not an ISO date') == 1, argv


def test_a_stale_packet_regenerates_byte_identically(in_project):
    """`--package` now appends variable-length derived prose (the reason lines)
    to a file whose byte-identity on re-run is a documented contract."""
    _four_stale_slots(in_project)
    cmd_illustrate.main(['--package'])
    first = _read_all(in_project)
    cmd_illustrate.main(['--package'])
    assert _read_all(in_project) == first


def test_the_render_order_distinguishes_current_art_from_stale(in_project,
                                                              capsys):
    """Three marks, three meanings: `*` ingested and current, `~` ingested and
    canon-stale, blank for no art. Only `~` was asserted, so collapsing the
    other two would have gone unnoticed."""
    spec = (
        ('a-establisher', 'act1-sc01', 'dorren-hayle;cartography-office', ''),
        ('b-darkest', 'act1-sc01', '', 'darkest'),
        ('c-brightest', 'act1-sc02', '', 'brightest'),
        ('d-later-state', 'act2-sc01', 'maps', ''),
    )
    _write_slot_rows(in_project, spec, ingested_at='2026-07-28')
    rows = ill.read_plan(in_project)
    rows[0]['ingested_at'] = ''      # stale
    rows[1]['status'] = 'planned'    # no art
    ill.write_plan(in_project, rows)

    cmd_illustrate.main(['--diagnose'])
    order = [l.split(']')[-1] for l in capsys.readouterr().out.splitlines()
             if '. a-establisher' in l or '. b-darkest' in l
             or '. c-brightest' in l]
    assert len(order) == 3, order
    assert any('~' in l and 'a-establisher' in l for l in order), order
    assert any('*' in l and 'c-brightest' in l for l in order), order
    assert any('b-darkest' in l and '*' not in l and '~' not in l
               for l in order), order


def test_the_stale_batch_note_agrees_with_its_own_count(in_project):
    """`4 of these already has art` — the headline sentence of the phase-1
    section, in the artifact whose only product is credibility."""
    _four_stale_slots(in_project)
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')
    assert '**4 of these already have art' in body
    assert 'They are still `ingested`, so they still ship' in body
    assert 'already has art' not in body


def test_the_anchor_batch_is_reported_once_when_package_yields_to_diagnose(
        in_project, capsys):
    """#290 item 2. `main` early-returns on `--diagnose`, so the collapse is
    exercised here rather than through the CLI — the point is that removing that
    early return cannot silently start printing the batch twice."""
    cmd_illustrate.run_package(in_project, False, report_batch=False)
    out = capsys.readouterr().out
    assert 'Anchor batch' not in out
    # Reporting it is the other half, so nothing was lost.
    cmd_illustrate.run_package(in_project, False, report_batch=True)
    assert 'Anchor batch' in capsys.readouterr().out
    # No default: a second caller must decide rather than inherit True silently.
    with pytest.raises(TypeError):
        cmd_illustrate.run_package(in_project, False)


# ============================================================================
# The renderers, driven directly
# ============================================================================

def test_a_clean_readme_claims_only_what_it_can(in_project):
    """With no gaps the README must still not promise the art will be right."""
    contents = packet.resolve(in_project)
    contents['gaps'] = []
    body = pp.render_readme(title='T', contents=contents, entry_count=2,
                            batch=packet.anchor_batch(in_project),
                            needs_render={})
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


def test_the_treatment_reaches_the_index_and_not_the_upload(in_project, staged):
    """The staging is author-facing here. `--prompts` takes it as a requirement
    when it writes the body, so the body already embodies it; repeating it in
    the uploaded file would be a second, competing staging note reaching the
    model. It is in `illustrations.md` so the author can check that the body
    honoured it."""
    staged(_sequence_response(
        ('the-finest-cartographer', 'close, low, interior, night')))
    cmd_illustrate.main(['--sequence'])
    cmd_illustrate.main(['--package'])

    assert 'close, low, interior, night' in _read(in_project,
                                                  'illustrations.md')
    assert 'close, low, interior, night' not in \
        _read_prompt(in_project, 'the-finest-cartographer')


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
    uploaded = _read_prompt(in_project, 'the-finest-cartographer')
    with open(os.path.join(in_project,
                           ill.default_prompt_rel('the-finest-cartographer')),
              encoding='utf-8') as f:
        prompt_file = f.read()
    state = {e['id']: e for e in packet.resolve(in_project)['entries']
             }['the-finest-cartographer']['state']
    assert state
    assert state in uploaded
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
    body = _read(in_project, 'README.md')
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
        _read(in_project, 'README.md')


def test_the_positive_headline_never_reaches_the_packet(in_project):
    """The `describe_style_reference` / `style_reference_warnings` split exists
    for this: a resolution line under "What is not in that list" reads as an
    exclusion."""
    from illustration_helpers import make_png
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 8)
    cmd_illustrate.main(['--package'])
    assert 'Style reference:' not in _read(in_project, 'README.md')


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


def test_a_retired_packet_file_is_removed_on_the_next_run(in_project):
    """A leftover `reference-images.md` is a second, stale answer to "what do I
    upload" sitting beside the current one — and the pre-#306 file omits every
    disclosure the aggregation added."""
    cmd_illustrate.main(['--package'])
    stale = os.path.join(in_project, packet.PACKET_DIR, 'reference-images.md')
    with open(stale, 'w', encoding='utf-8') as f:
        f.write('# Reference images\n\nupload these\n')

    cmd_illustrate.main(['--package'])

    assert not os.path.exists(stale)


def test_the_packet_directory_is_not_swept_wholesale(in_project):
    """Only the enumerated retired files go. The packet directory is the
    author's to leave a note in, and a wholesale sweep is the destructive shape
    this pipeline has been bitten by before."""
    cmd_illustrate.main(['--package'])
    note = os.path.join(in_project, packet.PACKET_DIR, 'my-notes.md')
    with open(note, 'w', encoding='utf-8') as f:
        f.write('mine')

    cmd_illustrate.main(['--package'])

    assert os.path.isfile(note)


def test_an_image_prompt_for_a_dropped_row_does_not_survive(in_project):
    """The upload directory's only job is being the thing the author uploads, so
    a file for a row that has left the plan reads exactly like a current one."""
    cmd_illustrate.main(['--package'])
    assert os.path.isfile(packet.image_prompt_file(in_project,
                                                   'the-blank-page'))
    rows = [r for r in ill.read_plan(in_project)
            if r['id'].strip() != 'the-blank-page']
    ill.write_plan(in_project, rows)

    cmd_illustrate.main(['--package'])

    assert not os.path.exists(
        packet.image_prompt_file(in_project, 'the-blank-page'))


def test_an_illegal_plan_id_cannot_name_a_path(in_project):
    """The plan is a documented hand-edit surface and `run_package` does not
    call `validate_plan`, so the check that keeps a written path inside the
    packet tree has to be at the write, not at a caller that may forget."""
    with pytest.raises(ValueError):
        packet.image_prompt_file(in_project, '../../evil')


def _seed_stale_renders(project_dir, spec):
    """Append ingested rows with the given `ingested_at` values."""
    from illustration_helpers import make_png
    make_png(os.path.join(project_dir, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 12)
    rows = ill.read_plan(project_dir)
    for index, ingested_at in enumerate(spec):
        row = ill.blank_row(f'old-{index}')
        rel = ill.default_asset_rel(row['id'])
        make_png(os.path.join(project_dir, rel), 8, 12)
        row.update({'scene_id': 'act1-sc01', 'placement': 'scene_open',
                    'status': 'ingested', 'asset_file': rel,
                    'ingested_at': ingested_at, 'beat': 'b', 'subject': 's'})
        rows.append(row)
    ill.write_plan(project_dir, rows)


def test_the_exclusion_note_aggregates_across_ingest_dates(in_project):
    """The defect the by-prose key reintroduced: `stale_render_reason`
    interpolates the row's own date, so four renders ingested on four days
    produced four near-identical notes — the seventeen-paragraph shape #306 is
    about, rebuilt by the choice of key. Keyed on the category, they are one."""
    _seed_stale_renders(in_project, ['2026-01-01', '2026-01-02',
                                     '2026-01-03', '2026-01-04'])

    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')

    assert '4 ingested illustration(s) are **not** listed' in body
    assert body.count('They were directed by canon') == 1
    assert 'All of them were ingested before the canon was last updated' in body
    assert 'and 1 more' in body          # capped, so the note stays readable


def test_two_different_stale_causes_stay_two_notes(in_project):
    """Aggregation must never cost the half of the sentence that says what to
    fix: an empty `ingested_at` and a date before the cutoff need different
    remedies, so they stay separate."""
    _seed_stale_renders(in_project, ['2026-01-01', '2026-01-02', ''])

    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')

    assert body.count('They were directed by canon') == 2
    assert 'All of them were ingested before the canon' in body
    assert 'None of them carries an `ingested_at`' in body


def test_a_stale_kind_is_non_empty_exactly_when_a_reason_is():
    """The two functions branch over the same conditions; a divergence would
    aggregate rows under a category their sentence contradicts."""
    cutoff = '2026-07-28'
    rows = [
        {'status': 'ingested', 'ingested_at': ''},
        {'status': 'ingested', 'ingested_at': 'nonsense'},
        {'status': 'ingested', 'ingested_at': '2026-01-01'},
        {'status': 'ingested', 'ingested_at': '2026-08-01'},
        {'status': 'rendered', 'ingested_at': ''},
        {'status': 'planned', 'ingested_at': '2026-01-01'},
    ]
    for row in rows:
        assert bool(ill.stale_render_kind(row, cutoff)) == \
            bool(ill.stale_render_reason(row, cutoff)), row
        # And nothing is stale when there is no cutoff to judge against.
        assert ill.stale_render_kind(row, '') == ''


def test_every_stale_kind_has_a_plural_clause():
    """A missing key is a `KeyError` while writing README — total by test, since
    a dict literal is not checked against its Literal key type."""
    from typing import get_args
    assert set(cmd_illustrate._STALE_KIND_CLAUSES) == \
        set(get_args(ill.StaleKind))


# ============================================================================
# Review fixes: the destructive paths and the silences (#306 review)
# ============================================================================

def test_the_cover_only_gap_does_not_name_a_deleted_file(in_project):
    """The packet's most consequential gap — twenty renders on disk and none of
    them reachable — pointed the author at `reference-images.md`, which the same
    run deletes. A dangling pointer in the section whose only product is
    credibility is how that section gets skipped."""
    from illustration_helpers import make_png
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 12)
    _ingest(in_project, 0, ingested_at='2026-01-01')   # pre-canon: excluded

    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'README.md')

    assert 'the reference-image list is cover-only or empty' in body
    assert 'Read this before you upload' in body
    for name in packet.RETIRED_PACKET_FILES:
        assert name not in body


def test_no_packet_file_names_a_retired_packet_file(in_project):
    """The general form, so a future retirement cannot leave a live pointer."""
    cmd_illustrate.main(['--package'])
    for rendered in packet.PACKET_FILES:
        body = _read(in_project, rendered)
        for retired in packet.RETIRED_PACKET_FILES:
            assert retired not in body, f'{rendered} names {retired}'


def test_written_and_retired_packet_files_are_disjoint():
    """A name in both would have one --package run delete a file it just wrote,
    or write one it just deleted, depending on call order."""
    assert not set(packet.PACKET_FILES) & set(packet.RETIRED_PACKET_FILES)


def test_an_illegal_id_is_refused_before_anything_is_written(in_project):
    """`run_export` refused up front and that check was lost when it retired.
    Left to `image_prompt_file`'s raise, a bad id cleared the previous run's
    uploads and then put a traceback on the terminal."""
    cmd_illustrate.main(['--package'])
    survivor = packet.image_prompt_file(in_project, 'the-finest-cartographer')
    assert os.path.isfile(survivor)
    rows = ill.read_plan(in_project)
    rows[1]['id'] = '../../evil'
    ill.write_plan(in_project, rows)

    assert cmd_illustrate.main(['--package']) == 1
    # Nothing was deleted on the way to refusing.
    assert os.path.isfile(survivor)


def test_an_over_long_id_is_refused_too(in_project):
    """`_ID_RE` has no length bound — it is shared with the marker regex — so a
    300-character id is legal and dies at `open()`, inside the same window."""
    rows = ill.read_plan(in_project)
    rows[1]['id'] = 'x' * 300
    ill.write_plan(in_project, rows)

    assert cmd_illustrate.main(['--package']) == 1


def test_a_missing_image_prompt_is_reported_not_read_as_current(in_project):
    """On a rebuild the root files already exist, so `is_built` is True before
    the delete pass — the write-order argument only covers a first build. A
    hollowed `image-prompts/` must not read as "built and current"."""
    cmd_illustrate.main(['--package'])
    os.remove(packet.image_prompt_file(in_project, 'the-blank-page'))

    assert packet.is_built(in_project)          # the window this closes
    findings = packet.packet_stale(in_project)
    assert [f['kind'] for f in findings] == ['packet_stale']
    assert 'the-blank-page' in findings[0]['detail']
    assert 'half-written' in findings[0]['detail']


def test_an_edited_body_at_a_declared_prompt_file_makes_the_packet_stale(
        in_project):
    """`_body_for` resolves through `prompt_file`, so listing the canonical
    directory missed both supported shapes: an unmigrated project and a declared
    path elsewhere. Editing the body left the packet reporting itself current
    while it inlined the old prose."""
    declared = os.path.join('reference', 'hand-written', 'LF.md')
    os.makedirs(os.path.join(in_project, 'reference', 'hand-written'))
    with open(os.path.join(in_project, declared), 'w', encoding='utf-8') as f:
        f.write('## Prompt\n\nPaste everything below into the image model.\n\n'
                '---\n\n## Scene\n\nfirst\n')
    rows = ill.read_plan(in_project)
    rows[0]['prompt_file'] = declared
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--package'])
    assert packet.packet_stale(in_project) == []

    os.utime(os.path.join(in_project, declared), (2 ** 31, 2 ** 31))
    with open(os.path.join(in_project, declared), 'a', encoding='utf-8') as f:
        f.write('\nsecond\n')

    findings = packet.packet_stale(in_project)
    assert [f['kind'] for f in findings] == ['packet_stale']
    assert declared in findings[0]['detail']


def test_an_unreadable_prompt_directory_is_unknown_not_current(in_project,
                                                               capsys):
    """Two unguarded `os.listdir` calls raised out of `validate_plan`, which is
    the single finding collector — one unreadable directory took the whole
    illustration health report down, blocking findings included. That is the
    #298 regression, and the fix must report *unknown* rather than swallow."""
    cmd_illustrate.main(['--package'])
    directory = packet.image_prompts_dir(in_project)
    os.chmod(directory, 0o000)
    try:
        findings = packet.packet_stale(in_project)
        # validate_plan must survive it too — that is the point.
        assert isinstance(ill.validate_plan(in_project), list)
    finally:
        os.chmod(directory, 0o755)

    assert [f['kind'] for f in findings] == ['packet_stale']
    assert 'could not be checked' in findings[0]['detail']
    assert 'unknown rather than' in findings[0]['detail']


def test_an_unremovable_retired_file_does_not_abort_the_build(in_project,
                                                              monkeypatch,
                                                              capsys):
    """Hygiene must not gate the build: raising left both the stale upload list
    and a packet that was never regenerated."""
    cmd_illustrate.main(['--package'])
    stale = os.path.join(in_project, packet.PACKET_DIR, 'reference-images.md')
    with open(stale, 'w', encoding='utf-8') as f:
        f.write('old')

    def _boom(path):
        raise PermissionError(13, 'Permission denied')
    monkeypatch.setattr(os, 'remove', _boom)

    assert cmd_illustrate.main(['--package']) == 0
    out = capsys.readouterr().out
    assert 'could not remove' in out
    assert 'delete it by hand' in out


# ============================================================================
# The prompt-file parser and the body fallbacks (#306 review, T-1/T-2)
#
# These moved from `export.py` into `packet.py` verbatim and their tests went
# with the deleted `test_illustrate_export.py`. Two mutations proved the gap:
# blanking `body_warning`/`body_cause` passed the whole suite, and so did making
# `parse_prompt_file` never cut at the trailer — which uploads the file's own
# stale Constraints block and its do-NOT-paste section straight to the model.
# ============================================================================

_MODEL_BODY = ('## Scene\n\nA long hall of slanted oak tables.\n\n'
               '## Subject\n\nDorren bent over the master survey.\n\n'
               '## Important details\n\n- Brass calipers.\n\n'
               '## Use case\n\nInterior illustration for a novel.')


def test_parse_prompt_file_round_trips_render_prompt_file():
    """The reader lives beside the writer so the two cannot drift over the
    strings that bound the body."""
    text = pi.render_prompt_file(
        row={'id': 'x', 'scene_id': 's1', 'beat': 'a beat'},
        body=_MODEL_BODY, references=[], state='a state', absent='a thing',
        contrast='different')
    parsed = pi.parse_prompt_file(text)
    assert parsed['status'] == 'ok'
    assert parsed['body'] == _MODEL_BODY


def test_parse_prompt_file_stops_before_the_constraints():
    """The constraints are regenerated from the plan, never inherited: a file
    written before a matrix edit still carries the old state, and an upload
    holding both would contradict itself."""
    text = pi.render_prompt_file(row={'id': 'x', 'scene_id': 's1'},
                                 body='## Scene\n\nA room.', references=[],
                                 state='a state')
    body = pi.parse_prompt_file(text)['body']
    assert 'a state' not in body
    assert 'PORTRAIT' not in body


def test_parse_prompt_file_reports_a_missing_prompt_section():
    assert pi.parse_prompt_file('# notes\n\nnothing')['status'] == \
        'no_prompt_section'


def test_parse_prompt_file_reports_an_empty_body():
    text = (f'# x\n\n{pi.PROMPT_HEADING}\n\n{pi.PASTE_SENTINEL}\n\n---\n\n'
            f'{pi.CONSTRAINTS_HEADING}\n\n- a rule\n')
    assert pi.parse_prompt_file(text) == {'body': '', 'status': 'empty_body'}


def test_parse_prompt_file_recovers_a_file_missing_the_sentinel():
    """The prompt file is documented as hand-editable, so refusing here would
    send an author to re-run a paid `--prompts`."""
    text = (f'# x\n\n{pi.PROMPT_HEADING}\n\n## Scene\n\nA room.\n\n'
            f'{pi.CONSTRAINTS_HEADING}\n\n- a rule\n')
    parsed = pi.parse_prompt_file(text)
    assert parsed['status'] == 'ok'
    assert parsed['body'] == '## Scene\n\nA room.'


def test_parse_prompt_file_handles_crlf():
    text = pi.render_prompt_file(row={'id': 'x', 'scene_id': 's1'},
                                 body='## Scene\n\nA room.', references=[])
    assert pi.parse_prompt_file(text.replace('\n', '\r\n'))['body'] == \
        '## Scene\n\nA room.'


def test_a_promoted_constraints_heading_does_not_leak_into_the_upload():
    """The likeliest hand edit — every heading around it is `##`. Cutting at the
    first match is the only reading that cannot self-contradict."""
    text = pi.render_prompt_file(row={'id': 'x', 'scene_id': 's1'},
                                 body='## Scene\n\nA room.', references=[],
                                 state='navy pajamas')
    parsed = pi.parse_prompt_file(
        text.replace(pi.CONSTRAINTS_HEADING, '## Constraints'))
    assert parsed['status'] == 'ok'
    assert 'navy pajamas' not in parsed['body']


def test_a_model_authored_constraints_heading_is_reported_as_truncated():
    """#293: a truncation every consumer accepts is worse than an absence."""
    body = ('## Scene\n\nA hall.\n\n## Constraints\n\nNo lettering.\n\n'
            '## Use case\n\nFull-page.')
    parsed = pi.parse_prompt_file(pi.render_prompt_file(
        row={'id': 'x', 'scene_id': 's1'}, body=body, references=[]))
    assert parsed['status'] == 'body_truncated'
    assert parsed['body'] == '## Scene\n\nA hall.'


def _body_note(project_dir, illus_id):
    """The `**Art direction.**` note for one row of illustrations.md."""
    body = _read(project_dir, 'illustrations.md')
    section = body.split(f'### `{illus_id}`')
    assert len(section) == 2, f'{illus_id} has no note in illustrations.md'
    return section[1].split('###')[0]


def test_a_truncated_body_is_used_and_reported(in_project):
    """The prose is still better than three plan cells, so it is kept — and the
    author is told a section is missing, in the file they read to choose."""
    from illustration_helpers import write_prompt_file
    write_prompt_file(in_project, 'the-finest-cartographer', body=(
        '## Scene\n\nA hall.\n\n## Constraints\n\nNo lettering.\n\n'
        '## Use case\n\nFull-page.'))
    assert cmd_illustrate.main(['--package']) == 0

    note = _body_note(in_project, 'the-finest-cartographer')
    assert 'carries its own `Constraints` heading' in note
    assert 'A hall.' in _read_prompt(in_project, 'the-finest-cartographer')
    assert 'Constraints` heading inside their prompt body' in \
        _read(in_project, 'README.md')


def test_a_declared_prompt_file_that_is_missing_gets_its_own_sentence(
        in_project):
    """An author who typed a path meant that path, so the prose usually exists
    somewhere — a different action from "generate it again"."""
    rows = ill.read_plan(in_project)
    rows[0]['prompt_file'] = 'reference/illustration-prompts/gone.md'
    ill.write_plan(in_project, rows)

    assert cmd_illustrate.main(['--package']) == 0
    assert 'the plan declares art direction at' in \
        _body_note(in_project, 'the-finest-cartographer')


def test_an_unreadable_prompt_file_falls_back_and_says_so(in_project):
    from illustration_helpers import write_prompt_file
    path = write_prompt_file(in_project, 'the-finest-cartographer')
    os.chmod(path, 0o000)
    try:
        assert cmd_illustrate.main(['--package']) == 0
        assert 'could not be read' in \
            _body_note(in_project, 'the-finest-cartographer')
    finally:
        os.chmod(path, 0o644)


def test_an_empty_prompt_body_falls_back_and_says_so(in_project):
    from illustration_helpers import write_prompt_file
    path = write_prompt_file(in_project, 'the-finest-cartographer')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'# x\n\n{pi.PROMPT_HEADING}\n\n{pi.PASTE_SENTINEL}\n\n---\n\n'
                f'{pi.CONSTRAINTS_HEADING}\n\n- a rule\n')

    assert cmd_illustrate.main(['--package']) == 0
    assert 'has an empty prompt body' in \
        _body_note(in_project, 'the-finest-cartographer')


def test_a_thin_body_is_never_silent_in_either_channel(in_project):
    """`body_warning` and `body_cause` are a strict biconditional, and blanking
    either passed the whole suite: a plan-row stand-in reads exactly like a
    complete prompt, so an author who cannot tell generates from it."""
    cmd_illustrate.main(['--package'])
    assert 'no written art direction' in \
        _body_note(in_project, 'the-finest-cartographer')
    assert 'have no written art direction' in _read(in_project, 'README.md')


def test_a_non_markdown_file_in_the_upload_directory_survives(in_project):
    """The clear pass removes `.md` files only. Widened to everything, an
    author's own note in there is deleted on every run — the destructive shape
    `_write_image_prompts`' docstring says is not its call to make. A mutation
    dropping the extension guard passed the whole suite (#306 review, T-7)."""
    cmd_illustrate.main(['--package'])
    note = os.path.join(packet.image_prompts_dir(in_project), 'notes.txt')
    with open(note, 'w', encoding='utf-8') as f:
        f.write('mine')

    cmd_illustrate.main(['--package'])

    assert os.path.isfile(note)


def test_export_exits_two_with_a_pointer(in_project, capsys):
    """Two, not one and not zero: a retired flag is neither a failed run nor a
    successful one, and the skill commits on the exit code."""
    assert cmd_illustrate.main(['--export']) == 2
    out = capsys.readouterr().out
    assert '--export was removed' in out
    assert '--package' in out
    assert packet.IMAGE_PROMPTS_SUBDIR in out
    # Refusing writes nothing.
    assert not os.path.isdir(packet.packet_dir(in_project))


def test_illegal_plan_ids_finds_what_it_claims_to():
    """The gate is only as good as the predicate; a version matching nothing
    would be a dead check that still reads as protection."""
    assert ill.illegal_plan_ids([{'id': 'LF-01'}, {'id': 'a_b-1'}]) == []
    assert ill.illegal_plan_ids([{'id': '../../evil'}]) == ['../../evil']
    assert ill.illegal_plan_ids([{'id': ''}]) == ['']
    assert ill.illegal_plan_ids([{'id': '-leading'}]) == ['-leading']
    assert ill.illegal_plan_ids([{'id': 'x' * 300}]) == ['x' * 300]


def test_a_superseded_export_directory_is_reported_never_deleted(in_project,
                                                                 capsys):
    """167 MB on the book this was filed about, so the author wants it gone —
    but a command that removes a directory it did not write is the destructive
    shape this pipeline has been bitten by before."""
    legacy = os.path.join(in_project, 'manuscript', 'illustration-export')
    os.makedirs(legacy)
    with open(os.path.join(legacy, 'README.md'), 'w', encoding='utf-8') as f:
        f.write('old')

    assert cmd_illustrate.main(['--package']) == 0

    assert 'superseded' in capsys.readouterr().out
    assert os.path.isfile(os.path.join(legacy, 'README.md'))


def test_cell_cannot_split_a_markdown_row():
    """A pipe closes a markdown cell, so an unescaped one shifts every later
    column along and drops the last.

    Tested at the renderer rather than through a plan cell, because the plan is
    itself pipe-delimited: `write_plan` sanitizes a pipe on the way out and an
    extra one shatters the row on the way in, so no cell can carry one. This is
    defence-in-depth for a renderer whose output nobody re-reads, and the test
    says which it is rather than implying a live path.
    """
    assert pp._cell('she looks up | he does not') == \
        r'she looks up \| he does not'
    assert pp._cell('two\nlines') == 'two lines'
    assert pp._cell('   ') == '—'
    assert pp._cell('') == '—'


def test_the_index_row_has_one_cell_per_column(in_project):
    """The shape the escaping protects: seven columns, so eight separators."""
    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'illustrations.md')
    header = next(l for l in body.split('\n') if l.startswith('| # |'))
    row = next(l for l in body.split('\n')
               if l.startswith('|') and '`the-finest-cartographer`' in l)
    assert len(row.split('|')) == len(header.split('|'))


def test_the_re_render_note_is_two_sentences_not_one_run_on(in_project):
    """`stale_render_reason` is a clause and ends without punctuation, so
    concatenating it raw produced '...last updated 2026-07-28 Generate it
    again', which reads as a defect in the packet."""
    _ingest(in_project, 0, ingested_at='')
    cmd_illustrate.main(['--package'])

    note = _body_note(in_project, 'the-finest-cartographer')
    assert '. Generate it again' in note


def test_a_declared_prompt_path_is_named_in_the_notes(in_project):
    """`prompt_source` and `body_source` had no reader, which is the write-only
    shape this PR removed `Entry.in_frame` for. The case worth a line is a path
    that is *not* the convention: README states the convention once, so noting
    it per row would put every illustration in the section whose value is that
    it holds only the ones worth reading."""
    from illustration_helpers import write_prompt_file
    default = write_prompt_file(in_project, 'the-finest-cartographer')
    declared = os.path.join(in_project, 'reference', 'elsewhere.md')
    os.rename(default, declared)
    rows = ill.read_plan(in_project)
    rows[0]['prompt_file'] = 'reference/elsewhere.md'
    ill.write_plan(in_project, rows)

    cmd_illustrate.main(['--package'])

    note = _body_note(in_project, 'the-finest-cartographer')
    assert 'reference/elsewhere.md' in note
    assert 'not the default path' in note


def test_a_conventional_prompt_path_is_not_noted_per_row(in_project):
    """The other half: a row whose art direction is fine and at the expected
    path has nothing to say, and must not appear."""
    from illustration_helpers import write_prompt_file
    write_prompt_file(in_project, 'the-finest-cartographer')
    write_prompt_file(in_project, 'the-blank-page')

    cmd_illustrate.main(['--package'])
    body = _read(in_project, 'illustrations.md')

    assert 'Nothing on any row needs reading first' in body


def test_the_model_reaches_the_upload(in_project):
    """`model` was written and rendered nowhere. It belongs in the file the
    author hands over, for the reason `size` and `quality` are there: it makes
    the render reproducible two weeks later."""
    cmd_illustrate.main(['--package'])
    assert pi.DEFAULT_IMAGE_MODEL in \
        _read_prompt(in_project, 'the-finest-cartographer')

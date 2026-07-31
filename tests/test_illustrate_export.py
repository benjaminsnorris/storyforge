"""Tests for `storyforge illustrate --export` — the self-contained bundle (#298).

The export's contract is narrower and stricter than the packet's: every unit
directory must be usable *on its own*. So the assertions here are about
completeness — one contiguous paste region carrying the model's prose plus the
resolved state, absent, and contrast; the reference images present as real files
with symlinks resolved; a manifest recording enough to reproduce the render — and
about the export never claiming coverage it does not have.

`in_project` seeds canon files, a plan, state transitions, and cover artwork into
a copy of the fixture; the shared fixture has none of those.
"""

import json
import os

import pytest

from storyforge import canon, cmd_illustrate, export as ex
from storyforge import illustrations as ill
from storyforge import prompts_export as pe
from storyforge import prompts_illustrate as pi
from illustration_helpers import make_png, seed_packet_project

FIRST = 'the-finest-cartographer'
SECOND = 'the-blank-page'

#: A body in the shape `--prompts` writes, long enough that a truncating parse
#: would be visible. The last line is what a body-boundary bug drops first.
MODEL_BODY = """### Scene

A long hall of slanted oak drafting tables under high north windows.

### Subject

Dorren Hayle bent over the master survey with brass calipers.

### Important details

- Umber and iron gall ink on four-foot vellum.
- A single hairline border rule.

### Use case

Full-page interior illustration for an adult literary fantasy."""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)


@pytest.fixture
def in_project(project_dir, monkeypatch):
    seed_packet_project(project_dir)
    make_png(os.path.join(project_dir, 'manuscript', 'assets',
                          'cover-illustration.png'), 800, 1200)
    monkeypatch.chdir(project_dir)
    return project_dir


def _write_prompt_file(project_dir, illus_id, *, body=MODEL_BODY,
                       state='', absent='', contrast=''):
    """Write a prompt file the way `--prompts` would, and point the row at it."""
    rows = ill.read_plan(project_dir)
    row = next(r for r in rows if r['id'].strip() == illus_id)
    rel = ill.default_prompt_rel(illus_id)
    os.makedirs(ill.prompts_dir(project_dir), exist_ok=True)
    with open(os.path.join(project_dir, rel), 'w', encoding='utf-8') as f:
        f.write(pi.render_prompt_file(
            row=row, body=body,
            references=[('manuscript/assets/cover-illustration.png', 'cover')],
            aspect=pi.aspect_for_row(row), state=state, absent=absent,
            contrast=contrast))
    row['prompt_file'] = rel
    row['status'] = 'prompted'
    ill.write_plan(project_dir, rows)
    return rel


def _read_unit(project_dir, illus_id, name=ex.PROMPT_FILENAME):
    with open(os.path.join(ex.unit_dir(project_dir, illus_id), name),
              encoding='utf-8') as f:
        return f.read()


def _manifest(project_dir, illus_id):
    return json.loads(_read_unit(project_dir, illus_id, ex.MANIFEST_FILENAME))


def _paste_block(text):
    """The contiguous region a reader is told to paste, and nothing else.

    `.index` raises on a missing marker, which is what keeps a negative assertion
    over this slice from passing vacuously. The ordering assert covers the other
    way it could return '': markers present but swapped.
    """
    start = text.index(pe._PASTE_OPEN) + len(pe._PASTE_OPEN)
    end = text.index(pe._PASTE_CLOSE)
    assert start < end, 'paste markers are out of order'
    return text[start:end]


def _tree(project_dir):
    root = ex.export_dir(project_dir)
    return sorted(os.path.relpath(os.path.join(base, name), root)
                  for base, _dirs, files in os.walk(root) for name in files)


# ============================================================================
# Structure
# ============================================================================

def test_export_writes_shared_files_and_one_directory_per_illustration(in_project):
    assert cmd_illustrate.main(['--export']) == 0
    assert _tree(in_project) == sorted([
        'README.md', 'acceptance.md', 'canon.md',
        f'{FIRST}/{ex.MANIFEST_FILENAME}', f'{FIRST}/{ex.PROMPT_FILENAME}',
        f'{FIRST}/references/1-cover-illustration.png',
        f'{SECOND}/{ex.MANIFEST_FILENAME}', f'{SECOND}/{ex.PROMPT_FILENAME}',
        f'{SECOND}/references/1-cover-illustration.png',
    ])


def test_export_makes_no_api_call(in_project, monkeypatch):
    """Set the key so the missing-key guard cannot make this pass vacuously."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('--export is assembly, not generation')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    assert cmd_illustrate.main(['--export']) == 0


def test_dry_run_writes_nothing(in_project, capsys):
    assert cmd_illustrate.main(['--export', '--dry-run']) == 0
    assert not os.path.isdir(ex.export_dir(in_project))
    out = capsys.readouterr().out
    assert ex.PROMPT_FILENAME in out and FIRST in out


def test_regeneration_is_byte_identical(in_project):
    """The export is a render: an edit is lost on the next run, so two runs over
    unchanged sources must not churn the tree either. No timestamps anywhere."""
    _write_prompt_file(in_project, FIRST)
    cmd_illustrate.main(['--export'])
    first = {name: _read(in_project, name) for name in _tree(in_project)
             if name.endswith(('.md', '.json'))}
    cmd_illustrate.main(['--export'])
    assert {name: _read(in_project, name) for name in _tree(in_project)
            if name.endswith(('.md', '.json'))} == first


def _read(project_dir, relative):
    with open(os.path.join(ex.export_dir(project_dir), relative),
              encoding='utf-8') as f:
        return f.read()


def test_a_freshly_written_export_is_not_stale(in_project):
    _write_prompt_file(in_project, FIRST)
    cmd_illustrate.main(['--export'])
    assert ex.export_stale(in_project) == []


def test_an_unbuilt_export_is_not_a_finding(in_project):
    """In-flight state, the same posture as an unbuilt packet."""
    assert ex.export_stale(in_project) == []
    assert not ex.is_built(in_project)


# ============================================================================
# The paste-ready block — the issue's central complaint
# ============================================================================

def test_the_paste_block_carries_the_model_authored_body(in_project):
    """`--package` renders the plan row; the export aggregates the prose that
    only exists in `prompts/{id}.md`. Every line of it, including the last —
    a body-boundary bug drops the tail, not the head."""
    _write_prompt_file(in_project, FIRST)
    cmd_illustrate.main(['--export'])
    block = _paste_block(_read_unit(in_project, FIRST))
    for line in MODEL_BODY.split('\n'):
        assert line in block, line


def test_the_paste_block_carries_state_absent_and_contrast(in_project):
    """The three fields the prompt file could not show and the packet showed in
    a different file. One contiguous block, per the issue's success criteria."""
    rows = ill.read_plan(in_project)
    rows[1]['absent'] = 'Ember. A second Great Lamp.'
    rows[1]['contrast'] = 'Much wider than the one before it.'
    ill.write_plan(in_project, rows)
    _write_prompt_file(in_project, SECOND)
    cmd_illustrate.main(['--export'])

    block = _paste_block(_read_unit(in_project, SECOND))
    assert 'one corner curled back under a paperweight' in block  # state
    assert 'Ember. A second Great Lamp.' in block                 # absent
    assert 'Much wider than the one before it.' in block          # contrast


def test_the_paste_block_is_one_contiguous_region(in_project):
    """A reader must not have to assemble anything. The open marker appears once,
    the close marker appears once, and the close is after the open."""
    _write_prompt_file(in_project, FIRST)
    cmd_illustrate.main(['--export'])
    text = _read_unit(in_project, FIRST)
    assert text.count(pe._PASTE_OPEN) == 1
    assert text.count(pe._PASTE_CLOSE) == 1
    assert text.index(pe._PASTE_OPEN) < text.index(pe._PASTE_CLOSE)


def test_the_export_reresolves_state_rather_than_inheriting_it(in_project):
    """The prompt file's own state line can be older than the matrix — there is
    no `prompt_stale`. The export takes the *body* from the file and the state
    from the plan, so the block cannot contradict itself the way #297's two
    artifacts contradicted each other."""
    _write_prompt_file(in_project, SECOND, state='a state nobody records now')
    cmd_illustrate.main(['--export'])
    block = _paste_block(_read_unit(in_project, SECOND))
    assert 'a state nobody records now' not in block
    assert 'one corner curled back under a paperweight' in block


def test_the_constraints_come_from_the_shared_builder(in_project):
    """One function renders the constraints for both artifacts, so neither can
    drift into stating a different orientation or no-text rule for one row."""
    _write_prompt_file(in_project, SECOND)
    cmd_illustrate.main(['--export'])
    block = _paste_block(_read_unit(in_project, SECOND))
    rows = ill.read_plan(in_project)
    row = next(r for r in rows if r['id'].strip() == SECOND)
    for bullet in pi.prompt_constraints(aspect=pi.aspect_for_row(row)):
        assert bullet in block, bullet


def test_the_acceptance_checks_are_outside_the_paste_block(in_project):
    """They read like prompt text and can name another illustration by id, which
    is why the prompt file marks them do-NOT-paste. Same discipline here."""
    _write_prompt_file(in_project, FIRST)
    cmd_illustrate.main(['--export'])
    text = _read_unit(in_project, FIRST)
    assert 'Accept only if' not in _paste_block(text)
    assert text.index(pe._PASTE_CLOSE) < text.index('### Accept only if')


def test_no_written_art_direction_is_stated_not_silent(in_project, capsys):
    """A block assembled from three plan cells reads exactly like a complete
    prompt. So it is named in the unit's own file, in README, and in the log —
    an author who cannot tell the difference generates from it."""
    assert cmd_illustrate.main(['--export']) == 0
    unit = _read_unit(in_project, FIRST)
    assert 'assembled from the plan row' in unit
    assert 'Read this first' in unit
    assert 'plan row only' in _read(in_project, 'README.md')
    assert 'no written art direction' in capsys.readouterr().out


def test_a_derived_body_still_carries_the_plan_row_content(in_project):
    """The stand-in is shaped like the real thing so a reader sees at a glance
    which parts are thin, rather than finding an empty template."""
    assert cmd_illustrate.main(['--export']) == 0
    block = _paste_block(_read_unit(in_project, SECOND))
    assert 'The village is gone from the new survey' in block
    assert 'Overhead, square, the sheet filling the frame' in block
    assert '_(not recorded in the plan)_' in block  # palette is empty


def test_an_unparseable_prompt_file_falls_back_and_says_so(in_project):
    """A hand-edited file that lost its `## Prompt` section must not export as
    an empty paste block, which would look like a complete artifact."""
    rel = _write_prompt_file(in_project, FIRST)
    with open(os.path.join(in_project, rel), 'w', encoding='utf-8') as f:
        f.write('# Illustration prompt\n\nnothing structured here\n')
    assert cmd_illustrate.main(['--export']) == 0
    unit = _read_unit(in_project, FIRST)
    assert 'no `## Prompt` section' in unit
    assert _manifest(in_project, FIRST)['body_source'] == 'plan_row'


# ============================================================================
# Reference images are files, not paths
# ============================================================================

def test_reference_images_are_copied_in_upload_order(in_project):
    assert cmd_illustrate.main(['--export']) == 0
    copy = os.path.join(ex.unit_dir(in_project, FIRST), 'references',
                        '1-cover-illustration.png')
    assert os.path.isfile(copy)
    source = os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png')
    with open(copy, 'rb') as a, open(source, 'rb') as b:
        assert a.read() == b.read()


def test_a_symlinked_reference_is_copied_not_linked(in_project):
    """A zip preserving a dangling link is worse than a copy, and symlinking the
    convention filename at the selected artwork is the documented workaround for
    a book with several cover variations."""
    assets = os.path.join(in_project, 'manuscript', 'assets')
    real = os.path.join(in_project, 'production', 'cover-v3.png')
    os.makedirs(os.path.dirname(real), exist_ok=True)
    os.replace(os.path.join(assets, 'cover-illustration.png'), real)
    os.symlink(os.path.join('..', '..', 'production', 'cover-v3.png'),
               os.path.join(assets, 'cover-illustration.png'))

    assert cmd_illustrate.main(['--export']) == 0
    copy = os.path.join(ex.unit_dir(in_project, FIRST), 'references',
                        '1-cover-illustration.png')
    assert os.path.isfile(copy) and not os.path.islink(copy)
    reference = _manifest(in_project, FIRST)['references'][0]
    assert reference['resolved_from'] == os.path.join('production',
                                                      'cover-v3.png')


def test_a_dangling_style_reference_symlink_is_a_gap(in_project):
    """`resolve_style_reference` never resolves a dangling link, so the export's
    honesty here comes from `style_reference_warnings` reaching its gaps — not
    from a copy-time check. The link is visible in `ls`, so "no cover artwork"
    would be the least useful thing to say."""
    assets = os.path.join(in_project, 'manuscript', 'assets')
    os.remove(os.path.join(assets, 'cover-illustration.png'))
    os.symlink('nowhere.png', os.path.join(assets, 'cover-illustration.png'))
    assert cmd_illustrate.main(['--export']) == 0
    readme = _read(in_project, 'README.md')
    assert 'symlink whose target does not exist' in readme
    assert _manifest(in_project, FIRST)['references'] == []


def test_an_unreadable_reference_is_skipped_with_a_note_not_a_traceback(
        in_project):
    """`_references_for` resolves with `isfile`, which follows symlinks — so a
    dangling link and an absent file never reach the copy. A file that exists and
    cannot be read does, and a traceback partway through writing the bundle is
    the wrong answer; so is a manifest promising an upload that is not there."""
    cover = os.path.join(in_project, 'manuscript', 'assets',
                         'cover-illustration.png')
    os.chmod(cover, 0o000)
    try:
        assert cmd_illustrate.main(['--export']) == 0
        assert 'could not be read' in _read_unit(in_project, FIRST)
        assert _manifest(in_project, FIRST)['references'] == []
    finally:
        os.chmod(cover, 0o644)


def test_reference_numbering_does_not_leave_a_previous_run_behind(in_project):
    """Numbering is positional, so a dropped reference would otherwise leave two
    files that both look current and a manifest naming one of them."""
    cmd_illustrate.main(['--export'])
    stray = os.path.join(ex.unit_dir(in_project, FIRST), 'references',
                         '2-stale-render.png')
    make_png(stray, 10, 10)
    cmd_illustrate.main(['--export'])
    assert not os.path.exists(stray)


def test_no_reference_images_at_all_is_a_gap(in_project):
    os.remove(os.path.join(in_project, 'manuscript', 'assets',
                           'cover-illustration.png'))
    assert cmd_illustrate.main(['--export']) == 0
    assert 'no reference images at all' in _read(in_project, 'README.md')


# ============================================================================
# manifest.json
# ============================================================================

def test_the_manifest_records_the_render_settings_and_every_digest(in_project):
    assert cmd_illustrate.main(['--export']) == 0
    manifest = _manifest(in_project, FIRST)
    assert manifest['id'] == FIRST
    assert manifest['model'] == pi.DEFAULT_IMAGE_MODEL
    assert manifest['aspect'] == 'portrait'
    assert manifest['size'] == ex.SIZES['portrait']
    assert manifest['quality'] == ex.QUALITY
    reference = manifest['references'][0]
    assert reference['sha256'] == ill.sha256_of(os.path.join(
        in_project, 'manuscript', 'assets', 'cover-illustration.png'))
    assert reference['file'] == os.path.join('references',
                                             '1-cover-illustration.png')


def test_the_manifest_records_where_the_body_came_from(in_project):
    rel = _write_prompt_file(in_project, FIRST)
    assert cmd_illustrate.main(['--export']) == 0
    manifest = _manifest(in_project, FIRST)
    assert manifest['body_source'] == 'prompt_file'
    assert manifest['prompt_source'] == rel


def test_the_size_follows_the_aspect(in_project):
    """A double-page spread is landscape whatever the composition says, and the
    recorded size has to follow or the manifest is not reproducible."""
    rows = ill.read_plan(in_project)
    rows[1]['layout'] = 'double_page'
    ill.write_plan(in_project, rows)
    assert cmd_illustrate.main(['--export']) == 0
    manifest = _manifest(in_project, SECOND)
    assert manifest['aspect'] == 'landscape'
    assert manifest['size'] == ex.SIZES['landscape']


# ============================================================================
# --ids and --anchor-batch
# ============================================================================

def test_ids_exports_only_the_named_illustrations(in_project):
    assert cmd_illustrate.main(['--export', '--ids', SECOND]) == 0
    assert os.path.isdir(ex.unit_dir(in_project, SECOND))
    assert not os.path.isdir(ex.unit_dir(in_project, FIRST))


def test_a_partial_export_says_so_and_names_what_it_did_not_touch(in_project):
    """Saying "1 illustration" over a directory holding two is the coverage
    overclaim the gap section exists to prevent."""
    cmd_illustrate.main(['--export'])
    cmd_illustrate.main(['--export', '--ids', SECOND])
    readme = _read(in_project, 'README.md')
    assert 'partial export' in readme
    assert FIRST in readme
    # Not pruned: a subset run has no business deleting units it was not asked
    # about, and README names them instead.
    assert os.path.isdir(ex.unit_dir(in_project, FIRST))


def test_a_whole_plan_export_is_not_called_partial(in_project):
    cmd_illustrate.main(['--export'])
    assert 'partial export' not in _read(in_project, 'README.md')


def test_ids_matching_nothing_is_a_failed_request(in_project, capsys):
    """The author named ids and got no directories. `run_prompts` returns 1 for
    the same flag with the same meaning, and two commands disagreeing about that
    is worse than either answer."""
    assert cmd_illustrate.main(['--export', '--ids', 'not-a-row']) == 1
    assert '--ids named 1 illustration(s)' in capsys.readouterr().out


def test_ids_matching_nothing_also_says_so_in_the_readme(in_project):
    """The stdout warning and the README gap are two different channels with two
    different sentences; asserting a substring both share pins neither."""
    cmd_illustrate.main(['--export', '--ids', 'not-a-row'])
    assert 'none of the requested ids match' in _read(in_project, 'README.md')


def test_some_valid_and_some_unknown_ids_still_exports_the_valid_ones(
        in_project, capsys):
    """A partial match is a partial success, not a failed request — only an
    empty result is the latter."""
    assert cmd_illustrate.main(
        ['--export', '--ids', f'{SECOND},not-a-row']) == 0
    assert os.path.isdir(ex.unit_dir(in_project, SECOND))
    assert 'not-a-row' in capsys.readouterr().out


def test_anchor_batch_exports_the_batch_in_one_command(in_project, capsys):
    assert cmd_illustrate.main(['--export', '--anchor-batch']) == 0
    out = capsys.readouterr().out
    assert 'Anchor batch' in out
    # Both fixture rows carry a register, so both slots resolve to real rows.
    assert os.path.isdir(ex.unit_dir(in_project, FIRST))
    assert os.path.isdir(ex.unit_dir(in_project, SECOND))


def test_anchor_batch_reports_how_the_slots_were_chosen(in_project, capsys):
    """The author who typed `--anchor-batch` never named the four ids, so a
    guessed `darkest` slot is a decision they are unaware of accepting."""
    rows = ill.read_plan(in_project)
    for row in rows:
        row['register'] = ''
    ill.write_plan(in_project, rows)
    assert cmd_illustrate.main(['--export', '--anchor-batch']) == 0
    out = capsys.readouterr().out
    assert 'register=darkest' in out and 'is a guess' in out


def test_anchor_batch_without_export_is_refused(in_project, capsys):
    """Silently dropping a scope is how a run meant to touch four rows touches
    twenty."""
    assert cmd_illustrate.main(['--package', '--anchor-batch']) == 1
    assert 'only applies to --export' in capsys.readouterr().out


def test_anchor_batch_with_ids_is_refused(in_project, capsys):
    assert cmd_illustrate.main(['--export', '--anchor-batch',
                                '--ids', FIRST]) == 1
    assert 'not both' in capsys.readouterr().out


def test_anchor_batch_over_an_empty_plan_fails_rather_than_writing_nothing(
        project_dir, monkeypatch):
    ill.write_plan(project_dir, [])
    monkeypatch.chdir(project_dir)
    assert cmd_illustrate.main(['--export', '--anchor-batch']) == 1


# ============================================================================
# Staleness
# ============================================================================

def test_a_moved_plan_makes_the_export_stale(in_project):
    cmd_illustrate.main(['--export'])
    os.utime(ill.plan_path(in_project), None)
    findings = ex.export_stale(in_project)
    assert [f['kind'] for f in findings] == ['export_stale']
    assert ill.PLAN_FILENAME in findings[0]['detail']


def test_a_moved_prompt_file_makes_the_export_stale(in_project):
    """The export aggregates the prompt body, so its sources include files the
    packet never reads. A `packet_stale` check would miss this entirely."""
    rel = _write_prompt_file(in_project, FIRST)
    cmd_illustrate.main(['--export'])
    os.utime(os.path.join(in_project, rel), None)
    assert [f['kind'] for f in ex.export_stale(in_project)] == ['export_stale']


def test_a_replaced_reference_image_makes_the_export_stale(in_project):
    """What the recorded sha256 is *for*. This is the one way the bundle goes
    stale without any file under reference/ being touched."""
    cmd_illustrate.main(['--export'])
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 640, 960)
    findings = ex.export_stale(in_project)
    assert [f['kind'] for f in findings] == ['export_stale']
    assert 'has changed since it was copied' in findings[0]['detail']


def test_a_deleted_reference_source_makes_the_export_stale(in_project):
    cmd_illustrate.main(['--export'])
    os.remove(os.path.join(in_project, 'manuscript', 'assets',
                           'cover-illustration.png'))
    findings = ex.export_stale(in_project)
    assert 'no longer exists' in findings[0]['detail']


def test_an_unreadable_manifest_is_reported_not_skipped(in_project):
    cmd_illustrate.main(['--export'])
    with open(os.path.join(ex.unit_dir(in_project, FIRST),
                           ex.MANIFEST_FILENAME), 'w') as f:
        f.write('{not json')
    findings = ex.export_stale(in_project)
    assert 'could not be read' in findings[0]['detail']


def test_export_staleness_reaches_validate_and_cleanup(in_project):
    """The finding has to land in the durable artifact `forge` scans, not only in
    a log line — a stale bundle looks exactly like a fresh one to whoever it was
    handed to."""
    from storyforge import cmd_cleanup
    cmd_illustrate.main(['--export'])
    os.utime(ill.plan_path(in_project), None)
    assert any(f['kind'] == 'export_stale'
               for f in ill.validate_plan(in_project))
    findings = cmd_cleanup._check_illustrations(in_project)
    stale = [f for f in findings if f['type'] == 'illus_export_stale']
    assert len(stale) == 1
    assert stale[0]['severity'] == 'warning'
    assert '--export' in stale[0]['action']


def test_export_stale_is_a_warning_not_a_blocker(in_project):
    """It is a render, so regenerating is the whole fix — blocking would take a
    working book offline over one command."""
    assert ill.severity_of('export_stale') == 'warning'
    assert 'export_stale' not in ill.BLOCKING_FINDINGS


# ============================================================================
# Pruning
# ============================================================================

def test_a_whole_plan_export_removes_units_for_dropped_rows(in_project):
    cmd_illustrate.main(['--export'])
    rows = [r for r in ill.read_plan(in_project) if r['id'].strip() == FIRST]
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--export'])
    assert not os.path.exists(ex.unit_dir(in_project, SECOND))
    assert os.path.isdir(ex.unit_dir(in_project, FIRST))


def test_a_superseded_row_is_removed_from_the_export(in_project):
    """`rows_in_reading_order` drops it, and a retired illustration must not sit
    in a bundle someone is about to work through."""
    cmd_illustrate.main(['--export'])
    rows = ill.read_plan(in_project)
    next(r for r in rows if r['id'].strip() == SECOND)['status'] = 'superseded'
    ill.write_plan(in_project, rows)
    cmd_illustrate.main(['--export'])
    assert not os.path.exists(ex.unit_dir(in_project, SECOND))


def test_pruning_never_deletes_a_directory_this_command_did_not_write(in_project):
    """Only directories holding a manifest.json are candidates, so an author's
    own notes directory survives."""
    cmd_illustrate.main(['--export'])
    mine = os.path.join(ex.export_dir(in_project), 'my-notes')
    os.makedirs(mine)
    with open(os.path.join(mine, 'thoughts.md'), 'w') as f:
        f.write('keep me')
    ill.write_plan(in_project, [])
    cmd_illustrate.main(['--export'])
    assert os.path.isfile(os.path.join(mine, 'thoughts.md'))


# ============================================================================
# Anchors and coverage honesty
# ============================================================================

def test_anchors_in_the_written_export_are_byte_identical(in_project):
    cmd_illustrate.main(['--export'])
    written = _read(in_project, 'canon.md')
    sources = canon.anchor_texts(in_project)
    assert sources
    for text in sources.values():
        assert text in written


def test_anchor_copy_drift_covers_the_export(in_project):
    """The export writes anchor copies through the same `anchor_block`, so it is
    under the same byte-identity invariant — and it is the artifact designed to
    be handed to someone else."""
    from storyforge import packet
    cmd_illustrate.main(['--export'])
    path = os.path.join(ex.export_dir(in_project), 'canon.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.replace('steel-rimmed', 'gold-rimmed'))
    findings = packet.anchor_copy_drift(in_project)
    assert [f['kind'] for f in findings] == ['anchor_copy_drift']
    assert '--export' in findings[0]['detail']
    assert ex.EXPORT_DIR in findings[0]['file']


def test_a_scaffolded_book_level_canon_file_is_a_gap_naming_the_export(in_project):
    """The shared gap collectors say "packet" by default; a gap in the export's
    README saying so sends the reader to a directory that may not exist."""
    from illustration_helpers import write_canon_file
    write_canon_file(in_project, canon_id='content-limits', canon_type='rules',
                     body='TODO: fill this in')
    assert cmd_illustrate.main(['--export']) == 0
    readme = _read(in_project, 'README.md')
    assert 'this export leaves it out entirely' in readme
    assert 'this packet' not in readme


def test_a_never_run_audit_is_a_gap(in_project):
    assert cmd_illustrate.main(['--export']) == 0
    assert 'contradiction audit has never been run' in _read(in_project,
                                                            'README.md')


def test_a_slug_labeled_anchor_is_a_gap_rather_than_a_log_line(in_project):
    """Reported in the artifact, so an export-only author hears it — and so
    `--package --export` in one command does not print it twice.

    `brass-calipers` is in no registry and declares no `display_name`, so its
    label falls all the way through to a title-cased slug, which is a guess.
    """
    from illustration_helpers import write_canon_file
    write_canon_file(in_project, canon_id='brass-calipers',
                     canon_type='motif', subdir='motifs',
                     body='A pair of brass calipers, worn bright at the hinge.')
    assert cmd_illustrate.main(['--export']) == 0
    readme = _read(in_project, 'README.md')
    assert 'labeled from their id' in readme
    assert 'brass-calipers' in readme


def test_canon_stale_art_says_re_render_in_the_unit_and_in_readme(in_project):
    """`status` is `ingested` everywhere else, so a unit reading "already
    rendered" over art the canon has outgrown is what let a whole set be handed
    over unrendered (#300)."""
    rows = ill.read_plan(in_project)
    row = next(r for r in rows if r['id'].strip() == FIRST)
    asset = ill.default_asset_rel(FIRST)
    make_png(os.path.join(in_project, asset), 100, 150)
    row.update({'status': 'ingested', 'asset_file': asset,
                'sha256': ill.sha256_of(os.path.join(in_project, asset)),
                'width': '100', 'height': '150', 'ingested_at': '2020-01-01'})
    ill.write_plan(in_project, rows)

    assert cmd_illustrate.main(['--export']) == 0
    assert 're-render' in _read(in_project, 'README.md')
    assert 'do not demote its `status`' in _read_unit(in_project, FIRST)


def test_a_rendered_unit_is_marked_in_the_readme_table(in_project):
    rows = ill.read_plan(in_project)
    next(r for r in rows if r['id'].strip() == FIRST)['status'] = 'rendered'
    ill.write_plan(in_project, rows)
    assert cmd_illustrate.main(['--export']) == 0
    assert 'already rendered' in _read(in_project, 'README.md')


# ============================================================================
# --diagnose
# ============================================================================

def test_diagnose_reports_the_export_rung(in_project, capsys):
    cmd_illustrate.main(['--diagnose'])
    assert 'Export: not built' in capsys.readouterr().out
    cmd_illustrate.main(['--export'])
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    assert 'Export: built and current' in capsys.readouterr().out


def test_diagnose_reports_a_stale_export(in_project, capsys):
    cmd_illustrate.main(['--export'])
    os.utime(ill.plan_path(in_project), None)
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    assert 'Export: built and stale' in capsys.readouterr().out


def test_the_export_rung_shows_even_when_no_packet_is_built(in_project, capsys):
    """The two rungs are independent — an author can want the per-image export
    and never the session bundle — and nesting one inside the other made the
    export invisible in exactly the state where its line is the useful one."""
    cmd_illustrate.main(['--export'])
    from storyforge import packet
    assert not packet.is_built(in_project)
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Packet: not built' in out
    assert 'Export: built and current' in out


def test_the_export_rung_is_reported_once(in_project, capsys):
    """`export_stale` hashes every copied reference image, so running it twice
    per diagnose would also print its WARNING twice."""
    cmd_illustrate.main(['--export'])
    capsys.readouterr()
    cmd_illustrate.main(['--diagnose'])
    assert capsys.readouterr().out.count('Export: built') == 1


# ============================================================================
# The prompt-file parser
# ============================================================================

def test_parse_prompt_file_round_trips_render_prompt_file():
    """The reader lives beside the writer so the two cannot drift over the
    strings that bound the body."""
    row = {'id': 'x', 'scene_id': 's1', 'beat': 'a beat'}
    text = pi.render_prompt_file(row=row, body=MODEL_BODY, references=[],
                                 state='a state', absent='a thing',
                                 contrast='different')
    parsed = pi.parse_prompt_file(text)
    assert parsed['status'] == 'ok'
    assert parsed['body'] == MODEL_BODY


def test_parse_prompt_file_stops_before_the_constraints():
    """The constraints are regenerated from the plan, never inherited: they are
    derived, and the model's prose is the irreplaceable half."""
    row = {'id': 'x', 'scene_id': 's1'}
    text = pi.render_prompt_file(row=row, body='### Scene\n\nA room.',
                                 references=[], state='a state')
    body = pi.parse_prompt_file(text)['body']
    assert 'a state' not in body
    assert 'PORTRAIT' not in body


def test_parse_prompt_file_reports_a_missing_prompt_section():
    assert pi.parse_prompt_file('# notes\n\nnothing')['status'] == \
        'no_prompt_section'


def test_parse_prompt_file_reports_an_empty_body():
    text = (f'# x\n\n{pi.PROMPT_HEADING}\n\n{pi.PASTE_SENTINEL}\n\n---\n\n'
            f'{pi.CONSTRAINTS_HEADING}\n\n- a rule\n')
    parsed = pi.parse_prompt_file(text)
    assert parsed == {'body': '', 'status': 'empty_body'}


def test_parse_prompt_file_recovers_a_hand_edited_file_missing_the_sentinel():
    """The prompt file is documented as the editable source, so refusing here
    would send an author to re-run a paid `--prompts`."""
    text = (f'# x\n\n{pi.PROMPT_HEADING}\n\n### Scene\n\nA room.\n\n'
            f'{pi.CONSTRAINTS_HEADING}\n\n- a rule\n')
    parsed = pi.parse_prompt_file(text)
    assert parsed['status'] == 'ok'
    assert parsed['body'] == '### Scene\n\nA room.'


def test_parse_prompt_file_handles_crlf():
    row = {'id': 'x', 'scene_id': 's1'}
    text = pi.render_prompt_file(row=row, body='### Scene\n\nA room.',
                                 references=[])
    parsed = pi.parse_prompt_file(text.replace('\n', '\r\n'))
    assert parsed['body'] == '### Scene\n\nA room.'


def test_the_shared_constraint_list_does_not_use_a_positional_reference():
    """The export renders these bullets in a block whose anchors live in a
    sibling `canon.md`, so "the anchor description above" would point at nothing
    in one of the two artifacts that share the list."""
    joined = '\n'.join(pi.prompt_constraints())
    assert 'above' not in joined


def test_contrast_is_opt_in_for_the_constraint_list():
    """The prompt file keeps it in its do-NOT-paste block; the export puts it in
    the paste block. One function, two callers, one explicit difference."""
    assert not any('apart from its neighbours' in bullet
                   for bullet in pi.prompt_constraints(state='s'))
    assert any('apart from its neighbours' in bullet
               for bullet in pi.prompt_constraints(contrast='wider'))


def test_the_prompt_file_still_omits_contrast_from_its_paste_block():
    """Regression: `render_prompt_file` must not start passing contrast through
    to `prompt_constraints` — the derived clause names another illustration by
    id, which is why that file marks it do-NOT-paste."""
    row = {'id': 'x', 'scene_id': 's1'}
    text = pi.render_prompt_file(row=row, body='### Scene\n\nA room.',
                                 references=[], contrast='follows `y`')
    head, _, tail = text.partition('## Accept only if')
    assert 'follows `y`' not in head
    assert 'follows `y`' in tail


# ============================================================================
# Review round: the destructive paths
# ============================================================================

def test_a_lost_plan_does_not_delete_the_bundle(in_project, capsys):
    """`ill.read_plan` returns [] for a plan file that is missing, renamed, or
    mid-merge, which made a single `complete` bool vacuously true and pruned every
    unit — exit 0, with a log line blaming rows that had not moved. A wipe
    authorized by a missing file is not a wipe authorized by a changed plan."""
    cmd_illustrate.main(['--export'])
    os.remove(ill.plan_path(in_project))
    capsys.readouterr()

    assert cmd_illustrate.main(['--export']) == 0
    assert os.path.isdir(ex.unit_dir(in_project, FIRST))
    assert os.path.isdir(ex.unit_dir(in_project, SECOND))
    assert 'nothing was pruned' in capsys.readouterr().out


def test_an_empty_plan_is_not_called_a_partial_export(in_project):
    """The other half of the same bool: README must not call an empty plan a
    partial export, which is why the scope flag and the prune authority had to
    become two different things rather than one."""
    ill.write_plan(in_project, [])
    assert cmd_illustrate.main(['--export']) == 0
    readme = _read(in_project, 'README.md')
    assert 'partial export' not in readme
    assert 'no illustrations to export' in readme


def test_an_id_that_escapes_the_export_tree_is_refused(in_project):
    """A plan `id` of `../../evil` names a directory this command writes to and
    `rmtree`s. The plan is a documented hand-edit surface, so a typo reaches it,
    and `run_export` does not call `validate_plan` — the one check whose absence
    is destructive is made directly."""
    outside = os.path.join(in_project, 'evil', 'references')
    os.makedirs(outside)
    keep = os.path.join(outside, 'precious.txt')
    with open(keep, 'w') as f:
        f.write('do not delete me')

    rows = ill.read_plan(in_project)
    rows[0]['id'] = os.path.join('..', '..', 'evil')
    ill.write_plan(in_project, rows)

    assert cmd_illustrate.main(['--export']) == 1
    assert os.path.isfile(keep)
    assert not os.path.isdir(ex.export_dir(in_project))


def test_unit_dir_refuses_an_illegal_id_even_without_the_preflight(in_project):
    """The pre-flight is the message; this is the guard that keeps a future caller
    from bypassing it."""
    with pytest.raises(ValueError, match='invalid_id'):
        ex.unit_dir(in_project, '../../evil')


def test_a_foreign_directory_is_not_a_prune_candidate_even_with_a_manifest(
        in_project):
    """`existing_units` keys on a legal id *and* a manifest, so a stray directory
    name cannot become a deletion candidate — nor crash `unit_dir` on the way to
    that decision."""
    stray = os.path.join(ex.export_dir(in_project), 'not a legal id')
    os.makedirs(stray)
    with open(os.path.join(stray, ex.MANIFEST_FILENAME), 'w') as f:
        f.write('{}')
    assert ex.existing_units(in_project) == []
    cmd_illustrate.main(['--export'])
    assert os.path.isdir(stray)


# ============================================================================
# Review round: staleness must never crash, and never pass for "checked"
# ============================================================================

def test_an_unreadable_reference_does_not_crash_validate(in_project):
    """`validate_plan` is the single finding collector, so an unguarded hash took
    `validate`, `cleanup`, and `--diagnose` down with a PermissionError — losing
    the blocking findings `cmd_validate` gates on, over a file permission."""
    cmd_illustrate.main(['--export'])
    cover = os.path.join(in_project, 'manuscript', 'assets',
                         'cover-illustration.png')
    os.chmod(cover, 0o000)
    try:
        findings = ill.validate_plan(in_project)
        assert [f['kind'] for f in ex.export_stale(in_project)] == \
            ['export_stale']
        assert any(f['kind'] == 'export_stale' for f in findings)
        assert 'could not be read' in ex.export_stale(in_project)[0]['detail']
    finally:
        os.chmod(cover, 0o644)


def test_a_deleted_copy_is_reported(in_project):
    """The claim the recorded digest exists to defend: a manifest never promises
    an upload the directory does not hold. Checking only the source left the file
    the reader actually uploads unverified."""
    cmd_illustrate.main(['--export'])
    os.remove(os.path.join(ex.unit_dir(in_project, FIRST), 'references',
                           '1-cover-illustration.png'))
    detail = ex.export_stale(in_project)[0]['detail']
    assert 'is missing, so the manifest promises an upload' in detail


def test_a_corrupted_copy_is_reported(in_project):
    """A copy that exists and is not the image it claims to be. Only re-hashing
    the copy catches this; the source is untouched."""
    cmd_illustrate.main(['--export'])
    make_png(os.path.join(ex.unit_dir(in_project, FIRST), 'references',
                          '1-cover-illustration.png'), 12, 12)
    detail = ex.export_stale(in_project)[0]['detail']
    assert 'does not match the digest recorded for it' in detail


def test_a_unit_with_no_prompt_file_is_reported(in_project):
    """Omitting the missing file from the mtime set was the shape where the
    absence of the thing being checked removes it from the check."""
    cmd_illustrate.main(['--export'])
    os.remove(os.path.join(ex.unit_dir(in_project, FIRST), ex.PROMPT_FILENAME))
    detail = ex.export_stale(in_project)[0]['detail']
    assert f'has no {ex.PROMPT_FILENAME}' in detail


def test_a_manifest_whose_references_is_not_a_list_is_reported(in_project):
    """Parseable JSON of the wrong shape left every reference unchecked while
    `--diagnose` printed `built and current`. Silence must mean checked."""
    cmd_illustrate.main(['--export'])
    path = os.path.join(ex.unit_dir(in_project, FIRST), ex.MANIFEST_FILENAME)
    manifest = json.loads(open(path).read())
    manifest['references'] = {'1': 'oops'}
    with open(path, 'w') as f:
        json.dump(manifest, f)
    detail = ex.export_stale(in_project)[0]['detail']
    assert 'rather than a list' in detail


def test_a_reference_entry_missing_its_digest_is_reported(in_project):
    """An entry with no `sha256` is unverifiable, and unverifiable must not render
    as verified."""
    cmd_illustrate.main(['--export'])
    path = os.path.join(ex.unit_dir(in_project, FIRST), ex.MANIFEST_FILENAME)
    manifest = json.loads(open(path).read())
    manifest['references'][0].pop('sha256')
    with open(path, 'w') as f:
        json.dump(manifest, f)
    assert 'records no sha256' in ex.export_stale(in_project)[0]['detail']


def test_a_non_object_reference_entry_is_reported(in_project):
    cmd_illustrate.main(['--export'])
    path = os.path.join(ex.unit_dir(in_project, FIRST), ex.MANIFEST_FILENAME)
    manifest = json.loads(open(path).read())
    manifest['references'].append('not an object')
    with open(path, 'w') as f:
        json.dump(manifest, f)
    assert 'is not an object' in ex.export_stale(in_project)[0]['detail']


def test_the_stale_detail_does_not_assert_a_mismatch_over_an_unknown(in_project):
    """"could not be read" is not "no longer matches its sources" — the detail
    must not claim more than the check established."""
    cmd_illustrate.main(['--export'])
    with open(os.path.join(ex.unit_dir(in_project, FIRST),
                           ex.MANIFEST_FILENAME), 'w') as f:
        f.write('{not json')
    assert 'or cannot be checked against them' in \
        ex.export_stale(in_project)[0]['detail']


def test_art_direction_appearing_at_the_default_path_is_reported(in_project):
    """`_body_for` picks up `default_prompt_rel` with no plan edit, and
    `parse_prompt_file` invites hand-authoring — so a bundle built from a
    three-cell stand-in must not report itself current once the real prose lands
    beside it. This is why `prompt_source` is recorded even when nothing was read
    from it."""
    cmd_illustrate.main(['--export'])
    assert ex.export_stale(in_project) == []
    _write_prompt_file(in_project, FIRST)
    detail = ex.export_stale(in_project)[0]['detail']
    assert 'now has art direction at' in detail


def test_a_vanished_prompt_file_is_reported(in_project):
    """The other direction: re-exporting would silently downgrade the body to the
    plan row."""
    rel = _write_prompt_file(in_project, FIRST)
    cmd_illustrate.main(['--export'])
    os.remove(os.path.join(in_project, rel))
    detail = ex.export_stale(in_project)[0]['detail']
    assert 'is gone, so re-exporting would fall back' in detail


def test_the_cover_is_hashed_once_per_run_not_once_per_unit(in_project,
                                                           monkeypatch):
    """The cover is a reference in every unit, so a twenty-illustration export
    hashed it twenty times per `validate_plan` — a command that previously hashed
    nothing, run by `validate`, `cleanup`, and `--diagnose`."""
    cmd_illustrate.main(['--export'])
    calls: list[str] = []
    real = ill.sha256_of
    monkeypatch.setattr(ill, 'sha256_of',
                        lambda path: calls.append(path) or real(path))
    ex.export_stale(in_project)
    # The *source*, not the copies: each unit's copy is a distinct file and is
    # hashed once, which is the check itself. The source is one file shared by
    # every unit, and it is the one that was hashed per unit.
    source = os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png')
    assert [c for c in calls if c == source] == [source], calls


# ============================================================================
# Review round: the shared-file write order
# ============================================================================

def test_the_shared_files_are_written_after_the_units(in_project):
    """`is_built` keys on the shared files, so writing them first flipped it True
    at the moment the bundle was emptiest — an interrupted run then reported
    `built and current` over zero unit directories."""
    order: list[str] = []
    real = open

    def _tracking(path, *args, **kwargs):
        if isinstance(path, str) and ex.EXPORT_DIR in path and 'w' in str(args[:1] + (kwargs.get('mode', ''),)):
            order.append(os.path.relpath(path, ex.export_dir(in_project)))
        return real(path, *args, **kwargs)

    import builtins
    builtins.open = _tracking
    try:
        cmd_illustrate.main(['--export'])
    finally:
        builtins.open = real

    shared = [i for i, name in enumerate(order) if name in ex.SHARED_FILES]
    units = [i for i, name in enumerate(order) if name not in ex.SHARED_FILES]
    assert shared and units
    assert min(shared) > max(units), order


# ============================================================================
# Review round: the parse, the leak, and the truncation
# ============================================================================

def test_a_promoted_constraints_heading_does_not_leak_into_the_paste_block():
    """The likeliest hand edit — every heading around `### Constraints` is `##` —
    used to carry the file's own stale constraints into the exported paste block
    beside the freshly derived ones. Two contradicting costume directives in one
    region a reader pastes whole is #297 inside the fix."""
    text = pi.render_prompt_file(row={'id': 'x', 'scene_id': 's1'},
                                 body='### Scene\n\nA room.', references=[],
                                 state='navy pajamas')
    parsed = pi.parse_prompt_file(
        text.replace(pi.CONSTRAINTS_HEADING, '## Constraints'))
    assert parsed['status'] == 'ok'
    assert 'navy pajamas' not in parsed['body']
    assert parsed['body'] == '### Scene\n\nA room.'


def test_a_model_authored_constraints_heading_is_reported_as_truncated():
    """Documented model behaviour, per `build_art_direction_request`'s own note.
    Cutting at the first heading is the only reading that cannot self-contradict,
    so the tail is dropped — and #293 is why that is said out loud rather than
    accepted: a truncation every consumer accepts is worse than an absence."""
    body = ('### Scene\n\nA hall.\n\n### Constraints\n\nNo lettering.\n\n'
            '### Use case\n\nFull-page.')
    parsed = pi.parse_prompt_file(pi.render_prompt_file(
        row={'id': 'x', 'scene_id': 's1'}, body=body, references=[]))
    assert parsed['status'] == 'body_truncated'
    assert parsed['body'] == '### Scene\n\nA hall.'


def test_a_truncated_body_is_used_and_reported_in_the_export(in_project):
    """The prose is still better than three plan cells, so it is kept — and the
    reader is told a section is missing, in the file they are reading."""
    _write_prompt_file(in_project, FIRST, body=(
        '### Scene\n\nA hall.\n\n### Constraints\n\nNo lettering.\n\n'
        '### Use case\n\nFull-page.'))
    assert cmd_illustrate.main(['--export']) == 0
    unit = _read_unit(in_project, FIRST)
    assert 'carries its own `Constraints` heading' in unit
    assert _manifest(in_project, FIRST)['body_source'] == 'prompt_file'
    assert 'Constraints` heading inside their prompt body' in \
        _read(in_project, 'README.md')


def test_a_declared_prompt_file_that_is_missing_gets_its_own_sentence(in_project):
    """An author who typed a path meant that path, so the prose usually exists
    somewhere (moved, renamed, uncommitted) — a different action from "generate
    it again"."""
    rows = ill.read_plan(in_project)
    rows[0]['prompt_file'] = 'manuscript/assets/illustrations/prompts/gone.md'
    ill.write_plan(in_project, rows)
    assert cmd_illustrate.main(['--export']) == 0
    assert 'the plan declares art direction at' in _read_unit(in_project, FIRST)


def test_an_unreadable_prompt_file_falls_back_and_says_so(in_project):
    rel = _write_prompt_file(in_project, FIRST)
    path = os.path.join(in_project, rel)
    os.chmod(path, 0o000)
    try:
        assert cmd_illustrate.main(['--export']) == 0
        assert 'could not be read' in _read_unit(in_project, FIRST)
        assert _manifest(in_project, FIRST)['body_source'] == 'plan_row'
    finally:
        os.chmod(path, 0o644)


def test_an_empty_prompt_body_falls_back_and_says_so(in_project):
    rel = _write_prompt_file(in_project, FIRST)
    with open(os.path.join(in_project, rel), 'w', encoding='utf-8') as f:
        f.write(f'# x\n\n{pi.PROMPT_HEADING}\n\n{pi.PASTE_SENTINEL}\n\n---\n\n'
                f'{pi.CONSTRAINTS_HEADING}\n\n- a rule\n')
    assert cmd_illustrate.main(['--export']) == 0
    assert 'has an empty prompt body' in _read_unit(in_project, FIRST)


# ============================================================================
# Review round: the invariant the whole PR rests on
# ============================================================================

def test_a_subset_export_renders_a_row_exactly_as_a_whole_plan_export_does(
        in_project):
    """#297's shape inside the fix: a one-row `--ids` run must not make that row
    its own book-start and strip the contrast clause it has in the full book. The
    docstrings said so and nothing asserted it — a mutation passing the subset to
    `state_context` survived all 63 tests."""
    _write_prompt_file(in_project, SECOND)
    cmd_illustrate.main(['--export', '--ids', SECOND])
    subset = _read_unit(in_project, SECOND)
    cmd_illustrate.main(['--export'])
    assert _read_unit(in_project, SECOND) == subset
    assert FIRST in subset, 'the contrast clause names its predecessor'


# ============================================================================
# Review round: where facts land
# ============================================================================

def test_the_warnings_come_before_the_paste_region(in_project):
    """The placement is the point and it is about money: a reader who has already
    pasted has already spent the render."""
    assert cmd_illustrate.main(['--export']) == 0
    text = _read_unit(in_project, FIRST)
    assert text.index('Read this first') < text.index(pe._PASTE_OPEN)


def test_a_reference_chain_note_reaches_the_log_and_the_readme(in_project,
                                                              capsys):
    """It reached only the unit's own `prompt.md` while README enumerated a count
    that implied completeness — a finding whose only channel is one artifact."""
    assert cmd_illustrate.main(['--export']) == 0
    out = capsys.readouterr().out
    assert 'cover-only' in _read(in_project, 'README.md')
    assert 'cover-only' in out


def test_a_chain_note_is_not_in_read_this_first(in_project):
    """An unavoidable note about a book with no ingested art yet is not a reason
    to stop, and putting it above the genuine blockers dilutes them."""
    assert cmd_illustrate.main(['--export']) == 0
    text = _read_unit(in_project, FIRST)
    head = text[:text.index(pe._PASTE_OPEN)]
    first_block = head[head.index('Read this first'):head.index('## References')]
    assert 'cover-only' not in first_block
    assert 'About these reference images' in head


def test_one_project_wide_cause_is_one_readme_gap(in_project):
    """Two rows with no art direction produced one aggregate log line plus two
    per-row WARNINGs plus two README bullets. On twenty rows that is the noise
    that teaches an author to skip the section the real warnings live in."""
    assert cmd_illustrate.main(['--export']) == 0
    readme = _read(in_project, 'README.md')
    assert readme.count('have no written art direction') == 1
    assert '2 of 2 illustration(s)' in readme
    # The per-unit sentence still reaches the unit's own file: two readers.
    assert 'no written art direction' in _read_unit(in_project, FIRST)


def test_a_stale_prior_render_note_names_export_not_package(in_project):
    """The note is rendered into *this* bundle, and `--package` does not rebuild
    it."""
    rows = ill.read_plan(in_project)
    asset = ill.default_asset_rel(SECOND)
    make_png(os.path.join(in_project, asset), 100, 150)
    row = next(r for r in rows if r['id'].strip() == SECOND)
    row.update({'status': 'ingested', 'asset_file': asset,
                'sha256': ill.sha256_of(os.path.join(in_project, asset)),
                'width': '100', 'height': '150', 'ingested_at': '2020-01-01'})
    ill.write_plan(in_project, rows)

    assert cmd_illustrate.main(['--export']) == 0
    readme = _read(in_project, 'README.md')
    assert 'then re-run --export' in readme
    assert 'then re-run --package' not in readme


# ============================================================================
# Review round: acceptance.md speaks the export's vocabulary
# ============================================================================

def test_acceptance_points_at_the_prompt_not_at_packet_entries(in_project):
    """The export has no entries, and its reader may have no repo to look them up
    in. Same class as the `bundle` noun, applied to the renderer that was missed."""
    assert cmd_illustrate.main(['--export']) == 0
    acceptance = _read(in_project, 'acceptance.md')
    assert 'entry' not in acceptance.lower()
    assert 'prompt.md' in acceptance
    assert "prompt's `Not in this image:` constraint" in acceptance


def test_the_packet_acceptance_still_points_at_its_entries(in_project):
    """Regression: parameterizing the renderer must not change the packet."""
    assert cmd_illustrate.main(['--package']) == 0
    from storyforge import packet
    with open(packet.packet_file(in_project, 'acceptance.md'),
              encoding='utf-8') as f:
        acceptance = f.read()
    assert "its entry's **Beat**" in acceptance
    assert "the entry's **Absent** line" in acceptance


# ============================================================================
# Review round: the remaining uncovered branches
# ============================================================================

def test_a_gap_free_export_says_nothing_was_missing(in_project):
    """The happy-path README shape is unreachable end to end — a book with nothing
    ingested always carries the cover-only chain note — so the branch is asserted
    at the renderer, which is where it lives. Its own blank `gap_block` region is
    what a future edit to the f-string would break."""
    contents = ex.resolve(in_project)
    contents['gaps'] = []
    readme = pe.render_readme(title='A Book', contents=contents)
    assert 'Nothing was missing from the data' in readme
    assert 'thing(s) below were missing' not in readme


def test_two_references_resolving_to_one_file_are_listed_once(in_project):
    """Positional numbering must not gap: `copy_references` writes only what the
    manifest lists, so a skipped `order` would leave `1-…`, `3-…`."""
    rows = ill.read_plan(in_project)
    asset = ill.default_asset_rel(SECOND)
    os.makedirs(os.path.dirname(os.path.join(in_project, asset)), exist_ok=True)
    os.symlink(os.path.join(in_project, 'manuscript', 'assets',
                            'cover-illustration.png'),
               os.path.join(in_project, asset))
    row = next(r for r in rows if r['id'].strip() == SECOND)
    row.update({'status': 'ingested', 'asset_file': asset,
                'sha256': ill.sha256_of(os.path.join(in_project, asset)),
                'width': '800', 'height': '1200', 'ingested_at': '2026-07-29'})
    ill.write_plan(in_project, rows)

    assert cmd_illustrate.main(['--export']) == 0
    references = _manifest(in_project, FIRST)['references']
    assert [r['order'] for r in references] == list(
        range(1, len(references) + 1))
    assert len({r['source'] for r in references}) == len(references)


def test_a_treatment_renders_outside_the_paste_block(in_project):
    """The only place `--sequence`'s work surfaces in the export, and its
    placement below the paste line is deliberate: the body already embodies it, so
    repeating it to the model would be a second competing staging note."""
    rows = ill.read_plan(in_project)
    rows[0]['treatment'] = 'close, low angle, interior, night'
    ill.write_plan(in_project, rows)
    assert cmd_illustrate.main(['--export']) == 0
    text = _read_unit(in_project, FIRST)
    assert 'Staging assigned to this image' in text
    assert 'close, low angle, interior, night' not in _paste_block(text)


def test_an_unresolved_visual_state_is_stated_in_the_export(in_project):
    """`packet.NOT_RECORDED`'s reasoning, on this artifact: an acceptance block
    announcing "checked against this illustration's row" while silently dropping
    the state check is the omission #297 was filed about."""
    rows = ill.read_plan(in_project)
    rows[0]['canon_refs'] = 'cartography-office'
    rows[0]['state_override'] = ''
    ill.write_plan(in_project, rows)
    assert cmd_illustrate.main(['--export']) == 0
    text = _read_unit(in_project, FIRST)
    assert 'no visual state resolved' in text
    assert 'No visual state resolved for this illustration' in text


def test_a_reference_outside_the_project_keeps_its_absolute_path(in_project,
                                                                tmp_path):
    """Disclosed by being visibly absolute rather than quietly relativized into
    `../../..`, because the path reaches a bundle handed to another machine."""
    outside = tmp_path / 'elsewhere' / 'cover.png'
    make_png(str(outside), 640, 960)
    convention = os.path.join(in_project, 'manuscript', 'assets',
                              'cover-illustration.png')
    os.remove(convention)
    os.symlink(str(outside), convention)

    assert cmd_illustrate.main(['--export']) == 0
    reference = _manifest(in_project, FIRST)['references'][0]
    assert os.path.isabs(reference['resolved_from']), reference


def test_export_stale_over_a_project_with_no_canon_tree(in_project):
    """The canon-directory branch was never taken with the directory absent."""
    import shutil
    cmd_illustrate.main(['--export'])
    shutil.rmtree(os.path.join(in_project, 'reference', 'canon'))
    assert isinstance(ex.export_stale(in_project), list)


def test_resolve_reads_the_canon_cutoff_itself_when_not_given_one(in_project):
    """`cmd_illustrate` always threads one in; the default is the documented
    one-walk-per-run contract for any other caller."""
    contents = ex.resolve(in_project)
    assert [u['id'] for u in contents['units']] == [FIRST, SECOND]


def test_an_export_with_no_anchors_says_so(in_project):
    import shutil
    shutil.rmtree(os.path.join(in_project, 'reference', 'canon', 'characters'))
    shutil.rmtree(os.path.join(in_project, 'reference', 'canon', 'locations'))
    shutil.rmtree(os.path.join(in_project, 'reference', 'canon', 'motifs'))
    assert cmd_illustrate.main(['--export']) == 0
    assert 'no entity canon file has a populated Embeddable block' in \
        _read(in_project, 'README.md')


def test_the_zip_hint_quotes_a_path_with_a_space(in_project):
    hint = pe.render_zip_hint('/tmp/my project', FIRST)
    assert "'/tmp/my project/manuscript/illustration-export'" in hint


# ============================================================================
# Review round: the two changes the whole suite did not notice
# ============================================================================

def test_the_prompt_file_renders_the_shared_constraint_list():
    """The extraction is shared, but nothing asserted the *prompt file* half —
    so the constraint wording could change and 5789 tests still pass."""
    text = pi.render_prompt_file(row={'id': 'x', 'scene_id': 's1'},
                                 body='### Scene\n\nA room.', references=[],
                                 state='a state', absent='a thing')
    for bullet in pi.prompt_constraints(state='a state', absent='a thing'):
        assert bullet in text, bullet


def test_the_constraint_list_has_no_positional_anchor_reference():
    """In the export the anchors live in a sibling `canon.md`, so "the anchor
    description above" pointed at nothing in one of the two artifacts."""
    assert 'above' not in '\n'.join(pi.prompt_constraints())


def test_the_packet_names_the_prompt_convention_and_export_once():
    """The code half of the answer to the issue's criterion 1. Deleting the whole
    paragraph left 5789 tests passing."""
    from storyforge import prompts_packet as pp
    text = pp.render_illustrations(entries=[])
    assert text.count('--export') == 1
    assert 'prompts/<id>.md' in text


def test_a_reference_with_no_recorded_copy_is_reported(in_project):
    """An entry naming a source but no copied file means nothing in that unit can
    be uploaded for it — unverifiable, so it is said rather than skipped."""
    cmd_illustrate.main(['--export'])
    path = os.path.join(ex.unit_dir(in_project, FIRST), ex.MANIFEST_FILENAME)
    manifest = json.loads(open(path).read())
    manifest['references'][0].pop('file')
    with open(path, 'w') as f:
        json.dump(manifest, f)
    assert 'records no copied file' in ex.export_stale(in_project)[0]['detail']


def test_an_unreadable_copy_is_reported_rather_than_crashing(in_project):
    """The copy's own read can fail for the reason the source's can, and the same
    rule applies: unverifiable is not verified, and neither is a traceback."""
    cmd_illustrate.main(['--export'])
    copy = os.path.join(ex.unit_dir(in_project, FIRST), 'references',
                        '1-cover-illustration.png')
    os.chmod(copy, 0o000)
    try:
        detail = ex.export_stale(in_project)[0]['detail']
        assert 'the copy cannot be checked at all' in detail
    finally:
        os.chmod(copy, 0o644)

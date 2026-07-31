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
    """The contiguous region a reader is told to paste, and nothing else."""
    start = text.index(pe._PASTE_OPEN) + len(pe._PASTE_OPEN)
    return text[start:text.index(pe._PASTE_CLOSE)]


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


def test_ids_naming_no_live_row_warns(in_project, capsys):
    assert cmd_illustrate.main(['--export', '--ids', 'not-a-row']) == 0
    assert 'no live plan row' in capsys.readouterr().out


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

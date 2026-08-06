"""Tests for `storyforge illustrate` and its pipeline integration (#278).

Covers ingest, embed, diagnose, coaching-level branching, the GN guard, the
prompt renderers, the cleanup findings, schema validation, and the two
integration guarantees that matter most: markers never reach a prose scorer,
and publishing an illustrated book leaves content_html untouched.
"""

import json
import os

import pytest

from storyforge import cmd_illustrate
from storyforge import illustrations as ill
from storyforge import packet
from storyforge import prompts_illustrate as pi
from illustration_helpers import (
    scene_split,
    SCENE, SCENE_ADVERSARIAL, make_jpeg, make_png, plan_row,
    truncated_png, write_csv, write_scene,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Keep every test on the no-API path, at a known coaching level.

    Other test modules leak STORYFORGE_COACHING into the environment (see the
    same defence in test_scoring_story_power.py), which would silently route a
    `--plan` call down the strict branch and skip the dry-run path entirely.
    """
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('STORYFORGE_COACHING', raising=False)


@pytest.fixture
def in_project(project_dir, monkeypatch):
    """Run the command from inside the project, as the CLI does."""
    monkeypatch.chdir(project_dir)
    return project_dir


def read_plan_map(project_dir):
    return ill.read_plan_as_map(project_dir)


# ============================================================================
# Dispatch and guards
# ============================================================================

def test_no_phase_flag_is_an_error(in_project, capsys):
    assert cmd_illustrate.main([]) == 1
    assert 'Nothing to do' in capsys.readouterr().out


def test_graphic_novel_projects_are_refused(project_dir_gn, monkeypatch, capsys):
    monkeypatch.chdir(project_dir_gn)
    assert cmd_illustrate.main(['--plan']) == 1
    out = capsys.readouterr().out
    assert 'prose books' in out
    # The refusal must name the GN alternative, not just say no.
    assert 'page-architecture' in out


def test_id_filter_parsing():
    assert cmd_illustrate._id_filter(None) is None
    assert cmd_illustrate._id_filter('a, b ,') == {'a', 'b'}
    assert cmd_illustrate._id_filter('  ') is None


def test_slugify():
    assert cmd_illustrate._slugify('The Lantern Vigil!') == 'the-lantern-vigil'
    assert cmd_illustrate._slugify('!!!') == 'illustration'


def test_sanitize_cell_removes_pipes_and_newlines():
    assert cmd_illustrate._sanitize_cell('a|b\nc\r') == 'a/b c'


# ============================================================================
# --diagnose
# ============================================================================

def test_diagnose_with_no_plan(in_project, capsys):
    assert cmd_illustrate.main(['--diagnose']) == 0
    assert 'No illustration plan yet' in capsys.readouterr().out


def test_diagnose_reports_a_clean_plan(in_project, capsys):
    write_scene(in_project, 'vigil', ill.insert_marker(SCENE, plan_row())['text'])
    make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(in_project, [plan_row(
        status='ingested', sha256='a' * 64,
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])

    assert cmd_illustrate.main(['--diagnose']) == 0
    out = capsys.readouterr().out
    assert 'ingested: 1' in out
    assert 'No problems found' in out


def test_diagnose_exits_nonzero_on_findings(in_project, capsys):
    write_scene(in_project, 'vigil', 'One.\n\n![[illus:ghost]]\n\nTwo.\n')
    ill.write_plan(in_project, [plan_row()])

    assert cmd_illustrate.main(['--diagnose']) == 1
    assert 'orphan_marker' in capsys.readouterr().out


def test_diagnose_reports_an_incomplete_reference_tier(in_project, capsys):
    """Mode detection shifted from 'no direction document' to 'no reference
    tier' — diagnose names the missing canon ids, not missing document
    sections."""
    write_scene(in_project, 'vigil', ill.insert_marker(SCENE, plan_row())['text'])
    make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(in_project, [plan_row(
        status='ingested', sha256='a' * 64,
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])

    assert cmd_illustrate.main(['--diagnose']) == 0
    out = capsys.readouterr().out
    assert 'reference tier incomplete' in out
    assert 'visual-foundation' in out
    assert 'visual-vocabulary' in out
    assert 'content-limits' in out


# ============================================================================
# --ingest
# ============================================================================

def test_ingest_matches_by_filename_stem(in_project, tmp_path, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    make_png(str(renders / 'lantern-vigil.png'), 40, 60)

    assert cmd_illustrate.main(['--ingest', str(renders)]) == 0

    row = read_plan_map(in_project)['lantern-vigil']
    assert row['status'] == 'ingested'
    assert row['asset_file'] == ill.default_asset_rel('lantern-vigil')
    assert row['width'] == '40' and row['height'] == '60'
    assert len(row['sha256']) == 64
    assert os.path.isfile(os.path.join(in_project, row['asset_file']))
    # Ingest embeds as its final step.
    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        assert ill.marker_ids(f.read()) == ['lantern-vigil']


def test_ingest_records_the_actual_digest(in_project, tmp_path):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    src = make_png(str(renders / 'lantern-vigil.png'), 8, 8)

    cmd_illustrate.main(['--ingest', str(renders)])
    assert read_plan_map(in_project)['lantern-vigil']['sha256'] == \
        ill.sha256_of(src)


def test_ingest_accepts_a_single_file(in_project, tmp_path):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    src = make_png(str(tmp_path / 'lantern-vigil.png'), 8, 8)

    assert cmd_illustrate.main(['--ingest', src]) == 0
    assert read_plan_map(in_project)['lantern-vigil']['status'] == 'ingested'


def test_ingest_skips_unmatched_filenames(in_project, tmp_path, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    make_png(str(renders / 'lantern-vigil.png'), 8, 8)
    make_png(str(renders / 'mystery-image.png'), 8, 8)

    assert cmd_illustrate.main(['--ingest', str(renders)]) == 0
    out = capsys.readouterr().out
    assert 'mystery-image.png does not match any plan id' in out
    assert 'lantern-vigil' in read_plan_map(in_project)


def test_ingest_with_nothing_matching_fails_and_lists_ids(in_project, tmp_path,
                                                          capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    make_png(str(renders / 'unrelated.png'), 8, 8)

    assert cmd_illustrate.main(['--ingest', str(renders)]) == 1
    out = capsys.readouterr().out
    assert 'nothing to ingest' in out
    assert 'Plan ids: lantern-vigil' in out


def test_ingest_rejects_an_empty_file(in_project, tmp_path, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    renders.mkdir()
    (renders / 'lantern-vigil.png').write_bytes(b'')

    cmd_illustrate.main(['--ingest', str(renders)])
    assert 'is empty' in capsys.readouterr().out
    assert read_plan_map(in_project)['lantern-vigil']['status'] == 'planned'


def test_ingest_rejects_an_unreadable_image(in_project, tmp_path, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    renders.mkdir()
    (renders / 'lantern-vigil.png').write_bytes(b'not really a png at all')

    cmd_illustrate.main(['--ingest', str(renders)])
    # The message names *why*, not just that it failed — a valid file the parser
    # doesn't cover and a corrupt one need different actions from the author.
    out = capsys.readouterr().out
    assert 'does not begin with PNG, JPEG, or WebP magic bytes' in out
    assert read_plan_map(in_project)['lantern-vigil']['status'] == 'planned'


def test_ingest_without_a_plan_fails(in_project, tmp_path, capsys):
    renders = tmp_path / 'renders'
    make_png(str(renders / 'anything.png'), 8, 8)
    assert cmd_illustrate.main(['--ingest', str(renders)]) == 1
    assert 'no illustration plan' in capsys.readouterr().out


def test_ingest_from_a_missing_path_fails(in_project, capsys):
    assert cmd_illustrate.main(['--ingest', '/nope/nothing']) == 1
    assert 'no image files found' in capsys.readouterr().out


def test_ingest_dry_run_writes_nothing(in_project, tmp_path, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    make_png(str(renders / 'lantern-vigil.png'), 8, 8)

    assert cmd_illustrate.main(['--ingest', str(renders), '--dry-run']) == 0
    assert '[dry-run]' in capsys.readouterr().out
    assert read_plan_map(in_project)['lantern-vigil']['status'] == 'planned'
    assert not os.path.isfile(
        os.path.join(in_project, ill.default_asset_rel('lantern-vigil')))


def test_ingest_preserves_a_non_png_extension(in_project, tmp_path):
    from illustration_helpers import make_webp
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    make_webp(str(renders / 'lantern-vigil.webp'), 30, 40)

    cmd_illustrate.main(['--ingest', str(renders)])
    assert read_plan_map(in_project)['lantern-vigil']['asset_file'].endswith(
        '.webp')


# ============================================================================
# --embed
# ============================================================================

def test_embed_is_idempotent(in_project, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])

    cmd_illustrate.main(['--embed'])
    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        first = f.read()

    cmd_illustrate.main(['--embed'])
    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        assert f.read() == first
    assert ill.marker_ids(first) == ['lantern-vigil']


def test_embed_reports_a_drifted_anchor_with_a_hint(in_project, capsys):
    write_scene(in_project, 'vigil',
                'The lantern guttered.\n\n'
                'She placed it upon the windowsill and waited.\n')
    ill.write_plan(in_project, [plan_row()])

    cmd_illustrate.main(['--embed'])
    out = capsys.readouterr().out
    assert 'anchor not found' in out
    assert 'nearest candidate' in out
    assert 'windowsill' in out
    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        assert ill.marker_ids(f.read()) == []


def test_embed_skips_superseded_rows(in_project):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(status='superseded')])

    cmd_illustrate.main(['--embed'])
    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        assert ill.marker_ids(f.read()) == []


def test_embed_warns_on_a_missing_scene_file(in_project, capsys):
    ill.write_plan(in_project, [plan_row(scene_id='nowhere')])
    cmd_illustrate.main(['--embed'])
    assert 'has no file' in capsys.readouterr().out


def test_embed_respects_the_id_filter(in_project):
    write_scene(in_project, 'vigil', SCENE)
    write_scene(in_project, 'other', SCENE)
    ill.write_plan(in_project, [
        plan_row(),
        plan_row(id='second', scene_id='other'),
    ])

    cmd_illustrate.main(['--embed', '--ids', 'second'])
    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        assert ill.marker_ids(f.read()) == []
    with open(os.path.join(in_project, 'scenes', 'other.md')) as f:
        assert ill.marker_ids(f.read()) == ['second']


def test_embed_dry_run_writes_nothing(in_project, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])

    cmd_illustrate.main(['--embed', '--dry-run'])
    assert '[dry-run] would embed' in capsys.readouterr().out
    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        assert ill.marker_ids(f.read()) == []


def test_nearest_anchor_hint_returns_nothing_on_no_overlap():
    hint = cmd_illustrate._nearest_anchor_hint(
        'Entirely different words.\n', plan_row())
    assert hint == ''


def test_nearest_anchor_hint_needs_no_anchor_to_be_safe():
    assert cmd_illustrate._nearest_anchor_hint(SCENE, plan_row(anchor='')) == ''


# ============================================================================
# --plan coaching branches
# ============================================================================

def test_plan_strict_writes_a_checklist_and_calls_no_api(in_project):
    assert cmd_illustrate.main(['--plan', '--coaching', 'strict']) == 0
    path = os.path.join(in_project, 'working', 'coaching',
                        'illustration-checklist.md')
    assert os.path.isfile(path)
    with open(path) as f:
        content = f.read()
    assert 'constraint checklist' in content
    assert 'It proposes nothing' in content
    assert 'storyforge illustrate --prompts' in content


def test_plan_full_without_an_api_key_fails_clearly(in_project, capsys):
    assert cmd_illustrate.main(['--plan', '--coaching', 'full']) == 1
    assert 'ANTHROPIC_API_KEY is not set' in capsys.readouterr().out


def test_plan_dry_run_needs_no_api_key(in_project, capsys):
    assert cmd_illustrate.main(['--plan', '--dry-run', '--coaching', 'full']) == 0
    assert '[dry-run] would propose' in capsys.readouterr().out


def test_plan_dry_run_honors_count(in_project, capsys):
    cmd_illustrate.main(['--plan', '--dry-run', '--count', '11'])
    assert 'would propose 11 illustrations' in capsys.readouterr().out


def test_plan_skips_the_llm_when_the_prepass_is_dry(tmp_path, monkeypatch,
                                                   capsys):
    """No gaps and an existing plan means no reason to spend a call."""
    bare = tmp_path / 'bare'
    (bare / 'reference').mkdir(parents=True)
    (bare / 'scenes').mkdir()
    (bare / 'storyforge.yaml').write_text('project:\n  title: "Bare"\n')
    ill.write_plan(str(bare), [plan_row(scene_id='')])

    monkeypatch.chdir(bare)
    assert cmd_illustrate.main(['--plan', '--coaching', 'full']) == 0
    assert 'skipping the LLM pass' in capsys.readouterr().out


def test_plan_merges_proposals_and_flags_bad_anchors(in_project, monkeypatch,
                                                     capsys):
    write_scene(in_project, 'vigil', SCENE)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: json.dumps({
        'proposals': [
            {'id': 'Lantern Vigil', 'scene_id': 'vigil',
             'anchor': 'She set it on the sill', 'placement': 'after_anchor',
             'beat': 'A woman waits', 'rationale': 'It holds the waiting',
             'avoid': 'the letter she has not opened'},
            {'id': 'drifted', 'scene_id': 'vigil',
             'anchor': 'a phrase that is not there', 'beat': 'Something else'},
        ]
    }))

    assert cmd_illustrate.main(['--plan', '--coaching', 'full']) == 0

    plan = read_plan_map(in_project)
    assert 'lantern-vigil' in plan          # id was slugified
    assert 'drifted' in plan
    # `avoid` has no column of its own, so it folds into the rationale.
    assert 'Must not show: the letter she has not opened' \
        in plan['lantern-vigil']['rationale']
    # Placement defaults when the model omits it.
    assert plan['drifted']['placement'] == 'after_anchor'
    out = capsys.readouterr().out
    assert 'need attention before embedding' in out
    assert 'anchor_drift' in out


def test_plan_coach_writes_a_brief_and_no_csv(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: json.dumps({
        'proposals': [{'id': 'candidate', 'scene_id': 'vigil',
                       'beat': 'A woman waits', 'anchor': 'x'}]
    }))

    assert cmd_illustrate.main(['--plan', '--coaching', 'coach']) == 0
    assert ill.read_plan(in_project) == []
    path = os.path.join(in_project, 'working', 'coaching',
                        'illustration-brief.md')
    with open(path) as f:
        content = f.read()
    assert 'Illustration planning brief' in content
    assert 'candidate' in content


def test_plan_reports_an_unparseable_response(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: 'no json here')
    assert cmd_illustrate.main(['--plan', '--coaching', 'full']) == 1
    assert 'could not parse proposals' in capsys.readouterr().out


def test_plan_reports_an_empty_response(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: '')
    assert cmd_illustrate.main(['--plan', '--coaching', 'full']) == 1
    assert 'no response from the API' in capsys.readouterr().out


# ============================================================================
# --prompts coaching branches
# ============================================================================

def test_prompts_with_nothing_planned(in_project, capsys):
    assert cmd_illustrate.main(['--prompts']) == 0
    assert 'No rows at status=planned' in capsys.readouterr().out


def test_prompts_strict_writes_a_scaffold_without_an_api_key(in_project):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(subject='A woman at a sill',
                                        palette='cold blue')])

    assert cmd_illustrate.main(['--prompts', '--coaching', 'strict']) == 0

    row = read_plan_map(in_project)['lantern-vigil']
    assert row['status'] == 'prompted'
    with open(os.path.join(in_project, row['prompt_file'])) as f:
        content = f.read()
    assert '### Subject' in content
    assert 'A woman at a sill' in content
    assert 'cold blue' in content
    assert '_(you fill this in)_' in content   # unset cells stay unset
    assert 'PORTRAIT orientation' in content
    assert 'no text, no letters, no words' in content


def test_prompts_full_without_an_api_key_fails(in_project, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 1
    assert 'ANTHROPIC_API_KEY is not set' in capsys.readouterr().out


def test_prompts_warns_missing_when_reference_tier_is_entirely_absent(
        in_project, capsys):
    """No reference/canon/ book-level files at all: the fix belongs to
    --direction, so the WARNING points there."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])

    assert cmd_illustrate.main(['--prompts', '--coaching', 'strict']) == 0
    out = capsys.readouterr().out
    assert 'is missing book-level file(s) for' in out
    assert 'visual-foundation' in out
    assert 'Run `storyforge illustrate --direction` first' in out
    assert 'has unfilled book-level file(s)' not in out


def test_prompts_warns_to_edit_when_reference_tier_is_placeholder(
        in_project, capsys):
    """Regression: after `--direction --coaching strict`, every book-level
    file already exists as a TODO scaffold. Telling the author to run
    --direction again would be a no-op (run_direction never overwrites an
    existing file) — the WARNING must point at editing the files, and must
    not repeat the 'missing' advice for files that already exist."""
    for canon_id, canon_type in (('visual-foundation', 'foundation'),
                                 ('visual-vocabulary', 'vocabulary'),
                                 ('content-limits', 'rules')):
        _write_book_level_canon(in_project, canon_id, canon_type,
                                'TODO — fill this in')
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])

    assert cmd_illustrate.main(['--prompts', '--coaching', 'strict']) == 0
    out = capsys.readouterr().out
    assert 'has unfilled book-level file(s) for' in out
    assert 'visual-foundation' in out
    assert 'edit them directly' in out
    assert 'is missing book-level file(s)' not in out


def test_prompts_full_writes_body_and_appends_new_anchors(in_project, monkeypatch):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '### Scene\n\nA cold street at night.\n\n'
        '### Subject\n\nA woman at a lit sill.\n\n'
        'ANCHORS\n- Dorren Hayle | character — a spare woman of fifty in a '
        'grey coat\n'
    ))

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0

    row = read_plan_map(in_project)['lantern-vigil']
    with open(os.path.join(in_project, row['prompt_file'])) as f:
        content = f.read()
    assert 'A cold street at night' in content
    # The anchor block is lifted out of the body, not left in the prompt.
    assert 'ANCHORS' not in content
    # A proposed anchor persists as a canon file stub for the author to review.
    from storyforge import canon
    assert canon.anchor_texts(in_project)['dorren-hayle'] == (
        'a spare woman of fifty in a grey coat')
    assert canon.resolve_canon_path(in_project, 'dorren-hayle').endswith(
        os.path.join('characters', 'dorren-hayle.md'))


def test_prompts_skips_a_row_when_the_api_returns_nothing(in_project, monkeypatch,
                                                          capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: '')

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 1
    out = capsys.readouterr().out
    assert 'no art direction returned' in out
    # Status must not advance past a failure.
    assert read_plan_map(in_project)['lantern-vigil']['status'] == 'planned'


def test_prompts_dry_run_writes_nothing(in_project, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    assert cmd_illustrate.main(['--prompts', '--dry-run']) == 0
    assert '[dry-run] would write' in capsys.readouterr().out
    assert read_plan_map(in_project)['lantern-vigil']['status'] == 'planned'


def test_prompts_references_prior_illustrations_for_style(in_project):
    make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR, 'earlier.png'),
             8, 8)
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 8)
    ill.write_plan(in_project, [
        plan_row(id='earlier', status='ingested',
                 asset_file=ill.default_asset_rel('earlier')),
        plan_row(),
    ])

    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil')
    paths = [path for path, _label in refs]
    assert any('cover-illustration.png' in p for p in paths)
    assert any('earlier.png' in p for p in paths)
    # An illustration never references itself.
    assert not any('lantern-vigil.png' in p for p in paths)
    # Every reference is labeled with what it is for.
    assert all(label for _path, label in refs)


def test_references_render_with_the_label_outside_the_code_span():
    block = pi.render_references_block([('a/b.png', 'cover art')])
    assert '1. `a/b.png` — cover art' in block


def test_references_accept_bare_paths():
    assert '1. `a/b.png`' in pi.render_references_block(['a/b.png'])


def test_references_are_capped(in_project):
    """More than a handful and the model starts averaging them.

    Asserted over the priors, not over `len(refs)`: this project resolves no
    cover, so a total count would equal the prior count by coincidence and stop
    distinguishing the two quantities #311 separated.
    """
    rows = []
    for i in range(8):
        make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR,
                              f'prior-{i}.png'), 8, 8)
        rows.append(plan_row(id=f'prior-{i}', status='ingested',
                             asset_file=ill.default_asset_rel(f'prior-{i}')))
    ill.write_plan(in_project, rows + [plan_row()])

    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil')
    priors = [p for p, _ in refs if 'cover-illustration' not in p]
    assert len(priors) == cmd_illustrate._MAX_PRIOR_REFERENCES


def test_scene_split_strips_markers(in_project):
    write_scene(in_project, 'vigil', ill.insert_marker(SCENE, plan_row())['text'])
    split = cmd_illustrate._scene_split(in_project, plan_row())
    assert '![[illus:' not in split['read']
    assert '![[illus:' not in split['unread']
    assert 'She set it on the sill' in split['read']


def test_scene_split_handles_a_missing_scene(in_project):
    """A missing scene is an unresolved *position*, not an empty unread side.

    Returning `unread: ''` with no error would tell the request there is nothing
    after this illustration — the exact silence #308 was filed about, arrived at
    from the other direction.
    """
    split = cmd_illustrate._scene_split(in_project, plan_row(scene_id='nowhere'))
    assert split['state'] == 'unknown'
    assert split['unread'] == ''
    assert 'nowhere' in split['error']
    # No `(scene file not found)` placeholder: it was printed to the model under
    # a heading calling it the prose the reader had read.
    assert split['read'] == ''


def test_scene_split_does_not_hand_the_model_the_next_page(in_project):
    """#308's regression, at the boundary the whole issue is about.

    The old excerpt was a window centred on the anchor, so the beat *after* the
    marker arrived as ordinary scene prose and came back as the illustration.
    """
    write_scene(in_project, 'vigil', SCENE)
    split = cmd_illustrate._scene_split(in_project, plan_row())

    assert 'She set it on the sill' in split['read']
    assert 'Nothing came' not in split['read']
    assert 'By morning she had decided' not in split['read']
    assert 'Nothing came' in split['unread']
    assert split['next_sentence'] == 'Nothing came.'


# ============================================================================
# Prompt renderers
# ============================================================================

@pytest.mark.parametrize('composition,aspect', [
    ('a tight square crop', 'square'),
    ('wide landscape vista', 'landscape'),
    ('close on her hands', 'portrait'),
    ('', 'portrait'),
])
def test_aspect_for_row(composition, aspect):
    assert pi.aspect_for_row(plan_row(composition=composition)) == aspect


@pytest.mark.parametrize('aspect,expected', [
    ('portrait', 'PORTRAIT'), ('landscape', 'LANDSCAPE'), ('square', 'SQUARE'),
])
def test_orientation_clause_states_the_aspect(aspect, expected):
    clause = pi.orientation_clause(aspect)
    assert expected in clause
    # Orientation is the one place negation is deliberate (#263).
    assert 'Do not render' in clause


def test_render_prompt_file_states_orientation_twice():
    content = pi.render_prompt_file(
        split=scene_split(), row=plan_row(), body='### Scene\n\nA street.\n', references=[],
        aspect='portrait',
    )
    assert content.count('PORTRAIT orientation') >= 1
    assert '**Aspect:** portrait' in content
    assert 'no text, no letters, no words, no typography' in content
    assert '| Attempt | Model |' in content


@pytest.mark.parametrize('kwargs,present,missing', [
    ({'state': 'Leo: rust-red jacket'},
     ['overrides any anchor detail that disagrees',
      'The visual state matches: Leo: rust-red jacket'],
     ['Not in this image', 'must not be', 'No visual state resolved']),
    ({'absent': 'the apprentice'},
     ['Not in this image: the apprentice',
      'Nothing in frame that must not be',
      'No visual state resolved'],
     ['The visual state matches']),
    ({'contrast': 'The darkest image in the book'},
     ['set apart from its neighbours', 'No visual state resolved'],
     ['The visual state matches: ', 'Not in this image']),
    ({}, ['No visual state resolved'],
     ['The visual state matches: ', 'Not in this image',
      'set apart from its neighbours']),
])
def test_the_prompt_file_emits_only_the_blocks_it_has(kwargs, present, missing):
    """Each of the three is independently optional. `## Accept only if` is always
    rendered, because a state that did not resolve is stated rather than
    omitted — an omitted line left the block claiming a completeness it did not
    have."""
    content = pi.render_prompt_file(split=scene_split(), row=plan_row(), body='### Scene\n\nX.\n',
                                    references=[], **kwargs)
    assert '## Accept only if' in content
    for text in present:
        assert text in content
    for text in missing:
        assert text not in content


def test_the_acceptance_block_is_marked_do_not_paste():
    """It follows "paste everything below", its prose reads like prompt text, and
    via `contrast` it can name another illustration by id — which the request
    explicitly forbids reaching the model."""
    content = pi.render_prompt_file(
        split=scene_split(), row=plan_row(), body='### Scene\n\nX.\n', references=[],
        contrast='Follows `lantern-vigil` and must not repeat its staging')
    assert '## Accept only if (not part of the prompt — do NOT paste)' in content
    paste_marker = 'Paste everything below into the image model.'
    assert content.index(paste_marker) < content.index('## Accept only if')


def test_render_references_block_labels_each_reference():
    block = pi.render_references_block(['a.png  — cover art', 'b.png  — prior'])
    assert '1. `a.png  — cover art`' in block
    assert '2. `b.png  — prior`' in block


def test_render_references_block_when_empty_explains_the_chain():
    block = pi.render_references_block([])
    assert 'first illustration establishes' in block


def test_split_anchor_block_without_a_block():
    body, anchors = pi.split_anchor_block('### Scene\n\nA street.\n')
    assert anchors == {}
    assert body == '### Scene\n\nA street.'


def test_split_anchor_block_parses_multiple_anchors():
    body, anchors = pi.split_anchor_block(
        '### Scene\n\nA street.\n\nANCHORS\n'
        '- Dorren Hayle — a spare woman in grey\n'
        '- **Vell** | character — a boy with ink-stained cuffs\n'
    )
    assert 'ANCHORS' not in body
    assert anchors == {
        'Dorren Hayle': ('', 'a spare woman in grey'),
        'Vell': ('character', 'a boy with ink-stained cuffs'),
    }


def test_append_anchor_stubs_never_overwrites_an_existing_anchor(project_dir):
    """Likeness continuity depends on the anchor staying byte-identical."""
    from storyforge import canon
    pi.append_anchor_stubs(
        project_dir, {'Dorren': ('character', 'original description')})
    added = pi.append_anchor_stubs(project_dir, {
        'Dorren': ('character', 'revised description'),
        'Vell': ('character', 'a boy'),
    })

    assert added == ['vell']
    anchors = canon.anchor_texts(project_dir)
    assert anchors['dorren'] == 'original description'
    assert anchors['vell'] == 'a boy'


def test_append_anchor_stubs_is_case_insensitive(project_dir):
    """Both display names slugify to the same canon_id, so the second call
    resolves an existing file rather than writing a sibling."""
    from storyforge import canon
    pi.append_anchor_stubs(project_dir, {'Dorren': ('character', 'original')})
    assert pi.append_anchor_stubs(
        project_dir, {'dorren': ('character', 'again')}) == []
    assert canon.anchor_texts(project_dir)['dorren'] == 'original'


def test_append_anchor_stubs_skips_empty_values(project_dir, capsys):
    """Regression (fix round 1, I-1): a bare `continue` used to drop a
    blank-name or blank-text proposal with no trace. Both branches must log a
    WARNING naming what was dropped, not vanish silently."""
    assert pi.append_anchor_stubs(project_dir, {
        'Nameless': ('character', ''), '': ('character', 'x'),
    }) == []
    out = capsys.readouterr().out
    assert "WARNING: proposed anchor 'Nameless' has no anchor text" in out
    assert "WARNING: proposed anchor '' has no usable slug" in out


def test_anchors_for_prompt_with_no_canon_dir(project_dir):
    assert pi.anchors_for_prompt(project_dir) == {}


def test_selection_prompt_embeds_the_prepass_findings(project_dir):
    write_csv(project_dir, 'spine.csv', 'id|title|summary',
              ['e1|The Assignment|A crown order arrives.'])
    prepass = ill.selection_prepass(project_dir)
    prompt = pi.build_selection_prompt(
        prepass=prepass, target_count=6, story_context='A novel.',
    )
    assert 'Choose 6 moments' in prompt
    assert 'The Assignment' in prompt
    assert 'does not spoil what the facing page' in prompt
    assert '"proposals"' in prompt


@pytest.mark.parametrize('text,status', [
    ('{"proposals": [{"id": "a"}]}', 'ok'),
    ('```json\n{"proposals": [{"id": "a"}]}\n```', 'ok'),
    ('Here you go:\n{"proposals": [{"id": "a"}]}\nDone.', 'ok'),
    ('{"other": []}', 'no_proposals_key'),
    ('{"proposals": []}', 'no_proposals_key'),
    ('not json at all', 'no_json'),
])
def test_parse_selection_response(text, status):
    proposals, got = pi.parse_selection_response(text)
    assert got == status
    if status == 'ok':
        assert proposals[0]['id'] == 'a'


def test_parse_selection_response_drops_proposals_with_no_id():
    proposals, status = pi.parse_selection_response(
        '{"proposals": [{"id": ""}, {"id": "keep"}]}')
    assert status == 'ok'
    assert [p['id'] for p in proposals] == ['keep']


def test_coach_brief_surfaces_findings_as_questions(project_dir):
    write_csv(project_dir, 'spine.csv', 'id|title|summary',
              ['e1|The Assignment|A crown order arrives.'])
    write_csv(project_dir, 'scene-briefs.csv', 'id|goal|motifs',
              ['s1|x|lantern', 's2|x|lantern', 's3|x|lantern'])
    brief = pi.render_coach_brief(
        prepass=ill.selection_prepass(project_dir), target_count=5)

    assert 'Spine events with no illustration' in brief
    assert 'Motifs that pay off' in brief
    assert 'Questions to settle' in brief
    assert 'lantern' in brief


def test_strict_checklist_reports_data_and_proposes_nothing(project_dir):
    checklist = pi.render_strict_checklist(
        prepass=ill.selection_prepass(project_dir), target_count=5)
    assert 'It proposes nothing' in checklist
    assert '| `anchor` |' in checklist
    assert 'before_anchor' in checklist


# ============================================================================
# schema validation
# ============================================================================

def test_schema_validation_with_no_plan(project_dir):
    from storyforge.schema import validate_illustration_plan
    result = validate_illustration_plan(project_dir)
    assert result == {'row_count': 0, 'errors': [], 'warnings': []}


def test_schema_validation_of_a_clean_plan(project_dir):
    from storyforge.schema import validate_illustration_plan
    write_scene(project_dir, 'vigil', ill.insert_marker(SCENE, plan_row())['text'])
    ill.write_plan(project_dir, [plan_row(status='planned')])

    result = validate_illustration_plan(project_dir)
    assert result['row_count'] == 1
    assert result['errors'] == []
    assert result['warnings'] == []


def test_schema_validation_rejects_a_bad_header(project_dir):
    from storyforge.schema import validate_illustration_plan
    path = ill.plan_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('id|scene_id\nlantern-vigil|vigil\n')

    result = validate_illustration_plan(project_dir)
    assert 'missing columns' in result['errors'][0]['message']


def test_schema_validation_splits_errors_from_warnings(project_dir):
    from storyforge.schema import validate_illustration_plan
    write_scene(project_dir, 'vigil', 'Rewritten prose.\n\n![[illus:ghost]]\n')
    ill.write_plan(project_dir, [plan_row(status='planned')])

    result = validate_illustration_plan(project_dir)
    assert any('orphan_marker' in e['message'] for e in result['errors'])
    assert any('anchor_drift' in w['message'] for w in result['warnings'])


def test_validate_reports_a_blocking_illustration_finding(project_dir,
                                                          monkeypatch, capsys):
    """Asserting only the exit code proved nothing: the fixture project already
    exits 1 on structural validation independently, so this test passed with the
    illustration wiring reverted entirely."""
    from storyforge import cmd_validate
    monkeypatch.chdir(project_dir)
    write_scene(project_dir, 'vigil', 'One.\n\n![[illus:ghost]]\n\nTwo.\n')
    ill.write_plan(project_dir, [plan_row(status='planned')])

    with pytest.raises(SystemExit) as exc:
        cmd_validate.main(['--quiet'])
    assert exc.value.code == 1
    # The illustration error is what must be surfaced, not merely a non-zero exit.
    out = capsys.readouterr().out
    assert 'Illustration plan' in out
    assert 'orphan_marker' in out


def test_validate_illustration_gate_is_wired(project_dir):
    """Directly assert the gate, independent of any other validation result."""
    from storyforge.schema import validate_illustration_plan
    write_scene(project_dir, 'vigil', 'One.\n\n![[illus:ghost]]\n\nTwo.\n')
    ill.write_plan(project_dir, [plan_row(status='planned')])

    result = validate_illustration_plan(project_dir)
    assert result['errors']
    assert not all(result[k] == [] for k in ('errors', 'warnings'))


# ============================================================================
# cleanup findings
# ============================================================================

def test_cleanup_reports_each_finding_with_remediation(project_dir):
    from storyforge.cmd_cleanup import _check_illustrations
    write_scene(project_dir, 'vigil', 'Rewritten.\n\n![[illus:ghost]]\n')
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR, 'stray.png'),
             8, 8)
    ill.write_plan(project_dir, [plan_row(
        status='ingested', asset_file=ill.default_asset_rel('lantern-vigil'),
    )])

    findings = _check_illustrations(project_dir)
    types = {f['type'] for f in findings}
    assert 'illus_orphan_marker' in types
    assert 'illus_missing_file' in types
    assert 'illus_orphan_file' in types
    assert 'illus_anchor_drift' in types
    # Every finding carries a concrete next step.
    assert all(f['action'] and f['detail'] for f in findings)


def test_cleanup_reports_duplicate_markers(project_dir):
    from storyforge.cmd_cleanup import _check_illustrations
    write_scene(project_dir, 'vigil',
                'One.\n\n![[illus:lantern-vigil]]\n\nTwo.\n\n'
                '![[illus:lantern-vigil]]\n')
    ill.write_plan(project_dir, [plan_row(anchor='', status='planned')])

    types = {f['type'] for f in _check_illustrations(project_dir)}
    assert 'illus_duplicate_marker' in types


def test_cleanup_severity_follows_finding_kind(project_dir):
    from storyforge.cmd_cleanup import _check_illustrations
    write_scene(project_dir, 'vigil', 'Rewritten prose.\n')
    ill.write_plan(project_dir, [plan_row(status='planned')])

    findings = _check_illustrations(project_dir)
    drift = next(f for f in findings if f['type'] == 'illus_anchor_drift')
    assert drift['severity'] == 'warning'


def test_cleanup_is_silent_on_a_clean_project(project_dir):
    from storyforge.cmd_cleanup import _check_illustrations
    assert _check_illustrations(project_dir) == []


def test_cleanup_does_not_flag_an_unrendered_row(project_dir):
    from storyforge.cmd_cleanup import _check_illustrations
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(status='planned')])
    assert _check_illustrations(project_dir) == []


# ============================================================================
# Prose-analysis integration — a marker must never be scored
# ============================================================================

#: Marked copies of the adversarial fixture, in the two placements that put a
#: marker where it could actually perturb an analysis.
MARKED = ill.insert_marker(SCENE_ADVERSARIAL, plan_row())['text']
MARKED_AT_OPEN = ill.insert_marker(
    SCENE_ADVERSARIAL, plan_row(placement='scene_open', anchor=''))['text']


@pytest.mark.parametrize('module,func', [
    ('scoring_passive', 'score_avoid_passive'),
    ('scoring_adverbs', 'score_avoid_adverbs'),
    ('scoring_weather', 'score_no_weather_dreams'),
    ('scoring_rhythm', 'score_sentence_as_thought'),
])
@pytest.mark.parametrize('marked', [MARKED, MARKED_AT_OPEN])
def test_deterministic_scorers_ignore_markers(module, func, marked):
    """Asserted on SCENE_ADVERSARIAL: on a clean fixture every density is 0/N
    and stays 0 whether the marker is counted, so these passed even with
    stripping fully reverted."""
    import importlib
    scorer = getattr(importlib.import_module(f'storyforge.{module}'), func)
    assert scorer(marked) == scorer(SCENE_ADVERSARIAL)


def test_the_adversarial_fixture_actually_produces_findings():
    """Tripwire: if the fixture ever goes clean, the assertions above go
    vacuous silently."""
    from storyforge.prose_analysis import (
        detect_adverbs, detect_filler_phrases, detect_passive_voice,
        extract_dialogue,
    )
    assert detect_passive_voice(SCENE_ADVERSARIAL)
    assert detect_adverbs(SCENE_ADVERSARIAL)
    assert detect_filler_phrases(SCENE_ADVERSARIAL)
    assert extract_dialogue(SCENE_ADVERSARIAL)[0].strip()


def test_economy_scorer_ignores_markers():
    from storyforge.scoring_economy import score_economy_clarity
    assert score_economy_clarity(MARKED) == \
        score_economy_clarity(SCENE_ADVERSARIAL)


@pytest.mark.parametrize('detector', [
    'detect_passive_voice', 'detect_adverbs', 'detect_filler_phrases',
])
@pytest.mark.parametrize('marked', [MARKED, MARKED_AT_OPEN])
def test_prose_detectors_ignore_markers(detector, marked):
    """Both placements: these detectors return character positions, and a
    marker only shifts them for content that follows it — so a marker in the
    middle leaves anything earlier in the scene unmoved."""
    from storyforge import prose_analysis
    fn = getattr(prose_analysis, detector)
    assert fn(marked) == fn(SCENE_ADVERSARIAL)


@pytest.mark.parametrize('marked', [MARKED, MARKED_AT_OPEN])
def test_dialogue_extraction_ignores_markers(marked):
    from storyforge.prose_analysis import extract_dialogue
    assert extract_dialogue(marked) == extract_dialogue(SCENE_ADVERSARIAL)


def test_a_marker_cannot_mask_a_real_weather_opening():
    """The dangerous direction, which the old test did not cover: _get_opening
    takes the first 80 whitespace-split words, so a marker consumes one and can
    push a weather word out of the window — suppressing a real craft finding."""
    from storyforge.scoring_weather import score_no_weather_dreams

    scene = ' '.join(['word'] * 78) + ' rain sky.\n\nShe waited.\n'
    marked = ill.insert_marker(scene, plan_row(placement='scene_open',
                                              anchor=''))['text']

    baseline = score_no_weather_dreams(scene)
    assert baseline['markers']['nwd-1'] == 1        # the finding is real
    assert score_no_weather_dreams(marked) == baseline


# ============================================================================
# Publish manifest integration — content_html must not move
# ============================================================================

def freshen_chapter_map(project_dir):
    """Map every scene in scenes.csv into a chapter.

    generate_publish_manifest refuses to build against a stale map, and the
    fixture's map covers only some of its scenes.
    """
    ids = []
    with open(os.path.join(project_dir, 'reference', 'scenes.csv')) as f:
        for line in f.read().splitlines()[1:]:
            scene_id = line.split('|')[0].strip()
            if scene_id:
                ids.append(scene_id)
    write_csv(project_dir, 'chapter-map.csv',
              'chapter|title|heading|part|scenes',
              [f'1|Chapter One|numbered-titled|1|{";".join(ids)}'])
    return ids


def give_project_a_cover(project_dir):
    """Put a publishable cover on disk.

    Required, not incidental: a manifest that declares assets without a
    `role: 'cover'` entry is refused, because Bookshelf would read it as "this
    book has no cover" and clear the live one. A small JPEG so the cover
    optimizer returns it untouched and the manifest build stays subprocess-free.
    """
    cover = os.path.join(project_dir, 'production', 'cover.jpg')
    if not os.path.isfile(cover):
        make_jpeg(cover, 800, 1200)
    return cover


def build_manifest(project_dir):
    from storyforge.assembly import generate_publish_manifest
    freshen_chapter_map(project_dir)
    give_project_a_cover(project_dir)
    path = generate_publish_manifest(project_dir, include_dashboard=False)
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def illustrated_project(project_dir):
    """The fixture project with one scene illustrated and ingested."""
    scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(scene_path) as f:
        original = f.read()

    row = plan_row(scene_id='act1-sc01', anchor='brass calipers',
                   status='ingested', sha256='a' * 64, width='40', height='60',
                   asset_file=ill.default_asset_rel('lantern-vigil'))
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 40, 60)
    ill.write_plan(project_dir, [row])

    result = ill.insert_marker(original, row)
    assert result['changed'], result['error']
    with open(scene_path, 'w') as f:
        f.write(result['text'])
    return project_dir


@pytest.mark.parametrize('placement,anchor', [
    ('after_anchor', 'brass calipers'),
    ('before_anchor', 'brass calipers'),
    ('scene_open', ''),
    ('scene_close', ''),
])
def test_manifest_content_html_is_unchanged_by_illustrations(project_dir,
                                                             placement, anchor):
    """The regression test for the whole design.

    Bookshelf derives highlight offsets from the scene's visible text. If an
    illustration changed content_html, every downstream highlight in that scene
    would silently re-anchor or orphan.

    Parametrized over all four placements: covering only after_anchor is how the
    scene_open frontmatter bug hid — it left content_html matching (pandoc eats a
    leading `---…---` as metadata) while leaking the whole YAML block into the
    epub and inflating word_count by 21.
    """
    before = build_manifest(project_dir)

    scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(scene_path) as f:
        original = f.read()
    row = plan_row(scene_id='act1-sc01', anchor=anchor, placement=placement,
                   status='ingested', sha256='a' * 64,
                   asset_file=ill.default_asset_rel('lantern-vigil'))
    ill.write_plan(project_dir, [row])
    result = ill.insert_marker(original, row)
    # Tripwire: without this the anchor could drift on a fixture edit, both
    # builds would be illustration-free, and the most important invariant in
    # the PR would be green forever while unguarded.
    assert result['changed'], result['error']
    with open(scene_path, 'w') as f:
        f.write(result['text'])

    after = build_manifest(project_dir)

    def scene_of(manifest):
        return next(s for ch in manifest['chapters'] for s in ch['scenes']
                    if s['slug'] == 'act1-sc01')

    # The placement really did land in this build, so the comparison is real.
    assert scene_of(after)['illustrations']
    assert scene_of(after)['content_html'] == scene_of(before)['content_html']
    assert scene_of(after)['word_count'] == scene_of(before)['word_count']


def test_assembled_chapter_never_leaks_frontmatter(project_dir):
    """content_html matching is not sufficient — the frontmatter leak was
    invisible to it."""
    from storyforge.assembly import assemble_chapter

    scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(scene_path) as f:
        original = f.read()
    assert 'drafted_at' in original          # the fixture has frontmatter
    row = plan_row(scene_id='act1-sc01', placement='scene_open', anchor='',
                   status='ingested', sha256='a' * 64,
                   asset_file=ill.default_asset_rel('lantern-vigil'))
    ill.write_plan(project_dir, [row])
    with open(scene_path, 'w') as f:
        f.write(ill.insert_marker(original, row)['text'])

    assert 'drafted_at' not in assemble_chapter(1, project_dir)


def test_manifest_carries_placements_and_assets(illustrated_project):
    manifest = build_manifest(illustrated_project)
    scene = next(s for ch in manifest['chapters'] for s in ch['scenes']
                 if s['slug'] == 'act1-sc01')

    assert scene['illustrations'] == [
        {'key': 'lantern-vigil', 'after_paragraph': 1}]
    assert '![[illus:' not in scene['content_html']
    illustrations = [a for a in manifest['assets']
                     if a['role'] == 'illustration']
    assert illustrations == [{
        'key': 'lantern-vigil', 'role': 'illustration',
        'sha256': 'a' * 64, 'extension': 'png',
        'width': 40, 'height': 60,
        'alt_text': 'A woman waits at a lit window',
    }]
    # The cover rides the same array. Without it the manifest would be refused.
    assert manifest['assets'][0]['role'] == 'cover'


def test_manifest_refuses_illustrations_with_no_cover(illustrated_project):
    """Assets with no cover asset would null out the live book's cover."""
    from storyforge.assembly import generate_publish_manifest
    freshen_chapter_map(illustrated_project)
    with pytest.raises(ValueError, match='none with role "cover"'):
        generate_publish_manifest(illustrated_project, include_dashboard=False)


def test_manifest_omits_assets_when_no_scene_is_illustrated(project_dir):
    manifest = build_manifest(project_dir)
    assert [a['role'] for a in manifest['assets']] == ['cover']
    assert all('illustrations' not in s
               for ch in manifest['chapters'] for s in ch['scenes'])


def test_manifest_drops_a_placement_with_no_publishable_asset(project_dir,
                                                              capsys):
    """A placement referencing an asset the manifest doesn't declare is a
    dangling reference handed to the reader app. A self-consistent manifest
    missing an illustration is strictly better than an inconsistent one."""
    scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(scene_path) as f:
        original = f.read()
    row = plan_row(scene_id='act1-sc01', anchor='brass calipers',
                   status='planned')
    ill.write_plan(project_dir, [row])
    result = ill.insert_marker(original, row)
    assert result['changed'], result['error']
    with open(scene_path, 'w') as f:
        f.write(result['text'])

    manifest = build_manifest(project_dir)

    assert not [a for a in manifest['assets'] if a['role'] == 'illustration']
    # The dangling placement is gone, not merely warned about.
    assert all('illustrations' not in s
               for ch in manifest['chapters'] for s in ch['scenes'])
    out = capsys.readouterr().out
    assert 'dropped 1 illustration placement' in out
    # And the cause is named, not left for the author to guess.
    assert 'status=planned' in out


def test_manifest_names_a_missing_digest_as_the_cause(project_dir, capsys):
    """An ingested row with no sha256 is fully ingested — the old warning said
    'not ingested', sending the author to look in the wrong place."""
    scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(scene_path) as f:
        original = f.read()
    row = plan_row(scene_id='act1-sc01', anchor='brass calipers',
                   status='ingested',
                   asset_file=ill.default_asset_rel('lantern-vigil'))
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 8, 8)
    ill.write_plan(project_dir, [row])
    with open(scene_path, 'w') as f:
        f.write(ill.insert_marker(original, row)['text'])

    build_manifest(project_dir)
    assert 'sha256 is missing' in capsys.readouterr().out


# ============================================================================
# Chapter assembly integration
# ============================================================================

def test_assemble_chapter_resolves_markers_to_relative_paths(illustrated_project):
    from storyforge.assembly import assemble_chapter
    chapter = assemble_chapter(1, illustrated_project)
    assert '![[illus:' not in chapter
    assert ('![A woman waits at a lit window]'
            '(manuscript/assets/illustrations/lantern-vigil.png)') in chapter
    # Paths must stay portable — no absolute machine paths in git-tracked output.
    assert illustrated_project not in chapter


def test_assemble_chapter_without_illustrations_is_unchanged(project_dir):
    from storyforge.assembly import assemble_chapter
    chapter = assemble_chapter(1, project_dir)
    assert '![' not in chapter
    assert 'Dorren Hayle' in chapter


# ============================================================================
# --direction
# ============================================================================

#: The book-level canon ids --direction writes, mirroring pi.CANON_PLAN
#: without importing it — a divergence between the two would be a bug worth
#: a loud test failure, not a silently-shared constant.
_BOOK_LEVEL_CANON_IDS = ('visual-foundation', 'visual-vocabulary',
                        'content-limits')


def test_direction_strict_writes_a_template_without_an_api_key(in_project):
    from storyforge import canon
    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0

    for canon_id in _BOOK_LEVEL_CANON_IDS:
        path = canon.resolve_canon_path(in_project, canon_id)
        assert path is not None, canon_id
        with open(path) as f:
            content = f.read()
        assert 'TODO —' in content
        # A strict scaffold proposes nothing, so the block stays placeholder.
        assert not canon.is_canon_block_populated(in_project, canon_id)
        # Both coaching levels emit 'TODO —'; only coach adds the question
        # framing, so this is the one assertion that actually distinguishes
        # strict's template from coach's.
        assert 'What would you say here' not in content


def test_direction_coach_template_asks_questions(in_project):
    from storyforge import canon
    assert cmd_illustrate.main(['--direction', '--coaching', 'coach']) == 0

    path = canon.resolve_canon_path(in_project, 'visual-vocabulary')
    with open(path) as f:
        content = f.read()
    assert 'What would you say here' in content
    assert not canon.is_canon_block_populated(in_project, 'visual-vocabulary')


def test_direction_template_stubs_an_anchor_per_registry_entry(in_project):
    from storyforge import canon
    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0

    # The fixture has characters and locations; both need anchors, filed by
    # the registry's own id rather than a re-slugified display name.
    path = canon.resolve_canon_path(in_project, 'dorren-hayle')
    assert path is not None
    assert path.endswith(os.path.join('characters', 'dorren-hayle.md'))
    with open(path) as f:
        content = f.read()
    assert 'canon_type: character' in content
    assert 'height, age, exact colors' in content

    loc_path = canon.resolve_canon_path(in_project, 'cartography-office')
    assert loc_path is not None
    assert loc_path.endswith(os.path.join('locations', 'cartography-office.md'))


def test_anchor_candidates_warns_on_a_registry_row_with_no_id(
        in_project, capsys):
    """A registry row missing its own id can't back a canon filename (the
    filename must equal the registry id), so it's dropped as a candidate —
    but silently is the wrong failure mode for a row an author forgot to
    finish; assert the drop is logged."""
    write_csv(in_project, 'characters.csv', 'id|name', ['|Nameless'])

    candidates = cmd_illustrate._anchor_candidates(in_project)

    assert 'Nameless' not in [name for _cid, _ct, name in candidates]
    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'characters.csv' in out


def test_direction_full_without_an_api_key_fails(in_project, capsys):
    assert cmd_illustrate.main(['--direction', '--coaching', 'full']) == 1
    out = capsys.readouterr().out
    assert 'ANTHROPIC_API_KEY is not set' in out
    assert '--coaching coach' in out       # names the offline alternative


def test_direction_full_writes_the_model_output(in_project, monkeypatch, capsys):
    from storyforge import canon
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '## visual-foundation\n\nFull-color photorealism for ages 6-8.\n\n'
        '## visual-vocabulary\n\nWarm amber against cool blue.\n\n'
        '## content-limits\n\nNever horror imagery.\n'
    ))

    assert cmd_illustrate.main(['--direction', '--coaching', 'full']) == 0

    def block(canon_id):
        return canon.embeddable_block_text(
            canon.resolve_canon_path(in_project, canon_id)).strip()

    assert block('visual-foundation') == 'Full-color photorealism for ages 6-8.'
    assert block('visual-vocabulary') == 'Warm amber against cool blue.'
    assert block('content-limits') == 'Never horror imagery.'
    for canon_id in _BOOK_LEVEL_CANON_IDS:
        assert canon.is_canon_block_populated(in_project, canon_id)
    out = capsys.readouterr().out
    assert 'Read the canon files before running --prompts' in out


def test_direction_reports_incomplete_sections(in_project, monkeypatch, capsys):
    from storyforge import canon
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k:
                        '## visual-foundation\n\nPhotorealism.\n')

    cmd_illustrate.main(['--direction', '--coaching', 'full'])
    out = capsys.readouterr().out
    assert 'needs your input' in out
    # The one filled block must not itself be reported as incomplete.
    needs_line = next(l for l in out.splitlines() if 'needs your input' in l)
    assert 'visual-vocabulary' in needs_line
    assert 'content-limits' in needs_line
    assert 'visual-foundation' not in needs_line
    assert canon.is_canon_block_populated(in_project, 'visual-foundation')


def _write_book_level_canon(project_dir, canon_id, canon_type, body):
    path = os.path.join(project_dir, 'reference', 'canon', f'{canon_id}.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            '---\n'
            f'canon_id: {canon_id}\n'
            f'canon_type: {canon_type}\n'
            'canon_updated: 2026-07-28\n'
            'appears_in:\n'
            'first_appearance:\n'
            '---\n\n'
            '## Embeddable block\n\n'
            f'{body}\n\n'
            '## Clauses\n\n## Related canon\n\n## Iteration history\n'
        )
    return path


def test_direction_skips_a_canon_file_that_already_exists(in_project, capsys):
    """Analogue of the old 'does not clobber a complete document' test: a
    canon file the author (or an earlier run) already wrote is left
    untouched and reported by name — at info level, not WARNING, since this
    is the ordinary steady state on every run after the first. (The
    WARNING-worthy variants — a malformed file at the candidate path, and
    an id claimed by a *different* path than expected — are covered by
    test_direction_never_touches_a_malformed_file_at_the_candidate_path in
    test_illustration_canon.py and
    test_direction_warns_when_an_existing_id_is_at_a_different_path below.)
    The command still proceeds to write whatever else is missing."""
    from storyforge import canon
    path = _write_book_level_canon(
        in_project, 'visual-foundation', 'foundation',
        'Cinematic photorealistic storybook art.')

    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0

    with open(path) as f:
        assert 'Cinematic photorealistic storybook art.' in f.read()
    out = capsys.readouterr().out
    assert 'visual-foundation.md already exists' in out
    assert 'WARNING' not in out
    # The rest still get written.
    assert canon.resolve_canon_path(in_project, 'visual-vocabulary') is not None
    assert canon.resolve_canon_path(in_project, 'content-limits') is not None


def test_direction_warns_when_an_existing_id_is_at_a_different_path(
        in_project, capsys):
    """The other branch of the existing_ids check: canon_id_index finds
    'dorren-hayle' declared in a file that is NOT where --direction would
    write it. Unlike the plain steady-state skip above, this is a real
    problem — two paths could both claim to be the canonical file for this
    id — so it stays a WARNING, and no second file gets written for it."""
    path = os.path.join(in_project, 'reference', 'canon', 'characters',
                        'dorren-hayle-renamed.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            '---\ncanon_id: dorren-hayle\ncanon_type: character\n'
            'canon_updated: 2026-07-28\nappears_in:\nfirst_appearance:\n'
            '---\n\n## Embeddable block\n\nSomething.\n\n'
            '## Clauses\n\n## Related canon\n\n## Iteration history\n'
        )

    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0

    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'dorren-hayle' in out
    assert not os.path.isfile(os.path.join(
        in_project, 'reference', 'canon', 'characters', 'dorren-hayle.md'))


def test_direction_reports_a_preexisting_placeholder_as_needing_input(
        in_project, capsys):
    """Restores the property the old test_direction_reports_gaps_in_an_
    existing_document covered for the single-document format: a canon file
    that already exists but was never filled in — the steady state after an
    earlier --direction run — must still show up in 'needs your input' on a
    later run, even though it is skipped rather than rewritten. Before this
    fix, needs_input was computed only over files THIS run wrote, so a
    second strict run over an all-placeholder reference tier silently
    reported nothing — 'Every canon file already exists... Edit them
    directly' read as an all-clear over pure TODO scaffolding."""
    from storyforge import canon
    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0
    capsys.readouterr()  # discard the first run's output

    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0
    out = capsys.readouterr().out

    assert 'needs your input' in out
    needs_line = next(l for l in out.splitlines() if 'needs your input' in l)
    for canon_id in _BOOK_LEVEL_CANON_IDS:
        assert canon_id in needs_line
    assert not canon.is_canon_block_populated(in_project, 'visual-foundation')
    # A real gap must not be masked by the "nothing to do" all-clear.
    assert 'Every canon file already exists' not in out


def test_direction_reports_gaps_across_canon_files(in_project, capsys):
    """One book-level file already has real content; the rest remain
    placeholder templates and get reported as needing the author."""
    _write_book_level_canon(
        in_project, 'visual-foundation', 'foundation',
        'Cinematic photorealistic storybook art.')

    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0
    out = capsys.readouterr().out
    needs_line = next(l for l in out.splitlines() if 'needs your input' in l)
    assert 'visual-vocabulary' in needs_line
    assert 'content-limits' in needs_line
    assert 'visual-foundation' not in needs_line


def test_direction_dry_run_writes_nothing(in_project, capsys):
    assert cmd_illustrate.main(['--direction', '--dry-run',
                                '--coaching', 'strict']) == 0
    assert '[dry-run] would write' in capsys.readouterr().out
    assert not os.path.isdir(os.path.join(in_project, 'reference', 'canon'))


def _write_entity_canon(project_dir, subdir, canon_id, anchor_text,
                        canon_type=None, canon_updated='2026-07-28',
                        display_name=None):
    """Minimal entity canon file for prompt-anchor tests. Anchors now come
    from reference/canon/, not the direction document's Continuity anchors
    section (task 4) — this is the canon-side equivalent of write_direction's
    old anchor headings.

    `canon_updated` is settable because it is the cutoff the reference chain
    compares ingest dates against; `display_name` because it is the first
    authority for an anchor's rendered label.
    """
    canon_type = canon_type or {
        'characters': 'character', 'locations': 'location',
        'motifs': 'motif',
    }[subdir]
    path = os.path.join(project_dir, 'reference', 'canon', subdir,
                        f'{canon_id}.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            '---\n'
            f'canon_id: {canon_id}\n'
            f'canon_type: {canon_type}\n'
            f'canon_updated: {canon_updated}\n'
            + (f'display_name: {display_name}\n' if display_name else '')
            + 'appears_in: vigil\n'
            'first_appearance: vigil\n'
            '---\n\n'
            '## Embeddable block\n\n'
            f'{anchor_text}\n\n'
            '## Clauses\n\n## Related canon\n\n## Iteration history\n'
        )
    return path


def _write_book_level_canon(project_dir, canon_id, canon_type, body):
    """One of the three CANON_PLAN book-level canon files (visual-foundation,
    visual-vocabulary, content-limits). This is the canon-side equivalent of
    the old direction document's non-anchor sections."""
    path = os.path.join(project_dir, 'reference', 'canon', f'{canon_id}.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            '---\n'
            f'canon_id: {canon_id}\n'
            f'canon_type: {canon_type}\n'
            'canon_updated: 2026-07-28\n'
            'appears_in:\n'
            'first_appearance:\n'
            '---\n\n'
            '## Embeddable block\n\n'
            f'{body}\n\n'
            '## Clauses\n\n## Related canon\n\n## Iteration history\n'
        )
    return path


def test_reference_tier_reaches_the_art_direction_prompt(in_project,
                                                         monkeypatch):
    """The whole point of the reference tier: every prompt carries it."""
    _write_book_level_canon(
        in_project, 'visual-foundation', 'foundation',
        'Full-color, cinematic photorealistic storybook imagery.')
    _write_book_level_canon(
        in_project, 'content-limits', 'rules',
        'Never horror imagery. No blood or gore.')
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'characters', 'leo',
                        'Ten years old; tall and lean for his age.')
    ill.write_plan(in_project, [plan_row(canon_refs='leo')])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    seen = {}

    def capture(project_dir, prompt, operation, **kwargs):
        seen['prompt'] = prompt
        return '### Scene\n\nA street.\n'

    monkeypatch.setattr(cmd_illustrate, '_invoke', capture)
    cmd_illustrate.main(['--prompts', '--coaching', 'full'])

    prompt = seen['prompt']
    assert 'Book-level art direction' in prompt
    assert 'cinematic photorealistic' in prompt
    assert 'Never horror imagery' in prompt
    # Anchors come from canon, rendered separately from the rest of the
    # book-level direction.
    assert 'Ten years old' in prompt


def test_prompts_narrow_anchors_to_what_the_illustration_shows(in_project,
                                                              monkeypatch):
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'characters', 'leo',
                        'Ten years old; tall and lean for his age.')
    _write_entity_canon(in_project, 'motifs', 'murkwolves',
                        'Large wolf-shaped concentrations of cold shadow.')
    ill.write_plan(in_project, [plan_row(canon_refs='murkwolves')])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    seen = {}
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda pd, prompt, op, **kw: (
                            seen.update(prompt=prompt) or '### Scene\n\nX.\n'))
    cmd_illustrate.main(['--prompts', '--coaching', 'full'])

    anchors_block = seen['prompt'].split('## Character anchors')[1]
    # Labeled by display name, not by canon_id (see the anchor-label tests).
    assert '**Murkwolves**' in anchors_block
    assert 'cold shadow' in anchors_block
    assert 'Ten years old' not in anchors_block   # leo is not in this frame


def test_relevant_anchors_falls_back_to_all_when_none_named():
    anchors = {'Leo': 'a boy', 'Nora': 'a girl'}
    assert cmd_illustrate._relevant_anchors(anchors, plan_row()) == anchors


def test_relevant_anchors_falls_back_when_nothing_matches():
    anchors = {'Leo': 'a boy'}
    row = plan_row(canon_refs='Someone Unrecorded')
    assert cmd_illustrate._relevant_anchors(anchors, row) == anchors


def test_relevant_anchors_warns_on_the_unmatched_fallback(capsys):
    """Regression (fix round 1, I-2): anchor keys became canon_ids (task 4),
    so a plan row still carrying a pre-canon display name in canon_refs
    (e.g. a leftover "The village and Great Lamp") matches nothing and used
    to fall back to the full cast with no sign anything was wrong — token
    cost, plus the model invited to include off-frame characters. The
    fallback must log a WARNING naming the unmatched canon_refs value."""
    anchors = {'Leo': 'a boy'}
    row = plan_row(canon_refs='The village and Great Lamp')
    assert cmd_illustrate._relevant_anchors(anchors, row) == anchors
    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'the village and great lamp' in out


def test_relevant_anchors_no_warning_when_canon_refs_is_simply_empty(capsys):
    """The fallback is unremarkable when the row named nothing at all — only
    a named-but-unmatched canon_refs value is the sign something drifted."""
    anchors = {'Leo': 'a boy', 'Nora': 'a girl'}
    cmd_illustrate._relevant_anchors(anchors, plan_row())
    assert 'WARNING' not in capsys.readouterr().out


# ============================================================================
# --review
# ============================================================================

def test_review_writes_the_sequence_checklist(in_project):
    _write_book_level_canon(
        in_project, 'content-limits', 'rules',
        'Never horror imagery. No blood or gore.')
    _write_entity_canon(in_project, 'characters', 'leo',
                        'Ten years old; tall and lean for his age.')
    _write_entity_canon(in_project, 'motifs', 'murkwolves',
                        'Large wolf-shaped concentrations of cold shadow.')
    write_csv(in_project, 'chapter-map.csv', 'chapter|scenes', ['1|s1;s2'])
    ill.write_plan(in_project, [
        plan_row(id='LF-01', scene_id='s1', canon_refs='Leo;Murkwolves',
                 status='ingested'),
        plan_row(id='LF-02', scene_id='s2', status='planned'),
    ])

    assert cmd_illustrate.main(['--review']) == 0

    path = os.path.join(in_project, 'working',
                        'illustration-sequence-review.md')
    with open(path) as f:
        content = f.read()
    assert '1 of 2 illustrations rendered' in content
    assert '**Identity**' in content
    assert '**Light progression**' in content
    assert 'Never horror imagery' in content       # content limits carried over
    assert '- [ ] **leo**' in content              # anchors to check against
    assert '1. [x] `LF-01`' in content             # rendered
    assert '2. [ ] `LF-02`' in content             # pending
    assert 'locks: Leo, Murkwolves' in content     # locks read canon_refs verbatim


def test_review_marks_the_visual_key(in_project):
    write_csv(in_project, 'chapter-map.csv', 'chapter|scenes', ['1|s1;s2'])
    ill.write_plan(in_project, [
        plan_row(id='LF-01', scene_id='s1', canon_refs='Nora'),
        plan_row(id='LF-02', scene_id='s2', canon_refs='Leo;Nora;Oak'),
    ])
    cmd_illustrate.main(['--review'])
    with open(os.path.join(in_project, 'working',
                           'illustration-sequence-review.md')) as f:
        assert '`LF-02` — **visual key**' in f.read()


def test_review_without_a_plan_fails(in_project, capsys):
    assert cmd_illustrate.main(['--review']) == 1
    assert 'No illustration plan to review' in capsys.readouterr().out


def test_review_dry_run_writes_nothing(in_project, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    assert cmd_illustrate.main(['--review', '--dry-run']) == 0
    assert '[dry-run] would write' in capsys.readouterr().out
    assert not os.path.isfile(os.path.join(
        in_project, 'working', 'illustration-sequence-review.md'))


def test_review_prompts_early_review_while_renders_remain(in_project, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    cmd_illustrate.main(['--review'])
    assert 'cheap moment' in capsys.readouterr().out


# ============================================================================
# --diagnose render order
# ============================================================================

def test_diagnose_prints_the_render_order_and_visual_key(in_project, capsys):
    write_scene(in_project, 's1', SCENE)
    write_scene(in_project, 's2', SCENE)
    write_csv(in_project, 'chapter-map.csv', 'chapter|scenes', ['1|s1;s2'])
    ill.write_plan(in_project, [
        plan_row(id='LF-01', scene_id='s1', canon_refs='Nora', anchor=''),
        plan_row(id='LF-02', scene_id='s2', canon_refs='Leo;Nora;Oak',
                 anchor=''),
    ])

    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Recommended render order' in out
    assert '<- visual key' in out
    assert 'locks: Leo, Nora, Oak' in out
    assert 'next to render: LF-02' in out


# ============================================================================
# Layout
# ============================================================================

@pytest.mark.parametrize('layout,aspect', [
    ('double_page', 'landscape'),
    ('full_page', 'portrait'),
    ('half_page', 'portrait'),
    ('', 'portrait'),
])
def test_layout_drives_aspect(layout, aspect):
    assert pi.aspect_for_row(plan_row(layout=layout)) == aspect


def test_layout_beats_a_conflicting_composition_note():
    """A double-page spread is wider than tall whatever the note says."""
    row = plan_row(layout='double_page', composition='a tight square crop')
    assert pi.aspect_for_row(row) == 'landscape'


def test_layout_appears_in_the_prompt_file():
    content = pi.render_prompt_file(
        split=scene_split(), row=plan_row(layout='double_page'), body='### Scene\n\nA street.\n',
        references=[], aspect=pi.aspect_for_row(plan_row(layout='double_page')),
    )
    assert 'LANDSCAPE orientation' in content


def test_layout_reaches_the_art_direction_prompt():
    prompt = pi.build_art_direction_request(
        split=scene_split(), row=plan_row(layout='double_page'),
        character_anchors={}, canon_context='x',
    )
    assert 'double_page' in prompt


def test_schema_accepts_the_layout_column(project_dir):
    from storyforge.schema import validate_illustration_plan
    write_scene(project_dir, 'vigil', ill.insert_marker(SCENE, plan_row())['text'])
    ill.write_plan(project_dir, [plan_row(layout='full_page', status='planned')])

    result = validate_illustration_plan(project_dir)
    assert result['errors'] == []


def test_cleanup_reports_an_invalid_layout(project_dir):
    from storyforge.cmd_cleanup import _check_illustrations
    write_scene(project_dir, 'vigil', SCENE)
    ill.write_plan(project_dir, [plan_row(layout='quarter_page',
                                         status='planned')])
    findings = {f['type']: f for f in _check_illustrations(project_dir)}
    assert 'illus_invalid_layout' in findings
    assert 'full_page' in findings['illus_invalid_layout']['action']


# ============================================================================
# Exit-code propagation and partial-failure semantics
# ============================================================================

def run_cli(project_dir, *args):
    """Invoke the real CLI entry point, returning (exit_code, output)."""
    import subprocess
    env = dict(os.environ)
    env['PYTHONPATH'] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'scripts', 'lib', 'python')
    env.pop('ANTHROPIC_API_KEY', None)
    env.pop('STORYFORGE_COACHING', None)
    proc = subprocess.run(
        ['python3', '-m', 'storyforge', 'illustrate', *args],
        cwd=project_dir, env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def test_a_nonzero_return_reaches_the_shell(project_dir):
    """Regression: the dispatcher discarded main()'s return, so every error
    path in this command exited 0 — the GN guard, the missing-API-key errors,
    and --diagnose's findings signal all reported success."""
    code, out = run_cli(project_dir, '--ingest', '/nonexistent/path')
    assert code == 1
    assert 'no image files found' in out


def test_no_phase_flag_exits_nonzero_through_the_cli(project_dir):
    code, out = run_cli(project_dir)
    assert code == 1
    assert 'Nothing to do' in out


def test_a_zero_return_still_exits_zero(project_dir):
    code, out = run_cli(project_dir, '--diagnose')
    assert code == 0
    assert 'No illustration plan yet' in out


def test_diagnose_exits_zero_on_warning_only_findings(in_project, capsys):
    """A drifted anchor is documented in-flight state, not a failure."""
    write_scene(in_project, 'vigil', 'Entirely rewritten prose.\n')
    make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR, 'stray.png'),
             8, 8)
    ill.write_plan(in_project, [plan_row(status='planned')])

    assert cmd_illustrate.main(['--diagnose']) == 0
    out = capsys.readouterr().out
    assert '0 blocking' in out
    assert 'WARNING: [anchor_drift]' in out


def test_diagnose_exits_nonzero_on_a_blocking_finding(in_project, capsys):
    write_scene(in_project, 'vigil', 'One.\n\n![[illus:ghost]]\n\nTwo.\n')
    ill.write_plan(in_project, [plan_row(anchor='', status='planned')])
    assert cmd_illustrate.main(['--diagnose']) == 1
    assert 'blocking' in capsys.readouterr().out


def test_prompts_partial_failure_exits_nonzero(in_project, monkeypatch, capsys):
    """2 of 3 succeeding must not report success — the skill commits on zero."""
    for sid in ('s1', 's2', 's3'):
        write_scene(in_project, sid, SCENE)
    ill.write_plan(in_project, [
        plan_row(id='a', scene_id='s1'),
        plan_row(id='b', scene_id='s2'),
        plan_row(id='c', scene_id='s3'),
    ])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    calls = {'n': 0}

    def flaky(*a, **k):
        calls['n'] += 1
        return '' if calls['n'] == 2 else '### Scene\n\nA street.\n'

    monkeypatch.setattr(cmd_illustrate, '_invoke', flaky)

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 1
    out = capsys.readouterr().out
    assert '2 of 3 illustration(s) completed' in out
    assert 'before committing' in out


def test_embed_partial_failure_exits_nonzero(in_project, capsys):
    write_scene(in_project, 'good', SCENE)
    write_scene(in_project, 'drifted', 'Entirely different prose.\n')
    ill.write_plan(in_project, [
        plan_row(id='a', scene_id='good'),
        plan_row(id='b', scene_id='drifted'),
    ])

    assert cmd_illustrate.main(['--embed']) == 1
    assert 'will not appear in the book' in capsys.readouterr().out


def test_ingest_propagates_an_embed_failure(in_project, tmp_path, capsys):
    """Ingest used to discard run_embed's return, so a drifted anchor during
    ingest reported success while --embed alone reported failure."""
    write_scene(in_project, 'vigil', 'Entirely rewritten prose.\n')
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    make_png(str(renders / 'lantern-vigil.png'), 8, 8)

    assert cmd_illustrate.main(['--ingest', str(renders)]) == 1
    out = capsys.readouterr().out
    assert 'Ingested 1 illustration' in out
    assert 'anchor not found' in out


def test_ingest_exits_nonzero_when_every_file_is_rejected(in_project, tmp_path,
                                                         capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    renders = tmp_path / 'renders'
    renders.mkdir()
    (renders / 'lantern-vigil.png').write_bytes(b'')

    assert cmd_illustrate.main(['--ingest', str(renders)]) == 1
    assert 'Ingested 0 illustration' in capsys.readouterr().out


def test_ingest_only_embeds_what_it_actually_ingested(in_project, tmp_path):
    """A rejected file has no art for a marker to point at."""
    write_scene(in_project, 'good', SCENE)
    write_scene(in_project, 'bad', SCENE)
    ill.write_plan(in_project, [
        plan_row(id='good-one', scene_id='good'),
        plan_row(id='bad-one', scene_id='bad'),
    ])
    renders = tmp_path / 'renders'
    make_png(str(renders / 'good-one.png'), 8, 8)
    renders.joinpath('bad-one.png').write_bytes(b'not an image')

    cmd_illustrate.main(['--ingest', str(renders)])

    with open(os.path.join(in_project, 'scenes', 'good.md')) as f:
        assert ill.marker_ids(f.read()) == ['good-one']
    with open(os.path.join(in_project, 'scenes', 'bad.md')) as f:
        assert ill.marker_ids(f.read()) == []


def test_ingest_refuses_a_truncated_render_and_preserves_the_good_one(
        in_project, tmp_path, capsys):
    """Regression (cover class, commit 33487b7): a header-valid stub — what an
    aborted download leaves — overwrote a good render, recorded its digest, and
    exited 0. The previous file is not recoverable once replaced."""
    write_scene(in_project, 'vigil', SCENE)
    good = make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR,
                                'lantern-vigil.png'), 800, 1200)
    good_bytes = open(good, 'rb').read()
    good_digest = ill.sha256_of(good)
    ill.write_plan(in_project, [plan_row(
        status='ingested', sha256=good_digest,
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])

    renders = tmp_path / 'renders'
    truncated_png(str(renders / 'lantern-vigil.png'), 800, 1200)

    assert cmd_illustrate.main(['--ingest', str(renders)]) == 1

    assert open(good, 'rb').read() == good_bytes
    assert read_plan_map(in_project)['lantern-vigil']['sha256'] == good_digest
    out = capsys.readouterr().out
    assert 'truncated' in out
    assert 'existing render is untouched' in out


def test_ingest_logs_a_replacement(in_project, tmp_path, capsys):
    """Re-rendering is the normal loop, but it must never be silent."""
    write_scene(in_project, 'vigil', SCENE)
    make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR,
                          'lantern-vigil.png'), 800, 1200)
    ill.write_plan(in_project, [plan_row(
        status='ingested', sha256='a' * 64,
        asset_file=ill.default_asset_rel('lantern-vigil'),
    )])
    renders = tmp_path / 'renders'
    make_png(str(renders / 'lantern-vigil.png'), 100, 150)

    cmd_illustrate.main(['--ingest', str(renders)])
    out = capsys.readouterr().out
    assert 'replacing lantern-vigil' in out
    assert '800×1200' in out and '100×150' in out


def test_ingest_of_a_file_already_in_place(in_project):
    """Rendering straight into the canonical directory must not raise."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    dest = make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR,
                                'lantern-vigil.png'), 40, 60)

    assert cmd_illustrate.main(['--ingest', dest]) == 0
    row = read_plan_map(in_project)['lantern-vigil']
    assert row['status'] == 'ingested'
    assert row['sha256'] == ill.sha256_of(dest)


def test_update_row_warns_when_the_id_is_gone(in_project, capsys):
    """Reachable when the plan is edited mid-run: the file lands on disk while
    the status update evaporates."""
    ill.write_plan(in_project, [plan_row()])
    assert cmd_illustrate._update_row(in_project, 'not-in-plan',
                                     {'status': 'prompted'}) is False
    assert 'no longer in the illustration plan' in capsys.readouterr().out


def test_update_row_updates_a_middle_row(in_project):
    ill.write_plan(in_project, [plan_row(id='a'), plan_row(id='b'),
                                plan_row(id='c')])
    assert cmd_illustrate._update_row(in_project, 'b',
                                     {'status': 'prompted'}) is True
    plan = read_plan_map(in_project)
    assert plan['b']['status'] == 'prompted'
    assert plan['a']['status'] == 'planned'
    assert plan['c']['status'] == 'planned'


def test_prompts_does_not_destroy_author_columns(in_project):
    """A --prompts run rewrites the plan once per illustration."""
    path = ill.plan_path(in_project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('|'.join(ill.PLAN_COLUMNS + ['author_note']) + '\n')
        f.write('lantern-vigil|vigil|She set it on the sill|after_anchor'
                + '|' * (len(ill.PLAN_COLUMNS) - 4) + '|keep me\n')
    write_scene(in_project, 'vigil', SCENE)

    cmd_illustrate.main(['--prompts', '--coaching', 'strict'])

    row = read_plan_map(in_project)['lantern-vigil']
    assert row['status'] == 'prompted'
    assert row['author_note'] == 'keep me'


# ============================================================================
# Anchor parsing and the direction document
# ============================================================================

@pytest.mark.parametrize('line,expected', [
    ('- Jean-Luc — a boy of 9, 130 cm',
     {'Jean-Luc': ('', 'a boy of 9, 130 cm')}),
    ('- Marie-Claire – a woman of 40', {'Marie-Claire': ('', 'a woman of 40')}),
    ('- Ember: an elderly Lantern woman',
     {'Ember': ('', 'an elderly Lantern woman')}),
    ('- Leo - ten years old', {'Leo': ('', 'ten years old')}),
    ('- **Wick** — a copper-haired Lantern child',
     {'Wick': ('', 'a copper-haired Lantern child')}),
    ('- Jean-Luc | character — a boy of 9, 130 cm',
     {'Jean-Luc': ('character', 'a boy of 9, 130 cm')}),
])
def test_anchor_lines_with_hyphenated_names_parse_whole(line, expected):
    """Regression: the separator class included a bare hyphen, so `Jean-Luc`
    became {'Jean': 'Luc — …'}. The mangled name was then written into the
    direction document as canonical, never revised, and stopped matching
    canon_refs — so the anchor silently left every prompt. The added
    `| type` group (task 4) must not reopen that hole."""
    _, anchors = pi.split_anchor_block(f'### Scene\n\nA room.\n\nANCHORS\n{line}\n')
    assert anchors == expected


@pytest.mark.parametrize('marker', ['ANCHORS', 'ANCHORS:', '**ANCHORS**'])
def test_anchor_block_marker_variants(marker):
    """A decorated marker used to lose every anchor AND leave the block in the
    prompt body, which the author pastes into the image model."""
    body, anchors = pi.split_anchor_block(
        f'### Scene\n\nA room.\n\n{marker}\n- Wick — a grey tabby\n')
    assert anchors == {'Wick': ('', 'a grey tabby')}
    assert 'ANCHORS' not in body


def test_split_anchor_block_removes_a_dangling_code_fence():
    """The request demonstrates the block inside a fence, so the model emits
    one; cutting at the ANCHORS line left the opening fence behind and
    corrupted every following section of the prompt file."""
    body, anchors = pi.split_anchor_block(
        '### Scene\n\nA dark room.\n\n```\nANCHORS\n- Wick — a cat\n```\n')
    assert anchors == {'Wick': ('', 'a cat')}
    assert '```' not in body
    assert body.endswith('A dark room.')


def test_unparsed_anchor_lines_are_reported():
    body_text = ('### Scene\n\nA room.\n\nANCHORS\n'
                 '- Wick — a grey tabby\n'
                 '- just a name with no description\n'
                 '- Nameless — \n')
    assert pi.split_anchor_block(body_text)[1] == {'Wick': ('', 'a grey tabby')}
    # Lines are reported verbatim, bullet included, so the author can find them.
    unparsed = pi.unparsed_anchor_lines(body_text)
    assert len(unparsed) == 2
    assert any('just a name with no description' in line for line in unparsed)
    assert any('Nameless' in line for line in unparsed)


def test_prompts_warns_about_mangled_anchor_lines(in_project, monkeypatch,
                                                  capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '### Scene\n\nA room.\n\nANCHORS\n- no separator here at all\n'))

    cmd_illustrate.main(['--prompts', '--coaching', 'full'])
    out = capsys.readouterr().out
    assert 'did not parse as' in out
    # Regression (fix round 1, M-4): the message quoted the pre-task-4 format
    # after the request text had already moved to "Name | type — description".
    assert 'Name | type — description' in out


def test_find_section_is_case_insensitive():
    sections = {'Continuity Anchors': 'a', 'Format': 'b'}
    assert ill.find_section(sections, 'continuity anchors') == \
        'Continuity Anchors'
    assert ill.find_section(sections, 'Nope') is None


# ============================================================================
# --ids re-prompt, and truncated responses
# ============================================================================

def test_ids_can_reprompt_an_already_prompted_illustration(in_project,
                                                           monkeypatch):
    """Regression: the status filter ran before the id filter, so an
    already-prompted row was unreachable and the hint advised the exact flag
    that had just been used."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(
        status='prompted', prompt_file=ill.default_prompt_rel('lantern-vigil'))])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '### Scene\n\nA revised room.\n')

    assert cmd_illustrate.main(
        ['--prompts', '--ids', 'lantern-vigil', '--coaching', 'full']) == 0

    rel = read_plan_map(in_project)['lantern-vigil']['prompt_file']
    with open(os.path.join(in_project, rel)) as f:
        assert 'A revised room' in f.read()


def test_ids_warns_about_an_unknown_id(in_project, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])

    cmd_illustrate.main(['--prompts', '--ids', 'lantern-vigil,typo',
                         '--coaching', 'strict'])
    assert 'no plan row: typo' in capsys.readouterr().out


def test_ids_matching_nothing_exits_nonzero(in_project, capsys):
    ill.write_plan(in_project, [plan_row()])
    assert cmd_illustrate.main(['--prompts', '--ids', 'nope']) == 1
    assert 'None of the named ids' in capsys.readouterr().out


def test_ids_reaches_a_superseded_row_instead_of_refusing(in_project,
                                                          monkeypatch, capsys):
    """This used to assert the opposite — `--ids` filtered superseded rows out,
    so a named retired row exited 1 with "None of the named ids match". Item 6
    made an explicitly named retired row revive instead (see
    test_prompting_a_superseded_row_revives_it for the transition itself).

    The API key is set deliberately: without it the missing-key guard returns 1
    ahead of everything this test is about, and the old assertion would have
    kept passing for the wrong reason."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(status='superseded')])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '### Scene\n\nX.\n')

    assert cmd_illustrate.main(['--prompts', '--ids', 'lantern-vigil']) == 0
    assert 'None of the named ids' not in capsys.readouterr().out


def test_invoke_discards_a_truncated_response(in_project, monkeypatch, capsys):
    """A prompt cut off at max_tokens loses its Constraints section — the
    orientation directive and the no-text rule."""
    monkeypatch.setattr(cmd_illustrate, 'invoke', lambda *a, **k: {
        'content': [{'type': 'text', 'text': '### Scene\n\nA room.'}],
        'usage': {'input_tokens': 10, 'output_tokens': 2048},
        'stop_reason': 'max_tokens',
    })
    result = cmd_illustrate._invoke(in_project, 'p', 'illustrate-prompt',
                                    task_type='creative', max_tokens=2048)
    assert result == ''
    assert 'cut off at max_tokens' in capsys.readouterr().out


def test_invoke_logs_an_empty_response(in_project, monkeypatch, capsys):
    monkeypatch.setattr(cmd_illustrate, 'invoke', lambda *a, **k: {})
    assert cmd_illustrate._invoke(in_project, 'p', 'op',
                                  task_type='creative', max_tokens=100) == ''
    assert 'empty response' in capsys.readouterr().out


def test_invoke_logs_an_error_response_without_billing_it(in_project,
                                                          monkeypatch, capsys):
    monkeypatch.setattr(cmd_illustrate, 'invoke', lambda *a, **k: {
        'error': {'type': 'rate_limit_error', 'message': 'slow down'}})
    assert cmd_illustrate._invoke(in_project, 'p', 'op',
                                  task_type='creative', max_tokens=100) == ''
    out = capsys.readouterr().out
    assert 'rate' in out or 'slow down' in out
    assert 'Not recording a cost entry' in out
    assert not os.path.isfile(
        os.path.join(in_project, 'working', 'costs', 'ledger.csv'))


def test_invoke_records_a_cost_entry_on_success(in_project, monkeypatch):
    monkeypatch.setattr(cmd_illustrate, 'invoke', lambda *a, **k: {
        'content': [{'type': 'text', 'text': 'body'}],
        'usage': {'input_tokens': 100, 'output_tokens': 50},
        'stop_reason': 'end_turn',
    })
    assert cmd_illustrate._invoke(in_project, 'p', 'illustrate-prompt',
                                  task_type='creative', max_tokens=100,
                                  target='lf-01') == 'body'
    ledger = os.path.join(in_project, 'working', 'costs', 'ledger.csv')
    with open(ledger) as f:
        assert 'illustrate-prompt' in f.read()


def test_invoke_returns_empty_on_an_exception(in_project, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError('network is down')

    monkeypatch.setattr(cmd_illustrate, 'invoke', boom)
    assert cmd_illustrate._invoke(in_project, 'p', 'op',
                                  task_type='creative', max_tokens=100) == ''
    assert 'network is down' in capsys.readouterr().out


def test_embed_removes_the_marker_of_a_superseded_row(in_project, capsys):
    """Retiring an illustration must remove its marker, not merely skip the row —
    a marker left behind keeps pointing at art that must not render. This is
    also what gives remove_marker a caller."""
    write_scene(in_project, 'vigil',
                ill.insert_marker(SCENE, plan_row())['text'])
    ill.write_plan(in_project, [plan_row(status='superseded')])

    assert cmd_illustrate.main(['--embed']) == 0

    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        text = f.read()
    assert ill.marker_ids(text) == []
    assert 'She set it on the sill' in text
    assert 'removed superseded marker' in capsys.readouterr().out


def test_embed_dry_run_does_not_remove_a_superseded_marker(in_project, capsys):
    write_scene(in_project, 'vigil',
                ill.insert_marker(SCENE, plan_row())['text'])
    ill.write_plan(in_project, [plan_row(status='superseded')])

    cmd_illustrate.main(['--embed', '--dry-run'])
    assert '[dry-run] would remove' in capsys.readouterr().out
    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        assert ill.marker_ids(f.read()) == ['lantern-vigil']


def test_enrich_word_count_excludes_markers(tmp_path):
    from storyforge.cmd_enrich import _word_count
    plain = tmp_path / 'plain.md'
    plain.write_text(SCENE)
    marked = tmp_path / 'marked.md'
    marked.write_text(ill.insert_marker(SCENE, plan_row())['text'])
    assert _word_count(str(marked)) == _word_count(str(plain))


# ============================================================================
# The reference chain vs. the canon (prompt item 3)
#
# Found on a real 20-illustration book: LF-05's prompt told the author to
# upload LF-01/02/03 as *style* references, all three being pre-canon renders
# whose drift the new canon was written to eliminate. LF-05 is the visual key,
# so everything downstream would have inherited it — and nothing said a word.
# ============================================================================

def _ingested_prior(project_dir, illus_id='earlier', ingested_at=''):
    """An ingested plan row with a real file on disk."""
    make_png(os.path.join(project_dir, ill.ILLUSTRATIONS_SUBDIR,
                          f'{illus_id}.png'), 8, 8)
    return plan_row(id=illus_id, status='ingested',
                    asset_file=ill.default_asset_rel(illus_id),
                    ingested_at=ingested_at)


def test_references_skip_art_ingested_before_the_canon(in_project, capsys):
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    ill.write_plan(in_project, [
        _ingested_prior(in_project, ingested_at='2026-07-01'), plan_row()])

    cutoff = cmd_illustrate._reference_cutoff(in_project, False)
    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil',
                                          canon_cutoff=cutoff)
    assert refs == []
    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'earlier.png' in out
    assert 'ingested 2026-07-01, before the canon was last updated 2026-07-20' in out
    assert '--no-prior-refs' in out


def test_references_skip_art_with_no_ingest_date(in_project, capsys):
    """The state of every row on the real book: the column postdates the plan
    schema, so "unknown" has to mean "predates the canon" or the fix does
    nothing without a migration."""
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    ill.write_plan(in_project, [_ingested_prior(in_project), plan_row()])

    cutoff = cmd_illustrate._reference_cutoff(in_project, False)
    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil',
                                          canon_cutoff=cutoff)
    assert refs == []
    out = capsys.readouterr().out
    assert 'WARNING' in out
    assert 'earlier.png' in out
    assert '`ingested_at` is empty' in out


def test_references_report_an_unparseable_ingest_date(in_project, capsys):
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    ill.write_plan(in_project, [
        _ingested_prior(in_project, ingested_at='last Tuesday'), plan_row()])

    cutoff = cmd_illustrate._reference_cutoff(in_project, False)
    assert cmd_illustrate._references_for(
        in_project, 'lantern-vigil', canon_cutoff=cutoff) == []
    out = capsys.readouterr().out
    assert 'not an ISO date' in out
    assert 'last Tuesday' in out


def test_references_keep_art_ingested_after_the_canon(in_project):
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    ill.write_plan(in_project, [
        _ingested_prior(in_project, ingested_at='2026-07-21'), plan_row()])

    cutoff = cmd_illustrate._reference_cutoff(in_project, False)
    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil',
                                          canon_cutoff=cutoff)
    assert [p for p, _ in refs] == [ill.default_asset_rel('earlier')]


def test_references_keep_art_ingested_the_same_day_as_the_canon(in_project):
    """Same-day is the ordinary incremental loop — write canon, render, ingest,
    prompt the next one — and a date cannot separate the two. Treating it as
    stale would empty the chain on every normal run."""
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    ill.write_plan(in_project, [
        _ingested_prior(in_project, ingested_at='2026-07-20'), plan_row()])

    cutoff = cmd_illustrate._reference_cutoff(in_project, False)
    assert cmd_illustrate._references_for(
        in_project, 'lantern-vigil', canon_cutoff=cutoff) != []


def test_references_are_unchecked_when_no_canon_date_exists(in_project, capsys):
    """No canon means no governing direction, so nothing can predate it.
    Inventing a cutoff here would discard every reference on a book that never
    adopted the canon tier."""
    ill.write_plan(in_project, [_ingested_prior(in_project), plan_row()])

    cutoff = cmd_illustrate._reference_cutoff(in_project, False)
    assert cutoff == ''
    assert 'without a staleness check' in capsys.readouterr().out
    assert cmd_illustrate._references_for(
        in_project, 'lantern-vigil', canon_cutoff=cutoff) != []


def test_no_prior_refs_falls_back_to_cover_only(in_project, capsys):
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 8)
    ill.write_plan(in_project, [
        _ingested_prior(in_project, ingested_at='2999-01-01'), plan_row()])

    cutoff = cmd_illustrate._reference_cutoff(in_project, True)
    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil',
                                          canon_cutoff=cutoff,
                                          no_prior_refs=True)
    assert [p for p, _ in refs] == [
        os.path.join('manuscript', 'assets', 'cover-illustration.png')]
    out = capsys.readouterr().out
    assert '--no-prior-refs' in out
    assert 'cover-only' in out
    assert '1 prior illustration(s) excluded' in out


def test_no_prior_refs_flag_reaches_the_prompt_file(in_project, monkeypatch):
    write_scene(in_project, 'vigil', SCENE)
    make_png(os.path.join(in_project, 'manuscript', 'assets',
                          'cover-illustration.png'), 8, 8)
    ill.write_plan(in_project, [
        _ingested_prior(in_project, ingested_at='2999-01-01'), plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '### Scene\n\nX.\n')

    assert cmd_illustrate.main(['--prompts', '--ids', 'lantern-vigil',
                                '--coaching', 'full', '--no-prior-refs']) == 0
    with open(os.path.join(in_project,
                           ill.default_prompt_rel('lantern-vigil'))) as f:
        content = f.read()
    assert 'cover-illustration.png' in content
    assert 'earlier.png' not in content


def test_an_empty_reference_chain_is_logged(in_project, capsys):
    ill.write_plan(in_project, [plan_row()])
    assert cmd_illustrate._references_for(in_project, 'lantern-vigil') == []
    assert 'no reference images at all' in capsys.readouterr().out


# ============================================================================
# The reference chain vs. the anchor batch (#311)
#
# Observed on the same 20-illustration book: the four images the author
# deliberately rendered and approved as the anchor batch were exactly the ones
# the cap discarded, because selection was a plan-order walk that never asked
# what the batch was. Phase 1 exists so phase 2 references four real images;
# nothing connected the guarantee to the consumer.
# ============================================================================

def _batch(**slots) -> packet.AnchorBatch:
    """An `AnchorBatch` with only the named slots filled.

    Passed in rather than derived, so these tests pin the *selection* — the
    derivation has its own tests in test_packet.py, and driving it from here
    would make a selection failure look like a batch-derivation failure.
    """
    batch: packet.AnchorBatch = {
        'establisher': '', 'darkest': '', 'brightest': '', 'later_state': '',
        'fallback': [], 'guessed': [],
    }
    batch.update(slots)          # type: ignore[typeddict-item]
    return batch


def _priors(project_dir, count, *, ingested_at='2026-07-28'):
    """`count` ingested rows with files on disk, named `prior-0`..., in order."""
    rows = []
    for i in range(count):
        rel = ill.default_asset_rel(f'prior-{i}')
        make_png(os.path.join(project_dir, rel), 8, 8)
        rows.append(plan_row(id=f'prior-{i}', status='ingested',
                             asset_file=rel, ingested_at=ingested_at))
    return rows


def _stems(refs):
    return [os.path.splitext(os.path.basename(p))[0] for p, _label in refs]


def test_a_full_anchor_batch_survives_the_reference_cap(in_project):
    """The bug: the batch ids sit late in plan order, so the cap dropped all
    four of the images phase 1 exists to produce."""
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 8) + [plan_row()])

    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(establisher='prior-7', darkest='prior-6',
                     brightest='prior-5', later_state='prior-4'))

    assert _stems(refs) == ['cover-illustration', 'prior-7', 'prior-6',
                            'prior-5', 'prior-4']


def test_the_cover_is_additive_to_the_prior_reference_cap(in_project):
    """Cover + a full four-slot batch is five, and the cap counts priors only:
    the cap's own justification is about like-for-like illustration references,
    and the cover does a different job (house style, not likeness)."""
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 8) + [plan_row()])

    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil')
    priors = [p for p, _ in refs if 'cover-illustration' not in p]
    assert len(priors) == cmd_illustrate._MAX_PRIOR_REFERENCES
    assert len(refs) == cmd_illustrate._MAX_PRIOR_REFERENCES + 1


def test_non_batch_rows_keep_plan_order_behind_the_batch(in_project):
    """The promotion is a stable sort, so everything else behaves as before."""
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 8) + [plan_row()])

    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil', batch=_batch(establisher='prior-6'))

    assert _stems(refs) == ['cover-illustration', 'prior-6', 'prior-0',
                            'prior-1', 'prior-2']


def test_only_the_slots_that_resolved_are_promoted(in_project):
    """A partially-resolved batch is the normal state — `later_state` is empty
    whenever no illustration shows an entity past its first transition."""
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 8) + [plan_row()])

    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(establisher='prior-7', darkest='prior-5'))

    assert _stems(refs) == ['cover-illustration', 'prior-7', 'prior-5',
                            'prior-0', 'prior-1']


def test_every_batch_slot_is_labeled_with_its_own_name(in_project):
    """The label is what README shows beside the path, and which of the four
    approved images this is tells the author what it is there to hold.

    All four, not just one: with a single slot asserted, suppressing the label for
    `later_state` alone passed the whole suite, and SKILL.md tells the author the
    batch is labeled — so they could not tell which upload locks a changed state.
    """
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 5) + [plan_row()])

    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(establisher='prior-0', darkest='prior-1',
                     brightest='prior-2', later_state='prior-3'))
    labels = dict(zip(_stems(refs), [label for _p, label in refs]))
    assert labels['prior-0'] == 'prior illustration (anchor batch: establisher)'
    assert labels['prior-1'] == 'prior illustration (anchor batch: darkest)'
    assert labels['prior-2'] == 'prior illustration (anchor batch: brightest)'
    assert labels['prior-3'] == 'prior illustration (anchor batch: later-state)'
    # `prior-4` is in no slot, so a full batch caps it out entirely — which is the
    # arithmetic that makes the cover's additiveness load-bearing.
    assert 'prior-4' not in labels


def test_one_row_filling_two_slots_takes_one_reference(in_project):
    """The common configuration rather than an edge case: with no `register`
    cells, darkest and brightest can resolve to the same illustration, which
    `anchor_batch` discloses as "the batch brackets nothing"."""
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 3) + [plan_row()])

    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(darkest='prior-2', brightest='prior-2',
                     later_state='prior-1'))
    # One reference for the doubled row, named by the first slot it fills, and
    # the later slot still ranked behind it rather than displaced.
    assert _stems(refs) == ['cover-illustration', 'prior-2', 'prior-1',
                            'prior-0']
    labels = dict(zip(_stems(refs), [label for _p, label in refs]))
    assert labels['prior-2'] == 'prior illustration (anchor batch: darkest)'


def test_the_batch_ranks_ids_that_are_not_lowercase(in_project):
    """`ill._ID_RE` accepts `LF-01`, `asset_key` exists to lowercase an id, and
    the book #311 was filed about uses `LF-05`/`LF-13`/`LF-19`/`LF-20` — so a
    stray `.lower()` on either side of the id comparison would reproduce the bug
    on exactly that book while every lowercase-id test stayed green."""
    _style_ref(in_project)
    rows = []
    for i in range(6):
        illus_id = f'LF-0{i}'
        rel = ill.default_asset_rel(illus_id)
        make_png(os.path.join(in_project, rel), 8, 8)
        rows.append(plan_row(id=illus_id, status='ingested', asset_file=rel,
                             ingested_at='2026-07-28'))
    ill.write_plan(in_project, rows + [plan_row()])

    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(establisher='LF-05', darkest='LF-04',
                     brightest='LF-03', later_state='LF-02'))
    assert _stems(refs) == ['cover-illustration', 'LF-05', 'LF-04',
                            'LF-03', 'LF-02']


def test_the_cap_leaves_room_for_every_anchor_batch_slot(in_project):
    """The invariant the whole fix rests on, and the one nothing pinned: a fifth
    slot (or a lowered cap) silently makes the fourth approved image droppable
    again, and `_batch`'s hardcoded keys mean no unit test would notice."""
    assert cmd_illustrate._MAX_PRIOR_REFERENCES >= len(packet.BATCH_SLOTS)


def test_a_stale_batch_member_stays_excluded(in_project):
    """Exclusion outranks promotion: a pre-canon render was directed by canon
    that has since been rewritten, and being in the batch does not change that.
    """
    _style_ref(in_project)
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    rows = _priors(in_project, 2)
    rows[1]['ingested_at'] = '2026-07-01'
    ill.write_plan(in_project, rows + [plan_row()])

    notes = []
    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil', canon_cutoff='2026-07-20',
        batch=_batch(establisher='prior-1'), notes=notes)

    assert _stems(refs) == ['cover-illustration', 'prior-0']
    assert any('prior-1.png' in n for n in notes)


def test_the_cap_note_names_a_dropped_anchor_batch_image(in_project,
                                                         monkeypatch, capsys):
    """Silent loss of the approved batch is the part that made #311 hard to
    notice, so a batch image dropped by the cap is never reported as an
    anonymous 'further ingested illustration'."""
    monkeypatch.setattr(cmd_illustrate, '_MAX_PRIOR_REFERENCES', 2)
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 8) + [plan_row()])

    notes = []
    cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(establisher='prior-7', darkest='prior-6',
                     brightest='prior-5', later_state='prior-4'),
        notes=notes)

    # Selected on the bolded phrase, not on `'anchor batch'`: the *anonymous*
    # cap note also contains that substring, and this test passed only because
    # this note happens to be appended first.
    dropped = next(n for n in notes if '**anchor batch**' in n)
    assert 'brightest' in dropped and 'later-state' in dropped
    assert 'prior-5.png' in dropped and 'prior-4.png' in dropped
    # The two that fit are not reported as dropped.
    assert 'prior-7.png' not in dropped and 'prior-6.png' not in dropped
    assert 'anchor batch' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# What the notes may claim about the batch (#311 review)
#
# The exclusion walk runs BEFORE the ranking, so promotion routinely has nothing
# to promote: a partly re-rendered batch is the normal state during phase 1. The
# first cut of #311 closed with "so what is listed is what was approved"
# unconditionally, which on that state was an affirmative falsehood in the one
# section whose job is saying the list is thinner than it looks.
# ---------------------------------------------------------------------------

def _partly_stale_batch(project_dir):
    """4 approved-but-pre-canon rows, 5 current non-batch rows. Phase 1, midway.

    Five, so the cap also bites and the capped note's claim about the batch is
    exercised on the same fixture. Returns the batch naming the four stale rows.
    """
    _style_ref(project_dir)
    stale = _priors(project_dir, 4, ingested_at='2026-07-01')
    for row, name in zip(stale, ('b-est', 'b-dark', 'b-bright', 'b-later')):
        row['id'] = name
        rel = ill.default_asset_rel(name)
        make_png(os.path.join(project_dir, rel), 8, 8)
        row['asset_file'] = rel
    current = _priors(project_dir, 5)
    ill.write_plan(project_dir, stale + current + [plan_row()])
    return _batch(establisher='b-est', darkest='b-dark',
                  brightest='b-bright', later_state='b-later')


def test_the_notes_never_claim_an_excluded_batch_is_in_the_list(in_project):
    """Reproduced from the review: 0 of 4 approved images reached the list, and
    the note said what is listed is what was approved."""
    batch = _partly_stale_batch(in_project)

    notes = []
    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil', canon_cutoff='2026-07-20',
        batch=batch, notes=notes)

    assert not any('prior-' not in p and 'b-' in p for p, _ in refs), \
        'a pre-canon batch member must not be referenced'
    assert not any('what is listed is what was approved' in n for n in notes)
    assert any('0 of 4 anchor-batch' in n for n in notes)


def test_the_notes_do_claim_the_batch_when_the_batch_is_all_there(in_project):
    """The reassurance is worth having — it just has to be checked."""
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 8) + [plan_row()])

    notes = []
    cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(establisher='prior-7', darkest='prior-6',
                     brightest='prior-5', later_state='prior-4'),
        notes=notes)
    assert any('what is listed is what was approved' in n for n in notes)


def test_an_excluded_batch_member_is_named_with_its_slot(in_project, capsys):
    """SKILL.md promises the author is told this. The exclusion note aggregates
    by `StaleKind` and cannot say which paths were the approved ones."""
    batch = _partly_stale_batch(in_project)

    notes = []
    cmd_illustrate._references_for(
        in_project, 'lantern-vigil', canon_cutoff='2026-07-20',
        batch=batch, notes=notes)

    named = next(n for n in notes if 'b-est.png' in n and 'establisher' in n)
    assert 'darkest' in named and 'brightest' in named and 'later-state' in named
    assert 'anchor-batch' in capsys.readouterr().out


def test_a_batch_member_whose_file_is_gone_is_not_dropped_silently(in_project,
                                                                   capsys):
    """The one exclusion that can silently lose an approved image: `ingested`,
    current `ingested_at`, and the PNG moved or renamed without a plan edit —
    realistic, since the author often works from another machine. `needs_render`
    never consults `asset_file`, so the batch table still reads `Rendered: yes`.
    """
    _style_ref(in_project)
    rows = _priors(in_project, 3)
    os.remove(os.path.join(in_project, rows[2]['asset_file']))
    ill.write_plan(in_project, rows + [plan_row()])

    notes = []
    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(establisher='prior-2'), notes=notes)

    assert 'prior-2' not in _stems(refs)
    assert any('prior-2.png' in n for n in notes)
    assert 'prior-2.png' in capsys.readouterr().out


def test_a_guessed_register_slot_is_labeled_as_a_guess(in_project):
    """CLAUDE.md: nothing populates `register` on most projects, so darkest and
    brightest fall back to first and last in reading order. A prompt file
    carries no batch table and no `fallback` notes, so an unqualified
    `anchor batch: brightest` is a claim the author cannot check anywhere."""
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 3) + [plan_row()])

    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(darkest='prior-0', brightest='prior-2',
                     guessed=['brightest']))
    labels = dict(zip(_stems(refs), [label for _p, label in refs]))
    assert 'guess' in labels['prior-2']
    assert 'guess' not in labels['prior-0']


def test_the_cap_can_drop_a_batch_member_when_a_plan_id_repeats(in_project):
    """The one production route into the dropped-batch note. `run_package`
    deliberately skips `validate_plan`, so nothing gates a `duplicate_id` there —
    two rows sharing a promoted id put five entries at a rank below the cap, and
    the fifth is an approved image. Pinned so the branch has a test that does not
    monkeypatch the constant."""
    _style_ref(in_project)
    rows = _priors(in_project, 4)
    twin = dict(rows[0])
    twin['asset_file'] = ill.default_asset_rel('prior-0-copy')
    make_png(os.path.join(in_project, twin['asset_file']), 8, 8)
    ill.write_plan(in_project, rows + [twin, plan_row()])

    notes = []
    cmd_illustrate._references_for(
        in_project, 'lantern-vigil',
        batch=_batch(establisher='prior-0', darkest='prior-1',
                     brightest='prior-2', later_state='prior-3'),
        notes=notes)

    dropped = next(n for n in notes if '**anchor batch**' in n)
    assert 'prior-3.png' in dropped and 'later-state' in dropped


def test_the_dropped_batch_note_bounds_a_list_a_bad_plan_can_lengthen(
        in_project, monkeypatch):
    """Ten rows sharing one batch id would otherwise print ten paths all labeled
    `(establisher)`. The unreferenceable-slot note is bounded at four by its own
    keying and is deliberately *not* truncated — see `_and_more_phrases`."""
    monkeypatch.setattr(cmd_illustrate, '_MAX_PRIOR_REFERENCES', 1)
    _style_ref(in_project)
    rows = _priors(in_project, 1)
    twins = []
    for i in range(6):
        twin = dict(rows[0])
        twin['asset_file'] = ill.default_asset_rel(f'copy-{i}')
        make_png(os.path.join(in_project, twin['asset_file']), 8, 8)
        twins.append(twin)
    ill.write_plan(in_project, rows + twins + [plan_row()])

    notes = []
    cmd_illustrate._references_for(
        in_project, 'lantern-vigil', batch=_batch(establisher='prior-0'),
        notes=notes)

    dropped = next(n for n in notes if '**anchor batch**' in n)
    assert 'and 3 more' in dropped
    assert dropped.count('(establisher)') == packet._MAX_NAMED_IDS


def test_no_prior_refs_is_unaffected_by_the_batch(in_project):
    """The rebuild switch is cover-only by design — promotion has nothing to
    promote."""
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 4) + [plan_row()])

    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil', no_prior_refs=True,
        batch=_batch(establisher='prior-3', darkest='prior-2'))
    assert _stems(refs) == ['cover-illustration']


def test_an_illustration_never_references_itself_however_it_is_ranked(
        in_project):
    """Re-rendering an image with its own previous version in front of the model
    is how a re-render reproduces what it was meant to replace — and the row
    being the establisher is exactly when it is most tempting."""
    _style_ref(in_project)
    rows = _priors(in_project, 2)
    self_row = plan_row(status='ingested', ingested_at='2026-07-28',
                        asset_file=ill.default_asset_rel('lantern-vigil'))
    make_png(os.path.join(in_project, self_row['asset_file']), 8, 8)
    ill.write_plan(in_project, rows + [self_row])

    refs = cmd_illustrate._references_for(
        in_project, 'lantern-vigil', batch=_batch(establisher='lantern-vigil'))
    assert 'lantern-vigil' not in _stems(refs)


def test_the_anchor_batch_is_derived_once_per_prompts_run(in_project,
                                                          monkeypatch):
    """Threaded like the style reference and the canon cutoff: `_references_for`
    is called per row, so a per-row derivation would re-read the plan, the
    chapter map, and the transition log once per illustration."""
    write_scene(in_project, 'vigil', SCENE)
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 2) + [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '### Scene\n\nX.\n')

    calls = []
    real = packet.anchor_batch
    monkeypatch.setattr(packet, 'anchor_batch',
                        lambda pd, **kw: (calls.append(pd), real(pd, **kw))[1])

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    assert len(calls) == 1, f'{len(calls)} anchor-batch derivations'


def test_the_transition_log_is_read_once_per_prompts_run(in_project,
                                                         monkeypatch):
    """Deriving the batch beside `state_context` read the log twice, so every
    malformed row logged its WARNING twice — "N walks read as N broken files",
    the defect CLAUDE.md holds a canon-tree test on (#311 review, SF-I1)."""
    from storyforge import visual_state as vs_mod
    write_scene(in_project, 'vigil', SCENE)
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 2) + [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '### Scene\n\nX.\n')

    reads = []
    real = vs_mod.read_transitions
    monkeypatch.setattr(vs_mod, 'read_transitions',
                        lambda pd: (reads.append(pd), real(pd))[1])

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    assert len(reads) == 1, f'{len(reads)} transition-log reads'


def test_the_fallback_derivation_uses_the_plan_it_was_given(in_project):
    """`anchor_batch` reads the plan from disk, so a caller passing an in-memory
    `plan` with no `batch` would rank memory candidates against disk slots — a
    precondition two callers can disagree about."""
    _style_ref(in_project)
    on_disk = _priors(in_project, 5)
    ill.write_plan(in_project, on_disk + [plan_row()])
    # Derived from the plan on disk, the brightest slot is `prior-4` — a row this
    # call is not considering, so promotion silently does nothing. Derived from
    # the rows actually passed, it is `prior-3`, which is promoted.
    in_memory = on_disk[1:4] + [plan_row()]

    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil',
                                          plan=in_memory)
    assert _stems(refs) == ['cover-illustration', 'prior-3',
                            'prior-1', 'prior-2']


def test_a_batch_missing_a_slot_key_raises_rather_than_promoting_nothing(
        in_project):
    """`.get` was the only one of four `BATCH_SLOTS` consumers that degraded
    silently: add a slot without its `AnchorBatch` key and the other three raise,
    while this one promoted nothing and reverted #311 without a sound."""
    _style_ref(in_project)
    ill.write_plan(in_project, _priors(in_project, 2) + [plan_row()])
    malformed = _batch(establisher='prior-1')
    del malformed['later_state']            # type: ignore[misc]

    with pytest.raises(KeyError):
        cmd_illustrate._references_for(in_project, 'lantern-vigil',
                                       batch=malformed)


# ============================================================================
# The style reference (#299)
# ============================================================================
#
# Found on a real 20-illustration book: `--prompts --no-prior-refs` wrote 20
# prompt files whose only style reference was `cover-illustration.png`, which on
# that project held a cover variation the author had explicitly rejected. Every
# live consumer pointed at a different file; nothing could declare which artwork
# counted, nothing staleness-checked the one reference always present, and
# nothing logged which file had been chosen. It surfaced by reading a generated
# prompt by hand, 20 calls too late.
# ============================================================================

def _style_ref(project_dir, name='cover-illustration.png'):
    return make_png(os.path.join(project_dir, 'manuscript', 'assets', name),
                    8, 8)


def _set_yaml_production(project_dir, key, value):
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
    """Set a file's mtime to midnight on an ISO date."""
    from datetime import datetime
    stamp = datetime.fromisoformat(f'{iso_date}T00:00:00').timestamp()
    os.utime(path, (stamp, stamp))


def test_a_declared_style_reference_beats_the_convention(in_project):
    """The regression: the convention filename held a superseded variation and
    the selected art sat next to it under a descriptive name."""
    _style_ref(in_project)  # the superseded variation
    _style_ref(in_project, 'cover-illustration-discovery.png')
    _set_yaml_production(in_project, 'cover_artwork',
                         'manuscript/assets/cover-illustration-discovery.png')

    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['path'] == os.path.join(
        'manuscript', 'assets', 'cover-illustration-discovery.png')
    assert style['source'] == 'declared'
    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil')
    assert [p for p, _ in refs] == [
        'manuscript/assets/cover-illustration-discovery.png']


def test_the_convention_still_answers_when_nothing_is_declared(in_project):
    """Existing projects keep working — the whole point of the fallback."""
    _style_ref(in_project)
    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['path'] == os.path.join('manuscript', 'assets',
                                         'cover-illustration.png')
    assert style['source'] == 'convention'
    assert 'the conventional filename' in \
        cmd_illustrate.describe_style_reference(style)


def test_the_convention_accepts_a_jpeg(in_project):
    make_jpeg(os.path.join(in_project, 'manuscript', 'assets',
                           'cover-illustration.jpg'), 8, 8)
    assert cmd_illustrate.resolve_style_reference(in_project)['path'] == \
        os.path.join('manuscript', 'assets', 'cover-illustration.jpg')


def test_a_declared_path_that_does_not_exist_warns_and_falls_back(in_project):
    _style_ref(in_project)
    _set_yaml_production(in_project, 'cover_artwork', 'manuscript/assets/gone.png')

    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['unresolved_declaration'] == 'manuscript/assets/gone.png'
    assert style['path'] == os.path.join('manuscript', 'assets',
                                         'cover-illustration.png')
    assert style['source'] == 'convention'
    warnings = cmd_illustrate.style_reference_warnings(style)
    assert any('does not exist' in w for w in warnings)
    assert any('may not be the artwork you meant' in w for w in warnings)


def test_a_declared_path_that_does_not_exist_with_no_convention(in_project):
    _set_yaml_production(in_project, 'cover_artwork', 'manuscript/assets/gone.png')
    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['path'] == ''
    assert cmd_illustrate.describe_style_reference(style) == ''
    warnings = cmd_illustrate.style_reference_warnings(style)
    assert any('no conventional style reference was found either' in w
               for w in warnings)
    assert any('no cover artwork' in w for w in warnings)


def test_a_style_reference_older_than_the_canon_warns(in_project):
    """The regression: every other reference was staleness-checked and the most
    influential one was exempt."""
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    _backdate(_style_ref(in_project), '2026-07-01')

    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['modified'] == '2026-07-01'
    assert style['checked_against'] == '2026-07-20'
    assert style['stale'] is True
    warning = ' '.join(cmd_illustrate.style_reference_warnings(style))
    assert 'cover-illustration.png' in warning
    assert 'last modified 2026-07-01' in warning
    assert '2026-07-20' in warning
    assert 'production.cover_artwork' in warning


def test_a_style_reference_newer_than_the_canon_is_not_stale(in_project):
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    _backdate(_style_ref(in_project), '2026-07-21')
    assert cmd_illustrate.resolve_style_reference(in_project)['stale'] is False


def test_a_style_reference_modified_the_same_day_is_not_stale(in_project):
    """Same-day is the ordinary loop — edit canon, re-render the cover, prompt."""
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    _backdate(_style_ref(in_project), '2026-07-20')
    assert cmd_illustrate.resolve_style_reference(in_project)['stale'] is False


def test_a_style_reference_is_never_excluded_for_being_stale(in_project, capsys):
    """It is warned about, not dropped: under --no-prior-refs it is the whole
    style signal, so excluding it would leave the run with nothing."""
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    _backdate(_style_ref(in_project), '2026-07-01')
    ill.write_plan(in_project, [plan_row()])

    notes = []
    # The conjunction the docstring names: stale AND --no-prior-refs AND still
    # in the list. Passing the flag's own suppressed cutoff is what `run_prompts`
    # actually does on that path.
    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil',
                                          canon_cutoff='', no_prior_refs=True,
                                          notes=notes)
    assert [p for p, _ in refs] == [os.path.join('manuscript', 'assets',
                                                 'cover-illustration.png')]
    assert any('before the canon was last updated' in n for n in notes)


def test_the_style_staleness_check_survives_no_prior_refs(in_project):
    """`_reference_cutoff` returns '' under --no-prior-refs, and inheriting that
    would leave the highest-stakes run — cover is 100% of the signal — as the
    only unchecked one."""
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    _backdate(_style_ref(in_project), '2026-07-01')

    cutoff = cmd_illustrate._reference_cutoff(in_project, True)
    assert cutoff == ''
    notes = []
    cmd_illustrate._references_for(in_project, 'lantern-vigil',
                                   canon_cutoff=cutoff, no_prior_refs=True,
                                   notes=notes)
    assert any('before the canon was last updated 2026-07-20' in n
               for n in notes)


def test_a_symlinked_style_reference_resolves_with_its_target(in_project):
    """The project-side workaround for a book with several cover variations."""
    real = _style_ref(in_project, 'cover-illustration-discovery.png')
    link = os.path.join(in_project, 'manuscript', 'assets',
                        'cover-illustration.png')
    os.symlink(os.path.basename(real), link)

    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['path'] == os.path.join('manuscript', 'assets',
                                         'cover-illustration.png')
    assert style['symlink_target'] == os.path.join(
        'manuscript', 'assets', 'cover-illustration-discovery.png')
    headline = cmd_illustrate.describe_style_reference(style)
    assert 'cover-illustration-discovery.png' in headline
    # The prompt file's reference list names the target too — it is what the
    # author recognizes when uploading.
    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil')
    assert 'cover-illustration-discovery.png' in refs[0][1]


def test_a_broken_symlink_is_not_a_style_reference(in_project):
    os.makedirs(os.path.join(in_project, 'manuscript', 'assets'), exist_ok=True)
    os.symlink('nowhere.png', os.path.join(in_project, 'manuscript', 'assets',
                                           'cover-illustration.png'))
    assert cmd_illustrate.resolve_style_reference(in_project)['path'] == ''


def test_prompts_logs_the_style_reference_before_any_call(in_project, monkeypatch,
                                                          capsys):
    """A run that spends 20 model calls must say what set the house style."""
    write_scene(in_project, 'vigil', SCENE)
    _style_ref(in_project, 'cover-illustration-discovery.png')
    _set_yaml_production(in_project, 'cover_artwork',
                         'manuscript/assets/cover-illustration-discovery.png')
    ill.write_plan(in_project, [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    before_first_call = []

    def _record(*a, **k):
        # Snapshot, not assert. `capsys.readouterr()` drains the buffer and this
        # runs on a `run_parallel` worker, so a second row's worker would see an
        # empty buffer and fail for a reason unrelated to ordering.
        if not before_first_call:
            before_first_call.append(capsys.readouterr().out)
        return '### Scene\n\nX.\n'
    monkeypatch.setattr(cmd_illustrate, '_invoke', _record)

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    assert before_first_call, '_invoke was never called — nothing was proved'
    # Anything logged after this point is too late to be useful.
    assert ('Style reference: manuscript/assets/cover-illustration-'
            'discovery.png') in before_first_call[0]


def test_a_declared_absolute_path_inside_the_project_is_relativized(in_project):
    """`path` reaches git-tracked prompt files and the packet, whose contract is
    project-relative paths — an absolute declaration would commit a
    machine-specific path into a shared artifact."""
    real = _style_ref(in_project, 'selected.png')
    _set_yaml_production(in_project, 'cover_artwork', real)   # absolute

    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['path'] == os.path.join('manuscript', 'assets', 'selected.png')
    assert style['source'] == 'declared'
    assert style['outside_project'] is False
    assert not os.path.isabs(
        cmd_illustrate._references_for(in_project, 'lantern-vigil')[0][0])


def test_a_declaration_outside_the_project_is_disclosed(in_project, tmp_path):
    """It cannot be relativized, so the absolute path does reach the prompt
    file — which is exactly why it is warned about rather than passed over."""
    art = make_png(str(tmp_path / 'elsewhere' / 'art.png'), 8, 8)
    _set_yaml_production(in_project, 'cover_artwork', art)

    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['path'] == art
    assert style['outside_project'] is True
    assert any('outside the project' in w
               for w in cmd_illustrate.style_reference_warnings(style))


def test_a_declared_file_an_image_model_cannot_read_is_warned_about(in_project):
    """`production/cover.svg` beside the rendered PNG is the realistic case, and
    it is the same project shape the new key exists to disambiguate."""
    path = os.path.join(in_project, 'production', 'cover.svg')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('<svg/>')
    _set_yaml_production(in_project, 'cover_artwork', 'production/cover.svg')

    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['unusable_extension'] == 'svg'
    warning = ' '.join(cmd_illustrate.style_reference_warnings(style))
    assert 'no image model' in warning
    assert 'still listed' in warning
    # Warned, not dropped: the one reference that is sometimes the only one.
    assert [p for p, _ in cmd_illustrate._references_for(
        in_project, 'lantern-vigil')] == ['production/cover.svg']


def test_the_convention_scan_cannot_produce_an_unusable_extension(in_project):
    _style_ref(in_project)
    assert cmd_illustrate.resolve_style_reference(
        in_project)['unusable_extension'] == ''


def test_an_unreadable_mtime_is_unknown_not_fresh(in_project, monkeypatch):
    """Deliberately the opposite of `ingested_at`: there is no bookkeeping
    column here for a file to predate, so unknown is genuinely unknown — and
    unknown must not report as checked."""
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    _style_ref(in_project)
    monkeypatch.setattr(os.path, 'getmtime',
                        lambda _p: (_ for _ in ()).throw(OSError('stat')))

    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['modified'] == ''
    assert style['stale'] is False
    warning = ' '.join(cmd_illustrate.style_reference_warnings(style))
    assert 'could not be read' in warning
    assert 'not the same as fresh' in warning
    headline = cmd_illustrate.describe_style_reference(style)
    assert 'cover-illustration.png' in headline
    assert 'unreadable' in headline


def test_no_canon_date_means_the_check_did_not_run_and_says_so(in_project):
    """The silent-unchecked case. `--no-prior-refs` skips the line that used to
    mention it, which is the run where the cover is the whole style signal."""
    _style_ref(in_project)
    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['checked_against'] == ''
    assert style['stale'] is False
    warning = ' '.join(cmd_illustrate.style_reference_warnings(style))
    assert 'could not be checked for staleness' in warning
    assert 'no canon date to check it against' in \
        cmd_illustrate.describe_style_reference(style)


def test_the_headline_names_what_the_mtime_was_compared_against(in_project):
    """A bare date is a verdict the reader completes themselves."""
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    _backdate(_style_ref(in_project), '2026-07-21')
    assert 'canon last updated 2026-07-20' in \
        cmd_illustrate.describe_style_reference(
            cmd_illustrate.resolve_style_reference(in_project))


def test_a_dangling_convention_symlink_is_not_reported_as_no_artwork(in_project):
    """The link is right there in `ls`; telling the author to create it is the
    least useful thing to say. Symlinking the convention path at the selected
    art is the workaround this resolution order documents, so a stale target is
    its likeliest failure mode."""
    assets = os.path.join(in_project, 'manuscript', 'assets')
    os.makedirs(assets, exist_ok=True)
    os.symlink('gone.png', os.path.join(assets, 'cover-illustration.png'))

    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['path'] == ''
    assert 'gone.png' in style['dangling_symlink']
    warning = ' '.join(cmd_illustrate.style_reference_warnings(style))
    assert 'target does not exist' in warning
    assert 'there is no cover artwork' not in warning


def test_a_symlink_target_outside_the_project_is_reported_absolute(in_project,
                                                                  tmp_path):
    art = make_png(str(tmp_path / 'ext' / 'real.png'), 8, 8)
    assets = os.path.join(in_project, 'manuscript', 'assets')
    os.makedirs(assets, exist_ok=True)
    os.symlink(art, os.path.join(assets, 'cover-illustration.png'))
    style = cmd_illustrate.resolve_style_reference(in_project)
    assert style['symlink_target'] == art


def test_the_packet_note_does_not_capitalize_the_yaml_key(in_project):
    """`Production.cover_artwork` is a key nothing reads, told to an author
    reading the packet to find out what to set."""
    _style_ref(in_project)
    _set_yaml_production(in_project, 'cover_artwork', 'manuscript/assets/gone.png')
    notes = []
    cmd_illustrate._references_for(in_project, 'lantern-vigil', notes=notes)
    assert any('production.cover_artwork' in n for n in notes)
    assert not any('Production.cover_artwork' in n for n in notes)


def test_the_extension_order_is_deterministic(in_project):
    """Four candidates, one answer — otherwise which cover directs the book
    depends on filesystem iteration order."""
    assets = os.path.join(in_project, 'manuscript', 'assets')
    make_jpeg(os.path.join(assets, 'cover-illustration.jpg'), 8, 8)
    _style_ref(in_project)
    assert cmd_illustrate.resolve_style_reference(in_project)['path'] == \
        os.path.join('manuscript', 'assets', 'cover-illustration.png')


def test_a_resolved_jpeg_cover_is_additive_to_the_cap(in_project):
    """The extension widening is not behaviour-neutral: a jpeg-only project
    previously resolved no cover at all and got four priors. It now gets the
    cover *and* those four — the cap counts prior illustrations only (#311).
    Documented on _STYLE_REFERENCE_EXTENSIONS; pinned here."""
    make_jpeg(os.path.join(in_project, 'manuscript', 'assets',
                           'cover-illustration.jpg'), 8, 8)
    rows = []
    for i in range(6):
        rel = ill.default_asset_rel(f'prior-{i}')
        make_png(os.path.join(in_project, rel), 8, 8)
        rows.append(plan_row(id=f'prior-{i}', status='ingested',
                             asset_file=rel))
    ill.write_plan(in_project, rows + [plan_row()])

    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil')
    assert len(refs) == cmd_illustrate._MAX_PRIOR_REFERENCES + 1
    assert refs[0][0].endswith('cover-illustration.jpg')
    priors = [p for p, _ in refs if 'cover-illustration' not in p]
    assert len(priors) == cmd_illustrate._MAX_PRIOR_REFERENCES


def test_prompts_refuses_when_the_declaration_names_a_missing_file(
        in_project, monkeypatch, capsys):
    """Unambiguous, unlike staleness: an author who typed a path meant that
    path. Spending the run on the convention's artwork and exiting 0 is #299's
    outcome with a warning stapled to it."""
    write_scene(in_project, 'vigil', SCENE)
    _style_ref(in_project)
    _set_yaml_production(in_project, 'cover_artwork', 'manuscript/assets/gone.png')
    ill.write_plan(in_project, [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('nothing should be spent')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 1
    out = capsys.readouterr().out
    assert 'refusing to write prompts' in out
    assert 'gone.png' in out
    assert not os.path.exists(
        os.path.join(in_project, ill.default_prompt_rel('lantern-vigil')))


def test_diagnose_reports_the_style_reference(in_project, capsys):
    """--diagnose is the health gate, and a stale or mis-declared style reference
    is a free pure-function health fact about the book's most influential image.
    Previously reachable only by starting a run or reading the packet by hand."""
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    _backdate(_style_ref(in_project), '2026-07-01')
    ill.write_plan(in_project, [plan_row()])

    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'Style reference: ' in out
    assert 'before the canon was last updated' in out


def test_diagnose_reports_the_style_reference_with_no_plan(in_project, capsys):
    """The no-plan branch is a separate exit; a book mid-setup is exactly when
    the author is choosing which cover artwork counts."""
    cmd_illustrate.main(['--diagnose'])
    out = capsys.readouterr().out
    assert 'no cover artwork' in out


def test_prompts_dry_run_names_the_style_reference(in_project, capsys):
    """The one pre-flight mode an author reaches for reported neither the cover
    nor the state gaps, because it returned before both."""
    write_scene(in_project, 'vigil', SCENE)
    _style_ref(in_project)
    ill.write_plan(in_project, [plan_row()])

    assert cmd_illustrate.main(['--prompts', '--dry-run']) == 0
    out = capsys.readouterr().out
    assert 'Style reference: ' in out
    assert '[dry-run] would write' in out


def test_prompts_logs_the_style_staleness_warning_once(in_project, monkeypatch,
                                                       capsys):
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'characters', 'leo', 'Ten years old.',
                        canon_updated='2026-07-20')
    _backdate(_style_ref(in_project), '2026-07-01')
    ill.write_plan(in_project, [plan_row(), plan_row(id='second')])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '### Scene\n\nX.\n')

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    out = capsys.readouterr().out
    # Two rows, one warning: resolved once for the run, not once per row.
    assert out.count('was last modified 2026-07-01') == 1


def test_ingest_records_the_ingest_date(in_project):
    from datetime import date
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    src = make_png(os.path.join(in_project, 'incoming', 'lantern-vigil.png'),
                   8, 8)

    assert cmd_illustrate.main(['--ingest', os.path.dirname(src)]) == 0
    row = read_plan_map(in_project)['lantern-vigil']
    assert row['ingested_at'] == date.today().isoformat()


def test_a_plan_predating_the_ingested_at_column_still_validates(in_project):
    """Every row on the real book is in this state. Failing its schema check
    would block the run that fixes it."""
    from storyforge.schema import validate_illustration_plan
    legacy = [c for c in ill.PLAN_COLUMNS if c != 'ingested_at']
    with open(ill.plan_path(in_project), 'w') as f:
        f.write('|'.join(legacy) + '\n')
        f.write('lantern-vigil' + '|' * (len(legacy) - 1) + '\n')

    result = validate_illustration_plan(in_project)
    # The header check must pass. (The row itself is blank, so its own
    # cross-referential findings are expected and beside the point here.)
    assert [e for e in result['errors'] if e['row'] == 'header'] == []
    assert any('ingested_at' in w['message'] for w in result['warnings'])


def test_cleanup_does_not_flag_a_plan_without_ingested_at(in_project):
    from storyforge.cmd_cleanup import report_csv_schema
    legacy = [c for c in ill.PLAN_COLUMNS if c != 'ingested_at']
    with open(ill.plan_path(in_project), 'w') as f:
        f.write('|'.join(legacy) + '\n')

    issues = report_csv_schema(in_project)
    assert not [i for i in issues if 'illustration-plan' in i]


def test_a_plan_write_upgrades_the_header(in_project):
    """Which is why the missing column is not worth an action item: the next
    write closes it."""
    legacy = [c for c in ill.PLAN_COLUMNS if c != 'ingested_at']
    with open(ill.plan_path(in_project), 'w') as f:
        f.write('|'.join(legacy) + '\n')
        f.write('lantern-vigil' + '|' * (len(legacy) - 1) + '\n')

    ill.write_plan(in_project, ill.read_plan(in_project))
    with open(ill.plan_path(in_project)) as f:
        assert 'ingested_at' in f.readline()


# ============================================================================
# Concurrency (prompt item 1)
#
# One measured art-direction call took 13 seconds; a 20-illustration book was
# 4-5 minutes of strictly serial waiting for calls that share nothing.
# ============================================================================

def test_prompt_calls_run_concurrently(in_project, monkeypatch):
    """A barrier is the assertion: if the calls are serialized, the first one
    waits for peers that never arrive and the barrier times out."""
    import threading

    rows = [plan_row(id=f'lf-{i}', scene_id='vigil') for i in range(3)]
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, rows)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    # run_parallel honours STORYFORGE_PARALLEL; a dev shell exporting 1 would
    # otherwise make this test fail for an environmental reason.
    monkeypatch.delenv('STORYFORGE_PARALLEL', raising=False)

    barrier = threading.Barrier(3, timeout=10)

    def _blocking(*a, **k):
        barrier.wait()
        return '### Scene\n\nX.\n'

    monkeypatch.setattr(cmd_illustrate, '_invoke', _blocking)
    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    assert all(read_plan_map(in_project)[f'lf-{i}']['status'] == 'prompted'
               for i in range(3))


def test_two_rows_proposing_the_same_anchor_write_one_canon_file(in_project,
                                                                 monkeypatch,
                                                                 capsys):
    """append_anchor_stubs mutates its canon_id_index in-loop precisely so two
    proposals in one batch write one file. A naive fan-out breaks that
    guarantee: both workers see no file and both write. First proposal wins,
    and the second is reported rather than overwriting it."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [
        plan_row(id='lf-01', scene_id='vigil'),
        plan_row(id='lf-02', scene_id='vigil'),
    ])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    bodies = {
        'lf-01': '### Scene\n\nA.\n\nANCHORS\n- Dorren Hayle | character — '
                 'first proposal, a spare woman of fifty\n',
        'lf-02': '### Scene\n\nB.\n\nANCHORS\n- Dorren Hayle | character — '
                 'second proposal, a stout woman of thirty\n',
    }
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda pd, prompt, op, **kw: bodies[kw['target']])

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0

    from storyforge import canon
    canon_dir = os.path.join(in_project, 'reference', 'canon', 'characters')
    assert sorted(os.listdir(canon_dir)) == ['dorren-hayle.md']
    assert canon.anchor_texts(in_project)['dorren-hayle'] == (
        'first proposal, a spare woman of fifty')
    assert 'already exists at' in capsys.readouterr().out


def test_a_worker_exception_fails_only_its_own_row(in_project, monkeypatch,
                                                   capsys):
    """Retry granularity: one raised call must not cost the other rows their
    prompts, and its own row must stay at `planned` so a re-run picks it up."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [
        plan_row(id='lf-01', scene_id='vigil'),
        plan_row(id='lf-02', scene_id='vigil'),
    ])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _flaky(pd, prompt, op, **kw):
        if kw['target'] == 'lf-01':
            raise OSError('network is down')
        return '### Scene\n\nX.\n'

    monkeypatch.setattr(cmd_illustrate, '_invoke', _flaky)
    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 1

    plan = read_plan_map(in_project)
    assert plan['lf-01']['status'] == 'planned'
    assert plan['lf-02']['status'] == 'prompted'
    out = capsys.readouterr().out
    assert 'network is down' in out
    assert 'lf-01' in out


def test_prompt_files_are_written_in_plan_order(in_project, monkeypatch,
                                                capsys):
    """Concurrency is in the calls only. Writes and their log lines stay
    sequential, so a run stays readable and reviewable."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(id=f'lf-{i}', scene_id='vigil')
                                for i in range(4)])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '### Scene\n\nX.\n')

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    out = capsys.readouterr().out
    written = [line for line in out.splitlines() if '→' in line]
    assert [f'lf-{i}' in line for i, line in enumerate(written)] == [True] * 4


# ============================================================================
# Anchor labels (prompt item 4) and the single Constraints section (item 5)
# ============================================================================

def _capture_request(in_project, monkeypatch):
    seen = {}
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda pd, prompt, op, **kw: (
                            seen.update(prompt=prompt)
                            or '### Scene\n\nX.\n'))
    return seen


def test_anchor_labels_use_the_registry_name_not_the_slug(in_project,
                                                          monkeypatch):
    """The leak: the model echoed the id back in its prose ("kneeling are
    leo — ten, warm light-brown skin…"), which is text the author pastes into
    an image model."""
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'characters', 'dorren-hayle',
                        'A spare woman of fifty in a grey coat.')
    ill.write_plan(in_project, [plan_row(canon_refs='dorren-hayle')])
    seen = _capture_request(in_project, monkeypatch)

    cmd_illustrate.main(['--prompts', '--coaching', 'full'])
    block = seen['prompt'].split('## Character anchors')[1]
    assert '**Dorren Hayle**' in block
    assert 'dorren-hayle' not in block
    # The anchor text itself is untouched — likeness continuity depends on it.
    assert 'A spare woman of fifty in a grey coat.' in block


def test_anchor_labels_prefer_a_frontmatter_display_name(in_project,
                                                         monkeypatch):
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'characters', 'dorren-hayle',
                        'A spare woman of fifty.',
                        display_name='Dr. Dorren Hayle')
    ill.write_plan(in_project, [plan_row(canon_refs='dorren-hayle')])
    seen = _capture_request(in_project, monkeypatch)

    cmd_illustrate.main(['--prompts', '--coaching', 'full'])
    assert '**Dr. Dorren Hayle**' in seen['prompt']


def test_an_anchor_with_no_recorded_name_is_labeled_and_reported(in_project,
                                                                monkeypatch,
                                                                capsys):
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'motifs', 'great-lamp',
                        'A brass lamp the height of a child.')
    ill.write_plan(in_project, [plan_row(canon_refs='great-lamp')])
    seen = _capture_request(in_project, monkeypatch)

    cmd_illustrate.main(['--prompts', '--coaching', 'full'])
    assert '**Great Lamp**' in seen['prompt']
    out = capsys.readouterr().out
    assert 'no recorded display name' in out
    assert 'great-lamp' in out


def test_canon_refs_still_match_on_the_canon_id(in_project, monkeypatch,
                                                capsys):
    """Only the rendered label changes; the matching key stays the canon_id, so
    a row naming the id must not warn about an unmatched canon_ref."""
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'characters', 'dorren-hayle',
                        'A spare woman of fifty.')
    _write_entity_canon(in_project, 'motifs', 'great-lamp', 'A brass lamp.')
    ill.write_plan(in_project, [plan_row(canon_refs='dorren-hayle')])
    seen = _capture_request(in_project, monkeypatch)

    cmd_illustrate.main(['--prompts', '--coaching', 'full'])
    block = seen['prompt'].split('## Character anchors')[1]
    assert '**Dorren Hayle**' in block
    assert 'A brass lamp' not in block   # narrowing still works
    assert 'matched no known anchor' not in capsys.readouterr().out


# ============================================================================
# The scene split in the request and the prompt file (#308)
# ============================================================================

def test_the_request_labels_the_read_side_and_forbids_the_unread_side():
    request = pi.build_art_direction_request(
        split=scene_split(), row=plan_row(),
        character_anchors={}, canon_context='c')

    assert 'read by the time the illustration appears' in request
    assert 'sits at the **end** of this text' in request
    assert '## What the reader has NOT read yet' in request
    assert 'Nothing came. The cold worked up.' in request


def test_the_request_forbids_naming_the_unread_beat_even_to_exclude_it():
    """The forbidden block must not become a fifth exception to positive
    framing. #263: a negated phrase in an image prompt puts the thing in the
    render, so "no hands raised against the light" is worse than silence."""
    request = pi.build_art_direction_request(
        split=scene_split(unread='hands raised against the light'),
        row=plan_row(), character_anchors={}, canon_context='c')
    assert 'silently' in request
    assert 'not even to exclude it' in request


def test_the_request_states_an_unresolved_position_rather_than_implying_none():
    request = pi.build_art_direction_request(
        split=scene_split(state='unknown', offset=None, unread='',
                          next_sentence='',
                          error='anchor not found in scene'),
        row=plan_row(), character_anchors={}, canon_context='c')
    assert 'could not be resolved' in request
    assert 'anchor not found in scene' in request


def test_the_unknown_state_does_not_also_claim_the_prose_was_read():
    """The header was unconditional, so the request asserted "this is the prose
    the reader has read… the illustration sits at the end of this text" and then
    contradicted it twelve lines later. The false statement came first."""
    request = pi.build_art_direction_request(
        split=scene_split(state='unknown', offset=None, unread='',
                          next_sentence='', error='anchor is ambiguous'),
        row=plan_row(), character_anchors={}, canon_context='c')
    assert 'sits at the **end** of this text' not in request
    assert 'read by the time the illustration appears' not in request


def test_an_opener_is_asked_to_illustrate_the_prose_it_opens():
    """`scene_open` had `read == ''`, so the request asserted "prose the reader
    has read" over an empty section and put the scene's opening in the forbidden
    block — telling the model to avoid the only description of the image it was
    being asked to draw. `scene_open` + `full_page` is the documented opener."""
    request = pi.build_art_direction_request(
        split=scene_split(state='establishing', offset=0, read='',
                          unread='The lantern guttered on the sill.',
                          next_sentence=''),
        row=plan_row(placement='scene_open', layout='full_page'),
        character_anchors={}, canon_context='c')

    assert '**opens** the scene' in request
    assert 'The lantern guttered on the sill.' in request
    assert '## What the reader has NOT read yet' not in request
    assert 'sits at the **end** of this text' not in request


def test_a_scene_close_request_carries_no_forbidden_block():
    """Nothing after the image — so nothing to forbid, and nothing unresolved."""
    request = pi.build_art_direction_request(
        split=scene_split(state='at_scene_end', unread='', next_sentence=''),
        row=plan_row(placement='scene_close'),
        character_anchors={}, canon_context='c')
    assert '## What the reader has NOT read yet' not in request
    assert 'could not be resolved' not in request


def test_the_acceptance_block_quotes_the_next_sentence():
    joined = '\n'.join(pi.prompt_acceptance_lines(
        split=scene_split(), state='a lit lamp'))
    assert 'Nothing from after the illustration appears in it' in joined
    assert '"Nothing came."' in joined


@pytest.mark.parametrize('state,because', [
    ('at_scene_end', 'no prose\nin that scene follows it'),
    ('establishing', 'opens its scene'),
])
def test_the_vacuous_states_state_their_absence_rather_than_a_check(state, because):
    """No check to tick — rendering one told the author to re-render a correct
    opener. But not silence either: `acceptance.md`'s page-turn item sends them
    here for a sentence, so emitting nothing made that a dead-end referral on the
    two states where no sentence exists."""
    joined = '\n'.join(pi.prompt_acceptance_lines(
        split=scene_split(state=state, unread='', next_sentence=''),
        state='a lit lamp'))
    assert 'Nothing from after' not in joined
    assert 'Cannot be checked' not in joined
    assert 'No page-turn check applies' in joined
    assert because.split('\n')[0] in joined


def test_an_image_at_the_very_start_is_not_told_the_reader_has_read_it():
    """`normal` with nothing read is legitimate — `before_anchor` anchored in the
    first paragraph — but it must not inherit the "here is what the reader has
    read" heading over an empty block, and it cannot be told to depict the prose
    below, which is what the author placed it in front of."""
    request = pi.build_art_direction_request(
        split=scene_split(offset=0, read='', unread='The lamp guttered.'),
        row=plan_row(placement='before_anchor'),
        character_anchors={}, canon_context='c')
    assert 'read **nothing** yet' in request
    assert 'sits at the **end** of this text' not in request
    assert 'may not depict' in request


def test_prompts_warn_about_an_image_anchored_in_the_first_paragraph(
        in_project, monkeypatch, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(
        anchor='The lantern guttered', placement='before_anchor')])
    _capture_request(in_project, monkeypatch)
    cmd_illustrate.main(['--prompts', '--coaching', 'full'])

    out = capsys.readouterr().out
    assert 'first paragraph' in out
    assert 'placement=scene_open' in out


def test_an_unreadable_scene_does_not_promise_prose_it_has_none_of():
    """The `unknown` heading was written for the anchor-failure case, which
    carries a leading window. The missing-scene, unreadable and undrafted causes
    carry no excerpt, so it promised an opening that was not there."""
    request = pi.build_art_direction_request(
        split=scene_split(state='unknown', offset=None, cause='scene_missing',
                          read='', unread='', next_sentence='',
                          error="scene file for 'nowhere' is not in scenes/"),
        row=plan_row(), character_anchors={}, canon_context='c')
    assert 'The scene could not be read' in request
    assert 'What follows is the *opening*' not in request
    assert 'no prose below' in request


def test_the_acceptance_block_says_when_the_spoiler_check_is_impossible():
    joined = '\n'.join(pi.prompt_acceptance_lines(
        split=scene_split(state='unknown', offset=None, unread='',
                          next_sentence='', error='anchor is ambiguous'),
        state='a lit lamp'))
    assert 'Cannot be checked for spoilers' in joined
    assert 'anchor is ambiguous' in joined


def test_the_prompt_file_carries_the_spoiler_check_end_to_end(in_project,
                                                             monkeypatch):
    """The whole of item 2, through the real command."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '### Scene\n\nA cold street.\n\n### Subject\n\nA woman.\n'))

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    with open(os.path.join(in_project,
                           ill.default_prompt_rel('lantern-vigil'))) as f:
        content = f.read()

    assert '"Nothing came."' in content
    # In the do-NOT-paste block, never in the pasted Constraints: the quote is
    # prose the image model must not see.
    accept = content.split('## Accept only if')[1]
    assert 'Nothing from after the illustration' in accept
    assert 'Nothing came' not in content.split('## Accept only if')[0]


def test_the_request_sends_the_read_side_not_a_window_round_the_anchor(
        in_project, monkeypatch):
    """#308 end to end: the post-anchor beat must not reach the model as scene
    prose. On LF-19 and LF-20 it did, and both prompts described it."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    seen = _capture_request(in_project, monkeypatch)
    cmd_illustrate.main(['--prompts', '--coaching', 'full'])

    scene_section = seen['prompt'].split('## The scene it accompanies')[1] \
                                 .split('## What the reader has NOT read yet')[0]
    assert 'She set it on the sill' in scene_section
    assert 'By morning she had decided' not in scene_section


def test_prompts_warn_when_a_row_has_no_resolvable_position(in_project,
                                                            monkeypatch, capsys):
    """The free-fix moment is before the call, not after paying for it."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(anchor='prose that is not there')])
    _capture_request(in_project, monkeypatch)
    cmd_illustrate.main(['--prompts', '--coaching', 'full'])

    out = capsys.readouterr().out
    assert 'no resolvable position' in out
    assert 'lantern-vigil' in out


def test_the_request_does_not_ask_for_a_constraints_section():
    """The deterministic block owns that section. Asking for one too produced
    `## Constraints` with a nested, contradicting `### Constraints`."""
    request = pi.build_art_direction_request(
        split=scene_split(), row=plan_row(), character_anchors={},
        canon_context='c')
    assert '**Constraints** — what must hold' not in request
    assert 'Do **not** write a Constraints section' in request
    assert 'four sections' in request


def test_the_prompt_file_has_exactly_one_constraints_heading(in_project,
                                                             monkeypatch):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '### Scene\n\nA cold street.\n\n### Subject\n\nA woman.\n\n'
        '### Important details\n\n- a lit sill\n\n### Use case\n\n'
        'Interior illustration.\n'))

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    with open(os.path.join(in_project,
                           ill.default_prompt_rel('lantern-vigil'))) as f:
        lines = f.read().splitlines()
    headings = [line for line in lines if line.lstrip('#').strip() == 'Constraints']
    assert headings == ['### Constraints']


def test_the_strict_scaffold_carries_no_constraints_section(in_project):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    assert cmd_illustrate.main(['--prompts', '--coaching', 'strict']) == 0
    with open(os.path.join(in_project,
                           ill.default_prompt_rel('lantern-vigil'))) as f:
        lines = f.read().splitlines()
    # Heading-level check, matching the --coaching full sibling: counting the
    # bare word would also match prose mentioning constraints, and would miss
    # the actual defect (two headings of the same name at different levels).
    headings = [line for line in lines
                if line.lstrip('#').strip() == 'Constraints']
    assert headings == ['### Constraints']


# ============================================================================
# Status only moves forward (prompt item 6)
#
# Reproduced on a live book: `--prompts --ids LF-05` on a fully-ingested plan
# took the publishable set from 20/20 to 19/20, with no warning and no error.
# `prompted` is not `ingested`, which is what `manifest_assets` gates on, so the
# art stopped shipping to Bookshelf. It kept shipping in the epub, the PDF, and
# the web book, which drop only `superseded` — so the editions disagreed about a
# book nobody had changed. The file was never touched, only the row that says it
# exists. `--diagnose` said "No problems found," because an
# unrendered row is legitimate in-flight state.
# ============================================================================

def _prompt_one(project_dir, monkeypatch, ids=None):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '### Scene\n\nX.\n')
    argv = ['--prompts', '--coaching', 'full']
    if ids:
        argv += ['--ids', ids]
    return cmd_illustrate.main(argv)


def test_prompting_a_planned_row_advances_it(in_project, monkeypatch):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(status='planned')])

    assert _prompt_one(in_project, monkeypatch) == 0
    row = read_plan_map(in_project)['lantern-vigil']
    assert row['status'] == 'prompted'
    assert row['prompt_file'] == ill.default_prompt_rel('lantern-vigil')


def test_prompting_a_superseded_row_revives_it(in_project, monkeypatch, capsys):
    """Naming a retired row by id is an unambiguous request to work on it, so
    it revives — but only as far as `prompted`. Its replacement render does not
    exist yet, so it must not go straight back to `ingested`."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(status='superseded')])

    assert _prompt_one(in_project, monkeypatch, ids='lantern-vigil') == 0
    row = read_plan_map(in_project)['lantern-vigil']
    assert row['status'] == 'prompted'
    assert row['prompt_file'] == ill.default_prompt_rel('lantern-vigil')
    assert 'reviving a retired row' in capsys.readouterr().out


def test_a_bulk_run_never_revives_a_superseded_row(in_project, monkeypatch):
    """Only an explicit --ids revives. A bulk `--prompts` must not resurrect
    retired art as a side effect of prompting the rest of the book."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [
        plan_row(id='retired', status='superseded'),
        plan_row(id='fresh', status='planned'),
    ])

    assert _prompt_one(in_project, monkeypatch) == 0
    plan = read_plan_map(in_project)
    assert plan['retired']['status'] == 'superseded'
    assert plan['retired']['prompt_file'] == ''
    assert plan['fresh']['status'] == 'prompted'


def test_prompting_a_rendered_row_keeps_its_status(in_project, monkeypatch,
                                                   capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(status='rendered')])

    assert _prompt_one(in_project, monkeypatch, ids='lantern-vigil') == 0
    row = read_plan_map(in_project)['lantern-vigil']
    assert row['status'] == 'rendered'
    # The prompt file is still written — that is the whole point of the run.
    assert row['prompt_file'] == ill.default_prompt_rel('lantern-vigil')
    out = capsys.readouterr().out
    assert 'already-rendered art' in out
    assert 're-render is pending' in out


def test_prompting_an_ingested_row_keeps_it_publishable(in_project, monkeypatch,
                                                        capsys):
    """The consequence that actually bit: the publishable set must be identical
    before and after, and the marker must still resolve into the local build.

    manifest_assets proves the publish side and never touches disk, so the file
    and its real digest are here for the resolution half — `resolve_for_local`
    only resolves a marker whose row is `ingested` AND whose file exists, which
    is the epub / PDF / web-book consequence."""
    art = make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR,
                               'lantern-vigil.png'), 8, 8)
    row_in = plan_row(
        status='ingested', asset_file=ill.default_asset_rel('lantern-vigil'),
        sha256=ill.sha256_of(art), width='8', height='8',
        ingested_at='2026-07-28')
    write_scene(in_project, 'vigil', ill.insert_marker(SCENE, row_in)['text'])
    ill.write_plan(in_project, [row_in])

    before = ill.manifest_assets(in_project)
    assert [a['key'] for a in before] == ['lantern-vigil']
    with open(os.path.join(in_project, 'scenes', 'vigil.md')) as f:
        scene_text = f.read()
    assert 'lantern-vigil.png' in ill.resolve_for_local(in_project, scene_text)

    assert _prompt_one(in_project, monkeypatch, ids='lantern-vigil') == 0

    row = read_plan_map(in_project)['lantern-vigil']
    assert row['status'] == 'ingested'
    assert row['prompt_file'] == ill.default_prompt_rel('lantern-vigil')
    # Digest, dimensions, the file record, and the ingest date are untouched —
    # a re-prompt is new art direction, not a new ingest.
    assert row['sha256'] == ill.sha256_of(art)
    assert row['asset_file'] == ill.default_asset_rel('lantern-vigil')
    assert row['ingested_at'] == '2026-07-28'
    assert ill.manifest_assets(in_project) == before
    dropped: list[str] = []
    assert 'lantern-vigil.png' in ill.resolve_for_local(
        in_project, scene_text, dropped=dropped)
    assert dropped == []
    out = capsys.readouterr().out
    assert 'already-ingested art' in out


def test_status_after_prompt_maps_every_status():
    """Every value in VALID_PLAN_STATUSES, so a new status cannot be added
    without deciding what re-prompting does to it."""
    advance = cmd_illustrate._status_after_prompt
    assert advance('') == 'prompted'
    assert advance('planned') == 'prompted'
    assert advance('superseded') == 'prompted'
    assert advance('prompted') == 'prompted'
    assert advance('rendered') == ''
    assert advance('ingested') == ''
    assert set(ill.VALID_PLAN_STATUSES) == {
        'planned', 'prompted', 'rendered', 'ingested', 'superseded'}


# ============================================================================
# LF line endings (prompt item 7)
# ============================================================================

def test_write_plan_writes_no_carriage_returns(in_project):
    """csv defaults to '\\r\\n', which turned a one-field edit into a whole-file
    diff and produced the state cleanup's own crlf_line_endings check flags.
    Note that opening with newline='\\n' would NOT have fixed it: the writer
    emits the terminator itself, and no translation is applied on write."""
    ill.write_plan(in_project, [plan_row(), plan_row(id='second')])
    with open(ill.plan_path(in_project), 'rb') as f:
        assert b'\r' not in f.read()


def test_a_prompt_run_leaves_the_plan_in_lf(in_project, monkeypatch):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    assert _prompt_one(in_project, monkeypatch) == 0
    with open(ill.plan_path(in_project), 'rb') as f:
        assert b'\r' not in f.read()


def test_cleanup_does_not_flag_a_freshly_written_plan(in_project):
    from storyforge.cmd_cleanup import _check_crlf
    ill.write_plan(in_project, [plan_row()])
    assert [f for f in _check_crlf(in_project)
            if 'illustration-plan' in f['file']] == []


# ============================================================================
# Anchors are inputs, not residue (fix round: item 1 regression)
#
# The per-illustration loop used to re-read the anchor set per row, so a canon
# stub written for row 1 reached rows 2..N verbatim. Building every request
# before the first call ended that: N rows with no anchor for a character now
# each invent their own description, the first stub wins the canon file, and the
# other N-1 prompt files disagree with it — the exact likeness drift the
# identical-string mechanism exists to prevent. Nothing downstream can repair
# it, so the check has to run before the calls are paid for.
# ============================================================================

def test_preflight_warns_when_canon_refs_names_a_missing_anchor(in_project,
                                                                monkeypatch,
                                                                capsys):
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'characters', 'dorren-hayle',
                        'A spare woman of fifty.')
    ill.write_plan(in_project, [
        plan_row(id='lf-01', scene_id='vigil',
                 canon_refs='dorren-hayle;great-lamp'),
        plan_row(id='lf-02', scene_id='vigil', canon_refs='dorren-hayle'),
    ])

    assert _prompt_one(in_project, monkeypatch) == 0
    out = capsys.readouterr().out
    warning = next(line for line in out.splitlines()
                   if 'no continuity anchor' in line)
    assert 'WARNING' in warning
    assert '1 row(s)' in warning
    assert 'lf-01 → great-lamp' in warning
    # lf-02's only canon_ref resolves, so it is not part of this finding.
    assert 'lf-02' not in warning
    # Actionable, and names the mechanism that makes it unrecoverable later.
    assert 'does NOT reach the other rows in this run' in warning
    assert '--direction' in warning


def test_preflight_is_silent_when_every_named_anchor_resolves(in_project,
                                                              monkeypatch,
                                                              capsys):
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'characters', 'dorren-hayle',
                        'A spare woman of fifty.')
    ill.write_plan(in_project, [plan_row(canon_refs='dorren-hayle')])

    assert _prompt_one(in_project, monkeypatch) == 0
    out = capsys.readouterr().out
    assert 'no continuity anchor' not in out
    assert 'have no canon_refs' not in out


def test_preflight_warns_about_the_unnarrowed_fallback(in_project, monkeypatch,
                                                       capsys):
    """An empty canon_refs sends the whole cast, so nothing can check whether
    this row's actual cast is anchored. Only worth saying when the book has
    entity canon at all.

    This is a WARNING rather than a plain log because narrowing is off
    entirely — the token cost and the off-frame-character risk are the
    consequence that justifies the severity, so the message has to carry them
    (an author reading it should learn why it matters, not only what the
    condition is). Both branches of the gate must also state the
    non-propagation rule and point at `--direction`; the missing-anchor branch
    had them from the start and this one did not."""
    write_scene(in_project, 'vigil', SCENE)
    _write_entity_canon(in_project, 'characters', 'dorren-hayle',
                        'A spare woman of fifty.')
    ill.write_plan(in_project, [plan_row(canon_refs='')])

    assert _prompt_one(in_project, monkeypatch) == 0
    out = capsys.readouterr().out
    warning = next(line for line in out.splitlines()
                   if 'have no canon_refs' in line)
    assert 'WARNING' in warning
    assert 'lantern-vigil' in warning
    # The consequence that justifies the severity.
    assert 'costs tokens' in warning
    assert 'off-frame characters' in warning
    # The two statements the fix requires of BOTH branches.
    assert 'does NOT reach the other rows in this run' in warning
    assert '--direction' in warning


def test_preflight_says_nothing_when_the_book_has_no_entity_canon(in_project,
                                                                  monkeypatch,
                                                                  capsys):
    """With no anchors at all there is no narrowing to fall back from, and
    _reference_tier_gaps already covers the missing reference tier — a second
    warning about the same absence is noise."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(canon_refs='')])

    assert _prompt_one(in_project, monkeypatch) == 0
    assert 'have no canon_refs' not in capsys.readouterr().out


def test_new_stubs_name_the_rerun_for_the_other_rows(in_project, monkeypatch,
                                                     capsys):
    """The stub is written after every request was built, so the other prompts
    in this run cannot contain it. Saying so without naming the re-run leaves
    the author to work out the remedy."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [
        plan_row(id='lf-01', scene_id='vigil'),
        plan_row(id='lf-02', scene_id='vigil'),
    ])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    bodies = {
        'lf-01': '### Scene\n\nA.\n\nANCHORS\n- Dorren Hayle | character — '
                 'a spare woman of fifty\n',
        'lf-02': '### Scene\n\nB.\n',
    }
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda pd, prompt, op, **kw: bodies[kw['target']])

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0
    out = capsys.readouterr().out
    assert 'wrote 1 new canon stub(s)' in out
    assert 'built before these stubs existed' in out
    assert '--prompts --ids lf-02' in out
    # And the claim is true: lf-02's prompt file cannot carry the new anchor.
    with open(os.path.join(in_project, ill.default_prompt_rel('lf-02'))) as f:
        assert 'spare woman of fifty' not in f.read()


def test_a_failed_row_reports_its_real_status(in_project, monkeypatch, capsys):
    """Hardcoding `planned` told an author whose re-prompt of finished art
    failed that it had been demoted — in the one area item 6 exists to fix."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(status='ingested')])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: '')

    assert cmd_illustrate.main(['--prompts', '--ids', 'lantern-vigil']) == 1
    out = capsys.readouterr().out
    assert 'status stays `ingested`' in out
    assert 'status stays `planned`' not in out
    assert read_plan_map(in_project)['lantern-vigil']['status'] == 'ingested'


def test_ingesting_over_a_superseded_row_says_it_un_retires_it(in_project,
                                                               capsys):
    """Ingest is the documented revival endpoint, so the transition is right —
    but a stale leftover file would otherwise change the publishable set with
    nothing said, which is the class of silent change item 6 closed."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(status='superseded')])
    src = make_png(os.path.join(in_project, 'incoming', 'lantern-vigil.png'),
                   8, 8)

    assert cmd_illustrate.main(['--ingest', os.path.dirname(src)]) == 0
    out = capsys.readouterr().out
    assert 'was retired (status=superseded)' in out
    assert 'un-retires it' in out
    assert read_plan_map(in_project)['lantern-vigil']['status'] == 'ingested'
    assert ill.manifest_assets(in_project) != []


# ============================================================================
# --state (#278 phase 2)
# ============================================================================

def test_state_strict_writes_a_template_and_makes_no_api_call(in_project, monkeypatch):
    """The key must be set or the missing-key guard fires before the trap and
    this test passes vacuously."""
    from storyforge import visual_state as vs
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('strict coaching must not call the API')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)

    assert cmd_illustrate.main(['--state', '--coaching', 'strict']) == 0
    assert os.path.isfile(os.path.join(in_project, 'reference',
                                       'visual-state.csv'))
    checklist = os.path.join(in_project, 'working', 'coaching',
                             'visual-state-checklist.md')
    assert os.path.isfile(checklist)
    with open(checklist, encoding='utf-8') as f:
        body = f.read()
    assert 'proposes nothing' in body
    # The two rows the fixture ships must survive the strict write.
    assert len(vs.read_transitions(in_project)) == 2


def test_state_coach_writes_questions_and_makes_no_api_call(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('coach coaching must not call the API')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)

    assert cmd_illustrate.main(['--state', '--coaching', 'coach']) == 0
    brief = os.path.join(in_project, 'working', 'coaching',
                         'visual-state-brief.md')
    with open(brief, encoding='utf-8') as f:
        body = f.read()
    assert 'Questions to settle' in body
    # The two rules with tests pinning them must both be stated.
    assert 'at** its own scene' in body
    assert '{canon_id}-{aspect}' in body


def test_state_full_writes_proposed_transitions(in_project, monkeypatch):
    from storyforge import visual_state as vs
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '{"transitions": [{"entity": "nora-clothing", '
        '"from_scene": "act1-sc01", "state": "nightclothes, barefoot", '
        '"evidence": "held her breath"}]}'
    ))
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 0
    transitions = vs.read_transitions(in_project)
    assert any(t['entity'] == 'nora-clothing' for t in transitions)


def test_state_full_never_revises_an_existing_transition(in_project, monkeypatch):
    from storyforge import visual_state as vs
    vs.write_transitions(in_project, [{
        'entity': 'nora-clothing', 'from_scene': 'act1-sc01',
        'state': 'AUTHOR ORIGINAL', 'evidence': 'held her breath'}])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '{"transitions": [{"entity": "nora-clothing", '
        '"from_scene": "act1-sc01", "state": "MODEL GUESS", '
        '"evidence": "held her breath"}]}'
    ))
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 0
    kept = [t for t in vs.read_transitions(in_project)
            if t['entity'] == 'nora-clothing' and t['from_scene'] == 'act1-sc01']
    assert len(kept) == 1
    assert kept[0]['state'] == 'AUTHOR ORIGINAL'


def test_state_full_reports_the_proposal_it_discarded(in_project, monkeypatch, capsys):
    from storyforge import visual_state as vs
    vs.write_transitions(in_project, [{
        'entity': 'nora-clothing', 'from_scene': 'act1-sc01',
        'state': 'AUTHOR ORIGINAL', 'evidence': 'held her breath'}])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '{"transitions": [{"entity": "nora-clothing", '
        '"from_scene": "act1-sc01", "state": "MODEL GUESS", '
        '"evidence": "held her breath"}]}'
    ))
    cmd_illustrate.main(['--state', '--coaching', 'full'])
    assert 'the proposal was discarded' in capsys.readouterr().out


def test_state_full_appends_a_second_track_for_the_same_entity(in_project, monkeypatch):
    """The preserve key is (entity, from_scene), not entity — an entity that
    changes twice needs both rows."""
    from storyforge import visual_state as vs
    vs.write_transitions(in_project, [{
        'entity': 'nora-clothing', 'from_scene': 'act1-sc01',
        'state': 'nightclothes', 'evidence': 'held her breath'}])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '{"transitions": [{"entity": "nora-clothing", '
        '"from_scene": "act2-sc01", "state": "travel coat", '
        '"evidence": "She checked her compass"}]}'
    ))
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 0
    assert len(vs.read_transitions(in_project)) == 2


def test_state_full_without_a_key_is_an_error_not_a_silent_skip(in_project, capsys):
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 1
    assert 'ANTHROPIC_API_KEY is not set' in capsys.readouterr().out


def test_state_dry_run_writes_nothing(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('--dry-run must not call the API')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    before = open(os.path.join(in_project, 'reference', 'visual-state.csv'),
                  'rb').read()
    assert cmd_illustrate.main(['--state', '--coaching', 'full',
                               '--dry-run']) == 0
    assert '[dry-run]' in capsys.readouterr().out
    after = open(os.path.join(in_project, 'reference', 'visual-state.csv'),
                 'rb').read()
    assert before == after


def test_state_full_reports_an_unparseable_response(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: 'not json at all')
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 1
    assert 'could not parse transitions' in capsys.readouterr().out


def test_state_full_warns_when_a_proposal_cannot_be_checked(in_project, monkeypatch, capsys):
    """A model that invents an evidence quote must be caught, not trusted."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '{"transitions": [{"entity": "lamp", "from_scene": "act1-sc01", '
        '"state": "lit", "evidence": "a sentence the book does not contain"}]}'
    ))
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 0
    assert 'evidence_not_found' in capsys.readouterr().out


def test_state_writes_lf_only(in_project, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '{"transitions": [{"entity": "lamp", "from_scene": "act1-sc01", '
        '"state": "lit", "evidence": "held her breath"}]}'
    ))
    cmd_illustrate.main(['--state', '--coaching', 'full'])
    with open(os.path.join(in_project, 'reference', 'visual-state.csv'),
              'rb') as f:
        assert b'\r' not in f.read()


def test_state_entity_hints_prefer_canon_then_registries(in_project):
    hints = cmd_illustrate._state_entity_hints(in_project)
    sources = {h['source'] for h in hints}
    assert 'characters.csv' in sources
    ids = [h['canon_id'] for h in hints]
    assert len(ids) == len(set(ids)), 'a hint must not appear twice'


def test_state_prose_skips_undrafted_scenes_loudly(in_project, capsys):
    os.remove(os.path.join(in_project, 'scenes', 'act2-sc01.md'))
    prose, found = cmd_illustrate._state_scene_prose(
        in_project, ['act1-sc01', 'act2-sc01'])
    assert found == 1
    assert 'act2-sc01' not in prose
    assert 'has no file in scenes/' in capsys.readouterr().out


def test_state_prose_strips_markers(in_project):
    path = os.path.join(in_project, 'scenes', 'act1-sc01.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text + '\n' + ill.marker_for('lantern-vigil') + '\n')
    prose, _found = cmd_illustrate._state_scene_prose(in_project, ['act1-sc01'])
    assert '![[illus:' not in prose


def test_parse_state_response_drops_rows_missing_a_field():
    rows, status = pi.parse_state_response(json.dumps({'transitions': [
        {'entity': 'a', 'from_scene': 's1', 'state': 'x', 'evidence': 'q'},
        {'entity': 'b', 'from_scene': 's1', 'state': 'x'},
    ]}))
    assert status == 'ok'
    assert [r['entity'] for r in rows] == ['a']


def test_parse_state_response_distinguishes_its_four_failure_modes():
    assert pi.parse_state_response('nope')[1] == 'no_json'
    assert pi.parse_state_response('{"other": []}')[1] == 'no_transitions_key'
    # An empty list is an answer — the model read the book and found nothing
    # whose visible state changes. Reporting it as unparseable exited non-zero.
    assert pi.parse_state_response('{"transitions": []}')[1] == 'empty'
    assert pi.parse_state_response(
        '{"transitions": [{"entity": "a"}]}')[1] == 'unusable'


def test_state_full_with_no_drafted_prose_is_an_error(in_project, monkeypatch, capsys):
    """Transitions are extracted from prose. With none, saying "0 added" would
    read as "nothing changes in this book"."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    def _boom(*a, **k):
        raise AssertionError('no prose means no call')
    monkeypatch.setattr(cmd_illustrate, '_invoke', _boom)
    for name in os.listdir(os.path.join(in_project, 'scenes')):
        os.remove(os.path.join(in_project, 'scenes', name))

    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 1
    assert 'No drafted scenes to read' in capsys.readouterr().out


def test_state_full_reports_an_empty_api_response(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: '')
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 1
    assert 'no response from the API' in capsys.readouterr().out


def test_state_entity_hints_dedupe_canon_against_the_registry(in_project):
    """A canon file and a registry row for one entity must yield one hint, and
    the canon file wins — its canon_id is the slug the log must match."""
    from test_canon_files import write_canon
    write_canon(in_project, 'characters/dorren-hayle.md', 'dorren-hayle',
                canon_type='character')
    hints = cmd_illustrate._state_entity_hints(in_project)
    matching = [h for h in hints if h['canon_id'] == 'dorren-hayle']
    assert len(matching) == 1
    assert matching[0]['source'] == 'canon'


def test_state_renderers_say_so_when_there_is_nothing_to_seed_from():
    """An empty table is worse than a sentence: it reads as "no candidates
    exist" rather than "nothing has been recorded yet"."""
    brief = pi.render_state_brief(hints=[], existing=[], scene_ids=[])
    assert 'Name the' in brief
    assert 'No transitions recorded yet' in brief
    assert 'No scenes in reading order yet' in brief
    checklist = pi.render_state_checklist(hints=[], existing=[], scene_ids=[])
    assert 'No transitions recorded yet' in checklist


def test_parse_state_response_ignores_non_dict_rows_and_wrong_shapes():
    assert pi.parse_state_response('[1, 2, 3]')[1] == 'no_transitions_key'
    assert pi.parse_state_response('{"transitions": "nope"}')[1] == (
        'no_transitions_key')
    rows, status = pi.parse_state_response(json.dumps({'transitions': [
        'a string, not a row',
        {'entity': 'a', 'from_scene': 's1', 'state': 'x', 'evidence': 'q'},
    ]}))
    assert status == 'ok'
    assert [r['entity'] for r in rows] == ['a']


# ============================================================================
# --state: an empty proposal, an invented scene, and strict's file discipline
# ============================================================================

def test_state_full_treats_no_proposals_as_an_answer_not_a_parse_error(
        in_project, monkeypatch, capsys):
    """A model that read the book and found nothing whose visible state changes
    is answering. Exiting 1 told the author their response was unreadable."""
    from storyforge import visual_state as vs
    before = open(os.path.join(in_project, 'reference', 'visual-state.csv'),
                  'rb').read()
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda *a, **k: '{"transitions": []}')
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 0
    out = capsys.readouterr().out
    assert 'proposed no transitions' in out
    assert 'could not parse' not in out
    assert open(os.path.join(in_project, 'reference', 'visual-state.csv'),
                'rb').read() == before
    assert len(vs.read_transitions(in_project)) == 2


def test_state_full_refuses_a_proposal_naming_a_scene_that_does_not_exist(
        in_project, monkeypatch, capsys):
    """That row is the model's, not the author's, so the never-revise rule does
    not protect it — and writing it puts a blocking error in the log on purpose."""
    from storyforge import visual_state as vs
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '{"transitions": [{"entity": "lamp", "from_scene": "invented-scene", '
        '"state": "lit", "evidence": "held her breath"}]}'
    ))
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 0
    assert not [t for t in vs.read_transitions(in_project)
                if t['from_scene'] == 'invented-scene']
    out = capsys.readouterr().out
    assert 'discarding the proposal' in out
    assert 'state_unknown_scene' not in out


def test_state_full_keeps_a_proposal_on_a_drafted_but_unmapped_scene(
        in_project, monkeypatch):
    """new-x1 is active in scenes.csv and absent from the chapter map — the row is
    fine, the map is incomplete, so the proposal must survive."""
    from storyforge import visual_state as vs
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '{"transitions": [{"entity": "lamp", "from_scene": "new-x1", '
        '"state": "lit", "evidence": "The maps don\'t lie"}]}'
    ))
    assert cmd_illustrate.main(['--state', '--coaching', 'full']) == 0
    assert [t for t in vs.read_transitions(in_project)
            if t['from_scene'] == 'new-x1']


def test_state_strict_leaves_an_existing_log_byte_identical(in_project, capsys):
    """Rewriting through read/write would drop a row with an empty entity and any
    column the author added beyond STATE_COLUMNS."""
    path = os.path.join(in_project, 'reference', 'visual-state.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('entity|from_scene|state|evidence|author_note\r\n')
        f.write('lamp|act1-sc01|lit|held her breath|keep this column\n')
    before = open(path, 'rb').read()
    assert cmd_illustrate.main(['--state', '--coaching', 'strict']) == 0
    assert open(path, 'rb').read() == before
    assert 'left untouched' in capsys.readouterr().out


def test_state_strict_creates_a_header_only_log_when_none_exists(in_project):
    from storyforge import visual_state as vs
    os.remove(os.path.join(in_project, 'reference', 'visual-state.csv'))
    assert cmd_illustrate.main(['--state', '--coaching', 'strict']) == 0
    with open(os.path.join(in_project, 'reference', 'visual-state.csv'),
              encoding='utf-8') as f:
        assert f.read() == '|'.join(vs.STATE_COLUMNS) + '\n'


def test_parse_state_response_logs_every_dropped_row(capsys):
    rows, status = pi.parse_state_response(json.dumps({'transitions': [
        {'entity': 'a', 'from_scene': 's1', 'state': 'x', 'evidence': 'q'},
        {'entity': 'b', 'from_scene': 's1'},
        7,
    ]}))
    assert status == 'ok' and len(rows) == 1
    out = capsys.readouterr().out
    assert 'row 2 is missing state, evidence' in out
    assert 'row 3 is not an object (int)' in out


# ============================================================================
# #309 — --prompts and a state_override that did not land as written
# ============================================================================

def test_prompts_refuses_a_prose_state_override(in_project, capsys):
    """Keyed on a sentence-as-entity-key, not on "nothing applied".

    On the real cell this was filed about, one clause *did* apply — under a
    nonsense key — so a nothing-applied test alone would have let it through and
    generated against the state the author meant to replace.
    """
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(
        state_override=('The instant AFTER extinction, which a10 does not '
                        'describe: the Great Lamp dark; EXACTLY FIVE alive'))])

    rc = cmd_illustrate.main(['--prompts', '--coaching', 'strict'])

    out = capsys.readouterr().out
    assert rc == 1, 'a prose override must refuse before anything is spent'
    assert 'did not land as written' in out
    # Two clauses: the colon-bearing fragment applied under a sentence key, and
    # `EXACTLY FIVE alive` was dropped for having no colon.
    assert '1 of 2 clauses applied, 1 skipped' in out


def test_prompts_reports_the_clause_count(in_project, capsys):
    """One line with a count — the signal the issue's author said would alone
    have caught this. Two per-clause warnings in a stream of reference-exclusion
    warnings did not."""
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(
        state_override='no-colon-here;lantern:lit from below')])

    cmd_illustrate.main(['--prompts', '--coaching', 'strict'])

    assert '1 of 2 clauses applied, 1 skipped' in capsys.readouterr().out


def test_prompts_accepts_an_override_for_an_untracked_entity(in_project,
                                                            capsys):
    """The legitimate case the refusal must not break.

    `state_for_row` deliberately applies an override for an entity the matrix
    does not track, which is why the refusal keys on a prose key rather than on
    "no key matches a tracked entity" as the issue proposed.
    """
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(
        state_override='one-off-prop:cracked down one side')])

    rc = cmd_illustrate.main(['--prompts', '--coaching', 'strict'])

    assert rc == 0
    assert 'did not land as written' not in capsys.readouterr().out

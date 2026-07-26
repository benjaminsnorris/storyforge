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
from storyforge import prompts_illustrate as pi
from illustration_helpers import (
    SAMPLE_DIRECTION, SCENE, SCENE_ADVERSARIAL, make_png, plan_row,
    truncated_png, write_csv, write_direction_file, write_scene,
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


def write_direction(project_dir, sections):
    """Write a direction document from {heading: body}."""
    path = ill.direction_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = '\n\n'.join(f'## {name}\n\n{text}'
                       for name, text in sections.items())
    with open(path, 'w') as f:
        f.write(f'# Illustration art direction\n\n{body}\n')
    return path


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


def test_prompts_full_writes_body_and_appends_new_anchors(in_project, monkeypatch):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row()])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '### Scene\n\nA cold street at night.\n\n'
        '### Subject\n\nA woman at a lit sill.\n\n'
        'ANCHORS\n- Dorren Hayle — a spare woman of fifty in a grey coat\n'
    ))

    assert cmd_illustrate.main(['--prompts', '--coaching', 'full']) == 0

    row = read_plan_map(in_project)['lantern-vigil']
    with open(os.path.join(in_project, row['prompt_file'])) as f:
        content = f.read()
    assert 'A cold street at night' in content
    # The anchor block is lifted out of the body, not left in the prompt.
    assert 'ANCHORS' not in content
    # A proposed anchor lands in the direction document for the author to review.
    anchors = ill.read_continuity_anchors(in_project)
    assert anchors['Dorren Hayle'] == 'a spare woman of fifty in a grey coat'


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
    """More than a handful and the model starts averaging them."""
    rows = []
    for i in range(8):
        make_png(os.path.join(in_project, ill.ILLUSTRATIONS_SUBDIR,
                              f'prior-{i}.png'), 8, 8)
        rows.append(plan_row(id=f'prior-{i}', status='ingested',
                             asset_file=ill.default_asset_rel(f'prior-{i}')))
    ill.write_plan(in_project, rows + [plan_row()])

    refs = cmd_illustrate._references_for(in_project, 'lantern-vigil')
    assert len(refs) == cmd_illustrate._MAX_REFERENCES


def test_scene_excerpt_strips_markers(in_project):
    write_scene(in_project, 'vigil', ill.insert_marker(SCENE, plan_row())['text'])
    excerpt = cmd_illustrate._scene_excerpt(in_project, plan_row())
    assert '![[illus:' not in excerpt
    assert 'She set it on the sill' in excerpt


def test_scene_excerpt_handles_a_missing_scene(in_project):
    assert cmd_illustrate._scene_excerpt(
        in_project, plan_row(scene_id='nowhere')) == '(scene file not found)'


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
        row=plan_row(), body='### Scene\n\nA street.\n', references=[],
        aspect='portrait',
    )
    assert content.count('PORTRAIT orientation') >= 1
    assert '**Aspect:** portrait' in content
    assert 'no text, no letters, no words, no typography' in content
    assert '| Attempt | Model |' in content


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
        '- **Vell** — a boy with ink-stained cuffs\n'
    )
    assert 'ANCHORS' not in body
    assert anchors == {
        'Dorren Hayle': 'a spare woman in grey',
        'Vell': 'a boy with ink-stained cuffs',
    }


def test_continuity_anchors_round_trip(project_dir):
    write_direction(project_dir, {
        ill.ANCHORS_SECTION: '### Dorren\n\na spare woman in grey',
    })
    assert ill.read_continuity_anchors(project_dir) == {
        'Dorren': 'a spare woman in grey'}


def test_continuity_anchors_collapse_multi_paragraph_bodies(project_dir):
    """A real anchor is a paragraph, not a phrase."""
    write_direction(project_dir, {
        ill.ANCHORS_SECTION: (
            '### Dorren\n\nTen years old; tall for her age.\n\n'
            'Navy pyjamas on the first night.\n\n'
            '### Vell\n\nA boy with ink-stained cuffs.'
        ),
    })
    anchors = ill.read_continuity_anchors(project_dir)
    assert anchors['Dorren'] == (
        'Ten years old; tall for her age. Navy pyjamas on the first night.')
    assert anchors['Vell'] == 'A boy with ink-stained cuffs.'


def test_append_anchor_stubs_never_overwrites_an_existing_anchor(project_dir):
    """Likeness continuity depends on the anchor staying byte-identical."""
    pi.append_anchor_stubs(project_dir, {'Dorren': 'original description'})
    added = pi.append_anchor_stubs(project_dir, {
        'Dorren': 'revised description', 'Vell': 'a boy'})

    assert added == ['Vell']
    anchors = ill.read_continuity_anchors(project_dir)
    assert anchors['Dorren'] == 'original description'
    assert anchors['Vell'] == 'a boy'


def test_append_anchor_stubs_is_case_insensitive(project_dir):
    pi.append_anchor_stubs(project_dir, {'Dorren': 'original'})
    assert pi.append_anchor_stubs(project_dir, {'dorren': 'again'}) == []


def test_append_anchor_stubs_skips_empty_values(project_dir):
    assert pi.append_anchor_stubs(project_dir, {'Nameless': '', '': 'x'}) == []


def test_append_anchor_stubs_preserves_other_sections(project_dir):
    write_direction(project_dir, {
        'Format': 'Full-color photorealism.',
        ill.ANCHORS_SECTION: '### Dorren\n\na spare woman in grey',
    })
    pi.append_anchor_stubs(project_dir, {'Vell': 'a boy'})

    direction = ill.read_direction(project_dir)
    assert direction['Format'] == 'Full-color photorealism.'
    assert set(ill.read_continuity_anchors(project_dir)) == {'Dorren', 'Vell'}


def test_read_continuity_anchors_with_no_document(project_dir):
    assert ill.read_continuity_anchors(project_dir) == {}
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


def build_manifest(project_dir):
    from storyforge.assembly import generate_publish_manifest
    freshen_chapter_map(project_dir)
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
    assert manifest['assets'] == [{
        'key': 'lantern-vigil', 'role': 'illustration',
        'sha256': 'a' * 64, 'extension': 'png',
        'width': 40, 'height': 60,
        'alt_text': 'A woman waits at a lit window',
    }]


def test_manifest_omits_assets_when_no_scene_is_illustrated(project_dir):
    manifest = build_manifest(project_dir)
    assert 'assets' not in manifest
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

    assert 'assets' not in manifest
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

def test_direction_strict_writes_a_template_without_an_api_key(in_project):
    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0

    path = ill.direction_path(in_project)
    assert os.path.isfile(path)
    with open(path) as f:
        content = f.read()
    for section in ill.DIRECTION_SECTIONS:
        assert f'## {section}' in content
    assert '_Required:' in content
    # A strict scaffold proposes nothing, so every section still needs the author.
    assert ill.missing_direction_sections(in_project) == \
        list(ill.DIRECTION_SECTIONS)


def test_direction_coach_template_asks_questions(in_project):
    assert cmd_illustrate.main(['--direction', '--coaching', 'coach']) == 0
    with open(ill.direction_path(in_project)) as f:
        content = f.read()
    assert 'notice missing' in content          # visual-promise question
    assert 'obviously from the same' in content  # recurring-language question
    assert '_Required:' not in content


def test_direction_template_stubs_an_anchor_per_registry_entry(in_project):
    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0
    with open(ill.direction_path(in_project)) as f:
        content = f.read()
    # The fixture has characters and locations; both need anchors.
    assert '### Dorren Hayle' in content
    assert 'height, age, exact colors' in content


def test_direction_full_without_an_api_key_fails(in_project, capsys):
    assert cmd_illustrate.main(['--direction', '--coaching', 'full']) == 1
    out = capsys.readouterr().out
    assert 'ANTHROPIC_API_KEY is not set' in out
    assert '--coaching coach' in out       # names the offline alternative


def test_direction_full_writes_the_model_output(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k: (
        '## Format\n\nFull-color photorealism for ages 6-8.\n\n'
        '## Visual promise\n\nThe ordinary world feels real.\n\n'
        '## Recurring visual language\n\nWarm amber against cool blue.\n\n'
        '## Content limits\n\nNever horror imagery.\n\n'
        '## Continuity anchors\n\n### Leo\n\nTen years old; tall for his age.\n'
    ))

    assert cmd_illustrate.main(['--direction', '--coaching', 'full']) == 0

    assert ill.missing_direction_sections(in_project) == []
    assert ill.read_continuity_anchors(in_project) == {
        'Leo': 'Ten years old; tall for his age.'}
    out = capsys.readouterr().out
    assert 'continuity anchors: 1' in out
    assert 'Read it before running --prompts' in out


def test_direction_reports_incomplete_sections(in_project, monkeypatch, capsys):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr(cmd_illustrate, '_invoke', lambda *a, **k:
                        '## Format\n\nPhotorealism.\n')

    cmd_illustrate.main(['--direction', '--coaching', 'full'])
    assert 'needs your input' in capsys.readouterr().out


def test_direction_does_not_clobber_a_complete_document(in_project, capsys):
    write_direction_file(in_project, SAMPLE_DIRECTION)

    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0
    assert 'already written' in capsys.readouterr().out
    with open(ill.direction_path(in_project)) as f:
        assert 'cinematic photorealistic' in f.read()


def test_direction_reports_gaps_in_an_existing_document(in_project, capsys):
    write_direction_file(in_project, '# D\n\n## Format\n\nPhotorealism.\n')

    assert cmd_illustrate.main(['--direction', '--coaching', 'strict']) == 0
    out = capsys.readouterr().out
    assert 'sections are empty or still placeholder' in out
    assert 'Continuity anchors' in out
    # And it must not overwrite what is there.
    with open(ill.direction_path(in_project)) as f:
        assert 'Photorealism.' in f.read()


def test_direction_dry_run_writes_nothing(in_project, capsys):
    assert cmd_illustrate.main(['--direction', '--dry-run',
                                '--coaching', 'strict']) == 0
    assert '[dry-run] would write' in capsys.readouterr().out
    assert not os.path.isfile(ill.direction_path(in_project))


def test_direction_reaches_the_art_direction_prompt(in_project, monkeypatch):
    """The whole point of the document: every prompt carries it."""
    write_direction_file(in_project, SAMPLE_DIRECTION)
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(canon_refs='Leo')])
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
    # Anchors are rendered separately from the rest of the direction.
    assert 'Ten years old' in prompt


def test_prompts_narrow_anchors_to_what_the_illustration_shows(in_project,
                                                              monkeypatch):
    write_direction_file(in_project, SAMPLE_DIRECTION)
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(canon_refs='Murkwolves')])
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    seen = {}
    monkeypatch.setattr(cmd_illustrate, '_invoke',
                        lambda pd, prompt, op, **kw: (
                            seen.update(prompt=prompt) or '### Scene\n\nX.\n'))
    cmd_illustrate.main(['--prompts', '--coaching', 'full'])

    anchors_block = seen['prompt'].split('## Character anchors')[1]
    assert 'Murkwolves' in anchors_block
    assert 'Ten years old' not in anchors_block   # Leo is not in this frame


def test_relevant_anchors_falls_back_to_all_when_none_named():
    anchors = {'Leo': 'a boy', 'Nora': 'a girl'}
    assert cmd_illustrate._relevant_anchors(anchors, plan_row()) == anchors


def test_relevant_anchors_falls_back_when_nothing_matches():
    anchors = {'Leo': 'a boy'}
    row = plan_row(canon_refs='Someone Unrecorded')
    assert cmd_illustrate._relevant_anchors(anchors, row) == anchors


# ============================================================================
# --review
# ============================================================================

def test_review_writes_the_sequence_checklist(in_project):
    write_direction_file(in_project, SAMPLE_DIRECTION)
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
    assert '- [ ] **Leo**' in content              # anchors to check against
    assert '1. [x] `LF-01`' in content             # rendered
    assert '2. [ ] `LF-02`' in content             # pending
    assert 'locks: Leo, Murkwolves' in content


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
        row=plan_row(layout='double_page'), body='### Scene\n\nA street.\n',
        references=[], aspect=pi.aspect_for_row(plan_row(layout='double_page')),
    )
    assert 'LANDSCAPE orientation' in content


def test_layout_reaches_the_art_direction_prompt():
    prompt = pi.build_art_direction_request(
        row=plan_row(layout='double_page'), scene_excerpt='x',
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
     {'Jean-Luc': 'a boy of 9, 130 cm'}),
    ('- Marie-Claire – a woman of 40', {'Marie-Claire': 'a woman of 40'}),
    ('- Ember: an elderly Lantern woman',
     {'Ember': 'an elderly Lantern woman'}),
    ('- Leo - ten years old', {'Leo': 'ten years old'}),
    ('- **Wick** — a copper-haired Lantern child',
     {'Wick': 'a copper-haired Lantern child'}),
])
def test_anchor_lines_with_hyphenated_names_parse_whole(line, expected):
    """Regression: the separator class included a bare hyphen, so `Jean-Luc`
    became {'Jean': 'Luc — …'}. The mangled name was then written into the
    direction document as canonical, never revised, and stopped matching
    canon_refs — so the anchor silently left every prompt."""
    _, anchors = pi.split_anchor_block(f'### Scene\n\nA room.\n\nANCHORS\n{line}\n')
    assert anchors == expected


@pytest.mark.parametrize('marker', ['ANCHORS', 'ANCHORS:', '**ANCHORS**'])
def test_anchor_block_marker_variants(marker):
    """A decorated marker used to lose every anchor AND leave the block in the
    prompt body, which the author pastes into the image model."""
    body, anchors = pi.split_anchor_block(
        f'### Scene\n\nA room.\n\n{marker}\n- Wick — a grey tabby\n')
    assert anchors == {'Wick': 'a grey tabby'}
    assert 'ANCHORS' not in body


def test_split_anchor_block_removes_a_dangling_code_fence():
    """The request demonstrates the block inside a fence, so the model emits
    one; cutting at the ANCHORS line left the opening fence behind and
    corrupted every following section of the prompt file."""
    body, anchors = pi.split_anchor_block(
        '### Scene\n\nA dark room.\n\n```\nANCHORS\n- Wick — a cat\n```\n')
    assert anchors == {'Wick': 'a cat'}
    assert '```' not in body
    assert body.endswith('A dark room.')


def test_unparsed_anchor_lines_are_reported():
    body_text = ('### Scene\n\nA room.\n\nANCHORS\n'
                 '- Wick — a grey tabby\n'
                 '- just a name with no description\n'
                 '- Nameless — \n')
    assert pi.split_anchor_block(body_text)[1] == {'Wick': 'a grey tabby'}
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
    assert 'did not parse as' in capsys.readouterr().out


def test_anchors_section_is_read_case_insensitively(project_dir):
    """A model asked for `## Continuity anchors` sometimes writes
    `## Continuity Anchors`; a case-sensitive lookup silently returned nothing,
    so the author's anchors were invisible to every prompt."""
    write_direction_file(project_dir,
                         '# D\n\n## Continuity Anchors\n\n### Mara\n\n'
                         'Eleven years old, black braid.\n')
    assert ill.read_continuity_anchors(project_dir) == {
        'Mara': 'Eleven years old, black braid.'}
    assert ill.ANCHORS_SECTION not in ill.missing_direction_sections(project_dir)


def test_append_does_not_create_a_second_anchors_section(project_dir):
    """Appending under a differently-cased heading used to add a *second*
    section, permanently orphaning everything under the first — and the
    missing-sections warning that would have caught it disappeared, because the
    new section was non-empty."""
    write_direction_file(project_dir,
                         '# D\n\n## Continuity Anchors\n\n### Mara\n\n'
                         'Eleven years old.\n')

    pi.append_anchor_stubs(project_dir, {'Wick': 'a grey tabby cat'})

    assert len(ill.anchors_section_headings(project_dir)) == 1
    assert sorted(ill.read_continuity_anchors(project_dir)) == ['Mara', 'Wick']


def test_the_anchors_phrase_in_prose_does_not_satisfy_the_section_check(
        project_dir):
    """A substring test matched the phrase in ordinary prose, so the stubs were
    appended into whatever section came last — and fed to the image model as,
    say, a content limit."""
    write_direction_file(
        project_dir,
        '# D\n\n## Format\n\nSee the Continuity anchors below for the cast.\n')

    pi.append_anchor_stubs(project_dir, {'Wick': 'a grey tabby cat'})

    assert ill.read_continuity_anchors(project_dir) == {
        'Wick': 'a grey tabby cat'}
    assert ill.read_direction(project_dir)['Format'].startswith('See the')


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


def test_ids_does_not_reprompt_a_superseded_row(in_project, capsys):
    write_scene(in_project, 'vigil', SCENE)
    ill.write_plan(in_project, [plan_row(status='superseded')])
    assert cmd_illustrate.main(['--prompts', '--ids', 'lantern-vigil']) == 1


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

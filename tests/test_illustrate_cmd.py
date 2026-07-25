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
from tests.test_illustrations import (
    SCENE, make_png, plan_row, write_csv, write_scene,
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
    assert 'not a readable PNG' in capsys.readouterr().out
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
    from tests.test_illustrations import make_webp
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


def test_prompts_full_writes_body_and_persists_anchors(in_project, monkeypatch):
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
    anchors = pi.read_character_anchors(in_project)
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
    joined = '\n'.join(refs)
    assert 'cover-illustration.png' in joined
    assert 'earlier.png' in joined
    # An illustration never references itself.
    assert 'lantern-vigil.png' not in joined


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


def test_character_anchors_round_trip(project_dir):
    pi.write_character_anchors(project_dir, {'Dorren': 'a spare woman in grey'})
    assert pi.read_character_anchors(project_dir) == {
        'Dorren': 'a spare woman in grey'}


def test_character_anchors_never_overwrite_an_existing_string(project_dir):
    """Likeness continuity depends on the anchor staying byte-identical."""
    pi.write_character_anchors(project_dir, {'Dorren': 'original description'})
    pi.write_character_anchors(project_dir, {'Dorren': 'revised description',
                                            'Vell': 'a boy'})
    anchors = pi.read_character_anchors(project_dir)
    assert anchors['Dorren'] == 'original description'
    assert anchors['Vell'] == 'a boy'


def test_read_character_anchors_with_no_file(project_dir):
    assert pi.read_character_anchors(project_dir) == {}


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


def test_validate_command_fails_on_a_blocking_finding(project_dir, monkeypatch):
    from storyforge import cmd_validate
    monkeypatch.chdir(project_dir)
    write_scene(project_dir, 'vigil', 'One.\n\n![[illus:ghost]]\n\nTwo.\n')
    ill.write_plan(project_dir, [plan_row(status='planned')])

    with pytest.raises(SystemExit) as exc:
        cmd_validate.main(['--quiet'])
    assert exc.value.code == 1


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

MARKED = ill.insert_marker(SCENE, plan_row())['text']


@pytest.mark.parametrize('module,func', [
    ('scoring_passive', 'score_avoid_passive'),
    ('scoring_adverbs', 'score_avoid_adverbs'),
    ('scoring_weather', 'score_no_weather_dreams'),
    ('scoring_rhythm', 'score_sentence_as_thought'),
])
def test_deterministic_scorers_ignore_markers(module, func):
    import importlib
    scorer = getattr(importlib.import_module(f'storyforge.{module}'), func)
    assert scorer(MARKED) == scorer(SCENE)


def test_economy_scorer_ignores_markers():
    from storyforge.scoring_economy import score_economy_clarity
    assert score_economy_clarity(MARKED) == score_economy_clarity(SCENE)


@pytest.mark.parametrize('detector', [
    'detect_passive_voice', 'detect_adverbs', 'detect_filler_phrases',
])
def test_prose_detectors_ignore_markers(detector):
    from storyforge import prose_analysis
    fn = getattr(prose_analysis, detector)
    assert fn(MARKED) == fn(SCENE)


def test_dialogue_extraction_ignores_markers():
    from storyforge.prose_analysis import extract_dialogue
    assert extract_dialogue(MARKED) == extract_dialogue(SCENE)


def test_a_marker_does_not_read_as_a_weather_opening():
    """scene_open placement puts a marker on line 1 — it must not be the opening."""
    from storyforge.scoring_weather import score_no_weather_dreams
    opened = ill.insert_marker(SCENE, plan_row(placement='scene_open',
                                              anchor=''))['text']
    assert score_no_weather_dreams(opened) == score_no_weather_dreams(SCENE)


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


def test_manifest_content_html_is_unchanged_by_illustrations(project_dir):
    """The regression test for the whole design.

    Bookshelf derives highlight offsets from the scene's visible text. If an
    illustration changed content_html, every downstream highlight in that scene
    would silently re-anchor or orphan.
    """
    before = build_manifest(project_dir)

    scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(scene_path) as f:
        original = f.read()
    row = plan_row(scene_id='act1-sc01', anchor='brass calipers',
                   status='ingested', sha256='a' * 64,
                   asset_file=ill.default_asset_rel('lantern-vigil'))
    ill.write_plan(project_dir, [row])
    with open(scene_path, 'w') as f:
        f.write(ill.insert_marker(original, row)['text'])

    after = build_manifest(project_dir)

    def scene_of(manifest):
        return next(s for ch in manifest['chapters'] for s in ch['scenes']
                    if s['slug'] == 'act1-sc01')

    assert scene_of(after)['content_html'] == scene_of(before)['content_html']
    assert scene_of(after)['word_count'] == scene_of(before)['word_count']


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


def test_manifest_warns_about_a_marked_but_unrendered_illustration(project_dir,
                                                                   capsys):
    scene_path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
    with open(scene_path) as f:
        original = f.read()
    row = plan_row(scene_id='act1-sc01', anchor='brass calipers',
                   status='planned')
    ill.write_plan(project_dir, [row])
    with open(scene_path, 'w') as f:
        f.write(ill.insert_marker(original, row)['text'])

    manifest = build_manifest(project_dir)
    assert 'assets' not in manifest
    assert 'will not publish' in capsys.readouterr().out


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

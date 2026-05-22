"""Tests for cmd_revise_gn — GN findings-driven panel-script revision."""

import json
import os

import pytest

from storyforge.csv_cli import get_field, update_field


# Initial draft (mimics what cmd_write_gn would have written). Two pages,
# one over-long balloon, one too-sparse composition — typical findings shape.
INITIAL_DRAFT = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1** (full bleed)
Cartographer at desk.

- CAPTION: *The map remained blank, as it always did at the start of these long nights when even the lamp seemed reluctant to throw its weak yellow light across the heavy parchment.*
- CARTOGRAPHER: It always begins this way.

---

## Page 2 — 4-GRID ⟵ PAGE-TURN REVEAL

**Panel 1** (top-left)
Hand close.

- CAPTION: *Forty years of practice.*

**Panel 2** (top-right)
Pen touches paper.

**Panel 3** (bottom-left)
Line appears.

- SFX: Scritch.

**Panel 4** (bottom-right)
He stares at the result.

- CARTOGRAPHER: No.
"""


# What we expect the API to return after revision — same structure, but the
# over-long balloon has been compressed and the sparse composition fleshed out.
REVISED_SCRIPT = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1** (full bleed)
The cartographer at his desk. Blank parchment seen close, lamp glow on paper
casting long shadows across the room. A trembling hand hovers above.

- CAPTION: *The map remained blank.*
- CARTOGRAPHER: It always begins this way.

---

## Page 2 — 4-GRID ⟵ PAGE-TURN REVEAL

**Panel 1** (top-left)
Close on his trembling hand above the parchment. Knuckles white, ink ready.

- CAPTION: *Forty years of practice.*

**Panel 2** (top-right)
The pen touches paper for the first time tonight.

**Panel 3** (bottom-left)
A thin line appears, hesitant against the blank field.

- SFX: Scritch.

**Panel 4** (bottom-right)
He stares at what he has made, breath caught, the lamp guttering low.

- CARTOGRAPHER: No.
"""


def _make_fake_invoke(response_text):
    """Build an invoke_to_file replacement that returns response_text."""
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': response_text}],
            'usage': {
                'input_tokens': 500, 'output_tokens': 800,
                'cache_read_input_tokens': 0,
                'cache_creation_input_tokens': 0,
            },
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response
    return fake


def _seed_draft(project_dir, scene_id, draft_text=INITIAL_DRAFT,
                page_count=2, panel_count=5):
    """Write a drafted scene + mark CSVs as drafted."""
    scene_path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
    os.makedirs(os.path.dirname(scene_path), exist_ok=True)
    with open(scene_path, 'w', encoding='utf-8') as f:
        f.write(draft_text)
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    update_field(scenes_csv, scene_id, 'status', 'drafted')
    update_field(scenes_csv, scene_id, 'page_count', str(page_count))
    update_field(scenes_csv, scene_id, 'panel_count', str(panel_count))


def _seed_score_findings(project_dir, scene_id, findings):
    """Write working/scores/latest/{id}.json with given findings."""
    path = os.path.join(project_dir, 'working', 'scores', 'latest', f'{scene_id}.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'scene_id': scene_id,
            'scored_at': '2026-05-22T00:00:00Z',
            'scores': {},
            'overall_score': 0.6,
            'findings': findings,
        }, f)


def _seed_eval_findings(project_dir, scene_id, findings):
    """Write working/evaluations/latest/{id}.json with given findings."""
    path = os.path.join(project_dir, 'working', 'evaluations', 'latest', f'{scene_id}.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'scene_id': scene_id,
            'evaluated_at': '2026-05-22T00:00:00Z',
            'personas_run': ['panel-composition', 'dialogue'],
            'findings': findings,
        }, f)


# ---------------------------------------------------------------------------
# Core revision flow
# ---------------------------------------------------------------------------

def test_revise_one_scene_with_findings(project_dir_gn, monkeypatch):
    """Revise a drafted scene that has findings → script updated, status='revised'."""
    monkeypatch.chdir(project_dir_gn)
    _seed_draft(project_dir_gn, 'the-blank-page')
    _seed_score_findings(project_dir_gn, 'the-blank-page', [
        {'kind': 'balloon_too_long', 'detail': 'Page 1 panel 1 CAPTION: 33 words',
         'severity': 'high'},
        {'kind': 'composition_too_sparse', 'detail': 'Page 1 panel 1: 4 words',
         'severity': 'medium'},
    ])

    from storyforge import api, cmd_revise_gn
    fake = _make_fake_invoke(REVISED_SCRIPT)
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_revise_gn, 'invoke_to_file', fake)

    cmd_revise_gn.main(['the-blank-page', '--no-branch'])

    scene_path = os.path.join(project_dir_gn, 'scenes', 'the-blank-page.md')
    content = open(scene_path).read()
    assert content == REVISED_SCRIPT, 'scene file should be overwritten with revised script'

    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    assert get_field(scenes_csv, 'the-blank-page', 'status') == 'revised'
    assert get_field(scenes_csv, 'the-blank-page', 'page_count') == '2'
    assert get_field(scenes_csv, 'the-blank-page', 'panel_count') == '5'


def test_revise_loads_both_score_and_eval_findings(project_dir_gn, monkeypatch):
    """The prompt receives both deterministic + persona findings."""
    monkeypatch.chdir(project_dir_gn)
    _seed_draft(project_dir_gn, 'the-blank-page')
    _seed_score_findings(project_dir_gn, 'the-blank-page', [
        {'kind': 'balloon_too_long', 'detail': '33 words', 'severity': 'high'},
    ])
    _seed_eval_findings(project_dir_gn, 'the-blank-page', [
        {'persona': 'panel-composition', 'severity': 'medium',
         'message': 'composition too sparse on page 1', 'page': 1, 'panel': 1},
    ])

    captured = {}

    def capture_and_respond(prompt, model, log_file, **kwargs):
        captured['prompt'] = prompt
        return _make_fake_invoke(REVISED_SCRIPT)(prompt, model, log_file, **kwargs)

    from storyforge import api, cmd_revise_gn
    monkeypatch.setattr(api, 'invoke_to_file', capture_and_respond)
    monkeypatch.setattr(cmd_revise_gn, 'invoke_to_file', capture_and_respond)

    cmd_revise_gn.main(['the-blank-page', '--no-branch'])

    prompt = captured['prompt']
    assert 'Deterministic findings' in prompt
    assert 'balloon_too_long' in prompt
    assert 'panel-composition' in prompt
    assert 'composition too sparse on page 1' in prompt
    assert 'page 1, panel 1' in prompt


# ---------------------------------------------------------------------------
# Skip behavior
# ---------------------------------------------------------------------------

def test_revise_skips_scenes_with_no_findings_by_default(project_dir_gn, monkeypatch):
    """Without findings, revise should refuse rather than polish blindly."""
    monkeypatch.chdir(project_dir_gn)
    _seed_draft(project_dir_gn, 'the-blank-page')
    # No findings seeded.

    calls = []

    def track(*args, **kwargs):
        calls.append(args)
        return _make_fake_invoke(REVISED_SCRIPT)(*args, **kwargs)

    from storyforge import api, cmd_revise_gn
    monkeypatch.setattr(api, 'invoke_to_file', track)
    monkeypatch.setattr(cmd_revise_gn, 'invoke_to_file', track)

    cmd_revise_gn.main(['the-blank-page', '--no-branch'])
    assert calls == [], 'should skip scenes with no findings unless --no-findings'

    # Status should remain 'drafted'
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    assert get_field(scenes_csv, 'the-blank-page', 'status') == 'drafted'


def test_revise_no_findings_flag_polishes_blind(project_dir_gn, monkeypatch):
    """--no-findings runs the revision with no findings input."""
    monkeypatch.chdir(project_dir_gn)
    _seed_draft(project_dir_gn, 'the-blank-page')

    captured = {}

    def capture_and_respond(prompt, model, log_file, **kwargs):
        captured['prompt'] = prompt
        return _make_fake_invoke(REVISED_SCRIPT)(prompt, model, log_file, **kwargs)

    from storyforge import api, cmd_revise_gn
    monkeypatch.setattr(api, 'invoke_to_file', capture_and_respond)
    monkeypatch.setattr(cmd_revise_gn, 'invoke_to_file', capture_and_respond)

    cmd_revise_gn.main(['the-blank-page', '--no-findings', '--no-branch'])

    assert 'prompt' in captured, 'API should be called with --no-findings'
    # Without findings the prompt should not have the findings section header
    assert 'Deterministic findings' not in captured['prompt']
    assert 'No findings were provided' in captured['prompt']


def test_revise_skips_briefed_scenes(project_dir_gn, monkeypatch):
    """Scenes at 'briefed' status (no draft) are skipped — only revise drafted/revised."""
    monkeypatch.chdir(project_dir_gn)
    # All fixture scenes start at 'briefed' and have no scene file.
    _seed_score_findings(project_dir_gn, 'the-blank-page', [
        {'kind': 'whatever', 'detail': 'x', 'severity': 'medium'},
    ])

    calls = []

    def track(*args, **kwargs):
        calls.append(args)
        return _make_fake_invoke(REVISED_SCRIPT)(*args, **kwargs)

    from storyforge import api, cmd_revise_gn
    monkeypatch.setattr(api, 'invoke_to_file', track)
    monkeypatch.setattr(cmd_revise_gn, 'invoke_to_file', track)

    # No revisable scenes anywhere → should sys.exit(1)
    with pytest.raises(SystemExit) as exc_info:
        cmd_revise_gn.main(['the-blank-page', '--no-branch'])
    assert exc_info.value.code != 0
    assert calls == []


# ---------------------------------------------------------------------------
# Dry-run + GN guard
# ---------------------------------------------------------------------------

def test_revise_dry_run_does_not_call_api(project_dir_gn, monkeypatch):
    """--dry-run prints the prompt without invoking the API."""
    monkeypatch.chdir(project_dir_gn)
    _seed_draft(project_dir_gn, 'the-blank-page')
    _seed_score_findings(project_dir_gn, 'the-blank-page', [
        {'kind': 'balloon_too_long', 'detail': 'x', 'severity': 'high'},
    ])

    def fail_on_call(*args, **kwargs):
        raise AssertionError('API should not be called in dry-run')

    from storyforge import api, cmd_revise_gn
    monkeypatch.setattr(api, 'invoke_to_file', fail_on_call)
    monkeypatch.setattr(cmd_revise_gn, 'invoke_to_file', fail_on_call)
    cmd_revise_gn.main(['the-blank-page', '--dry-run', '--no-branch'])

    # Status should remain 'drafted' (no revision applied)
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    assert get_field(scenes_csv, 'the-blank-page', 'status') == 'drafted'


def test_revise_rejects_novel_projects(project_dir, monkeypatch):
    """cmd_revise_gn on a novel-mode project exits with an error."""
    monkeypatch.chdir(project_dir)
    from storyforge import cmd_revise_gn
    with pytest.raises(SystemExit) as exc_info:
        cmd_revise_gn.main(['some-scene', '--no-branch'])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Re-parse + count updates
# ---------------------------------------------------------------------------

REVISED_WITH_EXTRA_PANEL = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1** (full bleed)
The cartographer at his desk. Blank parchment, lamp glow.

- CARTOGRAPHER: It always begins this way.

**Panel 2** (inset, lower-right)
Inset close on the inkwell, untouched.

---

## Page 2 — 4-GRID ⟵ PAGE-TURN REVEAL

**Panel 1** (top-left)
Hand trembles above the page.

**Panel 2** (top-right)
The pen touches paper.

**Panel 3** (bottom-left)
A line appears.

**Panel 4** (bottom-right)
He stares.

- CARTOGRAPHER: No.
"""


def test_revise_updates_panel_count_when_revision_changes_structure(
    project_dir_gn, monkeypatch
):
    """If revision adds a panel, panel_count is re-counted from the new script."""
    monkeypatch.chdir(project_dir_gn)
    _seed_draft(project_dir_gn, 'the-blank-page')  # starts at panel_count=5
    _seed_score_findings(project_dir_gn, 'the-blank-page', [
        {'kind': 'composition_too_sparse', 'detail': 'x', 'severity': 'medium'},
    ])

    from storyforge import api, cmd_revise_gn
    fake = _make_fake_invoke(REVISED_WITH_EXTRA_PANEL)
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_revise_gn, 'invoke_to_file', fake)

    cmd_revise_gn.main(['the-blank-page', '--no-branch'])

    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    # New script has 6 panels total (2 on page 1, 4 on page 2)
    assert get_field(scenes_csv, 'the-blank-page', 'panel_count') == '6'
    assert get_field(scenes_csv, 'the-blank-page', 'page_count') == '2'


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_revise_handles_missing_brief_row(project_dir_gn, monkeypatch):
    """If a scene's brief row is missing, it's reported as an error and skipped."""
    _seed_draft(project_dir_gn, 'the-blank-page')
    _seed_score_findings(project_dir_gn, 'the-blank-page', [
        {'kind': 'balloon_too_long', 'detail': 'x', 'severity': 'high'},
    ])

    # Blank out the briefs CSV (header only)
    briefs_csv = os.path.join(project_dir_gn, 'reference', 'scene-briefs.csv')
    with open(briefs_csv, encoding='utf-8') as f:
        header = f.readline()
    with open(briefs_csv, 'w', encoding='utf-8') as f:
        f.write(header)

    monkeypatch.chdir(project_dir_gn)

    calls = []

    def track(*args, **kwargs):
        calls.append(args)
        return _make_fake_invoke(REVISED_SCRIPT)(*args, **kwargs)

    from storyforge import api, cmd_revise_gn
    monkeypatch.setattr(api, 'invoke_to_file', track)
    monkeypatch.setattr(cmd_revise_gn, 'invoke_to_file', track)

    cmd_revise_gn.main(['the-blank-page', '--no-branch'])
    assert calls == [], 'should not invoke API when brief is missing'

    # Status should remain 'drafted' (revision was rejected)
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    assert get_field(scenes_csv, 'the-blank-page', 'status') == 'drafted'


def test_revise_via_dispatcher_routes_to_gn(project_dir_gn, monkeypatch):
    """Regression: storyforge revise on a GN project routes to cmd_revise_gn,
    not novel-mode cmd_revise (which would crash on GN data)."""
    monkeypatch.chdir(project_dir_gn)
    _seed_draft(project_dir_gn, 'the-blank-page')
    _seed_score_findings(project_dir_gn, 'the-blank-page', [
        {'kind': 'balloon_too_long', 'detail': 'x', 'severity': 'high'},
    ])

    from storyforge import api, cmd_revise_gn
    fake = _make_fake_invoke(REVISED_SCRIPT)
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_revise_gn, 'invoke_to_file', fake)

    # Simulate `storyforge revise the-blank-page --no-branch`
    monkeypatch.setattr('sys.argv',
                        ['storyforge', 'revise', 'the-blank-page', '--no-branch'])
    from storyforge.__main__ import main as dispatch_main
    dispatch_main()

    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    assert get_field(scenes_csv, 'the-blank-page', 'status') == 'revised'

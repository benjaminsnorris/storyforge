"""Tests for cmd_write_gn — GN scene drafting."""

import json
import os
import pytest

from storyforge.csv_cli import get_field


# A complete fake response: a 2-page script that honors a minimal brief
FAKE_SCRIPT = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1** (full bleed)
The cartographer at his desk. Blank parchment seen close, lamp glow.

- CAPTION: *The map remained blank.*
- CARTOGRAPHER: It always begins this way.

---

## Page 2 — 4-GRID ⟵ PAGE-TURN REVEAL

**Panel 1** (top-left)
Close on his trembling hand.

- CAPTION: *Forty years of practice.*

**Panel 2** (top-right)
The pen touches paper.

**Panel 3** (bottom-left)
A line appears.

- SFX: Scritch.

**Panel 4** (bottom-right)
He stares.

- CARTOGRAPHER: No.
"""


def _mock_invoke_to_file(prompt, model, log_file, **kwargs):
    """Drop-in replacement for api.invoke_to_file that writes a fake response."""
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    response = {
        'content': [{'type': 'text', 'text': FAKE_SCRIPT}],
        'usage': {
            'input_tokens': 200, 'output_tokens': 600,
            'cache_read_input_tokens': 0,
            'cache_creation_input_tokens': 0,
        },
    }
    with open(log_file, 'w') as f:
        json.dump(response, f)
    return response


def test_cmd_write_gn_drafts_a_scene(project_dir_gn, monkeypatch):
    """Running cmd_write_gn on a briefed scene drafts the script and updates CSVs."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import api, cmd_write_gn
    monkeypatch.setattr(api, 'invoke_to_file', _mock_invoke_to_file)

    cmd_write_gn.main(['the-blank-page', '--direct'])

    # Scene file was written
    scene_path = os.path.join(project_dir_gn, 'scenes', 'the-blank-page.md')
    assert os.path.isfile(scene_path), 'scene file should be written'
    content = open(scene_path).read()
    assert '## Page 1 — SPLASH' in content
    assert '## Page 2 — 4-GRID' in content
    assert '**Panel 1**' in content

    # CSV was updated: status, panel_count, page_count
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    assert get_field(scenes_csv, 'the-blank-page', 'status') == 'drafted'
    assert get_field(scenes_csv, 'the-blank-page', 'panel_count') == '5'
    assert get_field(scenes_csv, 'the-blank-page', 'page_count') == '2'


def test_cmd_write_gn_dry_run_does_not_call_api(project_dir_gn, monkeypatch):
    """--dry-run prints the prompt without invoking the API."""
    monkeypatch.chdir(project_dir_gn)
    from storyforge import api
    calls = []

    def fail_on_call(*args, **kwargs):
        calls.append(args)
        raise AssertionError('API should not be called in dry-run')

    monkeypatch.setattr(api, 'invoke_to_file', fail_on_call)
    from storyforge import cmd_write_gn
    cmd_write_gn.main(['the-blank-page', '--dry-run'])
    assert calls == []


def test_cmd_write_gn_skips_already_drafted_scenes(project_dir_gn, monkeypatch):
    """Scenes with status='drafted' are skipped unless --force is set."""
    from storyforge.csv_cli import update_field
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    update_field(scenes_csv, 'the-blank-page', 'status', 'drafted')

    monkeypatch.chdir(project_dir_gn)
    from storyforge import api, cmd_write_gn
    calls = []

    def track_call(*args, **kwargs):
        calls.append(args)
        return _mock_invoke_to_file(*args, **kwargs)

    monkeypatch.setattr(api, 'invoke_to_file', track_call)
    cmd_write_gn.main(['the-blank-page', '--direct'])
    assert calls == [], 'should not draft an already-drafted scene without --force'


def test_cmd_write_gn_force_re_drafts(project_dir_gn, monkeypatch):
    """--force re-drafts an already-drafted scene."""
    from storyforge.csv_cli import update_field
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    update_field(scenes_csv, 'the-blank-page', 'status', 'drafted')

    monkeypatch.chdir(project_dir_gn)
    from storyforge import api, cmd_write_gn
    calls = []

    def track_call(*args, **kwargs):
        calls.append(args)
        return _mock_invoke_to_file(*args, **kwargs)

    monkeypatch.setattr(api, 'invoke_to_file', track_call)
    cmd_write_gn.main(['the-blank-page', '--force', '--direct'])
    assert len(calls) == 1, 'expected one API call with --force on a drafted scene'

    # Scene should still be 'drafted' after the re-draft
    assert get_field(scenes_csv, 'the-blank-page', 'status') == 'drafted'


def test_cmd_write_gn_rejects_novel_projects(project_dir, monkeypatch):
    """Running cmd_write_gn on a novel-mode project exits with an error."""
    monkeypatch.chdir(project_dir)
    from storyforge import cmd_write_gn
    with pytest.raises(SystemExit) as exc_info:
        cmd_write_gn.main(['some-scene', '--direct'])
    assert exc_info.value.code != 0

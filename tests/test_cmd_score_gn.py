"""End-to-end tests for cmd_score_gn: GN scoring orchestration."""

import json
import os

import pytest

from storyforge.csv_cli import update_field


# ---------------------------------------------------------------------------
# Minimal drafted panel scripts (small/fast — no real API calls)
# ---------------------------------------------------------------------------

_SCRIPT_THE_BLANK_PAGE = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1**
The cartographer at his desk in lamplit study with blank parchment spread before him. Deep shadows fill the bookshelves. His posture suggests decades of waiting.

- CAPTION: *The map remained blank.*

---

## Page 2 — 4-GRID

**Panel 1**
Close on his trembling hand resting on the table edge.

- CAPTION: *Forty years of practice.*

**Panel 2**
Brush touches paper with a faint quiver visible.

**Panel 3**
A single line appears across the white expanse.

- SFX: Scritch.

**Panel 4**
He stares at the line growing darker and more certain.

- CARTOGRAPHER: No.
"""

_SCRIPT_SHADOWS_ARRIVE = """\
# Scene: shadows-arrive

**Target pages:** 1 | **Layout intent:** 6-grid

---

## Page 1 — 6-GRID

**Panel 1**
Door from outside the frame. Thin gap at bottom. Shadow just visible.

**Panel 2**
Shadow deepens under the door. Wind moving the curtains at the window behind.

**Panel 3**
The lamp flame gutters in a draught from somewhere unseen.

**Panel 4**
Cartographer turns away from the desk to face the door.

- CARTOGRAPHER: Who's there?

**Panel 5**
Listens. Head tilted. Silence on his face.

**Panel 6**
He stands, pushing back the chair.
"""

_SCRIPT_THE_FIRST_MARK = """\
# Scene: the-first-mark

**Target pages:** 1 | **Layout intent:** 3-tier

---

## Page 1 — 3-TIER

**Panel 1**
Returns to the desk from across the room. Back to the viewer. Lamp still burning.

- CAPTION: *He did not remember crossing the room.*

**Panel 2**
The page is no longer blank. Filled with coastline detail he has never drawn.

- CARTOGRAPHER: This place — I never drew it.

**Panel 3**
His hand reaches for the pen. Dawn light beginning at the window behind him.
"""


def _write_scenes(project_dir, scripts=None):
    """Write fake drafted scene files and set status=drafted in scenes.csv."""
    if scripts is None:
        scripts = {
            'the-blank-page': _SCRIPT_THE_BLANK_PAGE,
            'shadows-arrive': _SCRIPT_SHADOWS_ARRIVE,
            'the-first-mark': _SCRIPT_THE_FIRST_MARK,
        }
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    for sid, text in scripts.items():
        path = os.path.join(scenes_dir, f'{sid}.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        update_field(meta_csv, sid, 'status', 'drafted')


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestScoreAllDraftedScenes:
    def test_score_all_drafted_produces_json_and_summary(self, project_dir_gn, monkeypatch):
        """Run main([]) on all 3 drafted scenes; verify JSON + summary.csv exist."""
        monkeypatch.chdir(project_dir_gn)
        _write_scenes(project_dir_gn)

        from storyforge import cmd_score_gn
        cmd_score_gn.main([])

        output_dir = os.path.join(project_dir_gn, 'working', 'scores', 'latest')

        # All three scene JSON files should exist
        for sid in ('the-blank-page', 'shadows-arrive', 'the-first-mark'):
            json_path = os.path.join(output_dir, f'{sid}.json')
            assert os.path.isfile(json_path), f'Missing score JSON for {sid}'
            with open(json_path) as f:
                data = json.load(f)
            assert data['scene_id'] == sid
            assert isinstance(data['overall_score'], float)
            assert 0.0 <= data['overall_score'] <= 1.0, (
                f'{sid} overall_score {data["overall_score"]} not in [0,1]'
            )
            assert 'scores' in data
            assert 'findings' in data
            assert 'scored_at' in data

        # Summary CSV
        summary = os.path.join(output_dir, 'summary.csv')
        assert os.path.isfile(summary), 'summary.csv not written'
        with open(summary) as f:
            content = f.read()
        assert 'scene_id' in content
        assert 'overall_score' in content
        assert 'the-blank-page' in content


class TestScoreSingleSceneViaPositional:
    def test_positional_arg_scores_only_that_scene(self, project_dir_gn, monkeypatch):
        """main(['the-blank-page']) should score only that one scene."""
        monkeypatch.chdir(project_dir_gn)
        _write_scenes(project_dir_gn)

        from storyforge import cmd_score_gn
        cmd_score_gn.main(['the-blank-page'])

        output_dir = os.path.join(project_dir_gn, 'working', 'scores', 'latest')

        # Target scene scored
        assert os.path.isfile(os.path.join(output_dir, 'the-blank-page.json'))

        # Other scenes NOT scored
        assert not os.path.isfile(os.path.join(output_dir, 'shadows-arrive.json'))
        assert not os.path.isfile(os.path.join(output_dir, 'the-first-mark.json'))

        # Summary contains only the one scene
        summary = os.path.join(output_dir, 'summary.csv')
        with open(summary) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        # header + 1 data row
        assert len(lines) == 2, f'Expected 2 lines in summary, got {len(lines)}'
        assert 'the-blank-page' in lines[1]


class TestScoreWithPrinciplesFilter:
    def test_principles_filter_runs_only_requested_principles(
            self, project_dir_gn, monkeypatch):
        """--principles brief_fidelity,panel_density only runs those two."""
        monkeypatch.chdir(project_dir_gn)
        _write_scenes(project_dir_gn, {'the-blank-page': _SCRIPT_THE_BLANK_PAGE})

        from storyforge import cmd_score_gn
        cmd_score_gn.main(['the-blank-page',
                           '--principles', 'brief_fidelity,panel_density'])

        output_dir = os.path.join(project_dir_gn, 'working', 'scores', 'latest')
        json_path = os.path.join(output_dir, 'the-blank-page.json')
        assert os.path.isfile(json_path)

        with open(json_path) as f:
            data = json.load(f)

        scores = data['scores']
        # Only the two requested principles present
        assert 'brief_fidelity' in scores
        assert 'panel_density' in scores
        # Others absent
        for p in ('dialogue_compression', 'layout_rhythm',
                  'caption_economy', 'panel_composition_depth'):
            assert p not in scores, f'Unexpected principle {p} in filtered output'

        # Summary header should only have the two principles
        summary_path = os.path.join(output_dir, 'summary.csv')
        with open(summary_path) as f:
            header = f.readline().strip()
        assert 'brief_fidelity' in header
        assert 'panel_density' in header
        assert 'dialogue_compression' not in header


class TestDryRunWritesNothing:
    def test_dry_run_creates_no_output_files(self, project_dir_gn, monkeypatch):
        """--dry-run should not create any score files or the output directory."""
        monkeypatch.chdir(project_dir_gn)
        _write_scenes(project_dir_gn)

        output_dir = os.path.join(project_dir_gn, 'working', 'scores', 'latest')

        from storyforge import cmd_score_gn
        cmd_score_gn.main(['--dry-run'])

        # Output directory should not have any JSON or CSV written
        if os.path.isdir(output_dir):
            entries = os.listdir(output_dir)
            json_files = [e for e in entries if e.endswith('.json')]
            csv_files = [e for e in entries if e.endswith('.csv')]
            assert not json_files, f'Dry run wrote JSON files: {json_files}'
            assert not csv_files, f'Dry run wrote CSV files: {csv_files}'


class TestScoreRefusesNonGN:
    def test_refuses_non_gn_project(self, project_dir, monkeypatch):
        """Running on a novel project exits non-zero with a clear error."""
        monkeypatch.chdir(project_dir)

        from storyforge import cmd_score_gn
        with pytest.raises(SystemExit) as exc_info:
            cmd_score_gn.main([])
        assert exc_info.value.code != 0, 'Should exit non-zero for non-GN project'


class TestScoreSkipsNonDraftedScenes:
    def test_non_drafted_scenes_are_skipped(self, project_dir_gn, monkeypatch):
        """Scenes with status != 'drafted' are logged and skipped."""
        monkeypatch.chdir(project_dir_gn)

        # Only write + mark one scene as drafted
        _write_scenes(project_dir_gn,
                      {'the-blank-page': _SCRIPT_THE_BLANK_PAGE})

        # The other two remain 'briefed' (fixture default — not 'drafted')
        from storyforge import cmd_score_gn
        cmd_score_gn.main([])

        output_dir = os.path.join(project_dir_gn, 'working', 'scores', 'latest')

        # Only the drafted one scored
        assert os.path.isfile(os.path.join(output_dir, 'the-blank-page.json'))
        assert not os.path.isfile(os.path.join(output_dir, 'shadows-arrive.json'))
        assert not os.path.isfile(os.path.join(output_dir, 'the-first-mark.json'))

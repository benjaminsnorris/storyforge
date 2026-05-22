"""End-to-end tests for cmd_evaluate_gn: GN evaluation panel orchestration."""

import json
import os

import pytest

from storyforge.csv_cli import update_field


# ---------------------------------------------------------------------------
# Fake API response — what personas are instructed to output
# ---------------------------------------------------------------------------

FAKE_EVAL_RESPONSE = {
    'content': [{'type': 'text', 'text': '{"findings": [{"severity": "medium", "fix_location": "composition", "message": "Panel 3 composition is sparse", "scene_id": "the-blank-page", "page": 1, "panel": 3}]}'}],
    'usage': {'input_tokens': 200, 'output_tokens': 100, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0},
}


def _make_fake_invoke(response=None):
    """Return a fake invoke_to_file function that writes the given response JSON."""
    if response is None:
        response = FAKE_EVAL_RESPONSE

    def fake_invoke_to_file(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    return fake_invoke_to_file


# ---------------------------------------------------------------------------
# Minimal drafted panel scripts (mirrors test_cmd_score_gn)
# ---------------------------------------------------------------------------

_SCRIPT_THE_BLANK_PAGE = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1**
The cartographer at his desk in lamplit study with blank parchment spread before him.

- CAPTION: *The map remained blank.*

---

## Page 2 — 4-GRID

**Panel 1**
Close on his trembling hand resting on the table edge.

- CAPTION: *Forty years of practice.*

**Panel 2**
Brush touches paper.

**Panel 3**
A single line appears.

**Panel 4**
He stares at the line.

- CARTOGRAPHER: No.
"""

_SCRIPT_SHADOWS_ARRIVE = """\
# Scene: shadows-arrive

**Target pages:** 1 | **Layout intent:** 6-grid

---

## Page 1 — 6-GRID

**Panel 1**
Door from outside the frame.

**Panel 2**
Shadow deepens under the door.

**Panel 3**
The lamp flame gutters.

**Panel 4**
Cartographer turns to face the door.

- CARTOGRAPHER: Who's there?

**Panel 5**
Listens. Silence.

**Panel 6**
He stands, pushing back the chair.
"""


def _write_scenes(project_dir, scripts=None):
    """Write fake drafted scene files and set status=drafted in scenes.csv."""
    if scripts is None:
        scripts = {
            'the-blank-page': _SCRIPT_THE_BLANK_PAGE,
            'shadows-arrive': _SCRIPT_SHADOWS_ARRIVE,
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

class TestEvaluateAllDraftedScenes:
    def test_evaluate_all_drafted_scenes(self, project_dir_gn, monkeypatch):
        """Evaluating all drafted scenes runs each persona on each scene and writes JSON output."""
        monkeypatch.chdir(project_dir_gn)
        _write_scenes(project_dir_gn, {'the-blank-page': _SCRIPT_THE_BLANK_PAGE})

        fake = _make_fake_invoke()
        from storyforge import api as storyforge_api
        from storyforge import cmd_evaluate_gn
        monkeypatch.setattr(storyforge_api, 'invoke_to_file', fake)
        monkeypatch.setattr(cmd_evaluate_gn, 'invoke_to_file', fake)

        from storyforge import cmd_evaluate_gn
        cmd_evaluate_gn.main([])

        output_dir = os.path.join(project_dir_gn, 'working', 'evaluations', 'latest')

        json_path = os.path.join(output_dir, 'the-blank-page.json')
        assert os.path.isfile(json_path), 'Missing evaluation JSON for the-blank-page'

        with open(json_path) as f:
            data = json.load(f)

        assert data['scene_id'] == 'the-blank-page'
        assert 'evaluated_at' in data
        assert isinstance(data['personas_run'], list)
        assert len(data['personas_run']) == 3, (
            f'Expected 3 personas, got {data["personas_run"]}'
        )

        # Findings come from all 3 personas
        assert isinstance(data['findings'], list)
        # Each persona produced one finding from FAKE_EVAL_RESPONSE
        assert len(data['findings']) == 3, (
            f'Expected 3 findings (one per persona), got {len(data["findings"])}'
        )

        # Each finding should be tagged with its persona
        personas_in_findings = {f['persona'] for f in data['findings']}
        assert personas_in_findings == set(data['personas_run'])

        # All findings should have scene_id set
        for finding in data['findings']:
            assert 'scene_id' in finding


class TestEvaluatePersonaFilter:
    def test_persona_filter_runs_only_requested_persona(self, project_dir_gn, monkeypatch):
        """--personas pacing only invokes the pacing persona."""
        monkeypatch.chdir(project_dir_gn)
        _write_scenes(project_dir_gn, {'the-blank-page': _SCRIPT_THE_BLANK_PAGE})

        call_log = []

        def tracking_invoke(prompt, model, log_file, **kwargs):
            call_log.append(log_file)
            os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
            with open(log_file, 'w') as f:
                json.dump(FAKE_EVAL_RESPONSE, f)
            return FAKE_EVAL_RESPONSE

        from storyforge import api as storyforge_api
        from storyforge import cmd_evaluate_gn
        monkeypatch.setattr(storyforge_api, 'invoke_to_file', tracking_invoke)
        monkeypatch.setattr(cmd_evaluate_gn, 'invoke_to_file', tracking_invoke)

        cmd_evaluate_gn.main(['--personas', 'pacing'])

        # Only one API call should have been made (for pacing persona)
        assert len(call_log) == 1, (
            f'Expected 1 API call for pacing persona only, got {len(call_log)}'
        )
        assert 'pacing' in call_log[0], (
            f'Expected pacing log file, got {call_log[0]}'
        )

        # Output JSON should show only pacing persona
        output_dir = os.path.join(project_dir_gn, 'working', 'evaluations', 'latest')
        json_path = os.path.join(output_dir, 'the-blank-page.json')
        assert os.path.isfile(json_path)

        with open(json_path) as f:
            data = json.load(f)

        assert data['personas_run'] == ['pacing'], (
            f'Expected only pacing persona run, got {data["personas_run"]}'
        )


class TestEvaluateDryRunNoApiCalls:
    def test_dry_run_no_api_calls(self, project_dir_gn, monkeypatch):
        """--dry-run doesn't call the API and writes no output files."""
        monkeypatch.chdir(project_dir_gn)
        _write_scenes(project_dir_gn, {'the-blank-page': _SCRIPT_THE_BLANK_PAGE})

        api_called = []

        def spy_invoke(prompt, model, log_file, **kwargs):
            api_called.append(log_file)
            return FAKE_EVAL_RESPONSE

        from storyforge import api as storyforge_api
        from storyforge import cmd_evaluate_gn
        monkeypatch.setattr(storyforge_api, 'invoke_to_file', spy_invoke)
        monkeypatch.setattr(cmd_evaluate_gn, 'invoke_to_file', spy_invoke)

        from storyforge import cmd_evaluate_gn
        cmd_evaluate_gn.main(['--dry-run'])

        # No API calls should have been made
        assert not api_called, (
            f'--dry-run should not call API; got calls: {api_called}'
        )

        # No output JSON written
        output_dir = os.path.join(project_dir_gn, 'working', 'evaluations', 'latest')
        json_path = os.path.join(output_dir, 'the-blank-page.json')
        assert not os.path.isfile(json_path), (
            '--dry-run should not write evaluation JSON'
        )


class TestEvaluateRefusesNonGN:
    def test_refuses_non_gn_project(self, project_dir, monkeypatch):
        """Refuses to run on non-GN projects with exit code 1."""
        monkeypatch.chdir(project_dir)

        from storyforge import cmd_evaluate_gn
        with pytest.raises(SystemExit) as exc_info:
            cmd_evaluate_gn.main([])

        assert exc_info.value.code != 0, 'Should exit non-zero for non-GN project'


class TestEvaluateJsonParsing:
    def test_fenced_json_block_is_parsed(self, project_dir_gn, monkeypatch):
        """A response with JSON wrapped in ```json fences is correctly parsed."""
        monkeypatch.chdir(project_dir_gn)
        _write_scenes(project_dir_gn, {'the-blank-page': _SCRIPT_THE_BLANK_PAGE})

        fenced_response = {
            'content': [{'type': 'text', 'text': (
                'Here are my findings:\n\n'
                '```json\n'
                '{"findings": [{"severity": "high", "fix_location": "composition", '
                '"message": "Missing shot type", "scene_id": "the-blank-page", '
                '"page": 2, "panel": 1}]}\n'
                '```\n'
            )}],
            'usage': {'input_tokens': 100, 'output_tokens': 50,
                      'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0},
        }

        fake = _make_fake_invoke(fenced_response)
        from storyforge import api as storyforge_api
        from storyforge import cmd_evaluate_gn
        monkeypatch.setattr(storyforge_api, 'invoke_to_file', fake)
        monkeypatch.setattr(cmd_evaluate_gn, 'invoke_to_file', fake)

        cmd_evaluate_gn.main(['--personas', 'panel-composition'])

        output_dir = os.path.join(project_dir_gn, 'working', 'evaluations', 'latest')
        json_path = os.path.join(output_dir, 'the-blank-page.json')
        assert os.path.isfile(json_path)

        with open(json_path) as f:
            data = json.load(f)

        assert len(data['findings']) == 1
        assert data['findings'][0]['severity'] == 'high'
        assert data['findings'][0]['message'] == 'Missing shot type'

    def test_unparseable_response_skipped_gracefully(self, project_dir_gn, monkeypatch):
        """If a persona returns non-JSON, it is skipped and the run continues."""
        monkeypatch.chdir(project_dir_gn)
        _write_scenes(project_dir_gn, {'the-blank-page': _SCRIPT_THE_BLANK_PAGE})

        bad_response = {
            'content': [{'type': 'text', 'text': 'I cannot find any issues with this script.'}],
            'usage': {'input_tokens': 80, 'output_tokens': 20,
                      'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0},
        }

        fake = _make_fake_invoke(bad_response)
        from storyforge import api as storyforge_api
        from storyforge import cmd_evaluate_gn
        monkeypatch.setattr(storyforge_api, 'invoke_to_file', fake)
        monkeypatch.setattr(cmd_evaluate_gn, 'invoke_to_file', fake)

        # Should not raise — bad JSON is gracefully skipped
        cmd_evaluate_gn.main(['--personas', 'pacing'])

        output_dir = os.path.join(project_dir_gn, 'working', 'evaluations', 'latest')
        json_path = os.path.join(output_dir, 'the-blank-page.json')
        assert os.path.isfile(json_path)

        with open(json_path) as f:
            data = json.load(f)

        # The persona ran but produced no parseable findings
        assert data['personas_run'] == ['pacing']
        assert data['findings'] == []


# ---------------------------------------------------------------------------
# Unit tests for _parse_findings robustness (regression: null findings crash)
# ---------------------------------------------------------------------------

class TestParseFindings:
    """Direct unit tests for the _parse_findings helper."""

    def _call(self, text, persona='test-persona', scene_id='scene-x'):
        from storyforge.cmd_evaluate_gn import _parse_findings
        return _parse_findings(text, persona, scene_id)

    def test_null_findings_returns_empty_list(self):
        """{"findings": null} must not crash and must return []."""
        result = self._call('{"findings": null}')
        assert result == [], (
            '_parse_findings should return [] for {"findings": null}, not raise TypeError'
        )

    def test_null_findings_in_fenced_block_returns_empty_list(self):
        """A fenced block with {"findings": null} must not crash."""
        text = '```json\n{"findings": null}\n```'
        result = self._call(text)
        assert result == []

    def test_normal_findings_parsed_correctly(self):
        """Normal {"findings": [...]} parses to a list with scene_id stamped."""
        text = '{"findings": [{"severity": "medium", "message": "Test finding"}]}'
        result = self._call(text, scene_id='my-scene')
        assert len(result) == 1
        assert result[0]['scene_id'] == 'my-scene'
        assert result[0]['severity'] == 'medium'

    def test_empty_findings_list_returns_empty(self):
        """{"findings": []} returns []."""
        result = self._call('{"findings": []}')
        assert result == []

    def test_empty_response_returns_empty(self):
        """Empty string returns []."""
        result = self._call('')
        assert result == []

    def test_non_list_findings_returns_empty_list(self):
        """{"findings": "some string"} returns [] without crashing."""
        result = self._call('{"findings": "some string"}')
        assert result == []

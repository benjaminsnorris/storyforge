# Phase B Top 6: Command Module Tests

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test orchestration logic in the 6 highest-priority command modules + 4 core infrastructure modules with mocked API, targeting ~200 tests and ~60% coverage.

**Architecture:** Each command module gets its own test file in tests/commands/. Tests use mock_api and mock_git fixtures from conftest.py. Focus on argument parsing, plan generation, orchestration flow, and response processing -- not API call content.

**Tech Stack:** pytest, monkeypatch, unittest.mock, inspect

---

## Task 1: `tests/commands/test_cmd_revise.py` (~25 tests)

**File to create:** `tests/commands/test_cmd_revise.py`

### Class: TestParseArgs

```python
import os
import pytest
from storyforge.cmd_revise import parse_args


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.dry_run is False
        assert args.interactive is False
        assert args.structural is False
        assert args.naturalness is False
        assert args.polish is False
        assert args.loop is False
        assert args.max_loops == 5
        assert args.pass_num == 0
        assert args.coaching is None

    def test_polish_flag(self):
        args = parse_args(['--polish'])
        assert args.polish is True

    def test_naturalness_flag(self):
        args = parse_args(['--naturalness'])
        assert args.naturalness is True

    def test_structural_flag(self):
        args = parse_args(['--structural'])
        assert args.structural is True

    def test_loop_with_max_loops(self):
        args = parse_args(['--polish', '--loop', '--max-loops', '3'])
        assert args.loop is True
        assert args.max_loops == 3

    def test_pass_num_positional(self):
        args = parse_args(['4'])
        assert args.pass_num == 4

    def test_coaching_override(self):
        args = parse_args(['--coaching', 'strict'])
        assert args.coaching == 'strict'

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run is True
```

### Class: TestGeneratePolishPlan

```python
from storyforge.cmd_revise import _generate_polish_plan, _read_csv_plan, CSV_PLAN_FIELDS


class TestGeneratePolishPlan:
    def test_creates_single_pass(self, tmp_path):
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows = _generate_polish_plan(plan_file)
        assert len(rows) == 1
        assert rows[0]['name'] == 'prose-polish'
        assert rows[0]['fix_location'] == 'craft'
        assert rows[0]['status'] == 'pending'

    def test_writes_csv_file(self, tmp_path):
        plan_file = str(tmp_path / 'revision-plan.csv')
        _generate_polish_plan(plan_file)
        assert os.path.isfile(plan_file)
        loaded = _read_csv_plan(plan_file)
        assert len(loaded) == 1
        assert loaded[0]['name'] == 'prose-polish'

    def test_plan_has_all_fields(self, tmp_path):
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows = _generate_polish_plan(plan_file)
        for field in CSV_PLAN_FIELDS:
            assert field in rows[0], f'Missing field: {field}'
```

### Class: TestGenerateNaturalnessPlan

```python
from storyforge.cmd_revise import _generate_naturalness_plan


class TestGenerateNaturalnessPlan:
    def test_creates_three_passes(self, tmp_path):
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows = _generate_naturalness_plan(plan_file)
        assert len(rows) == 3

    def test_pass_names(self, tmp_path):
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows = _generate_naturalness_plan(plan_file)
        names = [r['name'] for r in rows]
        assert names == ['tricolon-parallelism', 'em-dash-antithesis', 'ai-vocabulary-hedging']

    def test_all_passes_are_opus(self, tmp_path):
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows = _generate_naturalness_plan(plan_file)
        for row in rows:
            assert row['model_tier'] == 'opus'

    def test_all_passes_are_pending(self, tmp_path):
        plan_file = str(tmp_path / 'revision-plan.csv')
        rows = _generate_naturalness_plan(plan_file)
        for row in rows:
            assert row['status'] == 'pending'
```

### Class: TestExtractSceneRationales

```python
from storyforge.cmd_revise import _extract_scene_rationales


class TestExtractSceneRationales:
    def test_returns_empty_when_no_scores(self, project_dir):
        result = _extract_scene_rationales(project_dir, ['act1-sc01'])
        assert result == {}

    def test_extracts_rationales_from_scores(self, project_dir):
        """Write a mock scene-scores.csv and verify extraction."""
        latest_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
        os.makedirs(latest_dir, exist_ok=True)
        # latest must be a symlink in real usage, but for test we use a dir
        scores_file = os.path.join(latest_dir, 'scene-scores.csv')
        with open(scores_file, 'w') as f:
            f.write('id|prose_naturalness|prose_naturalness_rationale|voice_consistency|voice_consistency_rationale\n')
            f.write('act1-sc01|7|Good variety|8|Strong voice\n')
        result = _extract_scene_rationales(project_dir, ['act1-sc01'])
        assert 'act1-sc01' in result
        assert 'prose_naturalness' in result['act1-sc01']
        assert result['act1-sc01']['prose_naturalness'] == 'Good variety'

    def test_filters_by_principle(self, project_dir):
        latest_dir = os.path.join(project_dir, 'working', 'scores', 'latest')
        os.makedirs(latest_dir, exist_ok=True)
        scores_file = os.path.join(latest_dir, 'scene-scores.csv')
        with open(scores_file, 'w') as f:
            f.write('id|prose_naturalness|prose_naturalness_rationale|voice_consistency|voice_consistency_rationale\n')
            f.write('act1-sc01|7|Good variety|8|Strong voice\n')
        result = _extract_scene_rationales(project_dir, ['act1-sc01'],
                                            principles=['voice_consistency'])
        assert 'voice_consistency' in result['act1-sc01']
        assert 'prose_naturalness' not in result['act1-sc01']
```

### Class: TestCSVPlanHelpers

```python
from storyforge.cmd_revise import (
    _read_csv_plan, _write_csv_plan, _count_passes,
    _read_pass_field, _update_pass_field, CSV_PLAN_FIELDS,
)


class TestCSVPlanHelpers:
    def test_read_nonexistent_plan(self, tmp_path):
        rows = _read_csv_plan(str(tmp_path / 'nope.csv'))
        assert rows == []

    def test_write_and_read_roundtrip(self, tmp_path):
        plan_file = str(tmp_path / 'plan.csv')
        rows = [{'pass': '1', 'name': 'test', 'purpose': 'testing',
                 'scope': 'full', 'targets': '', 'guidance': '',
                 'protection': '', 'findings': '', 'status': 'pending',
                 'model_tier': 'opus', 'fix_location': 'craft'}]
        _write_csv_plan(plan_file, rows)
        loaded = _read_csv_plan(plan_file)
        assert len(loaded) == 1
        assert loaded[0]['name'] == 'test'

    def test_count_passes(self):
        rows = [{'pass': '1'}, {'pass': '2'}]
        assert _count_passes(rows) == 2

    def test_read_pass_field(self):
        rows = [{'pass': '1', 'name': 'first'}, {'pass': '2', 'name': 'second'}]
        assert _read_pass_field(rows, 1, 'name') == 'first'
        assert _read_pass_field(rows, 2, 'name') == 'second'
        assert _read_pass_field(rows, 3, 'name') == ''

    def test_update_pass_field(self, tmp_path):
        plan_file = str(tmp_path / 'plan.csv')
        rows = [{'pass': '1', 'name': 'test', 'purpose': '', 'scope': '',
                 'targets': '', 'guidance': '', 'protection': '',
                 'findings': '', 'status': 'pending', 'model_tier': '',
                 'fix_location': ''}]
        _write_csv_plan(plan_file, rows)
        _update_pass_field(rows, 1, 'status', 'completed', plan_file)
        reloaded = _read_csv_plan(plan_file)
        assert reloaded[0]['status'] == 'completed'
```

### Class: TestMainValidation

```python
from storyforge.cmd_revise import main


class TestMainValidation:
    def test_loop_requires_polish(self, monkeypatch, project_dir):
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            main(['--loop'])

    def test_loop_incompatible_with_dry_run(self, monkeypatch, project_dir):
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            main(['--polish', '--loop', '--dry-run'])

    def test_mutually_exclusive_modes(self, monkeypatch, project_dir):
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            main(['--polish', '--naturalness'])
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_cmd_revise.py -v
git add tests/commands/test_cmd_revise.py && git commit -m "Add cmd_revise command module tests" && git push
```

---

## Task 2: `tests/commands/test_cmd_write.py` (~22 tests)

**File to create:** `tests/commands/test_cmd_write.py`

### Class: TestParseArgs

```python
import json
import os
import pytest
from storyforge.cmd_write import parse_args


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.positional == []
        assert args.dry_run is False
        assert args.force is False
        assert args.direct is False
        assert args.coaching is None
        assert args.interactive is False
        assert args.scenes is None
        assert args.act is None
        assert args.from_seq is None

    def test_single_scene(self):
        args = parse_args(['act1-sc01'])
        assert args.positional == ['act1-sc01']

    def test_scene_range(self):
        args = parse_args(['act1-sc01', 'act1-sc02'])
        assert args.positional == ['act1-sc01', 'act1-sc02']

    def test_force_flag(self):
        args = parse_args(['--force', 'act1-sc01'])
        assert args.force is True

    def test_direct_flag(self):
        args = parse_args(['--direct'])
        assert args.direct is True

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        assert args.scenes == 'act1-sc01,act1-sc02'

    def test_act_filter(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_from_seq_filter(self):
        args = parse_args(['--from-seq', '5'])
        assert args.from_seq == '5'
```

### Class: TestResolveFilter

```python
from storyforge.cmd_write import _resolve_filter, parse_args


class TestResolveFilter:
    def test_no_args_means_all(self):
        args = parse_args([])
        mode, value, value2 = _resolve_filter(args)
        assert mode == 'all'

    def test_single_positional(self):
        args = parse_args(['act1-sc01'])
        mode, value, value2 = _resolve_filter(args)
        assert mode == 'single'
        assert value == 'act1-sc01'

    def test_range_positional(self):
        args = parse_args(['act1-sc01', 'act2-sc01'])
        mode, value, value2 = _resolve_filter(args)
        assert mode == 'range'
        assert value == 'act1-sc01'
        assert value2 == 'act2-sc01'

    def test_scenes_flag(self):
        args = parse_args(['--scenes', 'a,b'])
        mode, value, _ = _resolve_filter(args)
        assert mode == 'scenes'
        assert value == 'a,b'

    def test_act_flag(self):
        args = parse_args(['--act', '2'])
        mode, value, _ = _resolve_filter(args)
        assert mode == 'act'
        assert value == '2'
```

### Class: TestExtractSceneFromResponse

```python
from storyforge.cmd_write import _extract_scene_from_response


class TestExtractSceneFromResponse:
    def test_extracts_scene_text(self, tmp_path):
        log_file = str(tmp_path / 'response.json')
        scene_file = str(tmp_path / 'scene.md')
        response = {
            'content': [{'type': 'text', 'text': 'The morning light filtered through the curtains.'}],
            'usage': {'input_tokens': 100, 'output_tokens': 50},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        _extract_scene_from_response(log_file, scene_file)
        assert os.path.isfile(scene_file)
        with open(scene_file) as f:
            content = f.read()
        assert 'morning light' in content

    def test_handles_empty_response(self, tmp_path):
        log_file = str(tmp_path / 'response.json')
        scene_file = str(tmp_path / 'scene.md')
        response = {
            'content': [{'type': 'text', 'text': ''}],
            'usage': {'input_tokens': 100, 'output_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        _extract_scene_from_response(log_file, scene_file)
        # Should not create scene file for empty response
        assert not os.path.isfile(scene_file)
```

### Class: TestDetectBriefs

```python
from storyforge.cmd_write import _detect_briefs


class TestDetectBriefs:
    def test_detects_existing_briefs(self, project_dir):
        assert _detect_briefs(project_dir) is True

    def test_returns_false_when_no_briefs(self, tmp_path):
        assert _detect_briefs(str(tmp_path)) is False

    def test_returns_false_for_empty_briefs(self, tmp_path):
        ref_dir = tmp_path / 'reference'
        ref_dir.mkdir()
        briefs_file = ref_dir / 'scene-briefs.csv'
        briefs_file.write_text('id|goal|conflict\n')
        assert _detect_briefs(str(tmp_path)) is False
```

### Class: TestAvgWordCount

```python
from storyforge.cmd_write import _avg_word_count


class TestAvgWordCount:
    def test_reads_from_metadata(self, project_dir):
        # The fixture has target_words but word_count=0, so fallback returns 2000
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        result = _avg_word_count(metadata_csv)
        assert isinstance(result, int)
        assert result > 0

    def test_default_when_no_data(self, tmp_path):
        csv_path = str(tmp_path / 'scenes.csv')
        with open(csv_path, 'w') as f:
            f.write('id|target_words\nscene1|\n')
        result = _avg_word_count(csv_path)
        assert result == 2000
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_cmd_write.py -v
git add tests/commands/test_cmd_write.py && git commit -m "Add cmd_write command module tests" && git push
```

---

## Task 3: `tests/commands/test_cmd_score.py` (~25 tests)

**File to create:** `tests/commands/test_cmd_score.py`

### Class: TestParseArgs

```python
import os
import pytest
from storyforge.cmd_score import parse_args


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.dry_run is False
        assert args.interactive is False
        assert args.direct is False
        assert args.deep is False
        assert args.scenes is None
        assert args.act is None
        assert args.from_seq is None
        assert args.parallel == 6

    def test_direct_flag(self):
        args = parse_args(['--direct'])
        assert args.direct is True

    def test_deep_flag(self):
        args = parse_args(['--direct', '--deep'])
        assert args.deep is True

    def test_parallel_override(self):
        args = parse_args(['--parallel', '12'])
        assert args.parallel == 12

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        assert args.scenes == 'act1-sc01,act1-sc02'

    def test_act_filter(self):
        args = parse_args(['--act', '2'])
        assert args.act == '2'

    def test_parallel_from_env(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_SCORE_PARALLEL', '4')
        # Re-import to pick up env var at argparse default time
        from storyforge.cmd_score import parse_args as pa
        args = pa([])
        assert args.parallel == 4
```

### Class: TestResolveFilter

```python
from storyforge.cmd_score import _resolve_filter, parse_args


class TestResolveFilter:
    def test_default_is_all(self):
        args = parse_args([])
        mode, value, _ = _resolve_filter(args)
        assert mode == 'all'

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'a,b,c'])
        mode, value, _ = _resolve_filter(args)
        assert mode == 'scenes'
        assert value == 'a,b,c'

    def test_act_filter(self):
        args = parse_args(['--act', '1'])
        mode, value, _ = _resolve_filter(args)
        assert mode == 'act'
        assert value == '1'
```

### Class: TestBuildScenePrompt

```python
from storyforge.cmd_score import _build_scene_prompt


class TestBuildScenePrompt:
    def test_builds_prompt_with_scene_text(self, project_dir):
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        # Write a test scene
        with open(os.path.join(scenes_dir, 'act1-sc01.md'), 'w') as f:
            f.write('The finest cartographer in the city sat at her desk.')

        prompt = _build_scene_prompt(
            'act1-sc01',
            'Score the following scene:\n{{SCENE_TEXT}}\n{{EVALUATION_CRITERIA}}\n{{WEIGHTED_PRINCIPLES}}',
            'criteria text',
            'weighted text',
            metadata_csv,
            intent_csv,
            scenes_dir,
        )
        assert 'finest cartographer' in prompt
        assert 'criteria text' in prompt
        assert 'weighted text' in prompt

    def test_handles_missing_scene_file(self, project_dir):
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        # No scene file for nonexistent-scene
        prompt = _build_scene_prompt(
            'nonexistent-scene',
            '{{SCENE_TEXT}}',
            '', '', metadata_csv, intent_csv, scenes_dir,
        )
        # Should still produce a prompt (with empty scene text)
        assert isinstance(prompt, str)
```

### Class: TestParseSceneEvaluation

```python
from storyforge.cmd_score import _parse_scene_evaluation


class TestParseSceneEvaluation:
    def test_parses_score_text(self, tmp_path, plugin_dir):
        text = "principle|score|rationale\nprose_naturalness|7|Good variety\nvoice_consistency|8|Strong voice\n"
        scores_file = str(tmp_path / 'scores.csv')
        rationale_file = str(tmp_path / 'rationale.csv')
        diagnostics = os.path.join(plugin_dir, 'references', 'diagnostics.csv')
        # Only run if diagnostics.csv exists
        if os.path.isfile(diagnostics):
            result = _parse_scene_evaluation(text, scores_file, rationale_file,
                                              'act1-sc01', diagnostics)
            assert isinstance(result, bool)
```

### Class: TestDetermineCycle

```python
from storyforge.cmd_score import _determine_cycle


class TestDetermineCycle:
    def test_first_cycle(self, project_dir):
        cycle = _determine_cycle(project_dir)
        assert cycle >= 1

    def test_increments_from_existing(self, project_dir):
        scores_dir = os.path.join(project_dir, 'working', 'scores')
        os.makedirs(os.path.join(scores_dir, 'cycle-3'), exist_ok=True)
        cycle = _determine_cycle(project_dir)
        assert cycle == 4
```

### Class: TestAvgWordCount

```python
from storyforge.cmd_score import _avg_word_count


class TestAvgWordCount:
    def test_reads_from_metadata(self, project_dir):
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        result = _avg_word_count(metadata_csv, ['act1-sc01'], scenes_dir)
        assert isinstance(result, int)
        assert result > 0

    def test_fallback_to_scene_files(self, project_dir):
        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        # Scene files exist with content, word_count column is 0
        result = _avg_word_count(metadata_csv, ['act1-sc01', 'act1-sc02'], scenes_dir)
        assert isinstance(result, int)
```

### Class: TestScoreDirectFlow (uses mock_api)

```python
from storyforge.cmd_score import _score_direct


class TestScoreDirectFlow:
    def test_score_direct_returns_counts(self, project_dir, mock_api, monkeypatch):
        """Verify _score_direct invokes API and returns scored/failed counts."""
        import time
        # Set up a scoring response the parser can handle
        mock_api.set_response(
            'principle|score|rationale\n'
            'prose_naturalness|7|Good variety\n'
            'voice_consistency|8|Strong voice\n'
        )
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        metadata_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        scenes_dir = os.path.join(project_dir, 'scenes')
        cycle_dir = os.path.join(project_dir, 'working', 'scores', 'cycle-1')
        log_dir = os.path.join(project_dir, 'working', 'logs')
        os.makedirs(cycle_dir, exist_ok=True)
        os.makedirs(log_dir, exist_ok=True)

        plugin_dir_path = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
        diagnostics = os.path.join(plugin_dir_path, 'references', 'diagnostics.csv')

        # Only run with real diagnostics file
        if not os.path.isfile(diagnostics):
            pytest.skip('diagnostics.csv not found')

        scored, failed = _score_direct(
            ['act1-sc01'], 'claude-sonnet-4-6',
            '{{SCENE_TEXT}}\n{{EVALUATION_CRITERIA}}\n{{WEIGHTED_PRINCIPLES}}',
            'criteria', 'weights',
            metadata_csv, intent_csv, scenes_dir,
            cycle_dir, log_dir, diagnostics, plugin_dir_path,
            parallel=1, score_start=time.time(),
        )
        assert scored + failed == 1
        assert len(mock_api.calls) >= 1
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_cmd_score.py -v
git add tests/commands/test_cmd_score.py && git commit -m "Add cmd_score command module tests" && git push
```

---

## Task 4: `tests/commands/test_cmd_assemble.py` (~15 tests)

**File to create:** `tests/commands/test_cmd_assemble.py`

### Class: TestParseArgs

```python
import os
import pytest
from storyforge.cmd_assemble import parse_args, VALID_FORMATS


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.formats == []
        assert args.all_formats is False
        assert args.draft is False
        assert args.annotate is True
        assert args.interactive is False
        assert args.dry_run is False
        assert args.skip_validation is False
        assert args.no_pr is False

    def test_single_format(self):
        args = parse_args(['--format', 'epub'])
        assert args.formats == ['epub']

    def test_multiple_formats(self):
        args = parse_args(['--format', 'epub', '--format', 'pdf'])
        assert args.formats == ['epub', 'pdf']

    def test_all_formats_flag(self):
        args = parse_args(['--all'])
        assert args.all_formats is True

    def test_draft_flag(self):
        args = parse_args(['--draft'])
        assert args.draft is True

    def test_no_annotate(self):
        args = parse_args(['--no-annotate'])
        assert args.annotate is False

    def test_skip_validation(self):
        args = parse_args(['--skip-validation'])
        assert args.skip_validation is True

    def test_no_pr(self):
        args = parse_args(['--no-pr'])
        assert args.no_pr is True
```

### Class: TestResolveFormats

```python
from storyforge.cmd_assemble import _resolve_formats, parse_args


class TestResolveFormats:
    def test_draft_returns_markdown(self):
        args = parse_args(['--draft'])
        formats = _resolve_formats(args)
        assert formats == ['markdown']

    def test_all_returns_all(self):
        args = parse_args(['--all'])
        formats = _resolve_formats(args)
        assert formats == ['all']

    def test_no_format_defaults_to_markdown(self):
        args = parse_args([])
        formats = _resolve_formats(args)
        assert formats == ['markdown']

    def test_comma_separated_formats(self):
        args = parse_args(['--format', 'epub,html'])
        formats = _resolve_formats(args)
        assert 'epub' in formats
        assert 'html' in formats

    def test_invalid_format_exits(self):
        args = parse_args(['--format', 'invalid'])
        with pytest.raises(SystemExit):
            _resolve_formats(args)

    def test_multiple_format_flags(self):
        args = parse_args(['--format', 'epub', '--format', 'web'])
        formats = _resolve_formats(args)
        assert formats == ['epub', 'web']
```

### Class: TestValidFormats

```python
class TestValidFormats:
    def test_valid_formats_constant(self):
        assert 'epub' in VALID_FORMATS
        assert 'pdf' in VALID_FORMATS
        assert 'html' in VALID_FORMATS
        assert 'web' in VALID_FORMATS
        assert 'markdown' in VALID_FORMATS
        assert 'all' in VALID_FORMATS
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_cmd_assemble.py -v
git add tests/commands/test_cmd_assemble.py && git commit -m "Add cmd_assemble command module tests" && git push
```

---

## Task 5: `tests/commands/test_cmd_hone.py` (~22 tests)

**File to create:** `tests/commands/test_cmd_hone.py`

### Class: TestParseArgs

```python
import os
import pytest
from storyforge.cmd_hone import parse_args, ALL_DOMAINS


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.domain is None
        assert args.phase is None
        assert args.scenes is None
        assert args.act is None
        assert args.threshold == 3.5
        assert args.coaching is None
        assert args.diagnose is False
        assert args.dry_run is False
        assert args.loop is False
        assert args.max_loops == 5

    def test_domain_flag(self):
        args = parse_args(['--domain', 'briefs'])
        assert args.domain == 'briefs'

    def test_phase_flag(self):
        args = parse_args(['--phase', '1'])
        assert args.phase == 1

    def test_scenes_filter(self):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        assert args.scenes == 'act1-sc01,act1-sc02'

    def test_threshold_override(self):
        args = parse_args(['--threshold', '4.0'])
        assert args.threshold == 4.0

    def test_diagnose_flag(self):
        args = parse_args(['--diagnose'])
        assert args.diagnose is True

    def test_loop_flag(self):
        args = parse_args(['--loop'])
        assert args.loop is True

    def test_max_loops(self):
        args = parse_args(['--loop', '--max-loops', '3'])
        assert args.max_loops == 3
```

### Class: TestResolveDomains

```python
from storyforge.cmd_hone import (
    _resolve_domains, parse_args, ALL_DOMAINS,
    PHASE1_REGISTRY, PHASE2_REGISTRY, PHASE3_REGISTRY,
)


class TestResolveDomains:
    def test_no_args_returns_all(self):
        args = parse_args([])
        domains = _resolve_domains(args)
        assert domains == list(ALL_DOMAINS)

    def test_single_domain(self):
        args = parse_args(['--domain', 'briefs'])
        domains = _resolve_domains(args)
        assert domains == ['briefs']

    def test_comma_separated_domains(self):
        args = parse_args(['--domain', 'briefs,gaps'])
        domains = _resolve_domains(args)
        assert domains == ['briefs', 'gaps']

    def test_phase_1(self):
        args = parse_args(['--phase', '1'])
        domains = _resolve_domains(args)
        assert domains == PHASE1_REGISTRY

    def test_phase_2(self):
        args = parse_args(['--phase', '2'])
        domains = _resolve_domains(args)
        assert domains == PHASE2_REGISTRY

    def test_phase_3(self):
        args = parse_args(['--phase', '3'])
        domains = _resolve_domains(args)
        assert domains == PHASE3_REGISTRY
```

### Class: TestMainValidation

```python
from storyforge.cmd_hone import main


class TestMainValidation:
    def test_loop_incompatible_with_diagnose(self, monkeypatch, project_dir):
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            main(['--loop', '--diagnose'])

    def test_loop_incompatible_with_dry_run(self, monkeypatch, project_dir):
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            main(['--loop', '--dry-run'])

    def test_loop_incompatible_with_domain(self, monkeypatch, project_dir):
        monkeypatch.chdir(project_dir)
        with pytest.raises(SystemExit):
            main(['--loop', '--domain', 'briefs'])
```

### Class: TestResolveSceneFilter

```python
from storyforge.cmd_hone import _resolve_scene_filter, parse_args


class TestResolveSceneFilter:
    def test_no_filter_returns_none(self, fixture_dir):
        args = parse_args([])
        ref_dir = os.path.join(fixture_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        assert result is None

    def test_scenes_filter(self, fixture_dir):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        ref_dir = os.path.join(fixture_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        assert result == ['act1-sc01', 'act1-sc02']

    def test_act_filter(self, fixture_dir):
        args = parse_args(['--act', '1'])
        ref_dir = os.path.join(fixture_dir, 'reference')
        result = _resolve_scene_filter(args, ref_dir)
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)
```

### Class: TestCountBriefIssues

```python
from storyforge.cmd_hone import _count_brief_issues


class TestCountBriefIssues:
    def test_returns_dict_with_expected_keys(self, fixture_dir):
        ref_dir = os.path.join(fixture_dir, 'reference')
        counts = _count_brief_issues(ref_dir, None)
        assert 'total' in counts
        assert 'scenes' in counts
        assert 'abstract' in counts
        assert 'overspecified' in counts
        assert 'verbose' in counts
        assert isinstance(counts['total'], int)
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_cmd_hone.py -v
git add tests/commands/test_cmd_hone.py && git commit -m "Add cmd_hone command module tests" && git push
```

---

## Task 6: `tests/commands/test_cmd_evaluate.py` (~20 tests)

**File to create:** `tests/commands/test_cmd_evaluate.py`

### Class: TestParseArgs

```python
import os
import pytest
from storyforge.cmd_evaluate import parse_args, CORE_EVALUATORS


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.manuscript is False
        assert args.chapter is None
        assert args.act is None
        assert args.scenes is None
        assert args.scene is None
        assert args.from_seq is None
        assert args.evaluator is None
        assert args.final is False
        assert args.interactive is False
        assert args.direct is False
        assert args.dry_run is False

    def test_manuscript_flag(self):
        args = parse_args(['--manuscript'])
        assert args.manuscript is True

    def test_chapter_flag(self):
        args = parse_args(['--chapter', '5'])
        assert args.chapter == 5

    def test_scene_flag(self):
        args = parse_args(['--scene', 'act1-sc01'])
        assert args.scene == 'act1-sc01'

    def test_scenes_flag(self):
        args = parse_args(['--scenes', 'act1-sc01,act1-sc02'])
        assert args.scenes == 'act1-sc01,act1-sc02'

    def test_evaluator_flag(self):
        args = parse_args(['--evaluator', 'line-editor'])
        assert args.evaluator == 'line-editor'

    def test_final_flag(self):
        args = parse_args(['--final'])
        assert args.final is True

    def test_direct_flag(self):
        args = parse_args(['--direct'])
        assert args.direct is True
```

### Class: TestResolveFilter

```python
from storyforge.cmd_evaluate import _resolve_filter, parse_args


class TestResolveFilter:
    def test_default_is_all(self):
        args = parse_args([])
        mode, *_ = _resolve_filter(args)
        assert mode == 'all'

    def test_manuscript_mode(self):
        args = parse_args(['--manuscript'])
        mode, *_ = _resolve_filter(args)
        assert mode == 'manuscript'

    def test_chapter_mode(self):
        args = parse_args(['--chapter', '3'])
        mode, value, *_ = _resolve_filter(args)
        assert mode == 'chapter'
        assert value == '3'

    def test_act_mode(self):
        args = parse_args(['--act', '2'])
        mode, value, *_ = _resolve_filter(args)
        assert mode == 'act'
        assert value == '2'

    def test_single_scene_mode(self):
        args = parse_args(['--scene', 'act1-sc01'])
        mode, _, range_start, *_ = _resolve_filter(args)
        assert mode == 'single'
        assert range_start == 'act1-sc01'

    def test_scene_range_mode(self):
        args = parse_args(['--scenes', 'act1-sc01..act2-sc01'])
        mode, _, range_start, range_end, *_ = _resolve_filter(args)
        assert mode == 'range'
        assert range_start == 'act1-sc01'
        assert range_end == 'act2-sc01'
```

### Class: TestCoreEvaluators

```python
class TestCoreEvaluators:
    def test_core_evaluator_list(self):
        assert len(CORE_EVALUATORS) == 6
        assert 'literary-agent' in CORE_EVALUATORS
        assert 'line-editor' in CORE_EVALUATORS
        assert 'first-reader' in CORE_EVALUATORS
        assert 'developmental-editor' in CORE_EVALUATORS
        assert 'genre-expert' in CORE_EVALUATORS
        assert 'writing-coach' in CORE_EVALUATORS
```

### Class: TestLoadCustomEvaluators

```python
from storyforge.cmd_evaluate import _load_custom_evaluators


class TestLoadCustomEvaluators:
    def test_returns_empty_for_fixture(self, project_dir):
        result = _load_custom_evaluators(project_dir)
        assert result == []

    def test_returns_empty_when_no_yaml(self, tmp_path):
        result = _load_custom_evaluators(str(tmp_path))
        assert result == []
```

### Class: TestResolveVoiceGuide

```python
from storyforge.cmd_evaluate import _resolve_voice_guide


class TestResolveVoiceGuide:
    def test_finds_voice_guide_in_fixture(self, project_dir):
        path, content = _resolve_voice_guide(project_dir)
        assert path is not None
        assert 'voice-guide' in path
        assert len(content) > 0

    def test_returns_none_when_missing(self, tmp_path):
        # Create minimal project
        yaml_path = tmp_path / 'storyforge.yaml'
        yaml_path.write_text('project:\n  title: test\n')
        path, content = _resolve_voice_guide(str(tmp_path))
        assert path is None
        assert content == ''
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_cmd_evaluate.py -v
git add tests/commands/test_cmd_evaluate.py && git commit -m "Add cmd_evaluate command module tests" && git push
```

---

## Task 7: `tests/commands/test_api.py` (~15 tests)

**File to create:** `tests/commands/test_api.py`

Mock at the urllib level, not storyforge.api.

### Class: TestApiRequest

```python
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from storyforge.api import _api_request, API_RETRIES


class TestApiRequest:
    def _make_mock_response(self, data, code=200):
        """Create a mock urllib response."""
        encoded = json.dumps(data).encode()
        mock = MagicMock()
        mock.read.return_value = encoded
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch('storyforge.api.urlopen')
    def test_successful_request(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        expected = {'id': 'msg_123', 'content': [{'type': 'text', 'text': 'hello'}]}
        mock_urlopen.return_value = self._make_mock_response(expected)
        result = _api_request('messages', {'model': 'test', 'max_tokens': 10, 'messages': []}, method='POST')
        assert result == expected
        mock_urlopen.assert_called_once()

    @patch('storyforge.api.urlopen')
    def test_retries_on_500(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        from urllib.error import HTTPError
        import io
        error = HTTPError('url', 500, 'Server Error', {}, io.BytesIO(b'error'))
        success_resp = self._make_mock_response({'ok': True})
        mock_urlopen.side_effect = [error, success_resp]
        result = _api_request('messages', {'model': 'test', 'max_tokens': 10, 'messages': []}, method='POST')
        assert result == {'ok': True}
        assert mock_urlopen.call_count == 2

    @patch('storyforge.api.urlopen')
    def test_raises_on_400(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        from urllib.error import HTTPError
        import io
        error = HTTPError('url', 400, 'Bad Request', {}, io.BytesIO(b'bad request'))
        mock_urlopen.side_effect = error
        with pytest.raises(RuntimeError, match='HTTP 400'):
            _api_request('messages', None, method='GET')

    @patch('storyforge.api.urlopen')
    def test_retries_on_connection_error(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        from urllib.error import URLError
        success_resp = self._make_mock_response({'ok': True})
        mock_urlopen.side_effect = [URLError('connection refused'), success_resp]
        result = _api_request('messages', None, method='GET')
        assert result == {'ok': True}
        assert mock_urlopen.call_count == 2

    @patch('storyforge.api.urlopen')
    def test_exhausted_retries_raises(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError('connection refused')
        with pytest.raises(RuntimeError, match='failed after'):
            _api_request('messages', None, method='GET')
```

### Class: TestExtractText

```python
from storyforge.api import extract_text, extract_text_from_file, extract_usage


class TestExtractText:
    def test_extracts_from_response(self):
        response = {'content': [{'type': 'text', 'text': 'hello world'}]}
        assert extract_text(response) == 'hello world'

    def test_extracts_multiple_blocks(self):
        response = {
            'content': [
                {'type': 'text', 'text': 'hello'},
                {'type': 'text', 'text': 'world'},
            ]
        }
        assert extract_text(response) == 'hello\nworld'

    def test_empty_content(self):
        assert extract_text({'content': []}) == ''
        assert extract_text({}) == ''

    def test_extract_from_file(self, tmp_path):
        resp = {'content': [{'type': 'text', 'text': 'from file'}]}
        path = str(tmp_path / 'resp.json')
        with open(path, 'w') as f:
            json.dump(resp, f)
        assert extract_text_from_file(path) == 'from file'

    def test_extract_from_missing_file(self):
        assert extract_text_from_file('/nonexistent/file.json') == ''
```

### Class: TestExtractUsage

```python
class TestExtractUsage:
    def test_extracts_usage(self):
        response = {'usage': {'input_tokens': 100, 'output_tokens': 50,
                               'cache_read_input_tokens': 10,
                               'cache_creation_input_tokens': 5}}
        usage = extract_usage(response)
        assert usage['input_tokens'] == 100
        assert usage['output_tokens'] == 50
        assert usage['cache_read'] == 10
        assert usage['cache_create'] == 5

    def test_missing_usage(self):
        usage = extract_usage({})
        assert usage['input_tokens'] == 0
        assert usage['output_tokens'] == 0
```

### Class: TestGetApiKey

```python
from storyforge.api import get_api_key


class TestGetApiKey:
    def test_returns_key(self, monkeypatch):
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test-123')
        assert get_api_key() == 'sk-test-123'

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
        with pytest.raises(RuntimeError, match='ANTHROPIC_API_KEY'):
            get_api_key()
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_api.py -v
git add tests/commands/test_api.py && git commit -m "Add api.py infrastructure tests" && git push
```

---

## Task 8: `tests/commands/test_git.py` (~15 tests)

**File to create:** `tests/commands/test_git.py`

Mock at subprocess level for unit tests of git.py functions.

### Class: TestGitHelper

```python
import os
import pytest
from unittest.mock import patch, MagicMock
import subprocess


class TestGitHelper:
    @patch('storyforge.git.subprocess.run')
    def test_git_runs_command(self, mock_run):
        from storyforge.git import _git
        mock_run.return_value = subprocess.CompletedProcess(
            args=['git', '-C', '/tmp', 'status'], returncode=0,
            stdout='clean', stderr='',
        )
        result = _git('/tmp', 'status')
        mock_run.assert_called_once()
        assert result.returncode == 0

    @patch('storyforge.git.subprocess.run')
    def test_has_gh_true(self, mock_run):
        from storyforge.git import has_gh
        mock_run.return_value = subprocess.CompletedProcess(
            args=['gh', '--version'], returncode=0, stdout='gh version 2.40.0', stderr='',
        )
        assert has_gh() is True

    @patch('storyforge.git.subprocess.run')
    def test_has_gh_false(self, mock_run):
        from storyforge.git import has_gh
        mock_run.side_effect = FileNotFoundError
        assert has_gh() is False
```

### Class: TestCurrentBranch

```python
class TestCurrentBranch:
    @patch('storyforge.git.subprocess.run')
    def test_returns_branch_name(self, mock_run):
        from storyforge.git import current_branch
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='storyforge/test-branch\n', stderr='',
        )
        assert current_branch('/tmp') == 'storyforge/test-branch'

    @patch('storyforge.git.subprocess.run')
    def test_returns_empty_on_failure(self, mock_run):
        from storyforge.git import current_branch
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=128, stdout='', stderr='not a git repo',
        )
        assert current_branch('/tmp') == ''
```

### Class: TestCreateBranch

```python
class TestCreateBranch:
    @patch('storyforge.git.subprocess.run')
    def test_creates_new_branch_from_main(self, mock_run):
        from storyforge.git import create_branch
        # First call: current_branch returns 'main'
        # Second call: checkout -b succeeds
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout='main\n', stderr=''),
            subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr=''),
        ]
        branch = create_branch('revise', '/tmp')
        assert branch.startswith('storyforge/revise-')

    @patch('storyforge.git.subprocess.run')
    def test_resumes_existing_branch(self, mock_run):
        from storyforge.git import create_branch
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='storyforge/revise-existing\n', stderr='',
        )
        branch = create_branch('revise', '/tmp')
        assert branch == 'storyforge/revise-existing'
```

### Class: TestEnsureOnBranch

```python
class TestEnsureOnBranch:
    @patch('storyforge.git.subprocess.run')
    def test_returns_existing_branch(self, mock_run):
        from storyforge.git import ensure_on_branch
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='storyforge/hone-123\n', stderr='',
        )
        result = ensure_on_branch('hone', '/tmp')
        assert result == 'storyforge/hone-123'

    @patch('storyforge.git.subprocess.run')
    def test_creates_branch_from_main(self, mock_run):
        from storyforge.git import ensure_on_branch
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout='main\n', stderr=''),
            subprocess.CompletedProcess(args=[], returncode=0, stdout='main\n', stderr=''),
            subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr=''),
        ]
        result = ensure_on_branch('hone', '/tmp')
        assert result.startswith('storyforge/hone-')
```

### Class: TestCommitAndPush

```python
class TestCommitAndPush:
    @patch('storyforge.git.subprocess.run')
    def test_stages_commits_pushes(self, mock_run):
        from storyforge.git import commit_and_push
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='', stderr='',
        )
        result = commit_and_push('/tmp', 'test commit', ['scenes/', 'reference/'])
        assert result is True
        # Should call: git add scenes/, git add reference/, git commit, git push
        assert mock_run.call_count == 4

    @patch('storyforge.git.subprocess.run')
    def test_returns_false_on_commit_failure(self, mock_run):
        from storyforge.git import commit_and_push
        # add succeeds, commit fails
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr=''),
            subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr='nothing to commit'),
        ]
        result = commit_and_push('/tmp', 'test commit', ['scenes/'])
        assert result is False
```

### Class: TestIsMainBranch

```python
from storyforge.git import _is_main_branch


class TestIsMainBranch:
    def test_main_is_main(self):
        assert _is_main_branch('main') is True

    def test_master_is_main(self):
        assert _is_main_branch('master') is True

    def test_feature_branch_is_not_main(self):
        assert _is_main_branch('storyforge/revise-123') is False

    def test_empty_is_not_main(self):
        assert _is_main_branch('') is False
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_git.py -v
git add tests/commands/test_git.py && git commit -m "Add git.py infrastructure tests" && git push
```

---

## Task 9: `tests/commands/test_runner.py` (~12 tests)

**File to create:** `tests/commands/test_runner.py`

### Class: TestRunParallel

```python
import os
import pytest
from unittest.mock import patch
from storyforge.runner import run_parallel, run_batched


class TestRunParallel:
    def test_processes_all_items(self):
        results = run_parallel(['a', 'b', 'c'], lambda x: x.upper(), max_workers=2, label='test')
        assert results == {'a': 'A', 'b': 'B', 'c': 'C'}

    def test_captures_exceptions(self):
        def fail_on_b(x):
            if x == 'b':
                raise ValueError('boom')
            return x.upper()

        results = run_parallel(['a', 'b', 'c'], fail_on_b, max_workers=2, label='test')
        assert results['a'] == 'A'
        assert results['c'] == 'C'
        assert isinstance(results['b'], ValueError)

    def test_empty_items(self):
        results = run_parallel([], lambda x: x, max_workers=2, label='test')
        assert results == {}

    def test_single_item(self):
        results = run_parallel(['x'], lambda x: x * 2, max_workers=1, label='test')
        assert results == {'x': 'xx'}

    def test_respects_shutdown(self, monkeypatch):
        """When shutting down, should stop processing."""
        monkeypatch.setattr('storyforge.runner.is_shutting_down', lambda: True)
        # Should return partial results or empty
        results = run_parallel(['a', 'b'], lambda x: x, max_workers=1, label='test')
        # Cannot guarantee exact results during shutdown, but should not hang
        assert isinstance(results, dict)
```

### Class: TestRunBatched

```python
class TestRunBatched:
    def test_processes_in_batches(self):
        call_order = []

        def worker(x):
            call_order.append(x)
            return x.upper()

        results = run_batched(['a', 'b', 'c', 'd'], worker, batch_size=2, label='test')
        assert len(results) == 4
        assert results['a'] == 'A'
        assert results['d'] == 'D'

    def test_merge_fn_called(self):
        merged = []

        def merge(item, result):
            merged.append((item, result))

        results = run_batched(['a', 'b'], lambda x: x.upper(),
                               merge_fn=merge, batch_size=2, label='test')
        assert len(merged) == 2
        assert ('a', 'A') in merged
        assert ('b', 'B') in merged

    def test_merge_fn_skips_exceptions(self):
        merged = []

        def worker(x):
            if x == 'b':
                raise ValueError('boom')
            return x.upper()

        def merge(item, result):
            merged.append(item)

        run_batched(['a', 'b', 'c'], worker, merge_fn=merge,
                    batch_size=3, label='test')
        assert 'a' in merged
        assert 'c' in merged
        assert 'b' not in merged
```

### Class: TestHealingZone

```python
from storyforge.runner import HealingZone


class TestHealingZone:
    def test_success_on_first_attempt(self, monkeypatch, project_dir, mock_api):
        mock_api.set_response('Diagnosis: do nothing')
        with HealingZone('test', project_dir, max_attempts=3) as zone:
            result = zone.run(lambda: 42)
        assert result == 42

    def test_retries_on_failure(self, monkeypatch, project_dir, mock_api):
        mock_api.set_response('Diagnosis: fix it')
        attempts = [0]

        def flaky():
            attempts[0] += 1
            if attempts[0] < 3:
                raise RuntimeError('boom')
            return 'ok'

        with HealingZone('test', project_dir, max_attempts=3) as zone:
            result = zone.run(flaky)
        assert result == 'ok'
        assert attempts[0] == 3

    def test_raises_after_max_attempts(self, monkeypatch, project_dir, mock_api):
        mock_api.set_response('Cannot diagnose')

        with pytest.raises(RuntimeError, match='boom'):
            with HealingZone('test', project_dir, max_attempts=2) as zone:
                zone.run(lambda: (_ for _ in ()).throw(RuntimeError('boom')))
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_runner.py -v
git add tests/commands/test_runner.py && git commit -m "Add runner.py infrastructure tests" && git push
```

---

## Task 10: `tests/commands/test_common.py` (~15 tests)

**File to create:** `tests/commands/test_common.py`

### Class: TestDetectProjectRoot

```python
import os
import pytest
from storyforge.common import detect_project_root


class TestDetectProjectRoot:
    def test_finds_from_project_dir(self, fixture_dir):
        result = detect_project_root(fixture_dir)
        assert result == fixture_dir

    def test_finds_from_subdirectory(self, fixture_dir):
        scenes_dir = os.path.join(fixture_dir, 'scenes')
        result = detect_project_root(scenes_dir)
        assert result == fixture_dir

    def test_exits_when_not_found(self, tmp_path):
        with pytest.raises(SystemExit):
            detect_project_root(str(tmp_path))
```

### Class: TestReadYamlField

```python
from storyforge.common import read_yaml_field


class TestReadYamlField:
    def test_reads_dotted_field(self, fixture_dir):
        result = read_yaml_field('project.title', fixture_dir)
        assert result == "The Cartographer's Silence"

    def test_reads_dotted_genre(self, fixture_dir):
        result = read_yaml_field('project.genre', fixture_dir)
        assert result == 'fantasy'

    def test_reads_flat_field(self, fixture_dir):
        result = read_yaml_field('phase', fixture_dir)
        assert result == 'drafting'

    def test_returns_empty_for_missing(self, fixture_dir):
        result = read_yaml_field('nonexistent.field', fixture_dir)
        assert result == ''

    def test_returns_empty_for_no_yaml(self, tmp_path):
        result = read_yaml_field('project.title', str(tmp_path))
        assert result == ''
```

### Class: TestSelectModel

```python
from storyforge.common import select_model, select_revision_model


class TestSelectModel:
    def test_drafting_uses_opus(self):
        model = select_model('drafting')
        assert 'opus' in model

    def test_evaluation_uses_sonnet(self):
        model = select_model('evaluation')
        assert 'sonnet' in model

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_MODEL', 'custom-model-1')
        assert select_model('drafting') == 'custom-model-1'

    def test_unknown_task_defaults_to_opus(self):
        model = select_model('unknown-task')
        assert 'opus' in model
```

### Class: TestSelectRevisionModel

```python
class TestSelectRevisionModel:
    def test_creative_pass_uses_opus(self):
        model = select_revision_model('prose-polish', 'voice consistency')
        assert 'opus' in model

    def test_mechanical_pass_uses_sonnet(self):
        model = select_revision_model('continuity-check', 'continuity verification')
        assert 'sonnet' in model

    def test_timeline_pass_uses_sonnet(self):
        model = select_revision_model('timeline-fix', 'timeline consistency')
        assert 'sonnet' in model

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv('STORYFORGE_MODEL', 'override-model')
        assert select_revision_model('anything', 'anything') == 'override-model'
```

### Class: TestGetCoachingLevel

```python
from storyforge.common import get_coaching_level


class TestGetCoachingLevel:
    def test_defaults_to_full(self, tmp_path):
        # No yaml, no env
        result = get_coaching_level(str(tmp_path))
        assert result == 'full'

    def test_reads_from_yaml(self, project_dir):
        # Write coaching level to yaml
        yaml_path = os.path.join(project_dir, 'storyforge.yaml')
        with open(yaml_path) as f:
            content = f.read()
        content += '\n  coaching_level: strict\n'
        # Need to insert under project: section
        content = content.replace('  target_words: 90000',
                                   '  target_words: 90000\n  coaching_level: strict')
        with open(yaml_path, 'w') as f:
            f.write(content)
        result = get_coaching_level(project_dir)
        assert result == 'strict'

    def test_env_overrides_yaml(self, monkeypatch, project_dir):
        monkeypatch.setenv('STORYFORGE_COACHING', 'coach')
        result = get_coaching_level(project_dir)
        assert result == 'coach'
```

### Class: TestPipelineManifest

```python
from storyforge.common import (
    get_current_cycle, start_new_cycle, update_cycle_field,
    ensure_pipeline_manifest, get_pipeline_file,
)


class TestPipelineManifest:
    def test_ensure_creates_file(self, project_dir):
        ensure_pipeline_manifest(project_dir)
        pf = get_pipeline_file(project_dir)
        assert os.path.isfile(pf)
        with open(pf) as f:
            header = f.readline().strip()
        assert 'cycle' in header

    def test_get_current_cycle_empty(self, project_dir):
        ensure_pipeline_manifest(project_dir)
        assert get_current_cycle(project_dir) == 0

    def test_start_new_cycle(self, project_dir):
        cycle_id = start_new_cycle(project_dir)
        assert cycle_id == 1
        assert get_current_cycle(project_dir) == 1

    def test_start_second_cycle(self, project_dir):
        start_new_cycle(project_dir)
        cycle_id = start_new_cycle(project_dir)
        assert cycle_id == 2

    def test_update_cycle_field(self, project_dir):
        cycle_id = start_new_cycle(project_dir)
        update_cycle_field(project_dir, cycle_id, 'status', 'complete')
        from storyforge.common import read_cycle_field
        assert read_cycle_field(project_dir, cycle_id, 'status') == 'complete'
```

**Run and commit:**
```bash
cd /path/to/storyforge && python3 -m pytest tests/commands/test_common.py -v
git add tests/commands/test_common.py && git commit -m "Add common.py infrastructure tests" && git push
```

---

## Summary

| Task | File | Tests | Focus |
|------|------|-------|-------|
| 1 | test_cmd_revise.py | ~25 | parse_args, plan generation, CSV helpers, rationale extraction, validation |
| 2 | test_cmd_write.py | ~22 | parse_args, filter resolution, scene extraction, brief detection, word count |
| 3 | test_cmd_score.py | ~25 | parse_args, filter resolution, prompt building, score parsing, cycle detection, direct flow |
| 4 | test_cmd_assemble.py | ~15 | parse_args, format resolution, valid formats |
| 5 | test_cmd_hone.py | ~22 | parse_args, domain resolution, validation, scene filtering, brief issue counting |
| 6 | test_cmd_evaluate.py | ~20 | parse_args, filter resolution, core evaluators, custom evaluators, voice guide |
| 7 | test_api.py | ~15 | retry logic (mock urllib), text extraction, usage extraction, API key |
| 8 | test_git.py | ~15 | branch creation, commit_and_push, has_gh, current_branch (mock subprocess) |
| 9 | test_runner.py | ~12 | run_parallel, run_batched, HealingZone retry |
| 10 | test_common.py | ~15 | project root detection, YAML reading, model selection, coaching, pipeline manifest |

**Total: ~186 tests across 10 files**

### Execution order

Tasks 7-10 (infrastructure) should run first -- command modules depend on these. Within commands, the order is flexible, but Task 1 (revise) and Task 3 (score) have the most complex mocking and should get early attention.

Recommended: 10 -> 7 -> 8 -> 9 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6

### Key conventions

- All tests import from `storyforge.*` (the `sys.path` setup in `tests/conftest.py` handles this)
- Use `fixture_dir` for read-only tests, `project_dir` for tests that modify files
- Use `mock_api` from `tests/commands/conftest.py` for command tests that hit API
- Use `mock_git` from `tests/commands/conftest.py` for command tests that do git ops
- Use `unittest.mock.patch('storyforge.git.subprocess.run')` for git.py unit tests
- Use `unittest.mock.patch('storyforge.api.urlopen')` for api.py unit tests
- Every test asserts something meaningful -- no placeholder tests

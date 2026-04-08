"""Integration tests for error recovery and resilience.

Tests graceful degradation on API failures, missing files, empty
responses, and the HealingZone retry mechanism.
"""

import os
import subprocess

import pytest

from storyforge.runner import HealingZone, run_parallel


# ---------------------------------------------------------------------------
# HealingZone retry behavior
# ---------------------------------------------------------------------------

class TestHealingZone:
    """Test the HealingZone retry-with-diagnosis mechanism."""

    def test_succeeds_on_first_try(self, project_dir, mock_api, monkeypatch):
        monkeypatch.chdir(project_dir)

        def always_works():
            return 42

        with HealingZone('test op', project_dir) as zone:
            result = zone.run(always_works)
        assert result == 42

    def test_retries_on_failure(self, project_dir, mock_api, monkeypatch):
        monkeypatch.chdir(project_dir)
        mock_api.set_response('Try checking the file path.')

        call_count = 0

        def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError('Temporary error')
            return 'ok'

        with HealingZone('test retry', project_dir, max_attempts=3) as zone:
            result = zone.run(fails_then_succeeds)
        assert result == 'ok'
        assert call_count == 3

    def test_exhausts_attempts(self, project_dir, mock_api, monkeypatch):
        monkeypatch.chdir(project_dir)
        mock_api.set_response('Cannot determine cause.')

        def always_fails():
            raise RuntimeError('Permanent error')

        with HealingZone('test exhaust', project_dir, max_attempts=2) as zone:
            with pytest.raises(RuntimeError, match='Permanent error'):
                zone.run(always_fails)

    def test_invokes_api_for_diagnosis(self, project_dir, mock_api, monkeypatch):
        monkeypatch.chdir(project_dir)
        mock_api.set_response('The file does not exist. Check the path.')

        call_count = 0

        def fails_once():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise FileNotFoundError('missing.csv')
            return 'recovered'

        with HealingZone('test diagnosis', project_dir, max_attempts=3) as zone:
            result = zone.run(fails_once)
        assert result == 'recovered'

        # Should have called invoke_api for diagnosis
        api_calls = [c for c in mock_api.calls if c['fn'] == 'invoke_api']
        assert len(api_calls) >= 1

    def test_context_manager_doesnt_suppress(self, project_dir, mock_api, monkeypatch):
        monkeypatch.chdir(project_dir)

        with pytest.raises(ZeroDivisionError):
            with HealingZone('test suppress', project_dir, max_attempts=1) as zone:
                zone.run(lambda: 1 / 0)


# ---------------------------------------------------------------------------
# run_parallel resilience
# ---------------------------------------------------------------------------

class TestRunParallelResilience:
    """Test that run_parallel handles worker failures gracefully."""

    def test_failed_worker_returns_exception(self):
        def worker(item):
            if item == 'bad':
                raise ValueError('Bad item')
            return f'ok-{item}'

        results = run_parallel(['good', 'bad', 'fine'], worker, max_workers=3)
        assert results['good'] == 'ok-good'
        assert results['fine'] == 'ok-fine'
        assert isinstance(results['bad'], ValueError)

    def test_all_workers_fail(self):
        def worker(item):
            raise RuntimeError(f'fail-{item}')

        results = run_parallel(['a', 'b'], worker, max_workers=2)
        assert isinstance(results['a'], RuntimeError)
        assert isinstance(results['b'], RuntimeError)

    def test_empty_items_raises(self):
        # NOTE: run_parallel with empty items hits max_workers=0 which
        # raises ValueError from ThreadPoolExecutor. This is a known
        # edge case — callers should check for empty items first.
        with pytest.raises(ValueError, match='max_workers must be greater than 0'):
            run_parallel([], lambda x: x, max_workers=1)


# ---------------------------------------------------------------------------
# Missing scene files
# ---------------------------------------------------------------------------

class TestMissingSceneFiles:
    """Test that commands handle missing scene files gracefully."""

    def test_score_no_scene_files_exits(self, project_dir, mock_api, mock_git, monkeypatch):
        """cmd_score should exit if no drafted scene files exist."""
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        # Remove all scene files
        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        from storyforge.cmd_score import main
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_write_nothing_to_draft(self, project_dir, mock_api, mock_git, monkeypatch, capsys):
        """cmd_write with all scenes drafted should report nothing to do."""
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

        # Mark all scenes as drafted in CSV with high word counts
        from storyforge.csv_cli import update_field
        metadata = os.path.join(project_dir, 'reference', 'scenes.csv')
        from storyforge.scene_filter import build_scene_list
        all_ids = build_scene_list(metadata)
        for sid in all_ids:
            update_field(metadata, sid, 'status', 'drafted')
            # Also create scene files with enough content
            scene_file = os.path.join(project_dir, 'scenes', f'{sid}.md')
            if not os.path.isfile(scene_file):
                with open(scene_file, 'w') as f:
                    f.write('Content here. ' * 100)

        from storyforge.cmd_write import main
        main(['--direct'])

        out = capsys.readouterr().out
        assert 'Nothing to draft' in out

    def test_extract_no_scenes_exits(self, project_dir, mock_api, mock_git, monkeypatch):
        """cmd_extract should exit if no scene files exist."""
        monkeypatch.chdir(project_dir)
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

        scenes_dir = os.path.join(project_dir, 'scenes')
        for f in os.listdir(scenes_dir):
            os.remove(os.path.join(scenes_dir, f))

        from storyforge.cmd_extract import main
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Empty API responses
# ---------------------------------------------------------------------------

class TestEmptyApiResponses:
    """Test that empty API responses don't crash processing."""

    def test_extract_text_from_empty_file(self, tmp_path):
        """extract_text_from_file should return empty string for missing files."""
        from storyforge.api import extract_text_from_file
        result = extract_text_from_file(str(tmp_path / 'nonexistent.json'))
        assert result == '' or result is None

    def test_extract_text_from_malformed_json(self, tmp_path):
        """extract_text_from_file should handle malformed JSON gracefully."""
        from storyforge.api import extract_text_from_file
        bad_file = tmp_path / 'bad.json'
        bad_file.write_text('not json at all')
        result = extract_text_from_file(str(bad_file))
        assert result == '' or result is None

    def test_extract_text_from_empty_content(self, tmp_path):
        """extract_text_from_file should handle response with empty content."""
        import json
        from storyforge.api import extract_text_from_file
        empty_response = {'content': [], 'usage': {'input_tokens': 0, 'output_tokens': 0}}
        file_path = tmp_path / 'empty.json'
        file_path.write_text(json.dumps(empty_response))
        result = extract_text_from_file(str(file_path))
        assert result == '' or result is None


# ---------------------------------------------------------------------------
# API failure in scoring
# ---------------------------------------------------------------------------

class TestScoringApiFailure:
    """Test that API failures during scoring degrade gracefully."""

    def test_score_dry_run_no_api_needed(self, project_dir, mock_git, monkeypatch, capsys):
        """Scoring dry-run should work even without API access."""
        monkeypatch.chdir(project_dir)
        monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

        # Ensure scene files exist
        scenes_dir = os.path.join(project_dir, 'scenes')
        for sid in ['act1-sc01', 'act1-sc02']:
            fpath = os.path.join(scenes_dir, f'{sid}.md')
            if not os.path.isfile(fpath):
                with open(fpath, 'w') as f:
                    f.write('Test scene content. ' * 100)

        from storyforge.cmd_score import main
        main(['--dry-run'])

        out = capsys.readouterr().out
        assert 'DRY RUN' in out or 'dry' in out.lower()

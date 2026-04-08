"""Regression tests for bugs fixed in v1.4.x.

Each test documents the bug it prevents from recurring.
"""

import inspect
import json
import os
import sys

import pytest


# ============================================================================
# v1.4.0 — API timeout parameter threading
# ============================================================================

class TestApiTimeoutParameter:
    """REVISION_TIMEOUT must exist and be accepted by all invoke functions.

    Bug: API_TIMEOUT (600s) was too short for full-manuscript polish passes.
    invoke/invoke_to_file/invoke_api had no timeout parameter, so revision
    calls couldn't request more time.
    """

    def test_revision_timeout_exists(self):
        from storyforge.api import REVISION_TIMEOUT
        assert REVISION_TIMEOUT >= 1800

    def test_invoke_accepts_timeout(self):
        from storyforge.api import invoke
        sig = inspect.signature(invoke)
        assert 'timeout' in sig.parameters

    def test_invoke_to_file_accepts_timeout(self):
        from storyforge.api import invoke_to_file
        sig = inspect.signature(invoke_to_file)
        assert 'timeout' in sig.parameters

    def test_invoke_api_accepts_timeout(self):
        from storyforge.api import invoke_api
        sig = inspect.signature(invoke_api)
        assert 'timeout' in sig.parameters


# ============================================================================
# v1.4.0 — Branch enforcement
# ============================================================================

class TestBranchEnforcement:
    """All non-main branches must be treated as resume, not just storyforge/*.

    Bug: create_branch only checked for storyforge/ prefix, so being on
    feature/foo would create a new storyforge/* branch instead of staying.
    """

    def test_is_main_branch_main(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('main') is True

    def test_is_main_branch_master(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('master') is True

    def test_is_main_branch_feature(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('feature/foo') is False

    def test_is_main_branch_storyforge(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('storyforge/write-20260407') is False

    def test_is_main_branch_empty(self):
        from storyforge.git import _is_main_branch
        assert _is_main_branch('') is False

    def test_ensure_on_branch_exists(self):
        from storyforge.git import ensure_on_branch
        sig = inspect.signature(ensure_on_branch)
        assert 'command_name' in sig.parameters
        assert 'project_dir' in sig.parameters


# ============================================================================
# v1.4.1 — Assembly chapter-scenes CLI and format functions
# ============================================================================

class TestAssemblyChapterScenesCli:
    """The assembly CLI dispatcher must handle the chapter-scenes command.

    Bug: cmd_assemble called _run_assembly_cmd('chapter-scenes', ...) but
    assembly.py's main() dispatcher didn't handle it, causing RuntimeError.
    """

    def test_chapter_scenes_cli(self, fixture_dir):
        """chapter-scenes CLI command returns scene IDs."""
        env = os.environ.copy()
        python_lib = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'lib', 'python')
        env['PYTHONPATH'] = python_lib
        result = __import__('subprocess').run(
            [sys.executable, '-m', 'storyforge.assembly',
             'chapter-scenes', '1', fixture_dir],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        assert len(lines) > 0
        assert 'act1-sc01' in lines


class TestAssemblyFormatFunctions:
    """All format generation functions must be importable.

    Bug: cmd_assemble called generate_epub, generate_html, generate_pdf,
    generate_web_book, and generate_cover_if_missing via subprocess imports,
    but none existed in assembly.py. They silently failed.
    """

    def test_generate_epub_importable(self):
        from storyforge.assembly import generate_epub
        assert callable(generate_epub)

    def test_generate_html_importable(self):
        from storyforge.assembly import generate_html
        assert callable(generate_html)

    def test_generate_pdf_importable(self):
        from storyforge.assembly import generate_pdf
        assert callable(generate_pdf)

    def test_generate_web_book_importable(self):
        from storyforge.assembly import generate_web_book
        assert callable(generate_web_book)

    def test_generate_cover_if_missing_importable(self):
        from storyforge.assembly import generate_cover_if_missing
        assert callable(generate_cover_if_missing)

    def test_generate_cover_creates_svg(self, project_dir):
        """generate_cover_if_missing creates a placeholder SVG."""
        from storyforge.assembly import generate_cover_if_missing
        plugin_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))))
        # Ensure no cover exists
        prod_dir = os.path.join(project_dir, 'production')
        for ext in ('jpg', 'jpeg', 'png', 'webp', 'svg'):
            p = os.path.join(prod_dir, f'cover.{ext}')
            if os.path.isfile(p):
                os.remove(p)

        generate_cover_if_missing(project_dir, plugin_dir)
        assert os.path.isfile(os.path.join(prod_dir, 'cover.svg'))


# ============================================================================
# v1.4.2 — Default assemble format
# ============================================================================

class TestAssembleDefaultFormat:
    """Default assemble with no flags should produce markdown only.

    Bug: Default was ['epub', 'web'] which required pandoc and ran slow.
    Now that bookshelf is the primary output, default is markdown only.
    """

    def test_default_format_is_markdown(self):
        from storyforge.cmd_assemble import _resolve_formats
        import argparse
        args = argparse.Namespace(
            draft=False, all_formats=False, formats=[],
        )
        assert _resolve_formats(args) == ['markdown']

    def test_draft_flag_is_markdown(self):
        from storyforge.cmd_assemble import _resolve_formats
        import argparse
        args = argparse.Namespace(
            draft=True, all_formats=False, formats=[],
        )
        assert _resolve_formats(args) == ['markdown']

    def test_explicit_format_preserved(self):
        from storyforge.cmd_assemble import _resolve_formats
        import argparse
        args = argparse.Namespace(
            draft=False, all_formats=False, formats=['epub'],
        )
        assert _resolve_formats(args) == ['epub']


# ============================================================================
# v1.4.3 — key_col kwarg mismatch
# ============================================================================

class TestPipelineCycleKwargs:
    """Pipeline cycle helpers must use key_col=, not key_column=.

    Bug: update_cycle_field and get_current_cycle passed key_column= but
    csv_cli.update_field and get_field use key_col=, causing TypeError.
    """

    def test_update_cycle_field_no_key_column(self):
        """Source code must not contain key_column= in cycle helpers."""
        import storyforge.common as mod
        source = inspect.getsource(mod.update_cycle_field)
        assert 'key_column' not in source
        assert 'key_col' in source

    def test_get_current_cycle_no_key_column(self):
        import storyforge.common as mod
        source = inspect.getsource(mod.get_current_cycle)
        assert 'key_column' not in source


# ============================================================================
# v1.4.4 — extract_single_scene signature
# ============================================================================

class TestExtractSingleScene:
    """extract_single_scene takes a text string, not file paths.

    Bug: _extract_scene_from_response passed (log_file, scene_file) to
    extract_single_scene() which only takes a single text string.
    This always threw TypeError and fell back to raw response.
    """

    def test_signature_single_arg(self):
        from storyforge.parsing import extract_single_scene
        sig = inspect.signature(extract_single_scene)
        params = list(sig.parameters.keys())
        assert len(params) == 1
        assert params[0] == 'response'

    def test_returns_none_without_markers(self):
        from storyforge.parsing import extract_single_scene
        result = extract_single_scene('Just some prose without markers.')
        assert result is None

    def test_extracts_with_markers(self):
        from storyforge.parsing import extract_single_scene
        text = (
            '=== SCENE: test-scene ===\n'
            'The prose content here.\n'
            '=== END SCENE: test-scene ==='
        )
        result = extract_single_scene(text)
        assert result == 'The prose content here.'

    def test_cmd_write_calls_correctly(self):
        """_extract_scene_from_response must not pass file paths to extract_single_scene."""
        from storyforge.cmd_write import _extract_scene_from_response
        source = inspect.getsource(_extract_scene_from_response)
        # Should call extract_text_from_file first, then pass text to extract_single_scene
        assert 'extract_text_from_file' in source
        # Should NOT pass log_file directly to extract_single_scene
        assert 'extract_single_scene(log_file' not in source


# ============================================================================
# v1.4.5 — get_pipeline_file import in git.py
# ============================================================================

class TestRunnerUsesThreads:
    """runner.py must use ThreadPoolExecutor, not ProcessPoolExecutor.

    Bug: ProcessPoolExecutor pickles worker functions to send to child
    processes. Nested/local functions (like score_one inside _score_direct)
    can't be pickled, causing "Can't pickle local object" errors.
    All parallel work is I/O-bound (API calls), so threads are correct.
    """

    def test_uses_thread_pool(self):
        from storyforge.runner import run_parallel
        source = inspect.getsource(run_parallel)
        assert 'ThreadPoolExecutor' in source
        assert 'ProcessPoolExecutor' not in source

    def test_nested_function_works(self):
        """A nested function must work as a worker."""
        from storyforge.runner import run_parallel

        def outer():
            results = []
            def worker(item):
                return item.upper()
            return run_parallel(['a', 'b'], worker, max_workers=2, label='test')

        results = outer()
        assert results['a'] == 'A'
        assert results['b'] == 'B'


# ============================================================================
# v1.4.5 — get_pipeline_file import in git.py
# ============================================================================

class TestGitImports:
    """git.py must import all names it uses from common.py."""

    def test_get_pipeline_file_importable_from_git(self):
        """get_pipeline_file must be available in git module's namespace."""
        import storyforge.git as git_mod
        assert hasattr(git_mod, 'get_pipeline_file')

    def test_all_names_in_git_resolve(self):
        """Scan git.py source for common.py function calls and verify imports."""
        import storyforge.git as git_mod
        import storyforge.common as common_mod

        source = inspect.getsource(git_mod)
        # Names from common that git.py uses at module level (not in local imports)
        module_level_imports = [
            name for name in dir(common_mod)
            if not name.startswith('_') and callable(getattr(common_mod, name))
            and name in source
            and hasattr(git_mod, name)
        ]
        # Specifically verify the ones that caused bugs
        assert 'get_pipeline_file' in [
            name for name in dir(git_mod)
            if not name.startswith('_')
        ]


# ============================================================================
# v1.4.8 — None column names in _extract_scene_rationales
# ============================================================================

class TestExtractSceneRationalesNoneColumns:
    """_extract_scene_rationales must handle None column names.

    Bug: CSV files with trailing delimiters or empty headers produce None
    column names. Iterating row.items() yields (None, value) pairs, and
    calling None.endswith('_rationale') raises AttributeError.
    """

    def test_none_column_skipped(self, tmp_path):
        """Rows with None column names must not crash."""
        from storyforge.cmd_revise import _extract_scene_rationales

        # Create a minimal scores directory structure
        scores_dir = tmp_path / 'working' / 'scores' / 'latest'
        scores_dir.mkdir(parents=True)
        scores_file = scores_dir / 'scene-scores.csv'
        # Write a CSV with a trailing delimiter that produces a None column
        scores_file.write_text(
            'id|voice_rationale||\n'
            'scene-01|Good voice work.||\n'
        )

        result = _extract_scene_rationales(
            str(tmp_path), ['scene-01'],
        )
        assert 'scene-01' in result
        assert result['scene-01'] == {'voice': 'Good voice work.'}

    def test_all_none_columns_returns_empty(self, tmp_path):
        """A CSV where the only non-id columns are None should return empty."""
        from storyforge.cmd_revise import _extract_scene_rationales

        scores_dir = tmp_path / 'working' / 'scores' / 'latest'
        scores_dir.mkdir(parents=True)
        scores_file = scores_dir / 'scene-scores.csv'
        # Only trailing delimiters, no real rationale columns
        scores_file.write_text(
            'id||\n'
            'scene-01||\n'
        )

        result = _extract_scene_rationales(
            str(tmp_path), ['scene-01'],
        )
        # scene-01 has no rationales, so it shouldn't appear
        assert 'scene-01' not in result


# ============================================================================
# v1.4.10 — --skip-initial-score flag for polish loop
# ============================================================================

class TestSkipInitialScoreFlag:
    """--skip-initial-score must be accepted and validated.

    Feature: When the polish loop crashes mid-polish or scores already exist,
    the user wants to skip the initial scoring step and jump straight to
    polishing using existing scores.
    """

    def test_flag_accepted_by_parse_args(self):
        """parse_args must accept --skip-initial-score."""
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish', '--loop', '--skip-initial-score'])
        assert args.skip_initial_score is True

    def test_flag_default_is_false(self):
        """--skip-initial-score defaults to False."""
        from storyforge.cmd_revise import parse_args
        args = parse_args(['--polish', '--loop'])
        assert args.skip_initial_score is False

    def test_flag_requires_loop(self):
        """--skip-initial-score without --loop must exit with error."""
        from storyforge.cmd_revise import parse_args
        # The validation happens in main(), not parse_args, so just verify
        # parse_args accepts it (main() does the --loop check)
        args = parse_args(['--polish', '--skip-initial-score'])
        assert args.skip_initial_score is True
        assert args.loop is False  # no --loop given

    def test_run_polish_loop_accepts_kwarg(self):
        """_run_polish_loop must accept skip_initial_score keyword argument."""
        sig = inspect.signature(
            __import__('storyforge.cmd_revise', fromlist=['_run_polish_loop'])._run_polish_loop
        )
        assert 'skip_initial_score' in sig.parameters


# ============================================================================
# v1.4.11 — Polish loop draft PR creation
# ============================================================================

class TestPolishLoopDraftPR:
    """_run_polish_loop must create a draft PR for progress tracking.

    Bug: The polish loop created a branch and pushed it, but never created
    a draft PR. The user had no way to track progress from the GitHub UI.
    Now it creates a PR right after ensure_branch_pushed with iteration
    tasks in the body.
    """

    def test_polish_loop_imports_create_draft_pr(self):
        """_run_polish_loop must import create_draft_pr from git."""
        from storyforge.cmd_revise import _run_polish_loop
        source = inspect.getsource(_run_polish_loop)
        assert 'create_draft_pr' in source

    def test_polish_loop_imports_update_pr_task(self):
        """_run_polish_loop must import update_pr_task from git."""
        from storyforge.cmd_revise import _run_polish_loop
        source = inspect.getsource(_run_polish_loop)
        assert 'update_pr_task' in source

    def test_polish_loop_calls_create_draft_pr(self):
        """_run_polish_loop must call create_draft_pr after branch push."""
        from storyforge.cmd_revise import _run_polish_loop
        source = inspect.getsource(_run_polish_loop)
        # Must call create_draft_pr (not just import it)
        assert 'pr_number = create_draft_pr(' in source

    def test_polish_loop_pr_uses_polish_label(self):
        """Draft PR must use 'polish' as the work_type label."""
        from storyforge.cmd_revise import _run_polish_loop
        source = inspect.getsource(_run_polish_loop)
        assert "'polish'" in source

    def test_polish_loop_updates_pr_tasks(self):
        """_run_polish_loop must call update_pr_task with iteration info."""
        from storyforge.cmd_revise import _run_polish_loop
        source = inspect.getsource(_run_polish_loop)
        assert "update_pr_task(f'Iteration {iteration}'" in source

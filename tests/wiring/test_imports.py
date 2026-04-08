"""Wiring tests: importability and public API surface.

Verifies that every module in the storyforge package is importable, that
shared modules expose the documented public functions, and that every
cmd_*.py module has the required parse_args/main entry points.
"""

import importlib
import os
import pkgutil

import pytest

# ---------------------------------------------------------------------------
# Discover all modules in the storyforge package
# ---------------------------------------------------------------------------

_PKG_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir,
    'scripts', 'lib', 'python', 'storyforge',
)
_PKG_DIR = os.path.normpath(_PKG_DIR)


def _all_module_names():
    """Return all module names under storyforge/ (excluding __pycache__)."""
    names = []
    for entry in sorted(os.listdir(_PKG_DIR)):
        if entry.startswith('__pycache__'):
            continue
        if entry.endswith('.py') and entry != '__init__.py':
            names.append(entry[:-3])
    return names


ALL_MODULES = _all_module_names()
CMD_MODULES = [m for m in ALL_MODULES if m.startswith('cmd_')]


# ---------------------------------------------------------------------------
# 1. Every module is importable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('module_name', ALL_MODULES)
def test_module_importable(module_name):
    """Each module under storyforge/ should import without error."""
    mod = importlib.import_module(f'storyforge.{module_name}')
    assert mod is not None


# ---------------------------------------------------------------------------
# 2. Shared modules expose documented public functions
# ---------------------------------------------------------------------------

_SHARED_FUNCTIONS = {
    'common': [
        'detect_project_root', 'log', 'read_yaml_field', 'select_model',
        'select_revision_model', 'get_coaching_level', 'get_plugin_dir',
        'extract_craft_sections', 'install_signal_handlers',
        'get_current_cycle', 'start_new_cycle', 'update_cycle_field',
        'get_pipeline_file',
    ],
    'git': [
        'create_branch', 'ensure_on_branch', 'ensure_branch_pushed',
        'create_draft_pr', 'update_pr_task', 'commit_and_push',
        'run_review_phase', 'current_branch', '_is_main_branch',
    ],
    'cli': [
        'base_parser', 'add_scene_filter_args', 'resolve_filter_args',
    ],
    'runner': [
        'run_parallel', 'run_batched', 'HealingZone',
    ],
    'api': [
        'invoke_api', 'invoke', 'invoke_to_file', 'extract_text',
        'extract_text_from_file', 'submit_batch', 'poll_batch',
        'download_batch_results', 'REVISION_TIMEOUT',
    ],
    'costs': [
        'calculate_cost', 'estimate_cost', 'check_threshold',
        'log_operation', 'print_summary',
    ],
    'scene_filter': [
        'build_scene_list', 'apply_scene_filter',
    ],
    'csv_cli': [
        'get_field', 'get_row', 'get_column', 'list_ids',
        'update_field', 'append_row',
    ],
    'history': [
        'append_cycle', 'get_scene_history', 'detect_stalls',
        'detect_regressions',
    ],
}


@pytest.mark.parametrize(
    'module_name,func_name',
    [
        (mod, fn)
        for mod, fns in _SHARED_FUNCTIONS.items()
        for fn in fns
    ],
    ids=lambda val: val if isinstance(val, str) else '',
)
def test_shared_function_exists(module_name, func_name):
    """Shared module should expose the documented function/attribute."""
    mod = importlib.import_module(f'storyforge.{module_name}')
    assert hasattr(mod, func_name), (
        f'storyforge.{module_name} is missing {func_name}'
    )


# ---------------------------------------------------------------------------
# 3. Every cmd_*.py has parse_args and main (except wrappers)
# ---------------------------------------------------------------------------

# cmd_reconcile is a thin wrapper that delegates to cmd_hone; it has main
# but intentionally omits parse_args.
_CMD_WRAPPERS = {'cmd_reconcile'}


@pytest.mark.parametrize('cmd_module', CMD_MODULES)
def test_cmd_has_main(cmd_module):
    """Every command module must expose a main() function."""
    mod = importlib.import_module(f'storyforge.{cmd_module}')
    assert hasattr(mod, 'main'), f'storyforge.{cmd_module} missing main()'
    assert callable(mod.main)


@pytest.mark.parametrize('cmd_module', [
    m for m in CMD_MODULES if m not in _CMD_WRAPPERS
])
def test_cmd_has_parse_args(cmd_module):
    """Non-wrapper command modules must expose parse_args()."""
    mod = importlib.import_module(f'storyforge.{cmd_module}')
    assert hasattr(mod, 'parse_args'), (
        f'storyforge.{cmd_module} missing parse_args()'
    )
    assert callable(mod.parse_args)


# ---------------------------------------------------------------------------
# 4. __main__.py dispatch table references valid modules
# ---------------------------------------------------------------------------

def test_main_dispatch_table_modules_importable():
    """Every module in __main__.COMMANDS should be importable."""
    from storyforge.__main__ import COMMANDS
    for cmd_name, module_path in COMMANDS.items():
        mod = importlib.import_module(module_path)
        assert hasattr(mod, 'main'), (
            f'COMMANDS[{cmd_name!r}] -> {module_path} has no main()'
        )


def test_main_dispatch_table_completeness():
    """__main__.COMMANDS should include all documented commands."""
    from storyforge.__main__ import COMMANDS
    expected = {
        'write', 'evaluate', 'revise', 'score', 'elaborate', 'extract',
        'validate', 'hone', 'reconcile', 'enrich', 'assemble', 'visualize',
        'timeline', 'cleanup', 'cover', 'scenes-setup', 'review', 'migrate',
    }
    missing = expected - set(COMMANDS.keys())
    assert not missing, f'Commands missing from dispatch table: {missing}'

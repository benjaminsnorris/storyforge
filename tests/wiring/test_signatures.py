"""Wiring tests: function signature compatibility.

Uses inspect.signature to verify that cross-module function calls use
kwargs that actually exist in the target function's signature.  Also
uses ast.parse to scan cmd_*.py source for calls to shared functions
and verify the kwargs match.
"""

import ast
import inspect
import os

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PKG_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir,
    'scripts', 'lib', 'python', 'storyforge',
)
_PKG_DIR = os.path.normpath(_PKG_DIR)


def _param_names(func):
    """Return set of parameter names for a function."""
    sig = inspect.signature(func)
    return set(sig.parameters.keys())


def _accepts_kwarg(func, kwarg_name):
    """Return True if func accepts the given keyword argument."""
    sig = inspect.signature(func)
    params = sig.parameters
    # Explicit parameter
    if kwarg_name in params:
        return True
    # **kwargs catch-all
    for p in params.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return False


# ---------------------------------------------------------------------------
# 1. csv_cli functions use key_col, not key_column
# ---------------------------------------------------------------------------

class TestCsvCliKeyword:
    """Verify csv_cli functions use key_col (not key_column) as parameter."""

    def test_get_field_uses_key_col(self):
        from storyforge.csv_cli import get_field
        assert _accepts_kwarg(get_field, 'key_col')
        assert not _accepts_kwarg(get_field, 'key_column'), \
            'get_field should use key_col, not key_column'

    def test_get_row_uses_key_col(self):
        from storyforge.csv_cli import get_row
        assert _accepts_kwarg(get_row, 'key_col')
        assert not _accepts_kwarg(get_row, 'key_column'), \
            'get_row should use key_col, not key_column'

    def test_update_field_uses_key_col(self):
        from storyforge.csv_cli import update_field
        assert _accepts_kwarg(update_field, 'key_col')
        assert not _accepts_kwarg(update_field, 'key_column'), \
            'update_field should use key_col, not key_column'


# ---------------------------------------------------------------------------
# 2. API functions accept timeout parameter
# ---------------------------------------------------------------------------

class TestApiSignatures:
    """Verify api module functions accept the documented parameters."""

    def test_invoke_accepts_timeout(self):
        from storyforge.api import invoke
        assert _accepts_kwarg(invoke, 'timeout')

    def test_invoke_to_file_accepts_timeout(self):
        from storyforge.api import invoke_to_file
        assert _accepts_kwarg(invoke_to_file, 'timeout')

    def test_invoke_api_accepts_timeout(self):
        from storyforge.api import invoke_api
        assert _accepts_kwarg(invoke_api, 'timeout')

    def test_invoke_accepts_label(self):
        from storyforge.api import invoke
        assert _accepts_kwarg(invoke, 'label')

    def test_invoke_to_file_accepts_label(self):
        from storyforge.api import invoke_to_file
        assert _accepts_kwarg(invoke_to_file, 'label')


# ---------------------------------------------------------------------------
# 3. git module signatures
# ---------------------------------------------------------------------------

class TestGitSignatures:

    def test_create_branch_params(self):
        from storyforge.git import create_branch
        names = _param_names(create_branch)
        assert 'command_name' in names
        assert 'project_dir' in names

    def test_ensure_on_branch_params(self):
        from storyforge.git import ensure_on_branch
        names = _param_names(ensure_on_branch)
        assert 'command_name' in names
        assert 'project_dir' in names

    def test_commit_and_push_params(self):
        from storyforge.git import commit_and_push
        names = _param_names(commit_and_push)
        assert 'project_dir' in names
        assert 'message' in names
        assert 'paths' in names


# ---------------------------------------------------------------------------
# 4. runner module signatures
# ---------------------------------------------------------------------------

class TestRunnerSignatures:

    def test_run_parallel_params(self):
        from storyforge.runner import run_parallel
        names = _param_names(run_parallel)
        assert 'items' in names
        assert 'worker_fn' in names
        assert 'max_workers' in names
        assert 'label' in names

    def test_run_batched_params(self):
        from storyforge.runner import run_batched
        names = _param_names(run_batched)
        assert 'items' in names
        assert 'worker_fn' in names
        assert 'merge_fn' in names
        assert 'batch_size' in names
        assert 'label' in names


# ---------------------------------------------------------------------------
# 5. costs.log_operation signature
# ---------------------------------------------------------------------------

class TestCostsSignatures:

    def test_log_operation_params(self):
        from storyforge.costs import log_operation
        names = _param_names(log_operation)
        assert 'project_dir' in names
        assert 'operation' in names
        assert 'model' in names
        assert 'input_tokens' in names
        assert 'output_tokens' in names
        assert 'cost' in names

    def test_log_operation_accepts_target(self):
        from storyforge.costs import log_operation
        assert _accepts_kwarg(log_operation, 'target')

    def test_log_operation_accepts_cache(self):
        from storyforge.costs import log_operation
        assert _accepts_kwarg(log_operation, 'cache_read')
        assert _accepts_kwarg(log_operation, 'cache_create')


# ---------------------------------------------------------------------------
# 6. common.update_cycle_field uses key_col internally (not key_column)
# ---------------------------------------------------------------------------

def test_update_cycle_field_uses_key_col():
    """update_cycle_field calls csv_cli.update_field with key_col=, not key_column=."""
    # Read the source of update_cycle_field and verify via AST
    from storyforge import common
    src = inspect.getsource(common.update_cycle_field)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                assert kw.arg != 'key_column', (
                    'update_cycle_field should pass key_col=, not key_column='
                )


# ---------------------------------------------------------------------------
# 7. AST-based scan of cmd_*.py for mismatched kwargs
# ---------------------------------------------------------------------------

def _cmd_source_files():
    """Yield (module_name, filepath) for each cmd_*.py."""
    for entry in sorted(os.listdir(_PKG_DIR)):
        if entry.startswith('cmd_') and entry.endswith('.py'):
            yield entry[:-3], os.path.join(_PKG_DIR, entry)


def _find_calls(tree, func_names):
    """Find all Call nodes that invoke any of the given function names.

    Returns list of (func_name, {kwarg_name, ...}, lineno).
    Handles both simple names (invoke_to_file) and attribute access
    (api.invoke_to_file).
    """
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Name) and node.func.id in func_names:
            name = node.func.id
        elif isinstance(node.func, ast.Attribute) and node.func.attr in func_names:
            name = node.func.attr
        if name:
            kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
            results.append((name, kwargs, getattr(node, 'lineno', 0)))
    return results


# Target functions and their valid kwargs (from actual signatures)
_TARGET_SIGNATURES = {}


def _ensure_target_signatures():
    """Lazily populate _TARGET_SIGNATURES from actual module introspection."""
    if _TARGET_SIGNATURES:
        return
    import storyforge.api as api
    import storyforge.git as git
    import storyforge.csv_cli as csv_cli

    for name in ('invoke', 'invoke_to_file', 'invoke_api'):
        _TARGET_SIGNATURES[name] = _param_names(getattr(api, name))
    for name in ('commit_and_push', 'create_branch', 'ensure_on_branch'):
        _TARGET_SIGNATURES[name] = _param_names(getattr(git, name))
    for name in ('get_field', 'update_field', 'get_row'):
        _TARGET_SIGNATURES[name] = _param_names(getattr(csv_cli, name))


_CHECKED_FUNCS = {
    'invoke_to_file', 'invoke', 'invoke_api',
    'commit_and_push', 'create_branch', 'ensure_on_branch',
    'get_field', 'update_field', 'get_row',
}


def _collect_kwarg_mismatches():
    """Scan all cmd_*.py files for calls with invalid kwargs.

    Returns list of (module, func, kwarg, lineno) tuples.
    """
    _ensure_target_signatures()
    mismatches = []
    for mod_name, filepath in _cmd_source_files():
        with open(filepath) as f:
            source = f.read()
        try:
            tree = ast.parse(source, filename=filepath)
        except SyntaxError:
            continue
        calls = _find_calls(tree, _CHECKED_FUNCS)
        for func_name, kwargs, lineno in calls:
            valid = _TARGET_SIGNATURES.get(func_name, set())
            for kw in kwargs:
                if kw not in valid:
                    mismatches.append((mod_name, func_name, kw, lineno))
    return mismatches


def test_cmd_modules_use_valid_kwargs():
    """No cmd_*.py should pass kwargs that don't exist in the target signature."""
    mismatches = _collect_kwarg_mismatches()
    if mismatches:
        lines = []
        for mod, func, kw, lineno in mismatches:
            lines.append(f'  {mod}:{lineno} calls {func}() with invalid kwarg {kw!r}')
        pytest.fail('Mismatched kwargs in command modules:\n' + '\n'.join(lines))


# ---------------------------------------------------------------------------
# 8. Scan all .py files (not just cmd_*) for key_column= calls to csv_cli
# ---------------------------------------------------------------------------

def _collect_key_column_misuse():
    """Find any call to csv_cli functions that uses key_column= instead of key_col=."""
    bad = []
    csv_funcs = {'get_field', 'update_field', 'get_row'}
    for entry in sorted(os.listdir(_PKG_DIR)):
        if not entry.endswith('.py'):
            continue
        filepath = os.path.join(_PKG_DIR, entry)
        with open(filepath) as f:
            source = f.read()
        try:
            tree = ast.parse(source, filename=filepath)
        except SyntaxError:
            continue
        calls = _find_calls(tree, csv_funcs)
        for func_name, kwargs, lineno in calls:
            if 'key_column' in kwargs:
                bad.append((entry, func_name, lineno))
    return bad


def test_no_key_column_kwarg_anywhere():
    """No module should pass key_column= to csv_cli functions (use key_col=)."""
    bad = _collect_key_column_misuse()
    if bad:
        lines = [f'  {f}:{ln} calls {fn}() with key_column=' for f, fn, ln in bad]
        pytest.fail('Found key_column= (should be key_col=):\n' + '\n'.join(lines))

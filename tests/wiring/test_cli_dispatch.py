"""Wiring tests: CLI dispatch tables.

Verifies that __main__.py and assembly.py dispatch tables cover all
documented commands without any dead entries.
"""

import ast
import importlib
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


# ---------------------------------------------------------------------------
# 1. __main__.py dispatch covers all documented commands
# ---------------------------------------------------------------------------

class TestMainDispatch:
    """Test the storyforge CLI dispatcher in __main__.py."""

    EXPECTED_COMMANDS = {
        'write', 'evaluate', 'revise', 'score', 'elaborate', 'extract',
        'validate', 'hone', 'reconcile', 'enrich', 'assemble', 'visualize',
        'timeline', 'cleanup', 'cover', 'scenes-setup', 'review', 'migrate',
        'migrate-medium',
    }

    def test_all_documented_commands_present(self):
        from storyforge.__main__ import COMMANDS
        missing = self.EXPECTED_COMMANDS - set(COMMANDS.keys())
        assert not missing, f'Missing from COMMANDS: {missing}'

    def test_no_dead_entries(self):
        """Every entry in COMMANDS should point to an importable module with main()."""
        from storyforge.__main__ import COMMANDS
        for cmd, mod_path in COMMANDS.items():
            mod = importlib.import_module(mod_path)
            assert callable(getattr(mod, 'main', None)), (
                f'COMMANDS[{cmd!r}] -> {mod_path} has no callable main()'
            )

    def test_command_modules_match_filesystem(self):
        """Every cmd_*.py file should be reachable via COMMANDS or GN_ROUTED_COMMANDS."""
        from storyforge.__main__ import COMMANDS, GN_ROUTED_COMMANDS
        reachable_modules = set(COMMANDS.values()) | set(GN_ROUTED_COMMANDS.values())

        for entry in sorted(os.listdir(_PKG_DIR)):
            if entry.startswith('cmd_') and entry.endswith('.py'):
                mod_name = f'storyforge.{entry[:-3]}'
                assert mod_name in reachable_modules, (
                    f'{entry} exists but is not in COMMANDS dispatch table'
                )


# ---------------------------------------------------------------------------
# 2. assembly.py CLI dispatch covers all documented subcommands
# ---------------------------------------------------------------------------

class TestAssemblyDispatch:
    """Test the assembly.py CLI dispatcher."""

    EXPECTED_SUBCOMMANDS = {
        'assemble', 'chapter', 'chapter-scenes', 'extract-prose',
        'word-count', 'metadata', 'toc', 'genre-css', 'count-chapters',
        'read-chapter-field',
    }

    def test_all_documented_subcommands_present(self):
        """assembly.py main() should handle all documented subcommands."""
        filepath = os.path.join(_PKG_DIR, 'assembly.py')
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)

        # Find the main() function
        main_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'main':
                main_func = node
                break

        assert main_func is not None, 'assembly.py has no main() function'

        # Extract command strings from if/elif comparisons
        found_commands = set()
        for node in ast.walk(main_func):
            if isinstance(node, ast.Compare):
                # Look for: command == 'string'
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                        found_commands.add(comp.value)

        missing = self.EXPECTED_SUBCOMMANDS - found_commands
        assert not missing, (
            f'assembly.py main() missing subcommands: {missing}'
        )

    def test_assembly_has_main(self):
        mod = importlib.import_module('storyforge.assembly')
        assert callable(getattr(mod, 'main', None))


# ---------------------------------------------------------------------------
# 3. csv_cli.py CLI dispatch covers its subcommands
# ---------------------------------------------------------------------------

class TestCsvCliDispatch:
    """Test the csv_cli.py CLI dispatcher."""

    EXPECTED_SUBCOMMANDS = {
        'get-field', 'get-row', 'get-column', 'list-ids',
        'update-field', 'append-row', 'renumber-seq',
    }

    def test_all_subcommands_present(self):
        filepath = os.path.join(_PKG_DIR, 'csv_cli.py')
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)

        main_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'main':
                main_func = node
                break

        assert main_func is not None, 'csv_cli.py has no main() function'

        found_commands = set()
        for node in ast.walk(main_func):
            if isinstance(node, ast.Compare):
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                        found_commands.add(comp.value)

        missing = self.EXPECTED_SUBCOMMANDS - found_commands
        assert not missing, (
            f'csv_cli.py main() missing subcommands: {missing}'
        )


# ---------------------------------------------------------------------------
# 4. api.py CLI dispatch covers its subcommands
# ---------------------------------------------------------------------------

class TestApiDispatch:
    """Test the api.py CLI dispatcher."""

    EXPECTED_SUBCOMMANDS = {
        'invoke', 'extract-text', 'log-usage',
        'submit-batch', 'poll-batch', 'download-results',
    }

    def test_all_subcommands_present(self):
        filepath = os.path.join(_PKG_DIR, 'api.py')
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)

        main_func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'main':
                main_func = node
                break

        assert main_func is not None, 'api.py has no main() function'

        found_commands = set()
        for node in ast.walk(main_func):
            if isinstance(node, ast.Compare):
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                        found_commands.add(comp.value)

        missing = self.EXPECTED_SUBCOMMANDS - found_commands
        assert not missing, (
            f'api.py main() missing subcommands: {missing}'
        )


# ---------------------------------------------------------------------------
# Elaboration score flags must bypass GN routing
# ---------------------------------------------------------------------------

class TestElaborationScoreBypassesGN:
    """The elaboration entry points on `storyforge score` (--level, --drift,
    --boundary, --bible-consistency, --compare, --all-levels, --all-boundaries)
    are medium-agnostic. They must always route to cmd_score regardless of
    project.medium so GN projects can run drift checks and floor scores."""

    def test_all_elaboration_flags_listed(self):
        from storyforge.__main__ import _ELABORATION_SCORE_FLAGS
        expected = {
            '--level', '--all-levels', '--compare', '--drift',
            '--boundary', '--all-boundaries', '--bible-consistency',
        }
        assert _ELABORATION_SCORE_FLAGS == expected

    def test_has_elaboration_score_flag_detects_simple(self):
        from storyforge.__main__ import _has_elaboration_score_flag
        assert _has_elaboration_score_flag(['--drift'])
        assert _has_elaboration_score_flag(['--bible-consistency'])
        assert _has_elaboration_score_flag(['--level', '0'])
        assert _has_elaboration_score_flag(['--boundary', '0->1'])

    def test_has_elaboration_score_flag_detects_equals_form(self):
        """--level=0 syntax must also be detected."""
        from storyforge.__main__ import _has_elaboration_score_flag
        assert _has_elaboration_score_flag(['--level=0'])
        assert _has_elaboration_score_flag(['--boundary=5->6'])

    def test_has_elaboration_score_flag_returns_false_for_gn_args(self):
        from storyforge.__main__ import _has_elaboration_score_flag
        assert not _has_elaboration_score_flag([])
        assert not _has_elaboration_score_flag(['--scenes', 'sc-1'])
        assert not _has_elaboration_score_flag(['--act', '1'])
        assert not _has_elaboration_score_flag(['--principles', 'panel_density'])

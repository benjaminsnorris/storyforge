"""Shared CLI helpers for Storyforge command modules.

Provides common argument parsing patterns and a base parser factory.
"""

import argparse
import os
import sys


def base_parser(prog: str, description: str) -> argparse.ArgumentParser:
    """Create a base argument parser with common flags."""
    parser = argparse.ArgumentParser(prog=f'storyforge {prog}', description=description)
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would happen without executing')
    parser.add_argument('--parallel', type=int, default=None,
                        help='Number of parallel workers')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Run in interactive mode')
    parser.add_argument('--coaching', choices=['full', 'coach', 'strict'],
                        help='Override coaching level')
    return parser


def add_scene_filter_args(parser: argparse.ArgumentParser) -> None:
    """Add scene filtering flags: --scenes, --act, --from-seq."""
    group = parser.add_argument_group('scene filtering')
    group.add_argument('--scenes', type=str, default=None,
                       help='Comma-separated scene IDs')
    group.add_argument('--act', type=str, default=None,
                       help='Filter to a specific act')
    group.add_argument('--from-seq', type=str, default=None,
                       help='Start from sequence number (N or N-M range)')


def resolve_filter_args(args) -> tuple[str, str | None, str | None]:
    """Resolve scene filter args to (mode, value, value2) tuple.

    Returns ('all', None, None) if no filter specified.
    """
    if hasattr(args, 'scenes') and args.scenes:
        return ('scenes', args.scenes, None)
    if hasattr(args, 'act') and args.act:
        return ('act', args.act, None)
    if hasattr(args, 'from_seq') and args.from_seq:
        return ('from_seq', args.from_seq, None)
    return ('all', None, None)


def add_check_method_args(parser: argparse.ArgumentParser, questions_help: str) -> None:
    """#738: the flags that force how the gate checks a scene against the
    book for the run (`gate.CHECK_FLAGS`), one at most: `--tandem` (the
    default: both checkers on a scene's first run, the questions alone on
    the re-checks after a fix), `--open` (the open checker on every run),
    `--questions` (`questions_help`). `check_method(args)` reads them."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--tandem', action='store_true',
                       help='The default: check a scene\'s first gate run with both the open '
                            'checker and the yes/no questions (the union of their findings), '
                            'and each re-check after a fix with the questions alone, the open '
                            'checker\'s findings standing where the fix left their words '
                            'alone and asked again where it did not')
    group.add_argument('--open', action='store_true',
                       help='Check every gate run with the open checker alone (two readings '
                            'against the book; no yes/no questions)')
    group.add_argument('--questions', action='store_true', help=questions_help)


def check_method(args) -> str | None:
    """The check method `add_check_method_args`' flags force, or None."""
    for method in ('tandem', 'open', 'questions'):
        if getattr(args, method, False):
            return method
    return None


def apply_coaching_override(args) -> None:
    """Set STORYFORGE_COACHING env var if --coaching was passed."""
    if hasattr(args, 'coaching') and args.coaching:
        os.environ['STORYFORGE_COACHING'] = args.coaching

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
                       help='Filter to a specific act/part')
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


def apply_coaching_override(args) -> None:
    """Set STORYFORGE_COACHING env var if --coaching was passed."""
    if hasattr(args, 'coaching') and args.coaching:
        os.environ['STORYFORGE_COACHING'] = args.coaching

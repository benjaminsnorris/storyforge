"""Storyforge CLI dispatcher.

Entry point for `python3 -m storyforge <command>` and the `./storyforge` runner.
"""

import importlib
import os
import sys

# Commands that don't yet support graphic-novel mode (Plan 1 boundary).
# When a project's medium is graphic-novel, these commands return a clear
# error instead of silently running novel-mode logic on the wrong data.
GN_UNSUPPORTED_COMMANDS = frozenset({
    'publish', 'annotations', 'repetition', 'enrich',
})

# Commands that route to a different module based on project.medium
GN_ROUTED_COMMANDS = {
    'write': 'storyforge.cmd_write_gn',
    'assemble': 'storyforge.cmd_script_package',
    'score': 'storyforge.cmd_score_gn',
    'evaluate': 'storyforge.cmd_evaluate_gn',
    'revise': 'storyforge.cmd_revise_gn',
    'extract': 'storyforge.cmd_extract_gn',
}

# `score` flags that target the medium-agnostic elaboration pipeline.
# When present, `score` must route to cmd_score (not cmd_score_gn) so GN
# projects can run drift checks, level floors, boundary diffs, and
# bible-consistency the same as novel projects.
_ELABORATION_SCORE_FLAGS = frozenset({
    '--level', '--all-levels', '--compare', '--drift',
    '--boundary', '--all-boundaries', '--bible-consistency',
    '--story-power',
})


def _has_elaboration_score_flag(argv: list[str]) -> bool:
    """True when `score` is invoked with any elaboration entry-point flag."""
    return any(a.split('=', 1)[0] in _ELABORATION_SCORE_FLAGS for a in argv)

COMMANDS = {
    'annotations': 'storyforge.cmd_annotations',
    'validate': 'storyforge.cmd_validate',
    'hone': 'storyforge.cmd_hone',
    'reconcile': 'storyforge.cmd_reconcile',
    'repetition': 'storyforge.cmd_repetition',
    'review': 'storyforge.cmd_review',
    'write': 'storyforge.cmd_write',
    'evaluate': 'storyforge.cmd_evaluate',
    'revise': 'storyforge.cmd_revise',
    'score': 'storyforge.cmd_score',
    'enrich': 'storyforge.cmd_enrich',
    'extract': 'storyforge.cmd_extract',
    'elaborate': 'storyforge.cmd_elaborate',
    'visualize': 'storyforge.cmd_visualize',
    'timeline': 'storyforge.cmd_timeline',
    'assemble': 'storyforge.cmd_assemble',
    'cleanup': 'storyforge.cmd_cleanup',
    'cover': 'storyforge.cmd_cover',
    'migrate': 'storyforge.cmd_migrate',
    'migrate-medium': 'storyforge.cmd_migrate_medium',
    'scenes-setup': 'storyforge.cmd_scenes_setup',
    'scenes-export': 'storyforge.cmd_scenes_export',
    'scenes-import': 'storyforge.cmd_scenes_import',
    'sync': 'storyforge.cmd_sync',
    'publish': 'storyforge.cmd_publish',
    'propose-summaries': 'storyforge.cmd_propose_summaries',
}

# Aliases
COMMANDS['scenes'] = COMMANDS['scenes-setup']


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print('Usage: storyforge <command> [options]')
        print()
        print('Commands:')
        for cmd in sorted(COMMANDS):
            if cmd != 'scenes':  # skip alias
                print(f'  {cmd}')
        print()
        print('Run `storyforge <command> -h` for command-specific help.')
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f'Unknown command: {cmd}', file=sys.stderr)
        print(f'Run `storyforge --help` for available commands.', file=sys.stderr)
        sys.exit(1)

    # Guard graphic-novel projects against commands that haven't gained a
    # GN-aware implementation yet. Importing storyforge.common lazily so
    # `storyforge --help` keeps working in directories without a project.
    if cmd in GN_UNSUPPORTED_COMMANDS:
        project_medium = None
        try:
            from storyforge.common import detect_project_root, get_medium
            project_dir = detect_project_root()
            project_medium = get_medium(project_dir)
        except (FileNotFoundError, OSError):
            # Not inside a project — let the command itself fail with its own error
            pass
        if project_medium == 'graphic-novel':
            print(
                f"Error: '{cmd}' is not yet supported for graphic-novel projects.",
                file=sys.stderr,
            )
            print(
                "Plan 1 supports: elaborate (spine/architecture/map/voice/briefs), "
                "hone, validate, cleanup. Drafting and production land in Plan 2.",
                file=sys.stderr,
            )
            sys.exit(2)

    # Route certain commands to GN-specific modules based on project.medium.
    # Exception: `score` elaboration entry points are medium-agnostic and must
    # always route to cmd_score regardless of medium (levels are the same
    # logline → drafts hierarchy whether the manuscript is prose or panels).
    if cmd in GN_ROUTED_COMMANDS:
        is_elaboration_score = (
            cmd == 'score' and _has_elaboration_score_flag(sys.argv[2:])
        )
        project_medium = None
        try:
            from storyforge.common import detect_project_root, get_medium
            project_dir = detect_project_root()
            project_medium = get_medium(project_dir)
        except (FileNotFoundError, OSError):
            pass
        if project_medium == 'graphic-novel' and not is_elaboration_score:
            sys.argv = [f'storyforge {cmd}'] + sys.argv[2:]
            module = importlib.import_module(GN_ROUTED_COMMANDS[cmd])
            module.main(sys.argv[1:])
            return

    # Remove 'storyforge' and command from argv so the module sees its own args
    sys.argv = [f'storyforge {cmd}'] + sys.argv[2:]

    module = importlib.import_module(COMMANDS[cmd])
    module.main(sys.argv[1:])


if __name__ == '__main__':
    main()

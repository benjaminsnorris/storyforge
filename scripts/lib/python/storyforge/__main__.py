"""Storyforge CLI dispatcher.

Entry point for `python3 -m storyforge <command>` and the `./storyforge` runner.
"""

import importlib
import sys

COMMANDS = {
    'validate': 'storyforge.cmd_validate',
    'hone': 'storyforge.cmd_hone',
    'reconcile': 'storyforge.cmd_reconcile',
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
    'scenes-setup': 'storyforge.cmd_scenes_setup',
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

    # Remove 'storyforge' and command from argv so the module sees its own args
    sys.argv = [f'storyforge {cmd}'] + sys.argv[2:]

    module = importlib.import_module(COMMANDS[cmd])
    module.main(sys.argv[1:])


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""E1 corpus tools.

    python3 evals/e1/cli.py validate          # format check, no repos needed
    python3 evals/e1/cli.py verify [--repo R] # every quote is in its file at its commit
    python3 evals/e1/cli.py holdout           # top up evals/fixtures/e1/holdout.json
    python3 evals/e1/cli.py stats

Repos are read from STORYFORGE_CORPUS_DIR (default ~/Developer). Exit 1 on any problem.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import e1  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='evals/e1/cli.py')
    parser.add_argument('command', choices=('validate', 'verify', 'holdout', 'stats'))
    parser.add_argument('--repo', help='verify only this repo')
    parser.add_argument('--cases-dir', default=e1.CASES_DIR, help=argparse.SUPPRESS)
    parser.add_argument('--holdout-file', default=e1.HOLDOUT_FILE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    cases = e1.load_cases(args.cases_dir)
    problems = e1.validate_corpus(cases)

    if args.command == 'verify':
        targets = [c for c in cases if not args.repo or c.get('repo') == args.repo]
        problems += e1.verify_quotes(targets)
    elif args.command == 'holdout':
        if problems:
            print('\n'.join(problems), file=sys.stderr)
            print('ERROR: fix the format problems before assigning a holdout', file=sys.stderr)
            return 1
        ids = e1.assign_holdout(cases, e1.load_holdout(args.holdout_file))
        os.makedirs(os.path.dirname(args.holdout_file), exist_ok=True)
        with open(args.holdout_file, 'w') as f:
            json.dump({'fraction': e1.HOLDOUT_FRACTION, 'ids': ids}, f, indent=2)
            f.write('\n')
        print(f'{len(ids)} of {len(cases)} cases held out')
    elif args.command == 'stats':
        print(json.dumps(e1.stats(cases, e1.load_holdout(args.holdout_file)), indent=2))

    if problems:
        print('\n'.join(problems), file=sys.stderr)
        print(f'{len(problems)} problem(s)', file=sys.stderr)
        return 1
    if args.command in ('validate', 'verify'):
        print(f'{len(cases)} case(s) OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())

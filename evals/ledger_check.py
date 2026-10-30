"""Run the ledger migration on a copy of each book repo and report.

    python3 evals/ledger_check.py [repo ...]

For each book under STORYFORGE_CORPUS_DIR (default ~/Developer), copies its
`reference/` to a temporary directory, migrates knowledge.csv and
physical-states.csv into ledger rows (`storyforge.ledger.migrate_registries`),
writes and re-reads commitments.csv there, and reports: rows by type, every
quirk, every error, the round-trip lines no quirk explains, and the ledger's
validation problems. The book repos are only read.

Exit 0 when every book migrates with no error and its round trip holds, 1
otherwise, 2 when a book repo is missing.
"""

import os
import shutil
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'scripts', 'lib', 'python'))

from storyforge import ledger  # noqa: E402

BOOKS = ('shared-dark', 'thornwall', 'lantern-folk', 'governor',
         'meridian-line', 'understory', 'slipform')


def check(repo_dir: str) -> bool:
    """Report one book; True when it migrates cleanly."""
    with tempfile.TemporaryDirectory() as tmp:
        ref = os.path.join(tmp, 'reference')
        shutil.copytree(os.path.join(repo_dir, 'reference'), ref)
        result = ledger.migrate_registries(ref)
        path = os.path.join(ref, ledger.LEDGER_FILE)
        ledger.write_ledger(path, result.rows)
        reread = ledger.read_ledger(path)
        round_trip = ledger.round_trip_differences(
            ref, ledger.Migration(reread, result.quirks, result.errors))
        problems = ledger.validate_ledger(
            reread,
            scene_ids=set(ledger._ids(os.path.join(ref, 'scenes.csv'))),
            character_ids=set(ledger._ids(os.path.join(ref, 'characters.csv'))))

    types = Counter(r['type'] for r in result.rows)
    print(f'## {os.path.basename(repo_dir)}: '
          + ', '.join(f'{n} {t}' for t, n in sorted(types.items())))
    kinds = Counter(q.kind for q in result.quirks)
    if kinds:
        print('quirks: ' + ', '.join(f'{k} {n}' for k, n in sorted(kinds.items())))
    for quirk in result.quirks:
        print(f'  quirk   {quirk}')
    for error in result.errors:
        print(f'  ERROR   {error}')
    for diff in round_trip:
        print(f'  ROUND   {diff}')
    for problem in problems:
        print(f'  invalid {problem}')
    if not (result.errors or round_trip):
        print('  round trip holds')
    print()
    return not (result.errors or round_trip)


def main(argv):
    corpus = os.environ.get('STORYFORGE_CORPUS_DIR', os.path.expanduser('~/Developer'))
    books = argv or BOOKS
    missing = [b for b in books if not os.path.isdir(os.path.join(corpus, b, 'reference'))]
    if missing:
        print(f'Missing book repos under {corpus}: {", ".join(missing)}')
        return 2
    ok = [check(os.path.join(corpus, b)) for b in books]
    print(f'{sum(ok)} of {len(ok)} books migrate with no error and round-trip')
    return 0 if all(ok) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

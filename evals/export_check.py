"""Run `storyforge export` on a copy of each book repo and check the round trip.

    python3 evals/export_check.py [repo ...]

For each book under STORYFORGE_CORPUS_DIR (default ~/Developer), copies the
repo (without .git and manuscript/, which export doesn't read) to a temporary
directory, runs `storyforge export` there, reads the bundle back and checks:
every table regenerates its file byte-for-byte (`export.tables_from_bundle`),
and every reference/*.csv is either a table or named in the bundle's
warnings. Reports the tables by kind, the score cycle and every warning. The
book repos are only read.

Exit 0 when every book exports and round-trips, 1 otherwise, 2 when a book
repo is missing.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'lib', 'python'))

from storyforge import export  # noqa: E402

BOOKS = ('shared-dark', 'thornwall', 'lantern-folk', 'governor',
         'meridian-line', 'understory', 'slipform')


def check(repo_dir: str) -> bool:
    """Report one book; True when it exports and every table round-trips."""
    name = os.path.basename(repo_dir)
    with tempfile.TemporaryDirectory() as tmp:
        book = os.path.join(tmp, name)
        shutil.copytree(repo_dir, book, symlinks=True,
                        ignore=shutil.ignore_patterns('.git', 'manuscript'))
        out = os.path.join(tmp, 'bundle.json')
        run = subprocess.run(
            [sys.executable, os.path.join(ROOT, 'storyforge'), 'export',
             '--output', out],
            cwd=book, capture_output=True, text=True)
        if run.returncode != 0:
            print(f'## {name}: export exited {run.returncode}')
            print('  ' + (run.stdout + run.stderr).strip().replace('\n', '\n  '))
            print()
            return False
        with open(out, encoding='utf-8') as f:
            bundle = json.load(f)
        size = os.path.getsize(out)

        mismatched = []
        for rel, text in export.tables_from_bundle(bundle).items():
            with open(os.path.join(book, rel), 'rb') as f:
                if text.encode('utf-8') != f.read():
                    mismatched.append(rel)
        warned = ' '.join(bundle['warnings'])
        unaccounted = [
            rel for rel in (os.path.relpath(p, book) for p in
                            sorted(glob.glob(os.path.join(glob.escape(book), 'reference', '*.csv'))))
            if rel not in bundle['tables'] and rel not in warned]

    kinds = Counter(t['kind'] for t in bundle['tables'].values())
    crlf = sorted(p for p, t in bundle['tables'].items() if t['line_ending'] == '\r\n')
    print(f'## {name}: schema {bundle["schema_version"]}, {len(bundle["tables"])} tables ('
          + ', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))
          + f'), score cycle {bundle["score_cycle"] or "none"}, {size // 1024} KB')
    if bundle['dashboard_data'] is None:
        print('  dashboard_data is null')
    for rel in crlf:
        print(f'  crlf    {rel}')
    for warning in bundle['warnings']:
        print(f'  warning {warning}')
    for rel in mismatched:
        print(f'  ROUND   {rel} does not regenerate byte-identical')
    for rel in unaccounted:
        print(f'  MISSING {rel} is neither a table nor named in warnings')
    ok = not (mismatched or unaccounted)
    if ok:
        print('  round trip holds')
    print()
    return ok


def main(argv):
    corpus = os.environ.get('STORYFORGE_CORPUS_DIR', os.path.expanduser('~/Developer'))
    books = argv or BOOKS
    missing = [b for b in books if not os.path.isdir(os.path.join(corpus, b, 'reference'))]
    if missing:
        print(f'Missing book repos under {corpus}: {", ".join(missing)}')
        return 2
    ok = [check(os.path.join(corpus, b)) for b in books]
    print(f'{sum(ok)} of {len(ok)} books export and round-trip')
    return 0 if all(ok) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

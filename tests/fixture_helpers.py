"""Copy a fixture project into a test's tmp dir.

Only the files git would commit are copied: tracked files plus untracked
files git doesn't ignore (so a fixture file being added shows up before it
is staged). Gitignored leftovers in a checkout never reach the copy. A
developer checkout had 6.7 MB of old `working/logs/*.txt` output (all of
`working/` is gitignored) sitting in `tests/fixtures/test-project`, and
copying it for every `project_dir` test cost ~18 GB of temp per full run
(#296). Every checkout now tests the same tree CI does.

Outside a git work tree (e.g. an unpacked release), the whole directory is
copied.
"""

import functools
import os
import shutil
import subprocess


@functools.lru_cache(maxsize=None)
def fixture_files(src):
    """Paths, relative to `src`, of the files under `src` that git would
    commit, sorted; None when `src` isn't inside a git work tree."""
    try:
        proc = subprocess.run(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', '.'],
            cwd=src, capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return tuple(sorted({os.fsdecode(p) for p in proc.stdout.split(b'\0') if p}))


def copy_fixture(src, dest):
    """Copy fixture project `src` to `dest` (which must not exist), leaving
    out gitignored files. Returns `dest` as a str."""
    src, dest = str(src), str(dest)
    files = fixture_files(src)
    if files is None:
        shutil.copytree(src, dest)
        return dest
    os.makedirs(dest)
    for rel in files:
        source = os.path.join(src, rel)
        # `--cached` still lists a tracked file deleted from disk; the copy
        # matches the disk, as copytree did.
        if not os.path.isfile(source):
            continue
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
    return dest

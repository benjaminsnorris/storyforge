"""Copy a fixture project into a test's tmp dir: only the files git would commit.

`copy_fixture` copies the files `committable_files` lists: tracked files plus
untracked files git doesn't ignore (so a fixture file being added shows up
before it is staged). Gitignored leftovers in a checkout never reach the
copy. A developer checkout had 6.7 MB of old `working/logs/*.txt` output
(`working/` and `*.log` are gitignored) sitting in
`tests/fixtures/test-project`, and copying it for every `project_dir` test
cost ~18 GB of temp per full run (#296). A fixture file under `working/`
must be force-added (`git add -f`) or the copy leaves it out.

Outside a git work tree (e.g. an unpacked release), or where git isn't
installed, the whole directory is copied and a warning says so. Any other
git failure raises.

About 18 tests copy only a fixture's `reference/` with `shutil.copytree`;
`reference/` holds no gitignored files, so they're left as they are.
"""

import os
import shutil
import subprocess
import warnings
from contextlib import contextmanager
from pathlib import Path

TESTS_DIR = Path(__file__).parent
FIXTURE_DIR = TESTS_DIR / 'fixtures' / 'test-project'
FIXTURE_DIR_GN = TESTS_DIR / 'fixtures' / 'test-project-gn'

# The working/ subdirectories command modules expect.
WORKING_DIRS = (
    'working/logs', 'working/scores', 'working/costs',
    'working/evaluations', 'working/reviews', 'working/coaching',
)

# A project copy above this is carrying something it shouldn't.
MAX_COPY_BYTES = 500_000

# Variables that point git at a different repository or index than the one
# around the fixture (set inside git hooks and `rebase --exec`). With
# GIT_DIR set, the root .gitignore isn't read; with another GIT_INDEX_FILE,
# force-added files such as working/pipeline.csv drop out.
_GIT_REPO_ENV = (
    'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
    'GIT_COMMON_DIR', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
)

_committable = {}
_warned = set()


def _warn_once(message):
    if message not in _warned:
        _warned.add(message)
        warnings.warn(message, stacklevel=3)


def _git(args, cwd):
    env = {k: v for k, v in os.environ.items() if k not in _GIT_REPO_ENV}
    return subprocess.run(['git', *args], cwd=cwd, env=env, capture_output=True)


def committable_files(src):
    """Paths, relative to `src`, of the files under `src` that git would
    commit, sorted; None when `src` isn't in a git work tree or git isn't
    installed (with a warning). Raises when git fails any other way, or
    when it lists nothing or no storyforge.yaml (an enclosing .gitignore
    covering the fixture)."""
    key = os.path.realpath(str(src))
    if key in _committable:
        return _committable[key]
    try:
        proc = _git(['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', '.'],
                    cwd=key)
    except FileNotFoundError:
        _warn_once(f'git is not installed: copying all of {key}, gitignored files included')
        return None
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors='replace').strip()
        if 'not a git repository' in stderr:
            _warn_once(f'{key} is not in a git work tree: copying all of it, '
                       f'gitignored files included')
            return None
        raise RuntimeError(f'git ls-files failed in {key}: {stderr}')
    files = tuple(sorted({os.fsdecode(p) for p in proc.stdout.split(b'\0') if p}))
    if 'storyforge.yaml' not in files:
        raise RuntimeError(
            f'git lists {len(files)} committable files in {key} and no storyforge.yaml: '
            f'is the fixture gitignored?')
    _committable[key] = files
    return files


def copy_fixture(src, dest):
    """Copy only the files git would commit from fixture project `src` to
    `dest` (which must not exist); everything when `src` is outside git.
    Returns `dest` as a str."""
    src, dest = str(src), str(dest)
    files = committable_files(src)
    if files is None:
        shutil.copytree(src, dest)
        return dest
    os.makedirs(dest)
    skipped = []
    for rel in files:
        source = os.path.join(src, rel)
        # `--cached` still lists a tracked file deleted from disk; the copy
        # matches the disk, as copytree did.
        if not os.path.lexists(source):
            continue
        if not os.path.isfile(source):  # broken symlink, submodule
            skipped.append(rel)
            continue
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
    if skipped:
        warnings.warn(f'{src}: not regular files, not copied: {", ".join(skipped)}',
                      stacklevel=2)
    return dest


def make_project(src, dest, working_dirs=False):
    """A writable project at `dest`: `copy_fixture(src, dest)`, plus the
    `WORKING_DIRS` command modules expect when `working_dirs`. Returns `dest`
    as a str."""
    dest = copy_fixture(src, dest)
    if working_dirs:
        for subdir in WORKING_DIRS:
            os.makedirs(os.path.join(dest, subdir), exist_ok=True)
    return dest


# ---------------------------------------------------------------------------
# Guard for the project fixtures (#296)
# ---------------------------------------------------------------------------

SENTINEL = os.path.join('working', 'logs', '_fixture_sentinel.log')


@contextmanager
def ignored_sentinel(src):
    """Write a gitignored file into fixture `src` for the duration, standing
    in for a checkout's leftovers; yields its path relative to `src`. A
    project fixture requested inside the block must leave it out."""
    src = str(src)
    path = os.path.join(src, SENTINEL)
    created = []
    parent = os.path.dirname(path)
    while not os.path.isdir(parent):
        created.append(parent)
        parent = os.path.dirname(parent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, 'w') as f:
            f.write('a leftover a project copy must leave out\n')
        if _git(['check-ignore', '-q', SENTINEL], cwd=src).returncode != 0:
            raise AssertionError(f'{SENTINEL} is not gitignored in {src}')
        yield SENTINEL
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        for d in created:  # deepest first
            try:
                os.rmdir(d)
            except OSError:
                pass


def assert_committed_copy(project, sentinel):
    """`project` left out `sentinel` and its files (outside any .git) come
    to under MAX_COPY_BYTES."""
    assert not os.path.lexists(os.path.join(project, sentinel)), \
        f'{project} copied gitignored {sentinel}: build it with fixture_helpers.make_project'
    size = 0
    for d, dirs, files in os.walk(project):
        dirs[:] = [x for x in dirs if x != '.git']
        size += sum(os.path.getsize(os.path.join(d, f)) for f in files)
    assert size < MAX_COPY_BYTES, f'{project} is {size} bytes'

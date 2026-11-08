"""`storyforge sync --install-hook` on real repositories (#612).

The hook used to be written to `<project>/.git/hooks` and to assume the
project sat at the repo root. These tests cover a project at the root, one
in `projects/<book>/`, two projects in one repo, a worktree, and
`core.hooksPath`, committing through the installed hook each time.
"""

import os
import subprocess

import pytest

from fixture_helpers import make_project
from storyforge.cmd_sync import _default_runner_path, detect_state, install_hook
from storyforge.csv_cli import update_field

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'test-project')


def _git(cwd, *args, check=True, env=None):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True,
                          check=check, env=env)


def _init_repo(root):
    os.makedirs(root, exist_ok=True)
    _git(root, 'init', '-q')
    _git(root, 'config', 'user.email', 'test@example.com')
    _git(root, 'config', 'user.name', 'Test')
    _git(root, 'config', 'commit.gpgsign', 'false')


def _commit_all(root, msg='initial'):
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '-m', msg)


@pytest.fixture
def hook_env(tmp_path):
    """An environment whose `storyforge` on PATH is this checkout's runner,
    so the hook never picks up another installed plugin."""
    runner = _default_runner_path()
    assert runner, 'the plugin runner must exist for these tests'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    wrapper = bin_dir / 'storyforge'
    wrapper.write_text(f'#!/bin/sh\nexec "{runner}" "$@"\n')
    wrapper.chmod(0o755)
    env = dict(os.environ)
    env['PATH'] = f'{bin_dir}{os.pathsep}{env.get("PATH", "")}'
    env.pop('STORYFORGE_SYNC_SKIP', None)
    return env


def _edit_and_commit(repo_root, project_dir, env, title='A New Title'):
    scenes = os.path.join(project_dir, 'reference', 'scenes.csv')
    update_field(scenes, 'act1-sc01', 'title', title)
    _git(repo_root, 'add', os.path.relpath(scenes, repo_root))
    return _git(repo_root, 'commit', '-m', 'edit title', check=False, env=env)


def _committed(repo_root, rel):
    r = _git(repo_root, 'show', f'HEAD:{rel}', check=False)
    return r.stdout if r.returncode == 0 else None


# --- where the hook goes ---------------------------------------------------

def test_hook_installs_for_project_at_repo_root(tmp_path):
    root = make_project(FIXTURE_DIR, tmp_path / 'book')
    _init_repo(root)
    path = install_hook(root)
    assert os.path.realpath(path) == os.path.realpath(
        os.path.join(root, '.git', 'hooks', 'pre-commit'))


def test_hook_installs_for_project_in_subfolder(tmp_path):
    """Regression (#612): `projects/<book>/.git/hooks` doesn't exist; the
    hook goes in the repository's hooks folder."""
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    project = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'book')
    path = install_hook(project)
    assert os.path.realpath(path) == os.path.realpath(
        os.path.join(repo, '.git', 'hooks', 'pre-commit'))


def test_hook_installs_in_worktree(tmp_path):
    """Regression (#612): in a worktree `.git` is a file, not a folder."""
    root = make_project(FIXTURE_DIR, tmp_path / 'book')
    _init_repo(root)
    _commit_all(root)
    wt = str(tmp_path / 'wt')
    _git(root, 'worktree', 'add', '-q', wt)
    assert os.path.isfile(os.path.join(wt, '.git'))
    path = install_hook(wt)
    hooks = _git(wt, 'rev-parse', '--git-path', 'hooks').stdout.strip()
    expected = hooks if os.path.isabs(hooks) else os.path.join(wt, hooks)
    assert os.path.realpath(path) == os.path.realpath(os.path.join(expected, 'pre-commit'))
    assert os.path.isfile(path)


def test_hook_installs_into_core_hooks_path(tmp_path):
    """Regression (#612): with `core.hooksPath` set, git ignores .git/hooks."""
    root = make_project(FIXTURE_DIR, tmp_path / 'book')
    _init_repo(root)
    custom = tmp_path / 'my-hooks'
    _git(root, 'config', 'core.hooksPath', str(custom))
    path = install_hook(root)
    assert os.path.realpath(path) == os.path.realpath(str(custom / 'pre-commit'))
    assert not os.path.exists(os.path.join(root, '.git', 'hooks', 'pre-commit'))


def test_install_hook_outside_git_exits(tmp_path):
    root = make_project(FIXTURE_DIR, tmp_path / 'book')
    with pytest.raises(SystemExit) as e:
        install_hook(root)
    assert e.value.code != 0


# --- what the hook does on commit ------------------------------------------

def test_hook_syncs_project_at_repo_root(tmp_path, hook_env):
    root = make_project(FIXTURE_DIR, tmp_path / 'book')
    _init_repo(root)
    _commit_all(root)
    install_hook(root)
    r = _edit_and_commit(root, root, hook_env)
    assert r.returncode == 0, r.stderr
    review = _committed(root, 'reference/scenes-review.md')
    assert review and 'A New Title' in review


def test_hook_syncs_project_in_subfolder(tmp_path, hook_env):
    """Regression (#612): the hook's path filter got repo-root paths and
    never matched, so a subfolder project's commit skipped sync."""
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    project = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'book')
    _commit_all(repo)
    install_hook(project)
    r = _edit_and_commit(repo, project, hook_env)
    assert r.returncode == 0, r.stderr
    review = _committed(repo, 'projects/book/reference/scenes-review.md')
    assert review and 'A New Title' in review
    assert _committed(repo, 'reference/scenes-review.md') is None


def test_hook_syncs_each_touched_project_only(tmp_path, hook_env):
    """One hook serves every project in the repo; it syncs those the
    commit touches."""
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    a = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'a b')
    make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'other')
    _commit_all(repo)
    install_hook(a)
    r = _edit_and_commit(repo, a, hook_env, title='Title In A')
    assert r.returncode == 0, r.stderr
    review = _committed(repo, 'projects/a b/reference/scenes-review.md')
    assert review and 'Title In A' in review
    assert _committed(repo, 'projects/other/reference/scenes-review.md') is None


def _stub_runner(tmp_path, body):
    """An environment whose `storyforge` is a stub shell script."""
    bin_dir = tmp_path / 'stub-bin'
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / 'storyforge'
    stub.write_text('#!/bin/sh\n' + body)
    stub.chmod(0o755)
    env = dict(os.environ)
    env['PATH'] = f'{bin_dir}{os.pathsep}{env.get("PATH", "")}'
    env.pop('STORYFORGE_SYNC_SKIP', None)
    return env


def test_hook_ignores_reference_csv_outside_a_project(tmp_path):
    """A `reference/scenes.csv` in a folder without storyforge.yaml isn't
    a project: the commit goes through without running sync, and the hook
    says it skipped the folder."""
    repo = str(tmp_path / 'repo')
    _init_repo(repo)
    project = make_project(FIXTURE_DIR, tmp_path / 'repo' / 'book')
    os.makedirs(os.path.join(repo, 'docs', 'reference'))
    with open(os.path.join(repo, 'docs', 'reference', 'scenes.csv'), 'w') as f:
        f.write('id|title\nx|y\n')
    install_hook(project)
    marker = tmp_path / 'sync-ran'
    env = _stub_runner(tmp_path, f'touch "{marker}"\n')
    _git(repo, 'add', 'docs')
    r = _git(repo, 'commit', '-m', 'docs', check=False, env=env)
    assert r.returncode == 0, r.stderr
    assert not marker.exists(), 'sync must not run for a folder that is not a project'
    assert 'skipped docs/ (no storyforge.yaml there)' in r.stderr


def test_hook_root_project_commit_without_tracked_paths_needs_no_runner(tmp_path):
    """Review (CR-2): an empty staged-list line read as the root project, so
    every commit in a root project needed the runner."""
    root = make_project(FIXTURE_DIR, tmp_path / 'book')
    _init_repo(root)
    _commit_all(root)
    hook = install_hook(root)
    # no runner anywhere: a stale baked path, nothing on PATH
    with open(hook, encoding='utf-8') as f:
        content = f.read().replace(_default_runner_path(), '/nonexistent/storyforge')
    with open(hook, 'w', encoding='utf-8') as f:
        f.write(content)
    env = dict(os.environ, PATH='/usr/bin:/bin')
    env.pop('STORYFORGE_HOME', None)
    with open(os.path.join(root, 'README.md'), 'w') as f:
        f.write('hi\n')
    _git(root, 'add', 'README.md')
    r = _git(root, 'commit', '-m', 'readme', check=False, env=env)
    assert r.returncode == 0, r.stderr


def test_hook_syncs_two_projects_in_one_commit(tmp_path, hook_env):
    """Review (T-3): the loop syncs and stages every touched project."""
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    a = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'a')
    b = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'b')
    _commit_all(repo)
    install_hook(a)
    for proj, title in ((a, 'Title In A'), (b, 'Title In B')):
        scenes = os.path.join(proj, 'reference', 'scenes.csv')
        update_field(scenes, 'act1-sc01', 'title', title)
        _git(repo, 'add', os.path.relpath(scenes, repo))
    r = _git(repo, 'commit', '-m', 'both', check=False, env=hook_env)
    assert r.returncode == 0, r.stderr
    assert 'Title In A' in _committed(repo, 'projects/a/reference/scenes-review.md')
    assert 'Title In B' in _committed(repo, 'projects/b/reference/scenes-review.md')


def test_hook_refuses_commit_when_sync_fails_in_second_project(tmp_path):
    """Review (T-4): a failing sync in any touched project refuses the
    commit and names the project."""
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    a = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'a')
    b = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'b')
    _commit_all(repo)
    install_hook(a)
    env = _stub_runner(tmp_path, 'case "$(pwd)" in */projects/b) exit 3;; esac\nexit 0\n')
    for proj in (a, b):
        scenes = os.path.join(proj, 'reference', 'scenes.csv')
        update_field(scenes, 'act1-sc01', 'title', 'Changed')
        _git(repo, 'add', os.path.relpath(scenes, repo))
    head = _git(repo, 'rev-parse', 'HEAD').stdout
    r = _git(repo, 'commit', '-m', 'x', check=False, env=env)
    assert r.returncode != 0
    assert 'project projects/b/' in r.stderr
    assert _git(repo, 'rev-parse', 'HEAD').stdout == head


def test_hook_handles_non_ascii_project_folder(tmp_path, hook_env):
    """Review (T-6): git quotes non-ASCII paths unless -z; the hook must
    still find the project."""
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    project = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'café')
    _commit_all(repo)
    install_hook(project)
    r = _edit_and_commit(repo, project, hook_env)
    assert r.returncode == 0, r.stderr
    assert 'A New Title' in _committed(repo, 'projects/café/reference/scenes-review.md')


def test_hook_fails_closed_when_staged_files_cannot_be_listed(tmp_path, hook_env):
    """Review (SF-2): a failing `git diff --cached` refuses the commit
    rather than reading as nothing staged."""
    root = make_project(FIXTURE_DIR, tmp_path / 'book')
    _init_repo(root)
    _commit_all(root)
    hook = install_hook(root)
    real_git = subprocess.run(['which', 'git'], capture_output=True, text=True).stdout.strip()
    wrap = tmp_path / 'gitwrap'
    wrap.mkdir()
    (wrap / 'git').write_text(
        '#!/bin/sh\nif [ "$1" = diff ] && [ "$2" = --cached ]; then '
        'echo "fatal: index file corrupt" >&2; exit 128; fi\n'
        f'exec "{real_git}" "$@"\n')
    (wrap / 'git').chmod(0o755)
    env = dict(hook_env)
    env['PATH'] = f'{wrap}{os.pathsep}{env["PATH"]}'
    r = subprocess.run([hook], cwd=root, capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert 'could not list the staged files' in r.stderr


def test_hook_refuses_unstaged_changes_in_subfolder_project(tmp_path, hook_env):
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    project = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'book')
    _commit_all(repo)
    install_hook(project)
    scenes = os.path.join(project, 'reference', 'scenes.csv')
    update_field(scenes, 'act1-sc01', 'title', 'Staged')
    _git(repo, 'add', 'projects/book/reference/scenes.csv')
    update_field(scenes, 'act1-sc01', 'title', 'Unstaged on top')
    r = _git(repo, 'commit', '-m', 'x', check=False, env=hook_env)
    assert r.returncode != 0
    assert 'unstaged scene changes in projects/book/' in r.stderr
    assert 'reference/scenes.csv' in r.stderr


def test_hook_fires_from_worktree(tmp_path, hook_env):
    root = make_project(FIXTURE_DIR, tmp_path / 'book')
    _init_repo(root)
    _commit_all(root)
    wt = str(tmp_path / 'wt')
    _git(root, 'worktree', 'add', '-q', '-b', 'side', wt)
    install_hook(wt)
    r = _edit_and_commit(wt, wt, hook_env)
    assert r.returncode == 0, r.stderr
    review = _committed(wt, 'reference/scenes-review.md')
    assert review and 'A New Title' in review


def test_hook_from_worktree_stages_subfolder_project_in_place(tmp_path, hook_env):
    """Review (SF-1): in a linked worktree git runs hooks with GIT_DIR set,
    so after `cd projects/book` git took that folder as the work tree's top
    and committed reference/ files at the repo root."""
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'book')
    _commit_all(repo)
    wt = str(tmp_path / 'wt')
    _git(repo, 'worktree', 'add', '-q', '-b', 'side', wt)
    project = os.path.join(wt, 'projects', 'book')
    install_hook(project)
    r = _edit_and_commit(wt, project, hook_env)
    assert r.returncode == 0, r.stderr
    files = _git(wt, 'show', '--name-only', '--format=', 'HEAD').stdout.split('\n')
    assert 'projects/book/reference/scenes-review.md' in files
    assert not any(f.startswith('reference/') for f in files), files
    assert 'A New Title' in _committed(wt, 'projects/book/reference/scenes-review.md')
    assert _git(wt, 'status', '--porcelain').stdout.strip() == ''


def test_hook_commit_all_in_subfolder_project(tmp_path, hook_env):
    """`git commit -a` (a temporary index) works for a subfolder project."""
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    project = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'book')
    _commit_all(repo)
    install_hook(project)
    update_field(os.path.join(project, 'reference', 'scenes.csv'), 'act1-sc01', 'title', 'All')
    _git(repo, 'add', '-N', '.')
    r = _git(repo, 'commit', '-a', '-m', 'all', check=False, env=hook_env)
    assert r.returncode == 0, r.stderr
    assert 'All' in _committed(repo, 'projects/book/reference/scenes-review.md')


# --- sync's own reads in a subfolder project -------------------------------

def test_detect_state_reads_head_relative_to_subfolder_project(tmp_path):
    """Regression (#612): `HEAD:reference/scenes.csv` is repo-root relative,
    so every committed file in a subfolder project looked absent from HEAD:
    always dirty, and a deleted one never reported missing."""
    repo = str(tmp_path / 'evals')
    _init_repo(repo)
    project = make_project(FIXTURE_DIR, tmp_path / 'evals' / 'projects' / 'book')
    _commit_all(repo)
    state = detect_state(project)
    assert state['dirty_csvs'] == []
    os.remove(os.path.join(project, 'reference', 'scenes.csv'))
    assert 'reference/scenes.csv' in detect_state(project)['missing_csvs']

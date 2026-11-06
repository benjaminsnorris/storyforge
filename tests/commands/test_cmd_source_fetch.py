"""`storyforge source fetch` and `storyforge init`: a Gutenberg text to a
project ready for scenes-setup, with Storyforge alone."""

import json
import os
import subprocess

import pytest

from storyforge import cmd_init, cmd_source

RAW = ('*** START OF THE PROJECT GUTENBERG EBOOK X ***\n\nCONTENTS\nI\nII\n\n\n'
       'I\n\n\nLO, the first line\nand the second.\n\nA new stanza\nends here.\n\n\n'
       'II\n\n\nThe last fitt.\n\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\n')
META = {'title': 'X', 'author': 'Anon', 'year': 900, 'genre': 'epic',
        'gutenberg_id': 99, 'chapter_heading': r'^([IVX]+)$', 'heading': 'Fitt {}'}


@pytest.fixture
def files(tmp_path):
    raw = tmp_path / 'raw.txt'
    raw.write_text(RAW)
    meta = tmp_path / 'meta.json'
    meta.write_text(json.dumps(META))
    return str(raw), str(meta)


@pytest.fixture
def git_env(monkeypatch):
    for k, v in {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(cmd_init, 'install_signal_handlers', lambda: None)
    monkeypatch.setattr(cmd_source, 'install_signal_handlers', lambda: None)


def _init(tmp_path, files, *extra):
    raw, meta = files
    project = tmp_path / 'book'
    code = cmd_init.main([str(project), '--meta', meta, '--fetch', '--input', raw, *extra])
    return code, project


class TestInit:
    def test_a_fresh_directory_becomes_a_project_and_a_repo(self, tmp_path, files, git_env):
        code, project = _init(tmp_path, files, '--verse')
        assert code == 0
        runner = project / 'storyforge'
        assert runner.is_file() and os.access(runner, os.X_OK)
        for rel in ('.gitignore', 'CLAUDE.md', 'working/pipeline.csv',
                    'reference/scenes.csv', 'reference/scene-intent.csv',
                    'reference/gutenberg.json', 'working/gutenberg/pg99.txt'):
            assert (project / rel).is_file(), rel
        assert not (project / 'reference' / 'visual-style.md').exists()
        yaml = (project / 'storyforge.yaml').read_text()
        assert 'title: "X"' in yaml and 'genre: "epic"' in yaml
        assert 'target_words: 1000' in yaml and 'author: "Anon"' in yaml
        assert (project / 'manuscript.md').read_text() == (
            '# Fitt I\n\nLO, the first line\\\nand the second.\n\n'
            'A new stanza\\\nends here.\n\n# Fitt II\n\nThe last fitt.\n')
        assert json.loads((project / 'reference/gutenberg.json').read_text())['verse'] is True
        assert 'Project Gutenberg #99' in (project / 'CLAUDE.md').read_text()
        log = subprocess.run(['git', 'log', '--format=%s', 'main'], cwd=project,
                             capture_output=True, text=True).stdout
        assert log.strip() == 'Initialize Storyforge project: X'
        status = subprocess.run(['git', 'status', '--porcelain'], cwd=project,
                                capture_output=True, text=True).stdout
        assert status == ''

    def test_a_non_empty_directory_is_refused(self, tmp_path, files, git_env):
        (tmp_path / 'book').mkdir()
        (tmp_path / 'book' / 'x').write_text('x')
        code, _ = _init(tmp_path, files)
        assert code == 1

    def test_a_config_that_cannot_make_a_manuscript_writes_nothing(
            self, tmp_path, files, git_env):
        raw, _ = files
        meta = tmp_path / 'bad.json'
        meta.write_text(json.dumps(dict(META, chapter_heading='^NOPE$')))
        code = cmd_init.main([str(tmp_path / 'book'), '--meta', str(meta),
                              '--fetch', '--input', raw])
        assert code == 1
        assert not (tmp_path / 'book').exists()

    def test_title_fills_the_reference_templates(self, tmp_path, git_env):
        # beowulf B-001: key-decisions.md kept its "PROJECT_TITLE" heading
        project = tmp_path / 'book'
        assert cmd_init.main([str(project), '--title', 'Beowulf', '--no-commit']) == 0
        text = (project / 'reference' / 'key-decisions.md').read_text()
        assert 'Key Decisions — Beowulf' in text
        for f in (project / 'reference').iterdir():
            assert 'PROJECT_TITLE' not in f.read_text(), f.name

    def test_the_translator_is_named(self, tmp_path, git_env):
        # beowulf B-001: "Beowulf by Anonymous (1909)" for Gummere's translation
        meta = tmp_path / 'meta.json'
        meta.write_text(json.dumps({'title': 'Beowulf', 'author': 'Anonymous',
                                    'translator': 'Francis Barton Gummere', 'year': 1909,
                                    'chapter_heading': '^([IVXL]+)$'}))
        project = tmp_path / 'book'
        assert cmd_init.main([str(project), '--meta', str(meta), '--no-commit']) == 0
        assert ('Beowulf by Anonymous, translated by Francis Barton Gummere (1909)'
                in (project / 'CLAUDE.md').read_text())

    def test_title_is_required(self, tmp_path, git_env):
        assert cmd_init.main([str(tmp_path / 'book'), '--no-commit']) == 1
        assert cmd_init.main([str(tmp_path / 'b2'), '--title', 'T', '--no-commit']) == 0


class TestFetch:
    def _project(self, tmp_path, files, monkeypatch):
        code, project = _init(tmp_path, files, '--no-commit')
        assert code == 0
        monkeypatch.setattr(cmd_source, 'detect_project_root', lambda: str(project))
        return project

    def test_reads_the_projects_config_and_cache(self, tmp_path, files, git_env, monkeypatch):
        project = self._project(tmp_path, files, monkeypatch)
        before = (project / 'manuscript.md').read_text()
        # the cached raw text is used: no download
        monkeypatch.setattr('storyforge.gutenberg.download',
                            lambda *a: pytest.fail('downloaded'))
        assert cmd_source.main(['fetch', '--no-commit']) == 0
        assert (project / 'manuscript.md').read_text() == before

    def test_a_different_manuscript_needs_force(self, tmp_path, files, git_env, monkeypatch):
        project = self._project(tmp_path, files, monkeypatch)
        (project / 'manuscript.md').write_text('My own edits.\n')
        assert cmd_source.main(['fetch', '--verse', '--no-commit']) == 1
        assert (project / 'manuscript.md').read_text() == 'My own edits.\n'
        assert cmd_source.main(['fetch', '--verse', '--no-commit', '--force']) == 0
        assert '\\\n' in (project / 'manuscript.md').read_text()

    def test_dry_run_writes_nothing(self, tmp_path, files, git_env, monkeypatch):
        project = self._project(tmp_path, files, monkeypatch)
        (project / 'manuscript.md').unlink()
        assert cmd_source.main(['fetch', '--dry-run']) == 0
        assert not (project / 'manuscript.md').exists()

    def test_no_config_says_so(self, tmp_path, git_env, monkeypatch, capsys):
        assert cmd_init.main([str(tmp_path / 'b'), '--title', 'T', '--no-commit']) == 0
        monkeypatch.setattr(cmd_source, 'detect_project_root', lambda: str(tmp_path / 'b'))
        assert cmd_source.main(['fetch']) == 1
        assert 'reference/gutenberg.json' in capsys.readouterr().out


def test_init_inside_a_repo_commits_on_its_branch(tmp_path, files, git_env):
    """A book repo's `source/`: committed on the branch it is on, never a new repo."""
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'commit', '-q', '--allow-empty', '-m', 'root'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'checkout', '-q', '-b', 'stage-1'], cwd=tmp_path, check=True)
    code, project = _init(tmp_path, files)
    assert code == 0
    assert not (project / '.git').exists()
    log = subprocess.run(['git', 'log', '--format=%s', 'stage-1'], cwd=tmp_path,
                         capture_output=True, text=True).stdout.split('\n')
    assert log[0] == 'Initialize Storyforge project: X'


def test_init_inside_a_repo_leaves_other_staged_files_out(tmp_path, files, git_env):
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'commit', '-q', '--allow-empty', '-m', 'root'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'checkout', '-q', '-b', 'stage-1'], cwd=tmp_path, check=True)
    (tmp_path / 'notes.md').write_text('mine')
    subprocess.run(['git', 'add', 'notes.md'], cwd=tmp_path, check=True)
    code, _ = _init(tmp_path, files)
    assert code == 0
    committed = subprocess.run(['git', 'show', '--name-only', '--format=', 'HEAD'],
                               cwd=tmp_path, capture_output=True, text=True).stdout.split()
    assert 'notes.md' not in committed and 'book/manuscript.md' in committed
    staged = subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=tmp_path,
                            capture_output=True, text=True).stdout.split()
    assert staged == ['notes.md']


def test_fetch_says_when_it_replaces_the_config(tmp_path, files, git_env, monkeypatch, capsys):
    code, project = _init(tmp_path, files, '--no-commit')
    assert code == 0
    monkeypatch.setattr(cmd_source, 'detect_project_root', lambda: str(project))
    other = tmp_path / 'other.json'
    other.write_text(json.dumps(dict(META, heading='Book {}')))
    assert cmd_source.main(['fetch', '--meta', str(other), '--force', '--no-commit']) == 0
    out = capsys.readouterr().out
    assert 'WARNING: replaced reference/gutenberg.json' in out
    assert json.loads((project / 'reference/gutenberg.json').read_text())['heading'] == 'Book {}'


def test_fetch_with_a_bad_config_writes_nothing(tmp_path, files, git_env, monkeypatch, capsys):
    code, project = _init(tmp_path, files, '--no-commit')
    monkeypatch.setattr(cmd_source, 'detect_project_root', lambda: str(project))
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps(dict(META, other_headings=['^X$'])))
    before = (project / 'manuscript.md').read_text()
    assert cmd_source.main(['fetch', '--meta', str(bad), '--no-commit']) == 1
    assert 'Nothing was written' in capsys.readouterr().out
    assert (project / 'manuscript.md').read_text() == before


class TestInitKinds:
    """#553 (Beowulf B-014, Gawain G-013): init makes an adaptation with
    --source, and a new novel's CLAUDE.md lists elaboration, not extraction."""

    def test_source_writes_the_block(self, tmp_path, git_env):
        src = tmp_path / 'beowulf-source'
        src.mkdir()
        (src / 'storyforge.yaml').write_text('project:\n  title: "Beowulf"\n')
        project = tmp_path / 'novel'
        assert cmd_init.main([str(project), '--title', 'Beowulf', '--source', str(src),
                              '--source-slug', 'beowulf', '--no-commit']) == 0
        from storyforge import source
        cfg = source.read_config(str(project))
        assert [(p.slug, p.path) for p in cfg.projects] == [('beowulf', '../beowulf-source')]
        assert cfg.mode == 'faithful'
        md = (project / 'CLAUDE.md').read_text()
        assert './storyforge source import' in md
        assert 'split-manuscript' not in md and '`./storyforge extract`' not in md

    def test_source_mode_and_default_slug(self, tmp_path, git_env):
        src = tmp_path / 'gawain'
        src.mkdir()
        (src / 'storyforge.yaml').write_text('project:\n  title: "G"\n')
        project = tmp_path / 'novel'
        assert cmd_init.main([str(project), '--title', 'G', '--source', str(src),
                              '--source-mode', 'free', '--no-commit']) == 0
        from storyforge import source
        cfg = source.read_config(str(project))
        assert cfg.projects[0].slug == 'gawain' and cfg.mode == 'free'

    def test_source_must_be_a_project(self, tmp_path, git_env):
        assert cmd_init.main([str(tmp_path / 'novel'), '--title', 'G', '--source',
                              str(tmp_path), '--no-commit']) == 1
        assert not (tmp_path / 'novel').exists()

    def test_source_has_no_manuscript(self, tmp_path, git_env):
        with pytest.raises(SystemExit):
            cmd_init.main([str(tmp_path / 'n'), '--title', 'G', '--source', str(tmp_path),
                           '--manuscript', 'x.md'])

    def test_a_new_novel_lists_elaboration(self, tmp_path, git_env):
        project = tmp_path / 'novel'
        assert cmd_init.main([str(project), '--title', 'T', '--no-commit']) == 0
        md = (project / 'CLAUDE.md').read_text()
        assert './storyforge elaborate --stage spine' in md
        assert 'split-manuscript' not in md
        assert 'source:' not in (project / 'storyforge.yaml').read_text()

    def test_an_extraction_still_lists_extraction(self, tmp_path, files, git_env):
        code, project = _init(tmp_path, files, '--no-commit')
        assert code == 0
        assert 'scenes-setup --split-manuscript' in (project / 'CLAUDE.md').read_text()


class TestInitWhereGitCantHelp:
    """#520 review (TD-3): init's own `_in_git_repo` read any git failure as
    "no repository", so inside a repository git refused it ran `git init`
    and nested a new one; and with no git installed it crashed."""

    def test_no_git_installed_is_an_error_not_a_crash(self, tmp_path, git_env,
                                                      monkeypatch, capsys):
        empty = tmp_path / 'empty-path'
        empty.mkdir()
        monkeypatch.setenv('PATH', str(empty))
        project = tmp_path / 'novel'
        assert cmd_init.main([str(project), '--title', 'T']) == 1
        assert (project / 'storyforge.yaml').is_file()
        assert 'not committed: git is not installed' in capsys.readouterr().out

    def test_a_refused_repository_gets_no_nested_repository(self, tmp_path, git_env,
                                                           monkeypatch, capsys):
        monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path.parent))
        subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
        monkeypatch.setenv('GIT_TEST_ASSUME_DIFFERENT_OWNER', '1')
        project = tmp_path / 'novel'
        assert cmd_init.main([str(project), '--title', 'T']) == 1
        assert not (project / '.git').exists()
        assert 'dubious ownership' in capsys.readouterr().out

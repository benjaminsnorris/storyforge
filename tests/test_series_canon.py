"""A series' shared canon (`series.canon`): read in place by every prompt
that carries the bibles, never written, and an error when it can't be used."""

import os

import pytest

from storyforge import common, series
from storyforge import prompts_elaborate as pe
from storyforge.source import SourceError


def _yaml(project_dir, block):
    path = os.path.join(project_dir, 'storyforge.yaml')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.rstrip('\n') + '\n\n' + block)


@pytest.fixture
def canon(tmp_path):
    """A series canon outside the project, like `homer/series-bible`."""
    d = tmp_path / 'homer' / 'series-bible'
    d.mkdir(parents=True)
    (d / 'gods.md').write_text('# The gods\n\nA god may not undo what fate has set.\n')
    (d / 'cast.md').write_text('# Cast\n\nTelemachus is twenty.\n')
    (d / 'decisions.md').write_text('# Open questions\n\nNot canon yet.\n')
    return d


@pytest.fixture(autouse=True)
def _fresh_shared_context():
    common._shared_context_cache.clear()
    yield
    common._shared_context_cache.clear()


def _shared_text(project_dir):
    return '\n'.join(b['text'] for b in
                     common.build_shared_context(project_dir, 'claude-opus-5-5'))


class TestConfig:
    def test_no_block_is_no_canon(self, project_dir):
        assert series.canon_paths(project_dir) == []
        assert series.canon_text(project_dir) == []
        assert series.summary_line(project_dir) == ''

    def test_list_and_single_path(self, project_dir, canon):
        rel = os.path.relpath(canon, project_dir)
        _yaml(project_dir, f'series:\n  canon:\n    - {rel}/gods.md\n'
                           f'    - "{rel}/cast.md"   # quoted, with a comment\n')
        assert series.canon_paths(project_dir) == [f'{rel}/gods.md', f'{rel}/cast.md']

    def test_one_path_on_the_line(self, project_dir, canon):
        rel = os.path.relpath(canon, project_dir)
        _yaml(project_dir, f'series:\n  canon: {rel}/gods.md\n')
        assert series.canon_paths(project_dir) == [f'{rel}/gods.md']

    def test_series_block_stops_at_the_next_top_level_key(self, project_dir, canon):
        rel = os.path.relpath(canon, project_dir)
        _yaml(project_dir, f'series:\n  canon:\n    - {rel}/gods.md\nother:\n  - not-canon.md\n')
        assert series.canon_paths(project_dir) == [f'{rel}/gods.md']

    def test_project_series_name_is_not_the_block(self, project_dir):
        # `project.series_name` is a different key; only a top-level `series:` counts
        assert series.canon_paths(project_dir) == []

    @pytest.mark.parametrize('block, message', [
        ('series: homer\n', 'must be a block'),
        ('series:\n  bible: x.md\n', 'it takes canon'),
        ('series:\n  canon: a.md\n  canon: b.md\n', 'twice'),
        ('series:\n  canon:\n    -\n', 'empty list item'),
        ('series:\n  canon:\n    stray text\n', "can't read"),
    ])
    def test_a_block_that_cant_be_used_is_an_error(self, project_dir, block, message):
        _yaml(project_dir, block)
        with pytest.raises(series.SeriesError, match=message):
            series.canon_paths(project_dir)

    def test_series_error_is_a_source_error(self):
        # every command that stops cleanly on a bad `source:` block stops on this
        assert issubclass(series.SeriesError, SourceError)


class TestFiles:
    def test_a_directory_is_its_md_files_in_name_order(self, project_dir, canon):
        (canon / 'cast.csv').write_text('id|name\n')
        _yaml(project_dir, f'series:\n  canon: {os.path.relpath(canon, project_dir)}\n')
        names = [os.path.basename(p) for _, p in series.canon_files(project_dir)]
        assert names == ['cast.md', 'decisions.md', 'gods.md']

    def test_a_file_named_twice_is_read_once(self, project_dir, canon):
        rel = os.path.relpath(canon, project_dir)
        _yaml(project_dir, f'series:\n  canon:\n    - {rel}/gods.md\n    - {rel}\n')
        names = [os.path.basename(p) for _, p in series.canon_files(project_dir)]
        assert names == ['gods.md', 'cast.md', 'decisions.md']

    def test_a_missing_path_is_an_error(self, project_dir):
        _yaml(project_dir, 'series:\n  canon:\n    - ../nowhere/gods.md\n')
        with pytest.raises(series.SeriesError, match='is not there'):
            series.canon_files(project_dir)

    def test_a_directory_with_no_md_is_an_error(self, project_dir, tmp_path):
        empty = tmp_path / 'empty'
        empty.mkdir()
        _yaml(project_dir, f'series:\n  canon: {empty}\n')
        with pytest.raises(series.SeriesError, match='no .md file'):
            series.canon_files(project_dir)

    def test_an_empty_file_is_an_error(self, project_dir, canon):
        (canon / 'gods.md').write_text('\n\n')
        _yaml(project_dir, f'series:\n  canon: {canon}/gods.md\n')
        with pytest.raises(series.SeriesError, match='is empty'):
            series.canon_text(project_dir)

    def test_a_file_not_utf8_is_an_error(self, project_dir, canon):
        (canon / 'gods.md').write_bytes(b'Caf\xe9 of the gods')
        _yaml(project_dir, f'series:\n  canon: {canon}/gods.md\n')
        with pytest.raises(series.SeriesError, match="can't read"):
            series.canon_text(project_dir)

    def test_text_labels_and_the_note_once(self, project_dir, canon):
        rel = os.path.relpath(canon, project_dir)
        _yaml(project_dir, f'series:\n  canon:\n    - {rel}/gods.md\n    - {rel}/cast.md\n')
        texts = series.canon_text(project_dir)
        assert [l for l, _ in texts] == [f'Series Canon ({rel}/gods.md)',
                                         f'Series Canon ({rel}/cast.md)']
        assert texts[0][1].startswith(series.CANON_NOTE)
        assert series.CANON_NOTE not in texts[1][1]
        assert 'fate has set' in texts[0][1]


class TestPrompts:
    def _configure(self, project_dir, canon):
        rel = os.path.relpath(canon, project_dir)
        _yaml(project_dir, f'series:\n  canon:\n    - {rel}/gods.md\n    - {rel}/cast.md\n')
        return rel

    def test_shared_context_carries_the_canon(self, project_dir, canon):
        rel = self._configure(project_dir, canon)
        text = _shared_text(project_dir)
        assert f'=== Series Canon ({rel}/gods.md) ===' in text
        assert 'A god may not undo what fate has set.' in text
        assert 'Telemachus is twenty.' in text
        assert 'Not canon yet.' not in text

    def test_elaborate_refs_carry_it_unless_the_shared_context_does(self, project_dir, canon):
        rel = self._configure(project_dir, canon)
        assert f'### Series Canon ({rel}/gods.md)' in pe._existing_refs(project_dir)
        assert 'Series Canon' not in pe._existing_refs(project_dir, shared=True)

    def test_no_block_leaves_prompts_as_they_were(self, project_dir):
        assert 'Series Canon' not in _shared_text(project_dir)
        assert 'Series Canon' not in pe._existing_refs(project_dir)

    def test_a_canon_that_cant_be_read_stops_the_prompt(self, project_dir):
        _yaml(project_dir, 'series:\n  canon: ../nowhere.md\n')
        with pytest.raises(series.SeriesError):
            common.build_shared_context(project_dir, 'claude-opus-5-5')
        with pytest.raises(series.SeriesError):
            pe._existing_refs(project_dir)

    def test_the_canon_is_never_written(self, project_dir, canon):
        self._configure(project_dir, canon)
        before = {p.name: p.read_bytes() for p in canon.iterdir()}
        _shared_text(project_dir)
        pe._existing_refs(project_dir)
        assert {p.name: p.read_bytes() for p in canon.iterdir()} == before


class TestValidate:
    def _run(self, project_dir, monkeypatch, capsys):
        from storyforge.cmd_validate import main
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        with pytest.raises(SystemExit) as exc:
            main([])
        return exc.value.code, capsys.readouterr().out

    def test_reports_the_canon(self, project_dir, canon, monkeypatch, capsys):
        _yaml(project_dir, f'series:\n  canon: {canon}/gods.md\n')
        _, out = self._run(project_dir, monkeypatch, capsys)
        assert '--- Series canon ---' in out
        assert 'Series canon: 1 file(s)' in out

    def test_a_bad_canon_blocks(self, project_dir, monkeypatch, capsys):
        code_before, out_before = self._run(project_dir, monkeypatch, capsys)
        assert '--- Series canon ---' not in out_before
        _yaml(project_dir, 'series:\n  canon: ../nowhere.md\n')
        code, out = self._run(project_dir, monkeypatch, capsys)
        assert '[blocking] series.canon: ../nowhere.md is not there' in out
        assert code == 1

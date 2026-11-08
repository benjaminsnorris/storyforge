"""A series' shared canon (`series.canon`): read in place by every prompt
that carries the bibles, never written, and an error when it can't be used."""

import json
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
        assert series.summary_lines(project_dir) == []
        series.require_canon(project_dir)

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
    """The exit code is checked with every other validator passing, so it is
    the canon's (the fixture fails validation on its own)."""

    def _run(self, project_dir, monkeypatch, capsys, argv=()):
        from storyforge.cmd_validate import main
        from commands.test_cmd_validate import (
            _no_errors_voice_profile, _passing_schema, _passing_structural)
        monkeypatch.setattr('storyforge.cmd_validate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.elaborate.validate_structure',
                            lambda ref_dir: _passing_structural())
        monkeypatch.setattr('storyforge.schema.validate_schema',
                            lambda ref_dir, project_dir=None: _passing_schema())
        monkeypatch.setattr('storyforge.schema.validate_voice_profile',
                            lambda pd: _no_errors_voice_profile())
        with pytest.raises(SystemExit) as exc:
            main(list(argv))
        return exc.value.code, capsys.readouterr().out

    def test_no_block_no_section_and_exit_unchanged(self, project_dir, monkeypatch, capsys):
        code, out = self._run(project_dir, monkeypatch, capsys)
        assert code == 0 and '--- Series canon ---' not in out
        code, out = self._run(project_dir, monkeypatch, capsys, ['--json'])
        assert 'series' not in json.loads(out)

    def test_reports_the_canon_and_passes(self, project_dir, canon, monkeypatch, capsys):
        (canon / 'gods.md').write_text('one two three\n')
        _yaml(project_dir, f'series:\n  canon: {canon}/gods.md\n')
        code, out = self._run(project_dir, monkeypatch, capsys)
        assert code == 0
        assert '--- Series canon ---' in out
        # the files' own words, not the note prompts open with (TD-1)
        assert 'Series canon: 1 file(s), 3 words' in out
        assert f'{canon}/gods.md' in out

    def test_a_bad_canon_blocks(self, project_dir, monkeypatch, capsys):
        _yaml(project_dir, 'series:\n  canon: ../nowhere.md\n')
        code, out = self._run(project_dir, monkeypatch, capsys)
        assert '[blocking] series.canon: ../nowhere.md is not there' in out
        assert code == 1

    def test_json_findings_in_sources_shape(self, project_dir, canon, monkeypatch, capsys):
        _yaml(project_dir, 'series:\n  canon: ../nowhere.md\n')
        _, out = self._run(project_dir, monkeypatch, capsys, ['--json'])
        got = json.loads(out)['series']
        assert got['lines'] == []
        [f] = got['findings']
        assert f['severity'] == 'blocking' and f['check'] == 'series'
        assert f['message'].startswith('series.canon: ../nowhere.md is not there')


class TestReviewFixes:
    """PR #624's review: values that aren't paths, blocks that name nothing or
    sit in the wrong place, an unlistable directory, the up-front check, the
    dispatcher, and the prompts that carried no canon."""

    @pytest.mark.parametrize('value', ['~', 'null', 'Null', '"~"', '[a.md, b.md]', '[]', '{}'])
    def test_a_value_that_isnt_a_path_is_refused(self, project_dir, value, tmp_path,
                                                 monkeypatch):
        # CR-1/SF-4: `~` expanded to the home directory and read its .md files
        home = tmp_path / 'home'
        home.mkdir()
        (home / 'todo.md').write_text('private notes\n')
        monkeypatch.setenv('HOME', str(home))
        _yaml(project_dir, f'series:\n  canon: {value}\n')
        with pytest.raises(series.SeriesError, match='not a path|block list'):
            series.canon_text(project_dir)

    def test_a_list_item_that_isnt_a_path_is_refused(self, project_dir):
        _yaml(project_dir, 'series:\n  canon:\n    - ~\n')
        with pytest.raises(series.SeriesError, match='not a path'):
            series.canon_paths(project_dir)

    @pytest.mark.parametrize('block', ['series:\n', 'series:\n  canon:\n',
                                       'series:\n  # nothing yet\n'])
    def test_a_block_naming_no_canon_is_an_error(self, project_dir, block):
        # SF-3: read as "no canon", so prompts went out without it in silence
        _yaml(project_dir, block)
        with pytest.raises(series.SeriesError, match='names no canon'):
            series.canon_paths(project_dir)

    @pytest.mark.parametrize('block, message', [
        ('series:\n  canon: a.md\nseries:\n  canon: b.md\n', 'given twice'),
        ('extra:\n  series:\n    canon: a.md\n', 'indented under another block'),
        ('canon:\n  - a.md\n', 'at the top level'),
    ])
    def test_a_misplaced_block_is_an_error(self, project_dir, block, message):
        _yaml(project_dir, block)
        with pytest.raises(series.SeriesError, match=message):
            series.canon_paths(project_dir)

    def test_a_bom_before_the_block_is_read(self, project_dir, canon):
        path = os.path.join(project_dir, 'storyforge.yaml')
        with open(path, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\ufeffseries:\n  canon: ' + str(canon / 'gods.md') + '\n' + text)
        assert len(series.canon_files(project_dir)) == 1

    @pytest.mark.skipif(hasattr(os, 'geteuid') and os.geteuid() == 0,
                        reason='root can list any directory')
    def test_a_directory_that_cant_be_listed_is_a_series_error(self, project_dir, canon):
        # SF-2: a bare PermissionError crashed validate and every command
        _yaml(project_dir, f'series:\n  canon: {canon}\n')
        os.chmod(canon, 0)
        try:
            with pytest.raises(series.SeriesError, match="can't list"):
                series.canon_files(project_dir)
        finally:
            os.chmod(canon, 0o755)

    def test_md_matches_any_case(self, project_dir, canon):
        (canon / 'Places.MD').write_text('Ithaca is rocky.\n')
        _yaml(project_dir, f'series:\n  canon: {canon}\n')
        names = [os.path.basename(p) for _, p in series.canon_files(project_dir)]
        assert 'Places.MD' in names

    def test_the_dispatcher_stops_plainly(self, project_dir, capsys):
        from storyforge import __main__ as dispatcher

        class Command:
            @staticmethod
            def main(argv):
                common.build_shared_context(project_dir, 'claude-opus-5-5')
        _yaml(project_dir, 'series:\n  canon: ../nowhere.md\n')
        with pytest.raises(SystemExit) as exc:
            dispatcher._dispatch(Command)
        assert exc.value.code == 1
        assert capsys.readouterr().err.startswith('ERROR: series.canon: ../nowhere.md')

    @pytest.mark.parametrize('module, argv', [
        ('cmd_write', ['--dry-run']),
        ('cmd_revise', ['--dry-run']),
        ('cmd_score', ['--dry-run']),
        ('cmd_evaluate', ['--dry-run']),
        ('cmd_extract', ['--dry-run']),
        ('cmd_elaborate', ['--stage', 'spine', '--dry-run']),
    ])
    def test_spending_commands_stop_before_anything_else(self, project_dir, monkeypatch,
                                                         module, argv):
        # CR-2/SF-1/SF-7: write's forecast warned and went on to branch and
        # open a PR; others branched before the first canon read
        import importlib
        mod = importlib.import_module(f'storyforge.{module}')
        monkeypatch.setattr(mod, 'detect_project_root', lambda: project_dir)
        _yaml(project_dir, 'series:\n  canon: ../nowhere.md\n')
        with pytest.raises(series.SeriesError, match='nowhere.md is not there'):
            mod.main(argv)

    def _configure(self, project_dir, canon):
        _yaml(project_dir, f'series:\n  canon: {canon}/gods.md\n')

    def test_drafting_prompt_without_system_context_carries_it(self, project_dir, canon):
        # SF-5: interactive and dry-run drafting never saw the canon
        from storyforge.prompts import build_scene_prompt
        self._configure(project_dir, canon)
        api = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
        assert '=== Series Canon (' in api and 'fate has set' in api
        listed = build_scene_prompt('act1-sc01', project_dir, api_mode=False)
        assert f'{canon}/gods.md (series canon' in listed
        shared = build_scene_prompt('act1-sc01', project_dir, api_mode=True,
                                    system_context=True)
        assert 'Series Canon' not in shared

    def test_drafting_prompts_unchanged_without_a_block(self, project_dir):
        from storyforge.prompts import build_scene_prompt
        assert 'Series Canon' not in build_scene_prompt('act1-sc01', project_dir, api_mode=True)
        assert 'series canon' not in build_scene_prompt('act1-sc01', project_dir)

    def test_the_gate_checker_reads_it(self, project_dir, canon):
        # the gate's checker read the book's bibles but not the canon, so a
        # scene contradicting the canon was never a finding
        from storyforge import checker
        self._configure(project_dir, canon)
        docs = checker.reference_docs(project_dir)
        assert docs['series-canon-gods.md'].startswith('# The gods')

    def test_the_checker_names_two_files_of_one_name_apart(self, project_dir, canon, tmp_path):
        from storyforge import checker
        other = tmp_path / 'other'
        other.mkdir()
        (other / 'gods.md').write_text('Other gods.\n')
        _yaml(project_dir, f'series:\n  canon:\n    - {canon}/gods.md\n    - {other}/gods.md\n')
        docs = checker.reference_docs(project_dir)
        assert docs['series-canon-gods.md'].startswith('# The gods')
        assert docs['series-canon-gods-2.md'] == 'Other gods.'

    def test_the_checker_stops_on_a_bad_canon(self, project_dir):
        from storyforge import checker
        _yaml(project_dir, 'series:\n  canon: ../nowhere.md\n')
        with pytest.raises(checker.CheckError, match='series canon'):
            checker.reference_docs(project_dir)

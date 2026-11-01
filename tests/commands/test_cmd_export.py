"""Tests for storyforge.cmd_export — writes the export bundle (plan §3.5)."""

import json
import os
import shutil

import pytest

from storyforge import export
from storyforge.cmd_export import main, parse_args


def _run(project_dir, monkeypatch, argv):
    monkeypatch.setattr('storyforge.cmd_export.detect_project_root', lambda: project_dir)
    main(argv)


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.output is None and not args.stdout

    def test_output_and_stdout_are_exclusive(self):
        with pytest.raises(SystemExit):
            parse_args(['--output', 'x.json', '--stdout'])


class TestMain:
    def test_writes_default_bundle(self, mock_api, project_dir, monkeypatch, capsys):
        _run(project_dir, monkeypatch, [])
        path = os.path.join(project_dir, 'working', 'export', 'bundle.json')
        with open(path, encoding='utf-8') as f:
            bundle = json.load(f)
        assert bundle['schema_version'] == export.SCHEMA_VERSION
        assert bundle['dashboard_data']['schema_version'] == 1
        for rel, text in export.tables_from_bundle(bundle).items():
            with open(os.path.join(project_dir, rel), 'rb') as f:
                assert text.encode('utf-8') == f.read(), rel
        assert 'Export bundle written' in capsys.readouterr().out
        assert mock_api.call_count == 0

    def test_output_path(self, project_dir, monkeypatch, tmp_path):
        out = tmp_path / 'elsewhere' / 'b.json'
        _run(project_dir, monkeypatch, ['--output', str(out)])
        assert json.loads(out.read_text(encoding='utf-8'))['schema_version'] == 1
        assert not os.path.exists(os.path.join(project_dir, export.DEFAULT_OUTPUT))

    def test_stdout_is_only_json(self, project_dir, monkeypatch, capsys):
        _run(project_dir, monkeypatch, ['--stdout'])
        captured = capsys.readouterr()
        assert json.loads(captured.out)['schema_version'] == 1
        assert 'Schema version 1' in captured.err
        assert not os.path.exists(os.path.join(project_dir, export.DEFAULT_OUTPUT))

    def test_stdout_survives_readers_that_print(self, project_dir, monkeypatch, capsys):
        """Anything printed while the bundle is built goes to stderr, so
        stdout parses as exactly one JSON document."""
        import storyforge.visualize as visualize
        real = visualize.load_dashboard_data

        def noisy(project, **kw):
            print('a reader that prints')
            return real(project)
        monkeypatch.setattr(visualize, 'load_dashboard_data', noisy)
        _run(project_dir, monkeypatch, ['--stdout'])
        captured = capsys.readouterr()
        assert json.loads(captured.out)['schema_version'] == 1
        assert 'a reader that prints' in captured.err

    def test_unwritable_output_exits_1_naming_it(self, project_dir, monkeypatch,
                                                 capsys, tmp_path):
        blocker = tmp_path / 'a-file'
        blocker.write_text('x')
        out = blocker / 'bundle.json'  # its "directory" is a file
        with pytest.raises(SystemExit) as exc:
            _run(project_dir, monkeypatch, ['--output', str(out)])
        assert exc.value.code == 1
        text = capsys.readouterr().out
        assert f'ERROR: could not write the bundle to {out}' in text
        assert 'Traceback' not in text

    def test_warnings_are_logged(self, project_dir, monkeypatch, capsys):
        with open(os.path.join(project_dir, 'reference', 'themes.csv'), 'wb') as f:
            f.write(b'id|name\nx|\xff\n')
        _run(project_dir, monkeypatch, [])
        out = capsys.readouterr().out
        assert 'WARNING: reference/themes.csv: not UTF-8' in out
        assert '1 warning(s)' in out

    def test_unmigrated_project_exits_1(self, project_dir, fixture_dir, monkeypatch, capsys):
        legacy = os.path.join(os.path.dirname(fixture_dir), 'legacy-registries')
        shutil.copy(os.path.join(legacy, 'knowledge.csv'),
                    os.path.join(project_dir, 'reference', 'knowledge.csv'))
        with pytest.raises(SystemExit) as exc:
            _run(project_dir, monkeypatch, [])
        assert exc.value.code == 1
        assert 'storyforge migrate' in capsys.readouterr().out
        assert not os.path.exists(os.path.join(project_dir, export.DEFAULT_OUTPUT))

    def test_malformed_ledger_exits_1(self, project_dir, monkeypatch, capsys):
        with open(os.path.join(project_dir, 'reference', 'commitments.csv'), 'a') as f:
            f.write('short|row\n')
        with pytest.raises(SystemExit) as exc:
            _run(project_dir, monkeypatch, ['--stdout'])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == '' and 'commitments.csv' in captured.err

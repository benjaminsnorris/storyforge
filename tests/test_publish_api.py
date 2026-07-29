"""Tests for API-compatible publish manifest generation and cmd_publish."""
import hashlib
import json
import os

import pytest


def _make_project(tmp_path, scenes, chapters):
    """Helper to create a minimal project for manifest tests."""
    ref = tmp_path / 'reference'
    ref.mkdir(exist_ok=True)
    scenes_dir = tmp_path / 'scenes'
    scenes_dir.mkdir(exist_ok=True)
    (tmp_path / 'storyforge.yaml').write_text(
        'project:\n  title: Test Book\n  author: Test Author\n  genre: fiction\n  language: en\n'
    )

    # scenes.csv
    lines = ['id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words']
    for i, sid in enumerate(scenes, 1):
        lines.append(f'{sid}|{i}|Title {i}|1|pov|loc|1|morning|short|action|drafted|100|200')
    (ref / 'scenes.csv').write_text('\n'.join(lines) + '\n')

    # chapter-map.csv
    ch_lines = ['chapter|title|heading|part|scenes']
    for i, (title, scene_ids) in enumerate(chapters, 1):
        ch_lines.append(f'{i}|{title}|numbered|1|{";".join(scene_ids)}')
    (ref / 'chapter-map.csv').write_text('\n'.join(ch_lines) + '\n')

    # scene markdown files
    for sid in scenes:
        (scenes_dir / f'{sid}.md').write_text(f'The prose for scene {sid}. Some words here.\n')

    return str(tmp_path)


class TestManifestMetadata:
    def test_includes_metadata(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        path = generate_publish_manifest(proj)
        with open(path) as f:
            manifest = json.load(f)
        assert 'metadata' in manifest
        assert manifest['metadata']['genre'] == 'fiction'
        assert manifest['metadata']['language'] == 'en'

    def test_no_cover_path_or_generated_at(self, tmp_path):
        """The API manifest carries `metadata`, not the old cover_path/generated_at."""
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        path = generate_publish_manifest(proj)
        with open(path) as f:
            manifest = json.load(f)
        assert 'cover_path' not in manifest
        assert 'generated_at' not in manifest


class TestManifestDashboard:
    def test_includes_dashboard_html(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])

        # Create a dashboard file
        working = tmp_path / 'working'
        working.mkdir(exist_ok=True)
        (working / 'dashboard.html').write_text('<html><body>Dashboard</body></html>')

        path = generate_publish_manifest(proj, include_dashboard=True)
        with open(path) as f:
            manifest = json.load(f)
        assert manifest['dashboard_html'] == '<html><body>Dashboard</body></html>'

    def test_skips_dashboard_when_not_requested(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])

        working = tmp_path / 'working'
        working.mkdir(exist_ok=True)
        (working / 'dashboard.html').write_text('<html>Dashboard</html>')

        path = generate_publish_manifest(proj, include_dashboard=False)
        with open(path) as f:
            manifest = json.load(f)
        assert 'dashboard_html' not in manifest
        assert 'dashboard_data' not in manifest

    def test_missing_dashboard_not_included(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        # No dashboard file exists
        path = generate_publish_manifest(proj, include_dashboard=True)
        with open(path) as f:
            manifest = json.load(f)
        assert 'dashboard_html' not in manifest


class TestManifestCover:
    """The cover is an ordinary content-addressed asset.

    It used to ride the manifest as base64 in `cover_base64`, which bookshelf
    deprecated: the server adopted it into a cover asset and warned. It is now
    declared as `role: 'cover'` alongside any illustrations, hashed the same
    way, with its bytes uploaded through the same signed-URL path.
    """

    def test_declares_the_cover_as_an_asset(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])

        production = tmp_path / 'production'
        production.mkdir(exist_ok=True)
        cover_data = b'\x89PNG fake cover data'
        (production / 'cover.png').write_bytes(cover_data)

        path = generate_publish_manifest(proj, include_cover=True)
        with open(path) as f:
            manifest = json.load(f)

        assert 'cover_base64' not in manifest
        assert 'cover_extension' not in manifest
        assert manifest['assets'] == [{
            'key': 'cover', 'role': 'cover',
            'sha256': hashlib.sha256(cover_data).hexdigest(),
            'extension': 'png', 'byte_size': len(cover_data),
        }]

    def test_records_the_cover_bytes_in_the_source_sidecar(self, tmp_path):
        """The transport uploads by digest, so the digest must map to a file."""
        from storyforge.assembly import (generate_publish_manifest,
                                         read_asset_sources)
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        production = tmp_path / 'production'
        production.mkdir(exist_ok=True)
        cover_data = b'\x89PNG fake cover data'
        (production / 'cover.png').write_bytes(cover_data)

        generate_publish_manifest(proj, include_cover=True)

        sources = read_asset_sources(proj)
        digest = hashlib.sha256(cover_data).hexdigest()
        assert os.path.isfile(sources[digest])
        with open(sources[digest], 'rb') as f:
            assert f.read() == cover_data

    def test_explicit_cover_path(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])

        # Create cover in a non-standard location
        custom = tmp_path / 'custom'
        custom.mkdir(exist_ok=True)
        cover_data = b'\xff\xd8\xff fake jpeg'
        (custom / 'my-cover.jpg').write_bytes(cover_data)

        path = generate_publish_manifest(
            proj, cover_path=str(custom / 'my-cover.jpg'), include_cover=True
        )
        with open(path) as f:
            manifest = json.load(f)
        cover = manifest['assets'][0]
        assert cover['sha256'] == hashlib.sha256(cover_data).hexdigest()
        # Normalized to `jpeg`: the storage path is {digest}.{extension}, so two
        # spellings of one format would occupy two paths for the same bytes.
        assert cover['extension'] == 'jpeg'

    def test_no_cover_when_not_requested(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])

        production = tmp_path / 'production'
        production.mkdir(exist_ok=True)
        (production / 'cover.png').write_bytes(b'PNG data')

        path = generate_publish_manifest(proj, include_cover=False)
        with open(path) as f:
            manifest = json.load(f)
        # No assets at all, so bookshelf reads nothing about the cover and
        # leaves the live one alone. An EMPTY array would not do: `Boolean([])`
        # is true in JS, and the server treats a declared array as a statement.
        assert 'assets' not in manifest

    def test_missing_cover_not_included(self, tmp_path, capsys):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        # No cover file exists
        path = generate_publish_manifest(proj, include_cover=True)
        with open(path) as f:
            manifest = json.load(f)
        assert 'assets' not in manifest
        assert 'no cover image found' in capsys.readouterr().out

    def test_svg_cover_is_refused_as_an_asset(self, tmp_path, capsys):
        """The asset bucket takes png/jpg/jpeg/webp. An SVG is not publishable.

        Autodetect must not settle for it either: a project can hold a
        production/cover.svg compositing source next to the rendered PNG that
        actually ships.
        """
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        production = tmp_path / 'production'
        production.mkdir(exist_ok=True)
        (production / 'cover.svg').write_text('<svg/>')

        path = generate_publish_manifest(proj, include_cover=True)
        with open(path) as f:
            manifest = json.load(f)
        assert 'assets' not in manifest
        assert 'no cover image found' in capsys.readouterr().out

    def test_autodetect_prefers_a_publishable_cover_over_an_svg(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        production = tmp_path / 'production'
        production.mkdir(exist_ok=True)
        (production / 'cover.svg').write_text('<svg/>')
        assets_dir = tmp_path / 'manuscript' / 'assets'
        assets_dir.mkdir(parents=True)
        (assets_dir / 'cover.jpg').write_bytes(b'\xff\xd8\xff jpeg')

        path = generate_publish_manifest(proj, include_cover=True)
        with open(path) as f:
            manifest = json.load(f)
        assert manifest['assets'][0]['extension'] == 'jpeg'


class TestResolveCoverPath:
    def test_auto_detects_production_cover(self, tmp_path):
        from storyforge.assembly import _resolve_cover_path
        (tmp_path / 'production').mkdir()
        (tmp_path / 'production' / 'cover.png').write_bytes(b'PNG')
        result = _resolve_cover_path(str(tmp_path), None)
        assert result.endswith('production/cover.png')

    def test_auto_detects_manuscript_assets_cover(self, tmp_path):
        from storyforge.assembly import _resolve_cover_path
        assets = tmp_path / 'manuscript' / 'assets'
        assets.mkdir(parents=True)
        (assets / 'cover.jpg').write_bytes(b'JPG')
        result = _resolve_cover_path(str(tmp_path), None)
        assert result.endswith('manuscript/assets/cover.jpg')

    def test_prefers_production_over_manuscript(self, tmp_path):
        from storyforge.assembly import _resolve_cover_path
        (tmp_path / 'production').mkdir()
        (tmp_path / 'production' / 'cover.png').write_bytes(b'PNG')
        assets = tmp_path / 'manuscript' / 'assets'
        assets.mkdir(parents=True)
        (assets / 'cover.jpg').write_bytes(b'JPG')
        result = _resolve_cover_path(str(tmp_path), None)
        assert 'production' in result

    def test_absolute_path_passthrough(self, tmp_path):
        from storyforge.assembly import _resolve_cover_path
        result = _resolve_cover_path(str(tmp_path), '/abs/path/cover.png')
        assert result == '/abs/path/cover.png'

    def test_relative_path_resolved(self, tmp_path):
        from storyforge.assembly import _resolve_cover_path
        result = _resolve_cover_path(str(tmp_path), 'custom/cover.svg')
        assert result == os.path.join(str(tmp_path), 'custom/cover.svg')

    def test_returns_none_when_no_cover(self, tmp_path):
        from storyforge.assembly import _resolve_cover_path
        result = _resolve_cover_path(str(tmp_path), None)
        assert result is None


class TestCmdPublishParseArgs:
    def test_defaults(self):
        from storyforge.cmd_publish import parse_args
        args = parse_args([])
        assert args.dashboard is True
        assert args.no_dashboard is False
        assert args.cover is False
        assert args.no_cover is False
        assert args.annotations is False
        assert args.dry_run is False

    def test_cover_flag(self):
        from storyforge.cmd_publish import parse_args
        args = parse_args(['--cover'])
        assert args.cover is True

    def test_no_cover_flag(self):
        from storyforge.cmd_publish import parse_args
        assert parse_args(['--no-cover']).no_cover is True

    def test_no_dashboard_flag(self):
        from storyforge.cmd_publish import parse_args
        args = parse_args(['--no-dashboard'])
        assert args.no_dashboard is True

    def test_dry_run_flag(self):
        from storyforge.cmd_publish import parse_args
        args = parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_annotations_flag(self):
        from storyforge.cmd_publish import parse_args
        args = parse_args(['--annotations'])
        assert args.annotations is True


# ============================================================================
# cmd_publish orchestration
# ============================================================================

def _illustrated_project(tmp_path):
    """A project with a cover, one ingested illustration, and a marked scene."""
    from illustration_helpers import make_jpeg, make_png
    from storyforge import illustrations as ill

    proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
    make_jpeg(os.path.join(proj, 'production', 'cover.jpg'), 600, 900)
    art = os.path.join(proj, ill.ILLUSTRATIONS_SUBDIR, 'lf-01.png')
    make_png(art, 40, 60)
    with open(ill.plan_path(proj), 'w') as f:
        f.write('|'.join(ill.PLAN_COLUMNS) + '\n')
        row = dict.fromkeys(ill.PLAN_COLUMNS, '')
        row.update(id='LF-01', scene_id='s1', placement='scene_open',
                   layout='full_page', status='ingested',
                   sha256=ill.sha256_of(art),
                   asset_file=ill.default_asset_rel('lf-01'))
        f.write('|'.join(row[c] for c in ill.PLAN_COLUMNS) + '\n')
    with open(os.path.join(proj, 'scenes', 's1.md'), 'w') as f:
        f.write('![[illus:LF-01]]\n\nThe prose for scene s1.\n')
    return proj


class TestCmdPublishAssets:
    def test_dry_run_uploads_nothing(self, tmp_path, capsys):
        """A dry run must not touch storage — and must not need credentials."""
        from unittest.mock import patch
        from storyforge import cmd_publish

        proj = _illustrated_project(tmp_path)
        with patch('storyforge.cmd_publish.detect_project_root', return_value=proj), \
             patch('storyforge.bookshelf.sync_assets') as sync, \
             patch('storyforge.bookshelf.publish') as pub, \
             patch('storyforge.bookshelf.check_env') as env:
            cmd_publish.main(['--dry-run', '--no-dashboard'])

        sync.assert_not_called()
        pub.assert_not_called()
        env.assert_not_called()
        out = capsys.readouterr().out
        assert 'Nothing uploaded' in out
        assert '2 declared (1 cover, 1 illustration)' in out

    def test_dry_run_reports_a_drifted_asset(self, tmp_path, capsys):
        from unittest.mock import patch
        from storyforge import cmd_publish
        from storyforge import illustrations as ill

        proj = _illustrated_project(tmp_path)
        art = os.path.join(proj, ill.ILLUSTRATIONS_SUBDIR, 'lf-01.png')
        with open(art, 'ab') as f:
            f.write(b'edited after ingest')

        with patch('storyforge.cmd_publish.detect_project_root', return_value=proj):
            cmd_publish.main(['--dry-run', '--no-dashboard'])

        out = capsys.readouterr().out
        assert 'has drifted' in out
        assert 'would block the publish' in out

    def test_assets_are_synced_before_the_manifest(self, tmp_path):
        """assets_missing_bytes fires before chapters are written, so bytes first."""
        from unittest.mock import patch
        from storyforge import cmd_publish

        proj = _illustrated_project(tmp_path)
        calls = []
        fake_env = {
            'BOOKSHELF_URL': 'https://bs.example.com',
            'BOOKSHELF_SUPABASE_URL': 'https://sb.example.com',
            'BOOKSHELF_SUPABASE_ANON_KEY': 'anon',
            'BOOKSHELF_EMAIL': 'a@b.c',
            'BOOKSHELF_PASSWORD': 'pw',
        }
        sync_result = {'declared': 2, 'objects': 2, 'uploaded': 2,
                       'unchanged': 0, 'bytes_uploaded': 1234}

        def record_sync(*args, **kwargs):
            calls.append('sync')
            return sync_result

        def record_publish(*args, **kwargs):
            calls.append('publish')
            return {'ok': True, 'book_id': 'id', 'slug': 'test-book',
                    'published': {'chapters': 1, 'scenes': 1, 'words': 7}}

        with patch('storyforge.cmd_publish.detect_project_root', return_value=proj), \
             patch('storyforge.bookshelf.check_env', return_value=fake_env), \
             patch('storyforge.bookshelf.authenticate', return_value='jwt'), \
             patch('storyforge.bookshelf.sync_assets', side_effect=record_sync) as sync, \
             patch('storyforge.bookshelf.publish', side_effect=record_publish):
            cmd_publish.main(['--no-dashboard'])

        assert calls == ['sync', 'publish']
        _url, _token, slug, declared, sources = sync.call_args.args
        assert slug == 'test-book'
        assert [a['role'] for a in declared] == ['cover', 'illustration']
        # Every declared digest resolves to a real file — that mapping is the
        # caller's job, not the transport's.
        assert all(os.path.isfile(sources[a['sha256']]) for a in declared)

    def test_a_failed_asset_sync_stops_before_publishing(self, tmp_path, capsys):
        from unittest.mock import patch
        from storyforge import cmd_publish

        proj = _illustrated_project(tmp_path)
        fake_env = {
            'BOOKSHELF_URL': 'https://bs.example.com',
            'BOOKSHELF_SUPABASE_URL': 'https://sb.example.com',
            'BOOKSHELF_SUPABASE_ANON_KEY': 'anon',
            'BOOKSHELF_EMAIL': 'a@b.c',
            'BOOKSHELF_PASSWORD': 'pw',
        }
        with patch('storyforge.cmd_publish.detect_project_root', return_value=proj), \
             patch('storyforge.bookshelf.check_env', return_value=fake_env), \
             patch('storyforge.bookshelf.authenticate', return_value='jwt'), \
             patch('storyforge.bookshelf.sync_assets',
                   side_effect=RuntimeError('storage refused')), \
             patch('storyforge.bookshelf.publish') as pub:
            with pytest.raises(SystemExit):
                cmd_publish.main(['--no-dashboard'])

        pub.assert_not_called()
        out = capsys.readouterr().out
        assert 'storage refused' in out
        assert 'live book is unchanged' in out

    def test_illustrations_without_a_cover_exit_nonzero(self, tmp_path, capsys):
        from unittest.mock import patch
        from storyforge import cmd_publish

        proj = _illustrated_project(tmp_path)
        os.remove(os.path.join(proj, 'production', 'cover.jpg'))

        with patch('storyforge.cmd_publish.detect_project_root', return_value=proj), \
             patch('storyforge.bookshelf.publish') as pub:
            with pytest.raises(SystemExit):
                cmd_publish.main(['--no-dashboard'])

        pub.assert_not_called()
        assert 'none with role "cover"' in capsys.readouterr().out

    def test_a_book_with_no_assets_skips_the_sync(self, tmp_path):
        """No cover, no art: nothing is declared, so bookshelf is told nothing."""
        from unittest.mock import patch
        from storyforge import cmd_publish

        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        fake_env = {
            'BOOKSHELF_URL': 'https://bs.example.com',
            'BOOKSHELF_SUPABASE_URL': 'https://sb.example.com',
            'BOOKSHELF_SUPABASE_ANON_KEY': 'anon',
            'BOOKSHELF_EMAIL': 'a@b.c',
            'BOOKSHELF_PASSWORD': 'pw',
        }
        with patch('storyforge.cmd_publish.detect_project_root', return_value=proj), \
             patch('storyforge.bookshelf.check_env', return_value=fake_env), \
             patch('storyforge.bookshelf.authenticate', return_value='jwt'), \
             patch('storyforge.bookshelf.sync_assets') as sync, \
             patch('storyforge.bookshelf.publish',
                   return_value={'ok': True, 'slug': 'test-book',
                                 'published': {}}):
            cmd_publish.main(['--no-dashboard'])

        sync.assert_not_called()

    def test_cover_flag_is_a_no_op_with_a_note(self, tmp_path, capsys):
        from unittest.mock import patch
        from storyforge import cmd_publish

        proj = _illustrated_project(tmp_path)
        with patch('storyforge.cmd_publish.detect_project_root', return_value=proj):
            cmd_publish.main(['--dry-run', '--no-dashboard', '--cover'])
        assert '--cover is a no-op' in capsys.readouterr().out

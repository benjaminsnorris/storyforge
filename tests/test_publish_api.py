"""Tests for API-compatible publish manifest generation and cmd_publish."""
import base64
import json
import os


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
        """The API manifest uses metadata/cover_base64 instead of cover_path/generated_at."""
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
    def test_includes_cover_base64(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])

        # Create a cover image
        production = tmp_path / 'production'
        production.mkdir(exist_ok=True)
        cover_data = b'\x89PNG fake cover data'
        (production / 'cover.png').write_bytes(cover_data)

        path = generate_publish_manifest(proj, include_cover=True)
        with open(path) as f:
            manifest = json.load(f)
        assert manifest['cover_base64'] == base64.b64encode(cover_data).decode('ascii')
        assert manifest['cover_extension'] == '.png'

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
        assert manifest['cover_base64'] == base64.b64encode(cover_data).decode('ascii')
        assert manifest['cover_extension'] == '.jpg'

    def test_no_cover_when_not_requested(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])

        production = tmp_path / 'production'
        production.mkdir(exist_ok=True)
        (production / 'cover.png').write_bytes(b'PNG data')

        path = generate_publish_manifest(proj, include_cover=False)
        with open(path) as f:
            manifest = json.load(f)
        assert 'cover_base64' not in manifest
        assert 'cover_extension' not in manifest

    def test_missing_cover_not_included(self, tmp_path):
        from storyforge.assembly import generate_publish_manifest
        proj = _make_project(tmp_path, ['s1'], [('Ch', ['s1'])])
        # No cover file exists
        path = generate_publish_manifest(proj, include_cover=True)
        with open(path) as f:
            manifest = json.load(f)
        assert 'cover_base64' not in manifest


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
        assert args.annotations is False
        assert args.dry_run is False

    def test_cover_flag(self):
        from storyforge.cmd_publish import parse_args
        args = parse_args(['--cover'])
        assert args.cover is True

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

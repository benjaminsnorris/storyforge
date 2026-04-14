"""Tests for storyforge annotations — reader annotation processing from Bookshelf.

Covers: parse_args (all flags and choices), main() orchestration with mocked
Bookshelf API and annotation processing, dry-run mode, authentication failure,
fetch failure, missing title, filtering by status/color/scene, exemplar
promotion, and display summary output.
"""

import os
import sys

import pytest

from storyforge.cmd_annotations import parse_args, main


# ============================================================================
# parse_args
# ============================================================================


class TestParseArgs:
    """Exhaustive tests for argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert args.status is None
        assert args.color is None
        assert args.scene is None
        assert not args.dry_run

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_status_new(self):
        args = parse_args(['--status', 'new'])
        assert args.status == 'new'

    def test_status_addressed(self):
        args = parse_args(['--status', 'addressed'])
        assert args.status == 'addressed'

    def test_status_skipped(self):
        args = parse_args(['--status', 'skipped'])
        assert args.status == 'skipped'

    def test_status_protected(self):
        args = parse_args(['--status', 'protected'])
        assert args.status == 'protected'

    def test_status_exemplar(self):
        args = parse_args(['--status', 'exemplar'])
        assert args.status == 'exemplar'

    def test_status_removed(self):
        args = parse_args(['--status', 'removed'])
        assert args.status == 'removed'

    def test_status_invalid(self):
        with pytest.raises(SystemExit):
            parse_args(['--status', 'invalid'])

    def test_color_pink(self):
        args = parse_args(['--color', 'pink'])
        assert args.color == 'pink'

    def test_color_orange(self):
        args = parse_args(['--color', 'orange'])
        assert args.color == 'orange'

    def test_color_blue(self):
        args = parse_args(['--color', 'blue'])
        assert args.color == 'blue'

    def test_color_green(self):
        args = parse_args(['--color', 'green'])
        assert args.color == 'green'

    def test_color_yellow(self):
        args = parse_args(['--color', 'yellow'])
        assert args.color == 'yellow'

    def test_color_invalid(self):
        with pytest.raises(SystemExit):
            parse_args(['--color', 'red'])

    def test_scene_filter(self):
        args = parse_args(['--scene', 'act1-sc01'])
        assert args.scene == 'act1-sc01'

    def test_combined_filters(self):
        args = parse_args(['--status', 'new', '--color', 'pink', '--scene', 'act1-sc01'])
        assert args.status == 'new'
        assert args.color == 'pink'
        assert args.scene == 'act1-sc01'

    def test_dry_run_with_filters(self):
        args = parse_args(['--dry-run', '--status', 'new', '--color', 'green'])
        assert args.dry_run
        assert args.status == 'new'
        assert args.color == 'green'


# ============================================================================
# Helpers for mocking Bookshelf / annotation functions
# ============================================================================


def _sample_api_annotations():
    """Return sample annotation data as would come from the Bookshelf API."""
    return [
        {
            'id': 'ann-001',
            'scene': {'slug': 'act1-sc01'},
            'chapter': {'number': 1},
            'user': {'display_name': 'Reader A'},
            'color': 'pink',
            'color_label': 'Needs Revision',
            'text': 'This sentence feels awkward and out of place.',
            'note': 'Consider rewording for clarity',
            'created_at': '2026-04-01T10:00:00Z',
        },
        {
            'id': 'ann-002',
            'scene': {'slug': 'act1-sc02'},
            'chapter': {'number': 1},
            'user': {'display_name': 'Reader B'},
            'color': 'green',
            'color_label': 'Strong Passage',
            'text': 'Beautiful imagery of the morning light filtering through the maps.',
            'note': 'Love the metaphor here',
            'created_at': '2026-04-01T11:00:00Z',
        },
        {
            'id': 'ann-003',
            'scene': {'slug': 'act1-sc01'},
            'chapter': {'number': 1},
            'user': {'display_name': 'Reader A'},
            'color': 'orange',
            'color_label': 'Cut / Reconsider',
            'text': 'This whole paragraph seems redundant.',
            'note': 'Already explained in the prior scene',
            'created_at': '2026-04-01T12:00:00Z',
        },
    ]


def _bookshelf_env():
    """Return a dict simulating Bookshelf environment variables."""
    return {
        'BOOKSHELF_URL': 'https://bookshelf.example.com',
        'BOOKSHELF_EMAIL': 'admin@example.com',
        'BOOKSHELF_PASSWORD': 'secret',
        'BOOKSHELF_SUPABASE_URL': 'https://supabase.example.com',
        'BOOKSHELF_SUPABASE_ANON_KEY': 'anon-key-123',
    }


def _setup_bookshelf_mocks(monkeypatch, api_annotations=None, auth_error=None,
                            fetch_error=None, existing_csv=None,
                            promoted=None):
    """Set up all Bookshelf and annotation mocks.

    Returns a dict of tracking lists for call inspection.
    """
    tracker = {
        'check_env': [],
        'authenticate': [],
        'get_annotations': [],
        'load_csv': [],
        'save_csv': [],
        'reconcile': [],
        'promote': [],
    }

    if api_annotations is None:
        api_annotations = _sample_api_annotations()

    if existing_csv is None:
        existing_csv = {}

    if promoted is None:
        promoted = []

    def mock_check_env():
        tracker['check_env'].append(1)
        return _bookshelf_env()

    def mock_authenticate(url, key, email, password):
        tracker['authenticate'].append(1)
        if auth_error:
            raise RuntimeError(auth_error)
        return 'jwt-token-xyz'

    def mock_get_annotations(url, token, slug):
        tracker['get_annotations'].append(slug)
        if fetch_error:
            raise RuntimeError(fetch_error)
        return {'annotations': api_annotations}

    def mock_load_csv(project_dir):
        tracker['load_csv'].append(1)
        return dict(existing_csv)

    def mock_save_csv(project_dir, annotations):
        tracker['save_csv'].append(annotations)
        return os.path.join(project_dir, 'working', 'annotations.csv')

    def mock_reconcile(existing, api_anns):
        tracker['reconcile'].append(1)
        # Build a simple reconciled result
        result = dict(existing)
        for ann in api_anns:
            ann_id = ann.get('id', '')
            if ann_id and ann_id not in result:
                color = ann.get('color', 'yellow')
                from storyforge.annotations import COLOR_LABELS, COLOR_TO_FIX_LOCATION
                result[ann_id] = {
                    'id': ann_id,
                    'scene_id': ann.get('scene', {}).get('slug', ''),
                    'chapter': str(ann.get('chapter', {}).get('number', '')),
                    'color': color,
                    'color_label': ann.get('color_label', COLOR_LABELS.get(color, color)),
                    'text': ann.get('text', ''),
                    'note': ann.get('note', ''),
                    'reader': ann.get('user', {}).get('display_name', 'Anonymous'),
                    'created_at': ann.get('created_at', ''),
                    'status': 'new',
                    'fix_location': COLOR_TO_FIX_LOCATION.get(color, 'craft'),
                    'fetched_at': '2026-04-14T00:00:00Z',
                }
        summary = {
            'new': len(api_anns),
            'existing': 0,
            'removed': 0,
            'total': len(result),
        }
        return result, summary

    def mock_promote(project_dir, annotations, coaching_level='full'):
        tracker['promote'].append(1)
        return list(promoted)

    monkeypatch.setattr('storyforge.bookshelf.check_env', mock_check_env)
    monkeypatch.setattr('storyforge.bookshelf.authenticate', mock_authenticate)
    monkeypatch.setattr('storyforge.bookshelf.get_annotations', mock_get_annotations)
    monkeypatch.setattr('storyforge.annotations.load_annotations_csv', mock_load_csv)
    monkeypatch.setattr('storyforge.annotations.save_annotations_csv', mock_save_csv)
    monkeypatch.setattr('storyforge.annotations.reconcile', mock_reconcile)
    monkeypatch.setattr('storyforge.annotations.promote_exemplars', mock_promote)

    return tracker


# ============================================================================
# main — missing project title
# ============================================================================


class TestMainMissingTitle:
    """Test main() when project title is missing."""

    def test_exits_with_error(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: '')
        _setup_bookshelf_mocks(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_error_message_logged(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: '')
        _setup_bookshelf_mocks(monkeypatch)
        with pytest.raises(SystemExit):
            main([])
        output = capsys.readouterr().out
        assert 'title' in output.lower() or 'ERROR' in output


# ============================================================================
# main — authentication failure
# ============================================================================


class TestMainAuthFailure:
    """Test main() when authentication with Bookshelf fails."""

    def test_exits_on_auth_error(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        _setup_bookshelf_mocks(monkeypatch, auth_error='Invalid credentials')
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_auth_error_message(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        _setup_bookshelf_mocks(monkeypatch, auth_error='Invalid credentials')
        with pytest.raises(SystemExit):
            main([])
        output = capsys.readouterr().out
        assert 'Authentication failed' in output or 'Invalid credentials' in output


# ============================================================================
# main — fetch failure
# ============================================================================


class TestMainFetchFailure:
    """Test main() when fetching annotations from Bookshelf fails."""

    def test_exits_on_fetch_error(self, project_dir, monkeypatch):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        _setup_bookshelf_mocks(monkeypatch, fetch_error='Network timeout')
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1

    def test_fetch_error_message(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        _setup_bookshelf_mocks(monkeypatch, fetch_error='Network timeout')
        with pytest.raises(SystemExit):
            main([])
        output = capsys.readouterr().out
        assert 'Failed to fetch' in output or 'Network timeout' in output


# ============================================================================
# main — successful run
# ============================================================================


class TestMainSuccess:
    """Test main() successful annotation fetching and processing."""

    def _setup(self, monkeypatch, project_dir, **kwargs):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        monkeypatch.setattr('storyforge.cmd_annotations.get_coaching_level',
                            lambda pd: 'full')
        return _setup_bookshelf_mocks(monkeypatch, **kwargs)

    def test_reconciles_annotations(self, project_dir, monkeypatch):
        tracker = self._setup(monkeypatch, project_dir)
        main([])
        assert len(tracker['reconcile']) == 1

    def test_saves_annotations_csv(self, project_dir, monkeypatch):
        tracker = self._setup(monkeypatch, project_dir)
        main([])
        assert len(tracker['save_csv']) == 1

    def test_slug_derived_from_title(self, project_dir, monkeypatch):
        tracker = self._setup(monkeypatch, project_dir)
        main([])
        # Slug should be derived from "The Cartographer's Silence"
        assert len(tracker['get_annotations']) == 1
        slug = tracker['get_annotations'][0]
        assert 'cartographer' in slug
        assert slug == 'the-cartographer-s-silence'

    def test_promotes_exemplars(self, project_dir, monkeypatch):
        tracker = self._setup(monkeypatch, project_dir)
        main([])
        assert len(tracker['promote']) == 1

    def test_promoted_annotations_marked(self, project_dir, monkeypatch):
        tracker = self._setup(monkeypatch, project_dir, promoted=['ann-002'])
        main([])
        # The saved annotations should have ann-002 marked as exemplar
        saved = tracker['save_csv'][0]
        assert saved['ann-002']['status'] == 'exemplar'
        assert saved['ann-002']['fix_location'] == 'exemplar'

    def test_summary_logged(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        main([])
        output = capsys.readouterr().out
        assert 'Reconciliation' in output
        assert 'new' in output

    def test_api_annotation_count_logged(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        main([])
        output = capsys.readouterr().out
        assert '3 annotation(s)' in output


# ============================================================================
# main — dry run
# ============================================================================


class TestMainDryRun:
    """Test main() with --dry-run flag."""

    def _setup(self, monkeypatch, project_dir, **kwargs):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        monkeypatch.setattr('storyforge.cmd_annotations.get_coaching_level',
                            lambda pd: 'full')
        return _setup_bookshelf_mocks(monkeypatch, **kwargs)

    def test_does_not_save_csv(self, project_dir, monkeypatch):
        tracker = self._setup(monkeypatch, project_dir)
        main(['--dry-run'])
        assert len(tracker['save_csv']) == 0

    def test_dry_run_message(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        main(['--dry-run'])
        output = capsys.readouterr().out
        assert 'Dry run' in output

    def test_still_fetches_annotations(self, project_dir, monkeypatch):
        tracker = self._setup(monkeypatch, project_dir)
        main(['--dry-run'])
        assert len(tracker['get_annotations']) == 1


# ============================================================================
# main — display filtering
# ============================================================================


class TestMainDisplayFilters:
    """Test main() display filtering by status, color, and scene."""

    def _setup(self, monkeypatch, project_dir, **kwargs):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        monkeypatch.setattr('storyforge.cmd_annotations.get_coaching_level',
                            lambda pd: 'full')
        return _setup_bookshelf_mocks(monkeypatch, **kwargs)

    def test_filter_by_color(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        main(['--color', 'pink'])
        output = capsys.readouterr().out
        # Only pink annotations should appear
        assert 'act1-sc01' in output
        # Green annotation should not appear in filtered output
        # (green annotation is for act1-sc02)
        lines = output.strip().split('\n')
        annotation_lines = [l for l in lines if '[new]' in l]
        for line in annotation_lines:
            assert 'Strong Passage' not in line

    def test_filter_by_scene(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        main(['--scene', 'act1-sc02'])
        output = capsys.readouterr().out
        annotation_lines = [l for l in output.split('\n') if '[new]' in l]
        for line in annotation_lines:
            assert 'act1-sc02' in line

    def test_filter_by_status(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        # All mocked annotations are 'new', filtering for 'addressed' should yield none
        main(['--status', 'addressed'])
        output = capsys.readouterr().out
        annotation_lines = [l for l in output.split('\n') if '[addressed]' in l]
        assert len(annotation_lines) == 0

    def test_annotation_display_includes_text(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        main([])
        output = capsys.readouterr().out
        # Should display truncated text from annotations
        assert 'awkward' in output or 'Beautiful' in output or 'redundant' in output


# ============================================================================
# main — unaddressed summary
# ============================================================================


class TestMainUnaddressedSummary:
    """Test main() unaddressed annotation summary output."""

    def _setup(self, monkeypatch, project_dir, **kwargs):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        monkeypatch.setattr('storyforge.cmd_annotations.get_coaching_level',
                            lambda pd: 'full')
        return _setup_bookshelf_mocks(monkeypatch, **kwargs)

    def test_craft_revisions_counted(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        main([])
        output = capsys.readouterr().out
        # Pink annotations route to craft
        assert 'craft revision' in output

    def test_structural_revisions_counted(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        main([])
        output = capsys.readouterr().out
        # Orange annotations route to structural
        assert 'structural revision' in output

    def test_protection_passages_counted(self, project_dir, monkeypatch, capsys):
        self._setup(monkeypatch, project_dir)
        main([])
        output = capsys.readouterr().out
        # Green annotations route to protection
        assert 'protect' in output.lower()


# ============================================================================
# main — empty annotations
# ============================================================================


class TestMainEmptyAnnotations:
    """Test main() when API returns no annotations."""

    def test_zero_annotations(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        monkeypatch.setattr('storyforge.cmd_annotations.get_coaching_level',
                            lambda pd: 'full')
        _setup_bookshelf_mocks(monkeypatch, api_annotations=[])
        main([])
        output = capsys.readouterr().out
        assert '0 annotation(s)' in output

    def test_no_unaddressed_summary_when_empty(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr('storyforge.cmd_annotations.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_annotations.read_yaml_field',
                            lambda field, pd: "The Cartographer's Silence" if 'title' in field else '')
        monkeypatch.setattr('storyforge.cmd_annotations.get_coaching_level',
                            lambda pd: 'full')
        _setup_bookshelf_mocks(monkeypatch, api_annotations=[])
        main([])
        output = capsys.readouterr().out
        assert 'Unaddressed' not in output

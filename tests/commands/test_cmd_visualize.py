"""Tests for cmd_visualize command module."""

import json
import os
import pytest
from storyforge.cmd_visualize import (
    parse_args, _build_data_injection, _inject_data,
)


class TestParseArgs:
    """Argument parsing for storyforge visualize."""

    def test_defaults(self):
        args = parse_args([])
        assert not args.open
        assert not args.dry_run

    def test_open_flag(self):
        args = parse_args(['--open'])
        assert args.open

    def test_dry_run(self):
        args = parse_args(['--dry-run'])
        assert args.dry_run

    def test_both_flags(self):
        args = parse_args(['--open', '--dry-run'])
        assert args.open
        assert args.dry_run


class TestBuildDataInjection:
    """_build_data_injection produces valid JavaScript."""

    def test_contains_const_declaration(self):
        data_json = json.dumps({'scenes': [], 'intents': [], 'project': {}})
        result = _build_data_injection(data_json)
        assert 'const _DATA' in result
        assert 'const SCENES' in result
        assert 'const INTENTS' in result

    def test_contains_all_expected_constants(self):
        data_json = json.dumps({
            'scenes': [], 'intents': [], 'characters': [],
            'motif_taxonomy': [], 'locations': [], 'scores': [],
            'weights': [], 'narrative_scores': [], 'project': {},
            'scene_rationales': [], 'act_scores': [],
            'act_rationales': [], 'character_scores': [],
            'character_rationales': [], 'genre_scores': [],
            'genre_rationales': [], 'narrative_rationales': [],
        })
        result = _build_data_injection(data_json)
        for name in ['SCENES', 'INTENTS', 'CHARACTERS', 'MOTIF_TAXONOMY',
                      'LOCATIONS', 'SCORES', 'WEIGHTS', 'NARRATIVE_SCORES',
                      'PROJECT', 'SCENE_RATIONALES', 'ACT_SCORES',
                      'BRIEFS', 'FIDELITY_SCORES', 'STRUCTURAL_SCORES',
                      'BRIEF_QUALITY']:
            assert f'const {name}' in result

    def test_optional_arrays_default_empty(self):
        data_json = json.dumps({'scenes': []})
        result = _build_data_injection(data_json)
        assert 'VALUES = _DATA.values || []' in result
        assert 'MICE_THREADS = _DATA.mice_threads || []' in result
        assert 'KNOWLEDGE = _DATA.knowledge || []' in result

    def test_briefs_merge_logic_present(self):
        data_json = json.dumps({'scenes': []})
        result = _build_data_injection(data_json)
        assert 'if (BRIEFS.length)' in result
        assert 'briefsById' in result


class TestInjectData:
    """_inject_data replaces the marker in the template."""

    def test_replaces_injection_point(self):
        template = '<html><script>// DATA_INJECTION_POINT\n</script></html>'
        data_json = json.dumps({'scenes': []})
        result = _inject_data(template, data_json)
        assert '// DATA_INJECTION_POINT' not in result
        assert 'const _DATA' in result

    def test_preserves_surrounding_html(self):
        template = '<html><head></head><body><script>// DATA_INJECTION_POINT\n</script></body></html>'
        data_json = json.dumps({'scenes': []})
        result = _inject_data(template, data_json)
        assert '<html>' in result
        assert '</body></html>' in result

    def test_fallback_data_injection_comment(self):
        template = (
            '<script>\n'
            '// ============================================================================\n'
            '// DATA INJECTION\n'
            '// rest of code\n'
            '</script>'
        )
        data_json = json.dumps({'scenes': []})
        result = _inject_data(template, data_json)
        assert 'const _DATA' in result

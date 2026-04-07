"""Tests for physical state tracking (migrated from test-physical-state.sh)."""

import os
import shutil


class TestEnumValidation:
    def test_valid_categories(self):
        from storyforge.schema import _check_enum, VALID_PHYSICAL_STATE_CATEGORIES
        for v in ['injury', 'equipment', 'ability', 'appearance', 'fatigue']:
            assert _check_enum(v, VALID_PHYSICAL_STATE_CATEGORIES) is True

    def test_invalid_categories(self):
        from storyforge.schema import _check_enum, VALID_PHYSICAL_STATE_CATEGORIES
        assert _check_enum('emotional', VALID_PHYSICAL_STATE_CATEGORIES) is False
        assert _check_enum('weather', VALID_PHYSICAL_STATE_CATEGORIES) is False


class TestSchemaDefinition:
    def test_physical_state_columns_defined(self):
        from storyforge.schema import COLUMN_SCHEMA
        psi = COLUMN_SCHEMA.get('physical_state_in')
        pso = COLUMN_SCHEMA.get('physical_state_out')
        assert psi is not None
        assert pso is not None
        assert psi['type'] == 'registry'
        assert psi['registry'] == 'physical-states.csv'
        assert psi['array'] is True
        assert psi['file'] == 'scene-briefs.csv'

    def test_registry_columns_defined(self):
        from storyforge.schema import COLUMN_SCHEMA
        cat = COLUMN_SCHEMA.get('physical_states_category')
        ag = COLUMN_SCHEMA.get('physical_states_action_gating')
        assert cat is not None and cat['type'] == 'enum'
        assert ag is not None and ag['type'] == 'boolean'


class TestElaborateIntegration:
    def test_briefs_cols_include_physical_state(self):
        from storyforge.elaborate import _BRIEFS_COLS
        assert 'physical_state_in' in _BRIEFS_COLS
        assert 'physical_state_out' in _BRIEFS_COLS


class TestValidation:
    def test_consistent_fixture(self, fixture_dir):
        from storyforge.elaborate import validate_structure
        result = validate_structure(os.path.join(fixture_dir, 'reference'))
        phys_checks = [c for c in result['checks'] if c['category'] == 'physical_state']
        if phys_checks:
            assert all(c['passed'] for c in phys_checks)

    def test_unknown_state_flagged(self, fixture_dir, tmp_path):
        from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP, validate_structure
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        briefs_path = os.path.join(ref, 'scene-briefs.csv')
        rows = _read_csv(briefs_path)
        for r in rows:
            if r['id'] == 'act1-sc01':
                r['physical_state_in'] = 'nonexistent-state'
        _write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

        result = validate_structure(ref)
        phys_fails = [c for c in result['checks']
                      if c['category'] == 'physical_state' and not c['passed']]
        assert any('nonexistent-state' in c.get('message', '') for c in phys_fails)

    def test_state_disappearance(self, fixture_dir, tmp_path):
        from storyforge.elaborate import _read_csv, _write_csv, _FILE_MAP, validate_structure
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        briefs_path = os.path.join(ref, 'scene-briefs.csv')
        rows = _read_csv(briefs_path)
        for r in rows:
            if r['id'] == 'act2-sc03':
                r['physical_state_in'] = 'archive-key-dorren;exhaustion-tessa'
                r['physical_state_out'] = 'archive-key-dorren'
        _write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

        states_path = os.path.join(ref, 'physical-states.csv')
        states_rows = _read_csv(states_path)
        for r in states_rows:
            if r['id'] == 'exhaustion-tessa':
                r['resolves'] = 'never'
        _write_csv(states_path, states_rows,
                   ['id', 'character', 'description', 'category', 'acquired', 'resolves', 'action_gating'])

        result = validate_structure(ref)
        phys_fails = [c for c in result['checks']
                      if c['category'] == 'physical_state' and not c['passed']]
        assert any(c.get('check') == 'state-disappearance' and 'exhaustion-tessa' in c.get('message', '')
                   for c in phys_fails)


class TestGranularity:
    def test_clean_fixture_passes(self, fixture_dir):
        from storyforge.schema import validate_physical_state_granularity
        result = validate_physical_state_granularity(os.path.join(fixture_dir, 'reference'))
        assert result['total_states'] == 4
        assert len(result['warnings']) == 0

    def test_long_description_flagged(self, fixture_dir, tmp_path):
        from storyforge.schema import validate_physical_state_granularity
        from storyforge.elaborate import _read_csv, _write_csv

        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        path = os.path.join(ref, 'physical-states.csv')
        rows = _read_csv(path)
        rows.append({
            'id': 'verbose-state', 'character': 'Dorren Hayle',
            'description': 'a really quite extraordinarily long and overly detailed description of a minor bruise on the left side of the upper right forearm near the elbow joint area',
            'category': 'injury', 'acquired': 'act1-sc01',
            'resolves': 'never', 'action_gating': 'false',
        })
        _write_csv(path, rows, ['id', 'character', 'description', 'category',
                                'acquired', 'resolves', 'action_gating'])

        result = validate_physical_state_granularity(ref)
        assert any(w['type'] == 'long_description' for w in result['warnings'])


class TestStructuralScoring:
    def test_valid_score_on_fixtures(self, fixture_dir):
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.structural import score_physical_state_chain

        scenes = _read_csv_as_map(os.path.join(fixture_dir, 'reference', 'scenes.csv'))
        briefs = _read_csv_as_map(os.path.join(fixture_dir, 'reference', 'scene-briefs.csv'))
        result = score_physical_state_chain(scenes, briefs, os.path.join(fixture_dir, 'reference'))
        assert 0 <= result['score'] <= 1
        assert isinstance(result['findings'], list)

    def test_empty_returns_zero(self):
        from storyforge.structural import score_physical_state_chain
        scenes = {'s1': {'id': 's1', 'seq': '1'}, 's2': {'id': 's2', 'seq': '2'}}
        briefs = {'s1': {'id': 's1'}, 's2': {'id': 's2'}}
        result = score_physical_state_chain(scenes, briefs, '/nonexistent')
        assert result['score'] == 0.0

    def test_included_in_structural_score(self, fixture_dir):
        from storyforge.structural import structural_score
        result = structural_score(os.path.join(fixture_dir, 'reference'))
        dims = {d['name'] for d in result['dimensions']}
        assert 'physical_state' in dims

    def test_enrichment_fields(self):
        from storyforge.structural import ENRICHMENT_FIELDS
        assert 'physical_state_in' in ENRICHMENT_FIELDS
        assert 'physical_state_out' in ENRICHMENT_FIELDS


class TestDraftingPrompts:
    def test_physical_state_in_prompt(self, fixture_dir, plugin_dir):
        from storyforge.prompts import build_scene_prompt_from_briefs
        prompt = build_scene_prompt_from_briefs('act2-sc03', fixture_dir, plugin_dir)
        assert 'Active Physical States' in prompt

    def test_no_state_no_section(self, fixture_dir, plugin_dir):
        from storyforge.prompts import build_scene_prompt_from_briefs
        prompt = build_scene_prompt_from_briefs('act1-sc01', fixture_dir, plugin_dir)
        assert 'Active Physical States' not in prompt


class TestExtraction:
    def test_build_physical_state_prompt(self):
        from storyforge.extract import build_physical_state_prompt
        prompt = build_physical_state_prompt(
            scene_id='act1-sc01',
            scene_text='Dorren reviewed the maps carefully.',
            skeleton={'pov': 'Dorren Hayle', 'on_stage': 'Dorren Hayle;Tessa Merrin'},
            prior_states={},
            prior_scene_summaries=[],
        )
        assert 'PHYSICAL_STATE_IN' in prompt
        assert 'injury' in prompt and 'equipment' in prompt

    def test_parse_physical_state_response(self):
        from storyforge.extract import parse_physical_state_response
        response = (
            'PHYSICAL_STATE_IN: archive-key-dorren\n'
            'PHYSICAL_STATE_OUT: archive-key-dorren;sprained-ankle-tessa\n'
            'NEW_STATES: sprained-ankle-tessa|Tessa Merrin|right ankle sprained|injury|true\n'
            'RESOLVED_STATES: '
        )
        result = parse_physical_state_response(response, 'act2-sc02')
        assert result['id'] == 'act2-sc02'
        assert result.get('physical_state_in') == 'archive-key-dorren'
        assert 'sprained-ankle-tessa' in result.get('physical_state_out', '')
        assert len(result.get('_new_states', [])) == 1


class TestCleanup:
    def test_normalizes_physical_state_wording(self, fixture_dir, tmp_path):
        from storyforge.extract import cleanup_physical_states
        from storyforge.elaborate import _read_csv, _write_csv, _read_csv_as_map, _FILE_MAP

        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)

        briefs_path = os.path.join(ref, 'scene-briefs.csv')
        rows = _read_csv(briefs_path)
        for r in rows:
            if r['id'] == 'act2-sc03':
                r['physical_state_in'] = 'archive-key-doren;exhaustion-tessa'
        _write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])

        fixes = cleanup_physical_states(ref)
        assert len(fixes) == 1

        briefs = _read_csv_as_map(briefs_path)
        assert 'archive-key-dorren' in briefs['act2-sc03'].get('physical_state_in', '')

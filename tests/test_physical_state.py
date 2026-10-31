"""Tests for physical state tracking (migrated from test-physical-state.sh)."""

import os
import shutil

from storyforge import ledger


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
        assert psi['registry'] == 'commitments.csv'
        assert psi['ledger_type'] == 'physical'
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

        states_rows = ledger.read_view(ref, 'physical')
        for r in states_rows:
            if r['id'] == 'exhaustion-tessa':
                r['resolves'] = 'never'
        ledger.write_view(ref, 'physical', states_rows, origin='author',
                          introduced_by='author')

        result = validate_structure(ref)
        phys_fails = [c for c in result['checks']
                      if c['category'] == 'physical_state' and not c['passed']]
        assert any(c.get('check') == 'state-disappearance' and 'exhaustion-tessa' in c.get('message', '')
                   for c in phys_fails)


    def test_a_recurring_state_ending_again_is_not_a_disappearance(self, fixture_dir, tmp_path):
        """F-110 (A Christmas Carol): Scrooge falls asleep again after the
        registry's resolving scene, and waking a second time was flagged:
        the registry can name only one resolving scene."""
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

        states_rows = ledger.read_view(ref, 'physical')
        for r in states_rows:
            if r['id'] == 'exhaustion-tessa':
                r['resolves'] = 'act1-sc02'   # ended once, earlier
        ledger.write_view(ref, 'physical', states_rows, origin='author',
                          introduced_by='author')

        result = validate_structure(ref)
        assert not any(c.get('check') == 'state-disappearance' and 'exhaustion-tessa' in c.get('message', '')
                       for c in result['checks'] if not c['passed'])

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

        rows = ledger.read_view(ref, 'physical')
        rows.append({
            'id': 'verbose-state', 'character': 'Dorren Hayle',
            'description': 'a really quite extraordinarily long and overly detailed description of a minor bruise on the left side of the upper right forearm near the elbow joint area',
            'category': 'injury', 'acquired': 'act1-sc01',
            'resolves': 'never', 'action_gating': 'false',
        })
        ledger.write_view(ref, 'physical', rows, origin='author', introduced_by='author')

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

    def test_states_out_are_a_must_show_checklist(self, fixture_dir, plugin_dir):
        from storyforge.prompts import build_scene_prompt_from_briefs
        prompt = build_scene_prompt_from_briefs('act1-sc02', fixture_dir, plugin_dir)
        task = prompt[prompt.index('## Task'):]
        assert 'Physical states checklist' in task
        checklist = task[task.index('Physical states checklist'):].split('**Prose rules')[0]
        assert checklist.count('- [ ]') == 2
        assert 'archive-key-dorren' not in checklist     # its description, not its id

    def test_a_state_in_words_is_listed_as_written(self, project_dir, plugin_dir):
        from storyforge.prompts import build_scene_prompt_from_briefs
        from storyforge.elaborate import update_scene
        update_scene('act1-sc02', os.path.join(project_dir, 'reference'),
                     {'physical_state_out': 'no sleep 36h'})
        prompt = build_scene_prompt_from_briefs('act1-sc02', project_dir, plugin_dir)
        assert '  - [ ] no sleep 36h' in prompt[prompt.index('## Task'):]

    def _checklist(self, project_dir, plugin_dir, coaching='full'):
        from storyforge.prompts import build_scene_prompt_from_briefs
        prompt = build_scene_prompt_from_briefs('act1-sc02', project_dir, plugin_dir,
                                                coaching_level=coaching)
        if 'Physical states checklist' not in prompt:
            return None
        return prompt[prompt.index('Physical states checklist'):].split('**Prose rules')[0]

    def _states_out(self, project_dir, value):
        from storyforge.elaborate import update_scene
        update_scene('act1-sc02', os.path.join(project_dir, 'reference'),
                     {'physical_state_out': value})

    def test_a_state_is_shown_by_character_name_and_description(self, project_dir, plugin_dir):
        checklist = self._checklist(project_dir, plugin_dir)
        assert 'Dorren Hayle: holds the restricted archive key' in checklist

    def test_an_id_in_another_case_still_names_the_state(self, project_dir, plugin_dir):
        self._states_out(project_dir, 'Archive-Key-Dorren')
        assert 'holds the restricted archive key' in self._checklist(project_dir, plugin_dir)

    def test_a_state_that_is_not_binding_is_left_out_with_a_warning(
            self, project_dir, plugin_dir, capsys):
        path = os.path.join(project_dir, 'reference', 'commitments.csv')
        with open(path) as f:
            text = f.read()
        with open(path, 'w') as f:
            f.write(text.replace('|migrated|binding|state|||||migration|fatigue|',
                                 '|migrated|rejected|state|||||migration|fatigue|'))
        checklist = self._checklist(project_dir, plugin_dir)
        assert 'exhausted' not in checklist and checklist.count('- [ ]') == 1
        assert 'exhaustion-tessa is rejected' in capsys.readouterr().out

    def test_only_full_coaching_gets_the_checklist(self, project_dir, plugin_dir):
        assert self._checklist(project_dir, plugin_dir, 'coach') is None
        assert self._checklist(project_dir, plugin_dir, 'strict') is None

    def test_no_states_out_no_checklist(self, fixture_dir, plugin_dir):
        from storyforge.prompts import build_scene_prompt_from_briefs
        prompt = build_scene_prompt_from_briefs('act1-sc01', fixture_dir, plugin_dir)
        assert 'Physical states checklist' not in prompt


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
        for field in ('physical_state_in', 'physical_state_out', 'new_states',
                      'resolved_states'):
            assert f'- {field}:' in prompt
        assert 'PHYSICAL_STATE_IN' not in prompt
        assert 'injury' in prompt and 'equipment' in prompt

    def test_parse_physical_state_response(self):
        import json
        from storyforge.extract import parse_physical_state_response
        response = json.dumps({
            'physical_state_in': ['archive-key-dorren'],
            'physical_state_out': ['archive-key-dorren', 'sprained-ankle-tessa'],
            'new_states': [{'id': 'sprained-ankle-tessa', 'character': 'Tessa Merrin',
                            'description': 'right ankle sprained', 'category': 'injury',
                            'action_gating': True}],
            'resolved_states': [],
        })
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

"""Tests for Python core modules (migrated from test-python.sh)."""

import json
import os
import tempfile
import shutil


class TestParsing:
    def test_extract_scenes_from_response(self, tmp_path):
        from storyforge.parsing import extract_scenes_from_response

        response_text = (
            'Here is the revision.\n\n'
            '=== SCENE: test-scene-1 ===\nFirst scene content.\nSecond line.\n'
            '=== END SCENE: test-scene-1 ===\n\n'
            '=== SCENE: test-scene-2 ===\nAnother scene.\n'
            '=== END SCENE: test-scene-2 ===\n\nSummary text here.'
        )

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(response_text, scenes_dir)

        assert os.path.isfile(os.path.join(scenes_dir, 'test-scene-1.md'))
        assert os.path.isfile(os.path.join(scenes_dir, 'test-scene-2.md'))

        with open(os.path.join(scenes_dir, 'test-scene-1.md')) as f:
            content = f.read()
        assert 'First scene content' in content
        assert '=== SCENE:' not in content

    def test_skip_parenthetical_entries(self, tmp_path):
        from storyforge.parsing import extract_scenes_from_response

        response_text = (
            '=== SCENE: my-scene ===\nOriginal.\n=== END SCENE: my-scene ===\n\n'
            '=== SCENE: my-scene (revised note) ===\nShould be skipped.\n'
            '=== END SCENE: my-scene (revised note) ==='
        )

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(response_text, scenes_dir)

        assert not os.path.isfile(os.path.join(scenes_dir, 'my-scene (revised note).md'))

    def test_extract_single_scene(self, tmp_path):
        from storyforge.parsing import extract_single_scene

        response_text = (
            'Some analysis.\n\n=== SCENE: drafted-scene ===\n'
            'The prose goes here.\nMore prose.\n'
            '=== END SCENE: drafted-scene ===\n\nNotes about the scene.'
        )

        content = extract_single_scene(response_text)
        assert content is not None
        assert 'The prose goes here' in content
        assert '=== SCENE:' not in content
        assert 'Notes about' not in content


class TestApi:
    def test_extract_text_from_file(self, tmp_path):
        from storyforge.api import extract_text_from_file

        response_file = str(tmp_path / 'api-response.json')
        with open(response_file, 'w') as f:
            json.dump({
                'content': [{'type': 'text', 'text': 'Hello world'}],
                'usage': {'input_tokens': 10, 'output_tokens': 5}
            }, f)

        result = extract_text_from_file(response_file)
        assert result == 'Hello world'

    def test_log_usage(self, tmp_path):
        from storyforge.api import log_operation, calculate_cost_from_usage

        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working', 'costs'))

        usage = {'input_tokens': 1000, 'output_tokens': 500,
                 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        cost = calculate_cost_from_usage(usage, 'claude-sonnet-4-6')
        log_operation(
            project_dir=project_dir,
            operation='test-op',
            model='claude-sonnet-4-6',
            input_tokens=1000,
            output_tokens=500,
            cost=cost,
            target='test-target',
        )

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        assert os.path.isfile(ledger)

        with open(ledger) as f:
            lines = f.readlines()
        assert len(lines) == 2  # header + 1 data row
        assert 'test-op' in lines[-1]
        assert '1000' in lines[-1]


class TestPrompts:
    def test_read_csv_field(self, fixture_dir):
        from storyforge.prompts import read_csv_field
        result = read_csv_field(
            os.path.join(fixture_dir, 'reference', 'scenes.csv'),
            'act1-sc01', 'title'
        )
        assert result == 'The Finest Cartographer'

    def test_get_scene_metadata(self, fixture_dir):
        from storyforge.prompts import get_scene_metadata
        result = get_scene_metadata('act1-sc01', fixture_dir)
        assert 'title: The Finest Cartographer' in result
        assert 'pov:' in result

    def test_get_previous_scene(self, fixture_dir):
        from storyforge.prompts import get_previous_scene
        result = get_previous_scene('act1-sc02', fixture_dir)
        assert result == 'act1-sc01'

    def test_list_reference_files(self, fixture_dir):
        from storyforge.prompts import list_reference_files
        result = list_reference_files(fixture_dir)
        # Returns a list of paths
        joined = '\n'.join(result) if isinstance(result, list) else str(result)
        assert 'reference/' in joined or 'reference' in joined


class TestRevision:
    def test_resolve_scope_full(self, fixture_dir):
        from storyforge.revision import resolve_scope
        result = resolve_scope('full', fixture_dir)
        # Returns a list of paths
        joined = ' '.join(result) if isinstance(result, list) else str(result)
        assert 'act1-sc01' in joined
        assert 'act2-sc01' in joined

    def test_resolve_scope_csv(self, fixture_dir):
        from storyforge.revision import resolve_scope
        result = resolve_scope('act1-sc01,act1-sc02', fixture_dir)
        joined = ' '.join(result) if isinstance(result, list) else str(result)
        assert 'act1-sc01' in joined
        assert 'act1-sc02' in joined

    def test_resolve_scope_new_prefix(self, fixture_dir):
        from storyforge.revision import resolve_scope
        result = resolve_scope('NEW:the-rupture,act1-sc01', fixture_dir)
        joined = ' '.join(result) if isinstance(result, list) else str(result)
        assert 'act1-sc01' in joined
        assert 'NEW:the-rupture' in joined

    def test_build_revision_prompt_includes_intent_protection(self, fixture_dir):
        from storyforge.revision import build_revision_prompt
        prompt = build_revision_prompt(
            pass_name='prose-tightening',
            purpose='Tighten prose and cut filler.',
            scope='act1-sc01',
            project_dir=fixture_dir,
            api_mode=True,
        )
        assert 'Intent-Beat Protection' in prompt
        assert 'act1-sc01' in prompt
        # Should include brief fields for the scene
        assert 'key_actions' in prompt or 'turning_point' in prompt

    def test_build_revision_prompt_intent_has_turning_point(self, fixture_dir):
        from storyforge.revision import build_revision_prompt
        prompt = build_revision_prompt(
            pass_name='prose-tightening',
            purpose='Tighten prose.',
            scope='act1-sc01',
            project_dir=fixture_dir,
            api_mode=True,
        )
        # act1-sc01 has turning_point='revelation' in the fixture
        assert 'turning_point' in prompt
        assert 'revelation' in prompt

    def test_build_revision_prompt_intent_beat_verification_in_summary(self, fixture_dir):
        from storyforge.revision import build_revision_prompt
        prompt = build_revision_prompt(
            pass_name='prose-tightening',
            purpose='Tighten prose.',
            scope='act1-sc01',
            project_dir=fixture_dir,
            api_mode=True,
        )
        assert 'Intent-beat verification' in prompt

    def test_build_revision_prompt_intent_beat_verification_non_api(self, fixture_dir):
        from storyforge.revision import build_revision_prompt
        prompt = build_revision_prompt(
            pass_name='prose-tightening',
            purpose='Tighten prose.',
            scope='act1-sc01',
            project_dir=fixture_dir,
            api_mode=False,
        )
        assert 'Intent-beat verification' in prompt

    def test_build_revision_prompt_no_intent_section_without_csv(self, tmp_path):
        """When no intent/briefs CSVs exist, no intent section is added."""
        import os
        from storyforge.revision import build_revision_prompt
        # Create minimal project structure
        scenes_dir = tmp_path / 'scenes'
        scenes_dir.mkdir()
        (scenes_dir / 'test-scene.md').write_text('Some prose.')
        ref_dir = tmp_path / 'reference'
        ref_dir.mkdir()
        (ref_dir / 'scenes.csv').write_text(
            'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
            'test-scene|1|Test|1|Someone|Here|1|morning|30|scene|draft|10|1000\n'
        )
        (tmp_path / 'storyforge.yaml').write_text('project:\n  title: Test\n')
        prompt = build_revision_prompt(
            pass_name='test-pass',
            purpose='Test purpose.',
            scope='test-scene',
            project_dir=str(tmp_path),
            api_mode=True,
        )
        assert 'Intent-Beat Protection' not in prompt


class TestScoring:
    def test_parse_score_output(self, tmp_path):
        from storyforge.scoring import parse_score_output

        text = (
            'Some analysis text.\n\n'
            '{{SCORES:}}\nprinciple|score\n'
            'economy_clarity|4\nenter_late_leave_early|3\n'
            '{{END_SCORES}}\n\n'
            '{{RATIONALE:}}\nprinciple|rationale\n'
            'economy_clarity|Good prose density\n'
            'enter_late_leave_early|Opens a bit early\n'
            '{{END_RATIONALE}}\n'
        )

        scores, rationale = parse_score_output(text)
        assert 'economy_clarity|4' in scores or 'economy_clarity' in scores

    def test_effective_weight_author_override(self, tmp_path):
        from storyforge.scoring import get_effective_weight as effective_weight

        weights_csv = str(tmp_path / 'weights.csv')
        with open(weights_csv, 'w') as f:
            f.write('section|principle|weight|author_weight|notes\n')
            f.write('scene_craft|enter_late_leave_early|5||\n')
            f.write('scene_craft|every_scene_must_turn|7|9|author override\n')

        assert effective_weight(weights_csv, 'every_scene_must_turn') == 9
        assert effective_weight(weights_csv, 'enter_late_leave_early') == 5


class TestAssembly:
    def test_extract_scene_prose(self, fixture_dir):
        from storyforge.assembly import extract_scene_prose
        result = extract_scene_prose(os.path.join(fixture_dir, 'scenes', 'act1-sc01.md'))
        assert result
        assert '---' not in result

    def test_count_chapters(self, fixture_dir):
        from storyforge.assembly import count_chapters
        assert count_chapters(fixture_dir) == 2

    def test_read_chapter_field(self, fixture_dir):
        from storyforge.assembly import read_chapter_field
        assert read_chapter_field(1, fixture_dir, 'title') == 'The Finest Cartographer'

    def test_get_chapter_scenes(self, fixture_dir):
        from storyforge.assembly import get_chapter_scenes
        scenes = get_chapter_scenes(1, fixture_dir)
        assert 'act1-sc01' in scenes
        assert 'act1-sc02' in scenes

    def test_word_count(self, tmp_path):
        from storyforge.assembly import manuscript_word_count
        test_file = str(tmp_path / 'test.md')
        with open(test_file, 'w') as f:
            f.write('One two three four five six seven eight nine ten.')
        assert manuscript_word_count(test_file) == 10


class TestVisualize:
    def test_csv_to_records(self, fixture_dir):
        from storyforge.visualize import csv_to_records
        records = csv_to_records(os.path.join(fixture_dir, 'reference', 'scenes.csv'))
        assert len(records) >= 3

    def test_load_dashboard_data(self, fixture_dir):
        from storyforge.visualize import load_dashboard_data
        data = load_dashboard_data(fixture_dir)
        assert 'scenes' in data
        assert 'intents' in data
        assert 'project' in data


class TestEnrich:
    def test_parse_enrich_response(self, tmp_path):
        from storyforge.enrich import parse_enrich_response

        response_text = (
            'Here is my analysis of this scene.\n\n'
            'TYPE: action\nLOCATION: The Deep Archive\n'
            'TIME_OF_DAY: evening\n'
            'CHARACTERS: Dorren;the Archivist;Pell\n'
            'EMOTIONAL_ARC: tension \u2192 revelation\n'
            'THREADS: succession;map trust\n'
            'MOTIFS: maps;depth\n'
        )

        result = parse_enrich_response(response_text, 'test-scene')
        assert result['type'] == 'action'
        assert 'Deep Archive' in result.get('location', '')
        assert 'Dorren' in result.get('characters', '')

    def test_alias_normalization(self, fixture_dir):
        from storyforge.enrich import load_alias_map, normalize_aliases
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'characters.csv'))
        result = normalize_aliases(amap, 'Dorren;the Archivist;Pell')
        assert result == 'dorren-hayle;kael-maren;pell'

    def test_validate_type_valid(self):
        from storyforge.enrich import validate_type
        assert validate_type('action') == 'action'

    def test_validate_type_invalid(self):
        from storyforge.enrich import validate_type
        assert validate_type('invalid_thing') == ''


class TestScenes:
    def test_generate_slug(self):
        from storyforge.scenes import generate_slug
        assert generate_slug('The Finest Cartographer') == 'finest-cartographer'

    def test_generate_slug_no_spaces(self):
        from storyforge.scenes import generate_slug
        result = generate_slug('A Very Long Title With Many Words')
        assert result
        assert ' ' not in result


class TestTimeline:
    def test_parse_indicators(self):
        from storyforge.timeline import parse_indicators
        response = 'DELTA: next_day\nEVIDENCE: "The sun rose over the archive"\nANCHOR: none\n'
        result = parse_indicators(response, 'test-scene')
        assert 'next_day' in json.dumps(result)
        assert 'sun rose' in json.dumps(result)

    def test_parse_timeline_assignments(self):
        from storyforge.timeline import parse_timeline_assignments
        response = (
            'Here is my analysis.\n\nTIMELINE:\nid|timeline_day\n'
            'scene-1|1\nscene-2|1\nscene-3|2\nscene-4|5\n\nSummary text.\n'
        )
        result = parse_timeline_assignments(response)
        assert result.get('scene-1') == 1
        assert result.get('scene-4') == 5


class TestCover:
    def test_wrap_title_for_svg(self):
        from storyforge.cover import wrap_title_for_svg
        result = wrap_title_for_svg('A Very Long Book Title That Needs Wrapping')
        # Returns a list of lines
        assert isinstance(result, list)
        assert len(result) >= 2

    def test_get_color_scheme(self):
        from storyforge.cover import get_color_scheme
        scheme = get_color_scheme('fantasy')
        assert 'bg' in scheme
        assert 'accent' in scheme

    def test_render_svg_template(self, tmp_path):
        from storyforge.cover import render_svg_template
        template = str(tmp_path / 'template.svg')
        with open(template, 'w') as f:
            f.write('<svg><text>{{TITLE}}</text><text>{{AUTHOR}}</text></svg>')

        content = render_svg_template(template, {'TITLE': 'Test Book', 'AUTHOR': 'Test Author'})
        assert 'Test Book' in content
        assert 'Test Author' in content
        assert '{{TITLE}}' not in content


class TestCosts:
    def test_calculate_cost_sonnet(self):
        from storyforge.costs import calculate_cost
        result = calculate_cost('claude-sonnet-4-6', 1000000, 0)
        assert f'{result:.2f}' == '3.00'

    def test_check_threshold_under(self):
        from storyforge.costs import check_threshold
        # Returns True if under threshold (ok to proceed)
        assert check_threshold(5.00, 100) is True

    def test_check_threshold_over(self):
        from storyforge.costs import check_threshold
        # Returns False if over threshold
        assert check_threshold(150.00, 100) is False


class TestProject:
    def test_project_config(self, fixture_dir):
        from storyforge.project import project_config
        cfg = project_config(fixture_dir)
        assert cfg.get('title', '') == "The Cartographer's Silence"

    def test_current_cycle(self, fixture_dir):
        from storyforge.project import current_cycle
        c = current_cycle(fixture_dir)
        assert c is not None
        assert str(c['cycle']) == '3'

    def test_project_summary(self, fixture_dir):
        from storyforge.project import project_summary
        result = project_summary(fixture_dir)
        # Returns a dict
        if isinstance(result, dict):
            result_str = str(result)
        else:
            result_str = str(result)
        assert 'Cartographer' in result_str or 'title' in result_str


class TestVisualizeExtended:
    def test_loads_rationale_and_extended_scores(self, tmp_path):
        from storyforge.visualize import load_dashboard_data

        vis_dir = str(tmp_path / 'vis')
        os.makedirs(os.path.join(vis_dir, 'working', 'scores', 'latest'))
        os.makedirs(os.path.join(vis_dir, 'reference'))

        with open(os.path.join(vis_dir, 'storyforge.yaml'), 'w') as f:
            f.write('project:\n  title: Test Novel\n  genre: thriller\n')

        # Minimal CSVs
        with open(os.path.join(vis_dir, 'reference', 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|pov|word_count|status|type|location|part\n')
            f.write('s1|1|Scene One|Alice|1000|draft|character|Home|act-1\n')

        with open(os.path.join(vis_dir, 'reference', 'scene-intent.csv'), 'w') as f:
            f.write('id|function|emotional_arc|characters|motifs\n')
            f.write('s1|opener|tension|Alice|light\n')

        scores_dir = os.path.join(vis_dir, 'working', 'scores', 'latest')

        with open(os.path.join(scores_dir, 'scene-rationale.csv'), 'w') as f:
            f.write('id|principle_a|principle_b\n')
            f.write('s1|Good pacing here|Needs more tension\n')

        with open(os.path.join(scores_dir, 'act-scores.csv'), 'w') as f:
            f.write('id|framework_a|framework_b\n')
            f.write('act-1|4|3\n')

        with open(os.path.join(scores_dir, 'character-scores.csv'), 'w') as f:
            f.write('character|want_need|voice_as_character\n')
            f.write('Alice|5|4\n')

        data = load_dashboard_data(vis_dir)
        assert 'scene_rationales' in data
        assert len(data['scene_rationales']) == 1
        assert data['scene_rationales'][0]['principle_a'] == 'Good pacing here'

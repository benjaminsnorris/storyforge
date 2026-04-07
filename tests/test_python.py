"""Tests for Python core modules (migrated from test-python.sh)."""

import json
import os
import tempfile
import shutil


class TestParsing:
    def test_extract_scenes_from_response(self, tmp_path):
        from storyforge.parsing import extract_scenes_from_response

        response_file = str(tmp_path / 'response.json')
        with open(response_file, 'w') as f:
            json.dump({
                'content': [{'type': 'text', 'text': (
                    'Here is the revision.\n\n'
                    '=== SCENE: test-scene-1 ===\nFirst scene content.\nSecond line.\n'
                    '=== END SCENE: test-scene-1 ===\n\n'
                    '=== SCENE: test-scene-2 ===\nAnother scene.\n'
                    '=== END SCENE: test-scene-2 ===\n\nSummary text here.'
                )}],
                'usage': {'input_tokens': 100, 'output_tokens': 50}
            }, f)

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(response_file, scenes_dir)

        assert os.path.isfile(os.path.join(scenes_dir, 'test-scene-1.md'))
        assert os.path.isfile(os.path.join(scenes_dir, 'test-scene-2.md'))

        with open(os.path.join(scenes_dir, 'test-scene-1.md')) as f:
            content = f.read()
        assert 'First scene content' in content
        assert '=== SCENE:' not in content

    def test_skip_parenthetical_entries(self, tmp_path):
        from storyforge.parsing import extract_scenes_from_response

        response_file = str(tmp_path / 'response.json')
        with open(response_file, 'w') as f:
            json.dump({
                'content': [{'type': 'text', 'text': (
                    '=== SCENE: my-scene ===\nOriginal.\n=== END SCENE: my-scene ===\n\n'
                    '=== SCENE: my-scene (revised note) ===\nShould be skipped.\n'
                    '=== END SCENE: my-scene (revised note) ==='
                )}],
                'usage': {'input_tokens': 10, 'output_tokens': 5}
            }, f)

        scenes_dir = str(tmp_path / 'scenes')
        os.makedirs(scenes_dir)
        result = extract_scenes_from_response(response_file, scenes_dir)

        assert not os.path.isfile(os.path.join(scenes_dir, 'my-scene (revised note).md'))

    def test_extract_single_scene(self, tmp_path):
        from storyforge.parsing import extract_single_scene

        response_file = str(tmp_path / 'single.json')
        with open(response_file, 'w') as f:
            json.dump({
                'content': [{'type': 'text', 'text': (
                    'Some analysis.\n\n=== SCENE: drafted-scene ===\n'
                    'The prose goes here.\nMore prose.\n'
                    '=== END SCENE: drafted-scene ===\n\nNotes about the scene.'
                )}],
                'usage': {'input_tokens': 10, 'output_tokens': 5}
            }, f)

        output_file = str(tmp_path / 'output.md')
        extract_single_scene(response_file, output_file)

        assert os.path.isfile(output_file)
        with open(output_file) as f:
            content = f.read()
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
        from storyforge.api import log_usage as api_log_usage

        project_dir = str(tmp_path / 'project')
        os.makedirs(os.path.join(project_dir, 'working', 'costs'))

        response_file = str(tmp_path / 'usage-response.json')
        with open(response_file, 'w') as f:
            json.dump({
                'content': [{'type': 'text', 'text': 'test'}],
                'usage': {
                    'input_tokens': 1000, 'output_tokens': 500,
                    'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0
                }
            }, f)

        api_log_usage(response_file, 'test-op', 'test-target', 'claude-sonnet-4-6',
                      project_dir=project_dir)

        ledger = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
        assert os.path.isfile(ledger)

        with open(ledger) as f:
            lines = f.readlines()
        assert len(lines) == 2  # header + 1 data row
        assert 'test-op|claude-sonnet-4-6|1000|500' in lines[-1]


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
        assert 'reference/' in result


class TestRevision:
    def test_resolve_scope_full(self, fixture_dir):
        from storyforge.revision import resolve_scope
        result = resolve_scope('full', fixture_dir)
        assert 'act1-sc01.md' in result
        assert 'act2-sc01.md' in result

    def test_resolve_scope_csv(self, fixture_dir):
        from storyforge.revision import resolve_scope
        result = resolve_scope('act1-sc01,act1-sc02', fixture_dir)
        assert 'act1-sc01.md' in result
        assert 'act1-sc02.md' in result

    def test_resolve_scope_new_prefix(self, fixture_dir):
        from storyforge.revision import resolve_scope
        result = resolve_scope('NEW:the-rupture,act1-sc01', fixture_dir)
        assert 'act1-sc01.md' in result
        assert 'NEW:the-rupture.md' in result


class TestScoring:
    def test_parse_score_output(self, tmp_path):
        from storyforge.scoring import parse_score_output

        text_file = str(tmp_path / 'scores-text.txt')
        with open(text_file, 'w') as f:
            f.write(
                'Some analysis text.\n\n'
                '{{SCORES:}}\nprinciple|score\n'
                'economy_clarity|4\nenter_late_leave_early|3\n'
                '{{END_SCORES}}\n\n'
                '{{RATIONALE:}}\nprinciple|rationale\n'
                'economy_clarity|Good prose density\n'
                'enter_late_leave_early|Opens a bit early\n'
                '{{END_RATIONALE}}\n'
            )

        scores_csv = str(tmp_path / 'scores.csv')
        rationale_csv = str(tmp_path / 'rationale.csv')
        parse_score_output(text_file, scores_csv, rationale_csv)

        assert os.path.isfile(scores_csv)
        assert os.path.isfile(rationale_csv)

        with open(scores_csv) as f:
            content = f.read()
        assert 'economy_clarity|4' in content

    def test_effective_weight_author_override(self, tmp_path):
        from storyforge.scoring import effective_weight

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
        from storyforge.assembly import word_count
        test_file = str(tmp_path / 'test.md')
        with open(test_file, 'w') as f:
            f.write('One two three four five six seven eight nine ten.')
        assert word_count(test_file) == 10


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
        lines = result.strip().split('\n')
        assert len(lines) >= 2

    def test_get_color_scheme(self):
        from storyforge.cover import get_color_scheme
        scheme = get_color_scheme('fantasy')
        assert 'bg' in scheme
        assert 'accent' in scheme

    def test_render_svg_template(self, tmp_path):
        from storyforge.cover import render_svg_template
        template = str(tmp_path / 'template.svg')
        output = str(tmp_path / 'output.svg')
        with open(template, 'w') as f:
            f.write('<svg><text>{{TITLE}}</text><text>{{AUTHOR}}</text></svg>')

        render_svg_template(template, output, title='Test Book', author='Test Author')
        with open(output) as f:
            content = f.read()
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
        assert check_threshold(5.00, 100) == 'ok'

    def test_check_threshold_over(self):
        from storyforge.costs import check_threshold
        assert check_threshold(150.00, 100) == 'over'


class TestProject:
    def test_project_config(self, fixture_dir):
        from storyforge.project import project_config
        cfg = project_config(fixture_dir)
        assert cfg.get('title', '') == "The Cartographer's Silence"

    def test_current_cycle(self, fixture_dir):
        from storyforge.project import current_cycle
        c = current_cycle(fixture_dir)
        assert c is not None
        assert c['cycle'] == 3

    def test_project_summary(self, fixture_dir):
        from storyforge.project import project_summary
        result = project_summary(fixture_dir)
        assert 'Cartographer' in result
        assert 'cycle' in result


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

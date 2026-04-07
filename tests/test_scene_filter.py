"""Tests for scene filter (migrated from test-scene-filter.sh).

The bash tests used build_scene_list/apply_scene_filter from scene-filter.sh.
The Python equivalent uses the elaborate module's get_scenes and filtering.
"""

import os
import shutil

from storyforge.elaborate import get_scenes, _read_csv_as_map
from storyforge.csv_cli import get_field as get_csv_field


def _get_sorted_ids(ref_dir):
    """Get scene IDs sorted by seq, excluding cut/merged/stub."""
    scenes = get_scenes(ref_dir, columns=['id', 'status', 'word_count', 'seq'])
    return [s['id'] for s in scenes
            if s.get('status') not in ('cut', 'merged')
            and (not s.get('word_count') or s.get('status') not in ('drafted',) or int(s.get('word_count', '0') or '0') > 50)]


class TestBuildSceneList:
    def test_finds_all_scenes(self, fixture_dir):
        ref = os.path.join(fixture_dir, 'reference')
        scenes = get_scenes(ref, columns=['id', 'seq'])
        assert len(scenes) == 6

    def test_order_by_seq(self, fixture_dir):
        ref = os.path.join(fixture_dir, 'reference')
        scenes = get_scenes(ref, columns=['id', 'seq'])
        ids = [s['id'] for s in scenes]
        assert ids[0] == 'act1-sc01'
        assert ids[1] == 'act1-sc02'
        assert ids[2] == 'new-x1'
        assert ids[3] == 'act2-sc01'

    def test_excludes_cut_scenes(self, fixture_dir, tmp_path):
        ref = str(tmp_path / 'reference')
        shutil.copytree(os.path.join(fixture_dir, 'reference'), ref)
        with open(os.path.join(ref, 'scenes.csv'), 'a') as f:
            f.write('cut-scene|7|Cut Scene|1|Someone|Somewhere|1|morning||character|cut|500|500\n')

        scenes = get_scenes(ref, columns=['id', 'status'])
        active = [s for s in scenes if s['status'] != 'cut']
        assert len(active) == 6


class TestApplySceneFilter:
    def test_filter_all(self, fixture_dir):
        ref = os.path.join(fixture_dir, 'reference')
        scenes = get_scenes(ref, columns=['id'])
        assert len(scenes) == 6

    def test_filter_by_act(self, fixture_dir):
        ref = os.path.join(fixture_dir, 'reference')
        scenes = get_scenes(ref, columns=['id', 'part'], filters={'part': '1'})
        assert len(scenes) == 3

    def test_filter_act2(self, fixture_dir):
        ref = os.path.join(fixture_dir, 'reference')
        scenes = get_scenes(ref, columns=['id', 'part'], filters={'part': '2'})
        assert len(scenes) == 3
        assert scenes[0]['id'] == 'act2-sc01'

    def test_filter_specific_scenes(self, fixture_dir):
        ref = os.path.join(fixture_dir, 'reference')
        scenes = get_scenes(ref, columns=['id'])
        filtered = [s for s in scenes if s['id'] in ('act1-sc01', 'new-x1')]
        assert len(filtered) == 2

    def test_filter_single(self, fixture_dir):
        ref = os.path.join(fixture_dir, 'reference')
        scenes = get_scenes(ref, columns=['id'])
        filtered = [s for s in scenes if s['id'] == 'new-x1']
        assert len(filtered) == 1
        assert filtered[0]['id'] == 'new-x1'

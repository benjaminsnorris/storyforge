"""Tests for chapter map freshness checking."""
import os


SCENES_HEADER = (
    'id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n'
)
CHAPTER_MAP_HEADER = 'chapter|title|heading|part|scenes\n'


class TestCheckChapterMapFreshness:
    def test_fresh_when_all_scenes_in_map(self, tmp_path):
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            SCENES_HEADER
            + 'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            + 'scene-b|2|B|1|k|here|1|morning|short|action|drafted|1000|1500\n'
        )
        (ref / 'chapter-map.csv').write_text(
            CHAPTER_MAP_HEADER
            + '1|Ch One|numbered|1|scene-a;scene-b\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is True
        assert missing == []
        assert extra == []

    def test_missing_scene_not_in_map(self, tmp_path):
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            SCENES_HEADER
            + 'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            + 'scene-b|2|B|1|k|here|1|morning|short|action|drafted|1000|1500\n'
        )
        (ref / 'chapter-map.csv').write_text(
            CHAPTER_MAP_HEADER
            + '1|Ch One|numbered|1|scene-a\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is False
        assert 'scene-b' in missing
        assert extra == []

    def test_extra_scene_in_map_but_cut(self, tmp_path):
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            SCENES_HEADER
            + 'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            + 'scene-b|2|B|1|k|here|1|morning|short|action|cut|1000|1500\n'
        )
        (ref / 'chapter-map.csv').write_text(
            CHAPTER_MAP_HEADER
            + '1|Ch One|numbered|1|scene-a;scene-b\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is False
        assert missing == []
        assert 'scene-b' in extra

    def test_cut_scenes_excluded(self, tmp_path):
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            SCENES_HEADER
            + 'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            + 'scene-cut|2|Cut|1|k|here|1|morning|short|action|cut|0|0\n'
            + 'scene-merged|3|Merged|1|k|here|1|morning|short|action|merged|0|0\n'
        )
        (ref / 'chapter-map.csv').write_text(
            CHAPTER_MAP_HEADER
            + '1|Ch One|numbered|1|scene-a\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is True

    def test_archived_scenes_excluded(self, tmp_path):
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            SCENES_HEADER
            + 'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            + 'scene-arch|2|Arch|1|k|here|1|morning|short|action|archived|0|0\n'
        )
        (ref / 'chapter-map.csv').write_text(
            CHAPTER_MAP_HEADER
            + '1|Ch One|numbered|1|scene-a\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is True

    def test_no_chapter_map(self, tmp_path):
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            SCENES_HEADER
            + 'scene-a|1|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is False
        assert 'scene-a' in missing

    def test_no_scenes_csv(self, tmp_path):
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'chapter-map.csv').write_text(
            CHAPTER_MAP_HEADER
            + '1|Ch One|numbered|1|scene-a\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is False
        assert 'scene-a' in extra

    def test_multiple_chapters_semicolon_separated(self, tmp_path):
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            SCENES_HEADER
            + 'sc1|1|S1|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            + 'sc2|2|S2|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            + 'sc3|3|S3|2|k|here|2|morning|short|action|drafted|1000|1500\n'
        )
        (ref / 'chapter-map.csv').write_text(
            CHAPTER_MAP_HEADER
            + '1|Ch One|numbered|1|sc1;sc2\n'
            + '2|Ch Two|numbered|2|sc3\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is True
        assert missing == []
        assert extra == []

    def test_returns_sorted_lists(self, tmp_path):
        from storyforge.common import check_chapter_map_freshness
        ref = tmp_path / 'reference'
        ref.mkdir()
        (ref / 'scenes.csv').write_text(
            SCENES_HEADER
            + 'zz-scene|1|Z|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            + 'aa-scene|2|A|1|k|here|1|morning|short|action|drafted|1000|1500\n'
            + 'mm-scene|3|M|1|k|here|1|morning|short|action|drafted|1000|1500\n'
        )
        (ref / 'chapter-map.csv').write_text(
            CHAPTER_MAP_HEADER
            + '1|Ch One|numbered|1|aa-scene\n'
        )
        is_fresh, missing, extra = check_chapter_map_freshness(str(tmp_path))
        assert is_fresh is False
        assert missing == ['mm-scene', 'zz-scene']
        assert extra == []

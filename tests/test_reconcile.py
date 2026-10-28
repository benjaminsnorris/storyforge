"""Tests for reconciliation module (migrated from test-reconcile.sh)."""

import os
import shutil


class TestNormalizeOutcomes:
    def test_strips_elaborations(self):
        from storyforge.reconcile import normalize_outcomes

        assert normalize_outcomes('yes') == 'yes'
        assert normalize_outcomes('yes-but') == 'yes-but'
        assert normalize_outcomes('no-and') == 'no-and'
        assert normalize_outcomes('no') == 'no'
        assert normalize_outcomes('yes-but \u2014 Hank successfully maps') == 'yes-but'
        assert normalize_outcomes('no-and \u2014 she fails') == 'no-and'
        assert normalize_outcomes('yes \u2014 clean victory') == 'yes'
        assert normalize_outcomes('[yes-but]') == 'yes-but'
        assert normalize_outcomes('[no-and \u2014 elaboration]') == 'no-and'
        assert normalize_outcomes('') == ''
        assert normalize_outcomes('unknown format') == 'unknown format'


class TestReconcileOutcomes:
    def test_normalizes_csv(self, tmp_path):
        from storyforge.reconcile import reconcile_outcomes
        from storyforge.elaborate import _read_csv_as_map

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)
        with open(os.path.join(ref, 'scene-briefs.csv'), 'w') as f:
            f.write('id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|key_dialogue|emotions|motifs|continuity_deps|has_overflow\n')
            f.write('s01|g|c|yes-but \u2014 long elaboration here|cr|d|k|k|a|d|e|m||false\n')
            f.write('s02|g|c|no-and|cr|d|k|k|a|d|e|m||false\n')
            f.write('s03|g|c|[yes]|cr|d|k|k|a|d|e|m||false\n')
            f.write('s04|g|c|yes|cr|d|k|k|a|d|e|m||false\n')

        changed = reconcile_outcomes(ref)
        assert changed == 2

        m = _read_csv_as_map(os.path.join(ref, 'scene-briefs.csv'))
        assert m['s01']['outcome'] == 'yes-but'
        assert m['s03']['outcome'] == 'yes'


class TestBuildMappingPrompt:
    def test_characters(self, tmp_path):
        from storyforge.reconcile import build_mapping_prompt
        ref = str(tmp_path / 'reference')
        os.makedirs(ref)
        with open(os.path.join(ref, 'characters.csv'), 'w') as f:
            f.write('id|name|role|aliases\nkael-davreth|Kael Davreth|protagonist|Kael\n')
        batch = [{'key': 'bren', 'text': 'Bren', 'type': '', 'scenes': ['s02']}]
        prompt = build_mapping_prompt('characters', ref, batch, context='Bren is a smith.')
        assert '- kael-davreth — Kael Davreth (protagonist)' in prompt
        assert '1. Bren  [scenes: s02]' in prompt
        assert 'Bren is a smith.' in prompt
        assert 'N | NEW | id | name | role' in prompt


class TestWriteRegistry:
    def test_writes_rows(self, tmp_path):
        from storyforge.reconcile import write_registry
        from storyforge.elaborate import _read_csv_as_map

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        rows = [
            {'id': 'kael', 'name': 'Kael Davreth', 'role': 'protagonist', 'aliases': 'Kael;kael'},
            {'id': 'sera', 'name': 'Sera Vasht', 'role': 'supporting', 'aliases': 'Sera'},
        ]
        write_registry(ref, 'characters', rows)

        m = _read_csv_as_map(os.path.join(ref, 'characters.csv'))
        assert len(m) == 2
        assert m['kael']['name'] == 'Kael Davreth'
        assert m['sera']['role'] == 'supporting'


class TestApplyMapping:
    def test_mice_threads_keep_prefixes(self, tmp_path):
        from storyforge.reconcile import apply_mapping
        from storyforge.elaborate import _read_csv_as_map

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)
        with open(os.path.join(ref, 'mice-threads.csv'), 'w') as f:
            f.write('id|name|type|aliases\n')
        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq\ns01|1\ns02|2\n')
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|A|A|+inquiry:old-thread\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|A|A|-inquiry:old-thread\n')

        batch = [{'key': 'old-thread', 'text': 'old-thread', 'type': 'inquiry', 'scenes': ['s01', 's02']}]
        new_rows = [{'id': 'new-thread', 'name': 'New thread', 'type': 'inquiry'}]
        apply_mapping('mice-threads', ref, batch, {1: ['new-thread']}, new_rows)

        m = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        assert m['s01']['mice_threads'] == '+new-thread'
        assert m['s02']['mice_threads'] == '-new-thread'
        reg = _read_csv_as_map(os.path.join(ref, 'mice-threads.csv'))
        assert reg['new-thread']['aliases'] == 'old-thread'


class TestApplyRegistryNormalization:
    def test_characters(self, tmp_path):
        from storyforge.reconcile import apply_registry_normalization
        from storyforge.elaborate import _read_csv_as_map

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|One|1|Kael|The Hold|1|morning|1 hour|action|drafted|1000|2000\n')
            f.write('s02|2|Two|1|kael|Thornwall|1|afternoon|1 hour|action|drafted|1000|2000\n')
            f.write('s03|3|Three|1|Sera Vasht|The Fissure|2|morning|1 hour|action|drafted|1000|2000\n')
        with open(os.path.join(ref, 'scene-intent.csv'), 'w') as f:
            f.write('id|function|action_sequel|emotional_arc|value_at_stake|value_shift|turning_point|characters|on_stage|mice_threads\n')
            f.write('s01|test|action|flat|truth|+/-|revelation|Kael;Sera|Kael|\n')
            f.write('s02|test|action|flat|truth|+/-|revelation|kael;Bren|kael|\n')
            f.write('s03|test|action|flat|justice|+/-|revelation|Sera Vasht;Kael Davreth|Sera Vasht|\n')
        with open(os.path.join(ref, 'characters.csv'), 'w') as f:
            f.write('id|name|role|aliases\n')
            f.write('kael|Kael Davreth|protagonist|Kael;kael;Kael Davreth\n')
            f.write('sera|Sera Vasht|protagonist|Sera;sera;Sera Vasht\n')
            f.write('bren|Bren Tael|supporting|Bren;bren\n')

        apply_registry_normalization('characters', ref)

        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        assert scenes['s01']['pov'] == 'kael'
        assert scenes['s03']['pov'] == 'sera'

        intent = _read_csv_as_map(os.path.join(ref, 'scene-intent.csv'))
        assert intent['s03']['characters'] == 'sera;kael'

    def test_locations(self, tmp_path):
        from storyforge.reconcile import apply_registry_normalization
        from storyforge.elaborate import _read_csv_as_map

        ref = str(tmp_path / 'reference')
        os.makedirs(ref)

        with open(os.path.join(ref, 'scenes.csv'), 'w') as f:
            f.write('id|seq|title|part|pov|location|timeline_day|time_of_day|duration|type|status|word_count|target_words\n')
            f.write('s01|1|One|1|A|The Hold|1|morning|1 hour|action|drafted|1000|2000\n')
            f.write('s02|2|Two|1|A|the hold|1|afternoon|1 hour|action|drafted|1000|2000\n')
            f.write('s03|3|Three|1|A|Thornwall Market|2|morning|1 hour|action|drafted|1000|2000\n')
        with open(os.path.join(ref, 'locations.csv'), 'w') as f:
            f.write('id|name|aliases\n')
            f.write('the-hold|The Hold|The Hold;the hold;Hold\n')
            f.write('thornwall-market|Thornwall Market|Thornwall Market\n')

        apply_registry_normalization('locations', ref)
        scenes = _read_csv_as_map(os.path.join(ref, 'scenes.csv'))
        assert scenes['s01']['location'] == 'the-hold'
        assert scenes['s02']['location'] == 'the-hold'
        assert scenes['s03']['location'] == 'thornwall-market'


class TestMiceNormalization:
    def test_bare_names(self, tmp_path):
        from storyforge.enrich import normalize_mice_threads, load_mice_registry

        reg_path = str(tmp_path / 'mice-threads.csv')
        with open(reg_path, 'w') as f:
            f.write('id|name|type|aliases\n')
            f.write('understory|The Understory|milieu|hidden world;the magical chicago\n')
            f.write('vanishings|The Vanishings|inquiry|disappearances\n')
            f.write('zara-identity|Zara Identity|character|\n')

        alias_map, type_map = load_mice_registry(reg_path)

        assert normalize_mice_threads('+understory', alias_map, type_map) == '+understory'
        assert normalize_mice_threads('-vanishings', alias_map, type_map) == '-vanishings'
        assert normalize_mice_threads('zara-identity', alias_map, type_map) == 'zara-identity'
        assert normalize_mice_threads('+understory;-vanishings;zara-identity', alias_map, type_map) == '+understory;-vanishings;zara-identity'

    def test_typed_preserved_or_stripped(self, tmp_path):
        from storyforge.enrich import normalize_mice_threads, load_mice_registry

        reg_path = str(tmp_path / 'mice-threads.csv')
        with open(reg_path, 'w') as f:
            f.write('id|name|type|aliases\n')
            f.write('understory|The Understory|milieu|\n')

        alias_map, type_map = load_mice_registry(reg_path)

        # Typed input should output bare
        assert normalize_mice_threads('+milieu:understory', alias_map, type_map) == '+understory'
        # Wrong type should be corrected
        assert normalize_mice_threads('+inquiry:understory', alias_map, type_map) == '+understory'

    def test_alias_resolution(self, tmp_path):
        from storyforge.enrich import normalize_mice_threads, load_mice_registry

        reg_path = str(tmp_path / 'mice-threads.csv')
        with open(reg_path, 'w') as f:
            f.write('id|name|type|aliases\n')
            f.write('understory|The Understory|milieu|hidden world;the magical chicago\n')

        alias_map, type_map = load_mice_registry(reg_path)
        assert normalize_mice_threads('+hidden world', alias_map, type_map) == '+understory'

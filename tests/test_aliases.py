"""Tests for alias normalization (migrated from test-aliases.sh)."""

import os

from storyforge.enrich import (
    load_alias_map,
    normalize_aliases,
    strip_parentheticals,
)


class TestLoadAliasMapCharacters:
    def test_returns_data(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'characters.csv'))
        assert amap
        assert 'dorren-hayle' in str(amap)

    def test_archivist_maps_to_kael(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'characters.csv'))
        assert normalize_aliases(amap, 'the Archivist') == 'kael-maren'


class TestLoadAliasMapMotifs:
    def test_cartography_maps_to_maps(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'motif-taxonomy.csv'))
        assert normalize_aliases(amap, 'cartography') == 'maps'

    def test_governance_as_weight(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'motif-taxonomy.csv'))
        assert normalize_aliases(amap, 'governance-as-weight') == 'governance'

    def test_depth_descent(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'motif-taxonomy.csv'))
        assert normalize_aliases(amap, 'depth/descent') == 'depth'


class TestLoadAliasMapLocations:
    def test_deep_archive(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'locations.csv'))
        assert normalize_aliases(amap, 'The Deep Archive') == 'deep-archive'

    def test_abbreviation(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'locations.csv'))
        assert normalize_aliases(amap, 'PCO') == 'cartography-office'

    def test_variant(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'locations.csv'))
        assert normalize_aliases(amap, "Dorren's private study") == 'private-study'

    def test_unknown_passthrough(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'locations.csv'))
        assert normalize_aliases(amap, 'Unknown Place') == 'Unknown Place'


class TestNormalizeAliasesCharacters:
    def test_aliases_resolve(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'characters.csv'))
        assert normalize_aliases(amap, 'Dorren;the Archivist;Pell') == 'dorren-hayle;kael-maren;pell'

    def test_case_insensitive(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'characters.csv'))
        assert normalize_aliases(amap, 'dorren;TESSA;kael') == 'dorren-hayle;tessa-merrin;kael-maren'

    def test_deduplicates(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'characters.csv'))
        assert normalize_aliases(amap, 'Dorren;Dr. Hayle;Hayle') == 'dorren-hayle'

    def test_unknown_passthrough(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'characters.csv'))
        assert normalize_aliases(amap, 'Dorren;Unknown Person;Pell') == 'dorren-hayle;Unknown Person;pell'


class TestNormalizeAliasesMotifs:
    def test_aliases_resolve(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'motif-taxonomy.csv'))
        assert normalize_aliases(amap, 'cartography;governance-as-weight;depth/descent') == 'maps;governance;depth'

    def test_deduplicates(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'motif-taxonomy.csv'))
        assert normalize_aliases(amap, 'maps/cartography;Maps;cartography') == 'maps'

    def test_case_insensitive(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'motif-taxonomy.csv'))
        assert normalize_aliases(amap, 'CARTOGRAPHY;Depth/Descent') == 'maps;depth'


class TestStripParentheticals:
    def test_removes_trailing(self):
        assert strip_parentheticals('Cora (referenced)') == 'Cora'

    def test_removes_complex(self):
        assert strip_parentheticals('Keele (implied through grief thread)') == 'Keele'

    def test_noop_without_parens(self):
        assert strip_parentheticals('Emmett Slade') == 'Emmett Slade'

    def test_during_normalization(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'characters.csv'))
        assert normalize_aliases(amap, 'Dorren (referenced);Kael (implied);Pell') == 'dorren-hayle;kael-maren;pell'


class TestEdgeCases:
    def test_empty_string(self):
        assert normalize_aliases({}, '') == ''

    def test_empty_map_passthrough(self):
        assert normalize_aliases({}, 'Dorren;Tessa') == 'Dorren;Tessa'

    def test_handles_whitespace(self, fixture_dir):
        amap = load_alias_map(os.path.join(fixture_dir, 'reference', 'characters.csv'))
        assert normalize_aliases(amap, '  Dorren ; Tessa  ;  Pell  ') == 'dorren-hayle;tessa-merrin;pell'

    def test_missing_file_returns_empty(self):
        amap = load_alias_map('/nonexistent/file.csv')
        assert len(amap) == 0

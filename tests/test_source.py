"""Adaptation (#477): the `source:` block, the name map, `source import`,
the source map and validate's coverage check."""

import os
import subprocess

import pytest

from storyforge import source

from source_helpers import NAME_MAP, YAML, _write, import_source as _import, make_adaptation


@pytest.fixture
def adaptation(tmp_path):
    return make_adaptation(tmp_path)


def _snapshot(base):
    out = {}
    for root, _dirs, names in os.walk(base):
        for n in names:
            p = os.path.join(root, n)
            with open(p, 'rb') as f:
                out[os.path.relpath(p, base)] = f.read()
    return out


# ----------------------------------------------------------------------------
# The yaml block
# ----------------------------------------------------------------------------

class TestConfig:
    def test_no_block_is_none(self, project_dir):
        assert source.read_config(project_dir) is None

    def test_reads_block(self, adaptation):
        cfg = source.read_config(adaptation)
        assert cfg.slugs() == ['odyssey']
        assert cfg.projects[0].path == '../odyssey'   # the inline comment is not the value
        assert cfg.name_map == 'reference/names.csv'
        assert cfg.mode == 'faithful'
        assert cfg.gap_severity == 'blocking'

    def test_defaults(self, tmp_path):
        _write(tmp_path, {'storyforge.yaml': 'source:\n  projects:\n    - slug: a\n      path: ../a\n'})
        cfg = source.read_config(str(tmp_path))
        assert (cfg.mode, cfg.name_map, cfg.rules) == ('faithful', '', '')

    def test_free_mode_is_advisory(self, tmp_path):
        _write(tmp_path, {'storyforge.yaml': YAML.format(extra='  mode: free')})
        assert source.read_config(str(tmp_path)).gap_severity == 'advisory'

    def test_several_projects_and_per_project_map(self, tmp_path):
        _write(tmp_path, {'storyforge.yaml': (
            'source:\n  projects:\n    - slug: iliad\n      path: ../iliad\n'
            '      name_map: ../maps/iliad.csv\n    - slug: odyssey\n      path: "../odyssey"\n'
            '  mode: free\nphase: spine\n')})
        cfg = source.read_config(str(tmp_path))
        assert cfg.slugs() == ['iliad', 'odyssey']
        assert cfg.map_path(cfg.project('iliad')) == '../maps/iliad.csv'
        assert cfg.map_path(cfg.project('odyssey')) == ''
        assert cfg.mode == 'free'

    @pytest.mark.parametrize('yaml, message', [
        ('source:\n  mode: free\n', 'lists no'),
        ('source:\n  projects:\n    - slug: a\n', 'needs both'),
        ('source:\n  projects:\n    - slug: A B\n      path: x\n', 'lowercase'),
        ('source:\n  projects:\n    - slug: a\n      path: x\n    - slug: a\n      path: y\n', 'twice'),
        ('source:\n  projects:\n    - slug: a\n      path: x\n  mode: loose\n', 'loose'),
        ('source: ../iliad\n', 'must be a block'),
    ])
    def test_bad_block(self, tmp_path, yaml, message):
        _write(tmp_path, {'storyforge.yaml': yaml})
        with pytest.raises(source.SourceError, match=message):
            source.read_config(str(tmp_path))

    def test_rules_section(self, adaptation):
        _write(adaptation, {'storyforge.yaml': YAML.format(
            extra='  rules: reference/key-decisions.md#version-rules')})
        rules = source.read_rules(adaptation, source.read_config(adaptation))
        assert 'softens the killing' in rules
        assert 'Not a rule' not in rules

    def test_rules_missing_section_raises(self, adaptation):
        _write(adaptation, {'storyforge.yaml': YAML.format(
            extra='  rules: reference/key-decisions.md#no-such')})
        with pytest.raises(source.SourceError, match='no heading'):
            source.read_rules(adaptation, source.read_config(adaptation))


# ----------------------------------------------------------------------------
# The name map
# ----------------------------------------------------------------------------

class TestNameMap:
    def _map(self, tmp_path, text):
        p = tmp_path / 'm.csv'
        p.write_text(text)
        return source.load_name_map(str(p))

    def test_longest_first_whole_words(self, tmp_path):
        nm = self._map(tmp_path, NAME_MAP)
        assert nm.apply_text('Pallas Minerva and Minerva') == 'Pallas Athena and Athena'
        assert nm.apply_text('the son of Saturn') == 'the son of Cronus'
        assert nm.apply_text("Ulysses' bow") == "Odysseus' bow"
        assert nm.apply_text('Minervas') == 'Minervas'          # not a whole word
        assert nm.apply_text('jove;minerva') == 'jove;minerva'  # ids are lowercase

    def test_no_double_replacement(self, tmp_path):
        nm = self._map(tmp_path, 'source_id|target_id|source_name|target_name\n'
                                 '||A|B\n||B|C\n')
        assert nm.apply_text('A B') == 'B C'

    def test_ids(self, tmp_path):
        nm = self._map(tmp_path, NAME_MAP)
        assert nm.map_ids('jove;telemachus;unknown') == 'zeus;telemachus;unknown'

    def test_homonyms_share_a_name(self, tmp_path):
        nm = self._map(tmp_path, 'source_id|target_id|source_name|target_name\n'
                                 'eumaeus|eumaeus|Eumaeus|Eumaeus\n'
                                 'eumaeus-2|eumaeus-trojan|Eumaeus|Eumaeus\n')
        assert not nm.ambiguous
        assert nm.map_ids('eumaeus-2') == 'eumaeus-trojan'

    def test_ambiguous_name_left_alone(self, tmp_path):
        nm = self._map(tmp_path, 'source_id|target_id|source_name|target_name\n'
                                 'xanthus|xanthus|Xanthus|Xanthus\n'
                                 'xanthus-river|scamander|Xanthus|Scamander\n')
        assert nm.ambiguous == {'Xanthus': ['Scamander', 'Xanthus']}
        assert nm.apply_text('Xanthus') == 'Xanthus'

    @pytest.mark.parametrize('text, message', [
        ('a|b|c|d\n', 'header'),
        ('source_id|target_id|source_name|target_name\njove|zeus|Jove\n', 'cells'),
        ('source_id|target_id|source_name|target_name\njove||Jove|Zeus\n', 'target_id'),
        ('source_id|target_id|source_name|target_name\njove|zeus|Jove|Zeus\njove|dis|Jove|Dis\n',
         'both'),
        ('source_id|target_id|source_name|target_name\n||Saturn|\n', 'text-only'),
    ])
    def test_bad_map(self, tmp_path, text, message):
        with pytest.raises(source.SourceError, match=message):
            self._map(tmp_path, text)


# ----------------------------------------------------------------------------
# Import
# ----------------------------------------------------------------------------

class TestImport:
    def test_applies_map_to_ids_names_and_text(self, adaptation):
        _import(adaptation)
        dest = os.path.join(adaptation, 'reference', 'source', 'odyssey')
        chars = open(os.path.join(dest, 'characters.csv')).read()
        assert 'zeus|Zeus|supporting|son of Cronus' in chars
        assert 'athena|Athena|supporting|Pallas Athena;Pallas' in chars
        intent = open(os.path.join(dest, 'scene-intent.csv')).read()
        assert 'zeus;athena;odysseus|zeus;athena|+ulysses-return' in intent  # thread id kept
        assert 'Pallas Athena rouses the son' in intent
        locs = open(os.path.join(dest, 'locations.csv')).read()
        assert 'ithaca-hall|Hall of Odysseus|' in locs
        ledger = open(os.path.join(dest, 'commitments.csv')).read()
        assert '|odysseus|Zeus decrees Odysseus goes home|"Odysseus shall go home"|athena' in ledger
        briefs = open(os.path.join(dest, 'scene-briefs.csv')).read()
        assert 'Hermes is sent' in briefs
        assert open(os.path.join(dest, 'world-bible.md')).read() == '# World\n\nZeus rules Olympus.\n'
        for name in ('scenes.csv', 'scene-intent.csv', 'scene-briefs.csv', 'characters.csv',
                     'commitments.csv', 'mice-threads.csv'):
            text = open(os.path.join(dest, name)).read()
            for roman in ('Jove', 'Minerva', 'Ulysses', 'Saturn'):
                assert roman not in text, (name, roman)

    def test_prose_is_byte_identical(self, adaptation, tmp_path):
        _import(adaptation)
        for name in ('gods-debate.md', 'minerva-visits.md'):
            with open(tmp_path / 'odyssey' / 'scenes' / name, 'rb') as a, \
                 open(os.path.join(adaptation, 'reference', 'source', 'odyssey', 'scenes', name),
                      'rb') as b:
                assert a.read() == b.read()

    def test_source_bible(self, adaptation):
        _import(adaptation)
        bible = open(os.path.join(adaptation, 'reference', 'source', 'odyssey',
                                  'source-bible.md')).read()
        assert '## Events in reading order (4 scenes)' in bible
        assert '1. **The Gods Debate** (`gods-debate`; day 1; POV narrator; olympus)' in bible
        assert 'Outcome: no-but. Value: authority -/+.' in bible
        assert '**Telemachus** (`telemachus`): protagonist, POV in 3' in bible
        assert '**Odysseus\' return** (`ulysses-return`, event): opens in `gods-debate`' in bible
        assert '- Day 2: `assembly-called`' in bible
        assert 'Jove' not in bible

    def test_second_run_is_a_no_op(self, adaptation):
        first = _import(adaptation)
        before = _snapshot(adaptation)
        second = _import(adaptation)
        assert first.changed and not second.changed
        assert _snapshot(adaptation) == before

    def test_writes_only_under_reference_source(self, adaptation):
        before = _snapshot(adaptation)
        _import(adaptation)
        after = _snapshot(adaptation)
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        assert changed and all(k.startswith(os.path.join('reference', 'source', 'odyssey'))
                               for k in changed)

    def test_reimport_refreshes_and_drops_stale_files(self, adaptation, tmp_path):
        _import(adaptation)
        os.remove(tmp_path / 'odyssey' / 'scenes' / 'ship-sails.md')
        assert _import(adaptation).changed
        assert not os.path.exists(os.path.join(adaptation, 'reference', 'source', 'odyssey',
                                               'scenes', 'ship-sails.md'))
        # the map beside it is the author's: never touched
        assert open(os.path.join(adaptation, 'reference', 'names.csv')).read() == NAME_MAP

    def test_map_gap_stops_before_writing(self, adaptation):
        with open(os.path.join(adaptation, 'reference', 'names.csv'), 'w') as f:
            f.write(NAME_MAP.replace('harbor|harbor|Harbor|Harbor\n', ''))
        with pytest.raises(source.SourceError, match='locations.csv:harbor'):
            _import(adaptation)
        assert not os.path.exists(os.path.join(adaptation, 'reference', 'source'))

    def test_without_a_map_names_stay(self, adaptation):
        _write(adaptation, {'storyforge.yaml': 'source:\n  projects:\n    - slug: odyssey\n'
                                               '      path: ../odyssey\n'})
        _import(adaptation)
        chars = open(os.path.join(adaptation, 'reference', 'source', 'odyssey',
                                  'characters.csv')).read()
        assert 'jove|Jove|' in chars
        bible = open(os.path.join(adaptation, 'reference', 'source', 'odyssey',
                                  'source-bible.md')).read()
        assert 'translator' not in bible

    def test_not_a_project(self, adaptation, tmp_path):
        os.remove(tmp_path / 'odyssey' / 'reference' / 'scenes.csv')
        with pytest.raises(source.SourceError, match='no reference/scenes.csv'):
            _import(adaptation)

    def test_malformed_source_csv(self, adaptation, tmp_path):
        (tmp_path / 'odyssey' / 'reference' / 'values.csv').write_text('id|name\nx|y|z\n')
        with pytest.raises(source.SourceError, match='values.csv'):
            _import(adaptation)

    def test_dry_run_writes_nothing(self, adaptation):
        r = _import(adaptation, dry_run=True)
        assert r.changed
        assert not os.path.exists(os.path.join(adaptation, 'reference', 'source'))

    def test_command(self, adaptation, monkeypatch):
        from storyforge import cmd_source
        monkeypatch.chdir(adaptation)
        assert cmd_source.main(['import', '--no-commit']) == 0
        assert source.is_imported(adaptation, 'odyssey')
        assert cmd_source.main(['import', '--slug', 'nope', '--no-commit']) == 1

    def test_command_without_block(self, project_dir, monkeypatch):
        from storyforge import cmd_source
        monkeypatch.chdir(project_dir)
        assert cmd_source.main(['import']) == 1


# ----------------------------------------------------------------------------
# Coverage
# ----------------------------------------------------------------------------

SCENES = ('id|seq|title\n'
          'olympus-council|1|Council\n'
          'athena-at-the-door|2|At the Door\n'
          'night-sailing|3|Night Sailing\n')


def _adapt(adaptation, map_rows, scenes=SCENES, mode='faithful'):
    _import(adaptation)
    _write(adaptation, {
        'storyforge.yaml': YAML.format(extra=f'  mode: {mode}'),
        'reference/scenes.csv': scenes,
        'reference/source-map.csv': 'scene_id|source_scenes|treatment|note\n' + map_rows,
    })
    return source.check_coverage(adaptation, source.read_config(adaptation))


FULL_MAP = ('olympus-council|gods-debate|dramatize|\n'
            'athena-at-the-door|minerva-visits|pov-shift|told from Athena\n'
            'night-sailing|ship-sails|compress|\n'
            '|assembly-called|cut|folded into the sailing\n')


class TestCoverage:
    def test_clean(self, adaptation):
        r = _adapt(adaptation, FULL_MAP)
        assert r['findings'] == []
        assert r['lines'] == ['Source odyssey: 4 scenes, 3 mapped, 1 compressed, '
                              '1 cut (reasons given)']

    def test_silent_cut_blocks_in_faithful(self, adaptation):
        r = _adapt(adaptation, FULL_MAP.replace('|assembly-called|cut|folded into the sailing\n', ''))
        assert [(f['severity'], f['message']) for f in r['findings']] == [
            ('blocking', 'source scene odyssey:assembly-called is not in the source map '
                         '(adapt it, or cut it with a reason)')]
        assert r['lines'][0].endswith('1 unaccounted for')

    def test_silent_cut_is_advisory_in_free(self, adaptation):
        r = _adapt(adaptation, FULL_MAP.replace('folded into the sailing', ''), mode='free')
        assert [f['severity'] for f in r['findings']] == ['advisory']
        assert 'cut with no reason' in r['findings'][0]['message']
        assert '(1 without a reason)' in r['lines'][0]

    def test_scene_without_row_and_dangling_row(self, adaptation):
        r = _adapt(adaptation, FULL_MAP + 'gone-scene||invent|\n',
                   scenes=SCENES + 'extra-scene|4|Extra\n')
        msgs = {(f['scene_id'], f['message']) for f in r['findings']}
        assert ('gone-scene', 'in the source map but not in scenes.csv') in msgs
        assert any(s == 'extra-scene' and 'no row' in m for s, m in msgs)
        assert all(f['severity'] == 'blocking' for f in r['findings'])

    def test_row_without_source_must_be_invent(self, adaptation):
        r = _adapt(adaptation, FULL_MAP.replace('gods-debate|dramatize', '|dramatize')
                   + '|gods-debate|cut|x\n')
        assert any('names no source scene' in f['message'] for f in r['findings'])

    def test_unknown_source_id_and_treatment(self, adaptation):
        r = _adapt(adaptation, FULL_MAP.replace('ship-sails|compress', 'ship-sails;nope|squash'))
        assert any('squash' in f['message'] for f in r['findings'])
        r = _adapt(adaptation, FULL_MAP.replace('ship-sails|compress', 'ship-sails;nope|compress'))
        assert any('source scene nope is not a scene of the source' in f['message']
                   for f in r['findings'])

    def test_reorder_across_timeline_needs_note(self, adaptation):
        rows = ('olympus-council|ship-sails|reorder|\n'
                'athena-at-the-door|minerva-visits|dramatize|\n'
                'night-sailing|gods-debate;assembly-called|compress|\n')
        r = _adapt(adaptation, rows)
        assert [(f['scene_id'], f['severity']) for f in r['findings']] == [
            ('olympus-council', 'blocking')]
        assert 'timeline' in r['findings'][0]['message']
        assert _adapt(adaptation, rows.replace('reorder|', 'reorder|opens in medias res'))[
            'findings'] == []
        assert _adapt(adaptation, rows, mode='free')['findings'] == []

    def test_no_map_yet_is_said(self, adaptation):
        _import(adaptation)
        r = source.check_coverage(adaptation, source.read_config(adaptation))
        assert not r['checked']
        assert [f['severity'] for f in r['findings']] == ['advisory']

    def test_not_imported_blocks(self, adaptation):
        r = source.check_coverage(adaptation, source.read_config(adaptation))
        assert any(f['severity'] == 'blocking' and 'not imported' in f['message']
                   for f in r['findings'])

    def test_bad_map_header(self, adaptation):
        _import(adaptation)
        _write(adaptation, {'reference/source-map.csv': 'scene|source\n'})
        r = source.check_coverage(adaptation, source.read_config(adaptation))
        assert r['findings'][0]['severity'] == 'blocking'

    def test_two_sources_need_prefixes_when_ambiguous(self, adaptation):
        cat = {'a': {'x': {}}, 'b': {'x': {}, 'y': {}}}
        assert source.resolve_source_id('x', cat) is None
        assert source.resolve_source_id('b:x', cat) == ('b', 'x')
        assert source.resolve_source_id('y', cat) == ('b', 'y')


# ----------------------------------------------------------------------------
# validate
# ----------------------------------------------------------------------------

def _validate(project_dir, *args):
    import sys
    plugin = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=os.path.join(plugin, 'scripts', 'lib', 'python'))
    return subprocess.run([sys.executable, '-m', 'storyforge', 'validate', *args],
                          cwd=project_dir, env=env, capture_output=True, text=True)


class TestValidate:
    def test_project_without_source_has_no_source_section(self, project_dir):
        import json
        r = _validate(project_dir, '--json')
        assert 'source' not in json.loads(r.stdout)
        assert 'Source coverage' not in _validate(project_dir).stdout

    def test_silent_cut_fails_validate(self, adaptation):
        _adapt(adaptation, FULL_MAP.replace('|assembly-called|cut|folded into the sailing\n', ''))
        r = _validate(adaptation, '--no-schema')
        assert '--- Source coverage (faithful) ---' in r.stdout
        assert 'odyssey:assembly-called is not in the source map' in r.stdout
        assert r.returncode == 1

    def test_free_mode_passes_with_advisory(self, adaptation):
        _adapt(adaptation, FULL_MAP.replace('|assembly-called|cut|folded into the sailing\n', ''),
               mode='free')
        _write(adaptation, {'reference/scene-intent.csv': (
            'id|function\nolympus-council|Zeus frees him\n'
            'athena-at-the-door|Athena rouses Telemachus\nnight-sailing|He sails\n')})
        r = _validate(adaptation, '--no-schema')
        assert '[advisory]' in r.stdout
        assert r.returncode == 0, r.stdout + r.stderr


# ----------------------------------------------------------------------------
# Review fixes (PR #485)
# ----------------------------------------------------------------------------

class TestConfigTypes:
    def test_mode_is_checked_by_the_type(self):
        """TD-2: a bad mode can't fail open to advisory."""
        with pytest.raises(source.SourceError, match='Faithful'):
            source.SourceConfig(projects=(source.SourceProject('a', '../a'),), mode='Faithful')
        with pytest.raises(source.SourceError, match='no'):
            source.SourceConfig(projects=())

    def test_name_map_is_frozen(self, tmp_path):
        """TD-3: the compiled pattern can't go stale."""
        p = tmp_path / 'm.csv'
        p.write_text(NAME_MAP)
        nm = source.load_name_map(str(p))
        with pytest.raises(Exception):
            nm.ids = {}
        assert nm.apply_text('Jove') == 'Zeus'

    def test_lowercase_source_name_refused(self, tmp_path):
        p = tmp_path / 'm.csv'
        p.write_text('source_id|target_id|source_name|target_name\n||jove|Zeus\n')
        with pytest.raises(source.SourceError, match='capital'):
            source.load_name_map(str(p))


class TestImportFixes:
    def test_names_in_id_columns_are_renamed(self, adaptation, tmp_path):
        """SF-1: a source that keeps names in pov/on_stage gets them renamed,
        and a token the map knows neither way is named in a note."""
        intent = tmp_path / 'odyssey' / 'reference' / 'scene-intent.csv'
        intent.write_text(intent.read_text().replace(
            'minerva;telemachus|minerva;telemachus|ulysses-return',
            'Minerva;telemachus|Minerva;Pell|ulysses-return'))
        r = _import(adaptation)
        text = open(os.path.join(adaptation, 'reference', 'source', 'odyssey',
                                 'scene-intent.csv')).read()
        assert '|athena;telemachus|athena;Pell|' not in text
        assert '|Athena;telemachus|Athena;Pell|' in text
        assert any('scene-intent.csv:on_stage (Pell)' in n for n in r.notes)

    def test_ambiguous_names_are_noted(self, adaptation):
        with open(os.path.join(adaptation, 'reference', 'names.csv'), 'a') as f:
            f.write('||Harbor|Haven\n')
        r = _import(adaptation)
        assert any('Harbor (Harbor, Haven)' in n for n in r.notes)

    def test_name_map_inside_the_slug_dir_is_refused(self, adaptation):
        """CR-5: a re-import would delete it."""
        _import(adaptation)
        _write(adaptation, {'reference/source/odyssey/names.csv': NAME_MAP,
                            'storyforge.yaml': YAML.format(extra='').replace(
                                'reference/names.csv', 'reference/source/odyssey/names.csv')})
        with pytest.raises(source.SourceError, match='inside reference/source/odyssey/'):
            _import(adaptation)
        assert os.path.isfile(os.path.join(adaptation, 'reference', 'source', 'odyssey',
                                           'names.csv'))

    def test_registry_without_id_column(self, adaptation, tmp_path):
        (tmp_path / 'odyssey' / 'reference' / 'locations.csv').write_text('name\nHarbor\n')
        with pytest.raises(source.SourceError, match='no id column'):
            _import(adaptation)

    def test_unreadable_prose_is_a_source_error(self, adaptation, tmp_path):
        (tmp_path / 'odyssey' / 'scenes' / 'bad.md').mkdir()   # a directory: can't be read
        os.rename(tmp_path / 'odyssey' / 'scenes' / 'bad.md',
                  tmp_path / 'odyssey' / 'scenes' / 'bad-scene.md')
        with pytest.raises(source.SourceError, match='bad-scene.md'):
            _import(adaptation)

    def test_multi_source_import_writes_all_or_nothing(self, adaptation, tmp_path,
                                                       monkeypatch):
        """SF-15: the second source failing leaves the first unwritten."""
        from storyforge import cmd_source
        _write(adaptation, {'storyforge.yaml': (
            'source:\n  projects:\n    - slug: odyssey\n      path: ../odyssey\n'
            '    - slug: missing\n      path: ../nowhere\n  name_map: reference/names.csv\n')})
        monkeypatch.chdir(adaptation)
        assert cmd_source.main(['import', '--no-commit']) == 1
        assert not os.path.exists(os.path.join(adaptation, 'reference', 'source', 'odyssey'))

    def test_status(self, adaptation, monkeypatch, capsys):
        from storyforge import cmd_source
        monkeypatch.chdir(adaptation)
        assert cmd_source.main(['status']) == 1          # not imported: blocking
        assert 'not imported' in capsys.readouterr().out
        _adapt(adaptation, FULL_MAP)
        assert cmd_source.main(['status']) == 0
        assert 'Source odyssey: 4 scenes' in capsys.readouterr().out


class TestCoverageFixes:
    @pytest.mark.parametrize('mode, severity', [('faithful', 'blocking'), ('free', 'advisory')])
    @pytest.mark.parametrize('rows, message', [
        (FULL_MAP.replace('|assembly-called|cut|folded into the sailing\n', ''),
         'is not in the source map'),
        (FULL_MAP.replace('folded into the sailing', ''), 'cut with no reason'),
    ])
    def test_gap_severity_follows_the_mode(self, adaptation, mode, severity, rows, message):
        """T-2: every mode x gap combination."""
        r = _adapt(adaptation, rows, mode=mode)
        assert [(f['severity'], message in f['message']) for f in r['findings']] == [
            (severity, True)]

    def test_cut_row_with_a_scene_id_says_so(self, adaptation):
        """C-5: the message says what is wrong."""
        r = _adapt(adaptation, FULL_MAP.replace('|assembly-called|cut|',
                                                'night-sailing|assembly-called|cut|'))
        assert any(f['message'].startswith('a cut row must have an empty scene_id')
                   for f in r['findings'])

    def test_invent_with_sources_duplicate_rows_and_adapted_and_cut(self, adaptation):
        rows = FULL_MAP + 'night-sailing||invent|\n|gods-debate|cut|x\n'
        r = _adapt(adaptation, rows.replace('athena-at-the-door|minerva-visits|pov-shift',
                                            'athena-at-the-door|minerva-visits|invent'))
        msgs = [f['message'] for f in r['findings']]
        assert 'an invent row names source scenes (use the treatment that adapts them)' in msgs
        assert 'more than one row in the source map' in msgs
        assert 'source scene odyssey:gods-debate is both adapted and cut' in msgs
        assert all(f['severity'] == 'blocking' for f in r['findings'])

    def test_cut_scene_covers_nothing(self, adaptation):
        """CR-1: a scene cut in scenes.csv doesn't adapt its source scenes."""
        scenes = SCENES.replace('id|seq|title\n', 'id|seq|title|status\n') \
            .replace('Council\n', 'Council|mapped\n').replace('At the Door\n', 'At the Door|mapped\n') \
            .replace('Night Sailing\n', 'Night Sailing|cut\n')
        r = _adapt(adaptation, FULL_MAP, scenes=scenes)
        msgs = {(f['severity'], f['message']) for f in r['findings']}
        assert ('blocking', 'source scene odyssey:ship-sails is not in the source map '
                            '(adapt it, or cut it with a reason)') in msgs
        assert any(s == 'advisory' and 'covers nothing' in m for s, m in msgs)

    def test_reorder_in_order_needs_no_note(self, adaptation):
        """T-4: no crossing, no finding; and an early day placed late is caught."""
        rows = ('olympus-council|gods-debate|reorder|\n'
                'athena-at-the-door|minerva-visits|dramatize|\n'
                'night-sailing|assembly-called;ship-sails|compress|\n')
        assert _adapt(adaptation, rows)['findings'] == []
        late = ('olympus-council|minerva-visits|dramatize|\n'
                'athena-at-the-door|ship-sails|dramatize|\n'
                'night-sailing|gods-debate;assembly-called|reorder|\n')
        assert [f['scene_id'] for f in _adapt(adaptation, late)['findings']] == ['night-sailing']

    def test_reorder_compares_days_within_one_source(self):
        """CR-2: two books' calendars are unrelated."""
        found = []
        rows = [{'scene_id': 'a', 'source_scenes': 'iliad:x', 'treatment': 'dramatize'},
                {'scene_id': 'b', 'source_scenes': 'iliad:y', 'treatment': 'dramatize'},
                {'scene_id': 'c', 'source_scenes': 'odyssey:p', 'treatment': 'reorder'},
                {'scene_id': 'd', 'source_scenes': 'odyssey:q', 'treatment': 'dramatize'}]
        cat = {'iliad': {'x': {'timeline_day': '40'}, 'y': {'timeline_day': '50'}},
               'odyssey': {'p': {'timeline_day': '1'}, 'q': {'timeline_day': '5'}}}
        scenes = [{'id': i} for i in 'abcd']
        source._check_reorders(rows, scenes, cat, lambda *a: found.append(a))
        assert found == []

    def test_reorder_without_days_is_said(self, adaptation, tmp_path):
        """SF-7: silence would read as checked."""
        src = tmp_path / 'odyssey' / 'reference' / 'scenes.csv'
        src.write_text(src.read_text().replace('|1\n', '|\n').replace('|2\n', '|\n')
                       .replace('|3\n', '|\n'))
        rows = ('olympus-council|ship-sails|reorder|\n'
                'athena-at-the-door|minerva-visits|dramatize|\n'
                'night-sailing|gods-debate;assembly-called|compress|\n')
        r = _adapt(adaptation, rows)
        assert [(f['severity'], 'not checked' in f['message']) for f in r['findings']] == [
            ('advisory', True)]

    def test_blank_and_duplicate_source_ids_block(self, adaptation):
        _import(adaptation)
        path = os.path.join(adaptation, 'reference', 'source', 'odyssey', 'scenes.csv')
        with open(path, 'a') as f:
            f.write('gods-debate|5|Again||narrator|olympus|9\n|6|No id||narrator|olympus|9\n')
        _write(adaptation, {'reference/scenes.csv': SCENES,
                            'reference/source-map.csv':
                                'scene_id|source_scenes|treatment|note\n' + FULL_MAP})
        r = source.check_coverage(adaptation, source.read_config(adaptation))
        msgs = [f['message'] for f in r['findings']]
        assert 'source odyssey: 1 scene(s) with no id' in msgs
        assert 'source odyssey: duplicate scene ids gods-debate' in msgs

    def test_findings_carry_validates_keys(self, adaptation):
        """TD-4: one shape, with the keys elaborate's checks carry."""
        r = _adapt(adaptation, FULL_MAP.replace('|assembly-called|cut|folded into the sailing\n', ''))
        assert set(r['findings'][0]) == {'severity', 'scene_id', 'message', 'check',
                                         'category', 'passed'}


class TestValidateFixes:
    def test_malformed_block_fails_validate(self, project_dir):
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'a') as f:
            f.write('\nsource:\n  projects:\n    - slug: a\n      path: ../a\n  mode: loose\n')
        r = _validate(project_dir, '--no-schema')
        assert 'loose' in r.stdout and r.returncode == 1

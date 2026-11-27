"""Deaths by code (#745): characters.csv's `death_scene` filled from a
faithful adaptation's source, placed through the source map, and the life
check binding it by character id."""

import os

import pytest

from storyforge import cmd_cleanup, continuity, source, source_deaths, typed_state
from storyforge.typed_state import Record

from source_helpers import NAME_MAP, YAML, _write, import_source, make_adaptation

#: The source's cast: Mentes dies by the source's own registry, the two
#: Pisanders are namesakes, Leodes and Phemius die in the ledger, Medon
#: lives (every fact about him is one the patterns must not read as a death),
#: and Antinous dies but isn't in the book's registry.
SOURCE_CHARACTERS = (
    'id|name|role|aliases|death_scene\n'
    'jove|Jove|supporting|son of Saturn|\n'
    'minerva|Minerva|supporting|Pallas Minerva;Pallas|\n'
    'ulysses|Ulysses|protagonist||\n'
    'telemachus|Telemachus|protagonist||\n'
    'narrator|Narrator|minor||\n'
    'mentes|Mentes|minor||minerva-visits\n'
    'pisander-slain|Pisander|minor||\n'
    'pisander-son-of-polyctor|Pisander|minor||\n'
    'leodes|Leodes|minor||\n'
    'phemius|Phemius|minor||\n'
    'medon|Medon|minor||\n'
    'antinous|Antinous|minor||\n'
)

LEDGER_HEADER = 'id|scene_id|type|subject|statement|quote|known_by|status\n'
SOURCE_LEDGER = LEDGER_HEADER + (
    'ulysses-to-return|gods-debate|knowledge|ulysses|Jove decrees Ulysses goes home|'
    '"Ulysses shall go home"|minerva|binding\n'
    # the registry's death wins over an earlier ledger one
    'mentes-ledger|gods-debate|physical|mentes|Killed by Jove\'s bolt.|||binding\n'
    # a subject's death, by the opening that says so
    'pisander-dies|assembly-called|physical|pisander-slain|Killed by Telemachus\'s spear in '
    'the assembly.|||binding\n'
    # the subject kills someone: not the subject's death
    'telemachus-kills|assembly-called|physical|telemachus|Kills a suitor with his spear; '
    'the suitor is killed by the spear.|||binding\n'
    # no subject: "<killer> killed <victim>", the victim by name
    'leodes-dies|ship-sails|knowledge||Telemachus killed Leodes on the shore|||binding\n'
    # the same death said again in the same scene is one death
    'leodes-again|ship-sails|knowledge||Ulysses killed Leodes, the bard says|||binding\n'
    # a shared name binds no one: a finding, never a guess
    'pisander-shared|ship-sails|knowledge||Telemachus killed Pisander on the beach|||binding\n'
    # someone's relative, not named here
    'son-dies|gods-debate|knowledge||Jove killed Ulysses\'s son in a dream|||binding\n'
    'phemius-dies|assembly-called|physical|phemius|Lies dead by the door.|||binding\n'
    'antinous-dies|ship-sails|physical|antinous|Killed by Ulysses\'s arrow.|||binding\n'
    # none of these is Medon's death (T-1)
    'medon-1|ship-sails|knowledge||Nestor says Telemachus killed Medon|||binding\n'
    'medon-2|ship-sails|knowledge||Telemachus nearly killed Medon|||binding\n'
    'medon-3|ship-sails|knowledge||Telemachus kills Medon in a dream|||binding\n'
    'medon-4|ship-sails|knowledge||Medon was killed by Telemachus, they say|||binding\n'
    'medon-5|ship-sails|physical|medon|Nearly killed by Telemachus\'s spear.|||binding\n'
    'medon-6|ship-sails|physical|medon|Killed by grief at the news, he says.|||binding\n'
    'medon-7|ship-sails|physical|medon|Falls dead drunk in the hall.|||binding\n'
    'medon-8|ship-sails|physical|medon;phemius|Killed by Telemachus.|||binding\n'
    'medon-9|ship-sails|physical|medon|Killed by Telemachus.|||superseded\n'
)

EXTRA_NAMES = ('mentes|mentes|Mentes|Mentes\n'
               'pisander-slain|pisander-slain|Pisander|Pisander\n'
               'pisander-son-of-polyctor|pisander-son-of-polyctor|Pisander|Pisander\n'
               'leodes|leodes|Leodes|Leodes\n'
               'phemius|phemius|Phemius|Phemius\n'
               'medon|medon|Medon|Medon\n'
               'antinous|antinous|Antinous|Antinous\n')

BOOK_SCENES = ('id|seq|title|timeline_day|time_mode\n'
               'council|1|Council|1|\n'
               'at-the-door|2|At the Door|1|\n'
               'door-again|3|Door Again|1|\n'
               'assembly|4|Assembly|2|\n'
               'sailing|5|Sailing|3|\n'
               'after|6|After|4|\n')

#: door-again listed before at-the-door, and a row for a scene scenes.csv
#: doesn't have: placement is by reading order among active scenes (T-4)
BOOK_MAP = ('scene_id|source_scenes|treatment|note\n'
            'council|gods-debate|dramatize|\n'
            'door-again|minerva-visits|expand|\n'
            'at-the-door|minerva-visits|expand|\n'
            'gone|minerva-visits|expand|\n'
            'assembly|assembly-called|dramatize|\n'
            'sailing|ship-sails|dramatize|\n'
            'after||invent|\n')

BOOK_CAST = [('zeus', 'Zeus'), ('athena', 'Athena'), ('odysseus', 'Odysseus'),
             ('telemachus', 'Telemachus'), ('mentes', 'Mentes'),
             ('pisander-slain', 'Pisander'), ('pisander-son-of-polyctor', 'Pisander'),
             ('leodes', 'Leodes'), ('phemius', 'Phemius'), ('medon', 'Medon')]

FILLED = {'mentes': 'door-again', 'pisander-slain': 'assembly', 'leodes': 'sailing',
          'phemius': 'assembly'}


def _book_characters(death_scenes=None):
    death_scenes = death_scenes or {}
    rows = ['id|name|aliases|role|death_scene|pronouns']
    for cid, name in BOOK_CAST:
        rows.append(f'{cid}|{name}||minor|{death_scenes.get(cid, "")}|')
    return '\n'.join(rows) + '\n'


@pytest.fixture
def book(tmp_path):
    proj = make_adaptation(tmp_path)   # writes the source too
    _write(tmp_path / 'odyssey', {'reference/characters.csv': SOURCE_CHARACTERS,
                                  'reference/commitments.csv': SOURCE_LEDGER})
    _write(proj, {'reference/names.csv': NAME_MAP + EXTRA_NAMES})
    import_source(proj)
    _write(proj, {'reference/scenes.csv': BOOK_SCENES,
                  'reference/source-map.csv': BOOK_MAP,
                  'reference/characters.csv': _book_characters()})
    return proj


def _fills(plan):
    return {f.who: f.scene_id for f in plan.fills}


def _source_file(book, name):
    return os.path.join(book, 'reference', 'source', 'odyssey', name)


def _append_ledger(book, rows):
    with open(_source_file(book, 'commitments.csv'), 'a') as f:
        f.write(rows)


class TestPlanDeaths:
    def test_each_source_death_is_placed_in_the_book(self, book):
        plan = source_deaths.plan_deaths(book)
        assert _fills(plan) == FILLED
        assert plan.of(source_deaths.WARNING) == []
        info = plan.of(source_deaths.INFO)
        assert any('Pisander' in n and 'bind no one' in n for n in info)
        assert any('several subjects' in n and 'medon-8' in n for n in info)
        assert any('antinous' in n and 'no row' in n for n in info)

    def test_no_fact_that_is_not_a_death_fills_one(self, book):
        # T-1: reported speech, "nearly", "kills", the passive, grief,
        # drunkenness, several subjects, a superseded fact
        plan = source_deaths.plan_deaths(book)
        assert 'medon' not in _fills(plan) and 'telemachus' not in _fills(plan)
        assert 'pisander-son-of-polyctor' not in _fills(plan)   # the namesake

    @pytest.mark.parametrize('statement', [
        'Killed by Diomedes\'s spear.', 'Killed by the spear of Ajax.', 'Struck dead by a stone.',
        'Lies dead where he fell.', 'Fell dead.', 'Falls dead on the sand.'])
    def test_the_victim_openings(self, statement):
        assert source_deaths.VICTIM.match(statement)

    @pytest.mark.parametrize('statement', [
        'Killed by grief.', 'Falls dead drunk.', 'Nearly killed by Ajax.', 'Kills Ajax.',
        'Ajax is killed by Hector.'])
    def test_not_victim_openings(self, statement):
        assert not source_deaths.VICTIM.match(statement)

    def test_the_registry_death_wins_and_names_the_scenes_adapting_it(self, book):
        # T-2: Mentes also dies earlier in the ledger; T-4: the last active
        # scene in reading order, whatever the map's row order
        fill = next(f for f in source_deaths.plan_deaths(book).fills if f.who == 'mentes')
        assert fill.death.scene == 'minerva-visits'
        assert fill.death.evidence == source_deaths.REGISTRY
        assert fill.adapting == ('at-the-door', 'door-again')
        assert 'the last of 2 scenes adapting it' in fill.describe()

    def test_a_retelling_in_a_later_scene_does_not_move_a_death(self, book):
        _append_ledger(book, 'leodes-early|minerva-visits|knowledge||Telemachus killed '
                             'Leodes first|||binding\n')
        assert _fills(source_deaths.plan_deaths(book))['leodes'] == 'door-again'

    def test_a_death_in_a_cut_scene_is_a_warning_not_a_fill(self, book):
        _write(book, {'reference/source-map.csv': BOOK_MAP.replace(
            'assembly|assembly-called|dramatize|\n', '|assembly-called|cut|told later\n')})
        plan = source_deaths.plan_deaths(book)
        assert 'phemius' not in _fills(plan) and 'pisander-slain' not in _fills(plan)
        assert any('phemius' in p and 'cuts' in p for p in plan.of(source_deaths.WARNING))

    def test_lives_is_respected_and_silences_the_warning(self, book):
        # CR-2/SF-6
        _write(book, {'reference/source-map.csv': BOOK_MAP.replace(
            'assembly|assembly-called|dramatize|\n', '|assembly-called|cut|told later\n'),
            'reference/characters.csv': _book_characters({'phemius': 'lives',
                                                          'mentes': 'lives'})})
        plan = source_deaths.plan_deaths(book)
        assert 'mentes' not in _fills(plan)
        assert not any('phemius' in p for p in plan.of(source_deaths.WARNING) +
                       plan.of(source_deaths.INFO))
        assert [d.who for d in typed_state.registry_deaths(book)] == []

    def test_an_authors_value_is_kept_and_a_disagreement_is_info(self, book):
        _write(book, {'reference/characters.csv': _book_characters(
            {'leodes': 'after', 'mentes': 'at-the-door'})})
        plan = source_deaths.plan_deaths(book)
        assert 'leodes' not in _fills(plan) and 'mentes' not in _fills(plan)
        assert not any('mentes' in p for p in plan.of(source_deaths.INFO))
        assert plan.of(source_deaths.WARNING) == []
        assert any('leodes death_scene after' in p and 'sailing' in p
                   for p in plan.of(source_deaths.INFO))

    def test_a_later_scene_with_them_on_stage_or_as_pov_stops_the_fill(self, book):
        # SF-5
        _write(book, {'reference/scene-intent.csv': 'id|function|on_stage\n'
                                                    'after|x|telemachus;Leodes\n',
                      'reference/scenes.csv': BOOK_SCENES.replace(
                          'council|1|Council|1|', 'council|1|Council|1|').replace(
                          'title|timeline_day|time_mode', 'title|timeline_day|time_mode|pov')
                      .replace('|\n', '||\n').replace('after|6|After|4||',
                                                      'after|6|After|4||phemius')})
        plan = source_deaths.plan_deaths(book)
        assert 'leodes' not in _fills(plan) and 'phemius' not in _fills(plan)
        warned = plan.of(source_deaths.WARNING)
        assert any('leodes' in w and 'after' in w and 'on stage' in w for w in warned)
        assert any('phemius' in w for w in warned)

    def test_an_off_present_later_scene_does_not_stop_it(self, book):
        _write(book, {'reference/scene-intent.csv': 'id|function|on_stage\nafter|x|leodes\n',
                      'reference/scenes.csv': BOOK_SCENES.replace('after|6|After|4|',
                                                                  'after|6|After|4|memory')})
        assert _fills(source_deaths.plan_deaths(book))['leodes'] == 'sailing'

    def test_free_mode_is_said_with_the_map_present(self, book):
        # T-6
        _write(book, {'storyforge.yaml': YAML.format(extra='  mode: free')})
        plan = source_deaths.plan_deaths(book)
        assert plan.fills == () and any('free mode' in n for n in plan.of(source_deaths.INFO))
        step = cmd_cleanup.plan_death_scenes(book)
        assert step.changes == () and step.summary is not None

    def test_no_map_yet_is_said(self, book):
        os.remove(os.path.join(book, 'reference', 'source-map.csv'))
        plan = source_deaths.plan_deaths(book)
        assert plan.fills == () and any('no reference/source-map.csv' in n
                                        for n in plan.of(source_deaths.INFO))

    def test_no_source_block_plans_nothing(self, project_dir):
        assert source_deaths.plan_deaths(project_dir) == source_deaths.DeathPlan()

    def test_a_death_outside_the_range_is_not_filled(self, book):
        _write(book, {'storyforge.yaml': YAML.replace(
            'path: ../odyssey   # the extraction',
            'path: ../odyssey\n      range: scenes gods-debate..minerva-visits').format(
                extra='  mode: faithful')})
        import_source(book)
        _write(book, {'reference/source-map.csv': (
            'scene_id|source_scenes|treatment|note\n'
            'council|gods-debate|dramatize|\n'
            'at-the-door|minerva-visits|expand|\n'
            'door-again|minerva-visits|expand|\n'
            'assembly||invent|\nsailing||invent|\nafter||invent|\n')})
        plan = source_deaths.plan_deaths(book)
        assert _fills(plan) == {'mentes': 'door-again'}
        assert any('outside the adapted range' in n for n in plan.of(source_deaths.INFO))

    def test_no_death_scene_column_is_a_warning(self, book):
        _write(book, {'reference/characters.csv': 'id|name\nleodes|Leodes\n'})
        plan = source_deaths.plan_deaths(book)
        assert plan.fills == () and any('no death_scene column' in p
                                        for p in plan.of(source_deaths.WARNING))

    def test_a_bad_source_death_scene_is_a_warning_and_the_ledger_isnt_asked(self, book):
        # SF-3: Phemius's source registry names no scene; his ledger death
        # isn't filled in its place
        path = _source_file(book, 'characters.csv')
        with open(path) as f:
            text = f.read()
        _write(book, {'reference/source/odyssey/characters.csv':
                      text.replace('phemius|Phemius|minor||', 'phemius|Phemius|minor||nowhere')})
        plan = source_deaths.plan_deaths(book)
        assert 'phemius' not in _fills(plan)
        assert any('nowhere' in p and 'not a scene of the source' in p
                   for p in plan.of(source_deaths.WARNING))

    def test_a_missing_source_table_is_a_warning(self, book):
        # SF-2
        os.remove(_source_file(book, 'commitments.csv'))
        plan = source_deaths.plan_deaths(book)
        assert _fills(plan) == {'mentes': 'door-again'}
        assert any('commitments.csv is missing' in p for p in plan.of(source_deaths.WARNING))

    def test_a_source_not_imported_is_a_warning(self, book):
        import shutil
        shutil.rmtree(os.path.join(book, 'reference', 'source'))
        plan = source_deaths.plan_deaths(book)
        assert any('not imported' in p for p in plan.of(source_deaths.WARNING))

    def test_deaths_in_two_sources_warn_until_the_author_sets_it(self, book, monkeypatch):
        # T-5
        two = {'leodes': [source_deaths.SourceDeath('leodes', 'odyssey', 'ship-sails', 'x'),
                          source_deaths.SourceDeath('leodes', 'iliad', 'other', 'y')]}
        monkeypatch.setattr(source_deaths, 'source_deaths', lambda *a, **k: (two, set()))
        plan = source_deaths.plan_deaths(book)
        assert plan.fills == ()
        assert any('more than one' in p for p in plan.of(source_deaths.WARNING))
        _write(book, {'reference/characters.csv': _book_characters({'leodes': 'sailing'})})
        assert source_deaths.plan_deaths(book).findings == ()

    def test_an_unreadable_registry_is_a_warning_not_a_crash(self, book):
        # CR-1/SF-4
        with open(os.path.join(book, 'reference', 'characters.csv'), 'wb') as f:
            f.write('id|name|aliases|role|death_scene\nleodes|Léodès||minor|\n'.encode('latin-1'))
        plan = source_deaths.plan_deaths(book)
        assert plan.fills == () and any('could not be read' in p
                                        for p in plan.of(source_deaths.WARNING))
        report = cmd_cleanup.build_cleanup_report(book)
        types = {f['type'] for f in report['findings']}
        assert {'unreadable_csv', 'source_death'} <= types
        assert cmd_cleanup.plan_death_scenes(book).changes == ()


class TestApplyAndLife:
    """The acceptance: a character acting after their mapped death scene is
    flagged; a namesake is not."""

    def test_fills_write_only_blank_cells(self, book):
        plan = source_deaths.plan_deaths(book)
        done = source_deaths.apply_fills(book, plan.fills)
        assert {f.who for f in done} == set(FILLED)
        assert {d.who: d.scene_id for d in typed_state.registry_deaths(book)} == FILLED
        assert source_deaths.plan_deaths(book).fills == ()

    def test_a_cell_the_author_set_after_planning_is_not_overwritten(self, book):
        # T-3
        step = cmd_cleanup.plan_death_scenes(book)
        _write(book, {'reference/characters.csv': _book_characters({'leodes': 'lives'})})
        done = step.apply()
        assert not any('for leodes' in c.did for c in done)
        assert len(done) == len(FILLED) - 1
        rows = {d.who for d in typed_state.registry_deaths(book)}
        assert 'leodes' not in rows

    def test_a_registry_with_a_byte_order_mark_is_filled(self, book):
        # CR-3
        path = os.path.join(book, 'reference', 'characters.csv')
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.write(_book_characters())
        step = cmd_cleanup.plan_death_scenes(book)
        assert len(step.apply()) == len(FILLED)
        assert {d.who: d.scene_id for d in typed_state.registry_deaths(book)} == FILLED
        with open(path, 'rb') as f:
            assert f.read().startswith(b'\xef\xbb\xbfid|')   # the mark is kept

    def test_presence_after_the_filled_death_is_flagged_and_a_namesake_is_not(self, book):
        plan = source_deaths.plan_deaths(book)
        source_deaths.apply_fills(book, plan.fills)
        from storyforge.elaborate import _read_csv
        from storyforge.enrich import load_alias_map
        path = os.path.join(book, 'reference', 'characters.csv')
        chars = _read_csv(path)
        scene_rows = _read_csv(os.path.join(book, 'reference', 'scenes.csv'))
        order = {r['id']: n for n, r in enumerate(scene_rows)}
        scenes = {r['id']: r for r in scene_rows}

        def life(records):
            b = continuity.Book('after', order, scenes, records={'after': [
                r.replace(scene_id='after') for r in records]},
                deaths=typed_state.registry_deaths(book), chars=load_alias_map(path),
                namesakes=continuity.namesakes(chars), ids=continuity.registry_ids(chars))
            return continuity.check_life(b)

        f, _notes = life([Record('at', 'pisander-slain', quote='Pisander rides in')])
        assert len(f) == 1 and 'death_scene assembly' in f[0].explanation
        assert life([Record('at', 'pisander-son-of-polyctor', quote='Pisander rides in')])[0] == []
        f, notes = life([Record('at', 'Pisander', quote='Pisander rides in')])
        assert f == [] and any('Pisander' in n for n in notes)   # said, never silent
        assert len(life([Record('at', 'Leodes', quote='Leodes sings')])[0]) == 1


class TestSeeding:
    def test_a_source_death_scene_is_not_seeded_and_is_said(self, tmp_path):
        proj = make_adaptation(tmp_path)
        _write(tmp_path / 'odyssey', {'reference/characters.csv': SOURCE_CHARACTERS})
        _write(proj, {'reference/names.csv': NAME_MAP + EXTRA_NAMES,
                      'reference/characters.csv': 'id|name|aliases|role|death_scene|pronouns\n'})
        import_source(proj)
        _seeded, notes = source.seed_registries(proj, source.read_config(proj))
        chars = open(os.path.join(proj, 'reference', 'characters.csv')).read()
        assert 'mentes|Mentes||minor||' in chars and 'minerva-visits' not in chars
        assert any('death_scene' in n and 'storyforge cleanup' in n for n in notes)


class TestCleanup:
    def test_every_finding_is_in_the_report(self, book):
        # SF-1: warnings and info alike, so `cleanup --csv` shows them
        _write(book, {'reference/source-map.csv': BOOK_MAP.replace(
            'assembly|assembly-called|dramatize|\n', '|assembly-called|cut|told later\n')})
        found = cmd_cleanup._check_source_deaths(book)
        assert {f['severity'] for f in found} == {'warning', 'info'}
        assert any('phemius' in f['detail'] and f['severity'] == 'warning' for f in found)
        assert any('Pisander' in f['detail'] and f['severity'] == 'info' for f in found)
        assert all(f['type'] == 'source_death' and '|' not in f['detail'] for f in found)
        report = cmd_cleanup.build_cleanup_report(book)
        assert len([f for f in report['findings'] if f['type'] == 'source_death']) == len(found)

    def test_the_step_fills_and_counts_what_it_did_not(self, book):
        step = cmd_cleanup.plan_death_scenes(book)
        assert len(step.changes) == len(FILLED) and 'see the report' in step.summary.would
        assert {c.did for c in step.apply()} == {c.did for c in step.changes}
        assert cmd_cleanup.plan_death_scenes(book).changes == ()

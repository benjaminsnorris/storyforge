"""Deaths by code (#745): characters.csv's `death_scene` filled from a
faithful adaptation's source, placed through the source map, and the life
check binding it by character id."""

import os

import pytest

from storyforge import continuity, source, source_deaths, typed_state
from storyforge.typed_state import Record

from source_helpers import NAME_MAP, YAML, _write, import_source, make_adaptation

#: The source's cast: Mentes dies by the source's own registry, the two
#: Pisanders are namesakes, Leodes and Phemius die in the ledger.
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
)

SOURCE_LEDGER = (
    'id|scene_id|type|subject|statement|quote|known_by\n'
    'ulysses-to-return|gods-debate|knowledge|ulysses|Jove decrees Ulysses goes home|'
    '"Ulysses shall go home"|minerva\n'
    # a subject's death, by the opening that says so
    'pisander-dies|assembly-called|physical|pisander-slain|Killed by Telemachus\'s spear in '
    'the assembly.||\n'
    # the subject kills someone: not the subject's death
    'telemachus-kills|assembly-called|physical|telemachus|Kills a suitor with his spear; '
    'the suitor is killed by the spear.||\n'
    # no subject: "<killer> killed <victim>", the victim by name
    'leodes-dies|ship-sails|knowledge||Telemachus killed Leodes on the shore||\n'
    # a later scene retelling an earlier death doesn't move it
    'leodes-retold|ship-sails|knowledge||Ulysses killed Leodes, the bard says||\n'
    # a shared name binds no one: a note, never a guess
    'pisander-shared|ship-sails|knowledge||Telemachus killed Pisander on the beach||\n'
    # someone's relative, not named here
    'son-dies|gods-debate|knowledge||Jove killed Ulysses\'s son in a dream||\n'
    # a death in a scene the map cuts
    'phemius-dies|assembly-called|physical|phemius|Lies dead by the door.||\n'
)

EXTRA_NAMES = ('mentes|mentes|Mentes|Mentes\n'
               'pisander-slain|pisander-slain|Pisander|Pisander\n'
               'pisander-son-of-polyctor|pisander-son-of-polyctor|Pisander|Pisander\n'
               'leodes|leodes|Leodes|Leodes\n'
               'phemius|phemius|Phemius|Phemius\n')

BOOK_SCENES = ('id|seq|title|timeline_day\n'
               'council|1|Council|1\n'
               'at-the-door|2|At the Door|1\n'
               'door-again|3|Door Again|1\n'
               'assembly|4|Assembly|2\n'
               'sailing|5|Sailing|3\n'
               'after|6|After|4\n')

BOOK_MAP = ('scene_id|source_scenes|treatment|note\n'
            'council|gods-debate|dramatize|\n'
            'at-the-door|minerva-visits|expand|\n'
            'door-again|minerva-visits|expand|\n'
            'assembly|assembly-called|dramatize|\n'
            'sailing|ship-sails|dramatize|\n'
            'after||invent|\n')


def _book_characters(death_scenes=None):
    death_scenes = death_scenes or {}
    rows = ['id|name|aliases|role|death_scene|pronouns']
    for cid, name in [('zeus', 'Zeus'), ('athena', 'Athena'), ('odysseus', 'Odysseus'),
                      ('telemachus', 'Telemachus'), ('mentes', 'Mentes'),
                      ('pisander-slain', 'Pisander'), ('pisander-son-of-polyctor', 'Pisander'),
                      ('leodes', 'Leodes'), ('phemius', 'Phemius')]:
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


class TestPlanDeaths:
    def test_each_source_death_is_placed_in_the_book(self, book):
        plan = source_deaths.plan_deaths(book)
        assert _fills(plan) == {
            'mentes': 'door-again',          # the registry's; the last of two adapting it
            'pisander-slain': 'assembly',    # the ledger, by subject id
            'leodes': 'sailing',             # the ledger, the victim by name
            'phemius': 'assembly',
        }
        assert plan.problems == ()
        assert any('Pisander' in n and 'bind no one' in n for n in plan.notes)
        # the namesake has no death
        assert 'pisander-son-of-polyctor' not in _fills(plan)

    def test_the_registry_death_names_how_many_scenes_adapt_it(self, book):
        fill = next(f for f in source_deaths.plan_deaths(book).fills if f.who == 'mentes')
        assert fill.adapting == ('at-the-door', 'door-again')
        assert 'the last of 2 scenes adapting it' in fill.describe()
        assert fill.death.evidence == source_deaths.REGISTRY

    def test_a_retelling_in_a_later_scene_does_not_move_a_death(self, book):
        path = os.path.join(book, 'reference', 'source', 'odyssey', 'commitments.csv')
        with open(path) as f:
            text = f.read()
        _write(book, {'reference/source/odyssey/commitments.csv': text + (
            'leodes-early|minerva-visits|knowledge||Telemachus killed Leodes first||\n')})
        assert _fills(source_deaths.plan_deaths(book))['leodes'] == 'door-again'

    def test_a_death_in_a_cut_scene_is_a_problem_not_a_fill(self, book):
        _write(book, {'reference/source-map.csv': BOOK_MAP.replace(
            'assembly|assembly-called|dramatize|\n', '|assembly-called|cut|told later\n')})
        plan = source_deaths.plan_deaths(book)
        assert 'phemius' not in _fills(plan) and 'pisander-slain' not in _fills(plan)
        assert any('phemius' in p and 'cuts' in p for p in plan.problems)

    def test_an_authors_value_is_kept_and_a_disagreement_said(self, book):
        _write(book, {'reference/characters.csv': _book_characters(
            {'leodes': 'after', 'mentes': 'at-the-door'})})
        plan = source_deaths.plan_deaths(book)
        assert 'leodes' not in _fills(plan) and 'mentes' not in _fills(plan)
        # at-the-door adapts Mentes' death scene too: no problem
        assert [p for p in plan.problems if 'mentes' in p] == []
        assert any('leodes death_scene after' in p and 'sailing' in p for p in plan.problems)

    def test_free_mode_and_no_map_are_said(self, book):
        os.remove(os.path.join(book, 'reference', 'source-map.csv'))
        plan = source_deaths.plan_deaths(book)
        assert plan.fills == () and any('no reference/source-map.csv' in n for n in plan.notes)
        _write(book, {'storyforge.yaml': YAML.format(extra='  mode: free')})
        plan = source_deaths.plan_deaths(book)
        assert plan.fills == () and any('free mode' in n for n in plan.notes)

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
        assert any('outside the adapted range' in n for n in plan.notes)

    def test_no_death_scene_column_is_a_problem(self, book):
        _write(book, {'reference/characters.csv': 'id|name\nleodes|Leodes\n'})
        plan = source_deaths.plan_deaths(book)
        assert plan.fills == () and any('no death_scene column' in p for p in plan.problems)

    def test_a_source_death_scene_that_is_no_scene_is_a_problem(self, book):
        path = os.path.join(book, 'reference', 'source', 'odyssey', 'characters.csv')
        with open(path) as f:
            text = f.read()
        _write(book, {'reference/source/odyssey/characters.csv':
                      text.replace('minerva-visits', 'no-such-scene')})
        plan = source_deaths.plan_deaths(book)
        assert 'mentes' not in _fills(plan)
        assert any('no-such-scene' in p and 'not a scene of the source' in p
                   for p in plan.problems)


class TestApplyAndLife:
    """The acceptance: a character acting after their mapped death scene is
    flagged; a namesake is not."""

    def test_fills_write_only_blank_cells(self, book):
        plan = source_deaths.plan_deaths(book)
        done = source_deaths.apply_fills(book, plan.fills)
        assert {f.who for f in done} == set(_fills(plan))
        rows = {d.who: d.scene_id for d in typed_state.registry_deaths(book)}
        assert rows == _fills(plan)
        # a second plan has nothing left to fill
        assert source_deaths.plan_deaths(book).fills == ()

    def test_presence_after_the_filled_death_is_flagged_and_a_namesake_is_not(self, book):
        plan = source_deaths.plan_deaths(book)
        source_deaths.apply_fills(book, plan.fills)
        from storyforge.elaborate import _read_csv
        from storyforge.enrich import load_alias_map
        path = os.path.join(book, 'reference', 'characters.csv')
        chars = _read_csv(path)
        order = {r['id']: n for n, r in enumerate(_read_csv(
            os.path.join(book, 'reference', 'scenes.csv')))}
        scenes = {r['id']: r for r in _read_csv(os.path.join(book, 'reference', 'scenes.csv'))}

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
    def test_what_cleanup_cant_fill_is_in_its_report(self, book):
        from storyforge import cmd_cleanup
        _write(book, {'reference/source-map.csv': BOOK_MAP.replace(
            'assembly|assembly-called|dramatize|\n', '|assembly-called|cut|told later\n')})
        found = cmd_cleanup._check_source_deaths(book)
        assert found and all(f['type'] == 'source_death' and f['severity'] == 'warning'
                             for f in found)
        assert any('phemius' in f['detail'] for f in found)
        assert all('|' not in f['detail'] for f in found)
        report = cmd_cleanup.build_cleanup_report(book)
        assert any(f['type'] == 'source_death' for f in report['findings'])

    def test_the_step_fills_and_says_what_it_did_not_read(self, book):
        from storyforge import cmd_cleanup
        step = cmd_cleanup.plan_death_scenes(book)
        assert len(step.changes) == 4 and step.summary is not None   # the shared-name note
        assert {c.did for c in step.apply()} == {c.did for c in step.changes}
        assert cmd_cleanup.plan_death_scenes(book).changes == ()

    def test_with_nothing_read_the_step_says_why(self, book):
        from storyforge import cmd_cleanup
        os.remove(os.path.join(book, 'reference', 'source-map.csv'))
        step = cmd_cleanup.plan_death_scenes(book)
        assert step.changes == () and 'source-map.csv' in step.summary.would

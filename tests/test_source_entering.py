"""A scene's entering state from the source's fact ledger (#747): who is
dead, wounded or healed, and who has whose armour, before the source scenes
it adapts, for the drafting prompt and for the source check's ruling. The
two acceptance cases are modelled on the Iliad's ledger: Patroclus in
Achilles's armour entering the fire at the ships, and the healing of Aeneas
in front of the ruling on "Aeneas back at the front"."""

import json
import os
from unittest.mock import patch

import pytest

from storyforge import gate_source, source
from storyforge.checker import Finding
from storyforge.prompts_source import drafting_section, entering_section

YAML = """project:
  title: "Wrath"
  medium: novel
phase: drafting

source:
  projects:
    - slug: iliad
      path: ../iliad
  mode: faithful
"""

ARMOUR = "Wears Achilles' armour, and is taken for Achilles."
HIP = "Diomedes's stone crushed the joint of Aeneas' hip."
HEALED = 'Apollo, Leto and Artemis healed Aeneas in Pergamus, and he rejoined the Trojans.'
HEALED_QUOTE = 'they healed him and made him glorious to behold'

#: The imported source (the import has already mapped its names)
SOURCE = {
    'scenes.csv': ('id|seq|title\n'
                   's-hip|1|The Hip\n'
                   's-heal|2|The Healing\n'
                   's-arm|3|The Arming\n'
                   's-fire|4|The Fire\n'
                   's-death|5|The Death\n'),
    'characters.csv': ('id|name|aliases\n'
                       'patroclus|Patroclus|\n'
                       'achilles|Achilles|Pelides\n'
                       'aeneas|Aeneas|\n'
                       'diomedes|Diomedes|\n'
                       'hector|Hector|\n'
                       'priam|Priam|\n'
                       'automedon|Automedon|\n'),
    'scene-intent.csv': ('id|function|on_stage\n'
                         's-hip|x|diomedes;aeneas\n'
                         's-heal|x|aeneas;diomedes\n'
                         's-arm|x|patroclus;achilles\n'
                         's-fire|x|patroclus;automedon;hector\n'
                         's-death|x|patroclus;hector\n'),
    'commitments.csv': (
        'id|scene_id|type|subject|statement|quote|status|category|resolves\n'
        f'hip|s-hip|physical|aeneas|{HIP}|The stone crushed this joint|binding||\n'
        'kills|s-hip|physical|aeneas|Aeneas killed Crethon and Orsilochus.||binding||\n'
        "son|s-hip|physical||Teucer's arrow killed Priam's son Gorgythion.||binding||\n"
        'shoulder|s-hip|physical|diomedes|An arrow wound in his right shoulder.||binding|'
        'injury|s-heal\n'
        f'healed|s-heal|knowledge||{HEALED}|{HEALED_QUOTE}|binding||\n'
        f'armour|s-arm|physical|patroclus|{ARMOUR}||binding|equipment|s-death\n'
        "vow|s-arm|promise|achilles|Achilles vows to bring back Hector's armour.||binding||\n"
        'spear|s-arm|physical|hector|Hector held his spear by the middle.||binding||\n'
        'dropped|s-arm|physical|patroclus|Patroclus lost an old wound.||rejected||\n'
        'dead|s-death|physical|patroclus|Patroclus is dead, speared by Hector.||binding|'
        'injury|never\n'),
}

SOURCE_PROSE = {
    's-heal': f'Then Leto and Artemis, {HEALED_QUOTE}, in the great sanctuary.',
    's-fire': 'Patroclus drove them from the ship and put out the fire.',
}

BOOK = {
    'storyforge.yaml': YAML,
    'reference/scenes.csv': ('id|seq|title|pov\n'
                             'patroclus-quenches-the-fire|1|Fire|patroclus\n'
                             'aeneas-back-at-the-front|2|Back|diomedes\n'
                             'priam-waits|3|Waits|priam\n'),
    'reference/scene-intent.csv': ('id|function|on_stage\n'
                                   'patroclus-quenches-the-fire|x|patroclus;automedon\n'
                                   'aeneas-back-at-the-front|x|\n'
                                   'priam-waits|x|priam\n'),
    'reference/source-map.csv': ('scene_id|source_scenes|treatment|note\n'
                                 'patroclus-quenches-the-fire|s-fire|dramatize|\n'
                                 'aeneas-back-at-the-front|s-heal|dramatize|\n'
                                 'priam-waits|s-fire|dramatize|\n'),
}


def _write(base, files):
    for rel, text in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)


@pytest.fixture
def book(tmp_path):
    proj = str(tmp_path / 'wrath')
    _write(proj, BOOK)
    _write(os.path.join(proj, 'reference', 'source', 'iliad'),
           {**SOURCE, **{f'scenes/{k}.md': v for k, v in SOURCE_PROSE.items()}})
    gate_source._MEMO.clear()
    return proj


FIRE = [('iliad', 's-fire')]
HEAL = [('iliad', 's-heal')]


def _ids(state):
    return [f.fact_id for f in state.facts]


# ---- what counts -----------------------------------------------------------

@pytest.mark.parametrize('row, kind', [
    ({'type': 'physical', 'category': 'equipment', 'statement': 'Has yoked the horses.'}, 'arms'),
    ({'type': 'knowledge', 'statement': 'Achilles lends Patroclus his armour.'}, 'arms'),
    ({'type': 'physical', 'statement': "Hector currently bears Achilles' armour."}, 'arms'),
    ({'type': 'physical', 'statement': 'Hector held his spear by the middle.'}, ''),
    ({'type': 'physical', 'statement': 'Menelaus gave his sword to Odysseus.'}, 'arms'),
    ({'type': 'physical', 'category': 'injury', 'statement': 'A gash in the arm.'}, 'wound'),
    ({'type': 'physical', 'statement': "The stone crushed Aeneas' hip."}, 'wound'),
    ({'type': 'world', 'statement': 'Patroclus is dead.'}, 'death'),
    ({'type': 'knowledge', 'statement': 'Apollo healed Aeneas.'}, 'healing'),
    ({'type': 'promise', 'statement': "He vows to strip Hector's armour."}, ''),
    ({'type': 'relationship', 'statement': 'Glaucus killed many beside him.'}, ''),
    ({'type': 'knowledge', 'category': 'motive-intent',
      'statement': 'Nestor urges him to fight in the armour.'}, ''),
    ({'type': 'physical', 'statement': 'He sat by the ships and wept.'}, ''),
])
def test_fact_kind(row, kind):
    assert source.fact_kind(row) == kind


# ---- the acceptance cases --------------------------------------------------

def test_patroclus_enters_the_fire_in_achilles_armour(book):
    """#747 acceptance: the entering state for `patroclus-quenches-the-fire`
    names Patroclus in Achilles's armour."""
    cast = source.scene_cast(book, 'patroclus-quenches-the-fire', FIRE)
    assert cast == {'patroclus', 'automedon'}
    state = source.entering_state(book, FIRE, cast)
    assert _ids(state) == ['armour']
    assert state.facts[0].who == ('patroclus',) and state.facts[0].ends == 's-death'
    text = drafting_section(book, 'patroclus-quenches-the-fire')
    assert '#### Entering state' in text
    assert f's-arm (arms): {ARMOUR} [until s-death]' in text
    # after the passage it enters
    assert text.index('#### Entering state') > text.index('put out the fire')


def test_the_ruling_on_aeneas_back_at_the_front_is_handed_the_healing(book):
    """#747 acceptance: the source check, ruling on "Aeneas back at the
    front", is handed the healing fact, told in this scene's own source."""
    finding = Finding(kind='contradiction', code='PHY',
                      scene_quote='Aeneas was back at the front, shouting',
                      established_scene='aeneas-felled', established_quote="crushed Aeneas' hip",
                      fact_id='', explanation='a crushed hip cannot fight')
    ctx = gate_source.setup(book)
    assert ctx.active() and ctx.refs['aeneas-back-at-the-front'] == HEAL
    sent = []

    def fake(prompt, model, log_file, max_tokens, **kw):
        sent.append(prompt)
        return {'content': [{'type': 'text', 'text': json.dumps(
            {'facts': [], 'contradictions': [], 'findings': [
                {'n': 1, 'verdict': 'source-has-it', 'source_quote': HEALED_QUOTE,
                 'why': 'the source heals him'}]})}], 'stop_reason': 'end_turn'}
    with patch('storyforge.api.invoke_to_file', side_effect=fake):
        review = gate_source.review(book, 'aeneas-back-at-the-front', 'Aeneas was back.', [],
                                    [], model='m', log_file=os.path.join(book, 'l.json'),
                                    ctx=ctx, findings=[finding])
    prompt = sent[0]
    assert "## The source's facts on these people" in prompt
    section = prompt.split("## The source's facts on these people")[1].split('## Scene')[0]
    assert f's-heal (healing): {HEALED} (the source: "{HEALED_QUOTE}")' in section
    assert f's-hip (wound): {HIP}' in section
    assert section.index('s-hip') < section.index('s-heal')   # oldest first
    assert 'Crethon' not in section   # his doing, not his state
    # the quote is still checked against the source prose
    assert review.has_it == [(0, HEALED_QUOTE, 'the source heals him')]


# ---- position, ends and whose fact -----------------------------------------

def test_entering_is_before_the_passage_and_through_takes_it_in(book):
    state = source.entering_state(book, HEAL, {'aeneas'})
    assert _ids(state) == ['hip']
    assert _ids(source.entering_state(book, HEAL, {'aeneas'}, through=True)) == ['hip', 'healed']


def test_a_state_ended_before_the_passage_is_left_out(book):
    """Diomedes's shoulder wound ends at s-heal: gone by the fire."""
    assert _ids(source.entering_state(book, HEAL, {'diomedes'})) == ['shoulder']
    assert _ids(source.entering_state(book, FIRE, {'diomedes'})) == []


def test_a_doers_kills_and_a_relatives_death_are_not_their_state(book):
    """"Aeneas killed Crethon" is nothing about Aeneas; "Priam's son
    Gorgythion" is not Priam. A promise, a held spear and a rejected row
    are no state either."""
    state = source.entering_state(book, FIRE, {'aeneas', 'priam', 'hector', 'achilles'})
    assert _ids(state) == ['hip', 'healed', 'armour']
    assert [f.who for f in state.facts] == [('aeneas',), ('aeneas',), ('achilles',)]


def test_the_latest_facts_are_kept(book, monkeypatch):
    monkeypatch.setattr(source, 'ENTERING_PER_PERSON', 1)
    state = source.entering_state(book, HEAL, {'aeneas'}, through=True)
    assert _ids(state) == ['healed'] and state.left_out == 1
    assert _ids(source.entering_state(book, HEAL, {'aeneas'}, through=True, limit=0)) == []


def test_the_book_scenes_cast_wins_over_the_sources(book):
    """A battle's source scene has every fighter on stage: the book scene's
    own `on_stage` is used, the source's only when it has none."""
    assert source.scene_cast(book, 'aeneas-back-at-the-front', HEAL) == {'diomedes', 'aeneas'}
    assert 'hector' not in source.scene_cast(book, 'patroclus-quenches-the-fire', FIRE)


# ---- what is said ----------------------------------------------------------

def test_a_scene_with_nothing_to_carry_has_no_section(book):
    assert entering_section(book, 'priam-waits', FIRE) == ''
    assert '#### Entering state' not in drafting_section(book, 'priam-waits')


def test_a_source_without_a_ledger_is_said(book, capsys):
    os.remove(os.path.join(book, 'reference', 'source', 'iliad', 'commitments.csv'))
    assert entering_section(book, 'patroclus-quenches-the-fire', FIRE) == ''
    assert 'WARNING: patroclus-quenches-the-fire: source iliad has no fact ledger' \
        in capsys.readouterr().out
    notes = []
    finding = Finding('contradiction', 'PHY', 'Aeneas fights', '', '', '', 'hip')
    assert gate_source._source_facts(book, 'aeneas-back-at-the-front', HEAL, [], [finding],
                                     notes) == []
    assert notes and 'no fact ledger' in notes[0]


def test_facts_left_out_are_said(book, capsys, monkeypatch):
    real = source.entering_state
    monkeypatch.setattr(source, 'entering_state', lambda *a, **k: source.EnteringState(
        real(*a, **k).facts, left_out=3))
    text = entering_section(book, 'patroclus-quenches-the-fire', FIRE)
    assert 'The latest 1 are given; 3 older ones are left out.' in text
    assert '3 older source facts about its people left out' in capsys.readouterr().out


def test_an_unreadable_ledger_is_a_note_and_the_ruling_goes_on(book):
    with open(os.path.join(book, 'reference', 'source', 'iliad', 'commitments.csv'), 'a',
              encoding='utf-8') as f:
        f.write('broken|row\n')
    notes = []
    finding = Finding('contradiction', 'PHY', 'Aeneas fights', '', '', '', 'hip')
    assert gate_source._source_facts(book, 'aeneas-back-at-the-front', HEAL, [], [finding],
                                     notes) == []
    assert 'could not be read' in notes[0]


def test_with_nothing_to_rule_on_no_facts_are_read(book):
    notes = []
    assert gate_source._source_facts(book, 'aeneas-back-at-the-front', HEAL, [], [], notes) == []
    assert notes == []


def test_a_finding_naming_nobody_falls_back_to_the_scenes_cast(book):
    notes = []
    finding = Finding('contradiction', 'PHY', 'he fights', '', '', '', 'a hip')
    lines = gate_source._source_facts(book, 'aeneas-back-at-the-front', HEAL, [], [finding],
                                      notes)
    assert any(HEALED in line for line in lines) and notes == []


def test_without_source_facts_the_prompt_is_unchanged():
    args = ('sc', 'prose', [], [], 'SRC', {}, '', 'adapt', '')
    assert gate_source.build_prompt(*args) == gate_source.build_prompt(*args, source_facts=[])
    assert "facts on these people" not in gate_source.build_prompt(*args)


# ---- #747's review ---------------------------------------------------------

def _names(*people):
    return {p.split(':')[0]: source._name_pattern([p.split(':')[-1]]) for p in people}


NAMES = _names('rhesus:Rhesus', 'diomedes:Diomed', 'machaon:Machaon', 'paris:Paris',
               'aeneas:Aeneas', 'patroclus:Patroclus', 'euphorbus:Euphorbus',
               'hector:Hector', 'priam:Priam', 'eurypylus:Eurypylus', 'tydeus:Tydeus',
               'maeon:Maeon', 'apollo:Apollo', 'achilles:Achilles', 'pandarus:Pandarus',
               'ajax:Ajax', 'teucer:Teucer')


@pytest.mark.parametrize('statement, subject, category, kind, cast, who', [
    # CR-1, SF-1: passives, with and without "by" right after the verb
    ('Rhesus was killed in his sleep by Diomed.', 'rhesus', '', 'death',
     {'rhesus', 'diomedes'}, ('rhesus',)),
    ('Machaon has been wounded and is carried from the field.', 'machaon', '', 'wound',
     {'machaon'}, ('machaon',)),
    ("Wounded in the right shoulder by Paris' arrow.", 'machaon', 'injury', 'wound',
     {'machaon', 'paris'}, ('machaon',)),
    ('Aeneas was wounded in the hip by Diomed.', 'aeneas', '', 'wound',
     {'aeneas', 'diomedes'}, ('aeneas',)),
    ("Aeneas's hip was crushed.", 'aeneas', 'injury', 'wound', {'aeneas'}, ('aeneas',)),
    ('Patroclus is dead, speared in the back by Euphorbus.', 'patroclus', 'injury', 'death',
     {'patroclus', 'euphorbus'}, ('patroclus',)),
    # active: the one it happens to, never the doer
    ('Hector killed Patroclus.', 'hector', '', 'death', {'hector', 'patroclus'},
     ('patroclus',)),
    ('Aeneas killed Crethon.', 'aeneas', '', 'death', {'aeneas'}, ()),
    ("Teucer killed Priam's son Gorgythion.", '', '', 'death', {'priam', 'teucer'}, ()),
    ('Ajax killed the son of Priam.', '', '', 'death', {'priam', 'ajax'}, ()),
    ('Tydeus slew the ambush led by Maeon.', 'tydeus', '', 'death', {'tydeus', 'maeon'}, ()),
    ('Diomed killed Pandarus by driving a spear through his nose.', 'diomedes', '', 'death',
     {'diomedes', 'pandarus'}, ('pandarus',)),
    ("Paris' arrow struck his right thigh.", 'eurypylus', 'injury', 'wound',
     {'eurypylus', 'paris'}, ('eurypylus',)),
    # CR-5: the healer is never the one healed
    ('Apollo healed Aeneas.', '', '', 'healing', {'apollo', 'aeneas'}, ('aeneas',)),
    ('Aeneas is healed by Apollo.', '', '', 'healing', {'apollo', 'aeneas'}, ('aeneas',)),
    ('Was healed and made whole.', 'aeneas', '', 'healing', {'aeneas'}, ('aeneas',)),
    ('Achilles lends Patroclus his armour.', 'achilles', '', 'arms',
     {'achilles', 'patroclus'}, ('achilles', 'patroclus')),
])
def test_whose_fact(statement, subject, category, kind, cast, who):
    row = {'statement': statement, 'subject': subject, 'category': category}
    assert source._about(row, kind, cast, NAMES) == who


@pytest.mark.parametrize('row, kind', [
    # T-5: a motive is no state, even one that would be armour
    ({'type': 'knowledge', 'category': 'motive-intent',
      'statement': 'Nestor urges him to put on the armour.'}, ''),
    # T-7: a healing wins over a death in the same words
    ({'type': 'world', 'statement': 'Apollo healed the wounds of the dead Sarpedon.'},
     'healing'),
    ({'type': 'physical', 'statement': 'Hector corpse bears fresh spear wounds.'}, 'death'),
])
def test_fact_kind_more(row, kind):
    assert source.fact_kind(row) == kind


def _ledger(book, rows, header='id|scene_id|type|subject|statement|quote|status|category|'
                               'resolves|supersedes'):
    with open(os.path.join(book, 'reference', 'source', 'iliad', 'commitments.csv'), 'w',
              encoding='utf-8') as f:
        f.write(header + '\n' + '\n'.join(rows) + '\n')


def test_two_source_scenes_start_at_the_first_and_through_ends_at_the_last(book):
    """T-1: the cut is the earliest of the scene's source scenes, whatever
    order the map lists them in; `through` reaches the last."""
    refs = [('iliad', 's-fire'), ('iliad', 's-heal')]
    assert _ids(source.entering_state(book, refs, {'aeneas', 'patroclus'})) == ['hip']
    assert _ids(source.entering_state(book, refs, {'aeneas', 'patroclus'}, through=True)) \
        == ['hip', 'healed', 'armour']


def test_a_superseded_fact_is_no_longer_the_state(book):
    """CR-4: a fact superseded by one told by then is left out."""
    _ledger(book, ['own|s-hip|physical|patroclus|Wears his own armour.||binding|equipment||',
                   'theirs|s-arm|physical|patroclus|Wears borrowed armour.||binding|'
                   'equipment||own'])
    assert _ids(source.entering_state(book, FIRE, {'patroclus'})) == ['theirs']
    assert _ids(source.entering_state(book, [('iliad', 's-arm')], {'patroclus'})) == ['own']


def test_facts_come_oldest_first_whatever_the_file_order(book):
    _ledger(book, ['b|s-arm|physical|patroclus|Wears new armour.||binding|equipment||',
                   'a|s-hip|physical|patroclus|Wears old armour.||binding|equipment||'])
    assert _ids(source.entering_state(book, FIRE, {'patroclus'})) == ['a', 'b']


def test_never_and_an_unknown_end(book):
    """T-6: `never` is no end; an end the source hasn't got is shown."""
    _ledger(book, ['a|s-hip|physical|patroclus|Wears old armour.||binding|equipment|never|',
                   'b|s-arm|physical|patroclus|Wears new armour.||binding|equipment|nowhere|'])
    state = source.entering_state(book, FIRE, {'patroclus'})
    assert [f.ends for f in state.facts] == ['', 'nowhere']
    from storyforge.prompts_source import entering_lines
    lines = entering_lines(state.facts)
    assert '[until' not in lines[0] and lines[1].endswith('[until nowhere]')


def test_the_newest_are_kept_under_the_cap(book, monkeypatch):
    """T-4: `limit` and `ENTERING_MAX` keep the newest."""
    state = source.entering_state(book, HEAL, {'aeneas'}, through=True, limit=1)
    assert _ids(state) == ['healed'] and state.left_out == 1
    monkeypatch.setattr(source, 'ENTERING_MAX', 1)
    assert _ids(source.entering_state(book, HEAL, {'aeneas'}, through=True)) == ['healed']


def _finding(quote='Aeneas fights', explanation='a hip', other=''):
    return Finding('contradiction', 'PHY', quote, '', other, '', explanation)


def test_the_ruling_gets_only_the_people_its_findings_name(book):
    """T-3: Diomedes is on stage, but the finding is about Aeneas."""
    lines = gate_source._source_facts(book, 'aeneas-back-at-the-front', HEAL, [],
                                      [_finding()], [])
    assert any(HEALED in line for line in lines)
    assert not any('shoulder' in line for line in lines)


def test_a_contradiction_alone_and_a_name_only_in_the_explanation_are_looked_up(book):
    lines = gate_source._source_facts(book, 'aeneas-back-at-the-front', HEAL,
                                      [_finding('he fights', "Aeneas's hip is crushed")], [],
                                      [])
    assert any(HEALED in line for line in lines)
    assert not any('shoulder' in line for line in lines)


def test_a_cut_list_says_it_is_partial(book, monkeypatch):
    """CR-2, SF-2: the ruling is told the list is partial, and so is the
    author."""
    monkeypatch.setattr(gate_source, 'MAX_SOURCE_FACTS', 1)
    notes = []
    lines = gate_source._source_facts(book, 'aeneas-back-at-the-front', HEAL, [],
                                      [_finding()], notes)
    assert lines[0].startswith('A partial list: 1 older fact(s)')
    assert len(lines) == 2 and HEALED in lines[1]
    assert notes == ['1 older source fact(s) on the people in the findings left out of '
                     'the ruling (the latest 1 were sent)']


def test_no_cast_is_said(book):
    """SF-3."""
    state = source.entering_state(book, FIRE, set())
    assert state.facts == [] and 'no one to look up' in state.notes[0]


def test_a_source_scene_with_no_seq_is_said_and_never_widens_the_span(book):
    """SF-4, CR-3: through a scene with no position is not through the
    rest of the ledger."""
    _write(os.path.join(book, 'reference', 'source', 'iliad'), {'scenes.csv': (
        'id|seq|title\ns-hip|1|a\ns-heal|2|b\ns-arm|3|c\ns-fire||d\ns-death|5|e\n')})
    state = source.entering_state(book, [('iliad', 's-heal'), ('iliad', 's-fire')],
                                  {'aeneas', 'patroclus'}, through=True)
    assert _ids(state) == ['hip', 'healed']
    assert any('s-fire has no seq' in n for n in state.notes)


def test_ledger_rows_on_no_known_scene_are_said(book):
    _ledger(book, ['a|s-gone|physical|patroclus|Wears old armour.||binding|equipment||',
                   'b|s-arm|physical|patroclus|Wears new armour.||binding|equipment||'])
    state = source.entering_state(book, FIRE, {'patroclus'})
    assert _ids(state) == ['b']
    assert any('1 ledger fact(s) name no source scene' in n for n in state.notes)


def test_a_cast_member_the_source_has_no_character_for_is_said(book):
    """SF-5."""
    state = source.entering_state(book, FIRE, {'patroclus', 'thersites'})
    assert any('no character thersites' in n for n in state.notes)


def test_the_pov_is_in_the_cast(book):
    """T-7."""
    _write(book, {'reference/scenes.csv': 'id|seq|title|pov\npriam-waits|3|Waits|hector\n'})
    assert source.scene_cast(book, 'priam-waits', FIRE) == {'hector', 'priam'}

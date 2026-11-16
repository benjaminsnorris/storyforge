"""An adaptation enters the ladder at the scene map (#658, plan D8): the
interpretation decisions, where a `source:` book enters, and status's route."""

import os

import pytest

from storyforge import adaptation, cmd_status, status

from source_helpers import YAML, _write, import_source, make_adaptation

DECISIONS = """
## Interpretation decisions

- **What this version is about:** a boy finds he can act without his father.
- **Whose eyes:** Telemachus, close third, throughout.
- **What's cut:** the gods' council is told, not shown.
- **What's invented:** a night with the nurse before he sails.
- **Where it ends:** the ship sails from Ithaca.
- **Mode:** faithful: every event of the span happens.
"""


def _decide(proj, text=DECISIONS):
    path = os.path.join(proj, 'reference', 'key-decisions.md')
    with open(path, encoding='utf-8') as f:
        old = f.read()
    _write(proj, {'reference/key-decisions.md': old + text})


def _map(proj, cuts):
    """A one-scene map adapting minerva-visits, plus `cuts` rows."""
    _write(proj, {
        'reference/scenes.csv': ('id|seq|title|summary|status|pov|location|timeline_day|'
                                 'time_of_day|duration\n'
                                 'athena-at-the-door|1|Door|Athena comes|mapped|telemachus|'
                                 'ithaca-hall|1|morning|1 hour\n'),
        'reference/source-map.csv': ('scene_id|source_scenes|treatment|note\n'
                                     'athena-at-the-door|minerva-visits|dramatize|\n' + cuts),
    })


def _voice(proj):
    _write(proj, {'reference/voice/book.md': '# The voice\n\nShort, plain sentences.\n',
                  'reference/voice/anchors/a.md': 'He ran.\n'})


@pytest.fixture
def adapted(tmp_path):
    return make_adaptation(tmp_path)


# ----------------------------------------------------------------------------
# The decisions
# ----------------------------------------------------------------------------

def _parse(body, heading='## Interpretation decisions'):
    return adaptation.parse_decisions(f'{heading}\n\n{body}\n')


class TestParseDecisions:
    def test_labelled_lines(self):
        p = adaptation.parse_decisions(DECISIONS)
        assert p.has_section and set(p.found) == {k for k, _ in adaptation.DECISIONS}
        assert p.found['eyes'] == 'Telemachus, close third, throughout.'
        assert p.found['mode'].startswith('faithful')

    def test_sub_headings_and_continued_lines(self):
        text = ('## Interpretation Decisions\n\n### What this version is about\n\nA boy.\n'
                'He grows up.\n\n### Whose eyes\n\nHis.\n\n## Settings\n\n- Cut: nothing\n')
        p = adaptation.parse_decisions(text)
        assert p.has_section
        assert p.found == {'about': 'A boy. He grows up.', 'eyes': 'His.'}   # Settings ends it

    @pytest.mark.parametrize('value', ['', '<who tells it>', 'TBD', '...', '**', '[TBD]',
                                       'N/A', '?', 'TBD: decide after import',
                                       '<pick> later', 'todo'])
    def test_an_empty_or_placeholder_value_is_not_recorded(self, value):
        """SF-2/CR-3: placeholders were read as decisions."""
        p = _parse(f'- **Whose eyes:** {value}')
        assert 'eyes' not in p.found
        if value.strip('*'):
            assert p.placeholders['eyes'] == value

    @pytest.mark.parametrize('body', [
        '- **Whose eyes:**\n  <!-- one line:\n       who holds the camera -->',
        '### Whose eyes\n\n<!-- who holds\nthe camera -->',
        '- **Whose eyes:** <!-- Hector? -->',
    ])
    def test_a_comment_is_not_a_decision(self, body):
        """SF-2/CR-3: a value that was only an HTML comment counted."""
        assert 'eyes' not in _parse(body).found

    def test_short_labels_and_plain_lines(self):
        text = ('About: grief\nPOV: Achilles\nCuts: the catalogue\n* Inventions: none\n'
                '**Ending**: the funeral\nmode: free\nNote: an aside under the mode\n')
        found = _parse(text).found
        assert found['about'] == 'grief' and found['eyes'] == 'Achilles'
        assert found['cut'] == 'the catalogue' and found['invented'] == 'none'
        assert found['ending'] == 'the funeral'
        assert found['mode'] == 'free Note: an aside under the mode'

    @pytest.mark.parametrize('line, key, value', [
        ('1. **Whose eyes:** Patroclus', 'eyes', 'Patroclus'),
        ('2) Whose eyes: Patroclus', 'eyes', 'Patroclus'),
        ('### What this book is about\n\nWrath.', 'about', 'Wrath.'),
        ('- **What this book is:** Wrath.', 'about', 'Wrath.'),
        ('- **Mode (faithful/free):** faithful', 'mode', 'faithful'),
        ('- **Whose eyes** — Patroclus', 'eyes', 'Patroclus'),
        ('- Whose eyes – Patroclus', 'eyes', 'Patroclus'),
        ('*Whose eyes:* Patroclus', 'eyes', 'Patroclus'),
        ('_Mode_: faithful', 'mode', 'faithful'),
        ('| Decision | Choice |\n|---|---|\n| Whose eyes | Patroclus |', 'eyes', 'Patroclus'),
    ])
    def test_the_forms_an_author_writes(self, line, key, value):
        """CR-2/SF-10: these read as missing."""
        assert _parse(line).found.get(key) == value

    def test_an_h1_section(self):
        p = _parse('- Whose eyes: Hector\n\n## Settings\n\n- Cut: x', heading='# Interpretation decisions')
        assert p.has_section and p.found == {'eyes': 'Hector'}

    def test_a_heading_in_a_code_fence_is_not_the_section(self):
        p = adaptation.parse_decisions('```\n## Interpretation decisions\n- Mode: free\n```\n')
        assert not p.has_section

    def test_a_label_naming_no_decision_is_kept_to_say(self):
        p = _parse('- **Theme:** grief\n- **Whose eyes:** Hector')
        assert p.unread == ('Theme',) and p.found == {'eyes': 'Hector'}

    def test_a_decision_given_twice_keeps_the_last(self):
        """SF-3: the first won, silently; an empty first entry hid a later one."""
        p = _parse('- **Whose eyes:** Achilles\n- **Mode:** free\n- **Whose eyes:** Hector')
        assert p.found['eyes'] == 'Hector' and p.repeated == {'eyes': 2}
        assert _parse('- **Whose eyes:**\n- **Whose eyes:** Hector').found['eyes'] == 'Hector'

    def test_an_indented_label_is_part_of_the_decision_above(self):
        """SF-4: a nested `Ending:` took over the ending."""
        p = _parse("- **What's invented:**\n  - A scene where\n  - Ending: Priam's dream\n"
                   "- **Where it ends:** Hector's funeral")
        assert p.found['ending'] == "Hector's funeral"
        assert "Priam's dream" in p.found['invented']
        q = _parse('### What this version is about\n\nWrath.\n  Cut: nothing else matters')
        assert 'cut' not in q.found and 'Cut: nothing' in q.found['about']

    def test_no_section(self):
        assert not adaptation.parse_decisions('# Key decisions\n\n## Version rules\n\nx\n'
                                              ).has_section


class TestReadDecisions:
    def test_missing_file_is_every_decision_missing(self, tmp_path):
        d = adaptation.read_decisions(str(tmp_path))
        assert not d.ok and len(d.missing) == len(adaptation.DECISIONS)
        assert 'has no `## Interpretation decisions` section' in d.summary()

    def test_missing_ones_are_named(self, adapted):
        _decide(adapted, DECISIONS.replace("- **What's invented:** a night with the nurse "
                                           "before he sails.\n", ''))
        d = adaptation.read_decisions(adapted, 'faithful')
        assert d.missing == ('invented',)
        assert "5 of 6 recorded; missing What's invented" in d.summary()

    def test_a_mode_disagreeing_with_the_yaml_is_a_problem(self, adapted):
        _decide(adapted)
        d = adaptation.read_decisions(adapted, 'free')
        assert not d.ok and 'says faithful' in d.summary() and 'source.mode is free' in d.summary()
        assert adaptation.read_decisions(adapted, 'faithful').ok

    def test_an_unreadable_file_is_a_problem(self, adapted):
        with open(os.path.join(adapted, 'reference', 'key-decisions.md'), 'wb') as f:
            f.write(b'\xff\xfe\x00bad')
        d = adaptation.read_decisions(adapted, 'faithful')
        assert not d.ok and "can't be read" in d.summary()


# ----------------------------------------------------------------------------
# Where a book enters
# ----------------------------------------------------------------------------

class TestEntry:
    def test_no_source_block_is_none(self, tmp_path):
        assert adaptation.entry(str(tmp_path)) is None

    def test_not_imported(self, adapted):
        e = adaptation.entry(adapted)
        assert e.enters_at_map and not e.ready and not e.imported
        assert any('not imported' in p for p in e.problems)

    def test_ready_once_imported_and_decided(self, adapted):
        import_source(adapted)
        assert not adaptation.entry(adapted).ready
        _decide(adapted)
        e = adaptation.entry(adapted)
        assert e.enters_at_map and e.ready and e.problems == ()

    @pytest.mark.parametrize('name, text', [
        ('spine.csv', 'id|seq|title\ne1|1|The suitors\n'),
        ('architecture.csv', 'id|seq|title\na1|1|The suitors\n'),
    ])
    def test_an_own_spine_or_architecture_is_the_full_ladder(self, adapted, name, text):
        import_source(adapted)
        _write(adapted, {f'reference/{name}': text})
        assert not adaptation.entry(adapted).enters_at_map

    def test_a_header_only_spine_is_not_its_own(self, adapted):
        _write(adapted, {'reference/spine.csv': 'id|seq|title\n'})
        assert adaptation.entry(adapted).enters_at_map

    def test_an_unusable_block_is_a_problem_not_a_crash(self, adapted):
        _write(adapted, {'storyforge.yaml': YAML.format(extra='  mode: loose')})
        e = adaptation.entry(adapted)
        assert not e.ready and "source: block can't be used" in e.problems[0]


# ----------------------------------------------------------------------------
# status
# ----------------------------------------------------------------------------

def _states(v):
    return {r['name']: r['state'] for r in v['ladder']}


class TestStatus:
    def test_not_imported_routes_to_the_import(self, adapted):
        v = status.build_status(adapted)
        assert v['phase'] == 'interpretation'
        assert v['next']['stage'] == 'interpretation'
        assert v['next']['command'] == 'storyforge source import'
        assert v['then']['stage'] == 'voice'
        assert [b['source'] for b in v['blockers']] == ['interpretation', 'interpretation']
        assert set(_states(v).values()) == {'not_started'}

    def test_imported_without_decisions_routes_to_the_decisions(self, adapted):
        import_source(adapted)
        v = status.build_status(adapted)
        assert v['phase'] == 'interpretation'
        assert v['next']['command'] == 'storyforge source status'
        assert 'Interpretation decisions' in v['next']['reason']
        assert 'has no `## Interpretation decisions` section' in v['blockers'][0]['detail']

    def test_ready_gives_the_upper_rungs_and_routes_to_voice_then_the_map(self, adapted):
        import_source(adapted)
        _decide(adapted)
        v = status.build_status(adapted)
        assert _states(v) == {'logline': 'given', 'synopsis': 'given', 'act-shape': 'given',
                              'spine': 'given', 'architecture': 'given',
                              'scene-map': 'not_started', 'briefs': 'not_started'}
        assert v['phase'] == 'voice'
        assert v['next']['command'] == 'storyforge elaborate --stage voice'
        # #656's voice step: the given rungs count as done, so the voice comes
        # before the scene map (the rung it would build)
        assert (v['then']['stage'], v['then']['command']) == (
            'scene-map', 'storyforge elaborate --stage map')
        assert 'voice sample --moment' in v['next']['reason']
        assert v['blockers'] == []
        assert v['phase_matches_yaml'] is True       # phase: spine, given counts as done
        text = cmd_status.render_human(v)
        assert 'L3 spine         ✓ given — from the source and the interpretation decisions' \
            in text

    def test_voice_stage_later_builds_the_map_first(self, adapted):
        """The author's `voice_stage: later` (#656) holds for an adaptation too."""
        import_source(adapted)
        _decide(adapted, DECISIONS + '\n## Settings\n\n- voice_stage: later\n')
        v = status.build_status(adapted)
        assert v['phase'] == 'scene-map'
        assert v['next']['command'] == 'storyforge elaborate --stage map'

    def test_with_a_voice_the_scene_map_is_next(self, adapted):
        import_source(adapted)
        _decide(adapted)
        _voice(adapted)
        v = status.build_status(adapted)
        assert v['phase'] == 'scene-map'
        assert v['next']['command'] == 'storyforge elaborate --stage map'
        assert v['then']['stage'] == 'briefs'
        assert v['blockers'] == []

    def test_a_logline_the_author_wrote_is_judged(self, adapted):
        import_source(adapted)
        _decide(adapted)
        _voice(adapted)
        _write(adapted, {'reference/story-summary.md': '## Logline\n' + 'word ' * 60 + '\n'})
        v = status.build_status(adapted)
        assert _states(v)['logline'] == 'thin' and _states(v)['synopsis'] == 'given'
        assert v['phase'] == 'logline'

    def test_coverage_between_given_rungs_is_not_asked(self, adapted):
        """An act shape the author wrote asks no spine of an adaptation."""
        import_source(adapted)
        _decide(adapted)
        _voice(adapted)
        _write(adapted, {'reference/story-summary.md': (
            '## Logline\nA boy sails.\n\n## Act-shape\n### Act 1\nHe sails.\n')})
        v = status.build_status(adapted)
        assert not [b for b in v['blockers'] if b['source'] == 'coverage']

    def test_the_full_ladder_with_a_spine_of_its_own(self, adapted):
        import_source(adapted)
        _decide(adapted)
        _write(adapted, {'reference/spine.csv': 'id|seq|title\ne1|1|The suitors\n'})
        v = status.build_status(adapted)
        assert _states(v)['logline'] == 'not_started'
        assert v['phase'] == 'logline' and v['next']['stage'] == 'logline'
        assert any('full ladder' in n for n in v['notes'])
        assert not any(b['source'] == 'interpretation' for b in v['blockers'])

    def test_no_source_block_is_unchanged(self, tmp_path):
        v = status.build_status(str(tmp_path))
        assert v['phase'] == 'logline' and v['notes'] == []

    @pytest.mark.parametrize('own_spine', [False, True])
    def test_source_coverage_is_a_blocker_once_the_map_exists(self, adapted, own_spine):
        """For a book entering at the map, and for a full-ladder one (decision 5)."""
        import_source(adapted)
        _decide(adapted)
        _voice(adapted)
        _map(adapted, '|gods-debate|cut|told in a line\n|assembly-called|cut|\n')
        if own_spine:
            _write(adapted, {'reference/spine.csv': 'id|seq|title\ne1|1|The suitors\n'})
        v = status.build_status(adapted)
        details = [b['detail'] for b in v['blockers'] if b['source'] == 'source']
        assert any('assembly-called is cut with no reason' in d for d in details)
        assert any('ship-sails is not in the source map' in d for d in details)
        assert (_states(v)['spine'] == 'given') is not own_spine

    def test_free_mode_gaps_are_a_note_not_a_blocker(self, adapted):
        """C-2: a dropped source scene blocks only in faithful mode."""
        _write(adapted, {'storyforge.yaml': YAML.format(extra='  mode: free')})
        import_source(adapted)
        _decide(adapted, DECISIONS.replace('faithful:', 'free:'))
        _voice(adapted)
        _map(adapted, '')
        v = status.build_status(adapted)
        assert not [b for b in v['blockers'] if b['source'] == 'source']
        assert any('advisory source-coverage finding' in n for n in v['notes'])

    def test_coverage_not_checked_is_said(self, adapted, monkeypatch):
        """SF-5/SF-9/T: the path that can't check says so, never blank."""
        import_source(adapted)
        _decide(adapted)
        _voice(adapted)
        _map(adapted, '|gods-debate|cut|x\n|assembly-called|cut|x\n|ship-sails|cut|x\n')

        def boom(*a, **k):
            raise RuntimeError('')
        monkeypatch.setattr('storyforge.source.check_coverage', boom)
        details = [b['detail'] for b in status.build_status(adapted)['blockers']
                   if b['source'] == 'source']
        assert details == ['source coverage not checked: RuntimeError']

    def test_a_map_without_a_source_map_is_not_checked_and_says_so(self, adapted):
        import_source(adapted)
        _decide(adapted)
        _voice(adapted)
        _map(adapted, '')
        os.remove(os.path.join(adapted, 'reference', 'source-map.csv'))
        details = [b['detail'] for b in status.build_status(adapted)['blockers']
                   if b['source'] == 'source']
        assert len(details) == 1 and details[0].startswith('source coverage not checked: ')
        assert 'source-map.csv' in details[0]

    def test_a_full_ladder_book_keeps_its_coverage_blockers(self, adapted):
        """T: coverage between rungs is dropped only for a book entering at the map."""
        import_source(adapted)
        _decide(adapted)
        _write(adapted, {
            'reference/story-summary.md': ('## Logline\nA boy sails.\n\n## Act-shape\n'
                                           '### Act 1\nHe sails.\n### Act 2\nHe returns.\n'),
            'reference/spine.csv': 'id|seq|title|act\ne1|1|The suitors|1\n',
        })
        v = status.build_status(adapted)
        assert [b for b in v['blockers'] if b['source'] == 'coverage' and b['level'] in (2, 3)]

    def test_a_broken_source_block_routes_to_fixing_it(self, adapted):
        """SF-8: it routed to `source import`, which fails on the same block."""
        _write(adapted, {'storyforge.yaml': YAML.format(extra='  mode: loose')})
        v = status.build_status(adapted)
        assert v['phase'] == 'interpretation'
        assert v['next']['command'] == 'storyforge source status'
        assert v['next']['action'] == "Fix storyforge.yaml's source: block"
        blockers = [b for b in v['blockers'] if b['source'] == 'interpretation']
        assert len(blockers) == 1 and "source: block can't be used" in blockers[0]['detail']

    def test_a_mode_mismatch_holds_the_rungs(self, adapted):
        """T: the source imported, the decisions there, the Mode the other one."""
        import_source(adapted)
        _decide(adapted, DECISIONS.replace('faithful:', 'free:'))
        v = status.build_status(adapted)
        assert v['phase'] == 'interpretation'
        assert v['next']['command'] == 'storyforge source status'
        assert _states(v)['spine'] == 'not_started'
        assert any('source.mode is faithful' in b['detail'] for b in v['blockers'])

    @pytest.mark.parametrize('setup, then_stage', [
        (lambda p: None, 'voice'),
        (_voice, 'scene-map'),
        (lambda p: _decide(p, '\n## Settings\n\n- voice_stage: later\n'), 'scene-map'),
    ])
    def test_the_step_after_the_decisions_follows_the_voice(self, adapted, setup, then_stage):
        """CR-1: it was always "Find the voice"."""
        import_source(adapted)
        setup(adapted)
        v = status.build_status(adapted)
        assert v['next']['stage'] == 'interpretation'
        assert v['then']['stage'] == then_stage

    def test_decision_notes_reach_status(self, adapted):
        """SF-3/SF-7: a decision given twice, a Mode that can't be compared."""
        import_source(adapted)
        _decide(adapted, DECISIONS.replace('faithful: every', 'mostly faithful: every')
                + '- **Whose eyes:** Telemachus, first person.\n')
        v = status.build_status(adapted)
        assert any('Whose eyes is given 2 times' in n for n in v['notes'])
        assert any("doesn't open with faithful or free" in n for n in v['notes'])
        assert _states(v)['spine'] == 'given'

    def test_a_placeholder_is_named_in_status(self, adapted):
        import_source(adapted)
        _decide(adapted, DECISIONS.replace('Telemachus, close third, throughout.', '[TBD]'))
        v = status.build_status(adapted)
        assert v['phase'] == 'interpretation'
        assert any("Whose eyes is a placeholder ('[TBD]')" in b['detail'] for b in v['blockers'])

    def test_a_graphic_novel_adaptation_gets_the_given_rungs(self, adapted):
        import_source(adapted)
        _decide(adapted)
        v = status.build_status(adapted, 'graphic-novel')
        assert [_states(v)[r] for r in ('logline', 'synopsis', 'act-shape', 'spine',
                                        'architecture')] == ['given'] * 5
        assert v['phase'] == 'scene-map'
        assert not [b for b in v['blockers'] if b['source'] == 'interpretation']

    def test_interpretation_is_a_recommendable_stage(self):
        nxt, then = status._recommend('interpretation')
        assert nxt == status.interpretation_step()
        assert nxt['command'] == 'storyforge source status' and then['stage'] == 'scene-map'


# ----------------------------------------------------------------------------
# The map prompt
# ----------------------------------------------------------------------------

def test_the_entry_section_is_only_for_a_book_entering_at_the_map(adapted, tmp_path):
    from storyforge.prompts_source import entry_section
    import_source(adapted)
    assert entry_section(adapted).startswith('### Entering at the scene map')
    assert 'whose eyes' in entry_section(adapted)
    _write(adapted, {'reference/architecture.csv': 'id|seq|title\na1|1|The suitors\n'})
    assert entry_section(adapted) == ''                    # the full ladder
    other = tmp_path / 'original'
    other.mkdir()
    assert entry_section(str(other)) == ''                 # no source: block

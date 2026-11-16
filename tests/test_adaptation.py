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


def _voice(proj):
    _write(proj, {'reference/voice/book.md': '# The voice\n\nShort, plain sentences.\n',
                  'reference/voice/anchors/a.md': 'He ran.\n'})


@pytest.fixture
def adapted(tmp_path):
    return make_adaptation(tmp_path)


# ----------------------------------------------------------------------------
# The decisions
# ----------------------------------------------------------------------------

class TestParseDecisions:
    def test_labelled_lines(self):
        has, found = adaptation.parse_decisions(DECISIONS)
        assert has and set(found) == {k for k, _ in adaptation.DECISIONS}
        assert found['eyes'] == 'Telemachus, close third, throughout.'
        assert found['mode'].startswith('faithful')

    def test_sub_headings_and_continued_lines(self):
        text = ('## Interpretation Decisions\n\n### What this version is about\n\nA boy.\n'
                'He grows up.\n\n### Whose eyes\n\nHis.\n\n## Settings\n\n- Cut: nothing\n')
        has, found = adaptation.parse_decisions(text)
        assert has
        assert found == {'about': 'A boy. He grows up.', 'eyes': 'His.'}   # Settings ends it

    @pytest.mark.parametrize('value', ['', '<who tells it>', 'TBD', '...', '**'])
    def test_an_empty_or_placeholder_value_is_not_recorded(self, value):
        _has, found = adaptation.parse_decisions(
            f'## Interpretation decisions\n\n- **Whose eyes:** {value}\n')
        assert 'eyes' not in found

    def test_short_labels_and_plain_lines(self):
        text = ('## Interpretation decisions\n\nAbout: grief\nPOV: Achilles\nCuts: the '
                'catalogue\n* Inventions: none\n**Ending**: the funeral\nmode: free\n'
                'Note: an aside under the mode\n')
        _has, found = adaptation.parse_decisions(text)
        assert found['about'] == 'grief' and found['eyes'] == 'Achilles'
        assert found['cut'] == 'the catalogue' and found['invented'] == 'none'
        assert found['ending'] == 'the funeral'
        assert found['mode'] == 'free Note: an aside under the mode'

    def test_no_section(self):
        assert adaptation.parse_decisions('# Key decisions\n\n## Version rules\n\nx\n') == \
            (False, {})


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
        assert e.higher and not e.ready and not e.imported
        assert any('not imported' in p for p in e.problems)

    def test_ready_once_imported_and_decided(self, adapted):
        import_source(adapted)
        assert not adaptation.entry(adapted).ready
        _decide(adapted)
        e = adaptation.entry(adapted)
        assert e.higher and e.ready and e.problems == ()

    @pytest.mark.parametrize('name, text', [
        ('spine.csv', 'id|seq|title\ne1|1|The suitors\n'),
        ('architecture.csv', 'id|seq|title\na1|1|The suitors\n'),
    ])
    def test_an_own_spine_or_architecture_is_the_full_ladder(self, adapted, name, text):
        import_source(adapted)
        _write(adapted, {f'reference/{name}': text})
        assert not adaptation.entry(adapted).higher

    def test_a_header_only_spine_is_not_its_own(self, adapted):
        _write(adapted, {'reference/spine.csv': 'id|seq|title\n'})
        assert adaptation.entry(adapted).higher

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
        assert v['then'] == {'stage': 'scene-map', 'action': 'Develop the scene-map',
                             'command': 'storyforge elaborate --stage map', 'reason': ''}
        assert 'before the scene map' in v['blockers'][0]['detail']
        assert v['phase_matches_yaml'] is True       # phase: spine, given counts as done
        text = cmd_status.render_human(v)
        assert 'L3 spine         ✓ given — from the source and the interpretation decisions' \
            in text

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

    def test_source_coverage_is_a_blocker_once_the_map_exists(self, adapted):
        import_source(adapted)
        _decide(adapted)
        _voice(adapted)
        _write(adapted, {
            'reference/scenes.csv': ('id|seq|title|status|pov|location|timeline_day|'
                                     'time_of_day|duration\n'
                                     'athena-at-the-door|1|Door|mapped|telemachus|ithaca-hall|'
                                     '1|morning|1 hour\n'),
            'reference/source-map.csv': ('scene_id|source_scenes|treatment|note\n'
                                         'athena-at-the-door|minerva-visits|dramatize|\n'
                                         '|gods-debate|cut|told in a line\n'
                                         '|assembly-called|cut|\n'),
        })
        v = status.build_status(adapted)
        details = [b['detail'] for b in v['blockers'] if b['source'] == 'source']
        assert any('assembly-called is cut with no reason' in d for d in details)
        assert any('ship-sails is not in the source map' in d for d in details)
        assert _states(v)['spine'] == 'given'

    def test_interpretation_is_a_recommendable_stage(self):
        nxt, then = status._recommend('interpretation')
        assert nxt['command'] == 'storyforge source status' and then['stage'] == 'voice'


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

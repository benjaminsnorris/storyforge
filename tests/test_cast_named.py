"""validate's `scene-cast-named` (#523): a scene whose own id names a
registry character that neither cast column lists. Extract phase 2 kept
casts to the POV-only character list, so `ulysses-reaches-eumaeus-hut` had
no Eumaeus and `iris-summons-helen-to-wall` no Iris. Advisory, and reported,
never repaired."""

import os

import pytest

from storyforge.elaborate import cast_named_gaps, validate_structure
from storyforge.source import INACTIVE_STATUSES


def _chars(*rows):
    out = []
    for row in rows:
        cid, name, *aliases = row
        out.append({'id': cid, 'name': name, 'aliases': ';'.join(aliases)})
    return out


def _report(scenes, characters):
    """*scenes*: id → (characters, on_stage[, pov[, status]])."""
    scenes_map, intent_map = {}, {}
    for sid, spec in scenes.items():
        chars, on_stage, pov, status = (list(spec) + ['', ''])[:4]
        scenes_map[sid] = {'id': sid, 'pov': pov, 'status': status}
        intent_map[sid] = {'id': sid, 'characters': chars, 'on_stage': on_stage}
    return cast_named_gaps(scenes_map, intent_map, characters)


def _gaps(scenes, characters):
    """The gaps, each shared name written ``a or b``."""
    return {sid: [' or '.join(ids) for ids in missing]
            for sid, missing in _report(scenes, characters).gaps.items()}


ODYSSEY = _chars(('ulysses', 'Ulysses', 'Odysseus'), ('eumaeus', 'Eumaeus'),
                 ('iris', 'Iris'), ('helen', 'Helen'), ('minerva', 'Minerva', 'Pallas Minerva'),
                 ('paris', 'Paris', 'Alexandrus'))


class TestCastNamedGaps:
    def test_a_named_character_missing_from_both_columns_is_reported(self):
        report = _report({
            'ulysses-reaches-eumaeus-hut': ('narrator;ulysses', 'narrator;ulysses'),
            'iris-summons-helen-to-wall': ('helen', 'helen'),
        }, ODYSSEY)
        assert report.gaps == {'ulysses-reaches-eumaeus-hut': [('eumaeus',)],
                               'iris-summons-helen-to-wall': [('iris',)]}
        assert (report.checked, report.uncast) == (2, 0)
        assert (report.unmatchable, report.idless) == ([], 0)

    def test_either_column_answers_and_names_and_aliases_resolve(self):
        gaps = _gaps({
            'ulysses-reaches-eumaeus-hut': ('Eumaeus', 'Odysseus'),
            'iris-summons-helen-to-wall': ('', 'iris;Helen'),
            'paris-challenges-the-greeks': ('Alexandrus', ''),
            'eumaeus-tends-the-swine': (' EUMAEUS ', ''),
        }, ODYSSEY)
        assert gaps == {}

    def test_the_pov_counts_as_present_by_id_or_name(self):
        gaps = _gaps({'eumaeus-tends-the-pigs': ('ulysses', 'ulysses', 'eumaeus'),
                      'eumaeus-feeds-the-dogs': ('ulysses', 'ulysses', 'Eumaeus')},
                     ODYSSEY)
        assert gaps == {}

    def test_whole_words_only(self):
        chars = _chars(('pell', 'Pell'), ('ann', 'Ann'))
        gaps = _gaps({
            'spell-breaks': ('x', 'x'),
            'annual-feast': ('x', 'x'),
            'pell-runs': ('x', 'x'),
        }, chars)
        assert gaps == {'pell-runs': ['pell']}

    def test_a_possessive_word_names_the_character(self):
        chars = ODYSSEY + _chars(('vey', 'Old Mother Vey'))
        gaps = _gaps({'footrace-ulysses-wins-with-minervas': ('ulysses', 'ulysses'),
                      'old-mother-veys-hut': ('ulysses', 'ulysses')}, chars)
        assert gaps == {'footrace-ulysses-wins-with-minervas': ['minerva'],
                        'old-mother-veys-hut': ['vey']}

    def test_multi_word_names_match_as_a_run(self):
        chars = _chars(('vey', 'Old Mother Vey'))
        gaps = _gaps({'old-mother-vey-dies': ('x', 'x'),
                      'old-mother-weeps': ('x', 'x')}, chars)
        assert gaps == {'old-mother-vey-dies': ['vey']}

    def test_one_character_named_twice_is_reported_once(self):
        gaps = _gaps({'pallas-minerva-appears': ('ulysses', '')}, ODYSSEY)
        assert gaps == {'pallas-minerva-appears': ['minerva']}

    def test_short_and_common_words_are_not_names(self):
        """An alias like "the King" or "Sleep", or a name like "Io", is too
        common (or short) in scene ids to read as the person; the filter
        is on whole keys, so "King Alcinous" still matches."""
        chars = _chars(('alcinous', 'Alcinous', 'the King', 'King', 'King Alcinous'),
                       ('io', 'Io'), ('hypnos', 'Sleep', 'Hypnos'))
        gaps = _gaps({
            'king-feasts-the-guest': ('x', 'x'),
            'the-king-feasts': ('x', 'x'),
            'io-wanders': ('x', 'x'),
            'argives-sup-and-sleep': ('x', 'x'),
            'hypnos-lulls-zeus': ('x', 'x'),
            'king-alcinous-feasts': ('x', 'x'),
        }, chars)
        assert gaps == {'hypnos-lulls-zeus': ['hypnos'], 'king-alcinous-feasts': ['alcinous']}

    def test_characters_no_scene_id_can_name_are_counted(self):
        report = _report({'grace-leaves': ('x', 'x')},
                         _chars(('grace', 'Grace'), ('io', 'Io'), ('pell', 'Pell'))
                         + [{'id': '', 'name': 'Argos', 'aliases': ''}])
        assert report.gaps == {}
        assert report.unmatchable == ['grace', 'io'] and report.idless == 1

    def test_someone_whose_id_begins_with_the_name_answers_it(self):
        """Quintus has `aias` and `aias-son-of-oileus`: a scene id's "aias"
        is answered by either in the cast, but a shorter name never answers
        a longer one."""
        chars = _chars(('aias', 'Aias'), ('aias-son-of-oileus', 'Aias son of Oileus'))
        gaps = _gaps({
            'aias-struggles-and-dies': ('aias-son-of-oileus;poseidon', 'poseidon'),
            'aias-holds-the-ships': ('hector', 'hector'),
            'aias-son-of-oileus-drowns': ('aias', ''),
        }, chars)
        assert gaps == {'aias-holds-the-ships': ['aias'],
                        'aias-son-of-oileus-drowns': ['aias-son-of-oileus']}

    def test_another_persons_alias_never_answers_for_someone(self):
        """Aliases name other people ("Hector's wife", "son of Peleus"):
        Andromache in the cast doesn't put Hector there."""
        chars = _chars(('hector', 'Hector'), ('andromache', 'Andromache', "Hector's wife"),
                       ('peleus', 'Peleus'), ('achilles', 'Achilles', 'son of Peleus'))
        gaps = _gaps({'hector-scolds-paris': ('andromache', 'andromache'),
                      'peleus-gifts-armor': ('achilles', 'achilles')}, chars)
        assert gaps == {'hector-scolds-paris': ['hector'], 'peleus-gifts-armor': ['peleus']}

    def test_ones_own_alias_answers(self):
        chars = _chars(('herakles', 'Herakles', 'Hercules'))
        assert _gaps({'philoctetes-armed-with-hercules-gear': ('herakles', '')}, chars) == {}

    def test_a_new_id_outside_the_registry_answers_the_name_it_begins_with(self):
        """Phase 2 now gives new ids; until hone adds them, a cast entry
        `eumaeus-the-swineherd` is Eumaeus written another way."""
        gaps = _gaps({'ulysses-reaches-eumaeus-hut': ('ulysses;eumaeus-the-swineherd', ''),
                      'eumaeus-returns-to-hut': ('ulysses;old-eumaeus', '')}, ODYSSEY)
        assert gaps == {'eumaeus-returns-to-hut': ['eumaeus']}

    def test_a_name_inside_a_longer_name_the_id_holds_is_that_name(self):
        chars = _chars(('ajax', 'Ajax'), ('ajax-the-lesser', 'Ajax the Lesser'),
                       ('xanthus', 'Xanthus'), ('xanthus-horse', 'Xanthus'))
        gaps = _gaps({
            'ajax-the-lesser-drowns': ('x', 'x'),
            'xanthus-horse-mourns': ('x', 'x'),
            'ajax-and-ajax-the-lesser-fight': ('x', 'x'),
        }, chars)
        assert gaps == {'ajax-the-lesser-drowns': ['ajax-the-lesser'],
                        'xanthus-horse-mourns': ['xanthus-horse'],
                        'ajax-and-ajax-the-lesser-fight': ['ajax', 'ajax-the-lesser']}

    def test_a_shared_name_is_reported_once_naming_both(self):
        chars = _chars(('xanthus', 'Xanthus'), ('xanthus-horse', 'Xanthus'))
        report = _report({
            'xanthus-mourns-troy': ('simois', 'simois'),
            'xanthus-speaks-to-achilles': ('achilles;xanthus-horse', 'achilles'),
        }, chars)
        assert report.gaps == {'xanthus-mourns-troy': [('xanthus', 'xanthus-horse')]}

    @pytest.mark.parametrize('status', sorted(INACTIVE_STATUSES))
    def test_inactive_scenes_are_skipped(self, status):
        report = _report({'eumaeus-is-gone': ('x', 'x', '', status)}, ODYSSEY)
        assert report.gaps == {} and (report.checked, report.uncast) == (0, 0)

    def test_uncast_scenes_are_counted_not_checked(self):
        report = _report({
            'eumaeus-not-cast-yet': ('', ''),
            'eumaeus-cast': ('eumaeus', ''),
        }, ODYSSEY)
        assert report.gaps == {} and (report.checked, report.uncast) == (1, 1)


def _cast_checks(project_dir):
    report = validate_structure(os.path.join(project_dir, 'reference'))
    return report, [c for c in report['checks'] if c['check'].startswith('scene-cast-named')]


def _rename_scene(project_dir, old, new):
    ref = os.path.join(project_dir, 'reference')
    for name in ('scenes.csv', 'scene-intent.csv', 'scene-briefs.csv'):
        path = os.path.join(ref, name)
        with open(path, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace(f'\n{old}|', f'\n{new}|'))


def _blank_cast(project_dir, sid):
    path = os.path.join(project_dir, 'reference', 'scene-intent.csv')
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    header = lines[0].split('|')
    ci, oi = header.index('characters'), header.index('on_stage')
    for i, line in enumerate(lines):
        cells = line.split('|')
        if cells[0] == sid:
            cells[ci] = cells[oi] = ''
            lines[i] = '|'.join(cells)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


class TestValidate:
    def test_the_fixture_is_clean_and_says_what_it_checked(self, project_dir):
        report, checks = _cast_checks(project_dir)
        assert [(c['check'], c['passed'], c['severity']) for c in checks] == [
            ('scene-cast-named', True, 'advisory')]
        assert '6 scene(s) checked' in checks[0]['message']
        assert 'not matched' not in checks[0]['message']

    def test_a_gap_is_one_advisory_finding_on_its_scene(self, project_dir):
        # act2-sc01's cast is Tessa Merrin;Pell; Kael isn't in it
        _rename_scene(project_dir, 'act2-sc01', 'kael-and-tessa-explore-the-east')
        report, checks = _cast_checks(project_dir)
        by_check = {c['check']: c for c in checks}
        c = by_check['scene-cast-named-kael-and-tessa-explore-the-east']
        assert (c['passed'], c['severity'], c['category']) == (False, 'advisory', 'characters')
        assert c['scene_id'] == 'kael-and-tessa-explore-the-east'
        assert c['fields'] == ['characters', 'on_stage']
        assert 'names kael-maren,' in c['message'] and 'tessa' not in c['message'].split('names')[1]
        summary = by_check['scene-cast-named']
        assert not summary['passed'] and '1 of 6 scene(s) checked' in summary['message']
        assert len(checks) == 2
        assert report['passed']  # advisory: never blocks

    def test_several_names_and_scenes(self, project_dir):
        _rename_scene(project_dir, 'act2-sc01', 'kael-and-dorren-follow-tessa')
        _rename_scene(project_dir, 'act2-sc02', 'kael-watches-tessa-fall')
        _, checks = _cast_checks(project_dir)
        by_check = {c['check']: c for c in checks}
        assert "names dorren-hayle, kael-maren," in \
            by_check['scene-cast-named-kael-and-dorren-follow-tessa']['message']
        assert 'names kael-maren,' in by_check['scene-cast-named-kael-watches-tessa-fall']['message']
        assert '2 of 6' in by_check['scene-cast-named']['message']

    def test_uncast_scenes_are_a_finding_even_beside_gaps(self, project_dir):
        _rename_scene(project_dir, 'act2-sc01', 'kael-and-tessa-explore-the-east')
        _blank_cast(project_dir, 'act2-sc02')
        _, checks = _cast_checks(project_dir)
        by_check = {c['check']: c for c in checks}
        uncast = by_check['scene-cast-named-uncast']
        assert not uncast['passed'] and uncast['message'].startswith('1 active scene(s)')
        assert '1 of 5 scene(s) checked' in by_check['scene-cast-named']['message']

    def test_unmatchable_characters_are_named_in_the_summary(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'characters.csv')
        with open(path, 'a', encoding='utf-8') as f:
            f.write('io|Io||minor|\n|Nameless||minor|\n')
        _, checks = _cast_checks(project_dir)
        message = checks[0]['message']
        assert checks[0]['passed']
        assert 'not matched: 1 character(s) with names too common or short to match: io' in message
        assert '1 characters.csv row(s) with no id' in message

    def test_no_registry_while_scenes_have_casts_is_a_finding(self, project_dir):
        os.remove(os.path.join(project_dir, 'reference', 'characters.csv'))
        _, checks = _cast_checks(project_dir)
        assert [(c['check'], c['passed']) for c in checks] == [
            ('scene-cast-named-unchecked', False)]
        assert 'not checked' in checks[0]['message']

    def test_a_header_only_registry_is_a_finding(self, project_dir):
        path = os.path.join(project_dir, 'reference', 'characters.csv')
        with open(path, encoding='utf-8') as f:
            header = f.readline()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(header)
        _, checks = _cast_checks(project_dir)
        assert [(c['check'], c['passed']) for c in checks] == [
            ('scene-cast-named-unchecked', False)]

    def test_no_registry_and_no_casts_passes(self, project_dir):
        ref = os.path.join(project_dir, 'reference')
        os.remove(os.path.join(ref, 'characters.csv'))
        path = os.path.join(ref, 'scene-intent.csv')
        with open(path, encoding='utf-8') as f:
            header = f.readline()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(header)
        _, checks = _cast_checks(project_dir)
        assert [(c['check'], c['passed']) for c in checks] == [('scene-cast-named', True)]
        assert 'nothing to check' in checks[0]['message']

    def test_an_unreadable_registry_is_a_finding(self, project_dir):
        with open(os.path.join(project_dir, 'reference', 'characters.csv'), 'wb') as f:
            f.write(b'id|name\n\xff\xfe|x\n')
        _, checks = _cast_checks(project_dir)
        assert [(c['check'], c['passed']) for c in checks] == [
            ('scene-cast-named-unchecked', False)]
        assert "can't be read" in checks[0]['message']

    def test_a_csv_error_is_a_finding_not_a_crash(self, project_dir, monkeypatch):
        import csv

        import storyforge.elaborate as elaborate
        real = elaborate._read_csv

        def failing(path):
            if path.endswith('characters.csv'):
                raise csv.Error('field larger than field limit')
            return real(path)

        monkeypatch.setattr(elaborate, '_read_csv', failing)
        checks = []
        ref = os.path.join(project_dir, 'reference')
        elaborate._validate_cast_named(
            elaborate._read_csv_as_map(os.path.join(ref, 'scenes.csv')),
            elaborate._read_csv_as_map(os.path.join(ref, 'scene-intent.csv')), ref, checks)
        assert [c['check'] for c in checks] == ['scene-cast-named-unchecked']
        assert 'field limit' in checks[0]['message']

"""validate's `scene-cast-named` (#523): a scene whose own id names a
registry character that neither cast column lists. Extract phase 2 kept
casts to the POV-only character list, so `ulysses-reaches-eumaeus-hut` had
no Eumaeus and `iris-summons-helen-to-wall` no Iris. Advisory, and reported,
never repaired."""

import os

from storyforge.elaborate import cast_named_gaps, validate_structure


def _chars(*rows):
    out = []
    for row in rows:
        cid, name, *aliases = row
        out.append({'id': cid, 'name': name, 'aliases': ';'.join(aliases)})
    return out


def _gaps(scenes, characters):
    """*scenes*: id → (characters, on_stage[, pov[, status]])."""
    scenes_map, intent_map = {}, {}
    for sid, spec in scenes.items():
        chars, on_stage, pov, status = (list(spec) + ['', ''])[:4]
        scenes_map[sid] = {'id': sid, 'pov': pov, 'status': status}
        intent_map[sid] = {'id': sid, 'characters': chars, 'on_stage': on_stage}
    return cast_named_gaps(scenes_map, intent_map, characters)


ODYSSEY = _chars(('ulysses', 'Ulysses', 'Odysseus'), ('eumaeus', 'Eumaeus'),
                 ('iris', 'Iris'), ('helen', 'Helen'), ('minerva', 'Minerva', 'Pallas Minerva'),
                 ('paris', 'Paris', 'Alexandrus'))


class TestCastNamedGaps:
    def test_a_named_character_missing_from_both_columns_is_reported(self):
        gaps, checked, uncast = _gaps({
            'ulysses-reaches-eumaeus-hut': ('narrator;ulysses', 'narrator;ulysses'),
            'iris-summons-helen-to-wall': ('helen', 'helen'),
        }, ODYSSEY)
        assert gaps == {'ulysses-reaches-eumaeus-hut': ['eumaeus'],
                        'iris-summons-helen-to-wall': ['iris']}
        assert (checked, uncast) == (2, 0)

    def test_either_column_answers_and_names_and_aliases_resolve(self):
        gaps, _, _ = _gaps({
            'ulysses-reaches-eumaeus-hut': ('Eumaeus', 'Odysseus'),
            'iris-summons-helen-to-wall': ('', 'iris;Helen'),
            'paris-challenges-the-greeks': ('Alexandrus', ''),
        }, ODYSSEY)
        assert gaps == {}

    def test_the_pov_counts_as_present(self):
        gaps, _, _ = _gaps({'eumaeus-tends-the-pigs': ('ulysses', 'ulysses', 'eumaeus')},
                           ODYSSEY)
        assert gaps == {}

    def test_whole_words_only(self):
        chars = _chars(('pell', 'Pell'), ('ann', 'Ann'))
        gaps, _, _ = _gaps({
            'spell-breaks': ('x', 'x'),
            'annual-feast': ('x', 'x'),
            'pell-runs': ('x', 'x'),
        }, chars)
        assert gaps == {'pell-runs': ['pell']}

    def test_a_possessive_word_names_the_character(self):
        gaps, _, _ = _gaps({'footrace-ulysses-wins-with-minervas': ('ulysses', 'ulysses')},
                           ODYSSEY)
        assert gaps == {'footrace-ulysses-wins-with-minervas': ['minerva']}

    def test_multi_word_names_match_as_a_run(self):
        chars = _chars(('vey', 'Old Mother Vey'))
        gaps, _, _ = _gaps({'old-mother-vey-dies': ('x', 'x'),
                            'old-mother-weeps': ('x', 'x')}, chars)
        assert gaps == {'old-mother-vey-dies': ['vey']}

    def test_short_and_common_words_are_not_names(self):
        """An alias like "the King" or "Sleep", or a name like "Io", is too
        common (or short) in scene ids to read as the person."""
        chars = _chars(('alcinous', 'Alcinous', 'the King', 'King'),
                       ('io', 'Io'), ('hypnos', 'Sleep', 'Hypnos'))
        gaps, _, _ = _gaps({
            'king-feasts-the-guest': ('x', 'x'),
            'io-wanders': ('x', 'x'),
            'argives-sup-and-sleep': ('x', 'x'),
            'hypnos-lulls-zeus': ('x', 'x'),
        }, chars)
        assert gaps == {'hypnos-lulls-zeus': ['hypnos']}

    def test_someone_holding_the_name_answers_it(self):
        """Quintus has `aias` and `aias-son-of-oileus`: a scene id's "aias"
        is answered by either in the cast."""
        chars = _chars(('aias', 'Aias'), ('aias-son-of-oileus', 'Aias son of Oileus'))
        gaps, _, _ = _gaps({
            'aias-struggles-and-dies': ('aias-son-of-oileus;poseidon', 'poseidon'),
            'aias-holds-the-ships': ('hector', 'hector'),
        }, chars)
        assert gaps == {'aias-holds-the-ships': ['aias']}

    def test_a_shared_name_is_reported_once_naming_both(self):
        chars = _chars(('xanthus', 'Xanthus'), ('xanthus-horse', 'Xanthus'))
        gaps, _, _ = _gaps({
            'xanthus-mourns-troy': ('simois', 'simois'),
            'xanthus-speaks-to-achilles': ('achilles;xanthus-horse', 'achilles'),
        }, chars)
        assert gaps == {'xanthus-mourns-troy': ['xanthus or xanthus-horse']}

    def test_inactive_and_uncast_scenes_are_not_checked(self):
        gaps, checked, uncast = _gaps({
            'eumaeus-is-cut': ('x', 'x', '', 'cut'),
            'eumaeus-not-cast-yet': ('', ''),
            'eumaeus-cast': ('eumaeus', ''),
        }, ODYSSEY)
        assert gaps == {} and (checked, uncast) == (1, 1)


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


class TestValidate:
    def test_the_fixture_is_clean_and_says_what_it_checked(self, project_dir):
        report, checks = _cast_checks(project_dir)
        assert [(c['passed'], c['severity']) for c in checks] == [(True, 'advisory')]
        assert '6 scene(s) checked' in checks[0]['message']

    def test_a_gap_is_one_advisory_finding_on_its_scene(self, project_dir):
        # act2-sc01's cast is Tessa Merrin;Pell; Kael isn't in it
        _rename_scene(project_dir, 'act2-sc01', 'kael-and-tessa-explore-the-east')
        report, checks = _cast_checks(project_dir)
        assert len(checks) == 1
        c = checks[0]
        assert c['check'] == 'scene-cast-named-kael-and-tessa-explore-the-east'
        assert (c['passed'], c['severity'], c['category']) == (False, 'advisory', 'characters')
        assert c['scene_id'] == 'kael-and-tessa-explore-the-east'
        assert c['fields'] == ['characters', 'on_stage']
        assert 'names kael-maren' in c['message'] and 'tessa' not in c['message'].split('names')[1]
        assert report['passed']  # advisory: never blocks

    def test_no_registry_while_scenes_have_casts_is_a_finding(self, project_dir):
        os.remove(os.path.join(project_dir, 'reference', 'characters.csv'))
        _, checks = _cast_checks(project_dir)
        assert [(c['check'], c['passed']) for c in checks] == [('scene-cast-named', False)]
        assert 'not checked' in checks[0]['message']

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

    def test_an_unreadable_registry_is_a_finding(self, project_dir):
        with open(os.path.join(project_dir, 'reference', 'characters.csv'), 'wb') as f:
            f.write(b'id|name\n\xff\xfe|x\n')
        _, checks = _cast_checks(project_dir)
        assert [(c['check'], c['passed']) for c in checks] == [
            ('scene-cast-named-unchecked', False)]
        assert "can't be read" in checks[0]['message']

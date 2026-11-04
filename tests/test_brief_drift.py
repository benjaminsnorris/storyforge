"""Brief drift (#496): names in the briefs on disk that no prose and no
reference file uses. shared-dark's briefs named about 100 people the book
never mentions (Olinsky, Ruzek, "Voight", from a brief rewrite that drifted,
ac569274), and a rewrite drafts its facts from the brief. `validate` reports
them as advisory findings, one per scene; `hone --diagnose` lists them."""

import os

from storyforge import cmd_hone
from storyforge.brief_names import describe_strays, stray_brief_names
from storyforge.elaborate import _FILE_MAP, _read_csv_as_map, _write_csv, validate_structure

DRAFTED = 'act1-sc01'     # has scenes/act1-sc01.md
UNDRAFTED = 'act2-sc03'   # briefed, no prose file
OTHER = 'act1-sc02'       # drafted too


def _ref(project_dir, name):
    return os.path.join(project_dir, 'reference', name)


def _briefs(project_dir):
    return _read_csv_as_map(_ref(project_dir, 'scene-briefs.csv'))


def _set_brief(project_dir, sid, **fields):
    briefs = _briefs(project_dir)
    briefs[sid].update(fields)
    _write_csv(_ref(project_dir, 'scene-briefs.csv'), list(briefs.values()),
               _FILE_MAP['scene-briefs.csv'])


def _strays(project_dir, scene_ids=None):
    return stray_brief_names(project_dir, _briefs(project_dir), scene_ids)


def _append(path, text):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text)


def _brief_checks(project_dir):
    return [c for c in validate_structure(os.path.join(project_dir, 'reference'))['checks']
            if c['category'] == 'briefs']


class TestValidate:
    def test_the_fixture_is_clean(self, project_dir):
        checks = _brief_checks(project_dir)
        assert [(c['check'], c['passed']) for c in checks] == [('brief-stray-names', True)]

    def test_a_stray_name_is_an_advisory_finding_per_scene(self, project_dir):
        before = validate_structure(os.path.join(project_dir, 'reference'))['passed']
        _set_brief(project_dir, DRAFTED, conflict='the warden, Olinsky, bars the archive door',
                   key_actions='Reviews maps;Calls Detective Ruzek;Files as error')
        report = validate_structure(os.path.join(project_dir, 'reference'))
        [finding] = [c for c in report['failures'] if c['category'] == 'briefs']
        assert finding['check'] == f'brief-stray-names-{DRAFTED}'
        assert finding['severity'] == 'advisory' and finding['scene_id'] == DRAFTED
        assert finding['fields'] == ['conflict', 'key_actions']
        assert 'conflict: Olinsky; key_actions: Detective Ruzek' in finding['message']
        # advisory: it never blocks
        assert report['passed'] == before

    def test_no_briefs_file_says_nothing_was_checked(self, project_dir):
        os.remove(_ref(project_dir, 'scene-briefs.csv'))
        [check] = _brief_checks(project_dir)
        assert check['passed'] and 'No briefs' in check['message']


class TestStrayNames:
    def test_multi_word_names_are_one_name(self, project_dir):
        _set_brief(project_dir, DRAFTED, goal='find Danny Olinsky before the audit')
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Danny Olinsky']}}

    def test_institutions_calendar_words_and_titles_pass(self, project_dir):
        _set_brief(project_dir, DRAFTED,
                   goal='report to Internal Affairs by Tuesday in March',
                   conflict='the Police Department wants Detective Hayle off the case')
        assert _strays(project_dir) == {}

    def test_possessives(self, project_dir):
        _set_brief(project_dir, DRAFTED, goal="read Tessa's notes and take Olinsky's key")
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Olinsky']}}

    def test_a_word_the_prose_uses_lowercase_passes(self, project_dir):
        _set_brief(project_dir, DRAFTED, goal='she opens the Sector ledger')
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Sector']}}
        _append(os.path.join(project_dir, 'scenes', f'{OTHER}.md'),
                '\nThe sector maps lay open.\n')
        assert _strays(project_dir) == {}

    def test_singular_and_plural_of_a_book_name_pass(self, project_dir):
        _append(os.path.join(project_dir, 'scenes', f'{OTHER}.md'),
                '\nThe Franklins rose on the horizon.\n')
        _set_brief(project_dir, DRAFTED, goal='she rides toward the Franklin range')
        assert _strays(project_dir) == {}

    def test_a_name_in_an_alias_passes(self, project_dir):
        _set_brief(project_dir, DRAFTED, goal='she asks Pip for the key')
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Pip']}}
        path = _ref(project_dir, 'characters.csv')
        with open(path, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace('Tessa;Merrin', 'Tessa;Merrin;Pip'))
        assert _strays(project_dir) == {}

    def test_a_name_only_in_another_scenes_prose_is_not_a_stray(self, project_dir):
        _set_brief(project_dir, DRAFTED, goal='she hides the map from Kessler')
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Kessler']}}
        _append(os.path.join(project_dir, 'scenes', 'act2-sc01.md'),
                '\nKessler watched them go.\n')
        assert _strays(project_dir) == {}

    def test_the_intent_file_does_not_vouch(self, project_dir):
        """A brief rewrite that drifted writes intent too (REWRITTEN_FILES)."""
        _set_brief(project_dir, DRAFTED, goal='she hides the map from Kael Voss')
        path = _ref(project_dir, 'scene-intent.csv')
        with open(path, encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace('Dorren Hayle', 'Dorren Hayle;Voss', 1))
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Kael Voss']}}

    def test_another_brief_vouches_only_for_an_undrafted_scene(self, project_dir):
        _set_brief(project_dir, OTHER, goal='she waits for Mallen at the archive')
        _set_brief(project_dir, DRAFTED, goal='she waits for Mallen at dawn')
        _set_brief(project_dir, UNDRAFTED, goal='she argues with Mallen before the council')
        strays = _strays(project_dir)
        # drafted scenes: the briefs are what drifted, so they vouch for nothing
        assert set(strays) == {DRAFTED, OTHER}
        # an undrafted scene alone naming someone is still the signal
        _set_brief(project_dir, UNDRAFTED, goal='she argues with Pettigrew before the council')
        assert _strays(project_dir)[UNDRAFTED] == {'goal': ['Pettigrew']}

    def test_beat_openers_are_names_only_where_briefs_use_them_as_names(self, project_dir):
        _set_brief(project_dir, DRAFTED, key_actions='Consults Tessa;Mallen arrives;Leaves')
        assert _strays(project_dir) == {}
        _set_brief(project_dir, OTHER, goal="she hides from Mallen")
        assert _strays(project_dir)[DRAFTED] == {'key_actions': ['Mallen']}

    def test_a_possessive_opener_is_a_name(self, project_dir):
        _set_brief(project_dir, DRAFTED, conflict="The copy cracks; Dechlan's riders arrive")
        assert _strays(project_dir) == {DRAFTED: {'conflict': ['Dechlan']}}

    def test_bracketed_notes_are_openers(self, project_dir):
        _set_brief(project_dir, DRAFTED, key_dialogue='[Minimal — mostly interior]')
        assert _strays(project_dir) == {}

    def test_scene_filter(self, project_dir):
        _set_brief(project_dir, DRAFTED, goal='find Olinsky')
        _set_brief(project_dir, OTHER, goal='find Ruzek')
        assert set(_strays(project_dir, [OTHER])) == {OTHER}

    def test_bom_and_crlf_files(self, project_dir):
        """A spreadsheet export: BOM and CRLF in the briefs and a registry."""
        _set_brief(project_dir, DRAFTED, goal='she asks Pip and Olinsky for the key')
        for name in ('scene-briefs.csv', 'characters.csv'):
            path = _ref(project_dir, name)
            with open(path, encoding='utf-8') as f:
                text = f.read()
            if name == 'characters.csv':
                text = text.replace('Tessa;Merrin', 'Tessa;Merrin;Pip')
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                f.write(text.replace('\n', '\r\n'))
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Olinsky']}}
        [finding] = [c for c in _brief_checks(project_dir) if not c['passed']]
        assert finding['scene_id'] == DRAFTED and finding['message'].endswith('goal: Olinsky')

    def test_describe_is_safe_for_a_pipe_delimited_report(self):
        assert describe_strays({'goal': ['A|B', 'C\nD']}) == 'goal: A/B, C D'


class TestHoneDiagnose:
    def _diagnose(self, project_dir, monkeypatch, capsys, *args):
        monkeypatch.setattr(cmd_hone, 'detect_project_root', lambda: project_dir)
        monkeypatch.setattr('storyforge.api._api_request',
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError('API')))
        cmd_hone.main(['--diagnose', *args])
        return capsys.readouterr().out

    def test_lists_stray_names_by_scene_and_field(self, project_dir, monkeypatch, capsys):
        _set_brief(project_dir, DRAFTED, goal='find Olinsky')
        out = self._diagnose(project_dir, monkeypatch, capsys)
        assert '=== Brief Names Found Nowhere in the Book ===' in out
        assert f'{DRAFTED}: goal: Olinsky' in out
        assert 'Stray brief names:   1 scenes' in out

    def test_clean_book_says_so(self, project_dir, monkeypatch, capsys):
        out = self._diagnose(project_dir, monkeypatch, capsys)
        assert 'Every name in the briefs appears in the prose or a reference file.' in out

    def test_respects_the_scene_filter(self, project_dir, monkeypatch, capsys):
        _set_brief(project_dir, DRAFTED, goal='find Olinsky')
        out = self._diagnose(project_dir, monkeypatch, capsys, '--scenes', OTHER)
        assert 'Olinsky' not in out

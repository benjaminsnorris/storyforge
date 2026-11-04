"""Brief drift (#496): names in the briefs on disk that no prose and no
reference file uses. One book's briefs named about 100 people it never
mentions (Olinsky, Ruzek, "Voight", from a brief rewrite that drifted), and
a rewrite drafts its facts from the brief. `validate` reports them as
advisory findings, one per scene; `hone --diagnose` lists them. A check that
couldn't look at something says so rather than reading clean."""

import os
import sys

import pytest

from storyforge import cmd_hone
from storyforge.brief_names import (
    FACT_FIELDS, brief_drift, describe_strays, invented_names, reference_text,
)
from storyforge.elaborate import (
    _BRIEFS_COLS, _FILE_MAP, _read_csv_as_map, _write_csv, validate_structure,
)

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
    return brief_drift(project_dir, scene_ids).strays


def _append(path, text):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text)


def _rewrite(path, fn, encoding='utf-8'):
    with open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    with open(path, 'w', encoding=encoding, newline='') as f:
        f.write(fn(text))


def _brief_checks(project_dir):
    return [c for c in validate_structure(os.path.join(project_dir, 'reference'))['checks']
            if c['category'] == 'briefs']


class TestValidate:
    def test_the_fixture_is_clean_and_says_what_it_checked(self, project_dir):
        [check] = _brief_checks(project_dir)
        assert check['check'] == 'brief-stray-names' and check['passed']
        assert '4 brief(s) (1 with no prose yet) checked against all scene prose' \
            in check['message']

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

    def test_no_briefs_file_passes_with_nothing_to_check(self, project_dir):
        os.remove(_ref(project_dir, 'scene-briefs.csv'))
        [check] = _brief_checks(project_dir)
        assert check['passed'] and 'No scene-briefs.csv' in check['message']

    @pytest.mark.parametrize('header_fix, why', [
        (lambda t: t.replace('id|goal', 'ID|goal', 1), "no pipe-delimited 'id' column"),
        (lambda t: t.replace('|', ','), "no pipe-delimited 'id' column"),
        (lambda t: t.replace('|subtext|', '|subtxt|', 1), 'no subtext column'),
    ])
    def test_a_header_it_cannot_use_is_a_finding_not_clean(self, project_dir, header_fix, why):
        """SF-1: a misspelled or missing column, or no `id`, read as clean."""
        _rewrite(_ref(project_dir, 'scene-briefs.csv'), header_fix)
        checks = _brief_checks(project_dir)
        unchecked = [c for c in checks if c['check'] == 'brief-stray-names-unchecked']
        assert unchecked and not unchecked[0]['passed']
        assert unchecked[0]['severity'] == 'advisory' and why in unchecked[0]['message']
        assert not any(c['passed'] for c in checks)

    def test_briefs_with_every_fact_field_empty_are_not_counted_checked(self, project_dir):
        _set_brief(project_dir, UNDRAFTED, **{f: '' for f in FACT_FIELDS})
        report = brief_drift(project_dir)
        assert report.checked == 3
        assert any(UNDRAFTED in n and 'every fact field empty' in n for n in report.notes)

    @pytest.mark.skipif(sys.platform == 'win32' or os.geteuid() == 0,
                        reason='needs POSIX permissions, not root')
    def test_an_unreadable_file_is_noted_and_the_rest_still_checked(self, project_dir):
        """SF-4: one unreadable scene or reference file crashed validate."""
        _set_brief(project_dir, DRAFTED, goal='find Olinsky')
        unreadable = [os.path.join(project_dir, 'scenes', 'act2-sc01.md'),
                      _ref(project_dir, 'voice-guide.md')]
        for path in unreadable:
            os.chmod(path, 0)
        try:
            report = validate_structure(os.path.join(project_dir, 'reference'))
        finally:
            for path in unreadable:
                os.chmod(path, 0o644)
        checks = [c for c in report['checks'] if c['category'] == 'briefs']
        assert any(c.get('scene_id') == DRAFTED for c in checks)
        notes = ' '.join(c['message'] for c in checks
                         if c['check'] == 'brief-stray-names-unchecked')
        assert 'scenes/act2-sc01.md could not be read' in notes
        assert 'reference/voice-guide.md could not be read' in notes

    def test_a_file_that_is_not_utf8_is_read_and_noted(self, project_dir):
        with open(os.path.join(project_dir, 'scenes', 'act2-sc01.md'), 'ab') as f:
            f.write('\nKessler said café.\n'.encode('latin-1'))
        _set_brief(project_dir, DRAFTED, goal='she hides the map from Kessler')
        report = brief_drift(project_dir)
        assert report.strays == {}
        assert any('scenes/act2-sc01.md is not UTF-8' in n for n in report.notes)

    def test_fact_fields_are_brief_columns(self):
        assert set(FACT_FIELDS) <= set(_BRIEFS_COLS)


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

    def test_a_contraction_is_not_a_possessive_name(self, project_dir):
        _set_brief(project_dir, DRAFTED, key_dialogue="Who's there?;What's that?")
        assert _strays(project_dir) == {}

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
        _rewrite(_ref(project_dir, 'characters.csv'),
                 lambda t: t.replace('Tessa;Merrin', 'Tessa;Merrin;Pip'))
        assert _strays(project_dir) == {}

    def test_a_name_only_in_another_scenes_prose_is_not_a_stray(self, project_dir):
        _set_brief(project_dir, DRAFTED, goal='she hides the map from Kessler')
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Kessler']}}
        _append(os.path.join(project_dir, 'scenes', 'act2-sc01.md'),
                '\nKessler watched them go.\n')
        assert _strays(project_dir) == {}

    def test_a_name_in_a_reference_subfolder_passes(self, project_dir):
        """CR-7: canon/ and source/<slug>/ are the book's own reference too."""
        _set_brief(project_dir, DRAFTED, goal='she hides the map from Kessler')
        canon = _ref(project_dir, 'canon')
        os.makedirs(canon, exist_ok=True)
        with open(os.path.join(canon, 'house-style.md'), 'w', encoding='utf-8') as f:
            f.write('Kessler always wears grey.\n')
        assert _strays(project_dir) == {}

    def test_the_intent_file_does_not_vouch(self, project_dir):
        """A brief rewrite that drifted writes intent too (REWRITTEN_FILES)."""
        _set_brief(project_dir, DRAFTED, goal='she hides the map from Kael Voss')
        _rewrite(_ref(project_dir, 'scene-intent.csv'),
                 lambda t: t.replace('Dorren Hayle', 'Dorren Hayle;Voss', 1))
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Kael Voss']}}

    def test_briefs_never_vouch_for_each_other(self, project_dir):
        """CR-2: a drifted name in several briefs, drafted or not, is reported
        in each, and stays reported in the others after one is fixed."""
        _set_brief(project_dir, OTHER, goal='she waits for Mallen at the archive')
        _set_brief(project_dir, DRAFTED, goal='she waits for Mallen at dawn')
        _set_brief(project_dir, UNDRAFTED, goal='she argues with Mallen before the council')
        assert set(_strays(project_dir)) == {DRAFTED, OTHER, UNDRAFTED}
        _set_brief(project_dir, DRAFTED, goal='she waits at dawn')
        assert set(_strays(project_dir)) == {OTHER, UNDRAFTED}

    def test_a_whitespace_only_scene_file_is_undrafted(self, project_dir):
        with open(os.path.join(project_dir, 'scenes', f'{UNDRAFTED}.md'), 'w') as f:
            f.write('  \n\n')
        assert brief_drift(project_dir).undrafted == 1
        with open(os.path.join(project_dir, 'scenes', f'{UNDRAFTED}.md'), 'w') as f:
            f.write('Dorren argued.\n')
        assert brief_drift(project_dir).undrafted == 0

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

    @pytest.mark.parametrize('goal, name', [
        ('Tessa sees Dr. Kossuth', 'Kossuth'),
        ('she calls Sgt. Ruzek', 'Ruzek'),
        ('she meets Det. Olinsky at St. Brendan', 'Olinsky, Brendan'),
        ('Tessa phones Mrs. Halke', 'Halke'),
    ])
    def test_a_period_after_an_abbreviation_does_not_open_a_sentence(
            self, project_dir, goal, name):
        """CR-3: "Dr. Kossuth" read as a sentence start and was skipped."""
        _set_brief(project_dir, DRAFTED, goal=goal)
        assert describe_strays(_strays(project_dir)[DRAFTED]) == f'goal: {name}'

    def test_unicode_names_are_whole(self, project_dir):
        """CR-5: Zoë, José and Seán were cut to Zo, Jos, Se."""
        _set_brief(project_dir, DRAFTED, goal="she meets Zoë, José and Seán O'Brien-Ní Dhuill")
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Zoë', 'José', "Seán O'Brien-Ní Dhuill"]}}
        _append(os.path.join(project_dir, 'scenes', f'{OTHER}.md'),
                "\nZoë and José waited for Seán O'Brien-Ní Dhuill.\n")
        assert _strays(project_dir) == {}

    def test_scene_filter(self, project_dir):
        _set_brief(project_dir, DRAFTED, goal='find Olinsky')
        _set_brief(project_dir, OTHER, goal='find Ruzek')
        assert set(_strays(project_dir, [OTHER])) == {OTHER}

    def test_a_filter_matching_no_brief_says_so(self, project_dir):
        """SF-1: a typo'd id or an act with no scenes read as clean."""
        report = brief_drift(project_dir, ['act1-sc1'])
        assert report.checked == 0 and any('No brief row for act1-sc1' in n for n in report.notes)
        report = brief_drift(project_dir, [])
        assert report.checked == 0 and any('No scenes selected' in n for n in report.notes)

    def test_bom_and_crlf_files(self, project_dir):
        """A spreadsheet export: BOM and CRLF in the briefs and a registry."""
        _set_brief(project_dir, DRAFTED, goal='she asks Pip and Olinsky for the key')
        _rewrite(_ref(project_dir, 'scene-briefs.csv'), lambda t: t.replace('\n', '\r\n'),
                 encoding='utf-8-sig')
        _rewrite(_ref(project_dir, 'characters.csv'),
                 lambda t: t.replace('Tessa;Merrin', 'Tessa;Merrin;Pip').replace('\n', '\r\n'),
                 encoding='utf-8-sig')
        assert _strays(project_dir) == {DRAFTED: {'goal': ['Olinsky']}}
        [finding] = [c for c in _brief_checks(project_dir) if not c['passed']]
        assert finding['scene_id'] == DRAFTED and finding['message'].endswith('goal: Olinsky')

    def test_describe_is_safe_for_a_pipe_delimited_report(self):
        assert describe_strays({'goal': ['A|B', 'C\nD']}) == 'goal: A/B, C D'


class TestGraphicNovel:
    """CR-1: a graphic novel's prose is its pages (pages/<prefix>-pN.md)."""

    def _page(self, project_dir, name, scene_id, body):
        with open(os.path.join(project_dir, 'pages', name), 'w', encoding='utf-8') as f:
            f.write(f'---\npage_id: {name[:-3]}\nscene_id: {scene_id}\n---\n{body}')

    def test_names_shared_by_briefs_are_reported(self, project_dir_gn):
        for sid in ('the-blank-page', 'shadows-arrive', 'the-first-mark'):
            _set_brief(project_dir_gn, sid, goal='she hides from Olinsky')
        assert set(_strays(project_dir_gn)) == {'the-blank-page', 'shadows-arrive',
                                                 'the-first-mark'}

    def test_a_scene_with_page_text_is_drafted_and_its_names_vouch(self, project_dir_gn):
        _set_brief(project_dir_gn, 'shadows-arrive', goal='she hides from Olinsky')
        assert brief_drift(project_dir_gn).undrafted == 3
        self._page(project_dir_gn, 'the-blank-page-p1.md', 'the-blank-page',
                   '## Panel 1\nOlinsky waits in the doorway.\n')
        report = brief_drift(project_dir_gn)
        assert report.undrafted == 2 and report.strays == {}

    def test_a_page_with_only_frontmatter_is_not_prose(self, project_dir_gn):
        self._page(project_dir_gn, 'the-blank-page-p1.md', 'the-blank-page', '\n  \n')
        assert brief_drift(project_dir_gn).undrafted == 3

    def test_a_page_without_scene_id_maps_by_prefix(self, project_dir_gn):
        with open(os.path.join(project_dir_gn, 'pages', 'the-first-mark-p1.md'), 'w') as f:
            f.write('---\npage_id: the-first-mark-p1\n---\nThe page fills.\n')
        assert brief_drift(project_dir_gn).undrafted == 2


class TestGuardUnchanged:
    """CR-4: the drift check's lenient rules must not loosen the guard that
    rejects revise's and hone's brief rewrites."""

    def test_brackets_still_hide_nothing_from_the_guard(self):
        assert invented_names(
            ['Tessa waits. [Marked note] Tessa leaves', '[Mallens arrive]',
             'Tessa reads [Ruzeks file]'], 'Tessa') == ['Mallens', 'Marked', 'Ruzeks']

    def test_reference_text_leaves_out_both_rewritten_files_by_default(self, project_dir):
        """TD-2: revise's guard used the default, which let scene-intent.csv
        vouch for a name; it never vouches now, as in hone's guard."""
        _rewrite(_ref(project_dir, 'scene-intent.csv'),
                 lambda t: t.replace('Dorren Hayle', 'Dorren Hayle;Quillon', 1))
        _rewrite(_ref(project_dir, 'scene-briefs.csv'),
                 lambda t: t.replace('quarterly', 'Brannock quarterly', 1))
        text = reference_text(project_dir)
        assert 'Quillon' not in text and 'Brannock' not in text
        assert 'Dorren Hayle' in text


    def test_a_gutenberg_config_is_read_not_noted_as_skipped(self, project_dir):
        """Gawain: `init --fetch` keeps the fetch config as
        reference/gutenberg.json, so every Gutenberg project's validate said
        the names check was incomplete. JSON is text: it is read."""
        with open(_ref(project_dir, 'gutenberg.json'), 'w') as f:
            f.write('{"edition": "Jessie L. Weston, 1898"}\n')
        notes = []
        text = reference_text(project_dir, notes=notes)
        assert 'Weston' in text
        assert not any('not a text format' in n for n in notes)


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
        assert 'Stray brief names:   1 of 4 briefs checked' in out

    def test_clean_book_says_what_it_checked(self, project_dir, monkeypatch, capsys):
        out = self._diagnose(project_dir, monkeypatch, capsys)
        assert 'None: 4 brief(s) (1 with no prose yet) checked against all scene prose' in out

    def test_respects_the_scene_filter(self, project_dir, monkeypatch, capsys):
        _set_brief(project_dir, DRAFTED, goal='find Olinsky')
        out = self._diagnose(project_dir, monkeypatch, capsys, '--scenes', OTHER)
        assert 'Olinsky' not in out

    def test_a_filter_matching_nothing_is_not_clean(self, project_dir, monkeypatch, capsys):
        out = self._diagnose(project_dir, monkeypatch, capsys, '--act', '9')
        assert 'Not checked: No scenes selected' in out
        assert 'None:' not in out
        out = self._diagnose(project_dir, monkeypatch, capsys, '--scenes', 'act1-sc1')
        assert 'Not checked: No brief row for act1-sc1' in out


class TestContractionsOfI:
    """G-022: on the Gawain novel 25 of 42 briefs were flagged for "I'm" and
    "I've" in key_dialogue: capitalized mid-line, so read as names."""

    @pytest.mark.parametrize('line', ["Gawain: I'm the weakest of us, and I've no lady.",
                                      'Gawain: I’ll go, and I’d go again.'])
    def test_i_contractions_are_not_names(self, project_dir, line):
        _set_brief(project_dir, DRAFTED, key_dialogue=line)
        report = validate_structure(os.path.join(project_dir, 'reference'))
        assert not [c for c in report['failures'] if c['category'] == 'briefs']

    def test_a_real_name_in_the_same_line_is_still_found(self, project_dir):
        _set_brief(project_dir, DRAFTED, key_dialogue="Gawain: I'm Olinsky's man.")
        report = validate_structure(os.path.join(project_dir, 'reference'))
        [finding] = [c for c in report['failures'] if c['category'] == 'briefs']
        assert 'Olinsky' in finding['message'] and "I'm" not in finding['message']

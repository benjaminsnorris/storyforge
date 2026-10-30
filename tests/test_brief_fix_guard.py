"""Regression tests for shared-dark (April 2026): revise's upstream brief fix
was given the scene's title, POV, outcome, value at stake, emotional arc and
current brief, but not its characters, place, plan or prose, and rewrote 21
of 23 Act 1 briefs into another story (a captor named Mallen, Danny Olinsky,
Detective Ruzek, a custody hearing; the book's own Hank Voigt recast as a
police sergeant). The redrafts then followed those briefs. The fix now sees
the scene's characters, place, plan and prose, and a rewrite that names a
capitalized word found nowhere in the reference files or the scene is
rejected."""

import os
from unittest.mock import patch

import pytest

from storyforge import cmd_revise
from storyforge.brief_names import invented_names
from storyforge.cmd_revise import _fix_and_redraft, _fix_upstream_briefs

# From shared-dark 0940bd4d (claires-cold), the rewrite that brought in Mallen.
MALLEN = ('The captor, Mallen, kneels without speaking and works with genuine, '
          "unhurried competence, and Claire's body is beginning to distinguish his touch")


class TestInventedNames:
    def test_flags_a_name_the_book_never_uses(self):
        assert invented_names([MALLEN], 'Claire is held in a basement room.') == ['Mallen']

    def test_book_names_and_possessives_pass(self):
        assert invented_names(["Claire's hands shake when Hank speaks."],
                               'Claire and Hank') == []

    def test_a_possessive_in_the_book_vouches_for_the_name(self):
        assert invented_names(['she waits for Mallen'], "Mallen's door") == []

    @pytest.mark.parametrize('field', [
        'Mallen blocks the door.',
        'She waits. Mallen blocks the door.',
        'the warden—Mallen—waits',
        'the warden (Mallen) waits',
        '“Go,” Voigt said.',
        'GOAL: Mallen',
    ])
    def test_names_opening_a_field_or_sentence_are_checked(self, field):
        assert invented_names([field], 'the warden waits at the door said go') != []

    def test_ordinary_openers_pass_when_the_book_uses_the_word(self):
        assert invented_names(['Refuses to answer. Stays silent: Holds still.'],
                               'she refused, stayed, holding') == []

    def test_capitalized_ordinary_word_the_book_uses_passes(self):
        assert invented_names(['she reaches the Basement door'], 'the basement') == []

    def test_camel_case_and_hyphenated_names(self):
        assert invented_names(['she calls McKenzie and Jean-Luc'],
                               'McKenzie spoke to Jean and Luc') == []
        assert invented_names(['she calls Luc'], 'Jean-Luc') == []
        assert invented_names(['she calls McMallen'], 'McKenzie') == ['McMallen']

    def test_calendar_words_and_titles_pass(self):
        assert invented_names(['by Tuesday in March she asks Dr. Hank'], 'Hank') == []


REPLY = 'GOAL: {g}\nCONFLICT: {c}\nCRISIS: the door locks\nDECISION: she stays'


def _brief(project_dir, sid='act1-sc01'):
    from storyforge.elaborate import _read_csv_as_map
    return _read_csv_as_map(os.path.join(project_dir, 'reference', 'scene-briefs.csv'))[sid]


def _set_brief(project_dir, sid, **fields):
    from storyforge.elaborate import _FILE_MAP, _read_csv_as_map, _write_csv
    path = os.path.join(project_dir, 'reference', 'scene-briefs.csv')
    briefs = _read_csv_as_map(path)
    briefs[sid].update(fields)
    _write_csv(path, list(briefs.values()), _FILE_MAP['scene-briefs.csv'])


def _append_prose(project_dir, sid, text):
    with open(os.path.join(project_dir, 'scenes', f'{sid}.md'), 'a', encoding='utf-8') as f:
        f.write(text)


def _fix(project_dir, reply, sids=('act1-sc01',)):
    replies = reply if isinstance(reply, list) else [reply]
    with patch('storyforge.cmd_revise.invoke_api', side_effect=replies) as api, \
         patch('storyforge.cmd_revise.select_model', return_value='m'):
        result = _fix_upstream_briefs(project_dir, list(sids))
    return result, api.call_args[0][0]


class TestFixUpstreamBriefs:
    def test_rewrite_naming_a_stranger_is_rejected(self, project_dir, capsys):
        before = _brief(project_dir)
        (fixed, skipped), _ = _fix(project_dir, REPLY.format(
            g='keep the ledger closed', c='the warden, Mallen, demands it'))
        assert fixed == [] and skipped == {'act1-sc01': 'named Mallen'}
        assert _brief(project_dir) == before
        out = capsys.readouterr().out
        assert 'WARNING' in out and 'Mallen' in out and 'brief is unchanged' in out

    def test_grounded_rewrite_is_written(self, project_dir):
        (fixed, skipped), _ = _fix(project_dir, REPLY.format(
            g='keep the map hidden', c='the storm pins her in place'))
        assert fixed == ['act1-sc01'] and skipped == {}
        assert _brief(project_dir)['conflict'] == 'the storm pins her in place'

    def test_mixed_outcomes_write_only_the_accepted_scene(self, project_dir):
        fields = ('goal', 'conflict', 'crisis', 'decision')
        before = [_brief(project_dir, 'act1-sc02')[k] for k in fields]
        (fixed, skipped), _ = _fix(project_dir, [
            REPLY.format(g='keep the map hidden', c='the storm pins her'),
            REPLY.format(g='find the village', c='Mallen burns the archive'),
        ], sids=('act1-sc01', 'act1-sc02'))
        assert fixed == ['act1-sc01'] and list(skipped) == ['act1-sc02']
        assert _brief(project_dir)['conflict'] == 'the storm pins her'
        assert [_brief(project_dir, 'act1-sc02')[k] for k in fields] == before

    def test_nothing_accepted_writes_nothing(self, project_dir):
        with patch('storyforge.elaborate._write_csv') as write:
            (fixed, _), _ = _fix(project_dir, REPLY.format(g='x', c='Mallen waits'))
        assert fixed == []
        write.assert_not_called()

    @pytest.mark.parametrize('reply, why', [
        ('', 'no reply'),
        ('GOAL: keep the map\nCONFLICT: the storm', 'reply lacked CRISIS, DECISION'),
        ('GOAL: keep the map\nCONFLICT:\nCRISIS: a\nDECISION: b', 'reply lacked CONFLICT'),
    ])
    def test_empty_or_partial_reply_changes_nothing(self, project_dir, reply, why):
        before = _brief(project_dir)
        (fixed, skipped), _ = _fix(project_dir, reply)
        assert fixed == [] and skipped == {'act1-sc01': why}
        assert _brief(project_dir) == before

    def test_markdown_bold_fields_are_parsed(self, project_dir):
        reply = ('**GOAL:** keep the map\n**CONFLICT:** the storm\n'
                 '**CRISIS:** the door locks\n- **DECISION:** she stays')
        (fixed, _), _ = _fix(project_dir, reply)
        assert fixed == ['act1-sc01']
        assert _brief(project_dir)['decision'] == 'she stays'

    def test_the_scenes_old_goal_does_not_vouch_for_a_name(self, project_dir):
        _set_brief(project_dir, 'act1-sc01', conflict='the warden Ostrander blocks her')
        (fixed, _), _ = _fix(project_dir, REPLY.format(g='x', c='Ostrander blocks her'))
        assert fixed == []

    def test_the_scenes_kept_fields_and_prose_vouch_for_a_name(self, project_dir):
        _set_brief(project_dir, 'act1-sc01', key_actions='Meets Ostrander')
        _append_prose(project_dir, 'act1-sc01', '\nVellstrom watched from the door.\n')
        (fixed, _), _ = _fix(project_dir, REPLY.format(
            g='x', c='Ostrander and Vellstrom block her'))
        assert fixed == ['act1-sc01']

    def test_other_scenes_briefs_and_prose_do_not_vouch(self, project_dir):
        _set_brief(project_dir, 'act1-sc02', goal='find Ostrander')
        _append_prose(project_dir, 'act1-sc02', '\nVellstrom watched from the door.\n')
        (_, skipped), _ = _fix(project_dir, REPLY.format(
            g='x', c='Ostrander and Vellstrom block her'))
        assert skipped == {'act1-sc01': 'named Ostrander, Vellstrom'}

    def test_prompt_carries_the_scene_and_forbids_inventing(self, project_dir):
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md')) as f:
            opening = ' '.join(f.read().split()[:12])
        _, prompt = _fix(project_dir, REPLY.format(g='x', c='y'))
        assert opening in prompt
        assert 'Location: Pressure Cartography Office' in prompt
        assert 'Characters: Dorren Hayle;Tessa Merrin;Pell' in prompt
        assert 'Key actions: Reviews maps;Finds anomaly' in prompt
        assert 'Do not introduce any person, place, organization or event' in prompt

    def test_undrafted_scene_says_so(self, project_dir):
        os.remove(os.path.join(project_dir, 'scenes', 'act1-sc01.md'))
        _, prompt = _fix(project_dir, REPLY.format(g='x', c='y'))
        assert '<scene>\n(not drafted yet)\n</scene>' in prompt

    def test_long_prose_is_cut_and_says_so(self, project_dir, monkeypatch, capsys):
        monkeypatch.setattr(cmd_revise, '_PROSE_CONTEXT_WORDS', 5)
        _, prompt = _fix(project_dir, REPLY.format(g='x', c='y'))
        assert ' [...]\n</scene>' in prompt
        assert 'sees the first 5 of its' in capsys.readouterr().out

    def test_non_utf8_prose_does_not_crash(self, project_dir):
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md'), 'ab') as f:
            f.write(b'\nthe caf\xe9 door\n')
        (fixed, _), prompt = _fix(project_dir, REPLY.format(g='x', c='y'))
        assert fixed == ['act1-sc01'] and 'caf�' in prompt


def test_only_rewritten_scenes_are_redrafted(project_dir, capsys):
    with patch('storyforge.cmd_revise._fix_upstream_briefs',
               return_value=(['a'], {'b': 'named Mallen'})), \
         patch('storyforge.cmd_revise._redraft_or_halt') as redraft:
        assert _fix_and_redraft(project_dir, ['a', 'b']) == (['a'], {'b': 'named Mallen'})
    redraft.assert_called_once_with(project_dir, ['a'])
    out = capsys.readouterr().out
    assert 'left 1 of 2 scenes unchanged' in out and 'b: named Mallen' in out


def test_nothing_rewritten_redrafts_nothing(project_dir):
    with patch('storyforge.cmd_revise._fix_upstream_briefs', return_value=([], {'a': 'no reply'})), \
         patch('storyforge.cmd_revise._redraft_or_halt') as redraft:
        assert _fix_and_redraft(project_dir, ['a'])[0] == []
    redraft.assert_not_called()


class TestHoneBriefsGuard:
    """hone's brief rewrites (concretize, trim, evaluation fixes) go through
    the same check as revise's upstream brief fix."""

    def _hone(self, project_dir, monkeypatch, reply):
        from storyforge import api
        from storyforge.hone import hone_briefs
        findings = os.path.join(project_dir, 'working', 'findings.csv')
        os.makedirs(os.path.dirname(findings), exist_ok=True)
        with open(findings, 'w') as f:
            f.write('scene_id|target_file|fields|guidance\n')
            f.write('act1-sc01|scene-briefs.csv|goal|Make the goal concrete\n')
        monkeypatch.setattr(api, 'invoke_to_file', lambda *a, **kw: None)
        monkeypatch.setattr(api, 'extract_text_from_file', lambda path: reply)
        return hone_briefs(os.path.join(project_dir, 'reference'), project_dir,
                           scene_ids=['act1-sc01'], model='m',
                           log_dir=os.path.join(project_dir, 'working', 'logs'),
                           coaching_level='full', findings_file=findings)

    def _goal(self, project_dir):
        from storyforge.elaborate import _read_csv_as_map
        return _read_csv_as_map(os.path.join(
            project_dir, 'reference', 'scene-briefs.csv'))['act1-sc01']['goal']

    def test_a_rewrite_naming_someone_the_book_never_does_is_refused(
            self, project_dir, monkeypatch, capsys):
        before = self._goal(project_dir)
        result = self._hone(project_dir, monkeypatch,
                            'goal: get Detective Ruzek to sign off on the audit')
        assert result['fields_rewritten'] == 0 and result['scenes_rewritten'] == 0
        assert result['rejected'] == {
            'act1-sc01': ['evaluation rewrite of goal named Detective, Ruzek']}
        assert self._goal(project_dir) == before
        assert 'WARNING: not rewriting act1-sc01' in capsys.readouterr().out

    def test_a_rewrite_in_the_books_own_names_is_kept(self, project_dir, monkeypatch):
        result = self._hone(project_dir, monkeypatch,
                            'goal: Dorren files the Deep Archive audit by nightfall')
        assert result['fields_rewritten'] == 1 and result['rejected'] == {}
        assert self._goal(project_dir) == 'Dorren files the Deep Archive audit by nightfall'

    def test_an_intent_rewrite_naming_someone_new_is_refused(self, project_dir, monkeypatch):
        from storyforge import api
        from storyforge.elaborate import _read_csv_as_map
        from storyforge.hone import hone_intent
        findings = os.path.join(project_dir, 'working', 'findings.csv')
        os.makedirs(os.path.dirname(findings), exist_ok=True)
        with open(findings, 'w') as f:
            f.write('scene_id|target_file|fields|guidance\n')
            f.write('act1-sc01|scene-intent.csv|function|Sharpen the function\n')
        monkeypatch.setattr(api, 'invoke_to_file', lambda *a, **kw: None)
        monkeypatch.setattr(api, 'extract_text_from_file',
                            lambda path: 'function: shows Mallen taking over the office')
        intent_csv = os.path.join(project_dir, 'reference', 'scene-intent.csv')
        before = _read_csv_as_map(intent_csv)['act1-sc01']['function']

        result = hone_intent(os.path.join(project_dir, 'reference'), project_dir,
                             scene_ids=['act1-sc01'], model='m',
                             log_dir=os.path.join(project_dir, 'working', 'logs'),
                             coaching_level='full', findings_file=findings)

        assert result['rejected'] == {
            'act1-sc01': ['evaluation rewrite of function named Mallen']}
        assert _read_csv_as_map(intent_csv)['act1-sc01']['function'] == before

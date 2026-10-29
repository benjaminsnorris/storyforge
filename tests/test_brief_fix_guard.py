"""Regression tests for shared-dark (April 2026): revise's upstream brief fix
was given only a scene's title, POV and emotional arc, and rewrote 21 of 23
Act 1 briefs into another story (a captor named Mallen, Detective Olinsky,
Sergeant Voigt, a custody hearing). The redrafts then followed those briefs.
The fix now sees the scene's characters, place, plan and prose, and a rewrite
that names someone the book never mentions is rejected."""

import os
from unittest.mock import patch

import pytest

from storyforge.cmd_revise import _fix_and_redraft, _fix_upstream_briefs, _invented_names

# From shared-dark 0940bd4d (claires-cold), the rewrite that brought in Mallen.
MALLEN = ('The captor, Mallen, kneels without speaking and works with genuine, '
          "unhurried competence, and Claire's body is beginning to distinguish his touch")


class TestInventedNames:
    def test_flags_a_name_the_book_never_uses(self):
        assert _invented_names([MALLEN], 'Claire is held in a basement room.') == ['Mallen']

    def test_book_names_and_possessives_pass(self):
        assert _invented_names(["Claire's hands shake when Hank speaks."],
                               'Claire and Hank') == []

    def test_sentence_and_field_openers_are_not_names(self):
        assert _invented_names(['Refuses to answer. Stays silent: Holds still.'], '') == []

    def test_capitalized_ordinary_word_the_book_uses_passes(self):
        assert _invented_names(['she reaches the Basement door'], 'the basement') == []


REPLY = 'GOAL: {g}\nCONFLICT: {c}\nCRISIS: the door locks\nDECISION: she stays'


def _brief(project_dir, sid='act1-sc01'):
    from storyforge.elaborate import _read_csv_as_map
    return _read_csv_as_map(os.path.join(project_dir, 'reference', 'scene-briefs.csv'))[sid]


def _fix(project_dir, reply, sid='act1-sc01'):
    with patch('storyforge.cmd_revise.invoke_api', return_value=reply) as api, \
         patch('storyforge.cmd_revise.select_model', return_value='m'):
        result = _fix_upstream_briefs(project_dir, [sid])
    return result, api.call_args[0][0]


class TestFixUpstreamBriefs:
    def test_rewrite_naming_a_stranger_is_rejected(self, project_dir, capsys):
        before = _brief(project_dir)
        result, _ = _fix(project_dir, REPLY.format(
            g='keep the ledger closed', c='the warden, Mallen, demands it'))
        assert result == []
        assert _brief(project_dir) == before
        out = capsys.readouterr().out
        assert 'WARNING' in out and 'Mallen' in out and 'brief is unchanged' in out

    def test_grounded_rewrite_is_written(self, project_dir):
        result, _ = _fix(project_dir, REPLY.format(
            g='keep the map hidden', c='the storm pins her in place'))
        assert result == ['act1-sc01']
        assert _brief(project_dir)['conflict'] == 'the storm pins her in place'

    def test_prompt_carries_the_scene_and_forbids_inventing(self, project_dir):
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md')) as f:
            opening = ' '.join(f.read().split()[:12])
        _, prompt = _fix(project_dir, REPLY.format(g='x', c='y'))
        assert opening in prompt
        assert 'Do not introduce any person, place, organization or event' in prompt


def test_only_rewritten_scenes_are_redrafted(project_dir):
    with patch('storyforge.cmd_revise._fix_upstream_briefs', return_value=['a']), \
         patch('storyforge.cmd_revise._redraft_or_halt') as redraft:
        assert _fix_and_redraft(project_dir, ['a', 'b']) == ['a']
    redraft.assert_called_once_with(project_dir, ['a'])


def test_nothing_rewritten_redrafts_nothing(project_dir):
    with patch('storyforge.cmd_revise._fix_upstream_briefs', return_value=[]), \
         patch('storyforge.cmd_revise._redraft_or_halt') as redraft:
        assert _fix_and_redraft(project_dir, ['a']) == []
    redraft.assert_not_called()

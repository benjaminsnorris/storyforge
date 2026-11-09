"""Plan decision 9: the briefs stage never writes goal, conflict, crisis or
decision (the author's notes, `elaborate.AUTHOR_NOTE_COLUMNS`); a reply that
gives them is not written, and an earlier value is kept and warned about."""

import os

from storyforge.elaborate import _read_csv_as_map


def _ref(proj):
    return os.path.join(proj, 'reference')


class TestTheBriefsStageNeverWritesThem:
    def test_a_reply_with_them_is_not_written_and_an_old_value_is_kept(
            self, project_dir, monkeypatch, mock_git, mock_costs, mock_api, capsys):
        from storyforge.cmd_elaborate import main
        from storyforge.prompts_elaborate import BRIEFS_OUTPUT_HEADER
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
        monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root',
                            lambda: project_dir)
        monkeypatch.setattr('storyforge.cmd_elaborate.select_model', lambda tier: 'm')
        path = os.path.join(_ref(project_dir), 'scene-briefs.csv')
        before = _read_csv_as_map(path)['act1-sc01']['goal']
        assert before
        header = BRIEFS_OUTPUT_HEADER + '|goal|crisis'
        n = len(BRIEFS_OUTPUT_HEADER.split('|'))
        row = ['act1-sc01', 'no-and', 'Dorren files the anomaly'] + [''] * (n - 3)
        row[-1] = 'false'
        reply = ('```briefs-csv\n' + header + '\n' + '|'.join(row + ['A new goal', 'A dilemma'])
                 + '\n```\n')
        mock_api.set_response_fn(lambda prompt: reply)
        try:
            main(['--stage', 'briefs', '--scene', 'act1-sc01'])
        except SystemExit:
            pass
        after = _read_csv_as_map(path)['act1-sc01']
        assert after['goal'] == before
        assert after['crisis'] != 'A dilemma'
        out = capsys.readouterr().out
        assert "left out the reply's goal, crisis" in out
        assert ("WARNING: kept the filled author's notes of 1 scene(s): act1-sc01 (goal, "
                'conflict, crisis, decision, key_dialogue, emotions, motifs)') in out

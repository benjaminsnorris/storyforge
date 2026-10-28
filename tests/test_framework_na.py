"""Narrative frameworks a book doesn't use score n/a, not 1 (evals F-036).

On The Great Gatsby the act rubric's 1 ("absent, or applied as a rigid
checklist") made a framework the book never uses read as poor execution:
act 1 was the diagnosis's worst item for the monomyth because "Nick
functions as observer rather than hero". Not using a framework is a creative
choice; n/a is left out of averages, diagnosis and proposals.
"""

import os

from storyforge.scoring import _sc_class, generate_diagnosis


def _prompt(plugin_dir, name):
    with open(os.path.join(plugin_dir, 'scripts', 'prompts', 'scoring', name)) as f:
        return f.read()


def test_act_prompt_asks_for_na_on_an_unused_framework(plugin_dir):
    prompt = _prompt(plugin_dir, 'act-level.md')
    assert 'does not use (its structure follows another logic) scores `n/a`, not 1' in prompt
    assert 'character_web and character_as_theme always get a number' in prompt


def test_novel_prompt_asks_for_na_on_an_unused_framework(plugin_dir):
    prompt = _prompt(plugin_dir, 'novel-narrative.md')
    assert 'Write `n/a` for a framework the manuscript does not use' in prompt
    assert '1=Not present' not in prompt


def test_na_is_left_out_of_the_diagnosis(tmp_path):
    cycle = tmp_path / 'cycle-1'
    cycle.mkdir()
    (cycle / 'act-scores.csv').write_text(
        'id|campbells_monomyth|kishotenketsu|character_web\n'
        'act-1|n/a|n/a|5\n'
        'act-2|4|n/a|4\n')
    weights = tmp_path / 'craft-weights.csv'
    weights.write_text('section|principle|weight\nnarrative|campbells_monomyth|5\n')
    generate_diagnosis(str(cycle), '-', str(weights))
    rows = {line.split('|')[0]: line.split('|')
            for line in (cycle / 'diagnosis.csv').read_text().splitlines()[1:]}
    # Averaged over the act that uses it; act 1 is not its worst item
    assert rows['campbells_monomyth'][2] == '4.0'
    assert rows['campbells_monomyth'][3] == ''
    # Used by no act: no diagnosis row, so no proposal
    assert 'kishotenketsu' not in rows


def test_na_has_no_score_colour():
    assert _sc_class('n/a') == ''


def test_dashboard_draws_na_as_na_not_zero(plugin_dir):
    with open(os.path.join(plugin_dir, 'templates', 'dashboard.html')) as f:
        html = f.read()
    assert 'var na = isNaN(parseInt(act[p]));' in html
    assert "var na = isNaN(parseInt(p.score));" in html
    assert 'parseInt(act[p]) || 0' not in html


def test_merge_appends_on_a_new_line_when_the_target_has_no_final_newline(tmp_path):
    """Evals F-050: act scores are merged one act at a time, and the first
    act's file has no final newline, so act 3's row was glued onto act 1's
    ("act-1|...|5act-3|4|...") and the diagnosis lost act 3."""
    from storyforge.scoring import merge_score_files, _read_csv
    target, source = tmp_path / 'act-scores.csv', tmp_path / 'act-3.csv'
    target.write_text('id|three_act\nact-1|4')
    source.write_text('id|three_act\nact-3|5\n')
    merge_score_files(str(target), str(source))
    _header, rows = _read_csv(str(target))
    assert rows == [['act-1', '4'], ['act-3', '5']]


def test_merge_adds_no_blank_line_when_the_target_ends_with_a_newline(tmp_path):
    from storyforge.scoring import merge_score_files
    target, source = tmp_path / 'act-scores.csv', tmp_path / 'act-2.csv'
    target.write_text('id|three_act\nact-1|4\n')
    source.write_text('id|three_act\nact-2|5\n')
    merge_score_files(str(target), str(source))
    assert target.read_text() == 'id|three_act\nact-1|4\nact-2|5\n'

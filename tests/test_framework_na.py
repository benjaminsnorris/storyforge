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


# The dashboard's n/a drawing (radar, drawers, frameworkScoreText) is tested
# in Bookshelf, which renders the dashboard (#371; bookshelf
# tests/unit/dashboard/render.test.ts).

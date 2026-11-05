"""`write`'s cost forecast (#563: G-027, B-026).

The forecast was priced from a flat token model (each scene's words plus
3,000 tokens, 1,500 out), so on Gawain it said $2.18 to draft 42 scenes
that cost $8.19, and on Beowulf $3.00 for three scenes that cost $1.16; and
`--dry-run` printed none. Once a book has drafts in its cost ledger the
forecast is priced from them; before that the token model counts the
earlier prose and shared context the draft is sent from cache; and a dry
run prints it.
"""

import os

import pytest

from storyforge import costs
from storyforge.cmd_write import _forecast_earlier_words, main

HEADER = costs.LEDGER_HEADER


def _ledger(project_dir, rows):
    path = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(HEADER + '\n')
        for op, target, cost in rows:
            f.write(f'2026-11-04T07:00:00|{op}|{target}|claude-opus-5-5|1|1|0|0|{cost}|0\n')


def test_priced_from_the_ledgers_drafts_once_it_has_three(tmp_path):
    # Beowulf's first three scenes: draft $0.41, gate $0.75 (B-026)
    _ledger(str(tmp_path), [('draft', 'a', 0.13), ('draft', 'b', 0.14), ('draft', 'c', 0.14),
                            ('gate', 'a', 0.30), ('gate', 'b', 0.20), ('gate-fix', 'b', 0.05),
                            ('gate', 'c', 0.20), ('score', 'a', 5.0)])
    f = costs.forecast_write(str(tmp_path), ['d', 'e', 'f'], 2000, 'claude-opus-5-5',
                             gate_per_scene=0.6)
    assert f.draft == pytest.approx(0.41)
    assert f.gate == pytest.approx(0.75)
    assert "3 drafts so far" in f.basis


def test_ungated_ledger_forecast_has_no_gate(tmp_path):
    _ledger(str(tmp_path), [('draft', s, 0.2) for s in 'abc'] + [('gate', 'a', 9.0)])
    f = costs.forecast_write(str(tmp_path), ['d'], 2000, 'claude-opus-5-5')
    assert (f.draft, f.gate) == (pytest.approx(0.2), 0.0)


def test_too_few_drafts_falls_back_to_the_token_model(tmp_path):
    _ledger(str(tmp_path), [('draft', 'a', 5.0), ('draft', 'b', 5.0)])
    f = costs.forecast_write(str(tmp_path), ['c'], 2000, 'claude-opus-5-5',
                             gate_per_scene=0.6)
    assert f.draft < 1.0 and f.gate == pytest.approx(0.6)
    assert 'once it has 3 drafts' in f.basis


def test_the_token_model_counts_cached_context_and_earlier_prose(tmp_path):
    """Gawain: 42 scenes of about 1,700 words drafted with the manuscript
    so far and an ~80k-token shared context cost $8.19; the old model said
    $2.18."""
    ids = [f's{i}' for i in range(42)]
    earlier = {s: i * 1700 for i, s in enumerate(ids)}
    f = costs.forecast_write(str(tmp_path), ids, 1700, 'claude-opus-5-5',
                             earlier_words=earlier, shared_tokens=80_000)
    assert 5.0 < f.draft < 12.0
    bare = costs.forecast_write(str(tmp_path), ids, 1700, 'claude-opus-5-5')
    assert bare.draft < f.draft


def test_earlier_words_follow_the_prior_prose_mode(project_dir):
    from storyforge import ledger
    order = sorted(ledger.scene_order(project_dir), key=ledger.scene_order(project_dir).get)
    pending = order[1:3]
    assert _forecast_earlier_words(project_dir, pending, 'none', 1000) == {}
    assert _forecast_earlier_words(project_dir, pending, 'window', 1000) == {
        s: 2000 for s in pending}
    full = _forecast_earlier_words(project_dir, pending, 'full', 1000)
    # the second pending scene follows the first, still to draft at avg words
    assert full[pending[1]] == full[pending[0]] + 1000


def test_dry_run_prints_the_forecast(mock_api, mock_git, mock_costs, project_dir,
                                     monkeypatch, capsys):
    monkeypatch.setattr('storyforge.cmd_write.detect_project_root', lambda: project_dir)
    main(['--dry-run', '--scenes', 'act1-sc01'])
    out = capsys.readouterr().out
    assert 'Cost forecast: ~$' in out
    assert mock_api.call_count == 0


def test_dry_run_over_the_threshold_says_so_and_goes_on(mock_api, mock_git, mock_costs,
                                                       project_dir, monkeypatch, capsys):
    monkeypatch.setattr('storyforge.cmd_write.detect_project_root', lambda: project_dir)
    mock_costs.threshold_ok = False
    main(['--dry-run', '--scenes', 'act1-sc01'])   # no SystemExit: nothing would be spent
    assert 'a real run would stop before drafting' in capsys.readouterr().out.replace('\n', ' ')

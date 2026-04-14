"""Tests for targeted scoring (--principles flag)."""

import os
import sys

import pytest


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

def test_parse_principles_flag():
    from storyforge.cmd_score import parse_args
    args = parse_args(['--principles', 'prose_repetition'])
    assert args.principles == 'prose_repetition'


def test_parse_multiple_principles():
    from storyforge.cmd_score import parse_args
    args = parse_args(['--principles', 'prose_repetition,prose_naturalness'])
    assert args.principles == 'prose_repetition,prose_naturalness'


def test_parse_principles_with_scenes():
    from storyforge.cmd_score import parse_args
    args = parse_args(['--principles', 'prose_repetition', '--scenes', 'a,b'])
    assert args.principles == 'prose_repetition'
    assert args.scenes == 'a,b'


def test_no_principles_flag_defaults_to_none():
    from storyforge.cmd_score import parse_args
    args = parse_args([])
    assert args.principles is None


# ---------------------------------------------------------------------------
# Principle validation
# ---------------------------------------------------------------------------

def test_load_known_principles(plugin_dir):
    from storyforge.cmd_score import _load_known_principles
    known = _load_known_principles(plugin_dir)
    assert 'prose_repetition' in known
    assert 'prose_naturalness' in known
    assert 'economy_clarity' in known
    assert len(known) >= 25


def test_parse_principles_valid(plugin_dir):
    from storyforge.cmd_score import _parse_principles
    result = _parse_principles('prose_repetition,prose_naturalness', plugin_dir)
    assert result == ['prose_repetition', 'prose_naturalness']


def test_parse_principles_unknown_exits(plugin_dir):
    from storyforge.cmd_score import _parse_principles
    with pytest.raises(SystemExit):
        _parse_principles('nonexistent_principle', plugin_dir)


# ---------------------------------------------------------------------------
# Deterministic detection
# ---------------------------------------------------------------------------

def test_deterministic_only_single():
    from storyforge.cmd_score import DETERMINISTIC_PRINCIPLES
    assert 'prose_repetition' in DETERMINISTIC_PRINCIPLES


def test_deterministic_only_detection():
    from storyforge.cmd_score import DETERMINISTIC_PRINCIPLES
    targeted = ['prose_repetition']
    assert all(p in DETERMINISTIC_PRINCIPLES for p in targeted)


def test_mixed_not_deterministic_only():
    from storyforge.cmd_score import DETERMINISTIC_PRINCIPLES
    targeted = ['prose_repetition', 'prose_naturalness']
    assert not all(p in DETERMINISTIC_PRINCIPLES for p in targeted)


# ---------------------------------------------------------------------------
# Evaluation criteria filtering
# ---------------------------------------------------------------------------

def _write_diagnostics(path, principles):
    """Write a minimal diagnostics CSV with given principles."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('principle|question\n')
        for p in principles:
            f.write(f'{p}|Is {p} maintained?\n')


def _write_guide(path):
    """Write a minimal principle guide."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('# Principle Guide\n')


def test_build_criteria_no_filter(tmp_path):
    from storyforge.scoring import build_evaluation_criteria
    diag = str(tmp_path / 'diagnostics.csv')
    guide = str(tmp_path / 'guide.md')
    _write_diagnostics(diag, ['economy_clarity', 'prose_naturalness', 'fictive_dream'])
    _write_guide(guide)

    result = build_evaluation_criteria(diag, guide)
    assert 'economy_clarity' in result
    assert 'prose_naturalness' in result
    assert 'fictive_dream' in result


def test_build_criteria_with_filter(tmp_path):
    from storyforge.scoring import build_evaluation_criteria
    diag = str(tmp_path / 'diagnostics.csv')
    guide = str(tmp_path / 'guide.md')
    _write_diagnostics(diag, ['economy_clarity', 'prose_naturalness', 'fictive_dream'])
    _write_guide(guide)

    result = build_evaluation_criteria(diag, guide, principles=['prose_naturalness'])
    assert 'prose_naturalness' in result
    assert 'economy_clarity' not in result
    assert 'fictive_dream' not in result


def test_build_criteria_filter_empty_list(tmp_path):
    from storyforge.scoring import build_evaluation_criteria
    diag = str(tmp_path / 'diagnostics.csv')
    guide = str(tmp_path / 'guide.md')
    _write_diagnostics(diag, ['economy_clarity', 'prose_naturalness'])
    _write_guide(guide)

    # Empty list should return nothing (no principles match)
    result = build_evaluation_criteria(diag, guide, principles=[])
    assert 'economy_clarity' not in result
    assert 'prose_naturalness' not in result


# ---------------------------------------------------------------------------
# Weighted text filtering
# ---------------------------------------------------------------------------

def _write_weights(path, rows):
    """Write a craft-weights CSV."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('section|principle|weight|author_weight|notes\n')
        for section, principle, weight in rows:
            f.write(f'{section}|{principle}|{weight}||\n')


def test_weighted_text_no_filter(tmp_path):
    from storyforge.scoring import build_weighted_text
    wf = str(tmp_path / 'weights.csv')
    _write_weights(wf, [
        ('prose_craft', 'economy_clarity', '8'),
        ('prose_craft', 'prose_naturalness', '5'),
    ])
    result = build_weighted_text(wf)
    assert 'economy_clarity' in result
    assert 'prose_naturalness' not in result  # weight < 7


def test_weighted_text_with_filter(tmp_path):
    from storyforge.scoring import build_weighted_text
    wf = str(tmp_path / 'weights.csv')
    _write_weights(wf, [
        ('prose_craft', 'economy_clarity', '8'),
        ('scene_craft', 'every_scene_must_turn', '9'),
    ])
    result = build_weighted_text(wf, principles=['economy_clarity'])
    assert 'economy_clarity' in result
    assert 'every_scene_must_turn' not in result


# ---------------------------------------------------------------------------
# Deterministic-only fast path (end-to-end)
# ---------------------------------------------------------------------------

def test_deterministic_dry_run(project_dir, plugin_dir, monkeypatch):
    """--principles prose_repetition --dry-run should report $0 cost."""
    from storyforge.cmd_score import main

    monkeypatch.setenv('STORYFORGE_PLUGIN_DIR', plugin_dir)
    monkeypatch.chdir(project_dir)

    output_lines = []
    import storyforge.common
    original_log = storyforge.common.log

    def capture_log(msg):
        output_lines.append(msg)

    monkeypatch.setattr('storyforge.common.log', capture_log)
    monkeypatch.setattr('storyforge.cmd_score.log', capture_log)

    main(['--principles', 'prose_repetition', '--dry-run'])

    combined = '\n'.join(output_lines)
    assert 'Deterministic' in combined
    assert '$0.00' in combined


def test_deterministic_scoring_writes_results(project_dir, plugin_dir, monkeypatch):
    """--principles prose_repetition should write scores without API calls."""
    from storyforge.cmd_score import main

    monkeypatch.setenv('STORYFORGE_PLUGIN_DIR', plugin_dir)
    monkeypatch.chdir(project_dir)

    # Stub out git operations
    monkeypatch.setattr('storyforge.cmd_score.create_branch', lambda *a, **k: None)
    monkeypatch.setattr('storyforge.cmd_score.ensure_branch_pushed', lambda *a, **k: None)
    monkeypatch.setattr('storyforge.cmd_score.commit_and_push', lambda *a, **k: None)

    main(['--principles', 'prose_repetition'])

    # Check that scores were written
    scores_dir = os.path.join(project_dir, 'working', 'scores')
    # Find the cycle directory
    cycle_dirs = [d for d in os.listdir(scores_dir)
                  if d.startswith('cycle-') and os.path.isdir(os.path.join(scores_dir, d))]
    assert cycle_dirs, 'No cycle directory created'

    cycle_dir = os.path.join(scores_dir, cycle_dirs[0])
    rep_path = os.path.join(cycle_dir, 'repetition-latest.csv')
    assert os.path.isfile(rep_path), 'repetition-latest.csv not created'

    with open(rep_path) as f:
        lines = f.readlines()
    assert lines[0].strip() == 'id|prose_repetition'
    # Should have scores for scenes that exist as files
    assert len(lines) > 1

    # Should also have scene-scores.csv (merged)
    scene_scores = os.path.join(cycle_dir, 'scene-scores.csv')
    assert os.path.isfile(scene_scores), 'scene-scores.csv not created'

    # latest symlink should exist
    latest = os.path.join(scores_dir, 'latest')
    assert os.path.islink(latest)

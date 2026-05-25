"""Tests for the elaboration-v1 cmd_score entry points (#229).

Covers `storyforge score --level N`, `--all-levels`, `--compare`,
`--drift`. These all short-circuit the existing scene-prose scoring path.
"""

import os

import pytest

from storyforge.cmd_score import main as score_main


def test_level_zero_runs_on_fixture(project_dir, monkeypatch, capsys):
    """`storyforge score --level 0` runs the logline floor checks."""
    monkeypatch.chdir(project_dir)
    score_main(['--level', '0'])
    out = capsys.readouterr().out
    assert '[level 0]' in out
    assert 'logline' in out


def test_level_three_against_spine_fixture(project_dir, monkeypatch, capsys):
    """Level 3 (spine) checks run; project_dir fixture has no spine.csv yet
    so the floor check should report it as missing — that's a real signal,
    not a test failure."""
    monkeypatch.chdir(project_dir)
    score_main(['--level', '3'])
    out = capsys.readouterr().out
    assert '[level 3]' in out
    # Without spine.csv, expect failure on the floor check
    assert 'spine.csv is missing' in out or 'spine' in out


def test_all_levels_emits_seven_reports(project_dir, monkeypatch, capsys):
    monkeypatch.chdir(project_dir)
    score_main(['--all-levels'])
    out = capsys.readouterr().out
    for level in range(0, 7):
        assert f'[level {level}]' in out


def test_compare_requires_level(project_dir, monkeypatch):
    """--compare without --level should exit with an error."""
    monkeypatch.chdir(project_dir)
    with pytest.raises(SystemExit) as exc:
        score_main(['--compare', 'one logline', 'another logline'])
    assert exc.value.code == 1


def test_compare_at_non_prose_level_errors(project_dir, monkeypatch):
    """--compare is only supported at the prose tier (0-2) in v1."""
    monkeypatch.chdir(project_dir)
    with pytest.raises(SystemExit) as exc:
        score_main(['--compare', 'a', 'b', '--level', '3'])
    assert exc.value.code == 1


def test_compare_logline_writes_report(project_dir, monkeypatch, capsys):
    """--compare --level 0 with two candidate strings produces a report file."""
    monkeypatch.chdir(project_dir)
    score_main([
        '--level', '0',
        '--compare',
        'A cartographer who maps the unmappable loses his daughter.',
        'A cartographer must find his daughter using maps no one else can read.',
    ])
    out = capsys.readouterr().out
    assert 'Comparison: logline candidates (2)' in out
    assert 'does not recommend a winner' in out

    # A file was written under working/
    working = os.path.join(project_dir, 'working')
    files = [f for f in os.listdir(working) if f.startswith('comparison-')]
    assert files, 'expected a comparison-*.md file under working/'


def test_compare_reads_files_as_candidates(project_dir, monkeypatch, capsys, tmp_path):
    """If a candidate arg is an existing file path, it's read as the candidate."""
    candidate_path = tmp_path / 'logline-A.md'
    candidate_path.write_text('A candidate logline loaded from a file.')

    monkeypatch.chdir(project_dir)
    score_main([
        '--level', '0',
        '--compare',
        str(candidate_path),
        'A second candidate provided inline.',
    ])
    out = capsys.readouterr().out
    assert 'A candidate logline loaded from a file.' in out


def test_drift_runs_against_fixture(project_dir, monkeypatch, capsys):
    """--drift produces the read-only deterministic report."""
    monkeypatch.chdir(project_dir)
    score_main(['--drift'])
    out = capsys.readouterr().out
    assert 'Drift report' in out
    assert 'Floor checks per level' in out
    assert 'Registry consistency per level' in out


def test_existing_score_path_unaffected(monkeypatch):
    """The existing scoring path (no --level, --compare, etc.) still parses
    correctly — the v1 flags are additive, not replacement."""
    # We don't run the existing path (it would invoke the API); just
    # confirm parse_args succeeds with the old flag set.
    from storyforge.cmd_score import parse_args
    args = parse_args(['--deterministic', '--scenes', 'a,b'])
    assert args.deterministic is True
    assert args.scenes == 'a,b'
    assert args.level is None
    assert args.compare is None

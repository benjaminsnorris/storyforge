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


# ---------------------------------------------------------------------------
# v2 CLI flags (#231)
# ---------------------------------------------------------------------------

import json


def _mock_boundary_invoke(payload):
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 100, 'output_tokens': 50,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response
    return fake


def _seed_story_summary(project_dir):
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(
            '# Story summary\n\n'
            '## Logline\nA test logline.\n\n'
            '## Synopsis\nA test synopsis. With more text. And more. And more.\n\n'
        )


def test_boundary_flag_invokes_score_boundary(project_dir, monkeypatch, capsys):
    """`storyforge score --boundary 0->1` dispatches to scoring_boundary."""
    _seed_story_summary(project_dir)
    monkeypatch.chdir(project_dir)

    fake = _mock_boundary_invoke({
        'upstream_summary': 'U', 'downstream_summary': 'D',
        'alignment': 'They differ.', 'proposed_verdict': 'correct=upstream',
        'rationale': 'because of X',
    })
    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', fake)

    score_main(['--boundary', '0->1'])
    out = capsys.readouterr().out
    assert '0->1' in out
    assert 'correct=upstream' in out


def test_invalid_boundary_string_exits_nonzero(project_dir, monkeypatch):
    monkeypatch.chdir(project_dir)
    with pytest.raises(SystemExit) as exc:
        score_main(['--boundary', '99->100'])
    assert exc.value.code == 1


def test_all_boundaries_runs_all(project_dir, monkeypatch, capsys):
    _seed_story_summary(project_dir)
    monkeypatch.chdir(project_dir)

    fake = _mock_boundary_invoke({
        'upstream_summary': 'U', 'downstream_summary': 'D',
        'alignment': 'a', 'proposed_verdict': 'both are right',
        'rationale': 'r',
    })
    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', fake)

    score_main(['--all-boundaries'])
    out = capsys.readouterr().out
    # At least the prose-tier boundaries should be visited
    assert '0->1' in out


def test_bible_consistency_flag(project_dir, monkeypatch, capsys):
    """`storyforge score --bible-consistency` dispatches to scoring_bible."""
    # Seed bibles + a drafted scene
    ref = os.path.join(project_dir, 'reference')
    with open(os.path.join(ref, 'character-bible.md'), 'w') as f:
        f.write('Character bible content.')
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'scene-1.md'), 'w') as f:
        f.write('Scene one prose.')

    monkeypatch.chdir(project_dir)

    findings_payload = {
        'findings': [{
            'bible': 'character-bible.md',
            'claim': 'X is true',
            'scene_says': 'but the scene shows Y',
            'fix_location': 'either',
            'severity': 'medium',
        }],
    }
    fake = _mock_boundary_invoke(findings_payload)
    from storyforge import api, scoring_bible
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_bible, 'invoke_to_file', fake)

    score_main(['--bible-consistency'])
    out = capsys.readouterr().out
    assert 'bible / scene-1' in out
    assert 'X is true' in out
    assert 'finding_id=' in out


def test_compare_semantic_flag_populates_ceiling(project_dir, monkeypatch, capsys):
    """`--compare ... --semantic` populates the ceiling axes table."""
    monkeypatch.chdir(project_dir)

    fake = _mock_boundary_invoke({
        'axes': [
            {'name': 'specificity', 'values': ['low', 'high']},
            {'name': 'irony between elements', 'values': ['absent', 'present']},
            {'name': 'memorable hook word', 'values': ['none', 'X']},
            {'name': 'genre/tone via imagery', 'values': ['generic', 'legible']},
        ],
    })
    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', fake)

    score_main([
        '--level', '0', '--semantic',
        '--compare', 'A logline.', 'A different logline.',
    ])
    out = capsys.readouterr().out
    # The populated ceiling header
    assert 'Ceiling axes (LLM)' in out
    # And the values came from the mock
    assert 'specificity' in out
    assert 'high' in out


def test_compare_without_semantic_still_renders_placeholders(project_dir, monkeypatch, capsys):
    monkeypatch.chdir(project_dir)
    score_main(['--level', '0', '--compare', 'A logline.', 'Another logline.'])
    out = capsys.readouterr().out
    assert 'run with --semantic to populate' in out


# ---------------------------------------------------------------------------
# v2 dry-run + API-key + cost gating (regression: PR #232 review)
# ---------------------------------------------------------------------------


def _fail_if_called(prompt, model, log_file, **kwargs):
    raise AssertionError(
        f'LLM was called during dry-run: model={model} log_file={log_file}'
    )


def test_boundary_dry_run_does_not_call_llm(project_dir, monkeypatch, capsys):
    """`--boundary --dry-run` must not call the LLM."""
    _seed_story_summary(project_dir)
    monkeypatch.chdir(project_dir)

    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', _fail_if_called)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', _fail_if_called)

    # Should complete without raising.
    score_main(['--boundary', '0->1', '--dry-run'])


def test_all_boundaries_dry_run_does_not_call_llm(project_dir, monkeypatch, capsys):
    """`--all-boundaries --dry-run` must not call the LLM."""
    _seed_story_summary(project_dir)
    monkeypatch.chdir(project_dir)

    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', _fail_if_called)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', _fail_if_called)

    score_main(['--all-boundaries', '--dry-run'])


def test_bible_consistency_dry_run_does_not_call_llm(project_dir, monkeypatch, capsys):
    """`--bible-consistency --dry-run` must not call the LLM."""
    ref = os.path.join(project_dir, 'reference')
    with open(os.path.join(ref, 'character-bible.md'), 'w') as f:
        f.write('content')
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'scene-1.md'), 'w') as f:
        f.write('Scene one prose.')

    monkeypatch.chdir(project_dir)

    from storyforge import api, scoring_bible
    monkeypatch.setattr(api, 'invoke_to_file', _fail_if_called)
    monkeypatch.setattr(scoring_bible, 'invoke_to_file', _fail_if_called)

    score_main(['--bible-consistency', '--dry-run'])


def test_compare_semantic_dry_run_does_not_call_llm(project_dir, monkeypatch, capsys):
    """`--compare ... --semantic --dry-run` must not call the LLM."""
    monkeypatch.chdir(project_dir)

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', _fail_if_called)

    score_main([
        '--level', '0', '--semantic', '--dry-run',
        '--compare', 'A logline.', 'A different logline.',
    ])
    out = capsys.readouterr().out
    # Without LLM, ceiling table should show placeholders, not real values.
    assert '—' in out or 'placeholder' in out.lower() or 'semantic' in out.lower()


def test_bible_consistency_without_api_key_errors_cleanly(project_dir, monkeypatch):
    """Missing ANTHROPIC_API_KEY should exit 1 with a clear message,
    not crash inside invoke_to_file with a network error."""
    ref = os.path.join(project_dir, 'reference')
    with open(os.path.join(ref, 'character-bible.md'), 'w') as f:
        f.write('content')
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'scene-1.md'), 'w') as f:
        f.write('Scene one prose.')

    monkeypatch.chdir(project_dir)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

    with pytest.raises(SystemExit) as exc:
        score_main(['--bible-consistency'])
    assert exc.value.code == 1


def test_boundary_without_api_key_errors_cleanly(project_dir, monkeypatch):
    """Same as above for --boundary."""
    _seed_story_summary(project_dir)
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

    with pytest.raises(SystemExit) as exc:
        score_main(['--boundary', '0->1'])
    assert exc.value.code == 1


def test_compare_semantic_without_api_key_errors_cleanly(project_dir, monkeypatch):
    """--compare --semantic should also gate on API key."""
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)

    with pytest.raises(SystemExit) as exc:
        score_main([
            '--level', '0', '--semantic',
            '--compare', 'A logline.', 'Another logline.',
        ])
    assert exc.value.code == 1


def test_compare_without_semantic_does_not_need_api_key(project_dir, monkeypatch, capsys):
    """Deterministic --compare (without --semantic) must NOT require a key."""
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    score_main([
        '--level', '0',
        '--compare', 'A logline.', 'Another logline.',
    ])
    out = capsys.readouterr().out
    assert 'Comparison' in out

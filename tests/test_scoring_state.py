"""Tests for scoring_state.py — overrides, verdicts, drafting mode (#229)."""

import os

import pytest

from storyforge.scoring_state import (
    OVERRIDES_PATH,
    VERDICTS_PATH,
    append_override,
    append_verdict,
    get_verdict,
    is_drafting_mode,
    is_override_accepted,
    read_overrides,
    read_verdicts,
)


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

def test_overrides_empty_when_no_file(tmp_path):
    assert read_overrides(str(tmp_path)) == []


def test_append_override_creates_file_with_header(tmp_path):
    append_override(
        scope='the-blank-page', axis='economy_clarity', finding_id='low-density',
        verdict='accepted', rationale='sparse is intentional here',
        recorded_at='2026-05-24',
        project_dir=str(tmp_path),
    )
    path = os.path.join(str(tmp_path), OVERRIDES_PATH)
    assert os.path.isfile(path)
    content = open(path).read()
    assert content.startswith(
        'scope|axis|finding_id|verdict|rationale|recorded_at\n'
    )
    assert 'the-blank-page' in content


def test_is_override_accepted_matches_exact_finding(tmp_path):
    append_override(
        'act1-sc12', 'brief_fidelity', 'missing-key-dialogue',
        'accepted', 'moved offstage on purpose', '2026-05-24',
        project_dir=str(tmp_path),
    )
    assert is_override_accepted(
        'act1-sc12', 'brief_fidelity', 'missing-key-dialogue',
        project_dir=str(tmp_path),
    )
    # Different finding for the same scene is NOT accepted
    assert not is_override_accepted(
        'act1-sc12', 'brief_fidelity', 'something-else',
        project_dir=str(tmp_path),
    )
    # Different scene is NOT accepted
    assert not is_override_accepted(
        'act1-sc13', 'brief_fidelity', 'missing-key-dialogue',
        project_dir=str(tmp_path),
    )


def test_rejected_verdict_does_not_count_as_accepted(tmp_path):
    append_override(
        'act1-sc01', 'pacing', 'too-slow',
        'rejected', 'the slow is the point', '2026-05-24',
        project_dir=str(tmp_path),
    )
    assert not is_override_accepted(
        'act1-sc01', 'pacing', 'too-slow', project_dir=str(tmp_path),
    )


def test_invalid_override_verdict_raises(tmp_path):
    with pytest.raises(ValueError):
        append_override(
            'a', 'b', 'c', 'maybe', 'reason', '2026-05-24',
            project_dir=str(tmp_path),
        )


# ---------------------------------------------------------------------------
# Verdicts (boundary diffs)
# ---------------------------------------------------------------------------

def test_verdicts_empty_when_no_file(tmp_path):
    assert read_verdicts(str(tmp_path)) == []


def test_append_verdict_creates_file(tmp_path):
    append_verdict(
        scope='act1-sc05', boundary='5->6', verdict='correct=upstream',
        rationale='the brief was right; the scene drifted',
        actor='author', recorded_at='2026-05-24',
        project_dir=str(tmp_path),
    )
    path = os.path.join(str(tmp_path), VERDICTS_PATH)
    assert os.path.isfile(path)
    content = open(path).read()
    assert 'scope|boundary|verdict|rationale|actor|recorded_at' in content
    assert 'act1-sc05' in content
    assert 'correct=upstream' in content


def test_get_verdict_returns_most_recent(tmp_path):
    """Append-only — later entry for the same (scope, boundary) wins."""
    for verdict, ts in (
        ('correct=upstream', '2026-05-20'),
        ('both are right', '2026-05-22'),
        ('needs work', '2026-05-24'),
    ):
        append_verdict(
            'act1-sc05', '5->6', verdict, 'rationale',
            'author', ts, project_dir=str(tmp_path),
        )
    result = get_verdict('act1-sc05', '5->6', project_dir=str(tmp_path))
    assert result is not None
    assert result['verdict'] == 'needs work'
    assert result['recorded_at'] == '2026-05-24'


def test_get_verdict_returns_none_when_unknown(tmp_path):
    assert get_verdict('nope', '5->6', project_dir=str(tmp_path)) is None


def test_invalid_boundary_verdict_raises(tmp_path):
    with pytest.raises(ValueError):
        append_verdict(
            'a', '5->6', 'invented-verdict', 'r', 'author', '2026-05-24',
            project_dir=str(tmp_path),
        )


def test_invalid_actor_raises(tmp_path):
    with pytest.raises(ValueError):
        append_verdict(
            'a', '5->6', 'both are right', 'r',
            'some-other-actor', '2026-05-24',
            project_dir=str(tmp_path),
        )


# ---------------------------------------------------------------------------
# Drafting mode
# ---------------------------------------------------------------------------

def test_drafting_mode_off_by_default(tmp_path, monkeypatch):
    """A project with no cascade_mode set and no env var → not drafting."""
    monkeypatch.delenv('STORYFORGE_DRAFTING', raising=False)
    (tmp_path / 'storyforge.yaml').write_text('project:\n  title: test\n')
    assert not is_drafting_mode(str(tmp_path))


def test_drafting_mode_on_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv('STORYFORGE_DRAFTING', '1')
    (tmp_path / 'storyforge.yaml').write_text('project:\n  title: test\n')
    assert is_drafting_mode(str(tmp_path))


def test_drafting_mode_on_via_yaml(tmp_path, monkeypatch):
    monkeypatch.delenv('STORYFORGE_DRAFTING', raising=False)
    (tmp_path / 'storyforge.yaml').write_text(
        'project:\n  title: test\n  cascade_mode: drafting\n'
    )
    assert is_drafting_mode(str(tmp_path))


def test_drafting_mode_paused_also_suppresses(tmp_path, monkeypatch):
    monkeypatch.delenv('STORYFORGE_DRAFTING', raising=False)
    (tmp_path / 'storyforge.yaml').write_text(
        'project:\n  title: test\n  cascade_mode: paused\n'
    )
    assert is_drafting_mode(str(tmp_path))


def test_drafting_mode_live_does_not_suppress(tmp_path, monkeypatch):
    monkeypatch.delenv('STORYFORGE_DRAFTING', raising=False)
    (tmp_path / 'storyforge.yaml').write_text(
        'project:\n  title: test\n  cascade_mode: live\n'
    )
    assert not is_drafting_mode(str(tmp_path))


def test_env_var_overrides_yaml(tmp_path, monkeypatch):
    """STORYFORGE_DRAFTING=1 wins over project.cascade_mode: live."""
    monkeypatch.setenv('STORYFORGE_DRAFTING', '1')
    (tmp_path / 'storyforge.yaml').write_text(
        'project:\n  title: test\n  cascade_mode: live\n'
    )
    assert is_drafting_mode(str(tmp_path))

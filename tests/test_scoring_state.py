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
        actor='author', coaching_level='full',
        recorded_at='2026-05-24',
        project_dir=str(tmp_path),
    )
    path = os.path.join(str(tmp_path), VERDICTS_PATH)
    assert os.path.isfile(path)
    content = open(path).read()
    assert 'scope|boundary|verdict|rationale|actor|coaching_level|recorded_at' in content
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
            'author', 'full', ts, project_dir=str(tmp_path),
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
            'a', '5->6', 'invented-verdict', 'r', 'author', 'full', '2026-05-24',
            project_dir=str(tmp_path),
        )


def test_invalid_actor_raises(tmp_path):
    with pytest.raises(ValueError):
        append_verdict(
            'a', '5->6', 'both are right', 'r',
            'some-other-actor', 'full', '2026-05-24',
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


def test_drafting_mode_unknown_value_warns_and_falls_to_live(tmp_path, monkeypatch, capsys):
    """A typo'd cascade_mode value falls to live with a WARNING (not silent)."""
    monkeypatch.delenv('STORYFORGE_DRAFTING', raising=False)
    (tmp_path / 'storyforge.yaml').write_text(
        'project:\n  title: test\n  cascade_mode: drating\n'  # typo
    )
    assert not is_drafting_mode(str(tmp_path))
    captured = capsys.readouterr()
    # Warning surfaced via log (which goes to stdout per common.log)
    assert 'WARNING' in captured.out
    assert 'drating' in captured.out


# ---------------------------------------------------------------------------
# Pipe sanitization in rationale field (#1)
# ---------------------------------------------------------------------------

def test_pipe_in_rationale_sanitized_on_write(tmp_path):
    """A rationale containing pipes is silently sanitized (pipes → slashes)
    so the file stays consistent with the project's split-on-pipe CSV
    convention. The on-disk file MUST NOT use RFC-4180 double-quoting,
    which would break downstream awk/cut readers."""
    append_override(
        'sc1', 'pacing', 'too-slow', 'accepted',
        'A | B | C considered',  # author typed pipes
        '2026-05-24', project_dir=str(tmp_path),
    )
    # On-disk content must not contain '"' (no RFC-4180 quoting)
    content = open(os.path.join(str(tmp_path), OVERRIDES_PATH)).read()
    assert '"' not in content, (
        'rationale should be sanitized in place, not RFC-4180-quoted'
    )
    # The substituted rationale is what comes back
    entries = read_overrides(str(tmp_path))
    assert entries[0]['rationale'] == 'A / B / C considered'


def test_rationale_without_pipes_preserved_verbatim(tmp_path):
    """Normal rationales survive untouched."""
    append_override(
        'sc1', 'pacing', 'too-slow', 'accepted',
        'the slow is intentional here',
        '2026-05-24', project_dir=str(tmp_path),
    )
    entries = read_overrides(str(tmp_path))
    assert entries[0]['rationale'] == 'the slow is intentional here'


def test_verdict_rationale_also_sanitized(tmp_path):
    """The same pipe-sanitization applies to verdicts (same field name)."""
    append_verdict(
        'sc1', '5->6', 'both are right',
        'either reading is defensible | depends on the act',
        'author', 'full', '2026-05-24',
        project_dir=str(tmp_path),
    )
    content = open(os.path.join(str(tmp_path), VERDICTS_PATH)).read()
    assert '"' not in content
    entry = read_verdicts(str(tmp_path))[0]
    assert entry['rationale'] == 'either reading is defensible / depends on the act'


# ---------------------------------------------------------------------------
# coaching_level on verdicts (#14)
# ---------------------------------------------------------------------------

def test_verdict_records_coaching_level(tmp_path):
    append_verdict(
        'sc1', '5->6', 'correct=upstream', 'rationale',
        'llm', 'full', '2026-05-24',
        project_dir=str(tmp_path),
    )
    entry = read_verdicts(str(tmp_path))[0]
    assert entry['coaching_level'] == 'full'
    assert entry['actor'] == 'llm'


def test_verdict_rejects_invalid_coaching_level(tmp_path):
    with pytest.raises(ValueError, match='coaching_level'):
        append_verdict(
            'sc1', '5->6', 'correct=upstream', 'rationale',
            'author', 'invented-mode', '2026-05-24',
            project_dir=str(tmp_path),
        )


def test_verdict_header_includes_coaching_level(tmp_path):
    """File format check: header must contain coaching_level."""
    append_verdict(
        'sc1', '5->6', 'needs work', 'r', 'author', 'strict', '2026-05-24',
        project_dir=str(tmp_path),
    )
    content = open(os.path.join(str(tmp_path), VERDICTS_PATH)).read()
    assert 'coaching_level' in content.splitlines()[0]


# ---------------------------------------------------------------------------
# Robustness of _read_pipe_csv (regression: PR #232 silent-failure review)
# ---------------------------------------------------------------------------

def test_malformed_row_logged_and_skipped(tmp_path, capsys):
    """A row with the wrong column count must be logged and skipped — not
    silently zip()-truncated into a half-valid dict that disables overrides."""
    overrides_path = os.path.join(str(tmp_path), OVERRIDES_PATH)
    os.makedirs(os.path.dirname(overrides_path), exist_ok=True)
    with open(overrides_path, 'w') as f:
        # Valid row, then a truncated row missing 2 columns, then a valid row.
        f.write('scope|axis|finding_id|verdict|rationale|recorded_at\n')
        f.write('sc1|bible-consistency|abc123|accepted|reason|2026-05-24\n')
        f.write('sc2|bible-consistency|def456|accepted\n')  # missing 2
        f.write('sc3|bible-consistency|ghi789|accepted|r|2026-05-24\n')
    entries = read_overrides(str(tmp_path))
    assert len(entries) == 2
    assert {e['scope'] for e in entries} == {'sc1', 'sc3'}
    out = capsys.readouterr().out
    assert 'WARNING' in out and 'columns' in out


def test_extra_columns_logged_and_skipped(tmp_path, capsys):
    """Same protection on the other side: more columns than the header."""
    overrides_path = os.path.join(str(tmp_path), OVERRIDES_PATH)
    os.makedirs(os.path.dirname(overrides_path), exist_ok=True)
    with open(overrides_path, 'w') as f:
        f.write('scope|axis|finding_id|verdict|rationale|recorded_at\n')
        f.write('sc1|bible|abc|accepted|reason|2026-05-24|stray|extra\n')
    entries = read_overrides(str(tmp_path))
    assert entries == []
    out = capsys.readouterr().out
    assert 'WARNING' in out


def test_override_lookup_survives_one_bad_row(tmp_path):
    """is_override_accepted still finds valid entries when a sibling row is
    corrupt — a typo in one row must not disable the override mechanism."""
    overrides_path = os.path.join(str(tmp_path), OVERRIDES_PATH)
    os.makedirs(os.path.dirname(overrides_path), exist_ok=True)
    with open(overrides_path, 'w') as f:
        f.write('scope|axis|finding_id|verdict|rationale|recorded_at\n')
        f.write('sc2|bible|def|accepted\n')  # malformed
        f.write('sc1|bible|abc|accepted|reason|2026-05-24\n')  # valid
    assert is_override_accepted(
        scope='sc1', axis='bible', finding_id='abc',
        project_dir=str(tmp_path),
    ) is True

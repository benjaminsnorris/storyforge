"""Tests for scoring_bible.py — bible-consistency LLM check."""

import json
import os

import pytest

from storyforge.scoring_bible import (
    score_bible_consistency,
    _finding_id,
    _parse_bible_response,
)


# ---------------------------------------------------------------------------
# Fixtures + mock plumbing
# ---------------------------------------------------------------------------

_FAKE_FINDINGS = {
    'findings': [
        {
            'bible': 'character-bible.md',
            'claim': 'The cartographer is left-handed',
            'scene_says': 'He signs with his right hand',
            'fix_location': 'either',
            'severity': 'medium',
        },
        {
            'bible': 'world-bible.md',
            'claim': 'The empire forbids written language outside the capital',
            'scene_says': 'A literate villager is shown reading aloud',
            'fix_location': 'scene',
            'severity': 'high',
        },
    ],
}


def _mock_bible_invoke(prompt, model, log_file, **kwargs):
    """Mock that records system blocks (to verify caching) and returns
    the canonical findings payload."""
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    response = {
        'content': [{'type': 'text', 'text': json.dumps(_FAKE_FINDINGS)}],
        'usage': {
            'input_tokens': 4000, 'output_tokens': 400,
            'cache_read_input_tokens': 3500,  # bibles were cached
            'cache_creation_input_tokens': 0,
        },
    }
    with open(log_file, 'w') as f:
        json.dump(response, f)
    return response


def _seed_project(project_dir, drafts: dict[str, str] | None = None,
                  bibles: dict[str, str] | None = None):
    """Place bible content and drafted scenes into project_dir."""
    if bibles is None:
        bibles = {
            'character-bible.md': 'The cartographer is left-handed and quiet.',
            'world-bible.md': 'Writing is forbidden outside the capital.',
            'voice-guide.md': 'Short sentences; first-person POV.',
        }
    if drafts is None:
        drafts = {
            'scene-1': 'He signs the map with his right hand, swiftly.',
        }
    ref = os.path.join(project_dir, 'reference')
    os.makedirs(ref, exist_ok=True)
    for fname, content in bibles.items():
        with open(os.path.join(ref, fname), 'w', encoding='utf-8') as f:
            f.write(content)
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    for sid, content in drafts.items():
        with open(os.path.join(scenes_dir, f'{sid}.md'), 'w', encoding='utf-8') as f:
            f.write(content)


@pytest.fixture
def patched_bible_invoke(monkeypatch):
    from storyforge import api, scoring_bible
    monkeypatch.setattr(api, 'invoke_to_file', _mock_bible_invoke)
    monkeypatch.setattr(scoring_bible, 'invoke_to_file', _mock_bible_invoke)


# ---------------------------------------------------------------------------
# Empty-state behavior
# ---------------------------------------------------------------------------

def test_returns_empty_when_no_bibles(tmp_path, monkeypatch):
    """No bibles → no LLM call, empty list."""
    scenes_dir = os.path.join(str(tmp_path), 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'scene-1.md'), 'w') as f:
        f.write('some prose')

    from storyforge import api
    called = []

    def track(*args, **kwargs):
        called.append(args)
    monkeypatch.setattr(api, 'invoke_to_file', track)
    from storyforge import scoring_bible as _sb
    monkeypatch.setattr(_sb, 'invoke_to_file', track)

    results = score_bible_consistency(str(tmp_path))
    assert results == []
    assert called == []  # never called the API


def test_returns_empty_when_no_drafts(tmp_path, monkeypatch):
    """Bibles present but no drafted scenes → empty list, no LLM call."""
    _seed_project(str(tmp_path), drafts={})

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file',
                        lambda *a, **kw: pytest.fail('should not call'))

    results = score_bible_consistency(str(tmp_path))
    assert results == []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_runs_against_drafted_scene(tmp_path, patched_bible_invoke):
    _seed_project(str(tmp_path))
    results = score_bible_consistency(str(tmp_path))
    # Two findings come back from the mock
    assert len(results) == 2
    assert all(r['scope'] == 'scene-1' for r in results)
    assert {r['bible'] for r in results} == {
        'character-bible.md', 'world-bible.md',
    }
    # Severity values are validated (high/medium/low only)
    assert all(r['severity'] in ('high', 'medium', 'low') for r in results)
    # Stable finding_id present
    assert all(r['finding_id'] for r in results)


def test_scope_filter_restricts_to_one_scene(tmp_path, patched_bible_invoke):
    _seed_project(str(tmp_path), drafts={
        'scene-1': 'first scene', 'scene-2': 'second scene',
    })
    results = score_bible_consistency(str(tmp_path), scope='scene-1')
    assert all(r['scope'] == 'scene-1' for r in results)


def test_passes_bibles_as_cached_system_blocks(tmp_path, monkeypatch):
    """The mock confirms `system=` is passed with cache_control on every block."""
    captured = {}

    def capture(prompt, model, log_file, **kwargs):
        captured['system'] = kwargs.get('system', [])
        return _mock_bible_invoke(prompt, model, log_file, **kwargs)

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', capture)
    from storyforge import scoring_bible as _sb
    monkeypatch.setattr(_sb, 'invoke_to_file', capture)
    _seed_project(str(tmp_path))
    score_bible_consistency(str(tmp_path))

    system_blocks = captured['system']
    # One instructions block + one block per bible (3) = 4
    assert len(system_blocks) == 4
    # Every block has cache_control set
    for block in system_blocks:
        assert block.get('cache_control', {}).get('type') == 'ephemeral', (
            'every system block must have cache_control for the bible-consistency '
            'cost target to hold (~$20-25/run vs ~$80 without caching)'
        )


def test_only_present_bibles_included(tmp_path, patched_bible_invoke):
    """Project with only one bible (e.g., voice-guide.md absent) still works."""
    _seed_project(str(tmp_path), bibles={
        'character-bible.md': 'A character bible.',
    })
    # The LLM call still happens; mock returns canonical findings
    results = score_bible_consistency(str(tmp_path))
    assert results  # findings returned (from the mock)


# ---------------------------------------------------------------------------
# Override propagation (v1's scoring-overrides.csv wired through)
# ---------------------------------------------------------------------------

def test_findings_tagged_when_overridden(tmp_path, patched_bible_invoke):
    """An author who has marked a finding as accepted via scoring-
    overrides.csv sees the finding tagged with accepted=True."""
    _seed_project(str(tmp_path))

    # Pre-populate an override for one of the findings the mock will return
    expected_id = _finding_id('scene-1', 'character-bible.md',
                              'The cartographer is left-handed')
    from storyforge.scoring_state import append_override
    append_override(
        scope='scene-1',
        axis='bible-consistency',
        finding_id=expected_id,
        verdict='accepted',
        rationale='Character has evolved through writing — bible will update',
        recorded_at='2026-05-24',
        project_dir=str(tmp_path),
    )

    results = score_bible_consistency(str(tmp_path))
    accepted = [r for r in results if r.get('accepted')]
    not_accepted = [r for r in results if not r.get('accepted')]
    assert len(accepted) == 1, (
        'the overridden finding should be tagged accepted=True'
    )
    assert accepted[0]['finding_id'] == expected_id
    # The other finding (world-bible.md) should NOT be tagged accepted
    assert len(not_accepted) == 1
    assert not_accepted[0]['bible'] == 'world-bible.md'


# ---------------------------------------------------------------------------
# Stable finding_id (overrides persist across re-runs)
# ---------------------------------------------------------------------------

def test_finding_id_deterministic():
    """Same (scope, bible, claim) → same finding_id across calls."""
    a = _finding_id('scene-1', 'character-bible.md', 'The cartographer is left-handed')
    b = _finding_id('scene-1', 'character-bible.md', 'The cartographer is left-handed')
    assert a == b
    assert len(a) == 12


def test_finding_id_differs_for_different_inputs():
    a = _finding_id('scene-1', 'character-bible.md', 'claim X')
    b = _finding_id('scene-2', 'character-bible.md', 'claim X')
    c = _finding_id('scene-1', 'world-bible.md', 'claim X')
    d = _finding_id('scene-1', 'character-bible.md', 'claim Y')
    assert len({a, b, c, d}) == 4


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

def test_dry_run_skips_llm(tmp_path, monkeypatch):
    _seed_project(str(tmp_path))

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file',
                        lambda *a, **kw: pytest.fail('should not call'))

    results = score_bible_consistency(str(tmp_path), dry_run=True)
    assert len(results) == 1
    assert results[0]['scope'] == 'scene-1'
    assert results[0]['bible'] == '(dry run)'


def test_garbage_llm_response_yields_no_findings(tmp_path, monkeypatch):
    def garbage(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': 'not json'}],
            'usage': {'input_tokens': 100, 'output_tokens': 20,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', garbage)
    from storyforge import scoring_bible as _sb
    monkeypatch.setattr(_sb, 'invoke_to_file', garbage)
    _seed_project(str(tmp_path))
    results = score_bible_consistency(str(tmp_path))
    assert results == []


def test_finding_missing_required_fields_dropped(tmp_path, monkeypatch):
    """LLM returns a finding with missing fields → it's dropped without
    poisoning the rest of the findings list."""
    def half_baked(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        payload = {
            'findings': [
                {'bible': 'character-bible.md', 'claim': 'has eyes'},  # missing scene_says
                {'bible': 'world-bible.md',
                 'claim': 'valid claim',
                 'scene_says': 'valid scene says',
                 'severity': 'medium'},  # valid
            ],
        }
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 100, 'output_tokens': 20,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', half_baked)
    from storyforge import scoring_bible as _sb
    monkeypatch.setattr(_sb, 'invoke_to_file', half_baked)
    _seed_project(str(tmp_path))
    results = score_bible_consistency(str(tmp_path))
    # Only the valid finding survives
    assert len(results) == 1
    assert results[0]['bible'] == 'world-bible.md'


def test_invalid_severity_coerced_to_medium(tmp_path, monkeypatch, capsys):
    """LLM returning a severity outside {high, medium, low} → coerce to
    medium rather than letting bad data flow through. The coercion must
    be logged so the author can audit it."""
    def bad_severity(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        payload = {'findings': [{
            'bible': 'character-bible.md', 'claim': 'c', 'scene_says': 's',
            'severity': 'CATASTROPHIC',
        }]}
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 100, 'output_tokens': 20,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', bad_severity)
    from storyforge import scoring_bible as _sb
    monkeypatch.setattr(_sb, 'invoke_to_file', bad_severity)
    _seed_project(str(tmp_path))
    results = score_bible_consistency(str(tmp_path))
    assert len(results) == 1
    assert results[0]['severity'] == 'medium'
    out = capsys.readouterr().out
    assert 'WARNING' in out and 'severity' in out
    assert 'CATASTROPHIC' in out or 'catastrophic' in out


def test_invalid_fix_location_coerced_with_warning(tmp_path, monkeypatch, capsys):
    """fix_location outside {bible, scene, either} → coerced to 'either'
    with a WARNING log entry. Regression test for silent failure."""
    def bad_loc(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        payload = {'findings': [{
            'bible': 'character-bible.md', 'claim': 'c', 'scene_says': 's',
            'severity': 'medium',
            'fix_location': 'NEITHER',
        }]}
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 100, 'output_tokens': 20,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', bad_loc)
    from storyforge import scoring_bible as _sb
    monkeypatch.setattr(_sb, 'invoke_to_file', bad_loc)
    _seed_project(str(tmp_path))
    results = score_bible_consistency(str(tmp_path))
    assert len(results) == 1
    assert results[0]['fix_location'] == 'either'
    out = capsys.readouterr().out
    assert 'WARNING' in out and 'fix_location' in out


def test_dropped_finding_logged_with_missing_fields(tmp_path, monkeypatch, capsys):
    """Findings dropped due to missing fields are visible in stdout, not silent.
    Regression test for silent failure."""
    def missing(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        payload = {'findings': [
            {'bible': 'character-bible.md', 'claim': 'has eyes'},  # no scene_says
        ]}
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 100, 'output_tokens': 20,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', missing)
    from storyforge import scoring_bible as _sb
    monkeypatch.setattr(_sb, 'invoke_to_file', missing)
    _seed_project(str(tmp_path))
    score_bible_consistency(str(tmp_path))
    out = capsys.readouterr().out
    assert 'WARNING' in out and 'dropped' in out
    assert 'scene_says' in out


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def test_parse_bible_response_direct_json():
    text = json.dumps(_FAKE_FINDINGS)
    result = _parse_bible_response(text)
    assert result is not None
    assert len(result) == 2


def test_parse_bible_response_fenced_block():
    text = f'Some prose.\n```json\n{json.dumps(_FAKE_FINDINGS)}\n```\nDone.'
    result = _parse_bible_response(text)
    assert result is not None
    assert len(result) == 2


def test_parse_bible_response_garbage_returns_none():
    assert _parse_bible_response('definitely not json') is None


def test_cost_ledger_records_bible_calls(tmp_path, patched_bible_invoke):
    """Each bible check writes to the cost ledger, including the cache_read
    token count so subsequent-call savings are visible."""
    _seed_project(str(tmp_path))
    score_bible_consistency(str(tmp_path))
    ledger = os.path.join(str(tmp_path), 'working', 'costs', 'ledger.csv')
    assert os.path.isfile(ledger)
    content = open(ledger).read()
    assert 'score-bible' in content
    # cache_read column should be present and non-zero (the mock reports 3500)
    assert '3500' in content

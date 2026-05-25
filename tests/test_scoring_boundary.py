"""Tests for scoring_boundary.py — LLM faithfulness diffs (#231).

Uses the same mock_invoke_to_file pattern as the existing GN revise / eval
tests: monkeypatch both the api module's `invoke_to_file` AND the module-
level imported name in scoring_boundary. The mock writes a fake JSON
response file that the real `extract_text_from_file` then reads.
"""

import json
import os

import pytest

from storyforge.scoring_boundary import (
    BOUNDARY_IDS, PROSE_BOUNDARIES,
    score_boundary, score_all_boundaries,
    _parse_diff_response,
)
from storyforge.scoring_state import read_verdicts


# ---------------------------------------------------------------------------
# Mock plumbing
# ---------------------------------------------------------------------------

_FAKE_DIFF = {
    'upstream_summary': 'Upstream says the protagonist wants X.',
    'downstream_summary': 'Downstream shows them pursuing Y.',
    'alignment': 'The downstream has drifted. X and Y are not compatible.',
    'proposed_verdict': 'correct=upstream',
    'rationale': 'Upstream framing is intentional; downstream picked the wrong target.',
}


def _mock_invoke(prompt, model, log_file, **kwargs):
    """Write a fake API response file with the canonical diff payload."""
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    response = {
        'content': [{'type': 'text', 'text': json.dumps(_FAKE_DIFF)}],
        'usage': {
            'input_tokens': 500, 'output_tokens': 200,
            'cache_read_input_tokens': 0,
            'cache_creation_input_tokens': 0,
        },
    }
    with open(log_file, 'w') as f:
        json.dump(response, f)
    return response


def _mock_with_verdict(verdict_text):
    """Build a fake-invoke that returns a verdict of our choosing."""
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        payload = dict(_FAKE_DIFF, proposed_verdict=verdict_text)
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


@pytest.fixture
def patched_invoke(monkeypatch):
    """Patch invoke_to_file in both the api module and scoring_boundary's
    bound name, returning the canonical fake-diff response."""
    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', _mock_invoke)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', _mock_invoke)


def _seed_story_summary(project_dir):
    """Write a minimal story-summary.md to project_dir/reference/."""
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            '# Story summary\n\n'
            '## Logline\n\n'
            'A cartographer loses his daughter to a country no map contains.\n\n'
            '## Synopsis\n\n'
            'Lucien Vey, master cartographer, draws maps of impossible places. '
            'When his daughter Mira vanishes into one, he must learn to read '
            'between his own lines to bring her back. Sentence three. Sentence four.\n\n'
            '## Act-shape\n\n'
            '### Act 1\nLucien is competent. Mira disappears.\n\n'
            '### Act 2\nThe maps lie. He learns to read them.\n\n'
            '### Act 3\nHe chooses Mira over the empire.\n\n'
            '## Theme\n\nWhat does it mean to recover what was never recorded?\n'
        )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_score_boundary_rejects_unknown_boundary(project_dir):
    with pytest.raises(ValueError, match='unknown boundary'):
        score_boundary(project_dir, '99->100')


def test_boundary_ids_complete():
    """Sanity: BOUNDARY_IDS covers all seven level boundaries."""
    assert len(BOUNDARY_IDS) == 7
    assert set(BOUNDARY_IDS) == {f'{i}->{i+1}' for i in range(7)}


def test_prose_boundaries_match_design():
    """Prose-tier boundaries are 0->1, 1->2, 2->3."""
    assert PROSE_BOUNDARIES == {'0->1', '1->2', '2->3'}


# ---------------------------------------------------------------------------
# Prose-tier boundary (0->1)
# ---------------------------------------------------------------------------

def test_boundary_0_to_1_runs_globally(project_dir, patched_invoke):
    """Prose-tier boundaries produce one diff per call, scope='global'."""
    _seed_story_summary(project_dir)
    results = score_boundary(project_dir, '0->1', coaching_level='full')
    assert len(results) == 1
    assert results[0]['scope'] == 'global'
    assert results[0]['boundary'] == '0->1'
    assert results[0]['proposed_verdict'] == 'correct=upstream'


def test_boundary_skipped_when_either_side_empty(project_dir, patched_invoke):
    """If upstream or downstream is empty, skip the LLM call (no point)."""
    # Create a story-summary.md with only the logline filled in.
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# Story summary\n\n## Logline\n\nOnly a logline.\n\n## Synopsis\n\n')
    results = score_boundary(project_dir, '0->1', coaching_level='full')
    assert results == []


# ---------------------------------------------------------------------------
# Coaching-level-aware persistence (the synthesis rule)
# ---------------------------------------------------------------------------

def test_full_coaching_persists_llm_verdict(project_dir, patched_invoke):
    _seed_story_summary(project_dir)
    results = score_boundary(project_dir, '0->1', coaching_level='full')
    assert results[0]['persisted']
    verdicts = read_verdicts(project_dir)
    assert len(verdicts) == 1
    assert verdicts[0]['actor'] == 'llm'
    assert verdicts[0]['coaching_level'] == 'full'
    assert verdicts[0]['boundary'] == '0->1'


def test_coach_coaching_does_not_persist(project_dir, patched_invoke):
    """In coach mode the LLM still produces the diff but we don't persist
    a verdict — the author has to confirm explicitly."""
    _seed_story_summary(project_dir)
    results = score_boundary(project_dir, '0->1', coaching_level='coach')
    assert not results[0]['persisted']
    # Diff is still returned
    assert results[0]['proposed_verdict']  # non-empty
    # But no verdict written to file
    assert read_verdicts(project_dir) == []


def test_strict_coaching_does_not_persist(project_dir, patched_invoke):
    _seed_story_summary(project_dir)
    results = score_boundary(project_dir, '0->1', coaching_level='strict')
    assert not results[0]['persisted']
    assert read_verdicts(project_dir) == []


# ---------------------------------------------------------------------------
# Idempotency — don't re-run when a verdict already exists
# ---------------------------------------------------------------------------

def test_existing_verdict_short_circuits_llm_call(project_dir, monkeypatch):
    """If get_verdict returns a row, the LLM call should NOT happen."""
    _seed_story_summary(project_dir)
    # Seed an existing verdict for the global 0->1 boundary.
    from storyforge.scoring_state import append_verdict
    append_verdict(
        scope='global', boundary='0->1', verdict='both are right',
        rationale='ok', actor='author', coaching_level='strict',
        recorded_at='2026-05-24', project_dir=project_dir,
    )

    calls = []

    def fail_if_called(*args, **kwargs):
        calls.append(args)
        raise AssertionError('LLM should not be invoked for boundaries with a verdict already')

    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', fail_if_called)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', fail_if_called)

    results = score_boundary(project_dir, '0->1', coaching_level='full')
    assert results == []
    assert calls == []


# ---------------------------------------------------------------------------
# Dry-run path
# ---------------------------------------------------------------------------

def test_dry_run_returns_stub_without_invoking_llm(project_dir, monkeypatch):
    _seed_story_summary(project_dir)

    def fail(*args, **kwargs):
        raise AssertionError('dry_run should not invoke the LLM')

    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', fail)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', fail)

    results = score_boundary(project_dir, '0->1',
                             coaching_level='full', dry_run=True)
    assert len(results) == 1
    assert results[0]['alignment'] == '(dry run)'
    assert not results[0]['persisted']


# ---------------------------------------------------------------------------
# Structural-tier boundary (5->6) per-scene
# ---------------------------------------------------------------------------

def test_boundary_5_to_6_produces_one_result_per_brief(project_dir, patched_invoke):
    """Map → Briefs: one diff per briefed scene."""
    results = score_boundary(project_dir, '5->6', coaching_level='strict')
    # The fixture has briefed scenes; we expect at least one result.
    assert len(results) >= 1
    assert all(r['boundary'] == '5->6' for r in results)
    assert all(r['scope'] != 'global' for r in results)


def test_boundary_5_to_6_filtered_to_scope(project_dir, patched_invoke):
    """Passing a scope_id restricts to that scene only.

    The fixture has act1-sc01 with both scene-intent and scene-briefs,
    so we MUST get a non-empty result — an empty list would be a
    regression in scope filtering or pair collection, not the test
    correctly skipping a missing fixture.
    """
    results = score_boundary(project_dir, '5->6', scope='act1-sc01',
                             coaching_level='strict')
    assert len(results) == 1, (
        f'expected one result for scope=act1-sc01 (fixture has intent+brief '
        f'for that scene); got {results!r}'
    )
    assert results[0]['scope'] == 'act1-sc01'


# ---------------------------------------------------------------------------
# Per-boundary collector coverage (regression: PR #232 test review)
# ---------------------------------------------------------------------------

def _seed_spine(project_dir, rows):
    path = os.path.join(project_dir, 'reference', 'spine.csv')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('id|seq|title|function|part\n')
        for r in rows:
            f.write('|'.join(r) + '\n')


def _seed_architecture(project_dir, rows):
    path = os.path.join(project_dir, 'reference', 'architecture.csv')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('id|seq|title|part|pov|spine_event|action_sequel|'
                'emotional_arc|value_at_stake|value_shift|turning_point\n')
        for r in rows:
            f.write('|'.join(r) + '\n')


def test_boundary_3_to_4_pairs_each_spine_event(project_dir, patched_invoke):
    """3->4 (spine → architecture) must produce one diff per spine event,
    with that event's id as the scope. Regression: the collector dispatch
    was untested for this boundary."""
    _seed_spine(project_dir, [
        ('ev-1', '1', 'Inciting incident', 'turn', '1'),
        ('ev-2', '2', 'First reversal', 'turn', '1'),
    ])
    _seed_architecture(project_dir, [
        ('arch-1', '1', 'Opens cold', '1', 'POV', 'ev-1',
         'action', 'tense', 'safety', '-', 'discovery'),
        # Note: ev-2 has no descendants — should still produce a diff
        # with a placeholder downstream.
    ])
    results = score_boundary(project_dir, '3->4', coaching_level='strict')
    scopes = {r['scope'] for r in results}
    assert scopes == {'ev-1', 'ev-2'}


def test_boundary_3_to_4_scope_filter(project_dir, patched_invoke):
    """3->4 with --scope X must return only the matching spine event."""
    _seed_spine(project_dir, [
        ('ev-1', '1', 'a', 'turn', '1'),
        ('ev-2', '2', 'b', 'turn', '1'),
    ])
    _seed_architecture(project_dir, [
        ('arch-1', '1', 'x', '1', 'P', 'ev-1', 'a', 'b', 'c', '-', 'd'),
    ])
    results = score_boundary(project_dir, '3->4', scope='ev-1',
                             coaching_level='strict')
    assert len(results) == 1
    assert results[0]['scope'] == 'ev-1'


def test_boundary_4_to_5_pairs_each_anchor(project_dir, patched_invoke):
    """4->5 (architecture → scene-map) must produce one diff per anchor."""
    _seed_spine(project_dir, [('ev-1', '1', 't', 'turn', '1')])
    _seed_architecture(project_dir, [
        ('arch-1', '1', 'anchor-1', '1', 'P', 'ev-1', 'a', 'b', 'c', '-', 'd'),
        ('arch-2', '2', 'anchor-2', '1', 'P', 'ev-1', 'a', 'b', 'c', '-', 'd'),
    ])
    results = score_boundary(project_dir, '4->5', coaching_level='strict')
    scopes = {r['scope'] for r in results}
    assert {'arch-1', 'arch-2'}.issubset(scopes)


# ---------------------------------------------------------------------------
# Summary column appears in boundary diffs when populated
# ---------------------------------------------------------------------------

def _seed_spine_with_summary(project_dir, id_seq_title_summary_function_part):
    path = os.path.join(project_dir, 'reference', 'spine.csv')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('id|seq|title|summary|function|part\n')
        for row in id_seq_title_summary_function_part:
            f.write('|'.join(row) + '\n')


def _seed_architecture_with_summary(project_dir, rows):
    path = os.path.join(project_dir, 'reference', 'architecture.csv')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('id|seq|title|summary|part|pov|spine_event|action_sequel|'
                'emotional_arc|value_at_stake|value_shift|turning_point\n')
        for r in rows:
            f.write('|'.join(r) + '\n')


def test_boundary_3_to_4_includes_summary_in_upstream(project_dir, monkeypatch):
    """When summary is populated, the boundary diff prompt must include it
    as a clear 'Summary:' line so the LLM can compare summaries directly."""
    _seed_spine_with_summary(project_dir, [
        ('ev-1', '1', 'Inciting incident',
         'Lucien finds an anomaly he cannot explain.', 'turn', '1'),
    ])
    _seed_architecture_with_summary(project_dir, [
        ('arch-1', '1', 'Studio scene',
         'Lucien notices changed records during a routine sitting.',
         '1', 'POV', 'ev-1', 'action', 'focus to alarm', 'truth', '+/-',
         'reveal'),
    ])

    captured = {}
    def fake(prompt, model, log_file, **kwargs):
        captured['prompt'] = prompt
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': json.dumps({
                'upstream_summary': 'u', 'downstream_summary': 'd',
                'alignment': 'a', 'proposed_verdict': 'both are right',
                'rationale': 'r',
            })}],
            'usage': {'input_tokens': 100, 'output_tokens': 50,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', fake)

    score_boundary(project_dir, '3->4', coaching_level='strict')
    assert 'Lucien finds an anomaly he cannot explain.' in captured['prompt']
    assert 'Lucien notices changed records during a routine sitting.' in captured['prompt']
    # The prompt should label the summary explicitly so the model can
    # compare same-shape content cross-tier.
    assert 'Summary:' in captured['prompt']


def test_boundary_3_to_4_falls_back_when_summary_empty(project_dir, monkeypatch):
    """If summary is empty, the collector falls back to function/title so
    the diff still works on legacy projects that haven't backfilled summary."""
    # No summary column at all (pre-migration shape)
    path = os.path.join(project_dir, 'reference', 'spine.csv')
    with open(path, 'w') as f:
        f.write('id|seq|title|function|part\n')
        f.write('ev-1|1|Inciting|turning point function|1\n')
    arch_path = os.path.join(project_dir, 'reference', 'architecture.csv')
    with open(arch_path, 'w') as f:
        f.write('id|seq|title|part|pov|spine_event|action_sequel|'
                'emotional_arc|value_at_stake|value_shift|turning_point\n')
        f.write('arch-1|1|Anchor|1|POV|ev-1|action|arc|truth|+/-|reveal\n')

    captured = {}
    def fake(prompt, model, log_file, **kwargs):
        captured['prompt'] = prompt
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': '{"alignment":"a","proposed_verdict":"both are right","rationale":"r","upstream_summary":"u","downstream_summary":"d"}'}],
            'usage': {'input_tokens': 50, 'output_tokens': 20,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', fake)

    score_boundary(project_dir, '3->4', coaching_level='strict')
    # Without summary, function should appear in the upstream framing.
    assert 'turning point function' in captured['prompt']
    # 'Summary:' line should NOT appear since the column was empty.
    assert 'Summary:' not in captured['prompt']


# ---------------------------------------------------------------------------
# score_all_boundaries
# ---------------------------------------------------------------------------

def test_score_all_boundaries_walks_each(project_dir, patched_invoke):
    """The aggregator runs every boundary that has comparable content."""
    _seed_story_summary(project_dir)
    results = score_all_boundaries(project_dir, coaching_level='strict')
    boundaries_seen = {r['boundary'] for r in results}
    # The prose-tier boundaries should at least all be present (we
    # seeded story-summary.md). Structural-tier ones depend on the
    # fixture's CSV contents.
    assert {'0->1', '1->2'}.issubset(boundaries_seen)


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

def test_cost_ledger_records_boundary_calls(project_dir, patched_invoke):
    _seed_story_summary(project_dir)
    score_boundary(project_dir, '0->1', coaching_level='strict')
    ledger_path = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
    assert os.path.isfile(ledger_path)
    content = open(ledger_path).read()
    assert 'score-boundary' in content
    assert '0->1/global' in content


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def test_parse_diff_response_direct_json():
    text = json.dumps(_FAKE_DIFF)
    result = _parse_diff_response(text)
    assert result is not None
    assert result['proposed_verdict'] == 'correct=upstream'


def test_parse_diff_response_fenced_block():
    text = f'Here is my response:\n```json\n{json.dumps(_FAKE_DIFF)}\n```\nDone.'
    result = _parse_diff_response(text)
    assert result is not None
    assert result['proposed_verdict'] == 'correct=upstream'


def test_parse_diff_response_returns_none_on_garbage():
    assert _parse_diff_response('this is not json') is None


# ---------------------------------------------------------------------------
# LLM verdict validation — bad verdict from LLM doesn't crash, just no persist
# ---------------------------------------------------------------------------

def test_llm_proposing_invalid_verdict_is_handled(project_dir, monkeypatch, capsys):
    """If the LLM returns a verdict that isn't in VALID_BOUNDARY_VERDICTS,
    the diff is still surfaced but no persist happens. The author sees
    the diff and can author a verdict themselves. The invalid value must
    be logged so the author knows their persist failed for a real reason."""
    _seed_story_summary(project_dir)

    bogus = _mock_with_verdict('invented-verdict-string')
    from storyforge import api, scoring_boundary
    monkeypatch.setattr(api, 'invoke_to_file', bogus)
    monkeypatch.setattr(scoring_boundary, 'invoke_to_file', bogus)

    results = score_boundary(project_dir, '0->1', coaching_level='full')
    assert len(results) == 1
    assert not results[0]['persisted']
    assert results[0]['proposed_verdict'] == 'invented-verdict-string'
    assert read_verdicts(project_dir) == []
    out = capsys.readouterr().out
    assert 'WARNING' in out and 'invented-verdict-string' in out

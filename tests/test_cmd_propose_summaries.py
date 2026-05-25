"""Tests for cmd_propose_summaries — coaching-level-aware draft proposals."""

import json
import os

import pytest


def _seed_story_summary(project_dir: str) -> None:
    # Seed a minimal storyforge.yaml so detect_project_root finds the root.
    yml = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yml):
        with open(yml, 'w') as f:
            f.write('project:\n  title: Test\n  medium: novel\n  '
                    'coaching_level: full\n')
    path = os.path.join(project_dir, 'reference', 'story-summary.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(
            '# Story summary\n\n'
            '## Logline\nA logline.\n\n'
            '## Synopsis\nOne. Two. Three. Four.\n\n'
            '## Act-shape\n\n'
            '### Act 1\nLucien finds an anomaly.\n\n'
            '### Act 2\nThe archive resists.\n\n'
            '### Act 3\nReality fractures.\n\n'
            '## Theme\nMemory vs preservation.\n'
        )


def _mock_llm(payload: dict):
    """Build a fake invoke_to_file that records its call and writes a
    response file."""
    captured = {}

    def fake(prompt, model, log_file, **kwargs):
        captured['prompt'] = prompt
        captured['model'] = model
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text': json.dumps(payload)}],
            'usage': {'input_tokens': 100, 'output_tokens': 80,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response

    return fake, captured


# ---------------------------------------------------------------------------
# strict coaching: rule-based checklist, no LLM
# ---------------------------------------------------------------------------

def test_strict_writes_constraint_checklist(tmp_path, monkeypatch):
    """strict mode produces a constraint checklist and NEVER calls the LLM."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))

    # Verify no LLM call happens
    from storyforge import api
    def fail(*args, **kwargs):
        raise AssertionError('LLM must not be called in strict mode')
    monkeypatch.setattr(api, 'invoke_to_file', fail)
    from storyforge import cmd_propose_summaries
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fail)

    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'strict'])
    out_path = os.path.join(str(tmp_path), 'working', 'coaching',
                            'propose-summaries-level-3.md')
    assert os.path.isfile(out_path)
    text = open(out_path).read()
    assert 'Constraint checklist' in text
    assert 'Row count target' in text
    assert 'What each summary must cover' in text
    # And no CSV writes
    assert not os.path.isfile(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
    )


def test_strict_includes_upstream_in_checklist(tmp_path, monkeypatch):
    """The checklist quotes the upstream content so the author can refer
    to it while drafting."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'strict'])
    text = open(os.path.join(
        str(tmp_path), 'working', 'coaching', 'propose-summaries-level-3.md',
    )).read()
    assert 'Lucien finds an anomaly' in text
    assert 'reality fractures' in text.lower()


# ---------------------------------------------------------------------------
# full coaching: LLM proposes, writes to CSV
# ---------------------------------------------------------------------------

def test_full_writes_proposals_into_target_csv(tmp_path, monkeypatch):
    """full mode invokes the LLM and writes the proposed summaries into
    reference/spine.csv (creating it when absent)."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    fake, captured = _mock_llm({
        'proposals': [
            {'summary': 'Event 1 summary.', 'rationale': 'r1'},
            {'summary': 'Event 2 summary.', 'rationale': 'r2'},
            {'summary': 'Event 3 summary.', 'rationale': 'r3'},
            {'summary': 'Event 4 summary.', 'rationale': 'r4'},
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)

    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'full'])
    spine_csv = os.path.join(str(tmp_path), 'reference', 'spine.csv')
    assert os.path.isfile(spine_csv)
    content = open(spine_csv).read()
    assert 'Event 1 summary.' in content
    assert 'Event 2 summary.' in content
    assert 'Event 3 summary.' in content
    assert 'Event 4 summary.' in content
    # Coaching brief should NOT be written in full mode
    assert not os.path.isfile(os.path.join(
        str(tmp_path), 'working', 'coaching',
        'propose-summaries-level-3.md',
    ))


def test_full_does_not_overwrite_existing_summaries(tmp_path, monkeypatch):
    """If a row already has a summary, full mode must NOT overwrite it.
    Proposals fill empty cells first, then append as new rows."""
    _seed_story_summary(str(tmp_path))
    spine_csv = os.path.join(str(tmp_path), 'reference', 'spine.csv')
    os.makedirs(os.path.dirname(spine_csv), exist_ok=True)
    with open(spine_csv, 'w') as f:
        f.write('id|seq|title|summary|function|part\n')
        # First row has author work; second row has empty summary.
        f.write('ev-1|1|t|AUTHOR-WRITTEN ALREADY.|inciting|1\n')
        f.write('ev-2|2|t||turn|2\n')
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    fake, _ = _mock_llm({
        'proposals': [
            {'summary': 'Proposed for empty row.', 'rationale': 'r'},
            {'summary': 'New appended row.', 'rationale': 'r'},
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)

    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'full'])
    content = open(spine_csv).read()
    # Author's work preserved
    assert 'AUTHOR-WRITTEN ALREADY.' in content
    # Empty cell on ev-2 filled
    assert 'Proposed for empty row.' in content
    # Extra proposal appended as a new row
    assert 'New appended row.' in content


# ---------------------------------------------------------------------------
# coach coaching: LLM proposes, writes brief to working/coaching
# ---------------------------------------------------------------------------

def test_coach_writes_brief_does_not_touch_csv(tmp_path, monkeypatch):
    """coach mode invokes the LLM but writes the proposals to a working/
    coaching brief — NOT to the target CSV."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    fake, _ = _mock_llm({
        'proposals': [
            {'summary': 'Coach proposal 1.', 'rationale': 'r1'},
            {'summary': 'Coach proposal 2.', 'rationale': 'r2'},
        ],
        'considerations': [
            'Should Act 2 carry more weight?',
            'Is the midpoint reversal too gentle?',
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)

    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'coach'])

    brief_path = os.path.join(str(tmp_path), 'working', 'coaching',
                              'propose-summaries-level-3.md')
    assert os.path.isfile(brief_path)
    text = open(brief_path).read()
    assert 'Coach proposal 1.' in text
    assert 'Should Act 2 carry more weight?' in text
    # CSV must NOT have been written
    assert not os.path.isfile(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
    )


# ---------------------------------------------------------------------------
# dry-run + API key gating
# ---------------------------------------------------------------------------

def test_dry_run_does_not_call_llm(tmp_path, monkeypatch):
    """--dry-run prints what would happen without calling the LLM or
    writing files."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge import api, cmd_propose_summaries
    def fail(*a, **k):
        raise AssertionError('LLM must not be called in dry-run')
    monkeypatch.setattr(api, 'invoke_to_file', fail)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fail)

    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'full', '--dry-run'])
    # No CSV, no brief, no log file
    assert not os.path.isfile(
        os.path.join(str(tmp_path), 'reference', 'spine.csv'),
    )


def test_full_without_api_key_errors_cleanly(tmp_path, monkeypatch):
    """Missing ANTHROPIC_API_KEY exits 1 cleanly in full mode."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    from storyforge.cmd_propose_summaries import main as ps_main
    with pytest.raises(SystemExit) as exc:
        ps_main(['--level', '3', '--coaching', 'full'])
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Levels 4 + 5
# ---------------------------------------------------------------------------

def test_level_4_reads_spine_summaries_as_upstream(tmp_path, monkeypatch):
    """--level 4 reads spine.csv summary column as the upstream content."""
    _seed_story_summary(str(tmp_path))
    spine_csv = os.path.join(str(tmp_path), 'reference', 'spine.csv')
    os.makedirs(os.path.dirname(spine_csv), exist_ok=True)
    with open(spine_csv, 'w') as f:
        f.write('id|seq|title|summary|function|part\n')
        f.write('ev-1|1|t|First spine event summary.|inciting|1\n')
        f.write('ev-2|2|t|Second spine event summary.|turn|2\n')
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    fake, captured = _mock_llm({
        'proposals': [
            {'summary': 'Anchor A.', 'rationale': 'r'},
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)

    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '4', '--coaching', 'full'])
    # The prompt must have included the spine summaries as upstream
    assert 'First spine event summary.' in captured['prompt']
    assert 'Second spine event summary.' in captured['prompt']
    # And architecture.csv exists with the proposal
    arch_csv = os.path.join(str(tmp_path), 'reference', 'architecture.csv')
    assert os.path.isfile(arch_csv)
    assert 'Anchor A.' in open(arch_csv).read()


def test_invalid_level_rejected(tmp_path, monkeypatch):
    """--level outside {3, 4, 5} is rejected by argparse."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_propose_summaries import main as ps_main
    with pytest.raises(SystemExit):
        ps_main(['--level', '0'])
    with pytest.raises(SystemExit):
        ps_main(['--level', '6'])

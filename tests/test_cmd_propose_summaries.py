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


def test_csv_pipes_in_summary_are_sanitized(tmp_path, monkeypatch):
    """LLM summary containing `|` or `\\n` must be sanitized before write —
    otherwise the row shatters and gets silently dropped on next read."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    fake, _ = _mock_llm({
        'proposals': [
            {'summary': 'Has a | pipe and a\nnewline.', 'rationale': 'r'},
            {'summary': 'Second proposal.', 'rationale': 'r'},
            {'summary': 'Third proposal.', 'rationale': 'r'},
            {'summary': 'Fourth proposal.', 'rationale': 'r'},
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)

    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'full'])
    spine_csv = os.path.join(str(tmp_path), 'reference', 'spine.csv')
    content = open(spine_csv).read()
    # Every data line has the same number of pipes as the header
    lines = [l for l in content.split('\n') if l.strip()]
    header_pipes = lines[0].count('|')
    for line in lines[1:]:
        assert line.count('|') == header_pipes, (
            f'row {line!r} has wrong pipe count'
        )
    # The pipe in the summary got replaced (with `/`)
    assert 'Has a / pipe' in content
    # The newline got replaced with a space
    assert 'pipe and a newline.' in content


def test_header_upgrade_preserves_orphan_columns(tmp_path, monkeypatch):
    """When upgrading a CSV that predates `summary`, existing columns
    NOT in target_cols must be preserved — never silently dropped."""
    _seed_story_summary(str(tmp_path))
    spine_csv = os.path.join(str(tmp_path), 'reference', 'spine.csv')
    os.makedirs(os.path.dirname(spine_csv), exist_ok=True)
    # Pre-PR header (no `summary`) + a hypothetical legacy column.
    with open(spine_csv, 'w') as f:
        f.write('id|seq|title|function|part|legacy_note\n')
        f.write('ev-1|1|Title|fn|1|author wrote this in 2024\n')
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    fake, _ = _mock_llm({
        'proposals': [
            {'summary': 'Proposed summary 1.', 'rationale': 'r'},
            {'summary': 'Proposed summary 2.', 'rationale': 'r'},
            {'summary': 'Proposed summary 3.', 'rationale': 'r'},
            {'summary': 'Proposed summary 4.', 'rationale': 'r'},
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)

    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'full'])

    content = open(spine_csv).read()
    # The legacy_note column survives in the header and the row data
    assert 'legacy_note' in content.split('\n')[0]
    assert 'author wrote this in 2024' in content


def test_write_failure_surfaces_log_pointer(tmp_path, monkeypatch, capsys):
    """If the CSV write blows up after the LLM has already been billed,
    surface a clear pointer to the log file where proposals were recorded."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    fake, _ = _mock_llm({
        'proposals': [
            {'summary': 'Summary 1.', 'rationale': 'r'},
            {'summary': 'Summary 2.', 'rationale': 'r'},
            {'summary': 'Summary 3.', 'rationale': 'r'},
            {'summary': 'Summary 4.', 'rationale': 'r'},
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)

    # Force the write to fail: stub open() for the target CSV path.
    real_open = open
    target = os.path.join(str(tmp_path), 'reference', 'spine.csv')
    def failing_open(path, *args, **kwargs):
        if path == target and 'w' in (args[0] if args else kwargs.get('mode', '')):
            raise OSError('disk full')
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr('builtins.open', failing_open)

    from storyforge.cmd_propose_summaries import main as ps_main
    with pytest.raises(OSError):
        ps_main(['--level', '3', '--coaching', 'full'])
    out = capsys.readouterr().out
    assert 'disk full' in out
    assert 'working/logs/propose-summaries' in out


def test_id_collision_with_existing_rows(tmp_path, monkeypatch):
    """If a CSV already has rows named `proposed-3-N`, the next run must
    avoid colliding on those ids."""
    _seed_story_summary(str(tmp_path))
    spine_csv = os.path.join(str(tmp_path), 'reference', 'spine.csv')
    os.makedirs(os.path.dirname(spine_csv), exist_ok=True)
    with open(spine_csv, 'w') as f:
        f.write('id|seq|title|summary|function|part\n')
        f.write('proposed-3-1|1|t|Old proposal kept.|inciting|1\n')
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')

    fake, _ = _mock_llm({
        'proposals': [
            {'summary': 'New proposal one.', 'rationale': 'r'},
            {'summary': 'New proposal two.', 'rationale': 'r'},
            {'summary': 'New proposal three.', 'rationale': 'r'},
            {'summary': 'New proposal four.', 'rationale': 'r'},
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)

    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'full'])

    content = open(spine_csv).read()
    lines = [l for l in content.split('\n') if l.strip()]
    ids = [l.split('|')[0] for l in lines[1:]]
    # No duplicate ids
    assert len(ids) == len(set(ids)), f'duplicate ids in {ids!r}'
    # Existing row preserved
    assert 'proposed-3-1' in ids


def test_coach_without_api_key_errors_cleanly(tmp_path, monkeypatch):
    """coach mode also calls the LLM, so missing API key must exit 1 cleanly
    just like full mode (previously only full was gated)."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    from storyforge.cmd_propose_summaries import main as ps_main
    with pytest.raises(SystemExit) as exc:
        ps_main(['--level', '3', '--coaching', 'coach'])
    assert exc.value.code == 1


def test_placeholder_id_warning_when_creating_csv(tmp_path, monkeypatch, capsys):
    """When _create_csv_with_proposals fires (target CSV didn't exist),
    surface a NOTE about placeholder ids + empty required columns so the
    author isn't surprised by the next validate/score wave."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    fake, _ = _mock_llm({
        'proposals': [
            {'summary': f'Summary {i}.', 'rationale': 'r'} for i in range(1, 5)
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)
    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'full'])
    out = capsys.readouterr().out
    assert 'NOTE' in out
    assert 'placeholder ids' in out


def test_row_count_below_range_warns(tmp_path, monkeypatch, capsys):
    """LLM returns fewer proposals than the level's row range expects → WARN."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    # Level 3 (novel) range is 5-10; return only 2 proposals.
    fake, _ = _mock_llm({
        'proposals': [
            {'summary': 'One.', 'rationale': 'r'},
            {'summary': 'Two.', 'rationale': 'r'},
        ],
    })
    from storyforge import api, cmd_propose_summaries
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_propose_summaries, 'invoke_to_file', fake)
    from storyforge.cmd_propose_summaries import main as ps_main
    ps_main(['--level', '3', '--coaching', 'full'])
    out = capsys.readouterr().out
    assert 'WARNING' in out and 'expects 5-10' in out


def test_parse_proposals_distinguishes_no_key_from_no_json():
    """_parse_proposals returns a status code distinguishing 'valid JSON
    but no proposals key' from 'no JSON at all', so the error message can
    point the author at the right fix."""
    from storyforge.cmd_propose_summaries import _parse_proposals
    # No JSON at all
    out, status = _parse_proposals('this is not json')
    assert out == []
    assert status == 'no_json'
    # Valid JSON, wrong key
    out, status = _parse_proposals('{"items": [{"summary": "x"}]}')
    assert out == []
    assert status == 'no_proposals_key'
    # Valid JSON, empty proposals
    out, status = _parse_proposals('{"proposals": []}')
    assert out == []
    assert status == 'no_proposals_key'
    # Valid JSON with proposals
    out, status = _parse_proposals('{"proposals": [{"summary": "ok"}]}')
    assert len(out) == 1
    assert status == 'ok'


def test_invalid_level_rejected(tmp_path, monkeypatch):
    """--level outside {3, 4, 5} is rejected by argparse."""
    _seed_story_summary(str(tmp_path))
    monkeypatch.chdir(str(tmp_path))
    from storyforge.cmd_propose_summaries import main as ps_main
    with pytest.raises(SystemExit):
        ps_main(['--level', '0'])
    with pytest.raises(SystemExit):
        ps_main(['--level', '6'])

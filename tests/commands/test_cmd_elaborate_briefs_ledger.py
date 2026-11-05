"""The briefs stage registers its new fact and state ids in the ledger.

The briefs prompt has the model coin knowledge and physical-state ids, but
the stage wrote only scene-briefs.csv: validate counted "0 facts across 42
scenes" on Gawain (G-023) and the knowledge chain scored 0 on Beowulf
(B-020). The stage now runs hone's reconciliation for both domains (#547)."""

import os

import pytest

from storyforge.cmd_elaborate import main

BRIEFS_REPLY = (
    '```briefs-csv\n'
    'id|goal|conflict|outcome|crisis|decision|knowledge_in|knowledge_out|key_actions|'
    'key_dialogue|emotions|motifs|subtext|continuity_deps|has_overflow|'
    'physical_state_in|physical_state_out\n'
    'new-x1|Learn the truth|The archivist lies|yes-but|Trust or not|Trusts|'
    '|archivist-knows-village|Asks;Listens|"Ask me again"|fear;hope||||false||\n'
    '```\n'
)


@pytest.fixture
def novel(project_dir, monkeypatch, mock_git, mock_costs):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    monkeypatch.setattr('storyforge.cmd_elaborate.detect_project_root', lambda: project_dir)
    monkeypatch.setattr('storyforge.cmd_elaborate.select_model', lambda tier: 'test-model')
    return project_dir


def _run(mock_api, reply, stage='briefs'):
    mock_api.set_response(reply)
    try:
        main(['--stage', stage])
    except SystemExit:
        pass


def test_briefs_stage_reconciles_knowledge_and_physical_states(novel, mock_api, monkeypatch):
    calls = []

    def fake(domain, ref_dir, model, log_dir, context=''):
        calls.append(domain)
        return {'registry_entries': 1, 'references_mapped': 0, 'fields_normalized': 0,
                'unresolved': 0, 'calls': 1}

    monkeypatch.setattr('storyforge.hone.reconcile_domain', fake)
    _run(mock_api, BRIEFS_REPLY)
    assert calls == ['knowledge', 'physical-states']


def test_ids_left_unregistered_are_reported(novel, mock_api, monkeypatch, capsys):
    def fake(domain, ref_dir, model, log_dir, context=''):
        return {'registry_entries': 0, 'references_mapped': 0, 'fields_normalized': 0,
                'unresolved': 1 if domain == 'knowledge' else 0, 'calls': 1}

    monkeypatch.setattr('storyforge.hone.reconcile_domain', fake)
    _run(mock_api, BRIEFS_REPLY)
    out = capsys.readouterr()
    assert ("the briefs' knowledge ids are not all in the ledger; run storyforge hone "
            "--domain knowledge,physical-states") in out.out + out.err


def test_the_architecture_stage_does_not_touch_the_ledger(novel, mock_api, monkeypatch):
    calls = []
    monkeypatch.setattr('storyforge.hone.reconcile_domain',
                        lambda *a, **k: calls.append(a[0]))
    _run(mock_api, BRIEFS_REPLY.replace('briefs-csv', 'intent-csv'), stage='architecture')
    assert calls == []

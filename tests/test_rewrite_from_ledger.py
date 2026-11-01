"""Phase 4 PR 5: rewrite-from-ledger (rethink plan §3.4, design note §6).

A redraft drafts from the plan and the binding ledger, with the scene's old
prose sent as a voice reference only. Before, a redraft never saw the old
prose, and revise's `_redraft_scenes` (after the upstream brief fix) used
the old prompt with neither the brief's fact columns nor the ledger."""

import os
import sys

import pytest

from storyforge import cmd_write
from storyforge.prompts import build_scene_prompt_from_briefs

from conftest import PLUGIN_DIR

HEADING = '## The Current Draft (voice reference only)'
MARKER = '![[illus:ill-1]]'


def _prompt(project_dir, coaching='full', voice='Old prose, in its voice.'):
    return build_scene_prompt_from_briefs('act1-sc01', project_dir, PLUGIN_DIR, coaching,
                                          voice_reference=voice)


class TestThePrompt:

    def test_a_rewrite_shows_the_old_prose_as_voice_only(self, project_dir):
        prompt = _prompt(project_dir)
        assert HEADING in prompt
        assert '<current_draft>\nOld prose, in its voice.\n</current_draft>' in prompt
        assert 'Take nothing else from it' in prompt
        assert 'This is a rewrite: the facts come from the brief' in prompt
        # after the facts, before the task
        assert prompt.index(HEADING) < prompt.index('## Task')

    def test_a_fresh_draft_has_no_such_block(self, project_dir):
        prompt = _prompt(project_dir, voice='')
        assert HEADING not in prompt and 'This is a rewrite' not in prompt

    def test_a_fresh_drafts_prompt_is_unchanged(self, project_dir):
        """E4's recordings (fresh drafts) replay only while it is byte-identical."""
        prompt = _prompt(project_dir, voice='')
        assert '{register_line}' not in prompt
        assert '\n\n\n\n## Task' not in prompt

    @pytest.mark.parametrize('coaching', ['coach', 'strict'])
    def test_coach_and_strict_write_no_prose_so_get_none(self, project_dir, coaching):
        assert HEADING not in _prompt(project_dir, coaching=coaching)


class TestBuildPrompt:

    def _scene(self, project_dir, text):
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md'), 'w') as f:
            f.write(text)

    def test_a_rewrite_reads_the_scene_without_its_markers(self, project_dir):
        self._scene(project_dir, f'The old voice.\n\n{MARKER}\n\nMore of it.\n')
        prompt = cmd_write._build_prompt('act1-sc01', project_dir, 'full', use_briefs=True,
                                         rewrite=True)
        assert 'The old voice.' in prompt and 'More of it.' in prompt
        assert MARKER not in prompt

    def test_without_rewrite_the_old_prose_is_not_sent(self, project_dir):
        self._scene(project_dir, 'The old voice.\n')
        prompt = cmd_write._build_prompt('act1-sc01', project_dir, 'full', use_briefs=True)
        assert HEADING not in prompt

    def test_a_scene_without_prose_gets_no_block(self, project_dir):
        path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        if os.path.exists(path):
            os.remove(path)
        prompt = cmd_write._build_prompt('act1-sc01', project_dir, 'full', use_briefs=True,
                                         rewrite=True)
        assert HEADING not in prompt


class TestRedraftsAreRewrites:

    def test_revise_redraft_from_briefs_asks_for_a_rewrite(self, project_dir, monkeypatch):
        from storyforge import cmd_revise
        seen = []
        monkeypatch.setattr(cmd_write, '_build_prompt',
                            lambda sid, *a, **k: seen.append(k.get('rewrite')) or '')
        monkeypatch.setattr(cmd_revise, 'commit_and_push', lambda *a, **k: True)
        with pytest.raises(cmd_revise.RedraftError):   # no prompt: nothing drafted
            cmd_revise._redraft_from_briefs(project_dir, ['act1-sc01'], 'm', str(project_dir),
                                            system=[{'type': 'text', 'text': 's'}])
        assert seen == [True]

    def test_the_upstream_fix_redraft_uses_the_brief_prompt_and_earlier_prose(
            self, project_dir, monkeypatch):
        from storyforge import cmd_revise
        seen, systems = [], []
        monkeypatch.setattr(cmd_write, '_build_prompt',
                            lambda sid, pd, coaching, **k: seen.append((sid, k)) or 'prompt')
        monkeypatch.setattr(cmd_write, '_detect_briefs', lambda pd: True)
        monkeypatch.setattr('storyforge.common.build_shared_context',
                            lambda *a, **k: [{'type': 'text', 'text': 'shared'}])
        monkeypatch.setattr('storyforge.prompts.prior_prose_blocks',
                            lambda sid, pd, mode: [{'type': 'text', 'text': f'before {sid}'}])

        def invoke(prompt, model, **k):
            systems.append(k.get('system'))
            return ''   # no reply: nothing written
        monkeypatch.setattr(cmd_revise, 'invoke_api', invoke)
        with pytest.raises(cmd_revise.RedraftError, match='no response'):
            cmd_revise._redraft_scenes(project_dir, ['act1-sc01'])
        assert seen[0][0] == 'act1-sc01'
        assert seen[0][1]['use_briefs'] is True and seen[0][1]['rewrite'] is True
        assert systems[0][-1] == {'type': 'text', 'text': 'before act1-sc01'}


def test_e5_measures_the_rewrite_and_the_ledger_alone(monkeypatch, tmp_path):
    sys.path.insert(0, os.path.join(PLUGIN_DIR, 'evals'))
    import importlib
    suite = importlib.import_module('suites.e5_roundtrip')
    import e5
    monkeypatch.setattr(e5, 'project', lambda w: str(tmp_path))
    monkeypatch.setattr(e5, 'sample', lambda p: ['a', 'b'])
    monkeypatch.setattr(e5, 'commit_prose', lambda p, s: None)
    calls = []

    def roundtrip(p, sid, rewrite=True):
        calls.append((sid, rewrite))
        n = 1 if rewrite else 3
        return 'x', [{'code': 'PHY', 'fact': 'f'}] * n
    monkeypatch.setattr(e5, 'roundtrip', roundtrip)
    out = suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())
    assert calls == [('a', True), ('a', False), ('b', True), ('b', False)]
    assert out.metrics['mismatches'] == 2 and out.metrics['ledger_only.mismatches'] == 6
    gate = next(g for g in out.gates if g.name == 'mismatches_per_scene')
    assert gate.passed   # 1.0 per scene, at or below Phase 2's 2.3

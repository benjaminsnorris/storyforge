"""Phase 4 PR 5: rewrite-from-ledger (rethink plan §3.4, design note §6).

A redraft drafts from the plan and the binding ledger, with the scene's old
prose sent as a voice reference only. Before, a redraft never saw the old
prose, and revise's `_redraft_scenes` (after the upstream brief fix) used
the old prompt with neither the brief's fact columns nor the ledger."""

import os
import re
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
        assert prompt.index('## Established Facts') < prompt.index(HEADING) \
            < prompt.index('## Task')

    def test_a_fresh_draft_has_no_such_block(self, project_dir):
        prompt = _prompt(project_dir, voice='')
        assert HEADING not in prompt and 'This is a rewrite' not in prompt

    @pytest.mark.parametrize('coaching', ['full', 'coach', 'strict'])
    @pytest.mark.parametrize('system_context', [True, False])
    def test_a_fresh_prompt_is_the_rewrite_prompt_minus_its_inserts(
            self, project_dir, coaching, system_context):
        """E4's recordings (fresh drafts) replay only while a fresh draft's
        prompt is byte-identical: the rewrite adds its block, its task line
        and its own-facts wording, and changes nothing else."""
        def build(voice):
            return build_scene_prompt_from_briefs('act1-sc01', project_dir, PLUGIN_DIR,
                                                  coaching, system_context=system_context,
                                                  voice_reference=voice)
        fresh, rewrite = build(''), build('Old prose.')
        if coaching == 'full':
            rewrite = rewrite[:rewrite.index(HEADING)] + rewrite[rewrite.index('## Task'):]
            rewrite = re.sub(r'\nThis is a rewrite: [^\n]*\n', '', rewrite)
            rewrite = re.sub(r'### Already established in this scene\n[^\n]*\n',
                             '### Established in this scene so far\n'
                             "From the scene's plan or its current draft. Keep each of "
                             'these unless the brief says otherwise: where they differ, '
                             'the brief wins.\n', rewrite)
        assert rewrite == fresh

    def test_a_rewrite_says_the_scenes_own_facts_still_hold(self, project_dir, monkeypatch):
        from storyforge import ledger
        real = ledger.drafting_slice

        def with_own(rows, sid, order, subjects):
            found = real(rows, sid, order, subjects)
            found.scene.append({'id': 'own-1', 'statement': 'The door is red.'})
            return found
        monkeypatch.setattr(ledger, 'drafting_slice', with_own)
        prompt = _prompt(project_dir)
        assert '### Already established in this scene' in prompt
        assert 'They hold even though the current draft below is a voice reference' in prompt
        assert prompt.index('The door is red.') < prompt.index(HEADING)
        fresh = _prompt(project_dir, voice='')
        assert '### Established in this scene so far' in fresh

    def test_without_ledger_facts_the_rewrite_names_the_brief_alone(self, project_dir,
                                                                    monkeypatch):
        from storyforge import prompts
        monkeypatch.setattr(prompts, '_established_facts_block', lambda *a, **k: '')
        prompt = _prompt(project_dir)
        assert 'comes from the brief, which win' in prompt
        assert 'Established Facts above' not in prompt

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

    @pytest.fixture(autouse=True)
    def _full(self, monkeypatch):
        # set, so teardown restores it: other tests leave the level in os.environ
        monkeypatch.setenv('STORYFORGE_COACHING', 'full')

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
        seen, systems, modes = [], [], []
        monkeypatch.setattr(cmd_write, '_build_prompt',
                            lambda sid, pd, coaching, **k: seen.append((sid, k)) or 'prompt')
        monkeypatch.setattr(cmd_write, '_detect_briefs', lambda pd: True)
        monkeypatch.setattr('storyforge.common.build_shared_context',
                            lambda *a, **k: [{'type': 'text', 'text': 'shared'}])
        monkeypatch.setattr('storyforge.prompts.prior_prose_blocks',
                            lambda sid, pd, mode: modes.append(mode)
                            or [{'type': 'text', 'text': f'before {sid}'}])

        def invoke(prompt, model, **k):
            systems.append(k.get('system'))
            return ''   # no reply: nothing written
        monkeypatch.setattr(cmd_revise, 'invoke_api', invoke)
        with pytest.raises(cmd_revise.RedraftError, match='no response'):
            cmd_revise._redraft_scenes(project_dir, ['act1-sc01'])
        assert seen[0][0] == 'act1-sc01'
        assert seen[0][1]['use_briefs'] is True and seen[0][1]['rewrite'] is True
        assert systems[0][-1] == {'type': 'text', 'text': 'before act1-sc01'}
        assert modes == ['full']   # the project's drafting.prior_prose (default full)

    def _redraft_scenes(self, project_dir, monkeypatch, ids=('act1-sc01',)):
        from storyforge import cmd_revise
        monkeypatch.setattr(cmd_revise, 'invoke_api',
                            lambda *a, **k: pytest.fail('spent before the check'))
        with pytest.raises(cmd_revise.RedraftError) as e:
            cmd_revise._redraft_scenes(project_dir, list(ids))
        return str(e.value)

    @pytest.mark.parametrize('level', ['coach', 'strict'])
    def test_the_upstream_fix_redraft_refuses_coach_and_strict(self, project_dir,
                                                                monkeypatch, level):
        """Their reply is a guide, which was written over the scene."""
        monkeypatch.setenv('STORYFORGE_COACHING', level)
        path = os.path.join(project_dir, 'scenes', 'act1-sc01.md')
        before = open(path).read() if os.path.exists(path) else None
        assert f'coaching is {level}' in self._redraft_scenes(project_dir, monkeypatch)
        assert (open(path).read() if os.path.exists(path) else None) == before

    def test_the_upstream_fix_redraft_needs_briefs(self, project_dir, monkeypatch):
        monkeypatch.setattr(cmd_write, '_detect_briefs', lambda pd: False)
        assert 'no briefs' in self._redraft_scenes(project_dir, monkeypatch)

    def test_a_bad_prior_prose_mode_stops_it_before_spending(self, project_dir, monkeypatch):
        with open(os.path.join(project_dir, 'storyforge.yaml'), 'a') as f:
            f.write('\ndrafting:\n  prior_prose: everything\n')
        assert 'prior_prose' in self._redraft_scenes(project_dir, monkeypatch)

    def test_a_scene_it_cannot_redraft_stops_the_rest(self, project_dir, monkeypatch):
        """The later scenes would see its stale prose among the earlier ones."""
        from storyforge import cmd_revise
        for sid in ('act1-sc01', 'act1-sc02'):
            with open(os.path.join(project_dir, 'scenes', f'{sid}.md'), 'w') as f:
                f.write('Old prose. ' * 100)
        monkeypatch.setattr(cmd_write, '_build_prompt', lambda *a, **k: 'prompt')
        monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
        sent = []
        monkeypatch.setattr(cmd_revise, 'invoke_api',
                            lambda prompt, model, **k: sent.append(k['label']) or '')
        with pytest.raises(cmd_revise.RedraftError) as e:
            cmd_revise._redraft_scenes(project_dir, ['act1-sc02', 'act1-sc01'])
        assert sent == ['redraft act1-sc01']
        assert 'act1-sc02 (not redrafted: redrafting stops' in str(e.value)

    def test_redraft_from_briefs_stops_at_an_unreadable_scene(self, project_dir, monkeypatch):
        from storyforge import cmd_revise
        with open(os.path.join(project_dir, 'scenes', 'act1-sc01.md'), 'wb') as f:
            f.write(b'\x93cp1252\x94')
        monkeypatch.setattr(cmd_revise, 'commit_and_push', lambda *a, **k: True)
        monkeypatch.setattr('storyforge.api.invoke_to_file',
                            lambda *a, **k: pytest.fail('drafted'))
        with pytest.raises(cmd_revise.RedraftError) as e:
            cmd_revise._redraft_from_briefs(project_dir, ['act1-sc01', 'act1-sc02'], 'm',
                                            str(project_dir),
                                            system=[{'type': 'text', 'text': 's'}])
        assert 'voice reference' in str(e.value)
        assert 'act1-sc02 (not redrafted' in str(e.value)


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
    gates = {g.name: g for g in out.gates}
    assert gates['mismatches_per_scene'].passed   # 1.0 per scene, at or below 2.3
    assert gates['ledger_only.mismatches_per_scene'].passed   # 3.0, not past 3.7
    assert out.metrics['ledger_only.PHY'] == 6
    assert any('ledger only, PHY: f' in n for n in out.notes)


@pytest.mark.parametrize('rewrite_n, ledger_n, rewrite_ok, ledger_ok', [
    (3, 3, False, True),      # the rewrite past Phase 2's 2.3
    (2.3, 3.7, True, True),   # exactly at both: <=
    (1, 4, True, False),      # the ledger regressed under a good rewrite
])
def test_e5_gates(monkeypatch, tmp_path, rewrite_n, ledger_n, rewrite_ok, ledger_ok):
    sys.path.insert(0, os.path.join(PLUGIN_DIR, 'evals'))
    import importlib
    suite = importlib.import_module('suites.e5_roundtrip')
    import e5
    monkeypatch.setattr(e5, 'project', lambda w: str(tmp_path))
    monkeypatch.setattr(e5, 'sample', lambda p: [str(i) for i in range(10)])
    monkeypatch.setattr(e5, 'commit_prose', lambda p, s: None)
    m = {'code': 'PHY', 'fact': 'f'}
    monkeypatch.setattr(e5, 'roundtrip', lambda p, sid, rewrite=True: (
        'x', [m] * (int(rewrite_n * 10) // 10 + (int(sid) < round(rewrite_n * 10) % 10)
                    if rewrite else
                    int(ledger_n * 10) // 10 + (int(sid) < round(ledger_n * 10) % 10))))
    out = suite.run(type('Ctx', (), {'work_dir': str(tmp_path)})())
    gates = {g.name: g.passed for g in out.gates}
    assert gates['mismatches_per_scene'] is rewrite_ok
    assert gates['ledger_only.mismatches_per_scene'] is ledger_ok


@pytest.mark.parametrize('rewrite', [True, False])
def test_e8_redraft_passes_rewrite_through_and_writes_nothing_ungated(
        monkeypatch, tmp_path, rewrite):
    sys.path.insert(0, os.path.join(PLUGIN_DIR, 'evals'))
    import e8
    (tmp_path / 'scenes').mkdir()
    (tmp_path / 'scenes' / 's.md').write_text('original')
    seen = []
    monkeypatch.setattr('storyforge.common.select_model', lambda t: 'm')
    monkeypatch.setattr('storyforge.common.build_shared_context', lambda p, model='': [])
    monkeypatch.setattr('storyforge.cmd_write._build_prompt',
                        lambda *a, **k: seen.append(k['rewrite']) or 'prompt')
    monkeypatch.setattr('storyforge.api.invoke', lambda *a, **k: {
        'content': [{'type': 'text', 'text': 'Drafted.'}]})
    assert e8.redraft(str(tmp_path), 's', gated=False, rewrite=rewrite).strip() == 'Drafted.'
    assert seen == [rewrite]
    assert (tmp_path / 'scenes' / 's.md').read_text() == 'original'


def test_revise_stops_on_a_bad_prior_prose_mode_before_any_brief_fix(
        project_dir, monkeypatch):
    """PR #476's review: `_redraft_scenes` reads drafting.prior_prose after
    the brief fix has been paid for and saved; revise checks it up front."""
    from storyforge import cmd_revise
    monkeypatch.setattr(cmd_revise, 'detect_project_root', lambda: project_dir)
    monkeypatch.setattr(cmd_revise, '_fix_upstream_briefs',
                        lambda *a, **k: pytest.fail('briefs fixed before the check'))
    with open(os.path.join(project_dir, 'storyforge.yaml'), 'a') as f:
        f.write('\ndrafting:\n  prior_prose: everything\n')
    with pytest.raises(SystemExit) as e:
        cmd_revise.main(['--naturalness'])
    assert e.value.code == 1

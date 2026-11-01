"""`write` over prose already on disk is a rewrite (Phase 4 PR 5): the old
prose goes in the prompt as a voice reference only, markers stripped."""

import json
import os

import pytest

from .test_write_guard import GOOD, _reply, setup  # noqa: F401

HEADING = '## The Current Draft (voice reference only)'


def _write(setup, monkeypatch, args):
    from storyforge.cmd_write import main
    prompts = {}

    def fake(prompt, model, log_file, max_tokens=4096, label='', timeout=600,
             system=None, output_schema=None, fallback=False):
        prompts[label.split()[-1]] = prompt
        with open(log_file, 'w') as f:
            json.dump(_reply(GOOD), f)
        return _reply(GOOD)
    monkeypatch.setattr('storyforge.cmd_write.invoke_to_file', fake)
    monkeypatch.setattr('storyforge.common.build_shared_context',
                        lambda *a, **k: [{'type': 'text', 'text': 's'}])
    with open(os.path.join(setup, 'scenes', 'act1-sc01.md'), 'w') as f:
        f.write('A distinctive OLDVOICE sentence.\n\n![[illus:x]]\n')
    path = os.path.join(setup, 'scenes', 'act1-sc02.md')
    if os.path.exists(path):
        os.remove(path)
    main(args)
    return prompts


def test_write_force_rewrites_from_the_old_prose_as_voice(setup, monkeypatch):
    prompts = _write(setup, monkeypatch, ['--direct', '--force', '--scenes',
                                          'act1-sc01,act1-sc02'])
    assert '<current_draft>\nA distinctive OLDVOICE sentence.\n</current_draft>' \
        in prompts['act1-sc01']
    assert '![[illus:x]]' not in prompts['act1-sc01']
    assert HEADING not in prompts['act1-sc02']   # a fresh draft


def test_an_unreadable_scene_stops_write_before_drafting(setup, monkeypatch, capsys):
    from storyforge.cmd_write import main
    monkeypatch.setattr('storyforge.cmd_write.invoke_to_file',
                        lambda *a, **k: pytest.fail('drafted without its voice reference'))
    with open(os.path.join(setup, 'scenes', 'act1-sc01.md'), 'wb') as f:
        f.write(b'Smart \x93quotes\x94 from cp1252.')
    with pytest.raises(SystemExit):
        main(['--direct', '--force', '--scenes', 'act1-sc01'])
    assert 'voice reference' in capsys.readouterr().out


def test_batch_mode_asks_for_a_rewrite_too(project_dir, monkeypatch):
    """Batch writes no prose at full (refused), but prose on disk is a
    rewrite in every mode (the block shows only at full)."""
    from storyforge import cmd_write
    seen = []
    monkeypatch.setattr(cmd_write, '_build_prompt',
                        lambda *a, **k: seen.append(k.get('rewrite')) or '')
    with pytest.raises(SystemExit):   # no prompt: stops
        cmd_write._run_batch_mode(['act1-sc01'], project_dir,
                                  os.path.join(project_dir, 'scenes'),
                                  os.path.join(project_dir, 'working', 'logs'),
                                  os.path.join(project_dir, 'reference', 'scenes.csv'),
                                  'coach', True, True, 'single')
    assert seen == [True]

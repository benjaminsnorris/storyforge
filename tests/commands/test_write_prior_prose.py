"""write sends earlier prose with each scene (decision 4)."""

import pytest

from .test_write_guard import GOOD, _reply, setup  # noqa: F401


@pytest.mark.parametrize('flag, earlier', [
    ([], ['act1-sc01']),                  # full (the default): the scene just drafted
    (['--prior-prose', 'window'], ['act1-sc01']),
    (['--prior-prose', 'none'], []),
    (['--prior-prose', 'full'], ['act1-sc01']),
])
def test_write_sends_the_earlier_prose_after_the_shared_context(
        setup, monkeypatch, flag, earlier):
    import json
    from storyforge.cmd_write import main
    systems = {}

    def fake(prompt, model, log_file, max_tokens=4096, label='', timeout=600,
             system=None, output_schema=None, fallback=False):
        sid = label.split()[-1]
        systems[sid] = system
        with open(log_file, 'w') as f:
            json.dump(_reply(GOOD), f)
        return _reply(GOOD)
    monkeypatch.setattr('storyforge.cmd_write.invoke_to_file', fake)
    monkeypatch.setattr('storyforge.common.build_shared_context',
                        lambda *a, **k: [{'type': 'text', 'text': 'shared'}])
    main(['--direct', '--force', '--scenes', 'act1-sc01,act1-sc02'] + flag)
    sent = systems['act1-sc02']
    assert sent[0]['text'] == 'shared'
    assert [b['text'].split('"')[1] for b in sent[2:]] == earlier


def test_a_bad_mode_stops_before_anything_is_set_up(setup, monkeypatch):
    from storyforge import cmd_write
    monkeypatch.setattr(cmd_write, 'create_branch',
                        lambda *a, **k: pytest.fail('set up before the check'))
    with open(f'{setup}/storyforge.yaml', 'a') as f:
        f.write('\ndrafting:\n  prior_prose: everything\n')
    with pytest.raises(SystemExit):
        cmd_write.main(['--direct', '--scenes', 'act1-sc01'])

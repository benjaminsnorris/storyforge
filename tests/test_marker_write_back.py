"""Paths that write a scene back keep its illustration markers (#610's review,
T-1 and SF-W).

#280 sends scene prose to analysis and prompts without markers. Code that
writes the file back must not: it reads the scene *with* its markers, and
whatever rewrote the prose (a redraft, a revision pass, the gate's fix, the
CLI) has them put back from the plan. Each test runs a write-back path on a
scene with a marker and fails if that path read the scene stripped or wrote
the rewrite as it came.
"""

import json
import os
from types import SimpleNamespace

import pytest

from illustration_helpers import plan_row, write_scene
from storyforge import illustrations as ill

SID = 'act1-sc01'
MARKER = '![[illus:lf-01]]'
ANCHOR = 'She set the lantern on the sill'

# Long enough for every word floor (`write`'s 100, the shrink guard).
BODY = ' '.join(f'Line {i} of the waiting, slow and cold.' for i in range(40))
ORIGINAL = f'{ANCHOR} and waited.\n\n{MARKER}\n\n{BODY}\n'
#: What a model writes back: the same scene, reworded, with no marker.
REWRITE = f'{ANCHOR} and waited a while.\n\n{BODY} The night held.\n'


@pytest.fixture
def illustrated(project_dir):
    """The fixture project with SID illustrated: one marker after ANCHOR's
    paragraph, and the plan row that places it."""
    write_scene(project_dir, SID, ORIGINAL)
    ill.write_plan(project_dir, [plan_row(id='lf-01', scene_id=SID, anchor=ANCHOR,
                                          placement='after_anchor')])
    assert ill.insert_marker(REWRITE, ill.read_plan_as_map(project_dir)['lf-01'])['changed']
    return project_dir


def _scene(project_dir, sid=SID):
    with open(os.path.join(project_dir, 'scenes', f'{sid}.md'), encoding='utf-8') as f:
        return f.read()


# ============================================================================
# write
# ============================================================================

def test_write_skips_a_short_illustrated_scene(project_dir):
    """SF-W: the skip rule counts prose words (#280), so a scene of 200 words
    and a marker no longer clears it on the marker's word; it is kept, not
    redrafted out from under its illustration, and the log says why."""
    from storyforge.cmd_write import _already_drafted, _drafted
    scenes_dir = os.path.join(project_dir, 'scenes')
    write_scene(project_dir, 's1', ' '.join(['word'] * 200) + f'\n\n{MARKER}\n')
    write_scene(project_dir, 's2', ' '.join(['word'] * 200) + '\n')
    assert _drafted(scenes_dir, 's1') and not _drafted(scenes_dir, 's2')
    assert 'illustration marker' in _already_drafted(scenes_dir, 's1')
    write_scene(project_dir, 's3', ' '.join(['word'] * 199) + f'\n\n{MARKER}\n{MARKER}\n')
    assert _already_drafted(scenes_dir, 's3').startswith('has 199 words and 2')


def _reply(log_dir, text):
    path = os.path.join(log_dir, 'reply.json')
    with open(path, 'w') as f:
        json.dump({'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn',
                   'usage': {'input_tokens': 1, 'output_tokens': 1}}, f)
    return path


def test_write_redraft_keeps_the_markers(illustrated, tmp_path, capsys):
    """`write --force` (and revise's redraft from briefs) write the reply
    through `_extract_scene_from_response`."""
    from storyforge.cmd_write import _extract_scene_from_response
    out = os.path.join(illustrated, 'scenes', f'{SID}.md')
    assert _extract_scene_from_response(_reply(str(tmp_path), REWRITE), out) == ''
    text = _scene(illustrated)
    assert MARKER in text and 'waited a while' in text
    assert 'restored 1 illustration marker(s) the redraft dropped: lf-01' in capsys.readouterr().out


def test_write_word_floor_counts_prose(tmp_path):
    """C-5: the floor on a reply counts prose words, as the skip rule does."""
    from storyforge.cmd_write import _extract_scene_from_response
    out = os.path.join(str(tmp_path), 'scenes', 's1.md')
    reply = (''.join(f'![[illus:x{i}]]\n\n' for i in range(3))
             + ' '.join(['word'] * 98) + ' end.\n')
    assert _extract_scene_from_response(_reply(str(tmp_path), reply), out) == \
        'only 99 words (the floor is 100)'


def test_write_interactive_floor_counts_prose(tmp_path):
    """C-5: the CLI's scene meets the same prose floor."""
    from storyforge.cmd_write import _interactive_problem
    path = os.path.join(str(tmp_path), 's1.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(' '.join(['word'] * 99) + '\n\n![[illus:a]]\n\n![[illus:b]]\n')
    assert _interactive_problem(path, '') == 'only 99 words (the floor is 100)'


def test_write_interactive_keeps_the_markers(illustrated, capsys):
    from storyforge.cmd_write import _keep_cli_markers
    path = os.path.join(illustrated, 'scenes', f'{SID}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(REWRITE)   # what the CLI wrote
    _keep_cli_markers(illustrated, SID, path, ORIGINAL)
    assert MARKER in _scene(illustrated)
    assert 'the CLI dropped: lf-01' in capsys.readouterr().out


@pytest.mark.real_gate
def test_gate_fix_keeps_the_markers(illustrated, monkeypatch):
    """The gate fixes prose by find/replace; whatever its fix drops comes back."""
    from storyforge import cmd_write, gate
    seen = []

    def gate_and_fix(project_dir, scene_id, *, prose, **k):
        seen.append(prose)
        return SimpleNamespace(fixed=True, prose=REWRITE, log_dir='', rounds=[], notes=[],
                               reextraction=None,
                               result=SimpleNamespace(passed=True, proposed=[], recheck=[]))
    monkeypatch.setattr(gate, 'gate_and_fix', gate_and_fix)
    monkeypatch.setattr(gate, 'report_lines', lambda r: [])
    monkeypatch.setattr(cmd_write, 'report_changes', lambda r: None)
    path = os.path.join(illustrated, 'scenes', f'{SID}.md')
    assert cmd_write._gate_drafted_scene(illustrated, SID, path, 'draft', str(illustrated)) \
        == (True, '')
    assert seen == [ORIGINAL]
    assert MARKER in _scene(illustrated) and 'waited a while' in _scene(illustrated)


# ============================================================================
# revise
# ============================================================================

def test_revision_pass_keeps_the_markers(illustrated):
    """A revision pass's reply is written by `parsing extract-scenes`."""
    from storyforge.parsing import extract_scenes_from_response
    reply = f'=== SCENE: {SID} ===\n{REWRITE}\n=== END SCENE: {SID} ===\n'
    assert extract_scenes_from_response(reply, os.path.join(illustrated, 'scenes')) == [SID]
    assert MARKER in _scene(illustrated) and 'waited a while' in _scene(illustrated)


def test_revise_gated_pass_keeps_the_markers(illustrated, monkeypatch):
    """cmd_revise reads what the pass wrote, with its markers, before the
    gate runs (`_gate_pass_scenes`), and puts back what the gate dropped."""
    from storyforge import cmd_revise, cmd_write, gate

    def gate_drops_the_marker(project_dir, sid, scene_file, *a, **k):
        with open(scene_file, 'w', encoding='utf-8') as f:
            f.write(REWRITE)
        return True, ''
    monkeypatch.setattr(cmd_write, '_gate_drafted_scene', gate_drops_the_marker)
    monkeypatch.setattr(cmd_write, '_gate_blockers', lambda *a, **k: [])
    monkeypatch.setattr(cmd_revise, '_commit', lambda *a, **k: None)
    monkeypatch.setattr(gate, 'clear_pending', lambda *a: None)
    monkeypatch.setattr(cmd_revise, '_recheck_after', lambda *a, **k: None)
    monkeypatch.setattr(cmd_revise, '_note_recheck', lambda *a, **k: None)
    cmd_revise._gate_pass_scenes(illustrated, [SID], 'p', str(illustrated))
    assert MARKER in _scene(illustrated)


def test_revise_redraft_keeps_the_markers(illustrated, monkeypatch):
    """`_redraft_scenes` reads the scene with its markers as the original the
    rewrite is restored from."""
    from storyforge import cmd_revise, cmd_write
    monkeypatch.setenv('STORYFORGE_COACHING', 'full')
    monkeypatch.setattr(cmd_write, '_build_prompt', lambda *a, **k: 'prompt')
    monkeypatch.setattr(cmd_write, '_detect_briefs', lambda pd: True)
    monkeypatch.setattr('storyforge.common.build_shared_context', lambda *a, **k: [])
    monkeypatch.setattr(cmd_revise, 'invoke_api', lambda *a, **k: REWRITE)
    monkeypatch.setattr('storyforge.git.commit_and_push', lambda *a, **k: True)
    monkeypatch.setattr(cmd_revise, '_leaning', lambda *a: '')
    monkeypatch.setattr(cmd_revise, '_gate_redraft', lambda *a, **k: '')
    monkeypatch.setattr(cmd_revise, '_recheck_after', lambda *a, **k: None)
    monkeypatch.setattr(cmd_revise, '_note_recheck', lambda *a, **k: None)
    cmd_revise._redraft_scenes(illustrated, [SID])
    assert MARKER in _scene(illustrated) and 'waited a while' in _scene(illustrated)


# ============================================================================
# cleanup
# ============================================================================

def test_cleanup_artifact_strip_keeps_the_markers(tmp_path):
    """Cleanup's scene-artifact fix rewrites the file: a marker is not an
    artifact."""
    from storyforge.cmd_cleanup import _scene_files_to_clean
    write_scene(str(tmp_path), 's1', f'# A Title\n\n{ORIGINAL}')
    [(name, cleaned)] = _scene_files_to_clean(str(tmp_path))
    assert name == 's1.md' and MARKER in cleaned and '# A Title' not in cleaned

"""Regression test for #151: _redraft_scenes must strip scene markers.

When the Claude API returns text wrapped in === SCENE: id === / === END SCENE ===
delimiters, _redraft_scenes should strip them before writing the scene file.
"""

import os
from unittest.mock import patch


def test_redraft_strips_scene_markers(project_dir):
    """Verify that _redraft_scenes strips === SCENE === markers from API output."""
    from storyforge.cmd_revise import _redraft_scenes

    # Create a scene file so _redraft_scenes will process it
    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    scene_file = os.path.join(scenes_dir, 'test-scene.md')
    with open(scene_file, 'w') as f:
        f.write('old content')

    # Simulate an API response wrapped in scene markers
    api_response = (
        '=== SCENE: test-scene ===\n'
        'The rain fell softly on the cobblestones.\n'
        '\n'
        'She paused at the corner, listening.\n'
        '=== END SCENE: test-scene ==='
    )

    with patch('storyforge.cmd_revise.invoke_api', return_value=api_response), \
         patch('storyforge.cmd_revise.select_model', return_value='claude-sonnet-4-6'), \
         patch('storyforge.prompts.build_scene_prompt', return_value='fake prompt'), \
         patch('storyforge.common.get_coaching_level', return_value='full'):
        count = _redraft_scenes(project_dir, ['test-scene'])

    assert count == 1
    with open(scene_file) as f:
        content = f.read()

    # The markers must NOT appear in the written file
    assert '=== SCENE:' not in content
    assert '=== END SCENE:' not in content

    # The actual prose must be present
    assert 'The rain fell softly on the cobblestones.' in content
    assert 'She paused at the corner, listening.' in content


def test_redraft_preserves_clean_response(project_dir):
    """When the API response has no markers, it should be written as-is."""
    from storyforge.cmd_revise import _redraft_scenes

    scenes_dir = os.path.join(project_dir, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    scene_file = os.path.join(scenes_dir, 'clean-scene.md')
    with open(scene_file, 'w') as f:
        f.write('old content')

    clean_response = 'The rain fell softly on the cobblestones.\n\nShe paused at the corner.'

    with patch('storyforge.cmd_revise.invoke_api', return_value=clean_response), \
         patch('storyforge.cmd_revise.select_model', return_value='claude-sonnet-4-6'), \
         patch('storyforge.prompts.build_scene_prompt', return_value='fake prompt'), \
         patch('storyforge.common.get_coaching_level', return_value='full'):
        count = _redraft_scenes(project_dir, ['clean-scene'])

    assert count == 1
    with open(scene_file) as f:
        content = f.read()

    assert content == clean_response

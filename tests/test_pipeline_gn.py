"""Integration test: full GN pipeline from briefs → write → script-package."""

import json
import os

import pytest


PIPELINE_SCRIPTS = {
    'the-blank-page': """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1**
Cartographer at desk. Blank parchment.

- CAPTION: *The map remained blank.*

---

## Page 2 — 4-GRID

**Panel 1**
Hand.

**Panel 2**
Pen.

**Panel 3**
Line.

**Panel 4**
Stare.
""",
    'shadows-arrive': """\
# Scene: shadows-arrive

**Target pages:** 1 | **Layout intent:** 6-grid

---

## Page 1 — 6-GRID

**Panel 1**
Door.

**Panel 2**
Shadow.

**Panel 3**
Lamp.

**Panel 4**
Cartographer turns.

**Panel 5**
Listens.

**Panel 6**
Stands.
""",
    'the-first-mark': """\
# Scene: the-first-mark

**Target pages:** 1 | **Layout intent:** 3-tier

---

## Page 1 — 3-TIER

**Panel 1**
Returns to desk.

**Panel 2**
Sees filled page.

**Panel 3**
Reaches.
""",
}


def _fake_invoke_to_file_for_pipeline(prompt, model, log_file, **kwargs):
    """Return a script that matches whichever scene is currently being drafted.

    We sniff the scene id from the prompt's 'id:' line.
    """
    scene_id = 'the-blank-page'  # default
    for sid in PIPELINE_SCRIPTS:
        if f'id: {sid}' in prompt:
            scene_id = sid
            break
    text = PIPELINE_SCRIPTS[scene_id]
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    response = {
        'content': [{'type': 'text', 'text': text}],
        'usage': {'input_tokens': 100, 'output_tokens': 300,
                  'cache_read_input_tokens': 0,
                  'cache_creation_input_tokens': 0},
    }
    with open(log_file, 'w') as f:
        json.dump(response, f)
    return response


def test_full_gn_pipeline(project_dir_gn, monkeypatch):
    """Run write → assemble on the GN fixture and verify the bundle."""
    monkeypatch.chdir(project_dir_gn)

    # Stub the API
    from storyforge import api
    monkeypatch.setattr(api, 'invoke_to_file', _fake_invoke_to_file_for_pipeline)

    # Write a chapter map
    map_path = os.path.join(project_dir_gn, 'reference', 'chapter-map.csv')
    with open(map_path, 'w') as f:
        f.write('chapter|title|heading|scenes\n')
        f.write('1|Opening|numbered-titled|the-blank-page;shadows-arrive;the-first-mark\n')

    # Run write (via the dispatcher to ensure routing works)
    from storyforge.__main__ import main as dispatcher_main
    monkeypatch.setattr('sys.argv', ['storyforge', 'write', '--direct'])
    dispatcher_main()

    # Verify all 3 scenes drafted
    from storyforge.csv_cli import get_field
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    for sid in PIPELINE_SCRIPTS:
        assert get_field(scenes_csv, sid, 'status') == 'drafted', f'{sid} not drafted'
        scene_path = os.path.join(project_dir_gn, 'scenes', f'{sid}.md')
        assert os.path.isfile(scene_path), f'{sid} script not written'

    # Run assemble (via the dispatcher to ensure routing works)
    monkeypatch.setattr('sys.argv', ['storyforge', 'assemble'])
    dispatcher_main()

    # Verify bundle
    bundle = os.path.join(project_dir_gn, 'manuscript')
    for filename in ('script.md', 'visual-references.md', 'chapter-map.md',
                     'handoff-readme.md'):
        path = os.path.join(bundle, filename)
        assert os.path.isfile(path), f'bundle missing {filename}'

    # script.md should have global page numbering: 2 + 1 + 1 = 4 pages
    script = open(os.path.join(bundle, 'script.md')).read()
    assert '## Page 1 —' in script
    assert '## Page 4 —' in script

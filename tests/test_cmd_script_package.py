"""Tests for cmd_script_package — GN artist handoff bundle."""

import os
import pytest


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    """Clear ANTHROPIC_API_KEY by default so the style-guide step falls
    back to the deterministic coach template — tests that explicitly
    test the LLM path re-set the env via monkeypatch.setenv."""
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)


SAMPLE_SCRIPT_A = """\
# Scene: the-blank-page

**Target pages:** 2 | **Layout intent:** splash p1, 4-grid p2

---

## Page 1 — SPLASH

**Panel 1**
Comp.

- CAPTION: *Cap A.*

---

## Page 2 — 4-GRID

**Panel 1**
Comp.
"""

SAMPLE_SCRIPT_B = """\
# Scene: shadows-arrive

**Target pages:** 1 | **Layout intent:** 6-grid p1

---

## Page 1 — 6-GRID

**Panel 1**
Comp.

- CAPTION: *Cap B.*
"""


def _setup_drafted_scenes(project_dir_gn):
    """Write fake drafted scenes and update CSV statuses."""
    scenes_dir = os.path.join(project_dir_gn, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'the-blank-page.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_A)
    with open(os.path.join(scenes_dir, 'shadows-arrive.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_B)
    from storyforge.csv_cli import update_field
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    update_field(scenes_csv, 'the-blank-page', 'status', 'drafted')
    update_field(scenes_csv, 'shadows-arrive', 'status', 'drafted')


def _setup_chapter_map(project_dir_gn):
    """Write a minimal chapter-map.csv mapping scenes 1-2 into chapter 1."""
    map_path = os.path.join(project_dir_gn, 'reference', 'chapter-map.csv')
    with open(map_path, 'w') as f:
        f.write('chapter|title|heading|scenes\n')
        f.write('1|Opening|numbered-titled|the-blank-page;shadows-arrive\n')


def test_script_package_produces_bundle(project_dir_gn, monkeypatch):
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main([])

    bundle = os.path.join(project_dir_gn, 'manuscript')
    assert os.path.isfile(os.path.join(bundle, 'script.md'))
    assert os.path.isfile(os.path.join(bundle, 'visual-references.md'))
    assert os.path.isfile(os.path.join(bundle, 'chapter-map.md'))
    assert os.path.isfile(os.path.join(bundle, 'handoff-readme.md'))
    assert os.path.isfile(os.path.join(bundle, 'style-guide.md'))


# ---------------------------------------------------------------------------
# Style-guide generation (coaching-aware)
# ---------------------------------------------------------------------------

def test_style_guide_strict_template_no_llm(project_dir_gn, monkeypatch):
    """coaching=strict produces a section template with no LLM call."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import api, cmd_script_package
    def fail(*a, **k):
        raise AssertionError('LLM must not be called in strict mode')
    monkeypatch.setattr(api, 'invoke_to_file', fail)
    cmd_script_package.main(['--coaching', 'strict'])
    text = open(os.path.join(project_dir_gn, 'manuscript',
                              'style-guide.md')).read()
    assert '## Palette' in text
    assert '## Line weight and inking' in text
    assert '## Lettering and caption tone' in text
    assert '## Panel-rhythm philosophy' in text
    assert '## Reference-art inspirations' in text
    # Strict template is a constraint list — no LLM-generated prose
    assert 'constraint template' in text.lower() or 'Constraint template' in text


def test_style_guide_coach_writes_questions_no_llm(project_dir_gn, monkeypatch):
    """coaching=coach produces cues + questions, no LLM call."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import api, cmd_script_package
    def fail(*a, **k):
        raise AssertionError('LLM must not be called in coach mode')
    monkeypatch.setattr(api, 'invoke_to_file', fail)
    cmd_script_package.main(['--coaching', 'coach'])
    text = open(os.path.join(project_dir_gn, 'manuscript',
                              'style-guide.md')).read()
    assert '## Palette' in text
    assert '- Question:' in text
    assert 'Coaching brief' in text or 'coaching=coach' in text


def test_style_guide_full_uses_llm_when_key_set(project_dir_gn, monkeypatch):
    """coaching=full + API key set → LLM-synthesized guide written to bundle."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    called = {}
    def fake(prompt, model, log_file, **kwargs):
        called['prompt'] = prompt
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text', 'text':
                          f'# Test — Style guide\n\n## Palette\n\n'
                          f'A pale, candlelit register with rare crimson.\n\n'
                          f'## Line weight and inking\n\nMedium with brush.\n\n'
                          f'## Lettering and caption tone\n\nWhisper captions.\n\n'
                          f'## Panel-rhythm philosophy\n\n4-grid baseline.\n\n'
                          f'## Reference-art inspirations\n\nMike Mignola.\n'}],
            'usage': {'input_tokens': 1000, 'output_tokens': 400,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            json.dump(response, f)
        return response
    import json
    from storyforge import api, cmd_script_package
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_script_package, 'invoke_to_file', fake,
                        raising=False)
    cmd_script_package.main(['--coaching', 'full'])
    text = open(os.path.join(project_dir_gn, 'manuscript',
                              'style-guide.md')).read()
    assert 'A pale, candlelit register with rare crimson.' in text
    assert called['prompt']  # was actually called


def test_style_guide_full_falls_back_on_unparseable_response(
    project_dir_gn, monkeypatch,
):
    """When the LLM returns a response that doesn't start with `#`, the
    style-guide step must fall back to the coach template AND record
    the call's cost with `:unparseable` target (the API call was
    billed)."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    import json as _json
    def fake(prompt, model, log_file, **kwargs):
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        response = {
            'content': [{'type': 'text',
                          'text': 'Sure! Here is the guide:\n(without a header)'}],
            'usage': {'input_tokens': 100, 'output_tokens': 50,
                      'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0},
        }
        with open(log_file, 'w') as f:
            _json.dump(response, f)
        return response
    from storyforge import api, cmd_script_package
    monkeypatch.setattr(api, 'invoke_to_file', fake)
    monkeypatch.setattr(cmd_script_package, 'invoke_to_file', fake)
    cmd_script_package.main(['--coaching', 'full'])
    text = open(os.path.join(project_dir_gn, 'manuscript',
                              'style-guide.md')).read()
    # Falls back to coach template
    assert '- Question:' in text
    # Cost ledger has the `unparseable` target
    ledger = open(os.path.join(project_dir_gn, 'working', 'costs',
                                'ledger.csv')).read()
    assert 'unparseable' in ledger


def test_style_guide_full_falls_back_on_llm_exception(
    project_dir_gn, monkeypatch,
):
    """When invoke_to_file raises, the bundle completes with the coach
    template — no exception propagates."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    def raise_exc(*a, **k):
        raise RuntimeError('simulated network failure')
    from storyforge import api, cmd_script_package
    monkeypatch.setattr(api, 'invoke_to_file', raise_exc)
    monkeypatch.setattr(cmd_script_package, 'invoke_to_file', raise_exc)
    cmd_script_package.main(['--coaching', 'full'])
    text = open(os.path.join(project_dir_gn, 'manuscript',
                              'style-guide.md')).read()
    assert '- Question:' in text


def test_style_guide_sections_consistent_across_modes():
    """Every renderer (strict, coach, LLM prompt) must emit the same set
    of sections in the same order. _STYLE_GUIDE_SECTIONS is the single
    source of truth — drift here is a real bug."""
    from storyforge.cmd_script_package import (
        _STYLE_GUIDE_SECTIONS, _render_strict_style_guide,
        _render_coach_style_guide, _build_full_style_guide_prompt,
        StyleGuideCues,
    )
    cues = StyleGuideCues(
        genre='', subgenre='', world_bible='', character_bible='',
        voice_guide='', scene_intent_excerpt='',
    )
    strict = _render_strict_style_guide('T', cues)
    coach = _render_coach_style_guide('T', cues)
    prompt = _build_full_style_guide_prompt('T', cues)
    for section in _STYLE_GUIDE_SECTIONS:
        assert f'## {section}' in strict, f'strict missing {section}'
        assert f'## {section}' in coach, f'coach missing {section}'
        assert f'## {section}' in prompt, f'LLM prompt missing {section}'


def test_style_guide_no_plan1_marker_in_user_facing_output():
    """The coach template must not leak 'Plan 1' task-state markers
    into the user-facing style-guide written to the artist bundle."""
    from storyforge.cmd_script_package import (
        _render_coach_style_guide, StyleGuideCues,
    )
    cues = StyleGuideCues(
        genre='', subgenre='', world_bible='', character_bible='',
        voice_guide='', scene_intent_excerpt='',
    )
    text = _render_coach_style_guide('T', cues)
    assert 'Plan 1' not in text


def test_style_guide_full_falls_back_without_api_key(project_dir_gn, monkeypatch, capsys):
    """coaching=full without API key → falls back to coach template; bundle
    still succeeds; final log line names the ACTUAL mode used, not 'full'."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    from storyforge import cmd_script_package
    cmd_script_package.main(['--coaching', 'full'])
    text = open(os.path.join(project_dir_gn, 'manuscript',
                              'style-guide.md')).read()
    # Falls back to coach template (recognizable by the Question: pattern)
    assert '- Question:' in text
    # The final log line must not lie about the mode: it should report
    # the fallback, not 'coaching=full'.
    out = capsys.readouterr().out
    assert 'no API key' in out or 'full→coach' in out


def test_script_package_global_page_numbering(project_dir_gn, monkeypatch):
    """The assembled script renumbers pages globally across scenes."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main([])

    script_md = open(os.path.join(project_dir_gn, 'manuscript', 'script.md')).read()
    # Scene A has 2 pages, scene B has 1. Globally renumbered: A pages 1-2, B page 3.
    assert '## Page 1 —' in script_md
    assert '## Page 2 —' in script_md
    assert '## Page 3 —' in script_md


def test_script_package_visual_references_extracted(project_dir_gn, monkeypatch):
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main([])

    refs = open(os.path.join(project_dir_gn, 'manuscript', 'visual-references.md')).read()
    # Cartographer Visual section content from the fixture
    assert 'Cartographer' in refs
    assert 'spectacles' in refs.lower() or 'silhouette' in refs.lower()
    # World bible content
    assert 'study' in refs.lower() or 'lamplight' in refs.lower()


def test_script_package_fails_when_no_chapter_map(project_dir_gn, monkeypatch):
    """Missing chapter-map.csv is a clear error."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    # Note: no chapter map
    from storyforge import cmd_script_package
    with pytest.raises(SystemExit) as exc_info:
        cmd_script_package.main([])
    assert exc_info.value.code != 0


def test_script_package_rejects_novel_projects(project_dir, monkeypatch):
    """Running cmd_script_package on a novel-mode project exits with an error."""
    monkeypatch.chdir(project_dir)
    from storyforge import cmd_script_package
    with pytest.raises(SystemExit) as exc_info:
        cmd_script_package.main([])
    assert exc_info.value.code != 0


def test_renumber_pages_preserves_page_turn_marker():
    """Global page renumbering must not strip the ⟵ PAGE-TURN REVEAL marker."""
    from storyforge.cmd_script_package import _renumber_pages
    text = '## Page 1 — SPLASH ⟵ PAGE-TURN REVEAL\n'
    result, _ = _renumber_pages(text, 5)
    assert result == '## Page 5 — SPLASH ⟵ PAGE-TURN REVEAL\n'


def test_script_package_handles_missing_scene_file(project_dir_gn, monkeypatch):
    """A chapter-map entry referencing a missing scene file produces a placeholder."""
    monkeypatch.chdir(project_dir_gn)
    _setup_drafted_scenes(project_dir_gn)
    # Chapter map references a scene that doesn't exist on disk
    map_path = os.path.join(project_dir_gn, 'reference', 'chapter-map.csv')
    with open(map_path, 'w') as f:
        f.write('chapter|title|heading|scenes\n')
        f.write('1|Opening|numbered-titled|the-blank-page;nonexistent-scene\n')
    # Also need 'nonexistent-scene' to appear in scenes.csv with status='drafted'
    # so the new draft-status check doesn't block it.
    scenes_csv = os.path.join(project_dir_gn, 'reference', 'scenes.csv')
    from storyforge.csv_cli import append_row
    # 16 columns matching the GN scenes.csv header (id|seq|title|part|pov|location|
    # timeline_day|time_of_day|duration|type|status|word_count|target_words|
    # target_pages|panel_count|page_count)
    append_row(scenes_csv, 'nonexistent-scene|99|Missing|1|cartographer|study|1|night|short|action|drafted||||')
    from storyforge import cmd_script_package
    cmd_script_package.main([])
    script_md = open(os.path.join(project_dir_gn, 'manuscript', 'script.md')).read()
    assert 'nonexistent-scene' in script_md
    assert 'not found' in script_md


def test_script_package_rejects_undrafted_scenes(project_dir_gn, monkeypatch):
    """Scenes with status != drafted cause a non-zero exit unless --force is passed."""
    monkeypatch.chdir(project_dir_gn)
    # Write scene files but leave CSV status as 'briefed' (fixture default)
    scenes_dir = os.path.join(project_dir_gn, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'the-blank-page.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_A)
    with open(os.path.join(scenes_dir, 'shadows-arrive.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_B)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    with pytest.raises(SystemExit) as exc_info:
        cmd_script_package.main([])
    assert exc_info.value.code != 0


def test_script_package_force_bypasses_status_check(project_dir_gn, monkeypatch):
    """--force allows bundling even when scenes are not drafted."""
    monkeypatch.chdir(project_dir_gn)
    scenes_dir = os.path.join(project_dir_gn, 'scenes')
    os.makedirs(scenes_dir, exist_ok=True)
    with open(os.path.join(scenes_dir, 'the-blank-page.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_A)
    with open(os.path.join(scenes_dir, 'shadows-arrive.md'), 'w') as f:
        f.write(SAMPLE_SCRIPT_B)
    _setup_chapter_map(project_dir_gn)
    from storyforge import cmd_script_package
    cmd_script_package.main(['--force'])
    bundle = os.path.join(project_dir_gn, 'manuscript')
    assert os.path.isfile(os.path.join(bundle, 'script.md'))

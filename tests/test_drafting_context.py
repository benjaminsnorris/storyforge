"""#596: drafting carries the author's key decisions, and no reference doc
still init's template reaches a prompt as the book's own (F-130).

Found drafting the Telemachy pilot: `write`'s scene prompt had no key
decisions (reading level, POV rules, how each hard event is told), and the
non-system-context prompt printed the voice-guide template, `[Title] --
Voice Guide` and all, as the book's voice guide.
"""

import os

import pytest

from storyforge.common import get_plugin_dir, is_unfilled_template, voice_guide_problem

TEMPLATES = os.path.join(get_plugin_dir(), 'templates', 'reference')
KD_MARK = 'KD-001: Magic System'          # the fixture's key decisions
VG_MARK = 'Narrative Voice'               # the fixture's voice guide


def _template(project_dir, name, title=None):
    """Reset reference/<name> to its template, as init writes it."""
    with open(os.path.join(TEMPLATES, name), encoding='utf-8') as f:
        text = f.read()
    if title is not None:
        text = text.replace('PROJECT_TITLE', title)
    with open(os.path.join(project_dir, 'reference', name), 'w', encoding='utf-8') as f:
        f.write(text)


def _briefs_prompt(project_dir, scene='act1-sc01', **kw):
    from storyforge.prompts import build_scene_prompt_from_briefs
    return build_scene_prompt_from_briefs(scene, project_dir, get_plugin_dir(), **kw)


# --- is_unfilled_template: init writes the title into key-decisions.md ---

def test_key_decisions_template_with_a_title_is_unfilled(project_dir):
    _template(project_dir, 'key-decisions.md', title="The Cartographer's Silence")
    assert is_unfilled_template(os.path.join(project_dir, 'reference', 'key-decisions.md'))


def test_key_decisions_with_a_decision_added_is_filled(project_dir):
    _template(project_dir, 'key-decisions.md', title='Telemachy')
    path = os.path.join(project_dir, 'reference', 'key-decisions.md')
    with open(path, 'a', encoding='utf-8') as f:
        f.write('\n## Reading level\n\nFlesch-Kincaid grade 5 to 7.\n')
    assert not is_unfilled_template(path)


def test_title_placeholder_matches_one_line_only(project_dir):
    _template(project_dir, 'key-decisions.md', title='Telemachy\n\nExtra paragraph')
    assert not is_unfilled_template(os.path.join(project_dir, 'reference', 'key-decisions.md'))


# --- part 1: key decisions reach the drafting prompt ---

@pytest.mark.parametrize('system_context', [False, True])
def test_briefs_prompt_carries_key_decisions(project_dir, system_context):
    prompt = _briefs_prompt(project_dir, system_context=system_context)
    assert '## Key Decisions' in prompt
    assert KD_MARK in prompt
    # before the voice guide, after the brief
    assert prompt.index('## Scene Brief') < prompt.index('## Key Decisions')
    if not system_context:
        assert prompt.index('## Key Decisions') < prompt.index('## Voice Guide')


@pytest.mark.parametrize('system_context', [False, True])
def test_briefs_prompt_leaves_out_template_or_missing_key_decisions(project_dir, system_context):
    _template(project_dir, 'key-decisions.md', title="The Cartographer's Silence")
    prompt = _briefs_prompt(project_dir, system_context=system_context)
    assert '## Key Decisions' not in prompt
    assert 'Consulted by all Storyforge skills' not in prompt
    os.remove(os.path.join(project_dir, 'reference', 'key-decisions.md'))
    assert '## Key Decisions' not in _briefs_prompt(project_dir, system_context=system_context)


@pytest.mark.parametrize('coaching', ['coach', 'strict'])
def test_key_decisions_at_every_coaching_level(project_dir, coaching):
    assert KD_MARK in _briefs_prompt(project_dir, coaching_level=coaching)


def test_legacy_prompt_with_system_context_carries_key_decisions(project_dir):
    from storyforge.prompts import build_scene_prompt
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True, system_context=True)
    assert KD_MARK in prompt


def test_version_rules_in_key_decisions_are_pointed_to_when_drafting(project_dir, monkeypatch):
    # Drafting now carries Key Decisions whole, so rules kept there aren't repeated (B-015)
    from storyforge import prompts_source
    monkeypatch.setattr(prompts_source.source, 'read_rules', lambda pd, cfg: '## Rules\n\nRULE-TEXT')
    monkeypatch.setattr(prompts_source, '_rules_in_key_decisions', lambda pd, cfg: True)
    block = prompts_source.rules_block(project_dir, object())
    assert 'RULE-TEXT' not in block
    assert 'in Key Decisions' in block


def test_write_dry_run_prints_key_decisions(project_dir, capsys, monkeypatch):
    from storyforge import cmd_write
    monkeypatch.setattr(cmd_write, 'detect_project_root', lambda: project_dir)
    try:
        cmd_write.main(['--dry-run', 'act1-sc01'])
    except SystemExit as e:
        assert not e.code
    out = capsys.readouterr()
    text = out.out + out.err
    assert '## Key Decisions' in text and KD_MARK in text


# --- part 3: no template voice guide (or bible) in the scene prompt ---

def test_briefs_prompt_leaves_out_template_voice_guide(project_dir):
    _template(project_dir, 'voice-guide.md')
    prompt = _briefs_prompt(project_dir)
    assert '## Voice Guide' not in prompt
    assert '[Title] -- Voice Guide' not in prompt


def test_briefs_prompt_keeps_a_filled_voice_guide(project_dir):
    prompt = _briefs_prompt(project_dir)
    assert '## Voice Guide' in prompt and VG_MARK in prompt


def test_briefs_prompt_leaves_out_template_character_bible(project_dir):
    _template(project_dir, 'character-bible.md')
    assert '## Character Bible' not in _briefs_prompt(project_dir)


def test_legacy_prompt_inlines_no_template(project_dir):
    from storyforge.prompts import build_scene_prompt
    _template(project_dir, 'voice-guide.md')
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    assert '=== FILE: reference/voice-guide.md ===' not in prompt
    assert '=== FILE: reference/key-decisions.md ===' in prompt
    assert 'Pay special attention to the voice guide' not in prompt
    listed = build_scene_prompt('act1-sc01', project_dir, api_mode=False)
    assert 'reference/voice-guide.md' not in listed


def test_revision_prompt_inlines_no_template_voice_guide(project_dir):
    from storyforge.revision import build_revision_prompt
    _template(project_dir, 'voice-guide.md')
    prompt = build_revision_prompt('prose', 'Tighten', 'act1-sc01', project_dir, api_mode=True)
    assert '=== FILE: reference/voice-guide.md ===' not in prompt


def test_hone_reads_no_template(project_dir):
    from storyforge.hone import _reference_text
    ref = os.path.join(project_dir, 'reference')
    assert VG_MARK in _reference_text(ref, 'voice-guide.md')
    _template(project_dir, 'voice-guide.md')
    assert _reference_text(ref, 'voice-guide.md') == ''
    assert _reference_text(ref, 'missing.md') == ''


def test_evaluate_skips_template_voice_guide_and_says_so(project_dir, capsys):
    from storyforge.cmd_evaluate import _build_assessment_prompt, _resolve_voice_guide
    _template(project_dir, 'voice-guide.md')
    _template(project_dir, 'key-decisions.md', title='X')
    assert _resolve_voice_guide(project_dir) == (None, '')
    out = capsys.readouterr()
    assert "voice-guide.md is still init's template" in out.out + out.err
    prompt, count = _build_assessment_prompt(project_dir, 'eval', 'ts', 'all', 'T', 'g',
                                             False, True)
    assert prompt is None and count == 0


def test_script_package_reads_no_template(project_dir):
    from storyforge.cmd_script_package import _read_optional
    path = os.path.join(project_dir, 'reference', 'voice-guide.md')
    assert VG_MARK in _read_optional(path)
    _template(project_dir, 'voice-guide.md')
    assert _read_optional(path) == ''


def test_recommend_step_leaves_out_template_key_decisions(project_dir, monkeypatch):
    from storyforge import api, git
    seen = []
    monkeypatch.setattr(api, 'invoke_api', lambda prompt, *a, **k: seen.append(prompt) or '')
    monkeypatch.setattr(git, 'commit_and_push', lambda *a, **k: True)
    git._run_recommend_step('evaluation', project_dir, 0)
    assert '=== FILE: reference/key-decisions.md ===' in seen[0]
    _template(project_dir, 'key-decisions.md', title='X')
    git._run_recommend_step('evaluation', project_dir, 0)
    assert '=== FILE: reference/key-decisions.md ===' not in seen[1]


# --- graphic novel: key decisions in the script prompt, no template bibles ---

def test_gn_drafting_prompt_carries_key_decisions(project_dir_gn):
    from storyforge.cmd_write_gn import _build_visual_refs
    from storyforge.prompts_gn import build_drafting_prompt
    path = os.path.join(project_dir_gn, 'reference', 'key-decisions.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# Key Decisions\n\n## Content\n\nNo gore on the page.\n')
    kw = dict(project_dir=project_dir_gn, scene_id='s1', scene_row={}, intent_row={},
              brief_row={}, character_visuals='', location_visuals='',
              voice_profile_text='')
    assert 'No gore on the page.' in build_drafting_prompt(**kw)
    _template(project_dir_gn, 'key-decisions.md', title='X')
    assert '# Key decisions' not in build_drafting_prompt(**kw)
    _template(project_dir_gn, 'character-bible.md')
    assert _build_visual_refs(project_dir_gn)[0] == ''


# --- part 2's helper and write's warning ---

def test_voice_guide_problem(project_dir):
    assert voice_guide_problem(project_dir) == ''
    _template(project_dir, 'voice-guide.md')
    assert voice_guide_problem(project_dir) == "is still init's template"
    with open(os.path.join(project_dir, 'reference', 'voice-guide.md'), 'w') as f:
        f.write('  \n')
    assert voice_guide_problem(project_dir) == 'is empty'
    os.remove(os.path.join(project_dir, 'reference', 'voice-guide.md'))
    assert voice_guide_problem(project_dir) == 'is missing'


def test_write_warns_on_template_voice_guide(project_dir, capsys):
    from storyforge.cmd_write import _check_voice_guide
    _check_voice_guide(project_dir)
    out = capsys.readouterr()
    assert 'WARNING' not in out.out + out.err
    _template(project_dir, 'voice-guide.md')
    _check_voice_guide(project_dir)
    out = capsys.readouterr()
    err = out.out + out.err
    assert "reference/voice-guide.md is still init's template" in err
    assert 'storyforge elaborate --stage voice' in err


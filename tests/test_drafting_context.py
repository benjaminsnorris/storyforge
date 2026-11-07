"""#596: drafting carries the author's key decisions, and no reference doc
still init's template reaches a prompt as the book's own (F-130).

Found drafting the Telemachy pilot: `write`'s scene prompt had no key
decisions (reading level, POV rules, how each hard event is told), and the
non-system-context prompt printed the voice-guide template, `[Title] --
Voice Guide` and all, as the book's voice guide.
"""

import os

import pytest

from storyforge.common import (
    PROJECT_TITLE, ReferenceDocError, get_plugin_dir, is_unfilled_template,
    resolve_voice_guide,
)

TEMPLATES = os.path.join(get_plugin_dir(), 'templates', 'reference')
KD_MARK = 'KD-001: Magic System'          # the fixture's key decisions
VG_MARK = 'Narrative Voice'               # the fixture's voice guide


def _template(project_dir, name, title=None):
    """Reset reference/<name> to its template, as init writes it."""
    with open(os.path.join(TEMPLATES, name), encoding='utf-8') as f:
        text = f.read()
    if title is not None:
        text = text.replace(PROJECT_TITLE, title)
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


def test_reference_text_reads_no_template(project_dir):
    # TD-4: the prompt readers (hone, script-package, revision, evaluate,
    # the recommend step) all read through it
    from storyforge.common import reference_text
    path = os.path.join(project_dir, 'reference', 'voice-guide.md')
    assert VG_MARK in reference_text(path)
    _template(project_dir, 'voice-guide.md')
    assert reference_text(path) == ''
    assert reference_text(os.path.join(project_dir, 'reference', 'missing.md')) == ''


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


# --- one voice guide resolver (CR-1/TD-1/TD-2) ---

def _vg(project_dir):
    return os.path.join(project_dir, 'reference', 'voice-guide.md')


def _write_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = 'wb' if isinstance(data, bytes) else 'w'
    with open(path, mode) as f:
        f.write(data)


def _yaml_voice_path(project_dir, rel):
    path = os.path.join(project_dir, 'storyforge.yaml')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text + f'\nreference:\n  voice_guide: {rel}\n')


def test_resolver_kinds(project_dir):
    assert resolve_voice_guide(project_dir).kind == 'ok'
    _template(project_dir, 'voice-guide.md')
    v = resolve_voice_guide(project_dir)
    assert (v.kind, v.detail) == ('template', "reference/voice-guide.md is still init's template")
    _write_file(_vg(project_dir), '  \n')
    assert resolve_voice_guide(project_dir).kind == 'empty'
    _write_file(_vg(project_dir), b'\xff\xfe bad bytes')
    v = resolve_voice_guide(project_dir)
    assert v.kind == 'unreadable' and "can't read reference/voice-guide.md" in v.detail
    os.remove(_vg(project_dir))
    assert resolve_voice_guide(project_dir).kind == 'missing'


def test_resolver_honours_the_yaml_path_and_passes_a_template(project_dir):
    # status, write and the prompt follow the same file (CR-1)
    _template(project_dir, 'voice-guide.md')
    _write_file(os.path.join(project_dir, 'docs', 'voice.md'), '# Voice\n\nTerse.\n')
    _yaml_voice_path(project_dir, 'docs/voice.md')
    v = resolve_voice_guide(project_dir)
    assert (v.kind, v.path, v.text) == ('ok', 'docs/voice.md', '# Voice\n\nTerse.')
    assert '## Voice Guide\n\n# Voice\n\nTerse.' in _briefs_prompt(project_dir)


def test_persistent_prompt_counts_only_for_the_prompt_that_reads_it(project_dir):
    os.remove(_vg(project_dir))
    _write_file(os.path.join(project_dir, 'reference', 'persistent-prompt.md'), 'Old voice.\n')
    assert resolve_voice_guide(project_dir).kind == 'unread'
    v = resolve_voice_guide(project_dir, briefs=False)
    assert (v.kind, v.path) == ('ok', 'reference/persistent-prompt.md')


def test_evaluate_moves_past_a_template_to_the_next_candidate(project_dir, capsys):
    # T-3: a template is passed over and said; the later file is used
    from storyforge.cmd_evaluate import _resolve_voice_guide
    _template(project_dir, 'voice-guide.md')
    _write_file(os.path.join(project_dir, 'reference', 'persistent-prompt.md'), 'Old voice.\n')
    path, text = _resolve_voice_guide(project_dir)
    assert path.endswith('reference/persistent-prompt.md') and text == 'Old voice.'
    out = capsys.readouterr()
    assert "reference/voice-guide.md is still init's template; left out" in out.out + out.err


# --- T-1 / SF-1: an unreadable voice guide or key decisions fails loudly ---

BAD = b'\xff\xfe not utf-8'


@pytest.mark.parametrize('name', ['voice-guide.md', 'key-decisions.md'])
@pytest.mark.parametrize('system_context', [False, True])
def test_unreadable_doc_raises_from_the_briefs_prompt(project_dir, name, system_context):
    _write_file(os.path.join(project_dir, 'reference', name), BAD)
    if name == 'voice-guide.md' and system_context:
        # the system context carries the voice guide; write stops before this
        _briefs_prompt(project_dir, system_context=True)
        return
    with pytest.raises(ReferenceDocError, match=name):
        _briefs_prompt(project_dir, system_context=system_context)


@pytest.mark.parametrize('name', ['voice-guide.md', 'key-decisions.md'])
@pytest.mark.parametrize('system_context', [False, True])
def test_unreadable_doc_raises_from_the_legacy_prompt(project_dir, name, system_context):
    from storyforge.prompts import build_scene_prompt
    _write_file(os.path.join(project_dir, 'reference', name), BAD)
    with pytest.raises(ReferenceDocError, match=name):
        build_scene_prompt('act1-sc01', project_dir, api_mode=True,
                           system_context=system_context)


@pytest.mark.parametrize('name', ['voice-guide.md', 'key-decisions.md'])
@pytest.mark.parametrize('dry_run', [False, True])
@pytest.mark.parametrize('coaching', ['full', 'coach'])
def test_write_stops_on_an_unreadable_doc(project_dir, capsys, name, dry_run, coaching):
    code, text = _check(project_dir, capsys, coaching=coaching, dry_run=dry_run,
                        setup=lambda: _write_file(os.path.join(project_dir, 'reference', name), BAD))
    assert code == 1
    assert f"ERROR: can't read reference/{name}" in text


def test_dispatcher_turns_an_unreadable_doc_into_exit_1(project_dir, monkeypatch, capsys):
    from storyforge import __main__ as dispatch
    from storyforge.cmd_script_package import _read_optional
    _write_file(_vg(project_dir), BAD)

    class Module:
        @staticmethod
        def main(argv):
            _read_optional(_vg(project_dir))
    monkeypatch.setattr(dispatch.sys, 'argv', ['storyforge', 'script-package'])
    with pytest.raises(SystemExit) as e:
        dispatch._dispatch(Module)
    assert e.value.code == 1
    assert "ERROR: can't read" in capsys.readouterr().err


def test_script_package_and_evaluate_fail_on_unreadable(project_dir, capsys):
    from storyforge.cmd_evaluate import _resolve_voice_guide
    from storyforge.cmd_script_package import _read_optional
    _write_file(_vg(project_dir), BAD)
    with pytest.raises(ReferenceDocError, match='voice-guide.md'):
        _read_optional(_vg(project_dir))
    with pytest.raises(SystemExit):
        _resolve_voice_guide(project_dir)
    out = capsys.readouterr()
    assert "ERROR: can't read reference/voice-guide.md" in out.out + out.err


# --- T-2 / SF-2: write's voice guide verdicts ---

def _check(project_dir, capsys, briefs=True, coaching='full', dry_run=False, setup=None):
    from storyforge.cmd_write import _check_reference_docs
    if setup:
        setup()
    code = None
    try:
        _check_reference_docs(project_dir, briefs, coaching, dry_run)
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    return code, out.out + out.err


def test_write_with_a_voice_guide_goes_on(project_dir, capsys):
    code, text = _check(project_dir, capsys)
    assert code is None and 'WARNING' not in text
    assert 'Voice guide: reference/voice-guide.md' in text


def _only_persistent_prompt(pd):
    os.remove(_vg(pd))
    _write_file(os.path.join(pd, 'reference', 'persistent-prompt.md'), 'Old.\n')


@pytest.mark.parametrize('setup, detail', [
    (lambda pd: _template(pd, 'voice-guide.md'), "reference/voice-guide.md is still init's template"),
    (lambda pd: _write_file(_vg(pd), '\n'), 'reference/voice-guide.md is empty'),
    (lambda pd: os.remove(_vg(pd)), 'reference/voice-guide.md is missing'),
    (_only_persistent_prompt,
     'only reference/persistent-prompt.md, which the brief-based drafting prompt does not read'),
])
def test_write_refuses_to_draft_without_a_voice_guide(project_dir, capsys, setup, detail):
    setup(project_dir)
    code, text = _check(project_dir, capsys)
    assert code == 1
    assert 'ERROR' in text and detail in text and 'Nothing was drafted' in text
    # a dry run and coach/strict say it and go on
    code, text = _check(project_dir, capsys, dry_run=True)
    assert code is None and 'WARNING' in text and detail in text
    assert 'a real run stops here' in text
    code, text = _check(project_dir, capsys, coaching='coach')
    assert code is None and 'coach coaching writes no prose' in text


def test_write_without_briefs_reads_persistent_prompt(project_dir, capsys):
    _only_persistent_prompt(project_dir)
    code, text = _check(project_dir, capsys, briefs=False)
    assert code is None and 'Voice guide: reference/persistent-prompt.md' in text


def test_write_says_a_passed_over_template(project_dir, capsys):
    # the fixture's artifacts.voice_guide.path (reference/voice-guide.md) is
    # the template, so the older reference.voice_guide key's file is used
    _template(project_dir, 'voice-guide.md')
    _write_file(os.path.join(project_dir, 'docs', 'voice.md'), 'Terse.\n')
    _yaml_voice_path(project_dir, 'docs/voice.md')
    code, text = _check(project_dir, capsys)
    assert code is None
    assert "WARNING: reference/voice-guide.md is still init's template; passed over" in text
    assert 'Voice guide: docs/voice.md' in text


def test_read_artifact_field(project_dir, tmp_path):
    from storyforge.common import read_artifact_field
    assert read_artifact_field(project_dir, 'voice_guide', 'path') == 'reference/voice-guide.md'
    assert read_artifact_field(project_dir, 'voice_guide', 'nope') == ''
    assert read_artifact_field(project_dir, 'no_such_artifact', 'path') == ''
    assert read_artifact_field(str(tmp_path), 'voice_guide', 'path') == ''


# --- SF-4: key decisions left out are said ---

@pytest.mark.parametrize('setup, detail', [
    (lambda pd: _template(pd, 'key-decisions.md', title='T'),
     "reference/key-decisions.md is still init's template"),
    (lambda pd: os.remove(os.path.join(pd, 'reference', 'key-decisions.md')),
     'reference/key-decisions.md is missing'),
])
def test_write_and_revise_note_missing_key_decisions(project_dir, capsys, setup, detail):
    from storyforge.cmd_revise import _note_reference_docs
    setup(project_dir)
    code, text = _check(project_dir, capsys)
    assert code is None
    assert f'NOTE: {detail}, so the drafting prompts carry no key decisions' in text
    _note_reference_docs(project_dir)
    out = capsys.readouterr()
    assert (f'NOTE: {detail}, so the prose passes and redrafts carry no key decisions'
            in out.out + out.err)


def test_rules_are_given_in_full_when_key_decisions_are_left_out(project_dir, monkeypatch):
    # the pointer would send the model to a Key Decisions the prompt doesn't have
    from storyforge import prompts_source
    monkeypatch.setattr(prompts_source.source, 'read_rules', lambda pd, cfg: 'RULE-TEXT')
    monkeypatch.setattr(prompts_source.source, 'resolve', lambda pd, rel: os.path.join(pd, rel))

    class Cfg:
        rules = 'reference/key-decisions.md'
    assert 'in Key Decisions' in prompts_source.rules_block(project_dir, Cfg())
    _template(project_dir, 'key-decisions.md', title='T')
    block = prompts_source.rules_block(project_dir, Cfg())
    assert 'RULE-TEXT' in block and 'in Key Decisions' not in block


# --- SF-3: revise without a voice guide says so, in the prompt and to the author ---

@pytest.mark.parametrize('api_mode', [True, False])
def test_revision_prompt_without_a_voice_guide_says_where_voice_comes_from(project_dir, api_mode):
    from storyforge.revision import build_revision_prompt
    prompt = build_revision_prompt('prose', 'Tighten', 'act1-sc01', project_dir, api_mode=api_mode)
    assert '## No Voice Guide' not in prompt
    _template(project_dir, 'voice-guide.md')
    prompt = build_revision_prompt('prose', 'Tighten', 'act1-sc01', project_dir, api_mode=api_mode)
    assert '## No Voice Guide' in prompt
    assert "take the voice from the book's existing scenes" in prompt
    assert '`reference/voice-guide.md`' not in prompt


def test_revise_warns_without_a_voice_guide(project_dir, capsys):
    from storyforge.cmd_revise import _note_reference_docs
    _note_reference_docs(project_dir)
    out = capsys.readouterr()
    assert 'WARNING' not in out.out + out.err
    _template(project_dir, 'voice-guide.md')
    _note_reference_docs(project_dir)
    out = capsys.readouterr()
    assert ("WARNING: reference/voice-guide.md is still init's template: the revision "
            'prompts have no voice guide') in out.out + out.err


def test_shared_context_follows_the_resolved_voice_guide(project_dir):
    from storyforge.common import _shared_context_cache, build_shared_context
    _template(project_dir, 'voice-guide.md')
    _write_file(os.path.join(project_dir, 'docs', 'voice.md'), '# Voice\n\nTerse.\n')
    _yaml_voice_path(project_dir, 'docs/voice.md')
    _shared_context_cache.clear()
    try:
        text = '\n'.join(b['text'] for b in build_shared_context(project_dir))
    finally:
        _shared_context_cache.clear()
    assert '=== Voice Guide ===\n\n# Voice\n\nTerse.' in text


# --- T-4 / T-5: is_unfilled_template edge cases ---

def test_partly_filled_key_decisions_is_filled(project_dir):
    _template(project_dir, 'key-decisions.md', title='Telemachy')
    path = os.path.join(project_dir, 'reference', 'key-decisions.md')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    _write_file(path, text.replace('narrator_pov: allowed', 'narrator_pov: off'))
    assert not is_unfilled_template(path)


@pytest.mark.parametrize('encode', [
    lambda t: t.replace('\n', '\r\n').encode('utf-8'),
    lambda t: b'\xef\xbb\xbf' + t.encode('utf-8'),
    lambda t: b'\xef\xbb\xbf' + t.replace('\n', '\r\n').encode('utf-8'),
])
def test_titled_template_with_crlf_or_bom_is_unfilled(project_dir, encode):
    with open(os.path.join(TEMPLATES, 'key-decisions.md'), encoding='utf-8') as f:
        text = f.read().replace(PROJECT_TITLE, 'Telemachy')
    path = os.path.join(project_dir, 'reference', 'key-decisions.md')
    _write_file(path, encode(text))
    assert is_unfilled_template(path)
    assert '## Key Decisions' not in _briefs_prompt(project_dir)


def test_reference_text_drops_a_bom(project_dir):
    from storyforge.common import reference_text
    path = os.path.join(project_dir, 'reference', 'key-decisions.md')
    _write_file(path, b'\xef\xbb\xbf# KD\n\nOne.\n')
    assert reference_text(path) == '# KD\n\nOne.'


# --- TD-9: every prompt with the version rules carries Key Decisions ---

def test_rules_block_callers_carry_key_decisions():
    """rules_block points at Key Decisions, so every prompt built from a
    section that calls it must carry them: the elaborate stages through
    `_existing_refs`, drafting through its `## Key Decisions`."""
    import re
    lib = os.path.join(get_plugin_dir(), 'scripts', 'lib', 'python', 'storyforge')
    sources = {}
    for name in os.listdir(lib):
        if name.endswith('.py'):
            with open(os.path.join(lib, name), encoding='utf-8') as f:
                sources[name] = f.read()
    callers = {n for n, t in sources.items() if re.search(r'(?<!def )\brules_block\(', t)}
    assert callers == {'prompts_source.py'}
    # the prompts_source sections that call it, and who builds a prompt from each
    calling = set(re.findall(
        r'def (\w+_section)\(.*?(?=\ndef |\Z)', sources['prompts_source.py'], re.S))
    calling = {fn for fn in calling
               if 'rules_block(' in re.search(rf'def {fn}\(.*?(?=\ndef |\Z)',
                                              sources['prompts_source.py'], re.S).group(0)}
    assert calling == {'spine_section', 'architecture_section', 'map_section',
                       'briefs_section', 'drafting_section'}
    builders = {n for n, t in sources.items() if n != 'prompts_source.py'
                and any(re.search(rf'\b{fn}\(', t) for fn in calling)}
    assert builders == {'prompts_elaborate.py', 'prompts.py'}
    assert "('key-decisions.md', 'Key Decisions', False)" in sources['prompts_elaborate.py']
    assert "reference_doc(project_dir, 'key-decisions.md')" in sources['prompts.py']


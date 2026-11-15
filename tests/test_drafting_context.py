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
)
from storyforge.voice_book import resolve as resolve_voice

TEMPLATES = os.path.join(get_plugin_dir(), 'templates', 'reference')
KD_MARK = 'KD-001: Magic System'          # the fixture's key decisions
VG_MARK = 'Measures before it feels'      # the fixture's reference/voice/book.md
ANCHOR_MARK = 'The village was not there'  # its anchor


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
    # before the voice, after the brief
    assert prompt.index('## Scene Brief') < prompt.index('## Key Decisions')
    if not system_context:
        assert prompt.index('## Key Decisions') < prompt.index('## The Voice')


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



# --- the voice (reference/voice/) in the scene prompts ---

VOICE_TEMPLATES = os.path.join(get_plugin_dir(), 'templates')


def _book(project_dir):
    return os.path.join(project_dir, 'reference', 'voice', 'book.md')


def _anchors(project_dir):
    return os.path.join(project_dir, 'reference', 'voice', 'anchors')


def _template_book(project_dir):
    """Reset reference/voice/book.md to init's template."""
    with open(os.path.join(VOICE_TEMPLATES, 'reference', 'voice', 'book.md'),
              encoding='utf-8') as f:
        _write_file(_book(project_dir), f.read())


def _no_anchors(project_dir):
    import shutil
    shutil.rmtree(_anchors(project_dir))


def test_briefs_prompt_leaves_out_a_template_voice(project_dir):
    _template_book(project_dir)
    prompt = _briefs_prompt(project_dir)
    assert '## The Voice' not in prompt
    assert 'What the voice does, said by quoting the anchors' not in prompt


def test_briefs_prompt_carries_the_voice_never_its_checks(project_dir):
    prompt = _briefs_prompt(project_dir)
    assert '## The Voice' in prompt and VG_MARK in prompt and ANCHOR_MARK in prompt
    assert 'kind: quiet, realization; POV: Dorren Hayle' in prompt
    assert 'Her heart pounded in her chest' not in prompt  # checks.md


def test_briefs_prompt_leaves_out_template_character_bible(project_dir):
    _template(project_dir, 'character-bible.md')
    assert '## Character Bible' not in _briefs_prompt(project_dir)


def test_legacy_prompt_inlines_the_voice_and_lists_no_voice_file(project_dir):
    from storyforge.prompts import build_scene_prompt
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    assert VG_MARK in prompt and ANCHOR_MARK in prompt
    assert 'reference/voice/' not in prompt.split('## The Voice')[0]
    assert '=== FILE: reference/key-decisions.md ===' in prompt
    listed = build_scene_prompt('act1-sc01', project_dir, api_mode=False)
    assert 'reference/voice/checks.md' not in listed
    assert 'Her heart pounded in her chest' not in listed + prompt


def test_legacy_prompt_lists_no_old_voice_file(project_dir):
    from storyforge.prompts import list_reference_files
    _write_file(os.path.join(project_dir, 'reference', 'voice-guide.md'), 'Old guide.\n')
    _write_file(os.path.join(project_dir, 'reference', 'exemplars', 'dorren.md'), 'Old.\n')
    listed = list_reference_files(project_dir)
    assert not [f for f in listed if 'voice' in f or 'exemplars' in f]


def test_revision_prompt_carries_the_voice_never_its_checks(project_dir):
    from storyforge.revision import build_revision_prompt
    prompt = build_revision_prompt('prose', 'Tighten', 'act1-sc01', project_dir, api_mode=True)
    assert VG_MARK in prompt and 'Her heart pounded in her chest' not in prompt
    _template_book(project_dir)
    prompt = build_revision_prompt('prose', 'Tighten', 'act1-sc01', project_dir, api_mode=True)
    assert VG_MARK not in prompt


def test_reference_text_reads_no_template(project_dir):
    # TD-4: the prompt readers (hone, script-package, revision, evaluate,
    # the recommend step) all read through it
    from storyforge.common import reference_text
    path = os.path.join(project_dir, 'reference', 'key-decisions.md')
    assert KD_MARK in reference_text(path)
    _template(project_dir, 'key-decisions.md', title='X')
    assert reference_text(path) == ''
    assert reference_text(os.path.join(project_dir, 'reference', 'missing.md')) == ''


def test_evaluate_without_a_voice_says_so(project_dir, capsys):
    from storyforge.cmd_evaluate import _build_assessment_prompt, _resolve_voice
    _template_book(project_dir)
    _template(project_dir, 'key-decisions.md', title='X')
    assert _resolve_voice(project_dir) == (None, '')
    out = capsys.readouterr()
    assert "reference/voice/book.md is still init's template" in out.out + out.err
    prompt, count = _build_assessment_prompt(project_dir, 'eval', 'ts', 'all', 'T', 'g',
                                             False, True)
    assert prompt is None and count == 0


def test_evaluate_assessment_carries_the_voice(project_dir):
    from storyforge.cmd_evaluate import _build_assessment_prompt, _resolve_voice
    path, text = _resolve_voice(project_dir)
    assert path == 'reference/voice' and VG_MARK in text
    prompt, _count = _build_assessment_prompt(project_dir, 'eval', 'ts', 'all', 'T', 'g',
                                              False, True)
    assert '## Voice Alignment' in prompt and VG_MARK in prompt


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



# --- one voice resolver (`voice_book.resolve`) ---

def _write_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = 'wb' if isinstance(data, bytes) else 'w'
    with open(path, mode) as f:
        f.write(data)


def test_resolver_kinds(project_dir):
    v = resolve_voice(project_dir)
    assert (v.kind, v.path) == ('ok', 'reference/voice') and VG_MARK in v.text
    _template_book(project_dir)
    v = resolve_voice(project_dir)
    assert (v.kind, v.detail) == ('template', "reference/voice/book.md is still init's template")
    _write_file(_book(project_dir), '  \n')
    assert resolve_voice(project_dir).kind == 'empty'
    _write_file(_book(project_dir), b'\xff\xfe bad bytes')
    v = resolve_voice(project_dir)
    assert v.kind == 'unreadable' and "can't read reference/voice/book.md" in v.detail
    os.remove(_book(project_dir))
    _no_anchors(project_dir)
    assert resolve_voice(project_dir).kind == 'missing'


def test_resolver_needs_an_anchor_beside_book_md(project_dir):
    _no_anchors(project_dir)
    v = resolve_voice(project_dir)
    assert (v.kind, v.detail) == ('empty', 'reference/voice/anchors/ holds no anchor passage')


def test_old_voice_files_are_not_read(project_dir):
    import shutil
    shutil.rmtree(os.path.join(project_dir, 'reference', 'voice'))
    _write_file(os.path.join(project_dir, 'reference', 'voice-guide.md'), '# Voice\n\nOld.\n')
    _write_file(os.path.join(project_dir, 'reference', 'persistent-prompt.md'), 'Old.\n')
    assert resolve_voice(project_dir).kind == 'missing'
    assert '# Voice\n\nOld.' not in _briefs_prompt(project_dir)


# --- T-1 / SF-1: an unreadable voice or key decisions fails loudly ---

BAD = b'\xff\xfe not utf-8'


def _bad(project_dir, name):
    rel = 'voice/book.md' if name == 'book.md' else name
    _write_file(os.path.join(project_dir, 'reference', rel), BAD)


@pytest.mark.parametrize('name', ['book.md', 'key-decisions.md'])
@pytest.mark.parametrize('system_context', [False, True])
def test_unreadable_doc_raises_from_the_briefs_prompt(project_dir, name, system_context):
    _bad(project_dir, name)
    if name == 'book.md' and system_context:
        # the system context carries the voice; write stops before this
        _briefs_prompt(project_dir, system_context=True)
        return
    with pytest.raises(ReferenceDocError, match=name):
        _briefs_prompt(project_dir, system_context=system_context)


@pytest.mark.parametrize('name', ['book.md', 'key-decisions.md'])
def test_unreadable_doc_raises_from_the_legacy_prompt(project_dir, name):
    from storyforge.prompts import build_scene_prompt
    _bad(project_dir, name)
    with pytest.raises(ReferenceDocError, match=name):
        build_scene_prompt('act1-sc01', project_dir, api_mode=True)


def test_unreadable_anchor_raises(project_dir):
    _write_file(os.path.join(_anchors(project_dir), 'bad.md'), BAD)
    with pytest.raises(ReferenceDocError, match='bad.md'):
        _briefs_prompt(project_dir)


@pytest.mark.parametrize('name', ['book.md', 'key-decisions.md'])
@pytest.mark.parametrize('dry_run', [False, True])
@pytest.mark.parametrize('coaching', ['full', 'coach'])
def test_write_stops_on_an_unreadable_doc(project_dir, capsys, name, dry_run, coaching):
    code, text = _check(project_dir, capsys, coaching=coaching, dry_run=dry_run,
                        setup=lambda: _bad(project_dir, name))
    assert code == 1
    assert "ERROR: can't read reference/" in text and name in text


def test_dispatcher_turns_an_unreadable_doc_into_exit_1(project_dir, monkeypatch, capsys):
    from storyforge import __main__ as dispatch
    from storyforge.cmd_script_package import _read_optional
    path = os.path.join(project_dir, 'reference', 'key-decisions.md')
    _write_file(path, BAD)

    class Module:
        @staticmethod
        def main(argv):
            _read_optional(path)
    monkeypatch.setattr(dispatch.sys, 'argv', ['storyforge', 'script-package'])
    with pytest.raises(SystemExit) as e:
        dispatch._dispatch(Module)
    assert e.value.code == 1
    assert "ERROR: can't read" in capsys.readouterr().err


def test_evaluate_fails_on_an_unreadable_voice(project_dir, capsys):
    from storyforge.cmd_evaluate import _resolve_voice
    _bad(project_dir, 'book.md')
    with pytest.raises(SystemExit):
        _resolve_voice(project_dir)
    out = capsys.readouterr()
    assert "ERROR: can't read reference/voice/book.md" in out.out + out.err


# --- T-2 / SF-2: write's voice verdicts ---

def _check(project_dir, capsys, briefs=True, coaching='full', dry_run=False, setup=None):
    from storyforge.cmd_write import _check_reference_docs
    if setup:
        setup()
    code = None
    try:
        _check_reference_docs(project_dir, coaching, dry_run)
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    return code, out.out + out.err


def test_write_with_a_voice_goes_on(project_dir, capsys):
    code, text = _check(project_dir, capsys)
    assert code is None and 'WARNING' not in text and 'NOTE: reference/' not in text
    assert 'Voice: reference/voice' in text


def test_write_notes_old_voice_files(project_dir, capsys):
    _write_file(os.path.join(project_dir, 'reference', 'voice-guide.md'), 'Old.\n')
    _write_file(os.path.join(project_dir, 'reference', 'voice-profile.csv'), 'character\n')
    code, text = _check(project_dir, capsys)
    assert code is None
    assert ('NOTE: reference/voice-guide.md, reference/voice-profile.csv are no longer read'
            in text)
    assert os.path.isfile(os.path.join(project_dir, 'reference', 'voice-guide.md'))


@pytest.mark.parametrize('setup, detail', [
    (_template_book, "reference/voice/book.md is still init's template"),
    (lambda pd: _write_file(_book(pd), '\n'), 'reference/voice/book.md is missing or empty'),
    (_no_anchors, 'reference/voice/anchors/ holds no anchor passage'),
    (lambda pd: (os.remove(_book(pd)), _no_anchors(pd)), 'reference/voice/ has no voice yet'),
])
def test_write_refuses_to_draft_without_a_voice(project_dir, capsys, setup, detail):
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


def test_read_artifact_field(project_dir, tmp_path):
    from storyforge.common import read_artifact_field
    assert read_artifact_field(project_dir, 'character_bible', 'path') == \
        'reference/character-bible.md'
    assert read_artifact_field(project_dir, 'character_bible', 'nope') == ''
    assert read_artifact_field(project_dir, 'no_such_artifact', 'path') == ''
    assert read_artifact_field(str(tmp_path), 'character_bible', 'path') == ''


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


# --- SF-3: revise without a voice says so, in the prompt and to the author ---

@pytest.mark.parametrize('api_mode', [True, False])
def test_revision_prompt_without_a_voice_says_where_voice_comes_from(project_dir, api_mode):
    from storyforge.revision import build_revision_prompt
    prompt = build_revision_prompt('prose', 'Tighten', 'act1-sc01', project_dir, api_mode=api_mode)
    assert '## No Voice Yet' not in prompt
    _template_book(project_dir)
    prompt = build_revision_prompt('prose', 'Tighten', 'act1-sc01', project_dir, api_mode=api_mode)
    assert '## No Voice Yet' in prompt
    assert "take it from the book's existing scenes" in prompt
    assert 'reference/voice/book.md`' not in prompt


def test_revise_warns_without_a_voice(project_dir, capsys):
    from storyforge.cmd_revise import _note_reference_docs
    _note_reference_docs(project_dir)
    out = capsys.readouterr()
    assert 'WARNING' not in out.out + out.err
    _template_book(project_dir)
    _note_reference_docs(project_dir)
    out = capsys.readouterr()
    assert ("WARNING: reference/voice/book.md is still init's template: the revision "
            'prompts have no voice') in out.out + out.err


def test_shared_context_carries_the_voice_never_its_checks(project_dir):
    from storyforge.common import _shared_context_cache, build_shared_context
    _shared_context_cache.clear()
    try:
        text = '\n'.join(b['text'] for b in build_shared_context(project_dir))
    finally:
        _shared_context_cache.clear()
    assert '=== The Voice ===' in text and VG_MARK in text and ANCHOR_MARK in text
    assert 'Her heart pounded in her chest' not in text


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
    assert builders == {'prompts_elaborate.py', 'prompts.py', 'session.py'}
    assert "('key-decisions.md', 'Key Decisions', False)" in sources['prompts_elaborate.py']
    assert "reference_doc(project_dir, 'key-decisions.md')" in sources['prompts.py']
    assert "reference_doc(project_dir, 'key-decisions.md')" in sources['session.py']


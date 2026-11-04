"""The elaborate stage prompts keep the reference docs the shared system
context doesn't carry.

`storyforge elaborate` always builds its prompts with `system_context=True`,
and a prompt built that way used to drop every reference doc, on the
grounds that the system context had them. It had the bibles and the voice
guide, but not the story summary, the story architecture or the key
decisions, so no CLI stage ever saw them: the architecture stage didn't see
the architecture the spine wrote, and no stage saw the author's decisions
(found on the Gawain novel, G-012)."""

import os
import shutil

import pytest

from storyforge import common, prompts_elaborate as pe

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOCS = {
    'story-summary.md': '# Story summary\n\n## Logline\n\nSUMMARY-MARKER logline.\n',
    'story-architecture.md': '# Story Architecture\n\nARCHITECTURE-MARKER premise.\n',
    'key-decisions.md': '# Key Decisions\n\nDECISIONS-MARKER: the lady is never a POV.\n',
    'character-bible.md': '# Character Bible\n\nBIBLE-MARKER Gawain.\n',
}

BUILDERS = {
    'spine': lambda p, sc: pe.build_spine_prompt(p, PLUGIN, 'seed', system_context=sc),
    'architecture': lambda p, sc: pe.build_architecture_prompt(p, PLUGIN, system_context=sc),
    'map': lambda p, sc: pe.build_map_prompt(p, PLUGIN, system_context=sc),
    'briefs': lambda p, sc: pe.build_briefs_prompt(p, PLUGIN, system_context=sc),
    'voice': lambda p, sc: pe.build_voice_prompt(p, PLUGIN, system_context=sc),
}


@pytest.fixture(autouse=True)
def _fresh_context():
    common.clear_shared_context_cache()
    yield
    common.clear_shared_context_cache()


@pytest.fixture
def project(project_dir):
    for name, text in DOCS.items():
        with open(os.path.join(project_dir, 'reference', name), 'w', encoding='utf-8') as f:
            f.write(text)
    return project_dir


@pytest.mark.parametrize('stage', sorted(BUILDERS))
def test_system_context_prompt_keeps_summary_architecture_and_decisions(project, stage):
    prompt = BUILDERS[stage](project, True)
    for marker in ('SUMMARY-MARKER', 'ARCHITECTURE-MARKER', 'DECISIONS-MARKER'):
        assert marker in prompt, f'{stage} prompt lost {marker}'


@pytest.mark.parametrize('stage', sorted(BUILDERS))
def test_system_context_prompt_leaves_shared_docs_to_the_system(project, stage):
    """The character bible is in the shared context; the prompt doesn't repeat it."""
    shared = ''.join(b['text'] for b in common.build_shared_context(project, 'claude-opus-5-5'))
    assert 'BIBLE-MARKER' in shared
    assert 'BIBLE-MARKER' not in BUILDERS[stage](project, True)


@pytest.mark.parametrize('stage', sorted(BUILDERS))
def test_prompt_without_system_context_carries_every_doc(project, stage):
    prompt = BUILDERS[stage](project, False)
    for marker in ('SUMMARY-MARKER', 'ARCHITECTURE-MARKER', 'DECISIONS-MARKER', 'BIBLE-MARKER'):
        assert marker in prompt


def test_template_docs_are_skipped(project):
    """A doc still holding init's template reads as no doc (F-130)."""
    for name in ('story-summary.md', 'key-decisions.md'):
        shutil.copy(os.path.join(PLUGIN, 'templates', 'reference', name),
                    os.path.join(project, 'reference', name))
    refs = pe._existing_refs(project, shared=True)
    assert 'Story Summary' not in refs and 'Key Decisions' not in refs
    assert 'ARCHITECTURE-MARKER' in refs


def test_map_prompt_asks_for_summary_part_and_target_words(project):
    """G-020: the map didn't ask for these, so a new novel's mapped scenes had
    no summary (the L5 floor fails) and no part or planned length."""
    prompt = pe.build_map_prompt(project, PLUGIN, system_context=True)
    assert ('id|seq|title|summary|act|part|pov|location|timeline_day|time_mode|'
            'time_of_day|duration|target_words|status') in prompt

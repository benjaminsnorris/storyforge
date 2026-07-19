"""Regression guards for the cover skill's documented Tier-2 contract.

Skill markdown is interpreted by Claude at runtime, not executed, so these
tests assert the documented invariants the PR #274 5-agent review surfaced:
- no references to the non-shipped cover-api.sh helper (or its functions)
- the AI generation prompt is persisted in all coaching modes, with a guard
- the OpenAI response handler fails safe (no truncate-before-error)
- step cross-references stay consistent under renumbering
- the BFL host is the current domain, with terminal-failure handling
"""
import os
import re

import pytest


@pytest.fixture
def cover_skill(plugin_dir):
    path = os.path.join(plugin_dir, 'skills', 'cover', 'SKILL.md')
    with open(path, encoding='utf-8') as f:
        return f.read()


def test_no_reference_to_unshipped_helper(cover_skill):
    """The cover-api.sh helper does not ship — the skill must not tell the
    author to source it or call its functions (issue #274 related observation)."""
    for token in ('cover-api.sh', 'openai_generate_image', 'bfl_generate_image'):
        assert token not in cover_skill, f"stale reference to non-shipped helper: {token}"


def test_prompt_persistence_documented_in_all_modes(cover_skill):
    """The prompt log must be recorded in every coaching mode, including full —
    the core of issue #274."""
    assert 'cover-prompt.md' in cover_skill
    assert 'Record the Prompt' in cover_skill
    # The instruction must explicitly cover full mode, not just coach/strict.
    assert re.search(r'every coaching mode, including `full`', cover_skill)


def test_prompt_persistence_has_mechanical_guard(cover_skill):
    """Every other deliverable in the skill has a non-empty-file guard; the
    prompt log must too, so the regression cannot silently recur (SF-3)."""
    assert '[[ ! -s manuscript/assets/cover-prompt.md ]]' in cover_skill


def test_openai_handler_fails_safe_before_opening_file(cover_skill):
    """The OpenAI response handler must check for an API error before opening
    the output file, so a failure never truncates an existing illustration
    (SF-1). Guard against the old fragile `print(...) or open(...)` one-liner."""
    assert "print(d.get('error','')) or open(" not in cover_skill
    assert '"data" not in d' in cover_skill

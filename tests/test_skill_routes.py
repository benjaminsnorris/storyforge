"""Every skill a SKILL.md tells the agent to invoke exists. forge routed to
`scenes`, `recommend`, `review` and `plan-revision` skills that had been
folded into other skills or commands."""

import re

from conftest import PLUGIN_DIR

SKILLS_DIR = PLUGIN_DIR / 'skills'


def test_every_named_skill_exists():
    existing = {p.name for p in SKILLS_DIR.iterdir() if (p / 'SKILL.md').is_file()}
    missing = []
    for skill_md in SKILLS_DIR.glob('*/SKILL.md'):
        for name in re.findall(r'`([a-z][a-z-]*)` skill', skill_md.read_text(encoding='utf-8')):
            if name not in existing:
                missing.append(f'{skill_md.parent.name}: {name}')
    assert missing == []


def test_forge_routes_voice_and_check_in_every_phase():
    """#601 review (CR-2/TD-6): the voice and gate-check routes sat inside the
    block forge reads only in an elaboration phase, and a successful briefs
    stage sets `phase: drafting`, so forge never reached them. They belong in
    Step 1, before that block."""
    text = (SKILLS_DIR / 'forge' / 'SKILL.md').read_text(encoding='utf-8')
    step2 = text.index('## Step 2')
    for route in ('**`next.stage` is `check`**', '**`next.stage` is `voice`**'):
        assert route in text and text.index(route) < step2, route
    # a direct "draft" request and the write prerequisite check the voice
    # blocker, not only that voice-guide.md exists (a template always does)
    assert text.count('no `voice` blocker') >= 3


def test_status_stages_named_in_docs():
    from typing import get_args

    from storyforge.status import Stage
    docs = (PLUGIN_DIR / 'docs' / 'agent-reference.md').read_text(encoding='utf-8')
    assert 'Stages: spine / architecture / voice /' in docs
    assert {'voice', 'check'} <= set(get_args(Stage))


def test_skill_commits_stage_only_the_project():
    """#520 review (C-A): a bare `git add -A` stages the whole work tree, so
    in a repo of several books (`projects/<book>/`) a skill's commit took a
    sibling book's edits. `init` (a new repo of its own) and
    `autonomous-prompt` (the plugin repo) are not book commits."""
    bare = []
    for skill_md in SKILLS_DIR.glob('*/SKILL.md'):
        if skill_md.parent.name in ('init', 'autonomous-prompt'):
            continue
        lines = skill_md.read_text(encoding='utf-8').splitlines()
        for n, line in enumerate(lines, 1):
            if (re.search(r'git add (-A|--all|\.)(?! -- \.)(\s|`|$)', line)
                    or 'git commit -a' in line):
                bare.append(f'{skill_md.parent.name}:{n}')
    assert bare == []

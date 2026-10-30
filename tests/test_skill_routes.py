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

# Hone Skill: Actions Log

## Files Read

| File | Purpose |
|------|---------|
| `skills/hone/SKILL.md` | Skill instructions |
| `tests/fixtures/test-project/storyforge.yaml` | Project config -- title, genre, coaching level (not set, defaults to full; overridden by user request to "coaching mode") |
| `tests/fixtures/test-project/reference/scenes.csv` | Scene metadata -- identified 3 act 2 scenes (part=2): act2-sc01, act2-sc02, act2-sc03 |
| `tests/fixtures/test-project/reference/scene-briefs.csv` | Drafting contracts -- found briefs only for act2-sc03; act2-sc01 and act2-sc02 missing entirely |
| `tests/fixtures/test-project/reference/scene-intent.csv` | Narrative dynamics -- all 3 act 2 scenes have intent data |
| `tests/fixtures/test-project/working/scores/` | Checked for scoring data -- directory empty, no latest scores or structural proposals |

## Domain Determination

- User requested: "briefs for act 2 scenes, coaching mode"
- Domain: **briefs**
- Scope: **act 2** (part=2 in scenes.csv)
- Coaching level: **coach** (user override, yaml has no coaching_level set)

## Coaching Level Routing

Per SKILL.md Step 2: coaching level is `coach`, so routed to **Coach/Strict Flow** section.
Coach mode behavior: detect issues, save proposals to working/hone/, walk through interactively, apply only author-approved changes.

## Scenes Analyzed

### act2-sc01 (Into the Blank)
- **Status:** architecture
- **Briefs:** MISSING -- no row in scene-briefs.csv
- **Intent:** Present (function, emotional_arc, value_at_stake populated)
- **Action proposed:** Defer to elaborate skill to generate briefs first

### act2-sc02 (First Collapse)
- **Status:** spine
- **Briefs:** MISSING -- no row in scene-briefs.csv
- **Intent:** Present (function, emotional_arc, value_at_stake populated)
- **Action proposed:** Defer to elaborate skill to generate briefs first

### act2-sc03 (The Warning Ignored)
- **Status:** briefed
- **Briefs:** Present, with 5 issues detected:

| Issue | Field | Severity |
|-------|-------|----------|
| Procedural goal | goal | Medium -- will produce bureaucratic scene opening |
| Over-specified beats | key_actions | High -- 5 actions for 2,200 words (1 per 440 words) |
| Prescriptive dialogue | key_dialogue | Medium -- exact quotes constrain drafter |
| Emotional arc granularity | emotions | Medium -- 4 beats force artificial escalation |
| Physical state data error | physical_state_in | Low -- references Tessa who is not in this scene |

## Actions Proposed (Coach Mode)

1. **Save proposals** to `working/hone/briefs-act2-sc03.md` with current values, issues, suggested rewrites, and reasoning
2. **Walk through interactively** -- present each proposal, get author approval before applying
3. **Apply only approved changes** to `reference/scene-briefs.csv`
4. **Commit and push** after author approves batch: `git commit -m "Hone: briefs (coach) -- concretize act2-sc03 goal, reduce key_actions, convert dialogue to direction"`
5. **Recommend elaboration** for act2-sc01 and act2-sc02 before attempting to hone their (nonexistent) briefs

## Script Command Built

```bash
cd /Users/cadencedev/Developer/storyforge/tests/fixtures/test-project && /Users/cadencedev/Developer/storyforge/scripts/storyforge-hone --domain briefs --act 2 --coaching coach
```

Flags mapped per SKILL.md Step 5 Command Builder:
- "briefs" -> `--domain briefs`
- "act 2" -> `--act 2`
- "coaching mode" -> `--coaching coach`

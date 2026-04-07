# Hone Skill Actions Log

## Files Read

1. **skills/hone/SKILL.md** -- skill instructions
2. **tests/fixtures/test-project/storyforge.yaml** -- project config (no coaching_level set, defaults to `full`)
3. **tests/fixtures/test-project/reference/scenes.csv** -- 6 scenes across 2 parts
4. **tests/fixtures/test-project/reference/scene-briefs.csv** -- 4 rows (3 with full briefs, 1 nearly empty)
5. **tests/fixtures/test-project/reference/scene-intent.csv** -- 6 rows with intent data
6. **working/scores/latest/scene-scores.csv** -- does not exist (no scoring data available)
7. **working/scores/structural-proposals.csv** -- does not exist

## Domain Determination

The author said: "My prose naturalness scores are low on a bunch of scenes. Can you help me figure out what's going on with my briefs?"

This maps to the **Briefs domain** per SKILL.md Step 3:
- "Improve my briefs" / "Fix abstract language" -> Briefs domain
- Additionally, the author explicitly mentions prose naturalness scores being low, and SKILL.md Step 3 says: "if prose_naturalness scores are low, recommend briefs domain"

No scoring data was found on disk, so the analysis relies on brief inspection rather than score correlation. The author's self-report of low naturalness scores is taken at face value.

## Coaching Level

No `coaching_level` field in storyforge.yaml, no `--coaching` flag, no env var detected. Defaults to `full`. Followed the standard (non-coach/strict) flow.

## Briefs Assessment Findings

### Over-Specified Beats (3 of 3 briefed scenes)
| Scene | Target Words | Key Actions Count | Max Recommended | Flagged |
|-------|-------------|-------------------|-----------------|---------|
| act1-sc01 | 2,500 | 5 | 3 | YES |
| act1-sc02 | 3,000 | 4 | 3 | borderline |
| act2-sc03 | 2,200 | 5 | 2 | YES |

### Prescriptive Dialogue (3 of 3 briefed scenes)
| Scene | Contains Exact Quotes |
|-------|----------------------|
| act1-sc01 | YES -- "The eastern readings are within acceptable variance" |
| act1-sc02 | YES -- "It was there forty years ago. It isn't there now. There is no note." |
| act2-sc03 | YES -- "We appreciate your diligence, Cartographer." / "They won't look." |

### Emotional Arc Granularity (3 of 3 briefed scenes)
| Scene | Emotion Count | Flagged (>3) |
|-------|--------------|--------------|
| act1-sc01 | 4 (competence;unease;self-doubt;resolve) | YES |
| act1-sc02 | 4 (routine;confusion;dread;determination) | YES |
| act2-sc03 | 4 (resolve;frustration;bitter-resignation;quiet-defiance) | YES |

### Procedural Goals (1 of 3 briefed scenes)
| Scene | Goal | Issue |
|-------|------|-------|
| act1-sc01 | "Complete the quarterly pressure audit on schedule" | Task framing, not dramatic question |

### Gaps (3 of 6 scenes)
| Scene | Status |
|-------|--------|
| new-x1 | Nearly empty brief (no goal, conflict, outcome, crisis, decision, knowledge_in, key_actions, key_dialogue, emotions, motifs) |
| act2-sc01 | No brief row at all |
| act2-sc02 | No brief row at all |

## Actions Proposed to Author

1. **Run `storyforge-hone --domain briefs`** to concretize the three existing briefs -- trim key_actions, convert prescriptive dialogue to direction, simplify emotional arcs, reframe procedural goals
2. **Fill gaps** for new-x1, act2-sc01, act2-sc02 (separate step, likely via elaborate --gap-fill)
3. **Re-draft affected scenes** after brief improvements to pick up the new concrete briefs
4. Offered standard Option A (run here) / Option B (run yourself) delegation pattern per SKILL.md Step 5

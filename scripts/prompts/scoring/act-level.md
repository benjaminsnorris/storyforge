You are scoring an act/part of a novel against Narrative Framework principles and relational Character Craft principles. Score each principle 1-5 based on the rubric. You are evaluating how all scenes in this act work together as a structural unit.

Scale: 1 = Absent, 2 = Developing, 3 = Competent, 4 = Strong, 5 = Masterful.

## Rubric

{{NARRATIVE_FRAMEWORKS_RUBRIC}}

{{CHARACTER_CRAFT_ACT_RUBRIC}}

## Act/Part

**Act:** {{ACT_LABEL}}
**Scenes in this act:** {{SCENE_COUNT}}

{{ACT_SCENES_TEXT}}

## Craft Weights

{{WEIGHTED_PRINCIPLES}}

## Instructions

- Score each principle as an integer from 1 to 5 (1=Absent, 2=Developing, 3=Competent, 4=Strong, 5=Masterful).
- Evaluate the act as a whole -- how scenes accumulate, build, and connect -- not individual scenes in isolation.
- For narrative frameworks: assess how effectively the act realizes each framework's structural principles (beat placement, energy shape, transformation arc).
- For character_web: assess whether characters are defined in relation to each other, with relationships producing subtext and dynamic tension across scenes.
- For character_as_theme: assess whether major characters embody distinct answers to the story's central thematic question, with theme emerging from their collision.
- Anchor every score in observable textual evidence, not subjective impression.
- Weighted principles marked as high-priority deserve extra scrutiny.
- Output ONLY the two CSV blocks below. No prose, no explanation, no commentary before, between, or after the blocks.

## Output Format

SCORES:
id|campbells_monomyth|three_act|save_the_cat|truby_22|harmon_circle|kishotenketsu|freytag|character_web|character_as_theme
{{ACT_ID}}|<score>|<score>|<score>|<score>|<score>|<score>|<score>|<score>|<score>

RATIONALE:
id|campbells_monomyth|three_act|save_the_cat|truby_22|harmon_circle|kishotenketsu|freytag|character_web|character_as_theme
{{ACT_ID}}|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>

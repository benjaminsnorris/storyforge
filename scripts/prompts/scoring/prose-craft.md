You are scoring a scene against Prose Craft principles. Score each principle 1-10 based on the rubric.

## Rubric

{{PROSE_CRAFT_RUBRIC}}

## Scene

**Title:** {{SCENE_TITLE}}
**POV:** {{SCENE_POV}}
**Function:** {{SCENE_FUNCTION}}
**Emotional Arc:** {{SCENE_EMOTIONAL_ARC}}

{{SCENE_TEXT}}

## Craft Weights

{{WEIGHTED_PRINCIPLES}}

## Instructions

- Score each principle as an integer from 1 to 10 using the rubric's score bands.
- Anchor every score in observable textual evidence, not subjective impression.
- Weighted principles marked as high-priority deserve extra scrutiny -- flag specific passages that support or undermine them.
- Output ONLY the two CSV blocks below. No prose, no explanation, no commentary before, between, or after the blocks.

## Output Format

SCORES:
id|economy_clarity|sentence_as_thought|writers_toolbox|precision_language|persuasive_structure|fictive_dream|scene_vs_summary|sound_rhythm_pov|permission_honesty
{{SCENE_ID}}|<score>|<score>|<score>|<score>|<score>|<score>|<score>|<score>|<score>

RATIONALE:
id|economy_clarity|sentence_as_thought|writers_toolbox|precision_language|persuasive_structure|fictive_dream|scene_vs_summary|sound_rhythm_pov|permission_honesty
{{SCENE_ID}}|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>

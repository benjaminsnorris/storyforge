You are scoring a scene against scene-level Character Craft principles. Score each principle 1-10 based on the rubric.

## Rubric

{{CHARACTER_CRAFT_SCENE_RUBRIC}}

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
- For egri_premise: assess whether the scene's conflict arises from the character's defining traits rather than external coincidence.
- For testing_characters: assess whether characters behave as specific individuals with distinctive responses, not as generic plot functions.
- Anchor every score in observable textual evidence, not subjective impression.
- Weighted principles marked as high-priority deserve extra scrutiny -- flag specific passages that support or undermine them.
- Output ONLY the two CSV blocks below. No prose, no explanation, no commentary before, between, or after the blocks.

## Output Format

SCORES:
id|egri_premise|testing_characters
{{SCENE_ID}}|<score>|<score>

RATIONALE:
id|egri_premise|testing_characters
{{SCENE_ID}}|<one sentence>|<one sentence>

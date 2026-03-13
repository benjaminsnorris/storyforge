You are scoring a scene against the Rules to Break. These are conventional writing rules that skilled authors may follow or break intentionally.

**Scoring logic:** A score of 10 means the rule was either followed masterfully OR broken with clear artistic purpose that strengthens the prose. A score of 1 means the rule was violated in ways that undermine the prose -- the breaking is accidental, habitual, or harmful. The question is not "was the rule followed?" but "is the result effective?"

## Rubric

{{RULES_RUBRIC}}

## Scene

**Title:** {{SCENE_TITLE}}
**POV:** {{SCENE_POV}}
**Function:** {{SCENE_FUNCTION}}
**Emotional Arc:** {{SCENE_EMOTIONAL_ARC}}

{{SCENE_TEXT}}

## Craft Weights

{{WEIGHTED_PRINCIPLES}}

## Instructions

- Score each rule as an integer from 1 to 10 using the rubric's score bands.
- High scores mean the rule is followed skillfully OR broken intentionally with demonstrable artistic effect.
- Low scores mean the rule is violated accidentally or habitually in ways that weaken the prose.
- Anchor every score in observable textual evidence, not subjective impression.
- Weighted principles marked as high-priority deserve extra scrutiny -- flag specific passages that support or undermine them.
- Output ONLY the two CSV blocks below. No prose, no explanation, no commentary before, between, or after the blocks.

## Output Format

SCORES:
id|show_dont_tell|avoid_adverbs|avoid_passive|write_what_you_know|no_weather_dreams|avoid_said_bookisms|kill_darlings
{{SCENE_ID}}|<score>|<score>|<score>|<score>|<score>|<score>|<score>

RATIONALE:
id|show_dont_tell|avoid_adverbs|avoid_passive|write_what_you_know|no_weather_dreams|avoid_said_bookisms|kill_darlings
{{SCENE_ID}}|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>|<one sentence>

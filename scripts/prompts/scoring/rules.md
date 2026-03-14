You are scoring a scene against the Rules to Break using deficit-first evaluation. These are conventional writing rules that skilled authors may follow or break intentionally.

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

For EACH rule below, complete ALL four steps IN ORDER before moving to the next rule. Do not skip steps or batch rules together.

**Step 1: Find deficits.**
Quote 2-5 specific passages where the rule is violated accidentally or habitually in ways that weaken the prose. For each quote, state in one sentence what's wrong and why it matters. If the scene has fewer than 2 genuine deficits, say so — but be honest. Intentional, effective rule-breaking is NOT a deficit.

**Step 2: Find strengths.**
Quote 1-3 specific passages where the rule is followed skillfully OR broken intentionally with demonstrable artistic effect. For each, state what makes it work.

**Step 3: Weigh the evidence.**
In 1-2 sentences, classify the deficits as structural (1-4), execution (5-7), or surface (8-9). No genuine deficits with notable strengths = 10.

**Step 4: Score.**
Assign a single integer 1-10 consistent with the evidence band from Step 3.

Complete all four steps for: show_dont_tell, avoid_adverbs, avoid_passive, write_what_you_know, no_weather_dreams, avoid_said_bookisms, kill_darlings.

After completing the full analysis for all rules, output ONLY the two CSV blocks below. The rationale for each rule should be the Step 3 assessment (structural/execution/surface classification + justification).

## Output Format

SCORES:
id|show_dont_tell|avoid_adverbs|avoid_passive|write_what_you_know|no_weather_dreams|avoid_said_bookisms|kill_darlings
{{SCENE_ID}}|<score>|<score>|<score>|<score>|<score>|<score>|<score>

RATIONALE:
id|show_dont_tell|avoid_adverbs|avoid_passive|write_what_you_know|no_weather_dreams|avoid_said_bookisms|kill_darlings
{{SCENE_ID}}|<assessment>|<assessment>|<assessment>|<assessment>|<assessment>|<assessment>|<assessment>

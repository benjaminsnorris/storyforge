You are scoring a scene against Prose Craft principles using deficit-first evaluation.

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

For EACH principle below, complete ALL four steps IN ORDER before moving to the next principle. Do not skip steps or batch principles together.

**Step 1: Find deficits.**
Quote 2-5 specific passages (exact text from the scene) where the scene falls short of this principle. For each quote, state in one sentence what the deficit is and why it matters. If the scene has fewer than 2 genuine deficits on this principle, say so — but be honest. Even strong scenes have places where a word could be cut or a rhythm could be sharper. "No deficits" should be rare and defensible.

**Step 2: Find strengths.**
Quote 1-3 specific passages where the scene executes this principle well. For each, state in one sentence what makes it work.

**Step 3: Weigh the evidence.**
In 1-2 sentences, classify the deficits as structural (1-4), execution (5-7), or surface (8-9). No genuine deficits with notable strengths = 10.

**Step 4: Score.**
Assign a single integer 1-10 consistent with the evidence band from Step 3.

Complete all four steps for: economy_clarity, sentence_as_thought, writers_toolbox, precision_language, persuasive_structure, fictive_dream, scene_vs_summary, sound_rhythm_pov, permission_honesty.

After completing the full analysis for all principles, output ONLY the two CSV blocks below. The rationale for each principle should be the Step 3 assessment (structural/execution/surface classification + justification).

## Output Format

SCORES:
id|economy_clarity|sentence_as_thought|writers_toolbox|precision_language|persuasive_structure|fictive_dream|scene_vs_summary|sound_rhythm_pov|permission_honesty
{{SCENE_ID}}|<score>|<score>|<score>|<score>|<score>|<score>|<score>|<score>|<score>

RATIONALE:
id|economy_clarity|sentence_as_thought|writers_toolbox|precision_language|persuasive_structure|fictive_dream|scene_vs_summary|sound_rhythm_pov|permission_honesty
{{SCENE_ID}}|<assessment>|<assessment>|<assessment>|<assessment>|<assessment>|<assessment>|<assessment>|<assessment>|<assessment>

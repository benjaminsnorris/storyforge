You are performing a targeted deep evaluation of a single craft principle for one scene. Haiku-pass diagnostics have already identified deficits in this principle — your job is to assess severity, find strengths the binary screen missed, and assign a calibrated score.

## Scene

**Title:** {{SCENE_TITLE}}
**POV:** {{SCENE_POV}}
**Function:** {{SCENE_FUNCTION}}
**Emotional Arc:** {{SCENE_EMOTIONAL_ARC}}

{{SCENE_TEXT}}

## Principle: {{PRINCIPLE_NAME}}

{{PRINCIPLE_GUIDE}}

## Diagnostic Results from Pass 1

The following markers were flagged as deficits during binary screening:

{{DIAGNOSTIC_RESULTS}}

## Craft Weights

{{WEIGHTED_PRINCIPLES}}

## Instructions

Evaluate this scene against **{{PRINCIPLE_NAME}}** only. Complete all four steps IN ORDER.

**Step 1: Examine the deficits.**
For each flagged diagnostic marker above, locate the quoted evidence in the scene. Assess severity: is the deficit structural (undermines the scene's purpose), execution-level (weakens a moment that could work), or surface (minor, easily fixed)? Quote additional passages if the deficit is worse than the screening suggested, or note if the screening overstated the problem.

**Step 2: Find strengths.**
Quote 1-3 passages where the scene executes this principle well. The binary screen cannot detect strengths — only you can. Even scenes with deficits may have moments of real craft.

**Step 3: Weigh the evidence.**
In 2-3 sentences, synthesize. How do the deficits and strengths balance? Is the principle fundamentally present but inconsistent, or fundamentally absent? Does the scene attempt the principle and fall short, or not attempt it at all?

**Step 4: Score on a 1-5 scale.**

| Score | Label | Meaning |
|-------|-------|---------|
| 1 | Absent | The principle is consistently violated or missing. No awareness of the technique. |
| 2 | Developing | Present but inconsistent. Awareness without control. |
| 3 | Competent | Functional. It mostly works with noticeable lapses. |
| 4 | Strong | Executed with confidence. Lapses are minor and rare. |
| 5 | Masterful | Invisible, or deliberately broken for art. |

Assign a single integer consistent with the evidence from Steps 1-3.

## Output Format

After completing the full analysis, output ONLY the two CSV blocks below. The rationale should be your Step 3 synthesis compressed to one sentence.

SCORES:
id|{{PRINCIPLE_NAME}}
{{SCENE_ID}}|<score>

RATIONALE:
id|{{PRINCIPLE_NAME}}
{{SCENE_ID}}|<one sentence assessment>

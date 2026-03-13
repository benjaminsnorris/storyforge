# Principled Scoring and Self-Improvement Design

**Date:** 2026-03-13
**Branch:** feature/scene-metadata
**Status:** Draft

## Problem

Storyforge's current evaluation system uses persona-based evaluators (literary agent, developmental editor, etc.) that produce subjective prose feedback. This feedback drives a revision cycle where Claude edits existing prose — iterating on text until it's "good enough." There is no structured measurement of craft quality, no way to track improvement over time, and no mechanism for the system to learn from its own results.

The evaluation loop is expensive and infrequent. The revision model is "fix this text" rather than "fix the system that produces text." Authors have no way to express which craft principles matter most to them, and the plugin has no way to improve its defaults based on real-world results.

## Goals

1. Score manuscript against craft engine principles with structured numeric scores at appropriate scales (scene, act, novel).
2. Use scores to diagnose weaknesses, propose prompt/guidance adjustments, and drive rewrites rather than revisions.
3. Build a self-improving system where each scoring cycle makes the next draft better.
4. Feed validated improvements back to the plugin itself via GitHub issues.
5. Allow authors to calibrate the system to their taste through optional score overrides.
6. Run frequently and cheaply — scoring is the tight feedback loop, not the expensive evaluation.

## Non-Goals

- Replacing persona-based evaluation entirely (it serves a different purpose — broad professional feedback 1-2 times per project).
- Fully automated plugin self-modification (start with issue submission, human review).
- Real-time scoring during drafting (scoring runs as a post-draft pass).

## Design

### Scoring Pass Architecture

#### Three Scoring Modes

**Grouped (default):** One Claude invocation per craft engine section **per scene**. For each scene, ~4 calls (scene craft, prose craft, character craft, rules). For a 100-scene manuscript, this is ~400 scene-level calls plus 2-3 for act/novel-level. Best balance of accuracy and cost per principle, but scales with scene count.

**Quick (`--quick`):** Single invocation per scene scores all principles at once. For 100 scenes, ~100 calls. Cheapest per-scene option, less precise. Good for directional checks between rewrites.

**Deep (`--deep`):** One invocation per individual principle per scene. ~23 calls per scene. Most expensive, highest accuracy. Used to investigate a specific weakness — typically combined with `--scenes` to target specific scenes rather than the full manuscript.

**Scope and mode are orthogonal:** Modes (`--quick`, `--deep`) and scope filters (`--scenes`, `--act`) can be combined. `--quick --scenes act1-sc01,act1-sc02` scores two scenes in quick mode. `--deep --act 2` deeply scores all scenes in act 2.

#### Scoring Tiers by Scale

Principles are scored at their natural scale:

**Per-scene (23 principles):**

| Section | Principles | Score range |
|---------|-----------|-------------|
| Scene Craft | Enter Late/Leave Early, Every Scene Must Turn, Scene Emotion vs Character Emotion, Psychic Distance at Scene Level, Show vs Tell in Scenes, Thread Management, Pacing Through Scene Variety | 1-10 each |
| Prose Craft | Economy and Clarity, Sentence as Unit of Thought, Writer's Toolbox, Precision in Language, Persuasive Structure, Fictive Dream and Psychic Distance, Scene vs Summary, Sound/Rhythm/POV, Permission and Emotional Honesty | 1-10 each |
| Rules to Break | Show Don't Tell, Avoid Adverbs, Avoid Passive Voice, Write What You Know, Never Open with Weather/Dreams, Avoid Said-Bookisms, Kill Your Darlings | 1-10 each |

**Per-act/part (~9 principles):**

| Section | Principles |
|---------|-----------|
| Narrative Frameworks | Campbell's Monomyth, Three-Act Structure, Save the Cat, Truby's 22 Steps, Harmon's Story Circle, Kishotenketsu, Freytag's Pyramid |
| Character Craft (relational) | Character Web, Character as Expression of Theme |

**Per-novel (varies by cast size):**

| Section | Principles |
|---------|-----------|
| Character Craft (per character) | Want/Need, Wound/Lie, Flaws as Strengths, Voice as Character |
| Tropes & Genre | Trope awareness, Archetype vs Cliche, Genre contract fulfillment, Subversion/Deconstruction awareness |

#### Overlapping Principles

Two principles share territory: `psychic_distance_scene` (Scene Craft) and `fictive_dream` (Prose Craft). They measure different things: `psychic_distance_scene` assesses the scene-level arc of distance (establishing shot → close-up at turn → pull-back), while `fictive_dream` assesses sentence-level distance control and whether the reader stays immersed. A scene can score high on the distance arc but low on prose-level immersion, or vice versa.

#### Rules to Break Scoring

Rules in Section 5 require special treatment. A low score doesn't necessarily mean "fix this." The scoring prompt instructs Claude to assess whether rule violations are **intentional and effective** or **accidental and harmful**. The score reflects craft execution, not blind compliance:

- **10:** Rule followed masterfully, or broken intentionally with clear artistic purpose
- **5:** Rule sometimes followed, sometimes broken without clear intent
- **1:** Rule consistently violated in ways that undermine the prose

### New Script: `storyforge-score`

Autonomous script at `scripts/storyforge-score`. Follows existing script patterns (`set -eo pipefail`, sources `common.sh`, healing zones, cost tracking).

**Usage:**

```bash
./storyforge score                    # Grouped mode, full manuscript
./storyforge score --quick            # Quick mode, single invocation
./storyforge score --deep             # Deep mode, per-principle
./storyforge score --scenes act1-sc01,act1-sc02   # Score specific scenes
./storyforge score --act 2            # Score act 2 only
```

**Behavior:**

1. Detect project root, read `metadata.csv` to get scene list
2. Determine current pipeline cycle (or create standalone scoring directory)
3. For each scoring group, build a prompt that includes: the relevant craft engine section, the scene text, the craft weights, and any per-scene overrides
4. Invoke Claude, parse structured scores from the response
5. Write scores to versioned CSV files
6. Run diagnosis
7. Generate proposals
8. Apply proposals per coaching level
9. Update tuning ledger
10. Log costs

### Score File Structure

```
working/scores/
  cycle-1/
    scene-scores.csv        # Per-scene principle scores
    scene-rationale.csv     # One-sentence rationale per score
    act-scores.csv          # Per-act principle scores
    act-rationale.csv
    novel-scores.csv        # Novel-level scores
    novel-rationale.csv
    diagnosis.csv           # Weakest principles and worst scenes
    proposals.csv           # Proposed tuning changes
    overrides.csv           # Per-scene prompt overrides (temporary)
  cycle-2/
    ...
  latest/                   # Symlink to most recent cycle
```

#### `scene-scores.csv`

One row per scene, one column per scene-level principle:

```
id|enter_late_leave_early|every_scene_must_turn|scene_emotion_vs_character|psychic_distance_scene|show_vs_tell_scenes|thread_management|pacing_variety|economy_clarity|sentence_as_thought|writers_toolbox|precision_language|persuasive_structure|fictive_dream|scene_vs_summary|sound_rhythm_pov|permission_honesty|show_dont_tell|avoid_adverbs|avoid_passive|write_what_you_know|no_weather_dreams|avoid_said_bookisms|kill_darlings
the-finest-cartographer|8|9|7|6|8|7|5|6|7|7|8|6|7|8|7|8|9|7|8|8|10|8|7
```

#### `scene-rationale.csv`

Same structure but cells contain one-sentence rationale instead of numeric score:

```
id|enter_late_leave_early|every_scene_must_turn|...
the-finest-cartographer|Opens with action at desk, no preamble|Clear turn when anomaly surfaces|...
```

#### `act-scores.csv`

```
part|campbells_monomyth|three_act|save_the_cat|truby_22|harmon_circle|kishotenketsu|freytag|character_web|character_as_theme
1|6|7|5|6|7|3|7|8|7
```

#### `character-scores.csv`

Per-character arc scores:

```
character|want_need|wound_lie|flaws_as_strengths|voice_as_character
Dorren Hayle|8|9|7|8
Tessa Merrin|7|6|8|7
```

#### `genre-scores.csv`

Novel-level trope and genre convention scores:

```
trope_awareness|archetype_vs_cliche|genre_contract|subversion_awareness
7|8|9|6
```

#### `diagnosis.csv`

Generated by analyzing scores:

```
principle|scale|avg_score|worst_items|delta_from_last|priority
economy_clarity|scene|4.2|the-footnote;the-weight-of-the-rim|-0.3|high
thread_management|scene|5.1|the-hollow-district;the-archivists-warning|+0.4|medium
campbells_monomyth|act|3.8|part-2||high
```

- `worst_items` is a `;`-separated array of scene IDs, act numbers, or character names depending on scale
- When previous cycle data is missing, corrupt, or has different columns, `delta_from_last` is left empty (not an error)
- Priority computed from: absolute score (lower = higher priority), regression (negative delta = higher priority), and craft weight (higher-weighted principles get higher priority)

#### `proposals.csv`

```
id|principle|lever|target|change|rationale|status
p001|economy_clarity|craft_weight|global|weight 5 → 8|Consistently low across 15 scenes, no improvement in 2 cycles|pending
p002|thread_management|scene_intent|the-footnote|Add: limit to 2 threads|Scene touches 5 threads, violating ≤3 guideline|pending
p003|economy_clarity|voice_guide|global|Add directive: cut any sentence that works without its last clause|Weight increase alone insufficient|pending
```

Status: `pending` → `approved` / `rejected` → `applied` → `validated` / `reverted`

### The Improvement Cycle

Seven steps, automation level determined by coaching level:

#### Step 1: Score

`storyforge-score` runs against the current draft. Produces all score CSVs for the current cycle.

#### Step 2: Diagnose

Analyze scores to identify weakest principles and contributing scenes. Compare to previous cycle if available. Write `diagnosis.csv`.

#### Step 3: Hypothesize

Based on diagnosis, generate proposals for specific lever changes. The system proposes changes to the five levers in priority order:

1. **Craft weights** (`working/craft-weights.csv`) — adjust emphasis for the next rewrite
2. **Voice guide** (`reference/voice-guide.md`) — add concrete prose directives when weight changes aren't enough
3. **Scene intent** (`scenes/intent.csv`) — sharpen function/emotional_arc for specific scenes
4. **Per-scene overrides** (`working/scores/latest/overrides.csv`) — temporary scene-specific instructions
5. **Tuning ledger** (`working/tuning.csv`) — always recorded regardless of other actions

Write `proposals.csv`.

#### Step 4: Approve

Depends on coaching level:

- **Full:** All proposals auto-approved. System applies and continues.
- **Coach:** Proposals presented to author with rationale. Author approves/rejects each. Could be interactive (`/storyforge:score` skill) or printed as a report.
- **Strict:** Report only. Author reads diagnosis and proposals, makes changes manually.

#### Step 5: Apply

Approved proposals update their targets:

- Craft weight changes → update `working/craft-weights.csv`
- Voice guide changes → append to `reference/voice-guide.md` (with a marker comment indicating system-generated)
- Scene intent changes → update `scenes/intent.csv` via `update_csv_field`
- Per-scene overrides → write to `working/scores/latest/overrides.csv`

#### Step 6: Rewrite

Author (or system in full coaching) runs `storyforge write` or `storyforge revise` with updated guidance. `prompt-builder.sh` reads craft weights and overrides to build prompts with appropriate emphasis.

#### Step 7: Record

After rewrite and re-score:

- Compare before/after scores for each applied proposal
- Record results in `working/tuning.csv`
- If a proposal didn't improve scores (or caused regression), mark as `kept: false` and revert the change

#### `working/tuning.csv`

The system's memory of what works and what doesn't. Append-only.

| Column | Type | Description |
|--------|------|-------------|
| `cycle` | integer | Pipeline cycle number |
| `proposal_id` | string | ID from proposals.csv |
| `principle` | string | Principle slug |
| `lever` | string | Which lever was adjusted (craft_weight, voice_guide, scene_intent, override) |
| `change` | string | What was changed (e.g., "weight 5→8") |
| `score_before` | decimal | Average score for this principle before the change |
| `score_after` | decimal | Average score after rewrite |
| `kept` | boolean | true if change was kept, false if reverted |

#### `working/scores/cycle-N/overrides.csv`

Temporary per-scene instructions that expire after one cycle.

| Column | Type | Description |
|--------|------|-------------|
| `scene_id` | string | Scene ID |
| `principle` | string | Principle slug |
| `instruction` | string | Specific directive for this scene |
| `source_proposal` | string | Proposal ID that generated this override |
| `expires_after_cycle` | integer | Cycle number after which this override is removed |
- Check for validated patterns (3+ successful applications of same principle+lever) and trigger plugin insight submission

### Craft Weights

#### `working/craft-weights.csv`

Primary tuning dials. Initialized from plugin defaults on first scoring run.

```
section|principle|weight|author_weight|notes
scene_craft|enter_late_leave_early|5||
scene_craft|every_scene_must_turn|7||
scene_craft|scene_emotion_vs_character|5||
scene_craft|psychic_distance_scene|5||
scene_craft|show_vs_tell_scenes|6||
scene_craft|thread_management|5||
scene_craft|pacing_variety|5||
prose_craft|economy_clarity|5||
prose_craft|sentence_as_thought|5||
prose_craft|writers_toolbox|5||
prose_craft|precision_language|5||
prose_craft|persuasive_structure|5||
prose_craft|fictive_dream|5||
prose_craft|scene_vs_summary|6||
prose_craft|sound_rhythm_pov|5||
prose_craft|permission_honesty|5||
character_craft|want_need|6||
character_craft|wound_lie|6||
character_craft|character_as_theme|5||
character_craft|egri_premise|5||
character_craft|character_web|5||
character_craft|flaws_as_strengths|5||
character_craft|voice_as_character|5||
character_craft|testing_characters|4||
rules|show_dont_tell|5||
rules|avoid_adverbs|5||
rules|avoid_passive|5||
rules|write_what_you_know|3||
rules|no_weather_dreams|4||
rules|avoid_said_bookisms|5||
rules|kill_darlings|4||
```

- `weight` (1-10): System-managed. Adjusted by the improvement cycle based on scoring results.
- `author_weight` (1-10, optional): Author override. When set, takes precedence over system weight. This is how the author says "I care about this."
- `notes`: Accumulated context from tuning cycles.

#### Plugin Defaults: `references/default-craft-weights.csv`

Same format, lives in the storyforge plugin. New projects copy this to `working/craft-weights.csv` on first scoring run. Updated when plugin insights are approved.

#### How Weights Affect Prompts

`prompt-builder.sh` reads `craft-weights.csv` and builds a **weighted directive** instead of injecting raw craft engine sections:

- Principles with effective weight 7+ get explicit emphasis: "Pay particular attention to [principle] — [one-line explanation from craft engine]"
- Principles with effective weight 4-6 are mentioned normally
- Principles with effective weight 3 or below are omitted (assumed baseline competence)

Effective weight = `author_weight` if set, otherwise `weight`.

**Scale-specific behavior:** Scene-level weights (scene_craft, prose_craft, rules) are injected into every scene drafting prompt. Act/novel-level weights (narrative_frameworks, character_craft) are injected only when drafting prompts for the first or last scene of an act (structural moments), or when the scene's `type` is `plot` or `character` — not into every scene. This prevents arc-level concerns from overwhelming scene-level execution.

This replaces injecting 2,000+ tokens of craft engine text with a ~200-token weighted summary — a significant token savings that compounds across every invocation.

Per-scene overrides are appended after the weighted directive for the specific scene being drafted.

### Scoring Rubrics and Exemplars

Reliable scoring requires more than principle definitions — Claude needs concrete criteria for what each score level looks like, grounded in real literary examples.

#### `references/scoring-rubrics.md`

A reference document in the plugin defining, for each principle:

1. **Score band definitions** — what 1-3, 4-6, 7-8, and 9-10 look like in concrete terms
2. **Reference exemplars** — 1-2 short excerpts from published works per band, drawn from established craft sources

Example structure for one principle:

```markdown
## Economy and Clarity

**1-3 (Weak):** Frequent filler phrases, redundant clauses, sentences that could lose 30%+ of their words without losing meaning. Habitual qualifications ("quite," "rather," "somewhat"), padding constructions ("the fact that," "it is important to note that"), and doubled descriptions where one would suffice.

> "It was a quite large and rather imposing building that seemed to loom up in a somewhat threatening manner over the small town square." — (constructed example of weak economy)

**4-6 (Developing):** Generally clean prose with habitual padding. The writer knows economy matters but hasn't internalized it. Occasional strong passages interrupted by slack ones.

> Compare Hemingway's draft vs. published versions of "Big Two-Hearted River" — early drafts contain the explanations; the published version trusts the reader.

**7-8 (Strong):** Nearly every word earns its place. Occasional missed cuts visible only on close reading. Prose moves with purpose.

> "The old man was thin and gaunt with deep wrinkles in the back of his neck." — Hemingway, *The Old Man and the Sea*. Every word does work: "thin and gaunt" aren't redundant (thin = body, gaunt = condition), "deep wrinkles" = age and weather in two words.

**9-10 (Masterful):** Prose is lean as bone. Nothing wasted. Every deletion would lose meaning or music.

> "He was an old man who fished alone in a skiff in the Gulf Stream and he had gone eighty-four days now without taking a fish." — Hemingway, *The Old Man and the Sea*. One sentence: character, situation, setting, conflict, stakes, timeline. 27 words.
```

**Sources for exemplars:** Craft textbooks (Strunk & White's *The Elements of Style*, Gardner's *The Art of Fiction*, Le Guin's *Steering the Craft*, Francine Prose's *Reading Like a Writer*, King's *On Writing*), university creative writing curricula, published literary criticism, and canonical novels that exemplify specific principles.

Each principle across all seven craft engine sections gets this treatment. The rubrics are the objective foundation the scoring system stands on.

#### Author Exemplar Bank: `working/exemplars.csv`

As the scoring system runs across cycles, it automatically collects the author's own best work as exemplars:

```
principle|scene_id|score|excerpt|cycle
economy_clarity|the-finest-cartographer|9|Dorren's pen moved through the third-drawer reports the way a surgeon's hand moves through familiar tissue.|3
sound_rhythm_pov|the-weight-of-the-rim|9|The lamp guttered. The map curled. And Voss — who had not meant to look — looked.|5
```

**How it works:**
- After each scoring run, any scene that scores 9+ on a principle has its strongest passage extracted and added to the exemplar bank
- These exemplars are injected into scoring prompts alongside the standard rubric: "Here is what a 9 on economy looks like in YOUR voice"
- This makes scoring increasingly calibrated to the author's style over time
- Author exemplars never replace standard rubric exemplars — they supplement them
- Any literal `|` in excerpt text is replaced with an em-dash before storage to avoid breaking the CSV format

**This is how the system becomes personalized without losing objectivity.** The rubric defines the principle. The standard exemplars show what it looks like in great literature. The author exemplars show what it looks like when this author does it well.

### Plugin-Level Learning

#### Validated Pattern Detection

At the end of Step 7 (Record), the system checks the tuning ledger for validated patterns:

**Criteria for a validated pattern:**
- Same principle + lever combination improved scores 3+ times across different cycles
- Average improvement > 10% relative to starting score
- No significant regressions in other principles (> 5% drop)

#### GitHub Issue Submission

When a validated pattern is detected, the system creates a GitHub issue on `benjaminsnorris/storyforge` using `gh issue create`. This happens **automatically regardless of coaching level** — plugin improvement is separate from author involvement preferences. Authors who want to disable this can set `STORYFORGE_AUTO_ISSUES=false` in their environment or `storyforge.yaml`.

**Issue structure:**

```markdown
## Plugin Insight: [section] — [principle]

**Source project:** [project title]
**Cycles validated:** [N]
**Average improvement:** +[X]% on [principle]
**Regressions:** [None observed / list]

### Change
[Specific change to plugin defaults]

### Evidence
| Cycle | Score Before | Score After | Delta |
|-------|-------------|-------------|-------|
| ...   | ...         | ...         | ...   |

### Recommendation
[What to update in the plugin]
```

**Labels:** `plugin-insight`, section label (e.g., `prose-craft`)

#### Plugin Defaults Update Path

1. Issues accumulate from projects
2. Plugin maintainer reviews issues — looks for patterns validated across multiple projects
3. Approved insights update `references/default-craft-weights.csv` and optionally craft engine text, evaluator prompts, or default voice guide templates
4. Future: automation that checks if multiple projects reported the same pattern and auto-creates a PR

### Author Calibration

#### `scenes/author-scores.csv`

Same column structure as `scene-scores.csv`. Most cells empty — author only scores what they feel strongly about.

```
id|economy_clarity|sentence_as_thought|enter_late_leave_early|...
the-finest-cartographer|8||6|...
the-footnote|3||||...
```

#### How the System Uses Author Scores

**Delta tracking:** When an author score exists alongside a system score, the delta is recorded in the tuning ledger. Over time, systematic biases emerge: "System consistently rates economy 2-3 points higher than this author does."

**Proposal filtering:** If the author has consistently overridden improvements for a principle (low author scores where system scores are high), the system stops proposing changes for that principle. The author's taste is sovereign.

**Calibration is project-level only.** Author taste preferences never become plugin insights. They represent individual aesthetic choices, not universal craft improvements.

#### Interactive Scoring Skill

`/storyforge:score` — an interactive skill that presents Claude's scores for a scene and invites the author to agree, adjust, or skip. Low-friction: the author sees the scores and only changes the numbers they disagree with.

### Script Integration

#### Changes to `prompt-builder.sh`

- New function: `build_weighted_directive(project_dir)` — reads `craft-weights.csv`, builds weighted summary of craft principles for prompt injection
- New function: `get_scene_overrides(scene_id, project_dir)` — reads current cycle's `overrides.csv` for scene-specific instructions
- Modify `build_scene_prompt()` — replace raw `extract_craft_sections` call with `build_weighted_directive` + scene overrides

#### Changes to `storyforge-write` and `storyforge-revise`

- After drafting/revision completes, suggest running `storyforge-score` if auto-scoring is enabled
- Read per-scene overrides when building prompts

#### New files in `scripts/`

- `scripts/storyforge-score` — main scoring script
- `scripts/lib/scoring.sh` — scoring library (diagnosis, proposal generation, tuning ledger management, pattern validation, issue submission)
- `scripts/prompts/scoring/` — prompt templates for each scoring group (scene-craft, prose-craft, character-craft, rules, act-level, novel-level)

#### New skill

- `skills/score/SKILL.md` — interactive scoring skill for author calibration and score review

### Cost Considerations

Scoring must be cheap enough to run frequently:

**Grouped mode (default):** ~5 invocations for scene-level + 2 for act/novel. Using Sonnet (analytical task). For a 100-scene manuscript: estimated ~$1-2 per full scoring run.

**Quick mode:** 1 invocation. Estimated ~$0.30-0.50.

**Deep mode:** ~23 invocations for scene-level alone. Estimated ~$5-8. Use sparingly.

All scoring invocations logged via `log_usage()` to the cost ledger with operation type `score`. The `estimate_cost` function in `costs.sh` needs a `score` case added (output estimate ~500 tokens per invocation — scoring returns structured data, not prose).

### Backward Compatibility

- Projects without `craft-weights.csv` continue using the existing `extract_craft_sections` injection. First `storyforge-score` run initializes the weights file.
- Projects without score history work normally — diagnosis simply has no delta to compare.
- The existing evaluation system (`storyforge-evaluate`) is unchanged and continues to work alongside scoring.

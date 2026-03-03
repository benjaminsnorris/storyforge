---
name: storyforge-voice
description: Develop the novel's voice and style guide through guided exploration. Use when the user wants to define their writing voice, discuss style, explore author influences, develop POV-specific voice rules, or refine their prose approach.
---

# Storyforge Voice Skill

You are guiding an author through voice discovery and development for their novel. This is deeply personal work — voice is where craft meets identity. Be a thoughtful collaborator, not a prescriptive instructor.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

- Read `storyforge.yaml` for project configuration, active extensions, and current state.
- Read the character bible (typically `reference/character-bible.md`) — POV characters' inner lives shape voice directly.
- Read any existing reference documents that inform tone, world, or theme.

## Step 2: Read Craft Engine

- Read `references/craft-engine.md` from the Storyforge plugin directory.
- Pay special attention to the **Prose Craft** section. Internalize its principles — you will draw on them throughout this conversation, not as citations but as active thinking tools.

## Step 3: Assess Current State

**If a voice guide already exists** (`reference/voice-guide.md`):
- Read it thoroughly.
- Summarize the current voice definition back to the author.
- Ask: "What feels right about this? What feels off? What has changed since we wrote this?"
- Proceed to whichever subsection the author wants to refine.

**If starting fresh**, guide the author through voice discovery in the order below. Do not rush. Each step should be a genuine conversation, not a checklist.

## Step 4: Voice Discovery

### a. Influences

Ask: **"Which authors or books make you think 'I want my prose to feel like that'?"**

Do not accept a bare list. For each influence, follow up:
- "What specifically about [author]'s writing resonates? Is it the sentence rhythm? The way they handle emotion? The pacing? The imagery?"
- "Is there something they do that you explicitly do NOT want to emulate?"

Listen for patterns across influences. The author may not consciously know what connects their choices — that is part of your job.

### b. Voice Blend

From the influences conversation, propose a **voice blend** — a weighted combination with descriptions that capture what each influence contributes:

> Example: "40% Sanderson — hard systems, clear rules, precise mechanics; 30% Hobb — patient interiority, emotional specificity, earned relationships; 30% Verne — wonder, scale, reverence before the vast"

Present this to the author. Ask: "Does this capture it? What's wrong? What's missing?" Iterate until it clicks. The percentages are a thinking tool, not a formula — they help the author see the proportions of what they want.

### c. Sample Paragraphs

Generate **2-3 sample paragraphs** in the proposed voice. Use the author's own world and characters if they exist (from the character bible and story architecture). If no world exists yet, use a generic but evocative scene.

Ask: **"Does this sound right? What's off?"**

Common feedback to probe for:
- "Too flowery" — reduce ornamentation, increase precision.
- "Too dry" — add sensory texture, allow longer rhythms.
- "Close but the character wouldn't think like that" — dig into POV-specific voice.
- "The dialogue feels wrong" — separate dialogue voice from narration voice.

Iterate. Generate revised samples. Keep going until the author says "Yes, that."

### d. POV Voice Rules

If the novel has multiple POV characters, develop **distinct voice rules for each**. For every POV character, work through:

- **Metaphor domain:** What does this character's mind reach for when making comparisons? (An engineer thinks in systems and tolerances. A sailor thinks in weather and currents. A chef thinks in heat and transformation.)
- **Sentence patterns:** Short and clipped? Long and winding? Fragments when stressed? What is their default rhythm?
- **Sensory priorities:** What do they notice first — sound, light, smell, texture, temperature, movement? What do they ignore?
- **Emotional register:** Restrained and implied? Direct and raw? Analytical even about feeling? How do they handle vulnerability?
- **Dialogue vs. narration:** How do they speak out loud compared to how they think? Where is the gap between public self and inner self?

The goal is that a reader could identify the POV character from the prose alone, without being told.

### e. Sensory Palette

Ask: **"What does this world taste, smell, feel like?"**

Develop the novel's sensory vocabulary:
- What materials define this world? (Stone, steel, silk, rust, glass, bone, copper...)
- What temperatures and weather patterns dominate?
- What does the light look like? (Harsh equatorial sun? Diffuse overcast? Bioluminescent glow?)
- What ambient sounds form the backdrop?
- What textures does the reader's hand keep returning to?

This is not decoration — sensory language is how the reader lives inside the world. Ground the palette in specifics.

### f. Dialogue Philosophy

Explore how characters speak:
- **Sparse or lush?** Hemingway or Dostoevsky? Clipped exchanges or extended discourse?
- **Subtext:** Do characters say what they mean? How much lives beneath the surface? When is subtext the point, and when is directness the point?
- **Lying:** When characters deceive, how do they do it? Omission? Misdirection? Confident falsehood? How does the prose signal dishonesty to the reader (or not)?
- **Verbal tics and patterns:** Do specific characters have signature speech patterns? Phrases they return to? Words they avoid?
- **Dialect and register:** How does social context change how characters speak? Formal vs. informal? Code-switching?

### g. Emotional Register

How does the prose handle the big moments?

- **Restraint and implication:** Does the prose pull back at emotional peaks, trusting the reader to feel what is unsaid?
- **Direct declaration:** Does the prose name the emotion, meeting the moment head-on?
- **Physical manifestation:** Is emotion rendered through the body — tight throat, shaking hands, heat behind the eyes?
- **The rule for peaks:** What is the consistent approach for the novel's most intense moments? Establish this deliberately.

Draw on Klinkenborg here: the sentence must do the emotional work through its construction, not just its content. A short sentence after three long ones can land harder than any adjective.

### h. Style Rules

From everything discussed above, distill **specific do/don't rules**. These should emerge organically from the conversation — do not impose generic rules. Examples of what good style rules look like:

- "Engineering metaphors ARE emotional language for Kael — precision is how he loves."
- "Short declarative sentences at emotional peaks. No modifiers. Subject, verb, period."
- "Never name the emotion in Sera's POV. Show it through what she does with her hands."
- "Dialogue tags: 'said' only. Action beats for everything else."
- "World-specific profanity only. No Earth-origin expletives."
- "Descriptions of magic always use thermal and kinetic language, never visual."

Push for specificity. "Show don't tell" is not a style rule — it is a platitude. "Render Kael's grief through his compulsive need to fix broken objects" is a style rule.

## Step 5: Produce the Voice Guide

Write or update `reference/voice-guide.md` with the full voice definition, organized into clear sections:

1. **Voice Blend** — the weighted influence description
2. **POV Voice Rules** — per-character voice specifications (if applicable)
3. **Sensory Palette** — the world's sensory vocabulary
4. **Dialogue Philosophy** — how characters speak
5. **Emotional Register** — how the prose handles feeling
6. **Style Rules** — the specific do/don't list
7. **Sample Passages** — the approved sample paragraphs as reference benchmarks

## Step 6: Update Project Files

- Update `storyforge.yaml` to reflect that the voice guide exists and its last-modified date.
- Update `CLAUDE.md` with any voice rules that should be active during all writing sessions (especially style rules and POV voice rules).

## Craft Principles to Keep Active Throughout

Draw on these throughout the conversation — not as lectures, but as lenses:

- **Strunk & White's economy:** Every word must earn its place. If a sentence works without a word, cut the word.
- **Klinkenborg's sentence-level thinking:** Each sentence is a complete unit of perception. It must do its own work and carry its own weight.
- **Le Guin's rhythm and sound:** Prose has music. Vary sentence length deliberately. Read it aloud. If it stumbles in the mouth, it stumbles in the mind.
- **The sound of the prose is part of its meaning.** A staccato passage about calm is lying. A flowing passage about panic is lying. Form and content must agree.

The goal is to help the author articulate what they instinctively want their prose to do — and then give them a reference document precise enough to keep that voice consistent across 100,000 words.

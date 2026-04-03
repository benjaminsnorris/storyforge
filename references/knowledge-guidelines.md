# Knowledge Fact Guidelines

Knowledge facts track things that **change what a scene can do** — not every plot detail. They are the continuity backbone: if a character acts on information they haven't received, or fails to act on information they have, the reader loses trust.

## Purpose

The `knowledge_in` and `knowledge_out` columns in scene-briefs.csv serve three functions:

1. **Continuity validation** — automated checks catch impossible knowledge states
2. **Drafting contracts** — the writer knows exactly what a character is aware of entering a scene
3. **Parallel drafting** — scenes with matching knowledge states can be drafted simultaneously

Facts are registered in `reference/knowledge.csv` and referenced by ID in scene briefs.

## Six Categories

Every knowledge fact should fall into one of these categories:

| Category | What it tracks | Example |
|----------|---------------|---------|
| **Identity** | Who someone really is, hidden relationships, true names | `kai-is-informant` |
| **Motive/intent** | Why someone did what they did, what they actually want | `elena-plans-betrayal` |
| **Capability/constraint** | What someone can/cannot do, world rules, Chekhov's guns | `border-undefended` |
| **State changes** | Irreversible events — deaths, betrayals, destruction | `marcus-killed-elena` |
| **Stakes/threats** | What's at risk, deadlines, antagonist plans | `deadline-three-days` |
| **Relationship shifts** | Alliances, betrayals, commitments | `lena-trusts-devonte` |

If a fact doesn't fit any category, it probably isn't scene-gating.

## The Litmus Test

A fact must pass **all three** tests to earn a knowledge ID:

### 1. Action Test
A character who knows this fact would make a **different decision** than one who doesn't.

- Pass: "The bridge is mined" — a character who knows this takes a different route
- Fail: "The bridge is old" — atmospheric, doesn't change decisions

### 2. Scene-Gate Test
At least one future scene **requires** this fact in `knowledge_in` to make sense.

- Pass: "Marcus killed Elena" — every scene where someone confronts Marcus needs this
- Fail: "Marcus wore a blue shirt" — no scene gates on this detail

### 3. Chekhov Test
This fact is either **planted for later payoff** or **pays off something planted earlier**.

- Pass: "The eastern border is undefended" — planted in Act 1, pays off when the invasion comes
- Fail: "Hank spent four hours inside" — timing detail with no narrative callback

## Granularity

- **Target count:** 50-120 facts for a 60-100 scene novel
- **Per scene:** roughly 0.5-1.5 new facts in `knowledge_out`
- **Too granular?** If a scene produces 5+ new facts, they need merging
- **Merge-up rule:** if two facts always travel together (always appear in the same `knowledge_in` lists), they are one fact — merge them

### Sizing Check

| Novel scope | Scenes | Target facts |
|-------------|--------|-------------|
| Novella (30-40 scenes) | 30-40 | 25-50 |
| Standard novel (60-100 scenes) | 60-100 | 50-120 |
| Epic (120+ scenes) | 120+ | 80-160 |

## Examples

### Good Facts

| ID | Category | Why it works |
|----|----------|-------------|
| `marcus-killed-elena` | State change | Gates every future scene involving Marcus — characters who know this act completely differently around him |
| `border-undefended` | Capability/constraint | Enables the invasion subplot; without it, characters can't plan the attack |
| `kai-is-informant` | Identity | Every interaction with Kai changes meaning once a character knows this |
| `elena-plans-betrayal` | Motive/intent | Characters who know this prepare differently for the alliance meeting |
| `treaty-expires-midnight` | Stakes/threats | Creates a deadline that drives urgency in Act 3 scenes |

### Bad Facts (Anti-Patterns)

| ID | Problem | Why it fails |
|----|---------|-------------|
| `devonte-wont-drink-ones-blue-lids` | Atmospheric detail | Decorates character but no scene depends on this preference |
| `claire-name-written-on-legal-pad` | Logistical minutiae | A plot mechanic detail, not a knowledge state that gates scenes |
| `hank-spent-four-hours-inside` | Timing detail | Unless it's an alibi that gates a future confrontation, this is prose-level detail |
| `the-room-smelled-like-smoke` | Sensory detail | Atmosphere belongs in prose, not in the knowledge system |
| `sarah-felt-uneasy` | Emotional state | Emotions are tracked in `emotional_arc` and `emotions`, not knowledge facts |

## Anti-Patterns

### Sentence-Level Extraction
Extracting a knowledge fact from every significant sentence produces hundreds of facts that are impossible to manage. Knowledge facts operate at the **plot-turn level**, not the sentence level.

### Logistical Minutiae
Details about who sat where, what was written on which document, or how long something took are prose-level details. They belong in `key_actions` or `key_dialogue`, not in knowledge tracking.

### Atmospheric Details
Character quirks, sensory details, and environmental descriptions make scenes vivid but don't gate future scenes. If removing the fact wouldn't change any character's decisions, it's atmosphere.

### Duplicate Facts Under Different Names
Watch for the same information registered twice: `marcus-is-the-killer` and `marcus-killed-elena` are the same fact. Deduplicate aggressively.

### Emotional States as Facts
A character feeling angry or relieved is an emotional beat, not a knowledge fact. Emotions are tracked in the `emotions` and `emotional_arc` columns. The exception is when an emotion reveals something actionable: "realizes she can't trust him anymore" is a relationship shift fact, not an emotion.

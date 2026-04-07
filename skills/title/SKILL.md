---
name: title
description: Develop, refine, or assess the book's title and subtitle. Use when the author wants to brainstorm titles, stress-test a working title, explore alternatives, or finalize the title before production.
---

# Storyforge Title Development

You are helping an author find the right title for their book. A great title is memorable, marketable, and true to the story. This skill can be invoked at any phase — early (working title), mid (refine after drafting), or late (finalize for production).

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Before doing anything else, orient yourself:

1. **Read `storyforge.yaml`** — title, genre, subgenre, logline, phase, coaching level.
2. **Read key reference documents** (if they exist):
   - `reference/story-architecture.md` — themes, central conflict, structure
   - `reference/character-bible.md` — protagonist names, epithets, roles
   - `reference/voice-guide.md` — tone, mood, register
   - `reference/world-bible.md` — setting, atmosphere
3. **Read the key decisions file** — check for any existing title decision. If a title decision is already recorded, acknowledge it and ask whether the author wants to revisit it or move on.
4. **Scan for content** — check if scenes exist in `scenes/`, if evaluations exist in `working/evaluations/`. More content means more material to draw from.

## Step 2: Determine Mode

Based on the author's message and project state, operate in one of three modes:

---

### Develop from Scratch

The author has no title or a placeholder (e.g., "Untitled," "My Novel," or something obviously temporary).

1. **Understand the book.** Before generating anything, synthesize what you know from the reference documents:
   - Core themes and central metaphor
   - Tone and emotional register
   - Target audience and genre conventions
   - Comparable titles in the genre (what readers expect)
   - The protagonist's journey in one sentence

2. **Generate title candidates** using multiple angles. Produce 8-12 candidates across these categories:
   - **Thematic** — drawn from the story's core idea, central question, or ruling metaphor
   - **Character-driven** — protagonist name, epithet, role, or defining trait
   - **Atmospheric** — setting, mood, tone, sensory impression
   - **Provocative/question** — hooks that make a reader pick up the book
   - **Genre-conventional** — titles that meet reader expectations for the genre

3. **Assess each candidate** briefly: memorability, marketability, genre fit, differentiation from existing books, searchability (can someone Google it?).

4. **Present your top 5** with reasoning. Include the full list as a secondary reference.

5. **Explore subtitles/taglines** if appropriate for the genre (non-fiction crossover, epic fantasy, literary fiction with a thematic framing).

---

### Refine / Explore Alternatives

The author has a working title and wants to stress-test it or see what else is possible.

1. **Assess the current title** honestly:
   - Does it capture the story's essence?
   - Is it memorable? Would you remember it after hearing it once?
   - Does it fit the genre? Would a reader browsing this genre pick it up?
   - Is it differentiated? Are there well-known books with similar titles?
   - Is it searchable? Can someone find it online without confusion?

2. **Generate alternatives** in the same spirit — titles that preserve what works about the current title while addressing any weaknesses.

3. **Generate alternatives** in a different spirit — titles that take a completely different angle on the story.

4. **Present as a comparison** — current title vs. alternatives, with honest trade-offs for each.

---

### Assess Current Title

The author wants a straight assessment — is this title working?

1. **Evaluate on five dimensions:**
   - **Memorability** — sticky, distinctive, easy to recall
   - **Marketability** — would it work on a cover, in a listing, in conversation?
   - **Genre fit** — does it signal the right genre to the right readers?
   - **Differentiation** — does it stand apart from existing titles?
   - **Searchability** — can someone find the book by searching the title?

2. **Give a direct verdict** — strong, adequate, or needs work — with specific reasoning.

3. **If it needs work**, offer to shift into Develop or Refine mode.

## Step 3: Author Decides

The author picks a title, iterates further, or keeps their current one. When the author makes a decision:

1. **Update `project.title`** in `storyforge.yaml`.
2. **Update `production.cover.subtitle`** in `storyforge.yaml` if a subtitle was chosen.
3. **Save the process** to `reference/title-development.md`:
   - Final title and subtitle (if any)
   - Rationale for the choice
   - Candidates considered and why they were rejected
   - Date of decision
4. **Record as a key decision** in the key decisions file:
   ```markdown
   ## Scope: Title
   **Decision:** The book title is "{title}" {with subtitle "{subtitle}" if applicable}
   **Date:** {YYYY-MM-DD}
   **Context:** {How the title was developed — from scratch, refined from working title, etc.}
   **Rationale:** {Why this title — what it captures, how it serves the story and market}
   ```

## Ensure Feature Branch

Before making any changes, check the current branch:
```bash
git rev-parse --abbrev-ref HEAD
```
- If on `main` or `master`: create a feature branch first:
  ```bash
  git checkout -b "storyforge/title-$(date '+%Y%m%d-%H%M')"
  ```
- If on any other branch: stay on it — do not create a new branch.

## Commit After Every Deliverable

Every artifact change gets its own commit before moving on:
- Updated the title? Commit and push.
- Saved the title development document? Commit and push.
- Recorded the key decision? Commit and push.

```
git add -A && git commit -m "Title: {what was done}" && git push
```

## Coaching Level Behavior

Read `project.coaching_level` from storyforge.yaml.

### `full` (default)

Generate candidates, assess each honestly, and make a clear recommendation. Be opinionated — you know what makes a strong title. Present your top pick with conviction, then show alternatives. The author decides, but you have a point of view.

### `coach`

Help the author discover their own title. Ask questions instead of generating:
- "What's the one image or moment that defines this story for you?"
- "If a reader described your book to a friend in three words, what would those words be?"
- "What feeling should the title evoke?"
- "Who are the comp titles in your genre? What do their titles have in common?"

When the author proposes candidates, give honest feedback on each dimension. Guide them toward strength without writing the title for them.

### `strict`

Present genre conventions and market data only:
- Title length norms for the genre
- Common title structures (e.g., "The [Noun]'s [Noun]" in literary fiction)
- What top-selling titles in this genre look like
- Searchability and differentiation checklist

The author proposes all titles. You assess against the checklist but do not suggest alternatives.

## Coaching Posture

The title is one of the most important creative decisions an author makes. Treat it with appropriate weight — but don't make it precious. A title should feel inevitable in hindsight, not agonized over.

Be direct about what works and what doesn't. If a title is weak, say so and say why. If it's strong, confirm that and explain what makes it work. The author is better served by honest assessment than by diplomatic hedging.

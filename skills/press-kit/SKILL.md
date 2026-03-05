---
name: press-kit
description: Produce a complete press kit for the book — blurbs, jacket copy, author bio, social media teasers, selling points, comp titles, and query pitch. Use when the author wants marketing copy, promotional materials, blurbs, or a press kit for their finished or near-finished book.
---

# Storyforge Press Kit

You are producing a complete press kit for a finished (or near-finished) book. This is a late-stage skill — the author has content to draw from. Every component is a separate file in `manuscript/press-kit/`, presented for approval before moving to the next.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Read Project State

Before doing anything else, orient yourself:

1. **Read `storyforge.yaml`** — title, genre, subgenre, logline, phase, coaching level, target word count.
2. **Read key reference documents** (all that exist):
   - `reference/story-architecture.md` — themes, structure, central conflict
   - `reference/character-bible.md` — protagonist and cast
   - `reference/voice-guide.md` — tone, mood, register
   - `reference/world-bible.md` — setting, atmosphere
   - `reference/key-decisions.md` — settled creative decisions
   - `scenes/scene-index.yaml` — scene count, structure
3. **Read evaluation synthesis** if it exists (`working/evaluations/synthesis.md` or most recent `findings.yaml`) — this tells you the manuscript's strengths, which are marketing gold.
4. **Check for existing press kit** — does `manuscript/press-kit/` already exist? If so, read existing components to understand what's been done.
5. **Verify content exists** — at least some scene files must exist in `scenes/`. A press kit needs story content to draw from. If no scenes exist, tell the author the press kit needs manuscript content and suggest drafting first.

## Step 2: Gather Author Context

Ask the author the following using `AskUserQuestion`, one at a time:

1. **Target audience** — "Who is the ideal reader for this book? Think demographics, reading habits, and what books they already love."

2. **Comparable titles** — "What are 3-5 books you'd place yours alongside on a shelf? These don't have to be perfect matches — 'for fans of X meets Y' positioning."

3. **Publication path** — "Are you planning to self-publish, query agents for traditional publication, or are you undecided?"

4. **Marketing tone** — "Should the marketing copy lean literary (emphasizes craft, theme, emotional depth) or commercial (emphasizes hook, stakes, pace)? Or somewhere in between?"

5. **Author bio context** — "Tell me about yourself as it relates to this book. What makes you the right person to write this story? Any relevant credentials, background, or personal connection?"

## Step 3: Generate Components

Create each component as a separate file in `manuscript/press-kit/`. Present each for approval or revision before moving to the next. Commit each file individually as it's approved.

Create the `manuscript/press-kit/` directory if it doesn't exist.

### Component 1: Short Blurb — `blurb-short.md`

Back cover / retail listing copy. 100-150 words.

- Open with the hook — the sentence that makes someone pick up the book
- Introduce the protagonist and their central problem
- Raise the stakes — what happens if they fail?
- End with a question or tension that demands resolution
- Do NOT reveal the ending

### Component 2: Long Blurb — `blurb-long.md`

Marketing page / detailed description. 250-400 words.

- Everything in the short blurb, expanded
- More context on the world and supporting characters
- Thematic resonance — what is this book really about?
- Pull quotes from evaluation synthesis if available (framed as editorial praise)
- Genre-appropriate tone throughout

### Component 3: Jacket Copy — `jacket-copy.md`

Front flap (hook + premise) and back flap (author context + positioning).

- **Front flap:** Expands the hook into a compelling narrative setup. More literary than the blurb — assumes the reader is already holding the book.
- **Back flap:** Brief author context, what inspired the book, and a sentence that positions it in the genre landscape.

### Component 4: Author Bio — `author-bio.md`

Three lengths for different contexts:

- **One-liner** (~15-20 words) — for social media profiles, contributor lists
- **Short** (~50 words) — for book listings, anthology credits
- **Full** (~150-200 words) — for the book's back matter, author website, press inquiries

All three should share the same voice and key facts, just at different resolutions.

### Component 5: Social Media — `social-media.md`

Platform-specific teasers:

- **Twitter/X** (280 characters) — hook + genre signal + call to action
- **Instagram caption** (~150 words) — more personal, behind-the-scenes tone, with hashtag suggestions
- **Longer post** (~250 words) — for Facebook, newsletter, blog. Story behind the story.

### Component 6: Selling Points — `selling-points.md`

3-5 bullet points for retailers and reviewers. Each bullet is one sentence that answers "why should I stock/review this book?"

- Lead with the strongest differentiator
- Mix craft strengths with market positioning
- Include comp title positioning

### Component 7: Comp Titles — `comp-titles.md`

Positioning against comparable books with rationale.

- 3-5 comp titles, each with:
  - Title and author
  - What this book shares with the comp
  - How this book differs or adds something new
- A positioning statement: "For readers who loved X but wished Y"

### Component 8: Query Pitch — `query-pitch.md`

Agent query paragraph. Only generate if the author indicated traditional publication path.

- One paragraph (~150-250 words)
- Hook, premise, stakes, protagonist, word count, genre, comp titles
- Professional tone — this is a business letter
- Follow standard query conventions

## Step 4: Generate Manifest

After all components are approved, generate `manuscript/press-kit/README.md`:

```markdown
# Press Kit — {Title}

Generated: {YYYY-MM-DD}

| Component | File | Words |
|-----------|------|-------|
| Short Blurb | [blurb-short.md](blurb-short.md) | {count} |
| Long Blurb | [blurb-long.md](blurb-long.md) | {count} |
| Jacket Copy | [jacket-copy.md](jacket-copy.md) | {count} |
| Author Bio | [author-bio.md](author-bio.md) | {count} |
| Social Media | [social-media.md](social-media.md) | {count} |
| Selling Points | [selling-points.md](selling-points.md) | {count} |
| Comp Titles | [comp-titles.md](comp-titles.md) | {count} |
| Query Pitch | [query-pitch.md](query-pitch.md) | {count} |
```

Commit the manifest:
```
git add -A && git commit -m "Press kit: generate manifest" && git push
```

## Commit After Every Deliverable

Every component gets its own commit as it's approved:

```
git add -A && git commit -m "Press kit: {component name}" && git push
```

Do not batch components. Each approval triggers its own commit and push.

## Coaching Level Behavior

Read `project.coaching_level` from storyforge.yaml.

### `full` (default)

Generate all copy yourself. Present each component for the author's refinement. Be opinionated about what works — you know marketing copy. Make a strong first draft and iterate from feedback.

### `coach`

Guide the author through each component with questions and structure, but don't write the copy:

- **Blurb:** "What's the one-sentence hook? Now expand it — what's at stake? Who's the reader rooting for?"
- **Jacket copy:** "Imagine someone picks up your book in a store. What do they read on the flap that makes them buy it?"
- **Author bio:** "What three things should a reader know about you?"
- **Social media:** "What's the behind-the-scenes moment that would make someone want to read this?"

Provide structural templates and word count targets. Review and give feedback on the author's drafts.

### `strict`

Provide checklists and word count targets per component only:

- Short blurb: 100-150 words. Must include: hook, protagonist, stakes, genre signal.
- Long blurb: 250-400 words. Must include: everything above plus world context, thematic depth, supporting cast.
- Jacket copy: Front flap (hook + premise), back flap (author + positioning).
- Author bio: Three lengths — one-liner, short (50w), full (150-200w).
- Social media: Platform-specific length constraints.
- Selling points: 3-5 bullets, one sentence each.
- Comp titles: 3-5 books with rationale.
- Query pitch: 150-250 words, standard query format.

The author writes everything. You assess completeness against the checklist but do not edit or suggest copy.

## Coaching Posture

Marketing copy is a different craft than novel writing. Many authors find it uncomfortable — they wrote a whole book and now they have to sell it in 150 words. Be encouraging but practical. The press kit exists to connect the book with readers who will love it.

Be direct about what works as marketing copy. Good prose and good marketing copy are not the same thing — a beautifully written blurb that doesn't hook is worse than a punchy one that does. The goal is to make readers pick up the book. Everything else is secondary.

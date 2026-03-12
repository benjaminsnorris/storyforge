---
name: annotate
description: Import author annotations from web book export and generate a revision plan. Use when the user has an annotations JSON or markdown file from reading their web book, or when they paste annotation notes directly.
---

# Storyforge: Import Annotations

Import annotations exported from the Storyforge web book reader and convert them into an actionable revision plan.

## Plugin Root

The plugin root is two levels up from this skill file.

## Step 1: Locate the Annotation File

Check for annotation export files:
1. Look in `working/` for files matching `annotations-*.json` or `annotations-*.md`
2. If the user pasted annotation content directly, parse it from the conversation
3. If no file found and nothing pasted, ask the user to provide their export file

## Step 2: Parse Annotations

**JSON format:**
- Read the file, parse the `annotations` array
- Each annotation has: `id`, `type`, `chapter`, `scene`, `anchor` (with `paragraphIndex`, `startOffset`, `endOffset`, `selectedText`), `comment`, `createdAt`

**Markdown format:**
- Parse by `## Chapter` and `### Scene:` headings
- Blockquotes (`>`) are selected text
- Lines after blockquotes are comments
- `(margin note)` suffix indicates margin notes

## Step 3: Validate Against Scene Files

For each annotation:
1. Map `scene` field to `scenes/{scene-id}.md`
2. Verify the scene file exists
3. Check if `selectedText` appears as a substring in the scene prose
4. If exact match fails, check for longest common substring (fuzzy match)
5. Annotations below 50% text overlap: flag as **stale** with a warning

Report validation summary:
- Total annotations
- Matched annotations
- Stale annotations (with quoted text for manual review)
- Annotations per scene (sorted by density — most-annotated first)

## Step 4: Categorize Notes

Read each annotation's comment and selected text. Categorize into:
- **Content** — rewrite, expand, cut, rephrase requests
- **Pacing** — too fast, too slow, dragging, rushing
- **Character** — voice, motivation, consistency
- **Continuity** — timeline issues, contradictions
- **Craft** — prose quality, word choice, repetition
- **Structure** — scene order, chapter breaks, transitions

Present the categorized summary to the user.

## Step 5: Generate Revision Plan

Build a revision plan ordered by scene, with the most-annotated scenes first:

For each scene with annotations:
1. List the scene file path
2. List all annotations with their categories
3. Quote the relevant text
4. Include the author's comment

Save the revision plan to `working/annotation-revision-plan.md`.

Then invoke `storyforge:plan-revision` to convert this into an executable revision pipeline, passing the annotation revision plan as input context.

## Coaching Level Behavior

- **full**: Parse annotations, validate, categorize, generate revision plan, invoke plan-revision
- **coach**: Parse and validate annotations, present categorized summary with recommendations, save analysis to `working/coaching/annotation-analysis.md`. Do not auto-generate revision plan — let the author decide what to revise
- **strict**: Parse and validate only. Present raw validated annotation list with stale warnings. Save to `working/coaching/annotation-checklist.md`. No categorization, no recommendations

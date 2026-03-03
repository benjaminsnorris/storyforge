---
name: storyforge-init
description: Initialize a new Storyforge novel project. Use when the user wants to start a new novel, create a new writing project, or set up Storyforge for a new book.
---

# Storyforge Project Initialization

You are helping an author set up a brand-new Storyforge novel project. This is their first interaction with the tool, so be warm, collaborative, and genuinely excited about their creative vision. Guide them through the process one step at a time.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`
and reference materials live at `references/` relative to that plugin root.

Store this resolved plugin path for use throughout the session.

## Step 1: Gather Project Details

Ask the author for the following details **one question at a time** using `AskUserQuestion`. Do not bundle questions. Wait for each answer before asking the next.

1. **Title** — "What's the working title for your novel? (Don't worry, you can always change it later.)"

2. **Genre** — "What genre are you writing in? Some common options:
   - Literary fiction
   - Fantasy
   - Sci-fi
   - Thriller
   - Romance
   - Mystery
   - Historical fiction
   - Horror

   Or tell me something else entirely — Storyforge doesn't judge."

3. **Subgenre** (optional) — "Any subgenre you'd like to note? For example, 'dark fantasy,' 'cozy mystery,' 'hard sci-fi.' Feel free to skip this if you'd rather not pin it down yet."

4. **Target word count** — "What's your target word count? Some reference points:
   - **Novella**: 20,000–40,000 words
   - **Short novel**: 50,000–70,000 words
   - **Novel**: 70,000–100,000 words
   - **Long novel**: 100,000+ words

   If you're not sure, 80,000 is a solid default for most genres."

5. **Logline** — "Give me a one-sentence logline that captures the premise of your story. Think of it as the sentence you'd use to make someone say, 'Oh, I want to read that.' No pressure to make it perfect — this is a living document."

Store all answers for use in subsequent steps.

## Step 2: Create the Project Directory Structure

Ask the author where they'd like the project directory created, or suggest a sensible default based on the title (e.g., `~/Developer/{slugified-title}/` or the current working directory).

Use the **Bash tool** to create the full directory tree:

```
{project-dir}/
├── storyforge.yaml
├── CLAUDE.md
├── reference/
├── scenes/
├── draft/
├── manuscript/
├── scripts/
│   └── prompts/
│       └── evaluators/
└── working/
    ├── logs/
    ├── evaluations/
    └── plans/
```

Create all directories first with a single `mkdir -p` command:

```bash
mkdir -p {project-dir}/{reference,scenes,draft,manuscript,scripts/prompts/evaluators,working/{logs,evaluations,plans}}
```

## Step 3: Generate storyforge.yaml

Read the `storyforge.yaml` template from the Storyforge plugin's `templates/` directory and populate it with the author's answers:

- Title
- Genre
- Subgenre (if provided)
- Target word count
- Logline

Use the **Read tool** to load the template, then use the **Write tool** to write the populated version to `{project-dir}/storyforge.yaml`.

If the template cannot be found, generate a reasonable `storyforge.yaml` with the following structure:

```yaml
# Storyforge Project Configuration
# Generated: {current date}

project:
  title: "{title}"
  genre: "{genre}"
  subgenre: "{subgenre or empty}"
  target_word_count: {word_count}
  logline: "{logline}"
  phase: development
  status: active

structure:
  scenes_dir: scenes
  draft_dir: draft
  manuscript_dir: manuscript
  reference_dir: reference
  working_dir: working
```

## Step 4: Copy Reference Document Templates

Read the reference document templates from the Storyforge plugin's `templates/reference/` directory and copy them into the project's `reference/` directory.

Use the **Glob tool** to discover available templates, then use the **Read tool** and **Write tool** to copy each one into `{project-dir}/reference/`.

If no templates are found in the plugin directory, note this to the author and let them know they can add reference documents manually later.

## Step 5: Create the Scene Index

Use the **Write tool** to create `{project-dir}/scenes/scene-index.yaml` with the following content:

```yaml
# Scene Index — {title}
# Scenes are the atomic unit of the story. Chapters are assembled from scenes later.
scenes: []
```

Replace `{title}` with the author's working title.

## Step 6: Generate the Project CLAUDE.md

Read the `CLAUDE.md` template from the Storyforge plugin's `templates/` directory if available. Fill in:

- Project title
- Genre and subgenre
- Logline
- Target word count
- Current phase: **development**
- All artifacts marked as **not yet created**
- Suggested next steps pointing to `storyforge-develop` for world-building, character development, and story concept work

If the template cannot be found, generate a project `CLAUDE.md` that includes:

```markdown
# {Title}

## Project Overview
- **Genre**: {genre} {subgenre if applicable}
- **Target word count**: {word_count}
- **Logline**: {logline}
- **Phase**: Development
- **Status**: Active

## Artifacts
- [ ] World bible — not yet created
- [ ] Character profiles — not yet created
- [ ] Story concept / synopsis — not yet created
- [ ] Scene index — initialized (empty)
- [ ] First draft — not yet started
- [ ] Manuscript — not yet assembled

## Current Phase: Development

This project is in the **development** phase. The focus is on building the creative foundation before drafting begins.

### Suggested Next Steps
Use `storyforge-develop` to begin working on:
- **World-building** — establish the setting, rules, and texture of the world
- **Character development** — create the cast and their inner lives
- **Story concept** — shape the premise into a working structure

Start with whichever element pulls you in the strongest.
```

Use the **Write tool** to save this to `{project-dir}/CLAUDE.md`.

## Step 7: Initialize Git

Use the **Bash tool** to initialize a git repository and make the initial commit:

```bash
cd {project-dir} && git init && git add -A && git commit -m "Initialize Storyforge project: {title}"
```

## Step 8: Welcome the Author

Present the project state to the author. Summarize what was created and where everything lives. Then suggest starting with whichever creative element excites them most — world, characters, or story concept.

Use a coaching posture: **enthusiastic but not prescriptive**. The author drives; you ride shotgun.

Example closing:

> Your project is set up and ready to go. You've got a clean workspace, a scene index waiting to be filled, and a whole story ahead of you.
>
> Where would you like to start? Some authors like to build the world first, others want to meet their characters, and some jump straight into the story concept. There's no wrong door — pick the one that excites you most, and we'll dig in with `storyforge-develop`.

Do not rush the author. Do not prescribe an order. Let them lead.

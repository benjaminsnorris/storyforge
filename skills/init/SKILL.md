---
name: init
description: Initialize a new Storyforge novel project. Use when the user wants to start a new novel, create a new writing project, or set up Storyforge for a new book.
---

# Storyforge Project Initialization

You are helping an author set up a brand-new Storyforge novel project. This is their first interaction with the tool, so be warm, collaborative, and genuinely excited about their creative vision. Guide them through the process one step at a time.

## Locating the Storyforge Plugin

The Storyforge plugin root is two levels up from this skill file's directory
(this skill's directory → `skills/` → plugin root). Scripts live at `scripts/`,
templates live at `templates/`, and reference materials live at `references/`
relative to that plugin root.

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

6. **Coaching level** — "How hands-on do you want Claude to be? This controls how much AI-generated content you'll see:
   - **Full** (default) — Claude proposes, generates, drafts, and revises. Maximum creative partnership.
   - **Coach** — Claude analyzes, plans, and critiques, but never writes prose. You write everything.
   - **Strict** — Claude only asks questions and produces checklists. Purely Socratic — you drive every decision.

   You can change this anytime in storyforge.yaml."

Store all answers for use in subsequent steps.

## Step 2: Create the Project Directory Structure

Ask the author where they'd like the project directory created, or suggest a sensible default based on the title (e.g., `~/Developer/{slugified-title}/` or the current working directory).

Use the **Bash tool** to create the full directory tree:

```
{project-dir}/
├── storyforge            (project runner — delegates to installed plugin)
├── storyforge.yaml
├── CLAUDE.md
├── reference/
│   └── key-decisions.md
├── scenes/
│   └── (scene .md files go here)
├── manuscript/
│   └── press-kit/        (marketing materials — blurbs, jacket copy, bios)
└── working/
    ├── pipeline.csv      (pipeline manifest — tracks eval/revision cycles)
    ├── logs/
    ├── evaluations/
    └── plans/
```

Create all directories first with a single `mkdir -p` command:

```bash
mkdir -p {project-dir}/{reference,scenes,manuscript/press-kit,working/{logs,evaluations,plans}}
```

Then create the initial pipeline manifest:

```bash
echo "cycle|started|status|evaluation|scoring|plan|review|recommendations|summary" > {project-dir}/working/pipeline.csv
```

Do NOT create a `draft/` directory. Storyforge works on scene files in `scenes/` throughout the entire pipeline — drafting, evaluation, and revision all operate on scenes. Manuscript assembly is a separate, late-stage step. The `manuscript/press-kit/` directory is created as a placeholder for marketing materials; the rest of `manuscript/` is populated by the assembly pipeline later.

Then copy the runner script from the plugin's `templates/storyforge-runner.sh` to the project root as `storyforge` and make it executable:

```bash
cp {plugin-root}/templates/storyforge-runner.sh {project-dir}/storyforge && chmod +x {project-dir}/storyforge
cp {plugin-root}/templates/gitignore {project-dir}/.gitignore
```

The runner script delegates to the installed plugin for `./storyforge write`, `./storyforge evaluate`, `./storyforge revise`, and `./storyforge assemble`. The `.gitignore` keeps logs, temp files, and generated output from cluttering git status.

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

## Step 5: Create the Scene CSV Files

Use the **Write tool** to create the two scene CSV files with headers only:

**`{project-dir}/reference/scene-metadata.csv`:**
```
id|seq|title|pov|location|part|type|timeline_day|time_of_day|status|word_count|target_words
```

**`{project-dir}/reference/scene-intent.csv`:**
```
id|function|emotional_arc|characters|threads|motifs|notes
```

## Step 6: Generate the Project CLAUDE.md

Generate a project `CLAUDE.md` that serves as **orientation only** — no status checklists, no artifact tracking, no phase display. Project state lives in `storyforge.yaml` and `working/pipeline.csv`.

```markdown
# {Title} — Storyforge Project

## About This Project
{genre} novel. {logline}

## Working with Storyforge
This project uses the Storyforge plugin for Claude Code. Key commands:
- `/storyforge:forge` — main hub, recommends what to work on next
- `./storyforge score` — score the manuscript against craft principles
- `./storyforge revise` — execute revision passes from a plan
- `./storyforge evaluate` — run multi-evaluator assessment
- `./storyforge write` — draft scenes autonomously

## Where to Find Things
- `storyforge.yaml` — project configuration (title, genre, phase, coaching level)
- `working/pipeline.csv` — pipeline history (evaluation/revision/scoring cycles)
- `reference/` — scene metadata, character bible, voice guide, world bible
- `scenes/` — scene prose files
- `working/scores/latest/` — most recent scoring results
- `working/evaluations/` — evaluation reports
- `working/plans/` — revision plans

## Standing Instructions
{Any author-specific instructions go here}
```

Use the **Write tool** to save this to `{project-dir}/CLAUDE.md`.

## Step 7: Initialize Git and Push

Use the **Bash tool** to initialize a git repository, make the initial commit, and push to a remote:

```bash
cd {project-dir} && git init && git add -A && git commit -m "Initialize Storyforge project: {title}"
```

Then ask the author if they have a remote repository to push to. If they provide a URL (e.g., a GitHub repo), set it up and push:

```bash
git remote add origin {url} && git push -u origin main
```

If they don't have one yet, let them know they can add one later. The important thing is that the repo exists locally — every Storyforge skill commits and pushes after each significant change so the repo always reflects the project's current state.

## Step 8: Welcome the Author

Present the project state to the author. Summarize what was created and where everything lives. Then suggest starting with whichever creative element excites them most — world, characters, or story concept.

Use a coaching posture: **enthusiastic but not prescriptive**. The author drives; you ride shotgun.

Example closing:

> Your project is set up and ready to go. You've got a clean workspace, a scene index waiting to be filled, and a whole story ahead of you.
>
> Where would you like to start? Some authors like to build the world first, others want to meet their characters, and some jump straight into the story concept. There's no wrong door — pick the one that excites you most, and we'll dig in with `/storyforge:develop`.

Do not rush the author. Do not prescribe an order. Let them lead.

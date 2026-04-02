# Elaboration Pipeline — Plan 2: Stages

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the elaboration pipeline stages — the scripts and skills that take a project from seed through validated briefs. Four stages (spine, architecture, scene map, briefs), each producing structured CSV data and reference materials, with validation gates between stages.

**Architecture:** New bash script `scripts/storyforge-elaborate` handles autonomous execution (API mode). New skill `skills/elaborate/SKILL.md` handles interactive sessions. Python prompt builders in `scripts/lib/python/storyforge/prompts_elaborate.py` construct stage-specific prompts. Each stage creates a branch, does the work, runs validation, and opens a PR.

**Tech Stack:** Python 3, bash, pipe-delimited CSV, Anthropic Messages API

**Spec:** `docs/superpowers/specs/2026-04-01-elaboration-pipeline-design.md`

---

## File Structure

### New files
- `scripts/storyforge-elaborate` — bash CLI for autonomous elaboration
- `scripts/lib/python/storyforge/prompts_elaborate.py` — prompt builders per stage
- `skills/elaborate/SKILL.md` — interactive elaboration skill

### Modified files
- `scripts/lib/python/storyforge/elaborate.py` — add response parsing helpers
- `templates/storyforge.yaml` — already updated in Plan 1

---

## Task 1: Prompt builders for each stage

Create `scripts/lib/python/storyforge/prompts_elaborate.py` with four functions that build the Claude prompt for each stage. Each reads the current project state and produces a prompt that tells Claude exactly what to produce and in what format.

**Key design:** Prompts instruct Claude to output structured CSV rows (pipe-delimited) wrapped in code fences, plus markdown for reference docs. A parser extracts both.

## Task 2: Response parsing

Add to `elaborate.py`: functions to parse Claude's response into CSV updates and markdown files. Claude outputs CSV rows in fenced blocks and markdown content in separate fenced blocks.

## Task 3: The `storyforge-elaborate` script

Bash script following the established patterns (source common.sh, detect_project_root, create_branch, create_draft_pr, invoke_anthropic_api, commit, run_review_phase). Accepts `--stage spine|architecture|map|briefs`, `--dry-run`, `--interactive`.

## Task 4: The `elaborate` skill

Interactive skill for Claude Code sessions. Routes based on project phase and author intent. Delegates to the script for autonomous work or handles stages interactively.

## Task 5: Tests, version bump, commit

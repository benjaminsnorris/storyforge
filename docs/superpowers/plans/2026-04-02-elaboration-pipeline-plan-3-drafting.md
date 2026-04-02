# Elaboration Pipeline — Plan 3: Drafting, Evaluation & Polish

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Modify the write script to draft from validated briefs in parallel waves. Add finding categorization to evaluation. Build the polish script. Add structural pre-draft scoring.

**Architecture:** New prompt builder `build_scene_prompt_from_briefs()` reads the three-file model. New wave planner computes dependency waves from `continuity_deps`. Polish script is a simplified revise targeting low craft scores. Evaluate synthesis prompt categorizes findings by fix location.

**Spec:** `docs/superpowers/specs/2026-04-01-elaboration-pipeline-design.md`

---

## Tasks

1. Wave planner — compute parallel drafting waves from continuity_deps
2. Brief-aware prompt builder — build_scene_prompt_from_briefs()
3. Modify storyforge-write to use briefs and waves when available
4. Structural pre-draft scoring — extend validate_structure
5. Evaluate finding categorization — modify synthesis prompt
6. Polish script — new storyforge-polish
7. Tests, version bump

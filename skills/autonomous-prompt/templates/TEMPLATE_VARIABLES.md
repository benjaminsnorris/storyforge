# Template Variables Reference

This document describes all template variables used in the autonomous implementation prompt templates.

## Base Template Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `{{ISSUE_NUMBER}}` | GitHub issue number | `171` |
| `{{ISSUE_TITLE}}` | Title of the GitHub issue | `Investigate additional deterministic scoring principles` |
| `{{BRIEF_DESCRIPTION}}` | Short description of what to implement | `additional deterministic scoring principles` |
| `{{ISSUE_TYPE}}` | Type of issue | `Scoring`, `Feature`, `Bug Fix`, `Creative`, `Pipeline`, `Refactoring` |
| `{{RELATED_ITEMS}}` | Related issues, PRs, plan docs | `#169, #168` |
| `{{GOAL_DESCRIPTION}}` | What needs to be accomplished | `Implement Wave 1 deterministic scorers...` |
| `{{SUCCESS_CRITERIA}}` | List of success criteria | `- Catches obvious deficits\n- Runs in <1s` |
| `{{RELEVANT_FILES}}` | Files to read before implementing | `cmd_score.py, repetition.py, exemplars.py` |
| `{{ISSUE_TYPE_STEPS}}` | Steps from the appropriate issue type template | (contents of scoring.md, feature.md, etc.) |
| `{{GENERATION_DATE}}` | Date when prompt was generated | `2026-04-14` |

## Issue Type Detection

The skill determines `{{ISSUE_TYPE}}` from GitHub issue labels:

| Labels | Issue Type |
|--------|------------|
| `scoring`, `evaluation`, `deterministic` | Scoring |
| `feature`, `enhancement` | Feature |
| `bug`, `fix` | Bug Fix |
| `creative`, `writing`, `drafting` | Creative |
| `pipeline`, `infrastructure` | Pipeline |
| `refactoring`, `refactor` | Refactoring |

If no matching label, infer from issue title and body. Defaults to `Feature`.

## Template Composition

The final prompt is composed by:

1. Reading `base-template.md`
2. Determining issue type from labels (or inference)
3. Reading the appropriate `additions/*.md` file
4. Replacing `{{ISSUE_TYPE_STEPS}}` with the addition content
5. Replacing all other variables with values from the issue

## Adding New Issue Types

To add a new issue type:

1. Create `additions/your-type.md` with the specific steps
2. Add the label mapping in `config/autonomous-workflow.yaml`
3. Add the template file mapping
4. Update this documentation

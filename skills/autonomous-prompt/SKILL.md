---
name: autonomous-prompt
description: Generate autonomous implementation prompts for GitHub issues, enabling complete implementation without user intervention. Use when asked to generate prompts for issues like 'prompt for issue #XX', 'create prompt', or 'generate implementation prompt'.
---

# USAGE

```
/autonomous-prompt <issue-number>
```

**Examples:**
- `/autonomous-prompt 171` - Generate prompt and execute (standard)
- `/autonomous-prompt 171 --no-exec` - Generate prompt only, don't execute
- `/autonomous-prompt 171 --exec-only` - Execute existing prompt (skip generation)

**What happens:**
1. Fetches issue details from GitHub
2. Generates comprehensive implementation prompt
3. Saves to `prompts/implement-issue-XX.md`
4. Creates draft PR linked to issue
5. Executes the prompt autonomously

---

# Troubleshooting

### Prompt Generation Fails
```
Error: Could not fetch issue #XX
```
**Solution**: Verify issue exists and you have access: `gh issue view XX`

### Draft PR Already Exists
```
Error: PR already exists for branch
```
**Solution**: The skill will detect and reuse existing PRs. No action needed.

### Branch Already Exists
The skill checks for an existing branch matching the issue. If found, it stays on that branch per CLAUDE.md rules (never create a new branch when already on a non-main branch).

---

# Autonomous Implementation Prompt Skill

Generate a world-class autonomous implementation prompt for a GitHub issue that enables complete, thorough implementation without user intervention.

## Configuration

All configurable values are in `config/autonomous-workflow.yaml`:
- Iteration limits by issue type
- Commands for build/test/format
- Completion signals

## Locating the Storyforge Plugin

```python
# Resolve plugin root — needed for templates and config
import os
plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Or from a skill context: read .claude-plugin/plugin.json to find root
```

In practice, the skill runs inside the plugin repo, so paths are relative to the repo root.

## Process Overview

### Phase 1: Understand the Issue

1. **Fetch issue details**
   ```bash
   gh issue view <number> --json number,title,body,labels
   ```

2. **Analyze the issue**
   - What is being requested?
   - Is this scoring, a feature, a bug fix, creative work, pipeline work, or refactoring?
   - What are the success criteria?
   - Are there related issues or PRs?

3. **Determine scope and type from labels**
   - See `config/autonomous-workflow.yaml` for label-to-type mapping
   - Type determines which template additions to use
   - If no matching label, infer from issue title/body

4. **Label issue as in-progress** (if not already)
   ```bash
   gh issue edit <number> --add-label "in-progress"
   ```

### Phase 2: Generate the Prompt

1. **Load base template** from `templates/base-template.md`

2. **Load issue-type additions** from `templates/additions/`:
   - `scoring.md` for scoring/evaluation work
   - `feature.md` for new features
   - `bug-fix.md` for bug fixes
   - `creative.md` for creative/writing pipeline work
   - `pipeline.md` for pipeline/infrastructure work
   - `refactoring.md` for refactoring

3. **Replace template variables** (see `templates/TEMPLATE_VARIABLES.md`):
   - `{{ISSUE_NUMBER}}`, `{{ISSUE_TITLE}}`, `{{ISSUE_TYPE}}`
   - `{{SUCCESS_CRITERIA}}`, `{{RELEVANT_FILES}}`
   - `{{ISSUE_TYPE_STEPS}}` with the addition content

4. **Add codebase-specific context**
   - Include relevant module paths from CLAUDE.md
   - Include existing test patterns from `tests/`
   - Include shared utility references

### Phase 3: Save Prompt, Create Draft PR

1. **Determine filename**
   ```bash
   # Pattern: implement-issue-XX-brief-description.md
   prompts/implement-issue-171-deterministic-scoring.md
   ```

2. **Ensure correct branch**
   - If on main: create `storyforge/{type}-{timestamp}` branch
   - If on a non-main branch: stay on it

3. **Save to prompts directory**
   ```bash
   # Write generated prompt to file
   cat > prompts/implement-issue-XX-description.md <<'EOF'
   [Generated prompt content]
   EOF
   ```

4. **Commit and push**
   ```bash
   git add prompts/implement-issue-XX-description.md
   git commit -m "Add autonomous implementation prompt for issue #XX"
   git push
   ```

5. **Create or reuse draft PR**
   ```bash
   # Check for existing PR first
   EXISTING_PR=$(gh pr list --state open --head "$(git branch --show-current)" --json number,url --jq '.[0]')

   if [ -n "$EXISTING_PR" ]; then
     PR_NUM=$(echo "$EXISTING_PR" | jq -r '.number')
     echo "Reusing existing PR #$PR_NUM"
   else
     gh pr create --draft \
       --title "${ISSUE_TITLE}" \
       --label "in-progress" \
       --body "## Summary
   Implementation in progress for #XX.

   ## Related
   - Closes #XX"
   fi
   ```

### Phase 4: Execute the Prompt

1. **Read the saved prompt**
   ```bash
   Read prompts/implement-issue-XX-description.md
   ```

2. **Follow the prompt instructions autonomously**
   - Work through all phases: Pre-Implementation, Implementation, Quality Assurance, PR
   - Commit and push after every logical change
   - Run tests frequently

3. **Signal completion**
   - On success: ensure PR is ready for review
   - If blocked: document the blocker in the PR and issue

## Commit After Every Deliverable

Per CLAUDE.md, every change must be committed and pushed immediately:
```bash
git add -A && git commit -m "prefix: description" && git push
```

Use domain-specific prefixes from CLAUDE.md (Add, Update, Fix, Score, etc.).

## Coaching Level Behavior

This skill operates at the implementation level and is not affected by coaching level settings. It always generates and executes prompts autonomously.

## Implementation Metrics

Track these metrics throughout implementation:

| Category | Metric | How to Collect |
|----------|--------|----------------|
| **Efficiency** | Total Commits | `git rev-list --count origin/main..HEAD` |
| | Files Changed | `git diff --name-only origin/main..HEAD \| wc -l` |
| | Lines Added/Removed | `git diff --stat origin/main..HEAD \| tail -1` |
| **Quality** | Test Failures | Count during implementation |
| | Tests Added | `git diff --name-only origin/main..HEAD \| grep test_ \| wc -l` |
| **Review** | Review Rounds | Count after PR review |

## Completion Signals

**On Success:**
```
IMPLEMENTATION_COMPLETE
```

**When Blocked:**
```
BLOCKED_NEEDS_HUMAN
```

## Directory Structure

```
skills/autonomous-prompt/
├── SKILL.md                      # This file
├── config/
│   └── autonomous-workflow.yaml  # Configurable values
└── templates/
    ├── base-template.md          # Core prompt structure
    ├── TEMPLATE_VARIABLES.md     # Variable reference
    └── additions/
        ├── scoring.md            # Scoring/evaluation work
        ├── feature.md            # New features
        ├── bug-fix.md            # Bug fixes
        ├── creative.md           # Creative/writing pipeline
        ├── pipeline.md           # Pipeline/infrastructure
        └── refactoring.md        # Refactoring
```

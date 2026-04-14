## Creative/Writing Pipeline Steps

### 1. Understand the Creative Context
- [ ] Read `storyforge.yaml` for project settings and coaching level
- [ ] Read relevant CSV files (`scenes.csv`, `scene-intent.csv`, `scene-briefs.csv`)
- [ ] Understand which scenes/chapters are affected
- [ ] Check `reference/voice-profile.csv` for voice constraints

### 2. Respect Coaching Level
- [ ] Check `project.coaching_level` in storyforge.yaml
- [ ] **full**: Act as creative partner — draft, revise, propose
- [ ] **coach**: Analyze, brief, critique — no prose generation
- [ ] **strict**: Report data, provide commands — no creative proposals

### 3. Implement the Creative Feature
- [ ] Use `select_model(task_type)` for appropriate model selection
- [ ] Use `invoke_api()` for Claude API calls
- [ ] Follow the brief-aware drafting pattern if writing prose
- [ ] Use pipe-delimited CSV for any metadata changes

### 4. Validate Output
- [ ] Scene files are pure prose markdown (no YAML frontmatter)
- [ ] CSV files maintain schema integrity
- [ ] Word counts are updated in `scenes.csv` if prose was modified
- [ ] No AI-tell vocabulary introduced (check against `references/ai-tell-words.csv`)

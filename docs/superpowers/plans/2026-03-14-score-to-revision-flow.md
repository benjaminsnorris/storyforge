# Score-to-Revision Flow Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add novel-level narrative scoring with radar chart visualization, and fix the score→revision pipeline by connecting scoring proposals to revision planning and consuming overrides during revision.

**Architecture:** Extract narrative principles from per-scene scoring into a dedicated novel-level pass in `storyforge-score`. Add a radar chart panel to `storyforge-visualize`. Update `plan-revision` skill to read scoring data. Update `storyforge-revise` to inject overrides into revision prompts.

**Tech Stack:** Bash, jq, SVG (vanilla JS), Anthropic Messages API

---

## Chunk 1: Narrative Scoring

### Task 1: Remove narrative principles from scene-level scoring

**Files:**
- Modify: `references/diagnostics.csv` (verify no narrative rows — confirmed none exist)
- Modify: `scripts/storyforge-score` (skip narrative principles in scene scoring)
- Modify: `scripts/lib/scoring.sh` (exclude narrative from scene diagnosis)

- [ ] **Step 1: Add NARRATIVE_PRINCIPLES exclusion list to storyforge-score**

After the weights/diagnostics loading section (around line 457), add:

```bash
# Narrative principles are scored at novel level, not per scene
NARRATIVE_PRINCIPLES="campbells_monomyth three_act save_the_cat truby_22 harmon_circle kishotenketsu freytag"
```

- [ ] **Step 2: Filter narrative principles from scene evaluation criteria**

In `build_evaluation_criteria` or the `WEIGHTED_TEXT` generation, exclude principles where section=narrative. The `build_weighted_text` function in scoring.sh reads craft-weights.csv — add a filter:

In `scoring.sh`, find `build_weighted_text()` and add a `section != "narrative"` filter to the awk that reads weights. This ensures scene-level prompts don't ask about narrative frameworks.

- [ ] **Step 3: Filter narrative from diagnosis generation**

In `generate_diagnosis()` in scoring.sh, the function reads all score files. Add logic to skip narrative principles when processing scene-scores.csv (they won't exist there after this change, but belt-and-suspenders).

- [ ] **Step 4: Run scoring tests**

Run: `./tests/run-tests.sh tests/test-scoring.sh`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/storyforge-score scripts/lib/scoring.sh
git commit -m "Score: exclude narrative principles from scene-level scoring"
```

---

### Task 2: Add novel-level narrative scoring pass

**Files:**
- Modify: `scripts/storyforge-score` (add narrative scoring section after novel-level character/genre scoring)
- Create: `scripts/prompts/novel-narrative.md` (narrative evaluation template)

- [ ] **Step 1: Create the narrative evaluation prompt template**

Create `scripts/prompts/novel-narrative.md`:

```markdown
You are evaluating the narrative structure of "{{PROJECT_TITLE}}".

## Your Task

Score how well this manuscript aligns with each of the 7 narrative frameworks below. This is NOT about whether the manuscript SHOULD follow each framework — it's about measuring how strongly each framework's structural patterns are present.

A score of 1 means "not using this framework" (which is a valid creative choice). A score of 5 means "strongly aligned with this framework's structure."

## The Manuscript

### Story Architecture
{{STORY_ARCHITECTURE}}

### Scene Index
{{SCENE_INDEX}}

### Chapter Structure
{{CHAPTER_MAP}}

## Narrative Frameworks to Evaluate

1. **Campbell's Monomyth** — Departure (call, refusal, threshold), Initiation (trials, ordeal, reward), Return (road back, resurrection, elixir)
2. **Three Act Structure** — Setup (inciting incident, first plot point), Confrontation (rising action, midpoint, second plot point), Resolution (climax, denouement)
3. **Save the Cat** — Opening image, theme stated, set-up, catalyst, debate, break into two, B story, fun and games, midpoint, bad guys close in, all is lost, dark night, break into three, finale, final image
4. **Truby's 22 Steps** — Self-revelation, need, desire, opponent, plan, battle, drive, attack by ally, obsessive drive, changed drive, moral decision, self-revelation, equilibrium
5. **Harmon Circle** — You (comfort zone), Need (want something), Go (unfamiliar), Search (adapt), Find (get it), Take (pay for it), Return (go back), Change (have changed)
6. **Kishotenketsu** — Ki (introduction), Sho (development), Ten (twist/complication without conflict), Ketsu (reconciliation/conclusion)
7. **Freytag's Pyramid** — Exposition, rising action, climax, falling action, denouement

## Output Format

For each framework, provide:

{{SCORES:}}
principle|score
campbells_monomyth|N
three_act|N
save_the_cat|N
truby_22|N
harmon_circle|N
kishotenketsu|N
freytag|N
{{END_SCORES}}

{{RATIONALE:}}
principle|rationale
campbells_monomyth|Your analysis of how the manuscript maps to this framework...
three_act|...
save_the_cat|...
truby_22|...
harmon_circle|...
kishotenketsu|...
freytag|...
{{END_RATIONALE}}
```

- [ ] **Step 2: Add narrative scoring pass to storyforge-score**

After the novel-level character/genre scoring section (after line ~847), add a new section:

```bash
# ============================================================================
# Novel-level narrative framework scoring
# ============================================================================

log ""
log "============================================"
log "Narrative Framework Scoring"
log "============================================"

NARRATIVE_TEMPLATE_FILE="${PROMPTS_DIR}/novel-narrative.md"
if [[ ! -f "$NARRATIVE_TEMPLATE_FILE" ]]; then
    log "WARNING: Narrative template not found at ${NARRATIVE_TEMPLATE_FILE}, skipping"
else
    NARRATIVE_TEMPLATE=$(cat "$NARRATIVE_TEMPLATE_FILE")

    # Build context: story architecture, scene index, chapter map
    STORY_ARCH=""
    [[ -f "${PROJECT_DIR}/reference/story-architecture.md" ]] && STORY_ARCH=$(cat "${PROJECT_DIR}/reference/story-architecture.md")

    SCENE_INDEX=""
    if [[ -f "$METADATA_CSV" ]]; then
        SCENE_INDEX=$(awk -F'|' 'NR==1 || $NF != "cut" { print }' "$METADATA_CSV")
    fi

    CHAPTER_MAP_TEXT=""
    CHAPTER_MAP_FILE="${PROJECT_DIR}/reference/chapter-map.csv"
    [[ -f "$CHAPTER_MAP_FILE" ]] && CHAPTER_MAP_TEXT=$(cat "$CHAPTER_MAP_FILE")

    # Substitute template
    NARRATIVE_PROMPT="$NARRATIVE_TEMPLATE"
    NARRATIVE_PROMPT="${NARRATIVE_PROMPT//\{\{PROJECT_TITLE\}\}/$PROJECT_TITLE}"
    NARRATIVE_PROMPT="${NARRATIVE_PROMPT//\{\{STORY_ARCHITECTURE\}\}/$STORY_ARCH}"
    NARRATIVE_PROMPT="${NARRATIVE_PROMPT//\{\{SCENE_INDEX\}\}/$SCENE_INDEX}"
    NARRATIVE_PROMPT="${NARRATIVE_PROMPT//\{\{CHAPTER_MAP\}\}/$CHAPTER_MAP_TEXT}"

    NARRATIVE_LOG="${LOG_DIR}/narrative-scoring.json"
    NARRATIVE_MODEL=$(select_model "evaluation")

    log "Scoring narrative frameworks (model: ${NARRATIVE_MODEL})..."

    _SF_INVOCATION_START=$(date +%s)
    export _SF_INVOCATION_START

    if invoke_anthropic_api "$NARRATIVE_PROMPT" "$NARRATIVE_MODEL" "$NARRATIVE_LOG" 4096; then
        log_api_usage "$NARRATIVE_LOG" "score" "narrative" "$NARRATIVE_MODEL"

        # Extract response and parse scores
        NARRATIVE_TEXT="${LOG_DIR}/narrative-scoring.txt"
        extract_api_response "$NARRATIVE_LOG" > "$NARRATIVE_TEXT"

        NARRATIVE_SCORES="${CYCLE_DIR}/narrative-scores.csv"
        NARRATIVE_RATIONALE="${CYCLE_DIR}/narrative-rationale.csv"

        parse_score_output "$NARRATIVE_TEXT" "$NARRATIVE_SCORES" "$NARRATIVE_RATIONALE" "SCORES" "RATIONALE"

        if [[ -f "$NARRATIVE_SCORES" ]]; then
            log "Narrative scores saved to $(basename "$NARRATIVE_SCORES")"
        else
            log "WARNING: Failed to parse narrative scores"
        fi
    else
        log "WARNING: Narrative scoring API call failed"
    fi
fi
```

- [ ] **Step 3: Update the "latest" symlink section to include narrative scores**

In the section that copies/symlinks scores to `working/scores/latest/`, ensure `narrative-scores.csv` and `narrative-rationale.csv` are included.

- [ ] **Step 4: Test with dry-run**

Run: `./storyforge-score --dry-run` from a novel project.
Expected: Narrative scoring section appears in dry-run output.

- [ ] **Step 5: Commit**

```bash
git add scripts/storyforge-score scripts/prompts/novel-narrative.md
git commit -m "Score: add novel-level narrative framework scoring pass"
```

---

## Chunk 2: Radar Chart Visualization

### Task 3: Add narrative radar chart to dashboard

**Files:**
- Modify: `scripts/storyforge-visualize` (add HTML panel + JS render function + data injection)

- [x] **Step 1: Add data injection for narrative scores**

In the data injection section (around line 659-668 where CSV data is converted to JSON), add:

```bash
# Narrative scores (novel-level)
NARRATIVE_SCORES_CSV="${SCORES_DIR}/narrative-scores.csv"
NARRATIVE_JSON="[]"
if [[ -f "$NARRATIVE_SCORES_CSV" ]]; then
    NARRATIVE_JSON=$(awk -F'|' 'NR>1 && $1 != "" {
        gsub(/"/, "\\\"", $2)
        printf "%s{\"principle\":\"%s\",\"score\":%s}", (NR>2?",":""), $1, $2
    }' "$NARRATIVE_SCORES_CSV")
    NARRATIVE_JSON="[${NARRATIVE_JSON}]"
fi
```

Inject into the HTML template:
```javascript
const NARRATIVE_SCORES = ${NARRATIVE_JSON};
```

- [x] **Step 2: Add HTML panel after the heatmap section**

After the heatmap `</div>` (around line 628), insert:

```html
<!-- 9. Narrative Framework Radar -->
<div class="section" id="narrative-radar-section" style="display:none;">
    <div class="section-header">
        <span class="dot"></span>
        <h2>Narrative Framework Radar</h2>
        <span class="subtitle">Novel-level alignment with 7 narrative structures</span>
    </div>
    <div class="vis-container" id="narrative-radar"></div>
</div>
```

- [x] **Step 3: Add radar chart render function**

After the heatmap render function, add the narrative radar renderer:

```javascript
(function renderNarrativeRadar() {
    if (!NARRATIVE_SCORES || NARRATIVE_SCORES.length === 0) return;
    document.getElementById('narrative-radar-section').style.display = '';
    const container = document.getElementById('narrative-radar');

    const W = 500, H = 500;
    const CX = W / 2, CY = H / 2;
    const R = 180; // max radius
    const RINGS = 5;
    const principles = NARRATIVE_SCORES;
    const N = principles.length;
    const angleStep = (2 * Math.PI) / N;
    const startAngle = -Math.PI / 2; // top

    const svg = makeSvg(container, W, H);

    // Draw concentric rings
    for (let ring = 1; ring <= RINGS; ring++) {
        const r = (ring / RINGS) * R;
        svg.appendChild(svgEl('circle', {
            cx: CX, cy: CY, r: r,
            fill: 'none', stroke: 'var(--border)', 'stroke-width': 0.5,
            'stroke-dasharray': ring < RINGS ? '2,3' : 'none'
        }));
        // Ring label
        svg.appendChild(svgEl('text', {
            x: CX + 4, y: CY - r + 12,
            'font-family': 'var(--font-mono)', 'font-size': 9,
            fill: 'var(--text-dim)', opacity: 0.6
        })).textContent = ring;
    }

    // Draw spokes and wedges
    const points = [];
    principles.forEach((p, i) => {
        const angle = startAngle + i * angleStep;
        const score = parseInt(p.score) || 0;
        const r = (score / RINGS) * R;

        // Spoke line
        const spokeX = CX + Math.cos(angle) * R;
        const spokeY = CY + Math.sin(angle) * R;
        svg.appendChild(svgEl('line', {
            x1: CX, y1: CY, x2: spokeX, y2: spokeY,
            stroke: 'var(--border)', 'stroke-width': 0.5
        }));

        // Data point
        const px = CX + Math.cos(angle) * r;
        const py = CY + Math.sin(angle) * r;
        points.push({ x: px, y: py, score, principle: p.principle });

        // Label
        const labelR = R + 24;
        const lx = CX + Math.cos(angle) * labelR;
        const ly = CY + Math.sin(angle) * labelR;
        const anchor = Math.abs(angle) < 0.1 || Math.abs(angle - Math.PI) < 0.1
            ? 'middle' : (lx > CX ? 'start' : 'end');
        const label = p.principle.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        svg.appendChild(svgEl('text', {
            x: lx, y: ly + 4, 'text-anchor': anchor,
            'font-family': 'var(--font)', 'font-size': 11,
            fill: 'var(--text)', 'font-weight': 500
        })).textContent = label;

        // Score value at point
        svg.appendChild(svgEl('text', {
            x: px, y: py - 8, 'text-anchor': 'middle',
            'font-family': 'var(--font-mono)', 'font-size': 10,
            fill: 'var(--text)', 'font-weight': 700
        })).textContent = score;
    });

    // Draw filled polygon
    if (points.length > 0) {
        const polyPoints = points.map(p => `${p.x},${p.y}`).join(' ');
        svg.appendChild(svgEl('polygon', {
            points: polyPoints,
            fill: 'var(--score-high)', 'fill-opacity': 0.15,
            stroke: 'var(--score-high)', 'stroke-width': 2
        }));

        // Draw score dots
        points.forEach(p => {
            const color = p.score <= 1 ? 'var(--score-low)' :
                          p.score <= 2 ? 'var(--score-mid-low)' :
                          p.score <= 3 ? 'var(--score-mid)' :
                          p.score <= 4 ? 'var(--score-mid-high)' :
                          'var(--score-high)';
            svg.appendChild(svgEl('circle', {
                cx: p.x, cy: p.y, r: 5,
                fill: color, stroke: 'var(--surface)', 'stroke-width': 2
            }));
        });
    }
})();
```

- [x] **Step 4: Test dashboard generation**

Run `./storyforge visualize` from a novel project with scores.
Expected: Dashboard generates without errors. If narrative scores exist, radar chart appears.

- [x] **Step 5: Commit**

```bash
git add scripts/storyforge-visualize
git commit -m "Visualize: add narrative framework radar chart to dashboard"
```

---

## Chunk 3: Pipeline Fixes

### Task 4: plan-revision reads scoring data

**Files:**
- Modify: `skills/plan-revision/SKILL.md` (add scoring data to files read)

- [ ] **Step 1: Update Step 1 (Read Evaluation Results) to also read scoring data**

In the "Files Read" section, add after evaluation findings:

```markdown
### Scoring Data (if available)

If a scoring cycle has run, also read:
- `working/scores/latest/diagnosis.csv` — principle-level strength/weakness analysis with priorities
- `working/scores/latest/proposals.csv` — recommended improvements from scoring
- `working/scores/latest/narrative-scores.csv` — novel-level narrative framework alignment

Use scoring data to supplement evaluation findings:
- High-priority craft deficits from `diagnosis.csv` should inform pass design (e.g., if `economy_clarity` scores low across many scenes, include a prose-tightening pass)
- Proposals from `proposals.csv` with `voice_guide` or `scene_intent` levers provide specific guidance for passes
- Narrative scores provide context about the manuscript's structural approach (informational, not deficit-driven)
```

- [ ] **Step 2: Update Step 3 (Design Revision Passes) to integrate scoring**

Add guidance for how scoring data shapes passes:

```markdown
### Integrating Scoring Data

When scoring data is available alongside evaluation findings:
1. **Cross-reference**: If both evaluation findings and scoring diagnosis flag the same principle, increase that pass's priority
2. **Add scoring-informed passes**: If scoring diagnosis identifies high-priority deficits not covered by evaluation findings, add targeted passes for those
3. **Include proposals as guidance**: When creating a pass that addresses a scored principle, incorporate relevant proposals from `proposals.csv` into the pass's guidance field
4. **Narrative context**: Mention the manuscript's narrative profile (from `narrative-scores.csv`) in passes that affect structure, but don't treat low narrative scores as deficits
```

- [ ] **Step 3: Commit**

```bash
git add skills/plan-revision/SKILL.md
git commit -m "Plan-revision: read scoring data to inform revision passes"
```

---

### Task 5: storyforge-revise consumes overrides.csv

**Files:**
- Modify: `scripts/lib/revision-passes.sh` (inject overrides into revision prompt)

- [ ] **Step 1: Find the prompt building section in revision-passes.sh**

The pass configuration is built around lines 259-274. After the protection list injection, add overrides injection:

```bash
# Inject relevant overrides from scoring proposals
local overrides_file="${PROJECT_DIR}/working/scores/latest/overrides.csv"
local overrides_section=""
if [[ -f "$overrides_file" ]]; then
    # Filter overrides relevant to this pass's targets
    local relevant_overrides=""
    if [[ -n "$_csv_targets" ]]; then
        # Match overrides by scene ID
        IFS=';' read -ra target_ids <<< "$_csv_targets"
        for tid in "${target_ids[@]}"; do
            local tid_trimmed
            tid_trimmed=$(echo "$tid" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
            local scene_overrides
            scene_overrides=$(awk -F'|' -v id="$tid_trimmed" 'NR>1 && $1 == id { print "- [" $1 "] " $2 ": " $3 }' "$overrides_file")
            [[ -n "$scene_overrides" ]] && relevant_overrides="${relevant_overrides}${scene_overrides}\n"
        done
    else
        # Full-scope pass — include all overrides
        relevant_overrides=$(awk -F'|' 'NR>1 { print "- [" $1 "] " $2 ": " $3 }' "$overrides_file")
    fi

    if [[ -n "$relevant_overrides" ]]; then
        overrides_section="
## Scoring Overrides

The following craft directives were approved during scoring. Apply them during this revision:

$(echo -e "$relevant_overrides")
"
    fi
fi
```

Then append `$overrides_section` to the pass configuration block.

- [ ] **Step 2: Run revision dry-run test**

Run: `./tests/run-tests.sh tests/test-dry-run.sh`
Expected: Revise dry-run still passes (overrides section only appears when overrides.csv exists).

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/revision-passes.sh
git commit -m "Revise: consume overrides.csv during revision passes"
```

---

### Task 6: Update score skill to display narrative profile

**Files:**
- Modify: `skills/score/SKILL.md` (add narrative scores to review mode)

- [ ] **Step 1: Add narrative-scores.csv to files read**

In the "Read Project State" section, add:

```markdown
- `working/scores/latest/narrative-scores.csv` — novel-level narrative framework alignment (if exists)
- `working/scores/latest/narrative-rationale.csv` — rationale for narrative scores (if exists)
```

- [ ] **Step 2: Add narrative profile to review display**

After the summary view (top 5 high/low principles), add:

```markdown
### Narrative Profile

If `narrative-scores.csv` exists, display the narrative framework profile:

> **Narrative Profile**
> Your manuscript's structural DNA:
>
> | Framework | Score | Alignment |
> |-----------|-------|-----------|
> | Three Act | 5 | Strong |
> | Campbell's Monomyth | 4 | Mostly aligned |
> | Harmon Circle | 4 | Mostly aligned |
> | Save the Cat | 3 | Partial |
> | Freytag | 3 | Partial |
> | Truby 22 | 2 | Loose |
> | Kishotenketsu | 1 | Not present |
>
> This shows which narrative structures your manuscript naturally follows. Low scores aren't deficits — they reflect creative choices about story structure.

Use the score color coding: 5=blue, 4=green, 3=yellow, 2=red, 1=near-black.
```

- [ ] **Step 3: Commit**

```bash
git add skills/score/SKILL.md
git commit -m "Score skill: display narrative profile in review mode"
```

---

### Task 7: Version bump and final verification

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run full test suite**

Run: `./tests/run-tests.sh`
Expected: All suites pass.

- [ ] **Step 2: Bump version to 0.27.0**

- [ ] **Step 3: Update CLAUDE.md if needed**

Add `narrative-scores.csv` to the Key CSV Files section.

- [ ] **Step 4: Commit and push**

```bash
git add .claude-plugin/plugin.json CLAUDE.md
git commit -m "Bump version to 0.27.0"
git push
```

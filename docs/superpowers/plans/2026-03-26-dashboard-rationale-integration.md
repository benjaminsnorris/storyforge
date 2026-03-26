# Dashboard Rationale Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface all score rationales in the visualization dashboard and add new visualizations for act, character, and genre scores.

**Architecture:** Extend the Python data loader (`visualize.py`) to load 7 new CSV data sources. Add a shared rationale drawer UI component and 3 new visualization IIFEs to the dashboard HTML generator (`storyforge-visualize`). Fix the narrative radar clipping bug. Add click-for-rationale to existing heatmap and detail panel.

**Tech Stack:** Python (data loading), Bash (HTML generation), vanilla JavaScript/SVG (visualizations), CSS (drawer styling)

---

### Task 1: Add Rationale and Score Data to Python Loader

**Files:**
- Modify: `scripts/lib/python/storyforge/visualize.py:128-179`
- Test: `tests/test-python.sh`

- [ ] **Step 1: Write the test for new data sources**

Append to `tests/test-python.sh`:

```bash
# ============================================================================
# storyforge.visualize — rationale and extended score loading
# ============================================================================

echo "  --- visualize: loads rationale and extended score CSVs ---"

VIS_TMP="$(mktemp -d)"
mkdir -p "${VIS_TMP}/working/scores/latest" "${VIS_TMP}/reference"

# Create storyforge.yaml
cat > "${VIS_TMP}/storyforge.yaml" <<'YAML'
project:
  title: Test Novel
  genre: thriller
YAML

# Create minimal required CSVs
echo "id|seq|title|pov|word_count|status|type|location|part" > "${VIS_TMP}/reference/scene-metadata.csv"
echo "s1|1|Scene One|Alice|1000|draft|character|Home|act-1" >> "${VIS_TMP}/reference/scene-metadata.csv"

echo "id|function|emotional_arc|characters|threads|motifs" > "${VIS_TMP}/reference/scene-intent.csv"
echo "s1|opener|tension|Alice|main-plot|light" >> "${VIS_TMP}/reference/scene-intent.csv"

# Create rationale CSVs
echo "id|principle_a|principle_b" > "${VIS_TMP}/working/scores/latest/scene-rationale.csv"
echo "s1|Good pacing here|Needs more tension" >> "${VIS_TMP}/working/scores/latest/scene-rationale.csv"

echo "id|framework_a|framework_b" > "${VIS_TMP}/working/scores/latest/act-scores.csv"
echo "act-1|4|3" >> "${VIS_TMP}/working/scores/latest/act-scores.csv"

echo "id|framework_a|framework_b" > "${VIS_TMP}/working/scores/latest/act-rationale.csv"
echo "act-1|Strong structure|Needs pacing work" >> "${VIS_TMP}/working/scores/latest/act-rationale.csv"

echo "character|want_need|voice_as_character" > "${VIS_TMP}/working/scores/latest/character-scores.csv"
echo "Alice|5|4" >> "${VIS_TMP}/working/scores/latest/character-scores.csv"

echo "character|want_need|voice_as_character" > "${VIS_TMP}/working/scores/latest/character-rationale.csv"
echo "Alice|Clear want/need arc|Distinct voice" >> "${VIS_TMP}/working/scores/latest/character-rationale.csv"

echo "trope_awareness|genre_contract" > "${VIS_TMP}/working/scores/latest/genre-scores.csv"
echo "5|4" >> "${VIS_TMP}/working/scores/latest/genre-scores.csv"

echo "trope_awareness|genre_contract" > "${VIS_TMP}/working/scores/latest/genre-rationale.csv"
echo "Tropes handled well|Contract fulfilled" >> "${VIS_TMP}/working/scores/latest/genre-rationale.csv"

echo "principle|rationale" > "${VIS_TMP}/working/scores/latest/narrative-rationale.csv"
echo "three_act|Well structured" >> "${VIS_TMP}/working/scores/latest/narrative-rationale.csv"

# Run the data loader
VIS_JSON=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.visualize data "${VIS_TMP}" 2>/dev/null)

# Check new keys exist and have data
scene_rat_count=$(echo "$VIS_JSON" | jq '.scene_rationales | length')
assert_equals "1" "$scene_rat_count" "visualize: loads scene rationales"

act_scores_count=$(echo "$VIS_JSON" | jq '.act_scores | length')
assert_equals "1" "$act_scores_count" "visualize: loads act scores"

act_rat_count=$(echo "$VIS_JSON" | jq '.act_rationales | length')
assert_equals "1" "$act_rat_count" "visualize: loads act rationales"

char_scores_count=$(echo "$VIS_JSON" | jq '.character_scores | length')
assert_equals "1" "$char_scores_count" "visualize: loads character scores"

char_rat_count=$(echo "$VIS_JSON" | jq '.character_rationales | length')
assert_equals "1" "$char_rat_count" "visualize: loads character rationales"

genre_scores_count=$(echo "$VIS_JSON" | jq '.genre_scores | length')
assert_equals "1" "$genre_scores_count" "visualize: loads genre scores"

genre_rat_count=$(echo "$VIS_JSON" | jq '.genre_rationales | length')
assert_equals "1" "$genre_rat_count" "visualize: loads genre rationales"

narrative_rat_count=$(echo "$VIS_JSON" | jq '.narrative_rationales | length')
assert_equals "1" "$narrative_rat_count" "visualize: loads narrative rationales"

# Check a specific value to verify content
scene_rat_val=$(echo "$VIS_JSON" | jq -r '.scene_rationales[0].principle_a')
assert_equals "Good pacing here" "$scene_rat_val" "visualize: scene rationale has correct content"

rm -rf "$VIS_TMP"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/bennorris/Developer/storyforge && ./tests/run-tests.sh tests/test-python.sh`
Expected: FAIL — keys `scene_rationales`, `act_scores`, etc. not found in JSON output

- [ ] **Step 3: Add new data sources to load_dashboard_data()**

In `scripts/lib/python/storyforge/visualize.py`, add CSV path variables after line 150 (the existing `narrative_csv` line):

```python
    scene_rationale_csv = os.path.join(project_dir, 'working/scores/latest/scene-rationale.csv')
    act_scores_csv = os.path.join(project_dir, 'working/scores/latest/act-scores.csv')
    act_rationale_csv = os.path.join(project_dir, 'working/scores/latest/act-rationale.csv')
    character_scores_csv = os.path.join(project_dir, 'working/scores/latest/character-scores.csv')
    character_rationale_csv = os.path.join(project_dir, 'working/scores/latest/character-rationale.csv')
    genre_scores_csv = os.path.join(project_dir, 'working/scores/latest/genre-scores.csv')
    genre_rationale_csv = os.path.join(project_dir, 'working/scores/latest/genre-rationale.csv')
    narrative_rationale_csv = os.path.join(project_dir, 'working/scores/latest/narrative-rationale.csv')
```

Then add these keys to the return dict (after the existing `'narrative_scores'` line):

```python
        'scene_rationales': csv_to_records(scene_rationale_csv),
        'act_scores': csv_to_records(act_scores_csv),
        'act_rationales': csv_to_records(act_rationale_csv),
        'character_scores': csv_to_records(character_scores_csv),
        'character_rationales': csv_to_records(character_rationale_csv),
        'genre_scores': csv_to_records(genre_scores_csv),
        'genre_rationales': csv_to_records(genre_rationale_csv),
        'narrative_rationales': csv_to_records(narrative_rationale_csv),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/bennorris/Developer/storyforge && ./tests/run-tests.sh tests/test-python.sh`
Expected: All new assertions PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/bennorris/Developer/storyforge
git add scripts/lib/python/storyforge/visualize.py tests/test-python.sh
git commit -m "Add rationale and extended score data loading to visualize module"
git push
```

---

### Task 2: Inject New Data as JS Constants

**Files:**
- Modify: `scripts/storyforge-visualize:636-648`

- [ ] **Step 1: Add new JS constants to data injection block**

In `scripts/storyforge-visualize`, find the data injection block (lines 636-648) that starts with `cat >> "$DASHBOARD_FILE" << EOF`. Add the new constants after the existing `const PROJECT = _DATA.project;` line:

```javascript
const SCENE_RATIONALES = _DATA.scene_rationales;
const ACT_SCORES = _DATA.act_scores;
const ACT_RATIONALES = _DATA.act_rationales;
const CHARACTER_SCORES = _DATA.character_scores;
const CHARACTER_RATIONALES = _DATA.character_rationales;
const GENRE_SCORES = _DATA.genre_scores;
const GENRE_RATIONALES = _DATA.genre_rationales;
const NARRATIVE_RATIONALES = _DATA.narrative_rationales;
```

- [ ] **Step 2: Add lookup maps after existing lookups**

In the JS utilities section (after line 677 where `SCORES.forEach(s => { scoreById[s.id] = s; });`), add:

```javascript
const sceneRationaleById = {};
const actScoreById = {};
const actRationaleById = {};
const charScoreByName = {};
const charRationaleByName = {};
const narrativeRationaleByPrinciple = {};

SCENE_RATIONALES.forEach(r => { sceneRationaleById[r.id] = r; });
ACT_SCORES.forEach(s => { actScoreById[s.id] = s; });
ACT_RATIONALES.forEach(r => { actRationaleById[r.id] = r; });
CHARACTER_SCORES.forEach(s => { charScoreByName[s.character] = s; });
CHARACTER_RATIONALES.forEach(r => { charRationaleByName[r.character] = r; });
NARRATIVE_RATIONALES.forEach(r => { narrativeRationaleByPrinciple[r.principle] = r; });
```

- [ ] **Step 3: Commit**

```bash
cd /Users/bennorris/Developer/storyforge
git add scripts/storyforge-visualize
git commit -m "Inject rationale and extended score data as JS constants"
git push
```

---

### Task 3: Add Rationale Drawer CSS and HTML

**Files:**
- Modify: `scripts/storyforge-visualize` (CSS section ~lines 433-492, HTML body ~lines 494-628)

- [ ] **Step 1: Add drawer CSS**

In the CSS section, before the `/* ── SVG shared styles ──` comment (line 433), add:

```css
/* ── Rationale drawer ─────────────────────────────── */
.rationale-drawer {
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.3s ease-out, padding 0.3s ease-out;
    background: var(--surface-raised);
    border: 1px solid var(--border);
    border-top: 2px solid var(--teal);
    border-radius: 0 0 var(--radius) var(--radius);
    margin-top: -1px;
}

.rationale-drawer.open {
    max-height: 40vh;
    overflow-y: auto;
    padding: 16px 20px;
}

.rationale-drawer-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border-light);
}

.rationale-drawer-header h3 {
    font-family: var(--font-mono);
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--teal);
    margin: 0;
}

.rationale-drawer .close-btn {
    background: none;
    border: none;
    color: var(--text-dim);
    cursor: pointer;
    font-size: 18px;
    line-height: 1;
    padding: 4px;
}

.rationale-drawer .close-btn:hover { color: var(--text); }

.rationale-drawer .rationale-text {
    font-size: 13px;
    line-height: 1.7;
    color: var(--text-secondary);
}

.rationale-drawer .rationale-text p {
    margin-bottom: 12px;
}

.rationale-drawer .rationale-text p:last-child {
    margin-bottom: 0;
}

.rationale-drawer .rationale-principle {
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--teal);
    margin-bottom: 4px;
}

.rationale-drawer .rationale-score {
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 700;
    margin-left: 8px;
}
```

- [ ] **Step 2: Add drawer HTML placeholders to each section that needs one**

After the heatmap vis-container (line 595, after `<div class="vis-container" id="score-heatmap"></div>`), add:
```html
    <div class="rationale-drawer" id="heatmap-drawer"></div>
```

After the narrative radar vis-container (line 605, after `<div class="vis-container" id="narrative-radar"></div>`), add:
```html
    <div class="rationale-drawer" id="narrative-radar-drawer"></div>
```

For the 3 new visualization sections (added in Task 5), their drawer HTML will be included inline.

- [ ] **Step 3: Add drawer JS utility functions**

In the JS utilities section (after the lookup maps added in Task 2), add:

```javascript
// ============================================================================
// RATIONALE DRAWER
// ============================================================================

const openDrawers = [];

function openRationaleDrawer(drawerId, title, contentHtml) {
    const drawer = document.getElementById(drawerId);
    if (!drawer) return;
    drawer.innerHTML = '<div class="rationale-drawer-header">' +
        '<h3>' + title + '</h3>' +
        '<button class="close-btn" onclick="closeRationaleDrawer(\'' + drawerId + '\')">&times;</button>' +
        '</div>' +
        '<div class="rationale-text">' + contentHtml + '</div>';
    drawer.classList.add('open');
    if (openDrawers.indexOf(drawerId) === -1) openDrawers.push(drawerId);
}

function closeRationaleDrawer(drawerId) {
    const drawer = document.getElementById(drawerId);
    if (!drawer) return;
    drawer.classList.remove('open');
    var idx = openDrawers.indexOf(drawerId);
    if (idx !== -1) openDrawers.splice(idx, 1);
}

function formatPrincipleLabel(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
}

function scoreColorClass(val) {
    var n = parseInt(val);
    if (isNaN(n)) return 'var(--text-dim)';
    if (n <= 1) return 'var(--score-low)';
    if (n <= 2) return 'var(--score-mid-low)';
    if (n <= 3) return 'var(--score-mid)';
    if (n <= 4) return 'var(--score-mid-high)';
    return 'var(--score-high)';
}

// Escape closes the most recently opened drawer
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && openDrawers.length > 0) {
        closeRationaleDrawer(openDrawers[openDrawers.length - 1]);
    }
});
```

- [ ] **Step 4: Commit**

```bash
cd /Users/bennorris/Developer/storyforge
git add scripts/storyforge-visualize
git commit -m "Add rationale drawer CSS, HTML, and JS utilities"
git push
```

---

### Task 4: Add Click-for-Rationale to Craft Heatmap

**Files:**
- Modify: `scripts/storyforge-visualize:1414-1428` (heatmap cell rendering)

- [ ] **Step 1: Replace existing cell rendering with clickable version**

In the heatmap rendering IIFE, replace the cell creation loop body (the `sortedScenes.forEach` inside `orderedPrinciples.forEach`, lines 1415-1428) with:

```javascript
        sortedScenes.forEach((s, ci) => {
            const score = scoreById[s.id];
            const val = score ? score[principle] : '';
            const rect = svgEl('rect', {
                x: LABEL_W + ci * (CELL + GAP),
                y,
                width: CELL, height: CELL,
                fill: scoreColor(val),
                rx: 1,
                opacity: val ? 0.85 : 0.15,
                style: val ? 'cursor:pointer' : ''
            });
            attachSceneHandlers(rect, s.id);
            if (val) {
                rect.addEventListener('click', function(e) {
                    e.stopPropagation();
                    var rat = sceneRationaleById[s.id];
                    if (!rat || !rat[principle]) return;
                    var scoreNum = parseInt(val);
                    var html = '<div class="rationale-principle">' + formatPrincipleLabel(principle) +
                        '<span class="rationale-score" style="color:' + scoreColor(scoreNum) + '">' + scoreNum + '/5</span>' +
                        '</div>' +
                        '<p><strong>' + s.seq + '. ' + s.title + '</strong></p>' +
                        '<p>' + rat[principle] + '</p>';
                    openRationaleDrawer('heatmap-drawer', 'Scene Craft Rationale', html);
                });
            }
            svg.appendChild(rect);
        });
```

- [ ] **Step 2: Verify by generating dashboard with a project that has rationale data**

Run: `cd /Users/bennorris/Developer/storyforge && ./scripts/storyforge-visualize --dry-run`
Expected: No errors. (Full generation test requires a project with score data.)

- [ ] **Step 3: Commit**

```bash
cd /Users/bennorris/Developer/storyforge
git add scripts/storyforge-visualize
git commit -m "Add click-for-rationale to craft score heatmap cells"
git push
```

---

### Task 5: Add Genre, Character, and Act Score Visualizations

**Files:**
- Modify: `scripts/storyforge-visualize` (HTML sections ~line 596, JS section before narrative radar ~line 1434)

- [ ] **Step 1: Add HTML sections for new visualizations**

In the HTML body, after the heatmap section's closing `</div>` (after line 596, which is `</div>` closing the heatmap section), add:

```html
<!-- Genre Scores -->
<div class="section" id="genre-section" style="display:none;">
    <div class="section-header">
        <span class="dot"></span>
        <h2>Genre Scores</h2>
        <span class="subtitle">Genre craft assessment</span>
    </div>
    <div class="vis-container" id="genre-scores"></div>
    <div class="rationale-drawer" id="genre-drawer"></div>
</div>

<!-- Character Scores -->
<div class="section" id="character-section" style="display:none;">
    <div class="section-header">
        <span class="dot"></span>
        <h2>Character Scores</h2>
        <span class="subtitle">Character craft by principle</span>
    </div>
    <div class="vis-container" id="character-scores-vis"></div>
    <div class="rationale-drawer" id="character-drawer"></div>
</div>

<!-- Act Scores -->
<div class="section" id="act-section" style="display:none;">
    <div class="section-header">
        <span class="dot"></span>
        <h2>Act Scores</h2>
        <span class="subtitle">Narrative framework alignment by act</span>
    </div>
    <div class="vis-container" id="act-scores-vis"></div>
    <div class="rationale-drawer" id="act-drawer"></div>
</div>
```

- [ ] **Step 2: Add genre scores IIFE**

In the JS section, after the heatmap IIFE closing `})();` (line 1432) and before the narrative radar comment (line 1434), add:

```javascript
// ============================================================================
// GENRE SCORES
// ============================================================================

(function renderGenreScores() {
    if (!GENRE_SCORES || GENRE_SCORES.length === 0) return;
    document.getElementById('genre-section').style.display = '';
    var container = document.getElementById('genre-scores');

    var genreData = GENRE_SCORES[0];
    var genreRat = GENRE_RATIONALES.length > 0 ? GENRE_RATIONALES[0] : {};
    var principles = Object.keys(genreData);

    var LABEL_W = 180;
    var BAR_H = 24;
    var BAR_GAP = 6;
    var MAX_BAR_W = 300;
    var H = principles.length * (BAR_H + BAR_GAP) + 8;
    var W = LABEL_W + MAX_BAR_W + 60;
    var svg = makeSvg(container, W, H);

    principles.forEach(function(p, i) {
        var y = i * (BAR_H + BAR_GAP) + 4;
        var score = parseInt(genreData[p]) || 0;
        var barW = (score / 5) * MAX_BAR_W;
        var color = scoreColorClass(score);

        // Label
        var label = svgEl('text', {
            x: LABEL_W - 8, y: y + BAR_H / 2 + 4,
            'text-anchor': 'end', 'font-family': 'var(--font-mono)',
            'font-size': 11, fill: 'var(--text-dim)'
        });
        label.textContent = formatPrincipleLabel(p);
        svg.appendChild(label);

        // Bar
        var rect = svgEl('rect', {
            x: LABEL_W, y: y,
            width: barW, height: BAR_H,
            fill: color, rx: 3, opacity: 0.85,
            style: 'cursor:pointer'
        });
        rect.addEventListener('click', function(e) {
            e.stopPropagation();
            var ratText = genreRat[p];
            if (!ratText) return;
            var html = '<div class="rationale-principle">' + formatPrincipleLabel(p) +
                '<span class="rationale-score" style="color:' + color + '">' + score + '/5</span></div>' +
                '<p>' + ratText + '</p>';
            openRationaleDrawer('genre-drawer', 'Genre Rationale', html);
        });
        svg.appendChild(rect);

        // Score label
        var scoreLabel = svgEl('text', {
            x: LABEL_W + barW + 8, y: y + BAR_H / 2 + 4,
            'font-family': 'var(--font-mono)', 'font-size': 12,
            'font-weight': 700, fill: color
        });
        scoreLabel.textContent = score;
        svg.appendChild(scoreLabel);
    });
})();
```

- [ ] **Step 3: Add character scores IIFE**

Immediately after the genre scores IIFE, add:

```javascript
// ============================================================================
// CHARACTER SCORES
// ============================================================================

(function renderCharacterScores() {
    if (!CHARACTER_SCORES || CHARACTER_SCORES.length === 0) return;
    document.getElementById('character-section').style.display = '';
    var container = document.getElementById('character-scores-vis');

    var principles = Object.keys(CHARACTER_SCORES[0]).filter(function(k) { return k !== 'character'; });
    var chars = CHARACTER_SCORES;

    var LABEL_W = 180;
    var BAR_H = 18;
    var BAR_GAP = 3;
    var GROUP_GAP = 16;
    var MAX_BAR_W = 300;
    var groupH = principles.length * (BAR_H + BAR_GAP);
    var H = chars.length * (groupH + GROUP_GAP) + 8;
    var W = LABEL_W + MAX_BAR_W + 60;
    var svg = makeSvg(container, W, H);

    var yOffset = 4;
    chars.forEach(function(ch) {
        var rat = charRationaleByName[ch.character] || {};

        // Character name header
        var nameLabel = svgEl('text', {
            x: 4, y: yOffset + 3,
            'font-family': 'var(--font-mono)', 'font-size': 11,
            'font-weight': 600, fill: 'var(--teal)'
        });
        nameLabel.textContent = ch.character;
        svg.appendChild(nameLabel);
        yOffset += 16;

        principles.forEach(function(p) {
            var score = parseInt(ch[p]) || 0;
            var barW = (score / 5) * MAX_BAR_W;
            var color = scoreColorClass(score);

            // Label
            var label = svgEl('text', {
                x: LABEL_W - 8, y: yOffset + BAR_H / 2 + 4,
                'text-anchor': 'end', 'font-family': 'var(--font-mono)',
                'font-size': 10, fill: 'var(--text-dim)'
            });
            label.textContent = formatPrincipleLabel(p);
            svg.appendChild(label);

            // Bar
            var rect = svgEl('rect', {
                x: LABEL_W, y: yOffset,
                width: barW, height: BAR_H,
                fill: color, rx: 3, opacity: 0.85,
                style: 'cursor:pointer'
            });
            rect.addEventListener('click', function(e) {
                e.stopPropagation();
                var ratText = rat[p];
                if (!ratText) return;
                var html = '<div class="rationale-principle">' + formatPrincipleLabel(p) +
                    '<span class="rationale-score" style="color:' + color + '">' + score + '/5</span></div>' +
                    '<p><strong>' + ch.character + '</strong></p>' +
                    '<p>' + ratText + '</p>';
                openRationaleDrawer('character-drawer', 'Character Rationale', html);
            });
            svg.appendChild(rect);

            // Score label
            var scoreLabel = svgEl('text', {
                x: LABEL_W + barW + 8, y: yOffset + BAR_H / 2 + 4,
                'font-family': 'var(--font-mono)', 'font-size': 11,
                'font-weight': 700, fill: color
            });
            scoreLabel.textContent = score;
            svg.appendChild(scoreLabel);

            yOffset += BAR_H + BAR_GAP;
        });

        yOffset += GROUP_GAP;
    });
})();
```

- [ ] **Step 4: Add act scores IIFE**

Immediately after the character scores IIFE, add:

```javascript
// ============================================================================
// ACT SCORES
// ============================================================================

(function renderActScores() {
    if (!ACT_SCORES || ACT_SCORES.length === 0) return;
    document.getElementById('act-section').style.display = '';
    var container = document.getElementById('act-scores-vis');

    var principles = Object.keys(ACT_SCORES[0]).filter(function(k) { return k !== 'id'; });
    var acts = ACT_SCORES;

    var LABEL_W = 200;
    var BAR_H = 18;
    var BAR_GAP = 3;
    var GROUP_GAP = 16;
    var MAX_BAR_W = 280;
    var groupH = principles.length * (BAR_H + BAR_GAP);
    var H = acts.length * (groupH + GROUP_GAP) + 8;
    var W = LABEL_W + MAX_BAR_W + 60;
    var svg = makeSvg(container, W, H);

    var FRAMEWORK_LABELS = {
        campbells_monomyth: "Campbell's Monomyth",
        three_act: 'Three Act',
        save_the_cat: 'Save the Cat',
        truby_22: 'Truby 22',
        harmon_circle: 'Harmon Circle',
        kishotenketsu: 'Kishotenketsu',
        freytag: "Freytag's Pyramid",
        character_web: 'Character Web',
        character_as_theme: 'Character as Theme'
    };

    var yOffset = 4;
    acts.forEach(function(act) {
        var rat = actRationaleById[act.id] || {};

        // Act name header
        var nameLabel = svgEl('text', {
            x: 4, y: yOffset + 3,
            'font-family': 'var(--font-mono)', 'font-size': 11,
            'font-weight': 600, fill: 'var(--teal)'
        });
        nameLabel.textContent = act.id.replace(/-/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
        svg.appendChild(nameLabel);
        yOffset += 16;

        principles.forEach(function(p) {
            var score = parseInt(act[p]) || 0;
            var barW = (score / 5) * MAX_BAR_W;
            var color = scoreColorClass(score);

            // Label
            var label = svgEl('text', {
                x: LABEL_W - 8, y: yOffset + BAR_H / 2 + 4,
                'text-anchor': 'end', 'font-family': 'var(--font-mono)',
                'font-size': 10, fill: 'var(--text-dim)'
            });
            label.textContent = FRAMEWORK_LABELS[p] || formatPrincipleLabel(p);
            svg.appendChild(label);

            // Bar
            var rect = svgEl('rect', {
                x: LABEL_W, y: yOffset,
                width: barW, height: BAR_H,
                fill: color, rx: 3, opacity: 0.85,
                style: 'cursor:pointer'
            });
            rect.addEventListener('click', function(e) {
                e.stopPropagation();
                var ratText = rat[p];
                if (!ratText) return;
                var actLabel = act.id.replace(/-/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
                var html = '<div class="rationale-principle">' + (FRAMEWORK_LABELS[p] || formatPrincipleLabel(p)) +
                    '<span class="rationale-score" style="color:' + color + '">' + score + '/5</span></div>' +
                    '<p><strong>' + actLabel + '</strong></p>' +
                    '<p>' + ratText + '</p>';
                openRationaleDrawer('act-drawer', 'Act Rationale', html);
            });
            svg.appendChild(rect);

            // Score label
            var scoreLabel = svgEl('text', {
                x: LABEL_W + barW + 8, y: yOffset + BAR_H / 2 + 4,
                'font-family': 'var(--font-mono)', 'font-size': 11,
                'font-weight': 700, fill: color
            });
            scoreLabel.textContent = score;
            svg.appendChild(scoreLabel);

            yOffset += BAR_H + BAR_GAP;
        });

        yOffset += GROUP_GAP;
    });
})();
```

- [ ] **Step 5: Commit**

```bash
cd /Users/bennorris/Developer/storyforge
git add scripts/storyforge-visualize
git commit -m "Add genre, character, and act score visualizations with rationale drawers"
git push
```

---

### Task 6: Fix Narrative Radar Clipping and Add Rationale Click

**Files:**
- Modify: `scripts/storyforge-visualize:1438-1543` (narrative radar IIFE)

- [ ] **Step 1: Fix the SVG viewport and add click-for-rationale**

Replace the narrative radar IIFE (lines 1438-1543) with:

```javascript
(function renderNarrativeRadar() {
    if (!NARRATIVE_SCORES || NARRATIVE_SCORES.length === 0) return;
    document.getElementById('narrative-radar-section').style.display = '';
    var container = document.getElementById('narrative-radar');

    var PAD_X = 120;
    var PAD_Y = 40;
    var R = 180;
    var W = R * 2 + PAD_X * 2;
    var H = R * 2 + PAD_Y * 2;
    var CX = W / 2;
    var CY = H / 2;
    var RINGS = 5;
    var principles = NARRATIVE_SCORES;
    var N = principles.length;
    var angleStep = (2 * Math.PI) / N;
    var startAngle = -Math.PI / 2;

    var LABELS = {
        three_act: 'Three Act',
        campbells_monomyth: "Campbell's Monomyth",
        save_the_cat: 'Save the Cat',
        truby_22: 'Truby 22',
        harmon_circle: 'Harmon Circle',
        kishotenketsu: 'Kishotenketsu',
        freytag: "Freytag's Pyramid"
    };

    var svg = makeSvg(container, W, H);

    // Draw concentric rings
    for (var ring = 1; ring <= RINGS; ring++) {
        var r = (ring / RINGS) * R;
        svg.appendChild(svgEl('circle', {
            cx: CX, cy: CY, r: r,
            fill: 'none', stroke: 'var(--border)', 'stroke-width': 0.5,
            'stroke-dasharray': ring < RINGS ? '2,3' : 'none'
        }));
        svg.appendChild(svgEl('text', {
            x: CX + 4, y: CY - r + 12,
            'font-family': 'var(--font-mono)', 'font-size': 9,
            fill: 'var(--text-dim)', opacity: 0.6
        })).textContent = ring;
    }

    // Draw spokes, data polygon, and labels
    var points = [];
    principles.forEach(function(p, i) {
        var angle = startAngle + i * angleStep;
        var score = parseInt(p.score) || 0;
        var sr = (score / RINGS) * R;

        // Spoke line
        var spokeX = CX + Math.cos(angle) * R;
        var spokeY = CY + Math.sin(angle) * R;
        svg.appendChild(svgEl('line', {
            x1: CX, y1: CY, x2: spokeX, y2: spokeY,
            stroke: 'var(--border)', 'stroke-width': 0.5
        }));

        // Data point
        var px = CX + Math.cos(angle) * sr;
        var py = CY + Math.sin(angle) * sr;
        points.push({ x: px, y: py, score: score, principle: p.principle });

        // Framework label around perimeter
        var labelR = R + 24;
        var lx = CX + Math.cos(angle) * labelR;
        var ly = CY + Math.sin(angle) * labelR;
        var anchor = Math.abs(Math.cos(angle)) < 0.05 ? 'middle' : (lx > CX ? 'start' : 'end');
        var label = LABELS[p.principle] || p.principle.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
        svg.appendChild(svgEl('text', {
            x: lx, y: ly + 4, 'text-anchor': anchor,
            'font-family': 'var(--font)', 'font-size': 11,
            fill: 'var(--text)', 'font-weight': 500
        })).textContent = label;

        // Score value near dot
        svg.appendChild(svgEl('text', {
            x: px, y: py - 8, 'text-anchor': 'middle',
            'font-family': 'var(--font-mono)', 'font-size': 10,
            fill: 'var(--text)', 'font-weight': 700
        })).textContent = score;
    });

    // Draw filled polygon
    if (points.length > 0) {
        var polyPoints = points.map(function(p) { return p.x + ',' + p.y; }).join(' ');
        svg.appendChild(svgEl('polygon', {
            points: polyPoints,
            fill: 'var(--score-high)', 'fill-opacity': 0.15,
            stroke: 'var(--score-high)', 'stroke-width': 2
        }));

        // Draw clickable score dots
        points.forEach(function(p) {
            var color = p.score <= 1 ? 'var(--score-low)' :
                        p.score <= 2 ? 'var(--score-mid-low)' :
                        p.score <= 3 ? 'var(--score-mid)' :
                        p.score <= 4 ? 'var(--score-mid-high)' :
                        'var(--score-high)';
            var dot = svgEl('circle', {
                cx: p.x, cy: p.y, r: 5,
                fill: color, stroke: 'var(--surface)', 'stroke-width': 2,
                style: 'cursor:pointer'
            });
            dot.addEventListener('click', function(e) {
                e.stopPropagation();
                var rat = narrativeRationaleByPrinciple[p.principle];
                if (!rat || !rat.rationale) return;
                var label = LABELS[p.principle] || formatPrincipleLabel(p.principle);
                var html = '<div class="rationale-principle">' + label +
                    '<span class="rationale-score" style="color:' + color + '">' + p.score + '/5</span></div>' +
                    '<p>' + rat.rationale + '</p>';
                openRationaleDrawer('narrative-radar-drawer', 'Narrative Rationale', html);
            });
            svg.appendChild(dot);
        });
    }
})();
```

- [ ] **Step 2: Commit**

```bash
cd /Users/bennorris/Developer/storyforge
git add scripts/storyforge-visualize
git commit -m "Fix narrative radar label clipping and add rationale click"
git push
```

---

### Task 7: Add "View Rationales" Link to Detail Panel

**Files:**
- Modify: `scripts/storyforge-visualize:842-857` (detail panel score display)

- [ ] **Step 1: Add rationale link after scores grid**

In the `updateDetailPanel` function, replace the score display block (lines 842-854) with:

```javascript
    if (score) {
        html += '<div style="margin-top:12px;padding-top:8px;border-top:1px solid var(--border-light)">';
        html += '<div class="detail-label" style="margin-bottom:4px">CRAFT SCORES</div>';
        html += '<div class="scores-grid">';
        for (const [k, v] of Object.entries(score)) {
            if (k === 'id') continue;
            const num = parseInt(v);
            if (isNaN(num)) continue;
            const color = num >= 5 ? 'var(--score-high)' : num >= 4 ? 'var(--score-mid-high)' : num >= 3 ? 'var(--score-mid)' : num >= 2 ? 'var(--score-mid-low)' : 'var(--score-low)';
            html += `<span class="sg-label">${k.replace(/_/g, ' ')}</span><span class="sg-value" style="color:${color}">${num}</span>`;
        }
        html += '</div>';

        const rat = sceneRationaleById[sceneId];
        if (rat) {
            html += '<div style="margin-top:8px;text-align:center">';
            html += '<a href="#" style="font-family:var(--font-mono);font-size:10px;color:var(--teal);text-decoration:none" ';
            html += 'onclick="event.preventDefault();showAllRationales(\'' + sceneId + '\')">View rationales &rarr;</a>';
            html += '</div>';
        }

        html += '</div>';
    }
```

- [ ] **Step 2: Add showAllRationales function**

In the JS utilities section (after the rationale drawer functions), add:

```javascript
function showAllRationales(sceneId) {
    var s = sceneById[sceneId];
    var score = scoreById[sceneId];
    var rat = sceneRationaleById[sceneId];
    if (!s || !rat) return;

    // Group by section using weights
    var sectionMap = {};
    WEIGHTS.forEach(function(w) {
        if (w.section && w.principle) sectionMap[w.principle] = w.section;
    });

    var sections = {};
    var principles = Object.keys(rat).filter(function(k) { return k !== 'id'; });
    principles.forEach(function(p) {
        var sec = sectionMap[p] || 'other';
        if (!sections[sec]) sections[sec] = [];
        sections[sec].push(p);
    });

    var html = '';
    for (var sec in sections) {
        html += '<div class="rationale-principle" style="margin-top:16px;margin-bottom:8px">' +
            sec.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); }) + '</div>';
        sections[sec].forEach(function(p) {
            if (!rat[p]) return;
            var scoreVal = score ? parseInt(score[p]) : 0;
            var color = scoreColorClass(scoreVal);
            html += '<p><strong style="font-family:var(--font-mono);font-size:10px">' +
                formatPrincipleLabel(p) +
                ' <span style="color:' + color + '">' + scoreVal + '/5</span></strong></p>' +
                '<p>' + rat[p] + '</p>';
        });
    }

    openRationaleDrawer('heatmap-drawer', s.seq + '. ' + s.title + ' — All Rationales', html);

    // Scroll to the drawer
    document.getElementById('heatmap-drawer').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/bennorris/Developer/storyforge
git add scripts/storyforge-visualize
git commit -m "Add view-rationales link to detail panel"
git push
```

---

### Task 8: Update Animation Delays and Final Testing

**Files:**
- Modify: `scripts/storyforge-visualize:481-491` (animation delay CSS)

- [ ] **Step 1: Extend animation delays for new sections**

The dashboard now has up to 15 sections. Replace lines 481-491 with:

```css
.section:nth-child(2) { animation-delay: 0.05s; }
.section:nth-child(3) { animation-delay: 0.1s; }
.section:nth-child(4) { animation-delay: 0.15s; }
.section:nth-child(5) { animation-delay: 0.2s; }
.section:nth-child(6) { animation-delay: 0.25s; }
.section:nth-child(7) { animation-delay: 0.3s; }
.section:nth-child(8) { animation-delay: 0.35s; }
.section:nth-child(9) { animation-delay: 0.4s; }
.section:nth-child(10) { animation-delay: 0.45s; }
.section:nth-child(11) { animation-delay: 0.5s; }
.section:nth-child(12) { animation-delay: 0.55s; }
.section:nth-child(13) { animation-delay: 0.6s; }
.section:nth-child(14) { animation-delay: 0.65s; }
.section:nth-child(15) { animation-delay: 0.7s; }
```

- [ ] **Step 2: Run all tests**

Run: `cd /Users/bennorris/Developer/storyforge && ./tests/run-tests.sh`
Expected: All test suites pass, including the new visualize tests from Task 1.

- [ ] **Step 3: Generate dashboard with night-watch project**

Run: `cd /Users/bennorris/Developer/storyforge && ./scripts/storyforge-visualize --open`
(Run from within the night-watch project directory, or adjust PROJECT_DIR accordingly.)
Expected: Dashboard opens in browser with:
- Genre scores bar chart visible with clickable bars
- Character scores grouped bars visible with clickable bars
- Act scores grouped bars visible with clickable bars
- Narrative radar labels fully visible (no clipping)
- Radar dots clickable, opening rationale drawer
- Heatmap cells clickable, opening rationale drawer
- Detail panel "View rationales" link works

- [ ] **Step 4: Bump plugin version**

In `.claude-plugin/plugin.json`, bump the patch version (e.g., `0.33.4` → `0.34.0` since this is a new feature).

- [ ] **Step 5: Commit**

```bash
cd /Users/bennorris/Developer/storyforge
git add scripts/storyforge-visualize .claude-plugin/plugin.json
git commit -m "Update animation delays, bump version to 0.34.0"
git push
```

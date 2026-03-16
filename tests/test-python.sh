#!/bin/bash
# test-python.sh — Tests for Python core modules (parsing, api)

PYTHON_DIR="${PLUGIN_DIR}/scripts/lib/python"

# ============================================================================
# storyforge.parsing
# ============================================================================

echo "  --- parsing: extract_scenes_from_response ---"

PARSE_TMP="$(mktemp -d)"

# Create a mock response with scene markers
cat > "${PARSE_TMP}/response.json" <<'JSON'
{"content":[{"type":"text","text":"Here is the revision.\n\n=== SCENE: test-scene-1 ===\nFirst scene content.\nSecond line.\n=== END SCENE: test-scene-1 ===\n\n=== SCENE: test-scene-2 ===\nAnother scene.\n=== END SCENE: test-scene-2 ===\n\nSummary text here."}],"usage":{"input_tokens":100,"output_tokens":50}}
JSON

mkdir -p "${PARSE_TMP}/scenes"
result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.parsing extract-scenes "${PARSE_TMP}/response.json" "${PARSE_TMP}/scenes" 2>/dev/null)
assert_contains "$result" "Wrote: test-scene-1" "parsing: extracts first scene"
assert_contains "$result" "Wrote: test-scene-2" "parsing: extracts second scene"
assert_contains "$result" "Total: 2" "parsing: reports correct count"
assert_file_exists "${PARSE_TMP}/scenes/test-scene-1.md" "parsing: creates scene file 1"
assert_file_exists "${PARSE_TMP}/scenes/test-scene-2.md" "parsing: creates scene file 2"

scene1=$(cat "${PARSE_TMP}/scenes/test-scene-1.md")
assert_contains "$scene1" "First scene content" "parsing: scene 1 has correct content"
assert_not_contains "$scene1" "=== SCENE:" "parsing: scene 1 no markers in content"

# Test: skip parenthetical entries
cat > "${PARSE_TMP}/response-parens.json" <<'JSON'
{"content":[{"type":"text","text":"=== SCENE: my-scene ===\nOriginal.\n=== END SCENE: my-scene ===\n\n=== SCENE: my-scene (revised note) ===\nShould be skipped.\n=== END SCENE: my-scene (revised note) ==="}],"usage":{"input_tokens":10,"output_tokens":5}}
JSON

rm -f "${PARSE_TMP}/scenes/"*
result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.parsing extract-scenes "${PARSE_TMP}/response-parens.json" "${PARSE_TMP}/scenes" 2>/dev/null)
assert_contains "$result" "Total: 1" "parsing: skips parenthetical entries"
# Should NOT create a file with parens in the name
if [[ -f "${PARSE_TMP}/scenes/my-scene (revised note).md" ]]; then
    FAIL=$((FAIL + 1))
    echo "  FAIL: parsing: should not create parenthetical scene file"
else
    PASS=$((PASS + 1))
    echo "  PASS: parsing: no parenthetical scene file created"
fi

echo "  --- parsing: extract_single_scene ---"

cat > "${PARSE_TMP}/single.json" <<'JSON'
{"content":[{"type":"text","text":"Some analysis.\n\n=== SCENE: drafted-scene ===\nThe prose goes here.\nMore prose.\n=== END SCENE: drafted-scene ===\n\nNotes about the scene."}],"usage":{"input_tokens":10,"output_tokens":5}}
JSON

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.parsing extract-single "${PARSE_TMP}/single.json" "${PARSE_TMP}/output.md" 2>/dev/null)
assert_file_exists "${PARSE_TMP}/output.md" "parsing: single extraction creates file"
content=$(cat "${PARSE_TMP}/output.md")
assert_contains "$content" "The prose goes here" "parsing: single extraction has prose"
assert_not_contains "$content" "=== SCENE:" "parsing: single extraction no markers"
assert_not_contains "$content" "Notes about" "parsing: single extraction no trailing text"

# ============================================================================
# storyforge.api (non-network functions only)
# ============================================================================

echo "  --- api: extract_text_from_file ---"

cat > "${PARSE_TMP}/api-response.json" <<'JSON'
{"content":[{"type":"text","text":"Hello world"}],"usage":{"input_tokens":10,"output_tokens":5}}
JSON

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.api extract-text "${PARSE_TMP}/api-response.json" 2>/dev/null)
assert_equals "Hello world" "$result" "api: extracts text from response"

echo "  --- api: log_usage ---"

PROJECT_DIR="${PARSE_TMP}/project"
mkdir -p "${PROJECT_DIR}/working/costs"
export PROJECT_DIR

cat > "${PARSE_TMP}/usage-response.json" <<'JSON'
{"content":[{"type":"text","text":"test"}],"usage":{"input_tokens":1000,"output_tokens":500,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}
JSON

PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.api log-usage "${PARSE_TMP}/usage-response.json" "test-op" "test-target" "claude-sonnet-4-6" 2>/dev/null
ledger="${PROJECT_DIR}/working/costs/ledger.csv"
assert_file_exists "$ledger" "api: log_usage creates ledger"

row_count=$(wc -l < "$ledger" | tr -d ' ')
assert_equals "2" "$row_count" "api: ledger has header + 1 row"

data_row=$(tail -1 "$ledger")
assert_contains "$data_row" "test-op|test-target|claude-sonnet-4-6|1000|500" "api: row has correct data"

# ============================================================================
# storyforge.prompts
# ============================================================================

echo "  --- prompts: read_csv_field ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.prompts import read_csv_field
print(read_csv_field('${FIXTURE_DIR}/reference/scene-metadata.csv', 'act1-sc01', 'title'))
" 2>/dev/null)
assert_equals "The Finest Cartographer" "$result" "prompts: read_csv_field reads title"

echo "  --- prompts: get_scene_metadata ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.prompts get-metadata act1-sc01 "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "title: The Finest Cartographer" "prompts: get_scene_metadata has title"
assert_contains "$result" "pov:" "prompts: get_scene_metadata has pov"

echo "  --- prompts: get_previous_scene ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.prompts get-previous act1-sc02 "$FIXTURE_DIR" 2>/dev/null)
assert_equals "act1-sc01" "$result" "prompts: get_previous_scene returns correct id"

echo "  --- prompts: list_reference_files ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.prompts list-refs "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "reference/" "prompts: list_reference_files returns relative paths"

# ============================================================================
# storyforge.revision
# ============================================================================

echo "  --- revision: resolve_scope ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.revision resolve-scope full "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "act1-sc01.md" "revision: resolve_scope full includes first scene"
assert_contains "$result" "act2-sc01.md" "revision: resolve_scope full includes act2 scene"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.revision resolve-scope act1-sc01,act1-sc02 "$FIXTURE_DIR" 2>/dev/null)
assert_contains "$result" "act1-sc01.md" "revision: resolve_scope csv includes first id"
assert_contains "$result" "act1-sc02.md" "revision: resolve_scope csv includes second id"

# ============================================================================
# storyforge.scoring
# ============================================================================

echo "  --- scoring: parse_score_output ---"

SCORE_TMP="$(mktemp -d)"
cat > "${SCORE_TMP}/scores-text.txt" <<'TXT'
Some analysis text.

{{SCORES:}}
principle|score
economy_clarity|4
enter_late_leave_early|3
{{END_SCORES}}

{{RATIONALE:}}
principle|rationale
economy_clarity|Good prose density
enter_late_leave_early|Opens a bit early
{{END_RATIONALE}}
TXT

PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.scoring parse-output "${SCORE_TMP}/scores-text.txt" "${SCORE_TMP}/scores.csv" "${SCORE_TMP}/rationale.csv" 2>/dev/null
assert_file_exists "${SCORE_TMP}/scores.csv" "scoring: parse_output creates scores file"
assert_file_exists "${SCORE_TMP}/rationale.csv" "scoring: parse_output creates rationale file"

scores_content=$(cat "${SCORE_TMP}/scores.csv")
assert_contains "$scores_content" "economy_clarity|4" "scoring: scores has correct value"

echo "  --- scoring: build_weighted_text ---"

# Use default weights from plugin
result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.scoring weighted-text "${PLUGIN_DIR}/references/default-craft-weights.csv" 2>/dev/null)
if [[ -n "$result" ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: scoring: weighted_text returns output"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: scoring: weighted_text returned empty"
fi

echo "  --- scoring: effective_weight ---"

# Create a temp weights file for testing
cat > "${SCORE_TMP}/weights.csv" <<'CSV'
section|principle|weight|author_weight|notes
scene_craft|enter_late_leave_early|5||
scene_craft|every_scene_must_turn|7|9|author override
CSV

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.scoring effective-weight "${SCORE_TMP}/weights.csv" every_scene_must_turn 2>/dev/null)
assert_equals "9" "$result" "scoring: effective_weight returns author_weight when set"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.scoring effective-weight "${SCORE_TMP}/weights.csv" enter_late_leave_early 2>/dev/null)
assert_equals "5" "$result" "scoring: effective_weight returns weight when no author_weight"

rm -rf "$SCORE_TMP"

# ============================================================================
# storyforge.assembly
# ============================================================================

echo "  --- assembly: extract_scene_prose ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.assembly extract-prose "${FIXTURE_DIR}/scenes/act1-sc01.md" 2>/dev/null)
assert_not_empty "$result" "assembly: extract_scene_prose returns content"
# Should not contain frontmatter markers
assert_not_contains "$result" "---" "assembly: extract_scene_prose strips frontmatter delimiters"

echo "  --- assembly: count_chapters ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.assembly import count_chapters
print(count_chapters('${FIXTURE_DIR}'))
" 2>/dev/null)
assert_equals "2" "$result" "assembly: count_chapters finds 2 chapters"

echo "  --- assembly: read_chapter_field ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.assembly import read_chapter_field
print(read_chapter_field(1, '${FIXTURE_DIR}', 'title'))
" 2>/dev/null)
assert_equals "The Finest Cartographer" "$result" "assembly: read_chapter_field reads title"

echo "  --- assembly: get_chapter_scenes ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.assembly import get_chapter_scenes
scenes = get_chapter_scenes(1, '${FIXTURE_DIR}')
print(';'.join(scenes))
" 2>/dev/null)
assert_contains "$result" "act1-sc01" "assembly: get_chapter_scenes includes first scene"
assert_contains "$result" "act1-sc02" "assembly: get_chapter_scenes includes second scene"

echo "  --- assembly: assemble_chapter ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.assembly chapter 1 "${FIXTURE_DIR}" 2>/dev/null)
assert_contains "$result" "Finest Cartographer" "assembly: assemble_chapter has title"
assert_not_empty "$result" "assembly: assemble_chapter returns content"

echo "  --- assembly: generate_toc ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.assembly toc "${FIXTURE_DIR}" 2>/dev/null)
assert_contains "$result" "Finest Cartographer" "assembly: generate_toc includes chapter 1"
assert_contains "$result" "Into the Blank" "assembly: generate_toc includes chapter 2"

echo "  --- assembly: word_count ---"

# Create a temp manuscript
ASSEMBLY_TMP="$(mktemp -d)"
echo "One two three four five six seven eight nine ten." > "${ASSEMBLY_TMP}/test.md"
result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.assembly word-count "${ASSEMBLY_TMP}/test.md" 2>/dev/null)
assert_equals "10" "$result" "assembly: word_count counts correctly"
rm -rf "$ASSEMBLY_TMP"

# ============================================================================
# storyforge.visualize
# ============================================================================

echo "  --- visualize: csv_to_records ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.visualize import csv_to_records
records = csv_to_records('${FIXTURE_DIR}/reference/scene-metadata.csv')
print(len(records))
" 2>/dev/null)
# Fixture has 4 scenes (3 data rows + act2-sc01 which might be 4 total)
if [[ "$result" -ge 3 ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: visualize: csv_to_records returns records ($result)"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: visualize: csv_to_records expected >= 3 records, got $result"
fi

echo "  --- visualize: load_dashboard_data ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.visualize import load_dashboard_data
data = load_dashboard_data('${FIXTURE_DIR}')
print(json.dumps(list(data.keys())))
" 2>/dev/null)
assert_contains "$result" "scenes" "visualize: load_dashboard_data has scenes key"
assert_contains "$result" "intents" "visualize: load_dashboard_data has intents key"
assert_contains "$result" "project" "visualize: load_dashboard_data has project key"

# ============================================================================
# storyforge.enrich
# ============================================================================

echo "  --- enrich: parse_enrich_response ---"

ENRICH_TMP="$(mktemp -d)"
cat > "${ENRICH_TMP}/response.txt" <<'TXT'
Here is my analysis of this scene.

TYPE: action
LOCATION: The Deep Archive
TIME_OF_DAY: evening
CHARACTERS: Dorren;the Archivist;Pell
EMOTIONAL_ARC: tension → revelation
THREADS: succession;map trust
MOTIFS: maps;depth
TXT

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.enrich import parse_enrich_response
with open('${ENRICH_TMP}/response.txt') as f:
    r = parse_enrich_response(f.read(), 'test-scene')
print(json.dumps(r))
" 2>/dev/null)
assert_contains "$result" '"type": "action"' "enrich: parse_enrich_response extracts type"
assert_contains "$result" "Deep Archive" "enrich: parse_enrich_response extracts location"
assert_contains "$result" "Dorren" "enrich: parse_enrich_response extracts characters"

echo "  --- enrich: alias normalization ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${FIXTURE_DIR}/reference/characters.csv')
print(normalize_aliases(amap, 'Dorren;the Archivist;Pell'))
" 2>/dev/null)
assert_equals "Dorren Hayle;Kael Maren;Pell" "$result" "enrich: normalize_aliases resolves character aliases"

echo "  --- enrich: validate_type ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import validate_type
print(validate_type('action'))
" 2>/dev/null)
assert_equals "action" "$result" "enrich: validate_type accepts valid type"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import validate_type
print(validate_type('invalid_thing'))
" 2>/dev/null)
assert_empty "$result" "enrich: validate_type rejects invalid type"

rm -rf "$ENRICH_TMP"

# ============================================================================
# storyforge.scenes
# ============================================================================

echo "  --- scenes: generate_slug ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.scenes generate-slug "The Finest Cartographer" 2>/dev/null)
assert_equals "finest-cartographer" "$result" "scenes: generate_slug produces correct slug"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.scenes generate-slug "A Very Long Title With Many Words" 2>/dev/null)
assert_not_empty "$result" "scenes: generate_slug handles long titles"
assert_not_contains "$result" " " "scenes: generate_slug has no spaces"

echo "  --- scenes: parse_scene_boundaries ---"

SCENES_TMP="$(mktemp -d)"
cat > "${SCENES_TMP}/response.txt" <<'TXT'
SCENE: 1 | the-finest-cartographer | Opening with Dorren at the table
SCENE: 45 | the-last-calibrator | Calibrator arrives
SCENE: 89 | into-the-blank | The expedition begins
TXT

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.scenes parse-boundaries "${SCENES_TMP}/response.txt" 2>/dev/null)
assert_contains "$result" "finest-cartographer" "scenes: parse_boundaries finds first scene"
assert_contains "$result" "last-calibrator" "scenes: parse_boundaries finds second scene"
assert_contains "$result" "into-the-blank" "scenes: parse_boundaries finds third scene"

rm -rf "$SCENES_TMP"

# ============================================================================
# storyforge.timeline
# ============================================================================

echo "  --- timeline: parse_indicators ---"

TIMELINE_TMP="$(mktemp -d)"
cat > "${TIMELINE_TMP}/response.txt" <<'TXT'
DELTA: next_day
EVIDENCE: "The sun rose over the archive"
ANCHOR: none
TXT

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.timeline import parse_indicators
with open('${TIMELINE_TMP}/response.txt') as f:
    r = parse_indicators(f.read(), 'test-scene')
print(json.dumps(r))
" 2>/dev/null)
assert_contains "$result" "next_day" "timeline: parse_indicators extracts delta"
assert_contains "$result" "sun rose" "timeline: parse_indicators extracts evidence"
assert_contains "$result" "none" "timeline: parse_indicators extracts anchor"

echo "  --- timeline: parse_timeline_assignments ---"

cat > "${TIMELINE_TMP}/assignments.txt" <<'TXT'
Here is my analysis.

TIMELINE:
id|timeline_day
scene-1|1
scene-2|1
scene-3|2
scene-4|5

Summary text.
TXT

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.timeline import parse_timeline_assignments
with open('${TIMELINE_TMP}/assignments.txt') as f:
    r = parse_timeline_assignments(f.read())
print(json.dumps(r))
" 2>/dev/null)
assert_contains "$result" '"scene-1": 1' "timeline: parse_assignments reads scene-1"
assert_contains "$result" '"scene-4": 5' "timeline: parse_assignments reads scene-4"

rm -rf "$TIMELINE_TMP"

# ============================================================================
# storyforge.cover
# ============================================================================

echo "  --- cover: wrap_title_for_svg ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.cover wrap-title "A Very Long Book Title That Needs Wrapping" 2>/dev/null)
# Should have multiple lines
line_count=$(echo "$result" | wc -l | tr -d ' ')
if [[ "$line_count" -ge 2 ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: cover: wrap_title produces multiple lines ($line_count)"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: cover: wrap_title expected >= 2 lines, got $line_count"
fi

echo "  --- cover: get_color_scheme ---"

result=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.cover import get_color_scheme
scheme = get_color_scheme('fantasy')
print(json.dumps(list(scheme.keys())))
" 2>/dev/null)
assert_contains "$result" "bg" "cover: get_color_scheme returns bg key"
assert_contains "$result" "accent" "cover: get_color_scheme returns accent key"

echo "  --- cover: render_svg_template ---"

COVER_TMP="$(mktemp -d)"
cat > "${COVER_TMP}/template.svg" <<'SVG'
<svg><text>{{TITLE}}</text><text>{{AUTHOR}}</text></svg>
SVG

result=$(PYTHONPATH="$PYTHON_DIR" python3 -m storyforge.cover render "${COVER_TMP}/template.svg" "${COVER_TMP}/output.svg" --title "Test Book" --author "Test Author" 2>/dev/null)
content=$(cat "${COVER_TMP}/output.svg")
assert_contains "$content" "Test Book" "cover: render substitutes title"
assert_contains "$content" "Test Author" "cover: render substitutes author"
assert_not_contains "$content" "{{TITLE}}" "cover: render removes placeholders"

rm -rf "$COVER_TMP"
rm -rf "$PARSE_TMP"

#!/bin/bash
# test-craft-sections.sh — Tests for craft engine section extraction
#
# Run via: ./tests/run-tests.sh
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# Verify all 7 sections are extractable
# ============================================================================

for i in 1 2 3 4 5 6 7; do
    result=$(extract_craft_sections "$i")
    assert_not_empty "$result" "section ${i}: extractable"
done

# ============================================================================
# Verify section headers
# ============================================================================

result=$(extract_craft_sections 1)
assert_contains "$result" "## 1. Narrative Structure Frameworks" "section 1: correct header"

result=$(extract_craft_sections 2)
assert_contains "$result" "## 2. Scene Craft" "section 2: correct header"

result=$(extract_craft_sections 3)
assert_contains "$result" "## 3. Prose Craft Principles" "section 3: correct header"

result=$(extract_craft_sections 4)
assert_contains "$result" "## 4. Character Craft" "section 4: correct header"

result=$(extract_craft_sections 5)
assert_contains "$result" "## 5. The Rules and When to Break Them" "section 5: correct header"

result=$(extract_craft_sections 6)
assert_contains "$result" "## 6. Tropes and Genre Conventions" "section 6: correct header"

result=$(extract_craft_sections 7)
assert_contains "$result" "## 7. The Coaching Posture" "section 7: correct header"

# ============================================================================
# Verify section content
# ============================================================================

result=$(extract_craft_sections 1)
assert_contains "$result" "Campbell" "section 1: contains Campbell"
assert_contains "$result" "Kishotenketsu" "section 1: contains Kishotenketsu"

result=$(extract_craft_sections 2)
assert_contains "$result" "Enter Late" "section 2: contains Enter Late"
assert_contains "$result" "Every Scene Must Turn" "section 2: contains scene turn"

result=$(extract_craft_sections 3)
assert_contains "$result" "Economy and Clarity" "section 3: contains Economy"

result=$(extract_craft_sections 4)
assert_contains "$result" "Want/Need Framework" "section 4: contains Want/Need"
assert_contains "$result" "Wound and the Lie" "section 4: contains Wound"

result=$(extract_craft_sections 5)
assert_contains "$result" "Show, Don't Tell" "section 5: contains Show Don't Tell"
assert_contains "$result" "Kill Your Darlings" "section 5: contains Kill Your Darlings"

result=$(extract_craft_sections 6)
assert_contains "$result" "Tropes" "section 6: contains Tropes"
assert_contains "$result" "Genre Conventions" "section 6: contains Genre Conventions"

result=$(extract_craft_sections 7)
assert_contains "$result" "Coaching Posture" "section 7: contains Coaching Posture"
assert_contains "$result" "Five Postures" "section 7: contains Five Postures"

# ============================================================================
# Verify sections don't overlap
# ============================================================================

section2=$(extract_craft_sections 2)
section3=$(extract_craft_sections 3)

# Section 2 should not contain section 3 content
assert_not_contains "$section2" "## 3. Prose Craft" "section 2: does not contain section 3 header"
assert_not_contains "$section2" "Economy and Clarity" "section 2: does not contain section 3 content"

# Section 3 should not contain section 2 content
assert_not_contains "$section3" "## 2. Scene Craft" "section 3: does not contain section 2 header"
assert_not_contains "$section3" "Enter Late" "section 3: does not contain section 2 content"

# Section 6 should not contain section 7 content
section6=$(extract_craft_sections 6)
assert_not_contains "$section6" "## 7." "section 6: does not contain section 7 header"
assert_not_contains "$section6" "Coaching Posture" "section 6: does not contain section 7 content"

# ============================================================================
# Multiple sections maintain order
# ============================================================================

multi=$(extract_craft_sections 1 4 7)
# Check that sections appear in order by finding their positions
pos1=$(echo "$multi" | grep -n "## 1\." | head -1 | cut -d: -f1)
pos4=$(echo "$multi" | grep -n "## 4\." | head -1 | cut -d: -f1)
pos7=$(echo "$multi" | grep -n "## 7\." | head -1 | cut -d: -f1)

if [[ -n "$pos1" && -n "$pos4" && -n "$pos7" ]] && (( pos1 < pos4 )) && (( pos4 < pos7 )); then
    PASS=$((PASS + 1))
    echo "  PASS: multi-section: sections in order (1 < 4 < 7)"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: multi-section: sections not in expected order"
    echo "    Positions: 1=${pos1:-missing}, 4=${pos4:-missing}, 7=${pos7:-missing}"
fi

# Separators between sections
assert_contains "$multi" "---" "multi-section: has separator"

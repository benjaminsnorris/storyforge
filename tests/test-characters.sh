#!/bin/bash
# test-characters.sh — Tests for characters.sh shared library

# Tests use $FIXTURE_DIR, $PROJECT_DIR, $PLUGIN_DIR, $TMPDIR
# Libraries are already sourced by run-tests.sh

CHARACTERS_CSV="${FIXTURE_DIR}/reference/characters.csv"

# ============================================================================
# load_character_aliases
# ============================================================================

echo "--- load_character_aliases ---"

ALIASES_FILE=$(load_character_aliases "$CHARACTERS_CSV")
assert_not_empty "$ALIASES_FILE" "load: returns a file path"
assert_file_exists "$ALIASES_FILE" "load: file exists"

# Check canonical self-mappings
RESULT=$(grep "^dorren hayle|" "$ALIASES_FILE" | head -1)
assert_contains "$RESULT" "Dorren Hayle" "load: canonical self-mapping for Dorren Hayle"

RESULT=$(grep "^pell|" "$ALIASES_FILE" | head -1)
assert_contains "$RESULT" "Pell" "load: canonical self-mapping for Pell"

# Check alias mappings
RESULT=$(grep "^dorren|" "$ALIASES_FILE" | head -1)
assert_contains "$RESULT" "Dorren Hayle" "load: alias 'Dorren' maps to Dorren Hayle"

RESULT=$(grep "^dr. hayle|" "$ALIASES_FILE" | head -1)
assert_contains "$RESULT" "Dorren Hayle" "load: alias 'Dr. Hayle' maps to Dorren Hayle"

RESULT=$(grep "^the archivist|" "$ALIASES_FILE" | head -1)
assert_contains "$RESULT" "Kael Maren" "load: alias 'the Archivist' maps to Kael Maren"

RESULT=$(grep "^tessa|" "$ALIASES_FILE" | head -1)
assert_contains "$RESULT" "Tessa Merrin" "load: alias 'Tessa' maps to Tessa Merrin"

# ============================================================================
# normalize_characters — basic resolution
# ============================================================================

echo "--- normalize_characters: basic ---"

RESULT=$(normalize_characters "$ALIASES_FILE" "Dorren Hayle;Tessa Merrin;Pell")
assert_equals "Dorren Hayle;Tessa Merrin;Pell" "$RESULT" "normalize: canonical names pass through"

RESULT=$(normalize_characters "$ALIASES_FILE" "Dorren;Tessa;Pell")
assert_equals "Dorren Hayle;Tessa Merrin;Pell" "$RESULT" "normalize: aliases resolve to canonical"

RESULT=$(normalize_characters "$ALIASES_FILE" "Dr. Hayle;the Archivist")
assert_equals "Dorren Hayle;Kael Maren" "$RESULT" "normalize: mixed aliases resolve"

# ============================================================================
# normalize_characters — case insensitive
# ============================================================================

echo "--- normalize_characters: case insensitive ---"

RESULT=$(normalize_characters "$ALIASES_FILE" "dorren;TESSA;pElL")
assert_equals "Dorren Hayle;Tessa Merrin;Pell" "$RESULT" "normalize: case-insensitive matching"

RESULT=$(normalize_characters "$ALIASES_FILE" "DORREN HAYLE")
assert_equals "Dorren Hayle" "$RESULT" "normalize: uppercase canonical resolves"

# ============================================================================
# normalize_characters — unknown names pass through
# ============================================================================

echo "--- normalize_characters: unknown passthrough ---"

RESULT=$(normalize_characters "$ALIASES_FILE" "Dorren;Unknown Character;Pell")
assert_equals "Dorren Hayle;Unknown Character;Pell" "$RESULT" "normalize: unknown names pass through"

RESULT=$(normalize_characters "$ALIASES_FILE" "Someone New")
assert_equals "Someone New" "$RESULT" "normalize: fully unknown passes through"

# ============================================================================
# normalize_characters — deduplication
# ============================================================================

echo "--- normalize_characters: deduplication ---"

RESULT=$(normalize_characters "$ALIASES_FILE" "Dorren;Dorren Hayle;Dr. Hayle")
assert_equals "Dorren Hayle" "$RESULT" "normalize: deduplicates multiple aliases to same canonical"

RESULT=$(normalize_characters "$ALIASES_FILE" "Tessa;Merrin;Tessa Merrin")
assert_equals "Tessa Merrin" "$RESULT" "normalize: deduplicates Tessa variants"

RESULT=$(normalize_characters "$ALIASES_FILE" "Dorren;Tessa;Dorren Hayle")
assert_equals "Dorren Hayle;Tessa Merrin" "$RESULT" "normalize: preserves first-occurrence order"

# ============================================================================
# normalize_characters — edge cases
# ============================================================================

echo "--- normalize_characters: edge cases ---"

RESULT=$(normalize_characters "$ALIASES_FILE" "")
assert_empty "$RESULT" "normalize: empty string returns empty"

RESULT=$(normalize_characters "" "Dorren;Tessa")
assert_equals "Dorren;Tessa" "$RESULT" "normalize: no aliases file passes through"

RESULT=$(normalize_characters "/nonexistent/file" "Dorren;Tessa")
assert_equals "Dorren;Tessa" "$RESULT" "normalize: nonexistent aliases file passes through"

RESULT=$(normalize_characters "$ALIASES_FILE" "  Dorren ; Tessa  ;  Pell  ")
assert_equals "Dorren Hayle;Tessa Merrin;Pell" "$RESULT" "normalize: handles whitespace around names"

# ============================================================================
# load_character_aliases — graceful with missing file
# ============================================================================

echo "--- load_character_aliases: missing file ---"

MISSING_ALIASES=$(load_character_aliases "/nonexistent/characters.csv")
assert_not_empty "$MISSING_ALIASES" "load missing: still returns a file path"
MISSING_LINES=$(wc -l < "$MISSING_ALIASES" | tr -d ' ')
assert_equals "0" "$MISSING_LINES" "load missing: file is empty"

# Clean up temp files
rm -f "$ALIASES_FILE" "$MISSING_ALIASES"

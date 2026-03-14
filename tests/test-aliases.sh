#!/bin/bash
# test-aliases.sh — Tests for aliases.sh shared library (characters, motifs, locations, threads)

# Tests use $FIXTURE_DIR, $PROJECT_DIR, $PLUGIN_DIR, $TMPDIR
# Libraries are already sourced by run-tests.sh

CHARACTERS_CSV="${FIXTURE_DIR}/reference/characters.csv"
MOTIF_CSV="${FIXTURE_DIR}/reference/motif-taxonomy.csv"
LOCATIONS_CSV="${FIXTURE_DIR}/reference/locations.csv"
THREADS_CSV="${FIXTURE_DIR}/reference/threads.csv"

# ============================================================================
# load_alias_map — characters
# ============================================================================

echo "--- load_alias_map: characters ---"

CHAR_MAP=$(load_alias_map "$CHARACTERS_CSV")
assert_not_empty "$CHAR_MAP" "load chars: returns a file path"
assert_file_exists "$CHAR_MAP" "load chars: file exists"

RESULT=$(grep "^dorren hayle|" "$CHAR_MAP" | head -1)
assert_contains "$RESULT" "Dorren Hayle" "load chars: canonical self-mapping"

RESULT=$(grep "^dorren|" "$CHAR_MAP" | head -1)
assert_contains "$RESULT" "Dorren Hayle" "load chars: alias mapping"

RESULT=$(grep "^the archivist|" "$CHAR_MAP" | head -1)
assert_contains "$RESULT" "Kael Maren" "load chars: alias 'the Archivist' maps to Kael Maren"

# ============================================================================
# load_alias_map — motifs
# ============================================================================

echo "--- load_alias_map: motifs ---"

MOTIF_MAP=$(load_alias_map "$MOTIF_CSV")
assert_not_empty "$MOTIF_MAP" "load motifs: returns a file path"

RESULT=$(grep "^cartography|" "$MOTIF_MAP" | head -1)
assert_contains "$RESULT" "Maps" "load motifs: alias 'cartography' maps to Maps"

RESULT=$(grep "^governance-as-weight|" "$MOTIF_MAP" | head -1)
assert_contains "$RESULT" "Governance" "load motifs: alias 'governance-as-weight' maps to Governance"

RESULT=$(grep "^depth/descent|" "$MOTIF_MAP" | head -1)
assert_contains "$RESULT" "Depth" "load motifs: alias 'depth/descent' maps to Depth"

# ============================================================================
# load_alias_map — locations
# ============================================================================

echo "--- load_alias_map: locations ---"

LOC_MAP=$(load_alias_map "$LOCATIONS_CSV")
assert_not_empty "$LOC_MAP" "load locations: returns a file path"

RESULT=$(grep "^the deep archive|" "$LOC_MAP" | head -1)
assert_contains "$RESULT" "Deep Archive" "load locations: alias 'The Deep Archive' maps to Deep Archive"

RESULT=$(grep "^pco|" "$LOC_MAP" | head -1)
assert_contains "$RESULT" "Pressure Cartography Office" "load locations: alias 'PCO' maps to canonical"

# ============================================================================
# normalize_aliases — characters
# ============================================================================

echo "--- normalize_aliases: characters ---"

RESULT=$(normalize_aliases "$CHAR_MAP" "Dorren;Tessa;Pell")
assert_equals "Dorren Hayle;Tessa Merrin;Pell" "$RESULT" "normalize chars: aliases resolve"

RESULT=$(normalize_aliases "$CHAR_MAP" "dorren;TESSA;pElL")
assert_equals "Dorren Hayle;Tessa Merrin;Pell" "$RESULT" "normalize chars: case-insensitive"

RESULT=$(normalize_aliases "$CHAR_MAP" "Dorren;Dorren Hayle;Dr. Hayle")
assert_equals "Dorren Hayle" "$RESULT" "normalize chars: deduplicates"

RESULT=$(normalize_aliases "$CHAR_MAP" "Dorren;Unknown Character;Pell")
assert_equals "Dorren Hayle;Unknown Character;Pell" "$RESULT" "normalize chars: unknown passthrough"

# ============================================================================
# normalize_aliases — motifs
# ============================================================================

echo "--- normalize_aliases: motifs ---"

RESULT=$(normalize_aliases "$MOTIF_MAP" "cartography;governance-as-weight;depth/descent")
assert_equals "Maps;Governance;Depth" "$RESULT" "normalize motifs: aliases resolve"

RESULT=$(normalize_aliases "$MOTIF_MAP" "maps/cartography;Maps;cartography")
assert_equals "Maps" "$RESULT" "normalize motifs: deduplicates variants"

RESULT=$(normalize_aliases "$MOTIF_MAP" "cartography;unknown_motif;depth/descent")
assert_equals "Maps;unknown_motif;Depth" "$RESULT" "normalize motifs: unknown passthrough"

RESULT=$(normalize_aliases "$MOTIF_MAP" "CARTOGRAPHY;Depth/Descent")
assert_equals "Maps;Depth" "$RESULT" "normalize motifs: case-insensitive"

# ============================================================================
# normalize_aliases — locations
# ============================================================================

echo "--- normalize_aliases: locations ---"

RESULT=$(normalize_aliases "$LOC_MAP" "The Deep Archive")
assert_equals "Deep Archive" "$RESULT" "normalize locations: resolves alias"

RESULT=$(normalize_aliases "$LOC_MAP" "PCO")
assert_equals "Pressure Cartography Office" "$RESULT" "normalize locations: abbreviation resolves"

RESULT=$(normalize_aliases "$LOC_MAP" "Dorren's private study")
assert_equals "Dorren's study" "$RESULT" "normalize locations: variant resolves"

RESULT=$(normalize_aliases "$LOC_MAP" "Unknown Place")
assert_equals "Unknown Place" "$RESULT" "normalize locations: unknown passthrough"

# ============================================================================
# load_alias_map + normalize_aliases — threads
# ============================================================================

echo "--- load_alias_map: threads ---"

THREAD_MAP=$(load_alias_map "$THREADS_CSV")
assert_not_empty "$THREAD_MAP" "load threads: returns a file path"
assert_file_exists "$THREAD_MAP" "load threads: file exists"

echo "--- normalize_aliases: threads ---"

RESULT=$(normalize_aliases "$THREAD_MAP" "succession;map trust;being erased")
assert_equals "Succession crisis;Trust in cartography;Erasure" "$RESULT" "normalize threads: aliases resolve"

RESULT=$(normalize_aliases "$THREAD_MAP" "the succession;Succession crisis;who rules next")
assert_equals "Succession crisis" "$RESULT" "normalize threads: deduplicates variants"

RESULT=$(normalize_aliases "$THREAD_MAP" "succession;unknown thread;erasure")
assert_equals "Succession crisis;unknown thread;Erasure" "$RESULT" "normalize threads: unknown passthrough"

RESULT=$(normalize_aliases "$THREAD_MAP" "SUCCESSION;Trusting Maps")
assert_equals "Succession crisis;Trust in cartography" "$RESULT" "normalize threads: case-insensitive"

# ============================================================================
# normalize_aliases — edge cases
# ============================================================================

echo "--- normalize_aliases: edge cases ---"

RESULT=$(normalize_aliases "$CHAR_MAP" "")
assert_empty "$RESULT" "normalize: empty string returns empty"

RESULT=$(normalize_aliases "" "Dorren;Tessa")
assert_equals "Dorren;Tessa" "$RESULT" "normalize: no map file passes through"

RESULT=$(normalize_aliases "/nonexistent/file" "Dorren;Tessa")
assert_equals "Dorren;Tessa" "$RESULT" "normalize: nonexistent map passes through"

RESULT=$(normalize_aliases "$CHAR_MAP" "  Dorren ; Tessa  ;  Pell  ")
assert_equals "Dorren Hayle;Tessa Merrin;Pell" "$RESULT" "normalize: handles whitespace"

# ============================================================================
# Backwards-compatible wrappers
# ============================================================================

echo "--- backwards compat ---"

COMPAT_MAP=$(load_character_aliases "$CHARACTERS_CSV")
assert_not_empty "$COMPAT_MAP" "compat: load_character_aliases works"
RESULT=$(normalize_characters "$COMPAT_MAP" "Dorren;Tessa")
assert_equals "Dorren Hayle;Tessa Merrin" "$RESULT" "compat: normalize_characters works"

# ============================================================================
# load_alias_map — graceful with missing file
# ============================================================================

echo "--- load_alias_map: missing file ---"

MISSING_MAP=$(load_alias_map "/nonexistent/file.csv")
assert_not_empty "$MISSING_MAP" "load missing: still returns a file path"
MISSING_LINES=$(wc -l < "$MISSING_MAP" | tr -d ' ')
assert_equals "0" "$MISSING_LINES" "load missing: file is empty"

# Clean up temp files
rm -f "$CHAR_MAP" "$MOTIF_MAP" "$LOC_MAP" "$COMPAT_MAP" "$MISSING_MAP"

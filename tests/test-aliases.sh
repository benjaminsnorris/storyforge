#!/bin/bash
# test-aliases.sh — Tests for alias normalization (Python enrich module)

# Tests use $FIXTURE_DIR, $PROJECT_DIR, $PLUGIN_DIR, $TMPDIR
PYTHON_DIR="${PLUGIN_DIR}/scripts/lib/python"

CHARACTERS_CSV="${FIXTURE_DIR}/reference/characters.csv"
MOTIF_CSV="${FIXTURE_DIR}/reference/motif-taxonomy.csv"
LOCATIONS_CSV="${FIXTURE_DIR}/reference/locations.csv"
THREADS_CSV="${FIXTURE_DIR}/reference/threads.csv"

# ============================================================================
# load_alias_map + normalize_aliases — characters
# ============================================================================

echo "--- load_alias_map: characters ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
import json
from storyforge.enrich import load_alias_map
amap = load_alias_map('${CHARACTERS_CSV}')
print(json.dumps(amap))
" 2>/dev/null)
assert_not_empty "$RESULT" "load chars: returns data"
assert_contains "$RESULT" "Dorren Hayle" "load chars: canonical self-mapping"
assert_contains "$RESULT" "Kael Maren" "load chars: alias mapping"

# Test 'the Archivist' maps to Kael Maren
RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'the Archivist'))
" 2>/dev/null)
assert_equals "Kael Maren" "$RESULT" "load chars: alias 'the Archivist' maps to Kael Maren"

echo "--- load_alias_map: motifs ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'cartography'))
" 2>/dev/null)
assert_equals "Maps" "$RESULT" "load motifs: alias 'cartography' maps to Maps"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'governance-as-weight'))
" 2>/dev/null)
assert_equals "Governance" "$RESULT" "load motifs: alias 'governance-as-weight' maps to Governance"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'depth/descent'))
" 2>/dev/null)
assert_equals "Depth" "$RESULT" "load motifs: alias 'depth/descent' maps to Depth"

echo "--- load_alias_map: locations ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${LOCATIONS_CSV}')
print(normalize_aliases(amap, 'The Deep Archive'))
" 2>/dev/null)
assert_equals "Deep Archive" "$RESULT" "load locations: resolves alias"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${LOCATIONS_CSV}')
print(normalize_aliases(amap, 'PCO'))
" 2>/dev/null)
assert_equals "Pressure Cartography Office" "$RESULT" "load locations: abbreviation resolves"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${LOCATIONS_CSV}')
print(normalize_aliases(amap, \"Dorren's private study\"))
" 2>/dev/null)
assert_equals "Dorren's study" "$RESULT" "load locations: variant resolves"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${LOCATIONS_CSV}')
print(normalize_aliases(amap, 'Unknown Place'))
" 2>/dev/null)
assert_equals "Unknown Place" "$RESULT" "load locations: unknown passthrough"

# ============================================================================
# normalize_aliases — characters
# ============================================================================

echo "--- normalize_aliases: characters ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'Dorren;the Archivist;Pell'))
" 2>/dev/null)
assert_equals "Dorren Hayle;Kael Maren;Pell" "$RESULT" "normalize chars: aliases resolve"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'dorren;TESSA;kael'))
" 2>/dev/null)
assert_equals "Dorren Hayle;Tessa Merrin;Kael Maren" "$RESULT" "normalize chars: case-insensitive"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'Dorren;Dr. Hayle;Hayle'))
" 2>/dev/null)
assert_equals "Dorren Hayle" "$RESULT" "normalize chars: deduplicates"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'Dorren;Unknown Person;Pell'))
" 2>/dev/null)
assert_equals "Dorren Hayle;Unknown Person;Pell" "$RESULT" "normalize chars: unknown passthrough"

# ============================================================================
# normalize_aliases — motifs
# ============================================================================

echo "--- normalize_aliases: motifs ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'cartography;governance-as-weight;depth/descent'))
" 2>/dev/null)
assert_equals "Maps;Governance;Depth" "$RESULT" "normalize motifs: aliases resolve"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'maps/cartography;Maps;cartography'))
" 2>/dev/null)
assert_equals "Maps" "$RESULT" "normalize motifs: deduplicates variants"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'cartography;unknown_motif;depth/descent'))
" 2>/dev/null)
assert_equals "Maps;unknown_motif;Depth" "$RESULT" "normalize motifs: unknown passthrough"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'CARTOGRAPHY;Depth/Descent'))
" 2>/dev/null)
assert_equals "Maps;Depth" "$RESULT" "normalize motifs: case-insensitive"

# ============================================================================
# load_alias_map + normalize_aliases — threads
# ============================================================================

echo "--- normalize_aliases: threads ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${THREADS_CSV}')
print(normalize_aliases(amap, 'succession;map trust;being erased'))
" 2>/dev/null)
assert_equals "Succession crisis;Trust in cartography;Erasure" "$RESULT" "normalize threads: aliases resolve"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${THREADS_CSV}')
print(normalize_aliases(amap, 'the succession;Succession crisis;who rules next'))
" 2>/dev/null)
assert_equals "Succession crisis" "$RESULT" "normalize threads: deduplicates variants"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${THREADS_CSV}')
print(normalize_aliases(amap, 'succession;unknown thread;erasure'))
" 2>/dev/null)
assert_equals "Succession crisis;unknown thread;Erasure" "$RESULT" "normalize threads: unknown passthrough"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${THREADS_CSV}')
print(normalize_aliases(amap, 'SUCCESSION;Trusting Maps'))
" 2>/dev/null)
assert_equals "Succession crisis;Trust in cartography" "$RESULT" "normalize threads: case-insensitive"

# ============================================================================
# Edge cases
# ============================================================================

echo "--- normalize_aliases: edge cases ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import normalize_aliases
print(normalize_aliases({}, ''))
" 2>/dev/null)
assert_empty "$RESULT" "normalize: empty string returns empty"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import normalize_aliases
print(normalize_aliases({}, 'Dorren;Tessa'))
" 2>/dev/null)
assert_equals "Dorren;Tessa" "$RESULT" "normalize: empty map passes through"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, '  Dorren ; Tessa  ;  Pell  '))
" 2>/dev/null)
assert_equals "Dorren Hayle;Tessa Merrin;Pell" "$RESULT" "normalize: handles whitespace"

# Missing file returns empty map
RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map
amap = load_alias_map('/nonexistent/file.csv')
print(len(amap))
" 2>/dev/null)
assert_equals "0" "$RESULT" "load missing: returns empty map"

#!/bin/bash
# test-aliases.sh — Tests for alias normalization (Python enrich module)

# Tests use $FIXTURE_DIR, $PROJECT_DIR, $PLUGIN_DIR, $TMPDIR
PYTHON_DIR="${PLUGIN_DIR}/scripts/lib/python"

CHARACTERS_CSV="${FIXTURE_DIR}/reference/characters.csv"
MOTIF_CSV="${FIXTURE_DIR}/reference/motif-taxonomy.csv"
LOCATIONS_CSV="${FIXTURE_DIR}/reference/locations.csv"

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
assert_contains "$RESULT" "dorren-hayle" "load chars: canonical id mapping"
assert_contains "$RESULT" "kael-maren" "load chars: alias maps to id"

# Test 'the Archivist' maps to kael-maren
RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'the Archivist'))
" 2>/dev/null)
assert_equals "kael-maren" "$RESULT" "load chars: alias 'the Archivist' maps to kael-maren"

echo "--- load_alias_map: motifs ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'cartography'))
" 2>/dev/null)
assert_equals "maps" "$RESULT" "load motifs: alias 'cartography' maps to maps"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'governance-as-weight'))
" 2>/dev/null)
assert_equals "governance" "$RESULT" "load motifs: alias 'governance-as-weight' maps to governance"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'depth/descent'))
" 2>/dev/null)
assert_equals "depth" "$RESULT" "load motifs: alias 'depth/descent' maps to depth"

echo "--- load_alias_map: locations ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${LOCATIONS_CSV}')
print(normalize_aliases(amap, 'The Deep Archive'))
" 2>/dev/null)
assert_equals "deep-archive" "$RESULT" "load locations: resolves alias"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${LOCATIONS_CSV}')
print(normalize_aliases(amap, 'PCO'))
" 2>/dev/null)
assert_equals "cartography-office" "$RESULT" "load locations: abbreviation resolves"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${LOCATIONS_CSV}')
print(normalize_aliases(amap, \"Dorren's private study\"))
" 2>/dev/null)
assert_equals "private-study" "$RESULT" "load locations: variant resolves"

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
assert_equals "dorren-hayle;kael-maren;pell" "$RESULT" "normalize chars: aliases resolve"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'dorren;TESSA;kael'))
" 2>/dev/null)
assert_equals "dorren-hayle;tessa-merrin;kael-maren" "$RESULT" "normalize chars: case-insensitive"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'Dorren;Dr. Hayle;Hayle'))
" 2>/dev/null)
assert_equals "dorren-hayle" "$RESULT" "normalize chars: deduplicates"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'Dorren;Unknown Person;Pell'))
" 2>/dev/null)
assert_equals "dorren-hayle;Unknown Person;pell" "$RESULT" "normalize chars: unknown passthrough"

# ============================================================================
# normalize_aliases — motifs
# ============================================================================

echo "--- normalize_aliases: motifs ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'cartography;governance-as-weight;depth/descent'))
" 2>/dev/null)
assert_equals "maps;governance;depth" "$RESULT" "normalize motifs: aliases resolve"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'maps/cartography;Maps;cartography'))
" 2>/dev/null)
assert_equals "maps" "$RESULT" "normalize motifs: deduplicates variants"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'cartography;unknown_motif;depth/descent'))
" 2>/dev/null)
assert_equals "maps;unknown_motif;depth" "$RESULT" "normalize motifs: unknown passthrough"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${MOTIF_CSV}')
print(normalize_aliases(amap, 'CARTOGRAPHY;Depth/Descent'))
" 2>/dev/null)
assert_equals "maps;depth" "$RESULT" "normalize motifs: case-insensitive"

# ============================================================================
# strip_parentheticals
# ============================================================================

echo "--- strip_parentheticals ---"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import strip_parentheticals
print(strip_parentheticals('Cora (referenced)'))
" 2>/dev/null)
assert_equals "Cora" "$RESULT" "strip parens: removes trailing qualifier"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import strip_parentheticals
print(strip_parentheticals('Keele (implied through grief thread)'))
" 2>/dev/null)
assert_equals "Keele" "$RESULT" "strip parens: removes complex qualifier"

RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import strip_parentheticals
print(strip_parentheticals('Emmett Slade'))
" 2>/dev/null)
assert_equals "Emmett Slade" "$RESULT" "strip parens: no-op without parens"

# Parentheticals stripped during normalization
RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map, normalize_aliases
amap = load_alias_map('${CHARACTERS_CSV}')
print(normalize_aliases(amap, 'Dorren (referenced);Kael (implied);Pell'))
" 2>/dev/null)
assert_equals "dorren-hayle;kael-maren;pell" "$RESULT" "normalize chars: strips parentheticals before lookup"

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
assert_equals "dorren-hayle;tessa-merrin;pell" "$RESULT" "normalize: handles whitespace"

# Missing file returns empty map
RESULT=$(PYTHONPATH="$PYTHON_DIR" python3 -c "
from storyforge.enrich import load_alias_map
amap = load_alias_map('/nonexistent/file.csv')
print(len(amap))
" 2>/dev/null)
assert_equals "0" "$RESULT" "load missing: returns empty map"

#!/bin/bash
# characters.sh — Character alias normalization for Storyforge
#
# Provides functions to load a canonical character registry (reference/characters.csv)
# and normalize extracted character names against it. Case-insensitive matching,
# graceful passthrough for unknown names.
#
# Source this file via common.sh; do not execute it directly.
# Requires csv.sh to be loaded first.

# ============================================================================
# load_character_aliases — build a lookup file from characters.csv
# ============================================================================
#
# Usage: ALIASES_FILE=$(load_character_aliases <characters_csv>)
#
# Reads the characters.csv file and writes a temp file with one
# lowercase_alias|canonical_name pair per line. Includes canonical names
# as self-mappings. Returns the temp file path via stdout.
#
# Caller is responsible for cleanup (rm) after use.
load_character_aliases() {
    local characters_csv="$1"
    local tmp
    tmp=$(mktemp "${TMPDIR:-/tmp}/sf-aliases.XXXXXX")

    [[ -f "$characters_csv" ]] || { echo "$tmp"; return; }

    awk -F'|' '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == "name") name_col = i
                if ($i == "aliases") alias_col = i
            }
            next
        }
        name_col {
            canonical = $name_col
            # Self-mapping: lowercase canonical -> canonical
            lower_canon = tolower(canonical)
            print lower_canon "|" canonical

            # Alias mappings
            if (alias_col && $alias_col != "") {
                n = split($alias_col, parts, ";")
                for (j = 1; j <= n; j++) {
                    # Trim whitespace
                    gsub(/^[[:space:]]+|[[:space:]]+$/, "", parts[j])
                    if (parts[j] != "") {
                        print tolower(parts[j]) "|" canonical
                    }
                }
            }
        }
    ' "$characters_csv" > "$tmp"

    echo "$tmp"
}

# ============================================================================
# normalize_characters — resolve aliases in a semicolon-separated string
# ============================================================================
#
# Usage: normalized=$(normalize_characters <aliases_file> <characters_string>)
#
# Takes a semicolon-separated character string (as returned by Claude),
# looks up each name case-insensitively in the aliases file, replaces
# matches with canonical names, passes through unknowns unchanged,
# deduplicates preserving first-occurrence order, and returns the
# normalized semicolon-separated string.
#
# If aliases_file is empty or doesn't exist, returns the input unchanged.
normalize_characters() {
    local aliases_file="$1"
    local raw="$2"

    # No aliases file or empty string — passthrough
    if [[ -z "$aliases_file" || ! -s "$aliases_file" || -z "$raw" ]]; then
        echo "$raw"
        return
    fi

    local result=""
    local seen=""
    local IFS_SAVE="$IFS"

    # Split on semicolons
    IFS=';' read -ra parts <<< "$raw"
    IFS="$IFS_SAVE"

    for part in "${parts[@]}"; do
        # Trim whitespace
        local trimmed
        trimmed=$(echo "$part" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        [[ -z "$trimmed" ]] && continue

        # Lookup: lowercase the name, find in aliases file
        local lower
        lower=$(echo "$trimmed" | tr '[:upper:]' '[:lower:]')
        local canonical
        canonical=$(awk -F'|' -v key="$lower" '$1 == key { print $2; exit }' "$aliases_file")

        # Use canonical if found, otherwise passthrough
        local name
        if [[ -n "$canonical" ]]; then
            name="$canonical"
        else
            name="$trimmed"
        fi

        # Deduplicate (first-occurrence wins)
        local lower_name
        lower_name=$(echo "$name" | tr '[:upper:]' '[:lower:]')
        if ! echo ";${seen};" | grep -qF ";${lower_name};"; then
            [[ -n "$result" ]] && result="${result};${name}" || result="$name"
            seen="${seen};${lower_name}"
        fi
    done

    echo "$result"
}

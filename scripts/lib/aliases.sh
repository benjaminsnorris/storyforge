#!/bin/bash
# aliases.sh — Generic alias normalization for Storyforge
#
# Provides functions to load any pipe-delimited CSV with name|aliases columns
# and normalize semicolon-separated strings against it. Used for characters,
# motifs, locations, and any future taxonomy files.
#
# Case-insensitive matching, graceful passthrough for unknown values.
#
# Source this file via common.sh; do not execute it directly.

# ============================================================================
# load_alias_map — build a lookup file from any CSV with name|aliases columns
# ============================================================================
#
# Usage: MAP_FILE=$(load_alias_map <csv_file>)
#
# Reads a CSV file with at least `name` and `aliases` columns, writes a temp
# file with one lowercase_alias|canonical_name pair per line. Includes
# canonical names as self-mappings. Returns the temp file path via stdout.
#
# Caller is responsible for cleanup (rm) after use.
load_alias_map() {
    local csv_file="$1"
    local tmp
    tmp=$(mktemp "${TMPDIR:-/tmp}/sf-aliases.XXXXXX")

    [[ -f "$csv_file" ]] || { echo "$tmp"; return; }

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
    ' "$csv_file" > "$tmp"

    echo "$tmp"
}

# ============================================================================
# normalize_aliases — resolve aliases in a semicolon-separated string
# ============================================================================
#
# Usage: normalized=$(normalize_aliases <map_file> <semicolon_string>)
#
# Takes a semicolon-separated string, looks up each value case-insensitively
# in the alias map file, replaces matches with canonical names, passes through
# unknowns unchanged, deduplicates preserving first-occurrence order, and
# returns the normalized semicolon-separated string.
#
# If map_file is empty or doesn't exist, returns the input unchanged.
normalize_aliases() {
    local map_file="$1"
    local raw="$2"

    # No map file or empty string — passthrough
    if [[ -z "$map_file" || ! -s "$map_file" || -z "$raw" ]]; then
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

        # Lookup: lowercase the name, find in map file
        local lower
        lower=$(echo "$trimmed" | tr '[:upper:]' '[:lower:]')
        local canonical
        canonical=$(awk -F'|' -v key="$lower" '$1 == key { print $2; exit }' "$map_file")

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

# Backwards-compatible aliases for existing callers
load_character_aliases() { load_alias_map "$@"; }
normalize_characters() { normalize_aliases "$@"; }

#!/bin/bash
# csv.sh — Pipe-delimited CSV reading and writing utilities for Storyforge
#
# All functions use '|' as the field delimiter.  The first row of every CSV
# file is a header row whose first column must be "id".
#
# Source this file from your script; do not execute it directly.

# ============================================================================
# Reading
# ============================================================================

# Print a single field value for a given ID.
# Usage: get_csv_field <file> <id> <field>
get_csv_field() {
    local file="$1" id="$2" field="$3"
    [[ -f "$file" ]] || return 0
    awk -F'|' -v id="$id" -v field="$field" '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == field) { col = i; break }
            }
            next
        }
        col && $1 == id { print $col }
    ' "$file"
}

# Print all field values for a given ID as a pipe-delimited string.
# Usage: get_csv_row <file> <id>
get_csv_row() {
    local file="$1" id="$2"
    [[ -f "$file" ]] || return 0
    awk -F'|' -v id="$id" '
        NR > 1 && $1 == id { print; exit }
    ' "$file"
}

# Print all values for a given column, one per line.
# Usage: get_csv_column <file> <field>
get_csv_column() {
    local file="$1" field="$2"
    [[ -f "$file" ]] || return 0
    awk -F'|' -v field="$field" '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == field) { col = i; break }
            }
            next
        }
        col { print $col }
    ' "$file"
}

# Print all IDs (first column), one per line, in file order.
# Usage: list_csv_ids <file>
list_csv_ids() {
    local file="$1"
    [[ -f "$file" ]] || return 0
    awk -F'|' 'NR > 1 { print $1 }' "$file"
}

# ============================================================================
# Writing
# ============================================================================

# Update a single field for a given ID.  Rewrites the file atomically
# (write to temp, then mv).
# Usage: update_csv_field <file> <id> <field> <value>
update_csv_field() {
    local file="$1" id="$2" field="$3" value="$4"
    [[ -f "$file" ]] || return 0
    local tmp="${file}.tmp.$$"
    awk -F'|' -v OFS='|' -v id="$id" -v field="$field" -v val="$value" '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == field) { col = i; break }
            }
            print
            next
        }
        col && $1 == id { $col = val }
        { print }
    ' "$file" > "$tmp" && mv "$tmp" "$file"
}

# Append a pipe-delimited row to the file.
# Usage: append_csv_row <file> <row>
append_csv_row() {
    local file="$1" row="$2"
    [[ -f "$file" ]] || return 0
    echo "$row" >> "$file"
}

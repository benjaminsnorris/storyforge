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
# Usage: get_csv_field <file> <id> <field> [key_column]
get_csv_field() {
    local file="$1" id="$2" field="$3" key_col="${4:-id}"
    [[ -f "$file" ]] || return 0
    awk -F'|' -v id="$id" -v field="$field" -v key_col="$key_col" '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == field) { fcol = i }
                if ($i == key_col) { kcol = i }
            }
            next
        }
        fcol && kcol && $kcol == id { print $fcol }
    ' "$file"
}

# Print all field values for a given ID as a pipe-delimited string.
# Usage: get_csv_row <file> <id> [key_column]
get_csv_row() {
    local file="$1" id="$2" key_col="${3:-id}"
    [[ -f "$file" ]] || return 0
    awk -F'|' -v id="$id" -v key_col="$key_col" '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == key_col) { kcol = i; break }
            }
            next
        }
        kcol && $kcol == id { print; exit }
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
# Usage: update_csv_field <file> <id> <field> <value> [key_column]
update_csv_field() {
    local file="$1" id="$2" field="$3" value="$4" key_col="${5:-id}"
    [[ -f "$file" ]] || return 0
    local tmp="${file}.tmp.$$"
    awk -F'|' -v OFS='|' -v id="$id" -v field="$field" -v val="$value" -v key_col="$key_col" '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == field) { fcol = i }
                if ($i == key_col) { kcol = i }
            }
            print
            next
        }
        fcol && kcol && $kcol == id { $fcol = val }
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

# Renumber the seq column in a CSV file sequentially from 1.
# Rows are sorted by current seq (numerically) before renumbering,
# so the existing order is preserved. Writes atomically.
# Usage: renumber_scenes <file>
renumber_scenes() {
    local file="$1"
    [[ -f "$file" ]] || return 0
    local tmp="${file}.tmp.$$"
    awk -F'|' -v OFS='|' '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == "seq") seq_col = i
            }
            print
            next
        }
        seq_col {
            rows[NR] = $0
            seqs[NR] = $seq_col + 0
            count++
        }
        END {
            # Sort indices by seq value (insertion sort — fine for < 1000 scenes)
            for (i = 2; i <= NR; i++) {
                for (j = i; j > 2 && seqs[j] < seqs[j-1]; j--) {
                    tmp_row = rows[j]; rows[j] = rows[j-1]; rows[j-1] = tmp_row
                    tmp_seq = seqs[j]; seqs[j] = seqs[j-1]; seqs[j-1] = tmp_seq
                }
            }
            # Output rows with renumbered seq
            new_seq = 1
            for (i = 2; i <= NR; i++) {
                if (rows[i] != "") {
                    split(rows[i], fields, "|")
                    fields[seq_col] = new_seq
                    line = fields[1]
                    for (k = 2; k <= length(fields); k++) line = line "|" fields[k]
                    print line
                    new_seq++
                }
            }
        }
    ' "$file" > "$tmp" && mv "$tmp" "$file"
}

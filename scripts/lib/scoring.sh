#!/bin/bash
# scoring.sh — Scoring library for principled evaluation
#
# Provides weight management functions for the craft-weights system.
# Source this file from your script; do not execute it directly.

# init_craft_weights(project_dir, plugin_dir)
# Copy default weights to project if craft-weights.csv doesn't exist
init_craft_weights() {
    local project_dir="$1" plugin_dir="$2"
    local weights_file="${project_dir}/working/craft-weights.csv"
    local defaults="${plugin_dir}/references/default-craft-weights.csv"
    if [[ ! -f "$weights_file" ]]; then
        mkdir -p "$(dirname "$weights_file")"
        cp "$defaults" "$weights_file"
    fi
}

# get_effective_weight(weights_file, principle)
# Return author_weight if set, otherwise weight
get_effective_weight() {
    local weights_file="$1" principle="$2"
    local author_w
    author_w=$(get_csv_field "$weights_file" "$principle" "author_weight" "principle")
    if [[ -n "$author_w" ]]; then
        echo "$author_w"
    else
        get_csv_field "$weights_file" "$principle" "weight" "principle"
    fi
}

# parse_score_output(log_file, score_target, rationale_target, marker)
# Extract SCORES: and RATIONALE: CSV blocks from Claude output.
# marker defaults to "SCORES" — for novel-level use "CHARACTER_SCORES" etc.
parse_score_output() {
    local log_file="$1"
    local score_target="$2"
    local rationale_target="$3"
    local score_marker="${4:-SCORES}"
    local rationale_marker="${5:-RATIONALE}"

    if [[ ! -f "$log_file" ]]; then
        log "WARNING: Log file not found for score parsing: $log_file"
        return 1
    fi

    # Extract text content from stream-json log (content blocks)
    local text_content
    text_content=$(sed -n 's/.*"type":"content_block_delta".*"text":"\([^"]*\)".*/\1/p' "$log_file" \
        | sed 's/\\n/\n/g; s/\\t/\t/g; s/\\"/"/g; s/\\\\/\\/g' || true)

    if [[ -z "$text_content" ]]; then
        # Fallback: try plain text extraction
        text_content=$(grep -v '^\s*{' "$log_file" 2>/dev/null || true)
    fi

    if [[ -z "$text_content" ]]; then
        log "WARNING: No text content found in $log_file"
        return 1
    fi

    # Extract SCORES block: lines between marker and next blank line or next marker
    local scores_block
    scores_block=$(echo "$text_content" | awk -v marker="${score_marker}:" '
        $0 ~ marker { found=1; next }
        found && /^[[:space:]]*$/ { found=0 }
        found && /^[A-Z_]+:/ { found=0 }
        found { print }
    ')

    # Extract RATIONALE block
    local rationale_block
    rationale_block=$(echo "$text_content" | awk -v marker="${rationale_marker}:" '
        $0 ~ marker { found=1; next }
        found && /^[[:space:]]*$/ { found=0 }
        found && /^[A-Z_]+:/ { found=0 }
        found { print }
    ')

    # Write scores
    if [[ -n "$scores_block" ]]; then
        echo "$scores_block" > "$score_target"
        return 0
    else
        log "WARNING: No ${score_marker} block found in $log_file"
        return 1
    fi

    # Write rationale (optional — not fatal if missing)
    if [[ -n "$rationale_block" ]]; then
        echo "$rationale_block" > "$rationale_target"
    fi
}

# merge_score_files(target, source)
# Merge columns from source into target, joining on id column.
# If target doesn't exist, just copy source.
merge_score_files() {
    local target="$1" source="$2"

    if [[ ! -f "$source" ]]; then
        log "WARNING: merge source not found: $source"
        return 1
    fi

    if [[ ! -f "$target" ]]; then
        cp "$source" "$target"
        return 0
    fi

    local tmp="${target}.merge.$$"
    awk -F'|' '
        # First file (target): store all rows keyed by id
        FNR == NR && FNR == 1 {
            target_header = $0
            target_ncols = NF
            next
        }
        FNR == NR {
            target_rows[$1] = $0
            target_order[++target_count] = $1
            next
        }
        # Second file (source): read header and rows
        FNR == 1 {
            source_header = ""
            for (i = 2; i <= NF; i++) {
                source_header = source_header "|" $i
            }
            next
        }
        {
            source_data[$1] = ""
            for (i = 2; i <= NF; i++) {
                source_data[$1] = source_data[$1] "|" $i
            }
            # Track new IDs not in target
            if (!($1 in target_rows)) {
                target_order[++target_count] = $1
                target_rows[$1] = $1
                for (i = 2; i <= target_ncols; i++) {
                    target_rows[$1] = target_rows[$1] "|"
                }
            }
        }
        END {
            # Print merged header
            print target_header source_header
            # Print merged rows in original order
            for (i = 1; i <= target_count; i++) {
                id = target_order[i]
                row = target_rows[id]
                if (id in source_data) {
                    row = row source_data[id]
                } else {
                    # Pad with empty columns matching source
                    n = split(source_header, a, "|") - 1
                    for (j = 1; j <= n; j++) row = row "|"
                }
                print row
            }
        }
    ' "$target" "$source" > "$tmp" && mv "$tmp" "$target"
}

# extract_rubric_section(section_name)
# Extract a section from scoring-rubrics.md by header name.
# Returns the section content to stdout.
extract_rubric_section() {
    local section="$1"
    local plugin_dir
    plugin_dir=$(get_plugin_dir)
    local rubric_file="${plugin_dir}/references/scoring-rubrics.md"

    if [[ ! -f "$rubric_file" ]]; then
        log "WARNING: Scoring rubrics not found at ${rubric_file}"
        return 1
    fi

    awk -v section="$section" '
        $0 ~ "^## " section { found=1; next }
        found && /^## / { found=0 }
        found { print }
    ' "$rubric_file"
}

# build_weighted_text(weights_file)
# Build the {{WEIGHTED_PRINCIPLES}} substitution text.
# Lists principles with effective weight >= 7 as high-priority.
build_weighted_text() {
    local weights_file="$1"

    if [[ ! -f "$weights_file" ]]; then
        echo "No craft weights available."
        return 0
    fi

    local high_priority=""
    local count=0

    while IFS='|' read -r section principle weight author_weight notes; do
        [[ "$section" == "section" ]] && continue  # skip header
        local eff_w="$weight"
        if [[ -n "$author_weight" ]]; then
            eff_w="$author_weight"
        fi
        if [[ -n "$eff_w" ]] && (( eff_w >= 7 )); then
            high_priority="${high_priority}\n- **${principle}** (weight: ${eff_w})"
            count=$((count + 1))
        fi
    done < "$weights_file"

    if (( count > 0 )); then
        echo -e "Pay particular attention to these high-priority principles:${high_priority}"
    else
        echo "All principles are weighted equally. No high-priority overrides."
    fi
}

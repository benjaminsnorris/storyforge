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

    # Extract text content from stream-json log
    # Try multiple extraction strategies for different output formats
    local text_content=""

    # Strategy 1: Extract from "result" field (claude -p with stream-json)
    if [[ -z "$text_content" ]]; then
        text_content=$(grep '"type":"result"' "$log_file" 2>/dev/null \
            | sed 's/.*"result":"//' | sed 's/","stop_reason.*//' \
            | sed 's/\\n/\n/g; s/\\t/\t/g; s/\\"/"/g; s/\\\\/\\/g' || true)
    fi

    # Strategy 2: Extract from assistant message content
    if [[ -z "$text_content" ]]; then
        text_content=$(grep '"type":"assistant"' "$log_file" 2>/dev/null \
            | sed 's/.*"text":"//' | sed 's/"}],"stop_reason.*//' \
            | sed 's/\\n/\n/g; s/\\t/\t/g; s/\\"/"/g; s/\\\\/\\/g' || true)
    fi

    # Strategy 3: Extract from content_block_delta (streaming format)
    if [[ -z "$text_content" ]]; then
        text_content=$(sed -n 's/.*"type":"content_block_delta".*"text":"\([^"]*\)".*/\1/p' "$log_file" \
            | sed 's/\\n/\n/g; s/\\t/\t/g; s/\\"/"/g; s/\\\\/\\/g' || true)
    fi

    # Strategy 4: Fallback to plain text lines
    if [[ -z "$text_content" ]]; then
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
# Smart merge: if headers match, append rows. If headers differ, join columns on id.
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

    # Check if headers match — if so, just append data rows
    local target_header source_header
    target_header=$(head -1 "$target")
    source_header=$(head -1 "$source")
    if [[ "$target_header" == "$source_header" ]]; then
        tail -n +2 "$source" >> "$target"
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

# ============================================================================
# Improvement cycle functions
# ============================================================================

# generate_diagnosis(scores_dir, prev_scores_dir, weights_file)
# Analyse score CSVs, compute per-principle averages, identify worst scenes,
# compare to previous cycle if available, write diagnosis.csv.
generate_diagnosis() {
    local scores_dir="$1"
    local prev_scores_dir="${2:-}"
    local weights_file="$3"

    local diagnosis_file="${scores_dir}/diagnosis.csv"
    echo "principle|scale|avg_score|worst_items|delta_from_last|priority" > "$diagnosis_file"

    # Process each score file (scene, act, character, genre)
    for score_entry in \
        "scene-scores.csv|scene" \
        "act-scores.csv|act" \
        "character-scores.csv|character" \
        "genre-scores.csv|genre"; do

        local csv_name="${score_entry%%|*}"
        local scale="${score_entry##*|}"
        local score_file="${scores_dir}/${csv_name}"
        [[ -f "$score_file" ]] || continue

        local prev_file=""
        if [[ -n "$prev_scores_dir" && -f "${prev_scores_dir}/${csv_name}" ]]; then
            prev_file="${prev_scores_dir}/${csv_name}"
        fi

        # Get header columns (skip first column which is id)
        local header
        header=$(head -1 "$score_file")
        local col_count
        col_count=$(echo "$header" | awk -F'|' '{ print NF }')

        # For each principle column (columns 2..N)
        local col=2
        while (( col <= col_count )); do
            local principle
            principle=$(echo "$header" | awk -F'|' -v c="$col" '{ print $c }')
            [[ -z "$principle" ]] && { col=$((col + 1)); continue; }

            # Compute average and find worst items
            local avg_and_worst
            avg_and_worst=$(awk -F'|' -v c="$col" '
                NR == 1 { next }
                {
                    val = $c + 0
                    sum += val; n++
                    ids[NR] = $1
                    scores[NR] = val
                }
                END {
                    if (n == 0) { print "0||"; exit }
                    avg = sum / n
                    # printf avg with one decimal
                    printf "%.1f|", avg
                    # Collect items below average, sort by score ascending, take worst 5
                    worst_count = 0
                    # Simple selection: gather below-average items
                    for (i in scores) {
                        if (scores[i] < avg && worst_count < 5) {
                            if (worst_count > 0) printf ";"
                            printf "%s", ids[i]
                            worst_count++
                        }
                    }
                    printf "|"
                }
            ' "$score_file")

            local avg_score="${avg_and_worst%%|*}"
            local rest="${avg_and_worst#*|}"
            local worst_items="${rest%%|*}"

            # Compute delta from previous cycle
            local delta=""
            if [[ -n "$prev_file" ]]; then
                local prev_avg
                prev_avg=$(awk -F'|' -v c="$col" -v p="$principle" '
                    NR == 1 {
                        for (i = 1; i <= NF; i++) {
                            if ($i == p) { tc = i; break }
                        }
                        next
                    }
                    tc {
                        val = $tc + 0; sum += val; n++
                    }
                    END {
                        if (n > 0) printf "%.1f", sum / n
                        else print ""
                    }
                ' "$prev_file")
                if [[ -n "$prev_avg" && -n "$avg_score" ]]; then
                    delta=$(awk -v cur="$avg_score" -v prev="$prev_avg" 'BEGIN {
                        d = cur - prev
                        if (d >= 0) printf "+%.1f", d
                        else printf "%.1f", d
                    }')
                fi
            fi

            # Determine priority
            local priority="low"
            local eff_weight=""
            if [[ -f "$weights_file" ]]; then
                eff_weight=$(get_effective_weight "$weights_file" "$principle" 2>/dev/null || true)
            fi

            # Check if avg < 4 -> high, avg < 6 -> medium
            local is_high=false is_medium=false
            if [[ -n "$avg_score" ]]; then
                is_high=$(awk -v a="$avg_score" 'BEGIN { print (a < 4) ? "true" : "false" }')
                is_medium=$(awk -v a="$avg_score" 'BEGIN { print (a < 6) ? "true" : "false" }')
            fi

            # Check if regressing > 0.5
            local is_regressing=false
            if [[ -n "$delta" ]]; then
                is_regressing=$(awk -v d="$delta" 'BEGIN {
                    # delta is negative when regressing (score went down)
                    print (d + 0 < -0.5) ? "true" : "false"
                }')
            fi

            if [[ "$is_high" == "true" || "$is_regressing" == "true" ]]; then
                priority="high"
            elif [[ "$is_medium" == "true" ]]; then
                priority="medium"
            fi

            # Boost to high if weight >= 7
            if [[ -n "$eff_weight" ]] && (( eff_weight >= 7 )); then
                if [[ "$priority" == "medium" || "$is_medium" == "true" ]]; then
                    priority="high"
                fi
            fi

            echo "${principle}|${scale}|${avg_score}|${worst_items}|${delta}|${priority}" >> "$diagnosis_file"
            col=$((col + 1))
        done
    done
}

# generate_proposals(scores_dir, weights_file)
# Read diagnosis.csv, generate proposals for high and medium priority items.
# Writes proposals.csv.
generate_proposals() {
    local scores_dir="$1"
    local weights_file="$2"

    local diagnosis_file="${scores_dir}/diagnosis.csv"
    local proposals_file="${scores_dir}/proposals.csv"

    if [[ ! -f "$diagnosis_file" ]]; then
        return 1
    fi

    echo "id|principle|lever|target|change|rationale|status" > "$proposals_file"

    local proposal_num=0
    while IFS='|' read -r principle scale avg_score worst_items delta priority; do
        [[ "$principle" == "principle" ]] && continue  # skip header
        [[ "$priority" != "high" && "$priority" != "medium" ]] && continue

        local current_weight=""
        if [[ -f "$weights_file" ]]; then
            current_weight=$(get_csv_field "$weights_file" "$principle" "weight" "principle")
        fi
        current_weight="${current_weight:-5}"

        # Determine weight increase
        local increase=1
        [[ "$priority" == "high" ]] && increase=2

        local new_weight=$((current_weight + increase))
        (( new_weight > 10 )) && new_weight=10

        proposal_num=$((proposal_num + 1))
        local pid
        pid=$(printf "p%03d" "$proposal_num")

        # If weight already >= 8 and still scoring low: propose voice_guide instead
        if (( current_weight >= 8 )); then
            echo "${pid}|${principle}|voice_guide|global|add voice guidance for ${principle}|avg_score ${avg_score}, weight already ${current_weight}|pending" >> "$proposals_file"
        else
            echo "${pid}|${principle}|craft_weight|global|weight ${current_weight} → ${new_weight}|avg_score ${avg_score}, priority ${priority}|pending" >> "$proposals_file"
        fi

        # If specific scenes score < 3 on this principle, propose scene-level overrides
        if [[ -n "$worst_items" ]]; then
            local scene_score_file="${scores_dir}/scene-scores.csv"
            if [[ -f "$scene_score_file" ]]; then
                IFS=';' read -ra worst_scenes <<< "$worst_items"
                for scene_id in "${worst_scenes[@]}"; do
                    [[ -z "$scene_id" ]] && continue
                    local scene_val
                    scene_val=$(get_csv_field "$scene_score_file" "$scene_id" "$principle")
                    if [[ -n "$scene_val" ]] && (( scene_val < 3 )); then
                        proposal_num=$((proposal_num + 1))
                        pid=$(printf "p%03d" "$proposal_num")
                        echo "${pid}|${principle}|scene_intent|${scene_id}|strengthen ${principle} intent|scene scores ${scene_val}, needs targeted fix|pending" >> "$proposals_file"
                    fi
                done
            fi
        fi
    done < "$diagnosis_file"
}

# record_tuning(project_dir, cycle, proposal_id, principle, lever, change, score_before, score_after, kept)
# Append a row to working/tuning.csv. Create header on first use.
record_tuning() {
    local project_dir="$1"
    local cycle="$2"
    local proposal_id="$3"
    local principle="$4"
    local lever="$5"
    local change="$6"
    local score_before="$7"
    local score_after="$8"
    local kept="$9"

    local tuning_file="${project_dir}/working/tuning.csv"
    if [[ ! -f "$tuning_file" ]]; then
        mkdir -p "$(dirname "$tuning_file")"
        echo "cycle|proposal_id|principle|lever|change|score_before|score_after|kept" > "$tuning_file"
    fi
    echo "${cycle}|${proposal_id}|${principle}|${lever}|${change}|${score_before}|${score_after}|${kept}" >> "$tuning_file"
}

# check_validated_patterns(project_dir)
# Read tuning.csv, find principle+lever combos with 3+ rows where kept=true.
# Returns validated patterns as lines: principle|lever|avg_improvement
check_validated_patterns() {
    local project_dir="$1"
    local tuning_file="${project_dir}/working/tuning.csv"

    if [[ ! -f "$tuning_file" ]]; then
        return 0
    fi

    awk -F'|' '
        NR == 1 { next }
        $8 == "true" {
            key = $3 "|" $4
            count[key]++
            improvement[key] += ($7 - $6)
        }
        END {
            for (k in count) {
                if (count[k] >= 3) {
                    avg_imp = improvement[k] / count[k]
                    printf "%s|%.1f\n", k, avg_imp
                }
            }
        }
    ' "$tuning_file"
}

# submit_plugin_insight(principle, lever, change, avg_improvement, project_title, evidence_lines)
# Creates a GitHub issue on benjaminsnorris/storyforge with structured insight data
submit_plugin_insight() {
    local principle="$1" lever="$2" change="$3" avg_improvement="$4"
    local project_title="$5" evidence="$6"

    # Check STORYFORGE_AUTO_ISSUES (default: true)
    local auto_issues
    auto_issues=$(read_yaml_field "auto_issues" 2>/dev/null || echo "true")
    [[ "${STORYFORGE_AUTO_ISSUES:-$auto_issues}" == "false" ]] && return 0

    # Check gh CLI available
    has_gh || { log "WARNING: gh not available, skipping plugin insight"; return 0; }

    local section
    section=$(get_csv_field "$WEIGHTS_FILE" "$principle" "section" "principle" 2>/dev/null || echo "unknown")

    local body="## Plugin Insight: ${section} — ${principle}

**Source project:** ${project_title}
**Average improvement:** ${avg_improvement}

### Change
${change}

### Evidence
${evidence}

### Recommendation
Update \`references/default-craft-weights.csv\` based on this validated pattern."

    gh issue create \
        --repo benjaminsnorris/storyforge \
        --title "Plugin Insight: ${principle} — ${lever}" \
        --body "$body" \
        --label "plugin-insight" \
        2>/dev/null || log "WARNING: Failed to create plugin insight issue"
}

# record_author_score(project_dir, scene_id, principle, score)
# Write to scenes/author-scores.csv
record_author_score() {
    local project_dir="$1" scene_id="$2" principle="$3" score="$4"
    local author_file="${project_dir}/scenes/author-scores.csv"

    # Create file with header if missing
    if [[ ! -f "$author_file" ]]; then
        # Copy header from scene-scores.csv if available
        local scores_dir="${project_dir}/working/scores/latest"
        if [[ -f "${scores_dir}/scene-scores.csv" ]]; then
            head -1 "${scores_dir}/scene-scores.csv" > "$author_file"
        else
            echo "id|${principle}" > "$author_file"
        fi
    fi

    # Check if principle column exists in header
    local header
    header=$(head -1 "$author_file")
    if ! echo "$header" | grep -q "|${principle}\(|\|$\)"; then
        # Add column to header
        sed -i '' "1s/$/$|${principle}/" "$author_file"
    fi

    # Update or add row for this scene+principle
    if grep -q "^${scene_id}|" "$author_file"; then
        # Row exists — update the specific column
        update_csv_field "$author_file" "$scene_id" "$principle" "$score"
    else
        # New row — build with empty columns, then set the value
        local col_count
        col_count=$(head -1 "$author_file" | awk -F'|' '{ print NF }')
        local new_row="${scene_id}"
        local i=2
        while (( i <= col_count )); do
            new_row="${new_row}|"
            i=$((i + 1))
        done
        echo "$new_row" >> "$author_file"
        update_csv_field "$author_file" "$scene_id" "$principle" "$score"
    fi
}

# compute_author_deltas(project_dir, scores_dir)
# Compare system scores to author scores, return systematic biases
compute_author_deltas() {
    local project_dir="$1" scores_dir="$2"
    local author_file="${project_dir}/scenes/author-scores.csv"
    local system_file="${scores_dir}/scene-scores.csv"
    [[ -f "$author_file" && -f "$system_file" ]] || return 0

    # For each cell where both system and author have a value,
    # compute delta (system - author), output principle|avg_delta
    awk -F'|' '
        # Read author file (first file)
        FNR == NR && FNR == 1 {
            for (i = 2; i <= NF; i++) author_cols[i] = $i
            author_ncols = NF
            next
        }
        FNR == NR {
            for (i = 2; i <= NF; i++) {
                if ($i != "") author_data[$1, author_cols[i]] = $i + 0
            }
            next
        }
        # Read system file (second file)
        FNR == 1 {
            for (i = 2; i <= NF; i++) system_cols[i] = $i
            system_ncols = NF
            next
        }
        {
            for (i = 2; i <= NF; i++) {
                if ($i != "") system_data[$1, system_cols[i]] = $i + 0
            }
        }
        END {
            # Find matching cells and compute deltas
            for (key in author_data) {
                if (key in system_data) {
                    split(key, parts, SUBSEP)
                    principle = parts[2]
                    delta = system_data[key] - author_data[key]
                    delta_sum[principle] += delta
                    delta_count[principle]++
                }
            }
            for (p in delta_count) {
                if (delta_count[p] > 0) {
                    avg = delta_sum[p] / delta_count[p]
                    printf "%s|%.1f\n", p, avg
                }
            }
        }
    ' "$author_file" "$system_file"
}

# collect_exemplars(scores_dir, project_dir, cycle)
# For scenes scoring 9+ on any principle, extract a passage for the exemplar bank
collect_exemplars() {
    local scores_dir="$1" project_dir="$2" cycle="$3"
    local exemplars_file="${project_dir}/working/exemplars.csv"
    local scores_file="${scores_dir}/scene-scores.csv"
    [[ -f "$scores_file" ]] || return 0

    if [[ ! -f "$exemplars_file" ]]; then
        mkdir -p "$(dirname "$exemplars_file")"
        echo "principle|scene_id|score|excerpt|cycle" > "$exemplars_file"
    fi

    local rationale_file="${scores_dir}/scene-rationale.csv"

    # Find cells with score >= 9
    local header
    header=$(head -1 "$scores_file")
    local col_count
    col_count=$(echo "$header" | awk -F'|' '{ print NF }')

    local col=2
    while (( col <= col_count )); do
        local principle
        principle=$(echo "$header" | awk -F'|' -v c="$col" '{ print $c }')
        [[ -z "$principle" ]] && { col=$((col + 1)); continue; }

        # Find rows with score >= 9 in this column
        awk -F'|' -v c="$col" -v p="$principle" '
            NR == 1 { next }
            $c + 0 >= 9 { print $1 "|" p "|" $c }
        ' "$scores_file" | while IFS='|' read -r scene_id prin score_val; do
            [[ -z "$scene_id" ]] && continue

            # Check if already present for this scene+principle
            if grep -q "^${prin}|${scene_id}|" "$exemplars_file" 2>/dev/null; then
                continue
            fi

            # Get rationale as excerpt
            local excerpt=""
            if [[ -f "$rationale_file" ]]; then
                excerpt=$(get_csv_field "$rationale_file" "$scene_id" "$prin" 2>/dev/null || true)
            fi
            excerpt="${excerpt:-high-scoring passage}"
            # Escape pipes in excerpt
            excerpt=$(echo "$excerpt" | tr '|' '-')

            echo "${prin}|${scene_id}|${score_val}|${excerpt}|${cycle}" >> "$exemplars_file"
        done

        col=$((col + 1))
    done
}

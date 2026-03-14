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

    # Extract text content using shared extraction function
    local text_content
    text_content=$(extract_claude_response "$log_file") || {
        log "WARNING: No text content found in $log_file"
        return 1
    }

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
                    # Power mean with p=0.5 (penalizes low scores harder)
                    pow_sum = 0
                    for (i in scores) pow_sum += scores[i] ^ 0.5
                    avg = (pow_sum / n) ^ (1 / 0.5)
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

            # Priority thresholds (1-5 scale):
            #   high: avg < 2 (absent/developing) or regressing > 0.25
            #   medium: avg < 3 (below competent)
            local is_high=false is_medium=false
            if [[ -n "$avg_score" ]]; then
                is_high=$(awk -v a="$avg_score" 'BEGIN { print (a < 2) ? "true" : "false" }')
                is_medium=$(awk -v a="$avg_score" 'BEGIN { print (a < 3) ? "true" : "false" }')
            fi

            # Check if regressing > 0.25 (scaled from 0.5 on 1-10)
            local is_regressing=false
            if [[ -n "$delta" ]]; then
                is_regressing=$(awk -v d="$delta" 'BEGIN {
                    # delta is negative when regressing (score went down)
                    print (d + 0 < -0.25) ? "true" : "false"
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

    # Find cells with score >= 5 (masterful on 1-5 scale)
    local header
    header=$(head -1 "$scores_file")
    local col_count
    col_count=$(echo "$header" | awk -F'|' '{ print NF }')

    local col=2
    while (( col <= col_count )); do
        local principle
        principle=$(echo "$header" | awk -F'|' -v c="$col" '{ print $c }')
        [[ -z "$principle" ]] && { col=$((col + 1)); continue; }

        # Find rows with score >= 5 in this column
        awk -F'|' -v c="$col" -v p="$principle" '
            NR == 1 { next }
            $c + 0 >= 5 { print $1 "|" p "|" $c }
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

# ============================================================================
# generate_score_report(cycle_dir, project_dir, cycle, mode, scene_count, cost)
# Generate a self-contained HTML report at cycle_dir/report.html
# ============================================================================

generate_score_report() {
    local cycle_dir="$1" project_dir="$2" cycle="$3" mode="$4" scene_count="$5" cost="$6"
    local report_file="${cycle_dir}/report.html"
    local project_title
    project_title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Unknown")

    # Build character table rows
    local char_rows=""
    if [[ -f "${cycle_dir}/character-scores.csv" ]]; then
        while IFS='|' read -r char wn wl fas vac; do
            [[ "$char" == "character" ]] && continue
            local avg
            avg=$(awk "BEGIN { printf \"%.1f\", ($wn + $wl + $fas + $vac) / 4 }")
            char_rows="${char_rows}<tr><td>${char}</td><td class=\"sc-${wn}\">${wn}</td><td class=\"sc-${wl}\">${wl}</td><td class=\"sc-${fas}\">${fas}</td><td class=\"sc-${vac}\">${vac}</td><td><strong>${avg}</strong></td></tr>"
        done < "${cycle_dir}/character-scores.csv"
    fi

    # Build act table rows
    local act_rows=""
    if [[ -f "${cycle_dir}/act-scores.csv" ]]; then
        while IFS='|' read -r id cm ta stc t22 hc ki fr cw ct; do
            [[ "$id" == "id" ]] && continue
            local label
            label=$(echo "$id" | sed 's/act-/Part /')
            act_rows="${act_rows}<tr><td>${label}</td><td class=\"sc-${cm}\">${cm}</td><td class=\"sc-${ta}\">${ta}</td><td class=\"sc-${stc}\">${stc}</td><td class=\"sc-${t22}\">${t22}</td><td class=\"sc-${hc}\">${hc}</td><td class=\"sc-${ki}\">${ki}</td><td class=\"sc-${fr}\">${fr}</td><td class=\"sc-${cw}\">${cw}</td><td class=\"sc-${ct}\">${ct}</td></tr>"
        done < "${cycle_dir}/act-scores.csv"
    fi

    # Build genre row
    local genre_row=""
    if [[ -f "${cycle_dir}/genre-scores.csv" ]]; then
        genre_row=$(awk -F'|' 'NR==2 { printf "<td class=\"sc-%s\">%s</td><td class=\"sc-%s\">%s</td><td class=\"sc-%s\">%s</td><td class=\"sc-%s\">%s</td>", $1,$1,$2,$2,$3,$3,$4,$4 }' "${cycle_dir}/genre-scores.csv")
    fi

    # Build top strengths / weaknesses from diagnosis
    local strengths="" weaknesses=""
    if [[ -f "${cycle_dir}/diagnosis.csv" ]]; then
        strengths=$(awk -F'|' 'NR>1 && $3+0 > 0 { print $3+0, $1, $4 }' "${cycle_dir}/diagnosis.csv" \
            | sort -t' ' -k1 -rn | head -5 \
            | while read -r score prin scenes; do
                echo "<tr><td>${prin//_/ }</td><td>${score}</td><td>${scenes}</td></tr>"
            done)
        weaknesses=$(awk -F'|' 'NR>1 && $3+0 > 0 { print $3+0, $1, $4 }' "${cycle_dir}/diagnosis.csv" \
            | sort -t' ' -k1 -n | head -5 \
            | while read -r score prin scenes; do
                echo "<tr><td>${prin//_/ }</td><td>${score}</td><td>${scenes}</td></tr>"
            done)
    fi

    # Build proposals rows
    local proposal_rows=""
    if [[ -f "${cycle_dir}/proposals.csv" ]]; then
        while IFS='|' read -r pid prin lever target change rationale status; do
            [[ "$pid" == "id" ]] && continue
            local status_badge
            case "$status" in
                applied) status_badge="<span class='badge badge-applied'>applied</span>" ;;
                approved) status_badge="<span class='badge badge-approved'>approved</span>" ;;
                rejected) status_badge="<span class='badge badge-rejected'>rejected</span>" ;;
                *) status_badge="<span class='badge badge-pending'>pending</span>" ;;
            esac
            proposal_rows="${proposal_rows}<tr><td>${prin//_/ }</td><td>${lever//_/ }</td><td>${change}</td><td>${rationale}</td><td>${status_badge}</td></tr>"
        done < "${cycle_dir}/proposals.csv"
    fi

    # Build scene heatmap rows (average per scene across principle groups)
    local scene_heatmap=""
    if [[ -f "${cycle_dir}/scene-scores.csv" ]]; then
        local header
        header=$(head -1 "${cycle_dir}/scene-scores.csv")
        local ncols
        ncols=$(echo "$header" | tr '|' '\n' | wc -l | tr -d ' ')
        scene_heatmap=$(awk -F'|' -v nc="$ncols" '
            NR==1 { next }
            {
                pow_sum=0; count=0
                for(i=2; i<=nc; i++) { if($i+0 > 0) { pow_sum += ($i+0) ^ 0.5; count++ } }
                avg = (count > 0) ? (pow_sum/count) ^ (1/0.5) : 0
                printf "<tr><td>%s</td><td class=\"sc-%d\">%.1f</td></tr>\n", $1, int(avg+0.5), avg
            }
        ' "${cycle_dir}/scene-scores.csv")
    fi

    cat > "$report_file" << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scoring Report</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
:root {
    --bg: #faf8f6; --surface: #fff; --border: #e5e1db; --text: #2c2420;
    --text-dim: #8a7d73; --teal: #0f766e; --teal-dim: rgba(15,118,110,0.07);
    --red: #dc2626; --amber: #d97706; --green: #16a34a;
}
@media (prefers-color-scheme: dark) {
    :root {
        --bg: #1a1614; --surface: #262019; --border: rgba(255,255,255,0.08);
        --text: #ede5dd; --text-dim: #a69889; --teal: #2dd4bf; --teal-dim: rgba(45,212,191,0.08);
        --red: #f87171; --amber: #fbbf24; --green: #4ade80;
    }
}
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
.page { max-width: 960px; margin: 0 auto; padding: 40px 24px; }
h1 { font-size: 28px; font-weight: 700; margin-bottom: 4px; }
h2 { font-size: 18px; font-weight: 600; margin: 32px 0 12px; color: var(--teal); border-bottom: 2px solid var(--teal-dim); padding-bottom: 6px; }
.meta { font-size: 13px; color: var(--text-dim); margin-bottom: 24px; }
.meta span { margin-right: 16px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 13px; }
th { text-align: left; padding: 8px 10px; background: var(--surface); border: 1px solid var(--border); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); }
td { padding: 6px 10px; border: 1px solid var(--border); }
.sc-1 { background: rgba(220,38,38,0.15); color: var(--red); font-weight: 600; }
.sc-2 { background: rgba(217,119,6,0.12); color: var(--amber); font-weight: 600; }
.sc-3 { background: rgba(217,119,6,0.06); }
.sc-4 { background: rgba(22,163,74,0.08); }
.sc-5 { background: rgba(22,163,74,0.15); color: var(--green); font-weight: 600; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; }
.badge-applied { background: rgba(22,163,74,0.12); color: var(--green); }
.badge-approved { background: rgba(22,163,74,0.06); color: var(--green); }
.badge-rejected { background: rgba(220,38,38,0.08); color: var(--red); }
.badge-pending { background: rgba(217,119,6,0.08); color: var(--amber); }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
@media (max-width: 640px) { .two-col { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="page">
HTMLEOF

    # Inject dynamic content
    cat >> "$report_file" << EOF
<h1>${project_title} — Scoring Report</h1>
<div class="meta">
    <span>Cycle ${cycle}</span>
    <span>Mode: ${mode}</span>
    <span>Scenes: ${scene_count}</span>
    <span>Cost: \$${cost}</span>
    <span>$(date '+%Y-%m-%d %H:%M')</span>
</div>

<h2>Character Arcs</h2>
<table>
<tr><th>Character</th><th>Want/Need</th><th>Wound/Lie</th><th>Flaws</th><th>Voice</th><th>Avg</th></tr>
${char_rows}
</table>

<h2>Act Structure</h2>
<table>
<tr><th>Act</th><th>Campbell</th><th>3-Act</th><th>Save Cat</th><th>Truby</th><th>Harmon</th><th>Kishoten.</th><th>Freytag</th><th>Char Web</th><th>Char Theme</th></tr>
${act_rows}
</table>

<h2>Genre Contract</h2>
<table>
<tr><th>Trope Awareness</th><th>Archetype vs Cliche</th><th>Genre Contract</th><th>Subversion</th></tr>
<tr>${genre_row}</tr>
</table>

<div class="two-col">
<div>
<h2>Top Strengths</h2>
<table>
<tr><th>Principle</th><th>Avg</th><th>Best Scenes</th></tr>
${strengths}
</table>
</div>
<div>
<h2>Areas for Improvement</h2>
<table>
<tr><th>Principle</th><th>Avg</th><th>Weakest Scenes</th></tr>
${weaknesses}
</table>
</div>
</div>

<h2>Improvement Proposals</h2>
<table>
<tr><th>Principle</th><th>Lever</th><th>Change</th><th>Rationale</th><th>Status</th></tr>
${proposal_rows}
</table>

<h2>Scene Averages</h2>
<table>
<tr><th>Scene</th><th>Avg Score</th></tr>
${scene_heatmap}
</table>

</div>
</body>
</html>
EOF

    log "Generated scoring report: ${report_file}"
}

# ============================================================================
# build_score_pr_comment(cycle_dir, project_dir, cycle, mode, scene_count, cost)
# Build a markdown PR comment with scoring summary
# ============================================================================

build_score_pr_comment() {
    local cycle_dir="$1" project_dir="$2" cycle="$3" mode="$4" scene_count="$5" cost="$6"
    local project_title
    project_title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Unknown")

    local comment="## Scoring Report — Cycle ${cycle}

**${project_title}** | ${mode} mode | ${scene_count} scenes | \$${cost}

"

    # Character arcs
    if [[ -f "${cycle_dir}/character-scores.csv" ]]; then
        comment="${comment}### Character Arcs
| Character | Want/Need | Wound/Lie | Flaws | Voice | Avg |
|-----------|-----------|-----------|-------|-------|-----|
"
        while IFS='|' read -r char wn wl fas vac; do
            [[ "$char" == "character" ]] && continue
            local avg
            avg=$(awk "BEGIN { printf \"%.1f\", ($wn + $wl + $fas + $vac) / 4 }")
            local wn_icon wl_icon fas_icon vac_icon
            wn_icon=$(_score_icon "$wn"); wl_icon=$(_score_icon "$wl")
            fas_icon=$(_score_icon "$fas"); vac_icon=$(_score_icon "$vac")
            comment="${comment}| ${char} | ${wn_icon} ${wn} | ${wl_icon} ${wl} | ${fas_icon} ${fas} | ${vac_icon} ${vac} | **${avg}** |
"
        done < "${cycle_dir}/character-scores.csv"
        comment="${comment}
"
    fi

    # Act structure
    if [[ -f "${cycle_dir}/act-scores.csv" ]]; then
        comment="${comment}### Act Structure
| Act | Campbell | 3-Act | Save Cat | Truby | Harmon | Kishoten. | Freytag | Char Web | Theme |
|-----|----------|-------|----------|-------|--------|-----------|---------|----------|-------|
"
        while IFS='|' read -r id cm ta stc t22 hc ki fr cw ct; do
            [[ "$id" == "id" ]] && continue
            local label
            label=$(echo "$id" | sed 's/act-/Part /')
            comment="${comment}| ${label} | ${cm} | ${ta} | ${stc} | ${t22} | ${hc} | ${ki} | ${fr} | ${cw} | ${ct} |
"
        done < "${cycle_dir}/act-scores.csv"
        comment="${comment}
"
    fi

    # Genre
    if [[ -f "${cycle_dir}/genre-scores.csv" ]]; then
        local genre_vals
        genre_vals=$(awk -F'|' 'NR==2' "${cycle_dir}/genre-scores.csv")
        comment="${comment}### Genre Contract
| Trope Awareness | Archetype vs Cliche | Genre Contract | Subversion |
|-----------------|---------------------|----------------|------------|
| $(echo "$genre_vals" | awk -F'|' '{ printf "%s | %s | %s | %s", $1, $2, $3, $4 }') |

"
    fi

    # Top strengths and weaknesses
    if [[ -f "${cycle_dir}/diagnosis.csv" ]]; then
        local top5_strong top5_weak
        top5_strong=$(awk -F'|' 'NR>1 && $3+0 > 0' "${cycle_dir}/diagnosis.csv" | sort -t'|' -k3 -rn | head -5)
        top5_weak=$(awk -F'|' 'NR>1 && $3+0 > 0' "${cycle_dir}/diagnosis.csv" | sort -t'|' -k3 -n | head -5)

        comment="${comment}### Top Strengths
| Principle | Avg | Best Scenes |
|-----------|-----|-------------|
"
        echo "$top5_strong" | while IFS='|' read -r prin scale avg scenes delta priority; do
            comment_line="| ${prin//_/ } | ${avg} | ${scenes} |"
            echo "$comment_line"
        done | while read -r line; do
            comment="${comment}${line}
"
        done
        # Use a simpler approach - pipe to a temp var
        local strong_rows weak_rows
        strong_rows=$(echo "$top5_strong" | while IFS='|' read -r prin scale avg scenes delta priority; do
            echo "| ${prin//_/ } | ${avg} | ${scenes} |"
        done)
        weak_rows=$(echo "$top5_weak" | while IFS='|' read -r prin scale avg scenes delta priority; do
            echo "| ${prin//_/ } | ${avg} | ${scenes} |"
        done)

        comment="${comment}${strong_rows}

### Areas for Improvement
| Principle | Avg | Weakest Scenes |
|-----------|-----|----------------|
${weak_rows}

"
    fi

    # Proposals
    if [[ -f "${cycle_dir}/proposals.csv" ]]; then
        local prop_count
        prop_count=$(awk -F'|' 'NR>1' "${cycle_dir}/proposals.csv" | wc -l | tr -d ' ')
        if (( prop_count > 0 )); then
            comment="${comment}### Improvement Proposals (${prop_count})
| Principle | Lever | Change | Status |
|-----------|-------|--------|--------|
"
            while IFS='|' read -r pid prin lever target change rationale status; do
                [[ "$pid" == "id" ]] && continue
                comment="${comment}| ${prin//_/ } | ${lever//_/ } | ${change} | ${status} |
"
            done < "${cycle_dir}/proposals.csv"
            comment="${comment}
"
        fi
    fi

    comment="${comment}---
*Report: \`working/scores/cycle-${cycle}/report.html\`*"

    echo "$comment"
}

# Helper: score icon for PR comment
_score_icon() {
    local score="$1"
    if (( score >= 4 )); then echo "🟢"
    elif (( score >= 3 )); then echo "🟡"
    else echo "🔴"
    fi
}

# ============================================================================
# Diagnostic scoring functions
# ============================================================================

# build_diagnostic_markers(diagnostics_csv)
# Reads the diagnostics CSV and formats markers into a readable text block
# for the Haiku diagnostic prompt. Groups by principle with headers.
build_diagnostic_markers() {
    local diagnostics_csv="$1"
    local filter_section="${2:-}"  # Optional: only markers for this section

    if [[ ! -f "$diagnostics_csv" ]]; then
        log "WARNING: Diagnostics CSV not found: $diagnostics_csv"
        return 1
    fi

    local current_principle=""
    local output=""

    while IFS='|' read -r section principle marker_id question deficit_if weight evidence_required; do
        # Skip header
        [[ "$section" == "section" ]] && continue

        # Filter by section if specified
        if [[ -n "$filter_section" && "$section" != "$filter_section" ]]; then
            continue
        fi

        # Print principle header when it changes
        if [[ "$principle" != "$current_principle" ]]; then
            current_principle="$principle"
            output="${output}
=== ${principle} ===
"
        fi

        output="${output}[${marker_id}] ${question}
"
    done < "$diagnostics_csv"

    echo "$output"
}

# list_diagnostic_sections(diagnostics_csv)
# Returns unique section names from the diagnostics CSV, one per line.
list_diagnostic_sections() {
    local diagnostics_csv="$1"
    awk -F'|' 'NR > 1 { if (!seen[$1]++) print $1 }' "$diagnostics_csv"
}

# count_diagnostic_markers(diagnostics_csv, section)
# Returns number of markers in a section.
count_diagnostic_markers() {
    local diagnostics_csv="$1"
    local section="$2"
    awk -F'|' -v s="$section" 'NR > 1 && $1 == s { count++ } END { print count+0 }' "$diagnostics_csv"
}

# parse_diagnostic_output(log_file, output_dir, scene_id)
# Extracts Claude's response from a stream-json log file using extract_claude_response.
# Parses the DIAGNOSTICS: CSV block.
# Writes marker results to ${output_dir}/.diag-${scene_id}.csv
# Format: marker_id|answer|evidence
# Returns 0 on success, 1 on failure.
parse_diagnostic_output() {
    local log_file="$1"
    local output_dir="$2"
    local scene_id="$3"

    if [[ ! -f "$log_file" ]]; then
        log "WARNING: Log file not found for diagnostic parsing: $log_file"
        return 1
    fi

    local text_content
    text_content=$(extract_claude_response "$log_file") || {
        log "WARNING: No text content found in $log_file"
        return 1
    }

    # Extract DIAGNOSTICS: block — lines between marker and next blank line or next marker
    local diag_block
    diag_block=$(echo "$text_content" | awk '
        /^DIAGNOSTICS:/ { found=1; next }
        found && /^[[:space:]]*$/ { found=0 }
        found && /^[A-Z_]+:/ { found=0 }
        found { print }
    ')

    if [[ -z "$diag_block" ]]; then
        log "WARNING: No DIAGNOSTICS block found in $log_file"
        return 1
    fi

    local diag_file="${output_dir}/.diag-${scene_id}.csv"
    # If block starts with the header line, use it directly; otherwise add header
    if echo "$diag_block" | head -1 | grep -q "^marker_id"; then
        echo "$diag_block" > "$diag_file"
    else
        echo "marker_id|answer|evidence" > "$diag_file"
        echo "$diag_block" >> "$diag_file"
    fi

    return 0
}

# aggregate_diagnostic_scores(diag_file, diagnostics_csv, output_scores, output_rationale, scene_id)
# Reads per-scene diagnostic results and the master diagnostics.csv.
# For each principle, computes deficit ratio and maps to 1-5 scale.
# Writes output_scores and output_rationale as pipe-delimited CSV.
aggregate_diagnostic_scores() {
    local diag_file="$1"
    local diagnostics_csv="$2"
    local output_scores="$3"
    local output_rationale="$4"
    local scene_id="$5"

    if [[ ! -f "$diag_file" || ! -f "$diagnostics_csv" ]]; then
        log "WARNING: Missing input files for diagnostic aggregation"
        return 1
    fi

    # Collect all principles in order (unique, preserving first-seen order)
    local principles_ordered=""
    local seen_principles=""
    while IFS='|' read -r section principle marker_id question deficit_if weight evidence_required; do
        [[ "$section" == "section" ]] && continue
        # Check if already seen using grep on the tracker string
        if ! echo "$seen_principles" | grep -q "|${principle}|"; then
            seen_principles="${seen_principles}|${principle}|"
            if [[ -z "$principles_ordered" ]]; then
                principles_ordered="$principle"
            else
                principles_ordered="${principles_ordered} ${principle}"
            fi
        fi
    done < "$diagnostics_csv"

    # For each principle, compute deficit ratio using awk across both files
    # We'll build the score and rationale rows in a temp file via awk
    local tmp_results="${output_scores}.tmp.$$"

    awk -F'|' '
        # First file: diagnostics_csv — read marker definitions
        # Fields: section|principle|marker_id|question|deficit_if|weight|evidence_required
        FNR == NR && FNR == 1 { next }
        FNR == NR {
            principle = $2
            marker = $3
            weight_val = $6 + 0

            marker_principle[marker] = principle
            marker_weight[marker] = weight_val
            max_points[principle] += weight_val

            # Track principle order
            if (!(principle in seen)) {
                seen[principle] = 1
                prin_order[++prin_count] = principle
            }
            next
        }
        # Second file: diag_file — read diagnostic results
        # Fields: marker_id|answer|evidence
        FNR == 1 { next }
        {
            marker = $1
            answer = $2
            evidence = $3

            if (marker in marker_principle) {
                p = marker_principle[marker]
                # YES = deficit found, NO = no deficit
                ans_lower = tolower(answer)
                if (ans_lower == "yes") {
                    deficit_points[p] += marker_weight[marker]
                    # Collect evidence
                    if (evidence != "" && evidence != "CLEAN") {
                        if (rationale[p] != "") rationale[p] = rationale[p] "; "
                        rationale[p] = rationale[p] marker ": " evidence
                    }
                }
            }
        }
        END {
            # Map deficit ratio to 1-5 scale
            # ratio = 0.00 -> 5, <= 0.20 -> 4, <= 0.50 -> 3, <= 0.80 -> 2, > 0.80 -> 1

            # Print header line
            header = "id"
            for (i = 1; i <= prin_count; i++) header = header "|" prin_order[i]
            print "H|" header

            # Print score row
            score_row = ""
            for (i = 1; i <= prin_count; i++) {
                p = prin_order[i]
                if (max_points[p] > 0) {
                    ratio = deficit_points[p] / max_points[p]
                } else {
                    ratio = 0
                }
                if (ratio == 0) score = 5
                else if (ratio <= 0.20) score = 4
                else if (ratio <= 0.50) score = 3
                else if (ratio <= 0.80) score = 2
                else score = 1
                if (score_row != "") score_row = score_row "|"
                score_row = score_row score
            }
            print "S|" score_row

            # Print rationale row
            rat_row = ""
            for (i = 1; i <= prin_count; i++) {
                p = prin_order[i]
                r = rationale[p]
                if (r == "") r = "No deficits"
                # Replace pipes in rationale with dashes
                gsub(/\|/, "-", r)
                if (rat_row != "") rat_row = rat_row "|"
                rat_row = rat_row r
            }
            print "R|" rat_row
        }
    ' "$diagnostics_csv" "$diag_file" > "$tmp_results"

    # Parse the temp results into scores and rationale files
    # Use sed to strip the prefix (H|, S|, R|) — avoids awk OFS issues
    local header_line score_line rationale_line
    header_line=$(grep '^H|' "$tmp_results" | sed 's/^H|//')
    score_line=$(grep '^S|' "$tmp_results" | sed 's/^S|//')
    rationale_line=$(grep '^R|' "$tmp_results" | sed 's/^R|//')

    echo "$header_line" > "$output_scores"
    echo "${scene_id}|${score_line}" >> "$output_scores"

    echo "$header_line" > "$output_rationale"
    echo "${scene_id}|${rationale_line}" >> "$output_rationale"

    rm -f "$tmp_results"
    return 0
}

# identify_deep_dive_targets(diag_file, diagnostics_csv, threshold)
# Identifies scene-principle pairs needing Sonnet deep dive.
# A principle needs deep dive if its diagnostic score is at or below threshold (default 3).
# Outputs pipe-delimited lines: principle|score|deficit_markers
identify_deep_dive_targets() {
    local diag_file="$1"
    local diagnostics_csv="$2"
    local threshold="${3:-3}"

    if [[ ! -f "$diag_file" || ! -f "$diagnostics_csv" ]]; then
        return 1
    fi

    awk -F'|' -v threshold="$threshold" '
        # First file: diagnostics_csv
        # Fields: section|principle|marker_id|question|deficit_if|weight|evidence_required
        FNR == NR && FNR == 1 { next }
        FNR == NR {
            marker = $3
            principle = $2
            weight_val = $6 + 0

            marker_principle[marker] = principle
            marker_weight[marker] = weight_val
            max_points[principle] += weight_val

            if (!(principle in seen)) {
                seen[principle] = 1
                prin_order[++prin_count] = principle
            }
            next
        }
        # Second file: diag_file
        FNR == 1 { next }
        {
            marker = $1
            answer = $2

            if (marker in marker_principle) {
                p = marker_principle[marker]
                ans_lower = tolower(answer)
                if (ans_lower == "yes") {
                    deficit_points[p] += marker_weight[marker]
                    if (deficit_markers[p] != "") deficit_markers[p] = deficit_markers[p] ";"
                    deficit_markers[p] = deficit_markers[p] marker
                }
            }
        }
        END {
            for (i = 1; i <= prin_count; i++) {
                p = prin_order[i]
                if (max_points[p] > 0) {
                    ratio = deficit_points[p] / max_points[p]
                } else {
                    ratio = 0
                }
                if (ratio == 0) score = 5
                else if (ratio <= 0.20) score = 4
                else if (ratio <= 0.50) score = 3
                else if (ratio <= 0.80) score = 2
                else score = 1

                if (score <= threshold) {
                    dm = deficit_markers[p]
                    if (dm == "") dm = "none"
                    print p "|" score "|" dm
                }
            }
        }
    ' "$diagnostics_csv" "$diag_file"
}

# build_principle_guide(principle_name, guide_file)
# Extracts the "what it looks like / doesn't look like" section for a specific
# principle from the principle-guide.md file.
# The guide uses ### principle_name headers. Extracts everything between
# the matching header and the next ### or ## header.
build_principle_guide() {
    local principle_name="$1"
    local guide_file="$2"

    if [[ ! -f "$guide_file" ]]; then
        log "WARNING: Principle guide not found: $guide_file"
        return 1
    fi

    awk -v principle="$principle_name" '
        $0 ~ "^### " principle "$" { found=1; next }
        found && /^###? / { found=0 }
        found { print }
    ' "$guide_file"
}

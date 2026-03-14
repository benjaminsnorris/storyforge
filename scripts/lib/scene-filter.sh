#!/bin/bash
# scene-filter.sh — Shared scene list building and filtering for Storyforge
#
# Provides a single source of truth for:
#   1. Building the ordered scene list from metadata.csv (sorted by seq, excluding cut)
#   2. Filtering by --scenes, --act, --from-seq (with range support)
#
# Source this file via common.sh; do not execute it directly.
# Requires csv.sh to be loaded first (for get_csv_field, list_csv_ids).

# ============================================================================
# build_scene_list — populate ALL_SCENE_IDS from metadata.csv
# ============================================================================
#
# Usage: build_scene_list <metadata_csv>
#
# Sets global array ALL_SCENE_IDS with scene IDs sorted by seq, excluding
# scenes with status "cut". Exits with error if no scenes found.
build_scene_list() {
    local metadata_csv="$1"

    if [[ ! -f "$metadata_csv" ]]; then
        log "ERROR: Metadata CSV not found: ${metadata_csv}"
        log "Run 'storyforge scenes' to create scene metadata."
        exit 1
    fi

    ALL_SCENE_IDS=()
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue
        local_status=$(get_csv_field "$metadata_csv" "$id" "status")
        if [[ "$local_status" != "cut" ]]; then
            ALL_SCENE_IDS+=("$id")
        fi
    done < <(awk -F'|' '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                if ($i == "seq") seq_col = i
            }
            next
        }
        seq_col { print $1 "|" $seq_col }
    ' "$metadata_csv" | sort -t'|' -k2 -n | cut -d'|' -f1)

    if [[ ${#ALL_SCENE_IDS[@]} -eq 0 ]]; then
        log "ERROR: No scenes found in ${metadata_csv}"
        exit 1
    fi

    log "Found ${#ALL_SCENE_IDS[@]} scenes in metadata.csv"
}

# ============================================================================
# apply_scene_filter — filter ALL_SCENE_IDS into FILTERED_IDS
# ============================================================================
#
# Usage: apply_scene_filter <metadata_csv> <mode> [value]
#
# Modes:
#   all                         — no filtering, all scenes
#   scenes <id,id,...>          — comma-separated scene IDs
#   single <id>                 — one specific scene ID
#   act <N>                     — scenes where CSV part column == N
#   from_seq <N> or <N-M>      — sequence range (N onward, or N through M)
#   range <start_id> <end_id>  — inclusive range by position in scene list
#
# Reads from ALL_SCENE_IDS (must be populated by build_scene_list first).
# Sets global array FILTERED_IDS.
apply_scene_filter() {
    local metadata_csv="$1"
    local mode="$2"
    local value="${3:-}"
    local value2="${4:-}"

    FILTERED_IDS=()

    case "$mode" in
        all)
            FILTERED_IDS=("${ALL_SCENE_IDS[@]}")
            ;;

        scenes)
            # Comma-separated list of scene IDs
            IFS=',' read -ra REQUESTED <<< "$value"
            for req in "${REQUESTED[@]}"; do
                req=$(echo "$req" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
                found=false
                for id in "${ALL_SCENE_IDS[@]}"; do
                    if [[ "$id" == "$req" ]]; then
                        FILTERED_IDS+=("$req")
                        found=true
                        break
                    fi
                done
                if [[ "$found" == false ]]; then
                    log "WARNING: Scene '$req' not found in metadata.csv, skipping"
                fi
            done
            if [[ ${#FILTERED_IDS[@]} -eq 0 ]]; then
                log "ERROR: None of the requested scenes were found"
                exit 1
            fi
            ;;

        single)
            # Single scene ID
            found=false
            for id in "${ALL_SCENE_IDS[@]}"; do
                if [[ "$id" == "$value" ]]; then
                    found=true
                    break
                fi
            done
            if [[ "$found" == false ]]; then
                log "ERROR: Scene '${value}' not found in metadata.csv"
                exit 1
            fi
            FILTERED_IDS=("$value")
            ;;

        act)
            # Filter by CSV part column
            for id in "${ALL_SCENE_IDS[@]}"; do
                scene_part=$(get_csv_field "$metadata_csv" "$id" "part")
                if [[ "$scene_part" == "$value" ]]; then
                    FILTERED_IDS+=("$id")
                fi
            done
            if [[ ${#FILTERED_IDS[@]} -eq 0 ]]; then
                log "ERROR: No scenes found in act/part ${value}"
                exit 1
            fi
            log "Filtered to ${#FILTERED_IDS[@]} scenes in act/part ${value}"
            ;;

        from_seq)
            # Parse N or N-M range
            local seq_start seq_end
            if [[ "$value" == *-* ]]; then
                seq_start="${value%%-*}"
                seq_end="${value##*-}"
            else
                seq_start="$value"
                seq_end=""
            fi

            # Validate
            if [[ ! "$seq_start" =~ ^[0-9]+$ ]]; then
                log "ERROR: Invalid sequence number: ${seq_start}"
                exit 1
            fi
            if [[ -n "$seq_end" && ! "$seq_end" =~ ^[0-9]+$ ]]; then
                log "ERROR: Invalid sequence end number: ${seq_end}"
                exit 1
            fi

            for id in "${ALL_SCENE_IDS[@]}"; do
                scene_seq=$(get_csv_field "$metadata_csv" "$id" "seq")
                if [[ -n "$scene_seq" && "$scene_seq" =~ ^[0-9]+$ ]]; then
                    if (( scene_seq >= seq_start )); then
                        if [[ -z "$seq_end" ]] || (( scene_seq <= seq_end )); then
                            FILTERED_IDS+=("$id")
                        fi
                    fi
                fi
            done
            if [[ ${#FILTERED_IDS[@]} -eq 0 ]]; then
                if [[ -n "$seq_end" ]]; then
                    log "ERROR: No scenes found with seq ${seq_start}-${seq_end}"
                else
                    log "ERROR: No scenes found with seq >= ${seq_start}"
                fi
                exit 1
            fi
            if [[ -n "$seq_end" ]]; then
                log "Filtered to ${#FILTERED_IDS[@]} scenes with seq ${seq_start}-${seq_end}"
            else
                log "Filtered to ${#FILTERED_IDS[@]} scenes with seq >= ${seq_start}"
            fi
            ;;

        range)
            # Inclusive range by position in ALL_SCENE_IDS (start_id to end_id)
            local start_id="$value"
            local end_id="$value2"
            in_range=false
            for id in "${ALL_SCENE_IDS[@]}"; do
                if [[ "$id" == "$start_id" ]]; then
                    in_range=true
                fi
                if [[ "$in_range" == true ]]; then
                    FILTERED_IDS+=("$id")
                fi
                if [[ "$id" == "$end_id" ]]; then
                    break
                fi
            done
            if [[ ${#FILTERED_IDS[@]} -eq 0 ]]; then
                log "ERROR: Could not find range ${start_id} to ${end_id}"
                exit 1
            fi
            ;;
    esac
}

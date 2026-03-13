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

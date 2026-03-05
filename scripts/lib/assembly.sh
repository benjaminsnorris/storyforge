#!/bin/bash
# assembly.sh — Library functions for chapter assembly and book production
#
# Source this file from storyforge-assemble; do not execute directly.
# Requires common.sh to be sourced first.

# ============================================================================
# Chapter map parsing
# ============================================================================

# Get the total number of chapters in chapter-map.yaml
# Usage: count_chapters "/path/to/project"
count_chapters() {
    local project_dir="$1"
    local chapter_map="${project_dir}/reference/chapter-map.yaml"

    if [[ ! -f "$chapter_map" ]]; then
        echo "0"
        return 1
    fi

    grep -cE '^[[:space:]]*- title:' "$chapter_map" 2>/dev/null || echo "0"
}

# Get the Nth chapter block (1-indexed) from chapter-map.yaml
# Usage: get_chapter_block 1 "/path/to/project"
get_chapter_block() {
    local chapter_num="$1"
    local project_dir="$2"
    local chapter_map="${project_dir}/reference/chapter-map.yaml"

    if [[ ! -f "$chapter_map" ]]; then
        return 1
    fi

    awk -v num="$chapter_num" '
        /^[[:space:]]*- title:/ { count++ }
        count == num { print }
        count > num { exit }
    ' "$chapter_map"
}

# Read a field from a chapter block
# Usage: read_chapter_field 1 "/path/to/project" "title"
read_chapter_field() {
    local chapter_num="$1"
    local project_dir="$2"
    local field="$3"

    local block
    block=$(get_chapter_block "$chapter_num" "$project_dir")
    if [[ -z "$block" ]]; then
        return 1
    fi

    # Match field with optional leading "- " (YAML list item prefix)
    echo "$block" \
        | grep -E "[[:space:]](-[[:space:]]+)?${field}:" \
        | head -1 \
        | sed "s/^.*${field}:[[:space:]]*//" \
        | sed 's/^["'"'"']//' \
        | sed 's/["'"'"']$//' \
        | sed 's/[[:space:]]*$//'
}

# Get the scene IDs for a chapter (from the scenes list in the chapter block)
# Usage: get_chapter_scenes 1 "/path/to/project"
get_chapter_scenes() {
    local chapter_num="$1"
    local project_dir="$2"

    local block
    block=$(get_chapter_block "$chapter_num" "$project_dir")
    if [[ -z "$block" ]]; then
        return 1
    fi

    # Extract scene IDs from the scenes list within the block
    echo "$block" \
        | sed -n '/scenes:/,/^[[:space:]]*[^-[:space:]]/p' \
        | grep -E '^[[:space:]]*-[[:space:]]' \
        | sed 's/^[[:space:]]*-[[:space:]]*//' \
        | sed 's/^["'"'"']//' \
        | sed 's/["'"'"']$//' \
        | sed 's/[[:space:]]*$//'
}

# ============================================================================
# Chapter assembly
# ============================================================================

# Extract prose from a scene file (strip YAML frontmatter)
# Usage: extract_scene_prose "/path/to/scene.md"
extract_scene_prose() {
    local scene_file="$1"

    if [[ ! -f "$scene_file" ]]; then
        return 1
    fi

    # Strip YAML frontmatter (between --- delimiters)
    awk '
        BEGIN { in_frontmatter=0; past_frontmatter=0 }
        /^---$/ {
            if (in_frontmatter) { past_frontmatter=1; in_frontmatter=0; next }
            if (!past_frontmatter) { in_frontmatter=1; next }
        }
        past_frontmatter { print }
    ' "$scene_file" | sed '/./,$!d'  # Strip leading blank lines
}

# Assemble a single chapter from its scenes
# Usage: assemble_chapter 1 "/path/to/project" "scene_break_style"
# scene_break_style: "blank" (default), "ornamental", "custom:SYMBOL"
assemble_chapter() {
    local chapter_num="$1"
    local project_dir="$2"
    local break_style="${3:-blank}"

    local title
    title=$(read_chapter_field "$chapter_num" "$project_dir" "title")
    local heading_format
    heading_format=$(read_chapter_field "$chapter_num" "$project_dir" "heading" 2>/dev/null || echo "")

    # Build chapter heading
    local heading=""
    case "$heading_format" in
        numbered)
            heading="# Chapter ${chapter_num}"
            ;;
        titled)
            heading="# ${title}"
            ;;
        numbered-titled|"")
            heading="# Chapter ${chapter_num}: ${title}"
            ;;
        none)
            heading=""
            ;;
    esac

    if [[ -n "$heading" ]]; then
        echo "$heading"
        echo ""
    fi

    # Build scene break marker
    local break_marker=""
    case "$break_style" in
        blank)
            break_marker=""
            ;;
        ornamental)
            break_marker="* * *"
            ;;
        custom:*)
            break_marker="${break_style#custom:}"
            ;;
    esac

    # Concatenate scene prose
    local scene_ids
    scene_ids=$(get_chapter_scenes "$chapter_num" "$project_dir")
    local first=true

    while IFS= read -r scene_id; do
        [[ -z "$scene_id" ]] && continue

        local scene_file="${project_dir}/scenes/${scene_id}.md"
        if [[ ! -f "$scene_file" ]]; then
            log "WARNING: Scene file not found: ${scene_file}"
            continue
        fi

        if [[ "$first" == true ]]; then
            first=false
        else
            # Scene break between scenes
            echo ""
            if [[ -n "$break_marker" ]]; then
                echo "$break_marker"
                echo ""
            fi
        fi

        extract_scene_prose "$scene_file"
    done <<< "$scene_ids"
}

# ============================================================================
# Production config parsing
# ============================================================================

# Read a production config value from chapter-map.yaml's production: section
# Usage: read_production_field "/path/to/project" "scene_break"
read_production_field() {
    local project_dir="$1"
    local field="$2"
    local chapter_map="${project_dir}/reference/chapter-map.yaml"

    if [[ ! -f "$chapter_map" ]]; then
        return 1
    fi

    sed -n '/^production:/,/^[^ ]/p' "$chapter_map" \
        | grep -E "^[[:space:]]+${field}:" \
        | head -1 \
        | sed "s/^[[:space:]]*${field}:[[:space:]]*//" \
        | sed 's/^["'"'"']//' \
        | sed 's/["'"'"']$//' \
        | sed 's/[[:space:]]*$//'
}

# Read a nested production field (e.g., production.front_matter.title)
# Usage: read_production_nested "/path/to/project" "front_matter" "title"
read_production_nested() {
    local project_dir="$1"
    local parent="$2"
    local child="$3"
    local chapter_map="${project_dir}/reference/chapter-map.yaml"

    if [[ ! -f "$chapter_map" ]]; then
        return 1
    fi

    # Use awk to extract the nested value from production > parent > child
    awk -v parent="$parent" -v child="$child" '
        /^production:/ { in_prod=1; next }
        in_prod && /^[^ ]/ { in_prod=0 }
        in_prod && $0 ~ "^[[:space:]]+" parent ":" { in_parent=1; next }
        in_parent && /^[[:space:]]+[^[:space:]]/ && !/^[[:space:]]+[[:space:]]/ { in_parent=0 }
        in_parent && $0 ~ "^[[:space:]]+" child ":" {
            val = $0
            sub("^[[:space:]]*" child ":[[:space:]]*", "", val)
            gsub(/^["'"'"'"]|["'"'"'"]$/, "", val)
            gsub(/[[:space:]]*$/, "", val)
            print val
            exit
        }
    ' "$chapter_map"
}

# ============================================================================
# Front/back matter generation
# ============================================================================

# Generate a title page in markdown
# Usage: generate_title_page "/path/to/project"
generate_title_page() {
    local project_dir="$1"

    local title
    title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Untitled")
    local author
    author=$(read_production_field "$project_dir" "author" 2>/dev/null || echo "")

    echo "---"
    echo "title: \"${title}\""
    if [[ -n "$author" ]]; then
        echo "author: \"${author}\""
    fi
    echo "---"
    echo ""
    echo "# ${title}"
    echo ""
    if [[ -n "$author" ]]; then
        echo "### ${author}"
        echo ""
    fi
}

# Generate a copyright page in markdown
# Usage: generate_copyright_page "/path/to/project"
generate_copyright_page() {
    local project_dir="$1"

    local title
    title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Untitled")
    local author
    author=$(read_production_field "$project_dir" "author" 2>/dev/null || echo "")
    local copyright_year
    copyright_year=$(read_production_nested "$project_dir" "copyright" "year" 2>/dev/null || date +%Y)
    local isbn
    isbn=$(read_production_nested "$project_dir" "copyright" "isbn" 2>/dev/null || echo "")
    local license_text
    license_text=$(read_production_nested "$project_dir" "copyright" "license" 2>/dev/null || echo "All rights reserved.")

    echo "# Copyright"
    echo ""
    echo "*${title}*"
    echo ""
    if [[ -n "$author" ]]; then
        echo "Copyright © ${copyright_year} ${author}"
    else
        echo "Copyright © ${copyright_year}"
    fi
    echo ""
    echo "${license_text}"
    echo ""
    if [[ -n "$isbn" ]]; then
        echo "ISBN: ${isbn}"
        echo ""
    fi
}

# Generate a table of contents in markdown
# Usage: generate_toc "/path/to/project"
generate_toc() {
    local project_dir="$1"

    local total
    total=$(count_chapters "$project_dir")
    if [[ "$total" == "0" ]]; then
        return 1
    fi

    echo "# Contents"
    echo ""

    for (( i=1; i<=total; i++ )); do
        local title
        title=$(read_chapter_field "$i" "$project_dir" "title")
        local heading_format
        heading_format=$(read_chapter_field "$i" "$project_dir" "heading" 2>/dev/null || echo "")

        case "$heading_format" in
            numbered)
                echo "- Chapter ${i}"
                ;;
            titled)
                echo "- ${title}"
                ;;
            none)
                echo "- Chapter ${i}"
                ;;
            *)
                echo "- Chapter ${i}: ${title}"
                ;;
        esac
    done
    echo ""
}

# Read front matter or back matter content file if it exists
# Usage: read_matter_file "/path/to/project" "front_matter" "dedication"
read_matter_file() {
    local project_dir="$1"
    local section="$2"
    local name="$3"

    # Check if a file path is specified in the chapter map
    local filepath
    filepath=$(read_production_nested "$project_dir" "$section" "$name" 2>/dev/null || echo "")

    if [[ -n "$filepath" && -f "${project_dir}/${filepath}" ]]; then
        cat "${project_dir}/${filepath}"
        return 0
    fi

    # Check default locations
    local default_path
    case "$section" in
        front_matter) default_path="manuscript/front-matter/${name}.md" ;;
        back_matter) default_path="manuscript/back-matter/${name}.md" ;;
    esac

    if [[ -n "$default_path" && -f "${project_dir}/${default_path}" ]]; then
        cat "${project_dir}/${default_path}"
        return 0
    fi

    return 1
}

# ============================================================================
# Epub metadata generation
# ============================================================================

# Generate pandoc metadata YAML for epub
# Usage: generate_epub_metadata "/path/to/project"
generate_epub_metadata() {
    local project_dir="$1"

    local title
    title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Untitled")
    local author
    author=$(read_production_field "$project_dir" "author" 2>/dev/null || echo "Anonymous")
    local language
    language=$(read_production_field "$project_dir" "language" 2>/dev/null || echo "en")
    local genre
    genre=$(read_yaml_field "project.genre" 2>/dev/null || read_yaml_field "genre" 2>/dev/null || echo "")
    local isbn
    isbn=$(read_production_nested "$project_dir" "copyright" "isbn" 2>/dev/null || echo "")
    local copyright_year
    copyright_year=$(read_production_nested "$project_dir" "copyright" "year" 2>/dev/null || date +%Y)
    local cover_image
    cover_image=$(read_production_field "$project_dir" "cover_image" 2>/dev/null || echo "")

    echo "---"
    echo "title: \"${title}\""
    echo "author: \"${author}\""
    echo "lang: ${language}"
    echo "date: ${copyright_year}"
    if [[ -n "$genre" ]]; then
        echo "subject: \"${genre}\""
    fi
    if [[ -n "$isbn" ]]; then
        echo "identifier: \"${isbn}\""
    fi
    if [[ -n "$cover_image" ]]; then
        # Resolve relative to project dir
        if [[ -f "${project_dir}/${cover_image}" ]]; then
            echo "cover-image: \"${project_dir}/${cover_image}\""
        fi
    fi
    # Series metadata (optional)
    local series_name
    series_name=$(read_yaml_field "project.series_name" 2>/dev/null || echo "")
    local series_position
    series_position=$(read_yaml_field "project.series_position" 2>/dev/null || echo "")
    if [[ -n "$series_name" ]]; then
        echo "belongs-to-collection: \"${series_name}\""
        if [[ -n "$series_position" ]]; then
            echo "group-position: \"${series_position}\""
        fi
    fi
    echo "rights: \"Copyright © ${copyright_year} ${author}\""
    echo "---"
}

# ============================================================================
# Manuscript assembly (full pipeline)
# ============================================================================

# Assemble the complete manuscript markdown file
# Usage: assemble_manuscript "/path/to/project" "/path/to/output.md"
assemble_manuscript() {
    local project_dir="$1"
    local output_file="$2"

    local break_style
    break_style=$(read_production_field "$project_dir" "scene_break" 2>/dev/null || echo "blank")

    local total
    total=$(count_chapters "$project_dir")

    if [[ "$total" == "0" ]]; then
        log "ERROR: No chapters found in chapter-map.yaml"
        return 1
    fi

    # Clear output file
    > "$output_file"

    # Front matter
    local include_toc
    include_toc=$(read_production_field "$project_dir" "include_toc" 2>/dev/null || echo "true")

    # Title page
    generate_title_page "$project_dir" >> "$output_file"

    # Copyright page
    generate_copyright_page "$project_dir" >> "$output_file"
    echo "" >> "$output_file"

    # Dedication (if exists)
    local dedication
    if dedication=$(read_matter_file "$project_dir" "front_matter" "dedication" 2>/dev/null); then
        echo "# Dedication" >> "$output_file"
        echo "" >> "$output_file"
        echo "$dedication" >> "$output_file"
        echo "" >> "$output_file"
    fi

    # Epigraph (if exists)
    local epigraph
    if epigraph=$(read_matter_file "$project_dir" "front_matter" "epigraph" 2>/dev/null); then
        echo "$epigraph" >> "$output_file"
        echo "" >> "$output_file"
    fi

    # Table of contents
    if [[ "$include_toc" != "false" ]]; then
        generate_toc "$project_dir" >> "$output_file"
    fi

    # Chapters
    for (( i=1; i<=total; i++ )); do
        assemble_chapter "$i" "$project_dir" "$break_style" >> "$output_file"
        echo "" >> "$output_file"
    done

    # Back matter
    local acknowledgments
    if acknowledgments=$(read_matter_file "$project_dir" "back_matter" "acknowledgments" 2>/dev/null); then
        echo "# Acknowledgments" >> "$output_file"
        echo "" >> "$output_file"
        echo "$acknowledgments" >> "$output_file"
        echo "" >> "$output_file"
    fi

    local about_author
    if about_author=$(read_matter_file "$project_dir" "back_matter" "about-the-author" 2>/dev/null); then
        echo "# About the Author" >> "$output_file"
        echo "" >> "$output_file"
        echo "$about_author" >> "$output_file"
        echo "" >> "$output_file"
    fi

    local also_by
    if also_by=$(read_matter_file "$project_dir" "back_matter" "also-by" 2>/dev/null); then
        echo "# Also By" >> "$output_file"
        echo "" >> "$output_file"
        echo "$also_by" >> "$output_file"
        echo "" >> "$output_file"
    fi

    return 0
}

# Count total words in the assembled manuscript
# Usage: manuscript_word_count "/path/to/manuscript.md"
manuscript_word_count() {
    local manuscript="$1"
    if [[ -f "$manuscript" ]]; then
        wc -w < "$manuscript" | tr -d ' '
    else
        echo "0"
    fi
}

# ============================================================================
# Tool detection
# ============================================================================

# Check if pandoc is available and return its version
# Usage: check_pandoc
check_pandoc() {
    if command -v pandoc &>/dev/null; then
        pandoc --version | head -1 | sed 's/pandoc //'
        return 0
    fi
    return 1
}

# Check if epubcheck is available
# Usage: check_epubcheck
check_epubcheck() {
    if command -v epubcheck &>/dev/null; then
        return 0
    fi
    # Also check for java-based jar
    if [[ -n "${EPUBCHECK_JAR:-}" && -f "$EPUBCHECK_JAR" ]]; then
        return 0
    fi
    return 1
}

# Check if weasyprint is available (for PDF)
# Usage: check_weasyprint
check_weasyprint() {
    if command -v weasyprint &>/dev/null; then
        return 0
    fi
    return 1
}

# ============================================================================
# CSS and styling
# ============================================================================

# Get the CSS file path for a genre preset
# Usage: get_genre_css "/path/to/plugin" "fantasy"
get_genre_css() {
    local plugin_dir="$1"
    local genre="$2"

    # Normalize genre to lowercase, replace spaces with hyphens
    local normalized
    normalized=$(echo "$genre" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')

    local css_file="${plugin_dir}/templates/production/css/${normalized}.css"

    if [[ -f "$css_file" ]]; then
        echo "$css_file"
        return 0
    fi

    # Fall back to default
    echo "${plugin_dir}/templates/production/css/default.css"
}

# ============================================================================
# Cover generation
# ============================================================================

# Generate a cover image if none is configured.
# Usage: generate_cover_if_missing "/path/to/project" "/path/to/plugin"
generate_cover_if_missing() {
    local project_dir="$1"
    local plugin_dir="$2"

    # Check if cover_image is already set and file exists
    local cover_image
    cover_image=$(read_production_field "$project_dir" "cover_image" 2>/dev/null || echo "")
    if [[ -n "$cover_image" && -f "${project_dir}/${cover_image}" ]]; then
        log "Cover image found: ${cover_image}"
        return 0
    fi

    # Check for cover generator script
    local cover_script="${plugin_dir}/scripts/storyforge-cover"
    if [[ ! -x "$cover_script" ]]; then
        log "No cover image configured and cover generator not found. Proceeding without cover."
        return 0
    fi

    log "No cover image found. For a custom cover, run /storyforge:cover interactively."
    log "Generating basic typographic cover from title and genre..."

    local cover_output="${project_dir}/manuscript/assets/cover.png"
    if ! "$cover_script" --output "$cover_output"; then
        log "WARNING: Cover generation failed. Proceeding without cover."
        return 0
    fi

    if [[ ! -s "$cover_output" ]]; then
        log "WARNING: No cover PNG produced. Proceeding without cover."
        return 0
    fi

    # Update chapter-map.yaml with the generated cover path
    local relative_path="${cover_output#${project_dir}/}"
    local chapter_map="${project_dir}/reference/chapter-map.yaml"
    if [[ -f "$chapter_map" ]]; then
        sed -i '' "s|^[[:space:]]*cover_image:.*|  cover_image: \"${relative_path}\"|" "$chapter_map" 2>/dev/null || true
        log "Updated chapter-map.yaml: cover_image: ${relative_path}"
    fi

    return 0
}

# ============================================================================
# Epub generation
# ============================================================================

# Generate epub from assembled manuscript using pandoc
# Usage: generate_epub "/path/to/project" "/path/to/manuscript.md" "/path/to/output.epub" "/path/to/plugin"
generate_epub() {
    local project_dir="$1"
    local manuscript="$2"
    local output_epub="$3"
    local plugin_dir="$4"

    if ! check_pandoc >/dev/null 2>&1; then
        log "ERROR: pandoc is required for epub generation but not found"
        log "Install: https://pandoc.org/installing.html"
        return 1
    fi

    # Get genre for CSS selection
    local genre
    genre=$(read_yaml_field "project.genre" 2>/dev/null || read_yaml_field "genre" 2>/dev/null || echo "default")

    local css_file
    css_file=$(get_genre_css "$plugin_dir" "$genre")

    # Check for custom CSS in project
    local project_css="${project_dir}/manuscript/assets/custom.css"
    if [[ -f "$project_css" ]]; then
        css_file="$project_css"
    fi

    # Generate metadata file
    local metadata_file="${project_dir}/manuscript/metadata.yaml"
    generate_epub_metadata "$project_dir" > "$metadata_file"

    # Build pandoc command
    local pandoc_args=(
        --from markdown
        --to epub3
        --output "$output_epub"
        --metadata-file "$metadata_file"
        --toc
        --toc-depth=1
        --epub-chapter-level=1
    )

    if [[ -f "$css_file" ]]; then
        pandoc_args+=(--css "$css_file")
    fi

    # Check for cover image
    local cover_image
    cover_image=$(read_production_field "$project_dir" "cover_image" 2>/dev/null || echo "")
    if [[ -n "$cover_image" && -f "${project_dir}/${cover_image}" ]]; then
        pandoc_args+=(--epub-cover-image "${project_dir}/${cover_image}")
    fi

    log "Running pandoc: epub3 generation..."
    pandoc "${pandoc_args[@]}" "$manuscript"
    local rc=$?

    if [[ $rc -ne 0 ]]; then
        log "ERROR: pandoc failed with exit code ${rc}"
        return 1
    fi

    log "Epub generated: ${output_epub}"
    return 0
}

# Validate epub with epubcheck
# Usage: validate_epub "/path/to/output.epub"
validate_epub() {
    local epub_file="$1"

    if ! check_epubcheck; then
        log "WARNING: epubcheck not found — skipping validation"
        log "Install: https://www.w3.org/publishing/epubcheck/"
        return 0
    fi

    log "Running epubcheck validation..."

    local result
    if [[ -n "${EPUBCHECK_JAR:-}" && -f "$EPUBCHECK_JAR" ]]; then
        result=$(java -jar "$EPUBCHECK_JAR" "$epub_file" 2>&1)
    else
        result=$(epubcheck "$epub_file" 2>&1)
    fi
    local rc=$?

    if [[ $rc -ne 0 ]]; then
        log "WARNING: epubcheck found issues:"
        echo "$result" | grep -E "(ERROR|WARNING)" | while IFS= read -r line; do
            log "  $line"
        done
        return 1
    fi

    log "Epub validation passed"
    return 0
}

# ============================================================================
# HTML generation
# ============================================================================

# Generate single-file HTML from assembled manuscript
# Usage: generate_html "/path/to/project" "/path/to/manuscript.md" "/path/to/output.html" "/path/to/plugin"
generate_html() {
    local project_dir="$1"
    local manuscript="$2"
    local output_html="$3"
    local plugin_dir="$4"

    if ! check_pandoc >/dev/null 2>&1; then
        log "ERROR: pandoc is required for HTML generation but not found"
        return 1
    fi

    local genre
    genre=$(read_yaml_field "project.genre" 2>/dev/null || read_yaml_field "genre" 2>/dev/null || echo "default")

    local css_file
    css_file=$(get_genre_css "$plugin_dir" "$genre")

    local project_css="${project_dir}/manuscript/assets/custom.css"
    if [[ -f "$project_css" ]]; then
        css_file="$project_css"
    fi

    local title
    title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Untitled")

    local pandoc_args=(
        --from markdown
        --to html5
        --output "$output_html"
        --standalone
        --metadata "title=${title}"
        --toc
        --toc-depth=1
    )

    if [[ -f "$css_file" ]]; then
        pandoc_args+=(--css "$css_file")
    fi

    log "Running pandoc: HTML generation..."
    pandoc "${pandoc_args[@]}" "$manuscript"
    local rc=$?

    if [[ $rc -ne 0 ]]; then
        log "ERROR: pandoc failed with exit code ${rc}"
        return 1
    fi

    log "HTML generated: ${output_html}"
    return 0
}

# ============================================================================
# Web book generation (multi-page static site)
# ============================================================================

# Generate a multi-page web book from assembled chapters.
# Produces a folder of HTML files — one per chapter, plus index and TOC.
# Usage: generate_web_book "/path/to/project" "/path/to/plugin"
generate_web_book() {
    local project_dir="$1"
    local plugin_dir="$2"
    local output_dir="${project_dir}/manuscript/output/web"
    local template_dir="${plugin_dir}/templates/production/web-book"
    local chapters_dir="${project_dir}/manuscript/chapters"

    if ! check_pandoc >/dev/null 2>&1; then
        log "ERROR: pandoc is required for web book generation but not found"
        return 1
    fi

    # Verify templates exist
    for tmpl in reading.css reading.js index.html toc.html chapter.html; do
        if [[ ! -f "${template_dir}/${tmpl}" ]]; then
            log "ERROR: Web book template missing: ${template_dir}/${tmpl}"
            return 1
        fi
    done

    # Read metadata
    local title
    title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Untitled")
    local author
    author=$(read_production_field "$project_dir" "author" 2>/dev/null || echo "")
    local language
    language=$(read_production_field "$project_dir" "language" 2>/dev/null || echo "en")
    local logline
    logline=$(read_yaml_field "project.logline" 2>/dev/null || echo "")
    local description
    description=$(read_production_nested "$project_dir" "web" "description" 2>/dev/null || echo "$logline")
    local base_url
    base_url=$(read_production_nested "$project_dir" "web" "base_url" 2>/dev/null || echo "")
    local series_name
    series_name=$(read_yaml_field "project.series_name" 2>/dev/null || echo "")
    local series_pos
    series_pos=$(read_yaml_field "project.series_position" 2>/dev/null || echo "")
    local copyright_year
    copyright_year=$(read_production_nested "$project_dir" "copyright" "year" 2>/dev/null || date +%Y)
    local cover_image
    cover_image=$(read_production_field "$project_dir" "cover_image" 2>/dev/null || echo "")

    local total_chapters
    total_chapters=$(count_chapters)

    # Read CSS and JS templates
    local css_content
    css_content=$(cat "${template_dir}/reading.css")
    local js_content
    js_content=$(cat "${template_dir}/reading.js")

    # Head script (prevents flash of wrong theme) — extracted from JS comment
    local head_script
    head_script="(function(){var t=localStorage.getItem('storyforge-theme');if(t)document.documentElement.dataset.theme=t;else if(window.matchMedia('(prefers-color-scheme:dark)').matches)document.documentElement.dataset.theme='dark'})()"

    # Create output directories
    mkdir -p "${output_dir}/chapters"

    log "Generating web book: ${total_chapters} chapters..."

    # --- Build chapter list for TOC ---
    local toc_entries=""
    local ch_titles=()
    local ch_slugs=()
    for (( ch=1; ch<=total_chapters; ch++ )); do
        local ch_title
        ch_title=$(read_chapter_field "$ch" "$project_dir" "title")
        local ch_slug
        ch_slug=$(printf 'chapter-%02d' "$ch")
        ch_titles+=("$ch_title")
        ch_slugs+=("$ch_slug")
        toc_entries="${toc_entries}    <li><a href=\"chapters/${ch_slug}.html\" data-chapter=\"${ch_slug}\">${ch_title}</a></li>
"
    done

    # --- Helper: substitute template variables ---
    _web_sub() {
        local content="$1"
        content="${content//\{\{BOOK_TITLE\}\}/$title}"
        content="${content//\{\{AUTHOR\}\}/$author}"
        content="${content//\{\{LANG\}\}/$language}"
        content="${content//\{\{DESCRIPTION\}\}/$description}"
        content="${content//\{\{TOTAL_CHAPTERS\}\}/$total_chapters}"
        content="${content//\{\{CSS\}\}/$css_content}"
        content="${content//\{\{JS\}\}/$js_content}"
        content="${content//\{\{HEAD_SCRIPT\}\}/$head_script}"
        content="${content//\{\{TOC_ENTRIES\}\}/$toc_entries}"

        # Canonical link
        if [[ -n "$base_url" ]]; then
            content="${content//\{\{CANONICAL\}\}/<link rel=\"canonical\" href=\"${base_url}\">}"
        else
            content="${content//\{\{CANONICAL\}\}/}"
        fi

        echo "$content"
    }

    # --- Generate index.html ---
    local index_tmpl
    index_tmpl=$(cat "${template_dir}/index.html")

    # Cover image
    local cover_html=""
    if [[ -n "$cover_image" && -f "${project_dir}/${cover_image}" ]]; then
        cp "${project_dir}/${cover_image}" "${output_dir}/cover.png" 2>/dev/null || \
        cp "${project_dir}/${cover_image}" "${output_dir}/cover.jpg" 2>/dev/null || true
        local cover_ext="${cover_image##*.}"
        cover_html="<img src=\"cover.${cover_ext}\" alt=\"${title}\" class=\"book-cover\">"
    fi

    # Logline
    local logline_html=""
    if [[ -n "$logline" ]]; then
        logline_html="<p class=\"book-logline\">${logline}</p>"
    fi

    # Series
    local series_html=""
    if [[ -n "$series_name" ]]; then
        series_html="<p class=\"book-series\">${series_name}"
        if [[ -n "$series_pos" ]]; then
            series_html="${series_html} &middot; Book ${series_pos}"
        fi
        series_html="${series_html}</p>"
    fi

    # Copyright
    local copyright_html="<p class=\"book-copyright\">&copy; ${copyright_year} ${author}</p>"

    local index_content
    index_content=$(_web_sub "$index_tmpl")
    index_content="${index_content//\{\{COVER_IMG\}\}/$cover_html}"
    index_content="${index_content//\{\{LOGLINE\}\}/$logline_html}"
    index_content="${index_content//\{\{SERIES\}\}/$series_html}"
    index_content="${index_content//\{\{COPYRIGHT\}\}/$copyright_html}"
    echo "$index_content" > "${output_dir}/index.html"

    # --- Generate contents.html ---
    local toc_tmpl
    toc_tmpl=$(cat "${template_dir}/toc.html")

    # Back matter links
    local back_matter_html=""
    for bm in "acknowledgments" "about-the-author" "also-by"; do
        local bm_path
        bm_path=$(read_production_nested "$project_dir" "back_matter" "$bm" 2>/dev/null || echo "")
        if [[ -n "$bm_path" && -f "${project_dir}/${bm_path}" ]]; then
            local bm_label
            case "$bm" in
                acknowledgments) bm_label="Acknowledgments" ;;
                about-the-author) bm_label="About the Author" ;;
                also-by) bm_label="Also By" ;;
            esac
            # Back matter pages not generated yet — link to last chapter as placeholder
            back_matter_html="${back_matter_html}"
        fi
    done

    local toc_content
    toc_content=$(_web_sub "$toc_tmpl")
    toc_content="${toc_content//\{\{BACK_MATTER_LINKS\}\}/$back_matter_html}"
    echo "$toc_content" > "${output_dir}/contents.html"

    # --- Generate chapter pages ---
    local ch_tmpl
    ch_tmpl=$(cat "${template_dir}/chapter.html")

    for (( ch=1; ch<=total_chapters; ch++ )); do
        local ch_idx=$(( ch - 1 ))
        local ch_title="${ch_titles[$ch_idx]}"
        local ch_slug="${ch_slugs[$ch_idx]}"
        local ch_num_fmt
        ch_num_fmt=$(printf '%02d' "$ch")
        local ch_md="${chapters_dir}/chapter-${ch_num_fmt}.md"

        if [[ ! -f "$ch_md" ]]; then
            log "WARNING: Chapter file missing: ${ch_md}"
            continue
        fi

        # Convert chapter markdown to HTML fragment
        local ch_html_fragment
        ch_html_fragment=$(pandoc --from markdown --to html5 "$ch_md" 2>/dev/null)

        # Build prev/next links
        local prev_link=""
        local next_link=""
        if (( ch > 1 )); then
            local prev_slug
            prev_slug=$(printf 'chapter-%02d' $(( ch - 1 )))
            local prev_title="${ch_titles[$(( ch - 2 ))]}"
            prev_link="<a href=\"${prev_slug}.html\" class=\"prev-chapter nav-link\"><span class=\"nav-label\">&larr; Previous Chapter</span><span class=\"nav-chapter-title\">${prev_title}</span></a>"
        else
            prev_link="<a href=\"../contents.html\" class=\"prev-chapter nav-link\"><span class=\"nav-label\">&larr; Contents</span></a>"
        fi
        if (( ch < total_chapters )); then
            local next_slug
            next_slug=$(printf 'chapter-%02d' $(( ch + 1 )))
            local next_title="${ch_titles[$ch]}"
            next_link="<a href=\"${next_slug}.html\" class=\"next-chapter nav-link\"><span class=\"nav-label\">Next Chapter &rarr;</span><span class=\"nav-chapter-title\">${next_title}</span></a>"
        else
            next_link="<a href=\"../index.html\" class=\"next-chapter nav-link\"><span class=\"nav-label\">Finished &rarr;</span><span class=\"nav-chapter-title\">Back to cover</span></a>"
        fi

        # Substitute into chapter template
        local page_content
        page_content=$(_web_sub "$ch_tmpl")
        page_content="${page_content//\{\{CHAPTER_TITLE\}\}/$ch_title}"
        page_content="${page_content//\{\{CHAPTER_SLUG\}\}/$ch_slug}"
        page_content="${page_content//\{\{CHAPTER_NUM\}\}/$ch}"
        page_content="${page_content//\{\{CHAPTER_CONTENT\}\}/$ch_html_fragment}"
        page_content="${page_content//\{\{PREV_LINK\}\}/$prev_link}"
        page_content="${page_content//\{\{NEXT_LINK\}\}/$next_link}"

        echo "$page_content" > "${output_dir}/chapters/${ch_slug}.html"
    done

    # --- Summary ---
    local total_files=$(( total_chapters + 2 ))  # chapters + index + contents
    log "Web book generated: ${total_files} pages at ${output_dir}/"
    log "  Landing: ${output_dir}/index.html"
    log "  Contents: ${output_dir}/contents.html"
    log "  Chapters: ${output_dir}/chapters/ (${total_chapters} files)"
    return 0
}

# ============================================================================
# PDF generation
# ============================================================================

# Generate PDF from assembled manuscript
# Usage: generate_pdf "/path/to/project" "/path/to/manuscript.md" "/path/to/output.pdf" "/path/to/plugin"
generate_pdf() {
    local project_dir="$1"
    local manuscript="$2"
    local output_pdf="$3"
    local plugin_dir="$4"

    if ! check_pandoc >/dev/null 2>&1; then
        log "ERROR: pandoc is required for PDF generation but not found"
        return 1
    fi

    local title
    title=$(read_yaml_field "project.title" 2>/dev/null || read_yaml_field "title" 2>/dev/null || echo "Untitled")
    local author
    author=$(read_production_field "$project_dir" "author" 2>/dev/null || echo "")

    # Try weasyprint first, then fall back to LaTeX
    if check_weasyprint; then
        log "Running weasyprint: PDF generation..."

        local genre
        genre=$(read_yaml_field "project.genre" 2>/dev/null || echo "default")
        local css_file
        css_file=$(get_genre_css "$plugin_dir" "$genre")

        local html_tmp="${output_pdf%.pdf}.tmp.html"

        # Generate HTML first, then convert to PDF
        pandoc --from markdown --to html5 --standalone \
            --metadata "title=${title}" \
            --toc --toc-depth=1 \
            ${css_file:+--css "$css_file"} \
            -o "$html_tmp" "$manuscript"

        weasyprint "$html_tmp" "$output_pdf"
        local rc=$?
        rm -f "$html_tmp"

        if [[ $rc -ne 0 ]]; then
            log "ERROR: weasyprint failed with exit code ${rc}"
            return 1
        fi
    else
        log "Running pandoc: PDF generation (LaTeX)..."

        local pandoc_args=(
            --from markdown
            --to pdf
            --output "$output_pdf"
            --metadata "title=${title}"
            --toc
            --toc-depth=1
            -V geometry:margin=1in
            -V fontsize=11pt
        )

        if [[ -n "$author" ]]; then
            pandoc_args+=(--metadata "author=${author}")
        fi

        pandoc "${pandoc_args[@]}" "$manuscript"
        local rc=$?

        if [[ $rc -ne 0 ]]; then
            log "ERROR: pandoc PDF generation failed with exit code ${rc}"
            log "Ensure a LaTeX distribution is installed (e.g., texlive, mactex)"
            return 1
        fi
    fi

    log "PDF generated: ${output_pdf}"
    return 0
}

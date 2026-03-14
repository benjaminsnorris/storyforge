#!/bin/bash
# test-cover-assembly.sh — Tests for cover-related assembly functions
#
# Run via: ./tests/run-tests.sh
# Tests generate_cover_if_missing from scripts/lib/assembly.sh.
#
# Depends on: FIXTURE_DIR, PROJECT_DIR, PLUGIN_DIR, assertion functions (from run-tests.sh)

# ============================================================================
# Setup: temp project directory for cover tests
# ============================================================================

COVER_TEST_DIR=$(mktemp -d)
trap "rm -rf $COVER_TEST_DIR" EXIT

# Copy the fixture project so we can modify it without affecting other tests
cp -R "${FIXTURE_DIR}/" "${COVER_TEST_DIR}/"

# ============================================================================
# generate_cover_if_missing: cover already exists
# ============================================================================

# Create a fake cover PNG and set it in the chapter map
mkdir -p "${COVER_TEST_DIR}/manuscript/assets"
echo "fake-png-data" > "${COVER_TEST_DIR}/manuscript/assets/cover.png"
sed -i '' 's|^  cover_image:.*|  cover_image: "manuscript/assets/cover.png"|' "${COVER_TEST_DIR}/storyforge.yaml"

result=$(generate_cover_if_missing "$COVER_TEST_DIR" "$PLUGIN_DIR" 2>&1)
rc=$?
assert_exit_code "0" "$rc" "generate_cover_if_missing: exits 0 when cover exists"
assert_contains "$result" "Cover image found" "generate_cover_if_missing: reports existing cover"

# ============================================================================
# generate_cover_if_missing: no cover, no generator script
# ============================================================================

# Reset: remove cover and clear the config
rm -f "${COVER_TEST_DIR}/manuscript/assets/cover.png"
sed -i '' 's|^  cover_image:.*|  cover_image:|' "${COVER_TEST_DIR}/storyforge.yaml"

# Point to a non-existent cover script
result=$(generate_cover_if_missing "$COVER_TEST_DIR" "/nonexistent/plugin" 2>&1)
rc=$?
assert_exit_code "0" "$rc" "generate_cover_if_missing: exits 0 when no generator available"
assert_contains "$result" "not found" "generate_cover_if_missing: reports generator not found"

# ============================================================================
# generate_cover_if_missing: cover_image set but file missing
# ============================================================================

# Set a cover path that doesn't exist on disk
sed -i '' 's|^  cover_image:.*|  cover_image: "manuscript/assets/missing-cover.png"|' "${COVER_TEST_DIR}/storyforge.yaml"

result=$(generate_cover_if_missing "$COVER_TEST_DIR" "/nonexistent/plugin" 2>&1)
rc=$?
assert_exit_code "0" "$rc" "generate_cover_if_missing: exits 0 when cover_image points to missing file"
# Should not report "Cover image found" since the file doesn't exist
assert_not_contains "$result" "Cover image found" "generate_cover_if_missing: does not claim missing file found"

# ============================================================================
# generate_cover_if_missing: generator script fails
# ============================================================================

# Create a fake cover generator that always fails
FAKE_PLUGIN_DIR=$(mktemp -d)
trap "rm -rf $COVER_TEST_DIR $FAKE_PLUGIN_DIR" EXIT
mkdir -p "${FAKE_PLUGIN_DIR}/scripts"
cat > "${FAKE_PLUGIN_DIR}/scripts/storyforge-cover" << 'SCRIPT'
#!/bin/bash
exit 1
SCRIPT
chmod +x "${FAKE_PLUGIN_DIR}/scripts/storyforge-cover"

# Reset cover_image to empty
sed -i '' 's|^  cover_image:.*|  cover_image:|' "${COVER_TEST_DIR}/storyforge.yaml"

result=$(generate_cover_if_missing "$COVER_TEST_DIR" "$FAKE_PLUGIN_DIR" 2>&1)
rc=$?
assert_exit_code "0" "$rc" "generate_cover_if_missing: exits 0 even when generator fails"
assert_contains "$result" "Cover generation failed" "generate_cover_if_missing: reports generator failure"

# ============================================================================
# generate_cover_if_missing: generator produces no PNG
# ============================================================================

# Create a generator that succeeds but produces nothing
cat > "${FAKE_PLUGIN_DIR}/scripts/storyforge-cover" << 'SCRIPT'
#!/bin/bash
# Succeeds but doesn't create any file
exit 0
SCRIPT
chmod +x "${FAKE_PLUGIN_DIR}/scripts/storyforge-cover"

# Make sure no cover file exists
rm -f "${COVER_TEST_DIR}/manuscript/assets/cover.png"

result=$(generate_cover_if_missing "$COVER_TEST_DIR" "$FAKE_PLUGIN_DIR" 2>&1)
rc=$?
assert_exit_code "0" "$rc" "generate_cover_if_missing: exits 0 when generator produces nothing"
assert_contains "$result" "No cover PNG produced" "generate_cover_if_missing: reports missing PNG output"

# ============================================================================
# generate_cover_if_missing: generator succeeds and produces PNG
# ============================================================================

# Create a generator that produces a real file
cat > "${FAKE_PLUGIN_DIR}/scripts/storyforge-cover" << 'SCRIPT'
#!/bin/bash
# Parse --output flag
OUTPUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --output) OUTPUT="$2"; shift 2 ;;
        *) shift ;;
    esac
done
if [[ -n "$OUTPUT" ]]; then
    mkdir -p "$(dirname "$OUTPUT")"
    echo "fake-png-data" > "$OUTPUT"
fi
exit 0
SCRIPT
chmod +x "${FAKE_PLUGIN_DIR}/scripts/storyforge-cover"

# Reset cover_image to empty
sed -i '' 's|^  cover_image:.*|  cover_image:|' "${COVER_TEST_DIR}/storyforge.yaml"
rm -f "${COVER_TEST_DIR}/manuscript/assets/cover.png"

result=$(generate_cover_if_missing "$COVER_TEST_DIR" "$FAKE_PLUGIN_DIR" 2>&1)
rc=$?
assert_exit_code "0" "$rc" "generate_cover_if_missing: exits 0 when generator succeeds"

# Verify the cover file was created
assert_file_exists "${COVER_TEST_DIR}/manuscript/assets/cover.png" "generate_cover_if_missing: PNG file created"

# Verify storyforge.yaml was updated
cover_field=$(grep 'cover_image:' "${COVER_TEST_DIR}/storyforge.yaml" | head -1)
assert_contains "$cover_field" "manuscript/assets/cover.png" "generate_cover_if_missing: storyforge.yaml updated with cover path"

# ============================================================================
# Cleanup
# ============================================================================

rm -rf "$COVER_TEST_DIR" "$FAKE_PLUGIN_DIR"
trap - EXIT

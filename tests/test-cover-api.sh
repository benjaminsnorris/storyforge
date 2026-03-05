#!/bin/bash
# test-cover-api.sh — Tests for scripts/lib/cover-api.sh
#
# Run via: ./tests/run-tests.sh
# Tests API detection, base64 decoding, and function existence.
#
# Depends on: PLUGIN_DIR, assertion functions (from run-tests.sh)

# Source cover-api.sh (common.sh is already loaded by the runner)
source "${PLUGIN_DIR}/scripts/lib/cover-api.sh"

# ============================================================================
# check_image_api
# ============================================================================

# With no API keys set, should return "none"
(
    unset OPENAI_API_KEY 2>/dev/null
    unset BFL_API_KEY 2>/dev/null
    result=$(check_image_api)
    assert_equals "none" "$result" "check_image_api: returns 'none' with no keys"
)

# With OPENAI_API_KEY set, should return "openai"
(
    export OPENAI_API_KEY="sk-test-fake-key"
    unset BFL_API_KEY 2>/dev/null
    result=$(check_image_api)
    assert_equals "openai" "$result" "check_image_api: returns 'openai' with OPENAI_API_KEY"
)

# With BFL_API_KEY set (no OpenAI), should return "bfl"
(
    unset OPENAI_API_KEY 2>/dev/null
    export BFL_API_KEY="bfl-test-fake-key"
    result=$(check_image_api)
    assert_equals "bfl" "$result" "check_image_api: returns 'bfl' with BFL_API_KEY"
)

# With both keys set, OpenAI takes priority
(
    export OPENAI_API_KEY="sk-test-fake-key"
    export BFL_API_KEY="bfl-test-fake-key"
    result=$(check_image_api)
    assert_equals "openai" "$result" "check_image_api: OpenAI takes priority when both keys set"
)

# With empty OPENAI_API_KEY, should not count as set
(
    export OPENAI_API_KEY=""
    unset BFL_API_KEY 2>/dev/null
    result=$(check_image_api)
    assert_equals "none" "$result" "check_image_api: empty OPENAI_API_KEY treated as unset"
)

# With empty OPENAI_API_KEY but valid BFL_API_KEY, should return "bfl"
(
    export OPENAI_API_KEY=""
    export BFL_API_KEY="bfl-test-fake-key"
    result=$(check_image_api)
    assert_equals "bfl" "$result" "check_image_api: falls through empty OPENAI to BFL"
)

# ============================================================================
# _decode_base64
# ============================================================================

# Encode a known string, decode it, verify round-trip
original="Hello, Storyforge cover!"
if base64 --help 2>&1 | grep -q '\-D'; then
    encoded=$(echo -n "$original" | base64)
else
    encoded=$(echo -n "$original" | base64)
fi
decoded=$(echo "$encoded" | _decode_base64)
assert_equals "$original" "$decoded" "_decode_base64: round-trip encode/decode"

# Empty input should produce empty output
decoded_empty=$(echo -n "" | _decode_base64 2>/dev/null || true)
assert_empty "$decoded_empty" "_decode_base64: empty input produces empty output"

# Multi-line base64 decode
long_string="This is a longer test string that will produce multi-line base64 output when encoded for testing purposes."
encoded_long=$(echo -n "$long_string" | base64)
decoded_long=$(echo "$encoded_long" | _decode_base64)
assert_equals "$long_string" "$decoded_long" "_decode_base64: handles longer base64 strings"

# ============================================================================
# openai_generate_image — argument validation
# ============================================================================

# Should fail without OPENAI_API_KEY
(
    unset OPENAI_API_KEY 2>/dev/null
    openai_generate_image "test prompt" "/tmp/test.png" 2>/dev/null
)
assert_exit_code "1" "$?" "openai_generate_image: fails without OPENAI_API_KEY"

# ============================================================================
# bfl_generate_image — argument validation
# ============================================================================

# Should fail without BFL_API_KEY
(
    unset BFL_API_KEY 2>/dev/null
    bfl_generate_image "test prompt" "/tmp/test.png" 2>/dev/null
)
assert_exit_code "1" "$?" "bfl_generate_image: fails without BFL_API_KEY"

# ============================================================================
# Function existence checks
# ============================================================================

assert_not_empty "$(type -t check_image_api)" "check_image_api: function exists"
assert_not_empty "$(type -t _decode_base64)" "_decode_base64: function exists"
assert_not_empty "$(type -t openai_generate_image)" "openai_generate_image: function exists"
assert_not_empty "$(type -t bfl_generate_image)" "bfl_generate_image: function exists"

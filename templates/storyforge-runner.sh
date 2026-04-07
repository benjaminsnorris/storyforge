#!/usr/bin/env bash
# Storyforge — delegates to installed plugin
# Created by /storyforge:init. Do not edit.
set -euo pipefail

find_plugin() {
  # 1. Environment variable (set by claude --plugin-dir)
  if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
    echo "$CLAUDE_PLUGIN_ROOT"
    return 0
  fi
  # 2. Plugin cache (installed via marketplace)
  local cache_dir="$HOME/.claude/plugins/cache"
  if [[ -d "$cache_dir" ]]; then
    local found
    found=$(find "$cache_dir" -maxdepth 5 -name "plugin.json" \
      -path "*/storyforge/*" 2>/dev/null | sort -V | tail -1)
    if [[ -n "$found" ]]; then
      dirname "$(dirname "$found")"
      return 0
    fi
  fi
  # 3. Development checkout (common location)
  local dev_dir="$HOME/Developer/storyforge"
  if [[ -f "$dev_dir/.claude-plugin/plugin.json" ]]; then
    echo "$dev_dir"
    return 0
  fi
  echo "Error: Storyforge plugin not found." >&2
  echo "Install via: claude --plugin-dir /path/to/storyforge" >&2
  return 1
}

PLUGIN_ROOT="$(find_plugin)"

if [[ $# -eq 0 ]]; then
  exec python3 -c "import sys; sys.path.insert(0, '${PLUGIN_ROOT}/scripts/lib/python'); from storyforge.__main__ import main; main()"
fi

COMMAND="$1"
shift

case "$COMMAND" in
  test)
    exec bash "${PLUGIN_ROOT}/tests/run-tests.sh" "$@"
    ;;
  *)
    PYTHONPATH="${PLUGIN_ROOT}/scripts/lib/python" exec python3 -m storyforge "$COMMAND" "$@"
    ;;
esac

# API Migration: Autonomous Scripts to Direct Anthropic API

**Date:** 2026-03-14
**Status:** Approved

## Summary

Migrate all autonomous `claude -p` invocations to direct Anthropic Messages API calls. Batch API is the default mode (50% cost savings). Direct API available via `--direct` flag. Interactive mode stays on Claude Code sessions.

## Motivation

- **Cost:** Batch API is 50% cheaper than real-time API, which is already cheaper than Claude Code overhead
- **Speed:** Direct curl calls eliminate Claude Code startup/shutdown overhead per invocation
- **Control:** Direct API gives explicit error handling, token tracking, and response parsing
- **Future:** Lays groundwork for standalone app (no Claude Code dependency for autonomous work)

## Architecture

### New library: `scripts/lib/api.sh`

Extract general-purpose API functions from `scoring.sh` into a shared library:

```
invoke_anthropic_api(prompt, model, log_file, [max_tokens])
extract_api_response(log_file)
extract_api_usage(log_file)
log_api_usage(log_file, operation, target, model, [ledger])
submit_batch(batch_file)
poll_batch(batch_id)
download_batch_results(batch_id, output_dir)
```

`common.sh` sources `api.sh`. All scripts get API functions automatically.

### Mode selection per script

| Script | Default Mode | `--direct` | `--interactive` |
|--------|-------------|------------|-----------------|
| storyforge-write | batch | direct API (parallel) | Claude Code session |
| storyforge-evaluate | batch | direct API (parallel) | Claude Code session |
| storyforge-enrich | batch | direct API (parallel) | Claude Code session |
| storyforge-timeline (phase 1) | batch | direct API (parallel) | Claude Code session |
| storyforge-timeline (phase 2) | direct API | — | Claude Code session |
| storyforge-revise | direct API | — | Claude Code session |
| storyforge-scenes-setup | batch | direct API (parallel) | Claude Code session |

Scripts with many items default to batch. Scripts with 1-3 calls default to direct API.

### Shared function updates in `common.sh`

- `_run_headless_session` → uses `invoke_anthropic_api` + `extract_api_response`
- Healing zone recovery → uses `invoke_anthropic_api`
- `extract_claude_response` remains for interactive mode stream-json logs
- `log_usage` (stream-json) remains alongside `log_api_usage` (API JSON)

### Batch mode pattern

```bash
# 1. Build JSONL batch file (one request per line)
for id in "${IDS[@]}"; do
    prompt=$(build_prompt "$id")
    jq -nc --arg id "$id" --arg model "$MODEL" --arg prompt "$prompt" '{
        custom_id: $id,
        params: { model: $model, max_tokens: 4096, messages: [{role: "user", content: $prompt}] }
    }' >> "$BATCH_FILE"
done

# 2. Submit batch
batch_id=$(submit_batch "$BATCH_FILE")

# 3. Poll until complete
poll_batch "$batch_id"

# 4. Download and parse results
download_batch_results "$batch_id" "$RESULTS_DIR"
for result_file in "$RESULTS_DIR"/*.json; do
    id=$(jq -r '.custom_id' "$result_file")
    # Parse response specific to this script's needs
done
```

### Direct API pattern

```bash
invoke_anthropic_api "$prompt" "$MODEL" "$log_file" 4096
response=$(extract_api_response "$log_file")
log_api_usage "$log_file" "operation" "$target" "$MODEL"
```

## What doesn't change

- Interactive mode code paths (keep `claude -p` with `--append-system-prompt`)
- Argument parsing, branch/PR workflow, progress monitors
- Cost estimation formulas (batch mode applies 50% discount)
- Response parsing logic (same text, different log format)

## Environment

- `ANTHROPIC_API_KEY` — required for all autonomous runs (scripts check and error early)
- `STORYFORGE_MODEL` — override model (unchanged)
- All existing env vars remain

## Implementation order

1. Extract `api.sh` from `scoring.sh` with batch helper functions
2. Update `common.sh` (`_run_headless_session`, healing zone)
3. Convert `storyforge-enrich` (simplest parallel pattern)
4. Convert `storyforge-timeline` (two phases, different modes)
5. Convert `storyforge-scenes-setup` (simple batch)
6. Convert `storyforge-evaluate` (parallel + synthesis)
7. Convert `storyforge-write` (creative, needs careful testing)
8. Convert `storyforge-revise` (complex revision pass system)
9. Update `storyforge-score` to source shared `api.sh`
10. Add tests for `api.sh` functions

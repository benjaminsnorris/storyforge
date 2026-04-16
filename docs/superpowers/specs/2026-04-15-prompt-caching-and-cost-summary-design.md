# Prompt Caching and Cost Summary Improvements

## Problem

Storyforge's API layer sends every request with the full prompt from scratch. Across a typical pipeline run (50+ API calls), 40-60% of input tokens are shared reference material (craft engine, voice guide, character bible, registries) that gets re-sent identically on every call. This wastes money and time.

Additionally, the cost summary shown after autonomous passes (`print_summary`) reports cumulative totals across all sessions, not the current session. The user sees "$96.96" and thinks this run cost $97, when it actually cost $21.50 and $97 is the all-time total.

## Scope

Two changes:

1. **Prompt caching** — use Anthropic's `system` parameter with `cache_control` blocks to cache shared project context across API calls (batch and direct).
2. **Cost summary** — show per-session and cumulative totals after each autonomous pass, with human-readable time formatting.

## Design

### 1. Shared Context Helper

A new function in `common.py`:

```python
def build_shared_context(project_dir: str, model: str = '') -> list[dict]:
```

Assembles project-level reference materials into an ordered list of system content blocks. The ordering is fixed so the cache prefix is stable across calls.

**Two-tier structure with separate cache breakpoints:**

**Tier 1 — Near-permanent** (TTL: 1 hour, cache creation cost 2x base):
- Craft engine (sections 2-5 from `references/craft-engine.md` or project override)
- Scoring rubrics (from `references/`)
- AI-tell vocabulary (`references/ai-tell-words.csv`)
- Schema definitions

These change only when the plugin is updated. The 1h TTL means a `score` run followed by a `revise` run 20 minutes later still hits cache on this tier.

**Tier 2 — Session-stable** (TTL: 5 minutes, cache creation cost 1.25x base):
- Character bible (`reference/character-bible.md`)
- World bible (`reference/world-bible.md`)
- Voice guide (`reference/voice-guide.md`)
- Voice profile CSV (`reference/voice-profile.csv`)
- Registries: characters, locations, MICE threads (from `reference/` CSVs)

These are stable within a session but may evolve between sessions as the author works.

**Cache breakpoint placement:** The last block in each tier gets `cache_control: {"type": "ephemeral", "ttl": "1h"}` (tier 1) or `cache_control: {"type": "ephemeral"}` (tier 2, default 5m). This creates two cache breakpoints — the API caches the prefix up to each independently.

**Minimum token threshold:** Each breakpoint requires a minimum token count (4,096 for Opus, 2,048 for Sonnet). If a tier's total content is below the threshold, its `cache_control` is omitted and the content simply flows into the next tier's prefix. The function accepts a `model` parameter to determine the threshold.

**Missing files:** Silently skipped. Not every project has every reference file.

**In-process caching:** The assembled blocks are cached in a module-level variable so repeated calls within the same process don't re-read files from disk.

### 2. API Layer Changes

#### `invoke()` — new `system` parameter

```python
def invoke(prompt: str, model: str, max_tokens: int = 4096, label: str = '',
           timeout: int = API_TIMEOUT, system: list[dict] | None = None) -> dict:
```

When `system` is provided, the request body includes it:

```python
body = {
    'model': model,
    'max_tokens': max_tokens,
    'system': system,
    'messages': [{'role': 'user', 'content': prompt}],
}
```

When `system` is `None` (default), the `system` key is omitted entirely. All existing callers work without modification.

`invoke_to_file()` and `invoke_api()` pass `system` through to `invoke()`.

#### `build_batch_request()` — new helper

```python
def build_batch_request(custom_id: str, prompt: str, model: str,
                        max_tokens: int = 4096,
                        system: list[dict] | None = None) -> dict:
    """Build a single batch request item (one JSONL line)."""
    params = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': [{'role': 'user', 'content': prompt}],
    }
    if system:
        params['system'] = system
    return {'custom_id': custom_id, 'params': params}
```

Replaces the inline dict construction currently copy-pasted across 6+ command modules. Each batch item gets the same `system` blocks, so the API caches the prefix once and reads it for all subsequent items.

### 3. Command Module Integration

Each command module changes to:

1. Call `build_shared_context(project_dir)` once before the batch/loop.
2. Use `build_batch_request()` instead of inline dict construction.
3. Pass `system` to `invoke_to_file()` for direct API calls.

**Prompt builders stop inlining shared material.** Each builder currently reads craft engine, voice guide, etc. and concatenates them into the prompt string. Those sections are removed — the content now arrives via the `system` parameter.

**Affected prompt builder modules:**
- `prompts.py` — remove: craft engine, voice guide, character/world bible inlining
- `prompts_elaborate.py` — remove: craft principles, existing refs (architecture, bibles, voice guide)
- `revision.py` — remove: craft rubric, voice guide, exemplars
- `scoring.py` — remove: craft rules, voice guide
- `extract.py` — remove: registries, craft definitions
- `hone.py` — remove: registries

Each builder retains its per-item content: scene brief, prose, metadata, pass-specific instructions, continuity dependencies.

**Command modules affected:**
- `cmd_write.py` — batch construction loop
- `cmd_score.py` — craft cycle batch + fidelity batch
- `cmd_evaluate.py` — eval batch
- `cmd_extract.py` — 3 extraction phase batches
- `cmd_revise.py` — direct invoke per scene per pass
- `cmd_elaborate.py` — direct invoke per stage + gap-fill batch
- `cmd_hone.py` — direct invoke calls
- `cmd_enrich.py` — per-domain batches
- `cmd_timeline.py` — direct + batch calls
- `cmd_scenes_setup.py` — batch calls

### 4. Cost Summary Improvements

#### Human-readable time formatting

New helper in `costs.py`:

```python
def format_duration(seconds: int) -> str:
    """Format seconds as Xh Xm Xs, omitting zero leading components."""
```

- `27888` -> `7h 44m 48s`
- `180` -> `3m 0s`
- `45` -> `45s`
- `0` -> `0s`

#### Session-scoped summaries

`print_summary` gains an optional `session_start` parameter:

```python
def print_summary(project_dir: str, operation: str | None = None,
                  session_start: str | None = None) -> None:
```

When `session_start` is provided (ISO timestamp string), the function makes two passes over the ledger:

1. **This session** — rows where `timestamp >= session_start` and operation matches
2. **Project total** — all rows where operation matches

Output format:

```
--- This session: revise (6 invocations) ---
Input tokens:  521,340
Output tokens: 98,201
Cache read:    412,800
Cache create:  108,540
Cost:          $14.22
Time:          57m 0s

--- Project total: revise (50 invocations) ---
Input tokens:  4,339,621
Output tokens: 823,482
Cache read:    412,800
Cache create:  108,540
Cost:          $89.52
Time:          7h 44m 48s
```

Each command module records its start time (`datetime.now().strftime('%Y-%m-%dT%H:%M:%S')`) at the top of `main()` and passes it to `print_summary` at the end.

Callers that don't pass `session_start` get the current behavior (cumulative only) — backward compatible.

### 5. Testing

All in `tests/test_prompt_caching.py` and extended `tests/test_costs.py`.

**`build_shared_context()` tests:**
- Returns correct two-tier block structure with `cache_control` on breakpoint blocks
- Skips missing reference files without error
- Fixed ordering produces identical output across calls
- In-process cache returns same object on second call
- Tier merging when content is below minimum token threshold

**`build_batch_request()` tests:**
- Includes `system` in params when provided
- Omits `system` key entirely when `None`
- Correct JSONL structure (custom_id, params with model/max_tokens/messages)

**`format_duration()` tests:**
- `0` -> `0s`
- `45` -> `45s`
- `180` -> `3m 0s`
- `3661` -> `1h 1m 1s`
- `27888` -> `7h 44m 48s`

**`print_summary` with `session_start` tests:**
- Filters correctly: only rows after session_start in session section
- Shows all rows in project total section
- Works without `session_start` (backward compatible)
- Handles empty ledger, no matching operation

**Request shape tests:**
- `invoke()` with `system` builds body with `system` key
- `invoke()` without `system` builds body without `system` key
- Batch JSONL file with system blocks is valid JSON per line

No tests for actual cache hit behavior — that's Anthropic's responsibility.

## Non-goals

- Changing the Batch API submission flow (`submit_batch` / `poll_batch` / `download_batch_results`)
- Per-command customization of which reference files are cached (all commands get the same shared context)
- Prompt caching for the CLI interface (`python3 -m storyforge.api invoke`)
- Changes to the ledger CSV schema

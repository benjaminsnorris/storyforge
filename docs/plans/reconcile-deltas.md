# Registry reconcile by deltas

Status: approved design, not yet implemented (finding F-026 in
`benjaminsnorris/storyforge-evals`).

## Problem

`hone.reconcile_domain` rebuilds a registry by asking the model to **re-emit
the whole registry plus an `UPDATE` line per scene, in one response**. Output
grows with scenes × entities, so the call has a size limit the book can exceed:

- *The Great Gatsby* (48k words, 40 scenes): the knowledge reconcile overflowed
  its 4,096-token budget, stopped partway through the registry, and applied
  none of its UPDATEs. A stopgap raised knowledge and physical states to 16,000
  tokens, and one call then took more than 2 minutes.
- Characters, locations, values and MICE threads still run at 4,096. A long
  novel, or a large cast (*War and Peace*), would truncate any of them. Since
  `a8f0e9b` a truncated response keeps the existing registry rather than
  wiping it, but the new references in it are then never resolved.

No call's output should grow with the book.

## Design

### 1. Only unresolved references go to the model

For each domain, collect the references in its target columns
(`_DOMAIN_TARGETS`) that don't resolve through the current alias map
(`find_unresolved`). If there are none, make **no API call**, so a
re-run on a reconciled project costs nothing.

### 2. The model returns changes in batches, and code applies them

Send the unresolved references in fixed-size numbered batches (start at ~60).
Each prompt includes the current registry (id + name + the domain's key
columns) and the domain's rules, plus the scenes each reference appears in for
disambiguation. One output line per reference:

```
N | id                      existing entry; the reference becomes its alias
N | id1;id2                 a composite reference (e.g. a route) → several entries
N | NEW | id | <fields>     a new entry; the reference becomes its alias
N | SKIP                    not an entity (placeholder, noise); left for reporting
```

Code applies each batch before the next, so later batches see new entries:
add rows, add aliases (single-id mappings only), and rewrite the target fields
through the mapping (preserving MICE `+`/`-` prefixes). Then
`apply_registry_normalization`. Output per call is bounded by the batch size,
not the book.

Fields per domain for `NEW` lines (derived columns are filled by code):

| domain | NEW fields | derived by code |
|---|---|---|
| characters | name, role | — |
| locations | name | — |
| values | name | — |
| mice-threads | name, type | — |
| knowledge | name, category | origin = first scene with it in `knowledge_out`, else `backstory` |
| physical-states | character (id), description, category, action_gating | acquired = first scene with it in `physical_state_out`; resolves = `never` |

The existing numbered knowledge mapping pass (`resolve_unresolved_knowledge`)
is this protocol for one domain. Generalize it and retire the full-rebuild
path (`build_registry_prompt` / `parse_registry_response` / `apply_updates` and
the retry block in `reconcile_domain`). `reconcile.py` re-exports these, so
keep the names working or update the callers.

### 3. MICE operations are decided per thread

The full rebuild also normalized MICE operations through per-scene UPDATEs.
Instead, find only the threads whose operations are anomalous (opened more than
once, closed more than once, closed without being opened) and send those in
batches with their timeline and scene functions. One line per thread:

```
thread | open_scene | close_scene-or-UNCLOSED
```

Code then rewrites the thread's operations: `+` at the open scene, `-` at the
close scene, a bare mention everywhere else. Output is one line per anomalous
thread.

### 4. Shared aliases

Resolve them deterministically: an alias stays with the entry whose id or name
equals it, otherwise with the first entry, and each move is logged. No call is
needed.

### 5. Every call checks for truncation

Wrap `invoke_to_file` for hone. If `stop_reason == 'max_tokens'`, log a WARNING
naming the batch and leave that batch's references unresolved (never apply a
partial batch's NEW rows). Apply the same check to the other one-shot calls
that grow with the book (the phase 0 characterization, the evaluation panels)
so a cut-off response is never silent.

## Verification

- Tests: mock the API per batch (as `tests/test_hone.py` does). Cover the
  no-unresolved → no-call case, multi-batch application order, composite
  mapping, NEW-row derived columns, SKIP reporting, the MICE per-thread rewrite,
  and truncation leaving the batch unresolved.
- On the evals corpus: re-run phases 1–3 + hone on *The Great Gatsby* and
  compare registry sizes and unresolved counts with the current output (the
  knowledge result to beat is 0 of 564 entries unresolved). Then run a long
  novel (*Middlemarch*, ~316k words) end to end as the stress test.

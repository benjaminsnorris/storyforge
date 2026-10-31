# Phase 4: safe revision — design

Date: 2026-10-31. Rethink plan §3.4 and §5 Phase 4; status doc Next steps item 4. **Decided by Ben, 2026-10-31:** the three decisions at the end, each as recommended (derived graph; a failing re-check reports and stops; forecast and run under the threshold).

## What Phase 4 must deliver (plan)

- A dependency graph, a **re-check set** after any edit, a rewrite-from-ledger command, and the reject-fact flow in the audit.
- Success: E5 on rewritten scenes ≤ the Phase 2 level; a rejected fact produces the correct re-check set on E1 cases; **E8 errors introduced per pass is zero** on the labeled set.

## Where things stand (v1.113.0)

- **`depends_on` is never written.** The column exists (plan §3.1), but no extraction, gate or hone path fills it. The only links between facts are `supersedes` (a later state replaces an earlier one) and `resolves` (where a state ends, set on the earlier row by a later scene's `ends`).
- **A redraft is refused when a later fact leans on the scene** (`gate._leaning_on`: a later row's `supersedes` or `depends_on` names one of the scene's commitments). That is the block E5 hit and the one phase 4 on the seven books would create everywhere: once every scene has commitments, almost every mid-book redraft is refused.
- **A later scene's `ends` on this scene's state is lost on a redraft.** The `resolves` the later scene set lives on the row the redraft replaces; the new row has none, so the state reads as in force for the rest of the book. Today this can't happen only because the leaning check refuses first (`resolves` isn't in `_leaning_on`, so it can: a gap to close with this work).
- **Rejected facts are still used.** `audit --mark rejected` sets `status`, but the typed views don't filter on it, so drafting and hone keep reading them (status doc, open follow-ups). `audit.leaning_scenes` lists the scenes whose brief names a rejected registry fact; nothing re-checks them.
- **Prose passes other than redraft are ungated** (polish, naturalness, continuity-audit): E8's reintroductions come from these families as well as redraft-from-brief.

## Proposal

### 1. The graph is derived, not extracted

A scene **depends on** an earlier fact when one of its binding facts links to it (`supersedes`, or the earlier row's `resolves` names this scene), or when one of its binding facts has the same `subject` and `type` as the earlier fact (the scene says something about the same person or thing in the same respect). Computed from the ledger on demand (`ledger.dependents(rows, fact_ids, order)` → later scene ids in reading order); nothing new is stored.

Why not have extraction fill `depends_on`: it is a prompt change to phase 4 and the gate (re-records E3, E4, E5, E8), it asks the extraction model for a judgement it would make inconsistently (which earlier facts a sentence "relies on"), and a missed link is a silent hole in the re-check set. The subject/type overlap over-includes, which costs checks but never skips a scene that could break. `depends_on` stays in the schema for hand-written links (an author can name one) and is honoured by the same function.

### 2. What changed

After a scene's prose changes and passes the gate, its **changed facts** are the old commitments with no new commitment of the same `subject`, `type` and normalized `statement`, plus the new commitments with no old match. Registry facts don't change on a redraft (the gate never writes them, except a blank quote). A rejected fact is a changed fact.

### 3. The re-check

For the changed facts, take the dependents in reading order and **re-gate each later scene's existing prose** (`gate_scene` with a new command, `recheck`): extract its commitments again against the new ledger (so its `supersedes`/`ends` link to the new ids), ask the persistence question, check it, and commit if clean. A scene whose re-extracted facts equal its old ones (same match as §2) ends the cascade on that branch; one whose facts changed adds its own dependents.

- **The redraft itself is no longer refused** for leaning facts: the re-check replaces the refusal. The leaning rows are replaced when their scene is re-gated, so no link is left dangling once the re-check finishes.
- **Order:** the redrafted scene commits first, then each dependent in reading order, one at a time (each sees the ledger the earlier ones left).
- **From PR 1's review, for this step:** skip dependents with no prose yet (`gate_scene` raises on them); report `Dependents.unrelated` (a fact with no subject and no link, such as a knowledge registry fact) rather than skip it silently; compare `ledger.ended_by` before and after each re-gate (a scene that no longer ends an earlier state changed it); and carry links by the old-to-new fact match, not by id (`extract.commitment_id` uses six words, so ids can swap between two similar facts).
- **Built in PR 2 (#468):** only the scene's earlier facts that were dropped or changed, and earlier states whose end in the scene came or went, list dependents; a fact new to the scene lists none (its own check reads it against later scenes; otherwise the first gate on any scene of a book without commitments would re-check the rest of the book). Unchanged facts keep their ids and later ends.
- **Atomicity:** the ledger is consistent after each step, not only at the end. A run interrupted mid-cascade leaves the remaining dependents listed in `working/gate-pending.csv` with the reason "re-check after {scene}", and `write`/`revise` refuse to draft past a pending scene, as today.

### 4. Reject-fact flow

`storyforge audit --mark rejected <id>`:
- the typed views and `extract.known_for_scene` leave non-binding rows out (the open follow-up), so nothing drafts from a rejected fact;
- the fact's dependents (§1) are listed pending with "re-check: {id} rejected", and `storyforge check --pending` re-gates them in reading order (§3, advisor mode: reports, never edits).
- **Built in PR 3a (#470):** `audit --mark rejected` lists the dependents (and the briefs naming the fact) for a re-check and names the fact's own scene for the author; drafting's entering-states block and the must-show checklist leave non-binding states out with a WARNING; `validate` reports a brief naming a rejected, superseded or pending fact. **Not done:** the typed views still include non-binding rows, because writers (hone, extract 3b/3c, enrich) read a view and write it back, and a view without a rejected row would delete it; readers that need binding facts filter on `status` themselves (drafting, checker, `known_for_scene`, `drafting_slice`). Scoring and visualization still read the full view.
- Measured on E1 cases: each case's established fact, rejected, must yield a re-check set that contains the scene where the error was introduced.

### 5. Every prose pass through the gate

Polish, naturalness and continuity-audit passes go through `gate.gate_and_fix` per scene, in reading order, as redraft-from-brief does since #456, followed by the re-check for each scene whose facts changed. E8 measures it (its target is zero reintroduced).

### 6. Rewrite-from-ledger

`revise`'s redraft-from-brief already drafts from the brief, the ledger slice and the earlier prose. "Rewrite-from-ledger" adds the scene's own binding commitments to the prompt as facts to keep (they are in the "Established in this scene so far" block today) and sends the old prose as voice reference only (plan §3.4). Small; it rides on the E5 measurement.

## Cost

A re-gate is about one extraction (Sonnet), one persistence call and one check (Opus, now with the story so far cached): roughly $0.40–0.60 a scene on shared-dark-sized scenes. A redraft early in a book with many shared subjects can pull in most later scenes. Each run forecasts the re-check set and its cost before spending, through `check_threshold` like `write`.

## PRs, in order

1. `ledger.dependents` and changed facts (§1–2), no model calls; tests on fixtures. Close the `resolves` gap in `_leaning_on` meanwhile.
2. The re-check (§3) in `gate`, used by `write --force` and revise's redrafts in place of the refusal; E5 and E8 re-recorded (E5's redraft gated again).
3. Reject flow (§4): views filter on status; `audit --mark rejected` lists dependents; `check --pending`. A new E1-based eval for the re-check set.
4. Prose passes through the gate (§5); E8.
5. Rewrite-from-ledger (§6); E5.

## Decisions (Ben, 2026-10-31: each as recommended)

1. **The graph: derived from the ledger (recommended) or extracted into `depends_on`.** Derived over-includes (more checks, never a missed scene) and needs no prompt change; extracted is tighter but costs a re-record of E3/E4/E5/E8 and trusts a model judgement for completeness.
2. **A later scene that fails its re-check: report and stop (recommended), or fix it.** Report-and-stop lists it pending with the findings and edits no prose the author didn't ask to change; the author fixes it with `revise` or by hand. Fixing it automatically would change scenes nobody chose to revise.
3. **The cost guard: forecast and run under the threshold (recommended), or always ask.** `write` already asks above `check_threshold`; the re-check would do the same with its own forecast.

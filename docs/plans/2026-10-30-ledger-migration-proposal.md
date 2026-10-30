# Ledger migration: proposed mapping and the decisions it needs

Written overnight on 2026-10-30, at the start of plan chunk 6 (Phase 2). Phase 1 is done. This doc is for Ben: it proposes how `knowledge.csv` and `physical-states.csv` map into `commitments.csv` and lists the decisions the mapping needs before any code changes author data. No code has been written for it yet.

## Why stop here

Plan §3.1 decides the migration (`knowledge.csv` and `physical-states.csv` move into `commitments.csv`, verified by round-tripping the old files out of the new one, no compatibility layer). Its column list doesn't hold everything the two files carry, though, so a lossless round trip needs schema choices the plan doesn't make:

| Old column | Holds | Has a place in §3.1's `commitments.csv`? |
|---|---|---|
| knowledge `aliases` | `;`-separated rewordings, used to match `knowledge_in` / `knowledge_out` wording | no |
| knowledge `category` | identity, state-change, capability-constraint, motive-intent, relationship-shift, stakes-threat (slipform: conspiracy, personal, relationship, tactical) | no (`type` is coarser) |
| knowledge `origin` | the scene id where the fact is established | yes, as `scene_id`; §3.1's `origin` means something else (`plan` / `prose` / `author`) |
| physical `category` | ability, appearance, equipment, fatigue, injury | no |
| physical `resolves` | the scene where the state ends, or `never` | only by inventing a superseding row's text |
| physical `action_gating` | `true` / `false` | no |
| physical `character` | a character's **name** (not an id) | `subject` wants a canonical id |

Every consumer also changes in the same step (no compatibility layer). That is 15 modules: extract, cmd_extract, hone, elaborate, schema, prompts, prompts_elaborate, enrich, cmd_enrich, revision, structural, cmd_cleanup, cmd_validate, visualize and cmd_migrate. It also changes prompt text that embeds the registries, so E2, E3, E5 and E8 would need re-recording (about $20 at today's prices). Changing what the author's files hold and spending on re-records are both calls Ben makes.

## What the books hold (read-only survey, 2026-10-30)

| Repo | knowledge rows | physical rows | Quirks |
|---|---|---|---|
| shared-dark | 37 | 103 | 3 knowledge `origin`s aren't scene ids (`burnside`, `playground`, `site-review`: renamed scenes, mappable through E1's id maps) |
| thornwall | 50 | 85 | 16 physical rows name `Garren`, who isn't in `characters.csv` |
| lantern-folk | 15 | none | extra `fact` column holds the statement; `name`, `aliases`, `category` and `origin` are all empty |
| governor | 75 | 98 | 1 duplicate knowledge id; 1 blank `origin`; 9 physical rows name `governor`, not a registry character |
| meridian-line | 70 | 102 | 4 `origin = backstory` (facts true before scene 1) |
| understory | 46 | 6 | the header has leading whitespace (`    id`); `name` holds a slug and `aliases` hold the statement's wording |
| slipform | 33 | 0 | its own category set |

Everywhere else the data is clean. Every physical `acquired` is a scene id, every `resolves` is a scene id or `never`, and knowledge and physical ids never collide within a repo. No `characters.csv` has `pronouns` yet. There is no eighth repo with these files (plan chunk 6 says "all eight"; `ashes` has no `reference/`).

## Proposed mapping

**Add four columns to §3.1's list** so nothing is lost, rather than encode them into other fields:
- `category`: the old files' category, as is;
- `aliases`;
- `resolves`: the scene where a `state` ends, or `never`;
- `action_gating`.

`resolves` stays a column rather than becoming a superseding row, because a superseding row would need a statement nobody wrote. Phase 3's gate can write real superseding rows later.

| commitments column | from knowledge.csv | from physical-states.csv |
|---|---|---|
| `id` | `id` (kept, so `knowledge_in` / `knowledge_out` in briefs stay valid) | `id` (kept, for `physical_state_in` / `physical_state_out`) |
| `scene_id` | `origin`; renamed scenes through the id maps; `backstory` and blank stay blank and are reported | `acquired` |
| `type` | `knowledge` | `physical` |
| `subject` | blank (a knowledge fact has no single subject; `known_by` carries who) | `character` resolved to its `characters.csv` id; an unresolved name (`Garren`, `governor`) is reported, never guessed |
| `statement` | `name` (lantern-folk: `fact`; understory: the first alias, since `name` is a slug there, to confirm) | `description` |
| `quote` | blank | blank |
| `origin` | `migrated` (new value: we can't tell plan from prose after the fact) | `migrated` |
| `status` | `binding` | `binding` |
| `mutable` | `state` | `state` |
| `known_by` | blank (the briefs' `knowledge_out` per scene could derive it; that's an inference, so it's left for the gate) | blank |
| `supersedes`, `depends_on` | blank | blank |
| `reviewed` | blank | blank |
| `introduced_by` | `migration` | `migration` |
| `category`, `aliases` | as is | `category` as is, `aliases` blank |
| `resolves`, `action_gating` | blank | as is |

**Round trip:** the migration writes `commitments.csv` and checks that `knowledge.csv` and `physical-states.csv` regenerate byte-for-byte from it before removing them. Two exceptions, reported rather than silently lost: understory's header whitespace, and governor's duplicate id. The check runs on a copy of each book repo; nothing is committed to a book repo by the tooling.

## Decisions for Ben

1. **The four extra columns** (`category`, `aliases`, `resolves`, `action_gating`), or another place for them.
2. **`origin` value for migrated rows:** `migrated`, or one of plan / prose / author.
3. **Unresolved physical `character` names** (thornwall's Garren, governor's `governor`): add them to `characters.csv`, or leave `subject` blank and report?
4. **understory's knowledge rows:** take the statement from the first alias? Its `name` column holds slugs.
5. **Facts with no scene** (`backstory`, blank): blank `scene_id`, or a sentinel such as `before`?
6. **Re-record budget** for E2, E3, E5 and E8 once consumers switch (about $20).
7. **Order:** migrate the schema and consumers in one PR (the plan's "no compatibility layer"), or land `ledger.py` (read, write, validate, derive per-character state) and the migration first, with consumers switching in a second PR before the old files are deleted.

Recommendation for 7: two PRs. The first adds `ledger.py`, the migration and its round-trip test (no consumer, prompt or author-data change). The second switches the 15 modules, re-records, and runs the migration on the books.

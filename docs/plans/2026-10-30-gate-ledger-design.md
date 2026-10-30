# The gate and the ledger: registry facts and commitments

Date: 2026-10-30. Phase 3, step 1 (`docs/plans/2026-10-28-rethink-status.md`, Next steps 1). **Decided by Ben, 2026-10-30:** two roles in one ledger, and the gate fills a confirmed registry fact's blank `quote`.

## The question

`reference/commitments.csv` holds two kinds of binding rows:

- **Registry facts** (`introduced_by` `extract`, `hone`, `migration`, or blank for a hand-added row). Briefs name them by id in `knowledge_in/out` and `physical_state_in/out`. The typed views (`ledger.knowledge_view` / `physical_view`) are these rows. None in the seven books has a quote.
- **Commitments** (extract phase 4, `introduced_by=commitments`). Every rubric fact, all seven types, each with a quote. Briefs can't name them; the views leave them out.

The gate (plan §3.2) must know what it checks a scene against and what it writes. F-128 already stops phase 4 restating a registry fact recorded for the scene; it doesn't say which kind is the truth.

## Decision: two roles, one ledger

The registry is the **plan's vocabulary**: the facts a brief promises, by id. Commitments are **what the prose said**. Neither becomes a view over the other, and no author data is migrated.

**What the gate checks against:**
- **Every binding fact in force entering the scene**, both kinds: earlier scenes' facts and backstory, not superseded, no `state` whose `resolves` scene is past (the rule `cmd_extract._phase4_known` uses). The checker reaches them by tool, by subject, scene and type, so there is no 200-fact cap.
- **The brief's promises.** `knowledge_in` / `physical_state_in` hold entering the scene, and the prose must not contradict them. `knowledge_out` / `physical_state_out` name registry facts the prose must establish: one it doesn't establish is a **broken promise**, reported by code with the registry id. The brief's outcome, key actions and key dialogue are promises too (the same items E4's judge counts as BPS); interpretive fields (emotions, motifs, subtext) are not.

**What halts (decision 2's immediate tier):**
- `audit.halting_conditions` on the proposed commitments: one supersedes or changes a binding `fixed` fact, or extraction flagged it low-confidence.
- **A contradiction with the plan**, which `halting_conditions` can't see: a proposed commitment that supersedes or contradicts a registry fact recorded for this scene or in force entering it. Phase 4 reports this today (its `disagrees` and `ends registry` WARNINGs); the gate halts on it instead. The checker's contradictions with any binding fact are the same tier.

**What the gate writes:**
- **Commitments only**, as binding rows with their quotes, through `ledger.save(…, command=)`, so each is in the audit log. `introduced_by` is the command that wrote the prose (`draft`, `redraft`, `revise`, …; plan §3.1), not `commitments`.
- **The quote of a confirmed registry fact.** When the checker finds the prose establishes a brief's `knowledge_out` / `physical_state_out` fact, the gate writes the establishing sentence into that registry row's `quote` **if the cell is blank**. It never overwrites a quote, and changes no other cell of a registry row. That is the only author-data change: registry rows gain evidence, and a registry fact with a quote is one the prose is known to have kept.
- **No restatements.** The commitment that establishes a registry fact is not written as a second row (phase 4's `recorded` rule). Registry rows stay the writers' they are today: extract 3b/3c, hone and the author.

## What changes in code

- **Telling the two apart.** Today a commitment is `introduced_by == ledger.COMMITMENTS_PASS`, which `ledger._in_view`, `extract.build_commitments_prompt` (the `, registry` mark), `cmd_extract._phase4_known` and `schema.py`'s owner check test. Gate rows carry the drafting command instead, so that test becomes membership in a named set, `ledger.COMMITMENT_WRITERS` (`commitments` plus the gate's commands), behind one helper `ledger.is_commitment(row)`. A blank `introduced_by` stays a registry row, so a hand-added registry fact still reaches the views.
- **Halting on the plan.** A `plan-contradiction` kind beside `audit.HALT_KINDS`, raised by the gate from the checker's findings and from extraction's `supersedes` / `ends` naming a registry fact.
- **Writing a quote.** A small ledger function that sets a blank `quote` on a registry row by id and refuses anything else (a non-blank quote, a commitment row, an unknown id), saved through `ledger.save` so the audit log shows it as `changed`.

## Rejected alternatives

- **Commitments as the source, the registry a view over them.** Briefs could name any commitment. It migrates author data in all seven books, puts hundreds of incidental rows (Carol: 42% of phase 4's rows) into the vocabulary hone and enrich match briefs against, and gains nothing until briefs are written from commitments (Phase 4's rewrite-from-ledger). Revisit then.
- **The gate writes both.** Recreating a registry row for every knowledge or physical commitment is the restatement F-128 removed: two rows per fact that can drift apart.

## Not decided here

- Whether the checker reports prose that **pre-empts a later brief** (a character learns in scene 5 what scene 9's `knowledge_out` gives them). It's a plan contradiction in spirit, but needs the later scenes' briefs; left for the checker's evaluation on E2.
- Advisor mode (`--advisor` or the coaching level) and whether batch mode stays: steps 3 and 4.

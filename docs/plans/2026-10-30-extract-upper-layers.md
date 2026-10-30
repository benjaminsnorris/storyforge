# Extract the upper reference layers (#440, F-130 part 2)

Status: plan approved 2026-10-30. PR 0 is #442 (groundwork and review fixes); PR 1 (5a/5b) is in progress. Written 2026-10-30 at v1.99.x, on branch `storyforge/extract-upper-layers-20261030-1525`.

## Goal

Start from a finished book and end with every file a Storyforge project normally has, each describing the book as written. Two reasons:

1. An extracted book can then be elaborated, scored at every level (L0–L6 floors, story-power, bible consistency) and revised the same way as a book built from a seed.
2. Famous books become a validation set for the plugin. If Storyforge can describe *Gatsby* well, judged against the text and the critical consensus, and the scorers rate *Gatsby*'s structure highly, that's evidence the rubrics measure quality. If they don't, we've found a scorer problem, not a writer problem.

## Where things are today (verified on this branch)

**What extraction writes:** `scenes.csv`, `scene-intent.csv`, `scene-briefs.csv`, the registries (`characters`, `locations`, `values`, `mice-threads`), `commitments.csv`, and `working/extraction-profile.json`. Phases 0–4 are in `cmd_extract.py`; prompts and parsers are in `extract.py`.

**What extraction leaves as the template** (what init copied in):

| File | Who reads it | Notes |
|---|---|---|
| `story-summary.md` | `scoring_levels` (L0–L2 floors), `scoring_story_power`, `scoring_coverage`, `cmd_illustrate` | Parsed by `common.parse_story_summary` (four `##` sections plus `_updated` frontmatter) |
| `story-architecture.md` | `cmd_score`, `cmd_evaluate`, `prompts_elaborate` | Read whole |
| `character-bible.md` | `cmd_score`, `scoring_bible`, `hone`, `prompts`, and `common.build_shared_context`, so **every drafting, revision and scoring call** | Read whole |
| `world-bible.md` | `scoring_bible`, `common.build_shared_context`, GN prompts | Read whole |
| `voice-guide.md` | `prompts`, `scoring`, `revision`, `hone`, `cmd_evaluate`, `scoring_bible` | Read whole |
| `voice-profile.csv` | `prompts`, `prompts_elaborate`, `common.build_shared_context`, GN | **Missing from the issue's table.** Elaborate's voice stage writes it next to the voice guide |
| `spine.csv`, `architecture.csv` | `scoring_levels` (L3/L4: 5–10 and 15–25 rows, summaries), `status`, `scoring_story_power`, `scoring_boundary`, `scoring_consistency`, `cmd_sync`, `illustrations` | Header only |
| `themes.csv` | `schema` (the `theme_threads` registry), `elaborate`, `cmd_illustrate` | Header only, and no scene has `theme_threads` |
| `motif-taxonomy.csv` | `enrich`, `cleanup`, `canon`, `illustrations`, `visualize`, `export` | Header only, while briefs already name motifs freely |
| `timeline.md` | nothing in code | Template |
| `systems-bible.md` | nothing in code | Optional by its own text |
| `key-decisions.md` | `cmd_evaluate`, `git`, `prompts_elaborate` | Author decisions; empty is correct for a book we didn't write |
| `visual-style.md`, `canon/` | GN pipeline / `illustrate` | Art direction, not description |
| `chapter-map.csv` | `assemble`, `score`, `illustrate`, `cleanup` | **Absent** on the Gatsby eval project (set up from one `manuscript.md`) |
| `storyforge.yaml` `project.genre` / `subgenre` | prompts, press-kit, produce | Still `PROJECT_GENRE` on an extracted book |

**Gaps found that the issue doesn't list:**

- **`scenes.csv:summary` was blank on extracted books** (fixed in PR 0). Phase 3b wrote a one-sentence summary for every scene, used it as rolling context, then dropped it. It now fills a blank cell, never an existing one. Books extracted before that still have blank summaries.
- **Template headers lagged the schema** (fixed in PR 0, together with cleanup's expected schemas, `migrate-medium`'s headers, `scenes.py` and the init skill, which now all follow `elaborate._FILE_MAP`). Writers write the canonical header, never whatever header is on disk; `update_scene` and `migrate-medium` keep columns beyond it.
- **`elaborate --stage voice` is prescriptive.** It asks for style rules, prohibited patterns and `banned_words`, which is right for a seed but wrong here (the issue's describe-don't-prescribe constraint). Extraction needs its own prompt. It should reuse elaborate's *output formats* (fenced `voice-guide` and `voice-profile-csv` blocks, CSV columns) so consumers see one shape.
- **Eval projects predate the ledger.** Gatsby's still has `knowledge.csv` / `physical-states.csv`. The bible step has to handle `NotMigratedError` (use the briefs' knowledge instead, and say so).

## Design

### One new phase, 5 ("describe"), in its own module

New code goes in **`storyforge/extract_describe.py`**: prompt builders, JSON schemas, parsers, the write gate, and renderers. `cmd_extract.py` only gains `--phase 5`, a `_run_phase_5` dispatcher, and a call after phase 4. That keeps the overlap with #439 (which moves phase 4's code into `extract.py`) to a few lines in `main`.

Phase 5 runs direct (not batch): it's about seven calls, several of which depend on each other. Independent steps run through `runner.run_parallel`, with exceptions checked. Every call goes through `api` with a JSON schema, like phases 0–4.

### Steps, in dependency order

The pattern throughout: **the model labels and code computes** (the #351 lesson). Anything copyable from CSVs is copied by code. The model only picks, names and describes.

| Step | Output | Model's job | Code's job | Model |
|---|---|---|---|---|
| **5a structure** | `spine.csv`, `architecture.csv`, `scenes.csv:architecture_scene`, `scenes.csv:summary` where blank, `project.genre` / `subgenre` | Choose 5–10 spine events, each with title, function and a one-sentence summary, plus the scene ids it spans. Choose 15–25 anchor scenes from the **existing** scene ids, each assigned to a spine event. Name the genre. | Validate ids against `scenes.csv` (an unknown id fails the step). Copy `act`, `pov`, `action_sequel`, `emotional_arc`, `value_at_stake`, `value_shift` and `turning_point` from the scene CSVs into `architecture.csv`. Anchor scenes get `architecture_scene` = their own id; interstitial scenes stay blank (the schema allows it, and assigning them would be a guess). Retry once on the **mechanical** floors only (counts, ids, summaries of at most 35 words). The L4 action/sequel balance is a fact about the book and is never retried for: if *Gatsby*'s anchors fail it, the scorer reports it. | Opus |
| **5b themes & motifs** | `themes.csv`, `motif-taxonomy.csv`, `scene-intent.csv:theme_threads`, normalized `scene-briefs.csv:motifs` | Name 3–7 themes as questions the book dramatizes, with tiers, and tag each scene with them. Group the briefs' free-text motifs into a taxonomy with aliases and tiers. | Count motif mentions in the briefs first. A motif in fewer than 2 scenes isn't offered as a candidate. Then normalize brief cells through the aliases, the same way `enrich` does. | Opus |
| **5c pitch & architecture** | `story-summary.md`, `story-architecture.md` | Write both from the profile, the spine, themes, `mice-threads.csv` and the scene summaries in reading order. One call for both, so the logline and the premise can't disagree. | Render `story-summary.md` in the exact shape `parse_story_summary` reads, with `_updated` stamps. Run the L0–L2 floors and retry once. Structure section word counts come from `scenes.csv`, never from the model. | Opus |
| **5d characters** | `character-bible.md` | Describe primary and secondary characters, the relationship map, voice notes and POV decisions, from the evidence it's given. | Build the evidence per character: `characters.csv`, the ledger's binding `fixed` facts (`trait`, `relationship`) with quotes, the arc from the scenes where they're POV or on stage, and 5–8 dialogue samples, cut from `prose_analysis._DIALOGUE_RE` matches by a new helper (`extract_dialogue` joins every line into one string, so it can't give samples). Order: POV characters, then by on-stage count. | Opus |
| **5e world** | `world-bible.md`, plus `systems-bible.md` only if the book has a formal system | Describe the world from the evidence. Say whether there's a formal system (magic, technology with rules); for *Gatsby*, there isn't. | Build the evidence: `locations.csv` with scene counts, the ledger's `world` facts with quotes, and the profile's `key_locations`. | Opus |
| **5f voice** | `voice-guide.md`, `voice-profile.csv` | Describe the voice from sampled prose: opening, middle, close, and the three scenes with the most dialogue, about 30k tokens in total. Describe the book's habits; don't write rules. | Pick samples deterministically (by `seq` and dialogue ratio). Measure what's measurable (sentence-length spread, dialogue share, contraction rate) and give the numbers to the model rather than letting it guess. `banned_words` stays empty: absence isn't a ban. | Opus |
| **5g deterministic** | `timeline.md`, `chapter-map.csv` if missing, provenance | none | Render `timeline.md` from `timeline_day` / `timeline_date` / `time_mode`, the profile's `timeline_span`, and flashback scenes (described, never flagged). Build the chapter map from the chapter headings scenes-setup left in each chapter's first scene. If there are none, report that rather than guessing. | none |

5d, 5e and 5f only need 5a, so they run in parallel after it. 5c needs 5b's themes.

### The never-overwrite rule

One gate, `extract_describe.write_described`, is the only way phase 5 writes: it decides, writes, and records the hash. `_POLICY` holds the rule for every `FileState`, with a totality test. A file is written if it is:

- missing,
- empty,
- a CSV whose one line looks like a header (any header, since older projects carry older ones; `grief|Grief|core` is a row, not a header),
- `is_unfilled_template`, or
- **under `--force` only:** a file whose current content hash matches the provenance record, meaning extraction wrote it and nobody has edited it since.

Anything else is **reported**, never overwritten, including an extracted doc an author has since edited, with or without `--force`. This follows the codebase's report-don't-mutate posture. So is a symlink (never written through), an unreadable file, and any file with content while the provenance record itself can't be read (`unverified`). The verdict names the file and why, so silence means it was written. An unusable provenance record is never rewritten: `write_described` raises `ProvenanceError` instead, because rewriting it from nothing would erase every other row.

### Provenance

There are two records because CSVs can't carry comments:

- Markdown docs start with `<!-- storyforge:extracted v1.x.y step=5c from=profile,spine,themes -->`, so a person reading the file knows where it came from.
- `working/extraction-provenance.csv` (`file|version|step|written_at|sha256`) is what the code trusts. The header alone isn't enough, because an author can edit the body and keep the header line.

Files a book doesn't use (`systems-bible.md` for *Gatsby*) get a one-paragraph extracted stub ("No formal system: …", with provenance), not the template. The scorers then see "checked, not applicable" rather than "never looked".

### Fixed scope and standing decisions

- **Describe, never prescribe.** No "Do / Do not" lists. Template sections that only make sense as prescriptions ("Things to Avoid", "Expansion Opportunities", "Influence Blend" weights) are renamed to their descriptive counterparts ("What the book never does", "What the text leaves open", "Lineage"). The headings consumers depend on stay put. A test asserts the voice guide has no imperative bullet lines.
- Flashbacks, uneven scene lengths and MICE nesting are described, never flagged.
- **Coaching levels:** phase 5 runs at every level, because it describes a book that exists rather than inventing one. That's the same reason phases 0–4 aren't gated. (Decision 3.)
- **Graphic-novel projects:** skipped with a log line; a separate issue covers them.
- **`key-decisions.md`:** never extracted. Inventing an author's decisions is the one thing this phase must not do. (Decision 1.)

## PRs, in order

Each PR has its own reviewer. Re-recording eval cassettes doesn't need a separate go-ahead.

0. **Groundwork (patch, can start now; doesn't touch `cmd_extract`'s phase 4 region).**
   - Bring the template CSV headers in line with `elaborate.py`.
   - Persist phase 3b's `_summary` into `scenes.csv:summary` where blank (never for a scene with no row).
   - Add the write gate (`extract_describe.write_described`) and the provenance record, with tests for every state, with and without `--force`.
   - **Done, plus review fixes** (#442): the stale column lists, `migrate-medium` dropping summaries, the scorers' unguarded reads.
1. **5a + 5b (minor).** Structure, themes and motifs. Tests: parsers on recorded replies, an unknown scene id failing the step, columns copied by code (not the model), the floor retry. **Needs #439 merged** for the `cmd_extract` dispatch.
2. **5c (minor).** Pitch and story architecture. Tests: round-trip through `parse_story_summary`, the L0–L2 floors on the output, word counts taken from CSVs.
3. **5d + 5e + 5f (minor).** Bibles and voice. Tests: evidence builders (fixed facts only, quotes kept, the `NotMigratedError` fallback stated), the no-imperatives lint, the `voice-profile.csv` schema, the systems-bible stub.
4. **5g + eval suite + docs (minor).**
   - `timeline.md` and the chapter map.
   - A new replay suite, **E9 (reference completeness)**, on the Carol fixture:
     - run phase 5 from cassettes;
     - assert no file in `reference/` is template-identical and no registry is header-only (with the decision 1 exemptions);
     - `score --all-levels` passes the L0–L6 floors;
     - `status` walks past the elaboration ladder;
     - `validate` passes on schema;
     - a second run with no `--force` writes nothing.
   - `docs/agent-reference.md`, the rethink status doc, and `skills/extract/SKILL.md`, which should offer phase 5.

After that, a hand-off to storyforge-evals: we don't touch `~/Developer/evals`, so they would add `gold/<slug>/reference-notes.md` (critical consensus per doc), run phase 5 on *Carol* and *Gatsby*, judge the docs against the text and gold, and re-score character, act and narrative against noise (*Carol* character noise is about 0.5).

## Cost estimate (the issue asks for it before a paid record)

Opus 5.5 at $4 per million input tokens and $20 per million output tokens (`costs.PRICING`). Per book, for a 40–100 scene novel:

| Step | In (tokens) | Out (tokens) | Cost |
|---|---|---|---|
| 5a structure | ~25k | ~5k | ~$0.20 |
| 5b themes & motifs | ~20k | ~4k | ~$0.16 |
| 5c pitch & architecture | ~20k | ~6k | ~$0.20 |
| 5d characters | ~40k | ~10k | ~$0.36 |
| 5e world | ~25k | ~6k | ~$0.22 |
| 5f voice | ~40k | ~6k | ~$0.28 |
| **Total** | | | **~$1.40, ~$2 with floor retries** |

- E9 record on *Carol* + *Gatsby*: **about $3–4**.
- All eight classics: **about $12–16**.
- Re-scoring (story-power and the character and narrative passes) is extra, at storyforge-evals' existing per-book figures.
- Worth weighing: on Sonnet 5.5 ($2/$10) the whole phase is about half the cost. 5a and 5b are mostly selection and could go to Sonnet; the descriptive docs should stay on Opus.

## Decisions (Ben, 2026-10-30)

1. **Files that stay empty:** the "no template-identical file" acceptance excludes `key-decisions.md` (author decisions can't be extracted), `visual-style.md` and `canon/` (art direction). E9 lists these exemptions.
2. **Describe only.** No prescriptive rules in this issue. A later elaborate step can turn a description into drafting rules if wanted.
3. **Coaching:** phase 5 runs at every level, `strict` included, because it describes a book that exists rather than inventing one.
4. **Model:** Opus for every phase 5 call, 5a and 5b included.
5. **`project.logline`** is left alone. It's deprecated as an input and `story-summary.md` is canonical.

## Risks

- **Long novels.** #355 fixed phase 0 dropping the middle of long books, but the profile is still a summary. 5a builds the spine from the scene CSVs, which cover the whole book, and uses the profile only as a hint.
- **Shared drafting context changes.** `build_shared_context` sends the character and world bibles to every drafting call. Once they're real, drafting on a re-extracted book changes (the intent). E4, E5 and E8 pin book commits, so their numbers don't move until a fixture is re-extracted. Note this in the status doc so a future jump isn't misread.
- **Description quality is the real test, and only storyforge-evals can grade it.** E9 checks completeness and the floors, not truth. Don't read a green E9 as "the bible is right".

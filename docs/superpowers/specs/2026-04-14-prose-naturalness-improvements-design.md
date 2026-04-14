# Prose Naturalness Improvements Design

**Date:** 2026-04-14
**Motivation:** Incorporate lessons from markus-michalski/storyforge's anti-AI prose approach — specifically their explicit banned word lists, structured author voice profiles, and cross-chapter repetition detection — into our pipeline. Delivered in three phases, each with standalone value.

## Context

Our current naturalness approach is strong on post-hoc detection and targeted revision (the `prose_naturalness` principle, 4 diagnostic markers, 3-pass `--naturalness` revision). What we lack:

1. **A single authoritative AI-tell word list.** Flagged words are scattered across diagnostics.csv, revision pass prompts, and evaluator instructions. No one canonical source.
2. **Structured voice constraints at draft time.** The voice guide is free-form prose — good for creative direction but hard for an LLM to enforce mechanically. No machine-parseable preferred/banned words per character.
3. **Cross-chapter repetition detection.** Per-scene evaluation can't catch the same simile appearing 18 times across 34 chapters.

## Phase 1: AI-Tell Word List + Revision Integration

### New File

**`references/ai-tell-words.csv`** — pipe-delimited, ships with the plugin.

```
word|category|severity|replacement_hint
```

Fields:
- `word` — the flagged word or phrase (primary key)
- `category` — `vocabulary`, `hedging`, or `structural`
- `severity` — `high` (almost never appropriate in fiction) or `medium` (context-dependent, might be fine in dialogue or specific registers)
- `replacement_hint` — brief guidance on what to use instead, or `[show don't name]` style directives

Categories:
- `vocabulary` — flagged nouns/verbs/adjectives: delve, tapestry, nuanced, vibrant, multifaceted, pivotal, intricate, myriad, beacon, paradigm, profound, juxtaposition, visceral, palpable, dichotomy, realm, testament, unprecedented, foster, harness, illuminate, bolster, transformative, compelling, dynamic, resonate, embark, navigate (metaphorical), uncover, ever-evolving, seamless, innovative, facilitate, streamline, differentiate, refine, interplay, synergy, cutting-edge, game-changing, scalable, rich (metaphorical), journey (metaphorical), embrace (metaphorical), compelling narrative
- `hedging` — qualifiers and softeners: perhaps, somewhat, almost as if, something like, something between, a kind of, the particular, it's worth noting, it should be mentioned, to some extent, generally speaking, broadly speaking, arguably, remarkably, one might argue
- `structural` — phrase-level patterns: at its core, to put it simply, this underscores the importance of, a key takeaway is, from a broader perspective, in essence, in many cases

Initial word count: ~70 entries. Consolidated from the current diagnostics.csv (pn-4), cmd_revise.py naturalness passes, line-editor.md evaluator prompt, and the markus-michalski anti-ai-patterns.md reference (55 words, cherry-picked for fiction relevance).

### Changes to Existing Code

**`cmd_revise.py`** — Pass 3 (AI-Vocabulary-Hedging):
- Currently has a hardcoded word list in the prompt template.
- Change: Load `ai-tell-words.csv` from the plugin's `references/` directory. Filter to relevant categories and inject into the revision prompt. Same pass logic, richer and maintainable input.

**`scripts/prompts/evaluators/line-editor.md`**:
- Currently has an inline list of AI patterns to watch for.
- Change: The evaluation prompt builder loads `ai-tell-words.csv` and injects the `high` severity words into the line editor's prompt. The evaluator instructions reference the injected list rather than maintaining their own.

**`prompts.py`** (scene drafting):
- Change: Load `high` severity words from `ai-tell-words.csv` and include as a "never use these words" constraint in scene drafting prompts. Lightweight prevention even before voice profiles exist.

**No changes to:**
- `diagnostics.csv` — the pn-1 through pn-4 markers describe *patterns* (antithesis framing, em-dash overuse, parallelism, hedging). The word list provides the *vocabulary*. They complement each other.
- `scoring-rubrics.md` — rubric descriptions stay the same.

### Testing

- Unit test: load ai-tell-words.csv, verify schema (all fields present, no duplicates, severity is high/medium, category is vocabulary/hedging/structural).
- Unit test: revision prompt builder includes words from the CSV.
- Unit test: drafting prompt builder includes high-severity words in the constraint block.

---

## Phase 2: Voice Profile from Elaborate Stage

### New File Per Project

**`reference/voice-profile.csv`** — pipe-delimited, produced during the elaborate voice stage.

```
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style
```

Fields:
- `character` — character ID from characters.csv, or `_project` for project-level fields
- `preferred_words` — semicolon-delimited words central to this voice (character-level only)
- `banned_words` — semicolon-delimited words that break this book's voice (project-level only; merged with universal ai-tell-words.csv at draft time)
- `metaphor_families` — semicolon-delimited domains to source metaphors from (character-level only)
- `rhythm_preference` — prose rhythm description (character-level only)
- `register` — prose register (project-level only)
- `dialogue_style` — how this character speaks (character-level only)

Design principle: project-level fields (`_project` row) hold book-wide constraints — banned_words, register. Character-level fields hold per-POV constraints — preferred_words, metaphor_families, rhythm_preference, dialogue_style. Each field lives in exactly one place; no override logic needed.

Example:

```
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style
_project||journey;beacon;resonate;embrace|||literary;restrained;precise|
dorren-hayle|calibrated;systematic;categorical;precise||cartography;measurement;institutional systems|short declarative for realization;clinical when overwhelmed||clipped;formal;avoids emotional language
tessa-merrin|gritty;rough;worn;cracked||textile decay;weather;kitchen/cooking|longer sensory runs;fragments for dark humor||casual;irreverent;trailing off with ellipses
```

### How It Gets Populated

The elaborate skill's voice stage already produces `reference/voice-guide.md`. After writing the voice guide, the same stage also produces `reference/voice-profile.csv` by extracting structured constraints from the creative decisions just made. One stage, two artifacts.

The `cmd_elaborate.py` voice stage prompt includes instructions: "After writing the voice guide, extract structured data into voice-profile.csv: one `_project` row with banned_words and register, then one row per POV character with preferred_words (10-20 words), metaphor_families, rhythm_preference, and dialogue_style."

### Changes to Existing Code

**`cmd_elaborate.py`**:
- Voice stage prompt updated to produce both artifacts.
- Voice-profile.csv columns validated by `schema.py`.

**`prompts.py`** (scene drafting):
- Loads `reference/voice-profile.csv` if it exists.
- Gets the POV character from the scene brief.
- Injects into the drafting prompt:
  - Character's `preferred_words` as "favor these words"
  - Character's `metaphor_families` as "source metaphors from these domains"
  - Character's `rhythm_preference` and `dialogue_style` as constraints
  - Project-level `banned_words` **merged with** high-severity words from `references/ai-tell-words.csv` (Phase 1) as "never use these words"
  - Project-level `register` as overall prose register

**`cmd_revise.py`**:
- Naturalness passes load the voice profile.
- Project-level `banned_words` merge with universal list — the revision prompt knows what's banned for this specific project.
- A word on the universal AI-tell list can be excluded via the project NOT listing it in banned_words (the universal list provides defaults; the project's banned_words field is the authority for this project).
- If no voice-profile.csv exists (project hasn't completed the voice stage), falls back to the universal AI-tell list only — same as Phase 1 behavior.

**Elaborate skill** (`skills/elaborate/SKILL.md`):
- Voice stage section updated to describe the two-artifact output.
- Explains what each field means and how it's used downstream.

**`schema.py`**:
- Add voice-profile.csv column definitions and validation (character must be `_project` or exist in characters.csv).

### Testing

- Unit test: voice-profile.csv schema validation (required columns, _project row exists, character IDs match characters.csv).
- Unit test: drafting prompt builder merges project banned_words + universal ai-tell-words correctly.
- Unit test: drafting prompt builder loads correct character row for POV character.
- Unit test: missing voice-profile.csv gracefully falls back to current behavior (voice guide only).

---

## Phase 3: Repetition Checker

### New Command

**`storyforge repetition`** — pure-stdlib n-gram scanner. No API calls, runs in seconds.

```
storyforge repetition                      # full manuscript scan
storyforge repetition --scenes S1,S2       # specific scenes only
storyforge repetition --min-occurrences 3  # raise threshold for long books
storyforge repetition --category simile    # filter to one category
```

### New Modules

**`scripts/lib/python/storyforge/repetition.py`** — scanning algorithm as library functions:

- `tokenize_scene(text) -> list[str]` — lowercase, strip punctuation, preserve word boundaries
- `extract_ngrams(tokens, n) -> dict[tuple, list[location]]` — n-grams with source locations (scene_id, approximate line)
- `scan_manuscript(project_dir, scene_ids=None, min_occurrences=None) -> list[Finding]` — full scan pipeline
- `categorize_finding(phrase, locations) -> str` — heuristic categorization
- `suppress_subphrases(findings) -> list[Finding]` — longer phrases suppress contained shorter phrases within +/-1 occurrence count

Algorithm:
1. Load scene prose files from `scenes/`, ordered by sequence from scenes.csv
2. Tokenize each scene
3. Extract n-grams at window sizes 4, 5, 6, 7
4. Count occurrences across scenes, tracking scene_id and line for each
5. Apply thresholds: 4-grams need 5+ hits, 5-grams 3+, 6-7 grams 2+
6. Drop n-grams that are entirely stop words
7. Suppress subphrases
8. Categorize and rank by severity

Finding categories:
- `simile` — contains "like", "as if", "as though"
- `character_tell` — body-part vocabulary (eyes, hands, jaw, chest, throat, etc.)
- `blocking_tic` — blocking verbs (looked, turned, nodded, glanced, stepped, reached)
- `sensory` — sensory tokens (smell, taste, sound, cold, warm, etc.)
- `structural` — patterns like "for the first time", "the kind of", "in a way that"
- `signature_phrase` — everything else

Severity: `high` (4+ occurrences), `medium` (2-3).

**`scripts/lib/python/storyforge/cmd_repetition.py`** — command module:

- Standard `parse_args`/`main` pattern
- Calls `repetition.scan_manuscript()`
- Writes `working/repetition-report.csv` (phrase, category, severity, count, scene_ids)
- Prints summary to stdout: scenes scanned, total findings, high-severity count, top 5 offenders

### New Scoring Principle

**`prose_repetition`** — new principle in the `prose_craft` section of craft weights.

Default weight: 4.

Diagnostic markers in `diagnostics.csv`:

```
prose_craft|prose_repetition|pr-1|Does the same simile or figurative comparison appear in 3+ scenes?|yes|2|List the repeated simile and scenes where it appears
prose_craft|prose_repetition|pr-2|Does the same character blocking tic (looked/turned/nodded + object) appear in 4+ scenes?|yes|1|List the repeated tic and scenes
prose_craft|prose_repetition|pr-3|Does the same structural phrase ("for the first time", "the kind of") appear in 4+ scenes?|yes|1|List the repeated phrase and scenes
prose_craft|prose_repetition|pr-4|Does the same signature phrase or sentence pattern appear in 3+ scenes?|yes|2|List the repeated phrase and scenes
```

### Scoring Integration

The score is fully deterministic — no LLM evaluation needed.

**`cmd_score.py`**:
- After LLM scoring and structural scoring, runs `repetition.scan_manuscript()`.
- For each scene, counts how many high-severity and medium-severity findings it participates in.
- Maps counts to marker deficits: pr-1 triggers if the scene shares a repeated simile, pr-2 for blocking tics, etc.
- Writes `working/scores/repetition-latest.csv` (scene_id, pr-1, pr-2, pr-3, pr-4, total_penalty).
- The scoring synthesis prompt sees the repetition scores alongside structural scores and LLM scores.

**`references/default-craft-weights.csv`**:
- Add row: `prose_craft|prose_repetition|4||`

**`references/scoring-rubrics.md`**:
- Add prose_repetition rubric: "When it works: Each image, gesture, and phrase pattern feels fresh across the manuscript. Similes are not recycled. Characters have varied physical responses. No structural tic reveals the writing was produced in isolation, chapter by chapter. When it fails: The same simile appears in multiple chapters. Characters repeatedly perform the same blocking action. Structural phrases recur mechanically across scenes. The manuscript reads as a collection of independently written chapters rather than a unified whole."

**`references/diagnostics.csv`**:
- Add pr-1 through pr-4 rows as shown above.

### Changes to Existing Code

**`__main__.py`**:
- Add `'repetition': 'storyforge.cmd_repetition'` to COMMANDS dict.

**`cmd_score.py`**:
- Import `repetition.scan_manuscript`.
- Add repetition scoring phase after structural scoring.
- Write repetition-latest.csv.
- Include repetition data in scoring synthesis.

**`schema.py`**:
- Add repetition-report.csv and repetition-latest.csv column definitions.

### Testing

- Unit test: tokenizer handles punctuation, contractions, em dashes correctly.
- Unit test: n-gram extraction with known input produces expected output.
- Unit test: threshold filtering (4-grams below 5 hits are dropped, etc.).
- Unit test: subphrase suppression (longer phrase suppresses contained shorter phrase).
- Unit test: categorization heuristics (simile detection, body-part vocabulary, etc.).
- Unit test: stop-word-only n-grams are dropped.
- Unit test: scoring integration maps findings to pr-1 through pr-4 markers correctly.
- Fixture: small test manuscript with known repeated phrases for deterministic testing.

---

## Phase Order and Dependencies

```
Phase 1 ──→ Phase 2 ──→ Phase 3
(word list)  (voice profile)  (repetition)
```

- Phase 1 is prerequisite for Phase 2: the voice profile's banned_words merge with the universal word list.
- Phase 3 is independent of Phase 2 but ordered last because it's the largest and most self-contained.
- Each phase delivers standalone value and can be shipped independently.

## Files Created/Modified Summary

### Phase 1
- **Create:** `references/ai-tell-words.csv`
- **Modify:** `cmd_revise.py`, `prompts.py`, `scripts/prompts/evaluators/line-editor.md`
- **Tests:** `tests/test_ai_tell_words.py`

### Phase 2
- **Create (per project):** `reference/voice-profile.csv`
- **Modify:** `cmd_elaborate.py`, `prompts_elaborate.py`, `prompts.py`, `cmd_revise.py`, `schema.py`, `skills/elaborate/SKILL.md`
- **Tests:** `tests/test_voice_profile.py`

### Phase 3
- **Create:** `scripts/lib/python/storyforge/repetition.py`, `scripts/lib/python/storyforge/cmd_repetition.py`
- **Modify:** `__main__.py`, `cmd_score.py`, `schema.py`, `references/default-craft-weights.csv`, `references/scoring-rubrics.md`, `references/diagnostics.csv`
- **Tests:** `tests/test_repetition.py`

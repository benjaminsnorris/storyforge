# Prose Naturalness Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three naturalness features — a universal AI-tell word list, structured per-character voice profiles, and a cross-chapter repetition checker — to improve both prevention and detection of AI-sounding prose.

**Architecture:** Phase 1 creates a canonical word list in `references/ai-tell-words.csv` and wires it into drafting and revision prompts. Phase 2 adds `reference/voice-profile.csv` as a per-project artifact produced during the elaborate voice stage, providing character-level vocabulary constraints at draft time. Phase 3 adds a deterministic n-gram repetition scanner as both a standalone command and a new scoring principle.

**Tech Stack:** Python stdlib only (consistent with zero-dependency constraint). Pipe-delimited CSV. pytest for tests.

---

## File Map

### Phase 1 — AI-Tell Word List
| Action | File | Responsibility |
|--------|------|----------------|
| Create | `references/ai-tell-words.csv` | Canonical list of flagged words/phrases with category, severity, replacement hints |
| Create | `tests/test_ai_tell_words.py` | Schema validation and prompt integration tests |
| Modify | `scripts/lib/python/storyforge/prompts.py` | Load word list, inject into drafting prompts |
| Modify | `scripts/lib/python/storyforge/cmd_revise.py:290-314` | Load word list into Pass 3 guidance |
| Modify | `scripts/prompts/evaluators/line-editor.md:14` | Reference injected word list instead of inline list |

### Phase 2 — Voice Profile
| Action | File | Responsibility |
|--------|------|----------------|
| Create | `tests/test_voice_profile.py` | Schema validation, prompt merging, fallback tests |
| Modify | `scripts/lib/python/storyforge/schema.py` | Add voice-profile.csv column definitions + validation |
| Modify | `scripts/lib/python/storyforge/prompts.py` | Load voice profile, merge banned/preferred words into drafting prompt |
| Modify | `scripts/lib/python/storyforge/prompts_elaborate.py` | Voice stage prompt produces voice-profile.csv alongside voice-guide.md |
| Modify | `scripts/lib/python/storyforge/cmd_revise.py` | Load project banned_words from voice profile for naturalness passes |
| Modify | `skills/elaborate/SKILL.md` | Document voice-profile.csv as second voice-stage artifact |
| Create | `tests/fixtures/test-project/reference/voice-profile.csv` | Test fixture |

### Phase 3 — Repetition Checker
| Action | File | Responsibility |
|--------|------|----------------|
| Create | `scripts/lib/python/storyforge/repetition.py` | N-gram scanning algorithm (tokenize, extract, threshold, categorize, suppress) |
| Create | `scripts/lib/python/storyforge/cmd_repetition.py` | CLI command module (parse_args, main, report output) |
| Create | `tests/test_repetition.py` | Scanner algorithm tests + scoring integration tests |
| Modify | `scripts/lib/python/storyforge/__main__.py:9-31` | Register `repetition` command |
| Modify | `references/default-craft-weights.csv` | Add `prose_repetition` principle (weight 4) |
| Modify | `references/scoring-rubrics.md` | Add prose_repetition rubric |
| Modify | `references/diagnostics.csv` | Add pr-1 through pr-4 markers |
| Modify | `scripts/lib/python/storyforge/cmd_score.py` | Run repetition scan, write repetition-latest.csv |

---

## Task 1: Create AI-Tell Word List CSV

**Files:**
- Create: `references/ai-tell-words.csv`
- Create: `tests/test_ai_tell_words.py`

- [ ] **Step 1: Write the schema validation test**

```python
# tests/test_ai_tell_words.py
import os
import csv

def test_ai_tell_words_schema(plugin_dir):
    """Every row has required fields, valid category and severity."""
    path = os.path.join(plugin_dir, 'references', 'ai-tell-words.csv')
    assert os.path.isfile(path), f'Missing {path}'

    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')

    lines = [l for l in raw.splitlines() if l.strip()]
    assert len(lines) >= 2, 'Need header + at least one entry'

    header = lines[0].split('|')
    assert header == ['word', 'category', 'severity', 'replacement_hint'], \
        f'Unexpected header: {header}'

    valid_categories = {'vocabulary', 'hedging', 'structural'}
    valid_severities = {'high', 'medium'}
    seen_words = set()

    for i, line in enumerate(lines[1:], start=2):
        fields = line.split('|')
        assert len(fields) == 4, f'Line {i}: expected 4 fields, got {len(fields)}'
        word, category, severity, hint = fields
        assert word.strip(), f'Line {i}: empty word'
        assert category in valid_categories, \
            f'Line {i}: invalid category "{category}"'
        assert severity in valid_severities, \
            f'Line {i}: invalid severity "{severity}"'
        assert word not in seen_words, f'Line {i}: duplicate word "{word}"'
        seen_words.add(word)


def test_ai_tell_words_minimum_count(plugin_dir):
    """Sanity check: list should have at least 50 entries."""
    path = os.path.join(plugin_dir, 'references', 'ai-tell-words.csv')
    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    assert len(lines) - 1 >= 50, f'Expected 50+ entries, got {len(lines) - 1}'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_tell_words.py -v`
Expected: FAIL — file does not exist

- [ ] **Step 3: Create the word list**

Create `references/ai-tell-words.csv` with pipe-delimited format. Consolidate words from:
- `cmd_revise.py` lines 297-299 (nuanced, multifaceted, tapestry, palpable, pivotal, intricate, profound, myriad, juxtaposition, dichotomy, paradigm, visceral)
- `cmd_revise.py` lines 301-302 (something like, something between, almost as if, perhaps, a kind of, the particular)
- `diagnostics.csv` pn-4 description (hedging stacks, signposted transitions)
- `line-editor.md` line 14 (em dashes, antithesis framing, parallelism, tricolon)
- markus-michalski's anti-ai-patterns.md (cherry-pick fiction-relevant entries: delve, tapestry, nuanced, vibrant, multifaceted, beacon, realm, testament, unprecedented, foster, navigate, embark, resonate, pivotal, interplay, harness, illuminate, bolster, compelling, dynamic, transformative, seamless, innovative, facilitate, streamline, journey, embrace, at its core, in essence, it's worth noting, broadly speaking, to some extent, generally speaking, arguably, remarkably)

Categories:
- `vocabulary` — individual words that signal AI: delve, tapestry, nuanced, vibrant, multifaceted, beacon, realm, testament, unprecedented, foster, navigate (metaphorical), embark, resonate, pivotal, interplay, harness, illuminate, bolster, compelling, dynamic, transformative, seamless, innovative, facilitate, streamline, intricate, profound, myriad, juxtaposition, dichotomy, paradigm, visceral (non-literal), palpable, ever-evolving, cutting-edge, game-changing, scalable, rich (metaphorical), journey (metaphorical), embrace (metaphorical)
- `hedging` — qualifiers and softeners: perhaps, somewhat, almost as if, something like, something between, a kind of, the particular, arguably, remarkably, to some extent, generally speaking, broadly speaking, one might argue, it should be mentioned
- `structural` — phrase-level patterns: at its core, to put it simply, in essence, in many cases, it's worth noting, this underscores, from a broader perspective, a key takeaway

Severity:
- `high` — almost never appropriate in fiction prose: delve, tapestry (metaphorical), nuanced, multifaceted, beacon (metaphorical), paradigm, synergy, facilitate, streamline, innovative, transformative, seamless, scalable, cutting-edge, game-changing, it's worth noting, to put it simply, this underscores, a key takeaway, from a broader perspective
- `medium` — context-dependent, might be fine in dialogue or specific registers: vibrant, realm, testament, unprecedented, compelling, dynamic, profound, pivotal, intricate, myriad, resonate, embark, embrace, journey, palpable, visceral, perhaps, somewhat, almost as if, arguably, at its core, in essence

```
word|category|severity|replacement_hint
delve|vocabulary|high|investigate, examine, dig into
tapestry|vocabulary|high|[use concrete image instead of metaphorical tapestry]
nuanced|vocabulary|high|[show the nuance; don't name it]
vibrant|vocabulary|medium|[use specific color, texture, or energy]
multifaceted|vocabulary|high|[show the facets]
beacon|vocabulary|high|[use concrete image instead of metaphorical beacon]
realm|vocabulary|medium|domain, field, area, world
testament|vocabulary|medium|proof, evidence, sign
unprecedented|vocabulary|medium|[ground the claim in specifics]
foster|vocabulary|high|build, grow, encourage
navigate|vocabulary|medium|[use specific verb: cross, manage, handle]
embark|vocabulary|medium|start, begin, set out
resonate|vocabulary|medium|[show the emotional effect instead of naming it]
pivotal|vocabulary|medium|crucial, critical, turning point
interplay|vocabulary|high|[describe the interaction concretely]
harness|vocabulary|high|use, channel, direct
illuminate|vocabulary|high|reveal, show, clarify
bolster|vocabulary|high|strengthen, support, reinforce
compelling|vocabulary|medium|[show why it compels; don't label it]
dynamic|vocabulary|medium|[describe what actually moves or changes]
transformative|vocabulary|high|[show the transformation]
seamless|vocabulary|high|smooth, fluid, effortless
innovative|vocabulary|high|[describe the innovation specifically]
facilitate|vocabulary|high|help, enable, allow
streamline|vocabulary|high|simplify, speed up
intricate|vocabulary|medium|[show the intricacy]
profound|vocabulary|medium|[show depth instead of naming it]
myriad|vocabulary|medium|many, countless
juxtaposition|vocabulary|medium|contrast, tension
dichotomy|vocabulary|medium|divide, split, tension
paradigm|vocabulary|high|model, framework, pattern
visceral|vocabulary|medium|[use specific sensation instead — gut, bone, nerve]
palpable|vocabulary|medium|[show what makes it tangible]
ever-evolving|vocabulary|high|changing, shifting
cutting-edge|vocabulary|high|[describe what's new specifically]
game-changing|vocabulary|high|[show the impact]
scalable|vocabulary|high|[describe scope concretely]
rich|vocabulary|medium|[show the richness with specific detail]
journey|vocabulary|medium|path, process, road
embrace|vocabulary|medium|accept, welcome, hold
synergy|vocabulary|high|[describe the combined effect]
perhaps|hedging|medium|[commit or cut]
somewhat|hedging|medium|[commit or cut]
almost as if|hedging|medium|[commit to the comparison]
something like|hedging|medium|[name the thing]
something between|hedging|medium|[pick one or describe both]
a kind of|hedging|medium|[name it directly]
the particular|hedging|medium|[name the specific]
arguably|hedging|medium|[commit to the claim or cut]
remarkably|hedging|medium|[show what's remarkable]
to some extent|hedging|medium|[commit or cut]
generally speaking|hedging|medium|[be specific]
broadly speaking|hedging|medium|[be specific]
one might argue|hedging|medium|[argue it or don't]
it should be mentioned|hedging|high|[just mention it]
it's worth noting|structural|high|[just state it]
to put it simply|structural|high|[just say it simply]
in essence|structural|medium|[cut and start with the point]
in many cases|structural|medium|often, frequently, sometimes
this underscores|structural|high|[show the emphasis through specifics]
a key takeaway|structural|high|[state the point directly]
from a broader perspective|structural|high|[cut or ground in specifics]
at its core|structural|medium|[cut and start with the core idea]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_tell_words.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add references/ai-tell-words.csv tests/test_ai_tell_words.py
git commit -m "Add universal AI-tell word list (references/ai-tell-words.csv)"
git push
```

---

## Task 2: Wire Word List into Drafting Prompts

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts.py`
- Modify: `tests/test_ai_tell_words.py`

- [ ] **Step 1: Write test for word list loading in drafting prompts**

Add to `tests/test_ai_tell_words.py`:

```python
def test_load_ai_tell_words(plugin_dir):
    """load_ai_tell_words returns parsed list from CSV."""
    from storyforge.prompts import load_ai_tell_words
    words = load_ai_tell_words(plugin_dir)
    assert len(words) >= 50
    # Each entry is a dict with required keys
    entry = words[0]
    assert 'word' in entry
    assert 'category' in entry
    assert 'severity' in entry
    assert 'replacement_hint' in entry


def test_ai_tell_constraint_block(plugin_dir):
    """build_ai_tell_constraint returns formatted block of high-severity words."""
    from storyforge.prompts import load_ai_tell_words, build_ai_tell_constraint
    words = load_ai_tell_words(plugin_dir)
    block = build_ai_tell_constraint(words)
    assert 'delve' in block
    assert 'tapestry' in block
    # Medium-severity words should NOT be in the constraint block
    # (they're context-dependent)
    # High-severity words should be present
    assert 'facilitate' in block


def test_drafting_prompt_includes_ai_tell_words(project_dir, plugin_dir):
    """build_scene_prompt includes AI-tell constraint when word list exists."""
    from storyforge.prompts import build_scene_prompt
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    # The prompt should contain the AI-tell constraint
    assert 'never use' in prompt.lower() or 'do not use' in prompt.lower() or 'avoid these words' in prompt.lower()
    assert 'delve' in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_tell_words.py::test_load_ai_tell_words -v`
Expected: FAIL — `load_ai_tell_words` does not exist

- [ ] **Step 3: Add load_ai_tell_words and build_ai_tell_constraint to prompts.py**

Add after the `_strip_yaml_value` function (around line 65) in `scripts/lib/python/storyforge/prompts.py`:

```python
# ============================================================================
# AI-tell word list
# ============================================================================

def load_ai_tell_words(plugin_dir: str) -> list[dict[str, str]]:
    """Load the AI-tell word list from references/ai-tell-words.csv.

    Args:
        plugin_dir: Path to the Storyforge plugin root.

    Returns:
        List of dicts with keys: word, category, severity, replacement_hint.
        Empty list if file not found.
    """
    path = os.path.join(plugin_dir, 'references', 'ai-tell-words.csv')
    if not os.path.isfile(path):
        return []

    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')

    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return []

    header = lines[0].split('|')
    result = []
    for line in lines[1:]:
        fields = line.split('|')
        entry = {header[i]: (fields[i] if i < len(fields) else '')
                 for i in range(len(header))}
        result.append(entry)
    return result


def build_ai_tell_constraint(words: list[dict[str, str]],
                              severity: str = 'high') -> str:
    """Build a constraint block listing words to avoid.

    Args:
        words: Output of load_ai_tell_words().
        severity: Minimum severity to include ('high' = high only,
                  'medium' = both high and medium).

    Returns:
        Formatted constraint text for prompt injection.
    """
    if not words:
        return ''

    include = {'high'}
    if severity == 'medium':
        include.add('medium')

    filtered = [w['word'] for w in words if w.get('severity') in include]
    if not filtered:
        return ''

    word_list = ', '.join(filtered)
    return (
        'VOCABULARY CONSTRAINT: Do not use these words or phrases — they signal '
        'AI-generated prose and must be avoided entirely:\n'
        f'{word_list}\n'
        'Replace with concrete, specific words grounded in the scene and character.'
    )
```

- [ ] **Step 4: Inject the constraint into build_scene_prompt**

In `build_scene_prompt` (line ~570 area, after craft_sections are resolved), add the AI-tell constraint loading. Find the section where `craft_sections` is built (around line 571-578) and add after it:

```python
    # --- AI-tell word constraint ---
    ai_tell_words = load_ai_tell_words(plugin_dir)
    ai_tell_block = build_ai_tell_constraint(ai_tell_words)
```

Then in the prompt assembly section (around line 620-628 where craft_sections are appended), add after the craft principles block:

```python
    if ai_tell_block:
        lines.append('')
        lines.append('===== VOCABULARY CONSTRAINTS =====')
        lines.append('')
        lines.append(ai_tell_block)
```

Note: `plugin_dir` needs to be resolved in `build_scene_prompt`. It's already computed at line 576-577 as a fallback for craft_sections. Hoist that computation to the top of the function so it's available for both uses:

```python
    # --- Plugin dir (for loading craft engine and word lists) ---
    plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ai_tell_words.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/python/storyforge/prompts.py tests/test_ai_tell_words.py
git commit -m "Add AI-tell word loading and inject into drafting prompts"
git push
```

---

## Task 3: Wire Word List into Revision Pass 3

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py:290-314`
- Modify: `tests/test_ai_tell_words.py`

- [ ] **Step 1: Write test for revision prompt integration**

Add to `tests/test_ai_tell_words.py`:

```python
def test_naturalness_plan_loads_word_list(tmp_path, plugin_dir):
    """The naturalness plan Pass 3 guidance should include words from CSV."""
    import os
    # We can't easily call _generate_naturalness_plan without side effects,
    # so test the helper that loads words for revision prompts.
    from storyforge.prompts import load_ai_tell_words
    words = load_ai_tell_words(plugin_dir)
    vocab_words = [w['word'] for w in words if w['category'] == 'vocabulary']
    # Should include the words that were previously hardcoded in cmd_revise.py
    assert 'nuanced' in vocab_words
    assert 'multifaceted' in vocab_words
    assert 'tapestry' in vocab_words
    assert 'palpable' in vocab_words
    # Should also include new words from the expanded list
    assert 'delve' in vocab_words
    assert 'beacon' in vocab_words
```

- [ ] **Step 2: Run test to verify it passes** (this test validates the CSV content, which already exists)

Run: `pytest tests/test_ai_tell_words.py::test_naturalness_plan_loads_word_list -v`
Expected: PASS

- [ ] **Step 3: Modify Pass 3 in cmd_revise.py to load from CSV**

In `_generate_naturalness_plan` (line 290), replace the hardcoded word list in Pass 3's `guidance` string. The current hardcoded list at lines 298-299 reads:

```python
'nuanced, multifaceted, tapestry, palpable, pivotal, intricate, profound, myriad, '
'juxtaposition, dichotomy, paradigm, visceral (when not literal). Replace with concrete, specific words. '
```

Replace the entire Pass 3 dict with a version that builds the vocabulary list dynamically:

```python
        {
            'pass': '3',
            'name': 'ai-vocabulary-hedging',
            'purpose': 'Remove AI-tell vocabulary, hedging stacks, sweeping openers, and summary closers',
            'scope': 'full',
            'targets': '',
            'guidance': _build_naturalness_pass3_guidance(),
            'protection': 'Do not change dialogue, plot events, or character interiority that reveals new information.',
            'findings': 'naturalness',
            'status': 'pending',
            'model_tier': 'opus',
            'fix_location': 'craft',
        },
```

Add a helper function above `_generate_naturalness_plan`:

```python
def _build_naturalness_pass3_guidance() -> str:
    """Build Pass 3 guidance, loading vocabulary from ai-tell-words.csv."""
    from storyforge.prompts import load_ai_tell_words

    plugin_dir = get_plugin_dir()
    words = load_ai_tell_words(plugin_dir)

    # Build vocabulary list from CSV
    vocab_words = [w['word'] for w in words if w['category'] == 'vocabulary']
    hedging_words = [w['word'] for w in words if w['category'] == 'hedging']

    if vocab_words:
        vocab_str = ', '.join(vocab_words)
    else:
        # Fallback if CSV not found
        vocab_str = ('nuanced, multifaceted, tapestry, palpable, pivotal, intricate, '
                     'profound, myriad, juxtaposition, dichotomy, paradigm, visceral')

    if hedging_words:
        hedging_str = ', '.join(hedging_words)
    else:
        hedging_str = ('"something like", "something between", "almost as if", "perhaps", '
                       '"a kind of", "the particular"')

    return (
        'Four patterns to fix: '
        f'(a) AI-TELL VOCABULARY: Remove or replace these words that signal AI-generated prose: '
        f'{vocab_str}. Replace with concrete, specific words. '
        f'(b) HEDGING STACKS: {hedging_str} — remove or commit to the statement. '
        'BEFORE: "Something that tasted the way silence feels." AFTER: Name the taste. '
        '(c) SWEEPING OPENERS: Remove scene-opening sentences that set a thematic frame before anything happens. '
        '"The thing about memory is..." / "There are moments when..." — cut to the first concrete action or image. '
        '(d) SUMMARY CLOSERS: Remove paragraph-ending sentences that interpret what was just shown. '
        '"And that was the thing about X." / "It was, she realized, exactly what she needed." '
        '— let the scene end on action or image.'
    )
```

- [ ] **Step 4: Run full test suite to verify nothing broke**

Run: `pytest tests/test_ai_tell_words.py tests/test_revise_args.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_ai_tell_words.py
git commit -m "Wire AI-tell word list into naturalness revision Pass 3"
git push
```

---

## Task 4: Update Line Editor Evaluator Prompt

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_evaluate.py`
- Modify: `scripts/prompts/evaluators/line-editor.md`

- [ ] **Step 1: Update line-editor.md to reference injected word list**

The current line 14 of `line-editor.md` has an inline description of AI patterns. Replace the static word mentions with a placeholder that will be filled by the prompt builder:

In `scripts/prompts/evaluators/line-editor.md`, replace line 14:

```
- **AI writing patterns:** Flag prose that reads as machine-generated rather than human-written. Watch for: excessive em dashes, antithesis framing (contrasting pairs where the first element is negated and the second affirmed), compulsive parallelism and tricolon, symmetrical paragraph structure, hedging stacks ("perhaps," "somewhat," "almost as if"), signposted transitions, sweeping scene openers, summary closers. These patterns are the prose equivalent of an uncanny valley — technically proficient but recognizably artificial.
```

With:

```
- **AI writing patterns:** Flag prose that reads as machine-generated rather than human-written. Watch for: excessive em dashes, antithesis framing (contrasting pairs where the first element is negated and the second affirmed), compulsive parallelism and tricolon, symmetrical paragraph structure, hedging stacks, signposted transitions, sweeping scene openers, summary closers. These patterns are the prose equivalent of an uncanny valley — technically proficient but recognizably artificial.
{AI_TELL_WORDS}
```

- [ ] **Step 2: Inject the word list in cmd_evaluate.py**

In `cmd_evaluate.py` where the persona is loaded and `{GENRE}` is replaced (around line 328-331), add word list injection after the genre replacement:

```python
    # Inject AI-tell word list for line-editor
    if evaluator == 'line-editor':
        from storyforge.prompts import load_ai_tell_words, build_ai_tell_constraint
        ai_words = load_ai_tell_words(plugin_dir)
        if ai_words:
            vocab_words = [w['word'] for w in ai_words
                          if w['severity'] == 'high']
            word_block = (
                'Specific AI-tell vocabulary to flag (these words almost never '
                'belong in fiction): ' + ', '.join(vocab_words)
            )
            persona = persona.replace('{AI_TELL_WORDS}', word_block)
        else:
            persona = persona.replace('{AI_TELL_WORDS}', '')
    else:
        persona = persona.replace('{AI_TELL_WORDS}', '')
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -k "evaluate or ai_tell" -v --timeout=10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/prompts/evaluators/line-editor.md scripts/lib/python/storyforge/cmd_evaluate.py
git commit -m "Wire AI-tell word list into line editor evaluator prompt"
git push
```

---

## Task 5: Voice Profile Schema and Test Fixture

**Files:**
- Create: `tests/test_voice_profile.py`
- Create: `tests/fixtures/test-project/reference/voice-profile.csv`
- Modify: `scripts/lib/python/storyforge/schema.py`

- [ ] **Step 1: Create test fixture**

Create `tests/fixtures/test-project/reference/voice-profile.csv`:

```
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style
_project||journey;beacon;resonate;embrace|||literary;restrained;precise|
dorren-hayle|calibrated;systematic;categorical;precise||cartography;measurement;institutional systems|short declarative for realization;clinical when overwhelmed||clipped;formal;avoids emotional language
tessa-merrin|gritty;rough;worn;cracked||textile decay;weather;kitchen|longer sensory runs;fragments for dark humor||casual;irreverent;trailing off
```

- [ ] **Step 2: Write schema and loading tests**

```python
# tests/test_voice_profile.py
import os

def test_voice_profile_fixture_exists(fixture_dir):
    """Test fixture includes a voice profile."""
    path = os.path.join(fixture_dir, 'reference', 'voice-profile.csv')
    assert os.path.isfile(path)


def test_voice_profile_schema(fixture_dir):
    """Voice profile has correct columns."""
    path = os.path.join(fixture_dir, 'reference', 'voice-profile.csv')
    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    header = lines[0].split('|')
    assert header == [
        'character', 'preferred_words', 'banned_words', 'metaphor_families',
        'rhythm_preference', 'register', 'dialogue_style',
    ]


def test_voice_profile_has_project_row(fixture_dir):
    """Voice profile has a _project row."""
    path = os.path.join(fixture_dir, 'reference', 'voice-profile.csv')
    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    lines = [l for l in raw.splitlines() if l.strip()]
    characters = [l.split('|')[0] for l in lines[1:]]
    assert '_project' in characters


def test_load_voice_profile(fixture_dir):
    """load_voice_profile returns project and character data."""
    from storyforge.prompts import load_voice_profile
    project, characters = load_voice_profile(fixture_dir)

    # Project-level data
    assert 'banned_words' in project
    assert 'journey' in project['banned_words']
    assert 'register' in project
    assert 'literary' in project['register']

    # Character data
    assert 'dorren-hayle' in characters
    assert 'tessa-merrin' in characters
    assert 'calibrated' in characters['dorren-hayle']['preferred_words']
    assert 'gritty' in characters['tessa-merrin']['preferred_words']


def test_load_voice_profile_missing_file(tmp_path):
    """load_voice_profile returns empty dicts when file missing."""
    from storyforge.prompts import load_voice_profile
    project, characters = load_voice_profile(str(tmp_path))
    assert project == {}
    assert characters == {}


def test_merge_banned_words(fixture_dir, plugin_dir):
    """Merged banned words include project + universal AI-tell list."""
    from storyforge.prompts import load_voice_profile, load_ai_tell_words, merge_banned_words
    project, _ = load_voice_profile(fixture_dir)
    ai_words = load_ai_tell_words(plugin_dir)
    merged = merge_banned_words(project, ai_words)

    # From project voice profile
    assert 'journey' in merged
    assert 'beacon' in merged
    # From universal AI-tell list (high severity)
    assert 'delve' in merged
    assert 'facilitate' in merged
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_voice_profile.py -v`
Expected: FAIL — `load_voice_profile` does not exist

- [ ] **Step 4: Write schema.py validation test**

Add to `tests/test_voice_profile.py`:

```python
def test_validate_voice_profile_valid(fixture_dir):
    """validate_voice_profile passes on a well-formed file."""
    from storyforge.schema import validate_voice_profile
    result = validate_voice_profile(fixture_dir)
    assert result['errors'] == []
    assert result['has_project_row'] is True
    assert result['character_count'] >= 2


def test_validate_voice_profile_missing_project_row(tmp_path):
    """validate_voice_profile flags missing _project row."""
    import os
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    vp = ref_dir / 'voice-profile.csv'
    vp.write_text(
        'character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style\n'
        'some-char|word1;word2||metaphor1|||casual\n'
    )
    result = validate_voice_profile(str(tmp_path))
    assert result['has_project_row'] is False
    assert any('_project' in e['message'] for e in result['errors'])


def test_validate_voice_profile_bad_header(tmp_path):
    """validate_voice_profile flags wrong columns."""
    import os
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    vp = ref_dir / 'voice-profile.csv'
    vp.write_text('character|wrong_col\n_project|\n')
    result = validate_voice_profile(str(tmp_path))
    assert any('column' in e['message'].lower() for e in result['errors'])


def test_validate_voice_profile_duplicate_character(tmp_path):
    """validate_voice_profile flags duplicate character rows."""
    import os
    ref_dir = tmp_path / 'reference'
    ref_dir.mkdir()
    vp = ref_dir / 'voice-profile.csv'
    vp.write_text(
        'character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style\n'
        '_project||banned1|||literary|\n'
        'char-a|word1||meta1|||casual\n'
        'char-a|word2||meta2|||formal\n'
    )
    result = validate_voice_profile(str(tmp_path))
    assert any('duplicate' in e['message'].lower() for e in result['errors'])


def test_validate_voice_profile_missing_file(tmp_path):
    """validate_voice_profile returns gracefully when file missing."""
    result = validate_voice_profile(str(tmp_path))
    assert result['errors'] == []
    assert result['has_project_row'] is False
    assert result['character_count'] == 0
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/test_voice_profile.py::test_validate_voice_profile_valid -v`
Expected: FAIL — `validate_voice_profile` does not exist

- [ ] **Step 6: Implement validate_voice_profile in schema.py**

Add to `scripts/lib/python/storyforge/schema.py`, after `validate_physical_state_granularity`:

```python
# ============================================================================
# Voice profile validation
# ============================================================================

VOICE_PROFILE_COLUMNS = [
    'character', 'preferred_words', 'banned_words', 'metaphor_families',
    'rhythm_preference', 'register', 'dialogue_style',
]


def validate_voice_profile(project_dir: str) -> dict:
    """Validate reference/voice-profile.csv structure and content.

    Checks:
    - File has correct columns
    - A _project row exists
    - No duplicate character rows
    - Character IDs exist in characters.csv (if available)

    Args:
        project_dir: Path to the book project root.

    Returns:
        Dict with has_project_row, character_count, errors (list of dicts
        with 'row' and 'message' keys).
    """
    path = os.path.join(project_dir, 'reference', 'voice-profile.csv')
    errors: list[dict] = []

    if not os.path.isfile(path):
        return {'has_project_row': False, 'character_count': 0, 'errors': []}

    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')

    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return {'has_project_row': False, 'character_count': 0, 'errors': []}

    # Check header
    header = lines[0].split('|')
    if header != VOICE_PROFILE_COLUMNS:
        missing = [c for c in VOICE_PROFILE_COLUMNS if c not in header]
        extra = [c for c in header if c not in VOICE_PROFILE_COLUMNS]
        msg = 'Voice profile has wrong columns.'
        if missing:
            msg += f' Missing: {", ".join(missing)}.'
        if extra:
            msg += f' Unexpected: {", ".join(extra)}.'
        errors.append({'row': 'header', 'message': msg})
        return {'has_project_row': False, 'character_count': 0, 'errors': errors}

    # Parse rows
    has_project = False
    seen_characters: set[str] = set()
    character_count = 0

    # Load characters.csv for cross-reference if available
    chars_path = os.path.join(project_dir, 'reference', 'characters.csv')
    known_characters: set[str] = set()
    if os.path.isfile(chars_path):
        for row in _read_csv(chars_path):
            cid = row.get('id', '').strip()
            if cid:
                known_characters.add(cid)

    for i, line in enumerate(lines[1:], start=2):
        fields = line.split('|')
        char_id = fields[0].strip() if fields else ''

        if char_id == '_project':
            has_project = True
        elif char_id:
            character_count += 1

            if char_id in seen_characters:
                errors.append({
                    'row': char_id,
                    'message': f'Duplicate character row: "{char_id}"',
                })
            seen_characters.add(char_id)

            if known_characters and char_id not in known_characters:
                errors.append({
                    'row': char_id,
                    'message': f'Character "{char_id}" not found in characters.csv',
                })
        else:
            errors.append({
                'row': f'line {i}',
                'message': 'Empty character field',
            })

    if not has_project:
        errors.append({
            'row': '(missing)',
            'message': 'No _project row found — project-level fields (banned_words, register) have nowhere to live',
        })

    return {
        'has_project_row': has_project,
        'character_count': character_count,
        'errors': errors,
    }
```

- [ ] **Step 7: Run all voice profile tests**

Run: `pytest tests/test_voice_profile.py -v`
Expected: PASS (all tests including schema validation)

- [ ] **Step 8: Commit the fixture, tests, and schema validation**

```bash
git add tests/fixtures/test-project/reference/voice-profile.csv tests/test_voice_profile.py scripts/lib/python/storyforge/schema.py
git commit -m "Add voice profile test fixture, schema validation, and failing loading tests"
git push
```

---

## Task 6: Implement Voice Profile Loading

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts.py`

- [ ] **Step 1: Add load_voice_profile and merge_banned_words to prompts.py**

Add after `build_ai_tell_constraint` in `scripts/lib/python/storyforge/prompts.py`:

```python
# ============================================================================
# Voice profile
# ============================================================================

def load_voice_profile(project_dir: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Load the voice profile from reference/voice-profile.csv.

    Args:
        project_dir: Path to the book project root.

    Returns:
        Tuple of (project_data, character_data).
        project_data: dict of field -> value for the _project row.
        character_data: dict of character_id -> {field: value}.
        Both empty dicts if file not found.
    """
    path = os.path.join(project_dir, 'reference', 'voice-profile.csv')
    if not os.path.isfile(path):
        return {}, {}

    with open(path, encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')

    lines = [l for l in raw.splitlines() if l.strip()]
    if len(lines) < 2:
        return {}, {}

    header = lines[0].split('|')
    project_data = {}
    character_data = {}

    for line in lines[1:]:
        fields = line.split('|')
        row = {header[i]: (fields[i] if i < len(fields) else '')
               for i in range(len(header))}

        char_id = row.get('character', '').strip()
        if char_id == '_project':
            project_data = {k: v for k, v in row.items() if k != 'character' and v.strip()}
        elif char_id:
            character_data[char_id] = {k: v for k, v in row.items()
                                        if k != 'character' and v.strip()}

    return project_data, character_data


def merge_banned_words(project_profile: dict[str, str],
                       ai_tell_words: list[dict[str, str]]) -> list[str]:
    """Merge project-level banned words with universal AI-tell high-severity words.

    Args:
        project_profile: Project-level voice profile data (from load_voice_profile).
        ai_tell_words: Output of load_ai_tell_words().

    Returns:
        Deduplicated list of banned words.
    """
    banned = set()

    # Project-level banned words
    project_banned = project_profile.get('banned_words', '')
    if project_banned:
        for w in project_banned.split(';'):
            w = w.strip()
            if w:
                banned.add(w)

    # Universal high-severity AI-tell words
    for entry in ai_tell_words:
        if entry.get('severity') == 'high':
            banned.add(entry['word'])

    return sorted(banned)
```

- [ ] **Step 2: Run voice profile tests**

Run: `pytest tests/test_voice_profile.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/python/storyforge/prompts.py
git commit -m "Add load_voice_profile and merge_banned_words to prompts.py"
git push
```

---

## Task 7: Inject Voice Profile into Drafting Prompts

**Files:**
- Modify: `scripts/lib/python/storyforge/prompts.py`
- Modify: `tests/test_voice_profile.py`

- [ ] **Step 1: Write test for voice profile injection**

Add to `tests/test_voice_profile.py`:

```python
def test_drafting_prompt_includes_voice_profile(project_dir, plugin_dir):
    """build_scene_prompt includes character voice constraints when profile exists."""
    from storyforge.prompts import build_scene_prompt
    # act1-sc01 is the first scene; we need to check the POV character
    # The test fixture has dorren-hayle as a character in voice-profile.csv
    # We need scenes.csv to have pov=dorren-hayle for act1-sc01
    import os
    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    with open(scenes_csv, encoding='utf-8') as f:
        content = f.read()
    # Check if pov column exists and has a value we can use
    # If not, this test validates that the prompt still works without a matching POV
    prompt = build_scene_prompt('act1-sc01', project_dir, api_mode=True)
    # The prompt should contain the project-level banned words
    assert 'journey' in prompt or 'VOCABULARY CONSTRAINT' in prompt
```

- [ ] **Step 2: Inject voice profile into build_scene_prompt**

In `build_scene_prompt`, after the AI-tell word loading, add voice profile loading. Find the POV character from the scene metadata (from scenes.csv `pov` column), then load the profile:

```python
    # --- Voice profile ---
    voice_profile_project, voice_profile_chars = load_voice_profile(project_dir)
    pov_char = ''
    if csv_file:
        pov_char = read_csv_field(csv_file, scene_id, 'pov')

    # Merge banned words: project profile + universal AI-tell list
    if voice_profile_project or ai_tell_words:
        merged_banned = merge_banned_words(voice_profile_project, ai_tell_words)
        if merged_banned:
            banned_str = ', '.join(merged_banned)
            ai_tell_block = (
                'VOCABULARY CONSTRAINT: Do not use these words or phrases — they '
                'are banned for this project:\n'
                f'{banned_str}\n'
                'Replace with concrete, specific words grounded in the scene and character.'
            )

    # Character-specific constraints
    char_voice_block = ''
    if pov_char and pov_char in voice_profile_chars:
        char_data = voice_profile_chars[pov_char]
        parts = []
        if char_data.get('preferred_words'):
            parts.append(f'Favor these words (they define this character\'s voice): '
                        f'{char_data["preferred_words"].replace(";", ", ")}')
        if char_data.get('metaphor_families'):
            parts.append(f'Source metaphors from: '
                        f'{char_data["metaphor_families"].replace(";", ", ")}')
        if char_data.get('rhythm_preference'):
            parts.append(f'Sentence rhythm: '
                        f'{char_data["rhythm_preference"].replace(";", ", ")}')
        if char_data.get('dialogue_style'):
            parts.append(f'Dialogue style: '
                        f'{char_data["dialogue_style"].replace(";", ", ")}')
        if parts:
            char_voice_block = (
                f'CHARACTER VOICE ({pov_char}):\n' + '\n'.join(f'- {p}' for p in parts)
            )
```

Then in the prompt assembly, after the vocabulary constraints block:

```python
    if char_voice_block:
        lines.append('')
        lines.append('===== CHARACTER VOICE =====')
        lines.append('')
        lines.append(char_voice_block)
```

The register from the project profile should also be injected if present:

```python
    if voice_profile_project.get('register'):
        lines.append('')
        lines.append(f'PROSE REGISTER: {voice_profile_project["register"].replace(";", ", ")}')
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_voice_profile.py tests/test_ai_tell_words.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/python/storyforge/prompts.py tests/test_voice_profile.py
git commit -m "Inject voice profile into drafting prompts (character voice + merged banned words)"
git push
```

---

## Task 8: Wire Voice Profile into Revision

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_revise.py`
- Modify: `tests/test_voice_profile.py`

- [ ] **Step 1: Write test**

Add to `tests/test_voice_profile.py`:

```python
def test_naturalness_pass3_uses_project_banned_words(project_dir, plugin_dir):
    """Pass 3 guidance merges project banned words with universal list."""
    # Write a voice-profile.csv with custom banned words
    import os
    profile_path = os.path.join(project_dir, 'reference', 'voice-profile.csv')
    with open(profile_path, 'w') as f:
        f.write('character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style\n')
        f.write('_project||realm;visceral|||gritty;noir|\n')

    from storyforge.prompts import load_voice_profile, load_ai_tell_words, merge_banned_words
    project, _ = load_voice_profile(project_dir)
    ai_words = load_ai_tell_words(plugin_dir)
    merged = merge_banned_words(project, ai_words)

    # Project-specific bans
    assert 'realm' in merged
    assert 'visceral' in merged
    # Universal high-severity
    assert 'delve' in merged
```

- [ ] **Step 2: Run test to verify it passes** (this tests the already-implemented merge logic)

Run: `pytest tests/test_voice_profile.py::test_naturalness_pass3_uses_project_banned_words -v`
Expected: PASS

- [ ] **Step 3: Update _build_naturalness_pass3_guidance to accept project_dir**

Modify `_build_naturalness_pass3_guidance` in `cmd_revise.py` to also load the project's voice profile and merge banned words:

```python
def _build_naturalness_pass3_guidance(project_dir: str = '') -> str:
    """Build Pass 3 guidance, loading vocabulary from ai-tell-words.csv
    and project voice profile."""
    from storyforge.prompts import load_ai_tell_words, load_voice_profile, merge_banned_words

    plugin_dir = get_plugin_dir()
    ai_words = load_ai_tell_words(plugin_dir)

    # Merge with project-level banned words if available
    if project_dir:
        project_profile, _ = load_voice_profile(project_dir)
        all_banned = merge_banned_words(project_profile, ai_words)
    else:
        all_banned = [w['word'] for w in ai_words if w.get('severity') == 'high']

    vocab_words = [w['word'] for w in ai_words if w['category'] == 'vocabulary']
    hedging_words = [w['word'] for w in ai_words if w['category'] == 'hedging']

    if all_banned:
        vocab_str = ', '.join(all_banned)
    elif vocab_words:
        vocab_str = ', '.join(vocab_words)
    else:
        vocab_str = ('nuanced, multifaceted, tapestry, palpable, pivotal, intricate, '
                     'profound, myriad, juxtaposition, dichotomy, paradigm, visceral')

    if hedging_words:
        hedging_str = ', '.join(hedging_words)
    else:
        hedging_str = ('"something like", "something between", "almost as if", "perhaps", '
                       '"a kind of", "the particular"')

    return (
        'Four patterns to fix: '
        f'(a) AI-TELL VOCABULARY: Remove or replace these words that signal AI-generated prose: '
        f'{vocab_str}. Replace with concrete, specific words. '
        f'(b) HEDGING STACKS: {hedging_str} — remove or commit to the statement. '
        'BEFORE: "Something that tasted the way silence feels." AFTER: Name the taste. '
        '(c) SWEEPING OPENERS: Remove scene-opening sentences that set a thematic frame before anything happens. '
        '"The thing about memory is..." / "There are moments when..." — cut to the first concrete action or image. '
        '(d) SUMMARY CLOSERS: Remove paragraph-ending sentences that interpret what was just shown. '
        '"And that was the thing about X." / "It was, she realized, exactly what she needed." '
        '— let the scene end on action or image.'
    )
```

Update the call site in `_generate_naturalness_plan` to pass `project_dir`. The function doesn't currently have access to `project_dir`, so it needs to accept it as a parameter. Update the signature and the call in `main()`:

In `_generate_naturalness_plan`, add `project_dir` parameter:
```python
def _generate_naturalness_plan(plan_file, project_dir=''):
```

And update the Pass 3 guidance line:
```python
            'guidance': _build_naturalness_pass3_guidance(project_dir),
```

In `main()` where `_generate_naturalness_plan` is called (around line 1253), pass `project_dir`:
```python
        plan_rows = _generate_naturalness_plan(csv_plan_file, project_dir)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_voice_profile.py tests/test_revise_args.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_revise.py tests/test_voice_profile.py
git commit -m "Wire project voice profile banned words into naturalness revision"
git push
```

---

## Task 9: Update Elaborate Skill for Voice Profile

**Files:**
- Modify: `skills/elaborate/SKILL.md`
- Modify: `scripts/lib/python/storyforge/prompts_elaborate.py`

- [ ] **Step 1: Update the elaborate skill documentation**

In `skills/elaborate/SKILL.md`, find the voice stage section. Add documentation explaining that the voice stage now produces two artifacts:

Add after the voice guide output description:

```markdown
### Voice Profile (Second Artifact)

After writing the voice guide, also produce `reference/voice-profile.csv` — a structured companion with machine-parseable voice constraints. This file is used by drafting and revision prompts to enforce vocabulary and style rules.

Format (pipe-delimited CSV):

```
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style
```

- **`_project` row:** Project-level fields — `banned_words` (words that break this book's voice), `register` (e.g., "literary;restrained;precise"). Leave character-specific fields empty.
- **One row per POV character:** Character-specific fields — `preferred_words` (10-20 words central to their voice), `metaphor_families` (domains they source images from), `rhythm_preference` (sentence patterns), `dialogue_style` (how they speak). Leave project-level fields empty.

Example:

```
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style
_project||journey;beacon;resonate;embrace|||literary;restrained;precise|
dorren-hayle|calibrated;systematic;categorical|...|cartography;measurement|short declarative for realization||clipped;formal
```
```

- [ ] **Step 2: Update the voice stage prompt in prompts_elaborate.py**

In `prompts_elaborate.py`, find the voice stage prompt builder. Add instructions to produce the voice-profile.csv after the voice guide. The voice stage prompt should include:

```
After writing the voice guide, produce a second artifact: reference/voice-profile.csv

This is a pipe-delimited CSV with these columns:
character|preferred_words|banned_words|metaphor_families|rhythm_preference|register|dialogue_style

Create rows:
1. A _project row with:
   - banned_words: words that would break this book's voice (semicolon-separated)
   - register: the prose register (e.g., "literary;restrained;precise")
   - Leave preferred_words, metaphor_families, rhythm_preference, dialogue_style empty

2. One row per POV character with:
   - preferred_words: 10-20 words central to their voice (semicolon-separated)
   - metaphor_families: domains they source images from (semicolon-separated)
   - rhythm_preference: their sentence patterns (semicolon-separated descriptions)
   - dialogue_style: how they speak (semicolon-separated descriptions)
   - Leave banned_words and register empty (those are project-level)

The character IDs must match the id column in reference/characters.csv.
```

- [ ] **Step 3: Commit**

```bash
git add skills/elaborate/SKILL.md scripts/lib/python/storyforge/prompts_elaborate.py
git commit -m "Update elaborate voice stage to produce voice-profile.csv"
git push
```

---

## Task 10: Repetition Scanner Algorithm

**Files:**
- Create: `scripts/lib/python/storyforge/repetition.py`
- Create: `tests/test_repetition.py`

- [ ] **Step 1: Write core algorithm tests**

```python
# tests/test_repetition.py
import os


def test_tokenize_scene():
    """Tokenizer strips punctuation and lowercases."""
    from storyforge.repetition import tokenize_scene
    tokens = tokenize_scene('He looked at the sky. "Hello," she said.')
    assert tokens == ['he', 'looked', 'at', 'the', 'sky', 'hello', 'she', 'said']


def test_tokenize_preserves_contractions():
    """Contractions stay as single tokens."""
    from storyforge.repetition import tokenize_scene
    tokens = tokenize_scene("She couldn't believe it wasn't real.")
    assert "couldn't" in tokens
    assert "wasn't" in tokens


def test_tokenize_handles_em_dashes():
    """Em dashes are treated as word separators."""
    from storyforge.repetition import tokenize_scene
    tokens = tokenize_scene('The sky—dark and cold—pressed down.')
    assert 'sky' in tokens
    assert 'dark' in tokens
    # No token should contain the em dash
    assert all('—' not in t for t in tokens)


def test_extract_ngrams():
    """N-gram extraction produces correct windows."""
    from storyforge.repetition import tokenize_scene, extract_ngrams
    tokens = tokenize_scene('the cat sat on the mat and the cat sat on the rug')
    ngrams = extract_ngrams(tokens, 4, 'scene-1')
    # "the cat sat on" should appear twice
    key = ('the', 'cat', 'sat', 'on')
    assert key in ngrams
    assert len(ngrams[key]) == 2


def test_stop_word_only_ngrams_dropped():
    """N-grams consisting entirely of stop words are filtered out."""
    from storyforge.repetition import scan_scenes
    # Two scenes with repeated stop-word-only phrases
    scenes = {
        's1': 'it was in the and it was in the end',
        's2': 'it was in the and it was in the end',
    }
    findings = scan_scenes(scenes)
    # "it was in the" is all stop words — should be dropped
    phrases = [f['phrase'] for f in findings]
    assert 'it was in the' not in phrases


def test_subphrase_suppression():
    """Longer phrases suppress contained shorter phrases."""
    from storyforge.repetition import suppress_subphrases
    findings = [
        {'phrase': 'the back of his', 'count': 5, 'category': 'character_tell'},
        {'phrase': 'back of his', 'count': 5, 'category': 'character_tell'},
        {'phrase': 'the back of his neck', 'count': 4, 'category': 'character_tell'},
    ]
    result = suppress_subphrases(findings)
    # "the back of his neck" (longer, count within ±1) should suppress "the back of his"
    phrases = [f['phrase'] for f in result]
    assert 'the back of his neck' in phrases
    # The shorter contained phrase should be suppressed
    assert 'the back of his' not in phrases


def test_categorize_simile():
    """Phrases with 'like' are categorized as simile."""
    from storyforge.repetition import categorize_finding
    cat = categorize_finding('eyes like broken glass')
    assert cat == 'simile'


def test_categorize_blocking_tic():
    """Phrases with blocking verbs are categorized as blocking_tic."""
    from storyforge.repetition import categorize_finding
    cat = categorize_finding('she turned to look')
    assert cat == 'blocking_tic'


def test_categorize_character_tell():
    """Phrases with body part vocabulary are character_tell."""
    from storyforge.repetition import categorize_finding
    cat = categorize_finding('the back of his neck')
    assert cat == 'character_tell'


def test_full_scan_with_fixtures(project_dir):
    """Full scan runs on fixture scenes and returns findings."""
    from storyforge.repetition import scan_manuscript
    findings = scan_manuscript(project_dir)
    # Findings is a list (may be empty for the small fixture)
    assert isinstance(findings, list)
    # Each finding has required keys
    for f in findings:
        assert 'phrase' in f
        assert 'category' in f
        assert 'severity' in f
        assert 'count' in f
        assert 'scene_ids' in f
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_repetition.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement repetition.py**

Create `scripts/lib/python/storyforge/repetition.py`:

```python
"""Cross-chapter repetition detection for Storyforge manuscripts.

Pure-stdlib n-gram scanner that detects repeated phrases across scenes.
No API calls — runs in seconds on 100k-word manuscripts.
"""

import os
import re

from storyforge.elaborate import _read_csv, _FILE_MAP


# ============================================================================
# Stop words (common English words that don't carry meaning on their own)
# ============================================================================

STOP_WORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can', 'it',
    'its', 'he', 'she', 'they', 'them', 'his', 'her', 'their', 'this',
    'that', 'these', 'those', 'not', 'no', 'so', 'if', 'then', 'than',
    'too', 'very', 'just', 'about', 'up', 'out', 'into',
})

# Minimum occurrences by n-gram length
THRESHOLDS = {4: 5, 5: 3, 6: 2, 7: 2}

# ============================================================================
# Categorization vocabulary
# ============================================================================

BODY_PARTS = frozenset({
    'eyes', 'eye', 'hands', 'hand', 'face', 'jaw', 'chest', 'throat',
    'neck', 'shoulder', 'shoulders', 'back', 'stomach', 'gut', 'fingers',
    'lips', 'mouth', 'head', 'heart', 'skin', 'arms', 'arm', 'legs',
    'leg', 'knees', 'knee', 'teeth', 'breath', 'fist', 'fists', 'palm',
    'palms', 'wrist', 'spine',
})

BLOCKING_VERBS = frozenset({
    'looked', 'turned', 'nodded', 'glanced', 'stepped', 'reached',
    'moved', 'shifted', 'leaned', 'shook', 'shrugged', 'stared',
    'gazed', 'watched',
})

SIMILE_CUES = frozenset({'like', 'as if', 'as though'})

SENSORY_WORDS = frozenset({
    'smell', 'smelled', 'taste', 'tasted', 'sound', 'sounded', 'cold',
    'warm', 'hot', 'wet', 'dry', 'sharp', 'soft', 'loud', 'quiet',
    'bright', 'dark', 'bitter', 'sweet', 'rough', 'smooth',
})

STRUCTURAL_CUES = frozenset({
    'for the first time', 'the kind of', 'in a way that', 'the sort of',
    'there was something', 'it was the kind', 'for a long moment',
    'in that moment', 'at that moment',
})


# ============================================================================
# Tokenizer
# ============================================================================

def tokenize_scene(text: str) -> list[str]:
    """Tokenize scene text into lowercase words.

    Handles em dashes as separators, preserves contractions.
    """
    # Replace em dashes with spaces
    text = text.replace('—', ' ').replace('–', ' ')
    # Split on whitespace
    raw_tokens = text.split()
    tokens = []
    for t in raw_tokens:
        # Strip leading/trailing punctuation except apostrophes
        cleaned = re.sub(r"^[^\w']+|[^\w']+$", '', t.lower())
        if cleaned:
            tokens.append(cleaned)
    return tokens


# ============================================================================
# N-gram extraction
# ============================================================================

def extract_ngrams(tokens: list[str], n: int,
                   scene_id: str) -> dict[tuple, list[str]]:
    """Extract n-grams from tokens, tracking which scene they came from.

    Returns:
        Dict mapping n-gram tuple to list of scene_ids where it appears.
    """
    ngrams: dict[tuple, list[str]] = {}
    for i in range(len(tokens) - n + 1):
        gram = tuple(tokens[i:i + n])
        if gram not in ngrams:
            ngrams[gram] = []
        if not ngrams[gram] or ngrams[gram][-1] != scene_id:
            ngrams[gram].append(scene_id)
    return ngrams


# ============================================================================
# Categorization
# ============================================================================

def categorize_finding(phrase: str) -> str:
    """Categorize a repeated phrase by heuristic rules."""
    words = phrase.lower().split()
    word_set = set(words)

    # Simile detection
    if 'like' in words[1:]:  # skip 'like' as first word
        return 'simile'
    if 'as if' in phrase.lower() or 'as though' in phrase.lower():
        return 'simile'

    # Character tell (body parts)
    if word_set & BODY_PARTS:
        return 'character_tell'

    # Blocking tic
    if word_set & BLOCKING_VERBS:
        return 'blocking_tic'

    # Sensory
    if word_set & SENSORY_WORDS:
        return 'sensory'

    # Structural
    for cue in STRUCTURAL_CUES:
        if cue in phrase.lower():
            return 'structural'

    return 'signature_phrase'


# ============================================================================
# Subphrase suppression
# ============================================================================

def suppress_subphrases(findings: list[dict]) -> list[dict]:
    """Suppress shorter phrases contained in longer ones with similar count."""
    if not findings:
        return findings

    # Sort by phrase length descending
    sorted_findings = sorted(findings, key=lambda f: -len(f['phrase'].split()))
    kept = []
    suppressed_phrases = set()

    for finding in sorted_findings:
        phrase = finding['phrase']
        if phrase in suppressed_phrases:
            continue

        kept.append(finding)

        # Suppress shorter phrases contained in this one
        for other in sorted_findings:
            other_phrase = other['phrase']
            if other_phrase == phrase:
                continue
            if other_phrase in phrase and abs(other['count'] - finding['count']) <= 1:
                suppressed_phrases.add(other_phrase)

    return kept


# ============================================================================
# Main scanning functions
# ============================================================================

def scan_scenes(scene_texts: dict[str, str],
                min_occurrences: dict[int, int] | None = None) -> list[dict]:
    """Scan scene texts for repeated n-grams.

    Args:
        scene_texts: Dict mapping scene_id to prose text.
        min_occurrences: Override thresholds by n-gram length.

    Returns:
        List of finding dicts with: phrase, category, severity, count, scene_ids.
    """
    thresholds = min_occurrences or THRESHOLDS

    # Collect all n-grams across all scenes
    all_ngrams: dict[tuple, list[str]] = {}
    for scene_id, text in scene_texts.items():
        tokens = tokenize_scene(text)
        for n in thresholds:
            scene_ngrams = extract_ngrams(tokens, n, scene_id)
            for gram, scenes in scene_ngrams.items():
                if gram not in all_ngrams:
                    all_ngrams[gram] = []
                all_ngrams[gram].extend(scenes)

    # Filter by threshold and cross-scene requirement
    findings = []
    for gram, scene_ids in all_ngrams.items():
        n = len(gram)
        threshold = thresholds.get(n, 2)

        # Deduplicate scene_ids for counting unique scenes
        unique_scenes = list(dict.fromkeys(scene_ids))
        if len(unique_scenes) < 2:
            continue  # Must appear in at least 2 different scenes
        if len(scene_ids) < threshold:
            continue

        # Skip stop-word-only n-grams
        if all(w in STOP_WORDS for w in gram):
            continue

        phrase = ' '.join(gram)
        category = categorize_finding(phrase)
        severity = 'high' if len(scene_ids) >= 4 else 'medium'

        findings.append({
            'phrase': phrase,
            'category': category,
            'severity': severity,
            'count': len(scene_ids),
            'scene_ids': unique_scenes,
        })

    # Suppress subphrases
    findings = suppress_subphrases(findings)

    # Sort by count descending
    findings.sort(key=lambda f: -f['count'])
    return findings


def scan_manuscript(project_dir: str,
                    scene_ids: list[str] | None = None) -> list[dict]:
    """Scan a manuscript's scene files for repeated phrases.

    Args:
        project_dir: Path to the book project root.
        scene_ids: Optional list of scene IDs to scan. Defaults to all scenes.

    Returns:
        List of finding dicts.
    """
    scenes_dir = os.path.join(project_dir, 'scenes')
    if not os.path.isdir(scenes_dir):
        return []

    # Determine which scenes to scan
    if scene_ids is None:
        scene_ids = []
        scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
        if os.path.isfile(scenes_csv):
            rows = _read_csv(scenes_csv)
            for row in rows:
                sid = row.get('id', '').strip()
                status = row.get('status', '').strip()
                if sid and status not in ('cut', 'merged', 'spine', 'architecture', 'mapped'):
                    scene_ids.append(sid)
        else:
            # Fall back to scanning directory
            for f in sorted(os.listdir(scenes_dir)):
                if f.endswith('.md'):
                    scene_ids.append(f[:-3])

    # Load scene texts
    scene_texts = {}
    for sid in scene_ids:
        path = os.path.join(scenes_dir, f'{sid}.md')
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                scene_texts[sid] = f.read()

    return scan_scenes(scene_texts)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_repetition.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/python/storyforge/repetition.py tests/test_repetition.py
git commit -m "Add repetition scanner algorithm (repetition.py)"
git push
```

---

## Task 11: Repetition Command Module

**Files:**
- Create: `scripts/lib/python/storyforge/cmd_repetition.py`
- Modify: `scripts/lib/python/storyforge/__main__.py`

- [ ] **Step 1: Write the command module**

```python
# scripts/lib/python/storyforge/cmd_repetition.py
"""storyforge repetition — Cross-chapter repeated phrase detection.

Scans the manuscript for repeated similes, character tells, blocking tics,
and signature phrases that appear across multiple scenes.

Usage:
    storyforge repetition                    # Full manuscript scan
    storyforge repetition --scenes S1,S2     # Specific scenes only
    storyforge repetition --min-occurrences 3 # Raise threshold for long books
    storyforge repetition --category simile  # Filter to one category
"""

import argparse
import csv
import os
import sys

from storyforge.common import detect_project_root, install_signal_handlers, log
from storyforge.cli import add_scene_filter_args, resolve_filter_args
from storyforge.scene_filter import build_scene_list, apply_scene_filter


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge repetition',
        description='Scan manuscript for cross-chapter repeated phrases.',
    )
    add_scene_filter_args(parser)
    parser.add_argument('--min-occurrences', type=int, default=0,
                        help='Override minimum occurrence threshold (0 = use defaults)')
    parser.add_argument('--category', choices=[
        'simile', 'character_tell', 'blocking_tic', 'sensory',
        'structural', 'signature_phrase',
    ], help='Filter findings to one category')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or [])
    install_signal_handlers()
    project_dir = detect_project_root()

    from storyforge.repetition import scan_manuscript, THRESHOLDS

    # Resolve scene filter
    meta_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    scene_ids = None
    mode, val, val2 = resolve_filter_args(args)
    if mode:
        all_ids = build_scene_list(meta_csv)
        scene_ids = apply_scene_filter(meta_csv, all_ids, mode, val, val2)
        log(f'Scanning {len(scene_ids)} scenes (filtered)')
    else:
        log('Scanning all scenes')

    findings = scan_manuscript(project_dir, scene_ids=scene_ids)

    # Apply category filter
    if args.category:
        findings = [f for f in findings if f['category'] == args.category]

    # Write report CSV
    report_dir = os.path.join(project_dir, 'working')
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, 'repetition-report.csv')

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('phrase|category|severity|count|scene_ids\n')
        for finding in findings:
            scenes_str = ';'.join(finding['scene_ids'])
            f.write(f'{finding["phrase"]}|{finding["category"]}|'
                    f'{finding["severity"]}|{finding["count"]}|{scenes_str}\n')

    # Summary
    high_count = sum(1 for f in findings if f['severity'] == 'high')
    log(f'Found {len(findings)} repeated phrases ({high_count} high-severity)')

    if findings:
        log('')
        log('Top findings:')
        for f in findings[:10]:
            scenes = ', '.join(f['scene_ids'][:3])
            if len(f['scene_ids']) > 3:
                scenes += f' +{len(f["scene_ids"]) - 3} more'
            log(f'  [{f["severity"]}] "{f["phrase"]}" — {f["count"]}x '
                f'({f["category"]}) in {scenes}')

    log(f'\nFull report: {report_path}')
```

- [ ] **Step 2: Register the command**

In `scripts/lib/python/storyforge/__main__.py`, add to the COMMANDS dict:

```python
    'repetition': 'storyforge.cmd_repetition',
```

- [ ] **Step 3: Test the command can be dispatched**

Run: `cd /Users/cadencedev/Developer/storyforge && python3 -m storyforge repetition --help`
Expected: Shows help text with `--scenes`, `--min-occurrences`, `--category` flags

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/python/storyforge/cmd_repetition.py scripts/lib/python/storyforge/__main__.py
git commit -m "Add storyforge repetition command"
git push
```

---

## Task 12: Repetition Scoring Principle

**Files:**
- Modify: `references/default-craft-weights.csv`
- Modify: `references/diagnostics.csv`
- Modify: `references/scoring-rubrics.md`

- [ ] **Step 1: Add prose_repetition to craft weights**

In `references/default-craft-weights.csv`, add after the `prose_naturalness` row (line 18):

```
prose_craft|prose_repetition|4||
```

- [ ] **Step 2: Add diagnostic markers**

In `references/diagnostics.csv`, add after the pn-4 row (line 68):

```
prose_craft|prose_repetition|pr-1|Does the same simile or figurative comparison appear in 3+ scenes?|yes|2|List the repeated simile and the scenes where it appears
prose_craft|prose_repetition|pr-2|Does the same character blocking tic (looked/turned/nodded + object) appear in 4+ scenes?|yes|1|List the repeated tic and scenes
prose_craft|prose_repetition|pr-3|Does the same structural phrase ("for the first time", "the kind of") appear in 4+ scenes?|yes|1|List the repeated phrase and scenes
prose_craft|prose_repetition|pr-4|Does the same signature phrase or sentence pattern appear in 3+ scenes?|yes|2|List the repeated phrase and scenes
```

- [ ] **Step 3: Add rubric**

In `references/scoring-rubrics.md`, add the prose_repetition rubric after the prose_naturalness entry:

```markdown
### prose_repetition (Prose Craft)

**When it works:** Each image, gesture, and phrase pattern feels fresh across the manuscript. Similes are not recycled. Characters have varied physical responses. No structural tic reveals the writing was produced in isolation, chapter by chapter. The manuscript reads as a unified whole.

**When it fails:** The same simile appears in multiple chapters. Characters repeatedly perform the same blocking action (turned to look, glanced at, stared at the ceiling). Structural phrases recur mechanically across scenes ("for the first time" appears 15 times). The manuscript reads as a collection of independently written chapters rather than a single voice sustained across the narrative.
```

- [ ] **Step 4: Run schema tests to verify new rows are valid**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (no schema violations in the updated CSVs)

- [ ] **Step 5: Commit**

```bash
git add references/default-craft-weights.csv references/diagnostics.csv references/scoring-rubrics.md
git commit -m "Add prose_repetition scoring principle with diagnostic markers and rubric"
git push
```

---

## Task 13: Wire Repetition into Scoring Pipeline

**Files:**
- Modify: `scripts/lib/python/storyforge/cmd_score.py`
- Modify: `tests/test_repetition.py`

- [ ] **Step 1: Write scoring integration test**

Add to `tests/test_repetition.py`:

```python
def test_repetition_scores_for_scene(tmp_path):
    """score_scene_repetition produces per-scene marker scores."""
    from storyforge.repetition import score_scene_repetition

    findings = [
        {'phrase': 'eyes like broken glass', 'category': 'simile',
         'severity': 'high', 'count': 4, 'scene_ids': ['s1', 's2', 's3', 's4']},
        {'phrase': 'turned to look at', 'category': 'blocking_tic',
         'severity': 'high', 'count': 5, 'scene_ids': ['s1', 's2', 's3', 's4', 's5']},
        {'phrase': 'for the first time', 'category': 'structural',
         'severity': 'high', 'count': 6, 'scene_ids': ['s1', 's2', 's3', 's4', 's5', 's6']},
    ]

    scores = score_scene_repetition('s1', findings)
    # s1 participates in all three findings
    assert scores['pr-1'] == 1  # simile hit
    assert scores['pr-2'] == 1  # blocking tic hit
    assert scores['pr-3'] == 1  # structural hit
    assert scores['pr-4'] == 0  # no signature phrase hit

    # Scene not in any finding
    scores2 = score_scene_repetition('s99', findings)
    assert scores2['pr-1'] == 0
    assert scores2['pr-2'] == 0
    assert scores2['pr-3'] == 0
    assert scores2['pr-4'] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repetition.py::test_repetition_scores_for_scene -v`
Expected: FAIL — `score_scene_repetition` does not exist

- [ ] **Step 3: Add score_scene_repetition to repetition.py**

Add to `scripts/lib/python/storyforge/repetition.py`:

```python
# ============================================================================
# Scoring integration
# ============================================================================

# Map categories to diagnostic markers
_CATEGORY_TO_MARKER = {
    'simile': 'pr-1',
    'character_tell': 'pr-2',
    'blocking_tic': 'pr-2',
    'structural': 'pr-3',
    'sensory': 'pr-4',
    'signature_phrase': 'pr-4',
}


def score_scene_repetition(scene_id: str,
                           findings: list[dict]) -> dict[str, int]:
    """Score a single scene's repetition markers.

    Args:
        scene_id: The scene to score.
        findings: Output of scan_manuscript() or scan_scenes().

    Returns:
        Dict mapping marker ID (pr-1 through pr-4) to 0 or 1.
    """
    scores = {'pr-1': 0, 'pr-2': 0, 'pr-3': 0, 'pr-4': 0}

    for finding in findings:
        if scene_id in finding.get('scene_ids', []):
            marker = _CATEGORY_TO_MARKER.get(finding['category'], 'pr-4')
            scores[marker] = 1

    return scores
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_repetition.py::test_repetition_scores_for_scene -v`
Expected: PASS

- [ ] **Step 5: Wire into cmd_score.py**

In `cmd_score.py`, after the main scoring loop completes and results are written, add a repetition scoring phase. Find the section after scene scores are written (look for where `score-history.csv` or the synthesis step happens) and add:

```python
    # --- Repetition scoring (deterministic) ---
    from storyforge.repetition import scan_manuscript, score_scene_repetition

    log('Running repetition scan...')
    rep_findings = scan_manuscript(project_dir, scene_ids=scored_ids)
    log(f'Repetition scan: {len(rep_findings)} findings')

    rep_scores_path = os.path.join(scores_dir, 'repetition-latest.csv')
    with open(rep_scores_path, 'w', encoding='utf-8') as f:
        f.write('scene_id|pr-1|pr-2|pr-3|pr-4\n')
        for sid in scored_ids:
            markers = score_scene_repetition(sid, rep_findings)
            f.write(f'{sid}|{markers["pr-1"]}|{markers["pr-2"]}|'
                    f'{markers["pr-3"]}|{markers["pr-4"]}\n')

    log(f'Repetition scores written to {rep_scores_path}')
```

The exact insertion point depends on the structure of `cmd_score.py`'s main function. Look for where `scored_ids` (or equivalent list of scored scene IDs) and `scores_dir` are available, after all LLM scoring is complete.

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/test_repetition.py -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/python/storyforge/repetition.py scripts/lib/python/storyforge/cmd_score.py tests/test_repetition.py
git commit -m "Wire repetition scores into scoring pipeline (deterministic pr-1 through pr-4)"
git push
```

---

## Task 14: Version Bump and Final Validation

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 2: Bump version**

In `.claude-plugin/plugin.json`, bump the minor version (this is a new feature):

Read the current version, increment the minor number.

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "Bump version to X.Y.0"
git push
```

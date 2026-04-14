## Scoring Implementation Steps

### 1. Understand the Scoring Infrastructure

- [ ] Read `cmd_score.py` — understand `DETERMINISTIC_PRINCIPLES`, the fast path, and how `_score_repetition` works
- [ ] Read `repetition.py` — the existing deterministic scorer pattern (tokenizer, n-gram scanner, `score_scene_repetition`)
- [ ] Read `exemplars.py` — reusable utilities (`split_sentences`, `compute_rhythm_signature`)
- [ ] Read `structural.py` — CSV metadata readers, pacing shape scorer
- [ ] Read `references/ai-tell-words.csv` — AI-tell vocabulary items
- [ ] Read `references/voice-profile.csv` — character voice constraints
- [ ] Read existing tests: `test_repetition.py`, `test_structural.py`, `test_targeted_scoring.py`

### 2. Follow the `prose_repetition` Pattern

Each new deterministic scorer must:
- Be a function that takes scene text (and optionally metadata/CSV data) and returns a 1-5 score with marker breakdown
- Run in **under 1 second** per scene on a 100k-word manuscript
- Be **conservative** — flag clear deficits (score 1-3) but default to 4 when uncertain
- Use pure stdlib (no external dependencies, no API calls)

### 3. Implement Scorers

For each new principle:

1. **Write the scorer function** in a module (new or existing, as appropriate)
   - Function signature: `score_<principle>(scene_text: str, **kwargs) -> dict` returning `{'score': int, 'markers': dict, 'details': str}`
   - Use existing utilities: `split_sentences()`, `tokenize_scene()`, `compute_rhythm_signature()`
   - Define constants for thresholds, word lists, and regex patterns

2. **Write tests first** in `tests/test_<principle>.py`
   - Test with known-good prose (should score 4-5)
   - Test with known-bad prose (should score 1-3)
   - Test edge cases: empty text, very short scenes, dialogue-heavy scenes
   - Validate marker breakdown is correct

3. **Register in `DETERMINISTIC_PRINCIPLES`** in `cmd_score.py`
   - Add to the `frozenset`
   - Add scoring function call in the deterministic scoring path
   - Follow the `_score_repetition` integration pattern

4. **Validate against existing LLM scores** if available
   - Compare deterministic scores to LLM-generated scores from prior cycles
   - Precision matters more than recall — false positives are worse than false negatives

### 4. Shared Utilities

If multiple scorers need the same text analysis:
- Extract shared utilities to a `prose_analysis.py` module
- Include: sentence splitting, passive voice regex, dialogue extraction, word frequency
- Reuse `exemplars.py` utilities where possible rather than duplicating

### 5. Integration Testing

- [ ] Run `./storyforge score --deterministic --dry-run` to verify registration
- [ ] Run `./storyforge score --principles <new_principle> --dry-run` to verify targeted scoring
- [ ] Verify that `--deterministic` flag picks up all new principles automatically
- [ ] Verify no API calls are made in the deterministic path

### 6. Performance Validation

- [ ] Each scorer runs in < 1 second per scene
- [ ] Full deterministic suite runs in < 30 seconds for a 100k-word manuscript
- [ ] No external dependencies required

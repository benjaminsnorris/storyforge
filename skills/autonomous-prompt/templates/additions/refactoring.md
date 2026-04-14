## Refactoring Implementation Steps

### 1. Understand the Current State
- [ ] Read all code that will be refactored
- [ ] Identify all callers/consumers of the code being changed
- [ ] Run existing tests to establish baseline: `python3 -m pytest tests/ -x -q`
- [ ] Understand why the refactoring is needed

### 2. Plan the Refactoring
- [ ] Identify the target state
- [ ] Plan incremental steps (each step should leave tests passing)
- [ ] Identify shared utilities that should be extracted or reused

### 3. Execute Incrementally
- [ ] Make one logical change at a time
- [ ] Run tests after each change
- [ ] Commit after each passing step
- [ ] Update callers when interfaces change

### 4. Clean Up
- [ ] Remove dead code — unused files, functions, imports
- [ ] Update any references in CLAUDE.md architecture tables
- [ ] Verify no circular imports introduced
- [ ] Run wiring tests: `python3 -m pytest tests/wiring/ -v`

### 5. Validate
- [ ] All existing tests pass (no regressions)
- [ ] All wiring tests pass (signatures intact)
- [ ] No dead code left behind
- [ ] Behavior is identical to before (unless intentionally changed)

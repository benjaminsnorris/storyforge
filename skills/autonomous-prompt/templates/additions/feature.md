## Feature Implementation Steps

### 1. Explore and Understand
- [ ] Search for similar functionality in the codebase
- [ ] Identify patterns used in related modules
- [ ] Note shared utilities that can be reused (check `common.py`, `cli.py`, `runner.py`, `api.py`)
- [ ] Read 2-3 most relevant files for patterns
- [ ] Identify existing test patterns for similar features

### 2. Plan the Implementation
- [ ] Decide where new code should live (new module or extend existing)
- [ ] Identify integration points with existing commands/skills
- [ ] Break feature into testable units
- [ ] Plan the implementation order

### 3. Write Tests First
- [ ] Write tests that describe the desired behavior
- [ ] Use fixtures from `conftest.py` (`fixture_dir`, `project_dir`)
- [ ] Cover happy path, edge cases, error cases
- [ ] Run tests to confirm they fail before implementing

### 4. Implement the Feature
- [ ] Follow the command module pattern: `parse_args(argv)` and `main(argv=None)`
- [ ] Import shared utilities rather than duplicating
- [ ] Use `argparse` for CLI flags (matching existing interface patterns)
- [ ] Use pipe-delimited CSV format for any data files

### 5. Integrate with Existing Infrastructure
- [ ] Register new commands in `__main__.py` if adding a CLI command
- [ ] Update skill SKILL.md files if the feature affects interactive workflows
- [ ] Add to CLAUDE.md architecture tables if appropriate

### 6. Verify
- [ ] All tests pass: `python3 -m pytest tests/ -x -q`
- [ ] Wiring tests pass: `python3 -m pytest tests/wiring/ -v`
- [ ] No dead code left behind

## Pipeline/Infrastructure Implementation Steps

### 1. Understand the Pipeline
- [ ] Read the relevant command module (`cmd_*.py`)
- [ ] Understand the data flow: which CSVs are read/written
- [ ] Check shared modules for existing utilities
- [ ] Review the elaboration pipeline stage order if relevant

### 2. Implement the Change
- [ ] Follow the command module pattern: `parse_args(argv)` and `main(argv=None)`
- [ ] Use `storyforge.runner` for parallel execution if needed
- [ ] Use `storyforge.api` for any Claude API calls
- [ ] Use `storyforge.costs` for cost tracking
- [ ] Use `storyforge.git` for branch/PR workflows

### 3. Maintain Backwards Compatibility
- [ ] Existing CLI flags must continue to work
- [ ] Existing CSV schemas must not change without migration
- [ ] Check for callers of any functions you modify

### 4. Validate
- [ ] Run `python3 -m storyforge <command> --help` to verify CLI
- [ ] Run `python3 -m storyforge <command> --dry-run` if applicable
- [ ] All existing tests pass
- [ ] Wiring tests pass (signatures haven't broken)

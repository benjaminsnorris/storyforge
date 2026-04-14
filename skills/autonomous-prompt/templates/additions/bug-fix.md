## Bug Fix Implementation Steps

### 1. Reproduce the Bug
- [ ] Identify the exact symptoms described in the issue
- [ ] Find the relevant code path
- [ ] Understand why the current behavior is wrong
- [ ] Identify the root cause (not just the symptoms)

### 2. Write a Regression Test
- [ ] Write a test that reproduces the bug (should fail before fix)
- [ ] Test name should describe what was broken
- [ ] Run test to confirm it fails

### 3. Fix the Bug
- [ ] Apply the minimal fix needed
- [ ] Don't refactor surrounding code — fix the bug only
- [ ] Keep the change focused and easy to review

### 4. Verify the Fix
- [ ] Run the regression test — it should now pass
- [ ] Run the full test suite — no regressions
- [ ] Test edge cases related to the fix

### 5. Commit Together
- [ ] **Regression test and fix must be in the same commit** (per CLAUDE.md feedback)
- [ ] Use "Fix" commit prefix

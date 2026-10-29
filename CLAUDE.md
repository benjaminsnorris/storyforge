# Storyforge Plugin Development

Read before working in an area:
- `docs/agent-reference.md` — shared-module table, project data files, commands and skills, skill standards, graphic-novel mode, **interior-illustration invariants (must not break)**, commit prefixes, and the **5-agent PR review workflow** (follow it when asked for "the 5-agent review" or after creating a PR).
- `docs/history.md` — rationale and bug history. Read the matching section before changing cleanup's planner, the YAML helpers, graphic-novel mode, or interior illustrations.
- `docs/plans/2026-10-28-rethink-status.md` — current rethink status and how to resume; read first when working on the rethink.

## Git Rules — MANDATORY
- **Never commit to main.** On `main`, create a `storyforge/{command}-{timestamp}` branch first. On any other branch, stay on it.
- **Commit and push after every change.** Never call something done before it is committed and pushed.
- Commit related changes in logical groups, immediately. Commit uncommitted files before creating branches or PRs.
- Merge PRs with `gh pr merge N --merge --delete-branch` (regular merge, never squash).
- Bump `version` in `.claude-plugin/plugin.json` on every release commit: minor for features, patch for fixes. Commit prefixes: `Add` / `Update` / `Fix` / `Remove`, `Bump version to X.Y.Z`.

## Code Standards
- Commands are `scripts/lib/python/storyforge/cmd_*.py`, registered in `storyforge/__main__.py` (`COMMANDS`), shaped `parse_args(argv)` + `main(argv=None)` with `argparse` (or `cli.base_parser`), `install_signal_handlers()`, `detect_project_root()`. Python 3.10–3.13.
- Every Claude call goes through `storyforge.api`; parallelism through `storyforge.runner` (`run_parallel` returns exceptions as values — check them). Check the shared modules in `docs/agent-reference.md` before writing helpers.
- Report author-owned problems; don't silently repair or delete. Every path that can't check something says so (a finding or WARNING), so silence means "checked and clean". Never warn-and-continue past a failure that makes output wrong.

### Gotchas that have caused real bugs
- `prompts.read_yaml_field(yaml_file, field)` has the **opposite** argument order from `common.read_yaml_field(field, project_dir)`.
- `parse_yaml_scalar` is the only YAML scalar parser. Edit `storyforge.yaml` entries with `update_artifact_entry`, never a regex over the whole file.
- `storyforge.yaml` line endings are **preserved** (`newline=''`, `detect_newline`, write only on change, `\r?\n` patterns). CSVs we write are **forced to LF** (`lineterminator='\n'`).
- Author prose interpolated into a finding `detail` goes through `common.csv_safe` — a `|` corrupts the report CSV.
- Scene files (`scenes/{id}.md`) are pure prose, no frontmatter; metadata lives in `reference/*.csv` (pipe-delimited, `;` for arrays, no quoting). Scene `id` is a permanent event slug, never positional.
- New cleanup step: a `plan_*` function registered in `cmd_cleanup.plan_cleanup` (no `if args.dry_run:` branch; read disk through `DiskFacts`), plus rows in `ARRANGEMENTS` and `TRANSCRIPTS` in `tests/commands/test_cmd_cleanup_dry_run.py`.

## Testing and evals
- `python3 -m pytest tests/` (or `./tests/run-tests.sh`). Fixtures in `tests/conftest.py` (`project_dir` is a writable copy of `tests/fixtures/test-project`). Every fix gets a regression test.
- `python3 evals/run.py` replays the eval suites from recorded API calls (exit 0 pass / 1 gate failed / 2 errored); see `evals/README.md`. A prompt change is a recording miss: re-record that suite.

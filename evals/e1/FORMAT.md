# E1 labeling guide

E1 is the gold set: real continuity errors from the author's book repos, each
with the two sides of the contradiction quoted from the tree where they
coexisted. Read `docs/plans/2026-10-28-storyforge-corpus-survey.md` for the
repo you are labeling before you start — it lists the label sources, the
id-rename commits, and the traps.

Field definitions and the JSON shape are in the docstring of
`evals/e1/__init__.py`. Cases go in `evals/fixtures/e1/cases/<repo>.json`.

## What counts as a case

One case per contradiction a careful reader would notice: fact A established
in one place, fact B contradicting it in another (or the same scene). Use the
error codes in the plan (§4.1). Pick the primary code by what breaks; add a
second code only when two genuinely break.

- **Split bundled fixes.** An audit commit that fixes six things is six cases.
- **Exclude author retcons.** A deliberate change of plan (thornwall's Hessal,
  meridian-line's Lena ↔ Cora swap, understory's 43 → 66 days) is not an error.
- **Exclude non-continuity edits** filed under a continuity pass (voice,
  antithesis culls, motif moves).
- **Exclude plan-vs-prose mismatches** where the prose never contained the
  fact (shared-dark's eval F003 shot finding).
- **Prose cases** quote scene prose on both sides (`level: prose`). A case
  whose contradiction lives only in CSVs or briefs is `level: csv`; label
  those too, but they do not count toward the 100.

## Quotes

- Quote verbatim from the tree at the commit you name: `git -C <repo> show
  <sha>:<path>`. Never paraphrase; the verifier checks every quote.
- `established` and `contradicted` spans name the **fix's parent** (the tree
  where both sides coexisted). Write the parent's full or short sha, never
  `<sha>~1`. For an unfixed case, use the repo's HEAD sha.
- `fix.after` spans name the **fix commit** and quote the corrected text.
- Quote enough to be unambiguous (usually one sentence), not whole paragraphs.
- `scene` is the slug at HEAD even when `path` is a pre-rename numeric file.
  Record every mapping you rely on in `evals/fixtures/e1/id-maps/<repo>.csv`
  (`old_path|slug|commit|method|notes`, pipe-delimited; `method` is `rename`
  when git's rename detection gave it, `content` when you matched by text).
- Prefer commits on `main`. A commit reachable only from a side branch is
  allowed (the verifier checks it exists) but say so in `notes`, since a
  main-only clone loses it.
- `git log -S` skips merge commits; add `-m` when an error may have come back
  through a merge.
- Restrict history searches to scene prose (`git log -S'...' -- scenes/`):
  `manuscript/`, builds, and backups duplicate the text and bury the signal.
- Give a span `"source": "metadata"`, `"csv"`, or `"reference"` when its
  quote is not scene prose (a `timeline_day` line, a CSV row, a bible or
  `key-decisions.md` rule). A prose-level case still needs prose on the
  contradicted side.
- A scene that was later cut has no slug at HEAD: use its last slug (or its
  old path's stem) as `scene` and say "cut" in `notes`.
- A fix that deletes a sentence has nothing to quote: quote the text that now
  stands where it was, and say "deleted" in `notes`.
- A dropped promise (PRM): `established` quotes the promise, `contradicted`
  quotes the scene where it should have been paid off (usually its close).
- A knowledge case whose "established" side is an absence (nothing earlier
  told the character) has `established: []` and says why in
  `established_by_absence`.

## Provenance

- `fix.status`: `fixed`; `incomplete` (the fix left part of the error in
  place — say what in `notes`); `unfixed` (still contradicted at HEAD).
- `fix.rewrite: true` when the error disappeared in a wholesale scene
  rewrite rather than a targeted edit (then `fix.after` may be empty). A fix
  spread over several commits: name the main one in `fix.commit` and give each
  `fix.after` span its own commit.
- `related_cases`: link a regression case to the original error's case (both
  ways), or two cases that share a cause.
- `introduced_by.kind`: `draft` (written in the first draft, author or
  `storyforge write` unknown), `author` (a later author edit), `plan` (a wrong
  brief/bible/tracker that the prose followed), `tool` (a Storyforge pass
  wrote it — set `pass` to the pass name and `commit`), or `unknown`.
- `regressed_by`: commits that reintroduced an error after it was fixed.
- `missed_by`: checks that read the error and passed it — an LLM audit, a
  continuity pass, an evaluator — as `{"pass": ..., "commit": ...}`. These are
  the cases a detector most needs to catch.
- `introduced_by.brief`: for a tool-introduced error that followed a wrong
  brief or bible line, the span-less pointer to it (`reference/scene-briefs.csv:<id>`).
- `subsets`: `author-labeled` when the author flagged it (annotation, read
  notes; put the pointer in `label_source`), `tool-introduced` iff
  `introduced_by.kind == "tool"`, `unfixed-at-head` iff `fix.status == "unfixed"`.
- `confidence`: `high` when both quotes verify and the error is
  unambiguous; `medium` when one side is weak (tracker-only, positional);
  `low` when the "right" answer churned (shared-dark's wake hour).

## Check your work

```bash
python3 evals/e1/cli.py validate
python3 evals/e1/cli.py verify --repo <repo>
python3 evals/e1/cli.py stats
```

Both must pass before committing. Do not edit `holdout.json` by hand; run
`python3 evals/e1/cli.py holdout` once a repo is finished.

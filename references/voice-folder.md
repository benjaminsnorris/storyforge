# The voice folder: `reference/voice/`

A prose book's voice lives in one folder. It is made of passages and notes
that quote them, not a list of rules. In *Wrath Like Smoke*'s voice rounds, a
sample written from a list of things to avoid avoided all of them and read
flat. Passages the author chose, and notes on what they do, worked.

```
reference/voice/
  book.md       # what the voice does, quoting the anchors; the people; decided rules
  anchors/      # passages the author chose or finished by hand, one .md each
  checks.md     # checks run on a finished scene; never in a writing prompt
```

`storyforge init` sets the folder up from templates. So does
`storyforge elaborate --stage voice`, which calls no model: it copies any
missing file (never over one that's there), commits, and says what the voice
still needs.

## When the voice is ready

Drafting needs `book.md` with your text in it (not init's template) and at
least one anchor. Until then `storyforge status` shows a `voice` blocker and
`storyforge write` won't draft at full coaching. A book with a `voice:` block
(an author voice repo, below) is ready with the repo alone.

## `anchors/`

The anchors are the voice spec. Each is one passage, usually 500 to 1,500
words, that you chose or finished by hand: a scene from a sample round, a
page you rewrote yourself, a passage from your own earlier work. The writer
reads all of them and writes toward them.

Different scenes need different anchors. A battle, an intimate scene and a
council read differently, so give each kind of scene you care about its own.

An anchor may start with header lines, before the first blank line:

```
kind: intimate, farewell
tense: present
pov: hector

The passage starts here...
```

- `kind:` what kind of scene it shows. Any words, comma-separated.
- `tense:` `present` or `past`.
- `pov:` whose point of view it is told from.

All three are optional. They tell the writer which anchor is closest to a
scene; nothing else reads them. The header is read only when every line
before the first blank line is one of these keys. Otherwise the whole file is
the passage. An anchor with an empty passage, a key given twice, or a tense
other than present or past is skipped; when no anchor is left, `status`
names why each was skipped.

Files are read in name order. Only `.md` files count.

## `book.md`

What the voice does, said by quoting the anchors. Write it after you have an
anchor. The template has four sections:

- **What it does.** Name a thing the voice does and quote the line that does
  it. "Sentences end on the concrete noun: *'He set the cup down by the
  door.'*" is useful. "Spare, muscular prose" is not: the writer can't aim at
  it.
- **People.** How each POV character thinks and speaks, again with quoted
  lines where you have them. Include the narrator when scenes are told by
  one (`pov` `narrator`): who they are and how close they stand.
- **Decided.** Rules you have settled: person, distance, tense by POV (for
  example, mortals in present, gods in past).
- **Register exemptions.** For a retelling, phrases and scenes that
  `storyforge score --register` should skip: a double-quoted phrase, or
  `scene: <id>` (several with `scenes:`). This replaces the old voice guide's
  register exemptions.

The drafting and revision prompts, the shared system context (evaluation,
scoring, the elaboration stages) and, for the claude CLI, a `voice.md` file
in the evaluation's folder carry `book.md` and every anchor. Hone, which
rewrites brief cells rather than prose, carries `book.md` alone (its first
6,000 characters, said in the log when cut). An anchor file left out (not a
top-level `.md` file, or a header it can't read) is a WARNING in `write`,
`revise`, `evaluate` and `validate`, and a NOTE in `status`.

## `checks.md`

Problems to look for in a finished scene, each with an example taken from
your own marks on a draft. It is for a reviewer reading a finished draft:
you, or Claude in the `elaborate` skill's sample rounds, or the voice
review in a writing session (`storyforge write --session`), which runs it on
each finished scene before the gate. With no checks in the file, no scene
gets a voice review, and the session says so.

The voice review is two agents. A reviewer reads the scene, the voice and
`checks.md`, and flags lines: the words, the check, why. A separate reviser,
in a fresh context, gets `book.md`, the anchors and the flagged lines, never
`checks.md`, and rewrites only those lines toward the anchors, or keeps one
and says why. Code keeps each edit inside the sentence its flag quotes; a
flag whose words aren't in the scene, or an edit outside its sentence, is
dropped and said. What happened to each flag (rewritten, kept, or its edits
refused) is in `working/voice-reviews/<scene>.md`. If the review fails, the
scene goes to the gate without it, and the session lists it at the end.

`storyforge revise --marks FILE` sends your own marks on drafted scenes to
the same reviser. A marks file:

```
## act1-sc03
> He had come all the way down from the house to say it.
cut: reads like AI

> Andromache did not smile.
keep
```

Each `## <scene id>` starts a scene. Each `>` line quotes the scene's
words, copied exactly; lines in a row join into one quote, and a blank line
ends it. The lines after a quote, up to a blank line, are your note. A
quote with no note, or with the note `keep`, `more like this`, `yes`,
`love this` or `perfect`, is a keep: the reviser is shown it as an example
of what works and may never edit it. Any other note asks for a change, and
only those lines are rewritten. A file that can't be read for sure (a
heading that isn't `## <scene id>`, a scene given twice, an empty quote, a
note with no quote above it) is refused, naming the line.

Each scene is then gated against the book as it was before the run, and
committed on a revise branch. A revision the gate rejects, and that can't
be committed provisionally, is rolled back: the old prose stays, and the
record is committed so you can see what was tried. `--dry-run` counts each scene's lines to revise and keeps, and
spends nothing.

**Marking a drafted scene on its PR.** `write --session` drafts onto a
branch with a draft PR. Mark the scenes there, as you marked the voice
rounds, then run `storyforge revise --marks-from-pr N` (first with
`--dry-run`) on that branch, pulled to the PR's head, with nothing
uncommitted under `scenes/` (the run checks all three). Even the dry run
needs the book's voice.

- A scene file holds a paragraph per line, so a line comment marks its
  paragraph. Quote the words you mean (a `>` line, or "words in quotes"
  at the start or end of the comment) to mark just those; a comment over
  several lines marks them all.
- The rest of the comment is your note. No note, or `keep`, `more like
  this`, `yes`, `love this` or `perfect`: a keep.
- A `suggestion` block is your own wording: it's applied as written,
  before the reviser runs, and committed on its own ("Apply the author's
  suggestions on <id>"); an empty one cuts the commented lines. Nothing
  rewrites it, and other comments on its lines are left out. Give one
  suggestion per comment, and keep any illustration marker it covers (one
  that would remove a marker is left out). Its comment's other words are
  shown, not sent.
- A comment that's outdated, on a line that no longer says what it said,
  on a blank line or an illustration marker, or on another file is left
  out and named. Review bodies and conversation comments are listed, not
  sent: they aren't tied to a line.

Only the PR author's comments count (a bot's, or anyone else's, are left
out); a tool that comments with your GitHub login counts as you. The revision
commits and pushes on the PR's branch, so the next round of marks goes on
the same PR. Each scene's record names the comments it acted on (your
suggestions, and the changes the reviser rewrote or kept, saying why), and
the next run leaves those out, naming them; a change it didn't answer, or
a revision rolled back, is sent again; keeps stay
examples while their lines still match. `--since TIME` also leaves out
comments made before a time. A run with nothing left to send exits 1.

`checks.md` never goes into a writing prompt. Writing from a list of things
to avoid makes flat prose: the writer steers away from the list instead of
toward the anchors. Put what you want in `book.md` and the anchors, and what
you don't want here.

## Tense per scene

`scenes.csv` has an optional `tense` column: `present` or `past`. Blank
means not said, and the writer follows the anchors. When it's set, the
drafting prompt states it. Use it when tense follows POV. Speech is as people
speak and doesn't count.

A writing session checks each scene's narration against it, for free. A
scene in the wrong tense goes back to the writer once, for the whole scene
again; still wrong after that, or wrong once the review and the gate have
changed it, stops the session. A scene with too few common verb
forms to judge (under 12) is not checked, and the session says so. A value
other than `present` or `past` is a WARNING in `write`, and that scene's
prompt states no tense. The gate doesn't check tense.

## The old voice files

Earlier versions kept the voice in `reference/voice-guide.md`,
`reference/voice-profile.csv`, `reference/persistent-prompt.md`,
`reference/prose-exemplars.md` and `reference/exemplars/<pov>.md`. A prose
book no longer reads any of them. If your book still has them, `status`,
`write`, `revise`, `evaluate`, `validate` and the voice stage print a NOTE,
and `cleanup`
reports an `old_voice_file` warning. They are never deleted for you: move
what you want to keep into `book.md` or an anchor, then delete them.

Graphic novels are unchanged. Their voice stage still writes
`voice-guide.md` and `voice-profile.csv`, and the script reads them.

## With an author voice repo

A book whose `storyforge.yaml` has a `voice:` block draws on the author's own
voice repo (`references/storyforge-yaml-schema.md`,
`references/voiceprints/README.md`). The repo's description, exemplars and
fiction anchor come first in the writing prompt, then this folder. With a
repo, `book.md` and the anchors are optional, but the book's POV rules,
people and tense still belong in `book.md`.

## Finding anchors

`storyforge voice sample` runs blind sample rounds, in the book, as PRs. One
scene is written several ways, you mark sentences, the next round writes
toward what you kept, and the winner becomes an anchor. The scene must be in
`scenes.csv`; its plan comes from the briefs, as in a writing session. The
book needs no voice yet: round 1 is how it is found. It works for a book in
a subfolder of its repo. At coach or strict coaching Claude writes no
samples; running the command is your choice.

1. **Round 1:** `storyforge voice sample --scene <id>`. One call writes
   `--variants` versions (default 5, 2 to 8) that vary `--vary` (default
   narrator stance, distance, tense), optionally blending `--influences
   "Pressfield, Renault"`. A reply without exactly that many versions, each
   with text, is an error (run it again); nothing is written. They're
   shuffled and labelled `Sample A`, `Sample B`... in
   `working/voice-samples/round-<n>.md`, one sentence per line, committed
   on a branch with a draft PR. `--no-pr` commits without the PR;
   `--dry-run` says what the round would do and spends nothing. Its cost
   line is a rough guess (about $1 for the round, and $0.30 to $0.60 a
   sample for the checks), not a forecast.
2. **Mark it in the PR's Files changed:** a comment on a sentence (keep, cut,
   more like this, a reason), a `suggestion` with your own wording (an empty
   one cuts the line; every suggestion block in a comment is kept), a
   comment on a sample's heading or word-count line for the whole sample, or
   a general reaction in a review, the conversation, or a comment on the
   whole file. **Submit the review**: comments in a review not yet submitted
   can't be read. Every page of comments is read.
3. **The next round:** `storyforge voice sample --from-pr <N>`. It reads the
   marks on the latest round in `working/voice-samples/` (so `N` is that
   round's PR, and it must change that file) and writes a new round toward
   the keeps and your wordings, not away from the cuts: a round that only
   avoided the cuts came out flat. The scene, influences and vary list carry
   over from the last round unless given.
4. **A take:** `--from-pr <N> --take B --versions "present tense;past
   tense"` revises one marked sample toward its marks, in versions that
   differ only in that one named thing (or two points of view). Name at
   least two, all different; `--take` needs `--versions`. Each version is
   headed by its name (`## present tense`), so the next round, or
   `--promote --sample "present tense"`, names it. After a round or two a
   take teaches more than another five blends.
5. **The winner:** `--promote working/voice-samples/round-<n>.md --sample B
   --name <name> [--kind K] [--tense present|past] [--pov P]` saves it as
   `anchors/<name>.md`, with those header lines, and commits it on a branch
   (never `main`). It reads the round file as it is now, so finish the
   sample by hand in the file first, and pull the branch if you edited it
   on GitHub. The sample is checked as an anchor before anything is
   written: an empty one is refused, even with `--force`, which otherwise
   replaces an anchor of that name. `--dry-run` writes nothing. Then say in
   `book.md` what it does, quoting it.

**How the marks are read.** `--from-pr` reads the round file as it is at
the PR's head, and refuses if your copy differs (edits or suggestions
committed on GitHub): pull the branch first, so the marks are read against
the same text. Only the PR author's comments count; a bot's or anyone
else's are left out and counted in a NOTE. General comments made before
the round was committed are left out (an earlier round's reactions). A
line comment is placed only when its line still says what GitHub showed;
one on a line since changed is counted and left out. A PR with none of its
author's marks on the round is refused, unless `--allow-unmarked`. A
latest round file that isn't committed as it is is refused.

**The key is kept outside the repo**, under
`~/.storyforge/voice-sample-keys/<book folder>-<hash of its path>/round-<n>.json`:
the round, its scene, what it varied and blended, what each sample tried,
the take, the round it came from, and a hash of its samples. Another clone
or worktree of the book has its own. It is saved only after the round is
committed, and no command shows it to you: you mark blind; the next round's
writer is given it. A round with no key here (made elsewhere) still runs,
from your marks without what each sample tried (a NOTE), and needs
`--scene`. A key whose hash doesn't match the round's samples (the round
was edited or remade) isn't used (a NOTE). A key that can't be read is an
error.

**Each sample is checked before you see it:** the blocking read (one
reading, for physical slips: hands, what is held, where people are) and,
when `checks.md` has checks, the voice review against it. A separate
reviser rewrites only the flagged lines. What was found, fixed and left
out (flags whose words aren't in the sample, unverified findings, any
check that didn't finish) is listed in the PR's description. The round's
spend is logged as `voice-sample`, the blocking reads as
`voice-sample-check`, the reviews as `voice-review`.

Each round is its own branch and PR: off `main`, or, run from a round's
branch, off that branch. If the branch or the PR can't be made, it's an
error (exit 1); the round is committed by then if only the PR failed.

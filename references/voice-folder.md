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

The drafting prompt, revision prompts, evaluation, hone and the elaboration
prompts all carry `book.md` and every anchor.

## `checks.md`

Problems to look for in a finished scene, each with an example taken from
your own marks on a draft. It is for a reviewer reading a finished draft:
you, or Claude in the `elaborate` skill's sample rounds. The long writing
sessions (#655) will run it on each finished scene.

`checks.md` never goes into a writing prompt. Writing from a list of things
to avoid makes flat prose: the writer steers away from the list instead of
toward the anchors. Put what you want in `book.md` and the anchors, and what
you don't want here.

## Tense per scene

`scenes.csv` has an optional `tense` column: `present` or `past`. Blank
means not said, and the writer follows the anchors. When it's set, the
drafting prompt states it. Use it when tense follows POV. Speech is as people
speak and doesn't count. A free check of the narration against it is coming
with the gate.

## The old voice files

Earlier versions kept the voice in `reference/voice-guide.md`,
`reference/voice-profile.csv`, `reference/persistent-prompt.md`,
`reference/prose-exemplars.md` and `reference/exemplars/<pov>.md`. A prose
book no longer reads any of them. If your book still has them, `status`,
`write`, `revise`, `evaluate` and `validate` print a NOTE, and `cleanup`
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

`storyforge voice sample` (#654, coming) will run blind sample rounds as a
PR. Until it exists, the `elaborate` skill's Voice Stage runs them by hand:
one scene written several ways, unlabelled, one sentence per line so you can
mark sentences in the PR. Later takes revise toward what you kept. You
finish the winner by hand and save it in `anchors/`.

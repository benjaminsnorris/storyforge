# Voiceprints

A voiceprint is a writer's measurable habits (plan
`docs/plans/2026-11-08-deterministic-gate-and-voiceprint.md`, Part B). The
fingerprint is code, free and deterministic: `storyforge.voiceprint`
(`scripts/lib/python/storyforge/voiceprint.py`, whose docstring lists every
measure and the API).

| Path | What |
|---|---|
| `baseline.json` | The general baseline: each measure's mean and standard deviation over a population of writers (the distance's scale) and the population's n-gram rates (what a writer says more often than writers do). Built by `voiceprint.build_baseline` |
| `austen/` | The reference voiceprint, in the author voice repo layout (B0): `voice.yaml`, `corpus/`, `fingerprint.json`, `description.md`, `exemplars/`, and `proposals/` (the model's draft claims and shortlist they came from). Storyforge's worked example and the fixture of `tests/test_voiceprint_reference.py` and `tests/test_voiceprint_description.py` |

The tests' other texts are in `tests/fixtures/voiceprint/`: `verne/` (two
translations) and `others/` (excerpts from seven other authors).

## The Austen reference voiceprint

`fingerprint.json` is the fingerprint of *Pride and Prejudice* alone; *Emma*
and *Persuasion* are held out, the tests' unseen Austen.
`test_reference_fingerprint_is_current` fails when the code would compute a
different one. To recompute it:

```python
from storyforge import voiceprint as vp
text = open('references/voiceprints/austen/corpus/pride-and-prejudice.md', encoding='utf-8').read()
vp.fingerprint({'corpus/pride-and-prejudice.md': text}).save('references/voiceprints/austen/fingerprint.json')
```

The corpus texts are Project Gutenberg's, normalized by `storyforge.gutenberg`
(the code behind `storyforge source fetch`): the Gutenberg header and
licence stripped, front matter and contents dropped, `# ` headings, one
paragraph per line. Configs:

| File | Gutenberg | Config |
|---|---|---|
| `pride-and-prejudice.md` | 42671 (Chapman's 1813 text) | the evals repo's `corpus/pride-and-prejudice/meta.json`; byte-identical to the evals' `manuscript.md` |
| `emma.md` | 158 | `{"chapter_heading": "^CHAPTER ([IVXLC]+)$", "part_heading": "^VOLUME ([IVX]+)$", "part_format": "Volume {}", "skip_from": ["^FINIS$"]}` |
| `persuasion.md` | 105 | `{"chapter_heading": "^CHAPTER ([IVXLC]+)\\.$", "skip_from": ["^Finis$"]}` |

## The test texts

- `tests/fixtures/voiceprint/verne/`: *Around the World in Eighty Days*
  (Gutenberg 103; the header names the translator, George M. Towle, 1873) and
  *Five Weeks in a Balloon* (Gutenberg 3526; Appleton, 1869; the header names
  no translator, the title page says "Done into English by 'William
  Lackland'"). Normalized with the evals repo's `meta.json` for each;
  byte-identical to the evals' `manuscript.md`.
- `tests/fixtures/voiceprint/others/<book>/01.md`..`10.md`: ten chunks of
  about 2,000 words (`voiceprint.chunks`), evenly spaced through each of the
  evals' manuscripts of *The Age of Innocence* (Wharton), *The Brimming Cup*
  (Dorothy Canfield Fisher), *A Christmas Carol* (Dickens), *The Great
  Gatsby* (Fitzgerald), *Middlemarch* (Eliot), *The Plastic Age* (Percy
  Marks) and *Self-Control* (Mary Brunton, 1811, Austen's contemporary).

Together the texts here and in the fixtures are about 4 MB (2.0 MB of Austen
and baseline, 0.9 MB of Verne, 0.9 MB of excerpts).

## The baseline

`baseline.json` comes from 28 public-domain books by writers the tests don't
use, 1719 to 1920, British and American, fiction and essays (the list, with
Gutenberg numbers, is its `sources`): twelve chunks of each, evenly spaced,
for the measures' population figures, and the whole books for the n-gram
rates. Only the derived figures are committed. To rebuild it (after a change
to a measure: `load_baseline` refuses a baseline missing a measure, and the
reference fingerprint test fails), download each `sources` book's plain text
from `https://www.gutenberg.org/cache/epub/<n>/pg<n>.txt` into an empty
folder, then:

```python
texts = {name: vp.population_text(open(path, encoding='utf-8').read()) for name, path in ...}
json.dump(vp.build_baseline(texts), open(vp.BASELINE_REL, 'w'), indent=1, ensure_ascii=False)
```

It's a 19th- and early 20th-century baseline. A modern writer's phrases
("you know", "a lot of") will read as over-represented against it; the
distance's scale is less affected, since it is each measure's spread across
writers, not its level.

## The tests and their numbers

`tests/test_voiceprint_reference.py`, free, about 6 s. Measured 2026-11-08;
each floor sits below the result with a margin.

| Test | Measured | Floor or threshold |
|---|---|---|
| 1. Held-out Austen chunks (117 from *Emma* and *Persuasion*) nearest Austen among eight authors | 117/117 = 1.000 | 0.95 |
| 1. The same with Austen fingerprinted from ten chunks, as many as each other author: ten spread through *Pride and Prejudice* / its first ten | 115/117 = 0.983 / 109/117 = 0.932 | 0.93 / 0.85 |
| 1. Other authors' chunks (70, each left out of its author's fingerprint) nearest their own author | 62/70 = 0.886 | 0.80 |
| 1. Other authors' chunks nearest Austen | 1/70 (a *Middlemarch* chunk) | at most 2 |
| 1. Ranked by distance from Austen alone: held-out Austen ahead of the others (AUC) | 1.000 | 0.97 |
| 1. The same against Brunton's *Self-Control* alone | 1.000 | 0.95 |
| 2. *Pride and Prejudice*'s two halves | 0.168 apart | share a voice (`SAME_VOICE_MAX` 0.30) |
| 2. Disjoint contiguous samples of her three novels in a row (every non-overlapping pair of windows on a half-window grid): 10k / 25k / 50k / 75k / 100k words | worst 0.799 / 0.501 / 0.362 / 0.257 / 0.207; median 0.415 / 0.301 / 0.240 / 0.212 / 0.160 (3486 / 325 / 55 / 21 / 10 pairs) | `MIN_CORPUS_WORDS` = the smallest size whose worst pair shares a voice: 75,000 |
| 3. The Verne translations | 0.368 apart: two voices | `SAME_VOICE_MAX` 0.30 |
| 3. Austen's novels in pairs | 0.209, 0.225, 0.226 | share a voice |
| 3. Each Verne translation's halves | share a voice | |
| 3. 16 Austen chunks + 4 of another author's (7 authors x 3 novels = 21 corpora) reported inconsistent | 18/21 | 0.75 |
| 3. Seeded chunks named | 63/84 = 0.75 | 0.60 |
| 3. Austen chunks named | 0 | 0 |
| 3. Pure Austen corpora (20 chunks of each novel): the minority's separation | 0.589-0.618: consistent | `OUTLIER_SEPARATION` 0.85 |
| 3. Pure Austen corpora of 20 pieces of `MIN_PIECE_WORDS` (1,500) words, through `consistency` | 0.560-0.680: consistent (1,000-word pieces reach 0.906, which is why the minimum is 1,500) | `OUTLIER_SEPARATION` 0.85 |

The three seeded corpora not reported inconsistent are *Pride and
Prejudice* seeded with *Middlemarch* (separation 0.808) and with
*Self-Control* (0.737), and *Persuasion* with *Self-Control* (0.843): Eliot
and Brunton are the other authors nearest her. The flagged corpora's
separations run 0.874 to 1.468; where fewer than four seeded chunks are
named, the split found a smaller minority (one or two of them).

The Verne pair is two voices because what the fingerprint reads in a
translation is the translator's English. A real author's corpus can mix
voices the same way: ghostwritten posts, quoted material, a decade of drift.

## The described voice and the exemplars (B3, B4, #651)

`storyforge voice propose`, run in a voice repo, shows a model a sample of
the fingerprinted corpus (15 runs of about 2,000 words, evenly spaced; every
paragraph numbered, with its word count) and the fingerprint's figures beside
other writers', and makes two calls (`storyforge.voiceprint_proposals`,
`common.select_model('synthesis')`). Neither prompt names the author.

1. **The description.** Claims of one sentence each, in five sections (what
   the voice does, never does, its stance toward the reader, its humour, its
   rhythm), each with a short example, go to `proposals/description-claims.csv`
   (`id|section|claim|example|mark`). The author writes `yes` or `no` in
   `mark` for every claim, rewording a claim before keeping it if they like.
2. **The shortlist.** The model names 30 runs of consecutive paragraphs (100
   to 400 words, tagged by job: description, argument, turn, humour, quiet,
   dialogue); the code cuts each from the corpus as written, refuses a run
   that is out of the sample, crosses a break, overlaps another or is the
   wrong length (each named), and measures each against the fingerprint. They
   go to `proposals/shortlist.csv`
   (`id|job|source|paragraphs|words|distance|limit|typical|why|pick`) and
   `proposals/shortlist/<id>.md`. The author writes `yes` in `pick` for
   each passage to keep, and may trim a passage's file.
3. `storyforge voice accept` writes `description.md` (the claims marked yes,
   by section; an unmarked claim stops it) and copies the picks to
   `exemplars/<id>.md`, indexed in `exemplars/exemplars.csv`. Free.

A passage is **typical** when its distance from the fingerprint is at most
the 90th percentile of the corpus's own passages of its size (bands of 100,
150, 200 and 300 words; short passages vary far more than the fingerprint's
2,000-word chunks). On Austen the limits are 0.95, 0.90, 0.87 and 0.82;
held-out *Emma* passages fall inside 89% of the time, the seven other
authors' 14%. `storyforge voice judge` measures the shortlist again after
the fingerprint changes (free).

Each call costs about $0.32 on Opus 5.5 for the Austen sample (67k tokens of
input each: the two calls' schemas differ, and a structured-output schema is
part of the cached prefix, so they can't share a cache).

### The Austen description and exemplars

**Nobody marked or picked them.** Ben wasn't there to mark claims or pick
passages, so both follow the rule the tests define:

- **Claims** are marked `no` when they assert something the critic's list
  rejects (`reference_mark` in `tests/test_voiceprint_description.py`) and
  `yes` otherwise. The recording has none the list rejects, so
  `description.md` keeps all 22.
- **Exemplars** are `voiceprint_proposals.auto_picks` (`voice accept
  --auto-pick`): every typical passage, topped up to 20 with the nearest of
  the rest. 27 of the 30 are typical, so 27 are exemplars, spanning all six
  jobs.

An author's own marks and picks replace both.

### Tests 4 and 5 (`tests/test_voiceprint_description.py`)

**Test 4, the description**, checks the recorded claims against a fixed
list of what a critic says of Austen's narrative voice, matched by patterns
on the claim text (a match preceded closely by a negation doesn't count).
The list was written and committed before the recording.

| The critic says yes (a positive claim must assert it) | Required |
|---|---|
| an ironic narrator | yes |
| free indirect discourse (by name, or the narration taking on a character's words or mind) | yes |
| balanced, periodic or antithetical sentences | yes |
| aphoristic generalisation | |
| wit, comedy or satire | |
| abstract, evaluative vocabulary | |
| little physical description (a positive claim that it's sparse, or a `never` claim about it) | |

| The critic says no (no positive claim may assert it) |
|---|
| plain, short sentences |
| lush description |
| stream of consciousness |

Gate: every required item, at least 5 of the 7, and no rejected one.

| Recording | Affirmed | Missed | Rejected |
|---|---|---|---|
| The committed one (2026-11-08) | 5 of 7, all three required | aphoristic generalisation, wit/comedy/satire | 0 |
| A first recording, discarded when the requests lost their cache mark (above) | 6 of 7 | aphoristic generalisation | 0 |

The misses are the patterns', not the model's: the committed claims say
"dry general verdicts on human conduct, delivered as settled fact" and
"deadpan anticlimax", which a critic would count as aphorism and comedy. The
list stays as it was fixed; it's a floor on a keyword proxy, not a reading.

**Test 5, the shortlist** (free): 20 to 40 passages of 100 to 400 words, each
the corpus as written; at least 75% typical (measured 27 of 30, 90%); at
least five of the six jobs and none over 40% (measured all six, five
passages each).

### Re-recording

The cassette `tests/fixtures/voiceprint/cassette/` holds the two calls'
requests and replies. `test_recording_is_the_committed_proposals` parses the
recorded replies against the recorded sample (found again in the corpus,
`voiceprint_proposals.recorded_sample`), so a change to the fingerprint or
the sampling doesn't invalidate the recording. It fails when a prompt, a
schema or the system block's opening (`SYSTEM_PREAMBLE`) changes: re-record
then, on purpose (about $0.65):

```bash
rm -r tests/fixtures/voiceprint/cassette references/voiceprints/austen/proposals
STORYFORGE_CASSETTE=$PWD/tests/fixtures/voiceprint/cassette STORYFORGE_CASSETTE_MODE=record \
    ./storyforge voice propose --dir references/voiceprints/austen --model claude-opus-5-5
rm -r tests/fixtures/voiceprint/cassette/82   # the Models API listing, unused by the test
```

then mark the claims by the critic's list and accept:

```bash
PYTHONPATH=scripts/lib/python:tests python3 -c "
import dataclasses, test_voiceprint_description as t
from storyforge import voiceprint_proposals as vpp
d = 'references/voiceprints/austen'
vpp.write_claims(d, [dataclasses.replace(c, mark=t.reference_mark(c)) for c in vpp.read_claims(d)])"
./storyforge voice accept --dir references/voiceprints/austen --auto-pick
```

Update
`RECORDED_MODEL` if the model changed, and record test 4's result here. If
the fingerprint changes, `voice judge` and `voice accept --auto-pick` bring
the shortlist's figures and the exemplars up to date for free.


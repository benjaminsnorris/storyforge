# Pilot: re-gate pre-fix prose before the redraft

A runbook for the pilot named in [ISSUES.md](ISSUES.md), "Before a redraft". The fixes it tests are on main (#732–#748, except #746's second half; #749 is PR #768).

Everything marked **proposal** is for Ben to confirm or change before the run.

## What it decides

1. **The fixed gate no longer makes the false stops the review found.** Re-gate the first-gated (pre-fix) prose of eight *Wrath Like Smoke* scenes and compare with the review's verdicts ([A](A-log-census.md) §2, [B](B-typed-state.md)).
2. **The gate's default check method:** `tandem` (the default since #738, PR #767) or `open`. The thing to watch is the question layer's false stops: it stopped about 0.48 of `gate-set-questions`' controls. Switching is one line, `gate.GATE_CHECK_METHOD`.
3. **Extraction thinking** (#743, PR #765): `gate.EXTRACT_THINK = True` (the default) or `False`; `check` takes `--extract-thinking` / `--no-extract-thinking` to set it for one run. Thinking off was faster and cheaper, but it lost about 15 of 333 continuity rows on 13 prompts, mostly a scene's last state changes. E3 was 42/7/0 with it off and 43/5/1 with it on (`docs/history.md`, #743).

## Limits

- **`check` never fixes.** Every `check` run is a first run, so the pilot measures first-run findings and stops, not fix rounds. Under `tandem` a stop sends the scene into the fix loop, and only `write` runs that loop. Watch fix rounds in the redraft's first session.
- **The open checker's new findings have no labels.** The review's open-checker verdicts are for the Nov 8 draft, whose prose is gone. Judge each new open finding by reading it, and mark it `unlabelled` in the table.
- **Namesakes and speech.** #746's alias half (patronymics at `source import`) is still open, and #749 is PR #768. If #768 hasn't merged, a false finding on a claim in speech is expected: tag it `#749` rather than counting it against the fixes. Run after #768 merges if you can.

## Prerequisites

- `~/Developer/iliad-adult` (the book) with its `working/logs/session/` and `working/logs/gate/` from the 2026-11-16/17 overnight run. They are gitignored, so they exist only on the machine that ran it.
- The source project at the path in the book's `storyforge.yaml` `source:` block (`../homer`). The path is relative, so the throwaway clone must sit next to the book.
- A storyforge checkout of current `origin/main` (one whose `storyforge check --help` lists `--no-extract-thinking`), and `ANTHROPIC_API_KEY`.

```bash
git -C ~/Developer/storyforge fetch origin
git -C ~/Developer/storyforge worktree add ~/Developer/sf-pilot origin/main
PY=python3.12   # storyforge needs Python 3.10-3.13; a bare python3 may be 3.9
sf() { "$PY" ~/Developer/sf-pilot/storyforge "$@"; }   # a function, so it works in zsh and bash
OUT=~/Developer/iliad-adult-pilot-results; mkdir -p "$OUT"

# throwaway clone, next to the book so ../evals and ../homer resolve; no remote, so nothing is pushed
git clone -q ~/Developer/iliad-adult ~/Developer/iliad-adult-pilot
cd ~/Developer/iliad-adult-pilot && git remote remove origin
sf source import          # picks up the source registry's death_scene (#761); commits locally
sf cleanup --dry-run      # lists the death_scene fills (#745, #761: about 229, against 44 from the ledger alone):
sf cleanup                # apply them here (the redraft will have them); commits locally
git tag pilot-base
export STORYFORGE_COST_THRESHOLD=1.25   # one scene's run fits; the re-checks after it mostly don't
```

There is no dry-run or no-commit option for `check`. A passing scene commits its facts and the report, `commit_and_push` warns when the push fails, and the commit stays in the clone. A scene that passes and changes facts can list later scenes for a re-check. The low threshold leaves those re-checks unrun. If one does run, note its cost apart and leave it out of the comparison.

**Base state (proposal):** the clone is the book at its current main. The scenes before each pilot scene are post-fix, and the ledger also holds later scenes' facts. The review's replay used the commit before each scene's commit instead. If findings against later scenes dominate, re-run that scene on `git checkout <scene's commit>^` (run `source import` and `cleanup` there too).

## Rebuild each scene's pre-fix prose

The pre-fix prose is what the gate first read: the session writer's reply, plus the voice reviser's edits. `scenes/{id}.md` in git holds only post-fix prose. Rebuild it from the logs, the way report A did:

```bash
SID=hector-duels-ajax
SESS=$(ls -d ~/Developer/iliad-adult/working/logs/session/*/ | while read d; do ls "$d" | grep -q "write-$SID.json" && echo "$d"; done | tail -1)
PYTHONPATH=~/Developer/sf-pilot/scripts/lib/python $PY - "$SESS" "$SID" "$OUT/$SID.prefix.md" <<'EOF'
import glob, json, os, sys
from storyforge.api import extract_text_from_file
from storyforge.session import parse_reply
from storyforge import voice_review
sess, sid, out = sys.argv[1:]
reply = sorted(glob.glob(os.path.join(sess, f'*-write-{sid}.json'))
               + glob.glob(os.path.join(sess, f'*-rewrite-{sid}.json')))[-1]  # a tense rewrite wins
prose = parse_reply(extract_text_from_file(reply), sid).prose
rev, revise = (os.path.join(sess, f'{sid}-{k}.json') for k in ('review', 'revise'))
if os.path.exists(revise):
    flags = voice_review.parse_review(extract_text_from_file(rev), prose).flags
    prose = voice_review.apply_revision(prose, flags, json.loads(extract_text_from_file(revise))).prose
open(out, 'w', encoding='utf-8').write(prose)
print(out, len(prose.split()), 'words')
EOF
```

**Check before spending.** Every first-run (`.`) quote that the scene's rows in report A §2 list must appear in the rebuilt file (`grep -F`). If one is missing, the rebuild is wrong. The usual cause is the wrong session folder or reply (a later session that wrote the scene again), or a review or revise reply from another run. Don't run that scene until it's fixed.

## The scenes

Six scenes with false stops, and two that check recall. The first-run (pre-fix) findings come from A §2. ✗ is a finding the review judged false, ✓ real, ~ debatable.

| Scene | First-run findings then | Fixed by | Pass if (proposal) |
|---|---|---|---|
| `hector-duels-ajax` | ✗ possession Q34 (helmet), Q35 (bow): two objects of one kind. ✗ promise Q36, Q37: promise worded as the later state ("carries", "wears") | #732, #748; promises #740 (partly) | no possession finding; record whether Q36/Q37 still stop it |
| `diomedes-spears-ares` | ✓ blocking Q20 (strap), Q21 (throws, then keeps hold), Q22 (ichor). ✗ possession Q23 (Ares's spear). Extraction `ends` on a state the scene sets up (B §6; it caused the halt) | #732, #734 | Q20–Q22 still found; no possession; `ends here` NOTE, no halt |
| `andromache-mourns-a-living-man` | ✗ life Q33 ("the boy": Astyanax matched to the dead Adrestus) | #733, #745 | passes |
| `diomedes-and-odysseus-raid` | ✗ life Q55 (Rhesus's death throes read as presence after death). ✗ injury Q56 (Diomedes's healed shoulder) | #733 | passes |
| `polydamas-reads-the-eagle` | ✗ injury Q72 (Hector's shield arm, three days on) | #733 | passes |
| `idomeneus-fights-at-the-ships` | ~ blocking Q82, Q83. ✗ life Q84 (the second Pisander). ✗ possession Q85 (a line in speech given to the wrong speaker), Q86 (shield of one kind) | #733/#745, #732/#748 | no life or possession finding; Q82/Q83 may stand |
| `hector-breaks-the-gate` (recall) | ✓ blocking Q79 (left/right after turning). ✓ time Q80 ("two days ago" is three) | none; must keep | both found |
| `aphrodite-drives-helen-to-bed` (recall, promise) | ✓ blocking Q7 (Paris already on the bed). On the re-check, ✗ promise Q8 ("Aphrodite rescued Paris", the previous scene's fact) | #740 | Q7 found; Q8's promise not asked |

The blocking read and the typed checks are the same in both modes, so Q7, Q20–22, Q79 and Q80 test the fixes, not the method.

## Runs

For each scene: three runs, each from `pilot-base`. Copy the outputs out before resetting.

```bash
cd ~/Developer/iliad-adult-pilot
run() {   # run MODE_DIR FLAG...
  local mode=$1; shift
  git reset -q --hard pilot-base && git clean -fdxq   # puts back the tracked cost ledger and clears working/'s ignored logs
  cp "$OUT/$SID.prefix.md" "scenes/$SID.md"
  /usr/bin/time -p "$PY" ~/Developer/sf-pilot/storyforge check "$SID" "$@" 2> "$OUT/$SID.$mode.time"
  mkdir -p "$OUT/$SID.$mode" && cp -R working/check-report.md working/logs/check "$OUT/$SID.$mode/"
  diff <(git show pilot-base:working/costs/ledger.csv) working/costs/ledger.csv | sed -n 's/^> //p' > "$OUT/$SID.$mode/costs.csv"   # this run's rows only
}
run tandem --tandem
run open --open
run tandem-nothink --tandem --no-extract-thinking
```

`--no-extract-thinking` sets `gate.EXTRACT_THINK` to False for that run only (the extraction call and its #734 retry); nothing in the checkout is edited, and the other runs keep the default (thinking on). A message pointing to `check --pending` from that run carries the flag.

## What to record

From each run's `check-report.md` (findings are tagged `[open checker]`, `[questions]` or `[open checker and questions]` under tandem), its `logs/check/<scene>/<stamp>/` folder, `costs.csv` (the cost ledger's rows this run added, since the ledger is tracked and holds the book's earlier spend: `cost_usd`, `duration_s` per call) and the `time` file:

| Scene | Mode | Findings (code, checker, Q# if in A) | Real / false / debatable / unlabelled | Stopped? On what | Tandem NOTEs | Cost $ | Wall s | Extract rows (state) |
|---|---|---|---|---|---|---|---|---|
| hector-duels-ajax | tandem | | | | | | | |
| hector-duels-ajax | open | | | | | | | |
| hector-duels-ajax | tandem-nothink (`--tandem --no-extract-thinking`) | | | | | | | |

Summary rows per mode: false stops (a scene stopped only by false findings), real catches kept (of Q7, Q20–22, Q79, Q80), new real catches, questions-only findings (true/false), total cost, median wall time.

**Thinking on and off.** Diff the two tandem runs' extraction replies (`gate-extract-<scene>.json`). For each state row the thinking-on run has in the scene's last quarter (holding, location, condition, knowledge, an `ends`), check that the thinking-off run has it. Also compare any finding or stop that differs.

## Decision rules (proposals)

- **Fixes confirmed:** across the eight scenes, no stop rests on a false possession, injury, life, same-scene-`ends` or earlier-scene-promise finding, and Q7, Q20–22, Q79 and Q80 are all found. A false namesake or speech finding counts against #746 or #749, not this. If the rule fails, file it against the issue named and hold the redraft.
- **Keep `tandem`** if the questions-only findings add at most 1 false stop over `open` across the eight, or if they add a real catch `open` missed and at most 2 false stops. **Switch to `open`** if they add 2 or more false stops and no real catch. At 0.48 per control scene, the eval rate would predict 3 or 4 false stops in eight.
- **Turn thinking off** only if no end-of-scene state change is lost in any of the eight scenes, and no real finding or stop differs. Otherwise keep it on. The speed (about 42 s down to 16 s) and about $3 over the book are not worth a lost state change.

## Results (run 2026-11-26)

Run on storyforge 1.205.0 (main 360a6996b, after #768 and #773) against a remote-less clone of iliad-adult main, with `source import` and `cleanup` applied (231 `death_scene`s filled). All 24 runs and the extra blocking reads cost **$17.04**, against the $13 estimate. Raw results: [pilot-results/](pilot-results/README.md).

### Decisions

1. **Fixes confirmed: no.** The rule has two halves.
   - *Passed: the false stops are gone.* No run of the 24 made a possession, injury, life, same-scene-`ends` or earlier-scene-promise finding. Report A's first runs of these scenes had 10 (Q23, Q33, Q34, Q35, Q55, Q56, Q72, Q84, Q85, Q86). Q8's promise was not asked as an earlier scene's.
   - *Failed: recall.* Q20, Q21 and Q80 were found in every run, but Q7 in 2 of 3, Q79 in 1 of 3 and **Q22 in none**. The blocking read alone, run 5 more times, found Q22 3 of 5, Q7 3 of 5 and Q79 4 of 5. Each is caught by about 0.2–0.3 of single readings.
   - Not caused by any fix. The blocking request is byte-identical to Nov 16, with the same prompt and model, so this is the read's own run-to-run recall.
   - Filed as **#774** against #626 (the blocking read). **Hold the redraft** until Ben decides it.
2. **Check method: keep `tandem`.**
   - *Questions-only findings:* 6 over the 16 tandem-mode runs, all false, and no real catch the open checker missed. They were 2 promises worded as the later state (Q36/Q37's pattern: `hector-has-ajax-belt`, `ajax-has-hector-sword`), 3 #769 source entering-state facts, and 1 knowledge fact read against "He took everything else in the city".
   - *False stops they add over `open`:* 0 with thinking on, 1 with thinking off. That one is `polydamas-reads-the-eagle`, stopped only by a source entering-state fact; `open` passed the scene.
   - At most 1, so keep `tandem`. The control rate of 0.48 predicted 3 or 4.
3. **Extraction thinking: keep it on.** The rule is "no end-of-scene state lost, and no real finding or stop differs".
   - *State rows: none lost.* All 28 thinking-on state rows in the scenes' last quarter have a thinking-off row; 8 needed checking by hand.
   - *Stops: they differ in three scenes.* `aphrodite-drives-helen-to-bed` passed with thinking on and stopped on Q7 with it off. Most of the difference is the run-to-run variance of the blocking read, the open checker and the question layer: `open`, also thinking on, varies the same way.
   - *One difference is the extraction's own.* Thinking off made a blocking `EXTRACTION` misquote on `andromache-mourns-a-living-man`, a quote across two adjacent lines that dropped the second line's opening quotation mark. The 16 thinking-on extractions made none.
   - *The saving is small.* Extraction output fell from 6,298 to 3,130 tokens a call. The gate's Sonnet spend fell from $1.68 to $1.41 for the eight scenes, and the median gate wall time from 147 s to 137 s, since extraction now runs beside the other calls.
4. **#769's source facts** are listed as their own category below. The 64 asked a run made 3 false findings, all one fact: Zeus's order that Hector hold back until Agamemnon is wounded, from Book 11, asked in Books 12 and 13 after the condition is met. They caused 1 false stop. The momentary combat states, such as "brandishes two spears", made none. **#775** proposes filtering by kind (conditional orders and constraints), not age. It is not implemented.

### Per run

Verdicts: R real, F false, D debatable, U unlabelled (judged by reading the prose, as given). `[Q]` marks a questions-only finding and `[O]` the open checker's. Extraction rows are given as total (state).

| Scene | Mode | Blocking findings | Verdicts | Stopped? On what | Cost $ | Wall s | Extract rows |
|---|---|---|---|---|---|---|---|
| hector-duels-ajax | tandem | BLK spear held after the throw (new); PRM `hector-has-ajax-belt` [Q] | R; F | yes, on R | 1.28 | 169 | 26 (10) |
| hector-duels-ajax | open | BLK spear (new); BLK Ajax has no free hand for the belt (Q40's kind) | R; R | yes, on R | 0.83 | 135 | 30 (13) |
| hector-duels-ajax | tandem-nothink | BLK Agamemnon "first" to stand, already up; PRM `ajax-has-hector-sword` [Q] | D; F | yes, on D and F | 0.74 | 163 | 29 (14) |
| diomedes-spears-ares | tandem | BLK Q20, Q21 (Q22 missed); no possession, no `ends` halt | R; R | yes, on R | 0.75 | 163 | 38 (20) |
| diomedes-spears-ares | open | BLK Q20, Q21 (Q22 missed) | R; R | yes, on R | 0.76 | 174 | 41 (17) |
| diomedes-spears-ares | tandem-nothink | BLK Q20, Q21 (Q22 missed) | R; R | yes, on R | 0.65 | 141 | 44 (26) |
| andromache-mourns-a-living-man | tandem | TRT Andromache a bound captive at Thebe, against her sheet [O] | U, judged R | yes, on R | 0.48 | 96 | 19 (7) |
| andromache-mourns-a-living-man | open | TRT the same | U, judged R | yes, on R | 0.46 | 86 | 18 (7) |
| andromache-mourns-a-living-man | tandem-nothink | EXTRACTION misquote; TRT the same [O]; KNO "He took everything else in the city" against the lyre fact [Q] | F; R; F | yes, on R | 0.46 | 91 | 17 (6) |
| diomedes-and-odysseus-raid | tandem | none | | passed | 0.86 | 186 | 33 (20) |
| diomedes-and-odysseus-raid | open | none | | passed | 0.67 | 167 | 20 (13) |
| diomedes-and-odysseus-raid | tandem-nothink | none | | passed | 0.77 | 158 | 23 (18) |
| polydamas-reads-the-eagle | tandem | BLK Sarpedon's hands on two shoulders while he tightens straps | D | yes, on D | 0.52 | 111 | 18 (14) |
| polydamas-reads-the-eagle | open | none | | passed | 0.52 | 78 | 16 (13) |
| polydamas-reads-the-eagle | tandem-nothink | PHY source fact: Zeus's order to hold back [Q] | F (source entering state) | **yes, on F alone** | 0.50 | 132 | 17 (14) |
| idomeneus-fights-at-the-ships | tandem | BLK second spear; BLK Q83 | D; D | yes, on D | 1.01 | 253 | 40 (16) |
| idomeneus-fights-at-the-ships | open | BLK Q83 | D | yes, on D | 0.90 | 169 | 32 (14) |
| idomeneus-fights-at-the-ships | tandem-nothink | BLK Q83; PHY source fact: Zeus's order [Q] | D; F (source entering state) | yes, on D and F | 0.90 | 195 | 36 (26) |
| hector-breaks-the-gate | tandem | TIM Q80 [O]; BLK Q81; PHY source fact: Zeus's order [Q] (Q79 missed) | R; R; F (source entering state) | yes, on R | 0.55 | 130 | 14 (11) |
| hector-breaks-the-gate | open | TIM Q80; BLK Q81; BLK Q79 | R; R; R | yes, on R | 0.50 | 97 | 18 (17) |
| hector-breaks-the-gate | tandem-nothink | TIM Q80 [O]; BLK doors on torn hinges; BLK Q81 (Q79 missed) | R; D; R | yes, on R | 0.56 | 119 | 18 (16) |
| aphrodite-drives-helen-to-bed | tandem | none (Q7 missed) | | passed | 0.47 | 74 | 18 (9) |
| aphrodite-drives-helen-to-bed | open | BLK Q7 | R | yes, on R | 0.36 | 62 | 17 (11) |
| aphrodite-drives-helen-to-bed | tandem-nothink | PRM `paris-rescued-by-aphrodite`, this scene's own fact [O and Q]; BLK Q7 | D; R | yes, on R | 0.51 | 78 | 17 (11) |

- **Tandem NOTEs.** All 16 tandem runs said only "the open checker (2 readings) and the questions both read it". The two checkers disagreed on no dispute.
- **Q36/Q37.** Neither promise is now asked as another scene's (#740). But one of the two pair facts (`hector-has-ajax-belt`, `ajax-has-hector-sword`) stops the scene as a questions-only broken promise in each tandem run, worded as the later state. The scene also stopped on other findings, so neither was a false stop here. In a fix loop, though, it would hold the scene after the real finding is fixed.
- **Advisory promises** (non-blocking) are not counted. Most were the brief's book-level facts that no scene shows, such as "Pandarus broke the truce oath".

### Summary per mode

| | tandem | open | tandem, thinking off |
|---|---|---|---|
| False stops (stopped only by false findings) | 0 | 0 | 1 (polydamas, source entering state) |
| Real catches kept, of Q7, Q20–22, Q79, Q80 | 3 of 6 (Q7, Q22, Q79 missed) | 5 of 6 (Q22 missed) | 4 of 6 (Q22, Q79 missed) |
| New real catches | 2 (hector-duels-ajax spear; andromache's capture, unlabelled) | 3 (spear, Ajax's hands, andromache) | 1 (andromache) |
| Questions-only findings (true / false) | 0 / 2 | n/a | 0 / 4 |
| Source entering-state findings (#769; true / false) | 0 / 1 | n/a | 0 / 2 |
| Scenes passed | 2 | 2 | 1 |
| Total cost | $5.91 | $5.00 | $5.08 |
| Median wall time | 147 s | 116 s | 137 s |

Blocking-read recall across all runs ([blocking-recall.csv](pilot-results/blocking-recall.csv)): Q20 and Q21 8/8 runs, Q7 5/8, Q79 5/8, Q22 3/8.

## Cost

Per scene and run: extraction about $0.13 with thinking on and about $0.05 off; the open checker about $0.30–0.60 (two readings; #741 made the second cheaper, and a warm one-hour cache helps the next run); the blocking read $0.07; typed state, questions and source check a few cents.

| Runs | Estimate |
|---|---|
| tandem, 8 scenes | about $5 (ISSUES.md's figure covers this alone) |
| open, 8 scenes | about $4 |
| tandem with thinking off, 8 scenes | about $4 |
| **Total** | **about $13; stop at $20** |

Pre-approved re-records don't cover this: it needs Ben's go. To spend less, run `--open` only on the scenes where tandem's questions-only findings stopped the scene.

## Clean up

```bash
rm -rf ~/Developer/iliad-adult-pilot                     # nothing was pushed
git -C ~/Developer/storyforge worktree remove ~/Developer/sf-pilot
```

Keep `$OUT` until the decisions are recorded: in `docs/history.md` under #738 and #743, and on this page.

## What's left after the pilot

In order.

### 1. Flip the defaults the pilot decides

**Done (2026-11-26): nothing to flip.** The rules keep both defaults: `GATE_CHECK_METHOD` stays `tandem`, and `EXTRACT_THINK` stays True (see Results). `e3-extraction` does not join step 2.

One small PR each, with a `docs/history.md` entry under #738 or #743 giving the pilot's numbers:

- `gate.GATE_CHECK_METHOD = 'open'`, only if the rule above says switch. Also update the comment above it, `cmd_check`'s docstring, `cli.add_check_method_args`' help ("the default") and the skills that name the default.
- `gate.EXTRACT_THINK = False`, only if the rule says so. This re-keys E3 and the gate sets' extraction requests, so add `e3-extraction` to the re-record below (about $2.80). Also update the comment above it and `cli.add_extract_thinking_args`' help ("the default"). Not flipping it still leaves `--no-extract-thinking` (and `--extract-thinking` once off is the default) on `check`, `write` and `revise` for a one-off run; that needs no re-record, since the default's requests are unchanged.

Bump the version (patch for each).

### 2. Consolidated eval re-record (Ben pre-approved about $130)

**Partly done (2026-11-27).** Only the suites with no blocking-read call were re-recorded, since #774 may change `BLOCKING_READINGS`. That would re-key every blocking call, so recording those suites first would pay twice.

- **Which suites make the call.** In the code, `blocking.check_blocking` is reached only through `gate.gate_scene`, `check --blocking`, the blocking set and `voice_sample`; in the evals, only through the gate and the blocking set. In the recordings, the blocking prompt is in `e4-generation`, `e8-revision-safety`, `gate-set`, `gate-set-questions` and `blocking-set`, and in no other cassette.
- **Re-recorded, $17.39 in all** (`--mode auto`, cheapest first, the reason line below):

  | Suite | Spent | Forecast |
  |---|---|---|
  | `question-set` | $0.05 | $0.05 |
  | `e5-roundtrip` | $4.55 | $4.50 |
  | `e2-carol-checker` | $5.23 | $5.86 |
  | `recheck-set` | $7.56 | $7.88 |

  Floors are from run 1. What moved is in `docs/history.md`, "The consolidated re-record, without the blocking calls".
- **Deferred until Ben decides #774.** Each makes blocking-read calls. Forecasts are for `--runs 3`:

  | Suite | Forecast | Basis |
  |---|---|---|
  | `gate-set-questions` | about $35 | its full recording; no baseline figure (stale) |
  | `gate-set` | about $100–130 | about $43 a run; its extraction and open-checker requests changed (#741, #749), so a top-up is close to a full record |
  | `e4-generation` | about $75 | $24.79 a run in the baseline |
  | `e8-revision-safety` | about $166 | $55.35 a run in the baseline |
  | **Total** | **about $375–405** | **past the $130 pre-approval, of which $17.39 is spent** |

  A third blocking reading would add about $0.035 a scene to each (half the two-reading read's $0.07, "Cost" above). Ben chooses what to record, and with what budget.
- **`baseline.json`** holds the four re-recorded suites' new entries. `--baseline` refuses while `gate-set` and `gate-set-questions` are stale with no old measurement to carry. Run it once those are recorded.

After step 1 and after #768, since each changes the requests. #769 adds no miss of its own (no recorded suite is an adaptation), so it doesn't hold this step. There is no forecast-only option, and `--over-budget` skips the budget check, so the harness won't stop at $130 for you.

- **Forecast by hand first:** sum `usd_if_live` for each suite in `evals/baseline.json`, times 3 for the frozen ones (`gate-set`, `gate-set-questions`, `e4-generation`, `e8-revision-safety`). A suite with no figure counts as $0 (the stale gate sets have none), so the sum is a lower bound. Use the figures below for those two.
- **Run the suites one at a time, cheapest first, and check the spend after each** (the run's summary, or `cost.usd_spent` in `evals/results/latest.json`). Stop and ask Ben once the running total would pass $130. E4 and E8 are stale at their first drafting prompt, so their top-up is close to a full re-record (about $75 and $165 for three runs). Pass `--over-budget` only to a suite that the running total still has room for.

```bash
R=(--over-budget "Ben approved the consolidated re-record (checker review, 2026-11-26)")
$PY evals/run.py --mode auto --suite question-set "${R[@]}"                 # cents
$PY evals/run.py --mode auto --suite e5-roundtrip "${R[@]}"                 # about $4.50
$PY evals/run.py --mode auto --suite e2-carol-checker "${R[@]}"             # about $6
$PY evals/run.py --mode auto --suite recheck-set "${R[@]}"                  # about $8
$PY evals/run.py --mode auto --suite gate-set-questions --runs 3 "${R[@]}"  # private; frozen, so --runs 3 is required; $35 was its full recording
$PY evals/run.py --mode auto --suite gate-set --runs 3 "${R[@]}"            # private; about $100 in full
$PY evals/run.py --mode auto --suite e4-generation --runs 3 "${R[@]}"
$PY evals/run.py --mode auto --suite e8-revision-safety --runs 3 "${R[@]}"
$PY evals/run.py --baseline        # replay everything, write evals/baseline.json
```

- **Where the recordings live.** `gate-set`, `gate-set-questions` (and `blocking-set`, `typed-state-set`) record into the private storyforge-evals clone (`STORYFORGE_PRIVATE_EVALS_DIR`, default `~/Developer/evals`). The rest record into this repo's `evals/fixtures/cassettes/` (E4 and E8 runs 2 and 3 into `fixtures/e6/run2`, `run3`). Commit each repo's recordings on a branch, open a PR in each, and merge both together: a storyforge main whose suites expect recordings the private repo doesn't have yet reads as unavailable.
- **Floors.** Set each changed metric's floor from run 1 in the same commit: `FLOORS` in `evals/suites/gate_set.py`, `gate_set_questions.py` and `question_set.py`, and `e2.FLOORS['e2-carol-checker']`. A metric that moved gets a line in `docs/history.md`. The three-run spread is in `consistency.py`'s report.

### 3. Add the blocking read's 38 findings to `blocking-set` (#744 follow-up; about $20, approved)

PR #753 left these out because the set is frozen. Report A §2's `blocking` rows are 38 distinct findings: 29 real, 9 debatable.

- **What to add:** each one as a case in storyforge-evals `blocking-set/` (the case files and the build script there, and `blocking-set/README.md` for how cases are found). Skip any that duplicate one of the 70 Wrath cases already in the set (match by quote). Label the 9 debatable ones so they can stay out of recall.
- **The prose.** Many quotes are in fix-round prose, which isn't in the book's git history. Rebuild it as above, then apply each logged `gate-fix-<scene>.json` edit in order (`session.parse_reply`/`gate.apply_edits`; report A's replay matched the committed prose byte for byte this way).
- **Record:** `$PY evals/run.py --mode record --suite blocking-set --runs 3 "${R[@]}"`. Then replay run 1, copy the private `results/latest.json` to `baseline-cases.json`, and set `FLOORS` and `RECORDED` (`blocking_set.fingerprint` / `.recordings`) in `evals/suites/blocking_set.py` (evals/README.md, "Private suites"). Raise `MIN_CASES` with the new size. As in step 2, both repos merge together.

### 4. Open follow-ups

States checked 2026-11-26.

| Issue | State | What's left |
|---|---|---|
| #746 | open | Second half: fill `aliases` with patronymics and standing epithets at `source import` (`source.py`), from a series-repo table whose format isn't defined yet. The namesake guard itself merged (PR #754) |
| #761 | open | (a) is done: the source registry (`evals/projects/iliad/reference/characters.csv`) gives `death_scene` for 233 Iliad deaths, and `source import` then `cleanup` fills 229 in the book (Hector and Patroclus stay warnings, which the author sets; iliad-adult PR 27 fixed the wrong Dolops and Melanippus ids in `ajax-holds-the-ships`). Left: (b), sending a death the draft leaves out to the source author list (that needs the gate's source check, a model call) |
| #769 | merged (PR #773) | The question layer asks the source's entering state with the brief's entering items (the latest 10 a scene, counted toward the cap of 30). It adds no recording miss: no recorded suite is an adaptation. Its acceptance case is a unit test, so the pilot is its first measurement: watch findings whose source is `source iliad:<scene>`. **Measured by the pilot:** 64 asked a run, 3 false findings (one conditional order) and 1 false stop. #775 proposes filtering by kind |
| #774 | open (from the pilot) | The blocking read finds real catches only intermittently: Q22 3/8 runs, Q7 5/8, Q79 5/8. It fails the recall half of "fixes confirmed" and **holds step 5** until decided. If it changes `BLOCKING_READINGS`, the blocking calls in `blocking-set` and the gate sets change too, so decide it before step 2 |
| #775 | open (from the pilot) | Leave conditional orders and constraints out of the source facts the question layer asks. It changes no recorded suite (none is an adaptation) |
| #749 | merged (PR #768) | A claim in speech is not narration. Its recording misses are in step 2 |

Follow-ups named in the merged PRs (#751–#767), not filed. Each is either a judgement call for Ben or waits on something else:

- **PR #751:** a fungible-kinds rule (spear, arrow and stone need a stated count). It would clear P31 but also drop the debatable P36.
- **PR #752:** a scene with disputes and one without still don't share a cache prefix. The open checker's disputes and endings sections appear only when there is something to rule.
- **PR #753:** typed-state recall isn't measured. The set holds only each scene's final run, and the one real typed catch (Q80) is on a first run. Seeded errors are the issue's "later" item.
- **PR #758:** a typed begin/end timeline of the source's facts (about $1.50 on Haiku) was left for later. Retrieval is enough for now.
- **PR #765:** the thinking switch covers the gate's extraction only. The typed-state (Haiku) call and `extract` phase 4 are untouched.
- **PR #767:** a recorded tandem eval (`gate-set-tandem`, replaying from the two gate sets' recordings) needs step 2 first.

### 5. Redraft *Wrath Like Smoke*

**Held (2026-11-26)** on #774: the pilot's recall half of "fixes confirmed" failed.

With the defaults decided and the evals green, redraft. Watch the first session's fix rounds, the stops per scene, and any finding of a kind the pilot cleared. The phantom-injury lines in iliad-adult PR 23 go with the redraft (README, "Decisions for Ben").

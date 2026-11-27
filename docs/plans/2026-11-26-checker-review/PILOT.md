# Pilot: re-gate pre-fix prose before the redraft

A runbook for the pilot named in [ISSUES.md](ISSUES.md), "Before a redraft". The fixes it tests are on main (#732–#748, except #746's second half; #749 is PR #768).

Everything marked **proposal** is for Ben to confirm or change before the run.

## What it decides

1. **The fixed gate no longer makes the false stops the review found.** Re-gate the first-gated (pre-fix) prose of eight *Wrath Like Smoke* scenes and compare with the review's verdicts ([A](A-log-census.md) §2, [B](B-typed-state.md)).
2. **The gate's default check method:** `tandem` (the default since #738, PR #767) or `open`. The thing to watch is the question layer's false stops: it stopped about 0.48 of `gate-set-questions`' controls. Switching is one line, `gate.GATE_CHECK_METHOD`.
3. **Extraction thinking** (#743, PR #765): `gate.EXTRACT_THINK = True` (the default) or `False`. Thinking off was faster and cheaper, but it lost about 15 of 333 continuity rows on 13 prompts, mostly a scene's last state changes. E3 was 42/7/0 with it off and 43/5/1 with it on (`docs/history.md`, #743).

## Limits

- **`check` never fixes.** Every `check` run is a first run, so the pilot measures first-run findings and stops, not fix rounds. Under `tandem` a stop sends the scene into the fix loop, and only `write` runs that loop. Watch fix rounds in the redraft's first session.
- **The open checker's new findings have no labels.** The review's open-checker verdicts are for the Nov 8 draft, whose prose is gone. Judge each new open finding by reading it, and mark it `unlabelled` in the table.
- **Namesakes and speech.** #746's alias half (patronymics at `source import`) is still open, and #749 is PR #768. If #768 hasn't merged, a false finding on a claim in speech is expected: tag it `#749` rather than counting it against the fixes. Run after #768 merges if you can.

## Prerequisites

- `~/Developer/iliad-adult` (the book) with its `working/logs/session/` and `working/logs/gate/` from the 2026-11-16/17 overnight run. They are gitignored, so they exist only on the machine that ran it.
- The source project at the path in the book's `storyforge.yaml` `source:` block (`../homer`). The path is relative, so the throwaway clone must sit next to the book.
- A storyforge checkout of current `origin/main`, and `ANTHROPIC_API_KEY`.

```bash
git -C ~/Developer/storyforge fetch origin
git -C ~/Developer/storyforge worktree add ~/Developer/sf-pilot origin/main
PY=python3.12   # storyforge needs Python 3.10-3.13; a bare python3 may be 3.9
sf() { "$PY" ~/Developer/sf-pilot/storyforge "$@"; }   # a function, so it works in zsh and bash
OUT=~/Developer/iliad-adult-pilot-results; mkdir -p "$OUT"

# throwaway clone, next to the book so ../homer resolves; no remote, so nothing is pushed
git clone -q ~/Developer/iliad-adult ~/Developer/iliad-adult-pilot
cd ~/Developer/iliad-adult-pilot && git remote remove origin
sf cleanup --dry-run      # if it lists death_scene fills (#745), the book hasn't had them yet:
sf cleanup                # apply them here (the redraft will have them); commits locally
git tag pilot-base
export STORYFORGE_COST_THRESHOLD=1.25   # one scene's run fits; the re-checks after it mostly don't
```

There is no dry-run or no-commit option for `check`. A passing scene commits its facts and the report, `commit_and_push` warns when the push fails, and the commit stays in the clone. A scene that passes and changes facts can list later scenes for a re-check. The low threshold leaves those re-checks unrun. If one does run, note its cost apart and leave it out of the comparison.

**Base state (proposal):** the clone is the book at its current main. The scenes before each pilot scene are post-fix, and the ledger also holds later scenes' facts. The review's replay used the commit before each scene's commit instead. If findings against later scenes dominate, re-run that scene on `git checkout <scene's commit>^` (run `cleanup` there too).

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
run() {   # run MODE_DIR FLAG
  git reset -q --hard pilot-base && git clean -fdxq   # puts back the tracked cost ledger and clears working/'s ignored logs
  cp "$OUT/$SID.prefix.md" "scenes/$SID.md"
  /usr/bin/time -p "$PY" ~/Developer/sf-pilot/storyforge check "$SID" "$2" 2> "$OUT/$SID.$1.time"
  mkdir -p "$OUT/$SID.$1" && cp -R working/check-report.md working/logs/check "$OUT/$SID.$1/"
  diff <(git show pilot-base:working/costs/ledger.csv) working/costs/ledger.csv | sed -n 's/^> //p' > "$OUT/$SID.$1/costs.csv"   # this run's rows only
}
run tandem --tandem
run open --open
# thinking off: a local one-line edit in the pilot checkout only, reverted straight after
sed -i '' 's/^EXTRACT_THINK = True$/EXTRACT_THINK = False/' ~/Developer/sf-pilot/scripts/lib/python/storyforge/gate.py
run tandem-nothink --tandem
git -C ~/Developer/sf-pilot checkout -- scripts/lib/python/storyforge/gate.py
```

There is no flag or environment variable for `EXTRACT_THINK`; it is a constant. Do the edit in the `sf-pilot` worktree, never in a shared checkout. Running all eight scenes thinking-off back to back is cheaper than toggling per scene. A `--extract-think` flag is a possible follow-up if this comparison is ever repeated.

## What to record

From each run's `check-report.md` (findings are tagged `[open checker]`, `[questions]` or `[open checker and questions]` under tandem), its `logs/check/<scene>/<stamp>/` folder, `costs.csv` (the cost ledger's rows this run added, since the ledger is tracked and holds the book's earlier spend: `cost_usd`, `duration_s` per call) and the `time` file:

| Scene | Mode | Findings (code, checker, Q# if in A) | Real / false / debatable / unlabelled | Stopped? On what | Tandem NOTEs | Cost $ | Wall s | Extract rows (state) |
|---|---|---|---|---|---|---|---|---|
| hector-duels-ajax | tandem | | | | | | | |
| hector-duels-ajax | open | | | | | | | |
| hector-duels-ajax | tandem-nothink | | | | | | | |

Summary rows per mode: false stops (a scene stopped only by false findings), real catches kept (of Q7, Q20–22, Q79, Q80), new real catches, questions-only findings (true/false), total cost, median wall time.

**Thinking on and off.** Diff the two tandem runs' extraction replies (`gate-extract-<scene>.json`). For each state row the thinking-on run has in the scene's last quarter (holding, location, condition, knowledge, an `ends`), check that the thinking-off run has it. Also compare any finding or stop that differs.

## Decision rules (proposals)

- **Fixes confirmed:** across the eight scenes, no stop rests on a false possession, injury, life, same-scene-`ends` or earlier-scene-promise finding, and Q7, Q20–22, Q79 and Q80 are all found. A false namesake or speech finding counts against #746 or #749, not this. If the rule fails, file it against the issue named and hold the redraft.
- **Keep `tandem`** if the questions-only findings add at most 1 false stop over `open` across the eight, or if they add a real catch `open` missed and at most 2 false stops. **Switch to `open`** if they add 2 or more false stops and no real catch. At 0.48 per control scene, the eval rate would predict 3 or 4 false stops in eight.
- **Turn thinking off** only if no end-of-scene state change is lost in any of the eight scenes, and no real finding or stop differs. Otherwise keep it on. The speed (about 42 s down to 16 s) and about $3 over the book are not worth a lost state change.

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

One small PR each, with a `docs/history.md` entry under #738 or #743 giving the pilot's numbers:

- `gate.GATE_CHECK_METHOD = 'open'`, only if the rule above says switch. Also update the comment above it, `cmd_check`'s docstring, `cli.add_check_method_args`' help ("the default") and the skills that name the default.
- `gate.EXTRACT_THINK = False`, only if the rule says so. This re-keys E3 and the gate sets' extraction requests, so add `e3-extraction` to the re-record below (about $2.80).

Bump the version (patch for each).

### 2. Consolidated eval re-record (Ben pre-approved about $130)

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
| #761 | open | #745's follow-up: fill `death_scene` in the source project's own registry, and send a death the draft leaves out to the source author list (that needs the gate's source check, a model call) |
| #769 | PR open | The question layer asks the source's entering state with the brief's entering items (the latest 10 a scene, counted toward the cap of 30). It adds no recording miss: no recorded suite is an adaptation. Its acceptance case is a unit test, so the pilot is its first measurement: watch findings whose source is `source iliad:<scene>` |
| #749 | PR #768 open | A claim in speech is not narration. Its recording misses are in step 2 |

Follow-ups named in the merged PRs (#751–#767), not filed. Each is either a judgement call for Ben or waits on something else:

- **PR #751:** a fungible-kinds rule (spear, arrow and stone need a stated count). It would clear P31 but also drop the debatable P36.
- **PR #752:** a scene with disputes and one without still don't share a cache prefix. The open checker's disputes and endings sections appear only when there is something to rule.
- **PR #753:** typed-state recall isn't measured. The set holds only each scene's final run, and the one real typed catch (Q80) is on a first run. Seeded errors are the issue's "later" item.
- **PR #758:** a typed begin/end timeline of the source's facts (about $1.50 on Haiku) was left for later. Retrieval is enough for now.
- **PR #765:** the thinking switch covers the gate's extraction only. The typed-state (Haiku) call and `extract` phase 4 are untouched.
- **PR #767:** a recorded tandem eval (`gate-set-tandem`, replaying from the two gate sets' recordings) needs step 2 first.

### 5. Redraft *Wrath Like Smoke*

With the defaults decided and the evals green, redraft. Watch the first session's fix rounds, the stops per scene, and any finding of a kind the pilot cleared. The phantom-injury lines in iliad-adult PR 23 go with the redraft (README, "Decisions for Ben").

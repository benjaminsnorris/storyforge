# Report B: typed-state checks and the blocking read

Research agent report, 2026-11-26, on *Wrath Like Smoke* (iliad-adult) gate logs. Read-only; no model calls. The fix numbers in section 4 were traced by hand, not run (see "How far to trust this").

## Summary

**Possession made no real catch: 36 distinct findings (48 across rounds), 0 real, 2 debatable, 34 false.** They account for 13 findings in `gate-pending.csv`. Five scenes are pending for nothing else, and one turned the `diomedes-spears-ares` slip into the session halt.

**Mechanism histogram (possession):**

| Mechanism | Count |
|---|---|
| Generic kind ("shield", "spear"), different people's own items, same scene | 22 |
| One handover recorded as two records on the same quote | 4 |
| Handover in the scene missed or dropped | 3 |
| Generic kind across scenes | 2 |
| Generic kind, same holder "lost then has" | 2 |
| Remnant or retelling of a destroyed object | 2 |
| Implied handover, bearer to owner | 1 |

The root cause is that Haiku names items by bare kind despite the prompt, and `check_possession` keys on that kind.

**Blocking read: 46 distinct findings, 41 real, 5 debatable, 0 false.** At least 3 slips were created by gate fixes. Reading 2 alone found about 14.

**Recorded evals:**
- The blocking read has recall 0.6154 and 1.27 false alarms per 10k words.
- The stage sheet has recall 0.2222 and 15.65 false alarms per 10k words.
- Both replayed free and passed.
- Typed state has no eval suite at all.

**Other typed-state checks:**
- **Place and sky** produced nothing: this book has no `reference/world.csv`.
- **Injury** carried Hector's momentary "shield arm" for 42 days, and the fixes wrote a lingering injury into five scenes. Ben should review those lines.
- **Life** made 6 findings, all false.

**Recommended fixes, ranked:**

1. **Owner-scoped object identity, handover pairing, unknown-after-misquote, destroyed semantics.** Removes 33 of 34 false findings and keeps both debatable ones. Code only, about a day with tests; no re-recording.
2. **`ends` guard.** An `ends` naming a fact the same scene sets up is not an extractor slip, and extractor slips should earn the re-extraction even when other findings exist. Code only, a few hours.
3. **Injury decay and severity; life check bound to character ids.** Code plus one prompt line.
4. **Identity question before a possession finding blocks** (Haiku, asked twice). Under $0.01 a finding, but a new call, so the gate-set needs a small top-up. Its effect is an estimate, not measured.
5. **Extractor prompt: name the owner, one record per handover.** Needs a re-extraction of the book (about $0.50) and a gate-set top-up (about $1). This is what makes Achilles' armour trackable in the remaining 40 scenes.

Keep the blocking read as it is, with two readings.

**What stays with the model:** the rules are already deterministic. Reading prose into events, object identity and physical plausibility cannot be done by code; the stage sheet's numbers show that.

**Confidence:**
- **High** on the possession classification (every finding read against the prose) and the mechanisms.
- **Medium** on blocking: 27 of 46 were checked against the passage, the rest judged from the quote pairs and the writer's fixes.
- **Medium** on the fix numbers: they were traced by hand through the rule, because the disk filled before the prototype could run.
- **Cross-scene findings are approximate:** they were rebuilt against today's typed-state files.

Scope: the gate runs of 2026-11-15 to 11-17 in `iliad-adult/working/logs/gate` and `logs/check` (56 runs, 134 gate rounds). Read-only; no model calls. One free replay of `blocking-set` and `blocking-set-sheet`.

## How far to trust this

- **Findings were rebuilt, not read from a log.** The gate logs hold replies only, and `overnight-write.log` prints only each scene's last round. `collect.py` re-ran `continuity.run_checks` on every logged `gate-state-*.json` reply and read every `gate-blocking-*.json` reply. The rebuilt last-round findings match all 14 rows of `gate-pending.csv`.
- **Cross-scene findings are approximate.** They were rebuilt against today's `working/typed-state/` files, not the files as they stood that night. This affects 2 possession findings (P28, P30), the life findings and the cross-scene injury findings.
- **Each round's prose was reconstructed** by undoing the logged fix edits from the final scene file.
- **The proposal tests in section 4 were traced by hand**, one finding at a time. None is a measured run.
- **Blocking classifications:** 27 of 46 were checked against the passage. The other 19 were judged from the quoted pair and the writer's fix, without reading the prose between the two quotes.

## 1. How the findings are produced

### Typed state (Haiku extraction, then code)

- **The call.** `typed_state.extract` (`typed_state.py:318-352`) makes one structured call. The gate log shows `claude-haiku-5-5`, about 10.9k tokens in and 12k out, 9.8k of that thinking.
- **The prompt** is `typed_state.PROMPT` (`:125-148`): the scene, the cast from `characters.csv`, the calendar, facts the POV may not know, "Injuries in force", and "Objects other scenes track".
- **The schema** (`:105-123`) is a list of `{type, who, item, value, detail, quote}`. Types are `alive, at, holds, knows, injury, uses, named, elapsed`.
- **The `holds` instruction** (`:141`) asks for "a particular object a later scene could track (a named weapon, the ring, the letter, Hector's helmet; not "a spear" among many)", with values `gets/has/gives/loses/destroyed`.
- **Haiku ignores the "not a spear among many" clause.** Every logged reply names items by bare kind: `spear`, `shield`, `helmet`, `sword`, `bow`, `cloak`.
- **Quote handling.** Each quote is checked with `quotes.quote_in`. A misquoted record is kept as `verified=False` and makes no finding. Records are ordered by where the quote stands in the prose (`place_in_prose`, `:233-248`); ties fall back to reply order.
- **Storage.** One file per scene, `working/typed-state/<scene>.json` (`STATE_DIR` `:75`, `write_state` `:367-380`), keyed by `prose_sha256` and `prompt_sha256`. A file is reused only while both match (`current_state` `:436-462`).
- **Carried state.** There is no separate state table. `continuity.load_book` (`continuity.py:1154-1229`) reloads every other scene's file on each check, and each check folds the records in story order.
- **Stage-sheet hands** join possession only from an *extracted* sheet (`sheet_holdings` `:484-524`). This book has 57 `*.writer.json` sheets and no extracted ones, so none were used.

### Possession rule

`continuity.check_possession` (`continuity.py:276-361`) folds all `holds` records per object key and checks this scene's records against the state before each.

- **The key** is `stage_sheet._obj` (`stage_sheet.py:385-390`): lower case, with articles and possessive pronouns stripped. So "his shield" becomes `shield`.
- **`_slot`** (`continuity.py:265-273`) also merges a bare name into a qualified one through `same_object` (`stage_sheet.py:392-402`). So `sword` merges with `hector sword`.
- **Three rules block:**
  - any non-`gets` record on an object whose status is `destroyed` (`:313-314`);
  - `has/gives/loses/destroyed` by a person while another person holds the object, in the same scene (`:316-318`);
  - the same holder using an object they gave away or lost (`:322-324`).
- **A different holder across scenes is only a note** (`:320`).

### Place and sky

- **Place** (`check_place`, `:535-602`) compares `at` records with the last place through `locations.csv` and the distance and speed rows of `reference/world.csv`.
- **Sky** (`check_sky`, `:1050-1082`) is a regex list (`_SKY`, `:1031-1047`) checked against `world.csv` directions. It makes no model call.
- **Both are inert in this book.** `iliad-adult/reference/world.csv` does not exist, and neither check produced a finding in 134 rounds. The logs carry notes such as "21 presence record(s) at a place locations.csv doesn't name".

### Blocking read

- **The call.** `blocking.check_blocking` (`blocking.py:197-237`) runs on the checking model (Opus). It makes two independent readings (`BLOCKING_READINGS = 2`, `:47`) and takes their union, de-duplicated by `_same` (`:123-130`).
- **The prompt** (`:68-98`) sends the scene alone. It asks the model to track hands, left and right, posture, what is worn, objects, light and doors.
- **It reports three kinds:** `contradiction` (both places quoted), `impossible` and `unclear`. It also carries a "what not to report" list: "When in doubt, leave it out".
- **The schema** (`:51-66`) is `{kind, scene_quote, other_quote, explanation}`. A quote not in the scene makes the finding `unverified` (`to_finding`, `:152-171`).

### Stage sheet

`stage_sheet.py` is the alternative blocking method: Haiku records events, code replays them (`replay`, `:538`), and yes/no questions are asked twice. It is off by default (`gate.GATE_BLOCKING_METHOD = 'read'`, `gate.py:99`).

### The gate

- Extraction, the blocking read and the typed state run together (`gate.py:1655-1681`).
- `_merge_continuity` (about `gate.py:3702`) adds typed findings unless the same code already covers the same words.
- All of them block (`GATE_BLOCKING` `:91`, `GATE_CONTINUITY` `:106`).

### Not part of the gate

`scoring_state.py` holds the scoring-override and verdict files. `world_table.py` only loads `world.csv`.

## 2. The findings, classified

### Possession: 36 distinct findings, 48 across rounds

| Verdict | Count |
|---|---|
| Real | 0 |
| Debatable | 2 |
| False | 34 |

**What they cost:**
- 13 of them are in `gate-pending.csv`, across 8 of the 14 pending scenes.
- 5 scenes are pending for nothing else: `menelaus-drags-paris`, `hector-finds-paris-at-home`, `diomedes-and-odysseus-raid`, `polydamas-counsels-a-pause`, `zeus-wakes-on-ida`.
- One possession false positive also turned the `diomedes-spears-ares` slip into a session halt (section 6).

**The full list.** Rounds: f = first, r = recheck, r2 = recheck-2.

| # | Scene | Object | Finding | Rounds | Verdict | Mechanism |
|---|---|---|---|---|---|---|
| P1 | diomedes-spears-ares | spear | Ares loses, Athena holds | check f, r2 | False | Generic kind: Athena's own spear and Ares's thrown one |
| P2 | diomedes-spears-ares | spear | Diomedes has, Athena holds | f, r | False | Generic kind |
| P3 | patroclus-watches-the-idle-days | cloak | Phoenix has, Automedon holds | check f | False | Generic kind |
| P4 | achilles-watches-from-the-stern | shield | Eurypylus has, Ajax holds | f | False | Generic kind |
| P5 | agamemnon-proposes-flight | cloak | Odysseus has, Nestor holds | f | False | Generic kind |
| P6 | ajax-fells-hector | sword | Ajax has (Hector's gift, silver studs), Poseidon holds | f, r, r2 (pending) | False | Generic kind: a unique object merged with Poseidon's sword |
| P7 | ajax-fells-hector | shield | Hector has, Ajax holds | f, r2 (pending) | False | Generic kind |
| P8 | ajax-holds-the-ships | shield | Teucer has, Ajax holds | f | False | Generic kind |
| P9 | ajax-holds-the-ships | helmet | Ajax has, Teucer holds | r | False | Generic kind |
| P10 | apollo-raises-hector | whip | Cebriones gives, Hector holds | f | False | One handover recorded twice |
| P11 | diomedes-and-odysseus-raid | bow | Diomedes gives, Odysseus holds | r2 (pending) | False | Two bows under one key (Dolon's in the tamarisk, Odysseus's own); Diomedes's pick-up not recorded |
| P12 | glaucus-and-diomedes-trade-armour | helmet | Glaucus has, Diomedes holds | f | False | Generic kind |
| P13 | hector-duels-ajax | helmet | Hector and Paris, both ways | f, r, r2 (pending) | False | Generic kind |
| P14 | hector-duels-ajax | bow | Helenus has, Paris holds | f, r2 (pending) | False | Generic kind |
| P15 | hector-duels-ajax | sword | Hector and Ajax, each drawing his own | r, r2 (pending) | False | Generic kind |
| P16 | hector-finds-paris-at-home | bow | Paris has, Helenus holds | r | False | Generic kind |
| P17 | hector-finds-paris-at-home | robe | Theano has, Hecuba holds | r2 (pending) | False | Handover on the page but its record dropped |
| P18 | hector-fires-the-ships | sword | Patroclus has (Achilles's), Hector holds | r2 (pending) | False | Generic kind |
| P19 | idomeneus-fights-at-the-ships | spear | Idomeneus destroys, already destroyed | f | False | Extraction error: Meriones's line "I broke mine" given to Idomeneus and recorded as a new event |
| P20 | idomeneus-fights-at-the-ships | shield | Alcathous has, Idomeneus holds | f | False | Generic kind |
| P21 | menelaus-drags-paris | spear | Paris "has", Menelaus holds | f | False | Throw not recorded; a spear lodged in a shield recorded as `has` |
| P22 | menelaus-drags-paris | sword | Menelaus loses the hilt, sword destroyed | r2 (pending) | False | Remnant of a destroyed object (Homer 3.363) |
| P23 | odysseus-stands-at-bay | shield | Ajax has, Odysseus holds | f, r | False | Generic kind |
| P24 | patroclus-quenches-the-fire | shield | Sarpedon has, Hector holds | f, r | False | Generic kind |
| P25 | patroclus-quenches-the-fire | spear | Patroclus has, Sarpedon holds | r | False | Generic kind ("two spears" each) |
| P26 | polydamas-counsels-a-pause | shield | Hector has, Polydamas holds | f, r | False | Generic kind |
| P27 | polydamas-counsels-a-pause | shield | Ajax has, Polydamas holds | r2 (pending) | False | Generic kind |
| P28 | polydamas-counsels-a-pause | spear | Hector has, destroyed in the idomeneus scene | r | False | Generic kind across scenes (Meriones's spear) |
| P29 | sarpedon-tells-glaucus-why | bow | Teucer has, Pandion holds ("carrying Teucer's bow") | f | Debatable | Same object; the handover from bearer to owner is implied |
| P30 | sarpedon-tells-glaucus-why | arrow | Glaucus has, destroyed in an earlier scene | f | False | Generic kind across scenes (Eurypylus's arrow) |
| P31 | sarpedon-tells-glaucus-why | spear | Sarpedon has, after "lets both spears fall" | f | False | Generic kind: the later spear is Ajax's, stuck in his shield |
| P32 | sarpedon-tells-glaucus-why | stone | Epicles has, Ajax holds | r | False | Generic kind |
| P33 | zeus-wakes-on-ida | helmet | Ares loses, Athena holds | r2 (pending) | False | One handover recorded twice |
| P34 | zeus-wakes-on-ida | shield | Ares loses, Athena holds | r2 (pending) | False | One handover recorded twice |
| P35 | zeus-wakes-on-ida | spear | Ares loses, Athena holds | r2 (pending) | False | One handover recorded twice |
| P36 | zeus-weighs-the-fates | spear | Diomedes has, after throwing it | f | Debatable | Homeric warriors carry two; the scene doesn't say |

**Notes on single findings:**
- **P17:** the prose has "She takes the robe from his mother". Haiku quoted it as "Theano takes the robe…", so the record was unverified and silently dropped from the fold.
- **P10, P33-35:** Haiku wrote `B gets` and `A loses/gives` with the same quote. The tie is broken by reply order, so B holds the object when A "loses" it.
- **P29:** the fix it prompted was useful ("Teucer takes his bow from Pandion").
- **P36:** the writer cut "with his spear".

**Mechanism histogram:**

| Mechanism | Count | Findings |
|---|---|---|
| Generic kind, different people's own items, same scene | 22 | P1-9, P12-16, P18, P20, P23-27, P32 |
| One handover recorded as two records on the same quote | 4 | P10, P33-35 |
| Handover in the scene missed or dropped | 3 | P11, P17, P21 |
| Generic kind across scenes (destroyed elsewhere) | 2 | P28, P30 |
| Generic kind, same holder "lost then has" | 2 | P31, P36 (debatable) |
| Remnant or retelling of a destroyed object | 2 | P19, P22 |
| Implied handover, bearer to owner | 1 | P29 (debatable) |

Mechanisms the brief named that did not occur in possession: armour stripping, off-page re-acquisition, time gaps, and stale carried state. Time gaps and stale state are the injury mechanism instead (below).

**What the false positives did to the prose.** The writer complied with each one:
- "his own" was inserted: "Hector puts his own helmet on", "with his own bow unslung", "a sword of his own", "his own curved bow".
- "One hand closes on a stone" became "on the dirt".
- "He takes the whip from Cebriones' hand" became "He snatches up the whip".
- "with his round shield up in front of him" was cut.

### Blocking read: 46 distinct findings, 65 reply items

| Verdict | Count |
|---|---|
| Real | 41 |
| Debatable | 5 |
| False | 0 |

**Real (41).** B-numbers follow `findings.json` order.

| # | Scene | Slip |
|---|---|---|
| B1 | briseis-led-from-the-hut | Looks back at the bench from behind the hull |
| B2 | achilles-refuses-the-embassy | Sees fires on the plain through the smoke-hole |
| B4 | achilles-watches-from-the-stern | Myrmidons "in the courtyard" then on the sand |
| B5/6 | achilles-watches-from-the-stern | Arrow in the right shoulder, the shield arm drops |
| B7 | agamemnon-is-wounded | Hector "at the gate" and "across the field" |
| B8 | agamemnon-proposes-flight | Washes both hands while leaning on the scepter |
| B9 | agamemnon-seizes-briseis | "On his feet again", never sat |
| B10 | ajax-fells-hector | Spear leaves a hand that already threw it |
| B12 | ajax-fells-hector | Falls forward with the spear through his eye |
| B15 | ajax-holds-the-ships | Falls from the prow, lands at the stern |
| B16 | ajax-holds-the-ships | Unclear "He" |
| B17 | aphrodite-drives-helen-to-bed | Paris is on the bed, then is led to it |
| B19 | athena-fires-diomedes | Jumps off a step he never climbed |
| B22 | briseis-led-from-the-hut | Lets go of a hand already handed over |
| B24 | chryses-ransom-refused | Wind off the sea on the backs of his legs, facing the sea |
| B25 | diomedes-and-odysseus-raid | Causeway direction |
| B26 | diomedes-spears-ares | Shield strap with the shield off |
| B27 | diomedes-spears-ares | Throws, then keeps hold |
| B28 | diomedes-spears-ares | Ichor between fingers after the hand is removed |
| B32 | glaucus-and-diomedes-trade-armour | Corslet over a helmeted head |
| B33 | glaucus-and-diomedes-trade-armour | Hands "still lifted" |
| B34 | hector-breaks-the-gate | Left and right after turning |
| B35 | hector-breaks-the-gate | "Nothing" behind the gate, then a dozen men |
| B37 | hector-drives-them-to-the-ships | "He has no spear", no drop shown |
| B38 | hector-duels-ajax | Ajax slings the baldric with sword and shield in hand |
| B40 | hector-finds-paris-at-home | Bow laid across the stool he sits on |
| B42/43 | hector-fires-the-ships | Torch taken with sword and shield in hand |
| B44 | hector-sends-paris-to-duel | Sees behind him; "again" |
| B46 | helen-watches-the-duel | Already up, then gets up |
| B48 | hera-seduces-zeus-on-ida | Which way Zeus faces |
| B49 | idomeneus-fights-at-the-ships | Spear never retrieved |
| B51 | menelaus-drags-paris | Unclear turn |
| B52 | menelaus-drags-paris | Two-handed blow with the shield on |
| B53 | odysseus-stands-at-bay | Hand taken while holding spear and shield |
| B54 | pandarus-breaks-the-oath | Draws a bow lying on the grass |
| B57/58 | patroclus-watches-the-idle-days | Bench "behind him" |
| B59 | patroclus-watches-the-idle-days | Dark lyre "pale" |
| B61 | sarpedon-rebukes-hector | Heel on the back, spear under the body |
| B62 | zeus-nods-to-thetis | Takes a cup already in her hands |
| B64 | zeus-nods-to-thetis | "The jug" never picked up |
| B65 | zeus-weighs-the-fates | Squires from nowhere |

**Debatable (5):**
- **B3:** a stain seen "under the bronze".
- **B13:** "empty hands" with a strap-hung shield.
- **B21:** the spear's path through Pandarus (Homer 5.290).
- **B50:** the spear count, which follows from B49.
- **B56:** "the ships are behind him" (the scene was aborted mid-gate).

**Patterns:**
- **Fixes created at least 3 of the slips.** B13 came from the fix for B10, B38 from a round-1 fix, and B42 from the fix for a broken promise.
- **One reading misses a lot.** 16 of 65 items were found by both readings, and about 14 distinct slips by reading 2 alone. Six real slips (B4, B25, B52, B59, B61, B64) first surfaced on a later round, in text that had been there from the start. That fits the eval's recall of 0.62.
- **Pending scenes.** 6 of the 14 have a blocking stop: 4 real (aphrodite, hector-duels, achilles-watches, ajax-holds), 1 debatable (ajax-fells, B13) and 1 Homer's own (athena-fires, B21).

### Other typed-state findings, for completeness

**Injury (13 across rounds, 4 injuries): 0 clearly real.**
- **Hector's "shield arm will not come up"** is a moment in the duel (Apollo lifts him, 7.272). Haiku graded it serious, and `SERIOUS_DAYS = 42` (`continuity.py:74`) carried it into 5 later scenes.
- **The gate wrote that injury into the book.** The fixes added "the left arm still stiff from Ajax's stone", "his shield arm still slow and held close", "with his good hand" and "swing right-handed, his shield arm still held close". Ben should decide whether to keep them.
- **Diomedes' shoulder** ("has stiffened") was carried into 3 scenes. Homer has Athena restore him (5.122).
- **Aeneas' hip** is half real.
- **Mechanism:** stale carried state, with severity inflated at extraction and no decay.

**Life (6): all false.**
- 2 homonyms: Homer's two Dolopses and several Pisanders.
- 1 generic descriptor: "the boy".
- 3 death moments read as presence after death: Cleitus, Rhesus's heels, Eniopeus named.

**Time (2):**
- "two days ago" against a 3-day gap: debatable.
- "Not a month since" against 21 days: false. It is a bound that holds.

## 3. Recorded evals

| Suite | Recall | False alarms per 10k words | Flags | Cost if live |
|---|---|---|---|---|
| `blocking-set` (the read, Opus, 2 readings) | 0.6154 (72 of 117) | 1.27 (3 flags in 14 clean scenes) | 99 | $6.77 |
| `blocking-set-sheet` (stage sheet, Haiku) | 0.2222 (26 of 117) | 15.65 (37 clean flags) | 288 | $0.85 |

- **Both replayed free and passed** all floors on 2026-11-26.
- **The read, in more detail:** recall 0.726 on Wrath and 0.432 on gawain. By category: hands 0.74, posture 0.91, sightline 0.33, worn 0.45, position 0.61, light 0.33. On slips found by readers: 0.32. Across the three recorded runs recall was 0.62 to 0.65.
- **The sheet, in more detail:** sightline 0.0, light 0.0, hands 0.44.
- **Typed state has no eval.** `evals/README.md:83-85` says the continuity checks "are code, tested in `tests/test_continuity.py`, not a suite". Nothing measures the extraction's precision, or possession's false-alarm rate on a large-cast book. That is why 34 false findings in one night were a surprise.
- **`gate-set` and `gate-set-questions` are `stale`** in `baseline.json`. Their private results on `main` carry no per-layer attribution.
- **Nearest precedent for a yes/no verifier:** `question-set` has recall 0.7647 and 0 false alarms on 96 questions (Haiku, asked twice).

## 4. Proposed fixes, tested by hand against the list

Possession made no real catch in this run, so "real catches lost" is 0 for every proposal. The test that matters is which false and debatable findings survive.

| | Fix | Kind | False removed (of 34) | Debatable kept (of 2) |
|---|---|---|---|---|
| F1 | Owner-scoped identity for bare kinds | Code | 32 | 2 |
| F2 | Pair handover records | Code | 4 (already in F1) | n/a |
| F3 | A misquoted record makes the object's state unknown | Code | 1 (P17, already in F1) | n/a |
| F4 | Destroyed semantics | Code | 2 (P19, P22) | n/a |
| F5 | Identity question, Haiku, asked twice | New call | About all 34 (estimate) | Probably P29 |
| F6 | Extractor names the owner; one record per handover | Prompt change | n/a (works on the cause) | n/a |
| F7 | Injury decay and severity | Code plus a small prompt change | n/a (injury) | n/a |
| F8 | Life check identity | Code | n/a (life) | n/a |

**F1, owner-scoped identity.** In `check_possession`:
- A bare-kind item ("shield", "his spear") is the holder's own object, `holder:kind`, unless the holder already holds exactly one object of that kind.
- A qualified name ("Teucer's bow") resolves to `teucer:bow`.
- `_slot` stops merging a bare name into another person's qualified object.
- The two-holders and destroyed rules then fire only on a proven same object.
- **Result:** leaves P22 and P31, and keeps both debatable findings (P29, P36). Unique objects named with an owner, such as Achilles' armour, are still tracked across scenes.

**F2, pair handovers.** `A loses/gives K` and `B gets K` on the same or overlapping quote become one handover, whatever the order. F1 already removes these four findings, but the pairing is still needed so the state is right afterwards.

**F3, unknown after a misquote.** A misquoted `holds` record on an object makes its state unknown from there, as the stage sheet already does. That part is the fix to the method: an unreadable handover no longer leaves the old holder in place. The "not compared" notes the check already writes would also say so.

**F4, destroyed semantics.** After `destroyed`, only an intact use (`has`, `gets`) blocks. The same holder discarding the remains, or a second `destroyed`, does not.

**F1 + F4 together** remove 33 of 34 and leave P31. A fungible-kinds rule would remove P31: for spear, arrow, javelin and stone, "lost then has" needs a stated count. It would also drop P36.

**F5, identity question.** Before a possession finding blocks, ask through `yes_no`: "are these two lines the same physical object, with nothing between that moves it?" Keep the finding only on two yeses.
- **Not measured.** The estimate rests on the passages being unambiguous and on `question-set`'s 0 false alarms.
- **Not advisory:** a confirmed finding still blocks.
- **Cost:** under $0.01 a finding.

**F6, extractor prompt.** Make the model name the owner in `item`, write one record per handover, and never record `has` for a thing lodged or thrown. This is what makes cross-scene tracking of Achilles' armour work in the remaining 40 scenes.

**F7, injuries.**
- A `serious` injury with no `impaired` use recorded in its own scene, or none within N days, lapses.
- A god's healing counts.
- Grading "arm will not come up" in the middle of a fight as `minor` needs a prompt line.

**F8, life.**
- A death binds only a registry character id, not a bare name or "the boy".
- Two characters sharing a name need distinct ids.
- An `at` record in the same sentence or paragraph as the death is the death itself.

**Blocking read.** Keep it as it is: 41 real of 46, none false. Two changes are worth making:
- After a fix round, re-read at least the edited paragraphs, since fixes made 3 of the slips. The gate already does this when the prose changes.
- Keep two readings. Reading 2 alone found about 14 slips.

For Homer's own oddities (B21), let the source check clear a blocking finding whose physical detail is in the source passage. That belongs in the source-check report.

**Recommended order:**
1. F1 + F2 + F3 + F4, one PR.
2. The `ends` guard from section 6.
3. F7 and F8.
4. F5, as a backstop for what F1 leaves.
5. F6, before the armour scenes if budget allows.

## 5. How much could be programmatic

- **The checks already are.** `continuity.py` is model-free given the records.
- **Every failure above is an extraction or identity failure,** not a rule failure:
  - which object a noun phrase means;
  - who "she" is;
  - whether "lodged in his shield" is holding;
  - how bad a wound is.
- **A symbolic ledger works for a narrow set:** owned, unique objects across scenes; deaths by character id; injuries with decay; days.
- **The model is irreducibly needed for four things:**
  - reading prose into events, with coreference;
  - object identity;
  - physical plausibility (trajectories, sightlines, what a strap or a helmet allows), which is most of what the blocking read caught;
  - what a reader assumes between sentences.
- **The stage sheet is the measured attempt to do blocking symbolically.** It scored recall 0.22 and 15.65 false alarms per 10k, against 0.62 and 1.27 for the read. The cause is extraction fidelity, not the rules.
- **So keep within-scene hands, posture and sightlines with the Opus read,** and narrow possession to cross-scene tracking of identified objects. The within-scene two-holders rule duplicates the read: B10, B37, B38, B54, B62 and B64 are all possession-type slips the read caught, and the rule caught none.
- **Place and sky need `reference/world.csv`** before they can check anything here: Ida's direction, the distance from the ships to the wall, speeds.

## 6. The `diomedes-spears-ares` slip

- **This is the ledger extraction (Sonnet, `gate-extract`), not the typed state.**
- **The reply.** In `recheck/` and `recheck-2/` of run `20261116-235310-17167`, the healing row reads: `"statement": "Paeon heals Ares…", "ends": ["ares-wounded-by-diomedes"]`.
- **The fact it names** is a plan fact whose scene is this scene (`reference/commitments.csv:26`, origin `plan`, introduced by `briefs`).
- **Why it blocks.** In `extract.commitment_rows`, `_link` returns the ref because it is in `here` (`extract.py:1183`). But `offered.get(gone)` is `None`, since `offered` holds only facts in force on entering the scene. So it lands in `problems['ends']` (`:1237-1238`), which is in `gate.UNRESOLVED` (`gate.py:122`) and blocks.
- **Why it became a halt.** The one free re-extraction for extractor slips runs only when slips are all that stopped the scene (`_only_extractor_slips`, `gate.py:3537-3547`, returns `[]` if `result.findings`). The possession false positive P1 was also present. So there was no re-roll, the scene could not be committed provisionally, and the session stopped at 00:04 with 73 scenes not attempted.
- **Guard 1.** In `commitment_rows`, an `ends` naming a fact in `here` (set up by this same scene) is not an extractor slip. Report it as `ends registry` (already in `REPORTED`) or set `resolves` to the scene. The wound is real and should not be carried forward.
- **Guard 2.** Let extractor slips earn the re-extraction even when prose findings are present. No prose edit can repair them.
- **Cost.** Both are code only, with a regression test from this reply.

## Files

These were written before the disk filled, all under `scratchpad/`:
- `scratchpad/collect.py` rebuilds the findings.
- `scratchpad/findings.json` holds every finding, with its round and quotes.
- `scratchpad/ctx.py` and `scratchpad/bctx.py` print the prose around each finding.

`report-B-typed-state.md` does not exist; the text above is the report.

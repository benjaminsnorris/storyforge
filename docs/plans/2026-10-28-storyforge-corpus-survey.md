# Continuity-failure eval corpus: survey of the author's book repos

Surveyed 2026-10-28. This was a read-only survey: nothing in any repo was changed, checked out or stashed. Prose quotes were checked against the tree at each fix commit's parent. I spot-checked three cases against the raw diffs: governor `f399507`, shared-dark `c6190fb` and lantern-folk `ab240c6`.

**Candidates.**
- **`guardian` does not exist** under `~/Developer` or anywhere in `~` (searched to depth 3). The other two named candidates, lantern-folk and thornwall, were surveyed.
- **Six more repos hold Storyforge data** and were also surveyed: shared-dark, governor, meridian-line, understory, slipform and ashes. `evals/` holds only the Gatsby pilot, and `storyforge/` only templates.

## Ranking

| Rank | Repo | Scenes | Final words* | Commits | Labeled fact fixes | High-conf | **Est. usable labeled cases** | Why |
|---|---|---|---|---|---|---|---|---|
| 1 | **shared-dark** | 102 | 90.5k | 1505 | ~62 | ~30 | **25–30 strong, +~15 medium** | The author labeled the errors in two places: `working/annotations.json` (22 continuity notes) and the page-cited first-read notes in `18c93cc:working/plans/revision-plan-6.yaml`. Fixes are small diffs from before the April regenerations. Includes fix-induced regressions and half-applied fixes. |
| 2 | **thornwall** | 62 | 67.0k | 860 | ~38 | ~16 | **30–35 (18–20 high), +~20 brief-fidelity** | Labels come from the author's first- and second-read notes (`56abeb1`, `fb1fe11`) and commit-body fix lists. Strong provenance: the commit that introduced each error, the audits that missed it, and the author's catch are all traceable. Mostly numeric TIM and TRT cases. Three scene-id eras make mapping harder. |
| 3 | **lantern-folk** | 15 | 20.0k | 206 | 36 | ~22 | **25–30 clean (35–40 with illustration cases)** | Very dense. Most fix commits name both sides of the contradiction. Short book, so labeling is fast. It is a children's illustrated book, which makes it less representative of novels. Adds a visual-state/illustration modality. |
| 4 | **governor** | 99 | 90.1k | 1136 | ~38 | ~17 | **15–20, +6 unfixed at HEAD** | Self-labeled: a continuity report at `f399507`, a numbered "Fixes Applied" log in `continuity-tracker.md`, and the author's annotations. Many errors were introduced by Storyforge redraft-from-brief passes. |
| 5 | **meridian-line** | 69 | 61.6k | 904 | 22 | ~15 | **12–15** | Mostly PHY quantities and TIM counts. Two fixes lost their pre-fix text in squashed PRs. History is mostly scoring and hone churn, so yield per commit is low. |
| 6 | **understory** | 58 | 79.2k | 505 | 3 | 3 | **~10 (mostly unfixed at HEAD)** | Continuity was never a revision target and the continuity tracker was never set up. Its value is as "should-flag" positives with no fix diff. |
| 7 | **slipform** | 63 | 78.7k | 259 | 4 (+1 regression) | 4 | **~7** | The whole history spans four days and is mostly whole-book redrafts. Standout case: Pell's pronoun was fixed, then a redraft undid it. |
| 8 | **ashes** | 43 rows / 1 drafted | 1.3k (one scene) | 89 | 0 | 0 | **~0** | A graphic novel still at the architecture stage. Its "fix" commits align bibles and spine with each other and are design changes, not prose errors. |
| — | guardian | — | — | — | — | — | — | Not found. |

\*"Final words" is `manuscript/manuscript.md` (governor: `manuscript/Chapter NN.md`), including front and back matter. lantern-folk's assembled manuscript is stale (see its data notes). Its current `scenes/` total is 22.2k.

**Corpus total: about 125–150 labeled prose cases, plus about 30 CSV/brief-level cases and 15–20 unfixed HEAD contradictions.**

**Recommended first repo to label fully: shared-dark.**
- It has the most high-confidence cases.
- The author has already written the label index, so mining cost is low.
- Each case maps to one commit (`c6190fb`, `80d0544`, `0a598b2`, `6a32342`, `10eaecc`).
- It is full novel length, so the cases are representative.
- Its fix-induced regressions test whether a checker catches errors that "fixes" create.

The main extraction cost is translating numeric scene ids (before `74bd85a`) to slugs. If a quick schema pilot is wanted first, lantern-folk can be labeled in an afternoon.

## Cross-repo patterns

- **Error mix.** TIM (counts, durations, day math) and TRT (names, pronouns, roles) dominate everywhere. KNO, REL and PRM are scarce, and VOI is almost absent. A corpus built from these books will be skewed. Plan to supplement KNO and PRM, for example with seeded errors or the Gatsby gold set.
- **Storyforge creates many of these errors.** Redraft-from-brief and global polish passes introduced or reintroduced many errors:
  - governor: Tessa's burns were misattributed in the CSVs, then written into prose.
  - slipform: Pell's pronoun regressed in redraft `c3d463a`.
  - shared-dark: the chair, "three nights" and the Steen deadline errors returned in redrafts.
  - thornwall: an invented name, Voss, leaked from a hallucinated brief into prose.

  These are useful as their own case type: "error introduced by tool X".
- **Facts the CSVs never recorded** (a recurring cause): Pell's pronoun (slipform); Wick's location and the survivor count (lantern-folk); most thornwall personnel numbers, because its knowledge and physical-state CSVs were extracted after the fixes. Each repo section has details.
- **Possible Storyforge bugs** (not fixed; you asked for no file changes, so none were logged in `FINDINGS.md`):
  - meridian-line `5433d3f`: a hone pass moved the "Tonkawa guide" alias from Naseka to Thomas.
  - governor `d7e98f3`: a CSV pass gave Elias's burns to Tessa.
  - understory: the `timeline-fix` pass (`5ac1c26`) changed nothing yet was marked complete; `bbfc945` duplicated `seq` 12 and left `pov` blank.
  - thornwall `19530d5`: a continuity-audit pass overwrote `council.md` with agent scratch text.
  - thornwall: `seq` 58 is duplicated.

## Data quality across repos

- **Scene-id renames from positional ids to slugs.** Diffs from before each rename need an id map:

  | Repo | Rename commit | Note |
  |---|---|---|
  | governor | `1672588` | |
  | thornwall | `0c3fd1f` | Git's rename detection mispairs files, so map by content. |
  | shared-dark | `74bd85a` | |
  | slipform | `44ab76f` | |
  | meridian-line | `dc37cda` | Also includes a deliberate name swap, Lena ↔ Cora, which is not an error. |
  | lantern-folk | none | Ids are stable but keep a positional `aNN-` prefix, against the standing decision. |
- **Knowledge resets.** thornwall's knowledge CSV was wiped in `1a3d566` and shared-dark's in `55516bf`. Knowledge ids before the reset don't join to HEAD.
- **Schema differences.**
  - lantern-folk:
    - `knowledge.csv` has an extra `fact` column, and its registry columns are blank.
    - There is no `physical-states.csv`. Physical state lives as tokens in the scene-briefs columns.
    - It has a `visual-state.csv`.
    - scene-briefs carries empty graphic-novel columns.
  - understory: the `knowledge.csv` header has leading whitespace.
  - ashes: scenes.csv has graphic-novel columns and `physical-states.csv` is header-only.
  - Only governor and thornwall have `continuity-tracker.md`.
  - Metadata moved from YAML frontmatter / `scene-index.yaml`, to `scene-metadata.csv`, to the three-file CSV model in March–April. Fields before April need a different reader.
- **Branches.** governor (`storyforge/visualize-20260417-2158`), shared-dark (3 commits ahead of main, none touching prose) and ashes are not on `main`. thornwall has an uncommitted `working/publish-manifest.json`, which I left alone.
- **Duplicate prose copies.** `manuscript/`, epub/web builds and YAML backups make `git log -S` noisy, so restrict searches to `-- scenes/`. lantern-folk's `manuscript/` was assembled before all of its fixes; it works as a free pre-fix snapshot but not as current text.
- **Author retcons are not errors.** Examples: thornwall's Hessal retcon, meridian-line's name swap, understory's 43→66-day expansion. Each repo section flags them.
- **Bundled fixes.** Many audit commits bundle 4–6 fixes and must be split into separate cases. Some fixes happened inside whole-scene redrafts and can't be isolated.

---

# Per-repo detail

Each section has: (1) the candidate fix list with hash, scene, type and confidence; (2) the ten strongest contradicting pairs; (3) facts the CSVs never recorded; (4) data-quality notes; (5) yield reasoning. Sections are in rank order.

## shared-dark

Repo: `~/Developer/shared-dark` (1505 commits). Surveyed read-only. Current branch
`storyforge/visualize-20260719-2251` is **3 commits ahead of `main`, 0 behind**
(`2328a5f`, `7cb585e` "Visualize: generate manuscript dashboard", `8399cd0` "Publish:
embed dashboard in manifest"). None of the three touch prose or the reference CSVs, so the
branch makes no difference for continuity work.

### Headline: the author labeled the errors themselves

This repo has more than commit history. It has **two author-written label sets** that
name specific continuity errors, quote the offending text, and often give the fix:

1. **`working/annotations.json`** holds 208 Bookshelf reader annotations by "Ben Norris"
   (2026-03-19 to 03-23). **22 have `category: continuity`**, and about 8 more under
   `content` are continuity in substance. Each one carries `scene_id`, the quoted `text`,
   the author's `note`, and a `validation` flag (`stale` means the text has since changed;
   `matched` means it is still present). They were worked in pass `6a32342` "Revision:
   continuity-fixes" plus `10eaecc` and `0a598b2` (PR #40, `166c6cc`).
2. **`working/plans/revision-plan-6.yaml`** (commit `18c93cc`, 2026-03-11): a "continuity-audit"
   pass that turns the author's first-read notes ("Author note p. NN", "30+ continuity errors
   identified in first read") into about 20 line-level decisions. They were executed in
   `c6190fb` "Revision: continuity-audit" (numeric filenames, before the slug rename), with
   follow-ups in `80d0544` "Author edits: continuity fixes…" and `0a598b2`.

The fixes these lists drive are small, targeted and checkable. They are the best-labeled
material in the repo. The later automated "continuity-audit" / "continuity-sweep" passes
(Sonnet) are mostly voice and antithesis edits that happen to be labeled continuity.

---

### 1. Fix commits that corrected a fact (listed one fix per line)

Scene ids are given as the current slug, with the old numeric file in brackets where the
fix predates the rename in `74bd85a`. A = author-labeled, P = Storyforge pass-labeled.

#### `c6190fb` Revision: continuity-audit (2026-03-11). Executes the author's notes from plan 6

| # | Fix | Scene(s) | Type | Conf | Label |
|---|---|---|---|---|---|
| 1 | "Four letters in careful print" → "Six letters" (Claire = 6) | name-surfaces [7], driving-west [9] | TRT | high | A pp.22,26 |
| 2 | "Three nights of dreams" / "three nights ago" → four (author decision: four nights before Coos Bay) | missing-persons [8], driving-west [9] | TIM | high | A pp.23,27 + key-decisions.md |
| 3 | "Four words" → "Five words" ("I want to go home" = 5). **Fix incomplete:** the next sentence kept "The same four words". The residual survived until about `dc85657`/`fe568ec` (03-26/28) | girl [77] | TRT (count) | high | A p.203 |
| 4 | "saved six children" / "recovered six children" → four (chapter is titled "Four Children") | twenty-three-days-ii [83] vs four-children [79] | PHY/count | high | A p.216 |
| 5 | Bend→Portland drive: "Five hours" → "Two and a half"; "Five hours. He drove them in four and a half" → "Three hours… two and a half" | phone-call [90], your-turn [91] vs no-response [44] | TIM/WLD | high | A pp.235,237 |
| 6 | Bookstore "closed, the stairwell dark" → "open… lit" (arrival is about 8:30 AM) | your-turn [91] | TIM | med | A p.237 |
| 7 | "She'd brought Portland gloves — leather, lined…" → "bought insulated gloves in Duluth" | property [72] vs iron-cold [62] | PHY | high | A p.185 |
| 8 | "If you've got them" → "You've got three left." (he knows her fridge from cooking carbonara) | open-the-windows [100] | KNO | med | A p.263 |
| 9 | Huang → Addison (case name). **Partial:** applied only in [83], which left "Huang" in nineteen-days [41] and nineteen-days-2 [56]. bbbbb37 later fixed [41] | twenty-three-days-ii [83] | TRT | high | A pp.152,217 |
| 10 | "Benitez precedent" → "Thornton ruling"; "Benitez had a shot" → "Whitfield had a shot" (the same scene says the Benitez motion was denied) | deena [88], arithmetic [92] | TRT/PRM | high | A pp.230,242 |
| 11 | "He had not washed his hands since Baltimore." while he is still in Baltimore | next-target [31] | PHY (location) | high | A p.81 |
| 12 | Laura knowledge: planted "My ex-wife told me loving me was like loving a wall." in keisha-argument [32] so that interrogation's "I told you about her in Baltimore" holds; removed Hank's surprise | keisha-argument [32], interrogation-part-1 [47] | KNO | high | A p.119 |
| 13 | "One sister. Rachel." → "Had a sister. Rachel." so that "She noted the past tense" holds | interrogation-part-1 [47] | KNO/VOI | high | A p.118 |
| 14 | Laura "not told but deposited" → "Hank had mentioned her once, Baltimore". Re-fixed in 80d0544 to "from the interrogation" | laura [85] | KNO | high | A p.229 |
| 15 | "handwriting he has never seen but recognizes" → "knows… the same handwriting from a dozen margin notes" | deena [88] | KNO | high | A p.223 |
| 16 | Maren recognizes hands "she'd felt on her shoulders in the dark" (Harmon's, which Hank dreamed). Reworked so she cannot yet know Hank dreams perpetrators | diner [11] | KNO/WLD | med | A pp.31,32 |
| 17 | 2:47 ↔ 3:47 wake-time alignment (eleven-days [20] 3:47→2:47; rachel [84] 3:47→2:47; decision [71] 3:07→2:47 with the minute arithmetic redone). **Later reversed** (see d10e04a, f916b27) | eleven-days, rachel, decision | TIM/WLD | low (rule churn) | A pp.55,222,227 |
| 18 | Tracker: "Hank drove … in four and a half (told Maren five)" → two and a half / three | continuity-tracker.md | TIM | high | P |

#### `80d0544` Author edits: continuity fixes and physical consequences (2026-03-12)

| # | Fix | Scene | Type | Conf |
|---|---|---|---|---|
| 19 | Maren now *wears* the insulated gloves ("Maren's hands on the wheel wore the insulated gloves she'd bought in Duluth") | property [072] | PHY | high |
| 20 | School assessment "Finished the assessment. Recommended retrofit." → La Pine water treatment plant. The school was finished months earlier in eleven-days [020]; author note p.217 | twenty-three-days-ii [083] | TIM/PRM | high |
| 21 | "Two and a half hours," → "Three hours," (Hank's spoken estimate vs the 3-hour route) | phone-call [090] | TIM | med |
| 22 | Bare hands on a frozen Sig at −15 °F: added the cost ("skin that had frozen to metal… palms raw") | sirens [078], four-children [079] | PHY (missing consequence) | med |

#### `0a598b2` Fix timeline consistency in scenes 070-071 (2026-03-12, author)

| 23 | Steen's desk clock / nightstand clock / "two hours" vs "just over an hour" made to chain against the 4:00 deadline; phone call replaced because they share a room | friday-afternoon-the-leak [070], decision [071] | TIM | high |

#### `a7b4f69` / `94f081a` continuity-audit (03-12)
| 24 | next-target "Three forty-seven AM" → "Two forty-seven" (part-wide rule) | next-target [031] | TIM/WLD | low (rule churn) |
| 25 | Tracker: Rook "Vet appointment next week" → "Arthritis confirmed… (scene 99)"; Hank "Freckle on left shoulder (scene 99)" | continuity-tracker.md | PHY | med (tracker-only) |

#### `dc2a340` continuity-audit (03-10, numeric files)
| 26 | Interlude "Twenty-Three Days" → "Nineteen Days" (title, opening, "twenty-third night" → "nineteenth"). Two interludes had collided | nineteen-days-2 [56] | TIM | med |
| 27 | "Rook has left her boots by the door" → "his boots" (Rook is female; the boots are Hank's) | six-men [58] | PHY/pronoun | med |
| 28 | Margaret's Delaware-shell link now explicitly sourced from "your fire marshal contact Chen" | shell-company [67] | KNO | low |

#### `f916b27` continuity-audit (03-14)
| 29 | "Dale Harmon, 47, of Coos Bay" → "51" (the tracker's locked details give "Dale Allen Harmon, 51"). Establishing sentence **not found in prose**; the tracker is the only source | return | TRT (age) | med |
| 30 | rachel wake clock 2:47 → 3:47 (reverses #17 under the new tracker rule "2:47 through Parts 1-4; ~3:47-3:52 in Part 5") | rachel | TIM/WLD | low |

#### `d10e04a` continuity-audit (03-14)
| 31 | decision: 2:47/2:48/2:49/2:50 → 3:07/3:08/3:09/3:10, and "Seventy-three/Seventy-one minutes" → "Fifty-three/Fifty-one" (reverses #17/#23) | decision | TIM | low (oscillating) |
| 32 | "forty minutes ago" → "less than an hour ago" (to fit the shifted clock) | decision | TIM | low |
| 33 | eleven-days "At 2:47 AM his hands woke him." → 3:47 (Baltimore dreams wake at 3:47 in fire-inside/fire-ostrowski) | eleven-days | TIM/WLD | med |
| 34 | friday-afternoon-the-leak: desk clock 2:07 → 1:07; nightstand "2:47." → "1:40 PM."; "forty" → "thirty-three" minutes; "an hour" → "two hours" | friday-afternoon-the-leak | TIM | med |

The author's 03-21 annotation on decision says: "1:40 or 3:07? We already fixed this once."
Treat items 17/23/24/30–34 as one **oscillating TIM cluster**. It is a good negative example
of a fix that never converged, and a poor source of a single gold answer.

#### `222ae9b` continuity-audit (03-15)
| 35 | Planted Margaret Okafor in fells-point, because later scenes rely on Maren already having her as a federal contact | fells-point | KNO (setup) | med |
| 36 | "Seven months after rescue" → "Nearly three months after rescue" (rescue in November; scene in January) | your-turn | TIM | high |

#### `bbbbb37` continuity-audit (03-16)
| 37 | "The Huang intake" → "The Addison intake" (completes #9) | nineteen-days | TRT | high |

#### `9354939` continuity-audit (03-16)
| 38 | theory: Maren claimed first-hand observation ("I sat across from you in that diner in Fells Point… in Duluth — the way you held that weapon"). Rewritten to report what Hank *told* her about the Ostrowski call | theory | KNO | med |

#### `7b5df61` continuity-audit (03-26)
| 39 | room: removed a duplicated "Still you / Still me" + kiss beat that night/still-you also held (duplicate beat) | room | PRM/KNO | low |

#### Author-annotation fixes: `6a32342` continuity-fixes (03-23), `10eaecc` (03-30), `0a598b2`
| 40 | Duluth room logistics. One shared room, against "next room"/"connecting door"/"Her room, not his"/phone calls between them | inside-riedel, same-architecture, childrens-dreams, friday-scheduled, friday-afternoon-the-leak, decision, come-inside, iron-cold | PHY (spatial) | high | A ×3 |
| 41 | come-inside "The truck's engine ticked as it cooled." Author: "They went in her car." → the Malibu, with Maren driving | come-inside | PHY | high | A |
| 42 | collision "a dead man's grammar" (Ostrowski is alive) → "a man's grammar that was not his own" | collision | TRT (status) | high | A |
| 43 | Jaw scar visible under a full beard ("The thin white line along his jaw"; "thin scar… she still does not know its origin") → felt "beneath the beard" | after, still-you, room | PHY | high | A ×3 |
| 44 | relief "She stood. Didn't let go." Author: "She was already standing" → line cut | relief | PHY | high | A |
| 45 | claire "A figure in a chair" vs kneeling. Author: "Not in a chair—kneeling." Only "crouched → knelt" changed. **Never fixed; the chair is still in claire.md and character-bible.md at HEAD** | claire | PHY | high | A |
| 46 | woodpile: Steen walks off the porch to the van, but my-name-is needs him still on the porch → "stood on the porch with his hands still in his vest pockets" | woodpile, my-name-is | PHY (position) | high | A ×2 |
| 47 | woodpile/child: "denim rough under her palms" while gloved. Author: "She still has gloves on" → gloves added. **The fix regressed #7/#19:** "the Portland leather useless against the Minnesota December", "the useless leather stiff with cold" | woodpile, child | PHY | high | A |
| 48 | pewter-town: drove down Friday afternoon, slept, and it is Saturday morning. Author: "This all needs to happen Friday." Plus "dead streetlight would not be apparent in the day" → told by Marie | pewter-town | TIM/KNO | high | A ×2 |
| 49 | bench "Get some sleep" when they still have to drive to her car → beat reordered, car logistics made explicit | bench | PHY | med | A (+ plan 6 p.53) |
| 50 | leaving-baltimore "It's filed… She'll run with it." Author: "Didn't she already say almost exactly this?" | leaving-baltimore | KNO (repeat) | low | A |
| 51 | decision: "Maren's feet found the floor — cold through her socks" after "Her shoes were on." | decision | PHY | high | A |
| 52 | rachel "The scarred thumb." in the 22-year-old's corridor. Author: "Would he have already deployed by this point?" (scar comes from Mosul) | rachel | TIM/PHY | med | A |

#### `fd3e02b` continuity-audit (03-30, after the fresh Duluth rewrite)
| 53 | Margaret history: "We overlapped on a trafficking referral last year" → "worked together three years ago… the Ramsey case" to match marens-network. **It left research.md's "two years back" in place** | fells-point vs marens-network, research | REL/TIM | high |
| 54 | "Everything out by three," → "four," (the same scene says "The property must be clean by four."). This **regressed** from the 03-11 fix after the Branch B Duluth redraft | friday-afternoon-the-leak | TIM | high |
| 55 | Planted the Addison case in nineteen-days-2 so later references have a setup | nineteen-days-2 | KNO | med |

#### `9e332fb` continuity-sweep (03-29)
| 56 | waves: "She surfaces at 2:47. The old time…" and later "3:41 AM" in the same scene, against the tracker's planted "dreams arrive at 2:14 and 3:41" → unified to 3:41 | waves | TIM/WLD | med |

#### `8375d7a` / `e655d59` / `b16c4f4` (04-08, cycle 20)
| 57 | "Madison just turned thirteen." → "Madison is sixteen." (next-target/watching-ostrowski: "Madison. Sixteen.") | call | TRT (age) | high |
| 58 | Rook "at the foot of the bed" in Maren's Portland apartment while Rook is with Hank on the road → replaced with a passing car | phone-call | PHY (location) | high |
| 59 | scenes.csv fire-marshal duration "approximately 2 hours (9–10am…)" → "3 hours (4–7am document assembly, 9am meeting…)" | fire-marshal (CSV) | TIM (CSV) | med |
| 60 | engineer: "Not corroded. Gone. Cut or sheared" → "Corroded down to stubs or sheared". Mostly an antithesis cull | engineer | WLD | low |
| 61 | no-response: "347 had been the fixed point" → "2:47" (the motif hour) | no-response | TIM/WLD | med |

#### `ea17208` "fix … timeline jumps" (04-05). CSV only
| 62 | scenes.csv `timeline_day` for planned rows: the-school −1→0, maren-runs −1→1, site-review 4→3, residue 101→96. Driven by the validator, not by prose | scenes.csv | TIM (CSV) | low |

**Total: about 62 individual fact fixes. About 45 are author-labeled** (22 annotations
plus about 23 plan-6 items) **and about 30 are high-confidence.**

---

### 2. Ten strongest cases, with the contradicting pair (verified with `git show <hash>~1:<path>`)

**Case 1. Bend→Portland drive time (TIM/WLD). Fix `c6190fb`, refined in `80d0544`**
- Established: no-response [44] at `c6190fb~1:scenes/44.md`:
  "Three hours. Bend to Portland. He drove it in two and a half."
  (Also in nineteen-days-2 [56]: "The three hours between Portland and Bend sat in a different register now.")
- Contradicted: phone-call [90]: `"Five hours," he said.` and your-turn [91]: "Five hours. He drove them in four and a half, Rook in the passenger seat…"
- Root cause: the brief itself was wrong. `scenes/scene-index.yaml` said "Hank drives to Portland. Five hours from Bend."
- Fix: [90] `"Two and a half hours," he said.`, later `"Three hours," he said.` (80d0544); [91] "Three hours. He drove them in two and a half…"

**Case 2. Gloves (PHY), fixed and then regressed by a later fix. `c6190fb` → `80d0544` → `6a32342`**
- Established: iron-cold [62]: "She bought a parka — olive drab, rated to forty below… Wool watch cap. Insulated gloves that would make her hands useless for anything precise."
- Contradicted: property [72]: "Maren's hands on the wheel were bare. She'd brought Portland gloves — leather, lined, fine for forty degrees and rain. Useless here."
- Fix (c6190fb): "She'd bought insulated gloves in Duluth — rated to minus twenty, the clerk had said — but they were in the bag in the back seat…"; then (80d0544, author): "Maren's hands on the wheel wore the insulated gloves she'd bought in Duluth — rated to minus twenty, the clerk had said."
- Regression: the author's later note on woodpile ("denim rough under her palms" → "She still has gloves on") was fixed in `6a32342` as "the cold pushing through her gloves, the Portland leather useless against the Minnesota December", and child.md got "her gloved hands, the useless leather stiff with cold". That contradicts the insulated gloves again. A good eval item for **fixes that introduce errors**.

**Case 3. Claire's letter count (TRT). Fix `c6190fb`**
- Established: the name, in the same sentence. driving-west [9]: "Claire. Four letters in careful print below the catalogue…"
- Contradicted: the same line, and name-surfaces [7]: "He wrote it on the legal pad, below the catalogue. Four letters in careful print."
- Fix: "Six letters in careful print." (both scenes). The plan note: "Claire = 6 letters."

**Case 4. Rescued-children count (PHY/count). Fix `c6190fb`**
- Established: four-children [79]: "Four children. The number settled into Maren's chest like a stone dropped into still water."
- Contradicted: twenty-three-days-ii [83]: "…cannot say so because the recklessness saved six children." and "…a system that had recovered six children and needed the recovery to be clean more than it needed the recovery to be true."
- Fix: "six" → "four" in both sentences.

**Case 5. "Five words" fix left half-done (TRT)**
- Established: girl [77]: `"I want to go home," the girl said.` (five words)
- Contradicted: "Her voice was small and hoarse and it landed in Maren's chest like a fist. Four words. The same four words Maren had heard…"
- Fix (`c6190fb`): "Five words. The same four words Maren had heard…" The second "four" was never changed. It lasted until the scene was rewritten around 03-26/28. A clean **incomplete-fix** item.

**Case 6. Duluth sleeping arrangement (PHY/spatial). Author annotations; fixes `0a598b2`, `6a32342`, `10eaecc`**
- Established: inside-riedel (`10eaecc~1`): "Same bed — they've shared the room since the second night."
- Contradicted: same-architecture: "Maren was asleep in the next room, or wasn't. The connecting door was closed. He hadn't knocked."; come-inside: "Maren looked at the two doors. … Side by side, the connecting door between them that they'd left unlocked all week." / "Her room, not his."; friday-scheduled: "From the next room she could hear Hank's voice, low and indistinct…"
- Author: "We have to make it clear—either they are sharing a room or not. So far it's been both."
- Fix: same-architecture "Maren was asleep behind him, or wasn't. He hadn't turned to check."; inside-riedel "they'd shared the room since she texted him the number from the Proctor motel's parking lot."; iron-cold adds "far bed — two doubles"; come-inside "their door. Room 6."

**Case 7. Laura already told (KNO). Fix `c6190fb`, refined `80d0544`**
- Established: absence. There was no on-page conversation about Laura before the interrogation (author note p.119: "no on-page conversation, and surprise contradicts having told her").
- Contradicted: interrogation-part-1 [47] (`c6190fb~1`): `"Tell me about Laura."` … `"I told you about her in Baltimore," he said.`; laura [85]: "Maren knows her name the way she knew Rachel's — not told but deposited…"
- Fix: plant in keisha-argument [32]: "Said nothing for a moment. Then: \"My ex-wife told me loving me was like loving a wall.\"" Laura [85], via 80d0544: "Maren knows her from the interrogation — Hank on her floor, palms up… *Laura. We married when I was twenty-eight. Divorced at thirty.*"
- Side effect: the author later annotated pasta-and-wine's "Laura told me that loving me was like loving a wall" with "Third time. Seems almost like a mistake." The plant created a repetition.

**Case 8. Benitez case outcome (TRT/PRM). Fix `c6190fb`**
- Established: deena [88]: "Three losses this week. … The Benitez motion denied on procedural grounds."
- Contradicted: the same scene: "She could cite the Benitez precedent, challenge the evidentiary threshold…"; arithmetic [92]: "Benitez had a shot. Morrison had a shot."
- Fix: "She could cite the Thornton ruling…"; "Whitfield had a shot."

**Case 9. Claire back at work "seven months" after rescue (TIM). Fix `222ae9b`**
- Established: waking-maren: "…she stood in her kitchen at 2:47 in the morning on a Thursday in November…"; your-turn itself: "the flat, low gray of January in Oregon".
- Contradicted: your-turn (`222ae9b~1`): "*Claire Renaud, RN. Emergency Department. Night Rotation.* Back on nights. Seven months after rescue."
- Fix: "Back on nights. Nearly three months after rescue, and she was working the shift she'd been leaving when Harmon took her."
- Note: the error came from the plan/tracker ("Claire Renaud confirmed back on night rotation … seven months after rescue"), so the reference doc was wrong.

**Case 10. Madison's age (TRT). Fix `8375d7a`**
- Established: next-target (`8375d7a~1`): "This one is Shannon's. Her student. Madison. Sixteen. Blue-lipped in a bathroom…"; watching-ostrowski: "This one is for Madison. Sixteen. Shannon's student."
- Contradicted: call: "Shannon teaches third grade at Hampstead Hill. Madison just turned thirteen. Brianna's the one who introduced you to the girl who overdosed."
- Fix: "Madison is sixteen."
- **Still unresolved at HEAD** (see §3): Brianna is now the 16-year-old who OD'd (next-target, keisha-argument); Madison and Shannon are tenants at 924 Eager (next-target: "Shannon on the second floor, west side. Madison on the third floor"); ostrowskis-grief calls them "Three girls at the daycare where Keisha worked"; and call still has Shannon teaching third grade.

Runners-up, all verified:
- next-target [31]: "He did not wash his hands. He had not washed his hands since Baltimore." (Hank is waking in the Fells Point motel during the Baltimore arc. No single establishing sentence; it is positional.) → "since before he'd slept — and he could not make himself do it now."
- Steen's deadline (fd3e02b): "Everything out by three," against "The property must be clean by four." in the same scene and "The property will be clean by four." in decision.
- Margaret history (fd3e02b): "We overlapped on a trafficking referral last year" against marens-network "They'd built their working relationship on the Ramsey case three years ago". The fix left research.md's "they'd overlapped on the Ramsey trafficking case two years back".
- Rook location (8375d7a): phone-call "Rook's breathing was the only sound in the apartment, slow and even from the foot of the bed." while Hank and Rook are on the road.

---

### 3. Load-bearing facts not in the CSVs, and live contradictions at HEAD

`reference/knowledge.csv` has only **37 rows**: verbose state-change facts from the
04-03 re-extraction. `physical-states.csv` has **103 rows**, almost all Hank, Maren or
Claire injury, fatigue or appearance. Grepping both, and character-bible.md, finds **none**
of these, though prose depended on all of them:

- Bend↔Portland ≈ 3 hours (it appears only in prose and loosely in the bible: "driving three hours").
- Maren's insulated gloves bought in Duluth (equipment state; not in physical-states).
- The Duluth shared room / Room 6 / two doubles.
- Steen's 4:00 PM cleanup deadline and the 1:07 PM / 3:07 AM clock chain.
- The Ramsey case as Maren's link to Margaret, and how many years ago.
- The Addison/Huang case; the Benitez/Thornton/Whitfield case names.
- Madison/Shannon/Brianna identities and ages.
- Laura disclosed in the interrogation (KNO). There is no knowledge row for "Maren knows about Laura".
- Harmon's age (51 appears only in continuity-tracker.md, which is now archived).
- Rook travels with Hank (location state); Rook's left hip appears only in the bible.
- Hank's jaw scar is under a full beard; Hank's hair is too short to grab (author notes).
- The 2:47 / 3:47 / 3:41 wake-hour rule per Part (it lived in the tracker, then key-decisions).

**Live contradictions at HEAD that no fix has addressed:** usable as unlabeled positives,
or as "the author flagged it and it was never fixed":
- claire.md: "Her phone found a shape on a metal chair fifteen feet in." vs building.md: "On her knees on the concrete. Hood over her face." The author flagged it ("Not in a chair—kneeling"), and character-bible.md still says "Zip-tied to a metal chair." The bible keeps regenerating the error through "redraft from briefs".
- claire.md: "Eleven nights inside this room." (Maren's dream nights) vs building.md: "every night for four nights", the author's four-night decision.
- claire.md: "…the same indifferent rhythm it had kept for all nine days and all eleven nights" (captivity length; the bible says "Held for nine days").
- driving-west.md: "The legal pad with three nights of notes went into the glove box." This regresses the four-night decision.
- The Madison/Shannon/Brianna tangle across call, next-target, keisha-argument and ostrowskis-grief (see Case 10).

---

### 4. Data-quality notes

- **Scene-id churn.** Files went `scenes/1.md` → zero-padded `001.md` (`dae6561`, 03-11) → slugs (`74bd85a`, 03-13; `37910f9` deleted 042 and renamed 054→`witness-prep`). Numeric numbers also shifted between cycles (cuts and insertions; "renumber 53-101 → 52-100" in `fe568ec`), so "scene 47" in a plan may not be `047.md` in a later tree. Map with `git show 74bd85a --name-status -M`. Near-duplicates: `prep`/`witness-prep`, `nineteen-days`/`nineteen-days-2`, `twenty-three-days-ii`.
- **Metadata migration.** `scenes/scene-index.yaml` → `reference/scene-metadata.csv` → `reference/scenes.csv` + `scene-intent.csv` + `scene-briefs.csv` (extraction PR #64, `f8de4e7`). The `||` → `;` delimiter migration was `b898d59`.
- **`55516bf` knowledge reset (04-03).** It deleted `knowledge.csv` (757 rows, "too verbose, non-atomic") and emptied `knowledge_in`/`knowledge_out`/`continuity_deps` in scene-briefs.csv. It was re-extracted to 37 rows. Knowledge-chain labels before 04-03 do not survive in the current CSV. The pre-reset file is at `55516bf~1:reference/knowledge.csv`. Ids are long sentence-slugs with many `;` aliases.
- **The continuity tracker is the old source of truth.** `reference/continuity-tracker.md` (archived to `working/archive/` in `29ae22a`, 04-03) has "Revision Notes" sections that record changes explicitly. Examples: "Steen's cleanup deadline is 4:00 PM (was 'three,' now 'four')", "renamed Addison per continuity-audit", "Margaret reference now says 'the Ramsey case' (was 'the Delgado case')". It is good for mining labels, but the tracker was itself sometimes wrong ("seven months", the shifting 2:47/3:47 rule).
- **Pass logs.** `working/logs/revision-pass-N-continuity-audit.log` (raw API JSON, 25–800 KB) holds the model's issue lists, for example the f916b27 log flagging "Dale Harmon, 47 … tracker's locked details say Harmon is 51". They are useful as weak labels but noisy and sometimes wrong (d10e04a: "it doesn't name Margaret at all").
- **An evaluation false positive.** eval-20260327 F003, "Shot continuity error between Chapters 18 and 19" (window frame vs shoulder), was a **plan-vs-prose** mismatch. "a single round into the window frame" exists only in `reference/story-architecture.md`. `git log -S suppressive -- scenes` finds no prose that ever contained it. Exclude it from gold labels, or keep it as a negative.
- **Wholesale regenerations.** "redraft 12/51/47 scenes from corrected briefs" (`62433fe`, `7be8a1b`, `9fbb07e`), the fresh Part 4 (`ea11de8`), the Branch A/B merge (`a8572fe`), and the April "Polish/Naturalness: upstream brief fixes" (`31d5df8`, `f56db28`, …) rewrite whole scenes. They **reintroduce** fixed errors (chair, three-nights, Steen deadline) because the briefs and bible still carry the old fact. Many `-S` hits are these; skip them unless the specific fact changed.
- **Squash merges.** Several PRs are squash-merged (`fe568ec` #48, `166c6cc` #40, `957168b` #60…), but the per-pass commits (`7b5df61`, `6a32342`) are still reachable in `git log`.
- **Automated "continuity" passes are mostly not continuity.** b16c4f4, 9c28579, a60d996, 9e332fb and 7b5df61 are mostly antithesis ("Not X, but Y") culls, sex-scene register edits and still-you motif moves. Under 25% of their hunks are factual.
- **Rule churn on the wake hour.** 2:47 vs 3:47 flipped at least four times (c6190fb, a7b4f69, d10e04a, f916b27, 9e332fb). Gold answers depend on which tracker rule was current, so give these low confidence.

---

### 5. Yield estimate

- **High-quality labeled pairs: about 25–30.** These are fixes the author labeled themselves (annotations.json plus plan-6 "Author note p.N") where the establishing and contradicting sentences both exist in the pre-fix tree. Ten are worked above. Most are short, mechanical and unambiguous: counts, travel times, names, ages, equipment, room logistics.
- **Medium: about 15.** Pass-labeled fixes with a clear before/after but a weaker or tracker-only establishing fact (Harmon 51, Huang→Addison, Rook pronoun, waves timestamp), plus 5 live HEAD contradictions that can serve as unfixed positives.
- **Low or unusable: about 15–20.** Wake-hour rule churn, CSV-only `timeline_day` edits, antithesis culls filed as continuity, and the plan-vs-prose shot finding (a negative).
- **Why the yield is high here:** a human author did a full first read (a page-cited note list) and in-app annotations with categories, and the fixes were applied as small diffs before the April wholesale regenerations. Mining effort is low: `working/annotations.json` and `18c93cc:working/plans/revision-plan-6.yaml` are a ready index. Each item maps to one commit (`c6190fb`, `80d0544`, `0a598b2`, `6a32342`, `10eaecc`). Extraction cost goes mostly into translating numeric scene ids (before `74bd85a`) to slugs.
- **Distinctive extras for the corpus:** two **fix-induced regressions** (gloves; Laura repetition), three **incomplete fixes** ("Five words. The same four words"; Huang only partly renamed; Ramsey "two years back" left in place), and **regressions reintroduced by brief-driven redrafts** (chair, three nights, Steen deadline). These test whether a checker catches errors that "fixes" create.


---

## thornwall

Repo: `~/Developer/thornwall` (860 commits, Mar 4 – Apr 17 2026). Read-only survey; nothing in the repo was changed. At HEAD there are 62 scene files (about 60.7k words), 62 rows in `scenes.csv`, and `scenes/archive/` holds 3 more files.

### Where the labels come from (best first)

1. **Author first-read notes**, `56abeb1:working/author-review.yaml`. The author wrote these by hand, with page and line refs and quotes. Four are explicit continuity calls: `tweak-02` ("Still five"), `tweak-03` ("Good night, Warden"), `tweak-04/05` (Sera's 14/20-year timeline) and `question-18` ("Kael never left" against "quieted panicking villagers"). The file was deleted at HEAD by `d758372`, but it is still readable in history.
2. **Author second-reading plan**, `fb1fe11:working/plans/revision-plan-3.yaml`, pass `hessal-and-personnel-timeline`. It lists about 15 concrete number/name errors with the intended fixes. The fixes landed in `9c24f36`, whose commit body has a line-by-line fix list.
3. **Machine continuity-audit commits.** These diffs are small and isolated, so they work well as labels: `fced67a`, `4d9e698`, `b03f901`, `c001bde`, `61941e2`, `ed23fe1`, `19530d5`, `93dfede`. Some commit bodies give the reasoning (for example, `4d9e698` explains the night count).
4. **`reference/personnel-timeline.md`** (created in `9c24f36`). Its "Locked Facts" are a ground-truth sheet, and it names one known-bad phrasing outright: "Do NOT describe Ves as having served 'longer than anyone except Torren.'"
5. **`working/plans/hone-findings-*.csv`** (April). These label *brief-vs-canon* contradictions: briefs that invented characters such as Voss, Maret, Dalton, Edris, Tessamine and Director Lorne. This is a different failure class (fidelity of the structured data), not a prose-to-prose contradiction.

Not useful as labels: the `Revision: redraft N scenes from corrected briefs` commits (wholesale rewrites, Apr 8–17), `passage-fixes` `426fa96` (line editing only), `full-prose-polish`, and most `Hone:` commits (normalization).

### 1. Candidate fixes (one row per fix)

Types: PHY physical continuity, TIM timeline, KNO knowledge, REL relationship, TRT trait/identity (including names and backstory numbers), WLD world rules, PRM promise/resolution, VOI voice. Scene ids are the names at fix time (positional `sNN-*` before `0c3fd1f`, Mar 14; slugs after). The rename map is in §4.

| # | Fix commit | Introduced by | Scene(s) | Description | Type | Conf | Label source |
|---|---|---|---|---|---|---|---|
| 1 | `36fe27a` | `ee7aa42` (draft) | s09-garrens-watch → garrens-ledger | Complement "Still five" after Bren's arrival, though it was five *before* he came. Fixed to "Six." | TIM/TRT (count) | high | author tweak-02 |
| 2 | `aba3ca8` | `9241784` (draft) | s11 → evening-visit | Sera says "Good night, Warden" after setting the first-names rule in s05. Fixed to "Good night, Kael." | VOI/REL | med | author tweak-03 |
| 3 | `aba3ca8` | drafts | s03, s16, s18 | Sera's career numbers: "fifth year" (s03), "fourteen years of field assessments" (s16), "twenty years of training and field work" (s18). An anchor "Fourteen years in" was added to s03. | TIM | med (the author notes they may be compatible) | author tweak-04/05 |
| 4 | `2fedfaa` | `6863e4c` (draft) | s02-the-letter vs s29-the-departure | Kael's voice "quieted panicking villagers", but s29 says he has never left the Hold in 23 years. The s02 clause was cut. | TRT/TIM (backstory) | high | author question-18 |
| 5 | `9c24f36` | draft | s07-the-stars vs s28-the-torch | Hessal is "he" in s07 and "a woman named Hessal" in s28. Fixed to "she". | TRT | high | fb1fe11 plan + commit body |
| 6 | `9c24f36` | draft | s08-the-journals | Journal writer: "Four people cannot do the work of twelve", written when the complement was about 8. Fixed to "Eight". | TIM | med | fb1fe11 |
| 7 | `9c24f36` | draft | s08-the-journals | "Filed a report… Third time this year". Changed to "Twice" for plausibility. | TIM | low | fb1fe11 |
| 8 | `9c24f36` | draft | s12-three-patterns → evidence-room | Ves (16 yrs) "longer than anyone except Torren", but Kael has served 23. Clause dropped. | TIM | med | fb1fe11 + personnel-timeline |
| 9 | `9c24f36` | `ca94700` (draft) | s17-through | "searched for anger weeks ago", but that search was the night before (s11 is Day 7, s17 is Day 8). Fixed to "last night". | TIM | high | fb1fe11 |
| 10 | `9c24f36` | draft | s20-brens-fire → new-technique | "Three years of training": his training predates his 3 years at Thornwall. Fixed to "Years of training". | TIM | med | fb1fe11 |
| 11 | `9c24f36` | `efef1c7` (healing-period-texture) | s20b-evening-light → two-cups | Sera "For nine years, I believed them" / "spent nine years measuring Holders", against 14–20 elsewhere. Fixed to "fifteen" (twice). | TIM/TRT | high | fb1fe11 |
| 12 | `9c24f36` | draft | s21-ivras-fire → ivra-at-the-fissure | Ivra's knees: "six years of service". She served at Garren's Watch before her 6 Thornwall years. Fixed to "eleven". | TIM | med | fb1fe11 |
| 13 | `9c24f36` | `31b2474` (draft) | s24-the-writ | "The chamber was not built for nine people", but the same scene lists ten. Fixed to "ten"; two officer beats added. | PHY (headcount) | high | fb1fe11 |
| 14 | `9c24f36` (+ tracker in `b03f901`) | `ce9eeed` (earn-thessan) | s24-the-writ | "Vellen will call it treason". The director is Corvin everywhere, including twice earlier in this scene. Fixed to "Corvin". | TRT (name) | high | fb1fe11 + b03f901 msg "Corvin name" |
| 15 | `9c24f36` | `3aa9ec0` (draft) | s26-rain-on-stone → courtyard-after | "Five days of sessions", while the same scene says "fourteen days ago". Fixed to "Thirteen days". | TIM | high | fb1fe11 |
| 16 | `9c24f36` | `112fd01` (part-four-expansion) | s29-the-departure → descent | "twenty-five days of mentorship", but Bren arrived three years ago. Fixed to "three years". | TIM | high | fb1fe11 |
| 17 | `9c24f36` | `0bf5c16`-era | s30-the-fire → weight-of-burning | Sera's letter lists "the compression" as the taught technique ("The compression lets you survive it"). Compression is Kael's own unsanctioned method. Removed. | WLD | high | fb1fe11 |
| 18 | `9c24f36` | draft | s02-the-letter | Kael states "The gap widens by roughly three percent per cycle" before Ivra discovers the pattern (s09). Made vaguer. | KNO | med | fb1fe11 |
| 19 | `d89578e` | `87fb209` / `112fd01` | s30-the-fire | "Their bedrolls spread on opposite sides of the fire" seven days after the kiss (s25b). Fixed to "side by side". | REL | med-high | fb1fe11 (pass 2 finding) |
| 20 | `fced67a` | `b772cf8` (draft) | s18-what-she-saw → undefended-flame | "sessions at seven Holds", against "Eleven sessions at six other Holds" in the same paragraph. Fixed to "six". | TRT (backstory count) | high | machine audit |
| 21 | `4d9e698` | `200fb23` (draft) | s06-the-inspection → he-knelt | "eleven sessions at seven Holds", against "six other Holds" at lines 13 and 67 of the same scene. Fixed to "six other Holds". | TRT | high | machine audit (msg + tracker note) |
| 22 | `4d9e698` | `1d995c4` (new-scene-intimacy) | s25c-the-hearth → confession-on-the-wall | "seven stars she had named… twelve nights ago". Naming was Day 5 and the scene is Day 19. Fixed to "fourteen". | TIM | high | machine audit; tracker records the Day math |
| 23 | `b03f901` | `d89578e`-era | s26-rain-on-stone | "The words she needed were simple — two words". The request is "Come with me" (three words). Fixed to "three". | TRT/PHY (internal fact) | med | machine review |
| 24 | `c001bde` | ? | riders-approach | "the Assessor who had climbed the switchback thirteen days ago". She arrived Day 2; the scene is Day 16–17. Fixed to "fourteen". | TIM | med (scene day is a range) | machine audit |
| 25 | `61941e2` | ? | confession-on-the-wall | "since the evening she sat in the dark… Ten days", but that evening was Day 5 and the scene is Day 19. Fixed to "Fourteen days". | TIM | high | machine audit |
| 26 | `61941e2` | ? | confession-on-the-wall | "His hand had been around hers an hour ago". The prior beat is the kiss the night before (parapet-after-torren, Day 18). Fixed to "Last night he had kissed her". | TIM/REL | med | machine audit |
| 27 | `ed23fe1` | `5fe9d18`? | settling-rhythm | A Sera-POV passage narrates Kael's private noticing ("he was not in the habit of pretending he hadn't noticed things"). Rewritten. | KNO (POV) | low-med | machine audit |
| 28 | `19530d5` | `e3adca1` (enforcement-timeline-restructure) | flame-and-wind, evening-visit | The restructure moved the decommission order to "day 5-6" in prose, but metadata kept lone-rider at Day 10. Flame-and-wind (Day 8) had Kael holding the order "since the rider two days ago". The audit stripped those references and changed "She had taken them from Ivra two nights before" to "the night before". | KNO/TIM | med (a prose-vs-metadata conflict; the audit also corrupted council.md, see §4) | machine audit |
| 29 | `93dfede` | — | s23 (scene-index.yaml) | Metadata time "Day 12-15", but the text opens on Day 11. | TIM (metadata) | med | machine audit msg |
| 30 | `109a4ac` | — | continuity-tracker.md | Tracker said Torren quotes "the door was never locked"; the prose now says "That the fire is theirs". Tracker corrected. | KNO (reference drift) | low | machine |
| 31 | `dbeebda` | — | s25-torrens-hold, s06 | Torren's copper ring added as a setup ("plant Torren's ring") so the later payoff lands. | PRM | low | cycle-2 plan |

**Not labeled by any fix commit, but provable from the tree:**

| # | Where | Description | Type | Conf |
|---|---|---|---|---|
| 32 | `36fe27a` result (s09/garrens-ledger) | The fix leaves "Complement: five. Net change: minus one." The complement went 5 → 6 → 5, so the net change is zero. This is a residual created by the fix itself. | TIM | med |
| 33 | s16-not-alone → shell-breaks-open, Mar 4 – Apr 3 | "On the courtyard wall, five nights ago". Courtyard is Day 5, the scene is Day 8, and the tracker itself says "three nights after Sera named it, Day 8 evening". It survived more than 10 audit passes and was removed silently by `10267cd` (structural-scene-changes). | TIM | med-high |
| 34 | s20-brens-fire, Mar 5 – Mar 14 | "Three years of compression against Kael's lifetime of it" attributes compression to Bren. `9c24f36`, whose stated target was "Compression technique incorrectly attributed to others", missed it. Removed silently by `9b1f507`. | WLD | med-high |
| 35 | HEAD `scenes/lone-rider.md` | Courier named **Voss** ("'Voss,' the rider said… 'Courier Second, assigned Kethren Ford.'"). `reference/key-decisions.md` forbids it: "Vosk → Thessan (Governor uses Voss — too similar)". It entered through a hallucinated brief and the redraft `edc8705`, and is absent from characters.csv. | TRT/WLD (rule-backed) | high (unfixed) |
| 36 | HEAD `reference/physical-states.csv` rows 24, 28 | `loosened-braid-kael` ("Hair loosened from braid") and `hair-loose-kael`. Kael's head is shaved: character-bible "Head shaved close"; wardens-welcome "Head shaved close, dark stubble…"; physical-states row 4 `stubble-scalp-kael`. The source line is Sera's braid in evening-visit ("Her braid was looser than he'd seen it"). | PHY (extraction misattribution) | high |
| 37 | HEAD `reference/physical-states.csv` rows 58–78 | 16 rows for a character "Garren". Garren's Watch is a place. The rows mix Torren (cold-stone, rend-came, seven-minutes, "thirty-one years") and Kael (chamber-farewell, "twenty-three years of kneeling"). Introduced by `5b1eec6`. | TRT (extraction) | high |
| 38 | `working/plans/hone-findings-{hallucinated-brief-repair,upstream-briefs-tier-1,-tier-2}.csv` | About 20 briefs invented characters and events (Voss/Dren/Linn/Maret in four-at-table; "calls Torren 'Sera's dead brother'" in settling-rhythm; Dalton, Edris, Tessamine, Almeda, Demara, Drellis…). The hone CSVs label these per scene. | TRT/KNO (brief vs canon) | high as labels, but a different task from prose continuity |

### 2. The ten strongest cases, with the pair verified against the pre-fix tree

Every quote below was read with `git show <fix>^:<path>`.

**C1. Vellen / Corvin (TRT, `9c24f36`, same scene)**
- Established (s24-the-writ, line 286, and s02-the-letter line 121 signature "*Director Corvin*"): "She reached into her uniform jacket and withdrew the writ of enforcement — a folded document, sealed with Director Corvin's sigil…" Line 290: "Director Corvin's sigil breaking apart on stone that had remembered what it was."
- Contradicted (s24-the-writ, line 294): "Her jaw tightened. "Vellen will call it treason. The directorate will call it dereliction. I know what this costs.""
- Fix: ""Corvin will call it treason."" `b03f901` then fixed the same name in continuity-tracker.md ("Names the cost (Vellen, treason, dereliction)" → "(Corvin, …)").
- Provenance: introduced in `ce9eeed` (Mar 5, "earn-thessan"). It survived the `93dfede` audit, which reported "Corvin letter… and Thessan's dialogue fully consistent", then `2708af8`, then several pipeline reviews. The author caught it on 2nd reading (`fb1fe11`: ""Vellen" → establish or change to Corvin").

**C2. "Still five" (TIM/count, `36fe27a`, same scene)**
- Established (s09-garrens-watch): "Four years ago: 74%. Complement held at five."
- Contradicted (same scene, next paragraph): "Three years ago: 71%. Bren arrived — bright, nervous, hadn't yet learned what the cost looked like up close. Still five. But Holder Dreya … three months after Bren's arrival she was transferred to a care facility in the lowlands. Complement: five, then four. Net change: minus one."
- Fix: "…up close. Six. But Holder Dreya … Complement: five. Net change: minus one." (The leftover "minus one" is residual #32.)
- Label: author tweak-02: "Continuity error — Bren's arrival brought the complement to six".

**C3. Hessal's gender (TRT, `9c24f36`, cross-scene)**
- Established (s28-the-torch, line 118): "The Warden before me — a woman named Hessal, quiet, steady, she'd served seventeen years — she looked at me and said, 'Good. Now do it again tomorrow.'"
- Contradicted (s07-the-stars): ""My Warden — Hessal — he told me this on my third day. Not to frighten me.""
- Fix: "My Warden — Hessal — she told me this on my third day."

**C4. Twenty-five days of mentorship (TIM, `9c24f36`, cross-scene)**
- Established (s09-garrens-watch, line 57): "Three years ago: 71%. Bren arrived — bright, nervous…". Also s28-the-torch: "Bren had walked these corridors a thousand times in three years."
- Contradicted (s29-the-departure): "The silence between them was full — twenty-five days of mentorship compressed into a look. The first session he'd guided Bren through. The supply runs on the switchback trail."
- Fix: "three years of mentorship compressed into a look." Introduced by `112fd01` (part-four-expansion), evidently from confusing story-days (the action lasts about 25 days) with the length of the relationship.

**C5. Five days vs fourteen days of sessions (TIM, `9c24f36`, same scene)**
- Established (s26-rain-on-stone, line 16): "When Kael had first opened — fourteen days ago, though fourteen days felt like a word from a language she used to speak — the gap had been three feet across."
- Contradicted (same scene, line 10): "Five days of sessions had taught her what the fissure sounded like when it was healing."
- Fix: "Thirteen days of sessions had taught her…". Present since the first draft (`3aa9ec0`); none of the four audits before the author caught it found it.

**C6. Nine vs ten people in the chamber (PHY headcount, `9c24f36`, same scene)**
- Established (s24-the-writ, line 102): "Kael led them down — Thessan, four of her officers, the rest left above to guard the gate. Sera walked beside Thessan. Bren and Ivra and Torren followed on the stairs behind the officers". Kael + Thessan + 4 + Sera + Bren + Ivra + Torren = 10.
- Contradicted (line 100): "The chamber was not built for nine people."
- Fix: "The chamber was not built for ten people." The fix also added "A third officer — heavyset, graying at the temples…" and a fourth-officer beat, so all four are tracked. The HEAD slug scene crowded-chamber keeps "ten people" as its title line in metadata.

**C7. Twelve nights vs Day 5 → Day 19 (TIM, `4d9e698`, same scene)**
- Established (s25c-the-hearth, line 21): ""About the wall," she said. "Day five. The first night you told me about the stars."". The scene is Day 19 (continuity tracker: "### s25c-the-hearth — "The Hearth" (Day 19, evening, Sera's POV)").
- Contradicted (line 15): "The Cord burned above the eastern ridge — the seven stars she had named for him on this wall twelve nights ago".
- Fix: "…fourteen nights ago". The commit adds a tracker note: "s25c originally read "twelve nights ago," corrected to "fourteen nights ago" in cycle 3 audit." Introduced the same day by `1d995c4` (new-scene-intimacy) and caught by the machine audit.

**C8. Seven Holds vs six other Holds (TRT, `4d9e698` and `fced67a`)**
- Established (s06-the-inspection line 13): "the same model she'd used at six other Holds, at eleven previous sessions". Line 67: ""I've observed eleven sessions at six Holds."". Also s16: "fourteen years of field assessments, six Holds, eleven observed sessions".
- Contradicted (s06 line 25): "swinging between readings with a mechanical indecision she had never seen in eleven sessions at seven Holds."
- Fix: "…in eleven sessions at six other Holds."
- Sibling (`fced67a`, s18-what-she-saw): "She had observed Holding sessions at seven Holds across the network. … Eleven sessions at six other Holds before Thornwall." became "at six Holds". Both "seven" slips sit within a few lines of the "six" they contradict. The ambiguity is "seven including Thornwall".

**C9. Sera's nine years (TIM/TRT, `9c24f36`, cross-scene)**
- Established (s03-the-road, after `aba3ca8`): "Fourteen years in, and the record had only sharpened." s16-not-alone: "Not in fourteen years of field assessments, six Holds, eleven observed sessions". s18: "Nothing in twenty years of training and field work".
- Contradicted (s20b-evening-light): ""I believed them. For nine years, I believed them."" and "She had spent nine years measuring Holders."
- Fix: "For fifteen years, I believed them." / "She had spent fifteen years measuring Holders." Introduced by `efef1c7` (healing-period-texture) on Mar 8, the day *after* the author had flagged Sera's year-count confusion (tweak-04/05) and `aba3ca8` had anchored it. A revision pass created a fresh error in exactly the fact that had just been locked.

**C10. "Ten days" since the dark-room evening (TIM, `61941e2`, slug era)**
- Established (confession-on-the-wall, line 15): ""About the wall," she said. "Day five. The first night you told me about the stars."" Line 37: ""I sat in my room without a lamp for two hours."". scene-metadata timeline_day is `19` for confession-on-the-wall and `5` for different-stars.
- Contradicted (line 3): "She had been looking, the way she had been looking since the evening she sat in the dark and could not light a lamp. Ten days."
- Fix: "Fourteen days." The same commit also replaced "His hand had been around hers an hour ago on this same stone" with "Last night he had kissed her on this same stone" (#26), to agree with parapet-after-torren (Day 18, the kiss).

**Honorable mentions (the pair is verified, kept short):**
- **s17 "weeks ago" (#9).** s11 opens "She came to him in the evening, after the meal" and contains "He searched for anger." (Day 7). s17 (Day 8, night) had "He had searched for anger weeks ago, after Sera showed him the supply records". Fixed to "last night".
- **s30 compression (#17).** s01 says of Kael's method: "He'd found something else — not taught, not sanctioned, arrived at through two decades of kneeling". Sera's letter to *all* Holders said "You were taught a technique. The wall, the compression, the resistance." and "The compression lets you survive it." Fixed to "The wall, the resistance, the containment."
- **s02 villagers vs s29 (#4).** s02: "the voice that settled rooms, that steadied frightened Holders and quieted panicking villagers." s29: "Kael had climbed this road once, twenty-three years ago… He had not descended it since." Resolved in `2fedfaa` by cutting the clause.

### 3. Facts later prose relied on that the CSVs never recorded

At fix time (Mar 4–14) there were **no structured CSVs**. Continuity lived in `reference/continuity-tracker.md`, `scenes/scene-index.yaml` and (from Mar 9) `reference/personnel-timeline.md`. `knowledge.csv` and `physical-states.csv` were first extracted from finished prose on Apr 2–7. So none of the cases above was, or could have been, caught by CSV-based checks when it happened.

At HEAD, checked with grep on knowledge.csv / physical-states.csv / scene-briefs.csv:
- **Not in any CSV:** Hessal (gender, 17-year tenure, burnout weeks after Kael arrived); the complement history (Marsh, Dreya, Sorrel, Ryn: 0 hits); Sera's career length (14/15/20 years: 0 in knowledge, only briefs prose); "eleven sessions at six Holds" (0); Torren's 31 years and Kael's arrival at 22 (they appear only inside a physical-state description, attributed to "Garren"); Kael's collarbone (0); the Cord being named on Day 5 (0); Davin/Greenhollow (0 in knowledge; briefs only); the forbidden-names rule (key-decisions.md only).
- **Partly present:** Kael's 23 years (inside the `kael-compression-technique` description); Corvin (2 knowledge rows, characters.csv); the reclassification requests (`kael-two-reclassification-requests-denied`).
- Character-tenure and backstory numbers, which make up most of this repo's errors, live only in `personnel-timeline.md` and `continuity-tracker.md`, not in any CSV. Several of those facts (Hessal, Dreya, Marsh, collarbone) no longer appear in the HEAD prose at all after the April redrafts.

### 4. Data-quality notes

- **Three naming eras.**
  - Mar 4–14: positional `sNN-slug.md` (s01–s30, with b/c inserts such as `s20b`, `s22b`, `s25b`, `s25c`; s10, s13 and s27 were absorbed or removed). Metadata lived in `scenes/scene-index.yaml`, `working/pipeline.yaml` and `revision-plan-N.yaml`.
  - `0c3fd1f` (Mar 14): 31 chapters split into about 48 scenes with slug ids. Git's rename detection pairs files oddly: `s25b-the-answer → parapet-after-torren`, `s14-the-decision-to-share → last-journal`, `s22-the-order → council` (with 88 deletions), `s06-the-inspection → he-knelt`, `s02-the-letter → four-at-table`. Several s-files (s01, s23, s24, s25, s28) were split with no rename edge. Map by content, not by `git log --follow`.
  - April: metadata migrated `scene-metadata.csv` → `scenes.csv` / `scene-intent.csv` / `scene-briefs.csv` (`c64880e`, `3921cc9`), and part of the YAML was deleted.
- **63 vs 62.** There is no real mismatch. `scenes.csv` has 62 data rows plus a header. `scenes/` has 62 `.md` files plus the `archive/` directory (last-morning, parapet, school-in-the-ledgers). But `last-morning` is in both `scenes/` and `scenes/archive/` with *different* content. It stays in scenes.csv with `seq` 58, which **duplicates** weight-of-burning's seq 58. No blank ids; timeline_day is never blank.
- **The early scenes.csv had alphabetical `seq`** (`81174a2^`: before-dawn-below=1, breaking-camp=2, …), so `seq` before about Apr 3 is not reading order. Use scene-metadata.csv `seq`/`part` for that period.
- **The audit pass corrupted files.** `19530d5` ("continuity-audit") replaced `scenes/council.md` with agent scratch text ("(fix "hadn't yet brought her full analysis to Kael")… Let me now write these out in full: ```"), word count 18, and cut lone-rider from 916 to 478 words. `5a61823` restored it. Any diff-mining over this window has to filter these out.
- **Prose and metadata disagree on timeline.** `e3adca1` restructured the prose (order arrives "day 5-6"), but scene-metadata kept lone-rider at Day 10. The following audit "fixed" prose to match the metadata. Labels in this window are ambiguous about which side was the error.
- **The `1a3d566` knowledge reset** (Apr 4) truncated knowledge.csv from 700 sentence-level facts (with "zero join integrity to the briefs") to the header only and cleared `knowledge_in/out` and `continuity_deps` in the briefs. `69eaa16` re-extracted it, `82aee23`–`f41f08e` normalized it, and HEAD now has 50 rows. Knowledge ids were renamed at least twice (`462ad17` "simplify knowledge IDs"). Knowledge-chain history before Apr 4 does not join to HEAD.
- **CSV extraction errors** (#36, #37): "Garren" treated as a character (16 rows), and Sera's braid attributed to the shaved-headed Kael. physical-states.csv covers 62 rows for Kael but only 4 for Sera, 2 for Ivra, 1 for Torren and none for Bren.
- **Hallucinated briefs** (#38): about 20 scene-briefs had goal/conflict fields describing a different story. At least one invented name (Voss) leaked into HEAD prose (#35).
- **Duplicate prose copies:** `manuscript/manuscript.md`, `manuscript/chapters/*`, epub/web assemblies (`ca036a9`, `6e91fd7`, `c3e51f9`, `48d2fea`) and stale YAML backups (`3921cc9`) all contain copies of the prose. `git log -S` results are therefore noisy, so restrict to `-- scenes/`.
- **Author retcons are not errors.** The Hessal change (Kael Warden for all 23 years; `reference/key-decisions.md`, Mar 9) is a deliberate retcon. Items that only exist because of it (the Hessal timeline in the diagram, "Twenty-three years of filing supply requests") should be excluded. #8 (Ves) is a borderline case: it was wrong even before the retcon.
- The CSV delimiter is `|`, and arrays use `;` (migrated from `||` in `db19137`).

### 5. Yield estimate

- **Prose fixes with a pair and a label (rows 1–29): about 29.** Of these, **about 16 are high-confidence**. All but a few have the establishing sentence within the same scene or in an adjacent scene, and the label is either the author's own note or a commit-body fix list. The high-confidence items are mostly TIM and TRT (number and name slips). PHY, REL, WLD and VOI each have only one or two.
- **Silently resolved or unfixed but provable (rows 32–35): about 4**, which need hand labeling.
- **CSV and brief-level (rows 36–38): 2 physical-state cases plus about 20 hallucinated-brief scenes.** Useful for a "structured data contradicts canon" eval, not for prose continuity.
- **Possible additional yield (not mined):**
  - (a) the remaining 13 decisions in `fb1fe11` passes 2–5 (romance and worldbuilding items, mostly not continuity);
  - (b) eval reports in `working/evaluations/*` (few continuity calls; checked, low yield);
  - (c) the April "redraft from corrected briefs" commits, which may hide fact changes but are wholesale rewrites;
  - (d) a systematic check of HEAD prose against personnel-timeline.md, likely 3–8 more unlabeled cases.
- **Realistic total: about 30–35 labeled prose cases (about 18–20 high-confidence), plus about 20 brief-fidelity cases.** The repo is strong for **numeric TIM/TRT drift introduced by revision passes**. It has unusually good provenance: the commit that introduced the error, the audits that missed it, and the author's catch are all traceable. It is weak for PHY, KNO and PRM, and for anything checkable against CSVs at the time of the error.


---

## lantern-folk

Repo: `~/Developer/lantern-folk` at HEAD `78d9f61` (206 commits, 2026-07-14 to 2026-08-19). 15 scenes, `scenes/aNN-<slug>.md`, pipe-delimited CSVs in `reference/`. I only read it; nothing in the repo was changed.

The commits fall into three eras:

- **Drafting and revision passes (07-18).** Craft passes plus two TRT fixes.
- **Timeline and seam work (07-19 to 08-01).** Prose vs. metadata fixes, seam repairs and a magic-system fix.
- **Illustration and contradiction-audit work (08-01 to 08-10).** Most of the high-quality fact fixes are here, with detailed commit messages that name both sides of each contradiction.

Commit messages in eras 2 and 3 are unusually good labels. Most name the establishing scene, the contradicting scene and the rule. Several commits bundle 3–6 separate fixes, so they need splitting.

### 1. Candidate fix commits (prose and metadata)

Error types: PHY (physical), TIM (timeline), KNO (knowledge), REL (relationship), TRT (trait/identity), WLD (world rules), PRM (promise/resolution), VOI (voice).

| # | Hash | Description | Scene(s) | Type | Conf. |
|---|------|-------------|----------|------|-------|
| 1 | 1d40cae (a) | a11: Nora finds *Wick's* lantern beside her and grieves him as newly dark, but Wick was snuffed at the creek in a07 (day 8) and laid on his own bed in a08. a11 is day 11. The lantern becomes a stranger's. The **scene brief also carried the error** ("Nora cups Wick's cold lantern"). | a07, a08 → a11 | PHY/TIM | high |
| 2 | 1d40cae (b) | Wick described as *inside* his lantern ("his face had peered out at her through the light", "no small warm voice" from inside the glass; a09 "the one inside", "five Folk inside them"). a03 has him carrying it and setting it on her fingertip. | a03 → a09, a11 | WLD/TRT | high |
| 3 | 1d40cae (c) | a11 ends with every Folk silent ("all its roots were dark"), but a12 has weeping Folk and the Keeper, and a14 has four Folk plus Ember lit. Fixed by having Nora count the last five. | a11 vs a12, a14 | PHY | high |
| 4 | 1d40cae (d) | a12: Leo "couldn't see" the Keeper a few paces off, but a14 calls her lantern "the steadiest light in the village". | a12 vs a14 | PHY | med |
| 5 | 60f1186 | a11: Nora states the rule "if the Lamp went dark they'd all go into the deep sleep", then the same chapter shows five survivors. a08 says "one lantern at a time". The rule was restated as a countdown. | a08 → a11 | WLD | high |
| 6 | c9cd9b3 | **Introduced by fix #3.** a12 opens with the Keeper settled "a while ago" among a crowd of Folk breathing "around them", but the new a11 ending has her still a moving light far off and all four Folk down in the roots. | a11 → a12 | PHY/TIM | high |
| 7 | 2d4c323 | a12 (Leo POV): Leo converses directly with the Keeper ("I am here, child") and hears the weeping as a "mosquito" whine and a "chorus". Leo can't hear the Folk (a03, a08 translation), and a14's payoff is that he hears a voice "he had never heard". Routed through Nora; 4 leaks fixed. | a03, a08, a14 → a12 | KNO/WLD | high |
| 8 | a947c04 | a10: "Every lantern in the village died at once", vs a11 "going out one by one" and a13 "Now there were four. Maybe five." Changed to a cascade. The LLM contradiction audit found this. The same audit **accepted a14's "dozens" as consistent** (see #9). | a10 vs a11, a13, a14 | WLD/PHY | high |
| 9 | ab240c6 | a14: "The Folk who were still awake had drawn close, dozens of them", minutes after a13 counts "four. Maybe five." The author caught it from the art. | a13 → a14 | PHY | high |
| 10 | 2dd0ea2 (a) | a10: Nora sat at Wick's house "yesterday", but Wick went dark in a07 (day 8) and a10 is day 11. | a07 → a10 | TIM | high |
| 11 | 2dd0ea2 (b) | The coinage "wardlight" / "the ward" in a10 and a14 vs a04's established "the line of light". This is a terminology fix (rule 9). | a04 → a10, a14 | WLD (naming) | low |
| 12 | 6c7fa1a | Bare "wolf" ×10 in a09 vs "murkwolf" everywhere else. Read-aloud listeners couldn't tell real wolves from murkwolves. | a09 | WLD (naming) | low |
| 13 | 81517bd (a) | a13 invents a stone hearth of coals ("where the Great Lamp had burned … coals", "the Lamp's hearth"), vs a04's bronze lamp "the size of a cooking pot" in a bowl of living wood. | a04 → a13 | PHY | high |
| 14 | 81517bd (b) | a14 "tall as Leo's chest" vs a04 "size of a cooking pot". Canon reconciles the two through kneeling, and kneeling is now explicit. | a04 → a14 | PHY | med |
| 15 | 81517bd (c) | a14 "weeks of frost" / lanterns "burning down for days" with no Lamp, but the Lamp died hours earlier the same night (a10–a14 are all day 11). | a10 → a14 | TIM | high |
| 16 | 81517bd (d) | a09 (Leo POV) head-hops: "Nora heard him from across the square", and Leo reports Pip's spoken count. | a09 | KNO/VOI | high |
| 17 | 81517bd (e) | a09: Leo hears Tallow shout a warning and reacts, then hears Tallow's dry aside. Both now reach him as gesture. | a03 → a09 | KNO | high |
| 18 | 81517bd (f) | a04: the Keeper "couldn't hear him any more than he could hear her", vs a05 "every one of them could hear him perfectly well" and a07–a09. The a05 line was added in 37bc78e, so this contradiction was created by a fix. | a05 ↔ a04 | WLD/KNO | high |
| 19 | 28b945f (a) | a04's ending had Leo say "Tell her we'll come back tomorrow night" and walk Nora home, then a05 opens continuously on the ledge the same night. | a04 → a05 | TIM | high |
| 20 | 28b945f (b) | a03→a04 written as continuous, but metadata puts a04 a day later. Added a "next night" bridge. | a03/a04 | TIM | med |
| 21 | 28b945f (c) | Metadata-side fix: a09 `timeline_day` 11→9 (prose ends at dawn, two nights before a10), a15 12→11 (continuous with a14). | a09, a15 (scenes.csv) | TIM | med-high |
| 22 | 28b945f (d) / 89e7146 | a01→a02 jumped from "everyone unpacking" to "everyone asleep" with no night passing. Restructured twice, the second time on author direction. | a01/a02 | TIM | med |
| 23 | 28b945f (e) | a07 had no time cue for the several-night guarding gap after a06 (day 4 → day 8). Added "four nights running… on the fifth night". | a06 → a07 | TIM | low-med |
| 24 | 070ffab | a02: "She was barefoot too" implies Leo is barefoot, six lines after "Leo went down the stairs in his socks". The socks later soak, tear and are ruined. | a02 | PHY | high |
| 25 | d15f495 | a02: dangling "it" made the couch, not the fire, burn down. | a02 | PHY (grammar) | low |
| 26 | 0004351 | a06 has Tallow as "old Folk woman" (she/her) and Pip as "Folk girl", vs he/him in a08/a09. The redraft e5c6d4c introduced it. | a08, a09 → a06 | TRT | high |
| 27 | 396ee8d | Residual "Tallow … with her arms folded and her small lined face", missed by 0004351 (incomplete fix). | a06 | TRT | high |
| 28 | 37bc78e (a) | a09: Tallow relights snuffed lanterns in the field with a flint ("Two relit"), vs systems-bible rule 4 (rekindling only at the Great Lamp). It came from the brief. It **resurfaced in visual-state**, fixed in a06ce61. | a09 (rule 4) | WLD | high |
| 29 | 37bc78e (b) | a10: Nora cites "the old words you taught me, the ones from the legend" with no antecedent in a08, and parleying contradicts rule 8. | a08 → a10 | KNO/WLD | med-high |
| 30 | 37bc78e (c) | The name "Ember" is first used in a07 ("Ember had told her about it") with no introduction in a01–a06. It is now introduced at the a05 pledge. | a07 | KNO/TRT | med |
| 31 | 37bc78e (d) | a13 overran: the Lamp's coals "catch and hold", then a14 reopens on a frost-dead bowl. a13 trimmed. | a13 → a14 | PHY | high |
| 32 | 37bc78e (e) | a10's "Two nights ago" points past a09 to a08, and a09 opened mid-attack with no day transition after a08 (day 8 → 9). | a08/a09/a10 | TIM | med |
| 33 | 14233ee | a04/a05 gave the murkwolves volition ("beasts", "hunting", "waiting"), vs rule 8 (elemental, no intent). This was a pass driven by the revision plan. | a04, a05 | WLD | low-med |
| 34 | 33732d7 | a11's unanswered calls for Tallow ("calling and calling … unanswered") were never paid off. a14 now has his waking. | a11 → a14 | PRM | med |
| 35 | 37bc78e (f) | CLAUDE.md still stated the superseded "permanent death, no resurrection" rule, while the systems-bible had it revised. This is reference-level only. | n/a | WLD (ref) | low |
| 36 | a947c04 (vs-only) | Ember carried a04's "walking, tall gold flame" state through a08, where she sits over a thumbnail flame. The going-dark transitions were logged at a12 instead of a11. | visual-state.csv | PHY (metadata) | med |

**Still open at HEAD, unlabeled.** In a11 (HEAD) Wick is "down in the roots in his own house, laid on his own bed … his lantern stood on the boards by his hand". Later the same night, a14 has "Wick lay wrapped in cloth beside the Lamp's base", with his lantern "carried by an old man". No prose moves him. It is plausible (a09 shows dark lanterns being carried to the Lamp), but it is unstated. Also open: the Lamp is "cooking pot" in a04 but "saucepan" in a13 and a14.

**Illustration-only fixes, a separate case type:**
- 66be820: Nora's barefoot transition in the art.
- 43c228c: costume changeover anchored "first two nights", but it is the first night only. LF-04 and LF-05 were swapped.
- a06ce61: a09 visual-state still said "two relit"; the rule-4 violation reached LF-11.
- fdd329e: LF-13 showed every lantern out (the a10 extinction error, a third time).
- 3c96020: LF-20 rendered dawn and the chimney from the paragraph *after* its marker.
- 5e93846: Great Lamp images re-prompted from the unified canon.
- 74b9048 and 99bc61d: images spoiling the page turn.
- 273eb02 and 547d146: LF-19 showed a woken village.
- a211100: LF-14 read as contentment, not grief.
- 11e0f9d: canon anchors drifted.
- 2dd0ea2 and 6c7fa1a: "wardlight" and "wolf-shadows" leaked into 6–7 prompts.

These follow one theme: visual-state granularity is per scene, so a mid-scene change (the Lamp dies at a10's close) resolves to the wrong side.

### 2. The ten strongest cases (quotes verified at the parent commit)

**C1. ab240c6. Survivor count, PHY**
- Established (a13, `ab240c6^`): "The village in the roots of the Oak had been a constellation the first time he'd seen it, dozens of tiny warm lights scattered through the hollows. Now there were four. Maybe five."
- Contradicted (a14, `ab240c6^`): "Around them, the village was silent. The Folk who were still awake had drawn close, dozens of them, their own lanterns held tight against their chests."
- Fix: "The Folk who were still awake had drawn close, and Nora counted them without meaning to. Four. Ember made five. Five small figures where there had been a whole village, and their lanterns dim, barely flickering —"
- Note: a947c04's LLM audit had already run over this, and its message describes "a14 has dozens of awake Folk" as *consistent*. It is a good miss case.

**C2. a947c04. The Lamp's death, all at once vs. cascade, WLD/PHY**
- Established (a11, `a947c04^`): "All around the village the little sounds were going out one by one, like the lanterns had, and each silence was a small surrender she could feel in her chest." Also a13: "Now there were four. Maybe five."
- Contradicted (a10, `a947c04^`): "Every lantern in the village died at once. Nora felt it."
- Fix: "All across the village, lanterns began to go out. Nora felt it. … one and then another and then four at once, stopping mid-note, faster than she could count and from every direction"

**C3. 1d40cae. Wick's lantern in a11, PHY/TIM**
- Established (a08, `1d40cae^`): "They had laid him on his own bed and set the lantern next to him where it belonged, and his mother had not made any sound at all". Also a07: "Far below, Wick's lantern lay on the stones, cold and lightless." (scenes.csv: a07 day 8, a11 day 11)
- Contradicted (a11, `1d40cae^`): "She knew it by touch. She had held it before, when it was warm, when the glass still glowed the color of honey and Wick's face had peered out at her through the light." Also: "She pressed Wick's lantern against her shirt"
- Fix: "Somebody's. She didn't know whose. It had been burning a minute ago." plus "Wick wasn't here. Wick was down in the roots in his own house, laid on his own bed with his mother sitting beside him, and his lantern stood on the boards by his hand where they had set it, dark since the creek."
- The same commit fixes "Wick's face … through the light" against a03's "Wick looked at her. Then he reached out and set his lantern on the tip of her finger."

**C4. 2dd0ea2. "Yesterday", TIM**
- Established (a10 itself, `2dd0ea2^`): "The night the five went dark, the circle of gold had still covered the outer root-houses. Last night it had shrunk back to the inner ring. Tonight it stopped at the square." Wick went dark before that, in a07 ("He hit the stones by the creek and didn't move.", day 8).
- Contradicted (a10, `2dd0ea2^`): "Wick's house with its green door where she'd sat yesterday and listened to him laugh."
- Fix: "Wick's house with its green door, where she used to sit and listen to him laugh."

**C5. 0004351 (+396ee8d). Tallow's and Pip's gender, TRT**
- Established (a08, `0004351^`): "Tallow's lantern swung from a hook on his belt, throwing their shadows long and strange against the bark. He had not spoken since they left Wick's darkened house." (a09: "Pip ran back and forth across the square … He carried no messages between them.")
- Contradicted (a06, `0004351^`): "The old Folk woman worked without speaking, her hands quick and sure, and Nora handed her each piece the way Tallow showed her". Also "Pip landed on Nora's shoulder. The Folk girl weighed almost nothing". Residual, at `396ee8d^`: "Tallow stood beside her with her arms folded and her small lined face sharp."
- Fix: "The old Folk man worked without speaking, his hands quick and sure" / "The Folk boy weighed almost nothing" / "with his arms folded and his small lined face sharp."
- Note: no CSV or bible recorded the pronouns at the time (see §3).

**C6. 070ffab. "Barefoot too", PHY**
- Established (a02, `070ffab^`): "Leo went down the stairs in his socks, hand on the banister, testing each step for the ones that creaked."
- Contradicted (a02, `070ffab^`): "She was barefoot too, still in her pajamas" and "The boards were cold and gritty under his feet."
- Fix: "She was barefoot, still in her pajamas" / "The boards were cold and gritty under his socks."
- This is within one scene. The art pipeline had "fixed" it in images only (66be820), and a reader note was still live.

**C7. 2d4c323. Leo talks with the Keeper, KNO**
- Established (a03, `2d4c323^`): "'His ears are too old?' … 'Too old,' Wick said". (a08: "Nora translated in a whisper." a14: "Three words, clear as a bell, in a voice he had never heard and knew at once.")
- Contradicted (a12, `2d4c323^`, Leo POV): "A pause. Then the old voice, low and calm and close to the ground. 'I am here, child.'" and "'Any true flame,' the Keeper said." Also "It came to him as a thin, insistent whine, like a mosquito he couldn't find."
- Fix: "'She says she's here,' Nora said." / "'She says any true flame,' Nora said. 'Kindled by hands. Not by the Lamp.'"

**C8. 81517bd. The Great Lamp as a stone hearth in a13, PHY**
- Established (a04, `81517bd^`): "The Great Lamp sat in a hollow at the base of the Oak, cradled in a bowl of living wood that the tree had grown around it. It was the size of a cooking pot, which was enormous here, among the Folk."
- Contradicted (a13, `81517bd^`): "And at the center, where the Great Lamp had burned, a thin curl of smoke rising from coals that were almost gray." and "He lowered the matchstick toward the Lamp's hearth."
- Fix: "And at the center, in its bowl of living wood, the Great Lamp. Its glass had gone cold and grey. … dark, it was just an old bronze pot the size of a saucepan, with a thread of smoke climbing out of it into the still air."

**C9. 37bc78e. Tallow relights lanterns in the field, WLD**
- Established (`reference/systems-bible.md` rule 4, `37bc78e^`): "A darkened Folk can be rekindled **only at the Great Lamp**, and **only before his or her flame goes fully cold**." I found no establishing prose sentence before this commit. The rule lives in the bible; the prose rule in a07 is "A sleep that does not end on its own."
- Contradicted (a09, `37bc78e^`): "He wedged the wax-cake against a stone, struck his flint, and coaxed the stub-end of a wick to catch." / "He moved to the next dark lantern and did it again. Two relit. Two still dark."
- Fix: "He wedged the wax-cake against a stone and began cutting it into slabs with a blade like a splinter of tin, and two other Folk carried the slabs off down the line, packing them under the lanterns that were still burning. / Not the dark ones. Tallow did not so much as look at the dark ones."

**C10. 81517bd. "She couldn't hear him", WLD/KNO**
- Established (a05, `81517bd^`): "She had heard him — she always could. That was the crooked arithmetic of the whole thing, and it had bothered him since the first night: every one of them could hear him perfectly well. It was only ever the other direction that failed."
- Contradicted (a04, `81517bd^`): "She couldn't hear him any more than he could hear her, but her eyes were clear and steady"
- Fix: "She could hear him well enough — it was only ever the other direction that failed — but he had nothing to say that would help, so he said nothing, and she answered the nothing anyway."
- Note: the a05 line arrived in 37bc78e, so the contradiction was created by that commit, then fixed here.

**Runners-up with clean pairs:**
- **60f1186.** The rule as stated in a11: "'The Keeper said if the Lamp went dark they'd all go into the deep sleep,' Nora whispered. 'She said there was no waking from it.'" It conflicts with a08's "That is the truth I have watched come true, one lantern at a time."
- **28b945f.** a04's "'Tell her we'll come back tomorrow night,' he said." plus walking home, vs a05 opening on the ledge the same night.
- **81517bd (c).** a14's "The wicks were stiff with weeks of frost." vs the Lamp dying hours earlier in a10.

### 3. Facts later prose depended on but no CSV recorded

- **Tallow and Pip are male.** There was no pronoun record at 0004351, and `characters.csv` has only `id|name|role|aliases`. `character-bible.md` has no Tallow or Pip entries even at HEAD. The pronouns are recorded only in `reference/canon/characters/tallow.md` and `pip.md` ("An older Lantern man", "A young Lantern boy"), created on 07-28, ten days after the fix.
- **The Folk hear humans; the barrier runs one way.** It was never recorded in the CSVs. `knowledge.csv` has `k-nora-can-speak` ("Nora alone can hear and speak with the Folk; Leo cannot"), which wrongly implies Leo can't be heard either. Systems-bible rule 7 states only that younger ears hear the Folk. The one-way fact lives only in a05 prose.
- **Survivor count (five, including Ember).** It is not in `knowledge.csv` or scene-briefs. `visual-state.csv` recorded it only after ab240c6, in the a14 row "only five still awake (Ember among them)". Before that, the a11 brief said "the whole village goes cold and silent".
- **Wick's location and state.** Laid on his own bed with his lantern (a08), and dark since day 8. The physical-state chain records only the token `wick-cold`. There is no knowledge fact and no location. visual-state has `wick-state` at a07 and then a14 only, which is why the a11 and a14 location question is still open.
- **A Folk carries their lantern; they are not inside it.** No record existed, and the error originated in prose. `k-lanterns-are-lives` ("Each Lantern person's flame is his or her life") is ambiguous.
- **Ember's name, and when the children learn it.** `characters.csv` has the alias `keeper;Ember;the Keeper`, but nothing in knowledge_in/out says when Nora or Leo learn the name.
- **Physical dimensions of the Great Lamp.** No CSV recorded them before `reference/canon/locations/the-great-lamp.md` (07-28). Before that, only the a04 prose held them.
- **The Lamp's death cascade (one lantern at a time).** `k-lamp-out` ("The Great Lamp has gone fully out") is silent on its effect. The a10 brief said "the whole village goes cold and silent", so the brief **originated** the a10 and a11 errors. Likewise the a11 brief had "Nora cups Wick's cold lantern" and the a09 brief had the field relight. Several errors were brief-first.
- **Leo in socks, Nora barefoot.** `visual-state.csv` (`nora-clothing`) only, from 07-29. There is no `leo-clothing` row for socks at the time. The current a02 note, "the socks are gone by the time she reaches the grass", is stale since 89e7146 made a02 two nights.
- **Day numbering.** It lives only in `scenes.csv.timeline_day` plus `reference/timeline.md`. Prose relative cues ("yesterday", "two nights ago", "three nights") are not tracked anywhere.

### 4. Data-quality notes

- **Scene ids are stable.** No renames happened; the 15 ids have been unchanged since `c7d145b` (07-17), and no blanks were found. The ids carry a positional `aNN-` prefix, which contradicts the evals standing decision on non-positional ids. Pre-scene-map spine and architecture rows use other keys; see `architecture_scene` in scenes.csv.
- **Schema.** All files are pipe-delimited.
  - `knowledge.csv` is `id|fact|name|aliases|category|origin`. It has the extra `fact` column, and `name`, `aliases`, `category` and `origin` are all blank (registry columns added by cleanup in 250731d). There are 15 facts, all coarse plot-level.
  - There is no `physical-states.csv`. Physical state lives in scene-briefs `physical_state_in/out` as bare tokens (`wick-cold`, `carried-flame`, `leo-hearing`).
  - `visual-state.csv` (`entity|from_scene|state|evidence`, 45 rows, 16 tracks) exists only from 7c5e031 (07-29). It is the richest continuity record, but it is illustration-driven.
  - scene-briefs also carries graphic-novel columns (`page_layout`, `panel_breakdown`, …), all empty.
- **Manuscript drift.** `manuscript/chapters/*.md` and `manuscript.md` were last assembled at `0c82541` (07-18), before every era 2 and 3 fix. They still contain "wardlight" and "dozens of them", and chapter-10 still has "died at once"-era text. Extract from `scenes/` only, and never from `manuscript/` as current text. As a historical snapshot it is a free "pre-fix" version, though.
- **Illustration markers.** These are embedded in scene prose since 4af39dc and need stripping before diffing or extraction.
- **Bundled fixes.** 1d40cae (4 fixes), 81517bd (6), 37bc78e (~6), 2dd0ea2 (2) and 28b945f (5) each need splitting into separate cases.
- **Fix-induced errors are worth keeping as their own case type:**
  - c9cd9b3 repaired the seam that 1d40cae broke.
  - 81517bd fixed an a04/a05 contradiction that 37bc78e's new a05 line created.
  - 396ee8d finished 0004351.
  - a06ce61 shows the relight error reappearing in visual-state after the prose fix.
- **Audit artifacts.** `working/illustration-contradictions.md` (a947c04, 2b424b9) holds LLM-audit findings, including two documented false positives ("boots are shoes; a pajama top is a shirt"). Those are useful negatives.
- **Origin of the errors.** Most error-introducing text came from LLM drafting and redrafting (780987e…a0ef409 drafts, e5c6d4c redraft, 5e5aaf3 and a387f4e global polish). Blame the parent to find the introducing commit when labeling "when it broke".

### 5. Yield estimate

There are **36 candidates** (table above, excluding illustration-only). About **22 are high confidence** and about 9 medium.

Fully labeled, this repo yields roughly **25–30 clean cases** with both an establishing quote and a contradicting quote:

- Most era 2 and 3 commits name both sides, and both sides are verifiable at the parent.
- The WLD cases against the systems-bible need a rule as the establishing source rather than prose.

Adding about 10 illustration/visual-state cases (a different modality) and 3–4 fix-induced or regression cases brings the total to about **35–40**.

The remaining items (terminology unification, grammar, PRM) are weak as continuity labels. There is also one unlabeled open contradiction at HEAD (Wick's location, a11 vs a14) that could serve as a held-out "still broken" probe.


---

## governor

Repo: `~/Developer/governor` (1136 commits on HEAD). Surveyed read-only through `git log`, `git show`, `git grep` and `cat`. The source is one Storyforge-built novel (*The Governor*: Tessa Merrin, Elias Vael, Dorren/Doreen Hayle, Governor Voss, Haddon Breck). It was drafted, revised through about 28 revision cycles, extracted to CSVs, and redrafted from briefs several times.

**Bottom line.** This is the richest source so far. The repo carries its own labels:

- `working/plans/continuity-report.md` at `f399507`, a full continuity audit with an "Issues Found / Fixes Applied" table.
- A numbered "Fixes Applied" log in `reference/continuity-tracker.md` that grows with each `continuity-audit` pass.
- Commit bodies that list each fix.
- `working/annotations/2026-03-31-annotations.json`, the author's own reader notes. One of them is a knowledge violation in the author's words: *"does she even know that Dorren is complicit yet?"*

Many errors can be tied to the commit that introduced them **and** the commit that fixed them, so each case gives clean before, error and after trees. Several errors were introduced by Storyforge's own redraft-from-briefs passes. One error, Tessa's burns, came from a CSV misattribution that was copied into the prose and was **never fixed**.

### Id schemes and renames (read this before using any hash)

- **Before 2026-03-14** scene ids are positional (`ch01-sc01`, `merged-ch12-sc02-03`, `new-h1`, `new-v2`, `new-s1`…). Commit `1672588` ("rename 99 scene files to slugs") maps them to slugs. Mappings used below:
  - `new-h1` → `haddons-junction`
  - `new-h2` → `order`
  - `ch01-sc01` → `finest-cartographer`
  - `merged-ch12-sc02-03` → `blackout`
  - `ch10-sc01` → `dorrens-footnote`
  - `ch13-sc01` → `running-the-numbers`
  - `ch13-sc02` → `confrontation-at-stairwell-nine`
  - `ch11-sc03` → `pulled-off-the-column`
  - `new-elias-part1` → `twenty-two-years`
  - `new-v2` → `governors-response`
  - `new-s1` → `sorayas-fifteen-years`
  - `ch16-sc01` → `someone-you-need-to-meet`
  - `merged-ch08-sc02-03` → `deliberate-collapse`

  Get the full map with `git show -M --name-status 1672588`.
- Before slugs, metadata lived in YAML frontmatter and `scenes/scene-index.yaml`. From mid-March it lived in `reference/scene-metadata.csv`. From the extraction on 2026-04-02 it lives in `reference/scenes.csv`, `scene-intent.csv`, `scene-briefs.csv`, `knowledge.csv` and `physical-states.csv`.
- **zsh gotcha:** `"$P:scenes/..."` triggers zsh's `:s` history modifier. Write `"${P}:scenes/..."` or use literal hashes.

### 1. Fix commits that corrected a fact error

Error types: PHY physical, TIM timeline, KNO knowledge, REL relationship, TRT trait or identity, WLD world, PRM promise or setup.

"Intro" is the commit that introduced the error, where I traced it.

| # | Fix hash | Intro | Scene (old id → slug) | Fix | Type | Conf. |
|---|---|---|---|---|---|---|
| 1 | f399507 | 4df2140 | new-h1 → haddons-junction | Haddon's father "Pol Breck" → "Marek Breck" (3×), to match new-h2 | TRT | high |
| 2 | f399507 | 4df2140 | new-h1 | Father's cause of death: chronic cough from mineral vapour → junction-coupling steam breach in the Ashward loop | TRT/PHY | high |
| 3 | f399507 | 4df2140 | new-h1 | Wife "Maren" → "Lenna" (3×) | TRT | high |
| 4 | f399507 | 4df2140 | new-h1 | Wife's fate: "lived another fourteen months before the condition took her" → survived ("Lenna had lived. The condition resolved. The debt did not.") | REL/TRT | high |
| 5 | f399507 | — | ch08-sc02/03/04 | `timeline_day: 3` → `4` (the shaft descent follows the Day 3 discovery) | TIM (meta) | med |
| 6 | f399507 | — | ch26-sc03 | Added a reference to the Terrace Row dead, which had been dropped after new-e2 (flagged as a thread gap) | PRM | low |
| 7 | f481ca8 | feb670e | ch01-sc01 → finest-cartographer | Calla "Tall" → "Small" (new-s3 says "She was small, dark-haired") | TRT | high |
| 8 | f481ca8 | — | new-s1 → sorayas-fifteen-years | Elias now plans to meet Tessa at the Ashward Reach access point, because ch16-sc01 has Tessa find him there. Before the fix he waits at Soraya's for Tessa to arrive. | PHY (location) | med |
| 9 | f481ca8 | d5a34c2 | merged-ch12-sc02-03 → blackout | "refined over eight descents" → "seven descents"; the same scene says "The seventh descent was the last one" | TIM (count) | high |
| 10 | f481ca8 | — | ch10-sc01 → dorrens-footnote | Report placed "four days ago" → "three days ago" (filed Day 2, scene on Day 5) | TIM | med |
| 11 | f481ca8 | — | ch10-sc01 | "The surveys had been waiting for twelve years" → "fourteen years"; "fourteen years" appears in 15+ scenes | TIM | high |
| 12 | f481ca8 | — | new-h2 → order | Notes "carried for nineteen years" → "sixteen years"; "sixteen years" is used 4× in the same scene. "Nineteen" is the sabotage span, so the two spans got conflated. | TIM | med |
| 13 | 29e9f63 | cut of ch07-sc05 (7990997) | ch08-sc02 | "Last night had taught her" → "That first descent had taught her" (the Night 3 descent scene was cut) | TIM | high |
| 14 | 29e9f63 | same | ch08-sc02 | "where they had turned back the night before" → "two nights ago" | TIM | high |
| 15 | 29e9f63 | same | ch08-sc02 | "three nights' depletion" → "lingering depletion" (only one prior descent) | PHY/TIM | med |
| 16 | 965a488 | 8b8a07a | new-elias-part1 → twenty-two-years | "These hands had held her face three hours ago" → "pressed into her depleted palms". The face-cradling happens on Day 10 (ch13-sc02); this scene was then on Day 6. | KNO/TIM | high |
| 17 | 8c18ae3 | — | new-v2 → governors-response | "removed window-then-desk spatial contradiction" (Voss moves to the window, then acts at the desk) | PHY | med |
| 18 | ab2f2f7 | — | merged-ch30-sc04-05 | Nessa's descent Day 24 → 25, to fix an inversion with the Day 25 scene. The continuity report calls the inversion deliberate, and the author's rules call flashbacks a device. | TIM | low |
| 19 | 9bc03f9 | 72d2299 | new-calla-part4 | `timeline_day: 90` → `89`; the prose says "Before tomorrow. Before the descent." | TIM (meta) | med |
| 20 | 8daaefc | — | continuity-tracker | Voss "Arrested Day 25" → "Day 13 (new-v4)" | TIM (ref only) | med |
| 21 | 7ea284c | — | ch04-sc01 / ch20-sc02 | Seeded the "southern access corridor", which ch22-sc02 already called back ("the secondary corridor Elias had noted on the old schematics") with no setup | PRM | med |
| 22 | 1ae8ab0 | pre-1672588 | governors-response | Cassiel "his senior secretary — twenty years managing the Governor's correspondence" → "senior alderman … managing the eastern development accounts"; weight-of-the-rim has "Alderman Cassiel" | TRT | high |
| 23 | 0f4a99a | ed304d5 | walking-the-eastern-development | Cut "different from Dorren's — but complicit". Tessa first learns of Dorren's complicity later the same day in archivists-box. **Author-labeled.** | KNO | high |
| 24 | 0f4a99a | ed304d5 | walking-the-eastern-development | Cut "It was not dead. It was being killed." Author's note: "referencing a nonexistent note. Nothing before said it dead". Also cut tribunal and Article Twelve foreshadowing that "knows what's coming". | PRM/KNO | med |
| 25 | 711eba3 and others | many | heart-of-the-world, ch06/ch11 scenes | Author annotations (8×): the word "governor/governed/governing" appears before Ch 15, where the term is introduced: "Stop spoiling the title!" | KNO (premature reveal) | med |
| 26 | c28f7f0 | e500877 | elias-disarms | Haddon's "His daughter could breathe" (cut) and "his daughter still needed the clinic" → "Lenna". Haddon has a wife, Lenna, and no daughter. | REL/TRT | high |
| 27 | 29e9e63 | — | order | "the note that had been in the left pocket since midday" removed; the note arrives in the evening, per haddons-reckoning | TIM | med |
| 28 | 29e9e63 → c1862d9 | fd576f1 | 15 scenes plus reference docs | Name flip-flop: Doreen → Dorren (29e9e63, 15 scenes), then d2ea7ac and c1862d9 revert to Doreen. c1862d9 says the reference docs said Dorren while the prose said Doreen. | TRT (name drift) | high (drift); low as an eval item |
| 29 | 6c74d09 | — | routine-maintenance | "On Block Fourteen … the stone-cutters" → "Block Fifteen" (the active construction site everywhere else). **Regressed:** HEAD again reads "the stone-cutters on Block Fourteen". | WLD | med |
| 30 | 6c74d09 | — | doreens-reckoning | The personal letter's "*I resign.*" is removed and a separate signed separation form is added, matching doreens-letter: "signed the separation form" | PRM/KNO | med |
| 31 | 6c74d09 / 811b04f | — | ascending-the-shaft | Haddon's escort "three companions" → "the crew"; a later redraft brings back "three companions", and 811b04f makes it "two". The crew count is muddled across order and elias-disarms. | PHY (count) | low |
| 32 | a3ca495 (brief-level redraft) | 7e5e62c | order | Draft had "Doreen four steps back with her survey case, Hanek beside her" inside **Haddon's demolition crew**. Doreen is Tessa's supervisor and is never present. The redraft replaced it with "Two men behind him, then the younger one". | REL/PHY (presence) | high error; fix not isolated |
| 33 | 240f2e5 | f74aa12 | confrontation-at-stairwell-nine | Blackout progression "Eleven seconds, four days ago … Seventeen seconds" → "Four seconds, three days ago … Eleven seconds" (the canonical progression is 4–11–30) | PHY/TIM | high |
| 34 | 240f2e5 | 58df81e | acceptable-losses | Tam Erdel "A child, nine" / "Nine years old" (3×) → "seven"; haddons-reckoning and the tracker give "Tam Erdel. Seven." | TRT | high |
| 35 | ae7eb72 | 0fad803 | commission-testimony | Doreen's testimony "Cartographer Vael's report" (2×) and "Tessa Vael" → "Merrin". The surnames of the two protagonists got merged. | TRT | high |
| 36 | ae7eb72 | — | commission-testimony | "Nine documents. Nine dated entries." trimmed; the exhibit count is fixed to Fourteen–Twenty-Two | PHY (count) | low |
| 37 | 9ee7247 | extraction | characters.csv | Removed `liaret-merrin;Liaret Merrin;Tessa's mother's daughter` from Tessa's aliases ("separate character") | TRT (CSV) | med |
| 38 | f391b73 | extraction (efe169d) | scenes.csv, 98 rows | "Part 4 scenes were incorrectly at day 5/9"; all timeline days re-derived | TIM (CSV) | high as a CSV error; not prose |

Items not listed individually:
- `efe169d` ("239 fixes"), `0fd09cb` ("155 fixes") and `5e4571a`: extraction cleanups covering timeline, knowledge and MICE. These are bulk CSV churn that I could not isolate fact by fact.
- About 30 `continuity-audit` commits that only reconcile word counts.
- `dbdd0d5` and the `6c74d09` tracker strips. These removed inline "continuity tracker" blocks from 11 scenes (ashward-reports, governors-response, finest-cartographer, governors-speech, heart-of-the-world, language-of-depletion, nessa-touches-the-column, rock-network, shimming-the-cot, the-governors-vigil, the-rupture). The blocks record per-scene "established details" and could serve as fact gold. See `git show dbdd0d5`.

### 2. The ten strongest cases: contradicting pairs

Every quote below is taken verbatim from `git show <hash>~1:<path>` unless marked HEAD.

**C1. Haddon's father and wife (TRT/REL), fixed in f399507, introduced in 4df2140.** Both Haddon scenes were drafted in the same commit and contradicted each other from the start. "Established" follows the version the fix kept. By reading order, h1 (Day 5) comes first.
- Kept fact, new-h2 → `order`: "His father. Marek Breck. Gallery engineer, thirty-one years. Died in the tunnels when a junction coupling failed in the Ashward loop and the steam did what steam did to a man standing within six feet of a full-pressure breach." Also: "Lenna lived. The blood condition resolved. The debt did not."
- Contradiction, new-h1 → `haddons-junction`: "Pol Breck, gallery engineer, thirty-one years in the deep sections before the cough took him — the wet, persistent cough that steam workers got…" Also: "Maren had seen the specialist, and the specialist had done what the specialist could do, and Maren had lived another fourteen months before the condition took her anyway".
- Fix: "Marek Breck, gallery engineer, thirty-one years in the deep sections before a junction coupling failed in the Ashward loop and the steam found him" and "Lenna had seen the specialist … and Lenna had lived. The condition resolved. The debt did not."
- Label source: `working/plans/continuity-report.md` (Issues 1–4, "Critical").

**C2. Tessa's burns (PHY), introduced through the CSVs and NOT FIXED.**
- Established, `ashward-breach` (Elias's POV), quoted at d7e98f3~1: "*— Elias Vael, senior gallery engineer (reporting). Second-degree burns, left forearm to shoulder. Sustained during personnel extraction from the affected section. Functional.*" `mothers-and-honest-infrastructure` agrees: "the scar tissue on his left forearm … Burns from the Ashward Breach."
- How the CSV went wrong: `d7e98f3`, "Hone: registries/physical-states" on 2026-04-07 at 07:47, created `burns-left-arm-tessa|tessa-merrin|Second-degree burns left forearm to shoulder with linen wrapping|injury|ashward-breach|never|true`. `4befb51` then copied it into `physical_state_in` across 80 scenes of `scene-briefs.csv`, where `burns-left-arm-tessa` appears 146 times.
- Contradiction: the redraft from briefs that evening (`c1043f4` and `093121f`, "Draft scene junction-fourteen"). HEAD `junction-fourteen` reads: "The burns on her left forearm still pulled when she flexed her fingers, the linen stiff with dried ointment." The burns recur in footnote, nineteen-year-sequence, rock-network, going-to-tessas-boarding-house and archivists-box. Tessa is never burned on the page.
- Fix: none. This is a Storyforge-caused error. In the same file, 73 of 98 physical states are attributed to `tessa-merrin`, which suggests the extractor defaults to the protagonist. `dust-on-knees-and-sleeves-tessa` (acquired in `weight-of-the-rim`, a Voss scene where the dust is on Voss and Sergeant Dahl) is the same kind of error.

**C3. Blackout progression (PHY/TIM), fixed in 240f2e5, introduced in f74aa12 ("redraft 39 scenes from corrected briefs").**
- Established, `blackout`: "Four seconds. Then eleven. Then thirty." `elias-agrees-to-the-terms` has "Four seconds. Eleven. Thirty." and `knowledge.csv` has `tessa-blackouts-lengthening`: "four seconds, then eleven, then thirty".
- Contradiction, `confrontation-at-stairwell-nine`: "\"Eleven seconds, four days ago. You lost motor control in your left hand for six seconds after you came back. You didn't report it.\"" and "\"Seventeen seconds. Two days ago. Your breathing stopped for three of them. I counted.\""
- Fix: "\"Four seconds, three days ago. You were standing at the column access. You didn't report it.\"" and "\"Eleven seconds. Two days ago. …\""

**C4. Premature knowledge of Dorren's complicity (KNO), fixed in 0f4a99a, introduced in ed304d5, labeled by the author.**
- Established, `archivists-box` (seq 42, Day 11 evening): "*Dorren Hayle. Pressure Cartography. Eastern quadrant classification management.*" followed by "Eleven years. Tessa had worked under Dorren for five of those eleven years." `knowledge.csv` has `doreen-hayle-named-conspirator`, origin `archivists-box`.
- Contradiction, `walking-the-eastern-development` (seq 35, Day 11 morning): "That made her complicit. Different from Voss's complicity, different from Dorren's — but complicit."
- Fix: the sentence was deleted.
- Author's note (2026-03-31 annotations): "This is making the crime more explicit than I like. And does she even know that Dorren is complicit yet?"

**C5. Haddon's "daughter" (REL), fixed in c28f7f0, introduced the same day in e500877 ("haddon-climax-expansion").**
- Established in the same scene, `elias-disarms`: "He'd built the whole arrangement around Lenna." In `order`: "Lenna sick in the fourth year of their marriage."
- Contradiction: "…and he could not take it back, and his daughter still needed the clinic, and the pistol was on the floor." Earlier in the scene: "Days she could breathe. His daughter could breathe."
- Fix: "…and Lenna still needed the clinic…", and the "His daughter could breathe." sentence was deleted.
- Unfixed residue: the same passage says Lenna "still needed the clinic", against order's "Lenna lived. The blood condition resolved".

**C6. "Tessa Vael" (TRT), fixed in ae7eb72, introduced in 0fad803 (Apr 7 draft from briefs).**
- Established: Tessa Merrin throughout, for example "Senior Surveyor Merrin's report". Vael is Elias's surname.
- Contradiction, `commission-testimony`: "\"On the fourteenth of Frostmarch, I received Cartographer Vael's report on the eastern pressure anomaly.\"" and "\"I selected Tessa Vael for the eastern survey because her Calibration sensitivity would confirm what I already knew.\""
- Fix: "Cartographer Merrin's report" and "I selected Tessa Merrin…".

**C7. Cassiel's role (TRT), fixed in 1ae8ab0.**
- Established, `weight-of-the-rim`: "Alderman Cassiel was watching, spectacles low on his nose, the quarterly projections spread before him."
- Contradiction, `governors-response`: "Cassiel, his senior secretary — twenty years managing the Governor's correspondence, the man who knew every permit number…"
- Fix: "Cassiel, his senior alderman — twenty years managing the eastern development accounts".

**C8. Calla's build (TRT), fixed in f481ca8.**
- Established, new-s3: "She was small, dark-haired, with the quietness of a woman who had learned to take up exactly as much space as her work required and no more."
- Contradiction, ch01-sc01 → `finest-cartographer`: "Calla was first. Tall, composed, her survey journal already open."
- Fix: "Calla was first. Small, composed, her survey journal already open."
- Caveat: new-s3 was later cut (9f14676). The tracker re-logs the fix as "consistent with ch05-sc04".

**C9. A face touch referenced before it happens (KNO/TIM), fixed in 965a488, introduced in 8b8a07a.**
- Established, ch13-sc02 → `confrontation-at-stairwell-nine` (Day 10): "He cupped her face. Both hands. Palms against her jaw, fingers along her cheekbones…" On Day 5, ch11-sc03 ends with hand-tending: "Elias took her hand in both of his."
- Contradiction, new-elias-part1 → `twenty-two-years` (then Day 6): "These hands had held her face three hours ago."
- Fix: "These hands had pressed into her depleted palms three hours ago. Had felt the warmth of her skin returning…"

**C10. Descent count after a cut scene (TIM), fixed in 29e9f63.** The cut of ch07-sc05 (the Night 3 second descent) left ch08-sc02 pointing at a night that no longer happens.
- Established, timeline: the first descent is on Day 2 night, the second descent was cut, and ch08-sc02 is on Day 4 night.
- Contradiction, ch08-sc02: "Last night had taught her the sealed galleries' rhythms", "The polished stone began where they had turned back the night before", and "the faint residual tightness of three nights' depletion".
- Fix: "That first descent had taught her…", "…turned back two nights ago…", "…of lingering depletion".

Runners-up, each with a pair already verified above: Tam Erdel's age (#34), "eight → seven descents" (#9, contradiction within one scene), "twelve → fourteen years" (#11), and Doreen inside Haddon's crew (#32).

### 3. Facts later prose depends on that the CSVs never record, plus contradictions still in HEAD

**Schema gap.** `characters.csv` has only `id|name|aliases|role|death_scene`. It has no fields for traits, relationships or age, so it cannot record any of the facts that drove the TRT/REL fixes:
- Calla is small.
- Cassiel is an alderman.
- Tam Erdel is 7 and Sera Holdt is 68.
- Lenna is Haddon's wife and survived.
- Marek died in a coupling breach when Haddon was 19.

`lenna`, `marek-breck`, `cassiel` and `tam-erdel` exist only as name rows. `death_scene` is empty for `sera-holdt` and `tam-erdel` even though both die on the page.

**Not in any CSV:**
- the count of descents and mapping sessions
- the 14-year sealing
- Haddon's 16-year arrangement versus the 19-year sabotage
- the Elias and Tessa touch chronology (hands on Day 5, face on Day 10)
- which building is under construction (Block Fifteen)

**Recorded with the wrong origin:** `knowledge.csv` gives `tessa-blackouts-lengthening` the origin `finest-cartographer` (seq 1, a Doreen scene on Day 1), before any blackout happens.

**Contradictions still in HEAD.** None of these were caught. They are candidates for unlabeled cases.

- **Tessa's burns** (C2): the prose follows a CSV misattribution.
- **Sera Holdt has two identities.** In `acceptable-losses`, Voss's office worker is named Sera Holdt ("centered on the blotter where Sera Holdt had placed it"), and the same scene lists the dead as "An elderly woman, seventy-three." `haddons-reckoning` has "Sera Holdt. Sixty-eight. Upper floors", while `the-governors-vigil` has "Sera Holdt. First floor, nine years." "Sera" is also the name of a Calibrator benchmark case. Types: TRT and PHY.
- **Block Fourteen and Fifteen.** The 6c74d09 fix regressed: `routine-maintenance` again says "the stone-cutters on Block Fourteen". `article-twelve` says "The sabotage had begun before Block Fifteen's foundations were poured" (more than 19 years ago), while `terrace-row` (Day 7) has crews "preparing Block Fifteen's foundations". Types: WLD and TIM.
- **Marek's service.** `order` says both "a man who'd spent thirty years in galleries" and "Forty-eight years of honest work". It also says "Haddon had been twenty-three", against "Haddon had been nineteen" in the pre-slug new-h2. Type: TRT/TIM.
- **Where the thirty-second blackout happened.** `elias-agrees-to-the-terms` says "Thirty at Fenwick Row", while `blackout` and `confrontation-at-stairwell-nine` put it at the column ("The one from last night, in the eastern gallery"). Type: PHY/TIM.
- **Noted but never fixed** in the March reports:
  - Dorren says the Thornveil map was "eleven days ago" both on Day 1 (ch02-sc03) and on Day 3 (ch07-sc03).
  - Elias is "well over six feet" in the prose but 6'0" in the character bible.
  - Elias's reports span "twenty-three months" in one place and "two years" in another.

### 4. Data-quality notes

- **Branch.** HEAD is `storyforge/visualize-20260417-2158` at 8e10648. It is exactly 4 commits ahead of `main` at 9ccdd00 (cost ledger, cover jpg, dashboard, publish manifest) and 0 behind. Prose, CSVs and reference files are identical to `main`, so either one works.
- **99 vs 100.** There is no real mismatch. `scenes/` holds 99 `.md` files plus a `working/` subdirectory (`scenes/working/{absorbed,plans}`), which makes 100 entries. Scene ids and `scenes.csv` ids match exactly. The other CSVs show 100 lines including the header.
- **Manuscript drift.** There are two stale assemblies:
  - `manuscript/Chapter 01–34.md`: 34 files last touched 2026-03-03 (`6b45c48`). They use pre-slug structure and the "Dorren" spelling, with 26 hits in Ch 01.
  - `manuscript/chapters/chapter-01–31.md`: 31 files, about 90.1k words, last assembled 2026-04-08 (`3c8d460`).

  `scenes/` is about 78.6k words after the Apr 15–16 redrafts, which rewrote 60 scenes from briefs. Neither manuscript matches the scenes. The "~90k in manuscript" in the brief is the Apr 8 assembly. `chapter-map.csv` has 31 rows.
- **Timeline drift between the CSV and the reference files.**
  - `scenes.csv` puts the coda on Day **103**: 7 scenes, including `three-months-later`, `first-session` and `like-a-beginning`.
  - The Dorren visit is on Day 26/27 and Calla's confession (`road-she-didnt-take`) on Day 27.
  - `continuity-tracker.md` and `timeline.md` still say Day 90, Day 21 and Day 89.
  - `confrontation-at-stairwell-nine` is Day 7 in `scenes.csv` but Day 10 in the older metadata.

  The CSV timeline was re-derived by extraction (`f391b73`) and by later redrafts. The tracker was never updated after 2026-04-08 and still uses `ch`-era ids and "Ch. 33" chapter numbers. Treat it as a March-era record.
- **Name churn.** The rename-doreen pass, the Dorren standardization and the revert back to Doreen produce noise on `-S` searches. Slugs still use `doreen` (`doreens-reckoning`, `going-to-doreen`) while older slugs use `dorren` (`dorrens-footnote`).
- **Many errors come from regeneration.** Storyforge's redraft-from-briefs passes introduced several errors: f74aa12 (C3), 0fad803 (C6), 58df81e (#34), 7e5e62c (#32) and the d7e98f3/4befb51 chain (C2). Integration sweeps such as 240f2e5 and ae7eb72 often caught them the same day. This gives an eval clean triples: pre-error tree, error tree, fix tree.
- **Other schema quirks:**
  - `scenes.csv` mixes slugged location ids with free text.
  - `motif-taxonomy.csv` has only a header.
  - `physical-states.csv` is heavily skewed toward Tessa (73 of 98).
  - `reference/scene-metadata.csv` (pre-extraction) and the scene-file YAML frontmatter are deleted in HEAD, so recover them from history.
  - Inline continuity-tracker blocks once lived inside scene files (removed in dbdd0d5 and 6c74d09).

### 5. Yield estimate

- **About 38 individually labeled fact fixes** (table above). About **17 are high-confidence** genuine continuity errors with verifiable establishing and contradicting text: #1–4, 7, 9, 11, 13, 14, 16, 22, 23, 26, 33, 34, 35, plus #32 as an error. About 12 are medium and about 9 are low or CSV-only.
- **About 6 unlabeled contradictions still in HEAD** (section 3), with C2 the strongest.
- **Realistic eval yield: 15–20 strong items.** The mix is TRT-heavy (names and roles: 8), then TIM (7), KNO (3), PHY (3) and REL (2).

Why the yield is high:
- The repo labels itself: a continuity report, numbered audit logs and the author's annotations.
- Most errors are one-sentence prose fixes.
- Many have a traceable introducing commit.

Limits:
- Some "established" facts were themselves chosen arbitrarily during harmonization (C1).
- Pre-March-14 cases need translating to slug ids.
- Several fixes happened inside full redrafts and cannot be isolated (#32).
- The bulk CSV cleanups (efe169d, 0fd09cb) are not itemizable.


---

## meridian-line

Repo: `~/Developer/meridian-line` (904 commits). Surveyed read-only via `git log`/`show`/`grep`.

**Read this first: names and ids changed twice.**
- `c83e85c` (2026-03-04): an early rename in the reference docs (Elias Voss → Emmett Slade, Tessa Merrin → Lena Callis, Declan Merrin → Rowan Callis). It came before almost all the prose.
- `dc37cda` (2026-04-03, PR #57): a **deliberate authorial name swap**. The surveyor protagonist Lena Callis became **Cora Dunning**. The boarding-house keeper Cora Dunning became **Lena Callis**. Rowan Callis became Rowan Dunning. This is not a continuity error and nothing in it is labelled as one. Every commit before 2026-04-03 uses the old names: *Lena* = surveyor, *Cora* = boarding-house keeper. All quotes below are verbatim from the pre-fix trees, so they use the old names.

### 1. Fix commits that corrected a detail or fact error

Scene ids are given as *old id → current slug*.

| # | Commit | Fix | Scene(s) | Type | Conf. |
|---|---|---|---|---|---|
| 1 | `68e913d` (sweep) | Solo-station count "twenty-five" → "twenty-six" (stations 164–189 = 26) | `16` → porch-and-name | PHY (quantity) | high |
| 2 | `68e913d` | Same fix, "Twenty-five stations remain" | `18` → evidence-laid-out | PHY | high |
| 3 | `68e913d` | Same fix, "twenty-five stations left to measure" | `21` → road-east | PHY | high |
| 4 | `68e913d` | "twenty-five stations behind her and ten ahead" (35 total) → "sixteen … behind" (26 total) | `25` → emmett-presents-case | PHY/TIM | high |
| 5 | `05dbd1e` (sweep) | Emmett's ledger "small book, leather-bound" → "plain composition book, its cover warped from carrying" | `1` → arranged-dead | PHY (object) | high |
| 6 | `05dbd1e` | "Twenty-five stations left" → "Twenty-six" (missed by the previous sweep) | `20` → midnight-arrival | PHY | high |
| 7 | `05dbd1e` | "six county seats" → "three county seats" | `31` → testimony / emmett-testifies | WLD (case fact) | high |
| 8 | `05dbd1e` | "across six counties" → "across three counties" | `31` → emmett-testifies | WLD | high |
| 9 | `6a2556d` (sweep, F012) | Added Lena's knowledge of Keele's falsified map to the planning scene (it was omitted) | `18` → evidence-laid-out (knowledge from `16` → inside-study) | KNO (omission) | med |
| 10 | `6a2556d` (F024) | Added who wrote the falsified official summary (Webb) | `12` → statement-at-coras-kitchen → statement-at-lenas-kitchen | PRM/logic gap | low |
| 11 | `15c12b7` (squash PR #7, third-revision sweep) | "Thomas sat his paint" → "Thomas sat his dun". The error and fix both happened inside one squash, so the pre-fix text is **not on main**. Labelled only by continuity-tracker.md | `30c` → devils-river → crossing | PHY (horse) | high (label) / pre-fix text unrecoverable |
| 12 | `bbf0852` (sweep) | Station-38 "three weeks of shared fieldwork" → "five days" | station-38 | TIM | high |
| 13 | `bbf0852` | Barrera's report "delivered in this room two weeks ago" → "nine days ago" | charter-and-the-reckoning | TIM | high |
| 14 | `bbf0852` | Deleted the stray closing line "Barrera rode south." from a Thomas-POV scene | seep-spring | KNO/POV (VOI) | low |
| 15 | `0585a5e` (sweep) | Cora "outlived two husbands and raised four children" → "been feeding this town for twenty-three years" (her four children are dead) | coras-intelligence → lenas-intelligence | TRT (backstory) | med |
| 16 | `005fd2d` (squash PR #47, "Fix three review items") | numbers-without-witness "Three days" → "Nine days" since the separation. Introduced and fixed inside the squash, so the pre-fix text is **not on main**. The fix is quoted in the commit body and flagged in `working/archive/reviews/pipeline-review-20260401-013705.md` (C2) | numbers-without-witness | TIM | high (label) / pre-fix unrecoverable |
| 17 | `30aebf0` | Mescalero place name *tú biká dah si'áné* was attributed to Naseka (Tonkawa); reattributed to "Thomas's people" | thomas-in-the-courtroom | TRT/WLD (ethnicity/language) | high |
| 18 | `30d9b3a` (CSV) | scenes.csv `timeline_day` for station-38: 5 → 9 (prose says "fifth evening" of fieldwork, after day 8) | station-38 | TIM (CSV) | high |
| 19 | `30d9b3a` (CSV) | scenes.csv `timeline_day` for clara-oakes-rides-in: 5 → 28 (prose says "On the fifth night" of the solo survey, after day 27) | clara-oakes-rides-in | TIM (CSV) | high |
| 20 | (redraft `c2e2e8c`, 2026-04-05) | thomas-in-the-courtroom said Thomas had stood there "for eleven days", but the trial opened day 78 and this scene is day 85. Flagged in pipeline-review-20260402-211658 §6 and as plan item "continuity-fixes" in `dc37cda`. It disappeared in a full redraft, so the fix can't be isolated | thomas-in-the-courtroom vs trial-opens | TIM | med (label) / low (isolable) |
| 21 | `d8208ec` (CSV) | lenas-house-at-war `timeline_day` 14 morning → 13 night. The scene was still only `briefed` (no prose), so this is planning-data only | lenas-house-at-war | TIM (CSV) | low |
| 22 | `2104341` (CSV) | 84 forward references removed from `knowledge_in` in scene-briefs.csv. This is a bulk validator cleanup of extraction artifacts (e.g. arrest-at-keeles-settlement had `keele-arrested` as *input*; crossing had `verdict-guilty`) | many | KNO (CSV) | low for an eval (bulk, mechanical) |

**Totals:** 22 items. 19 have recoverable before/after text on main (rows 1–10, 12–15, 17–19, 21–22). Rows 11 and 16 exist only as labels inside squash commits. Row 20 was fixed by a redraft. About 15 are high-confidence.

**Leads that turned out not to be errors:**
- `bc81c01`: duplicate seq.
- `19fe2f3`: duplicated paragraph, not a fact error.
- `6377cd8`: a thematic thread closure.
- `bfb9dff`, `8cdc1af`, `e290556`: voice and seeding changes.
- The name swap in `dc37cda`.

### 2. The ten strongest cases: contradicting pairs

All quotes were checked with `git show <hash>^:<path>`.

**Case A: station-38, "three weeks" vs "fifth evening" (TIM, high, contradiction inside one scene). `bbf0852`**
- Established (station-38, `bbf0852^`): "On the fifth evening they made camp at Station 38, where the creek bent south around a limestone outcrop…"
- Contradicted (same scene): "Somewhere in the three weeks of shared fieldwork, her instrument had adjusted to include him."
- Fix: "Somewhere in the five days of shared fieldwork, her instrument had adjusted to include him."
- Related CSV fix in `30d9b3a`: station-38 `timeline_day` 5 → 9.

**Case B: when Keele learned of the surveyor (TIM, high). `bbf0852`**
- Established (judges-morning, `bbf0852^`; `timeline_day` 3): Barrera reports in Keele's study: "A woman came to Meridian on yesterday's stage. Surveyor. Working for the T&P." … "Her name is Callis."
- Contradicted (charter-and-the-reckoning, `timeline_day` 12): "Keele had expected it since Barrera's last report -- the one delivered in this room two weeks ago, the one that said the Callis woman had arrived in Meridian and asked for Thomas Bright Horse."
- Fix: "…the one delivered nine days ago, after the woman first arrived in Meridian and asked for Thomas Bright Horse." Day 3 + 9 = day 12.

**Case C: Naseka is Tonkawa, but the place name is Mescalero (TRT/WLD, high). `30aebf0`**
- Established (seep-spring, `30aebf0^`): "Naseka, who was Tonkawa, and who should have been an enemy by every rule of blood and history…"; "A Tonkawa song for the dying, which Naseka said his mother had sung to his father when the fever came." Also characters.csv: `naseka|Naseka|Tonkawa guide|referenced`.
- Contradicted (thomas-in-the-courtroom): "Naseka had called it *tú biká dah si'áné,* the stone that stands above water … and never once hold the Mescalero name for the place where the bearing was shot."
- Fix: "Thomas's people called it *tú biká dah si'áné,* … Naseka had shown the spring to Rowan Callis on the ninth day of the survey…"
- **Label noise:** pipeline-review-20260402-211658 §4 wrongly asserts that earlier scenes made Naseka "Mescalero". The cycle-13 plan in `dc37cda` also proposed keeping "Tonkawa" in the court record as a deliberate court error. Only the commit's own rationale is correct.

**Case D: what Emmett's ledger looks like (PHY, high). `05dbd1e`**
- Established (scene `3` → coras-table, `05dbd1e^`): "It was a plain composition book, the sort a schoolchild might use, its cover warped from two years of being carried in the inside pocket of his coat and then locked in the drawer when carrying it became too much of a risk." Also scene `10`: "Plain composition book, warped cover, the spine cracked from two years of careful, methodical entries that no one had ever seen."
- Contradicted (scene `1` → arranged-dead): "Emmett had started his own ledger. A small book, leather-bound, that he kept in the bottom drawer of his desk beneath a stack of Army dispatches."
- Fix: "A plain composition book, its cover warped from carrying, that he kept in the bottom drawer…"

**Case E: three counties vs six (WLD/case fact, high). `05dbd1e`**
- Established (scene `3`): "Forty-seven entries. Each one a land transaction filed at a county seat in one of three counties." Scene `10`: "Forty-seven entries. Three counties." Scene `18`: "Forty-seven land transactions across three counties."
- Contradicted (scene `31` → emmett-testifies): "Sheriff Slade, you've submitted into evidence forty-seven land transactions filed across six county seats between 1869 and 1872." Also "…a county sheriff investigating land transactions across six counties, without a federal warrant…"
- Fix: "three county seats" and "across three counties".

**Case F: the solo segment is 26 stations, not 25 (PHY quantity, high). `68e913d`**
- Established (scene `29` → ride-south, `68e913d^`): "But stations 164 through 189 were hers. Twenty-six stations past the place where her father's work stopped."
- Contradicted, in three places:
  - Scene `16` → porch-and-name: "She had twenty-five stations left to survey."
  - Scene `18` → evidence-laid-out: "Twenty-five stations remain. When I finish, the line will run … one hundred and eighty-nine stations…"
  - Scene `21` → road-east: "…worked alone in open country with a transit and a rifle and twenty-five stations left to measure."
- Fix: each one changed to "twenty-six". Scene `20` ("Twenty-five stations left.") was missed and fixed in the next sweep, `05dbd1e`.
- The establishing sentence was itself cut later, so the "164 through 189" anchor survives only in pre-split trees.

**Case G: stations behind plus ahead add up wrong (PHY/TIM, high). `68e913d`**
- Established: as in Case F (26 solo stations).
- Contradicted (scene `25` → emmett-presents-case): "…she had twenty-five stations behind her and ten ahead…" That makes 35.
- Fix: "…she had sixteen stations behind her and ten ahead…"

**Case H: Cora's four children were buried, not raised (TRT, med). `0585a5e`**
- Established (bread-and-cellar, `0585a5e^`): "The hotel clerk — the boy of seventeen whose name she could never remember because she had buried four children and some part of her had stopped committing young faces to memory — …" Also coras-table: "The nod of a woman who had survived the war and two husbands and four children in the ground…"
- Contradicted (coras-intelligence): "…the attention of someone who had outlived two husbands and raised four children and still set the table every morning because the alternative was not setting it."
- Fix: "…the attention of someone who had been feeding this town for twenty-three years."
- **This was a partial fix.** coras-porch still read "a woman who had buried two husbands and raised four children" after `0585a5e`. That line went away only when lenas-porch was redrafted (`7010533`). A sweep that missed a sibling instance is a useful negative example.

**Case I: Lena's knowledge of the map missing from the plan (KNO omission, med). `6a2556d` (F012)**
- Established (scene `16` → inside-study, `6a2556d^`): "…along that corridor, marked in a different hand than the settlement survey, were benchmark elevations." And: "The benchmarks on the map placed the terrain along the southern corridor at elevations consistently lower than the elevations her transit and her father's transit had recorded for the same ground."
- Contradicted by omission (scene `18`): Lena's evidence inventory lists the field books and the journal but not the map. The flag came from eval-20260305 F012: "Scene 16 knowledge not reflected in Scene 18 plan".
- Fix (added line): "And I've seen his map. The falsified benchmarks are on his study wall -- drawn in a different notation than the settlement survey, adjusted at twelve stations I counted. He built the fraud into his own records…"
- **Caveat:** the fix invents a number ("twelve stations") that scene 16 never established.

**Case J: Thomas's horse (PHY, high label, pre-fix text not on main). `15c12b7`**
- Established (scene `19` → thomas-rides-south): "A dun gelding, not young, with the deep chest and short cannon bones of a horse bred for country that punished anything fragile."
- Contradicted (scene `30c` → crossing, introduced by the barrera-arc-completion pass inside squash PR #7): "Thomas sat his paint". This is quoted only in continuity-tracker.md (`6b52cd9^`).
- Fix (`15c12b7:scenes/30c.md`): "…rode to the north bank and stopped ten feet from where Thomas sat his dun."
- To use it, rebuild the pre-fix sentence by substituting "paint" for "dun".

Runner-up: `005fd2d` numbers-without-witness "Three days" → "Nine days since the separation. Twenty-three days into the survey." The fix is quoted in the commit body. The pre-fix sentence is not on main.

### 3. Facts later prose depended on that were never recorded in the CSVs

Checked against the current `reference/knowledge.csv`, `physical-states.csv` and `characters.csv`.
- **The ledger is a plain composition book.** Absent. knowledge.csv has only "47-entry ledger".
- **The fraud spans three counties** (Pecos, Reeves, Presidio). Absent. Only `keele-accelerates-filings` mentions Pecos County.
- **The solo segment is stations 164–189, 26 stations.** Absent. Only `survey-complete-189-stations`.
- **Thomas's dun gelding and Barrera's dark bay** (which favours the right foreleg on downhill stands). No horses appear anywhere in physical-states.csv. continuity-tracker.md recorded both as "locked", but it was archived (`6b52cd9`) and never migrated.
- **The boarding-house keeper buried four children and two husbands.** Absent. It survives only in prose and in scene-intent text ("four children buried east of town").
- **Naseka is Tonkawa and Thomas is Mescalero.** Now **wrong** in the registry. Hone commit `5433d3f` ("0 normalizations") moved the alias "Tonkawa guide" off Naseka and onto Thomas. It still reads `thomas-bright-horse|…|Thomas;Tonkawa guide` and `naseka|Naseka|referenced|naseka`. This is a live TRT error that a tool introduced, and a Storyforge bug candidate.
- **When Keele learned of the surveyor (day 3, via Barrera).** Not recorded. Case B depends on it.
- **physical-states.csv has live misattributions.**
  - emmett-returns-to-town is an Emmett-POV scene on day 13 while the surveyor is in the field. Its entries were relabelled to the surveyor by hone `0d970bd`: `eight-day-ride-fatigue-cora`, `shoulders-aching-cora`, `knees-aching-cora`, `mental-cleared-pattern-cora` "…pattern recognition in dark office".
  - architect-in-his-cell is Keele's scene. It originally had `imprisoned-webb`/`weight-loss-webb`. Those were deleted, and Keele never received a confinement state.

### 4. Data-quality notes

**Three generations of scene ids:**
- Numbered `1.md`–`33.md` plus `30b`, `30c` (until 2026-03-13).
- Renamed to chapter slugs (`59e5947`, R100 renames, e.g. `1.md` → geometry-of-dying, `16.md` → surveyor-and-the-judge, `18.md` → architecture-of-the-case, `30c.md` → devils-river, `31.md` → testimony).
- Then split into 75 scenes (`a05c8a5`) and merged back to 64 (`37fd603`). Later scenes were added to reach 66–69.

Mapping the fixed lines through the split (found by `git grep` at `37fd603`):

| Old id | Slug after split |
|---|---|
| 1 | arranged-dead |
| 3 | coras-table |
| 10 | emmett-returns-to-town |
| 12 | statement-at-coras-kitchen |
| 16 | porch-and-name (map content → inside-study) |
| 18 | evidence-laid-out |
| 19 | thomas-rides-south |
| 20 | midnight-arrival |
| 21 | road-east |
| 25 | emmett-presents-case |
| 28 | last-station |
| 30c | crossing |
| 31 | emmett-testifies |

- **Name swap (`dc37cda`)** also renamed slugs:
  - coras-* → lenas-*
  - lena-testifies → cora-testifies
  - lena-alone → cora-alone

  For about a day after the swap, characters.csv had mismatched ids (`lena-callis|Cora Dunning`), fixed in `771687b`. Any text-based extraction has to be swap-aware by date.
- **Squash merges hide pre-fix text.** PRs #7 (`15c12b7`) and #47 (`005fd2d`) squashed their revise/continuity passes. Errors introduced and fixed inside them leave no pre-fix tree on main. The labels survive only in commit bodies and continuity-tracker.md.
- **continuity-tracker.md** (reference/, deleted in `6b52cd9`) is the best label source. It has explicit "X → Y" correction logs and "locked details". It is written in the swapped names, because `dc37cda` rewrote it before it was archived.
- **Schema churn:**
  - scene-metadata.csv (until `dc37cda`) was replaced by scenes.csv, scene-intent.csv and scene-briefs.csv.
  - characters.csv columns were reordered (`f401966`), so an old "role description" column became "aliases". That is likely how "Tonkawa guide" ended up as an alias.
  - CRLF churn: `83334fc`, `ed1ff72`.
  - scene-briefs.csv knowledge lists contain leading-space tokens (`' keele-land-fraud'`).
  - `timeline_day` values sit in parallel tracks (field vs town) that the validator reads as inversions (station-147 day 12 at seq 27 after day 14).
- **Wholesale redrafts** (2026-04-05/07 "Draft scene …"; 2026-04-15/17 "redraft N scenes from corrected briefs") swamp any small diffs after April. Nothing after `30aebf0` can be isolated as a fact fix.
- **Eval labels are noisy.** Most findings marked "continuity" in `working/evaluations/*/findings.*` are craft notes (over-explaining, clarity). The real continuity labels are in the archived pipeline reviews (`working/archive/reviews/pipeline-review-20260401-013705.md` C2; `pipeline-review-20260402-211658.md` §4, §6) and in the tracker.

### 5. Yield estimate

**Expect about 12–15 usable labelled pairs**, all from roughly 2026-03-05 to 2026-04-02 (the numbered-scene and early-slug era):
- **About 10 strong pairs** with both sentences recoverable and a clean fix: Cases A–I, with Case F counting as 3–4 instances.
- **About 9 more** that are sibling instances (each extra station-count line, the second county line), CSV timeline fixes (rows 18, 19), or squash-only labels (rows 11, 16).
- **3 live, unfixed registry errors** (Thomas "Tonkawa guide" alias, Emmett→Cora physical-state misattribution, the missing Keele confinement state). These suit a "detect CSV error" eval rather than a prose-contradiction eval.

Error types are skewed: mostly PHY quantities and objects (station counts, ledger, counties, horse) and TIM (day and week counts). There is one TRT/WLD ethnicity case and one KNO omission. There are no REL or VOI cases worth using. The 904-commit history is mostly scoring, hone and redraft churn, so the yield per commit is low.


---

## understory

Surveyed read-only (`git log`/`show`/`-S`/`-G`, grep). HEAD = `4ebc480`. 58 rows in `reference/scenes.csv`, 59 files in `scenes/`. Timeline in the CSV currently runs day 1 → 66.

**Main finding:** labeled fix commits for continuity are rare. Almost all prose change came from whole-scene redrafts ("redraft N scenes from corrected briefs", 15+ such commits). The redrafts rewrite the time phrases incidentally, so a factual fix can't be isolated in them. The best eval material is (a) a handful of review-labeled fixes and (b) about 8 **unfixed** contradictions at HEAD. Most of (b) are relative-time phrases ("three weeks ago") that disagree with `timeline_day` or with other prose. The b8e66fb expansion (43 → 66 days) and later redrafts made these worse.

### 1. Fix commits that corrected a detail/fact error

| hash | what | scene(s) | type | conf |
|---|---|---|---|---|
| `24406fb` (Revision: prose-cuts-merges, 2026-04-07) | Removed "Hunter brought up the rear, silent as always." The antagonist's name was used as a crew member. Flagged in `working/reviews/pipeline-review-20260406-230215.md` Minor Issue 1 ("This is either a continuity error … or a drafting artifact … genuine concern"). | burns | TRT (name) | high |
| `bbfc945` (Revision: structural-kavi-timeline, 2026-04-16) | `rami-door.timeline_day` 44 → 43. Fixes four "night" scenes on day 44 (rami-door, preparing, naji-helps, eve). Flagged in `pipeline-review-20260414-195732.md` concern 5. | rami-door | TIM (CSV) | high (labeled) |
| `5ac1c26` (Revision: timeline-fix, 2026-04-14) | **No-op.** It only set the pass to `in_progress`. `24b3777` then marked it `completed`, but `scenes.csv` still had rami-door at 44 (checked at `ab17593`). The real edit came 2 days later in `bbfc945`. This is a Storyforge bookkeeping bug (a structural pass marked done with no data change), not a book fix. | rami-door | — | high |
| `040bbf3` (Brief reconstruction, 2026-04-08) | Rebuilt 23 briefs that had wrong-story content (Callisto Station, blast doors, iron-wing drones, characters Marta/Kael/Archivist Leng) plus the `gathering` brief. That brief called Rami "thirteen, uninitiated, Marta's son"; in the prose he is Zara's 16-year-old brother. This is CSV-vs-prose drift, fixed by re-reading the prose (script `working/scripts/apply-brief-corrections.py`). | 24 briefs incl. gathering | TRT/REL (CSV) | high |
| `72dadd6`-style setup fix | none found in understory | | | |
| `66e4aad`-style name fix | none found in understory | | | |
| `5ba7bf7` (Clean up scenes-review, 2026-04-14) | Not a fix. It **introduced** the leading-whitespace header in `knowledge.csv` (`-id|name|…` → `+    id|name|…`). | — | data | high |
| `bbfc945` (same commit) | **Introduced** a new TIM error. Inserted `kavi-recipe` with `seq` 12 (duplicates `cost`), empty `pov`, and `timeline_day` 8, placed between cost (day 12) and vanishing (day 16). Still present at HEAD. | kavi-recipe | TIM (CSV) | high |

Sweep commits checked and found to contain no isolatable fact fixes: `47e140c`/`25d669f`/`a1643da`/`85644cb`/`4ebc480` (redrafts), `5ff25f2` (321 repetition edits), `a27993e`/`acfd628` (naturalness), `b8e66fb` (CSV-only, deliberate).

### 2. Strongest contradicting pairs

A–C are labeled fixes. D–J are **unfixed at HEAD**: real, objectively checkable contradictions, but with no human or evaluator label. Quotes come from HEAD unless marked otherwise.

**A. "Hunter" as a crew member (TRT, fixed, labeled)**
- Establishing (deeper, seq 16, at `24406fb^`): "The old places are how the Hunter finds you," I said.  Also cost (seq 12): "Naji had described the Hunter in vague terms, careful terms, the way you'd describe a storm to someone who'd never seen one."
- Contradicting (burns, seq 23, at `24406fb^`): "Suki came around the corner first, her flashlight beam cutting low across the floor. Mal behind her, then Oren, then Dex. Hunter brought up the rear, silent as always."
- Fix (`24406fb`): "Suki came around the corner first, her flashlight beam cutting low across the floor. Mal behind her, then Oren, then Dex."

**B. Four scenes on night 44 (TIM, fixed in CSV, labeled)**
- Data: at `bbfc945^`, `rami-door|46|…|44|night`, `preparing|47|…|44|night`, `naji-helps|48|…|44|night`, `eve|49|…|44|night`.
- Label: pipeline-review-20260414 concern 5: "Four scenes … all occupy 'night' on day 44 … Moving `rami-door.md` to day 43 (night) would resolve the compression."
- Fix (`bbfc945`): `rami-door|46|Rami at the Door|3|zara|understory|43|night|…`. No prose changed.

**C. Rami's identity in the gathering brief (TRT/REL, CSV vs prose, fixed)**
- Contradicting brief (`040bbf3^:reference/scene-briefs.csv`, gathering): "Rami — thirteen, uninitiated, Marta's son — stumbles through the chamber door calling for his mother".
- Establishing prose: two-lives: "Rami at sixteen was something else". The bible says "Zara's younger brother, 16" (see also F).
- Fix (`040bbf3`): "The real Rami arrives unprotected, forcing Zara to split attention between holding the defense and saving her brother."

**D. Hand wrapped "three weeks ago" vs that morning (TIM, prose↔prose, unfixed). Best unlabeled case.**
- Establishing (two-lives, seq 25, day 29 afternoon): "The blisters had gone tight and shiny overnight, the skin pulled taut across my palm where I'd pressed it against the tunnel residue. I'd wrapped it in gauze this morning and told Tarek I'd gr[abbed…]"
- Contradicting (rami-follows, seq 26, **same day 29**, night): "Three weeks ago you came home with your hand wrapped up and told Mom you burned it on the flattop."
- The burn itself is in burns (day 26): "blisters forming across the heel of my palm and the pads of my fingers". `physical-states.csv`: `blistered-hand-zara|…|burns|council`. "Three weeks ago" first appeared in redraft `47e140c`; it fails under both the old and new timelines.

**E. Oren's near-erasure: "three days ago" vs "two days ago" (TIM, prose↔prose, unfixed)**
- Event (strikes, seq 30, day 33): "Their hand went transparent in mine."
- tunnels-deep (seq 34, day 35): "Oren had almost gone transparent three days ago and I'd held their name in my skull like a hot coal until reality took them back."
- Contradicting (hemorrhage, seq 39, day 40): "The voice of someone who'd almost been erased two days ago and was now choosing to be the steady one." The two phrases are 5 days apart in story time but disagree on the anchor (≈day 32 vs ≈day 38). Introduced by redraft `85644cb`.

**F. Hemorrhage "three days ago" the next day (TIM, prose vs CSV, unfixed)**
- Establishing: hemorrhage is `timeline_day` 40, night (Zara's eye bleeds in that scene: "My left eye started to throb.").
- Contradicting (four-hundred, day 41 afternoon): "My left eye throbbed behind the socket, the dull remnant of the hemorrhage three days ago."
- Hemorrhage and four-hundred have been adjacent days (23/24 before the expansion, 40/41 after), so this was never consistent. Introduced in `85644cb`.

**G. Mal's sling on and off in the same scene (PHY, prose↔prose, unfixed)**
- gathering-assembly (seq 50) ¶1: "Mal stood by the east tunnel, arms crossed, weight on his back foot. His sling was off but he kept the arm close to his body".
- Same scene, later: "He planted himself at the kirin's left shoulder, close enough that the heat must have pulsed against his sling, and he didn't step back."
- gathering-hunt (seq 52, same morning): "His left arm hung in its sling. Useless."
- CSV: `broken-arm-mal|…|burns|preparing` (resolves at seq 47). eve (seq 49): "His sling was off". The CSV resolution doesn't match the prose either.

**H. "Seven days since" the vanishing, two days later (TIM, prose vs CSV, unfixed)**
- Establishing: vanishing (seq 13, day 16) is when Yuki's noodle shop is found gone: "'The noodle shop.' I pointed at the wall. 'Right here.'"
- Contradicting (three-days, seq 15, day 18): "Seven days since the noodle shop had gone empty." The scene title is "Three Days". An earlier version (`3015dbe`) read "Three days since the noodle shop"; redraft `33f75b8` changed it to "Seven".

**I. Rami's age in the bible (TRT, reference doc internal, unfixed)**
- `character-bible.md` line 34: "**Rami (brother, 14):** Protective, teasing, genuinely close."
- Line 149: "**Role:** Zara's younger brother, 16."  Prose: "sixteen-year-old" (after, gathering-hunt, two-lives). Both versions date to `7f2b58b`/`b2e78e3`.

**J. "Two weeks since the Gathering" at day 66 (TIM, prose vs CSV, unfixed, medium)**
- Gathering = day 45 (gathering-assembly … gathering-chosen); `b8e66fb` moved welcome from 43 to 66.
- welcome: "Two weeks since the Gathering. Fourteen days of a city that looked the same and wasn't." That's 21 days by the CSV. It was 17 days even before the expansion.

Lower-confidence relative-time drift (medium/low):
- kirin (d24) "the same voice that had asked me if I was okay on the curb three days ago" (curb scene unanchored)
- el-sees (d9) "a conversation with Naji three days ago"
- vanishing (d16) "You came here with me … Two weeks ago" (crew is d7)
- mother (d43) "I'd used it to press against my nose three weeks ago in the alley" (unanchored)
- kavi-recipe at day 8 inserted between day-12 and day-16 scenes. The eval-20260416 first reader: "Kavi's Fate … the timeline was slightly unclear."

### 3. Facts later prose depended on that were never recorded in the CSVs
- Date of the hand wrapping/gauze lie (two-lives day 29) is used by rami-follows and mother. Only the injury window is recorded (`blistered-hand-zara`).
- Exact day of Oren's near-erasure. `near-erasure-oren` records only acquisition at strikes, so the relative references (tunnels-deep, hemorrhage) have no anchor.
- Mal's sling status. `broken-arm-mal` resolves at preparing, but prose keeps the sling through gathering-hunt. No intermediate "sling off" state exists.
- Yuki (kitsune, noodle shop) name and vanish date. She is the subject of three-days, council ("I'd found one two days after she vanished"), betrayal, alone, and after, but has no characters.csv row.
- Rami's age (14 vs 16). `characters.csv` has no age column (`id|name|role|aliases|death_scene`).
- Elapsed time welcome-from-Gathering, and Naji's "sixty years" in Chicago vs deals since 1623. The latter was checked by the 2026-04-06 review and is consistent.

### 4. Data-quality notes
- `knowledge.csv` header is `    id|name|aliases|category|origin` (4 leading spaces). Introduced by `5ba7bf7` "Clean up scenes-review" (2026-04-14).
- `scenes/gathering.md` is an orphan with no CSV row. The gathering was split into 4 sub-scenes in `17fd69a`, but the old file stayed. It contains its own stale time references: "five days ago", "holding twenty-eight names".
- `kavi-recipe` row: `seq` 12 duplicates `cost`, `pov` is empty, `timeline_day` 8 is out of order, and `type` is `reaction` (not used elsewhere).
- Scene ids were renamed to slugs in `b7304bf` (2026-04-05). Several were merged or cut in `24406fb` (cartography, dex-back, mal-back, noodle, scorch deleted). Reviews before 04-07 cite those dead ids and old seq numbers (e.g. "scene 51, day 28"), so label lookups must map through history.
- Old project title "Unicorn Tail" appears in early evals and reviews.
- `b8e66fb` re-dated every scene (43 → 66 days). Any timeline label older than 2026-04-14 09:21 uses the old days.
- The `5ac1c26` "timeline-fix" pass was marked completed without changing the data (see §1).

### 5. Yield estimate
- **Labeled, isolatable fixes: 3** (A name, B CSV timeline, C brief drift).
- **Unlabeled but verified contradictions at HEAD: 6 strong** (D–I) and **about 5 medium**. These are good as "should-flag" test items (ground truth = CSV day math or same-book prose). They have no fix diff.
- Reasoning: 505 commits, but prose churn is dominated by whole-scene redrafts and pattern sweeps. Continuity was never a revision target except the day-44 compression, and the continuity tracker was never initialized (`recommendations-4.md`). Expect about 10 usable items total. The redrafts are a rich *source* of new TIM errors, especially relative-time phrases regenerated without the CSV day.


---

## slipform

Surveyed read-only. HEAD = `11c2c41`. 63 rows in `reference/scenes.csv`, 63 files in `scenes/` (the sets match). History runs 2026-04-14 → 04-17. All POV is Silas, first-person present (KD-006).

**Main finding:** two labeled continuity problems with isolatable fix commits. One is Pell's pronoun; the other is the Chapter 4 "Quiet Block" timeline, whose fix was only partial. There is also one labeled setup/payoff fix (Croy's presence in the facility) and a reference-doc name fix. The strongest finding is a **regression**. The Pell pronoun fix (`39424de`) was undone by the 61-scene redraft (`c3d463a`), because Pell's pronoun was never recorded in any CSV or the bible. Pell is he, she, and they at HEAD.

### 1. Fix commits that corrected a detail/fact error

| hash | what | scene(s) | type | conf |
|---|---|---|---|---|
| `39424de` (Revision: pell-pronoun-fix, 2026-04-14 22:44) | Pell she→he in what-they-took and they→he in recon. Labeled by `working/reviews/pipeline-review-20260414-222055.md` §3 "Continuity: Pell's gender pronoun is inconsistent" and plan pass 2 (`3e5093f`). The reviewer got the majority pronoun wrong (it said they/them was canonical and proposed changing door's "His lists" to "their"). The plan chose he/him. | what-they-took, recon | TRT (pronoun) | high |
| `c3d463a` (redraft 61 scenes, 2026-04-16) | **Regressed** the above. crew went from "He crouches forward" to "Pell crouches … Her fingernail …". temptation now uses she/her and deep uses their (scale, frequency, and two-kinds-of-wired still use he). Not fixed at HEAD. | crew, temptation, deep | TRT (pronoun) | high |
| `72dadd6` (Revision: croy-facility-setup, 2026-04-14) | Added setup so Croy's presence in grace isn't unearned: a "CRO" comms tag in into-the-spire and Croy's jacket in hard-part. Labeled by pipeline-review-20260414-222055 §6 and plan pass 4 (R006). Marked done in `c9e382c`. | into-the-spire, hard-part (for grace) | PRM | high (labeled) |
| `cdf4d23` (Revision: timeline-and-pov, 2026-04-16) | quiet-block `timeline_day` 4 → 25. Labeled by eval-20260416-085301 (synthesis #1, assessment "hard stop", E01). **Partial and wrong:** `seq` stayed at 100, a duplicate of `delivery`, and chapter-map still puts quiet-block in Ch 4. Reader order is unchanged, the prose wasn't touched, and day 25 is *before* the rescue (day 26), while the prose is post-rescue. The other half of the pass, the his-place third-person POV slip, wasn't fixed here. It disappeared in the `c3d463a` redraft (not isolatable). | quiet-block (his-place) | TIM (+VOI) | high |
| `66e4aad` (Pre-map cleanup, 2026-04-14) | Stale names in reference docs: "Mara's terms" → "Reva's terms" (story-architecture; Mara is a phantom name), and "HANA (sensei…)" → "REVA" in the bible relationship map (the deliberate rename `6574642` missed it). | — (reference docs) | TRT (names) | high |
| `6574642` | Hana → Reva rename to avoid name reuse with Understory. Deliberate, not an error. | — | — | — |
| `212f984` (PR #14 "scene-map-surgery") | **Introduced** quiet-block at `seq` 100, day 4, among day-5 scenes. This is the source of the Ch 4 timeline error. | quiet-block | TIM | high |

### 2. Strongest contradicting pairs

**A. Pell's pronoun: fixed, then regressed (TRT)**
- Establishing (quietfall, seq 230, at `39424de^`): "Pell's pen moves across his physical notes." Also door (seq 340): "His lists got us this far. His lists and his memory and the fact that he doesn't forget anything".
- Contradicting (what-they-took, seq 250, at `39424de^`): "\"Approximately forty thousand records,\" she said. … She couldn't look at me when she said the number." recon (seq 330): "That's the most human thing Pell has said in the two days I've known them." and "Small and dark against their pale fingers."
- Fix (`39424de`): "…\" he said. … He couldn't look at me when he said the number." / "…the two days I've known him." / "Small and dark against his pale fingers."
- Regression (HEAD, crew seq 280, from `c3d463a`): "Pell crouches before anyone else moves. Her fingernail catches on every junction point". Before that commit the line was "He crouches forward, tablet forgotten, and traces the perimeter with a fingernail." temptation (HEAD): "\"The polling signature matches,\" Pell says. She's got her tablet braced against her forearm". deep (HEAD): "Pell brings up the rear, folding their frame into the tight space". frequency and two-kinds-of-wired (HEAD) still use he.

**B. Quiet Block: post-rescue scene placed in Act 1 (TIM, fix partial)**
- Establishing: the rescue happens on day 26 (mother/real/grace at night, way-out at dawn). quiet-block's own text is post-rescue: "\"Lira says stable. Dehydrated. Confusion comes and goes.\" … \"She knew Jem. Knew me. Asked about the mats.\"" and "her hand comes down on my shoulder, the left one, where the muscle seized during the exit."
- Contradicting data (at `cdf4d23^`): `quiet-block|100|The Quiet Block|1|silas|mid-tier-streets|4|evening`, with seq 100 shared by `delivery|100|…|5|night`. chapter-map: `4|The Offer|numbered-titled|quiet-block;offer`.
- Label: eval-20260416-085301 synthesis: "Fix the Chapter 4 'Quiet Block' timeline displacement. Move the safehouse scene to its correct chronological position (post-Chapter 24) or clearly signal it as a flash-forward."
- Fix (`cdf4d23`): `quiet-block|100|…|25|evening`. Only the day changed. seq, part 1, and the chapter didn't, and day 25 still predates the rescue. This is a good negative example (a "fixed" item that isn't).

**C. Croy appears in the facility without setup (PRM, fixed, labeled)**
- Payoff (grace, seq 530): Silas saves Croy in Quietfall. At `72dadd6^`, grace says "Three months ago Croy handed me a delivery package and told me it was data. Firmware."
- Label: review §6: "Croy's presence in the facility is never fully established … the prose currently assumes knowledge the scene itself doesn't provide."
- Fix (`72dadd6`, into-the-spire): "The tag carries a name prefix. Three letters. CRO. / I file it. Keep moving." and (hard-part) "A jacket, draped over a conduit housing. Dark material, expensive cut. … I've seen Croy wear one like it."
- Side note: "Three months ago" in grace conflicts with the CSV (the Croy delivery is day 5 and grace is day 26, about 3 weeks). It was removed by redraft, so it isn't isolatable.

**D. "Eight days ago" Tier 4 run (TIM, prose vs CSV, unfixed)**
- Establishing (easy-money, seq 60, day 3): "Croy's drop point is a service office on Tier 4, unmarked door between a water-reclamation outlet and a subscription kiosk that hasn't worked in months."
- Contradicting (what-he-built, seq 130, day 5): "Same casing I carried for Croy eight days ago." / "Eight days ago was the Tier 4 run." (introduced `11c2c41`, the last commit; the previous version said "Three days ago"). Medium confidence. The phrase could refer to an earlier Tier 4 job, but easy-money is the only Tier 4 Croy run in the book.

**E. "Three weeks ago" frequency analysis (TIM, prose vs CSV, unfixed, medium)**
- Establishing: frequency is seq 220, day 15 (Silas builds the frequency plot with Pell).
- Contradicting (temptation, seq 400, day 24): "scrolling through the frequency analysis I built three weeks ago". That's 9 days by the CSV. Introduced in `c3d463a`.

**F. Mara/Hana stale names in reference docs (TRT, fixed `66e4aad`)**
- Before (story-architecture at `66e4aad^`): "Conditional trust. Mara's terms: earn the floor you stand on." The fix reads "Reva's terms". The bible map line `HANA (sensei, model of integrity)` became `REVA`. Doc-level only, so it's lower value for prose evals.

### 3. Facts later prose depended on that were never recorded in the CSVs
- **Pell's pronoun.** `characters.csv` is `id|name|aliases|role|death_scene` (`pell|Pell||secondary|`). The bible's Pell section avoids pronouns ("Pell's anxiety…"). That is why the redraft regressed the fix. This is the clearest "unrecorded fact caused a regression" case in either repo.
- Talia's rescue state (stable, dehydrated, safehouse, Silas's seized left shoulder) is used by quiet-block but appears in no physical-states row.
- Croy's presence in Quietfall (knowledge/setup) was fixed only in prose. No knowledge row was added.
- Dates of Croy's past runs (Tier 4/7/9, "eleven weeks ago") and Talia's disappearance ("three years ago" in mother, real, her-hands, what-remains). The prose agrees on three years, but nothing records it.
- Frequency-analysis build date (see E).

### 4. Data-quality notes
- **Id rename `44ab76f`** (2026-04-14 22:12) mapped arc-NN/map-NN to slugs. Full map (old→new, seq): arc-01→bare 10, map-01→corridors 20, arc-02→weight 30, map-20→taking 40, arc-03→blind-spot 50, map-02→easy-money 60, map-35→short 65, arc-04→offer 70, map-21→note 80, map-22→climb 90, arc-05→delivery 100, arc-06→blackout 110, map-23→naya 120, arc-07→what-he-built 130, arc-08→earning-the-floor 140, map-24→floor 150, map-03→first-shift 160, map-25→others 170, arc-09→boring-part 180, map-04→two-kinds-of-wired 190, map-05→quiet-one 200, map-36→steady-hands 205, arc-10→unfiltered 210, map-06→frequency 220, map-37→list 225, arc-11→quietfall 230, map-07→scale 240, arc-12→what-they-took 250, map-08→her-hands 260, map-26→his-place 270, arc-13→crew 280, arc-14→leverage 290, map-09→the-map 300, arc-15→dumb-thing 310, map-10→clean 320, map-11→recon 330, map-27→door 340, arc-16→node 350, map-12→what-we-found 360, arc-17→pattern 370, map-28→wall 380, map-13→space 390, arc-18→temptation 400, arc-19→stitches 410, map-14→clock 420, map-29→inventory 430, arc-20→window 440, map-15→night-before 450, arc-21→into-the-spire 460, map-16→deep 470, arc-22→hard-part 480, map-30→brave-thing 490, map-31→air 500, map-17→mother 510, map-32→real 520, arc-23→grace 530, map-18→way-out 540, arc-24→what-remains 550, map-33→weight-of-it 560, map-19→reckoning 570, arc-25→mat 580. Added later: quiet-block, croy-bridge (both in `212f984`).
- **Duplicate seqs at HEAD:**
  - 100 (delivery day 5 / quiet-block day 25)
  - 310 (croy-bridge day 20 night / dumb-thing day 21)
  - 370 (pattern day 23 *night* / what-we-found day 23 *morning*; what-we-found moved from 360, so the seq order now contradicts time of day)
- Seqs are spaced by 10, which leaves room for inserts.
- `knowledge.csv` header is clean (`id|name|aliases|category|origin`). Column order differs from understory's `characters.csv` (`aliases|role` vs `role|aliases`).
- her-hands shipped with an empty `status` (review §2). It was drafted later in `3a3aa32`.
- The pipeline reviewer was itself wrong about the canonical pronoun. Any label taken from that review needs author-decision context (the plan chose he/him).

### 5. Yield estimate
- **Labeled, isolatable: 4** (A pronoun fix, B quiet-block partial fix, C Croy setup, F doc names), plus **1 labeled regression** (A at `c3d463a`), which is very useful as a test case.
- **Unlabeled verified at HEAD: 2–3** (D, E, the current Pell pronoun mix, the seq-370 ordering).
- Reasoning: the 4-day history is mostly brief/intent hone passes and whole-book redrafts (61-, 27-, 27-scene). Continuity was only an explicit target in cycle 0 (pronoun, Croy) and in the timeline-and-pov pass. Expect about 7 usable items. The pronoun regression and the half-fixed quiet-block are the standout cases because they show Storyforge "fixing" something and the error surviving or coming back.


---

## ashes

Graphic novel at the architecture stage: 43 planned scenes in scenes.csv, one scene drafted (`s01-studio-finalization`, 1,285 words), five rendered pages, 19 coarse knowledge facts, and a header-only physical-states.csv. Its 89 commits are bible, spine and act-shape refinements ("align with Version B", "tier 1 + tier 2 quality fixes"). These are design changes, not continuity errors in prose. Yield: about 0 prose cases. Revisit once pages are drafted.

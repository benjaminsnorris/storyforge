# Pronouns in the books: the judgement calls (2026-11-03)

Every character in the eight books got `he` or `she` in `reference/characters.csv`, merged in each book's repo (ashes #11, governor #83, lantern-folk #16, meridian-line #87, shared-dark #91, slipform #25, thornwall #72, understory #38). Most were clear from the prose and the character bible. These were judgement calls, with what decided each. Changing one is a one-cell edit in that book's `characters.csv`.

## The book uses something other than he or she

The instruction was he or she for every character. Each of these is written another way in the book. With a single pronoun, the drafting prompt will steer the writer toward that pronoun.

| Book | Character | Set to | The book's own usage |
|---|---|---|---|
| understory | Oren | he (Ben's choice) | The bible says "nonbinary (they/them)", and the prose uses they/their about 60 times. A rewrite will change those lines; the checker may flag the existing prose until then. |
| understory | The Hunter | he | A force, written "it" (13 of the pronouns after "the Hunter"). |
| lantern-folk | The Murkwolves | he | Creatures, written "it". |
| lantern-folk | The Parents | he | The mother and the father together: one pronoun is wrong for one of them. Splitting them into `mom` and `dad` rows would fix it, but scenes name `parents`. |
| lantern-folk | The Lantern Folk | he | A people: "a Folk man", "a Folk boy", women too. |
| governor | crews and groups: haddon-crew, garren-crew, gallery-authority-medics, rescue-crew, unnamed-pipe-crew, unnamed-residents, two-foundry-engineers, two-foundry-officials, two-unnamed-crew-members, two-maintenance-workers, three-commission-members, three-unnamed-voss-figures, the-three-companions, the-founders, sarel-davans-children | he | Groups. The named crew members are men, which decided crews; the others have no single gender. |
| ashes | The Erased Archivist | he | The bible writes "they" on purpose: "different documents name them differently". Aliases Severin Ott, Iorel Tace, Casris Vel. |
| ashes | The Unheld Child | she | A composite figure, "they" in the bible, no gendered reference anywhere. |

## No gendered reference in the book: decided by the name

| Book | Character | Set to | Note |
|---|---|---|---|
| shared-dark | Devonte | he | Named only in characters.csv. |
| shared-dark | Delgado | he | Never gendered. The name also collides with Sofia Delgado and a staff sergeant named Delgado. |
| shared-dark | Madison | she | One of three kids in Keisha's posts, with Shannon and Brianna (both she). |
| governor | Alden Pryce, Davin Creel, Jessik, Rennick, Ostin, Halder | he | Never gendered in the prose. |
| governor | Liaret Merrin | she | Not in the prose at all. |
| governor | the-building-warden, the-unnamed-recruiter, the-1794-mapper, unnamed-supervisor, unnamed-younger-crew-member, crew-chief-unnamed, unnamed-younger-ga-figure | he | No gendered reference. |
| governor | fenwick | he | Probably a place (Fenwick Row), not a person: worth removing from characters.csv. |
| governor | Devra Erdel | she | Voss calls her name across the cordon; never gendered. |
| meridian-line | Margaret Pollard | she | Her row's name is Margaret. "Pollard left on a Tuesday … He'd arranged" in town-empties may be her husband. |

## The prose disagrees with itself

These are errors in the prose, worth fixing before or during the rewrite.

| Book | Character | Set to | The conflict |
|---|---|---|---|
| thornwall | Lieutenant Marren | she | `courtyard-after`: "the regional office would have his report"; she everywhere else. |
| shared-dark | Judge Alderman | he | `diner-on-grand`: "Alderman wants it cleaner. He's not wrong", but an earlier line may read as "She says Thursday". |
| governor | Tam Erdel | he | "Tam Erdel. Seven … He was in the corridor." (#480's E8 notes mention a dead girl in governor; that is another child.) |
| governor | Oskar Brenn | she | "an elderly woman named Oskar Brenn". The name reads male, the text says woman. |
| lantern-folk | Tallow | he | The prose has "his woodpile" and "his arms folded"; a redraft in E8 (lantern-folk-020) made Tallow "her", which the gate passed. |

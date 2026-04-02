# Brief Fidelity Evaluation

You are evaluating whether a scene's prose delivers what its brief promised. This is not a quality judgment — a scene can be beautifully written and still fail to deliver its brief. And a scene that delivers every brief element can still need prose polish.

## Scene Brief

{BRIEF_DATA}

## Scene Prose

{SCENE_PROSE}

## Instructions

For each brief element, score how faithfully the prose delivers it on a 1-5 scale:

- **1 (Missing):** The brief element is absent from the prose
- **2 (Gestured):** The element is hinted at but not substantively present
- **3 (Present):** The element is delivered but could be stronger or more specific
- **4 (Delivered):** The element is clearly and effectively delivered
- **5 (Transcended):** The element is delivered and the prose found something better than what the brief specified

## Output Format

Output ONLY pipe-delimited CSV rows. First the scores, then the gaps.

SCORES
id|goal|conflict|outcome|crisis|decision|key_actions|key_dialogue|emotions|knowledge
{SCENE_ID}|score|score|score|score|score|score|score|score|score

RATIONALE
id|element|score|evidence
{SCENE_ID}|goal|N|one sentence explaining the score
{SCENE_ID}|conflict|N|one sentence explaining the score
{SCENE_ID}|outcome|N|one sentence explaining the score
{SCENE_ID}|crisis|N|one sentence explaining the score
{SCENE_ID}|decision|N|one sentence explaining the score
{SCENE_ID}|key_actions|N|one sentence explaining the score
{SCENE_ID}|key_dialogue|N|one sentence explaining the score
{SCENE_ID}|emotions|N|one sentence explaining the score
{SCENE_ID}|knowledge|N|one sentence explaining the score

## Scoring Guidance

- **goal:** Does the POV character pursue the stated goal? Is it visible in their actions and thoughts?
- **conflict:** Is the stated conflict present and felt? Does it create real opposition?
- **outcome:** Does the scene end with the stated outcome (yes/no/yes-but/no-and)?
- **crisis:** Does the character face the stated dilemma? Is it a genuine choice?
- **decision:** Does the character make the stated decision? Is it active, not passive?
- **key_actions:** Are the specified actions present in the prose? (Score based on proportion present)
- **key_dialogue:** Do the specified lines or close paraphrases appear? (Paraphrases that preserve meaning count as delivered)
- **emotions:** Does the emotional sequence match? Do the beats land in the right order?
- **knowledge:** Does the character know what knowledge_out says by scene end? Does knowledge_in match their awareness at the start?

A scene that follows the brief exactly scores 4s. A scene that departs from the brief but finds something better scores 5s. A scene that ignores the brief scores 1s regardless of prose quality.

You are scoring a novel against novel-level Character Craft principles and Genre/Trope principles. You will produce two separate output blocks: one for character scores (one row per major character) and one for genre scores (a single row).

## Rubric

{{CHARACTER_CRAFT_NOVEL_RUBRIC}}

{{GENRE_RUBRIC}}

## Manuscript Summary

{{MANUSCRIPT_SUMMARY}}

## Character Bible

{{CHARACTER_BIBLE}}

## Story Architecture

{{STORY_ARCHITECTURE}}

## Craft Weights

{{WEIGHTED_PRINCIPLES}}

## Instructions

- Score each principle as an integer from 1 to 10 using the rubric's score bands.
- For character scores: produce one row per major character. Assess each character's want/need tension, wound/lie depth, flaw-strength unity, and voice distinctiveness independently.
- For genre scores: produce a single row. Assess the novel's overall engagement with its genre traditions.
- Anchor every score in observable textual evidence from the summary, character bible, and architecture -- not subjective impression.
- Weighted principles marked as high-priority deserve extra scrutiny.
- Output ONLY the two CSV blocks below. No prose, no explanation, no commentary before, between, or after the blocks.

## Output Format

CHARACTER_SCORES:
character|want_need|wound_lie|flaws_as_strengths|voice_as_character
{{CHARACTER_NAME}}|<score>|<score>|<score>|<score>
{{CHARACTER_NAME}}|<score>|<score>|<score>|<score>

CHARACTER_RATIONALE:
character|want_need|wound_lie|flaws_as_strengths|voice_as_character
{{CHARACTER_NAME}}|<one sentence>|<one sentence>|<one sentence>|<one sentence>
{{CHARACTER_NAME}}|<one sentence>|<one sentence>|<one sentence>|<one sentence>

GENRE_SCORES:
trope_awareness|archetype_vs_cliche|genre_contract|subversion_awareness
<score>|<score>|<score>|<score>

GENRE_RATIONALE:
trope_awareness|archetype_vs_cliche|genre_contract|subversion_awareness
<one sentence>|<one sentence>|<one sentence>|<one sentence>

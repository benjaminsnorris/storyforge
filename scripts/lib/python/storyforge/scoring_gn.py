"""Deterministic craft scorers for graphic-novel mode.

Each scorer takes a parsed script (via storyforge.script_format.parse_script)
and a brief row, then returns a structured score dict with findings.

Scorers expose `score_scene(parsed_script, brief_row, scene_id) -> dict` and
the module exposes a top-level `score_project(project_dir) -> dict` for the
dispatcher contract (returns {'skipped': True, 'reason': '...'} on errors,
otherwise a structured score dict).
"""

import statistics
from storyforge.script_format import (
    parse_script, check_brief_fidelity, check_layout_anti_patterns,
)
from storyforge.common import get_medium

PRINCIPLES = (
    'brief_fidelity', 'panel_density', 'dialogue_compression',
    'layout_rhythm', 'caption_economy', 'panel_composition_depth',
)


def score_brief_fidelity(parsed, brief_row, script_text):
    """1.0 - (distinct_failing_kinds / 4). 4 kinds: dialogue, visuals, panels, page-turns.

    Multiple failures of the same kind (e.g. 5 missing dialogue lines) count
    as a single distinct failure kind so the score degrades by category, not
    by raw count.
    """
    failures = check_brief_fidelity(brief_row, script_text)
    total_kinds = 4  # dialogue_missing, visual_keyword_missing, panel_count_mismatch, page_turn_missing
    distinct_kinds = len({f['kind'] for f in failures}) if failures else 0
    score = max(0.0, 1.0 - distinct_kinds / total_kinds)
    findings = [
        {'kind': f['kind'], 'detail': f['detail'], 'severity': f.get('severity', 'medium')}
        for f in failures
    ]
    return {'principle': 'brief_fidelity', 'score': score, 'findings': findings}


def score_panel_density(parsed, brief_row=None, script_text=None):
    """Sweet spot: 4-7 panels per page. Score = 1.0 - (|avg - 5.5| / 5.5)."""
    pages = parsed['pages']
    if not pages:
        return {'principle': 'panel_density', 'score': 1.0, 'findings': []}
    densities = [len(p['panels']) for p in pages]
    avg = sum(densities) / len(densities)
    score = max(0.0, 1.0 - abs(avg - 5.5) / 5.5)
    findings = []
    for p in pages:
        n = len(p['panels'])
        if n > 9:
            findings.append({
                'kind': 'panel_density_high',
                'detail': f'Page {p["number"]}: {n} panels (cramped)',
                'severity': 'medium',
            })
        elif n == 0:
            findings.append({
                'kind': 'panel_density_zero',
                'detail': f'Page {p["number"]}: no panels parsed',
                'severity': 'high',
            })
    return {'principle': 'panel_density', 'score': score, 'findings': findings}


def score_dialogue_compression(parsed, brief_row=None, script_text=None):
    """Word balloons <= 25 words. Score = fraction under threshold."""
    MAX_WORDS = 25
    all_balloons = []
    for page in parsed['pages']:
        for panel in page['panels']:
            for d in panel['dialogue']:
                # Only count actual dialogue and captions — skip SFX
                if d['prefix'] in ('SFX',):
                    continue
                word_count = len(d['text'].split())
                all_balloons.append((page['number'], panel['number'],
                                     d['prefix'], word_count))
    if not all_balloons:
        return {'principle': 'dialogue_compression', 'score': 1.0, 'findings': []}
    under = sum(1 for _, _, _, w in all_balloons if w <= MAX_WORDS)
    score = under / len(all_balloons)
    findings = [
        {
            'kind': 'balloon_too_long',
            'detail': f'Page {pg} panel {pn} {pre}: {w} words (max {MAX_WORDS})',
            'severity': 'medium' if w <= 40 else 'high',
        }
        for pg, pn, pre, w in all_balloons if w > MAX_WORDS
    ]
    return {'principle': 'dialogue_compression', 'score': score, 'findings': findings}


# Per-severity score deductions for layout anti-patterns surfaced by
# check_layout_anti_patterns. Capped at the score floor (0.0) by the
# enclosing max(). Values picked so that one high-severity anti-pattern
# (page_turn_on_page_one) costs ~30% of the layout-rhythm score, in
# line with the deterministic principles' overall calibration.
_ANTI_PATTERN_DEDUCTIONS = {'high': 0.3, 'medium': 0.15, 'low': 0.05}


def score_layout_rhythm(parsed, brief_row=None, script_text=None):
    """Stdev of panels-per-page + deterministic anti-pattern findings.

    The score combines two layers:
    1. Triangle scoring on panel-count stdev — too uniform (<=0.3,
       mechanical) or too chaotic (>=3.0) both lose points; sweet
       spot stdev ~1.0-2.0.
    2. Anti-pattern penalties from check_layout_anti_patterns (the
       deterministic detectors documented in
       references/gn-layout-vocabulary.md): page_turn_on_page_one
       (high, -0.3), panel_density_excessive (medium, -0.15),
       tier_panel_count_unconventional (low, -0.05), and
       script_unparseable (high, -0.3).

    Both layers' findings surface in the result so the revision prompt
    receives them; the score reflects the combined penalty floored at 0.
    """
    pages = parsed['pages']
    findings = []

    # Anti-pattern findings always run; they don't depend on having
    # multiple pages (a 1-page script with the page-turn marker is
    # still wrong) and they're cheap.
    if script_text is not None:
        findings.extend(
            check_layout_anti_patterns(script_text, brief_row)
        )

    if len(pages) < 2:
        # Stdev needs ≥2 pages; with fewer, the rhythm score floor is
        # 1.0 but anti-pattern penalties still apply.
        score = 1.0
        for f in findings:
            score -= _ANTI_PATTERN_DEDUCTIONS.get(f.get('severity', 'medium'), 0.15)
        return {
            'principle': 'layout_rhythm',
            'score': max(0.0, score),
            'findings': findings,
        }

    densities = [len(p['panels']) for p in pages]
    stdev = statistics.stdev(densities)
    # Triangle scoring: peak at stdev=1.5, falls off either side
    if stdev <= 1.5:
        score = max(0.0, stdev / 1.5)
    else:
        score = max(0.0, 1.0 - (stdev - 1.5) / 2.0)
    if stdev <= 0.3:
        findings.append({
            'kind': 'layout_too_uniform',
            'detail': f'Panel-count stdev {stdev:.2f}: pages feel mechanically identical',
            'severity': 'medium',
        })
    if stdev >= 3.0:
        findings.append({
            'kind': 'layout_too_chaotic',
            'detail': f'Panel-count stdev {stdev:.2f}: wild variation may disorient',
            'severity': 'low',
        })

    # Apply anti-pattern penalties to the stdev-based score, floored at 0.
    for f in findings:
        # Only deduct for anti-pattern kinds we own; layout_too_uniform/
        # layout_too_chaotic already factor into the stdev triangle.
        if f.get('kind') in {
            'page_turn_on_page_one',
            'panel_density_excessive',
            'tier_panel_count_unconventional',
            'script_unparseable',
        }:
            score -= _ANTI_PATTERN_DEDUCTIONS.get(
                f.get('severity', 'medium'), 0.15,
            )

    return {
        'principle': 'layout_rhythm',
        'score': max(0.0, score),
        'findings': findings,
    }


CAPTION_STRATEGY_TARGETS = {
    'minimal': 1,
    'journal-voiceover': 3,
    'journal voiceover': 3,
    'omniscient': 4,
    'omniscient narration': 4,
    'none': 0,
}


def score_caption_economy(parsed, brief_row, script_text=None):
    """Captions per page. Strategy-aware target."""
    strategy = (brief_row.get('caption_strategy') or 'minimal').strip().lower()
    target = CAPTION_STRATEGY_TARGETS.get(strategy, 2)
    pages = parsed['pages']
    if not pages:
        return {'principle': 'caption_economy', 'score': 1.0, 'findings': []}
    findings = []
    within = 0
    for page in pages:
        captions = [
            d for panel in page['panels'] for d in panel['dialogue']
            if d['prefix'] == 'CAPTION'
        ]
        cap_count = len(captions)
        # Strategy=none: any caption is a failure (takes priority over generic excess check)
        if strategy == 'none' and cap_count > 0:
            findings.append({
                'kind': 'caption_when_none',
                'detail': f'Page {page["number"]}: {cap_count} captions; strategy is "none"',
                'severity': 'high',
            })
            within = max(within - 1, 0)
        else:
            # Allow exceeding target by 1; flag at +2
            if cap_count <= target + 1:
                within += 1
            else:
                findings.append({
                    'kind': 'caption_excess',
                    'detail': f'Page {page["number"]}: {cap_count} captions (strategy "{strategy}" suggests <= {target})',
                    'severity': 'low' if cap_count <= target + 2 else 'medium',
                })
    score = within / len(pages)
    return {'principle': 'caption_economy', 'score': score, 'findings': findings}


def score_panel_composition_depth(parsed, brief_row=None, script_text=None):
    """Composition prose word count. Sweet spot: 15-50 words per panel."""
    MIN_WORDS = 15
    MAX_WORDS = 50
    panels = [(page['number'], panel)
              for page in parsed['pages'] for panel in page['panels']]
    if not panels:
        return {'principle': 'panel_composition_depth', 'score': 1.0, 'findings': []}
    findings = []
    within = 0
    for page_num, panel in panels:
        w = len(panel['composition'].split())
        if MIN_WORDS <= w <= MAX_WORDS:
            within += 1
        elif w < MIN_WORDS:
            findings.append({
                'kind': 'composition_too_sparse',
                'detail': f'Page {page_num} panel {panel["number"]}: {w} words (artist needs more visual detail)',
                'severity': 'medium',
            })
        else:  # w > MAX_WORDS
            findings.append({
                'kind': 'composition_too_dense',
                'detail': f'Page {page_num} panel {panel["number"]}: {w} words (consider tightening)',
                'severity': 'low',
            })
    score = within / len(panels)
    return {'principle': 'panel_composition_depth', 'score': score, 'findings': findings}


SCORERS = {
    'brief_fidelity': score_brief_fidelity,
    'panel_density': score_panel_density,
    'dialogue_compression': score_dialogue_compression,
    'layout_rhythm': score_layout_rhythm,
    'caption_economy': score_caption_economy,
    'panel_composition_depth': score_panel_composition_depth,
}


def score_scene(scene_id, parsed_script, brief_row, script_text):
    """Run all scorers on one scene. Returns dict of principle -> score+findings."""
    return {
        principle: fn(parsed_script, brief_row, script_text)
        for principle, fn in SCORERS.items()
    }


def score_project(project_dir):
    """Top-level entry -- matches the contract used by novel-mode scorers."""
    if get_medium(project_dir) != 'graphic-novel':
        return {'skipped': True, 'reason': 'not a graphic-novel project'}
    # Actual scoring orchestration lives in cmd_score_gn -- this is just the contract.
    return {'principles': list(PRINCIPLES)}

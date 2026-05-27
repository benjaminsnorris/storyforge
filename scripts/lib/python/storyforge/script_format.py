"""Panel-script format parser and brief-fidelity checker.

Parses scene markdown files produced by cmd_write_gn into structured data
and verifies that the drafted script matches the brief's contract:
dialogue lines, visual keywords, panel breakdown, page-turn beats.

Script format reference: docs/superpowers/specs/2026-05-20-graphic-novel-mode-design.md
Layout anti-patterns: references/gn-layout-vocabulary.md
"""

import re
from typing import Final, Literal, TypedDict

# Severity Literal reused from scoring_story_power (the canonical
# severity scale across the codebase). Imported lazily inside the
# TypedDict context to avoid a circular import at module load.
from storyforge.scoring_story_power import Severity

# --- Regex patterns ---

PAGE_HEADER = re.compile(
    r'^## Page (\d+)\s+—\s+([A-Z0-9][A-Z0-9 \-]+?)'
    r'(?:\s+(⟵ PAGE-TURN REVEAL))?\s*$',
    re.MULTILINE,
)
PANEL_HEADER = re.compile(
    r'^\*\*Panel (\d+)\*\*(?:\s+\(([^)]+)\))?\s*$',
    re.MULTILINE,
)
DIALOGUE_LINE = re.compile(
    r'^- ([A-Z][A-Z\-]+(?:\s+[A-Z][A-Z\-]+)*)\s*:\s*(.*)$',
)

KNOWN_PREFIXES = {'CAPTION', 'SFX', 'WHISPER', 'THOUGHT', 'OFF-PANEL'}


def _split_pages(text):
    """Yield (header_match, body_text) tuples for each page."""
    matches = list(PAGE_HEADER.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        yield m, text[start:end]


def _split_panels(page_body):
    """Yield (header_match, body_text) tuples for each panel within a page."""
    matches = list(PANEL_HEADER.finditer(page_body))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(page_body)
        yield m, page_body[start:end]


def _parse_panel(panel_body):
    """Return {'composition': str, 'dialogue': [{'prefix', 'speaker', 'text'}]}.

    Composition is the prose narration of the panel (everything between
    the panel header and the first dialogue line). Dialogue captures every
    line matching the prefix-name pattern.
    """
    lines = panel_body.split('\n')
    composition_lines = []
    dialogue = []
    in_dialogue = False
    for raw in lines:
        line = raw.rstrip()
        m = DIALOGUE_LINE.match(line)
        if m:
            in_dialogue = True
            prefix = m.group(1).strip()
            text = m.group(2).strip()
            # Strip surrounding emphasis like *...* on caption lines
            if text.startswith('*') and text.endswith('*'):
                text = text[1:-1].strip()
            speaker = None if prefix in KNOWN_PREFIXES else prefix
            dialogue.append({'prefix': prefix, 'speaker': speaker, 'text': text})
        elif not in_dialogue and line:
            composition_lines.append(line)
        # blank lines between sections are ignored
    composition = ' '.join(composition_lines).strip()
    return {'composition': composition, 'dialogue': dialogue}


def parse_script(text):
    """Parse a panel-script markdown into structured data.

    Returns:
        {
          'pages': [
            {'number': int, 'layout': str, 'is_page_turn': bool,
             'panels': [{'number': int, 'size_hint': str|None,
                         'composition': str, 'dialogue': [...]}]},
            ...
          ],
          'page_count': int,
          'total_panels': int,
        }
    """
    pages = []
    total_panels = 0
    for page_match, page_body in _split_pages(text):
        page_num = int(page_match.group(1))
        layout = page_match.group(2).strip()
        is_page_turn = bool(page_match.group(3))
        panels = []
        for panel_match, panel_body in _split_panels(page_body):
            panel_num = int(panel_match.group(1))
            size_hint = panel_match.group(2)
            parsed = _parse_panel(panel_body)
            panels.append({
                'number': panel_num,
                'size_hint': size_hint,
                **parsed,
            })
            total_panels += 1
        pages.append({
            'number': page_num,
            'layout': layout,
            'is_page_turn': is_page_turn,
            'panels': panels,
        })
    return {
        'pages': pages,
        'page_count': len(pages),
        'total_panels': total_panels,
    }


def count_pages(text):
    return len(PAGE_HEADER.findall(text))


def count_panels(text):
    return len(PANEL_HEADER.findall(text))


def detect_page_turn_pages(text):
    return [int(m.group(1)) for m in PAGE_HEADER.finditer(text) if m.group(3)]


# --- Brief fidelity ---

PANEL_TOKEN = re.compile(r'^\s*(splash|double-spread|tier|irregular|(\d+)-grid)\s*$', re.IGNORECASE)


def _panels_per_token(token):
    """Return expected panel count for a brief panel-breakdown token, or None
    when the token is 'irregular' OR 'tier' (no exact-count check).

    'tier' is conventionally 2-4 panels (see references/gn-layout-vocabulary.md);
    a single expected count would mis-flag canonical 2- or 4-panel tiers.
    The `tier_panel_count_unconventional` detector in check_layout_anti_patterns
    owns the tier-range check; this function returns None for 'tier' so
    check_brief_fidelity's `panel_count_mismatch` doesn't double-fire on the
    same offense.
    """
    token = token.strip().lower()
    m = PANEL_TOKEN.match(token)
    if not m:
        return None
    if m.group(2):  # N-grid
        n = int(m.group(2))
        if n <= 0:
            return None
        return n
    label = m.group(1).lower()
    if label == 'splash':
        return 1
    if label == 'double-spread':
        return 1
    if label == 'tier':
        # See docstring — tier's range check lives in check_layout_anti_patterns
        # to avoid double-firing with check_brief_fidelity.
        return None
    return None  # irregular


def _parse_panel_breakdown(breakdown):
    """Parse 'p1:splash; p2:6-grid' into {1: 'splash', 2: '6-grid'}."""
    result = {}
    if not breakdown:
        return result
    for chunk in breakdown.split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ':' not in chunk:
            continue
        page_part, tokens_part = chunk.split(':', 1)
        page_part = page_part.strip().lower()
        if not page_part.startswith('p'):
            continue
        try:
            page_num = int(page_part[1:])
        except ValueError:
            continue
        # Take the first token if multiple
        first_token = tokens_part.split('+')[0].strip()
        result[page_num] = first_token
    return result


def check_brief_fidelity(brief_row, script_text):
    """Return list of failure dicts, empty when the script honors the brief.

    Failure kind values: 'dialogue_missing', 'visual_keyword_missing',
    'panel_count_mismatch', 'page_turn_missing'.

    Checks performed:
      - Every non-empty segment of brief['key_dialogue'] appears as a
        substring somewhere in the script (case-insensitive).
      - Every entry in brief['visual_keywords'] appears in the composed
        panel prose (case-insensitive).
      - Each page whose panel breakdown is specified in brief['panel_breakdown']
        has the expected number of panels.
      - When brief['page_turn_beats'] is non-empty, at least ONE page in the
        script must carry the page-turn marker. This is an existence-only
        check; we don't try to parse beat descriptions like "p2 reveal" back
        to specific page numbers. Position-specific verification is a future
        improvement.
    """
    failures = []
    parsed = parse_script(script_text)
    pages = parsed['pages']
    script_lower = script_text.lower()

    # 1. Dialogue contract: each non-empty segment of key_dialogue must
    # appear somewhere in the script. We use substring matching on the
    # full text since punctuation/formatting normalization is hard.
    key_dialogue = (brief_row.get('key_dialogue') or '').strip()
    if key_dialogue:
        # Split on semicolons; each chunk is a separate quote
        for chunk in key_dialogue.split(';'):
            quote = chunk.strip().strip('"').strip()
            if not quote:
                continue
            if quote.lower() not in script_lower:
                failures.append({
                    'kind': 'dialogue_missing',
                    'detail': quote,
                    'expected': quote,
                    'severity': 'high',
                })

    # 2. Visual keywords: each must appear in some panel's composition prose
    visual_kws = (brief_row.get('visual_keywords') or '').strip()
    if visual_kws:
        all_composition = ' '.join(
            panel['composition'] for page in pages for panel in page['panels']
        ).lower()
        for chunk in visual_kws.split(';'):
            kw = chunk.strip()
            if not kw:
                continue
            if kw.lower() not in all_composition:
                failures.append({
                    'kind': 'visual_keyword_missing',
                    'detail': kw,
                    'expected': kw,
                    'severity': 'medium',
                })

    # 3. Panel count per page must match brief panel_breakdown
    breakdown_map = _parse_panel_breakdown(brief_row.get('panel_breakdown') or '')
    for page in pages:
        expected_token = breakdown_map.get(page['number'])
        if not expected_token:
            continue
        expected_count = _panels_per_token(expected_token)
        if expected_count is None:
            continue  # irregular or unknown — skip count check
        actual_count = len(page['panels'])
        if actual_count != expected_count:
            failures.append({
                'kind': 'panel_count_mismatch',
                'detail': f"page {page['number']}: expected {expected_count} panels ({expected_token}), got {actual_count}",
                'expected': str(expected_count),
                'severity': 'medium',
            })

    # 4. Page-turn beats: any brief page_turn_beats text means SOME page in
    # the script must carry the page-turn marker. This is an existence-only
    # check — we don't attempt to map beat descriptions like "p2 reveal" to
    # specific page numbers (future improvement).
    page_turn_beats = (brief_row.get('page_turn_beats') or '').strip()
    if page_turn_beats:
        # Reuse already-parsed page data; is_page_turn was populated by parse_script.
        turn_pages = [p['number'] for p in pages if p['is_page_turn']]
        if not turn_pages:
            failures.append({
                'kind': 'page_turn_missing',
                'detail': 'brief specifies page-turn beats but no page in the script carries the ⟵ PAGE-TURN REVEAL marker',
                'expected': page_turn_beats,
                'severity': 'high',
            })

    return failures


# Density and tier conventions per references/gn-layout-vocabulary.md.
# Density limit: 13+ panels on a single page becomes a legibility
# crisis (the reader can't scan comfortably). Tier convention: 2-4
# panels in a single horizontal row; outside this band the token is
# almost certainly mis-labeled.
_PANEL_DENSITY_LIMIT: Final[int] = 13
_TIER_PANEL_RANGE: Final[tuple[int, int]] = (2, 4)


# Closed set of layout anti-pattern kinds. Mirrors the
# CrossTierPatternKey / StoryPowerStatus / BriefOutcome Literal+tuple
# pattern from scoring_story_power.py — a consumer doing
# `finding['kind'] == 'panel_density_excesive'` (typo) gets a static
# mypy error instead of a silent false-negative.
LayoutAntiPatternKind = Literal[
    'page_turn_on_page_one',
    'panel_density_excessive',
    'tier_panel_count_unconventional',
    'script_unparseable',
]


class _LayoutAntiPatternRequired(TypedDict):
    kind: LayoutAntiPatternKind
    detail: str
    severity: Severity
    expected: str


class LayoutAntiPattern(_LayoutAntiPatternRequired, total=False):
    """A deterministic layout anti-pattern surfaced by
    check_layout_anti_patterns. `page` is set for page-anchored
    findings (page_turn_on_page_one, panel_density_excessive,
    tier_panel_count_unconventional); absent for script-wide
    findings (script_unparseable).

    Failure-shape Required+Optional split mirrors ContinuityFinding /
    BriefFinding / FieldCoherenceFinding in scoring_story_power.py.
    """
    page: int


def check_layout_anti_patterns(
        script_text: str,
        brief_row: dict | None = None,
        ) -> list[LayoutAntiPattern]:
    """Return a list of failure dicts for deterministic layout
    anti-patterns documented in references/gn-layout-vocabulary.md.

    Three checks today:

    1. `page_turn_on_page_one`: a script with the ⟵ PAGE-TURN REVEAL
       marker on page 1. Impossible — there's no preceding page to
       turn from. Severity high.

    2. `panel_density_excessive`: any page with ≥13 panels. Legibility
       crisis at this threshold; the reader can no longer scan the
       panels comfortably. Severity medium.

    3. `tier_panel_count_unconventional`: the brief's panel_breakdown
       declares `pN:tier` but the script's page N has a panel count
       outside {2, 3, 4}. A tier conventionally holds 2-4 panels;
       outside this band it's almost certainly an N-grid mis-labeled,
       or a splash mis-labeled as a tier. Severity low. Requires
       brief_row (skipped when no brief is provided).

    Each failure dict carries: kind, detail, severity, and (where
    available) page/expected fields for the revision prompt. Empty
    list when the script is clean.
    """
    failures: list[LayoutAntiPattern] = []
    parsed = parse_script(script_text)
    pages = parsed['pages']

    # 0. Unparseable script: text is non-empty but no pages parsed.
    # Without this guard the function returns [] (clean), indistinguishable
    # from a well-formed clean script. Catches encoding regressions, regex
    # drift, header-format violations, or accidental truncation.
    if not pages and script_text.strip():
        failures.append({
            'kind': 'script_unparseable',
            'detail': 'script text is non-empty but no pages parsed; '
                      'check the page header format '
                      '(expected `## Page N — LAYOUT [⟵ PAGE-TURN REVEAL]`)',
            'expected': 'at least one parseable `## Page N` header',
            'severity': 'high',
        })
        # Bail early — the rest of the checks have nothing to iterate.
        return failures

    # 1. Page-turn marker on page 1.
    # Defensive against malformed scripts with duplicate `## Page 1`
    # headers (e.g. cross-chapter regenerated drafts); surface one
    # finding rather than N when multiple match.
    for page in pages:
        if page['number'] == 1 and page['is_page_turn']:
            failures.append({
                'kind': 'page_turn_on_page_one',
                'detail': 'page 1 carries the ⟵ PAGE-TURN REVEAL marker, '
                          'but page 1 cannot be a page-turn (no preceding '
                          'page to turn from)',
                'expected': 'remove the marker from page 1, or move the '
                            'reveal beat to a later page',
                'severity': 'high',
                'page': 1,
            })
            break

    # 2. Panel-density ceiling.
    for page in pages:
        n = len(page['panels'])
        if n >= _PANEL_DENSITY_LIMIT:
            failures.append({
                'kind': 'panel_density_excessive',
                'detail': f'page {page["number"]}: {n} panels exceeds the '
                          f'{_PANEL_DENSITY_LIMIT}-panel legibility '
                          'ceiling',
                'expected': f'≤{_PANEL_DENSITY_LIMIT - 1} panels per page',
                'severity': 'medium',
                'page': page['number'],
            })

    # 3. Tier-panel-count check against brief's panel_breakdown.
    if brief_row:
        breakdown_map = _parse_panel_breakdown(
            brief_row.get('panel_breakdown') or ''
        )
        low, high = _TIER_PANEL_RANGE
        for page in pages:
            token = breakdown_map.get(page['number'])
            if not token or token.strip().lower() != 'tier':
                continue
            n = len(page['panels'])
            if not (low <= n <= high):
                failures.append({
                    'kind': 'tier_panel_count_unconventional',
                    'detail': (
                        f'page {page["number"]}: declared `tier` in '
                        f'panel_breakdown but rendered with {n} panels '
                        f'(convention is {low}-{high} panels per tier)'
                    ),
                    'expected': f'{low}-{high} panels on a tier page',
                    'severity': 'low',
                    'page': page['number'],
                })

    return failures

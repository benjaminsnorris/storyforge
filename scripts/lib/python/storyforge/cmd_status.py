"""storyforge status — deterministic next-step verdict.

Usage:
    storyforge status            # human-readable tree + recommended next step
    storyforge status --json     # structured verdict for tooling (e.g. forge)

Read-only, no LLM. Synthesizes the elaboration floor/coverage/consistency
checks plus phase and scene draft-state into one routable verdict.
"""

import argparse
import json

from storyforge.common import detect_project_root, get_medium
from storyforge.status import CRAFT_ADVISORY_SOURCE, PlanGapsRecord, build_status

_STATE_MARK = {'solid': '✓', 'thin': '✗', 'not_started': '—', 'unreadable': '!',
               'given': '✓'}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='storyforge status',
        description='Deterministic next-step verdict for the current project.')
    parser.add_argument('--json', action='store_true', dest='json_output',
                        help='Emit the structured verdict as JSON')
    parser.add_argument('--dry-run', action='store_true',
                        help='No-op flag for interface parity (status never writes)')
    return parser.parse_args(argv)


def _voice_line(voice: dict) -> str:
    """The voice's line in the ladder (#656): where it sits, and the POVs
    the check after the map found book.md silent on."""
    parts = [voice['detail']] if voice['detail'] else []
    if voice['when'] != 'first':
        parts.append(f"later (key-decisions.md: voice_stage: {voice['when']})")
    if voice['pov_gaps']:
        parts.append(f"book.md says nothing of POV(s): {', '.join(voice['pov_gaps'])}")
    elif voice['pov_gaps'] == []:   # None: the check after the map didn't run
        parts.append('book.md names every POV of the map')
    detail = f" — {'; '.join(parts)}" if parts else ''
    return f"  V  {voice['name']:<13} {_STATE_MARK[voice['state']]} {voice['state']}{detail}"


def render_human(verdict: dict) -> str:
    lines = []
    match = ('matches storyforge.yaml' if verdict['phase_matches_yaml']
             else f"declared '{verdict['phase_declared']}'")
    suffix = '' if not verdict['phase_declared'] else f'  ({match})'
    lines.append(f"PHASE: {verdict['phase']}{suffix}")
    lines.append('LADDER:')
    voice = verdict.get('voice')
    for r in verdict['ladder']:
        if voice and r['level'] == 3 and voice['when'] == 'first':
            lines.append(_voice_line(voice))   # #656: the voice before the spine
        mark = _STATE_MARK[r['state']]
        detail = f" — {r['detail']}" if r['detail'] else ''
        lines.append(f"  L{r['level']} {r['name']:<13} {mark} {r['state']}{detail}")
    if voice and voice['when'] != 'first':
        lines.append(_voice_line(voice))   # voice_stage: later, before drafting
    nxt = verdict['next']
    cmd = f"  [{nxt['command']}]" if nxt['command'] else ''
    lines.append(f"NEXT:  {nxt['action']}{cmd}")
    if nxt['reason']:
        lines.append(f"       {nxt['reason']}")
    if verdict['then']:
        lines.append(f"THEN:  {verdict['then']['action']}")
    if verdict['blockers']:
        lines.append('BLOCKERS:')
        for b in verdict['blockers']:
            lines.append(f"  [{b['source']}] {b['detail']}")
    else:
        lines.append('BLOCKERS: none')
    for note in verdict.get('notes') or []:
        lines.append(f'NOTE: {note}')
    every = verdict.get('advisory') or []
    craft = [a for a in every if a['source'] == CRAFT_ADVISORY_SOURCE]
    from storyforge.gate import advisory_line, is_knowledge_row, is_unruled_row
    gated = [a for a in every if a['source'] != CRAFT_ADVISORY_SOURCE]
    unruled = [a for a in gated if is_unruled_row(a)]
    advisory = [a for a in gated if not is_knowledge_row(a) and not is_unruled_row(a)]
    knowing = [a for a in gated if is_knowledge_row(a)]
    if advisory:
        lines.append(f'ADVISORY: {len(advisory)} broken promise(s) the gate reported but did '
                     f'not stop on (working/gate-advisory.csv); the prose stands. Amend the '
                     f'brief, or mark the beat `must:` to require it:')
        for row in advisory:
            lines.append(f'  {advisory_line(row)}')
    if knowing:
        lines.append(f'ADVISORY: {len(knowing)} use(s) of a fact before the scene that shows '
                     f'it learned, by the typed knowledge check, which the gate reported but '
                     f'did not stop on (working/gate-advisory.csv). Fix the prose, or the '
                     f'brief\'s knowledge_in or knowledge_out, where one is wrong:')
        for row in knowing:
            lines.append(f'  {advisory_line(row)}')
    if unruled:
        lines.append(f'ADVISORY: {len(unruled)} plan fact(s) the scene may change that the '
                     f'check gave no ruling on, which the gate reported but did not stop on '
                     f'(working/gate-advisory.csv); the plan\'s fact stands. Fix the plan, or '
                     f'the prose, where the scene does change it:')
        for row in unruled:
            lines.append(f'  {advisory_line(row)}')
    if craft:
        # #643: diagnostics the author can use, never a stop
        lines.append(f'ADVISORY: {len(craft)} craft-framework check(s) not met; a scene '
                     f"needn't fit a framework, so these never block:")
        for row in craft:
            lines.append(f"  {row['finding']}  [{row['command']}]")
    lines.extend(_plan_gap_lines(verdict.get('plan_gaps')))
    return '\n'.join(lines)


def _plan_gap_lines(record: 'PlanGapsRecord | None') -> list[str]:
    """The two-writers test's gaps (#702), as `storyforge bibles` lists
    them: advisory, since a plan may leave a question open on purpose."""
    if not record:
        return []
    from storyforge.bibles import Gap
    gaps = [Gap(**g) for g in record['gaps']]
    lines = []
    if gaps:
        lines.append(f'PLAN GAPS: {len(gaps)} place(s) two writers drafting from the plan could '
                     f'disagree (the two-writers test; advisory, settle them or leave them '
                     f'open on purpose):')
        lines += [f'  {g.message()}' for g in gaps]
    else:
        lines.append('PLAN GAPS: none the two-writers test can see')
    lines += [f'  NOTE: {n}' for n in record['notes']]
    return lines


def main(argv=None):
    args = parse_args(argv or [])
    project_dir = detect_project_root()
    medium = get_medium(project_dir) or 'novel'
    verdict = build_status(project_dir, medium)
    if args.json_output:
        print(json.dumps(verdict, indent=2))
    else:
        print(render_human(verdict))

"""Source fidelity: an adaptation's briefs or prose against its source (#477).

The same shape as brief fidelity (`scoring.build_fidelity_prompt`), with the
source scenes on the left-hand side: one call per mapped scene (score uses
the evaluation tier, Sonnet) compares the scene's brief, or its prose, with the source scenes it adapts
(`reference/source-map.csv`) on `ELEMENTS`, lists every departure and tags it
`deliberate` (the map row's treatment or note, or a version rule under
`source.rules`, authorizes it) or `drift` (nothing does). Elements are scored
1-5 on drift only, so a deliberate departure is never penalized. With a
`range:`, a scene whose map row names a source scene outside it is not
checked (it is broken data, which validate blocks on).

Output, in the score cycle's directory: `source-fidelity.csv`
(`SCORE_COLUMNS`) and `source-fidelity-rationale.csv` (`RATIONALE_COLUMNS`),
merged by (scene, target) so a briefs run and a prose run share a cycle.
`target_hash` records what was scored; `latest_drift` only returns drift
whose brief or prose hasn't changed since, which is what revise's upstream
fix reads (so a fixed brief isn't fixed again on stale scores). `mode` is
the revise hook's business: in `free` mode drift is reported, not fixed.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field

from storyforge import source
from storyforge.common import csv_safe, log

ELEMENTS = ('goal', 'outcome', 'key_actions', 'key_dialogue', 'on_stage', 'knowledge_out')
TAGS = ('deliberate', 'drift')
TARGETS = ('brief', 'prose')

SCORES_FILE = 'source-fidelity.csv'
RATIONALE_FILE = 'source-fidelity-rationale.csv'
SCORE_COLUMNS = ['id', 'target', 'target_hash', *ELEMENTS, 'overall', 'drift', 'deliberate']
RATIONALE_COLUMNS = ['id', 'target', 'element', 'tag', 'evidence', 'authority']

# The brief fields a brief target shows (knowledge_out with its statements)
_BRIEF_FIELDS = ('goal', 'conflict', 'outcome', 'crisis', 'decision', 'key_actions',
                 'key_dialogue', 'knowledge_out')
# The source fields compared (plus summary, pov and on_stage for orientation)
_SOURCE_FIELDS = ('goal', 'outcome', 'key_actions', 'key_dialogue', 'knowledge_out')
# Brief fields the target shows that aren't scored elements: a departure on
# one is kept in the rationale under its own name, never a failed scene. The
# model comments on what it is shown (Beowulf B-023: 3 of 48 scenes lost)
NOTED_FIELDS = ('title', 'pov', 'conflict', 'crisis', 'decision')
# How knowledge_out is shown on both sides: what the scene adds. The briefs
# prompt makes knowledge_out knowledge_in plus the scene's new facts, so the
# whole list compared with a source scene's own facts read every carried
# fact as drift (Gawain G-024: 36 of 95 drift items)
KNOWLEDGE_LABEL = 'knowledge_out (new in this scene)'


def new_facts(brief: dict) -> list[str]:
    """The fact ids a brief's knowledge_out adds to its knowledge_in."""
    carried = set(source.split_ids(brief.get('knowledge_in', '')))
    return [f for f in source.split_ids(brief.get('knowledge_out', '')) if f not in carried]


class SourceFidelityError(Exception):
    """A reply that can't be used: refused, cut off, or not in the format."""


@dataclass(frozen=True)
class Result:
    scene_id: str
    target: str
    target_hash: str
    scores: dict[str, int]
    departures: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self):
        if self.target not in TARGETS:
            raise ValueError(f'target {self.target!r}')
        if set(self.scores) != set(ELEMENTS) or not all(
                isinstance(v, int) and 1 <= v <= 5 for v in self.scores.values()):
            raise ValueError(f'{self.scene_id}: scores must be 1-5 for exactly {ELEMENTS}')

    @property
    def overall(self) -> float:
        from storyforge.scoring import _power_mean
        return round(_power_mean([float(v) for v in self.scores.values()]), 1)

    def count(self, tag: str) -> int:
        return sum(1 for d in self.departures if d['tag'] == tag)


# ============================================================================
# The two sides
# ============================================================================

def _project_tables(project_dir: str) -> dict[str, dict[str, dict]]:
    from storyforge.elaborate import _read_csv
    ref = os.path.join(project_dir, 'reference')
    return {name: {r.get('id', ''): r for r in _read_csv(os.path.join(ref, name))}
            for name in ('scenes.csv', 'scene-intent.csv', 'scene-briefs.csv',
                         'commitments.csv')}


def target_text(project_dir: str, scene_id: str, target: str,
                tables: dict | None = None) -> str | None:
    """What is scored for a scene: its brief (with on_stage and the facts its
    knowledge_out names), or its prose without illustration markers. None
    when there is none (no brief goal, or no prose file)."""
    if target == 'prose':
        from storyforge.illustrations import strip_markers
        path = os.path.join(project_dir, 'scenes', f'{scene_id}.md')
        try:
            with open(path, encoding='utf-8') as f:
                prose = strip_markers(f.read()).strip()
        except FileNotFoundError:
            return None
        return prose or None
    t = tables or _project_tables(project_dir)
    brief = t['scene-briefs.csv'].get(scene_id, {})
    if not brief.get('goal', '').strip():
        return None
    scene = t['scenes.csv'].get(scene_id, {})
    intent = t['scene-intent.csv'].get(scene_id, {})
    facts = t['commitments.csv']
    lines = []
    for key, val in (('title', scene.get('title', '')), ('pov', scene.get('pov', '')),
                     ('on_stage', intent.get('on_stage', ''))):
        if val.strip():
            lines.append(f'**{key}:** {val.strip()}')
    for key in _BRIEF_FIELDS:
        val = brief.get(key, '').strip()
        if not val:
            continue
        if key == 'knowledge_out':
            val = '; '.join(f'{f} ({facts[f]["statement"]})' if facts.get(f, {}).get('statement')
                            else f for f in new_facts(brief))
            if not val:
                continue
            key = KNOWLEDGE_LABEL
        lines.append(f'**{key}:** {val}')
    return '\n'.join(lines)


def target_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def _source_side(project_dir: str, refs: list[tuple[str, str]], tables=None) -> str:
    from storyforge.prompts_source import _Tables
    t = tables or _Tables(project_dir)
    blocks = []
    for slug, sid in refs:
        scene = t.row(slug, 'scenes.csv', sid)
        brief = t.row(slug, 'scene-briefs.csv', sid)
        intent = t.row(slug, 'scene-intent.csv', sid)
        facts = {k: r.get('statement', '') for k, r in t.table(slug, 'commitments.csv').items()}
        lines = [f'### {slug}:{sid}' + (f': {scene["title"]}' if scene.get('title') else '')]
        summary = scene.get('summary', '') or intent.get('function', '')
        for key, val in (('summary', summary), ('pov', scene.get('pov', '')),
                         ('on_stage', intent.get('on_stage', ''))):
            if val.strip():
                lines.append(f'**{key}:** {val.strip()}')
        for key in _SOURCE_FIELDS:
            val = brief.get(key, '').strip()
            if not val:
                continue
            if key == 'knowledge_out':
                val = '; '.join(f'{f} ({facts[f]})' if facts.get(f) else f
                                for f in new_facts(brief))
                if not val:
                    continue
                key = KNOWLEDGE_LABEL
            lines.append(f'**{key}:** {val}')
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


# ============================================================================
# Prompt
# ============================================================================

@dataclass(frozen=True)
class Plan:
    """What one scene's check needs, or why it can't be checked: exactly one
    of `prompt` (with its `target_hash`) and `skip`."""
    scene_id: str
    prompt: str = ''
    target_hash: str = ''
    skip: str = ''        # why there is no prompt ('' when there is one)
    broken: bool = False  # the skip means the data is wrong, not that there's nothing to do

    def __post_init__(self):
        if bool(self.prompt) == bool(self.skip) or bool(self.prompt) != bool(self.target_hash):
            raise ValueError(f'{self.scene_id}: a Plan has a prompt and its hash, or a skip')


def plan_scene(project_dir: str, scene_id: str, target: str, plugin_dir: str,
               cfg: source.SourceConfig, map_rows: dict[str, dict],
               rules: str, tables: dict | None = None,
               cat: dict | None = None, source_tables=None,
               spans: dict | None = None) -> Plan:
    """One scene's check, or why there is none. `cat` and `spans` (each
    source's adapted scene ids, from `source.spans`) are read when not given; a caller
    planning many scenes passes them. A map row naming a source scene outside
    its source's `range:` is broken: only the range is being adapted, and
    validate blocks on it."""
    if target not in TARGETS:
        raise ValueError(f'target must be one of {TARGETS}')
    row = map_rows.get(scene_id)
    if row is None:
        return Plan(scene_id, skip='not in the source map (run validate)', broken=True)
    if row.get('treatment') == 'invent':
        return Plan(scene_id, skip='invented (no source scene)')
    cat = cat if cat is not None else source.catalogue(project_dir, cfg)
    refs = [source.resolve_source_id(r, cat) for r in source.split_ids(row.get('source_scenes', ''))]
    if not refs or any(r is None for r in refs):
        return Plan(scene_id, skip='its source scenes are not in the imported source '
                                   '(run validate)', broken=True)
    spans = spans if spans is not None else source.spans(project_dir, cfg)
    outside = [f'{slug}:{sid}' for slug, sid in refs if source.outside_range((slug, sid), spans)]
    if outside:
        return Plan(scene_id, skip=f'its source scenes {", ".join(outside)} are outside the '
                                   f'adapted range (run validate)', broken=True)
    text = target_text(project_dir, scene_id, target, tables)
    if text is None:
        return Plan(scene_id, skip='no brief' if target == 'brief' else 'no prose')

    template_path = os.path.join(plugin_dir, 'scripts', 'prompts', 'scoring',
                                 'source-fidelity.md')
    with open(template_path, encoding='utf-8') as f:
        template = f.read()
    kind = 'brief' if target == 'brief' else 'prose'
    prompt = (template
              .replace('{SOURCE_DATA}', _source_side(project_dir, refs, source_tables))
              .replace('{TREATMENT}', row.get('treatment', ''))
              .replace('{NOTE}', row.get('note', '') or '(none)')
              .replace('{MODE}', cfg.mode)
              .replace('{RULES}', rules or '(none)')
              .replace('{TARGET_DATA}', text)
              .replace('{TARGET_KIND}', kind)
              .replace('{SCENE_ID}', scene_id))
    return Plan(scene_id, prompt=prompt, target_hash=target_hash(text))


# ============================================================================
# Parsing
# ============================================================================

def parse_response(response: str, scene_id: str, target: str, hash_: str) -> Result:
    """The reply's SCORES and DEPARTURES. Raises SourceFidelityError when an
    element has no 1-5 score, or a departure names an unknown element or tag,
    says nothing, or is `deliberate` with no authority: a result with a
    misread tag would send the wrong scenes to revise."""
    scores: dict[str, int] = {}
    departures: list[dict[str, str]] = []
    problems: list[str] = []
    score_rows = 0
    section = None
    for line in response.splitlines():
        s = line.strip().strip('`')
        if not s:
            continue
        if re.match(r'^\**SCORES\**:?$', s, re.I):
            section = 'scores'
            continue
        if re.match(r'^\**DEPARTURES\**:?$', s, re.I):
            section = 'departures'
            continue
        parts = [p.strip() for p in s.split('|')]
        if parts[0] == 'id' or section is None:
            continue
        if parts[0] != scene_id:
            problems.append(f'a row for {parts[0]!r}, not {scene_id}')
            continue
        if section == 'scores':
            score_rows += 1
            if score_rows > 1:
                problems.append('more than one SCORES row')
                continue
            if len(parts) != len(ELEMENTS) + 1:
                problems.append(f'a SCORES row with {len(parts)} cells')
                continue
            for el, val in zip(ELEMENTS, parts[1:]):
                if val.isdigit() and 1 <= int(val) <= 5:
                    scores[el] = int(val)
                else:
                    problems.append(f'{el} score {val!r} is not 1-5')
        else:
            if len(parts) != 5:
                # a | inside the text would cut the evidence short
                problems.append(f'a DEPARTURES row with {len(parts)} cells, not 5')
                continue
            element, tag, evidence, authority = parts[1], parts[2].lower(), parts[3], parts[4]
            if element not in ELEMENTS and element not in NOTED_FIELDS:
                problems.append(f'departure element {element!r}')
            elif tag not in TAGS:
                problems.append(f'departure tag {tag!r} (deliberate or drift)')
            elif not evidence:
                problems.append(f'a {tag} departure on {element} that says nothing')
            elif tag == 'deliberate' and authority.lower() in ('', 'none'):
                problems.append(f'a deliberate departure on {element} with no authority')
            elif tag == 'drift' and authority.lower() not in ('', 'none'):
                problems.append(f'a drift departure on {element} that names an authority '
                                f'({authority}): deliberate or drift?')
            else:
                departures.append({'element': element, 'tag': tag, 'evidence': evidence,
                                   'authority': authority if tag == 'deliberate' else 'none'})
    missing = [el for el in ELEMENTS if el not in scores]
    if missing and not problems:
        problems.append(f'no score for {", ".join(missing)}')
    if problems:
        raise SourceFidelityError(f'{scene_id}: ' + '; '.join(problems))
    return Result(scene_id, target, hash_, scores, departures)


# ============================================================================
# Files
# ============================================================================

def _read(path: str, columns: list[str]) -> list[dict[str, str]]:
    """A results file's rows ([] when there is none). Raises SourceError for
    one that can't be read, has another header, or a row with the wrong
    number of cells: drift read from it would be wrong."""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
    except (OSError, UnicodeDecodeError) as e:
        raise source.SourceError(f'{path} could not be read ({e})') from e
    if not lines:
        return []
    if lines[0].split('|') != columns:
        raise source.SourceError(f'{path}: the header must be {"|".join(columns)}; '
                                 f're-run score --source-fidelity')
    rows = [l.split('|') for l in lines[1:]]
    bad = [n for n, r in enumerate(rows, 2) if len(r) != len(columns)]
    if bad:
        raise source.SourceError(f'{path} line {bad[0]}: wrong number of cells')
    return [dict(zip(columns, r)) for r in rows]


def _write(path: str, columns: list[str], rows: list[dict[str, str]]) -> None:
    out = ['|'.join(columns)] + ['|'.join(csv_safe(str(r.get(c, ''))) for c in columns)
                                 for r in rows]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(out) + '\n')


def write_results(results: list[Result], out_dir: str) -> None:
    """Merge results into the cycle's two files: a row for the same scene and
    target is replaced; every other row stays."""
    os.makedirs(out_dir, exist_ok=True)
    done = {(r.scene_id, r.target) for r in results}
    scores_path = os.path.join(out_dir, SCORES_FILE)
    rat_path = os.path.join(out_dir, RATIONALE_FILE)
    scores = [r for r in _read(scores_path, SCORE_COLUMNS)
              if (r.get('id'), r.get('target')) not in done]
    rats = [r for r in _read(rat_path, RATIONALE_COLUMNS)
            if (r.get('id'), r.get('target')) not in done]
    for res in results:
        row = {'id': res.scene_id, 'target': res.target, 'target_hash': res.target_hash,
               'overall': res.overall, 'drift': res.count('drift'),
               'deliberate': res.count('deliberate')}
        row.update({el: res.scores[el] for el in ELEMENTS})
        scores.append(row)
        rats += [{'id': res.scene_id, 'target': res.target, **d} for d in res.departures]
    _write(scores_path, SCORE_COLUMNS, scores)
    _write(rat_path, RATIONALE_COLUMNS, rats)


def _cycles(project_dir: str) -> list[str]:
    scores_dir = os.path.join(project_dir, 'working', 'scores')
    if not os.path.isdir(scores_dir):
        return []
    found = []
    for name in os.listdir(scores_dir):
        m = re.match(r'^cycle-(\d+)$', name)
        if m and os.path.isfile(os.path.join(scores_dir, name, SCORES_FILE)):
            found.append((int(m.group(1)), os.path.join(scores_dir, name)))
    return [p for _, p in sorted(found, reverse=True)]


@dataclass
class DriftState:
    """What the newest source-fidelity results say, per scene and target."""
    drift: dict[str, list[str]] = field(default_factory=dict)  # scene -> drift lines
    stale: list[str] = field(default_factory=list)    # scored on a brief/prose since changed
    checked: int = 0                                   # (scene, target) results read


def drift_state(project_dir: str) -> DriftState:
    """Drift from each scene's newest source-fidelity result per target, only
    where the brief or prose scored is unchanged since (its hash matches);
    results scored on something since changed are listed `stale`. An empty
    state for a project without a source block. Raises SourceError for a
    results file that can't be read (see `_read`)."""
    state = DriftState()
    if source.read_config(project_dir) is None:
        return state
    tables = _project_tables(project_dir)
    seen: set[tuple[str, str]] = set()
    for cycle in _cycles(project_dir):
        rats = _read(os.path.join(cycle, RATIONALE_FILE), RATIONALE_COLUMNS)
        for row in _read(os.path.join(cycle, SCORES_FILE), SCORE_COLUMNS):
            key = (row['id'], row['target'])
            if key in seen or key[1] not in TARGETS:
                continue
            seen.add(key)
            state.checked += 1
            current = target_text(project_dir, key[0], key[1], tables)
            if current is None or target_hash(current) != row['target_hash']:
                state.stale.append(f'{key[0]} ({key[1]})')
                continue
            lines = [f'{key[1]} {r["element"]}: {r["evidence"]}' for r in rats
                     if (r['id'], r['target']) == key and r['tag'] == 'drift']
            if str(len(lines)) != row['drift']:
                raise source.SourceError(
                    f'{os.path.join(cycle, SCORES_FILE)}: {key[0]} ({key[1]}) counts '
                    f'{row["drift"]} drift but {RATIONALE_FILE} lists {len(lines)}')
            if lines:
                state.drift.setdefault(key[0], []).extend(lines)
    return state


def latest_drift(project_dir: str) -> dict[str, list[str]]:
    """{scene id: its current drift departures as one-line descriptions}
    (`drift_state(...).drift`)."""
    return drift_state(project_dir).drift


# ============================================================================
# Running
# ============================================================================

def run(project_dir: str, scene_ids: list[str], target: str, *, plugin_dir: str,
        out_dir: str, log_dir: str, model: str, system: list | None = None,
        parallel: int = 6) -> tuple[list[Result], dict[str, str], dict[str, str]]:
    """Check each mapped scene; write the results into `out_dir`.

    Returns (results, skipped, failed): `skipped` is scene -> why it had
    nothing to check (invented, no brief or prose), `failed` is scene -> why
    there is no result: a check that ran and failed, or a scene whose map
    data is broken (not mapped, source scenes not found or outside the
    source's `range:`). Raises SourceError for a source block, map, range or
    rules file that can't be used, or a source not imported.
    """
    from storyforge.api import (
        calculate_cost_from_usage, extract_text, extract_usage, invoke_to_file, stop_problem,
    )
    from storyforge.costs import log_operation
    from storyforge.runner import run_parallel

    cfg = source.read_config(project_dir)
    if cfg is None:
        raise source.SourceError('storyforge.yaml has no `source:` block')
    rows = source.read_source_map(project_dir)
    if rows is None:
        raise source.SourceError(f'there is no reference/{source.SOURCE_MAP} yet '
                                 f'(elaborate --stage map writes it)')
    map_rows = source.map_rows_by_scene(rows)
    rules = source.read_rules(project_dir, cfg)
    tables = _project_tables(project_dir)

    from storyforge.prompts_source import _Tables
    source.require_imported(project_dir, cfg)
    cat = source.catalogue(project_dir, cfg)
    spans = source.spans(project_dir, cfg)
    src_tables = _Tables(project_dir)
    plans = {sid: plan_scene(project_dir, sid, target, plugin_dir, cfg, map_rows, rules,
                             tables, cat, src_tables, spans)
             for sid in scene_ids}
    skipped = {sid: p.skip for sid, p in plans.items() if p.skip and not p.broken}
    broken = {sid: p.skip for sid, p in plans.items() if p.broken}
    todo = [sid for sid, p in plans.items() if not p.skip]
    os.makedirs(log_dir, exist_ok=True)

    def check(sid: str) -> Result:
        plan = plans[sid]
        log_file = os.path.join(log_dir, f'source-fidelity-{target}-{sid}.json')
        if os.path.exists(log_file):
            os.remove(log_file)   # never read an earlier run's reply as this one's
        response = invoke_to_file(plan.prompt, model, log_file, 2048, system=system)
        usage = extract_usage(response)
        log_operation(project_dir, f'score-source-fidelity-{target}', model,
                      usage['input_tokens'], usage['output_tokens'],
                      calculate_cost_from_usage(usage, model), target=sid,
                      cache_read=usage.get('cache_read', 0),
                      cache_create=usage.get('cache_create', 0))
        problem = stop_problem(response)
        if problem:
            raise SourceFidelityError(f'{sid}: {problem}')
        return parse_response(extract_text(response), sid, target, plan.target_hash)

    outcomes = run_parallel(todo, check, max_workers=parallel,
                            label=f'source fidelity ({target})')
    results: list[Result] = []
    failed: dict[str, str] = dict(broken)
    for sid in todo:
        out = outcomes.get(sid)
        if isinstance(out, Result):
            results.append(out)
        else:
            failed[sid] = str(out) if out is not None else 'not run (interrupted)'
    if results:
        write_results(results, out_dir)
    return results, skipped, failed


def report(results: list[Result], skipped: dict[str, str], failed: dict[str, str],
           target: str) -> None:
    """Log what the run found and what it couldn't check."""
    if results:
        avg = sum(r.overall for r in results) / len(results)
        drift = [r for r in results if r.count('drift')]
        log(f'  Source fidelity ({target}): {len(results)} scenes, avg {avg:.1f}/5; '
            f'{sum(r.count("deliberate") for r in results)} deliberate departures, '
            f'{sum(r.count("drift") for r in results)} drift in {len(drift)} scenes')
        for r in drift:
            for d in r.departures:
                if d['tag'] == 'drift':
                    log(f'    drift {r.scene_id} {d["element"]}: {d["evidence"]}')
    if skipped:
        log(f'  Not checked ({len(skipped)}): '
            + '; '.join(f'{s} ({why})' for s, why in skipped.items()))
    for sid, why in failed.items():
        log(f'  WARNING: no source-fidelity result for {sid}: {why}')

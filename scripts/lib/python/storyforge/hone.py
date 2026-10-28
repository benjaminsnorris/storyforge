"""CSV data quality tool — registries, briefs, structural fixes, gap fill.

Domains:
- registries: Build canonical registries and normalize field values (absorbs reconcile.py)
- briefs: Concretize abstract brief language as concrete physical beats
- structural: Fix CSV fields from evaluation findings
- gaps: Fill empty fields from context

Each domain follows: detect → prompt → apply → commit.
"""

import csv
import os
import re

from storyforge.common import log

from storyforge.elaborate import (
    _read_csv, _read_csv_as_map, _write_csv, _FILE_MAP, DELIMITER,
)
from storyforge.enrich import (
    is_placeholder, load_alias_map, load_mice_registry, normalize_aliases,
    normalize_mice_threads, strip_parentheticals, strip_placeholders,
)

# ============================================================================
# Outcome normalization (deterministic — no API call)
# ============================================================================

_OUTCOME_ENUM = {'yes', 'yes-but', 'no', 'no-and', 'no-but'}
_OUTCOME_RE = re.compile(
    r'^\[?(yes-but|no-and|no-but|yes|no)\b',
    re.IGNORECASE,
)


def normalize_outcomes(raw: str) -> str:
    """Extract enum value from a possibly-elaborated outcome string.

    Handles: 'yes-but — long elaboration', '[no-and]', 'No, but ...', 'yes', etc.
    Returns the raw string unchanged if no enum is recognized.
    """
    raw = raw.strip()
    if not raw:
        return raw
    from storyforge.schema import canonical_outcome_phrase
    m = _OUTCOME_RE.match(canonical_outcome_phrase(raw))
    if m:
        return m.group(1).lower()
    return raw


def reconcile_outcomes(ref_dir: str) -> int:
    """Normalize all outcome fields in scene-briefs.csv to enum values.

    Returns the number of rows changed.
    """
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    rows = _read_csv(briefs_path)
    if not rows:
        return 0

    changed = 0
    for row in rows:
        raw = row.get('outcome', '')
        normalized = normalize_outcomes(raw)
        if normalized != raw:
            row['outcome'] = normalized
            changed += 1

    if changed:
        _write_csv(briefs_path, rows, _FILE_MAP['scene-briefs.csv'])
    return changed


# ============================================================================
# Registry reconcile by deltas
#
# A registry is never rebuilt by the model. Code resolves every reference it
# can through the registry's aliases; only the references that still don't
# resolve go to the model, in fixed-size numbered batches, and it answers one
# line per reference. Code applies each batch before the next. No call's
# output grows with the book, and a reconciled project makes no call at all.
# ============================================================================

KNOWLEDGE_CATEGORIES = frozenset({
    'identity', 'motive-intent', 'capability-constraint', 'state-change',
    'stakes-threat', 'relationship-shift',
})

_REGISTRY_COLUMNS = {
    'characters': ['id', 'name', 'role', 'aliases'],
    'locations': ['id', 'name', 'aliases'],
    'values': ['id', 'name', 'aliases'],
    'mice-threads': ['id', 'name', 'type', 'aliases'],
    'knowledge': ['id', 'name', 'aliases', 'category', 'origin'],
    'physical-states': ['id', 'character', 'description', 'category', 'acquired', 'resolves', 'action_gating'],
}

_DOMAIN_TO_REGISTRY = {
    'characters': 'characters.csv',
    'locations': 'locations.csv',
    'values': 'values.csv',
    'mice-threads': 'mice-threads.csv',
    'knowledge': 'knowledge.csv',
    'physical-states': 'physical-states.csv',
}

# Which CSV columns to normalize per domain
_DOMAIN_TARGETS = {
    'characters': [
        ('scenes.csv', ['pov']),
        ('scene-intent.csv', ['characters', 'on_stage']),
    ],
    'locations': [
        ('scenes.csv', ['location']),
    ],
    'values': [
        ('scene-intent.csv', ['value_at_stake']),
    ],
    'mice-threads': [
        ('scene-intent.csv', ['mice_threads']),
    ],
    'knowledge': [
        ('scene-briefs.csv', ['knowledge_in', 'knowledge_out']),
    ],
    'physical-states': [
        ('scene-briefs.csv', ['physical_state_in', 'physical_state_out']),
    ],
}

# Fields a NEW line supplies, after the id. Derived columns (knowledge
# origin; physical-state acquired/resolves) are filled by code.
_NEW_FIELDS = {
    'characters': ['name', 'role'],
    'locations': ['name'],
    'values': ['name'],
    'mice-threads': ['name', 'type'],
    'knowledge': ['name', 'category'],
    'physical-states': ['character', 'description', 'category', 'action_gating'],
}

# References per call. Output is one short line per reference, so this bounds
# every call's output regardless of the book's length.
_BATCH_SIZE = 60
_BATCH_MAX_TOKENS = 8000

# Chain fields where a model writes "none" / "(none)" / "(empty)" for an empty
# list. Normalization drops those entries, so a placeholder is never stored as
# a fact or a physical state (and is cleaned from data written before the
# extraction parsers dropped them).
_PLACEHOLDER_DOMAINS = {'knowledge', 'physical-states'}


def _scene_order(ref_dir: str) -> list[str]:
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    return sorted(scenes_map, key=lambda sid: int(scenes_map[sid].get('seq') or 0))


def _collect_knowledge_chain(ref_dir: str) -> list[tuple[str, str, str, str]]:
    """Collect knowledge facts in scene order: [(scene_id, seq, knowledge_in, knowledge_out), ...]."""
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    chain = []
    for sid in _scene_order(ref_dir):
        brief = briefs_map.get(sid, {})
        k_in = brief.get('knowledge_in', '').strip()
        k_out = brief.get('knowledge_out', '').strip()
        if k_in or k_out:
            chain.append((sid, scenes_map[sid].get('seq', '0'), k_in, k_out))
    return chain


def _collect_physical_state_chain(ref_dir: str) -> list[tuple[str, str, str, str]]:
    """Collect physical states in scene order: [(scene_id, seq, state_in, state_out), ...]."""
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    chain = []
    for sid in _scene_order(ref_dir):
        brief = briefs_map.get(sid, {})
        ps_in = brief.get('physical_state_in', '').strip()
        ps_out = brief.get('physical_state_out', '').strip()
        if ps_in or ps_out:
            chain.append((sid, scenes_map[sid].get('seq', '0'), ps_in, ps_out))
    return chain


def _split_mice(entry: str) -> tuple[str, str, str]:
    """``+inquiry:who-is-gatsby`` → ``('+', 'inquiry', 'who-is-gatsby')``."""
    entry = entry.strip()
    prefix = ''
    if len(entry) > 1 and entry[0] in '+-':
        prefix, entry = entry[0], entry[1:]
    type_part, sep, name = entry.partition(':')
    if not sep:
        return prefix, '', entry.strip()
    return prefix, type_part.strip().lower(), name.strip()


def _reference_key(domain: str, part: str) -> tuple[str, str, str] | None:
    """A target-field entry as ``(lookup key, display text, type hint)``, or
    None for an empty entry or a placeholder. Mirrors the lookups in
    :func:`normalize_aliases` and :func:`normalize_mice_threads`."""
    if domain == 'mice-threads':
        _prefix, type_hint, name = _split_mice(part)
        return (name.lower(), name, type_hint) if name else None
    text = strip_parentheticals(part.strip())
    if not text or (domain in _PLACEHOLDER_DOMAINS and is_placeholder(text)):
        return None
    return text.lower(), text, ''


def _registry_lookup(domain: str, ref_dir: str) -> dict[str, str]:
    """Lowercased id, name and alias → canonical id for the domain's registry."""
    path = os.path.join(ref_dir, _DOMAIN_TO_REGISTRY[domain])
    if domain == 'mice-threads':
        lookup = load_mice_registry(path)[0]
    else:
        lookup = load_alias_map(path)
    # physical-states.csv has no name column, so load_alias_map is empty
    for row in _read_csv(path):
        if row.get('id'):
            lookup.setdefault(row['id'].lower(), row['id'])
    return lookup


def _unresolved_references(domain: str, ref_dir: str) -> dict[str, dict]:
    """Target-field references the registry does not resolve, in scene order:
    ``{key: {'key', 'text', 'type', 'scenes'}}``."""
    lookup = _registry_lookup(domain, ref_dir)
    order = {sid: i for i, sid in enumerate(_scene_order(ref_dir))}
    found: dict[str, dict] = {}
    for filename, columns in _DOMAIN_TARGETS[domain]:
        rows = _read_csv(os.path.join(ref_dir, filename))
        rows.sort(key=lambda r: order.get(r.get('id', ''), len(order)))
        for row in rows:
            for col in columns:
                for part in (row.get(col) or '').split(';'):
                    ref = _reference_key(domain, part)
                    if not ref or ref[0] in lookup:
                        continue
                    entry = found.setdefault(ref[0], {'key': ref[0], 'text': ref[1],
                                                      'type': ref[2], 'scenes': []})
                    if row.get('id') and row['id'] not in entry['scenes']:
                        entry['scenes'].append(row['id'])
    return found


def find_unresolved(domain: str, ref_dir: str) -> list[str]:
    """Return target-column references the domain's registry does not resolve.

    Semicolon-split, parentheticals stripped, case-insensitive, placeholders
    ignored; a MICE entry is resolved by its thread name.
    """
    return sorted(e['text'] for e in _unresolved_references(domain, ref_dir).values())


def find_alias_collisions(domain: str, ref_dir: str) -> dict[str, list[str]]:
    """Return aliases (lowercased) claimed by more than one registry entry.

    :func:`load_alias_map` keeps whichever entry comes last, so a collision
    silently routes references to the wrong entry.
    """
    owners: dict[str, set[str]] = {}
    for row in _read_csv(os.path.join(ref_dir, _DOMAIN_TO_REGISTRY[domain])):
        entry_id = row.get('id', '')
        names = [row.get('name', ''), entry_id] + (row.get('aliases') or '').split(';')
        for name in names:
            key = name.strip().lower()
            if key:
                owners.setdefault(key, set()).add(entry_id)
    return {k: sorted(v) for k, v in sorted(owners.items()) if len(v) > 1}


def resolve_alias_collisions(domain: str, ref_dir: str) -> int:
    """Give each shared alias to one entry, deterministically.

    The alias stays with the entry whose id or name equals it, otherwise with
    the first entry listing it, and is removed from the others' aliases. Each
    move is logged. A clash between two ids or names can't be fixed by moving
    aliases and is left for :func:`find_alias_collisions` to report. Returns
    the number of aliases removed.
    """
    collisions = find_alias_collisions(domain, ref_dir)
    if not collisions:
        return 0
    rows = _read_csv(os.path.join(ref_dir, _DOMAIN_TO_REGISTRY[domain]))
    removed = 0
    for alias, _ids in collisions.items():
        named = [r for r in rows if alias in (r.get('id', '').lower(), r.get('name', '').strip().lower())]
        listing = [r for r in rows if alias in
                   (a.strip().lower() for a in (r.get('aliases') or '').split(';'))]
        owner = (named or listing)[0]
        for row in listing:
            if row is owner:
                continue
            row['aliases'] = ';'.join(a for a in row['aliases'].split(';')
                                      if a.strip() and a.strip().lower() != alias)
            removed += 1
            log(f'  {domain}: alias "{alias}" kept on {owner["id"]}, removed from {row["id"]}')
    if removed:
        write_registry(ref_dir, domain, rows)
    return removed


# ============================================================================
# Registry writing and normalization
# ============================================================================

def write_registry(ref_dir: str, domain: str, rows: list[dict[str, str]]) -> None:
    """Write registry rows to the domain's CSV file.

    Columns beyond the domain's own (a ``death_scene`` an author added to
    characters.csv) are kept.

    Args:
        ref_dir: Path to the reference/ directory.
        domain: One of the keys in _DOMAIN_TO_REGISTRY.
        rows: List of dicts keyed by the domain's columns.
    """
    if domain not in _DOMAIN_TO_REGISTRY:
        raise ValueError(f'Unknown reconciliation domain: {domain}')

    # Strip type: prefix from IDs when the type is already a separate column
    # (e.g., mice-threads: "character:angela-chen" → "angela-chen")
    if domain in ('mice-threads',):
        for row in rows:
            rid = row.get('id', '')
            if ':' in rid and row.get('type', ''):
                row['id'] = rid.split(':', 1)[1]

    # A physical state belongs to a character: store the character's id
    if domain == 'physical-states':
        char_map = load_alias_map(os.path.join(ref_dir, 'characters.csv'))
        for row in rows:
            if row.get('character'):
                row['character'] = normalize_aliases(char_map, row['character'])

    columns = list(_REGISTRY_COLUMNS[domain])
    for row in rows:
        columns += [c for c in row if c not in columns]
    _write_csv(os.path.join(ref_dir, _DOMAIN_TO_REGISTRY[domain]), rows, columns)


def apply_registry_normalization(
    domain: str, ref_dir: str
) -> int:
    """Load the domain's registry and normalize all target CSV columns.

    Args:
        domain: The reconciliation domain.
        ref_dir: Path to the reference/ directory.

    Returns:
        Total number of individual field values changed.
    """
    if domain not in _DOMAIN_TO_REGISTRY:
        raise ValueError(f'Unknown reconciliation domain: {domain}')

    registry_path = os.path.join(ref_dir, _DOMAIN_TO_REGISTRY[domain])

    # Load alias map (and type map for MICE)
    if domain == 'mice-threads':
        alias_map, type_map = load_mice_registry(registry_path)
    else:
        alias_map = _registry_lookup(domain, ref_dir)
        type_map = None

    if not alias_map and domain not in _PLACEHOLDER_DOMAINS:
        return 0

    targets = _DOMAIN_TARGETS.get(domain, [])
    total_changed = 0

    for filename, columns in targets:
        path = os.path.join(ref_dir, filename)
        rows = _read_csv(path)
        if not rows:
            continue

        file_changed = 0
        for row in rows:
            for col in columns:
                old_val = row.get(col, '')
                if not old_val:
                    continue

                if domain == 'mice-threads' and col == 'mice_threads':
                    new_val = normalize_mice_threads(old_val, alias_map, type_map)
                elif domain in _PLACEHOLDER_DOMAINS:
                    new_val = normalize_aliases(alias_map, strip_placeholders(old_val))
                else:
                    new_val = normalize_aliases(alias_map, old_val)

                if new_val != old_val:
                    row[col] = new_val
                    file_changed += 1

        if file_changed:
            _write_csv(path, rows, _FILE_MAP[filename])
            total_changed += file_changed

    return total_changed


# ============================================================================
# Mapping prompt, parsing and application
# ============================================================================

_DOMAIN_NOUN = {
    'characters': 'character',
    'locations': 'place',
    'values': 'value at stake',
    'mice-threads': 'MICE thread',
    'knowledge': 'knowledge fact',
    'physical-states': 'physical state',
}


def _domain_rules(domain: str) -> str:
    from storyforge.schema import MAX_FACT_NAME_WORDS
    return {
        'characters': """- NEW fields: `N | NEW | id | name | role`
- id: kebab-case slug of the full name (e.g., kael-davreth); name: display name (e.g., Kael Davreth)
- role: protagonist, antagonist, supporting, minor, or referenced
- Variants of one person are one entry (Kael, kael, Kael Davreth); a group ("the Buchanans") maps to each member's id""",
        'locations': """- NEW fields: `N | NEW | id | name`
- id: kebab-case slug (e.g., resonance-chamber); name: canonical display name (e.g., Resonance Chamber)
- Every entry is one real place. Never make an entry for a route, journey or transition ("East Egg to New York", "on the road to the city"): map it to each place it passes through (`N | east-egg;new-york`)
- Variants of one place (case, punctuation, a parenthetical detail, "the" or not) map to the same id""",
        'values': """- NEW fields: `N | NEW | id | name`
- id: kebab-case abstract concept (e.g., justice, truth, autonomy); name: display name (e.g., Justice)
- A novel has 8-15 core thematic values. Map an over-specified value onto the abstract value it specifies ("justice-specifically-restorative-accountability" → justice); declare NEW only for a distinct core value""",
        'mice-threads': """- NEW fields: `N | NEW | id | name | type`
- id: kebab-case slug (e.g., who-killed-rowan); name: descriptive name (e.g., Who killed Rowan?)
- type: milieu, inquiry, character, or event (the reference's own type prefix, when it has one, is usually right)
- One thread worded differently in different scenes is one entry: an orphaned close like `can-Cora-be-trusted-at-Lenas-table` maps to an open `can-cora-be-trusted`""",
        'knowledge': f"""- NEW fields: `N | NEW | id | name | category`
- id: kebab-case, 2-5 words (e.g., marcus-killed-elena)
- name: the fact alone in at most {MAX_FACT_NAME_WORDS} words (e.g., Marcus killed Elena), no reasons, consequences, or second clause
- category: identity, motive-intent, capability-constraint, state-change, stakes-threat, or relationship-shift
- A rewording of a fact already in the registry maps to its id; a reference stating two facts maps to both (`N | id1;id2`)""",
        'physical-states': """- NEW fields: `N | NEW | id | character | description | category | action_gating`
- id: kebab-case slug scoped to the character (e.g., broken-arm-marcus, has-compass-elena)
- character: the character's id from the Character Registry (e.g., marcus-hale, not Marcus Hale)
- description: concise, prose-usable description (under 20 words)
- category: injury, equipment, ability, appearance, or fatigue
- action_gating: true if this state constrains what the character can physically do, false otherwise
- One state described differently in different scenes is one entry""",
    }[domain]


def _registry_line(domain: str, row: dict[str, str]) -> str:
    if domain == 'characters':
        return f'- {row["id"]} — {row.get("name", "")} ({row.get("role", "")})'
    if domain == 'mice-threads':
        return f'- {row["id"]} — {row.get("name", "")} ({row.get("type", "")})'
    if domain == 'knowledge':
        return f'- {row["id"]} — {row.get("name", "")}'
    if domain == 'physical-states':
        return (f'- {row["id"]} — {row.get("description", "")} '
                f'({row.get("character", "")}, {row.get("category", "")})')
    return f'- {row["id"]} — {row.get("name", "")}'


def build_mapping_prompt(domain: str, ref_dir: str, batch: list[dict],
                         context: str = '') -> str:
    """Prompt asking what each unresolved reference in *batch* denotes.

    References are numbered so the answer names them by number: echoing a
    long sentence back verbatim is what failed when these were matched as
    aliases of a rebuilt registry.
    """
    noun = _DOMAIN_NOUN[domain]
    registry = [r for r in _read_csv(os.path.join(ref_dir, _DOMAIN_TO_REGISTRY[domain]))
                if r.get('id')]
    registry_text = '\n'.join(_registry_line(domain, r) for r in registry) or '(empty)'
    refs = []
    for i, ref in enumerate(batch, 1):
        text = f'{ref["type"]}:{ref["text"]}' if ref.get('type') else ref['text']
        used = ref['scenes'][:3]
        refs.append(f'{i}. {text}' + (f'  [scenes: {", ".join(used)}]' if used else ''))

    sections = [f'## {noun[0].upper() + noun[1:]} Registry\n\n{registry_text}']
    if domain == 'physical-states':
        chars = [r for r in _read_csv(os.path.join(ref_dir, 'characters.csv')) if r.get('id')]
        if chars:
            sections.append('## Character Registry\n\n' + '\n'.join(
                f'- {r["id"]} — {r.get("name", "")}' for r in chars))
    if context:
        sections.append(f'## Additional Context\n\n{context}')
    sections.append('## Unresolved References\n\n' + '\n'.join(refs))

    return f"""A novel's scene data refers to each {noun} by an id from its registry, but these references match no registry id, name, or alias. Decide what each one denotes.

{chr(10).join(s + chr(10) for s in sections)}
## Instructions

For each numbered reference, output exactly one line:

N | id
  the reference denotes this registry entry.

N | id1;id2
  the reference names several entries at once.

N | NEW | id | <fields>
  only when it denotes a {noun} the registry does not contain. A NEW id may be used by other lines too.

N | SKIP
  the reference is not a {noun} at all (a placeholder or noise).

Rules:
{_domain_rules(domain)}
- Map several references to one id when they denote the same {noun}; never declare a NEW id that is already in the registry

Output only these lines, one per reference, no other commentary."""


def parse_mapping_response(
    domain: str, response: str, batch_size: int, known_ids: set[str]
) -> tuple[dict[int, list[str]], list[dict[str, str]], set[int]]:
    """Parse ``N | id``, ``N | id1;id2``, ``N | NEW | id | …`` and ``N | SKIP``.

    Returns ``(mapping, new_rows, skipped)``: mapping is reference number →
    ids, new_rows are registry rows with the NEW fields filled (derived
    columns left to the caller), skipped the numbers answered SKIP. A line
    naming an id that is neither registered nor declared NEW is ignored, as is
    a number outside the batch. A NEW id that is already registered maps to
    that entry.
    """
    fields = _NEW_FIELDS[domain]
    known = {i.lower(): i for i in known_ids}
    lines = []
    for line in response.split('\n'):
        parts = [p.strip() for p in line.strip().lstrip('-* ').split('|')]
        num = parts[0].rstrip('.').strip()
        if len(parts) >= 2 and num.isdigit() and 1 <= int(num) <= batch_size:
            lines.append((int(num), parts[1:]))

    new_rows: list[dict[str, str]] = []
    for _num, parts in lines:
        if parts[0].upper() != 'NEW' or len(parts) < 3:
            continue
        rid = parts[1].strip().lower()
        if not rid or not parts[2] or rid in known:
            continue
        values = parts[2:2 + len(fields)]
        row = {'id': rid, **{f: (values[i] if i < len(values) else '') for i, f in enumerate(fields)}}
        known[rid] = rid
        new_rows.append(row)

    mapping: dict[int, list[str]] = {}
    skipped: set[int] = set()
    for num, parts in lines:
        head = parts[0]
        if head.upper() == 'SKIP':
            skipped.add(num)
            continue
        ids = [parts[1].strip()] if head.upper() == 'NEW' and len(parts) > 1 else head.split(';')
        ids = [i.strip().lower() for i in ids if i.strip()]
        if ids and all(i in known for i in ids):
            mapping[num] = [known[i] for i in ids]
    return mapping, new_rows, skipped


def _rewrite_targets(domain: str, ref_dir: str, mapping: dict[str, list[str]]) -> int:
    """Rewrite target fields through *mapping* (lookup key → ids), keeping
    MICE ``+``/``-`` prefixes. Returns the number of fields changed."""
    changed = 0
    for filename, columns in _DOMAIN_TARGETS[domain]:
        path = os.path.join(ref_dir, filename)
        rows = _read_csv(path)
        file_changed = 0
        for row in rows:
            for col in columns:
                old_val = row.get(col) or ''
                if not old_val:
                    continue
                out: list[str] = []
                for part in old_val.split(';'):
                    if not part.strip():
                        continue
                    ref = _reference_key(domain, part)
                    ids = mapping.get(ref[0]) if ref else None
                    if ids is None:
                        out.append(part.strip())
                    elif domain == 'mice-threads':
                        prefix = _split_mice(part)[0]
                        out += [prefix + i for i in ids]
                    else:
                        out += ids
                new_val = ';'.join(dict.fromkeys(out))
                if new_val != old_val:
                    row[col] = new_val
                    file_changed += 1
        if file_changed:
            _write_csv(path, rows, _FILE_MAP[filename])
            changed += file_changed
    return changed


def _first_scene_with(ref_dir: str, column: str, entry_id: str) -> str:
    briefs = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    for sid in _scene_order(ref_dir):
        if entry_id in (briefs.get(sid, {}).get(column) or '').split(';'):
            return sid
    return ''


def apply_mapping(domain: str, ref_dir: str, batch: list[dict],
                  mapping: dict[int, list[str]], new_rows: list[dict[str, str]]) -> int:
    """Apply one parsed batch: add NEW rows (derived columns filled), record
    single-id mappings as aliases, and rewrite the target fields. Returns the
    number of fields changed."""
    by_key = {batch[n - 1]['key']: ids for n, ids in mapping.items()}
    changed = _rewrite_targets(domain, ref_dir, by_key)

    registry = _read_csv(os.path.join(ref_dir, _DOMAIN_TO_REGISTRY[domain]))
    for row in new_rows:
        if domain == 'knowledge':
            row['aliases'] = ''
            row['origin'] = _first_scene_with(ref_dir, 'knowledge_out', row['id']) or 'backstory'
        elif domain == 'physical-states':
            row['acquired'] = (_first_scene_with(ref_dir, 'physical_state_out', row['id'])
                               or _first_scene_with(ref_dir, 'physical_state_in', row['id']))
            row['resolves'] = 'never'
        registry.append(row)

    # A reference mapped to one entry becomes its alias, so the next
    # extraction's spelling resolves without a call. Knowledge is the
    # exception: its references are sentences that won't recur verbatim, and
    # extraction prompts list the registry, so they would only bloat it.
    if 'aliases' in _REGISTRY_COLUMNS[domain] and domain != 'knowledge':
        rows_by_id = {r['id']: r for r in registry if r.get('id')}
        for n, ids in mapping.items():
            text = batch[n - 1]['text']
            row = rows_by_id.get(ids[0])
            if len(ids) != 1 or row is None or '|' in text:
                continue
            existing = {a.strip().lower() for a in (row.get('aliases') or '').split(';')}
            if text.lower() in existing | {row['id'].lower(), row.get('name', '').lower()}:
                continue
            row['aliases'] = ';'.join(a for a in [row.get('aliases', ''), text] if a)

    if new_rows or mapping:
        write_registry(ref_dir, domain, registry)
    return changed


def _invoke_batch(prompt: str, model: str, log_file: str, label: str) -> str | None:
    """One hone call. Returns the response text, or None when it was cut off
    at the token limit (a partial batch is never applied)."""
    from storyforge.api import invoke_to_file, extract_text_from_file, is_truncated
    response = invoke_to_file(prompt, model, log_file, max_tokens=_BATCH_MAX_TOKENS, label=label)
    if is_truncated(response):
        log(f'  WARNING: {label} hit the {_BATCH_MAX_TOKENS}-token limit; '
            f'its references are left unresolved')
        return None
    return extract_text_from_file(log_file)


def _report_remaining(domain: str, ref_dir: str, skipped: list[str]) -> int:
    remaining = find_unresolved(domain, ref_dir)
    skipped_keys = {s.lower() for s in skipped}
    left = [r for r in remaining if r.lower() not in skipped_keys]
    if skipped:
        log(f'  {domain}: {len(skipped)} reference(s) skipped as not a {_DOMAIN_NOUN[domain]}: '
            + '; '.join(skipped[:10]) + (f' (and {len(skipped) - 10} more)' if len(skipped) > 10 else ''))
    if left:
        log(f'  WARNING: {len(left)} {domain} reference(s) still unresolved: '
            + '; '.join(left[:10]) + (f' (and {len(left) - 10} more)' if len(left) > 10 else ''))
    shared = find_alias_collisions(domain, ref_dir) if domain != 'physical-states' else {}
    if shared:
        log(f'  WARNING: {len(shared)} {domain} alias(es) still shared: '
            + '; '.join(f'{a} ({", ".join(i)})' for a, i in shared.items()))
    return len(remaining)


# ============================================================================
# MICE operations: one open and at most one close per thread
# ============================================================================

def _mice_timelines(ref_dir: str) -> dict[str, list[tuple[str, str]]]:
    """Thread id → [(scene_id, '+' | '-' | ''), ...] in scene order."""
    intent = _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv'))
    timelines: dict[str, list[tuple[str, str]]] = {}
    for sid in _scene_order(ref_dir):
        for entry in (intent.get(sid, {}).get('mice_threads') or '').split(';'):
            prefix, _type, name = _split_mice(entry)
            if name:
                timelines.setdefault(name, []).append((sid, prefix))
    return timelines


def find_mice_anomalies(ref_dir: str) -> list[str]:
    """Threads opened more than once, closed more than once, or closed
    before (or without) being opened."""
    anomalous = []
    for thread, timeline in _mice_timelines(ref_dir).items():
        ops = [op for _sid, op in timeline if op]
        if (ops.count('+') > 1 or ops.count('-') > 1
                or ('-' in ops and ('+' not in ops or ops.index('-') < ops.index('+')))):
            anomalous.append(thread)
    return anomalous


def build_mice_operations_prompt(ref_dir: str, threads: list[str]) -> str:
    registry = _read_csv_as_map(os.path.join(ref_dir, 'mice-threads.csv'))
    functions = {sid: (row.get('function') or '').strip()[:100] for sid, row in
                 _read_csv_as_map(os.path.join(ref_dir, 'scene-intent.csv')).items()}
    timelines = _mice_timelines(ref_dir)
    blocks = []
    for thread in threads:
        entry = registry.get(thread, {})
        head = f'### {thread}' + (f' — {entry.get("name", "")} ({entry.get("type", "")})' if entry else '')
        lines = [f'  {sid}: {op or "mention"}    [function: {functions.get(sid, "")}]'
                 for sid, op in timelines.get(thread, [])]
        blocks.append(head + '\n' + '\n'.join(lines))
    return f"""These MICE threads in a novel are opened more than once, closed more than once, or closed before they open. Each is listed with every scene that touches it, in scene order, with the operation the scene currently records (+ open, - close, or a mention) and the scene's function.

{chr(10).join(blocks)}

## Instructions

Each thread opens exactly once, in the scene where it begins, and closes at most once, in the scene where it is actually resolved; judge both from the scene functions. Threads may interleave: never move a close to make threads nest.

For each thread, output exactly one line:

thread | open_scene | close_scene

Use UNCLOSED as close_scene when the thread is never resolved in the book. Both scenes must be scenes listed under the thread. Output only these lines, no other commentary."""


def parse_mice_operations_response(
    response: str, ref_dir: str, threads: list[str]
) -> dict[str, tuple[str, str]]:
    """Parse ``thread | open | close`` lines into thread → (open, close);
    close is ``''`` for UNCLOSED. A line naming a thread outside the batch,
    a scene that doesn't touch the thread, or a close before the open is
    ignored."""
    timelines = _mice_timelines(ref_dir)
    result = {}
    for line in response.split('\n'):
        parts = [p.strip() for p in line.strip().lstrip('-* ').split('|')]
        if len(parts) < 3 or parts[0] not in threads:
            continue
        sids = [sid for sid, _op in timelines.get(parts[0], [])]
        open_sid = parts[1]
        close_sid = '' if parts[2].upper() == 'UNCLOSED' else parts[2]
        if open_sid not in sids or (close_sid and (close_sid not in sids
                                                   or sids.index(close_sid) < sids.index(open_sid))):
            continue
        result[parts[0]] = (open_sid, close_sid)
    return result


def apply_mice_operations(ref_dir: str, decisions: dict[str, tuple[str, str]]) -> int:
    """Rewrite each decided thread: ``+`` at its open scene, ``-`` at its
    close scene (both, when it opens and closes in one scene), a bare
    mention everywhere else. Returns the number of fields changed."""
    if not decisions:
        return 0
    path = os.path.join(ref_dir, 'scene-intent.csv')
    rows = _read_csv(path)
    changed = 0
    for row in rows:
        old_val = row.get('mice_threads') or ''
        out = []
        for entry in old_val.split(';'):
            if not entry.strip():
                continue
            _prefix, _type, name = _split_mice(entry)
            if name not in decisions:
                out.append(entry.strip())
                continue
            open_sid, close_sid = decisions[name]
            ops = [op for op, sid in (('+', open_sid), ('-', close_sid)) if sid == row.get('id')]
            out += [op + name for op in ops] or [name]
        new_val = ';'.join(dict.fromkeys(out))
        if new_val != old_val:
            row['mice_threads'] = new_val
            changed += 1
    if changed:
        _write_csv(path, rows, _FILE_MAP['scene-intent.csv'])
    return changed


def reconcile_mice_operations(ref_dir: str, model: str, log_dir: str) -> tuple[int, int]:
    """Decide the open and close of each anomalous thread, in batches.

    No call when no thread is anomalous. Returns (fields changed, calls made).
    """
    threads = find_mice_anomalies(ref_dir)
    changed = 0
    n = 0
    for n, start in enumerate(range(0, len(threads), _BATCH_SIZE), 1):
        batch = threads[start:start + _BATCH_SIZE]
        log(f'  mice-threads: deciding opens and closes for {len(batch)} thread(s)')
        text = _invoke_batch(build_mice_operations_prompt(ref_dir, batch), model,
                             os.path.join(log_dir, f'reconcile-mice-threads-ops-{n}.json'),
                             f'hone registries/mice-threads operations (batch {n})')
        if text is not None:
            changed += apply_mice_operations(
                ref_dir, parse_mice_operations_response(text, ref_dir, batch))
    remaining = find_mice_anomalies(ref_dir)
    if remaining:
        log(f'  WARNING: {len(remaining)} MICE thread(s) still opened or closed '
            f'more than once: {"; ".join(remaining[:10])}')
    return changed, n


# ============================================================================
# Full domain reconciliation
# ============================================================================

def reconcile_domain(
    domain: str, ref_dir: str, model: str, log_dir: str,
    context: str = ''
) -> dict:
    """Reconcile one domain's registry with the scene data, by deltas.

    Shared aliases are resolved and every resolvable reference normalized to
    its id in code; the references left over go to the model in numbered
    batches (see :func:`build_mapping_prompt`), each applied before the next.
    For MICE threads, threads with anomalous operations are then decided per
    thread. A project with nothing unresolved makes no call.

    Args:
        domain: One of 'characters', 'locations', 'values',
                'mice-threads', 'knowledge', 'physical-states', or 'outcomes'.
        ref_dir: Path to the reference/ directory.
        model: Anthropic model ID for the API calls.
        log_dir: Directory for API log files.
        context: Optional extra context for the prompt (the character bible).

    Returns:
        Dict with keys: registry_entries, references_mapped,
        fields_normalized, unresolved, calls.
    """
    # Outcomes are deterministic — no API call needed
    if domain == 'outcomes':
        changed = reconcile_outcomes(ref_dir)
        return {'registry_entries': 0, 'references_mapped': 0,
                'fields_normalized': changed, 'unresolved': 0, 'calls': 0}

    if domain not in _DOMAIN_TO_REGISTRY:
        raise ValueError(f'Unknown reconciliation domain: {domain}')

    os.makedirs(log_dir, exist_ok=True)
    if domain != 'physical-states':
        resolve_alias_collisions(domain, ref_dir)
    fields_normalized = apply_registry_normalization(domain, ref_dir)

    unresolved = list(_unresolved_references(domain, ref_dir).values())
    batches = [unresolved[i:i + _BATCH_SIZE] for i in range(0, len(unresolved), _BATCH_SIZE)]
    if unresolved:
        log(f'  {domain}: {len(unresolved)} unresolved reference(s) in '
            f'{len(batches)} batch(es)')
    mapped = 0
    calls = 0
    skipped: list[str] = []
    for n, batch in enumerate(batches, 1):
        # An earlier batch's new entries or aliases may already resolve some
        lookup = _registry_lookup(domain, ref_dir)
        batch = [r for r in batch if r['key'] not in lookup]
        if not batch:
            continue
        label = f'hone registries/{domain} (batch {n} of {len(batches)})'
        text = _invoke_batch(build_mapping_prompt(domain, ref_dir, batch, context=context),
                             model, os.path.join(log_dir, f'reconcile-{domain}-{n}.json'), label)
        calls += 1
        if text is None:
            continue
        known = set(lookup.values())
        mapping, new_rows, skip = parse_mapping_response(domain, text, len(batch), known)
        fields_normalized += apply_mapping(domain, ref_dir, batch, mapping, new_rows)
        mapped += len(mapping)
        skipped += [batch[i - 1]['text'] for i in sorted(skip)]

    fields_normalized += apply_registry_normalization(domain, ref_dir)
    if domain == 'mice-threads':
        # Repeated opens of an already-open thread are mentions
        from storyforge.extract import cleanup_mice_threads
        fields_normalized += len(cleanup_mice_threads(ref_dir))
        ops_changed, ops_calls = reconcile_mice_operations(ref_dir, model, log_dir)
        fields_normalized += ops_changed
        calls += ops_calls

    remaining = _report_remaining(domain, ref_dir, skipped)
    registry = _read_csv(os.path.join(ref_dir, _DOMAIN_TO_REGISTRY[domain]))
    return {
        'registry_entries': len(registry),
        'references_mapped': mapped,
        'fields_normalized': fields_normalized,
        'unresolved': remaining,
        'calls': calls,
    }


# ============================================================================
# Briefs domain: abstract language detection
# ============================================================================

ABSTRACT_INDICATORS = {
    'realizes', 'recognizes', 'connects', 'crystallizes', 'deepens',
    'builds', 'grows', 'shifts', 'transforms', 'emerges', 'settles',
    'dawns', 'unfolds', 'intensifies', 'resolves', 'strengthens',
    'the realization', 'the parallel', 'the tension', 'the connection',
    'the weight of', 'the cost of', 'the truth of', 'the meaning of',
    'beginning to', 'starting to', 'learning to',
}

CONCRETE_INDICATORS = {
    'hands', 'eyes', 'door', 'walks', 'picks up', 'sets down',
    'turns', 'stops', 'reaches', 'holds', 'drops', 'pulls',
    'sits', 'stands', 'crosses', 'opens', 'closes', 'looks',
    'says', 'asks', 'watches', 'hears', 'smells', 'tastes',
    'runs', 'steps', 'grabs', 'pushes', 'carries', 'presses',
}

_CONCRETIZABLE_FIELDS = ['key_actions', 'crisis', 'decision', 'goal', 'conflict', 'emotions']

OBSERVATION_INDICATORS = {
    'notices', 'observes', 'discovers', 'reflects', 'grapples with',
    'contemplates', 'realizes', 'wonders', 'considers', 'processes',
    'absorbs', 'witnesses', 'watches', 'senses', 'recognizes',
    'comes to understand', 'begins to see', 'takes in',
}

OPPOSITION_INDICATORS = {
    'refuses', 'blocks', 'demands', 'threatens', 'confronts', 'denies',
    'challenges', 'prevents', 'forbids', 'attacks', 'rejects', 'opposes',
    'locks', 'traps', 'forces', 'resists', 'fights', 'argues',
    'interrupts', 'undermines', 'betrays', 'withholds', 'hides',
}

_FLAT_SHIFTS = {'+/+', '-/-', '0/0', ''}


def detect_abstract_fields(
    briefs_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Scan brief fields for abstract/thematic language.

    Args:
        briefs_map: dict keyed by scene ID, values are brief row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field, value, abstract_count, concrete_count, issue: 'abstract'}.
        Only returns fields where abstract_count >= 2 and abstract_count > concrete_count.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(briefs_map.keys())

    for sid in ids_to_check:
        brief = briefs_map.get(sid, {})
        for field in _CONCRETIZABLE_FIELDS:
            value = brief.get(field, '').strip()
            if not value:
                continue

            value_lower = value.lower()
            abstract_count = sum(1 for ind in ABSTRACT_INDICATORS if ind in value_lower)
            concrete_count = sum(1 for ind in CONCRETE_INDICATORS if ind in value_lower)

            if abstract_count >= 2 and abstract_count > concrete_count:
                results.append({
                    'scene_id': sid,
                    'field': field,
                    'value': value,
                    'abstract_count': abstract_count,
                    'concrete_count': concrete_count,
                    'issue': 'abstract',
                })

    return results


# ============================================================================
# Briefs domain: over-specification detection
# ============================================================================

# Beats per 1000 words — above this threshold the scene is over-specified.
# 3 beats in 1500 words = 2.0/1k is fine. 5 in 1500 = 3.3/1k is tight.
# We flag above 2.5/1k, which catches 5+ beats in short scenes.
_BEATS_PER_1K_THRESHOLD = 2.5

# Absolute beat count threshold — flag regardless of word count.
_MAX_BEATS_ABSOLUTE = 6

# Max emotional beats before arc feels mechanical.
_MAX_EMOTION_BEATS = 3


def detect_overspecified(
    briefs_map: dict[str, dict[str, str]],
    scenes_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect scenes where beat counts are too high for the target word count.

    Checks key_actions beat count against target_words, and emotions beat count.

    Args:
        briefs_map: dict keyed by scene ID, values are brief row dicts.
        scenes_map: dict keyed by scene ID, values are scene metadata dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field, value, beat_count, target_words,
                        beats_per_1k, issue: 'overspecified'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(briefs_map.keys())

    for sid in ids_to_check:
        brief = briefs_map.get(sid, {})
        scene = scenes_map.get(sid, {})
        target_words = int(scene.get('target_words', '0') or '0')

        # Check key_actions
        ka = brief.get('key_actions', '').strip()
        if ka:
            beats = [b.strip() for b in ka.split(';') if b.strip()]
            beat_count = len(beats)
            beats_per_1k = (beat_count / target_words * 1000) if target_words else 0

            flagged = False
            if beat_count >= _MAX_BEATS_ABSOLUTE:
                flagged = True
            elif target_words and beat_count > 2 and beats_per_1k > _BEATS_PER_1K_THRESHOLD:
                flagged = True

            if flagged:
                results.append({
                    'scene_id': sid,
                    'field': 'key_actions',
                    'value': ka,
                    'beat_count': beat_count,
                    'target_words': target_words,
                    'beats_per_1k': round(beats_per_1k, 2),
                    'issue': 'overspecified',
                })

        # Check emotions
        emotions = brief.get('emotions', '').strip()
        if emotions:
            beats = [b.strip() for b in emotions.split(';') if b.strip()]
            beat_count = len(beats)
            if beat_count > _MAX_EMOTION_BEATS:
                results.append({
                    'scene_id': sid,
                    'field': 'emotions',
                    'value': emotions,
                    'beat_count': beat_count,
                    'target_words': target_words,
                    'beats_per_1k': 0,
                    'issue': 'overspecified',
                })

    return results


# ============================================================================
# Briefs domain: verbose/prose-like field detection
# ============================================================================

# Fields that should be terse (beat lists or short phrases).
_TERSE_FIELDS = {
    'key_actions': 200,    # max chars — beats should be verb phrases
    'emotions': 60,        # max chars — short labels
    'goal': 80,            # max chars — one dramatic question
    'conflict': 80,        # max chars — one tension statement
}

# Fields where sentences/paragraphs indicate extraction bloat.
_PROSE_FIELDS = {
    'decision': 80,        # max chars — one action choice
    'crisis': 100,         # max chars — one dilemma
    'subtext': 150,        # max chars — directive, not a paragraph
}

# Prose indicators: patterns that suggest the field became a paragraph.
_PROSE_PATTERNS = re.compile(
    r'(?:'
    r'\. [A-Z]'           # sentence boundary (period + capital)
    r'|—\s*[a-z]'        # em-dash clause continuation
    r'|\b(?:she|he|they|her|his|their)\b.*\b(?:she|he|they|her|his|their)\b'
                          # multiple pronoun references = narrative
    r')',
)


def detect_verbose_fields(
    briefs_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect fields that are too long or prose-like for their purpose.

    This catches extraction artifacts where fields become paragraph summaries
    instead of terse beat lists or short phrases.

    Args:
        briefs_map: dict keyed by scene ID, values are brief row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field, value, char_count, max_chars,
                        sentence_count, issue: 'verbose'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(briefs_map.keys())

    all_fields = dict(_TERSE_FIELDS)
    all_fields.update(_PROSE_FIELDS)

    for sid in ids_to_check:
        brief = briefs_map.get(sid, {})
        for field, max_chars in all_fields.items():
            value = brief.get(field, '').strip()
            if not value:
                continue

            char_count = len(value)
            # Count sentences: period-space-capital or end-of-string after period
            sentence_count = len(re.findall(r'\. [A-Z]', value)) + 1
            has_prose = bool(_PROSE_PATTERNS.search(value))

            flagged = False
            if char_count > max_chars:
                flagged = True
            elif has_prose and sentence_count >= 3 and char_count > max_chars * 0.6:
                # Multiple sentences with prose patterns, but only if
                # approaching the length limit — short punchy sentences
                # like "She stops. Names them. Go." are fine.
                flagged = True

            if flagged:
                results.append({
                    'scene_id': sid,
                    'field': field,
                    'value': value,
                    'char_count': char_count,
                    'max_chars': max_chars,
                    'sentence_count': sentence_count,
                    'issue': 'verbose',
                })

    return results


# ============================================================================
# Briefs domain: conflict-free detection
# ============================================================================

def detect_conflict_free(
    briefs_map: dict[str, dict[str, str]],
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect scenes whose conflict field lacks actual opposition.

    Two checks are applied:
    - **Keyword**: the conflict text contains observation words (notices, realizes…)
      but zero opposition words (refuses, blocks…) → reason='keyword'.
    - **Structural**: the scene's outcome=='yes' AND value_shift is flat (+/+, -/-, 0/0,
      or empty) → reason='structural'.
    - When both checks trigger → reason='both'.

    Empty conflict fields are skipped (that's a gap, not a conflict-free issue).

    Args:
        briefs_map: dict keyed by scene ID, values are brief row dicts.
        intent_map: dict keyed by scene ID, values are scene-intent row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts:
          {scene_id, field: 'conflict', value, issue: 'conflict_free',
           reason: 'keyword'|'structural'|'both',
           observation_count, opposition_count}
        plus 'outcome' and 'value_shift' when the structural check contributed.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(briefs_map.keys())

    for sid in ids_to_check:
        brief = briefs_map.get(sid, {})
        conflict = brief.get('conflict', '').strip()
        if not conflict:
            continue

        conflict_lower = conflict.lower()

        # Keyword check
        observation_count = sum(1 for ind in OBSERVATION_INDICATORS if ind in conflict_lower)
        opposition_count = sum(1 for ind in OPPOSITION_INDICATORS if ind in conflict_lower)
        keyword_flagged = observation_count > 0 and opposition_count == 0

        # Structural check
        intent_row = intent_map.get(sid, {})
        outcome = brief.get('outcome', '').strip().lower()
        value_shift = intent_row.get('value_shift', '').strip()
        structural_flagged = outcome == 'yes' and value_shift in _FLAT_SHIFTS

        if not keyword_flagged and not structural_flagged:
            continue

        if keyword_flagged and structural_flagged:
            reason = 'both'
        elif keyword_flagged:
            reason = 'keyword'
        else:
            reason = 'structural'

        entry: dict = {
            'scene_id': sid,
            'field': 'conflict',
            'value': conflict,
            'issue': 'conflict_free',
            'reason': reason,
            'observation_count': observation_count,
            'opposition_count': opposition_count,
        }
        if structural_flagged or reason == 'both':
            entry['outcome'] = outcome
            entry['value_shift'] = value_shift

        results.append(entry)

    return results


# ============================================================================
# Briefs domain: combined detection
# ============================================================================

def detect_brief_issues(
    briefs_map: dict[str, dict[str, str]],
    scenes_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
    intent_map: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Run all brief quality detectors and return combined results.

    Each result dict includes an 'issue' key: 'abstract', 'overspecified',
    'verbose', or 'conflict_free'.

    Args:
        briefs_map: dict keyed by scene ID.
        scenes_map: dict keyed by scene ID (needed for target_words).
        scene_ids: Optional scope.
        intent_map: Optional dict keyed by scene ID (scene-intent rows). When
            provided, also runs conflict-free detection.

    Returns:
        Combined list of all issue dicts, sorted by scene_id then field.
    """
    issues = []
    issues.extend(detect_abstract_fields(briefs_map, scene_ids))
    issues.extend(detect_overspecified(briefs_map, scenes_map, scene_ids))
    issues.extend(detect_verbose_fields(briefs_map, scene_ids))
    if intent_map is not None:
        issues.extend(detect_conflict_free(briefs_map, intent_map, scene_ids))
    issues.sort(key=lambda d: (d['scene_id'], d['field'], d['issue']))
    return issues


# ============================================================================
# Briefs domain: graphic-novel diagnostics
# ============================================================================

def _diagnose_gn_briefs(project_dir: str, briefs_rows: list[dict]) -> list[dict]:
    """Return findings for graphic-novel-specific brief gaps.

    Checks:
      - panel_breakdown must be non-empty on every briefed scene
      - page_layout must be non-empty on every briefed scene
    """
    findings = []
    for row in briefs_rows:
        scene_id = row.get('id', '')
        if not (row.get('panel_breakdown') or '').strip():
            findings.append({
                'scene_id': scene_id,
                'field': 'panel_breakdown',
                'severity': 'high',
                'message': 'panel_breakdown is empty — graphic-novel briefs must specify per-page panel structure',
                'fix_location': 'brief',
                'issue': 'gn_missing_field',
            })
        if not (row.get('page_layout') or '').strip():
            findings.append({
                'scene_id': scene_id,
                'field': 'page_layout',
                'severity': 'medium',
                'message': 'page_layout intent is empty — describe the rhythm of this scene',
                'fix_location': 'brief',
                'issue': 'gn_missing_field',
            })
    return findings


def diagnose_briefs(project_dir: str) -> list[dict]:
    """Run all brief quality diagnostics and return findings.

    This is the public entrypoint for brief diagnostics. It loads briefs from
    the project's reference directory, runs all existing quality detectors
    (abstract language, overspecification, verbose fields, conflict-free), and
    for graphic-novel projects also runs GN-specific checks (panel_breakdown,
    page_layout).

    Args:
        project_dir: Path to the project root directory.

    Returns:
        List of finding dicts, each containing at minimum 'scene_id', 'field',
        and 'issue' keys. Additional keys depend on the detector.
    """
    from storyforge.common import get_medium
    from storyforge.elaborate import _read_csv, _read_csv_as_map

    ref_dir = os.path.join(project_dir, 'reference')
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')

    if not os.path.isfile(briefs_path):
        return []

    briefs_rows = _read_csv(briefs_path)
    briefs_map = {r['id']: r for r in briefs_rows if r.get('id')}
    scenes_map = _read_csv_as_map(scenes_path) if os.path.isfile(scenes_path) else {}
    intent_map = (_read_csv_as_map(intent_path)
                  if os.path.isfile(intent_path) else None)

    findings = list(detect_brief_issues(briefs_map, scenes_map, intent_map=intent_map))

    medium = get_medium(project_dir)
    if medium == 'graphic-novel':
        findings.extend(_diagnose_gn_briefs(project_dir, briefs_rows))

    return findings


# ============================================================================
# Briefs domain: concretization prompt builder and parser
# ============================================================================

def build_concretize_prompt(
    scene_id: str,
    fields: list[str],
    current_values: dict[str, str],
    voice_guide: str = '',
    character_entry: str = '',
) -> str:
    """Build prompt to rewrite abstract brief fields as concrete physical beats.

    Args:
        scene_id: The scene being concretized.
        fields: List of field names to rewrite.
        current_values: Dict of field_name -> current value.
        voice_guide: Excerpt from the voice guide (POV character's sensory palette).
        character_entry: Character bible entry for the POV character.

    Returns:
        Prompt string for Claude.
    """
    field_block = '\n'.join(
        f"**{field}:** {current_values.get(field, '')}"
        for field in fields
    )

    field_output = '\n'.join(f'{field}: [rewritten value]' for field in fields)

    return f"""Rewrite these scene brief fields so every item is something the POV character physically does or perceives.

## Scene: {scene_id}

## Current Values (abstract — need rewriting)
{field_block}

## Voice Guide (POV character)
{voice_guide if voice_guide else '(not available)'}

## Character
{character_entry if character_entry else '(not available)'}

## Rules

1. Every action must be something the POV character physically does or perceives through their senses. No thematic descriptions, no narrator interpretations, no emotion names as events.
2. Replace "the realization building" with what the character DOES when they realize something (hands stop, breath catches, they set something down).
3. Replace "tension deepening" with what the character SEES or FEELS (someone's jaw tightening, the room going quiet, a hand moving to a weapon).
4. Replace "connecting X to Y" with the physical moment: what does the character look at, touch, or say when the connection happens?
5. Keep the same number of beats (semicolon-separated items). Don't add or remove story events — just rewrite HOW they're described.
6. Use the character's sensory palette from the voice guide. If they think in food metaphors, their observations should reflect that.

## Output Format

Return each field on its own labeled line, exactly like the input but rewritten:

{field_output}

No explanation. No markdown. Just the labeled lines."""


def build_trim_prompt(
    scene_id: str,
    issues: list[dict],
    current_values: dict[str, str],
    target_words: int = 0,
) -> str:
    """Build prompt to trim overspecified/verbose brief fields.

    Handles both overspecified (too many beats) and verbose (too long)
    fields in a single prompt per scene.
    """
    field_blocks = []
    for issue in issues:
        field = issue['field']
        value = current_values.get(field, '')
        if not value:
            continue
        if issue['issue'] == 'overspecified':
            beats = len([b for b in value.split(';') if b.strip()])
            if field == 'emotions':
                field_blocks.append(
                    f"**{field}** (overspecified: {beats} beats, max 3):\n"
                    f"{value}\n"
                    f"→ Reduce to 2 beats: start state and end state. "
                    f"The drafter finds the middle ground."
                )
            else:
                max_beats = max(2, int(target_words / 800)) if target_words else 3
                field_blocks.append(
                    f"**{field}** (overspecified: {beats} beats, target {max_beats} for {target_words}w scene):\n"
                    f"{value}\n"
                    f"→ Reduce to {max_beats} beats. Keep only the structurally essential "
                    f"events. Cut beats that the drafter can infer from context."
                )
        elif issue['issue'] == 'verbose':
            max_chars = issue.get('max_chars', 80)
            field_blocks.append(
                f"**{field}** (verbose: {len(value)} chars, max {max_chars}):\n"
                f"{value}\n"
                f"→ Condense to under {max_chars} characters. One phrase, not a paragraph. "
                f"Cut prose-style elaboration — keep only the core action or choice."
            )

    if not field_blocks:
        return ''

    field_output = '\n'.join(
        f'{issue["field"]}: [trimmed value]' for issue in issues
        if current_values.get(issue['field'])
    )

    return f"""Trim these scene brief fields to be terse and directive.

## Scene: {scene_id}

## Fields to Trim

{chr(10).join(field_blocks)}

## Rules

1. For key_actions: keep only beats where story events CHANGE — entrances, decisions, revelations. Cut transitions, reactions, and beats the drafter will naturally produce from context.
2. For emotions: use 2 beats maximum (start → end). "resolve;bitter-defiance" not "resolve;frustration;bitter-resignation;quiet-defiance".
3. For decision/crisis/goal/conflict: one clause. No sentences, no em-dashes, no elaboration.
4. Preserve the MEANING — just say it in fewer words.

## Output Format

Return each field on its own labeled line:

{field_output}

No explanation. No markdown. Just the labeled lines."""


def parse_concretize_response(
    response: str, scene_id: str, fields: list[str]
) -> dict[str, str]:
    """Parse concretization/trim response into field values.

    Returns:
        Dict mapping field_name -> rewritten value.
    """
    result = {}
    for line in response.split('\n'):
        line = line.strip()
        if not line:
            continue
        for field in fields:
            prefix = f'{field}:'
            if line.lower().startswith(prefix.lower()):
                value = line[len(prefix):].strip()
                if value:
                    result[field] = value
                break
    return result


# ============================================================================
# External findings loader
# ============================================================================

def load_external_findings(findings_file: str) -> list[dict]:
    """Load external evaluation findings from a pipe-delimited CSV file.

    Expected columns: scene_id|target_file|fields|guidance

    When ``fields`` contains semicolon-separated values (e.g. "goal;conflict"),
    one issue dict is created per field.  When ``fields`` is empty, a single
    issue dict with ``field=''`` is created.

    Args:
        findings_file: Path to the findings CSV file.

    Returns:
        List of dicts: {scene_id, field, target_file, guidance, issue: 'evaluation'}.
        Returns [] if the file does not exist.
    """
    if not os.path.isfile(findings_file):
        return []
    # Strip \r for CRLF safety
    with open(findings_file, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    results = []
    reader = csv.DictReader(raw.splitlines(), delimiter='|')
    for row in reader:
        sid = row.get('scene_id', '').strip()
        target_file = row.get('target_file', '').strip()
        fields_raw = row.get('fields', '').strip()
        guidance = row.get('guidance', '').strip()
        if not sid:
            continue
        if fields_raw:
            for field in fields_raw.split(';'):
                field = field.strip()
                if field:
                    results.append({
                        'scene_id': sid, 'field': field,
                        'target_file': target_file,
                        'guidance': guidance, 'issue': 'evaluation',
                    })
        else:
            results.append({
                'scene_id': sid, 'field': '',
                'target_file': target_file,
                'guidance': guidance, 'issue': 'evaluation',
            })
    return results


def build_evaluation_fix_prompt(
    scene_id: str,
    fields: list[str],
    current_values: dict[str, str],
    guidance: str,
    voice_guide: str = '',
    character_entry: str = '',
) -> str:
    """Build prompt to rewrite brief fields based on evaluation findings.

    The output format matches ``build_concretize_prompt`` so it is parseable
    by the existing ``parse_concretize_response()``.

    Args:
        scene_id: The scene being fixed.
        fields: List of field names to rewrite.
        current_values: Dict of field_name -> current value.
        guidance: Evaluation guidance text describing what to fix.
        voice_guide: Excerpt from the voice guide (truncated externally to 3000 chars).
        character_entry: Character bible entry (truncated externally to 2000 chars).

    Returns:
        Prompt string for Claude.
    """
    field_block = '\n'.join(
        f"**{field}:** {current_values.get(field, '')}"
        for field in fields
    ) if fields else '(no specific fields flagged)'

    field_output = '\n'.join(f'{field}: [rewritten value]' for field in fields)

    return f"""Rewrite these scene brief fields to address the evaluation findings below.

## Scene: {scene_id}

## Evaluation Findings
{guidance}

## Current Field Values
{field_block}

## Voice Guide (POV character)
{voice_guide if voice_guide else '(not available)'}

## Character
{character_entry if character_entry else '(not available)'}

## Rules

1. Address the evaluation guidance directly — fix the specific problems identified.
2. Every action must be something the POV character physically does or perceives. No thematic descriptions, no narrator interpretations.
3. Do not invent characters, locations, or events not implied by the existing fields.
4. Keep each field concise — brief contract language, not prose.

## Output Format

Return each field on its own labeled line:

{field_output}

No explanation. No markdown. Just the labeled lines."""


# ============================================================================
# Briefs domain: hone_briefs
# ============================================================================

def hone_briefs(
    ref_dir: str,
    project_dir: str,
    scene_ids: list[str] | None = None,
    threshold: float = 3.5,
    model: str = '',
    log_dir: str = '',
    coaching_level: str = 'full',
    dry_run: bool = False,
    findings_file: str | None = None,
) -> dict:
    """Concretize abstract brief fields as concrete physical beats.

    Args:
        ref_dir: Path to reference/ directory.
        project_dir: Path to project root.
        scene_ids: Optional list of scene IDs to check. If None, check all.
        threshold: prose_naturalness score threshold (scenes below this are flagged).
        model: Anthropic model ID for API calls.
        log_dir: Directory for API log files.
        coaching_level: full/coach/strict.
        dry_run: If True, detect but don't rewrite.
        findings_file: Optional path to a pipe-delimited CSV of external evaluation
            findings (scene_id|target_file|fields|guidance).  Findings targeting
            scene-briefs.csv are merged into all_issues before processing.

    Returns:
        Dict with scenes_flagged, scenes_rewritten, fields_rewritten.
    """
    briefs_map = _read_csv_as_map(os.path.join(ref_dir, 'scene-briefs.csv'))
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    intent_map = _read_csv_as_map(intent_path) if os.path.isfile(intent_path) else None

    # Detect all issue types
    all_issues = detect_brief_issues(briefs_map, scenes_map, scene_ids, intent_map=intent_map)

    # Merge external findings if provided
    if findings_file:
        external = load_external_findings(findings_file)
        external_briefs = [e for e in external if e.get('target_file', '') == 'scene-briefs.csv']
        existing_keys = {(i['scene_id'], i['field']) for i in all_issues}
        for ext in external_briefs:
            if ext['field'] and (ext['scene_id'], ext['field']) not in existing_keys:
                all_issues.append(ext)
            elif ext['field']:
                # Replace detected issue with external (has guidance)
                all_issues = [i for i in all_issues
                              if not (i['scene_id'] == ext['scene_id'] and i['field'] == ext['field'])]
                all_issues.append(ext)
            elif not ext['field']:
                all_issues.append(ext)

    if dry_run or not all_issues:
        return {
            'scenes_flagged': len(set(f['scene_id'] for f in all_issues)),
            'scenes_rewritten': 0,
            'fields_rewritten': 0,
        }

    if coaching_level == 'strict':
        # Save analysis only
        hone_dir = os.path.join(project_dir, 'working', 'hone')
        os.makedirs(hone_dir, exist_ok=True)
        for f in all_issues:
            path = os.path.join(hone_dir, f'briefs-analysis-{f["scene_id"]}.md')
            with open(path, 'a') as fh:
                fh.write(f"**{f['field']}:** {f['issue']}\n")
                if 'value' in f:
                    fh.write(f"  Current: {f['value'][:200]}\n")
        return {
            'scenes_flagged': len(set(f['scene_id'] for f in all_issues)),
            'scenes_rewritten': 0,
            'fields_rewritten': 0,
        }

    # Load voice guide and character bible for prompt building
    voice_guide = ''
    voice_path = os.path.join(ref_dir, 'voice-guide.md')
    if os.path.isfile(voice_path):
        with open(voice_path, encoding='utf-8') as fh:
            voice_guide = fh.read()

    char_bible = ''
    char_path = os.path.join(ref_dir, 'character-bible.md')
    if os.path.isfile(char_path):
        with open(char_path, encoding='utf-8') as fh:
            char_bible = fh.read()

    from storyforge.api import invoke_to_file, extract_text_from_file

    # Group issues by scene and separate by type
    by_scene: dict[str, list[dict]] = {}
    for issue in all_issues:
        by_scene.setdefault(issue['scene_id'], []).append(issue)

    scenes_rewritten = 0
    fields_rewritten = 0
    total_scenes = len(by_scene)

    for idx, (sid, issues) in enumerate(by_scene.items(), 1):
        if sid not in briefs_map:
            log(f'  [{idx}/{total_scenes}] WARNING: "{sid}" is not a valid scene ID in scene-briefs.csv — skipping')
            continue
        abstract_issues = [i for i in issues if i['issue'] == 'abstract']
        trim_issues = [i for i in issues if i['issue'] in ('overspecified', 'verbose')]
        issue_types = sorted(set(i['issue'] for i in issues))
        log(f'  [{idx}/{total_scenes}] {sid} ({", ".join(issue_types)})')

        # Handle abstract issues with concretization prompt
        if abstract_issues and coaching_level == 'full':
            abstract_fields = list(set(i['field'] for i in abstract_issues))
            current_values = {f: briefs_map[sid].get(f, '') for f in abstract_fields}

            prompt = build_concretize_prompt(
                scene_id=sid,
                fields=abstract_fields,
                current_values=current_values,
                voice_guide=voice_guide[:3000],
                character_entry=char_bible[:2000],
            )

            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f'hone-abstract-{sid}.json')
            invoke_to_file(prompt, model, log_file, max_tokens=2048,
                           label=f'hone abstract {idx}/{total_scenes} ({sid})')
            response = extract_text_from_file(log_file)

            rewrites = parse_concretize_response(response, sid, abstract_fields)
            for field, new_value in rewrites.items():
                if new_value and new_value != current_values.get(field):
                    briefs_map[sid][field] = new_value
                    fields_rewritten += 1

        # Handle overspecified/verbose issues with trim prompt
        if trim_issues and coaching_level == 'full':
            trim_fields = list(set(i['field'] for i in trim_issues))
            current_values = {f: briefs_map[sid].get(f, '') for f in trim_fields}
            target_words = int(scenes_map.get(sid, {}).get('target_words', '0') or '0')

            prompt = build_trim_prompt(
                scene_id=sid,
                issues=trim_issues,
                current_values=current_values,
                target_words=target_words,
            )

            if prompt:
                os.makedirs(log_dir, exist_ok=True)
                log_file = os.path.join(log_dir, f'hone-trim-{sid}.json')
                invoke_to_file(prompt, model, log_file, max_tokens=2048,
                               label=f'hone trim {idx}/{total_scenes} ({sid})')
                response = extract_text_from_file(log_file)

                rewrites = parse_concretize_response(response, sid, trim_fields)
                for field, new_value in rewrites.items():
                    if new_value and new_value != current_values.get(field):
                        briefs_map[sid][field] = new_value
                        fields_rewritten += 1

        # Handle evaluation issues (from external findings)
        eval_issues = [i for i in issues if i['issue'] == 'evaluation']
        if eval_issues and coaching_level == 'full':
            eval_fields = list(set(i['field'] for i in eval_issues if i['field']))
            if not eval_fields:
                eval_fields = [f for f in briefs_map[sid].keys() if f != 'id' and briefs_map[sid].get(f, '')]
            current_values = {f: briefs_map[sid].get(f, '') for f in eval_fields}
            guidance = '; '.join(i.get('guidance', '') for i in eval_issues if i.get('guidance'))

            prompt = build_evaluation_fix_prompt(
                scene_id=sid,
                fields=eval_fields,
                current_values=current_values,
                guidance=guidance,
                voice_guide=voice_guide[:3000],
                character_entry=char_bible[:2000],
            )

            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f'hone-eval-{sid}.json')
            invoke_to_file(prompt, model, log_file, max_tokens=2048,
                           label=f'hone eval {idx}/{total_scenes} ({sid})')
            response = extract_text_from_file(log_file)

            rewrites = parse_concretize_response(response, sid, eval_fields)
            for field, new_value in rewrites.items():
                if new_value and new_value != current_values.get(field):
                    briefs_map[sid][field] = new_value
                    fields_rewritten += 1

        # Coach mode: save proposals for all issue types
        if coaching_level == 'coach':
            hone_dir = os.path.join(project_dir, 'working', 'hone')
            os.makedirs(hone_dir, exist_ok=True)
            proposal_path = os.path.join(hone_dir, f'briefs-{sid}.md')
            with open(proposal_path, 'w') as fh:
                fh.write(f"# Brief Quality Proposals: {sid}\n\n")
                for issue in issues:
                    fh.write(f"## {issue['field']} — {issue['issue']}\n")
                    if 'value' in issue:
                        fh.write(f"**Current:** {issue['value'][:300]}\n\n")
            continue

        if abstract_issues or trim_issues or eval_issues:
            scenes_rewritten += 1

    # Write back if any changes were made
    if fields_rewritten > 0:
        briefs_rows = list(briefs_map.values())
        briefs_rows.sort(key=lambda r: r.get('id', ''))
        _write_csv(
            os.path.join(ref_dir, 'scene-briefs.csv'),
            briefs_rows,
            _FILE_MAP['scene-briefs.csv'],
        )

    return {
        'scenes_flagged': len(by_scene),
        'scenes_rewritten': scenes_rewritten,
        'fields_rewritten': fields_rewritten,
    }


# ============================================================================
# Gaps domain: detect missing fields
# ============================================================================

_GAPS_REQUIRED = {
    'briefed': [
        'function', 'value_at_stake', 'value_shift', 'emotional_arc',
        'goal', 'conflict', 'outcome', 'crisis', 'decision',
    ],
    'drafted': [
        'function', 'value_at_stake', 'value_shift', 'emotional_arc',
        'goal', 'conflict', 'outcome', 'crisis', 'decision',
    ],
}


def detect_gaps(
    scenes_map: dict[str, dict],
    intent_map: dict[str, dict],
    briefs_map: dict[str, dict],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Scan for empty required fields given each scene's status.

    Returns:
        List of dicts: {scene_id, field, status, file}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(scenes_map.keys())

    for sid in ids_to_check:
        scene = scenes_map.get(sid, {})
        status = scene.get('status', 'spine')
        required = _GAPS_REQUIRED.get(status, [])
        if not required:
            continue

        # Merge all data for this scene
        merged = dict(scene)
        if sid in intent_map:
            merged.update({k: v for k, v in intent_map[sid].items() if k != 'id'})
        if sid in briefs_map:
            merged.update({k: v for k, v in briefs_map[sid].items() if k != 'id'})

        for field in required:
            if not merged.get(field, '').strip():
                # Determine which file owns this field
                file = 'scene-briefs.csv'
                if field in ('function', 'value_at_stake', 'value_shift', 'emotional_arc'):
                    file = 'scene-intent.csv'
                results.append({
                    'scene_id': sid,
                    'field': field,
                    'status': status,
                    'file': file,
                })

    return results


# ============================================================================
# Intent domain: quality detectors
# ============================================================================

# Function field: abstract verbs (internal, unobservable)
INTENT_ABSTRACT_INDICATORS = frozenset({
    'realizes', 'connects', 'deepens', 'transforms', 'grows', 'learns',
    'bonds', 'evolves', 'processes', 'reflects', 'grapples', 'emerges',
    'shifts', 'develops feelings', 'comes to understand', 'works through',
    'beginning to',
})

# Function field: concrete action verbs (externally observable)
INTENT_CONCRETE_INDICATORS = frozenset({
    'says', 'asks', 'discovers', 'decides', 'refuses', 'confesses',
    'chooses', 'confronts', 'reveals', 'finds', 'witnesses', 'reads',
    'writes', 'signs', 'opens', 'closes', 'walks', 'runs', 'stops',
    'picks up', 'sets down', 'hands', 'pulls', 'pushes', 'reaches',
})

# Emotional arc: rich transition phrases
_ARC_RICH_RE = re.compile(
    r'giving way to|shifting to|breaking into|dissolving into|'
    r'transforming into|turning to|hardening into|softening into|'
    r'replaced by|becoming',
    re.IGNORECASE,
)

# Emotional arc: simple "X to Y" pattern
_ARC_SIMPLE_RE = re.compile(r'\b\w+\s+to\s+\w+', re.IGNORECASE)

# Emotional arc: abstract emotion nouns (ungrounded)
EMOTIONAL_ARC_ABSTRACT = frozenset({
    'tension', 'emotion', 'feeling', 'turmoil', 'struggle', 'growth',
    'shift', 'realization', 'understanding', 'complexity', 'process',
    'resolution', 'development', 'transformation', 'change',
})

# Emotional arc: grounded/specific emotion words
EMOTIONAL_ARC_GROUNDED = frozenset({
    'grief', 'joy', 'fear', 'anger', 'shame', 'relief', 'longing',
    'tenderness', 'dread', 'exhilaration', 'guilt', 'warmth', 'pride',
    'regret', 'hope', 'despair', 'horror', 'calm', 'rage', 'sorrow',
    'awe', 'disgust', 'jealousy', 'contempt', 'resignation', 'resolve',
    'unease', 'alarm', 'shock', 'determination',
})

# Value shift polarity indicators
_POSITIVE_SHIFT_RE = re.compile(r'/\+{1,2}$')
_NEGATIVE_SHIFT_RE = re.compile(r'/-{1,2}$')


def detect_vague_function(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect function fields dominated by abstract internal-state language.

    Flags when abstract_count >= 2 AND abstract_count > concrete_count.

    Args:
        intent_map: dict keyed by scene ID, values are scene-intent row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field='function', value, abstract_count,
                        concrete_count, issue='vague'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        row = intent_map.get(sid, {})
        value = row.get('function', '').strip()
        if not value:
            continue

        value_lower = value.lower()
        abstract_count = sum(1 for ind in INTENT_ABSTRACT_INDICATORS if ind in value_lower)
        concrete_count = sum(1 for ind in INTENT_CONCRETE_INDICATORS if ind in value_lower)

        if abstract_count >= 2 and abstract_count > concrete_count:
            results.append({
                'scene_id': sid,
                'field': 'function',
                'value': value,
                'abstract_count': abstract_count,
                'concrete_count': concrete_count,
                'issue': 'vague',
            })

    return results


def detect_overlong_function(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect function fields that exceed the 400-character limit.

    Args:
        intent_map: dict keyed by scene ID, values are scene-intent row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field='function', value, char_count,
                        issue='overlong'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        row = intent_map.get(sid, {})
        value = row.get('function', '').strip()
        if not value:
            continue

        char_count = len(value)
        if char_count > 400:
            results.append({
                'scene_id': sid,
                'field': 'function',
                'value': value,
                'char_count': char_count,
                'issue': 'overlong',
            })

    return results


def detect_flat_emotional_arc(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect emotional_arc fields that lack any transition phrase.

    An arc should show movement: either a rich transition phrase ("giving way to",
    "breaking into") or a simple "X to Y" pattern. Fields that match neither
    are flagged as flat.

    Args:
        intent_map: dict keyed by scene ID, values are scene-intent row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field='emotional_arc', value, issue='flat'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        row = intent_map.get(sid, {})
        value = row.get('emotional_arc', '').strip()
        if not value:
            continue

        has_transition = _ARC_RICH_RE.search(value) or _ARC_SIMPLE_RE.search(value)
        if not has_transition:
            results.append({
                'scene_id': sid,
                'field': 'emotional_arc',
                'value': value,
                'issue': 'flat',
            })

    return results


def detect_abstract_emotional_arc(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect emotional_arc fields that rely on abstract emotion nouns.

    Flags when abstract_count >= 2 AND abstract_count > concrete_count.

    Args:
        intent_map: dict keyed by scene ID, values are scene-intent row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field='emotional_arc', value, abstract_count,
                        concrete_count, issue='abstract_arc'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        row = intent_map.get(sid, {})
        value = row.get('emotional_arc', '').strip()
        if not value:
            continue

        value_lower = value.lower()
        abstract_count = sum(1 for word in EMOTIONAL_ARC_ABSTRACT if word in value_lower)
        concrete_count = sum(1 for word in EMOTIONAL_ARC_GROUNDED if word in value_lower)

        if abstract_count >= 2 and abstract_count > concrete_count:
            results.append({
                'scene_id': sid,
                'field': 'emotional_arc',
                'value': value,
                'abstract_count': abstract_count,
                'concrete_count': concrete_count,
                'issue': 'abstract_arc',
            })

    return results


def detect_onstage_subset_violation(
    intent_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect scenes where on_stage characters are not in the characters field.

    on_stage must be a subset of characters (both semicolon-separated).

    Args:
        intent_map: dict keyed by scene ID, values are scene-intent row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field='on_stage', value, violating,
                        issue='not_subset'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        row = intent_map.get(sid, {})
        on_stage_raw = row.get('on_stage', '').strip()
        if not on_stage_raw:
            continue

        characters_raw = row.get('characters', '').strip()
        characters_set = {
            c.strip().lower()
            for c in characters_raw.split(';')
            if c.strip()
        }
        on_stage_set = {
            c.strip().lower()
            for c in on_stage_raw.split(';')
            if c.strip()
        }

        violating = sorted(on_stage_set - characters_set)
        if violating:
            results.append({
                'scene_id': sid,
                'field': 'on_stage',
                'value': on_stage_raw,
                'violating': violating,
                'issue': 'not_subset',
            })

    return results


def detect_value_shift_outcome_mismatch(
    intent_map: dict[str, dict[str, str]],
    briefs_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Detect scenes where value_shift polarity contradicts the outcome.

    Rules:
    - outcome='yes' → shift should end /+ or /++ → mismatch if /- or /--
    - outcome='no'  → shift should end /- or /-- → mismatch if /+ or /++
    - outcome='yes-but', 'no-and' or 'no-but' → skip (mixed results, any shift plausible)

    Args:
        intent_map: dict keyed by scene ID, values are scene-intent row dicts.
        briefs_map: dict keyed by scene ID, values are scene-briefs row dicts.
        scene_ids: Optional list of scene IDs to check. If None, check all.

    Returns:
        List of dicts: {scene_id, field='value_shift', value, value_shift,
                        outcome, issue='outcome_mismatch'}.
    """
    results = []
    ids_to_check = scene_ids if scene_ids else list(intent_map.keys())

    for sid in ids_to_check:
        intent_row = intent_map.get(sid, {})
        brief_row = briefs_map.get(sid, {})

        value_shift = intent_row.get('value_shift', '').strip()
        outcome = brief_row.get('outcome', '').strip().lower()

        if not value_shift or not outcome:
            continue

        # Skip mixed-result outcomes
        if outcome in ('yes-but', 'no-and', 'no-but'):
            continue

        mismatch = False
        if outcome == 'yes' and _NEGATIVE_SHIFT_RE.search(value_shift):
            mismatch = True
        elif outcome == 'no' and _POSITIVE_SHIFT_RE.search(value_shift):
            mismatch = True

        if mismatch:
            results.append({
                'scene_id': sid,
                'field': 'value_shift',
                'value': value_shift,
                'value_shift': value_shift,
                'outcome': outcome,
                'issue': 'outcome_mismatch',
            })

    return results


def detect_intent_issues(
    intent_map: dict[str, dict[str, str]],
    scenes_map: dict[str, dict[str, str]],
    briefs_map: dict[str, dict[str, str]],
    scene_ids: list[str] | None = None,
) -> list[dict]:
    """Run all intent quality detectors and return combined results.

    Each result dict includes an 'issue' key: 'vague', 'overlong',
    'flat', 'abstract_arc', 'not_subset', or 'outcome_mismatch'.

    Args:
        intent_map: dict keyed by scene ID (scene-intent rows).
        scenes_map: dict keyed by scene ID (scenes.csv rows).
        briefs_map: dict keyed by scene ID (scene-briefs rows).
        scene_ids: Optional scope.

    Returns:
        Combined list of all issue dicts, sorted by (scene_id, field, issue).
    """
    issues: list[dict] = []
    issues.extend(detect_vague_function(intent_map, scene_ids))
    issues.extend(detect_overlong_function(intent_map, scene_ids))
    issues.extend(detect_flat_emotional_arc(intent_map, scene_ids))
    issues.extend(detect_abstract_emotional_arc(intent_map, scene_ids))
    issues.extend(detect_onstage_subset_violation(intent_map, scene_ids))
    issues.extend(detect_value_shift_outcome_mismatch(intent_map, briefs_map, scene_ids))
    issues.sort(key=lambda d: (d['scene_id'], d['field'], d['issue']))
    return issues


# ============================================================================
# Intent domain: fix prompt builder
# ============================================================================

def build_intent_fix_prompt(
    scene_id: str,
    fields: list[str],
    current_values: dict[str, str],
    issues: list[dict],
    voice_guide: str = '',
) -> str:
    """Build a prompt to fix intent quality issues.

    Handles vague, overlong, flat, abstract_arc issues. Produces labeled
    output parsed by parse_concretize_response().

    Args:
        scene_id: The scene being fixed.
        fields: List of field names to rewrite.
        current_values: Dict of field_name -> current value.
        issues: List of issue dicts for this scene.
        voice_guide: Optional voice guide excerpt.

    Returns:
        Prompt string for Claude.
    """
    # Build per-field instructions based on issues
    issue_types_by_field: dict[str, list[str]] = {}
    for issue in issues:
        field = issue.get('field', '')
        issue_type = issue.get('issue', '')
        if field and issue_type:
            issue_types_by_field.setdefault(field, []).append(issue_type)

    field_blocks = []
    for field in fields:
        value = current_values.get(field, '')
        if not value:
            continue
        field_issues = issue_types_by_field.get(field, [])

        instructions = []
        if 'vague' in field_issues:
            instructions.append(
                'Rewrite as testable actions: what does the POV character say, ask, '
                'decide, refuse, confess, reveal, or physically do? No internal-state verbs '
                '(realizes, connects, grapples, grows).'
            )
        if 'overlong' in field_issues:
            instructions.append(
                'Compress to 1-3 sentences. State the scene\'s dramatic purpose '
                'concisely — cut elaboration and nested clauses.'
            )
        if 'flat' in field_issues:
            instructions.append(
                'Add a transition phrase showing emotional movement: '
                '"X giving way to Y", "X shifting to Y", "X breaking into Y", etc. '
                'The arc needs a clear before and after.'
            )
        if 'abstract_arc' in field_issues:
            instructions.append(
                'Replace abstract emotion nouns (tension, turmoil, growth, shift) '
                'with grounded, specific feelings: grief, dread, relief, shame, longing, '
                'resolve, unease, joy, etc.'
            )

        instruction_text = '\n'.join(f'  - {i}' for i in instructions) if instructions else '  - Rewrite to be more concrete and specific.'
        field_blocks.append(
            f"**{field}** (current):\n{value}\n\nFix instructions:\n{instruction_text}"
        )

    field_output = '\n'.join(f'{field}: [rewritten value]' for field in fields)

    return f"""Rewrite these scene intent fields to fix quality issues.

## Scene: {scene_id}

## Fields to Fix

{chr(10).join(field_blocks)}

## Voice Guide (POV character)
{voice_guide if voice_guide else '(not available)'}

## Output Format

Return each field on its own labeled line:

{field_output}

No explanation. No markdown. Just the labeled lines."""


# ============================================================================
# Intent domain: hone_intent
# ============================================================================

def hone_intent(
    ref_dir: str,
    project_dir: str,
    scene_ids: list[str] | None = None,
    model: str = '',
    log_dir: str = '',
    coaching_level: str = 'full',
    dry_run: bool = False,
    findings_file: str | None = None,
) -> dict:
    """Fix scene-intent.csv quality issues.

    Detects and repairs vague function fields, overlong function fields,
    flat or abstract emotional arcs, on_stage subset violations, and
    value_shift/outcome mismatches.

    Args:
        ref_dir: Path to reference/ directory.
        project_dir: Path to project root.
        scene_ids: Optional list of scene IDs to check. If None, check all.
        model: Anthropic model ID for API calls.
        log_dir: Directory for API log files.
        coaching_level: full/coach/strict.
        dry_run: If True, detect but don't rewrite.
        findings_file: Optional path to a pipe-delimited CSV of external evaluation
            findings (scene_id|target_file|fields|guidance).  Findings targeting
            scene-intent.csv are merged into all_issues before processing.

    Returns:
        Dict with scenes_flagged, scenes_rewritten, fields_rewritten.
    """
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    if not os.path.isfile(intent_path):
        return {'scenes_flagged': 0, 'scenes_rewritten': 0, 'fields_rewritten': 0}

    intent_map = _read_csv_as_map(intent_path)
    scenes_map = _read_csv_as_map(os.path.join(ref_dir, 'scenes.csv'))
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')
    briefs_map = _read_csv_as_map(briefs_path) if os.path.isfile(briefs_path) else {}

    # Detect all issue types
    all_issues = detect_intent_issues(intent_map, scenes_map, briefs_map, scene_ids)

    # Merge external findings if provided
    if findings_file:
        external = load_external_findings(findings_file)
        external_intent = [e for e in external if e.get('target_file', '') == 'scene-intent.csv']
        existing_keys = {(i['scene_id'], i['field']) for i in all_issues}
        for ext in external_intent:
            if ext['field'] and (ext['scene_id'], ext['field']) not in existing_keys:
                all_issues.append(ext)
            elif ext['field']:
                # External takes priority — replace detected issue
                all_issues = [i for i in all_issues
                              if not (i['scene_id'] == ext['scene_id'] and i['field'] == ext['field'])]
                all_issues.append(ext)
            elif not ext['field']:
                all_issues.append(ext)

    if dry_run or not all_issues:
        return {
            'scenes_flagged': len(set(f['scene_id'] for f in all_issues)),
            'scenes_rewritten': 0,
            'fields_rewritten': 0,
        }

    # --- Deterministic fix: not_subset (no API required) ---
    # Add on_stage characters that are missing from characters (not the reverse).
    # character_presence scoring rewards characters being in on_stage, so we
    # expand the characters list rather than shrinking on_stage.
    det_fields_rewritten = 0
    not_subset_issues = [i for i in all_issues if i['issue'] == 'not_subset']
    for issue in not_subset_issues:
        sid = issue['scene_id']
        if sid not in intent_map:
            continue
        chars_raw = intent_map[sid].get('characters', '')
        valid_chars = {c.strip().lower() for c in chars_raw.split(';') if c.strip()}
        on_stage_raw = intent_map[sid].get('on_stage', '')
        on_stage_entries = [c.strip() for c in on_stage_raw.split(';') if c.strip()]
        missing = [c for c in on_stage_entries if c.lower() not in valid_chars]
        if missing:
            existing_chars = [c.strip() for c in chars_raw.split(';') if c.strip()]
            new_chars = existing_chars + missing
            intent_map[sid]['characters'] = ';'.join(new_chars)
            det_fields_rewritten += 1

    # Write deterministic fixes immediately if any
    if det_fields_rewritten > 0:
        intent_rows = list(intent_map.values())
        intent_rows.sort(key=lambda r: r.get('id', ''))
        _write_csv(intent_path, intent_rows, _FILE_MAP['scene-intent.csv'])

    # Strict mode: save analysis and return (after deterministic fixes)
    if coaching_level == 'strict':
        hone_dir = os.path.join(project_dir, 'working', 'hone')
        os.makedirs(hone_dir, exist_ok=True)
        for f in all_issues:
            if f['issue'] == 'not_subset':
                continue  # already fixed
            path = os.path.join(hone_dir, f'intent-analysis-{f["scene_id"]}.md')
            with open(path, 'a') as fh:
                fh.write(f"**{f['field']}:** {f['issue']}\n")
                if 'value' in f:
                    fh.write(f"  Current: {f['value'][:200]}\n")
        det_scenes = len(set(i['scene_id'] for i in not_subset_issues)) if det_fields_rewritten > 0 else 0
        return {
            'scenes_flagged': len(set(f['scene_id'] for f in all_issues)),
            'scenes_rewritten': det_scenes,
            'fields_rewritten': det_fields_rewritten,
        }

    # Load voice guide
    voice_guide = ''
    voice_path = os.path.join(ref_dir, 'voice-guide.md')
    if os.path.isfile(voice_path):
        with open(voice_path, encoding='utf-8') as fh:
            voice_guide = fh.read()

    from storyforge.api import invoke_to_file, extract_text_from_file

    # Group remaining API-fixable issues by scene (excluding already-fixed not_subset)
    api_fixable_issues = [i for i in all_issues if i['issue'] != 'not_subset']
    by_scene: dict[str, list[dict]] = {}
    for issue in api_fixable_issues:
        by_scene.setdefault(issue['scene_id'], []).append(issue)

    scenes_rewritten = (len(set(i['scene_id'] for i in not_subset_issues))
                        if det_fields_rewritten > 0 else 0)
    api_fields_rewritten = 0
    total_scenes = len(by_scene)

    for idx, (sid, issues) in enumerate(by_scene.items(), 1):
        if sid not in intent_map:
            continue

        eval_issues = [i for i in issues if i['issue'] == 'evaluation']
        detected_issues = [i for i in issues if i['issue'] != 'evaluation']

        issue_types = sorted(set(i['issue'] for i in issues))
        log(f'  [{idx}/{total_scenes}] {sid} ({", ".join(issue_types)})')

        scene_fields_rewritten = 0

        # Handle detected quality issues (vague, overlong, flat, abstract_arc)
        if detected_issues and coaching_level == 'full':
            detected_fields = list(dict.fromkeys(i['field'] for i in detected_issues))
            current_values = {f: intent_map[sid].get(f, '') for f in detected_fields}

            prompt = build_intent_fix_prompt(
                scene_id=sid,
                fields=detected_fields,
                current_values=current_values,
                issues=detected_issues,
                voice_guide=voice_guide[:3000],
            )

            eff_log_dir = log_dir or os.path.join(project_dir, 'working', 'logs')
            os.makedirs(eff_log_dir, exist_ok=True)
            log_file = os.path.join(eff_log_dir, f'hone-intent-{sid}.json')
            invoke_to_file(prompt, model, log_file, max_tokens=2048,
                           label=f'hone intent {idx}/{total_scenes} ({sid})')
            response = extract_text_from_file(log_file)

            rewrites = parse_concretize_response(response, sid, detected_fields)
            for field, new_value in rewrites.items():
                if new_value and new_value != current_values.get(field):
                    intent_map[sid][field] = new_value
                    api_fields_rewritten += 1
                    scene_fields_rewritten += 1

        # Handle evaluation issues (from external findings)
        if eval_issues and coaching_level == 'full':
            eval_fields = list(dict.fromkeys(i['field'] for i in eval_issues if i['field']))
            if not eval_fields:
                eval_fields = [f for f in intent_map[sid].keys()
                               if f != 'id' and intent_map[sid].get(f, '')]
            current_values = {f: intent_map[sid].get(f, '') for f in eval_fields}
            guidance = '; '.join(i.get('guidance', '') for i in eval_issues if i.get('guidance'))

            prompt = build_evaluation_fix_prompt(
                scene_id=sid,
                fields=eval_fields,
                current_values=current_values,
                guidance=guidance,
                voice_guide=voice_guide[:3000],
            )

            eff_log_dir = log_dir or os.path.join(project_dir, 'working', 'logs')
            os.makedirs(eff_log_dir, exist_ok=True)
            log_file = os.path.join(eff_log_dir, f'hone-intent-eval-{sid}.json')
            invoke_to_file(prompt, model, log_file, max_tokens=2048,
                           label=f'hone intent eval {idx}/{total_scenes} ({sid})')
            response = extract_text_from_file(log_file)

            rewrites = parse_concretize_response(response, sid, eval_fields)
            for field, new_value in rewrites.items():
                if new_value and new_value != current_values.get(field):
                    intent_map[sid][field] = new_value
                    api_fields_rewritten += 1
                    scene_fields_rewritten += 1

        # Coach mode: save proposals instead of applying
        if coaching_level == 'coach':
            hone_dir = os.path.join(project_dir, 'working', 'hone')
            os.makedirs(hone_dir, exist_ok=True)
            proposal_path = os.path.join(hone_dir, f'intent-{sid}.md')
            with open(proposal_path, 'w') as fh:
                fh.write(f"# Intent Quality Proposals: {sid}\n\n")
                for issue in issues:
                    fh.write(f"## {issue['field']} — {issue['issue']}\n")
                    if 'value' in issue:
                        fh.write(f"**Current:** {issue['value'][:300]}\n\n")
            continue

        if scene_fields_rewritten > 0:
            scenes_rewritten += 1

    # Write back if any API-driven changes were made (deterministic writes already happened above)
    if api_fields_rewritten > 0:
        intent_rows = list(intent_map.values())
        intent_rows.sort(key=lambda r: r.get('id', ''))
        _write_csv(intent_path, intent_rows, _FILE_MAP['scene-intent.csv'])

    return {
        'scenes_flagged': len(set(f['scene_id'] for f in all_issues)),
        'scenes_rewritten': scenes_rewritten,
        'fields_rewritten': det_fields_rewritten + api_fields_rewritten,
    }


# ============================================================================
# Physical state chain propagation
# ============================================================================

def propagate_physical_states(ref_dir: str, dry_run: bool = False) -> dict:
    """Fill gaps in physical_state_in/out by propagating states through scenes.

    For each state in the registry, every scene between its acquired scene
    and its resolved scene should carry it — unless the character is not
    on-stage in that scene.

    Deterministic — no API calls.

    Args:
        ref_dir: Path to the reference/ directory.
        dry_run: If True, report what would change without writing.

    Returns:
        Dict with states_propagated, scenes_updated, changes.
    """
    registry_path = os.path.join(ref_dir, 'physical-states.csv')
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')
    briefs_path = os.path.join(ref_dir, 'scene-briefs.csv')

    if not os.path.isfile(registry_path):
        return {'states_propagated': 0, 'scenes_updated': 0, 'changes': []}

    registry = _read_csv(registry_path)
    scenes_map = _read_csv_as_map(scenes_path)
    intent_map = _read_csv_as_map(intent_path) if os.path.isfile(intent_path) else {}
    briefs_map = _read_csv_as_map(briefs_path)

    # Build ordered scene list
    ordered_ids = sorted(
        scenes_map.keys(),
        key=lambda sid: int(scenes_map[sid].get('seq', 0) or 0)
    )
    seq_index = {sid: idx for idx, sid in enumerate(ordered_ids)}

    changes = []
    states_propagated = set()

    for state in registry:
        state_id = state.get('id', '').strip()
        character = state.get('character', '').strip()
        acquired = state.get('acquired', '').strip()
        resolves = state.get('resolves', '').strip()

        if not state_id or not acquired or acquired not in seq_index:
            continue

        start_idx = seq_index[acquired]
        if resolves and resolves != 'never' and resolves in seq_index:
            end_idx = seq_index[resolves]
        else:
            end_idx = len(ordered_ids) - 1

        for idx in range(start_idx, end_idx + 1):
            sid = ordered_ids[idx]
            brief = briefs_map.get(sid, {})

            # Check if character is on-stage (or is POV)
            scene = scenes_map.get(sid, {})
            intent = intent_map.get(sid, {})
            pov = scene.get('pov', '').strip()
            on_stage_raw = intent.get('on_stage', '') or intent.get('characters', '')
            on_stage = {c.strip().lower() for c in on_stage_raw.split(';') if c.strip()}
            on_stage.add(pov.lower())

            if character and character.lower() not in on_stage:
                continue

            # physical_state_in: all scenes after acquired
            if idx > start_idx:
                current_in = brief.get('physical_state_in', '').strip()
                current_in_set = {s.strip() for s in current_in.split(';') if s.strip()}
                if state_id not in current_in_set:
                    current_in_set.add(state_id)
                    new_val = ';'.join(sorted(current_in_set))
                    changes.append({
                        'scene_id': sid, 'field': 'physical_state_in',
                        'added_states': [state_id],
                    })
                    if not dry_run:
                        briefs_map[sid]['physical_state_in'] = new_val
                    states_propagated.add(state_id)

            # physical_state_out: acquired through end, except the resolve scene
            is_resolve_scene = (resolves and resolves != 'never' and sid == resolves)
            if not is_resolve_scene:
                current_out = brief.get('physical_state_out', '').strip()
                current_out_set = {s.strip() for s in current_out.split(';') if s.strip()}
                if state_id not in current_out_set:
                    current_out_set.add(state_id)
                    new_val = ';'.join(sorted(current_out_set))
                    changes.append({
                        'scene_id': sid, 'field': 'physical_state_out',
                        'added_states': [state_id],
                    })
                    if not dry_run:
                        briefs_map[sid]['physical_state_out'] = new_val
                    states_propagated.add(state_id)

    scenes_updated = len(set(c['scene_id'] for c in changes))
    if not dry_run and changes:
        briefs_rows = list(briefs_map.values())
        briefs_rows.sort(key=lambda r: r.get('id', ''))
        _write_csv(briefs_path, briefs_rows, _FILE_MAP['scene-briefs.csv'])

    return {
        'states_propagated': len(states_propagated),
        'scenes_updated': scenes_updated,
        'changes': changes,
    }


# ============================================================================
# MICE thread dormancy detection
# ============================================================================

_DORMANCY_THRESHOLD = 8  # scenes


def detect_mice_dormancy(ref_dir: str) -> list[dict]:
    """Detect MICE thread dormancy gaps.

    For each thread in the registry, finds gaps > _DORMANCY_THRESHOLD
    scenes between consecutive mentions.

    Args:
        ref_dir: Path to the reference/ directory.

    Returns:
        List of dicts: {thread_id, thread_name, thread_type, gap_size,
                        before_scene, after_scene, gap_scenes: [scene_ids]}.
    """
    registry_path = os.path.join(ref_dir, 'mice-threads.csv')
    scenes_path = os.path.join(ref_dir, 'scenes.csv')
    intent_path = os.path.join(ref_dir, 'scene-intent.csv')

    if not os.path.isfile(registry_path):
        return []

    registry = {r['id']: r for r in _read_csv(registry_path)}
    scenes_map = _read_csv_as_map(scenes_path)
    intent_map = _read_csv_as_map(intent_path) if os.path.isfile(intent_path) else {}

    ordered_ids = sorted(
        scenes_map.keys(),
        key=lambda sid: int(scenes_map[sid].get('seq', 0) or 0)
    )

    # Build lookup: bare name -> registry ID (handles type:name registry keys)
    bare_to_id = {}
    for rid in registry:
        bare_to_id[rid] = rid  # exact match
        if ':' in rid:
            bare_to_id[rid.split(':', 1)[1]] = rid  # bare name -> full ID

    # Build per-thread mention indices
    thread_mentions = {}  # thread_id -> [scene_index]
    for idx, sid in enumerate(ordered_ids):
        mice = intent_map.get(sid, {}).get('mice_threads', '').strip()
        if not mice:
            continue
        for entry in mice.split(';'):
            entry = entry.strip()
            if not entry:
                continue
            # Strip +/- prefix
            name = entry.lstrip('+-')
            # Try exact match first, then bare name (without type: prefix)
            reg_id = bare_to_id.get(name)
            if not reg_id and ':' in name:
                reg_id = bare_to_id.get(name.split(':', 1)[1])
            if reg_id:
                thread_mentions.setdefault(reg_id, []).append(idx)

    # Find gaps
    results = []
    for thread_id, indices in thread_mentions.items():
        indices = sorted(set(indices))
        if len(indices) < 2:
            continue
        for i in range(len(indices) - 1):
            gap = indices[i + 1] - indices[i]
            if gap > _DORMANCY_THRESHOLD:
                gap_scene_ids = ordered_ids[indices[i] + 1:indices[i + 1]]
                reg = registry.get(thread_id, {})
                results.append({
                    'thread_id': thread_id,
                    'thread_name': reg.get('name', thread_id),
                    'thread_type': reg.get('type', 'unknown'),
                    'gap_size': gap,
                    'before_scene': ordered_ids[indices[i]],
                    'after_scene': ordered_ids[indices[i + 1]],
                    'gap_scenes': gap_scene_ids,
                })

    return results


def build_mice_fill_prompt(
    thread_id: str,
    thread_name: str,
    thread_type: str,
    gap_scenes: list[dict],
    before_scene: str,
    after_scene: str,
) -> str:
    """Build prompt for Claude to identify which gap scenes should mention a thread.

    Args:
        thread_id: Canonical thread ID (e.g., 'family-secret').
        thread_name: Display name (e.g., 'The Family Secret').
        thread_type: MICE type (milieu, inquiry, character, event).
        gap_scenes: List of dicts with id, title, goal, function for each scene in the gap.
        before_scene: Scene ID where thread was last mentioned.
        after_scene: Scene ID where thread is next mentioned.

    Returns:
        Prompt string for Claude.
    """
    scene_block = '\n'.join(
        f"- **{s['id']}** ({s.get('title', '')}): goal: {s.get('goal', 'unknown')}; function: {s.get('function', 'unknown')}"
        for s in gap_scenes
    )

    return f"""A MICE thread has gone dormant — too many scenes without a reference. Your job is to identify which scenes in the gap should mention this thread to keep it alive in the reader's awareness.

## Thread

- **ID:** {thread_id}
- **Name:** {thread_name}
- **Type:** {thread_type}
- **Last mentioned:** scene {before_scene}
- **Next mentioned:** scene {after_scene}
- **Gap:** {len(gap_scenes)} scenes without a reference

## Scenes in the Gap

{scene_block}

## Instructions

Pick 1-3 scenes from the gap where this thread could be naturally referenced — where the scene's goal or function connects to the thread's concerns. A thread reference doesn't mean the thread advances or resolves. It means the thread is present in the scene: a passing thought, a detail in the environment, a line of dialogue that touches the thread without resolving it.

For an **inquiry** thread, a mention might be a character wondering about the question, or noticing evidence.
For a **character** thread, a mention might be the character exhibiting the trait or tension the thread tracks.
For a **milieu** thread, a mention might be awareness of the space — its sounds, its boundaries, its effect on the characters.
For an **event** thread, a mention might be the characters feeling the disruption's ongoing effects.

Do NOT add mentions to scenes where the thread doesn't fit. Fewer mentions in the right places is better than more mentions forced into wrong scenes. If no scene in the gap naturally connects, say NONE.

## Output Format

One line per recommended scene:

MENTION: scene_id

Or if no scenes fit:

NONE

No explanation. Just the scene IDs."""


def parse_mice_fill_response(response: str) -> list[str]:
    """Parse Claude's response to a mice-fill prompt.

    Returns list of scene IDs that should get thread mentions.
    """
    results = []
    for line in response.split('\n'):
        line = line.strip()
        if line.upper() == 'NONE':
            return []
        if line.startswith('MENTION:'):
            scene_id = line[len('MENTION:'):].strip()
            if scene_id:
                results.append(scene_id)
    return results

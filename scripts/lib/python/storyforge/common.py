"""Core utilities for Storyforge — replaces scripts/lib/common.sh.

Provides: logging, YAML reading, project root detection, plugin dir,
model selection, coaching level, craft section extraction, pipeline manifest,
signal handling, and interactive mode helpers.
"""

import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Final


# ============================================================================
# Logging
# ============================================================================

_log_file: str | None = None


def set_log_file(path: str) -> None:
    global _log_file
    _log_file = path
    os.makedirs(os.path.dirname(path), exist_ok=True)


def log(msg: str) -> None:
    """Timestamped log to stdout and optional log file."""
    ts = datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')
    line = f'{ts} {msg}'
    print(line, flush=True)
    if _log_file:
        with open(_log_file, 'a') as f:
            f.write(line + '\n')


# ============================================================================
# Project root detection
# ============================================================================

def detect_project_root(start: str | None = None) -> str:
    """Walk up from start (default cwd) looking for storyforge.yaml.

    Returns the project directory path.
    Raises SystemExit if not found within 20 levels.
    """
    d = Path(start or os.getcwd()).resolve()
    for _ in range(20):
        if (d / 'storyforge.yaml').exists():
            return str(d)
        parent = d.parent
        if parent == d:
            break
        d = parent
    print('ERROR: Could not find storyforge.yaml in any parent directory.', file=sys.stderr)
    print('Are you inside a Storyforge project?', file=sys.stderr)
    sys.exit(1)


# ============================================================================
# Plugin directory
# ============================================================================

def get_plugin_dir() -> str:
    """Get the Storyforge plugin directory (repo root).

    Navigates up from this file: python/storyforge/ -> python/ -> lib/ -> scripts/ -> repo root
    """
    here = Path(__file__).resolve().parent  # storyforge/
    return str(here.parent.parent.parent.parent)


# ============================================================================
# YAML helpers (no pyyaml dependency)
# ============================================================================

def read_yaml_field(field: str, project_dir: str | None = None) -> str:
    """Read a value from storyforge.yaml.

    Supports flat keys ('title') and dotted keys ('project.title').
    Returns empty string if not found.
    """
    if project_dir is None:
        project_dir = detect_project_root()

    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_file):
        return ''

    with open(yaml_file) as f:
        lines = f.readlines()

    if '.' in field:
        parent, child = field.split('.', 1)
        in_parent = False
        for line in lines:
            if re.match(rf'^{re.escape(parent)}:', line):
                in_parent = True
                continue
            if in_parent:
                if line and not line[0].isspace():
                    in_parent = False
                    continue
                m = re.match(rf'^\s+{re.escape(child)}:\s*(.*)', line)
                if m:
                    return _strip_yaml_value(m.group(1))
    else:
        for line in lines:
            m = re.match(rf'^{re.escape(field)}:\s*(.*)', line)
            if m:
                return _strip_yaml_value(m.group(1))

    return ''


def parse_yaml_scalar(raw: str) -> str:
    """Parse the text after a `key:` into the scalar the author meant.

    The one such function in the repo. There were three — `_strip_yaml_value`
    here, the same name in `prompts.py`, and `_strip_yaml_quotes` in
    `assembly.py` — all quote-stripping only, so **every** one of them returned
    a value with its inline comment glued on. Both other copies now delegate,
    for the reason `common.csv_safe` lives here rather than in `illustrations`:
    one behaviour, one place to correct it.

    Two things beyond stripping quotes, and #277 is what happens without them:

    **An inline comment is not part of the value.** `genre: "Children's book"
    # Primary genre` yielded the comment too, and — worse — an *empty* field
    carrying a template comment (`series_name:  # Optional: series title`)
    yielded that comment as a **truthy** value, which is how a project with no
    series emitted a `belongs-to-collection:` line into its epub.

    **A `#` is only a comment where YAML says it is.** Inside quotes it is
    literal, and unquoted it opens a comment only at the start or after
    whitespace — so `path: a#b` is the value `a#b`, not `a`. Stripping on a bare
    `#` would silently truncate any value legitimately containing one (a URL
    fragment, a CSS colour), which is the failure this function exists to stop,
    pointed the other way.
    """
    val = raw.strip()
    if not val:
        return ''

    if val[0] in ('"', "'"):
        parsed = _parse_quoted_scalar(val)
        if parsed is not None:
            return parsed
        # Malformed quoting falls through to the lenient pre-#277 strip below.
        # Returning the strict read instead would be worse than the bug being
        # fixed: `title: ""Unicorn Tail""` is not valid YAML, but its strict
        # reading is the empty string, which turns a typo into a silently
        # missing title rather than a visible one. A malformed value degrades to
        # the result it has always had.

    if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
        return val[1:-1]
    return _strip_inline_comment(val)


def _parse_quoted_scalar(val: str) -> str | None:
    """Read a quoted YAML scalar, or None if the quoting is malformed.

    Scans for the closing quote rather than testing `val[-1]`, which is what the
    three copies of this did: comparing first and last character means a quoted
    value followed by a comment (`"A"  # note`) fails the test and is returned
    whole — quotes, comment, and all.

    Malformed means either no closing quote, or trailing content after it that
    is not a comment. Both return None so the caller can fall back.
    """
    quote = val[0]
    i = 1
    while i < len(val):
        if val[i] == '\\' and quote == '"':
            i += 2  # escaped char in a double-quoted scalar
            continue
        if val[i] == quote:
            if quote == "'" and val[i + 1:i + 2] == "'":
                i += 2  # '' is an escaped apostrophe in YAML
                continue
            rest = val[i + 1:].strip()
            if rest and not rest.startswith('#'):
                return None
            inner = val[1:i]
            return (inner.replace("''", "'") if quote == "'"
                    else _unescape_double_quoted(inner))
        i += 1
    return None


def _strip_inline_comment(val: str) -> str:
    """Drop a trailing `# comment` from an unquoted scalar."""
    if val.startswith('#'):
        return ''
    m = re.search(r'\s#', val)
    return val[:m.start()].strip() if m else val


def _unescape_double_quoted(inner: str) -> str:
    """Resolve the escape sequences a double-quoted YAML scalar may carry."""
    return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t', 'r': '\r'}.get(
        m.group(1), m.group(1)), inner)


def yaml_single_quote(value: str) -> str:
    """Quote a value for emission into a YAML file we generate.

    Single-quoted style, because that is what `generate_epub_metadata` has
    always emitted and two tests pin it. Escaping is what was missing: in a
    single-quoted YAML scalar an apostrophe is written by **doubling** it, and
    nothing did, so `Children's` closed the string early and pandoc exited 64 on
    a valid project (#277). Nothing else needs escaping in this style —
    backslashes are literal and there are no escape sequences — which is a good
    reason to keep it rather than move to double quotes.

    Newlines are collapsed: a value read from one YAML line cannot contain one
    today, and a multi-line scalar would break the metadata block rather than
    the value.
    """
    collapsed = re.sub(r'\s+', ' ', str(value)).strip()
    return "'" + collapsed.replace("'", "''") + "'"


def _strip_yaml_value(val: str) -> str:
    """Back-compat alias for `parse_yaml_scalar`."""
    return parse_yaml_scalar(val)


#: Keys `update_artifact_entry` will write, in the order the template lists them
#: under an artifact. Enumerated positively so a caller cannot name an arbitrary
#: key and have this function invent a line for it.
_ARTIFACT_WRITABLE_KEYS: Final[tuple[str, ...]] = ('exists', 'updated')


def update_artifact_entry(project_dir: str, artifact: str, *,
                          exists: bool | None = None,
                          updated: str | None = None) -> bool:
    """Set `exists` / `updated` on one `artifacts:` entry, in place.

    Returns True if the file changed.

    **Line-scoped on purpose.** This replaces a whole-file `re.sub` under
    `re.DOTALL` whose pattern ended in an unanchored `.*`, which matched to end
    of file — so updating `chapter_map.updated` deleted every block after it
    (`manuscript`, `phase`, `parts`, the entire `production` section) and
    `assemble` then committed the truncated file. Data loss on every run (#276).

    That bug had a second, quieter half worth keeping in mind here: because the
    first artifact's rewrite had already deleted the second one, the loop's next
    iteration silently matched nothing and the update it existed to perform never
    happened. So a caller gets a bool — "I found the block and wrote it" is a
    fact worth being able to check, and its absence is what let the original go
    unnoticed.

    Everything outside the two value tokens is preserved byte for byte,
    including blank lines, key order, and **inline comments** on the lines it
    rewrites. Comments matter more than they look: #277 is a bug caused by
    reading them as values, and stripping them on write would quietly discard
    author annotations while fixing that.
    """
    yaml_file = os.path.join(project_dir, 'storyforge.yaml')
    if not os.path.isfile(yaml_file):
        log(f'WARNING: cannot update artifact {artifact!r} — no '
            f'storyforge.yaml at {yaml_file}')
        return False

    # `newline=''` on both ends: the default universal-newline translation would
    # read CRLF as LF and write LF back, normalizing the *whole* file as a side
    # effect of editing two values — which `cleanup` then reports as
    # `crlf_line_endings`. Preserving them verbatim is the same discipline
    # `write_plan`'s explicit `lineterminator` enforces for CSVs.
    with open(yaml_file, newline='') as f:
        lines = f.readlines()

    span = _artifact_block_span(lines, artifact)
    if span is None:
        log(f'WARNING: no `{artifact}:` entry under `artifacts:` in '
            f'storyforge.yaml — nothing updated. Run `storyforge cleanup` to '
            f'add missing artifact entries.')
        return False

    start, end, indent = span
    # An inserted line has to match the file it lands in, or a CRLF project
    # gains one stray LF line and `cleanup` reports mixed endings.
    newline = '\r\n' if lines[0].endswith('\r\n') else '\n'
    values = {'exists': None if exists is None else str(exists).lower(),
              'updated': None if updated is None else f'"{updated}"'}
    changed = False
    for key in _ARTIFACT_WRITABLE_KEYS:
        if values[key] is None:
            continue
        result = _set_block_value(lines, start, end, key, values[key])
        if result is None:
            # The key is absent from an otherwise valid block. Insert rather
            # than skip: the caller asked for the value to be recorded, and a
            # silent no-op here is exactly the shape of the bug above.
            lines.insert(end, f'{indent}  {key}: {values[key]}{newline}')
            end += 1
            changed = True
        elif result:
            changed = True

    if changed:
        with open(yaml_file, 'w', newline='') as f:
            f.writelines(lines)
    return changed


def _artifact_block_span(lines: list[str],
                         artifact: str) -> tuple[int, int, str] | None:
    """Locate one artifact's block as `(first_child, end, key_indent)`.

    `end` is exclusive and is the last child line + 1, ignoring trailing blanks
    so an inserted key lands inside the block rather than after the blank line
    that separates it from its sibling.
    """
    top = next((i for i, line in enumerate(lines)
                if re.match(r'^artifacts:', line)), None)
    if top is None:
        return None

    key_re = re.compile(rf'^(\s+){re.escape(artifact)}:\s*(?:#.*)?$')
    for i in range(top + 1, len(lines)):
        line = lines[i]
        # A non-indented, non-blank, non-comment line ends the artifacts block.
        if line.strip() and not line[0].isspace() and not line.startswith('#'):
            return None
        m = key_re.match(line)
        if not m:
            continue
        indent = m.group(1)
        end = i + 1
        last_content = i + 1
        for j in range(i + 1, len(lines)):
            if not lines[j].strip():
                end = j + 1
                continue
            if len(lines[j]) - len(lines[j].lstrip()) <= len(indent):
                break
            end = last_content = j + 1
        return i + 1, last_content, indent
    return None


def _set_block_value(lines: list[str], start: int, end: int,
                     key: str, value: str) -> bool | None:
    """Rewrite `key`'s value within `lines[start:end]`, keeping any comment.

    Returns True if the line changed, False if it was already correct, and None
    if the key is not in the block — three outcomes the caller must tell apart,
    since "not there" means insert and "already correct" must not dirty the file.

    The trailing-newline group keeps CRLF intact. A rewrite that normalized line
    endings would show up as `crlf_line_endings` from `cleanup` on a project that
    legitimately uses them, which is the failure `write_plan`'s explicit
    `lineterminator` exists to avoid at the CSV layer.
    """
    pattern = re.compile(rf'^(\s*{re.escape(key)}:)([^#\n\r]*)(#.*?)?(\r?\n?)$')
    for i in range(start, min(end, len(lines))):
        m = pattern.match(lines[i])
        if not m:
            continue
        comment = f'  {m.group(3)}' if m.group(3) else ''
        newline = m.group(4) or '\n'
        rewritten = f'{m.group(1)} {value}{comment}{newline}'
        if rewritten == lines[i]:
            return False
        lines[i] = rewritten
        return True
    return None


# ============================================================================
# Story summary parsing (reference/story-summary.md)
# ============================================================================

STORY_SUMMARY_PATH = os.path.join('reference', 'story-summary.md')
STORY_SUMMARY_SECTIONS = ('logline', 'synopsis', 'act_shape', 'theme')


def parse_story_summary(project_dir: str | None = None) -> dict | None:
    """Parse `reference/story-summary.md` into a structured dict.

    Returns:
        {
          'frontmatter': {logline_updated, synopsis_updated,
                          act_shape_updated, theme_updated},
          'logline':   str,  # the body of `## Logline`
          'synopsis':  str,  # the body of `## Synopsis`
          'act_shape': str,  # the body of `## Act-shape` (includes `### Act N` sub-headers)
          'theme':     str,  # the body of `## Theme`
        }

    Returns None if the file is absent. Missing sections return ''. The
    HTML/Markdown comment at the top of the template is stripped before
    section parsing.
    """
    if project_dir is None:
        project_dir = detect_project_root()
    path = os.path.join(project_dir, STORY_SUMMARY_PATH)
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        text = f.read()

    # Strip a leading HTML comment block, if any (templates start with one).
    text = re.sub(r'^\s*<!--.*?-->\s*', '', text, count=1, flags=re.DOTALL)

    # Extract YAML frontmatter (between leading `---` lines).
    frontmatter = {
        'logline_updated': '',
        'synopsis_updated': '',
        'act_shape_updated': '',
        'theme_updated': '',
    }
    fm_match = re.match(r'^---\n(.*?)\n---\n', text, flags=re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            m = re.match(r'^([a-z_]+):\s*(.*)$', line)
            if m and m.group(1) in frontmatter:
                frontmatter[m.group(1)] = _strip_yaml_value(m.group(2))
        text = text[fm_match.end():]

    # Split on level-2 headings. Section keys are normalized:
    #   "Logline"    → 'logline'
    #   "Synopsis"   → 'synopsis'
    #   "Act-shape"  → 'act_shape'  (hyphen → underscore)
    #   "Theme"      → 'theme'
    sections = {k: '' for k in STORY_SUMMARY_SECTIONS}
    # The level-1 heading (`# Story summary`) is ignored.
    parts = re.split(r'^##\s+(.+?)$', text, flags=re.MULTILINE)
    # parts = [pre, name1, body1, name2, body2, ...]
    for i in range(1, len(parts), 2):
        name = parts[i].strip().lower().replace('-', '_').replace(' ', '_')
        body = parts[i + 1].strip() if i + 1 < len(parts) else ''
        if name in sections:
            sections[name] = body

    return {'frontmatter': frontmatter, **sections}


# ============================================================================
# File checks
# ============================================================================

def check_file_exists(filepath: str, label: str | None = None,
                      project_dir: str | None = None) -> None:
    """Verify a required file exists. Exits if not found."""
    if not os.path.isabs(filepath) and project_dir:
        filepath = os.path.join(project_dir, filepath)
    if not os.path.isfile(filepath):
        log(f'ERROR: Required file missing — {label or filepath}: {filepath}')
        sys.exit(1)


# ============================================================================
# Model selection
# ============================================================================

# Single source of truth: the concrete model ID currently used for each
# capability tier. The Anthropic API requires an exact model ID (there is no
# floating "latest"/"opus" alias — a bare tier name 404s), so when a newer
# model ships, bump the ID here — in this one place — and every dispatch site
# below follows, because they all refer to the tier, never a version string.
LATEST_MODELS = {
    'opus':   'claude-opus-4-8',
    'sonnet': 'claude-sonnet-4-6',
    'haiku':  'claude-haiku-4-5-20251001',
}

# Which capability tier each task type dispatches to.
_TASK_TIER = {
    'drafting': 'opus',
    'revision': 'opus',
    'mechanical': 'sonnet',
    'evaluation': 'sonnet',
    'extraction': 'haiku',
    'synthesis': 'opus',
    'review': 'sonnet',
    # creative: synthesis-style work that needs strong judgment but isn't
    # full-scene drafting (style guides, summary proposals, prose adaptation).
    'creative': 'opus',
}


def model_for_tier(tier: str) -> str:
    """Return the current concrete model ID for a capability tier."""
    return LATEST_MODELS[tier]


def select_model(task_type: str) -> str:
    """Select the appropriate model for a task type.

    Resolves the task's tier through LATEST_MODELS; unknown tasks default to
    the opus tier. STORYFORGE_MODEL env var overrides all.
    """
    override = os.environ.get('STORYFORGE_MODEL')
    if override:
        return override
    return LATEST_MODELS[_TASK_TIER.get(task_type, 'opus')]


def select_revision_model(pass_name: str, purpose: str = '') -> str:
    """Select model for a revision pass.

    Creative passes get Opus, mechanical passes get Sonnet.
    """
    override = os.environ.get('STORYFORGE_MODEL')
    if override:
        return override

    key = f'{pass_name} {purpose}'.lower()
    if re.search(r'continuity|timeline|fact.check|thread.track', key):
        return LATEST_MODELS['sonnet']
    return LATEST_MODELS['opus']


# ============================================================================
# Coaching level
# ============================================================================

from typing import Literal

CoachingLevel = Literal['full', 'coach', 'strict']


def get_coaching_level(project_dir: str | None = None) -> CoachingLevel:
    """Get coaching level: full, coach, or strict.

    Priority: STORYFORGE_COACHING env > storyforge.yaml > 'full'
    """
    env = os.environ.get('STORYFORGE_COACHING')
    if env in ('full', 'coach', 'strict'):
        return env  # type: ignore[return-value]

    if project_dir:
        level = read_yaml_field('project.coaching_level', project_dir)
        if level in ('full', 'coach', 'strict'):
            return level  # type: ignore[return-value]

    return 'full'


# ============================================================================
# Craft engine section extraction
# ============================================================================

def extract_craft_sections(*section_nums: int) -> str:
    """Extract sections from the craft engine by number.

    Returns extracted text with --- dividers between sections.
    """
    craft_file = os.path.join(get_plugin_dir(), 'references', 'craft-engine.md')
    if not os.path.isfile(craft_file):
        log(f'WARNING: Craft engine not found at {craft_file}')
        return ''

    with open(craft_file) as f:
        lines = f.readlines()

    sections = []
    for num in section_nums:
        pattern = re.compile(rf'^## {num}\. ')
        capturing = False
        section_lines: list[str] = []

        for line in lines:
            if pattern.match(line):
                capturing = True
            elif capturing and re.match(r'^## \d+\. ', line):
                break
            if capturing:
                section_lines.append(line)

        if section_lines:
            sections.append(''.join(section_lines))

    return '\n---\n\n'.join(sections)


# ============================================================================
# Shared context for prompt caching
# ============================================================================

_shared_context_cache: dict[str, list[dict]] = {}


def clear_shared_context_cache() -> None:
    """Clear the in-process shared context cache.

    Call after operations that modify reference files (commits, hone passes)
    so the next build_shared_context reads fresh data.
    """
    _shared_context_cache.clear()


# Minimum tokens per cache breakpoint (estimated at ~4 chars/token)
_MIN_CACHE_CHARS = {
    'opus': 4096 * 4,
    'sonnet': 2048 * 4,
    'haiku': 2048 * 4,
}


def _model_tier(model: str) -> str:
    """Map model name to pricing tier for cache threshold."""
    m = model.lower()
    if 'opus' in m:
        return 'opus'
    if 'haiku' in m:
        return 'haiku'
    return 'sonnet'


def _read_if_exists(path: str) -> str:
    """Read a file if it exists, return empty string otherwise."""
    if not os.path.isfile(path):
        return ''
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError) as e:
        log(f'WARNING: Could not read {path}: {e}')
        return ''


def build_shared_context(project_dir: str, model: str = '') -> list[dict]:
    """Assemble project reference materials as cacheable system blocks.

    Two-tier structure:
    - Tier 1 (1h TTL): Plugin-level references (craft engine, rubrics, AI-tell words)
    - Tier 2 (5m TTL): Project-level references (bibles, voice guide, registries)

    Results are cached in-process so repeated calls don't re-read files.

    Args:
        project_dir: Path to the Storyforge project.
        model: Model ID for determining minimum cache token threshold.

    Returns:
        List of content blocks for the API 'system' parameter.
    """
    cache_key = f'{project_dir}:{model}'
    if cache_key in _shared_context_cache:
        return _shared_context_cache[cache_key]

    plugin_dir = get_plugin_dir()
    min_chars = _MIN_CACHE_CHARS.get(_model_tier(model), 4096 * 4)

    # --- Tier 1: Plugin-level (near-permanent) ---
    tier1_sources = [
        (os.path.join(plugin_dir, 'references', 'craft-engine.md'), 'Craft Engine'),
        (os.path.join(plugin_dir, 'references', 'scoring-rubrics.md'), 'Scoring Rubrics'),
        (os.path.join(plugin_dir, 'references', 'ai-tell-words.csv'), 'AI-Tell Vocabulary'),
    ]

    tier1_blocks = []
    tier1_chars = 0
    for path, label in tier1_sources:
        content = _read_if_exists(path)
        if content:
            tier1_blocks.append({'type': 'text', 'text': f'=== {label} ===\n\n{content}'})
            tier1_chars += len(content) + len(label) + 10

    # --- Tier 2: Project-level (session-stable) ---
    ref_dir = os.path.join(project_dir, 'reference')
    tier2_sources = [
        (os.path.join(ref_dir, 'character-bible.md'), 'Character Bible'),
        (os.path.join(ref_dir, 'world-bible.md'), 'World Bible'),
        (os.path.join(ref_dir, 'voice-guide.md'), 'Voice Guide'),
        (os.path.join(ref_dir, 'voice-profile.csv'), 'Voice Profile'),
        (os.path.join(ref_dir, 'characters.csv'), 'Character Registry'),
        (os.path.join(ref_dir, 'locations.csv'), 'Location Registry'),
        (os.path.join(ref_dir, 'mice-threads.csv'), 'MICE Thread Registry'),
    ]

    tier2_blocks = []
    tier2_chars = 0
    for path, label in tier2_sources:
        content = _read_if_exists(path)
        if content:
            tier2_blocks.append({'type': 'text', 'text': f'=== {label} ===\n\n{content}'})
            tier2_chars += len(content) + len(label) + 10

    # --- Apply cache_control breakpoints ---
    blocks = []

    if tier1_blocks:
        if tier1_chars >= min_chars:
            # Tier 1 meets threshold — add breakpoint with extended TTL
            tier1_blocks[-1]['cache_control'] = {'type': 'ephemeral', 'ttl': '1h'}
        blocks.extend(tier1_blocks)

    if tier2_blocks:
        cumulative_chars = tier1_chars + tier2_chars
        if cumulative_chars >= min_chars:
            # Cumulative prefix meets threshold — add breakpoint with default TTL
            tier2_blocks[-1]['cache_control'] = {'type': 'ephemeral'}
        blocks.extend(tier2_blocks)

    _shared_context_cache[cache_key] = blocks
    return blocks


# ============================================================================
# Pipeline manifest
# ============================================================================

PIPELINE_HEADER = 'cycle|started|status|evaluation|scoring|plan|review|recommendations|summary'


def get_pipeline_file(project_dir: str) -> str:
    return os.path.join(project_dir, 'working', 'pipeline.csv')


def ensure_pipeline_manifest(project_dir: str) -> None:
    pf = get_pipeline_file(project_dir)
    if os.path.isfile(pf):
        return
    os.makedirs(os.path.dirname(pf), exist_ok=True)
    with open(pf, 'w') as f:
        f.write(PIPELINE_HEADER + '\n')


def get_current_cycle(project_dir: str) -> int:
    pf = get_pipeline_file(project_dir)
    if not os.path.isfile(pf):
        return 0
    with open(pf) as f:
        lines = [l.strip() for l in f if l.strip()]
    if len(lines) <= 1:
        return 0
    last = lines[-1].split('|')
    try:
        return int(last[0])
    except (ValueError, IndexError):
        return 0


def read_cycle_field(project_dir: str, cycle_id: int, field: str) -> str:
    from storyforge.csv_cli import get_field
    pf = get_pipeline_file(project_dir)
    if not os.path.isfile(pf):
        return ''
    return get_field(pf, str(cycle_id), field, key_col='cycle')


def start_new_cycle(project_dir: str) -> int:
    ensure_pipeline_manifest(project_dir)
    current = get_current_cycle(project_dir)
    new_id = current + 1
    today = datetime.now().strftime('%Y-%m-%d')
    from storyforge.csv_cli import append_row
    pf = get_pipeline_file(project_dir)
    append_row(pf, f'{new_id}|{today}|pending|||||||')
    return new_id


def update_cycle_field(project_dir: str, cycle_id: int, field: str, value: str) -> None:
    from storyforge.csv_cli import update_field
    pf = get_pipeline_file(project_dir)
    if os.path.isfile(pf):
        update_field(pf, str(cycle_id), field, value, key_col='cycle')


def get_cycle_plan_file(project_dir: str, cycle: int | None = None) -> str:
    if cycle is None:
        cycle = get_current_cycle(project_dir)
    plan_name = read_cycle_field(project_dir, cycle, 'plan')
    if plan_name:
        return os.path.join(project_dir, 'working', 'plans', plan_name)
    return os.path.join(project_dir, 'working', 'plans', 'revision-plan.csv')


def get_cycle_eval_dir(project_dir: str, cycle: int | None = None) -> str:
    if cycle is None:
        cycle = get_current_cycle(project_dir)
    eval_name = read_cycle_field(project_dir, cycle, 'evaluation')
    if eval_name:
        return os.path.join(project_dir, 'working', 'evaluations', eval_name)
    return ''


# ============================================================================
# Chapter map freshness
# ============================================================================

def check_chapter_map_freshness(project_dir: str) -> tuple[bool, list[str], list[str]]:
    """Compare scene IDs in scenes.csv against chapter-map.csv.

    Scenes with status in ('cut', 'merged', 'archived') are excluded.

    Returns:
        (is_fresh, missing_from_map, extra_in_map)
        - is_fresh: True if all active scenes are in the map and vice versa
        - missing_from_map: scene IDs in scenes.csv but not in chapter-map.csv
        - extra_in_map: scene IDs in chapter-map.csv but not in scenes.csv (active)
    """
    from storyforge.csv_cli import get_column

    scenes_csv = os.path.join(project_dir, 'reference', 'scenes.csv')
    chapter_map_csv = os.path.join(project_dir, 'reference', 'chapter-map.csv')

    # Get active scene IDs from scenes.csv
    active_ids = set()
    excluded_statuses = {'cut', 'merged', 'archived'}
    if os.path.isfile(scenes_csv):
        all_ids = get_column(scenes_csv, 'id')
        all_statuses = get_column(scenes_csv, 'status')
        for sid, status in zip(all_ids, all_statuses):
            if sid and status.strip().lower() not in excluded_statuses:
                active_ids.add(sid.strip())

    # Get scene IDs from chapter-map.csv
    map_ids = set()
    if os.path.isfile(chapter_map_csv):
        scenes_col = get_column(chapter_map_csv, 'scenes')
        for cell in scenes_col:
            for sid in cell.split(';'):
                sid = sid.strip()
                if sid:
                    map_ids.add(sid)

    missing_from_map = sorted(active_ids - map_ids)
    extra_in_map = sorted(map_ids - active_ids)
    is_fresh = len(missing_from_map) == 0 and len(extra_in_map) == 0

    return is_fresh, missing_from_map, extra_in_map


# ============================================================================
# Signal handling
# ============================================================================

_child_pids: list[int] = []
_shutting_down = False


def is_shutting_down() -> bool:
    return _shutting_down


def register_child_pid(pid: int) -> None:
    _child_pids.append(pid)


def unregister_child_pid(pid: int) -> None:
    try:
        _child_pids.remove(pid)
    except ValueError:
        pass


def _handle_interrupt(signum, frame):
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True

    log('INTERRUPTED — shutting down gracefully...')

    killed = 0
    for pid in _child_pids:
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except OSError:
            pass

    if killed:
        log(f'Sent SIGTERM to {killed} background process(es). Waiting up to 5s...')
        deadline = time.time() + 5
        while time.time() < deadline:
            still_running = sum(1 for p in _child_pids if _pid_alive(p))
            if not still_running:
                break
            time.sleep(0.5)

        for pid in _child_pids:
            if _pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                    log(f'Force-killed process {pid}')
                except OSError:
                    pass

    log('Shutdown complete.')
    sys.exit(130)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def install_signal_handlers():
    """Install SIGINT/SIGTERM handlers. Call at script startup."""
    signal.signal(signal.SIGINT, _handle_interrupt)
    signal.signal(signal.SIGTERM, _handle_interrupt)


# ============================================================================
# Interactive mode helpers
# ============================================================================

def show_interactive_banner(subtitle: str, mode: str = 'single') -> None:
    """Display the interactive mode banner."""
    w = 60
    lines = [
        f'INTERACTIVE MODE - {subtitle}',
        '',
        'You can watch, give feedback, or redirect Claude.',
        'When done with this step, type /exit to continue.',
    ]
    if mode == 'multi':
        lines.append('Say "finish without me" to run the rest autonomously.')

    print()
    print('╔' + '═' * w + '╗')
    for line in lines:
        print(f'║  {line:<{w - 4}}  ║')
    print('╚' + '═' * w + '╝')
    print()


def offer_interactive(project_dir: str, step_label: str) -> bool:
    """Between steps, offer the user a chance to go interactive.

    Returns True if user pressed 'i', False otherwise.
    """
    timeout = int(os.environ.get('STORYFORGE_REJOIN_TIMEOUT', '5'))
    interactive_file = os.path.join(project_dir, 'working', '.interactive')

    print(f'\n  Next: {step_label}. Press \'i\' for interactive, or wait {timeout}s... ', end='', flush=True)

    import select as sel
    ready, _, _ = sel.select([sys.stdin], [], [], timeout)
    print()

    if ready:
        key = sys.stdin.read(1)
        if key.lower() == 'i':
            Path(interactive_file).touch()
            print('  Switching to interactive mode.')
            return True

    return False


# ============================================================================
# Medium
# ============================================================================

def get_medium(project_dir: str) -> str:
    """Return the project's medium: 'novel' (default) or 'graphic-novel'.

    Reads `project.medium` from storyforge.yaml. Unknown values fall back
    to 'novel' with a logged warning rather than failing — old projects
    without the field stay valid.
    """
    value = read_yaml_field('project.medium', project_dir)
    if not value:
        return 'novel'
    value = value.strip().lower()
    if value in ('novel', 'graphic-novel'):
        return value
    log(f"Warning: project.medium='{value}' is not a recognized value; defaulting to 'novel'")
    return 'novel'


# ============================================================================
# Text comparison
# ============================================================================

def normalize_for_comparison(text: str) -> str:
    """Normalize text for drift/equality comparison. Strips outer whitespace,
    strips leading and trailing whitespace per line, and collapses internal
    blank-line runs so cosmetic whitespace shifts (indentation drift from
    a formatter, stray blank line, trailing-space drift) don't surface as
    drift."""
    lines = [ln.strip() for ln in text.strip().splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if not ln:
            if not blank:
                out.append('')
            blank = True
        else:
            out.append(ln)
            blank = False
    return '\n'.join(out)


def csv_safe(text: str) -> str:
    """Collapse *text* onto one physical line with no `|`.

    Finding `detail` strings land in the unquoted pipe-delimited
    `working/cleanup-report.csv` (`cmd_cleanup._write_report`), one row per
    newline and one column per `|`. Anything interpolated into a `detail` from
    author prose — anchor text, an evidence quote, a heading lifted out of a
    canon file — must pass through this first.

    A stray `|` is not cosmetic: it shifts every later field one column right,
    so the trailing `status` cell (which `build_cleanup_report` sets to
    `pending` for every actionable finding) reads as empty, and the
    `status=pending` scan in `skills/forge/SKILL.md` walks straight past the
    finding. A report row that silences its own finding is worse than no row.

    Lives here rather than in `illustrations` so `canon` can reach it —
    `illustrations` imports `canon`, so the reverse would be circular.
    """
    return ' '.join(text.split()).replace('|', '/')


def build_interactive_system_prompt(project_dir: str, work_unit: str = 'step') -> str:
    """Build system prompt appendix for interactive mode."""
    interactive_file = os.path.join(project_dir, 'working', '.interactive')
    return f"""You are in interactive mode, managed by a script that loops over {work_unit}s one at a time.

RULES:
- Complete THIS {work_unit} ONLY. Do not proceed to the next {work_unit} — the script handles sequencing.
- When this {work_unit} is done, tell the user it is complete and wait for them to respond.
- The user may give you feedback, ask for changes, or say they are satisfied.
- When the user is done with this {work_unit}, they will type /exit to move on.

AUTOPILOT:
- If the user says 'autopilot the rest', 'go autonomous', 'finish without me', 'go auto', 'auto mode', or similar:
  1. Run: rm -f {interactive_file}
  2. Tell them: 'Switching to autopilot — the remaining {work_unit}s will run autonomously. Type /exit to continue.'
- Do NOT exit on your own. The user types /exit when ready."""

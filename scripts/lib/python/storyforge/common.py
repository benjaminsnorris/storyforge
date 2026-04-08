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


def _strip_yaml_value(val: str) -> str:
    """Strip quotes and trailing whitespace from a YAML value."""
    val = val.strip()
    if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
        val = val[1:-1]
    return val


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

_MODEL_MAP = {
    'drafting': 'claude-opus-4-6',
    'revision': 'claude-opus-4-6',
    'mechanical': 'claude-sonnet-4-6',
    'evaluation': 'claude-sonnet-4-6',
    'extraction': 'claude-haiku-4-5-20251001',
    'synthesis': 'claude-opus-4-6',
    'review': 'claude-sonnet-4-6',
}


def select_model(task_type: str) -> str:
    """Select the appropriate model for a task type.

    STORYFORGE_MODEL env var overrides all.
    """
    override = os.environ.get('STORYFORGE_MODEL')
    if override:
        return override
    return _MODEL_MAP.get(task_type, 'claude-opus-4-6')


def select_revision_model(pass_name: str, purpose: str = '') -> str:
    """Select model for a revision pass.

    Creative passes get Opus, mechanical passes get Sonnet.
    """
    override = os.environ.get('STORYFORGE_MODEL')
    if override:
        return override

    key = f'{pass_name} {purpose}'.lower()
    if re.search(r'continuity|timeline|fact.check|thread.track', key):
        return 'claude-sonnet-4-6'
    return 'claude-opus-4-6'


# ============================================================================
# Coaching level
# ============================================================================

def get_coaching_level(project_dir: str | None = None) -> str:
    """Get coaching level: full, coach, or strict.

    Priority: STORYFORGE_COACHING env > storyforge.yaml > 'full'
    """
    env = os.environ.get('STORYFORGE_COACHING')
    if env:
        return env

    if project_dir:
        level = read_yaml_field('project.coaching_level', project_dir)
        if level in ('full', 'coach', 'strict'):
            return level

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

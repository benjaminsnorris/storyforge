"""Simplified cost tracking for Storyforge.

Replaces scripts/lib/costs.sh and the duplicate cost logic in api.py.
Key simplification: one ledger row per operation, not per API call.

Ledger format (pipe-delimited):
    timestamp|operation|model|input_tokens|output_tokens|cost_usd|duration_s
"""

import os
import sys
from datetime import datetime


# ============================================================================
# Pricing (per million tokens, env-overridable)
# ============================================================================

PRICING = {
    'opus':   {'input': 15.00, 'output': 75.00, 'cache_read': 1.50, 'cache_create': 18.75},
    'sonnet': {'input': 3.00,  'output': 15.00, 'cache_read': 0.30, 'cache_create': 3.75},
    'haiku':  {'input': 0.80,  'output': 4.00,  'cache_read': 0.08, 'cache_create': 1.00},
}

LEDGER_HEADER = 'timestamp|operation|target|model|input_tokens|output_tokens|cache_read|cache_create|cost_usd|duration_s'

# Output tokens per scope item, by operation type (for estimates)
_OUTPUT_PER_ITEM = {
    'draft': 1500,
    'write': 1500,
    'evaluate': 2000,
    'revise': 1000,
    'score': 800,
}
_DEFAULT_OUTPUT_PER_ITEM = 1500


def _detect_tier(model: str) -> str:
    """Map a model name to a pricing tier."""
    m = model.lower()
    if 'opus' in m:
        return 'opus'
    if 'haiku' in m:
        return 'haiku'
    return 'sonnet'


def _get_price(model: str, token_type: str) -> float:
    """Get per-million-token price, checking env overrides first."""
    tier = _detect_tier(model)
    env_key = f'PRICING_{tier.upper()}_{token_type.upper()}'
    env_val = os.environ.get(env_key)
    if env_val:
        return float(env_val)
    return PRICING[tier][token_type]


# ============================================================================
# Core functions
# ============================================================================

def calculate_cost(model: str, input_tokens: int, output_tokens: int,
                   cache_read: int = 0, cache_create: int = 0) -> float:
    """Calculate cost in USD from token counts.

    Cache tokens are folded into the cost but not tracked separately
    in the ledger — they affect the dollar amount only.
    """
    cost = 0.0
    cost += input_tokens * _get_price(model, 'input') / 1_000_000
    cost += output_tokens * _get_price(model, 'output') / 1_000_000
    cost += cache_read * _get_price(model, 'cache_read') / 1_000_000
    cost += cache_create * _get_price(model, 'cache_create') / 1_000_000
    return cost


def log_operation(project_dir: str, operation: str, model: str,
                  input_tokens: int, output_tokens: int, cost: float,
                  duration_s: int = 0, target: str = '',
                  cache_read: int = 0, cache_create: int = 0) -> None:
    """Append one row to the ledger CSV.

    Full format matching bash costs.sh: includes target, cache_read, cache_create.
    """
    ledger_file = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')
    os.makedirs(os.path.dirname(ledger_file), exist_ok=True)

    if not os.path.exists(ledger_file):
        with open(ledger_file, 'w') as f:
            f.write(LEDGER_HEADER + '\n')

    timestamp = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    row = f"{timestamp}|{operation}|{target}|{model}|{input_tokens}|{output_tokens}|{cache_read}|{cache_create}|{cost:.6f}|{duration_s}"

    with open(ledger_file, 'a') as f:
        f.write(row + '\n')


def estimate_cost(operation: str, scope_count: int, avg_words: int,
                  model: str) -> float:
    """Forecast cost for an operation.

    Input tokens ~ scope_count * (avg_words * 1.3 + 3000 overhead)
    Output tokens ~ scope_count * per-item estimate (varies by operation)
    """
    output_per_item = _OUTPUT_PER_ITEM.get(operation, _DEFAULT_OUTPUT_PER_ITEM)

    input_tokens = scope_count * (avg_words * 1.3 + 3000)
    output_tokens = scope_count * output_per_item

    price_in = _get_price(model, 'input')
    price_out = _get_price(model, 'output')

    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def print_summary(project_dir: str, operation: str | None = None) -> None:
    """Print cost totals from the ledger, optionally filtered by operation."""
    ledger_file = os.path.join(project_dir, 'working', 'costs', 'ledger.csv')

    if not os.path.exists(ledger_file):
        print('No cost data available.')
        return

    count = 0
    total_input = 0
    total_output = 0
    total_cache_r = 0
    total_cache_c = 0
    total_cost = 0.0
    total_dur = 0

    with open(ledger_file) as f:
        header = f.readline()  # skip header
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            if len(parts) < 10:
                # Old format (7 cols) — handle gracefully
                if len(parts) >= 7:
                    row_op = parts[1]
                    if operation and row_op != operation:
                        continue
                    count += 1
                    total_input += int(parts[3])
                    total_output += int(parts[4])
                    total_cost += float(parts[5])
                    total_dur += int(parts[6])
                continue

            row_op = parts[1]
            if operation and row_op != operation:
                continue

            count += 1
            total_input += int(parts[4])
            total_output += int(parts[5])
            total_cache_r += int(parts[6])
            total_cache_c += int(parts[7])
            total_cost += float(parts[8])
            total_dur += int(parts[9])

    if count == 0:
        label = f' for operation: {operation}' if operation else ''
        print(f'No cost data{label}.')
        return

    label = operation or 'all operations'
    print(f'--- Cost Summary: {label} ---')
    print(f'Invocations:   {count}')
    print(f'Input tokens:  {total_input}')
    print(f'Output tokens: {total_output}')
    print(f'Cache read:    {total_cache_r}')
    print(f'Cache create:  {total_cache_c}')
    print(f'Total cost:    ${total_cost:.4f}')
    print(f'Total time:    {total_dur}s')


def check_threshold(estimated_cost: float, threshold: float = 100.0) -> bool:
    """Check whether estimated cost is within threshold.

    Returns True if OK to proceed, False if over threshold.
    Uses STORYFORGE_COST_THRESHOLD env var if set.
    """
    threshold = float(os.environ.get('STORYFORGE_COST_THRESHOLD', threshold))
    return estimated_cost <= threshold


# ============================================================================
# CLI interface
# ============================================================================

def main():
    """CLI entry point.

    python3 -m storyforge.costs log <project_dir> <operation> <model> <input_tokens> <output_tokens> <cost> [duration]
    python3 -m storyforge.costs estimate <operation> <scope_count> <avg_words> <model>
    python3 -m storyforge.costs summary <project_dir> [operation]
    python3 -m storyforge.costs check <estimated_cost> [threshold]
    """
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.costs <command> [args]', file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'log':
        if len(sys.argv) < 8:
            print('Usage: ... log <project_dir> <operation> <model> <input_tokens> <output_tokens> <cost> [duration]',
                  file=sys.stderr)
            sys.exit(1)
        project_dir = sys.argv[2]
        operation = sys.argv[3]
        model = sys.argv[4]
        input_tokens = int(sys.argv[5])
        output_tokens = int(sys.argv[6])
        cost = float(sys.argv[7])
        duration = int(sys.argv[8]) if len(sys.argv) > 8 else 0
        log_operation(project_dir, operation, model, input_tokens, output_tokens, cost, duration)
        print('ok')

    elif command == 'estimate':
        if len(sys.argv) < 6:
            print('Usage: ... estimate <operation> <scope_count> <avg_words> <model>',
                  file=sys.stderr)
            sys.exit(1)
        operation = sys.argv[2]
        scope_count = int(sys.argv[3])
        avg_words = int(sys.argv[4])
        model = sys.argv[5]
        cost = estimate_cost(operation, scope_count, avg_words, model)
        print(f'{cost:.2f}')

    elif command == 'summary':
        if len(sys.argv) < 3:
            print('Usage: ... summary <project_dir> [operation]', file=sys.stderr)
            sys.exit(1)
        project_dir = sys.argv[2]
        operation = sys.argv[3] if len(sys.argv) > 3 else None
        print_summary(project_dir, operation)

    elif command == 'check':
        if len(sys.argv) < 3:
            print('Usage: ... check <estimated_cost> [threshold]', file=sys.stderr)
            sys.exit(1)
        estimated = float(sys.argv[2])
        threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0
        ok = check_threshold(estimated, threshold)
        print('ok' if ok else 'over')
        sys.exit(0 if ok else 1)

    else:
        print(f'Unknown command: {command}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

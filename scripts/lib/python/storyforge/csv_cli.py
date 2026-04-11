"""Pipe-delimited CSV operations.

Provides both programmatic API (functions return values) and CLI interface
(python3 -m storyforge.csv_cli <command>).

Commands:
    get-field <file> <id> <field> [key_column]
    get-row <file> <id> [key_column]
    get-column <file> <field>
    list-ids <file>
    update-field <file> <id> <field> <value> [key_column]
    append-row <file> <row>
    renumber-seq <file>
"""

import os
import sys

DELIMITER = '|'


def _read_lines(path):
    """Read file lines, stripping \\r and trailing whitespace.

    Reads the entire file and normalises all line endings (CRLF and stray
    ``\\r`` characters embedded by awk-based CSV edits) before splitting.
    """
    with open(path, newline='', encoding='utf-8') as f:
        raw = f.read().replace('\r\n', '\n').replace('\r', '')
    return raw.splitlines()


def _write_lines(path, lines):
    """Write lines atomically (write to temp, then rename)."""
    tmp = path + f'.tmp.{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(line + '\n')
    os.replace(tmp, path)


def get_field(path, row_id, field, key_col='id'):
    """Return a single field value for a given ID. Returns '' if not found."""
    if not os.path.isfile(path):
        return ''
    lines = _read_lines(path)
    if not lines:
        return ''
    headers = lines[0].split(DELIMITER)
    try:
        fcol = headers.index(field)
        kcol = headers.index(key_col)
    except ValueError:
        return ''
    for line in lines[1:]:
        fields = line.split(DELIMITER)
        if kcol < len(fields) and fields[kcol] == row_id:
            if fcol < len(fields):
                return fields[fcol]
            return ''
    return ''


def get_row(path, row_id, key_col='id'):
    """Return all fields for a given ID as a pipe-delimited string. Returns '' if not found."""
    if not os.path.isfile(path):
        return ''
    lines = _read_lines(path)
    if not lines:
        return ''
    headers = lines[0].split(DELIMITER)
    try:
        kcol = headers.index(key_col)
    except ValueError:
        return ''
    for line in lines[1:]:
        fields = line.split(DELIMITER)
        if kcol < len(fields) and fields[kcol] == row_id:
            return line
    return ''


def get_column(path, field):
    """Return all values for a given column as a list. Returns [] if not found."""
    if not os.path.isfile(path):
        return []
    lines = _read_lines(path)
    if not lines:
        return []
    headers = lines[0].split(DELIMITER)
    try:
        col = headers.index(field)
    except ValueError:
        return []
    result = []
    for line in lines[1:]:
        fields = line.split(DELIMITER)
        if col < len(fields):
            result.append(fields[col])
    return result


def list_ids(path):
    """Return all IDs (first column) as a list. Returns [] if not found."""
    if not os.path.isfile(path):
        return []
    lines = _read_lines(path)
    result = []
    for line in lines[1:]:
        fields = line.split(DELIMITER)
        if fields:
            result.append(fields[0])
    return result


def update_field(path, row_id, field, value, key_col='id'):
    """Update a single field for a given ID. Atomic write."""
    if not os.path.isfile(path):
        return
    lines = _read_lines(path)
    if not lines:
        return
    headers = lines[0].split(DELIMITER)
    try:
        fcol = headers.index(field)
        kcol = headers.index(key_col)
    except ValueError:
        return
    out = [lines[0]]
    for line in lines[1:]:
        fields = line.split(DELIMITER)
        if kcol < len(fields) and fields[kcol] == row_id:
            # Extend fields if needed
            while len(fields) <= fcol:
                fields.append('')
            fields[fcol] = value
            out.append(DELIMITER.join(fields))
        else:
            out.append(line)
    _write_lines(path, out)


def append_row(path, row):
    """Append a pipe-delimited row to the file."""
    with open(path, 'a', encoding='utf-8') as f:
        f.write(row + '\n')


def renumber_seq(path):
    """Renumber the seq column sequentially from 1."""
    lines = _read_lines(path)
    if not lines:
        return
    headers = lines[0].split(DELIMITER)
    try:
        seq_col = headers.index('seq')
    except ValueError:
        return
    # Parse and sort by current seq
    rows = []
    for line in lines[1:]:
        fields = line.split(DELIMITER)
        try:
            seq_val = int(fields[seq_col]) if seq_col < len(fields) else 0
        except ValueError:
            seq_val = 0
        rows.append((seq_val, fields))
    rows.sort(key=lambda r: r[0])
    # Renumber
    out = [lines[0]]
    for i, (_, fields) in enumerate(rows, 1):
        while len(fields) <= seq_col:
            fields.append('')
        fields[seq_col] = str(i)
        out.append(DELIMITER.join(fields))
    _write_lines(path, out)


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 -m storyforge.csv_cli <command> [args]',
              file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'get-field':
        if len(sys.argv) < 5:
            print('Usage: get-field <file> <id> <field> [key_column]',
                  file=sys.stderr)
            sys.exit(1)
        key_col = sys.argv[5] if len(sys.argv) > 5 else 'id'
        result = get_field(sys.argv[2], sys.argv[3], sys.argv[4], key_col)
        if result:
            print(result)

    elif cmd == 'get-row':
        if len(sys.argv) < 4:
            print('Usage: get-row <file> <id> [key_column]', file=sys.stderr)
            sys.exit(1)
        key_col = sys.argv[4] if len(sys.argv) > 4 else 'id'
        result = get_row(sys.argv[2], sys.argv[3], key_col)
        if result:
            print(result)

    elif cmd == 'get-column':
        if len(sys.argv) < 4:
            print('Usage: get-column <file> <field>', file=sys.stderr)
            sys.exit(1)
        for val in get_column(sys.argv[2], sys.argv[3]):
            print(val)

    elif cmd == 'list-ids':
        if len(sys.argv) < 3:
            print('Usage: list-ids <file>', file=sys.stderr)
            sys.exit(1)
        for val in list_ids(sys.argv[2]):
            print(val)

    elif cmd == 'update-field':
        if len(sys.argv) < 6:
            print('Usage: update-field <file> <id> <field> <value> [key_column]',
                  file=sys.stderr)
            sys.exit(1)
        key_col = sys.argv[6] if len(sys.argv) > 6 else 'id'
        update_field(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], key_col)

    elif cmd == 'append-row':
        if len(sys.argv) < 4:
            print('Usage: append-row <file> <row>', file=sys.stderr)
            sys.exit(1)
        append_row(sys.argv[2], sys.argv[3])

    elif cmd == 'renumber-seq':
        if len(sys.argv) < 3:
            print('Usage: renumber-seq <file>', file=sys.stderr)
            sys.exit(1)
        renumber_seq(sys.argv[2])

    else:
        print(f'Unknown command: {cmd}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

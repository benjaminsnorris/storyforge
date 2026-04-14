#!/bin/bash
# Run Storyforge test suite with coverage.
#
# Usage:
#   ./tests/run-tests.sh              # Run with coverage (default)
#   ./tests/run-tests.sh --no-cov     # Run without coverage
#   ./tests/run-tests.sh -k pattern   # Pass args through to pytest
cd "$(dirname "$0")/.."

if [ "$1" = "--no-cov" ]; then
    shift
    python3 -m pytest tests/ --no-cov "$@"
else
    python3 -m pytest tests/ "$@"
fi

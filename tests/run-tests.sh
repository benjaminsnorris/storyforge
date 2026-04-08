#!/bin/bash
cd "$(dirname "$0")/.."
if [ "$1" = "--coverage" ]; then
    python3 -m pytest tests/ --cov=scripts/lib/python/storyforge --cov-report=term-missing
else
    python3 -m pytest tests/ "$@"
fi

"""storyforge reconcile — Backwards-compatible wrapper for storyforge hone.

All reconciliation logic lives in cmd_hone.
"""

import sys

from storyforge.cmd_hone import main as hone_main


def main(argv=None):
    hone_main(argv)

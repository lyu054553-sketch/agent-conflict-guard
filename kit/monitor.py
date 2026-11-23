#!/usr/bin/env python3
"""Entry point installed into a project at scripts/agents/monitor.py.

The kit scripts and the Claude Code hook call this file; it runs the bundled
conflict_guard package that install.sh copies next to it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conflict_guard.cli import main  # noqa: E402

main()

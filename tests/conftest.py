"""Shared fixtures for investing tests."""

import os
import sys

# Add scripts/ to path so `from common.X import Y` works
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

# Add scripts/tools/ to path so tool modules can be imported directly
TOOLS_DIR = os.path.join(SCRIPTS_DIR, "tools")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

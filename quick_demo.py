"""Roundtable Demo — 3 lines of code, full discussion flow.

Usage:
    python quick_demo.py

This demonstrates the complete Roundtable workflow:
  1. Create a discussion with participants
  2. Run multi-round speeches with convergence tracking
  3. Generate conclusion with consensus/disagreement summary
"""

import os
import tempfile
from pathlib import Path

from roundtable import RoundtableCore, RoundtableDB

db_path = os.environ.get("ROUNDTABLE_DB")
if db_path is None:
    db_path = str(Path(tempfile.gettempdir()) / "roundtable-demo.db")

core = RoundtableCore(RoundtableDB(db_path))
result = core.run_demo()

print("\nDemo complete")
print(f"Discussion ID: {result['discussion_id']}")
print(f"Web status: {result.get('web_status')}")
if result.get("web_url"):
    print(f"Web viewer: {result['web_url']}")
elif result.get("web_error"):
    print(f"Web error: {result['web_error']}")
    print(result.get("web_help", ""))

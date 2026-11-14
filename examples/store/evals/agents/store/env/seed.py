"""The `seed` hook: put the world into the case's start_state before every attempt."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import store_world  # noqa: E402

case = json.load(sys.stdin)
store_world.path().write_text(json.dumps(case.get("start_state") or {}))

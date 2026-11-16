"""The `observe` hook: print the world (orders, refunds, returns and the log of calls) as JSON."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import store_world  # noqa: E402

sys.stdout.write(json.dumps(store_world.load(), sort_keys=True))

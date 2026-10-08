import json
import os
import sys
from pathlib import Path

case = json.load(sys.stdin)
Path(os.environ.get("WORLD_FILE", "world.json")).write_text(json.dumps(case["start_state"]))

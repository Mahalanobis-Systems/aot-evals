import os
import sys
from pathlib import Path

sys.stdout.write(Path(os.environ.get("WORLD_FILE", "world.json")).read_text())

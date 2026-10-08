"""A stand-in generative judge: right about nine times in ten, deterministically."""
import hashlib
import json
import re
import sys

req = json.load(sys.stdin)
out = req["input"].get("end.output") or ""
ok = bool(re.search(r"\d{2}:\d{2}", out))
if int(hashlib.sha256(out.encode()).hexdigest(), 16) % 10 == 0:
    ok = not ok
print(json.dumps({"verdict": "pass" if ok else "fail", "reasoning": "looked for a time", "cost": 0.002}))

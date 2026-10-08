"""A toy calendar agent speaking the aot-evals agent contract (references/agent-contract.md).

AGENT_VARIANT selects a self-test behaviour:
  good    books the requested meeting
  liar    claims success without changing anything
  flaky   books the wrong time on some trials
  costly  same as good, at 3x the cost
  slow    hangs past the timeout on about a third of attempts
  terse   books correctly, but half the replies leave out the date and time
  silent  prints nothing, like an agent whose model provider has stopped answering
  peek    searches its working directory for its own case file, as a coding harness might; if it
          finds one it says so and leaves a mark in it
AGENT_BREAK (comma-separated case ids) books the wrong time on exactly those cases, in any variant:
a second agent version that differs from the first on a known set of cases (redundancy, C15).
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

WORLD = Path(os.environ.get("WORLD_FILE", "world.json"))
VARIANT = os.environ.get("AGENT_VARIANT", "good")
BREAK = {c for c in os.environ.get("AGENT_BREAK", "").split(",") if c}
REQUEST = re.compile(r"Book '(?P<title>[^']+)' on (?P<date>\d{4}-\d{2}-\d{2}) at (?P<time>\d{2}:\d{2})")


def bucket(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest(), 16) % 6


def main() -> None:
    case = json.load(sys.stdin)
    if VARIANT == "silent":
        return
    if VARIANT == "peek":
        for found in Path(".").rglob(f"{case['case_id']}.json"):
            with found.open("a") as f:
                f.write("\n")
            print(json.dumps({"answer": f"Read the expected answer in {found}.", "model_ids": {"main": "toy-model-1"}}))
            return
    cost = 0.002 * (3 if VARIANT == "costly" else 1)
    usage = {"tokens_input": 900, "tokens_output": 60, "tokens_cached": 600, "cost": cost, "tool_calls": 1}
    if VARIANT == "slow" and bucket(case["case_id"], case["trial"], case["attempt"]) < 2:
        time.sleep(30)
    m = REQUEST.search(case["question"])
    if VARIANT == "liar":
        print(json.dumps({"answer": "Done, booked successfully.", "usage": usage,
                          "model_ids": {"main": "toy-model-1"}}))
        return
    if not m:
        print(json.dumps({"answer": "Nothing to do.", "usage": {**usage, "tool_calls": 0},
                          "model_ids": {"main": "toy-model-1"}}))
        return
    event = m.groupdict()
    if VARIANT == "flaky" and case["trial"] == "1" and bucket(case["case_id"]) % 2 == 0:
        event["time"] = "09:00"
    if case["case_id"] in BREAK:
        event["time"] = "09:00"
    world = json.loads(WORLD.read_text())
    world["events"].append(event)
    WORLD.write_text(json.dumps(world))
    answer = f"Booked {event['title']} on {event['date']} at {event['time']}."
    if VARIANT == "terse" and bucket(case["case_id"]) % 2 == 0:
        answer = f"Booked {event['title']}."
    print(json.dumps({"answer": answer, "usage": usage,
                      "model_ids": {"main": "toy-model-1"}}))


main()

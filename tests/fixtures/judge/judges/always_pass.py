"""The always-pass self-test judge: agrees with every passing label and catches nothing."""
import json
import sys

json.load(sys.stdin)
print(json.dumps({"verdict": "pass", "reasoning": "looks fine", "cost": 0.0001}))

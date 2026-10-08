---
id: reply-states-time
failure_mode: reply-omits-time
version: 1
question_type: noul
question: The reply tells the user the date and time of the meeting that was booked.
detects: pass
inputs: [end.output, case.inputs.event]
mode: binary
primary: so
backends:
  so:     {type: systemone, model: jev-test, family: typesafe, base_url: "{FAKE_URL}"}
  llm:    {type: command, command: ["{PYTHON}", judges/fake_llm.py], model: fake-llm-1, family: fake-llm}
  always: {type: command, command: ["{PYTHON}", judges/always_pass.py], model: always-pass, family: rubber-stamp}
---

Pass when the reply states both the date and the time of the booked meeting. A reply that only
says the meeting was booked fails.

---
id: <check-id>                 # must match the file name
failure_mode: <failure-mode-id>
version: 1                     # bump on every change to the question, options or inputs
question_type: noul            # noul (a true/false claim) | choice | score
question: <One claim about the output, e.g. "The summary states a figure that does not appear in the source.">
detects: failure               # noul only: a "yes" means the failure is present (failure) or the requirement is met (pass)
# choice:  options: {grounded: "...", invented: "..."}   pass_options: [grounded]
# score:   options: [Poor, Adequate, Good]               pass_min_level: 1
inputs: [end.output, case.inputs.source_document]   # the only fields the judge sees (dotted paths into case / start / end)
mode: binary                   # binary | pairwise (pairwise needs a different family from the agent, G4)
min_tpr: 0.75                  # floors: below either, the judge is uncalibrated and greyed (G3)
min_tnr: 0.75
primary: jev                   # the backend whose verdicts count
backends:
  jev:
    type: systemone            # any POST /v1/systemone endpoint: TypeSafe, OpenCode Zen, a local LAYA server
    model: jev-1.13-free       # free via OpenCode Zen, no key; see references/judge-backends.md
    daily_limit: 250           # the free tier refuses (HTTP 429) after about 250 calls a day per IP;
                               # one calibration pass over a few judges can use it up. Paid: jev-1.13
    family: typesafe
    base_url: https://opencode.ai/zen
  claude:
    type: anthropic            # generative, structured {reasoning, answer}; a different family from the agent
    model: claude-opus-5-5
    family: anthropic
    effort: medium
  # mine:
  #   type: command            # any judge you run yourself; see references/judge-backends.md
  #   command: [python, evals/env/my_judge.py]
  #   model: <id>
  #   family: <family>
---

# <One failure mode, one binary question>

**Pass when.** <A concrete, observable condition.>

**Fail when.** <A concrete, observable condition.>

**Not this judge's job.** <Neighbouring failure modes that other checks cover.>

This body is sent to generative backends as guidance. System One backends see only the
`question` (and `options`). Keep it short and observable.

# Choosing an eval strategy from an agent's properties

Not every agent needs the same kind of eval. Six questions about the agent
decide what to build. Answer them per agent (and often per category within an
agent), then follow the decision procedure at the end.

The "What the research adds" notes below cite
[eval-best-practices](../eval-best-practices.md).

---

## The six questions

### Q1. Is the outcome verifiable?

Can code decide, from the end state, whether the job was done right?

| Answer | Meaning | Eval shape |
|---|---|---|
| **Fully** | The right result is a definite state: a row, an event, an email to X, a file with fields F, a number | State-diff checks. No judge. Grade the end state, not the transcript |
| **Partly** | Some of it is definite (the record exists, the format holds, nothing else changed) and some is judgement (was the summary faithful) | Code checks for the definite part; a narrow judge per subjective part; never a single overall score |
| **Not** | Correctness is a matter of judgement or taste | See Q6 |

Rules of thumb:
- **Side effects outside scope are always verifiable and always count**: a
  changed row that shouldn't change, an email sent without approval, a post in
  the wrong channel. Every agent gets these checks regardless of Q1.
- **Grade outcomes, not paths.** Two different sequences of tool calls that
  reach the right state both pass. Grade the path only where the path *is*
  the requirement (an approval step, a confirmation before a destructive
  action).
- **"Verifiable" is per category.** An agent can have a verifiable "create
  record" category and an unverifiable "advise" category.

**What the research adds.**
- **Never grade from the agent's own report.** In single-control τ²-bench
  domains, 45–48% of failures are the agent confidently claiming success
  while the state says otherwise. Checks diff the real end state (mailbox,
  calendar, repo, sheet), never the chat reply.
- **Write checkers against the goal, not one golden path.** Rule-based
  graders that expect a fixed sequence under-report success
  (AgentRewardBench); state-diff graders don't.
- **Screen cases for validity.** SWE-bench Verified kept 500 of 2,294 tasks
  after human screening; a checklist audit found task-validity flaws in 7 of
  10 agent benchmarks. Every case gets a human read plus a sanity run (a
  reference solution passes, a do-nothing agent fails).
- **Keep some trajectory judging.** Outcome-only judges catch 84% of visible
  faults but 45% of silent ones (an action taken that the goal didn't ask
  for). A step-level judge on a sample, at ~3× cost, catches those.

### Q2. Are you happy with performance? If so, optimize cost or latency?

If quality is acceptable, the eval's job changes: it becomes a **guardrail**
that lets you cut cost or latency without losing what works.

| Situation | Eval shape |
|---|---|
| **Not happy with quality** | Quality eval first (Q1/Q6). Cost and latency are secondary metrics, recorded but not optimized |
| **Happy; cost matters** | A non-regression suite (pass rate must not drop below the current baseline, per category) plus cost per successful task. Then experiments: cheaper model, shorter prompt, skip work when the input is unchanged, cache |
| **Happy; latency matters** | Same suite plus latency per step and per turn (p50/p90), with a budget per category. Experiments: fewer tool calls, parallel steps, early exit |

Which one, cost or latency, depends on who waits:
- **Scheduled runs** (crons): nobody waits. Optimize cost. Latency only
  matters against the wall-clock limit.
- **Person-triggered runs**: someone is waiting for the reply. Optimize latency
  first; cost second.

The baseline must be measured before any change, with enough runs per case to
see variance (pass^k).

**What the research adds.**
- **Freeze a regression suite that passes ~100% today** and re-run it on every
  prompt, skill, tool or model edit; that is the floor cost work may not
  break.
- **Report cost per successful task**, not cost per run, plus per-step
  latency percentiles.
- **Prompt caching is the largest free lever** (cache reads at 0.1× input
  price), but any change to the prompt prefix (system prompt, tool
  definitions, a timestamp) invalidates it. Track cache-hit rate as a
  regression metric.
- **Routing beats ensembles:** sending easy cases to a cheaper model gave
  >2× savings (RouteLLM); majority-vote and self-refine "rarely justify the
  costs".
- **pass^k is unforgiving:** 75% per trial is ~42% pass^3. Decide which
  categories need every run to pass.

### Q3. If performance is fine, what does drift look like, and how is it measured?

Drift is the agent getting worse without anyone changing it on purpose. Causes:
the model behind the API changes; a skill or stored prompt is edited (by a
person or by the agent itself); a tool or API changes; the inputs change
(new kinds of email, a new repo layout); user behaviour changes.

Quantify it with two instruments:

1. **A golden set re-run on a schedule.** A fixed set of cases (from Q1/Q6),
   run weekly and after every prompt, skill, model or harness change. Report
   pass rate per category and pass^k. A drop beyond normal variance is drift.
2. **Online fingerprints from production**, per agent, per week, on a control
   chart: rate of silent turns on addressed asks, time to first reply, turns
   killed at the limit, tokens and cost per turn, tool calls per turn, the
   mix of categories, and any agent-specific outcome rate (approvals acted
   on, records saved, citations valid). A shift outside the usual
   band flags drift before anyone complains.

"Normal" variance has to be measured first: run the golden set several times
on the same build to see the spread before reading any change as drift.

**What the research adds.**
- **Run-to-run noise is large:** temperature-0 accuracy varies by up to 15
  points across runs; 1,000 identical completions produced 80 distinct
  outputs. Only a change outside a k-run confidence interval is drift
  (Anthropic's error-bars guidance).
- **Provider drift is real but bounded:** Anthropic pins weights per model
  ID; serving changes can still shift minor behaviour. The golden set
  catches it; so does logging the model ID per turn.
- **Offline evals and A/B tests can both "look good" while the product gets
  worse** (OpenAI's 2025 sycophancy incident, driven by optimizing
  thumbs-up). Keep a weekly human read of 10–20 outlier traces; treat
  feedback buttons as monitoring inputs, never as the objective.

### Q4. Can a sandbox be built?

A sandbox is a copy of the agent's world where nothing real happens and the
starting state can be set. It is possible when the world is:

| World | Sandbox | How |
|---|---|---|
| A git repo | Yes, trivially | A repo at a commit; grade the diff |
| A structured SaaS API with few endpoints (Calendar, Sheets, a mail subset, a read-only finance API) | Yes | Stateful fakes seeded with recorded responses, behind a proxy |
| A read-only API (GitHub, a finance API's GET endpoints) | Yes | Record and replay real responses |
| The open web | No, but replayable | Record every page a real run fetched; replay; plant items for ground truth |
| A rich editor (Slides, Docs) | Costly | Use a real scratch account instead |
| A person in the loop | Partly | A scripted or simulated user for follow-ups |

A sandbox also needs: a frozen clock, a fresh state per case, the agent's own
files (anything that lives only in its sandbox), and the same model and
harness as production.

**What the research adds.**
- **Fake only what changes state.** Record-and-replay for read-only tools
  (search, free/busy, GitHub, read-only finance endpoints); thin stateful fakes only for
  send/create/commit; scheduled contract tests of each fake against the real
  API so fakes don't drift.
- **Isolate every trial.** Shared state between trials let an agent cheat by
  reading another trial's git history.
- **The simulated user is the weakest part.** Unconstrained LLM users erred
  40–47% of the time (12–13% critical) in τ²-bench; a tool-constrained one
  16% (6%). Swapping the user model moved agent scores by up to 9 points.
  Script the user where possible; when simulating, constrain it with tools
  and ground it in real transcripts, and report scores
  per simulator.
- **Validity compounds:** task × simulator × judge each at 70% ≈ 34% overall.

### Q5. If no sandbox is possible, what then?

The eval moves from *before* deployment to *around* it:

| Method | What it gives |
|---|---|
| **Recorded replay** | Re-run the agent against the tool outputs a real run saw. Not a true sandbox (the agent can't take a different path), but catches regressions on the recorded path |
| **Shadow runs** | Run a candidate build on live inputs alongside production; compare outputs; nothing from the candidate is delivered |
| **Canary** | Roll the change to one channel or a fraction of runs; watch the online fingerprints |
| **Online judging** | A narrow judge scores a sample of live outputs on fixed criteria; trend it |
| **Human spot checks** | A statistically sized sample reviewed each week in a trace review tool |
| **Feedback capture** | Reactions, corrections, re-asks and edits after output, as labels |

Without a sandbox, "eval" mostly means **monitoring with a fixed instrument**,
and every change must be reversible.

**What the research adds.**
- **Shadow mode before write access:** the agent states what it would do; a
  judge compares it with what the human did. Ramp staged its agent this way
  (99% "improved", 25% rejection rate) before letting it act.
- **Online judge sampling rates:** 1–10% of traffic at high volume, 50–100%
  at low volume (Braintrust). For a low-volume agent, judge everything.
- **The best production labels are behavioural:** edits made after the
  output (edit distance), acceptance rate, follow-up corrections and
  re-asks. Capture them; they cost nothing.

### Q6. Are outputs too subjective to judge? If so, what criteria can be specified instead?

"Quality 1–10" from a judge is not an eval. Replace it with **specified
criteria**: statements that are true or false of an output, each checkable
by code or answerable by a narrow judge.

| Approach | When |
|---|---|
| **Criteria checklist** | Most cases. "Every claim has a source", "no personal details", "under N words", "mentions the two options". Each item is pass/fail; the score is the count |
| **Reference-guided judging** | When a gold answer exists (a human-written note, a known list of action items): grade against it with precision and recall |
| **Pairwise comparison** | When only "better or worse" is definable: compare candidate vs baseline output, swapping order to cancel position bias |
| **Human labels as the standard** | Always calibrate the judge: measure agreement with human labels on the same items before trusting it, and re-check after any judge change |
| **Monitor only** | When no criteria can be written that the owner would sign off on. Then the output is not evaluated; it is watched (Q5), and the owner's reactions are the signal |

The test for "too subjective": can the agent's owner write down what a good
output must contain and must not contain? If yes, it's criteria. If no, it's
monitor-only until they can.

**What the research adds.**
- **One binary judge per failure mode**, each with its own labelled set:
  plan 100–200 human labels per failure mode, and report true-positive and
  true-negative rates, not raw agreement (Hamel & Shankar). Fewer than ~60
  labels gives intervals too wide to act on.
- **Binary beats Likert:** "the difference between 3 and 4 is subjective".
  A 1–10 outcome-quality score is a triage signal for humans, not a judge
  target.
- **Judge with a different model family** than the agent: self-preference
  correlates with self-recognition. Good judges reach ~80% agreement with
  humans, which is also the human–human ceiling.
- **Pairwise needs position swapping** (position bias 50–70% without it).
  Use pairwise plus edit distance to *trend* subjective outputs (drafts,
  summaries, syntheses) rather than score them absolutely.
- **Rubrics drift as you grade** (EvalGen): version the criteria, and
  re-calibrate after any change.
- 82% of 55 agent-eval papers reported broken inter-rater statistics:
  compute and publish judge–human reliability per agent.

---

## Decision procedure

For each agent, per category:

```
Q1 verifiable?
  fully  → state-diff checks; sandbox if Q4 allows, else recorded replay
  partly → code checks for the definite part + criteria (Q6) for the rest
  not    → Q6: criteria checklist / reference-guided / pairwise; else monitor-only

Q4 sandbox possible?
  yes → build it; cases = translations of reviewed traces + variants
  no  → Q5: recorded replay + shadow/canary + online judging + spot checks

Q2 happy with quality?
  no  → quality eval is the priority; record cost and latency
  yes → non-regression suite as a guardrail; optimize cost (scheduled) or latency (person-triggered)

Q3 for every agent, regardless:
  golden set re-run weekly and on every change; online fingerprints on a control chart
```

Two cross-cutting rules, plus three the research insists on:
- **Side-effect checks for everyone** (nothing changed outside scope, nothing
  sent without approval).
- **Conversation-behaviour checks for every chat agent** (addressed asks get a
  reply; people talking to each other don't; replies in the agent's own
  threads get a turn).
- **A frozen regression suite re-run on every edit**, with k runs and error
  bars; single-run scores mean little.
- **State-diff grading only**; never grade from what the agent said it did.
- **Every judge is binary, per failure mode, calibrated on 100–200 human
  labels, and from a different model family than the agent.**

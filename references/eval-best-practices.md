# Eval practice: findings from the 2025–2026 literature

What the literature says about evaluating production LLM agents. Single-author 2026 preprints
are marked as such in the source list: directional, not settled.

Citations are short tags like [Anthropic 2026]; each resolves to an entry under
[Sources](#sources).

## 1. Verifiability

**Finding.** Grade the end state with code wherever the task leaves one, and
grade it against the *goal*, not one expected path: rule-based checkers that
expect a fixed sequence under-report success, and agents find valid paths the
author didn't anticipate [Anthropic 2026, AgentRewardBench]. Never take the
agent's own report as the signal: 45–48% of failures in comparable
single-control benchmarks were the agent confidently claiming success while
the state said otherwise [False success]. Keep trajectory judging for hard
constraints (a required approval before a destructive step) and for silent
faults: outcome-only judges caught 84% of user-visible faults but only 45% of
silent ones [trajectory-judge]. "Verifiable" is a property you establish per
task by human screening; SWE-bench kept 500 of 2,294 tasks after developers
checked them, and fixing grader bugs alone moved one Anthropic score from 42%
to 95% [SWE-bench Verified, Anthropic 2026].

## 2. Optimizing cost or latency once quality is acceptable

**Finding.** When quality is acceptable, the eval becomes a guardrail: freeze
a regression suite the agent passes today at ~100%, measure cost per
*successful* task (not per run), per-step latency percentiles and cache-hit
rate, then run cheaper configurations against that floor with paired
comparisons [Anthropic 2026, Cost-of-Pass, Error bars]. Inference-time tricks
(majority vote, self-refine) "rarely justify the costs" without a real
verifier [Cost-of-Pass, Monkeys]; routing easy cases to a cheaper model cut
cost by more than 2× in some cases without quality loss [RouteLLM]; ablating
modules (planning depth, tool set, memory) kept 96.7% of performance at 43%
less cost in one study [Efficient Agents]. Prompt caching is the largest free
lever (cache reads at 0.1× input price, "up to 90%" cheaper on long prompts)
but any edit to the prompt prefix, tool definitions or a timestamp in it
invalidates the cache [Caching]. pass^k is unforgiving: 75% per trial is
about 42% pass^3 [Anthropic 2026].

## 3. Drift

**Finding.** "Drift" bundles five different things: the provider's model
changing, the team's own prompt and skill edits, upstream API changes, a shift in the
inputs, and run-to-run nondeterminism that only looks like drift. Practice
separates them: pin model IDs so provider changes are observable (Anthropic
doesn't change weights behind an ID, but serving changes can shift minor
behaviour) [Model IDs]; make every prompt or skill edit a CI event that
re-runs the regression suite; contract-test the fakes against the real APIs;
test the inputs for distribution shift [Evidently]; and measure normal
variance first, because temperature-0 accuracy varies by up to 15 points
between runs and 1,000 identical completions produced 80 distinct outputs
[Nondeterminism, Thinking Machines]. Same-name models have moved by tens of
points in a quarter [Chen 2023]. The canonical warning is OpenAI's sycophancy
regression: offline evals and A/B tests both looked good, because nobody had
a metric for the thing that changed and thumbs-up was the optimization
target; only expert readers noticed [Sycophancy]. No source gives a universal
"normal drift" number; the honest answer is your own k-run confidence
interval [Error bars].

## 4. Sandboxes

**Finding.** Four designs recur: hand-written fakes (full control, high
maintenance), record-and-replay cassettes (exact for the recorded path,
useless off it), staging accounts (high fidelity, slow, flaky), and
self-hosted real software with seeded data [TheAgentCompany, Agent VCR].
The consistent rules: isolate and reset state per trial (leftover git history
let an agent cheat across trials), freeze time and seeds, grade the end
state, and treat the simulated user as the least reliable part [Anthropic
2026]. Numbers on that last point: unconstrained LLM users erred 40–47% of
the time (12–13% critically) versus 16% (6%) when constrained by tools
[τ²-bench]; agent scores moved up to 9 points just by changing the
simulator's model [Lost in Simulation]; personas written by hand matched
real users on only 6–8% of stylistic dimensions, and grounding simulators in
real conversations raised that to 45% and exposed hidden failures
[RealUserSim]. Validity compounds: task × simulator × judge each at 70% is
about 34% overall [Validity]. Before trusting an environment, a trivial agent
should score ~0 and a reference solution ~100 [ABC checklist].

## 5. When the world can't be faked

**Finding.** For open-web research, live SaaS and human-in-the-loop flows,
the eval moves into production instead of pretending: shadow mode (the agent
says what it would do; a judge compares it with what the human did) before
write access [Ramp]; canary cohorts; online reference-free judges on a sample
of live traffic (1–10% at high volume, 50–100% at low) [Braintrust, LangSmith,
Datadog evals]; a fixed weekly human quota [Hamel FAQ]; and the user's own
behaviour as the label: edits made after the output, acceptance, follow-up
corrections, which the literature finds more honest than thumbs [PRELUDE,
Copilot]. Ramp staged its merchant-classification agent this way (manual
review, then follow-up rate, then a 25% rejection rate, then a judge finding
about 99% of proposals improved) before letting it act [Ramp]. Cheap
false-success detectors work as the first monitor, with judges only on the
flagged subset [False success].

## 6. Subjective outputs

**Finding.** The consensus procedure: replace "rate quality 1–10" with
binary pass/fail on named criteria, one judge per failure mode ("the
difference between 3 and 4 is subjective") [Hamel judge, Hamel FAQ]; build
each judge from one domain expert's labelled critiques and report
true-positive and true-negative rates, not raw agreement (a judge that always
says pass still "agrees" 95% of the time); plan 100–200 labelled examples per
failure mode, since below about 60 the intervals are too wide [Hamel judge,
Hamel FAQ]. Use pairwise comparison with position swapping for "better or
worse than before" (position bias is 50–70% without the swap) and a
different model family for the judge, because self-preference tracks
self-recognition [MT-Bench, Yan, Self-preference]. Expect the criteria to
change while you grade, and version them [Validators]. Good judges reach
about 80% agreement with humans, which is also the human–human ceiling
[MT-Bench]. Checklists help most when items are objective and the mode is
pairwise [TICK, Checklists]. 82% of 55 agent-eval papers reported broken or
missing inter-rater statistics; publish yours [Validity]. And some outputs
can only be monitored, not scored: when two experts can't agree pass/fail
after seeing each other's critiques, track pairwise trends and edit distance
instead [Hamel judge, Validators].

## Sources

Fetched and checked 2026-09-30. Grouped by the section that leans on them;
several are cited in more than one.

### Verifiability

- **[Anthropic 2026]** Anthropic, "Demystifying evals for AI agents",
  2026-01-09. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents.
  Grade what the agent produced, not the path; code, model and human graders,
  "choose deterministic where possible"; partial credit; capability vs
  regression evals; pass^k (75% per trial ≈ 42% pass^3); isolate every trial;
  CORE-Bench 42% → 95% after fixing grader bugs.
- **[Multi-agent]** Anthropic, "How we built our multi-agent research
  system", 2025-06-13. https://www.anthropic.com/engineering/multi-agent-research-system.
  Judge the final state for state-changing agents; one rubric judge emitting
  0–1 scores plus pass/fail was most aligned with humans; ~20 real queries
  were enough early on; humans still found what evals missed.
- **[τ-bench]** Sierra, "τ-bench", 2024-06-17. https://arxiv.org/abs/2406.12045.
  Compares the database state at the end with the annotated goal state;
  introduced pass^k; gpt-4o <50% success and pass^8 <25% on retail.
- **[AgentRewardBench]** 2025-04-11, rev. 2025-10. https://arxiv.org/abs/2504.08942.
  1,302 expert-labelled trajectories; rule-based evaluation "tends to
  underreport the success rate"; no single LLM judge best everywhere.
- **[ABC checklist]** "Establishing Best Practices for Building Rigorous
  Agentic Benchmarks", 2025-07-03. https://arxiv.org/abs/2507.02825. Task
  validity, outcome validity, reporting; flaws mis-estimate performance "by
  up to 100% in relative terms"; trivial-agent and reference-solution runs.
- **[SWE-bench Verified]** OpenAI + SWE-bench, 2024-08.
  https://www.swebench.com/verified.html (OpenAI's post
  https://openai.com/index/introducing-swe-bench-verified/ blocks fetches).
  500 tasks kept after developers confirmed each was clear, correct and
  solvable.
- **[False success]** "From Confident Closing to Silent Failure:
  Characterizing False Success in LLM Agents", 2026-06-01, preprint.
  https://arxiv.org/abs/2606.09863. 45–48% of failures in single-control
  τ²-bench domains are false success claims; 3% in dual-control telecom;
  75.8% among self-assessing coding agents; cheap TF-IDF detectors beat LLM
  judges for triage (AUROC 0.83–0.95).
- **[trajectory-judge]** "What Outcome-Only LLM Judges Miss", 2026-08-29,
  preprint. https://arxiv.org/abs/2609.00038. Outcome judges: 84% of visible
  faults, 45% of silent ones, 33% false alarms; step judges: 77% of silent
  faults, zero false alarms, ~3× cost.
- **[RLVR]** Tülu 3, AI2, 2024-11-22, https://arxiv.org/abs/2411.15124; and
  "Let's Verify Step by Step", OpenAI, 2023-05-31,
  https://arxiv.org/abs/2305.20050. Verification functions replace learned
  judges where outcomes are verifiable; process supervision pays where
  outcomes are cheap to fake.
- **[ADK]** Google ADK evaluation docs. https://adk.dev/evaluate/. Ships
  strict trajectory matching by default (EXACT / IN_ORDER / ANY_ORDER): the
  opposite of Anthropic's advice; use only for true invariants.

### Cost and latency

- **[Cost-of-Pass]** Stanford, 2025-04-17. https://arxiv.org/abs/2504.13359.
  Expected dollars per correct solution; majority voting and self-refinement
  "rarely justify the costs"; cost halves every few months on hard tasks.
- **[Efficient Agents]** 2025-07-24. https://arxiv.org/abs/2508.02694. Kept
  96.7% of performance while cutting $0.398 → $0.228 per task by ablating
  modules.
- **[RouteLLM]** LMSYS, 2024-06-26 (ICLR 2025). https://arxiv.org/abs/2406.18665.
  Preference-trained routing: "cost reductions—by over 2 times in certain
  cases—without compromising the quality".
- **[Monkeys]** "Large Language Monkeys", 2024-07-31.
  https://arxiv.org/abs/2407.21787. Coverage scales with samples only where
  an automatic verifier exists.
- **[Caching]** Anthropic prompt caching: pricing
  https://platform.claude.com/docs/en/about-claude/pricing; guide
  https://platform.claude.com/docs/en/build-with-claude/prompt-caching;
  launch post https://claude.com/blog/prompt-caching. Cache read 0.1× input
  (0.05× Opus 5.5, 0.025× Fable 5.1); "up to 90%" cost and "up to 85%"
  latency on long prompts; any prefix edit invalidates.
- **[Pricing]** Anthropic pricing, fetched 2026-09-30. Opus 5.5 $4/$20 per
  MTok, Sonnet 5 $2/$10, Haiku 4.5 $1/$5, Fable 5.1 $10/$50; Batch −50%;
  the 4.7+ tokenizer yields ~30% more tokens for the same text.
- **[Datadog metrics]** Datadog Agent Observability metrics.
  https://docs.datadoghq.com/llm_observability/monitoring/metrics/. Span
  duration as distributions by span kind and model; tokens, cost, errors,
  eval scores on spans.
- **[Error bars]** Miller (Anthropic), "Adding Error Bars to Evals",
  2024-11-01. https://arxiv.org/abs/2411.00640. Paired differences on the
  same task set, clustered standard errors, resampling, power analysis.

### Drift

- **[Chen 2023]** Chen, Zaharia, Zou, "How is ChatGPT's behavior changing
  over time?", 2023-07-18. https://arxiv.org/abs/2307.09009. GPT-4 prime
  identification 84% → 51% in three months.
- **[Model IDs]** Anthropic, "Model IDs and versioning", fetched 2026-09-30.
  https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions.
  Weights behind an ID don't change; serving infrastructure can, with
  "minor differences in observable behavior".
- **[Sycophancy]** OpenAI, "Expanding on what we missed with sycophancy",
  2025-05-02. https://openai.com/index/expanding-on-sycophancy/ (blocks
  fetches; quotes verified at
  https://simonwillison.net/2025/May/2/what-we-missed-with-sycophancy/).
  Offline evals and A/B tests looked good; expert testers said it "felt"
  off; thumbs-up as a reward signal was the cause.
- **[Nondeterminism]** "Non-Determinism of 'Deterministic' LLM Settings",
  2024-08-06, rev. 2025-04. https://arxiv.org/abs/2408.04667. Accuracy varied
  up to 15 points across temperature-0 runs.
- **[Thinking Machines]** "Defeating Nondeterminism in LLM Inference",
  2025-09-10. https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/.
  1,000 identical completions, 80 distinct outputs; batch-size-dependent
  kernels.
- **[Evidently]** "5 methods to detect drift in ML embeddings", 2023-05-17,
  updated 2025-07-16. https://www.evidentlyai.com/blog/embedding-drift-detection.
  Domain-classifier method with ROC-AUC ≈ 0.55 threshold as the default for
  text.
- **[Hamel FAQ]** Hamel Husain & Shreya Shankar, evals FAQ, 2025, updated
  2026-09. https://hamel.dev/blog/posts/evals-faq/. Re-run error analysis on
  significant changes; review 10–20 outlier traces weekly; binary over
  Likert; 100–200 labels per failure mode; "60–80% of our development time
  on error analysis and evaluation".

### Sandboxes

- **[τ²-bench]** Sierra, 2025-06-09. https://arxiv.org/abs/2506.07982.
  User-simulator error rates: retail 40% (12% critical), airline 47% (13%),
  tool-constrained telecom 16% (6%); dual control drops agent pass^1 by
  18–25 points.
- **[Lost in Simulation]** 2026-01-23. https://arxiv.org/abs/2601.17087.
  Success varies up to 9 points across user LLMs; simulators misestimate by
  task difficulty and dialect.
- **[RealUserSim]** Salesforce, 2026-04-07. https://arxiv.org/abs/2605.20204.
  Hand-written personas match real users on 6–8% of stylistic dimensions;
  grounding in 14K real conversations raised it to 45.3% and exposed hidden
  failures.
- **[TheAgentCompany]** CMU, 2024-12-18, rev. 2025-09.
  https://arxiv.org/abs/2412.14161. Self-hosted GitLab, RocketChat,
  ownCloud, Plane with seeded data; checkpoint-based partial credit; best
  agent ~30% of 175 tasks.
- **[Agent VCR]** Capital One, 2025. https://github.com/Jarvis2021/agent-vcr.
  Records MCP traffic to cassettes; replays as a mock server; diffs
  recordings across versions; five match modes.

### No sandbox

- **[Ramp]** "Fixing merchant classifications with AI", 2025.
  https://builders.ramp.com/post/fixing-merchant-classifications-with-ai.
  Shadow mode; staged signals; 25% rejection rate; judge found ~99%
  improved; live actions only after shadow results held.
- **[Braintrust]** Online scoring docs. https://www.braintrust.dev/docs/platform/logs/score.
  Sample 1–10% at high volume, 50–100% at low; promote traces into the
  offline set.
- **[LangSmith]** Evaluation concepts. https://docs.langchain.com/langsmith/evaluation-concepts.
  Offline vs online; pairwise when direct scoring is hard; backtesting on
  historical inputs.
- **[Datadog evals]** https://docs.datadoghq.com/llm_observability/evaluations/.
  Custom judge prompts over traces; external results and end-user feedback
  attached to the same spans.
- **[PRELUDE]** PRELUDE / CIPHER, NeurIPS 2024, 2024-04-23.
  https://arxiv.org/abs/2404.15269. The user's edits as the feedback signal;
  cost = edit distance.
- **[Copilot]** GitHub Copilot productivity study, 2022-05-13.
  https://arxiv.org/abs/2205.06537. Acceptance rate tracks perceived
  productivity better than persistence.

### Subjective outputs

- **[Hamel judge]** Hamel Husain, "Creating a LLM-as-a-Judge That Drives
  Business Results", 2024-10-29. https://hamel.dev/blog/posts/llm-judge/.
  Critique shadowing; ~100 labels per failure mode; below 60 the intervals
  are too wide; report TPR and TNR; Honeycomb converged in three iterations.
- **[Validators]** Shankar et al., "Who Validates the Validators?", UIST
  2024. https://arxiv.org/abs/2404.12272. Criteria drift: grading outputs
  changes the criteria.
- **[MT-Bench]** Zheng et al., "Judging LLM-as-a-judge", NeurIPS 2023.
  https://arxiv.org/abs/2306.05685. Position, verbosity and self-enhancement
  bias; >80% agreement with humans, the human–human level.
- **[Yan]** Eugene Yan, "Evaluating the Effectiveness of LLM-Evaluators",
  2024-08. https://eugeneyan.com/writing/llm-evaluators/. Direct scoring for
  objective checks, pairwise for subjective; position bias 50–70%; a few
  hundred labels to align.
- **[Self-preference]** Panickssery, Bowman, Feng, "LLM Evaluators Recognize
  and Favor Their Own Generations", 2024-04-15. https://arxiv.org/abs/2404.13076.
- **[Arena]** Chatbot Arena, 2024-03-07. https://arxiv.org/abs/2403.04132.
  Pairwise votes → Bradley-Terry ranking with confidence intervals.
- **[TICK]** 2024-10-04. https://arxiv.org/abs/2410.03608. YES/NO checklists
  raised LLM–human agreement 46.4% → 52.2%.
- **[Checklists]** "Are Checklists Really Useful?", EMNLP 2025, 2025-08-21.
  https://arxiv.org/abs/2508.15218. Gains hold in pairwise settings, less in
  direct scoring.
- **[Validity]** Caban, "Measurement Without Validity", 2026-08, preprint.
  https://arxiv.org/abs/2608.00794. Validity compounds across task ×
  simulator × judge; 82% of 55 papers report broken inter-rater statistics;
  proposes ICC ≥ 0.70.

---

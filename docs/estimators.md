# Evals as estimators

*Target design for aot-evals 2.0. Draft. Until the 2.0 refactor lands, [method.md](method.md) describes
what the tool does today.*

An eval exists to make a decision: ship this prompt change, swap this model, keep this subagent. To
make that decision you want a number, and the eval is how you estimate it. So an eval is a
statistical **estimator**, and like any estimator it is only as good as four things you have to
write down:

| Part | The question it answers | What you write down |
|---|---|---|
| **1. Estimand** | What number, about what, drives which decision? | The unit being evaluated, the population of requests, the segments of that population and the weight of each, and the decision |
| **2. Sampling design** | Which cases, drawn how? | Where cases come from, how they were selected, the chance each had of being selected, and which cases are related |
| **3. Measurement model** | How wrong is the grader? | One check per failure mode, each with its measured error rates, and how many times each case runs |
| **4. Decision rule** | When do we act? | The test, the margin, the error rates you'll tolerate, and how many times you'll look |

Each part has a long history in another field: validity in psychometrics (Cronbach & Meehl 1955; Messick 1989;
AERA, APA & NCME 2014), sampling in survey statistics (Neyman 1934; Horvitz & Thompson 1952; Kish 1965),
measurement error in diagnostic testing and inter-rater agreement (Rogan & Gladen 1978; Cohen 1960),
and decision rules in hypothesis testing (Neyman & Pearson 1933; Wald 1947). None of it is new.
aot-evals writes all four down for each eval of an agent, and lets the rules for building a suite
follow from them instead of from rules of thumb.

Everything in aot-evals 2.0 is organized by these four parts. The [problems](problems.md) show where
each part bites in practice, with worked examples. The [statistics](statistics.md) derive the
numbers. This page is the structure both of them hang on.

## Contents

1. [Where evals go](#1-where-evals-go)
2. [The running example](#2-the-running-example)
3. [Part 1: the estimand](#3-part-1-the-estimand)
4. [Part 2: the sampling design](#4-part-2-the-sampling-design)
5. [Part 3: the measurement model](#5-part-3-the-measurement-model)
6. [Part 4: the decision rule](#6-part-4-the-decision-rule)
7. [The estimate](#7-the-estimate)
8. [The suite spec](#8-the-suite-spec)
9. [Changing a suite](#9-changing-a-suite)
10. [The rules in one table](#10-the-rules-in-one-table)
11. [Out of scope, and open problems](#11-out-of-scope-and-open-problems)
12. [Prior work](#12-prior-work)
13. [References](#13-references)

## 1. Where evals go

An agent system usually has an orchestrator that reads the request and routes it, steps that share
the orchestrator's context, and subagents that run in a context of their own:

```
                ┌─ shared context ─────────────────────────┐
  Eval 0 ─────► │  orchestrator (routing) ── Step 1        │
  (whole        │          │              └─ Step N        │
   system)      └──────────┼───────────────────────────────┘
                           │ handoff
                ┌─ own context ───────────┐
                │  Step 2 (subagent)      │ ◄───── Eval 2
                └─────────────────────────┘        (Step 2 alone)
```

Eval 0 covers everything, Step 2 included. Eval 2 covers Step 2 by itself, starting from the
handoffs it receives.

One eval answers one question, so a system can need more than one. These rules say how many and
where:

1. **Every agent gets an end-to-end eval** (Eval 0). Its unit is the whole system as a user meets
   it, subagents included, because the user experiences the whole system and the decision to ship
   is made about the whole system.
2. **A component gets an eval of its own only at a context boundary** (Eval 2). A subagent with its
   own context receives a defined input, a handoff, that can be captured and replayed. A step that
   shares the orchestrator's context receives the whole transcript so far, which can't be sampled
   or replayed on its own.
3. **...and only when someone decides about it separately.** A subagent with its own prompt, model
   or owner, changed on its own schedule, earns an eval. One that is only ever changed together with
   the rest of the system doesn't: an eval whose number drives no decision is a diagnostic, and the
   end-to-end eval's checks already cover it.
4. **Steps inside a shared context are graded by checks in the eval that encloses them.** Steps 1
   and N are covered by Eval 0, through checks on the steps of the run (did it call the right tool,
   with the right arguments).
5. **A component eval's cases are the handoffs it receives in production.** Eval 2 draws its cases
   from the inputs the orchestrator actually hands Step 2, taken from end-to-end traces. A change to
   routing changes those inputs, so it re-opens every eval downstream of it (rule 26).
6. **The end-to-end eval has the last word.** A change to a component ships when the component's
   own decision rule passes *and* the end-to-end eval shows no regression. A better component does
   not prove a better system.
7. **Gating on several evals at once needs a multiplicity correction** (rule 22), the same as
   gating on several segments.

Graders and the store of traces are shared between evals. The four parts are not: each eval writes
down its own.

## 2. The running example

The examples on this page, and in the problems and statistics, use one agent: **a support agent for
an online store**. It answers about 1,000 requests a day:

| Segment | Per day | Share |
|---|---:|---:|
| Where's my order? | 700 | 70% |
| Start a return | 200 | 20% |
| Change my address | 80 | 8% |
| Refund me | 20 | 2% |

An orchestrator reads each request and answers order and return questions itself, using a tool that
reads orders and one that changes addresses. Refunds go to a **refund subagent** with its own prompt
and its own model. It checks the order against the refund policy and issues the refund or declines.
A separate team owns the refund subagent and changes it on its own schedule.

So the store has two evals:

- **Eval 0, the support agent.** Unit: the whole system. Population: all customer requests. It
  decides whether a change to the system ships.
- **Eval 2, the refund subagent.** Unit: the subagent alone. Population: the refund handoffs the
  orchestrator produces. It decides whether the refund team's changes ship.

## 3. Part 1: the estimand

**The question.** What number, about what, drives which decision?

**What you write down.**

- **Unit**: the thing that ships, at a context boundary (section 1).
- **Quantity**: a pass rate, a mean score, or the rate of one failure mode.
- **Population**: which requests, from which window, in which environment.
- **Segments**: a partition of the population into kinds of request, each with its measured share
  of traffic. Shares sum to 1.
- **Weights**: how much each segment counts in the decision. Either "traffic" (weights equal the
  shares), or a number per segment that the owner states. An unstated weight is unknown, not 1.
- **Decision**: the action this number drives, who owns it, and how often it is made.

The estimand is then one number, the weighted pass rate θ:

θ = Σ_s w_s · μ_s

where μ_s is the true pass rate in segment s and the weights w_s sum to 1. The eval estimates θ.

**Segments and failure modes are two different things.** A segment is a kind of request ("refund
me"). It carries weight, because it is part of the population the decision is about. A failure mode
is a way the agent can go wrong ("refunded an order outside the policy window"). It is a check, part
of the measurement model (section 5). A single segment can fail in several modes, and one mode can
occur in several segments. aot-evals 1.x mixed the two into "categories"; 2.0 keeps them apart.

**Example.** Suppose the store's eval uses traffic weights and the system passes 91.0% of requests.
A bug makes refunds fail 15% of the time instead of 5%. That is 2 more bad refunds a day, and θ moves
from 91.0% to 90.8%, which nobody will notice. Now suppose the owner says what a failure costs in
each segment: $1 for a wrong order status, $5 for a botched return, $20 for an address change and $50
for a refund. Weighting each segment by share × cost gives:

| Segment | Share | Cost of a failure | Share × cost | Weight |
|---|---:|---:|---:|---:|
| Order status | 0.70 | $1 | 0.70 | 0.16 |
| Return | 0.20 | $5 | 1.00 | 0.23 |
| Address | 0.08 | $20 | 1.60 | 0.37 |
| Refund | 0.02 | $50 | 1.00 | 0.23 |

Under these weights the same bug moves θ by 0.23 × 10 = 2.3 points, which is the size of the harm.
With weights proportional to share × cost, 1 − θ is proportional to the expected cost of failures
per request, so the number means something a business owner can use.

**Rules that follow.**

- **One eval, one estimand** (rule 1). Two units, two populations or two decisions need two evals.
  This is what puts evals at context boundaries (section 1).
- **The headline is θ̂ under the stated weights** (rule 2), with the per-segment table beside it
  as the diagnostic. An unweighted average over segments is an arbitrary weighting nobody chose.
- **A shift in the population re-opens the estimand** (rule 26). The shares are part of θ, so a
  new mix of traffic means a new θ. Shares are measured again on a schedule.

## 4. Part 2: the sampling design

**The question.** Which cases, drawn how?

**What you write down.**

- **Frame**: where cases come from (production traces, the handoffs into a subagent, written
  tasks), and the window.
- **Two pools.** The **quality set** is a random sample from the frame, stratified by segment,
  with each case's chance of being drawn (its inclusion probability, π) recorded. The
  **bug-finding set** is picked by hand to find failures: hard cases, rare ones, ones from the
  coverage list. It has no π.
- **Cluster key**: what makes cases related (the same template, the same customer, the same source
  trace), so related cases are counted as one piece of evidence and not several.

**Example.** For Eval 0, a quality set of 200 drawn at random from last month's traffic, in
proportion to traffic, would hold about 140 order lookups, 40 returns, 16 address changes and 4
refunds. Four refunds can't say much about refunds, and refunds carry a weight of 0.23. So the
design draws refunds at a higher rate, records that π, and the estimator weights each refund case
back down by 1/π. The estimate stays (approximately) unbiased and the refund segment gets enough cases to
measure.
Meanwhile the bug-finding set holds 30 written refund cases that each probe a corner of the policy
(an order one day outside the window, a partial refund, a refund on a gift card). They find bugs.
They never enter θ̂, because nobody knows how often such requests occur.

**Rules that follow.**

- **Bug-finding cases never enter a rate** unless their π was recorded (rule 5). A hand-picked
  pass rate describes the hand-picking, not the traffic. Software testing draws the same line between
  testing to find faults and testing to measure reliability (Musa 1993; Frankl et al. 1998).
- **The quality set is drawn, not picked** (rule 6): seeded, with π recorded per case.
- **The number of cases comes from the decision rule** (rule 7, section 6), not from a constant.
- **Spread the budget by optimum allocation** (rule 8): each segment gets cases in proportion to
  its weight × the spread of its outcomes ÷ √(cost of a case), which is Neyman's allocation extended
  for cost (Cochran 1977). A gated segment the formula would short gets its minimum, and the formula
  spreads the rest over the others. This makes θ̂ as precise as the budget allows.
- **Count clusters, not cases** (rule 9). Twenty cases from one template are worth fewer than twenty
  independent cases. The effective count is n ÷ (1 + (m − 1)ρ), where m is the cluster size and ρ
  is how alike cases in a cluster behave (Kish 1965).
- **The quality set and the bug-finding set are disjoint by cluster key** (rule 10), not just by
  source trace.

## 5. Part 3: the measurement model

**The question.** How wrong is the grader, and how is the score corrected for it?

**What you write down.**

- **Checks**: one check per failure mode, each a yes-or-no question. Each is code (exact) or a judge
  (a model that reads the run).
- **Error rates for every judge**: its **catch rate** (of the runs a person fails, the share it
  fails) and its **clean pass rate** (of the runs a person passes, the share it passes), measured on
  a set of runs that people labeled, with the size of that set and the date. These are a diagnostic
  test's sensitivity and specificity, and the same two numbers measure the eval as a whole (rule 15).
- **Trials**: how many times each case runs (k), because the agent doesn't give the same answer
  every time.
- **Correction**: how the score is corrected for the judges' errors.

**Example.** A judge checks whether a refund followed the policy. On 1,000 refund decisions, 30
truly broke the policy. The judge catches 24 of the 30 (catch rate 0.80) and wrongly flags 97 of
the 970 good ones (clean pass rate 0.90). It flags 121 runs, a 12.1% failure rate, when the true rate is
3%. The correction undoes this. If the judge flags a share f_obs of runs, the true failure rate is (Rogan & Gladen 1978)

f = (f_obs + clean − 1) / (catch + clean − 1) = (0.121 + 0.90 − 1) / 0.70 = 0.03

When some runs also have a person's label, prediction-powered inference uses those labels to
correct the judge's rate and gives an interval that accounts for both (Angelopoulos et al. 2023).

**A grader's error costs you cases.** If a judge's catch rate and clean pass rate sum to 1 + J, a
real change of Δ in the failure rate shows up as a change of only J × Δ in what the judge reports.
Near a 50% failure rate, seeing it takes about 1/J² as many cases. For rare failures it takes far
more, because the judge's false flags on good runs swamp the few real failures. At the refunds' 3%
failure rate, the judge above needs about 7.5 times the cases a code check would, and a judge at
0.75 on both needs about 27 times. That is how much a judge's errors cost, and it is how a floor on
judge quality is set: decide how many extra cases you are willing to pay for at the failure rates
you care about ([statistics §3.3](statistics.md#33-what-a-graders-error-costs-you)). It assumes the
judge errs the same way on both versions being compared; when it doesn't, the comparison is biased
and more cases don't help (Fiedler 2026).

**Rules that follow.**

- **One failure mode per check** (rule 11). Error rates are defined for one yes-or-no question; a
  check that asks two has no single catch rate.
- **Exactly one check per failure mode counts toward the score** (rule 12). Extra checks on the same
  mode are diagnostics, or a mode would be counted twice.
- **A judge is part of the instrument** (rule 13). Changing its prompt or model makes a new
  instrument with unknown error rates. Measure them again before its numbers count.
- **Use code where code can decide** (rule 14). Code checks have no error to correct.
- **Hold the whole eval to a person, not only each judge** (rule 15). A run passes only if every
  check passes, so errors combine across checks in ways the per-check rates don't show. People label
  whole runs, and the eval's verdicts are compared with theirs.
- **More cases beat more trials** when cases differ more than trials do (rule 16). Set k from the
  measured split between the two.
- **Cases with an unverified answer stay out of the score** (rule 17). Their measurement error is
  unknown.

## 6. Part 4: the decision rule

**The question.** When do we act?

**What you write down.**

- **Test**: superiority (the change is better), non-inferiority (the change is no worse than a
  margin), or a threshold (the rate is above a bar).
- **Margin** (Δ): the smallest change that matters to the decision.
- **α and power**: how often you'll accept a false alarm (usually 5%) and how often you need to
  catch a real change of size Δ (usually 80%).
- **Looks**: one fixed look, a planned sequence of looks, or an optimizer that never sees a held-out
  split.
- **Constraints**: limits that hold whatever the score says, such as cost per run or latency.

**Example.** The refund team wants to show the subagent's policy-breaking rate is below 5%, at 95%
confidence. If it passes every case, it needs 59 cases, because a subagent that breaks the policy 5%
of the time would still pass 58 in a row about 5% of the time (0.95⁵⁸ ≈ 0.05; 0.95⁵⁹ < 0.05). That
assumes a code check. The policy judge, which wrongly flags 10% of good refunds, never returns a clean
run; testing the same bar through it (80% power against a true rate of 1%) takes about 860 cases,
against about 120 with a code check. For Eval 0, the owner sets a non-inferiority
rule: ship a prompt change if θ̂ falls by no more than 2 points, judged case by case against the
current version on the same cases.

**Rules that follow.**

- **The case count comes from the decision rule** (rule 7). The number of cases solves "power at
  least 1 − β to detect Δ at level α", with the judges' error included (section 5). The zero-failure
  version is n ≥ ln(α) / ln(1 − p). No flat count per segment.
- **Compare versions case by case** (rule 18): the same cases, the same trials, a paired test.
  Pairing removes the differences between cases from the comparison.
- **"No significant difference" is not "no worse"** (rule 19). Claiming no regression takes a
  non-inferiority test with a stated margin.
- **A segment gets its own gate only when someone decides about it, and when its rule can be
  powered** (rule 20). Otherwise its row is a diagnostic. If no one will act on it, it shouldn't
  gate.
- **Fix the looks in advance** (rule 21). Labeling until the number clears the bar, or checking
  after every batch, inflates false passes.
- **Several gates need a multiplicity correction** (rule 22). Ten gated segments at α = 0.05, with
  no real change, flag at least one about 40% of the time (1 − 0.95¹⁰).
- **An optimizer keeps a split it never sees** (rule 23), and its looks at that split are counted
  (Dwork et al. 2015).
- **Cost and latency are constraints, not part of θ** (rule 24). A change can improve θ and still
  fail its budget.

## 7. The estimate

Put together, the eval's estimate of θ is

θ̂ = Σ_s w_s · μ̂_s,  with  μ̂_s = Σ_{i∈s} (ŷ_i / π_i) / Σ_{i∈s} (1 / π_i)

where ŷ_i is case i's outcome averaged over its k trials and corrected for the checks' error rates,
and π_i is its inclusion probability. (Within each segment this is the Hájek estimator: the Horvitz–Thompson estimator normalized by
its own weights, which is approximately unbiased; Hájek 1971.)

Its interval accounts for three sources of uncertainty: which cases were drawn (with clusters and
segments), how wrong the judges are (from the size of their calibration sets), and how much trials
of the same case vary. The decision rule says which interval to compute and which bar it has to
clear.

## 8. The suite spec

Each eval writes its four parts in one file. An eval is complete when every field is filled. A
missing field doesn't stop the eval from running; it means nothing says what its number means, and
the report says so.

```yaml
eval: refund-subagent
version: 1.0                     # major: estimand, weights, design or checks changed
estimand:
  unit: refund subagent          # at a context boundary
  quantity: failure_rate:breaks_policy
  population: refund handoffs from production, last 30 days
  segments: {full_refund: 0.80, partial_refund: 0.15, gift_card: 0.05}
  weights: traffic               # or {segment: weight}, stated by the owner
  decision: ship refund-subagent changes; owner refunds team; weekly
design:
  frame: handoffs captured in end-to-end traces
  quality_set: {selection: stratified_random, strata: segments, seed: 1234, inclusion_prob: per_case}
  bug_finding_set: {selection: purposive}       # never enters the rate
  cluster_key: order_template
measurement:
  checks:
    breaks_policy: {type: judge, catch_rate: 0.80, clean_pass_rate: 0.90, calibration_n: 200, calibrated_on: 2026-11-01}
    refund_amount_correct: {type: code}
  trials_per_case: 3
  correction: ppi                # or rogan_gladen, or none when every check is code
decision_rule:
  test: threshold                # superiority | non_inferiority | threshold
  bar: 0.05
  margin: null
  alpha: 0.05
  power: 0.80
  looks: fixed                   # fixed | sequential | optimizer_holdout
  multiplicity: none             # or benjamini_hochberg when several gates count
  constraints: {cost_per_run_usd: 0.02, p95_latency_ms: 8000}
```

The field names are a sketch. The 2.0 refactor will settle them.

## 9. Changing a suite

Every change to an eval is one of three kinds, and the four parts say which:

| Change | When | What happens |
|---|---|---|
| **Expand** | New cases from the same frame, same segments, same checks, with known π | Same version. The interval narrows; θ is the same quantity |
| **Revise** | The estimand, weights, segments, design or checks change. A new judge counts | Major version. Re-run the baseline; old and new scores are different quantities and are not compared |
| **Split** | A segment or a component gets its own decision, owner and powered rule | A new eval with its own four parts. The old eval keeps the segment in its estimand. Whether a sub-score adds anything beyond the total has a test (Haberman 2008) |

A new kind of request is a new segment, so it is a revision, not an expansion. Pruning for cost may
remove bug-finding cases freely; it may not remove quality-set cases, because that changes their π
and biases θ̂ (rule 25).

## 10. The rules in one table

Each rule names the part it follows from, the [problem](problems.md) that shows why it matters, and
the section of [statistics.md](statistics.md) that derives it.

| # | Rule | Part | Problem | Statistics |
|---|---|---|---|---|
| 1 | One eval, one estimand: one unit, one population, one decision | Estimand | 2 | §1.3 |
| 2 | The headline is θ̂ under the stated weights, with the per-segment table as the diagnostic | Estimand | 1 | §1.1 |
| 3 | Every agent has an end-to-end eval; components get their own only at a context boundary, when decided on separately | Estimand | 2 | §1.3 |
| 4 | A component eval's population is its production handoffs | Estimand, design | 2 | §1.3, §2.1 |
| 5 | Bug-finding cases never enter a rate without a recorded π | Design | 4 | §2.1 |
| 6 | The quality set is a seeded random draw with π per case | Design | 4 | §2.2 |
| 7 | Case counts come from the decision rule's power, with judge error included | Decision rule | 9 | §4.1, §3.3 |
| 8 | The budget goes by optimum allocation (Neyman's, with cost), around each gated segment's minimum | Design | 4 | §2.3 |
| 9 | Count clusters, not cases | Design | 5 | §2.4 |
| 10 | The quality and bug-finding sets are disjoint by cluster key | Design | 4, 5 | §2.4 |
| 11 | One failure mode per check | Measurement | 6 | §3.1 |
| 12 | Exactly one check per failure mode counts toward the score | Measurement | 6 | §3.1 |
| 13 | A new judge, or a changed one, is a new instrument: measure its error rates again | Measurement | 3, 6 | §3.2, §3.8 |
| 14 | Use code where code can decide | Measurement | 6 | §3.1 |
| 15 | Hold the whole eval to people's labels of whole runs | Measurement | 7 | §3.6 |
| 16 | Set trials per case from the measured variance split | Measurement | 8 | §3.7 |
| 17 | Cases with an unverified answer stay out of the score | Measurement | 6 | §3.8 |
| 18 | Compare versions case by case | Decision rule | 10 | §4.3, §4.4 |
| 19 | Claim "no worse" only with a non-inferiority test | Decision rule | 11 | §4.5 |
| 20 | A segment gates only when decided on separately and when its rule can be powered | Decision rule | 1 | §1.2 |
| 21 | Fix the looks in advance | Decision rule | 12 | §4.7 |
| 22 | Several gates need a multiplicity correction | Decision rule | 2, 12 | §4.6 |
| 23 | An optimizer keeps a split it never sees | Decision rule | 12 | §4.7 |
| 24 | Cost and latency are constraints, not part of θ | Decision rule | 10 | §4.8 |
| 25 | Prune only where θ̂ stays unbiased | Design | 3 | §2.6 |
| 26 | A population shift, or a routing change upstream, re-opens the estimand | Estimand | 3 | §1.4 |

Everything else aot-evals asks of a team (how to write failure modes, how to run labeling sessions,
how to lay out files) is process. It doesn't follow from the four parts and doesn't have to, but it
has to serve one of them or go.

## 11. Out of scope, and open problems

**Out of scope: simulated users and the fidelity of fakes.** An agent runs in a sandbox (fakes for
the store's order system, for example), and the sandbox is part of what is measured: both versions
in a comparison run in the same one, and the sandbox is versioned with every result. Whether a pass
in the sandbox means a pass in production is a measurement-model question that nobody has error
rates for. aot-evals 2.0 does not claim to answer it.

**Open problems.** These are the places where agents differ from the settings the four parts come
from:

- **Few versions to compare.** Psychometrics has thousands of test-takers; an agent team has a
  handful of versions. Methods that need many examinees (item response theory, subscore analysis)
  work only as qualitative checks.
- **The population moves.** Traffic mix and tools change monthly, so θ has a date. Baselines go
  stale.
- **Runs, not answers.** A case is a multi-step run, and a failure can happen at any step. Whether
  the estimand is per run or per step changes how many cases are needed.
- **The sandbox's realism**, as above.
- **Randomness in the agent.** The right number of trials per case is an empirical question for
  each eval.

## 12. Prior work

Every part has precedent, and recent work combines several of them for language models and agents.
aot-evals builds on all of it.

- Miller (2024) treats eval questions as a draw from a larger population, with clustered standard
  errors, paired comparisons and power analysis. It does not model grading error.
- Chouldechova et al. (2024) define the population an eval measures, and argue that an eval sampled
  by red-teaming would overstate how often failures occur in normal use. They offer no error model
  for annotators and no decision rule.
- Binette and Reiter (2024) bring clinical-trial estimands to ML evaluation (metric, population, how
  data and labels are acquired, aggregation), with intervals but no thresholds or power.
- Huang (2026) asks what an agent leaderboard rank actually compares: the estimand, the agent
  configuration as the unit, the verifier's error rates and a practical margin.
- Prediction-powered inference (Angelopoulos et al. 2023) corrects a judge's scores with human
  labels and gives valid intervals. Boyeau et al. (2024) apply it to model evaluation, and Fisch et
  al. (2024) stratify it.
- Judge error in power and sample size is old in epidemiology (Rubin, Rosenbaum & Cobb 1956;
  Hársfalvi & Reiczigel 2024) and recent for LLM judges: a threshold test whose critical value and
  power are written in the judge's error rates (Feng et al. 2026), power for prediction-powered
  inference (Chen, Guo & Li 2026), and how to split a budget between human and judge labels (Kim
  2026).
- Wallach et al. (2025) and Salaudeen et al. (2025) set out validity frameworks for AI evaluation,
  conceptually rather than as a statistical object.

Two results limit what the measurement model can do. Dorner, Nastl and Hardt (2025) show that
correcting a judge that is no stronger than the model being judged saves at most half the human
labels, so labels don't become free. And correcting two versions with one shared estimate of a
judge's error rates, when its rates differ between them, can reverse a comparison with apparent
confidence (Fiedler 2026), which is why a changed judge, or a changed agent under the same judge,
calls for fresh labels (rule 13).

## 13. References

- AERA, APA & NCME (2014). *Standards for Educational and Psychological Testing.* Washington, DC: American Educational Research Association.
- Angelopoulos, A. N., Bates, S., Fannjiang, C., Jordan, M. I. & Zrnic, T. (2023). Prediction-powered inference. *Science* 382(6671):669–674. doi:10.1126/science.adi6000
- Binette, O. & Reiter, J. P. (2024). Improving the validity and practical usefulness of AI/ML evaluations using an estimands framework. arXiv:2406.10366
- Boyeau, P., Angelopoulos, A. N., Yosef, N., Malik, J. & Jordan, M. I. (2024). AutoEval done right: Using synthetic data for model evaluation. arXiv:2403.07008
- Chen, Y. T., Guo, M. & Li, S. (2026). Power analysis for prediction-powered inference. arXiv:2603.16041
- Chouldechova, A. et al. (2024). A shared standard for valid measurement of generative AI systems' capabilities, risks, and impacts. NeurIPS 2024 Workshop on Statistical Foundations of LLMs and Foundation Models. arXiv:2412.01934
- Cochran, W. G. (1977). *Sampling Techniques* (3rd ed.). New York: Wiley.
- Cohen, J. (1960). A coefficient of agreement for nominal scales. *Educational and Psychological Measurement* 20(1):37–46. doi:10.1177/001316446002000104
- Cronbach, L. J. & Meehl, P. E. (1955). Construct validity in psychological tests. *Psychological Bulletin* 52(4):281–302. doi:10.1037/h0040957
- Dorner, F. E., Nastl, V. Y. & Hardt, M. (2025). Limits to scalable evaluation at the frontier: LLM as judge won't beat twice the data. *ICLR 2025*. arXiv:2410.13341
- Dwork, C., Feldman, V., Hardt, M., Pitassi, T., Reingold, O. & Roth, A. (2015). The reusable holdout: Preserving validity in adaptive data analysis. *Science* 349(6248):636–638. doi:10.1126/science.aaa9375
- Feng, C., Shen, M., Balashankar, A., Gerner-Beuerle, C. & Rodrigues, M. R. D. (2026). Noisy but valid: Robust statistical evaluation of LLMs with imperfect judges. arXiv:2601.20913
- Fiedler, J. (2026). Bias and uncertainty in LLM-as-a-judge estimation. arXiv:2605.06939
- Fisch, A., Maynez, J., Hofer, R. A., Dhingra, B., Globerson, A. & Cohen, W. W. (2024). Stratified prediction-powered inference for hybrid language model evaluation. arXiv:2406.04291
- Frankl, P. G., Hamlet, R. G., Littlewood, B. & Strigini, L. (1998). Evaluating testing methods by delivered reliability. *IEEE Transactions on Software Engineering* 24(8):586–601. doi:10.1109/32.707695
- Haberman, S. J. (2008). When can subscores have value? *Journal of Educational and Behavioral Statistics* 33(2):204–229. doi:10.3102/1076998607302636
- Hájek, J. (1971). Comment on "An essay on the logical foundations of survey sampling, part one" by D. Basu. In V. P. Godambe & D. A. Sprott (Eds.), *Foundations of Statistical Inference* (p. 236). Toronto: Holt, Rinehart and Winston.
- Hársfalvi, P. & Reiczigel, J. (2024). The effect of misclassification on sample size for one and two-sample tests with binary endpoints. *Journal of Biopharmaceutical Statistics* 36(3):561–572. doi:10.1080/10543406.2024.2444231
- Horvitz, D. G. & Thompson, D. J. (1952). A generalization of sampling without replacement from a finite universe. *JASA* 47(260):663–685. doi:10.1080/01621459.1952.10483446
- Huang, W.-J. (2026). What does an LLM-agent leaderboard rank actually compare? arXiv:2609.07785
- Kim, J. P. (2026). Augmenting human evaluation with LLM judges: How many human reviews do you need? arXiv:2605.16354
- Kish, L. (1965). *Survey Sampling.* New York: Wiley.
- Messick, S. (1989). Validity. In R. L. Linn (Ed.), *Educational Measurement* (3rd ed., pp. 13–103). New York: American Council on Education / Macmillan.
- Miller, E. (2024). Adding error bars to evals: A statistical approach to language model evaluations. arXiv:2411.00640
- Musa, J. D. (1993). Operational profiles in software-reliability engineering. *IEEE Software* 10(2):14–32. doi:10.1109/52.199724
- Neyman, J. (1934). On the two different aspects of the representative method: The method of stratified sampling and the method of purposive selection. *JRSS* 97(4):558–625. doi:10.2307/2342192
- Neyman, J. & Pearson, E. S. (1933). On the problem of the most efficient tests of statistical hypotheses. *Phil. Trans. R. Soc. A* 231:289–337. doi:10.1098/rsta.1933.0009
- Rogan, W. J. & Gladen, B. (1978). Estimating prevalence from the results of a screening test. *American Journal of Epidemiology* 107(1):71–76. doi:10.1093/oxfordjournals.aje.a112510
- Rubin, T., Rosenbaum, A. S. & Cobb, S. (1956). The use of interview data for the detection of associations in field studies. *Journal of Chronic Diseases* 4(3):253–266. doi:10.1016/0021-9681(56)90028-5
- Salaudeen, O. et al. (2025). Measurement to meaning: A validity-centered framework for AI evaluation. arXiv:2505.10573
- Wald, A. (1947). *Sequential Analysis.* New York: Wiley.
- Wallach, H. et al. (2025). Position: Evaluating generative AI systems is a social science measurement challenge. *ICML 2025*. arXiv:2502.00561

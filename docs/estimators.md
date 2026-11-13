# Evals as estimators

*Target design for aot-evals 2.0. Draft. Until the 2.0 refactor lands, [method.md](method.md) describes
what the tool does today.*

An eval exists to make a decision: ship this prompt change, swap this model, keep this subagent. To
make that decision you want a number, and the eval is how you estimate it. So an eval is a
statistical **estimator**, and like any estimator it is only as good as four things you have to
write down:

| Part | The question it answers | What you write down |
|---|---|---|
| **1. Estimand** | What number, about what, drives which decision? | The unit being evaluated, the population of requests, the use cases of that population and the weight of each, and the decision |
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

- [Terms](#terms)
1. [Where evals go](#1-where-evals-go)
2. [The running example](#2-the-running-example)
3. [Part 1: the estimand](#3-part-1-the-estimand)
4. [Part 2: the sampling design](#4-part-2-the-sampling-design)
5. [Part 3: the measurement model](#5-part-3-the-measurement-model)
6. [Part 4: the decision rule](#6-part-4-the-decision-rule)
7. [The estimate](#7-the-estimate)
8. [The eval spec](#8-the-eval-spec)
9. [Changing an eval](#9-changing-an-eval)
10. [The rules in one table](#10-the-rules-in-one-table)
11. [Out of scope, and open problems](#11-out-of-scope-and-open-problems)
12. [Prior work](#12-prior-work)
13. [References](#13-references)

## Terms

Each term below means one thing, here, in the [problems](problems.md), in the
[statistics](statistics.md) and in the tool. Where aot-evals uses a plainer word than the field it
comes from, the last column gives the standard name, so the sources can be read alongside.

**The eval and what it covers**

| Term | Meaning | Standard term |
|---|---|---|
| **eval** | One estimator: one unit, one population, one decision, with its four parts written down. An agent can have several | estimator |
| **eval spec** | The file that writes an eval's four parts down (`eval.yaml`). Changing it can change what the number means ([§9](#9-changing-an-eval)) | study protocol |
| **suite** | An eval's cases and checks: what you build and run | test set |
| **unit** | What the eval evaluates: the whole agent, or one component of it | system under test |
| **end-to-end eval** | The eval whose unit is the whole agent as a user meets it, subagents included. Every agent has one | |
| **component eval** | An eval of one subagent on its own, run from the handoffs it receives | |
| **context boundary** | Where a subagent starts with a context of its own instead of sharing the orchestrator's | |
| **handoff** | The input a subagent receives across a context boundary | |
| **baseline**, **candidate** | The version running now, and the changed version being decided on | control, treatment |

**Part 1: the estimand**

| Term | Meaning | Standard term |
|---|---|---|
| **estimand** | The number the decision needs (θ), defined before any case runs | estimand |
| **population** | Every request the decision is about: from where, over which window, in which environment | target population |
| **use case** | A kind of request the agent is built to handle, such as a refund or an address change. Use cases partition the population: each request belongs to exactly one | stratum |
| **share** | A use case's fraction of the population | stratum weight |
| **cost of a failure** | What one failure in a use case costs, stated by its owner | loss |
| **weight** (w) | How much a use case counts in θ: its share ("traffic"), or share × cost scaled to sum to 1 ("cost") | |
| **pass rate** (μ) | The share of a use case's requests the agent gets right | |
| **θ** | The weighted pass rate, Σ w · μ over use cases. The headline | population parameter |

**Part 2: the sampling design**

| Term | Meaning | Standard term |
|---|---|---|
| **case** | One request, with what's needed to run it and grade the result | sampled unit |
| **frame** | The list cases are drawn from, such as last month's production traces | sampling frame |
| **pool** | Which of two separate sets a case belongs to: the quality set or the bug-finding set | |
| **quality set** | Cases drawn at random from the frame, use case by use case. The only cases that count toward θ̂ | stratified probability sample |
| **bug-finding set** | Cases picked by hand to find failures. They never count toward θ̂ | purposive sample |
| **inclusion probability** (π) | The chance a case had of being drawn. The estimate weights each case by 1/π | inclusion probability |
| **oversampling** | Drawing a use case at more than its share, so its own row can be read. π records it | disproportionate allocation |
| **cluster** | Cases that aren't independent, such as several from one customer. They count as one piece of evidence | cluster |
| **coverage** | The list of situations the bug-finding set has to reach | test adequacy criterion |
| **plan** | How many cases each use case and pool needs, worked out from the decision rule | sample-size calculation, optimum allocation |

**Part 3: the measurement model**

| Term | Meaning | Standard term |
|---|---|---|
| **failure mode** | One way a run can go wrong, such as breaking the refund policy | outcome definition |
| **check** | The yes-or-no test that grades one failure mode: code, or a judge | measurement instrument |
| **judge** | A check made of a model that reads the run | automated rater |
| **grader** | Whatever produces a verdict: a check, a judge, or the eval as a whole | rater |
| **label** | A person's verdict on a whole run. Graders are measured against labels | reference standard |
| **catch rate** | Of the runs a person fails, the share the grader fails | sensitivity, with failure as the positive |
| **clean pass rate** | Of the runs a person passes, the share the grader passes | specificity |
| **J** | Catch rate + clean pass rate − 1. 1 is a perfect grader; 0 is a coin flip | Youden's J |
| **correction** | Adjusting the observed failure rate for the grader's measured errors | Rogan–Gladen estimator, prediction-powered inference |
| **inflation** | How many times more cases a grader's errors cost, compared with a grader that never errs. `max_inflation` caps it | variance inflation factor |
| **trial** | One run of a case. Each case runs k times, because the agent doesn't answer the same way every time | replicate |

**Part 4: the decision rule**

| Term | Meaning | Standard term |
|---|---|---|
| **decision rule** | When to act: the test, its bar or margin, α, power and the looks | decision rule |
| **superiority test** | Shows the candidate is better than the baseline | superiority test |
| **non-inferiority test** | Shows the candidate is no worse than the baseline by more than the margin | non-inferiority test |
| **threshold test** | Shows a rate is on the right side of a fixed bar, such as policy errors below 5% | one-sample test against a fixed bound |
| **bar** | The fixed value a threshold test compares with | |
| **margin** (Δ) | The smallest change that matters to the decision. In a non-inferiority test, the largest drop still counted as "no worse" | minimal important difference, non-inferiority margin |
| **α** | How often you accept acting on a change that isn't real, usually 5% | type I error rate |
| **power** | How often you need to detect a real change of size Δ, usually 80% | power, 1 − β |
| **look** | One time the results are checked against the rule. The number of looks is fixed in advance | interim analysis |
| **gate** | A decision rule a change must pass: the headline, a use case's own rule, or another eval | |
| **multiplicity correction** | Adjusting α when any one of several tests can trigger the action on its own. Gates that must all pass need none | familywise error control; intersection–union test |
| **constraint** | A limit that holds whatever θ says, such as cost per run or latency | constraint |

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

- **Every agent gets an end-to-end eval** (Eval 0, rule 3). Its unit is the whole system as a user meets
   it, subagents included, because the user experiences the whole system and the decision to ship
   is made about the whole system.
- **A component gets an eval of its own only at a context boundary** (Eval 2, rule 3). A subagent with its
   own context receives a defined input, a handoff, that can be captured and replayed. A step that
   shares the orchestrator's context receives the whole transcript so far, which can't be sampled
   or replayed on its own.
- **...and only when someone decides about it separately** (rule 3). A subagent with its own prompt, model
   or owner, changed on its own schedule, earns an eval. One that is only ever changed together with
   the rest of the system doesn't: an eval whose number drives no decision is a diagnostic, and the
   end-to-end eval's checks already cover it.
- **Steps inside a shared context are graded by checks in the eval that encloses them** (rule 3). Steps 1
   and N are covered by Eval 0, through checks on the steps of the run (did it call the right tool,
   with the right arguments).
- **A component eval's cases are the handoffs it receives in production** (rule 4). Eval 2 draws its cases
   from the inputs the orchestrator actually hands Step 2, taken from end-to-end traces. A change to
   routing changes those inputs, so it re-opens every eval downstream of it (rule 26).
- **The end-to-end eval has the last word** (rule 27). A change to a component ships when the component's
   own decision rule passes *and* the end-to-end eval shows no regression. A better component does
   not prove a better system.
- **Several evals gating one change are several tests** (rule 22). When the change ships only if
  every one of them passes, testing each at α already keeps the chance of shipping a bad change at
  α, so no correction is needed; each needs enough cases of its own.

Graders and the store of traces are shared between evals. The four parts are not: each eval writes
down its own.

## 2. The running example

The examples on this page, and in the problems and statistics, use one agent: **a support agent for
an online store**. It answers about 1,000 requests a day:

| Use case | Per day | Share |
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
- **Use cases**: a partition of the population into kinds of request, each with its measured share
  of traffic. Shares sum to 1.
- **Weights**: how much each use case counts in the decision. Either "traffic" (weights equal the
  shares), or a number per use case that the owner states. An unstated weight is unknown, not 1.
- **Decision**: the action this number drives, who owns it, and how often it is made.

The estimand is then one number, the weighted pass rate θ:

θ = Σ_s w_s · μ_s

where μ_s is the true pass rate in use case s and the weights w_s sum to 1. The eval estimates θ.

**Use cases and failure modes are two different things.** A use case is a kind of request ("refund
me"). It carries weight, because it is part of the population the decision is about. A failure mode
is a way the agent can go wrong ("refunded an order outside the policy window"). It is a check, part
of the measurement model (section 5). A single use case can fail in several modes, and one mode can
occur in several use cases. aot-evals 1.x mixed the two into "categories"; 2.0 keeps them apart.

**Example.** Suppose the store's eval uses traffic weights and the system passes 91.0% of requests.
A bug makes refunds fail 15% of the time instead of 5%. That is 2 more bad refunds a day, and θ moves
from 91.0% to 90.8%, which nobody will notice. Now suppose the owner says what a failure costs in
each use case: $1 for a wrong order status, $5 for a botched return, $20 for an address change and $50
for a refund. Weighting each use case by share × cost gives:

| Use case | Share | Cost of a failure | Share × cost | Weight |
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
- **The headline is θ̂ under the stated weights** (rule 2), with the per-use-case table beside it
  as the diagnostic. An unweighted average over use cases is an arbitrary weighting nobody chose.
- **A shift in the population re-opens the estimand** (rule 26). The shares are part of θ, so a
  new mix of traffic means a new θ. Shares are measured again on a schedule.

## 4. Part 2: the sampling design

**The question.** Which cases, drawn how?

**What you write down.**

- **Frame**: where cases come from (production traces, the handoffs into a subagent, written
  tasks), and the window.
- **Two pools.** The **quality set** is a random sample from the frame, stratified by use case,
  with each case's chance of being drawn (its inclusion probability, π) recorded. The
  **bug-finding set** is picked by hand to find failures: hard cases, rare ones, ones from the
  coverage list. It has no π.
- **Cluster key**: what makes cases related (the same template, the same customer, the same source
  trace), so related cases are counted as one piece of evidence and not several.

**Example.** For Eval 0, a quality set of 200 drawn at random from last month's traffic, in
proportion to traffic, would hold about 140 order lookups, 40 returns, 16 address changes and 4
refunds. Four refunds can't say much about refunds, and refunds carry a weight of 0.23. So the
design draws refunds at a higher rate, records that π, and the estimator weights each refund case
back down by 1/π. The estimate stays (approximately) unbiased and the refund use case gets enough cases to
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
- **Spread the budget by optimum allocation** (rule 8): each use case gets cases in proportion to
  its weight × the spread of its outcomes ÷ √(cost of a case), which is Neyman's allocation extended
  for cost (Cochran 1977). A gated use case the formula would short gets its minimum, and the formula
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
you care about. At the default limit of twice the cases, the policy judge above is refused at a 3%
failure rate, while one at catch 0.95 and clean 0.99 costs about 1.4 times ([statistics §3.3](statistics.md#33-what-a-graders-error-costs-you)). It assumes the
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
  version is n ≥ ln(α) / ln(1 − p). No flat count per use case.
- **Compare versions case by case** (rule 18): the same cases, the same trials, a paired test.
  Pairing removes the differences between cases from the comparison.
- **"No significant difference" is not "no worse"** (rule 19). Claiming no regression takes a
  non-inferiority test with a stated margin.
- **A use case gets its own gate only when someone decides about it, and when its rule can be
  powered** (rule 20). Otherwise its row is a diagnostic. If no one will act on it, it shouldn't
  gate.
- **Fix the looks in advance** (rule 21). Labeling until the number clears the bar, or checking
  after every batch, inflates false passes.
- **Correct for multiplicity where one test alone can trigger the action** (rule 22). Flagging a
  regression in any of ten use cases at α = 0.05, with no real change, flags at least one about 40%
  of the time (1 − 0.95¹⁰). A change that ships only when every gate passes is different: testing
  each gate at α keeps the chance of shipping a bad change at α (an intersection–union test; Berger
  1982), so it needs no correction, only enough cases for each gate.
- **An optimizer keeps a split it never sees** (rule 23), and its looks at that split are counted
  (Dwork et al. 2015).
- **Cost and latency are constraints, not part of θ** (rule 24). A change can improve θ and still
  fail its budget.

## 7. The estimate

Put together, the eval's estimate of θ is

θ̂ = Σ_s w_s · μ̂_s,  with  μ̂_s = Σ_{i∈s} (ŷ_i / π_i) / Σ_{i∈s} (1 / π_i)

where ŷ_i is case i's outcome averaged over its k trials and corrected for the checks' error rates,
and π_i is its inclusion probability. (Within each use case this is the Hájek estimator: the Horvitz–Thompson estimator normalized by
its own weights, which is approximately unbiased; Hájek 1971.)

Its interval accounts for three sources of uncertainty: which cases were drawn (with clusters and
use cases), how wrong the judges are (from the size of their calibration sets), and how much trials
of the same case vary. The decision rule says which interval to compute and which bar it has to
clear.

## 8. The eval spec

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
  use_cases: {full_refund: 0.80, partial_refund: 0.15, gift_card: 0.05}
  weights: traffic               # or {use_case: weight}, stated by the owner
  decision: ship refund-subagent changes; owner refunds team; weekly
design:
  frame: handoffs captured in end-to-end traces
  quality_set: {selection: stratified_random, strata: use_cases, seed: 1234, inclusion_prob: per_case}
  bug_finding_set: {selection: purposive}       # never enters the rate
  cluster_key: order_template
measurement:
  checks:
    breaks_policy: {type: judge}  # its catch and clean pass rates live in its calibration file
    refund_amount_correct: {type: code}
  trials_per_case: 3
  max_inflation: 2.0             # a judge may cost at most twice the cases a code check would
  correction: ppi                # or rogan_gladen, or none when every check is code
decision_rule:
  test: threshold                # superiority | non_inferiority | threshold
  bar: 0.05
  margin: null
  alpha: 0.05
  power: 0.80
  looks: fixed                   # fixed | sequential | optimizer_holdout
  multiplicity: none             # holm when any one gate alone can act; none when all must pass
  constraints: {cost_per_success_usd: 0.05, latency_p90_ms: 8000}
```

The field names are a sketch; [v2-design.md](v2-design.md) settles them. The judges' measured error rates
are not in the spec. They are measurements, kept with each judge's calibration, so recalibrating a
judge doesn't change the spec.

## 9. Changing an eval

Every change to an eval is one of three kinds, and the four parts say which:

| Change | When | What happens |
|---|---|---|
| **Expand** | New cases from the same frame, same use cases, same checks, with known π | Same version. The interval narrows; θ is the same quantity |
| **Revise** | The estimand, weights, use cases, design or checks change. A new judge counts | Major version. Re-run the baseline; old and new scores are different quantities and are not compared |
| **Split** | A use case or a component gets its own decision, owner and powered rule | A new eval with its own four parts. The old eval keeps the use case in its estimand. Whether a sub-score adds anything beyond the total has a test (Haberman 2008) |

A new kind of request is a new use case, so it is a revision, not an expansion. Pruning for cost may
remove bug-finding cases freely; it may not remove quality-set cases, because that changes their π
and biases θ̂ (rule 25).

## 10. The rules in one table

Each rule names the part it follows from, the [problem](problems.md) that shows why it matters, and
the section of [statistics.md](statistics.md) that derives it.

| # | Rule | Part | Problem | Statistics |
|---|---|---|---|---|
| 1 | One eval, one estimand: one unit, one population, one decision | Estimand | 2 | §1.3 |
| 2 | The headline is θ̂ under the stated weights, with the per-use-case table as the diagnostic | Estimand | 1 | §1.1 |
| 3 | Every agent has an end-to-end eval; components get their own only at a context boundary, when decided on separately | Estimand | 2 | §1.3 |
| 4 | A component eval's population is its production handoffs | Estimand, design | 2 | §1.3, §2.1 |
| 5 | Bug-finding cases never enter a rate without a recorded π | Design | 4 | §2.1 |
| 6 | The quality set is a seeded random draw with π per case | Design | 4 | §2.2 |
| 7 | Case counts come from the decision rule's power, with judge error included | Decision rule | 9 | §4.1, §3.3 |
| 8 | The budget goes by optimum allocation (Neyman's, with cost), around each gated use case's minimum | Design | 4 | §2.3 |
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
| 20 | A use case gates only when decided on separately and when its rule can be powered | Decision rule | 1 | §1.2 |
| 21 | Fix the looks in advance | Decision rule | 12 | §4.7 |
| 22 | Correct for multiplicity where one test alone can trigger the action; gates that must all pass need none | Decision rule | 2, 12 | §4.6 |
| 23 | An optimizer keeps a split it never sees | Decision rule | 12 | §4.7 |
| 24 | Cost and latency are constraints, not part of θ | Decision rule | 10 | §4.8 |
| 25 | Prune only where θ̂ stays unbiased | Design | 3 | §2.6 |
| 26 | A population shift, or a routing change upstream, re-opens the estimand | Estimand | 3 | §1.4 |
| 27 | A component change ships only when the end-to-end eval also shows no regression | Estimand, decision rule | 2 | §1.3, §4.5 |

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
aot-evals builds on all of it. The closest work, against the four parts (✓ covers it; ~ partly;
– not addressed), judged from each paper's full text where it was available and its abstract
otherwise (November 2026):

| Work | Estimand | Sampling design | Grader error | Decision rule | Grader error in power | Rules for building a suite |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Miller (2024) | ✓ | ✓ clustered | – | ✓ paired tests, power | – | – |
| Chouldechova et al. (2024) | ✓ | ✓ | – | – | – | – |
| Binette and Reiter (2024) | ✓ | ✓ | ~ annotation as part of data acquisition | ~ intervals only | – | – |
| Huang (2026) | ✓ | – | ~ verifier error, reported | ~ practical margin | – | ~ reporting guidance |
| Feng et al. (2026) | ~ one failure rate | – | ✓ | ✓ threshold test | ✓ | – |
| Chen, Guo and Li (2026) | – | – | ✓ via PPI | ✓ power, sample size | ✓ via PPI's variance | – |
| Kim (2026) | – | ✓ two-stage, known π | ~ via R² | ~ precision target | ✓ | – |
| Fiedler (2026) | – | – | ✓ incl. differential error | – | – | – |
| Schultzberg (2026) | – | – | ~ | ✓ ship, test or stop | – | – |
| Kotawala (2026) | – | ~ clusters | – | ✓ paired, multiplicity, anytime-valid | – | – |
| Reuel et al. (2024); Zhu et al. (2025) | – | – | – | – | – | ~ checklists, not derived |
| **aot-evals 2.0** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ derived from the four parts |

What the table describes:

- Miller (2024) treats eval questions as a draw from a larger population, with clustered standard
  errors, paired comparisons and power analysis, and does not model grading error.
- Chouldechova et al. (2024) define the population an eval measures, and argue that an eval sampled
  by red-teaming would overstate how often failures occur in normal use.
- Binette and Reiter (2024) bring clinical-trial estimands to ML evaluation (metric, population, how
  data and labels are acquired, aggregation).
- Huang (2026) asks what an agent leaderboard rank actually compares: the estimand, the agent
  configuration as the unit, the verifier's error rates and a practical margin.
- Feng et al. (2026) give a threshold test whose critical value and power are written in the judge's
  error rates; Chen, Guo and Li (2026) give power and sample size for prediction-powered inference;
  Kim (2026) splits a budget between human and judge labels under a stratified two-stage design.
- Fiedler (2026) shows that correcting two versions with one shared estimate of a judge's error
  rates, when its rates differ between them, can reverse a comparison with apparent confidence; Li
  (2026) measures judge error that changes with the agent's version.
- Schultzberg (2026) gives a closed-form rule for when offline evals alone justify shipping;
  Kotawala (2026) gives resolution diagnostics for paired comparisons.
- Reuel et al. (2024) and Zhu et al. (2025) give checklists for building benchmarks, as practice
  rather than derivation.

**Wider related work.** Correcting a judge's rates with human labels is prediction-powered inference
(Angelopoulos et al. 2023; Angelopoulos, Duchi & Zrnic 2026), applied to model evaluation by Boyeau et
al. (2024) and stratified by Fisch et al. (2024); related corrections and reporting standards for
LLM judges are Lee et al. (2026), Chen et al. (2026), Collot et al. (2026), Messing (2026) and
Arawjo (2026). Design-based prevalence estimation with LLM labels is in industrial use (Dobi et al.
2026). Validity frameworks for AI evaluation are conceptual rather than statistical (Wallach et al.
2025; Salaudeen et al. 2025; Weidinger et al. 2025), and a review of 445 LLM benchmarks found
patterns in what they measure and how they score it that undermine the validity of their claims
(Bean et al. 2025). Power analysis came to NLP with Card et al. (2020).

**Grader error in power is old outside AI.** Misclassification shrinks a difference between
proportions (Bross 1954) and costs a test efficiency (Rubin, Rosenbaum & Cobb 1956; Walsh 1963; Mote
& Anderson 1965; Quade et al. 1980; Lagakos 1988); sample sizes that compensate for it are worked out
by Tavaré, Sobel and Gilles (1995) and in closed form by Hársfalvi and Reiczigel (2024). The factor
sensitivity + specificity − 1 is Youden's index (Youden 1950), and the corrected prevalence's
variance scales with its inverse square (Rogan & Gladen 1978; Lang & Reiczigel 2014).

Two results limit what the measurement model can do. Dorner, Nastl and Hardt (2025) show that
correcting a judge that is no stronger than the model being judged saves at most half the human
labels, so labels don't become free. And the shared-calibration reversal above (Fiedler 2026) is why
a changed judge, or a changed agent under the same judge, calls for fresh labels (rule 13).

## 13. References

- AERA, APA & NCME (2014). *Standards for Educational and Psychological Testing.* Washington, DC: American Educational Research Association.
- Angelopoulos, A. N., Bates, S., Fannjiang, C., Jordan, M. I. & Zrnic, T. (2023). Prediction-powered inference. *Science* 382(6671):669–674. doi:10.1126/science.adi6000
- Angelopoulos, A. N., Duchi, J. C. & Zrnic, T. (2026). PPI++: Efficient prediction-powered inference. *The Annals of Applied Statistics* 20(3):2235–2252. doi:10.1214/26-AOAS2215. arXiv:2311.01453
- Arawjo, I. (2026). How to run statistics over LLM judges and trust the results: Calibrated inference for small-sample AI evaluation with evalstats. arXiv:2609.35815
- Bean, A. M. et al. (2025). Measuring what matters: Construct validity in large language model benchmarks. *NeurIPS 2025, Datasets and Benchmarks Track*. doi:10.52202/085713-0590. arXiv:2511.04703
- Binette, O. & Reiter, J. P. (2024). Improving the validity and practical usefulness of AI/ML evaluations using an estimands framework. arXiv:2406.10366
- Boyeau, P., Angelopoulos, A. N., Yosef, N., Malik, J. & Jordan, M. I. (2024). AutoEval done right: Using synthetic data for model evaluation. arXiv:2403.07008
- Berger, R. L. (1982). Multiparameter hypothesis testing and acceptance sampling. *Technometrics* 24(4):295–300. doi:10.2307/1267823
- Bross, I. (1954). Misclassification in 2 × 2 tables. *Biometrics* 10(4):478–486. doi:10.2307/3001619
- Card, D., Henderson, P., Khandelwal, U., Jia, R., Mahowald, K. & Jurafsky, D. (2020). With little power comes great responsibility. *EMNLP 2020*, 9263–9274. doi:10.18653/v1/2020.emnlp-main.745
- Chen, Y. T., Guo, M. & Li, S. (2026). Power analysis for prediction-powered inference. arXiv:2603.16041
- Chen, Y. T., Lu, S., Li, S., Guo, M. & Li, S. (2026). Efficient inference for noisy LLM-as-a-judge evaluation. arXiv:2601.05420
- Chouldechova, A. et al. (2024). A shared standard for valid measurement of generative AI systems' capabilities, risks, and impacts. NeurIPS 2024 Workshop on Statistical Foundations of LLMs and Foundation Models. arXiv:2412.01934
- Cochran, W. G. (1977). *Sampling Techniques* (3rd ed.). New York: Wiley.
- Cohen, J. (1960). A coefficient of agreement for nominal scales. *Educational and Psychological Measurement* 20(1):37–46. doi:10.1177/001316446002000104
- Collot, S., Fraser, C., Zhao, J., Shen, W. F., Willi, T. & Leontiadis, I. (2026). Balanced accuracy: The right metric for evaluating LLM judges, explained through Youden's J statistic. *EACL 2026, Industry Track*, 927–936. arXiv:2512.08121
- Cronbach, L. J. & Meehl, P. E. (1955). Construct validity in psychological tests. *Psychological Bulletin* 52(4):281–302. doi:10.1037/h0040957
- Dobi, A., Manickavasagam, A., Thompson, B., Yang, X. & Farooq, F. (2026). Measuring the prevalence of policy violating content with ML assisted sampling and LLM labeling. arXiv:2602.18518
- Dorner, F. E., Nastl, V. Y. & Hardt, M. (2025). Limits to scalable evaluation at the frontier: LLM as judge won't beat twice the data. *ICLR 2025*. arXiv:2410.13341
- Dwork, C., Feldman, V., Hardt, M., Pitassi, T., Reingold, O. & Roth, A. (2015). The reusable holdout: Preserving validity in adaptive data analysis. *Science* 349(6248):636–638. doi:10.1126/science.aaa9375
- Feng, C., Shen, M., Balashankar, A., Gerner-Beuerle, C. & Rodrigues, M. R. D. (2026). Noisy but valid: Robust statistical evaluation of LLMs with imperfect judges. *ICLR 2026*. arXiv:2601.20913
- Fiedler, J. (2026). Bias and uncertainty in LLM-as-a-judge estimation. arXiv:2605.06939
- Fisch, A., Maynez, J., Hofer, R. A., Dhingra, B., Globerson, A. & Cohen, W. W. (2024). Stratified prediction-powered inference for hybrid language model evaluation. *NeurIPS 2024*, 111489–111514, published as "Stratified prediction-powered inference for effective hybrid evaluation of language models". doi:10.52202/079017-3541. arXiv:2406.04291
- Frankl, P. G., Hamlet, R. G., Littlewood, B. & Strigini, L. (1998). Evaluating testing methods by delivered reliability. *IEEE Transactions on Software Engineering* 24(8):586–601. doi:10.1109/32.707695
- Haberman, S. J. (2008). When can subscores have value? *Journal of Educational and Behavioral Statistics* 33(2):204–229. doi:10.3102/1076998607302636
- Hájek, J. (1971). Comment on "An essay on the logical foundations of survey sampling, part one" by D. Basu. In V. P. Godambe & D. A. Sprott (Eds.), *Foundations of Statistical Inference* (p. 236). Toronto: Holt, Rinehart and Winston.
- Hársfalvi, P. & Reiczigel, J. (2024). The effect of misclassification on sample size for one and two-sample tests with binary endpoints. *Journal of Biopharmaceutical Statistics* 36(3):561–572. doi:10.1080/10543406.2024.2444231
- Horvitz, D. G. & Thompson, D. J. (1952). A generalization of sampling without replacement from a finite universe. *JASA* 47(260):663–685. doi:10.1080/01621459.1952.10483446
- Huang, W.-J. (2026). What does an LLM-agent leaderboard rank actually compare? arXiv:2609.07785
- Kim, J. P. (2026). Augmenting human evaluation with LLM judges: How many human reviews do you need? arXiv:2605.16354
- Kish, L. (1965). *Survey Sampling.* New York: Wiley.
- Kotawala, A. (2026). Resolution diagnostics for paired LLM evaluation. ICML 2026 Workshop on Hypothesis Testing. arXiv:2605.30315
- Lagakos, S. W. (1988). Effects of mismodelling and mismeasuring explanatory variables on tests of their association with a response variable. *Statistics in Medicine* 7(1–2):257–274. doi:10.1002/sim.4780070126
- Lang, Z. & Reiczigel, J. (2014). Confidence limits for prevalence of disease adjusted for estimated sensitivity and specificity. *Preventive Veterinary Medicine* 113(1):13–22. doi:10.1016/j.prevetmed.2013.09.015
- Lee, C., Zeng, T., Jeong, J., Sohn, J. & Lee, K. (2026). How to correctly report LLM-as-a-judge evaluations. *ICML 2026*. arXiv:2511.21140
- Li, J. (2026). Frozen judges, moving agents: Version-dependent LLM-judge error and the limits of judge-assisted agent evaluation. arXiv:2609.34198
- Messick, S. (1989). Validity. In R. L. Linn (Ed.), *Educational Measurement* (3rd ed., pp. 13–103). New York: American Council on Education / Macmillan.
- Messing, S. (2026). Hidden measurement error in LLM pipelines distorts annotation, evaluation, and benchmarking. *NeurIPS 2026*. arXiv:2604.11581
- Miller, E. (2024). Adding error bars to evals: A statistical approach to language model evaluations. arXiv:2411.00640
- Mote, V. L. & Anderson, R. L. (1965). An investigation of the effect of misclassification on the properties of χ²-tests in the analysis of categorical data. *Biometrika* 52(1–2):95–109. doi:10.1093/biomet/52.1-2.95
- Musa, J. D. (1993). Operational profiles in software-reliability engineering. *IEEE Software* 10(2):14–32. doi:10.1109/52.199724
- Neyman, J. & Pearson, E. S. (1933). On the problem of the most efficient tests of statistical hypotheses. *Phil. Trans. R. Soc. A* 231:289–337. doi:10.1098/rsta.1933.0009
- Neyman, J. (1934). On the two different aspects of the representative method: The method of stratified sampling and the method of purposive selection. *JRSS* 97(4):558–625. doi:10.2307/2342192
- Quade, D., Lachenbruch, P. A., Whaley, F. S., McClish, D. K. & Haley, R. W. (1980). Effects of misclassifications on statistical inferences in epidemiology. *American Journal of Epidemiology* 111(5):503–515. doi:10.1093/oxfordjournals.aje.a112930
- Reuel, A., Hardy, A., Smith, C., Lamparth, M., Hardy, M. & Kochenderfer, M. J. (2024). BetterBench: Assessing AI benchmarks, uncovering issues, and establishing best practices. *NeurIPS 2024, Datasets and Benchmarks Track*. doi:10.52202/079017-0685. arXiv:2411.12990
- Rogan, W. J. & Gladen, B. (1978). Estimating prevalence from the results of a screening test. *American Journal of Epidemiology* 107(1):71–76. doi:10.1093/oxfordjournals.aje.a112510
- Rubin, T., Rosenbaum, J. & Cobb, S. (1956). The use of interview data for the detection of associations in field studies. *Journal of Chronic Diseases* 4(3):253–266. doi:10.1016/0021-9681(56)90028-5
- Salaudeen, O. et al. (2025). Measurement to meaning: A validity-centered framework for AI evaluation. arXiv:2505.10573
- Schultzberg, M. (2026). When can you ship on evals alone? Trial-level surrogacy for offline evaluation of LLM systems. arXiv:2610.10142
- Tavaré, C. J., Sobel, E. L. & Gilles, F. H. (1995). Misclassification of a prognostic dichotomous variable: Sample size and parameter estimate adjustment. *Statistics in Medicine* 14(12):1307–1314. doi:10.1002/sim.4780141204
- Wald, A. (1947). *Sequential Analysis.* New York: Wiley.
- Wallach, H. et al. (2025). Position: Evaluating generative AI systems is a social science measurement challenge. *ICML 2025*. arXiv:2502.00561
- Walsh, J. E. (1963). Loss in test efficiency due to misclassification for 2 × 2 tables. *Biometrics* 19(1):158–162. doi:10.2307/2527579
- Weidinger, L. et al. (2025). Toward an evaluation science for generative AI systems. arXiv:2503.05336
- Youden, W. J. (1950). Index for rating diagnostic tests. *Cancer* 3(1):32–35. doi:10.1002/1097-0142(1950)3:1<32::aid-cncr2820030106>3.0.co;2-3
- Zhu, Y. et al. (2025). Establishing best practices for building rigorous agentic benchmarks. arXiv:2507.02825

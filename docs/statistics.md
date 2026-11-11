# The statistics behind aot-evals

aot-evals does the arithmetic so you don't have to. Every number it prints carries `n`, `k` and an
interval, and the gates refuse claims the data can't support. This document is for anyone who
wants to know **why** a rule is what it is, or **when to change it**: how many cases, how many
trials, how many labels and of which kind, when a judge can be trusted, when a difference is real,
and what to do next as the suite grows.

Each section follows the same shape: the decision you face, what aot-evals does, the statistics
behind it (with the source), and when to deviate. The arithmetic is in small formulas you can skip.
[§9](#9-audit-every-rule-of-thumb-against-its-source) audits every rule of thumb in the method
against the literature, and [§10](#10-proposals) lists the changes that analysis suggests and that
this release does not yet make.

Statuses used below: **computed** (the CLI prints it and `report.json` carries it), **gated** (a
gate reads it), **library** (a function in `aot_evals.stats` that the CLI doesn't call yet, named
as `stats.<function>`), **proposed** (described here, not implemented; see §10).

## Contents

1. [The measurement model](#1-the-measurement-model)
2. [Designing the test set](#2-designing-the-test-set)
3. [Constructing cases](#3-constructing-cases)
4. [Trials, noise and k](#4-trials-noise-and-k)
5. [Graders: checks and judges](#5-graders-checks-and-judges)
6. [People: labels, labelers and whole-run agreement](#6-people-labels-labelers-and-whole-run-agreement)
7. [Comparing versions](#7-comparing-versions)
8. [Evolving the suite](#8-evolving-the-suite)
9. [Audit: every rule of thumb against its source](#9-audit-every-rule-of-thumb-against-its-source)
10. [Proposals](#10-proposals)
11. [References](#11-references)

---

## 1. The measurement model

An eval is a measurement, and each of its numbers is an estimate with three sources of error:

| Source | Question | Shrinks with | Borrowed from |
|---|---|---|---|
| **Sampling** | Would different cases have given a different number? | more cases, chosen well | survey sampling (Cochran; Neyman 1934; Horvitz & Thompson 1952) |
| **Noise** | Would running the same cases again? | more trials per case | generalizability theory (Cronbach et al. 1972); clustered errors (Miller 2024) |
| **Instrument** | Would a person have graded it the same way? | better checks, calibrated judges, more labels | diagnostic-test statistics (Rogan & Gladen 1978; Begg & Greenes 1983); psychometrics |

Most eval tooling reports only the first, as one pass rate with no interval. aot-evals keeps all
three apart because each needs a different fix: more cases do nothing for a miscalibrated judge,
and more trials do nothing for a suite with too few cases.

Five fields supply the methods, and they rarely cite each other:

- **Survey sampling** sizes and weights the case sets (§2).
- **Software testing** says what the set must cover and whether it catches faults (§2.4, §2.5).
- **Psychometrics** decomposes noise (§4), designs graders (§5.1) and keeps scores comparable
  across versions (§8).
- **Diagnostic-test statistics** treats every check and judge as a test with a sensitivity and a
  specificity, and corrects rates for its error (§5).
- **Experiment design** pairs comparisons, sets power and controls repeated looks (§7).

The method's rule that **unknown values are `null`, never `0`** is a statistical rule as well: a
zero is a measurement, and a measurement that wasn't made must not look like one.

### 1.1 What the score is for: category weights

**Decision.** What single quantity is the suite trying to estimate and improve?

**What aot-evals does today.** The headline is the traffic-weighted pass rate of the
quality-estimate set (M14). Each category also has a `worth` (high, medium, low), but `worth` is
ordinal: it orders the report and the authoring queue and enters no arithmetic.

**Why that is a choice, not a default.** A traffic-weighted pass rate counts every failure as
equally bad: a wrong number in a report and a deleted customer record each cost one failed run.
For some agents that is close enough, and for others it is badly wrong. The estimand should say
what a failure in each category is worth, as a **ratio** to the others:

  objective = Σ share × weight × pass rate  /  Σ share × weight

The share-weighted estimator stays as it is; only the weights change. Equal weights are allowed,
but they must be stated, so the traffic-weighted score becomes the stated special case rather than
an unexamined default (`stats.objective_weights`; requiring a numeric weight at C3 is proposal
P14). An unstated weight is unknown, not 1.

**The blind-spot check.** A weighted score can still miss a category. A drop of δ in a category
with objective weight w moves the score by w·δ. If that is below the comparison's detectable
effect, the score cannot see the drop. A category with 2% of traffic that drops 10 points moves a
traffic-weighted score by 0.2 points, and a 100-case paired comparison detects about 11. Weighting
helps less than it seems: even at 60 times the weight of the rest, that category's 10-point drop
moves the score only 5.5 points. So a category that matters and is blind gets a **guardrail** of its
own: a non-inferiority test on that category alone, sized in §2.2 (`stats.blind_spot`; P14).

### 1.2 Are failures equally costly?

Much of the default arithmetic assumes they are: flat case targets per category, symmetric floors
for TPR/TNR and for catch/clean pass rates, Youden's J for thresholds, unweighted pass rates in
comparisons. Before choosing between these flat rules and the cost-aware ones (category weights,
P14; cost-weighted thresholds, P4; weighted allocation, P5), check whether costs really differ.
The check has two sources, because what the owner expects and what the agent does can differ, and
the expensive failures are often ones nobody predicted.

**Ask the owner.**

- In Assess, one question: *are some of this agent's mistakes much worse than others? Which ones?*
  Prompts that help: can it change or delete records, send messages, or move money? Would anyone
  notice a mistake before it did damage?
- At C3 and C4, when the owner confirms categories and failure modes: do the values in the cost row
  really differ? Today the row is checked for presence only. Record whether the owner judged costs
  even or uneven, and why.

**Look at the actual failures.** Tag each baseline failure (C12) and each C19 disagreement with
what it cost: did it write, delete or send; can it be undone; would a person have noticed before
acting on it? `stats.failure_severity` turns those answers into low, medium or high: an
irreversible write is high, a reversible side effect or an unnoticeable wrong answer is medium, a
wrong answer a person would catch is low. `stats.cost_flags` then flags a category whose failures
span severities with a high one among them, or whose worst failure is worse than its declared cost.
The canonical case is **an agent asked for a report that changes CRM state**: a read-only request
that writes costs far more than a wrong number, in a category the owner would rate low-cost. Feed
each flag back to the cost row (C3), to the failure modes (C4: a side-effect check on read-only
requests) and to allocation (C5).

**What it decides.** If costs come out roughly even, the flat rules are fine, and the report should
say so. If they are uneven, the report says where, and allocation, floors and comparisons should
weight by cost, or at least flag where unweighted numbers mislead: a comparison that is "better" on
pass rate while it adds a costly failure, or a judge that clears symmetric floors while missing the
expensive failures. The check runs in Assess, at C3/C4, after every baseline and with C19 triage
(proposal P13, ahead of P4, P5 and P14, which all depend on its answer).

---

## 2. Designing the test set

### 2.1 Two sets, because there are two questions

**Decision.** Should the cases that find bugs also tell you how good the agent is?

**What aot-evals does.** It keeps two disjoint sets (method §2.3): an **error-finding** set,
enriched with hard and rare cases, and a **quality-estimate** set, sampled in proportion to
traffic. Only the second may be called "quality" (G6).

**Why.** These are two different estimands. Error-finding is *elicitation*: the goal is to see each
failure at least once, so cases are chosen where failures are likely. Quality is *estimation*: the
goal is an unbiased production rate, so the probability of choosing each case must be known. An
enriched set over-represents failures by design, so its pass rate is biased low by an amount nobody
knows. Survey sampling allows one set to serve both purposes only when each case's **inclusion
probability** is recorded at sampling time, so each case can be reweighted by its inverse
(Horvitz & Thompson 1952; for models, active testing, Kossen et al. 2021). aot-evals does not record
inclusion probabilities today, so the sets stay separate (proposal P5).

**The quality-estimate set must be drawn, not picked.** Proportional counts per category are not
enough: if the author chooses which traces fill each quota, the set is a quota sample, and a quota
sample carries the author's selection bias with no way to measure it. Each category's cases should
be a **seeded simple random draw** from that category's traces, with the seed and each case's
inclusion probability recorded, and every skip after the draw (a trace with PII that can't be
scrubbed, a duplicate) recorded with its reason and replaced from a second seeded draw, never by
hand (`stats.stratified_draw`; P5).

### 2.2 Sizing a category's cases: improvement, regression guard and detection

**Decision.** How many cases does each category get?

**What aot-evals does today.** `allocate` targets 10 per category, 3 for simple ones, and now prints
the rarest failure each target will surface (**computed**, M30). The rule reads neither the
category's weight nor its measured accuracy, which are the two inputs that should set its count.
Use it to start, before any baseline exists; after the first baseline, size each category as below
(proposal P14).

A category's cases do one of two jobs, and the jobs need different arithmetic, so one flat number
can't serve both.

**Improvement: seeing whether a change helped.** Size it with the paired comparison the method
uses. The cases needed depend on the smallest change the owner wants to see and on the share of
cases that flip between versions (§7.1), not directly on the category's accuracy:
N ≈ 7.85·d/Δ² for a net change Δ at flip rate d (`stats.cases_for_flip_rate`). Realistic gains
scale with the room left to improve, so "harder needs more cases" doesn't hold. Halving the failure
rate, unpaired (pairing lowers every row), takes per version (`stats.cases_per_arm`):

| Failure rate | Cases per version to see it halved |
|---:|---:|
| 50% | 55 |
| 30% | 118 |
| 10% | 432 |
| 1% | 4,671 |

**Detection: seeing failures you can't afford to miss.** If a failure affects a fraction *p* of a
category's runs, *n* cases show it at least once with probability 1 − (1 − *p*)ⁿ. Fix that chance at
95% and solve:

| Cases | Surfaces, with 95% probability, a failure that affects at least |
|---:|---:|
| 3 | 63% of runs |
| 10 | 26% |
| 20 | 14% |
| 30 | 9.5% |
| 59 | 5% |
| 100 | 3% |
| 299 | 1% |

Detection applies **per failure mode**, and this is where hard categories really do need more
cases: a category at 70% is usually several failure modes at a few percent each, not one at 30%,
and each needs enough cases to be seen.

The same number, read backwards, is the **zero-failure bound**: if all *n* cases pass, the failure
rate could still be as high as 1 − 0.05^(1/*n*), about 3/*n* (the "rule of three", Hanley &
Lippman-Hand 1983). The report prints it on every category with no failure
(`zero_failure_bound`), over clusters rather than cases when cases carry a cluster key (§4.3).
A clean run on 10 cases cannot rule out a failure that hits one run in five.

**Two states per category, with costly failure modes on top.** Recomputed after every baseline,
weight and measured accuracy put each category in one of two states. Separately, a category in
either state can have rare, costly failure modes (§1.2), each adding a detection need.

| | Its cases do | Sized by |
|---|---|---|
| **Room to improve** | improvement | the smallest change worth seeing there, and its flip rate |
| **Solved**, the remaining failures explained | regression guard | the drop it must catch, set by the weight |
| **On top, in either state:** a rare, costly failure mode | detection, per mode | that mode's rate; or a check on every production run when offline cases can't reach it |
| **On top, if the blind-spot check fired** (§1.1) | a guardrail | the drop the category alone must catch |

A category's target is the largest of these needs, since the same cases serve every job, subject
to a floor (`stats.allocation_target`). Weight enters through the inputs: a heavier category gets a
smaller worthwhile change, a tighter tolerated drop and more of its failure modes counted as costly.
Scaled to the budget by weight, this is the error-finding counterpart of the Neyman allocation in
§2.3.

**Solved has to be shown.** A category at 99% has one question: what is the 1%?

| The 1% is | How you tell | Then |
|---|---|---|
| Noise | the case passes on a re-run (within-case variance, M31) | solved |
| A gold or check error | a person passes the run (C19 triage: `wrong-expectation`, `check-bug`) | fix it, then solved |
| A real rare failure | it fails consistently on some input | low weight: solved and accepted; high weight: solved, with that failure as a costly mode with its own detection need |

**A solved category needs a regression guard.** Near 100%, with noise ruled out, one new
consistent failure is signal, so the guard is sized by detection: the smallest *n* with
1 − (1 − δ)ⁿ ≥ 95% for a tolerated drop δ set by the weight.

| Tolerated drop | Cases |
|---:|---:|
| 10 points | 29 |
| 5 points | 59 |
| 2 points | 149 |
| 1 point | 299: use a check on every production run or a canary instead |

This replaces the `simple` flag's "3 cases" with something checkable: a category gets few cases
because it is shown solved and its weight tolerates a loose guard, not because it looks easy.

**For a rare, costly failure,** don't wait for random cases to find it. Write cases that target it
directly: contrast sets, metamorphic relations, the situations grid (§3). Targeted cases are
elicitation, so they can't estimate its rate. To estimate the rate, sample with recorded weights
(importance sampling, Zhao et al. 2016; Wu & Hilton 2024).

### 2.3 Sizing the quality-estimate set: how precise must the number be?

**Decision.** How many cases, and how are they split across categories?

**What aot-evals does.** n = z²·p(1 − p)/h², with p = 0.5 (the worst case) and h the half-width
the owner needs (default ±5 points, 385 cases). The cases are split in proportion to each
category's share of traffic, and the estimate is the share-weighted pass rate (M14).

**Why.** This is stratified sampling with **proportional allocation** (Cochran, ch. 5). It is
unbiased and easy to explain. Two refinements matter at small sizes:

- **Neyman allocation** puts more cases where the objective weight times the standard deviation is
  largest, with objective weight = share × category weight (§1.1), so it carries the weight as well
  as the variance. A category at 99% pass needs far fewer cases than one at 70% to reach the same
  precision. With unequal variances it gives the narrowest interval on the weighted objective for
  a fixed budget (`stats.neyman_allocation`; proposal P5).
- **Small strata.** Proportional allocation gives a category with 1% of traffic about 4 of 385
  cases, too few to say anything about that category itself. Domain estimation sets a minimum per
  stratum and reweights (proposal P5). Until then, the per-category rows of the quality-estimate set
  are wide, and the report shows how wide.

**Intervals.** The weighted interval is a normal approximation with an Agresti–Caffo-style
adjustment, so that a stratum at 0% or 100% never contributes zero variance. Normal intervals are
too narrow below a few hundred items (Bowyer et al. 2025), which is why single-category rates use
Wilson intervals and why a beta-posterior interval for the weighted estimate is listed as P5.

### 2.4 Coverage: what should the set cover?

**Decision.** Is anything missing?

**What aot-evals does.** Coverage is counted against a list written outside the suite: the
product spec, a tool surface, a help-center topic list (method §2.4, G5). The discovery report lays
task types against **situations** (unanswerable, ambiguous, forbidden, tool error and so on) as a
grid.

**Why.** A coverage claim needs a denominator, and one derived from the cases always reads 100%.
Psychometrics calls the external list a **test blueprint**, and content validity depends on its
weights coming from outside the test (Lawshe 1975; Messick 1995). Software testing calls the grid
**category-partition** (Ostrand & Balcer 1988): the case space written as factors and levels, with
impossible combinations struck out.

The grid's cells grow multiplicatively. **Combinatorial (t-way) testing** makes it tractable: most
field faults involve one or two interacting factors, and nearly all involve six or fewer (Kuhn,
Wallace & Gallo 2004). Take a case space of six factors with 8, 5, 4, 4, 3 and 3 levels. The full
grid is 5,760 cases. A **covering array** in which every pair of levels appears at least once needs
about 43, and every triple about 191. So "every pair of factors covered" costs about what "10 per
category" costs, and unlike that rule it can be checked by someone else (proposal P10).

### 2.5 Adequacy: would the set catch a fault?

**Decision.** Is the suite good enough to trust a clean result?

**What aot-evals does.** The C7 screens are planted faults: the do-nothing agent must fail, the
reference must pass, a do-nothing agent that claims success must fail (G10), other correct
wordings must pass and an answer with every number wrong is reported (M22).

**Why.** In software testing this is **mutation analysis** (DeMillo, Lipton & Sayward 1978): plant
known faults, count the fraction the suite catches (the mutation score), and use it as the suite's
adequacy. Mutant detection correlates with detecting real faults (Just et al. 2014). Agent
benchmarks that skipped this step were wrong by large margins. SWE-Bench+ found that 31% of
"resolved" issues passed only because the tests were weak (Aleithan et al. 2024), and the Agentic
Benchmark Checklist found errors of up to 100% in relative terms (Zhu et al. 2025). The C7 screens
are one fixed set of mutants. A standing mutation score over agent mutants (drop a tool, stale a
document, delete a policy line, change a unit) is proposal P9.

---

## 3. Constructing cases

The statistics of case construction are mostly about **validity**: does a case test what it says it
tests?

| Practice in aot-evals | Formal basis | What it guards against |
|---|---|---|
| Cases from real traffic, with provenance (C0, C6) | content validity; sampling frame | testing a distribution nobody sends |
| Human read and the reference / do-nothing screens (C7) | label-error audits: at least 3.3% of labels are wrong across ten common test sets, and model rankings flip on corrected labels (Northcutt et al. 2021) | a wrong expected answer hiding a real failure |
| Other correct wordings must pass (C7, accepted variants) | construct validity: the check measures correctness, not phrasing | false fails on paraphrases |
| A check never reads the agent's own success claim (G10) | verification bias (Begg & Greenes 1983): the referent must not depend on the thing being tested | the "confident closing" failure, where state and claim disagree |
| Leakage screen for public-source cases (M26) | contamination tests (Oren et al. 2023; Yang et al. 2023: rephrased items pass n-gram checks) | memorized answers |

Four generators are worth knowing. They all fill the **error-finding** set, since they choose
cases to surface failures and say nothing about production rates:

- **Partial-input baselines** (Poliak et al. 2018; Gururangan et al. 2018). Run the case without
  the file, the tool or the user turn. If the agent still passes, the case doesn't need what it
  claims to test.
- **Contrast sets** (Gardner et al. 2020): a small edit that flips the expected answer. Model
  scores fell by up to 25% on them. A premise the files contradict is the agent version.
- **Metamorphic relations** (Chen et al. 1998; Hyun et al. 2023). When the right answer is unknown,
  test a relation between answers: a paraphrase leaves the result unchanged, an irrelevant
  document leaves it unchanged, doubling a quantity doubles the total. One irrelevant clause cut
  model scores by up to 65% on GSM-Symbolic (Mirzadeh et al. 2024). Each relation brings its own
  oracle.
- **Property-based testing with shrinking** (Claessen & Hughes 2000). Generate many inputs and
  shrink each failure to the smallest case that still fails. A drafted case that fails should be
  shrunk before it is committed.

Synthetic cases (method §4.3) are elicitation by construction. Model-written evaluations can be
good: crowdworkers agreed with 90–100% of the labels in Perez et al. (2022). But synthetic cases
never join the quality-estimate set, because their selection probability is undefined.

---

## 4. Trials, noise and k

### 4.1 Where the noise comes from

**Decision.** More cases, or more trials per case?

**What aot-evals does.** The baseline runs each case k = 3–5 times (C12). Pass-rate intervals
treat a case's trials as a cluster (cluster-robust standard errors, Miller 2024). The report now
splits the variance into its two parts (`variance_components`, **computed**, M31).

**Why.** A case's k trials are not k independent observations: a hard case tends to fail every
time. Generalizability theory splits the variance of a per-trial outcome into a **between-case**
part (cases differ in difficulty) and a **within-case** part (run-to-run noise on one case). The
standard error of the mean pass rate over N cases and k trials is then

  SE = √( σ²_between / N  +  σ²_within / (N·k) ).

Only the second term shrinks with k. Three numbers in `variance_components` turn this into a
decision:

- **ICC** (intraclass correlation): the between-case share of the variance. Near 1, cases are
  deterministic and extra trials are wasted. Near 0, every case is a coin flip and trials are as
  good as new cases.
- **Effective n** = (N·k) / design effect, where the design effect is 1 + (k − 1)·ICC (Kish). It
  is how many independent trials the run is worth. Ten deterministic cases at k = 3 are worth 10,
  not 30.
- **`se_double_cases` and `se_double_trials`**: the standard error you would get by doubling
  each. Buy whichever shrinks it more for the cost. A G-study followed by a D-study is exactly this
  calculation (Cronbach et al. 1972; Brennan 2001).

In typical agent suites the between-case part dominates, so **more cases beat more trials** once k
is large enough to see flakiness at all (Miller 2024 reaches the same conclusion). k = 3 is the
smallest k that gives a majority verdict and an estimate of within-case noise.

**Caveat.** Cluster-robust intervals are anti-conservative with few clusters: with 5 to 30 of
them, tests built on them over-reject (Cameron, Gelbach & Miller 2008; MacKinnon, Nielsen & Webb
2023). The pass-rate interval therefore uses a t(G − 1) critical value rather than z, and builds
the interval on the logit scale when a symmetric one would cross 0% or 100% (`ci_method`
`cluster_robust_t` or `cluster_robust_t_logit`). Below about 30 cases, still read it as a minimum
width. The report falls back to a Wilson interval over cases (or clusters) when the cluster
estimate collapses.

### 4.2 Flakiness and pass^k

- **Flakiness** (M4) marks a case with 0 < passes < k. A case that passes 95% of the time is
  flagged at k = 3 with probability 14%, and at k = 5 with 23%. A case that isn't flagged is not
  shown to be stable.
- **pass^k** (M3), the share of cases that pass all k trials, is the reliability a user sees on
  repeated use (Yao et al. 2024). It falls fast: 75% per trial is 42% at k = 3 and 10% at k = 8.
  When a case has more trials than k, the unbiased estimator is C(c, k)/C(n, k) for c passes in n
  trials (the pass@k estimator of Chen et al. 2021, applied to all-pass). The report uses the
  plug-in on exactly k trials today (proposal P7).

### 4.3 Correlated cases: clusters

**Decision.** Are the cases as independent as the intervals assume?

**What aot-evals does.** Trials are clustered within a case (§4.1). Everywhere else (McNemar, the
sign-flip test, the bootstrap, Wilson intervals, the zero-failure bound, effective n) cases were
treated as independent. A case may now carry an optional **`cluster`** key: the template it was
generated from, the source trace it came from, or the seed of its fixture. When cases have one,
the report counts clusters, the comparison flips signs per cluster, and both say which regime the
cluster count allows (**computed**, informational). Without keys, both say "cases assumed
independent".

**Why.** Cases flip together when they share a template or a source trace, a check, or a judge,
and when an outage or a model change hits one run. Clustered outcomes inflate variance by the
design effect 1 + (m − 1)ρ, for clusters of size m with within-cluster correlation ρ (Kish 1965).
Clustered standard errors run 1.1–3 times the naive ones on real benchmarks (Miller 2024), and on
small clustered evals only a clustered model reached nominal coverage (Bowyer et al. 2025). The
size of the effect: 24 gains and 6 losses give p ≈ 0.002 if every case is independent. If the 24
gains are 4 templates of 6 copies that flip together, signs flipped per template give p ≈ 0.13,
and counted as 4 gains against 6 losses, McNemar gives p ≈ 0.75.

**What G allows.** A sign-flip test on G clusters can't return a two-sided p below 2/2^G
(`stats.min_attainable_p`), so:

| Clusters (G) | What can be said | How |
|---|---|---|
| ≤ 5 | only "better on these cases": no test can reach 5%, however many cases each cluster holds | report the fixed-suite estimate and say why |
| 6–9 | a test, with care | sign-flip with Webb's six-point weights (Webb 2023), which have more distinct patterns than ±1 |
| ≥ 10 | a test | sign-flip per cluster (Rademacher signs), cross-checked with a cluster jackknife (CV3) standard error and t(G − 1) |

A cluster holding more than 30% of the cases is flagged: one template then decides the result.
`stats.cluster_summary` reports G, the sizes and the regime.

**Bounds on effective n.** The zero-failure bound and Wilson intervals should count effective
cases, n / (1 + (m − 1)ρ) (`stats.effective_n`), or clusters when failures are all-or-nothing per
seed. 100 clean cases from 10 seeds bound the failure rate at about 26%, not 3%. A clean category
can't show how correlated its clusters are, so its zero-failure bound counts clusters.

**Dependence checks** (each set's `dependence` block, informational):

- **Shocks across a run:** Cochran's Q (Cochran 1950), with cases as blocks and repeats as
  treatments, shuffling each case's outcomes across its repeats (`stats.cochran_q`). A small p means
  one repeat failed more than the others: an outage, a rate limit, a provider change mid-run.
- **Template clustering:** a dispersion test of case pass rates across clusters, shuffling cases
  across clusters at fixed sizes, with the cluster-level ICC (`stats.overdispersion_test`; Tarone
  1979 for the parametric version).
- **Drift while the comparison runs:** interleave baseline and candidate trials in the same time
  window, in random order, so an outage hits both sides. An A/A rerun of the baseline shows whether
  shocks exist at all (proposal P15).

**Shared judges are a cluster too.** One judge or rubric used across many cases, or a judge from
the same model family as the candidate, makes errors move together. On one leaderboard, models
agreed on about 60% of the items where both were wrong, more so when they shared a provider or an
architecture, and larger, more accurate models had more correlated errors (Kim et al. 2025). Model
mistakes grow more similar as capability rises, which weakens one model overseeing another (Goel
et al. 2025). See §5.1 for what that does to a suite of checks.

---

## 5. Graders: checks and judges

### 5.1 Grader design: binary, one failure mode each

**Decision.** A 1–10 rubric, or several yes/no checks?

**What aot-evals does.** Every check, code or judge, answers one binary question about one failure
mode (method §5).

**Why.** Three results point the same way:

1. **A binary check is a diagnostic test**, with a sensitivity and a specificity you can measure
   against labels (§5.2). A score on a scale has a different threshold for every rater: in
   generalizability theory the rater facet and its interaction with items carry much of the
   variance, and in item response theory the threshold parameters differ per rater.
2. **Holistic rubric verdicts are more reproducible than pairwise preferences** (Kumar et al. 2026),
   and checklists help most when the items are objective (Cook et al. 2024; "Are checklists really
   useful?", 2025).
3. **One failure mode per check makes errors attributable.** A disagreement can be traced to a
   check (C19 triage), and a check that never fires can be pruned (M11).

**The price of many checks.** A run passes only if every counted check passes. If each of *m*
independent checks passes a correct run with probability TPR_i, a correct run passes the suite with
probability ∏ TPR_i. Five judge checks at TPR 0.9 pass a correct run only 59% of the time. Code
checks are near TPR 1, so this cost falls almost entirely on judges. It is why the suite as a whole
is held to people (C19's **clean pass rate**), and why a judge should guard a failure mode that
code can't decide, not double one that code already checks.

The product ∏ TPR_i assumes the judges err independently. Judges that share a model family, a
rubric or a prompt template don't (§4.3), so their errors overlap. That makes the product a poor
predictor in both directions: correlated false fails land on the same runs, and correlated misses
let the same bad runs through every check. Measure the suite's false-fail rate directly from the
clean pass rate rather than multiplying, and treat judges from one family as one cluster when
reading their agreement (C11).

### 5.2 A judge is a diagnostic test

**What aot-evals does.** C10 measures **TPR** = P(judge passes | person passes) and **TNR** =
P(judge fails | person fails), separately, with Wilson intervals. Raw agreement is never reported
(M8).

**Why.** Accuracy mixes the two rates and the base rate. At a 95% pass rate a judge that always
says "pass" is 95% accurate and catches nothing. Medicine settled this decades ago: report
sensitivity and specificity, which don't depend on prevalence, and derive predictive values for a
given prevalence.

**Correcting a rate for the judge's error** (**computed**, M32). If a judge fires (calls a
failure) on a share *q* of runs, the true failure rate is not *q*. With pass orientation,

  π = (q_pass + TNR − 1) / (TPR + TNR − 1)

(Rogan & Gladen 1978). The report now carries `corrected_trigger_rate` on every judge check, with
a delta-method interval that includes the uncertainty of TPR and TNR as well as of the runs. Two
things follow:

- A judge with TPR + TNR ≤ 1 is no better than chance, and its rate cannot be corrected. The
  report says so instead of printing a number.
- A judge calibrated on few labels gives a wide corrected interval even on thousands of runs. The
  labels, not the runs, limit what the judge can tell you.

**Choosing a probabilistic judge's threshold.** C10 maximizes TPR + TNR (Youden's J) on dev labels
and scores the result out of fold. Youden's J treats a missed failure and a false alarm as equally
costly and ignores the base rate. Decision theory puts the optimal threshold where the ROC slope
equals (cost of a false pass / cost of a false fail) × ((1 − π)/π). `categories.yaml` already
carries a cost matrix, so the threshold could be chosen from it (proposal P4).

**Probabilities.** ECE and Brier (C10) say whether a judge's probabilities mean what they say. ECE
with 10 bins is biased upward on small label sets (Kumar, Liang & Ma 2019). On 60 labels, read it
as a ranking between backends, not as an absolute value.

### 5.3 How many labels, and which ones

**What aot-evals does.** C9 asks for 100–200 labels per judge and C10 needs at least 60, with
both kinds present. `label status` now prints the per-kind count for ±10 points.

**Why the count is per kind.** TPR is measured only on items a person passed, and TNR only on items
a person failed. Each is its own proportion with its own n. At a rate of 0.8, a Wilson interval of
±10 points needs about **60 labels of that kind**, and ±5 points needs about 245. Sixty labels in
total, split 58/2, measure TNR on two items: the interval on TNR runs from 34% to 100%. The current
gate counts total labels and only requires both kinds to be present (proposal P2 adds a per-kind
minimum).

**Which kind to label more of.** When the judge is used to estimate a low failure rate, its
**false alarms on passing runs** drive the error, not its misses. Take a true failure rate of 5%, a
judge that catches 80% of failures and false-alarms on 5% of passes, and 10,000 graded runs. The
95% interval on the corrected failure rate is:

| Labels (failing + passing) | Interval on the corrected failure rate | Width |
|---|---|---:|
| 30 + 30 | 0.0% to 14.7% | 14.7 pts |
| 100 + 100 | 0.0% to 10.5% | 10.5 pts |
| 200 + 200 | 1.1% to 8.9% | 7.8 pts |
| 100 + 300 | 1.7% to 8.3% | 6.5 pts |
| 50 + 350 | 1.7% to 7.9% | 6.2 pts |

The same 400 labels placed mostly on passing runs give an interval 20% narrower than an even split,
and 100 + 100 can't exclude a zero failure rate. A balanced split is right for *calibrating* a judge
(both rates, equally). For *using* a judge to estimate a rate, put the labels where the variance
comes from (proposal P8: let the label queue say which kind to add).

**The ceiling on what a judge saves.** Combining a few labels with many judge verdicts can cut the
labels needed (§6.4), but when the judge is no more accurate than the agent it grades, no method
can cut them by more than half (Dorner, Nastl & Hardt 2024). A judge from the same family as the
agent, grading the agent's own kind of answer, sits near that ceiling. It is one more reason for G4
and for preferring code checks.

### 5.4 Floors: clearing a bar versus showing that you cleared it

**What aot-evals does.** A judge is calibrated when its TPR and TNR are at or above their floors
(0.75 by default). A category is validated when the suite's catch and clean pass rates are at or
above 85% (C19). Both read the **point estimate**. C10 and C19 now also report **floor evidence**
(**computed**, M35, informational).

**Why this needs evidence.** A point estimate on a few items clears a floor by luck about half the
time when the true rate sits at the floor. Two examples:

| Measured | Point | 95% lower bound | Meets the point floor | Within 10 pts of the floor at the lower bound |
|---|---:|---:|:---:|:---:|
| Catch 13 of 15 (floor 85%) | 87% | 62% | yes | no; about 48 needed at this rate |
| TNR 23 of 30 (floor 75%) | 77% | 59% | yes | no; about 61 needed |
| Catch 15 of 15 | 100% | 80% | yes | yes |
| Catch 90 of 100 | 90% | 83% | yes | yes |

Clinical trials and annotator replacement both solve this with a **non-inferiority margin**: the
estimate must reach the bar, and the lower confidence bound must sit no more than a stated margin
below it (Calderon, Reichart & Dror 2025, for "can this model replace an annotator"; the FDA's
non-inferiority guidance for trials). The floor evidence in C10 and C19 reports exactly that with a
10-point margin, plus the number of items of that kind a rate at today's level would need. No gate
reads it in this release (proposal P1).

### 5.5 Reliability is not validity

**What aot-evals does.** C11 reports self-consistency across *m* sessions and agreement across two
model families, always next to TPR/TNR and never in its place (M9).

**Why.** A judge can be perfectly consistent and consistently wrong. In one audit, the most
deterministic judge matched ground truth 51% of the time (Kumar et al. 2026). Agreement across
families rules out one family's quirks, not a shared blind spot: a unanimous panel can still be
wrong, and an item-level risk score catches some of those cases (Ba et al. 2026). Only labels
measure validity. For pairwise grading, position bias flips many verdicts on hard items (Wang et
al. 2023; Shi et al. 2024), so both orders should be judged and a flip recorded as no verdict
(proposal P6).

### 5.6 Choosing between judges (E5)

**What aot-evals does.** The cheapest backend that clears both floors is recommended.

**Why, and the limit.** Two backends judged on the same labels are a paired design. The right test
of "is A better than B" is McNemar's test on the items where exactly one of them is right, and on
60 labels it detects only large differences. So read E5 as "both are
good enough, take the cheaper one", not as "A is better than B". The alternative-annotator test
(Calderon et al. 2025) is the formal version of "can this judge stand in for a person".

### 5.7 When the judge changes

A new judge version invalidates its calibration, and aot-evals recalibrates from cached
judgments (method §4.1). Psychometrics keeps two forms of a test comparable with a small
**anchor set**: common items scored on both forms, with an equating function and its error (Kolen
& Brennan 2014). A labeled anchor set re-judged on every version would show whether old and new
verdicts are on the same scale, without relabeling everything (proposal P12).

---

## 6. People: labels, labelers and whole-run agreement

### 6.1 Agreement between people

**What aot-evals does.** One run in four in a labeler's queue is one someone else labeled, so
agreement between people is measured (method §4.2). Each pair of labelers gets the share agreed,
Cohen's κ, and now **Gwet's AC1** and agreement on fails and on passes separately (**computed**,
M34).

**Why.** κ depends on the base rate. When most runs pass, two people can agree on 90% of runs and
still get κ below zero, because chance agreement is already high: the "high agreement, low kappa"
paradox (Feinstein & Cicchetti 1990). AC1 corrects for chance in a way that doesn't collapse at a
skewed base rate (Gwet 2008), and the two **specific agreements** (Cicchetti & Feinstein 1990) show
where the disagreement is. In the paradox example, people agree on 95% of passes and **on none of
the failures**, and the failures are the part that matters. Report all three. Read κ only when the
pass rate is near 50%.

How many overlaps? The interval on agreement shrinks like a proportion's: about 60 shared runs give
±10 points. With one overlap in four, that is about 240 labels per pair of people. The rate is a
deliberate trade between measuring people and labeling new runs.

### 6.2 Settling disagreements and keeping the standard stable

- **Rulings** (method §4.2) are adjudication: a disagreement goes to a third person, and the ruling
  becomes the verdict. A latent-class model (Dawid & Skene 1979) can estimate each labeler's error
  rates from their disagreements alone. That would be useful once there are many labelers, but its
  independence assumption needs checking first.
- **Onboarding on settled runs** (five runs with a known answer, shown after each label) is rater
  training against anchor items, standard in performance assessment.
- **Criteria drift.** Grading outputs changes the criteria people grade by (Shankar et al. 2024).
  That is why the labeling standard is versioned and an accepted rule triggers a recheck of the
  labels it could flip (method §4.1).

### 6.3 Whole-run agreement (C19)

**What aot-evals does.** People label whole runs blind. Every labeled run is re-graded by the
suite as it is now. **Catch rate** = P(suite fails | person fails) and **clean pass rate** =
P(suite passes | person passes), on dev and holdout (M29).

**Why.** These are the suite's own sensitivity and specificity, with a person as the reference
standard: §5.2 applied to the whole instrument instead of one judge. Everything in §5 carries over:

- **Per kind, not in total.** At the gate's 15-of-each minimum, each rate's 95% interval is about
  ±17–19 points around a rate of 80–87%. The floor evidence (§5.4) shows when that is too thin.
- **Iterate on dev, check holdout once.** Every fix made by reading dev disagreements fits the suite
  to dev. The holdout stays honest only while nobody looks at it to make a choice. Each look spends
  some of its validity, and adaptive data analysis bounds how much (Dwork et al. 2015; Blum & Hardt
  2015). The method's rule, "check holdout once; label a fresh batch before a new claim", follows
  from that.
- **Don't label until it passes.** Labeling a few runs, checking the rate, and labeling more until
  it clears the floor is optional stopping, and it validates suites that shouldn't pass. Fix the
  batch size before looking, or use an always-valid sequential interval (Howard et al. 2021;
  proposal P1 takes this into account).
- **Many categories, many chances.** Per-category validation runs one test per category. With ten
  categories each at its floor, about two suites in five would show at least one category above the
  floor by luck. That is a reason to read per-category validation alongside its n.

### 6.4 What would a person say the pass rate is? (PPI)

**What aot-evals does.** `agreement` now combines the labels with the suite's verdict on every
other run of the same baseline into a **human-anchored pass rate** with an interval (**computed**,
M33, `human_anchored` in `report/agreement.json`).

**Why.** The suite grades every run, but it is wrong sometimes. People grade a few runs and are the
reference. **Prediction-powered inference** combines the two into an estimate of what people would
say about all of them, with a valid interval (Angelopoulos et al. 2023). The estimate is the labels'
mean, plus a correction for how far the suite's verdicts on the labeled runs sit from its verdicts
on the rest. PPI++ (Angelopoulos, Duchi & Zrnic 2023) weighs the suite's contribution by how well it
tracks the labels: a suite that agrees with people narrows the interval well below labels alone,
and one that doesn't is given no weight, so the estimate is never meaningfully worse than the labels
alone. `human_anchored` prints the labels-only and suite-only rates beside it.

**Assumption.** The labeled runs must be a random sample of the runs they stand for. The queue
takes one run per case first, so cases count about equally. Runs chosen because they looked wrong
would bias it, and that is why the label queue, not hand-picking, is the source.

---

## 7. Comparing versions

### 7.1 The paired design

**What aot-evals does.** A candidate runs on the same cases as the baseline, with one declared
variable (G7). Gains and losses are listed separately (M6).

**Why.** Pairing removes between-case variance from the comparison: a hard case is hard on both
sides. At 50 cases, an unpaired comparison at a 50% pass rate detects about 28 points. A paired one
detects about 7 points when the change shifts every case alike, and about 15 points when it affects
cases unevenly (a 15% discordance rate). Listing gains and losses separately follows from the same
logic. A net of zero can hide ten fixes and ten new breaks, and both lists need reading.

**The flips are all the evidence.** When A and B run on the same N cases, only the flips carry
information: b cases went from pass to fail, c from fail to pass. Cases that both pass or both fail
add nothing. The net change is Δ = (c − b)/N, the **flip rate** is d = (b + c)/N, and the standard
error of Δ is √((d − Δ²)/N). The same +5 points at N = 200 can be a clear win or noise:

| What the change did | d | 95% interval on Δ |
|---|---:|---|
| 10 gains, 0 losses | 5% | +5 ± 3.0 points |
| 30 gains, 20 losses | 25% | +5 ± 6.9 points |

Every comparison now prints b, c and d next to Δ (`flips`, **computed**). The cases needed to
detect Δ at 80% power are about **N ≈ 7.85·d/Δ²** (`stats.cases_for_flip_rate`): set by the flip
rate, not the pass rate. Flaky cases inflate d with no real change, so an A/A rerun of the
baseline gives the noise floor of d, and more trials per case shrink only that noise, not real
churn. Store d from past comparisons and size the next one from it (proposal P3); the MDE printed
before a run (M7) assumes the change moves every case alike, so it is optimistic.

### 7.2 Which test, and what it can detect

**What aot-evals does.** Each side's verdict on a case is its majority over k trials. Flips are
tested with **McNemar's exact test**, a bootstrap interval covers the mean per-case delta, and the
verdict needs both to agree and the net to fall outside the baseline's variance band. The MDE (M7)
is printed from the baseline's within-case variance. The comparison now also reports a **paired
sign-flip test** on every change in a case's pass rate, and an **MDE from the observed deltas**
(**computed**, informational).

**Why the additions.** McNemar on majority flips throws away every change that doesn't flip a
majority: a case going from 3/3 to 2/3 counts for nothing. The printed MDE, though, is computed for
a test on the mean per-case delta, which counts that change. So the MDE describes a more sensitive
test than the one that decides the verdict. The sign-flip permutation test is the exact paired test
of that mean (Fisher 1935; Good 2005). Reporting it beside McNemar shows when the two disagree.
`mde_from_deltas` uses the spread of the actual per-case deltas, which includes how unevenly the
change moved cases, so after the fact it is the honest detectable effect. Proposal P3 would make
the verdict read the paired test.

**Exact McNemar is conservative.** The exact conditional test's real size is often near 2% at a
nominal 5%, and a comparison of methods for paired binary data recommends against it in every
situation studied, in favor of the mid-p version (Fagerland, Lydersen & Laake 2013). Where a
McNemar is shown, the comparison now also prints the **mid-p** value (`mcnemar_midp`, **computed**);
P3 retires the exact test from the verdict.

**The interval.** The percentile bootstrap over cases under-covers on small suites near a ceiling,
where the deltas are few, discrete and skewed. Inverting the sign-flip test gives an interval that
assumes only that each case's delta is symmetric about the true mean: every μ at which flipping the
signs of (delta − μ) is not rejected (`paired_mean_test.ci`, **computed**; `stats.sign_flip_interval`).
At N ≥ 100 the two agree; below that, read the sign-flip interval. P3 makes it the verdict's
interval, flipped per cluster when cases carry one (§4.3).

**The variance band.** The band is the min–max of per-repeat pass rates over the baseline's k
repeats. Its width depends on k (more repeats, wider range), and it double-counts noise the paired
test already accounts for. It is useful as a drift reference (C16), where a control chart with
limits from the variance components is the standard tool (Shewhart; Montgomery 2019). As a second
gate on the verdict it makes the stated MDE optimistic (proposal P3).

**k = 1 is refused (G2)** because a single trial gives no within-case variance, so neither the
MDE nor a test can be computed honestly.

### 7.3 Many categories

The comparison tests every category. With ten categories and no real change, about two comparisons
in five would show at least one "significant" category by chance. Per-category p-values now come
with a **Benjamini–Hochberg** adjustment (`p_adjusted_bh`, **computed**), which controls the share of
false discoveries among the categories called (Benjamini & Hochberg 1995). Read the adjusted value
before acting on one category's result.

### 7.4 Cost and latency

Plane-B numbers are counters, so they have no instrument error, but they do have sampling error,
and costs are skewed. Compare cost per successful task (M18) rather than per run, and medians and
p90 rather than means. Intervals on percentiles by bootstrap over cases are listed under P3. The
"trade" verdict (G11) is a decision rule, not a test: a gain that comes with a budget breach is
reported with both numbers so a person can weigh them.

---

## 8. Evolving the suite

### 8.1 What to prune

**What aot-evals does.** Over two or more versions, each case is always-pass, always-fail or
discriminating, and below a 0.3 discriminating fraction C15 proposes prunes (M13). Quality-estimate
cases are never pruned.

**Why, and the error in the classification.** A case's class is itself an estimate. A case that
truly passes 90% of the time looks always-pass across two versions at k = 3 with probability 53%,
and across three versions with probability 39%. So always-pass means "not shown to discriminate",
not "can't discriminate", and the prune proposal re-runs the pairwise tests to show the detectable
effect is unchanged. Item response theory gives the formal version: each case gets a difficulty and
a discrimination (Lalor et al. 2016; Vania et al. 2021). Software testing's suite minimization
keeps a coverage criterion while removing cases (Yoo & Harman 2012). Optimal test assembly combines
the two in an integer program over blueprint cells, discrimination and run cost (van der Linden
2005). One caution from LLM evals: item analysis struggled to reduce variance in practice (Madaan et
al. 2024). Prune for cost, and keep coverage.

### 8.2 Optimization loops and the holdout

An optimizer that queries the suite thousands of times (prompt search, skill evolution) fits the
suite, the way repeated holdout reuse fits a holdout. The theory bounds how many adaptive queries
a holdout can answer before the answers stop generalizing. In practice the damage from moderate
reuse can be small: Recht et al. (2019) found an 11–14% drop on a fresh ImageNet test set, but
gains on the old set carried over, and the drop came mostly from a shift between the two sets. An
optimizer making thousands of queries is not moderate reuse. Two remedies exist: a reusable holdout that answers with
noise or thresholds (Dwork et al. 2015), and a leaderboard that only reports a significant
improvement (the Ladder, Blum & Hardt 2015). Any loop that optimizes against an aot-evals suite
should keep a split it never sees and meter its looks (proposal P11). The judge has the same
exposure: optimizing against a proxy grader eventually lowers the real score (Gao, Schulman &
Hilton 2022; Goodhart variants in Manheim & Garrabrant 2018). Relabel a fresh sample after an
optimization run before trusting its gains.

### 8.3 What a change invalidates

The table in method §4.1 is a statistical statement: each change breaks an assumption behind
specific numbers.

| Change | Assumption broken | Numbers affected |
|---|---|---|
| The agent | same population of runs | the baseline, the variance band, the discriminating set |
| A check | same instrument | catch and clean pass rates (C19) |
| A judge version | same TPR/TNR | that judge's calibration and the corrected rates |
| The labeling standard | same reference standard | the labels a new rule could flip |
| Category mix | same strata weights | the quality estimate (M14) and the allocation (C5) |

### 8.4 Compounded validity

M25 multiplies stage validities (task × simulator × judge, 70% × 70% × 70% ≈ 34%). Read it as a
warning that error at each stage reaches the result, not as a probability: stage errors can cancel
or compound, and "validity" here is not a single measured rate. A measured version is the C19 catch
and clean pass rates on whole runs, which include every stage at once.

---

## 9. Audit: every rule of thumb against its source

Many of the method's thresholds started as practitioner guidance (notably Husain & Shankar's evals
FAQ and judge guide, and Anthropic's agent-eval guidance). This table checks each one against the
formal literature.

| Rule | Where | Origin | Formal basis | Verdict | Status |
|---|---|---|---|---|---|
| Every failure costs the same (implicit in flat targets, symmetric floors, Youden's J, unweighted pass rates) | C3–C5, C10, C13, C19 | unstated | decision theory; the cost check of §1.2 is the test of it | **test it**: keep the flat rules only where costs come out even, and say so | P13; `stats.cost_flags` |
| Traffic-weighted pass rate as the objective; `worth` ordinal | M14, C3 | practice | weighted estimand; blind-spot check against the MDE | **revise**: a numeric weight per category, equal weights stated | P14; `stats.objective_weights`, `stats.blind_spot` |
| Two disjoint case sets | §2.3, G6 | practice | elicitation vs estimation; Horvitz–Thompson | **keep** | gated |
| ≥10 cases per category, 3 for simple | C5 | practice | detection probability weighted by importance per failure mode; improvement sized by flip rate; regression guards sized by a tolerated drop | **revise**: the rule ignores both inputs that should set a count, the category's weight and its measured accuracy. Keep it only as the starting point before a baseline | P14; bound computed (M30); `stats.allocation_target` |
| Quality set n = z²p(1−p)/h², proportional | C5, M14 | survey sampling | proportional allocation (Cochran) | **keep**; add Neyman allocation carrying the weight as well as the variance, and a minimum per stratum | P5 |
| Quality-estimate cases chosen by the author within each quota | C6 | practice | quota vs stratified random sampling | **revise**: a seeded random draw per category, recorded, skips with reasons | P5; `stats.stratified_draw` |
| Normal interval on the weighted estimate | M14 | — | too narrow under a few hundred items (Bowyer et al. 2025) | **revise** | P5 |
| Coverage against an external list | G5 | psychometrics, testing | blueprint; content validity; category-partition | **keep**; add t-way coverage | P10 |
| Reference passes, do-nothing fails | C7 | ABC checklist | mutation analysis | **keep**; extend to a mutation score | P9 |
| k = 3–5 | C12 | practice | G-study: depends on ICC | **keep as default**; choose from `variance_components` | computed (M31) |
| Cluster-robust pass-rate CI with z | M2 | Miller 2024 | small-cluster bias (Cameron, Gelbach & Miller 2008) | **revised**: t(G − 1), logit scale near the bounds | done |
| Cases independent of each other | M2, M30, C13 | unstated | design effect; cluster randomization inference; wild cluster bootstrap | **revise**: an optional cluster key per case; signs flip per cluster; bounds on effective n | P15; cluster tests and dependence checks computed |
| ∏ TPR for a suite of judges | §5.1 | — | assumes independent errors; same-family judges correlate (Kim et al. 2025) | **qualify**: measure the false-fail rate via clean pass rate | — |
| pass^k from k trials | M3 | τ-bench | unbiased C(c,k)/C(n,k) | **refine** | P7 |
| Binary judges, one failure mode each | §5 | practice | diagnostic tests; rater facet variance | **keep** | — |
| TPR/TNR, never raw agreement | M8 | practice; medicine | sensitivity/specificity | **keep** | gated |
| 100–200 labels per judge; ≥60 to calibrate | C9, C10, M10 | practitioner guidance | Wilson width per kind: ±10 pts needs ~60 *of each kind* | **revise**: count per kind | P2; per-kind count printed |
| Even label split | C9 | practice | variance of the corrected rate (Rogan–Gladen) | **revise for estimation**: weight toward the kind that drives the error | P8 |
| Floors on point estimates (0.75; 85%) | C10, C19 | practice | non-inferiority margin; alt-test | **revise** | P1; evidence computed (M35) |
| Threshold by Youden's J | C10 | ROC practice | expected-cost threshold from the cost matrix | **revise** | P4 |
| 5-fold out-of-fold TPR/TNR, 20% hash holdout | C10 | ML practice | honest error estimation | **keep** | — |
| Self-consistency next to, never instead of, TPR/TNR | M9 | practice | reliability ≠ validity | **keep**; swap orders in pairwise | P6 |
| Different family for pairwise (G4) | G4 | self-preference studies | Dorner ceiling | **keep** | gated |
| Cohen's κ between people | §4.2 | practice | prevalence paradox | **supplement** with AC1 and specific agreement | computed (M34) |
| One overlap in four | §4.2 | practice | precision of agreement | **keep**; ~60 shared runs for ±10 pts | — |
| ≥60 whole runs, ≥15 of each | C19 | practice | Wilson width per kind (±17–19 pts at 15) | **revise** with P1 | evidence computed |
| Dev iterated, holdout checked once | E15 | ML practice | adaptive data analysis | **keep**; meter optimizer loops | P11 |
| McNemar on majority flips + band | C13 | practice | paired permutation test matches M7; exact McNemar is conservative (Fagerland et al. 2013) | **revise**: the verdict should read the paired test; mid-p where McNemar is shown | P3; test and mid-p computed |
| Percentile bootstrap interval on the mean delta | C13 | practice | under-covers on small suites near a ceiling | **revise**: the inverted sign-flip interval | P3; interval computed |
| A net delta with gains and losses listed | M6 | practice | flip rate d sets the precision: N ≈ 7.85·d/Δ² | **supplement** with b, c, d and the interval from d | computed |
| MDE from within-case variance | M7 | Miller 2024 | omits case-by-change interaction | **supplement** with the MDE from observed deltas | computed |
| No multiplicity control on categories | C13 | — | Benjamini–Hochberg | **add** | computed |
| Discriminating fraction ≥ 0.3 | C15 | practice | IRT discrimination; misclassification at small k | **keep as a heuristic**; never prune without the MDE check | — |
| Compounded validity as a product | M25 | single-author preprint | not a probability | **keep as a warning**, read C19 instead | — |
| Corrected flag rates | — | practitioner guidance | Rogan–Gladen with its variance; PPI | **adopt** | computed (M32, M33) |

---

## 10. Proposals

These follow from §9 and are not in this release. Ids are stable; the build order is below the
table.

| id | Change | What it fixes | Cost to a team |
|---|---|---|---|
| **P1** | Floors read the non-inferiority rule (point at the floor, 95% lower bound within 10 points of it) for judge TPR/TNR and C19 catch/clean, with a fixed batch per claim | floors cleared by luck on a few items; optional stopping | about 50–60 labels or runs of each kind at typical rates, up from 15–30 |
| **P2** | Judge calibration counts labels per kind (e.g. ≥30 failing and ≥30 passing), not in total | TNR measured on a handful of failing labels | more failing labels, which are the scarce kind |
| **P3** | The comparison verdict reads the paired sign-flip test on per-case deltas; the variance band moves to drift (C16); bootstrap intervals on p50/p90 | the MDE describes a different test than the verdict; double-counted noise | none; some verdicts change from indistinguishable to better or worse |
| **P4** | A probabilistic judge's threshold is chosen from the category's cost matrix and base rate | equal-cost assumption in Youden's J | none beyond a filled cost matrix |
| **P5** | Record inclusion probabilities when sampling traces; Horvitz–Thompson estimates; Neyman allocation with a minimum per stratum; a beta-posterior interval for the weighted estimate | one sampled set serving both purposes; small strata; narrow normal intervals | a field on each sampled case |
| **P6** | Pairwise judges judge both orders; a flip is no verdict | position bias | twice the pairwise calls |
| **P7** | pass^k by the unbiased estimator when a case has more than k trials | plug-in bias | none |
| **P8** | The label queue says which kind of label narrows the interval most, and prefers items the judge is unsure of, with valid inference (Zrnic & Candès 2024; Gligorić et al. 2024) | labels spent where they don't help | none |
| **P9** | A mutation score: agent mutants (drop a tool, stale a document, delete a policy line, change a unit) run against the suite, with the share caught and an interval | adequacy as a number | one run per mutant |
| **P10** | Declare the situations grid as factors and report t-way coverage beside the empty-cell count | coverage with a checkable denominator | writing down the factors |
| **P11** | A holdout budget for optimization loops: a split the optimizer never sees, and a count of looks | adaptive overfitting | a held-out split |
| **P12** | A judge anchor set re-judged on every judge version, with an equating check | judge versions on different scales | judge calls on the anchor set |
| **P13** | The uneven-cost check (§1.2): the owner's answer recorded in Assess and at C3/C4; every baseline failure and C19 disagreement tagged with what it did (wrote, deleted, sent; reversible; noticed); categories flagged by `stats.cost_flags`; the report says whether costs came out even, and where not | flat rules applied where costs differ; costly failures in categories rated low-cost | one question in Assess; a cost tag per triaged failure |
| **P14** | A numeric weight per category, required at C3 (equal weights allowed, stated); the weighted objective as the headline; per-category targets from state (improve or solved), costly failure modes and the blind-spot guardrail (§2.2), re-run after every baseline; a non-inferiority guardrail per blind category | the score silently weighting every failure alike; allocation blind to weight and accuracy; categories the score can't see | changes allocation and the headline, so which suites pass C5 and what they report. Existing suites default to equal weights, recorded as an explicit choice, so nothing moves until an owner sets real ones; the blind-spot check then shows which categories need one |
| **P15** | An optional `cluster` key per case at C6 (template, source trace, seed); the verdict's test and interval flip signs per cluster, with Webb weights at 6 ≤ G < 10 and "better on these cases" only at G ≤ 5; a cluster jackknife cross-check; bounds on effective n; baseline and candidate trials interleaved, and an A/A mode | evidence overstated when cases share a template, a source or a judge | one optional field on a case; without it everything behaves as today and the report says "cases assumed independent". Some verdicts move from better or worse to indistinguishable |

**Build order.** P1 and P2 (floors and label counts), then P3 with P15 in the same release
(the verdict's test, its interval and clusters change together), then P13 and P14 (costs and
weights), and only then P4 and P5, because cost-weighted thresholds and weighted allocation both
need P13's answer and P14's numeric weights; built in the old order they would rest on ordinal
labels. P6 to P12 follow in the order listed.

P1, P2, P3, P14 and P15 change which suites pass their gates or what a comparison concludes, so
they belong in a minor release with migration notes: `floors.yaml` and the judge's
`min_tpr`/`min_tnr` stay the levers, the margin is a new one, and equal weights and missing cluster
keys keep today's behavior until an owner sets them.

---

## 11. References

Classical references are cited from standard sources. arXiv identifiers were checked against the
arXiv API when the surveys behind this document were written (October–November 2026).

**Sampling and estimation.** Neyman, J. (1934), "On the two different aspects of the representative
method", *JRSS*. Horvitz, D. & Thompson, D. (1952), "A generalization of sampling without
replacement from a finite universe", *JASA*. Cochran, W. (1977), *Sampling Techniques*, 3rd ed.
Kish, L. (1965), *Survey Sampling*. Hanley, J. & Lippman-Hand, A. (1983), "If nothing goes wrong, is
everything all right?", *JAMA*. Kossen et al. (2021), Active Testing,
[2103.05331](https://arxiv.org/abs/2103.05331); Kossen et al. (2022), Active Surrogate Estimators,
[2202.06881](https://arxiv.org/abs/2202.06881). Zhao et al. (2016), accelerated evaluation,
[1605.04965](https://arxiv.org/abs/1605.04965). Wu & Hilton (2024), estimating rare outputs,
[2410.13211](https://arxiv.org/abs/2410.13211). Jones et al. (2025), forecasting rare behaviors,
[2502.16797](https://arxiv.org/abs/2502.16797).

**Error bars and comparisons.** Miller, E. (2024), "Adding error bars to evals",
[2411.00640](https://arxiv.org/abs/2411.00640). Bowyer et al. (2025), small-sample intervals for
evals, [2503.01747](https://arxiv.org/abs/2503.01747). Madaan et al. (2024), variance in evals,
[2406.10229](https://arxiv.org/abs/2406.10229). McNemar, Q. (1947), *Psychometrika*.
Fisher, R. (1935), *The Design of Experiments*. Good, P. (2005), *Permutation, Parametric and
Bootstrap Tests of Hypotheses*. Benjamini, Y. & Hochberg, Y. (1995), "Controlling the false
discovery rate", *JRSS B*. Howard et al. (2021), "Time-uniform, nonparametric, nonasymptotic
confidence sequences", *Annals of Statistics*. Montgomery, D. (2019), *Introduction to Statistical
Quality Control*. Yao et al. (2024), τ-bench and pass^k, [2406.12045](https://arxiv.org/abs/2406.12045).
Chen et al. (2021), unbiased pass@k, [2107.03374](https://arxiv.org/abs/2107.03374).

**Paired and clustered inference.** Fagerland, M., Lydersen, S. & Laake, P. (2013), "The McNemar
test for binary matched-pairs data: mid-p and asymptotic are better than exact conditional", *BMC
Medical Research Methodology*, https://pmc.ncbi.nlm.nih.gov/articles/PMC3716987/. Cameron, A.,
Gelbach, J. & Miller, D. (2008), "Bootstrap-based improvements for inference with clustered errors",
*Rev. Economics and Statistics*, https://www.nber.org/papers/t0344. MacKinnon, J., Nielsen, M. &
Webb, M. (2023), "Cluster-robust inference: a guide to empirical practice", *J. Econometrics*,
[2205.03285](https://arxiv.org/abs/2205.03285). Webb, M. (2023), "Reworking wild bootstrap-based
inference for clustered errors", *Canadian J. Economics*. Cochran, W. (1950), "The comparison of
percentages in matched samples", *Biometrika*. Tarone, R. (1979), "Testing the goodness of fit of
the binomial distribution", *Biometrika*. Kim, E. et al. (2025), "Correlated errors in large language
models", [2506.07962](https://arxiv.org/abs/2506.07962). Goel, S. et al. (2025), "Great models think
alike and this undermines AI oversight", [2502.04313](https://arxiv.org/abs/2502.04313).

**Diagnostic tests and judges.** Rogan, W. & Gladen, B. (1978), "Estimating prevalence from the
results of a screening test", *Am. J. Epidemiology*. Begg, C. & Greenes, R. (1983), "Assessment of
diagnostic tests when disease verification is subject to selection bias", *Biometrics*. Dawid, A. &
Skene, A. (1979), "Maximum likelihood estimation of observer error-rates", *JRSS C*. Angelopoulos et
al. (2023), prediction-powered inference, [2301.09633](https://arxiv.org/abs/2301.09633);
Angelopoulos, Duchi & Zrnic (2023), PPI++, [2311.01453](https://arxiv.org/abs/2311.01453); Boyeau et
al. (2024), AutoEval Done Right, [2403.07008](https://arxiv.org/abs/2403.07008); Fisch et al. (2024),
stratified PPI, [2406.04291](https://arxiv.org/abs/2406.04291). Zrnic & Candès (2024), active
statistical inference, [2403.03208](https://arxiv.org/abs/2403.03208). Gligorić et al. (2024),
confidence-driven inference, [2408.15204](https://arxiv.org/abs/2408.15204). Dorner, Nastl & Hardt
(2024), limits of judges as evaluators, [2410.13341](https://arxiv.org/abs/2410.13341). Calderon,
Reichart & Dror (2025), the alternative annotator test,
[2501.10970](https://arxiv.org/abs/2501.10970). Jung, Brahman & Choi (2024), Trust or Escalate,
[2407.18370](https://arxiv.org/abs/2407.18370). Zheng et al. (2023), MT-Bench and judge biases,
[2306.05685](https://arxiv.org/abs/2306.05685). Wang et al. (2023), position bias,
[2305.17926](https://arxiv.org/abs/2305.17926); Shi et al. (2024),
[2406.07791](https://arxiv.org/abs/2406.07791). Kumar, Rathore & Moitra (2026), All Verdicts are Not
Equal, [2610.12083](https://arxiv.org/abs/2610.12083). Ba, Mancenido & Pan (2026), SCUR,
[2610.14029](https://arxiv.org/abs/2610.14029). Kumar, Liang & Ma (2019), "Verified uncertainty
calibration", NeurIPS. Cook et al. (2024), TICK, [2410.03608](https://arxiv.org/abs/2410.03608).
"Are checklists really useful?" (2025), [2508.15218](https://arxiv.org/abs/2508.15218).

**Agreement between people.** Cohen, J. (1960), *Educ. Psych. Measurement*. Feinstein, A. &
Cicchetti, D. (1990), "High agreement but low kappa: I", *J. Clin. Epidemiology*; Cicchetti, D. &
Feinstein, A. (1990), "… II. Resolving the paradoxes". Gwet, K. (2008), "Computing inter-rater
reliability and its variance in the presence of high agreement", *Br. J. Math. Stat. Psych.*
Krippendorff, K. (2004), *Content Analysis*. Shankar et al. (2024), "Who validates the validators?",
[2404.12272](https://arxiv.org/abs/2404.12272).

**Psychometrics.** Cronbach, L. et al. (1972), *The Dependability of Behavioral Measurements*.
Brennan, R. (2001), *Generalizability Theory*. Lawshe, C. (1975), "A quantitative approach to
content validity", *Personnel Psychology*. Messick, S. (1995), "Validity of psychological
assessment", *Am. Psychologist*. Kolen, M. & Brennan, R. (2014), *Test Equating, Scaling, and
Linking*. van der Linden, W. (2005), *Linear Models for Optimal Test Design*. Lalor et al. (2016),
IRT for NLP, [1605.08889](https://arxiv.org/abs/1605.08889). Vania et al. (2021),
[2106.00840](https://arxiv.org/abs/2106.00840). Polo et al. (2024), tinyBenchmarks,
[2402.14992](https://arxiv.org/abs/2402.14992).

**Software testing and case construction.** Ostrand, T. & Balcer, M. (1988), "The category-partition
method", *CACM*. Kuhn, D., Wallace, D. & Gallo, A. (2004), "Software fault interactions and
implications for software testing", *IEEE TSE*. DeMillo, R., Lipton, R. & Sayward, F. (1978), "Hints
on test data selection", *Computer*. Just et al. (2014), "Are mutants a valid substitute for real
faults?", FSE. Yoo, S. & Harman, M. (2012), "Regression testing minimization, selection and
prioritization: a survey", *STVR*. Chen, T. et al. (1998), metamorphic testing, tech. report; Hyun et
al. (2023), METAL, [2312.06056](https://arxiv.org/abs/2312.06056). Claessen, K. & Hughes, J. (2000),
QuickCheck, ICFP. Ribeiro et al. (2020), CheckList, [2005.04118](https://arxiv.org/abs/2005.04118).
Gardner et al. (2020), contrast sets, [2004.02709](https://arxiv.org/abs/2004.02709). Poliak et al.
(2018), [1805.01042](https://arxiv.org/abs/1805.01042); Gururangan et al. (2018),
[1803.02324](https://arxiv.org/abs/1803.02324). Mirzadeh et al. (2024), GSM-Symbolic,
[2410.05229](https://arxiv.org/abs/2410.05229). Perez et al. (2022), model-written evaluations,
[2212.09251](https://arxiv.org/abs/2212.09251). Northcutt et al. (2021), label errors in test sets,
[2103.14749](https://arxiv.org/abs/2103.14749). Zhu et al. (2025), Agentic Benchmark Checklist,
[2507.02825](https://arxiv.org/abs/2507.02825). Aleithan et al. (2024), SWE-Bench+,
[2410.06992](https://arxiv.org/abs/2410.06992). Oren et al. (2023), contamination test,
[2310.17623](https://arxiv.org/abs/2310.17623); Yang et al. (2023),
[2311.04850](https://arxiv.org/abs/2311.04850).

**Reuse, optimization and validity.** Dwork et al. (2015), the reusable holdout,
[1506.02629](https://arxiv.org/abs/1506.02629). Blum, A. & Hardt, M. (2015), the Ladder,
[1502.04585](https://arxiv.org/abs/1502.04585). Recht et al. (2019), ImageNet test-set reuse,
[1902.10811](https://arxiv.org/abs/1902.10811). Gao, Schulman & Hilton (2022), reward
over-optimization, [2210.10760](https://arxiv.org/abs/2210.10760). Manheim, D. & Garrabrant, S.
(2018), "Categorizing variants of Goodhart's law", [1803.04585](https://arxiv.org/abs/1803.04585).
Zhang, G. & Hardt, M. (2024), benchmark diversity and stability,
[2405.01719](https://arxiv.org/abs/2405.01719).

**Practitioner guidance audited in §9.** Husain, H. & Shankar, S., evals FAQ (2025, updated 2026),
https://hamel.dev/blog/posts/evals-faq/; Husain, H. (2024), "Creating a LLM-as-a-Judge That Drives
Business Results", https://hamel.dev/blog/posts/llm-judge/. Anthropic (2026), "Demystifying evals for
AI agents", https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents.

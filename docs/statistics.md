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
gate reads it), **proposed** (described here, not implemented; see §10).

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

### 2.2 Sizing the error-finding set: what can it find?

**Decision.** How many cases per category?

**What aot-evals does.** `allocate` targets 10 per category, 3 for simple ones, and now prints
the rarest failure each target will surface (**computed**, M30).

**Why.** An error-finding set is sized by **detection probability**, not by an interval. If a
failure affects a fraction *p* of a category's runs and cases are drawn from that category, the
chance that *n* cases show it at least once is 1 − (1 − *p*)ⁿ. Fix that chance at 95% and solve:

| Cases in the category | Surfaces, with 95% probability, a failure that affects at least |
|---:|---:|
| 3 | 63% of runs |
| 10 | 26% |
| 20 | 14% |
| 30 | 9.5% |
| 59 | 5% |
| 100 | 3% |
| 299 | 1% |

The same number, read backwards, is the **zero-failure bound**: if all *n* cases pass, the failure
rate could still be as high as 1 − 0.05^(1/*n*), about 3/*n* (the "rule of three", Hanley &
Lippman-Hand 1983). The report prints it on every category with no failure
(`zero_failure_bound`).

So "10 per category" finds frequent failures quickly and says nothing about rare ones. A clean run
on 10 cases cannot rule out a failure that hits one run in five. That is fine for a first pass, and
it is the reason the error-finding set should grow in the categories where a rare failure is
costly, not uniformly.

**When to deviate.**

- **A rare, costly failure** (a wrong refund, a leaked record): don't wait for random cases to find
  it. Write cases that target it directly: contrast sets, metamorphic relations, the situations
  grid (§3). Targeted cases are elicitation, so they can't estimate its rate. To estimate the rate,
  sample with recorded weights (importance sampling, Zhao et al. 2016; Wu & Hilton 2024).
- **A simple category** (one deterministic path): 3 cases surface only failures in more than 63% of
  runs. That is the intent. If a simple category ever fails, it isn't simple.
- `stats.cases_to_surface(rate)` gives the count for any rate: 59 for 5%, 299 for 1%, 2,995 for
  0.1%.

### 2.3 Sizing the quality-estimate set: how precise must the number be?

**Decision.** How many cases, and how are they split across categories?

**What aot-evals does.** n = z²·p(1 − p)/h², with p = 0.5 (the worst case) and h the half-width
the owner needs (default ±5 points, 385 cases). The cases are split in proportion to each
category's share of traffic, and the estimate is the share-weighted pass rate (M14).

**Why.** This is stratified sampling with **proportional allocation** (Cochran, ch. 5). It is
unbiased and easy to explain. Two refinements matter at small sizes:

- **Neyman allocation** puts more cases where the share times the standard deviation is largest. A
  category at 99% pass needs far fewer cases than one at 70% to reach the same precision. With
  unequal variances it gives the narrowest interval for a fixed budget (proposal P5).
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

**Caveat.** Cluster-robust intervals are anti-conservative with few clusters (Cameron & Miller
2015). Below about 30 cases, read the interval as a minimum width. The report falls back to a
Wilson interval over cases when the cluster estimate collapses.

### 4.2 Flakiness and pass^k

- **Flakiness** (M4) marks a case with 0 < passes < k. A case that passes 95% of the time is
  flagged at k = 3 with probability 14%, and at k = 5 with 23%. A case that isn't flagged is not
  shown to be stable.
- **pass^k** (M3), the share of cases that pass all k trials, is the reliability a user sees on
  repeated use (Yao et al. 2024). It falls fast: 75% per trial is 42% at k = 3 and 10% at k = 8.
  When a case has more trials than k, the unbiased estimator is C(c, k)/C(n, k) for c passes in n
  trials (the pass@k estimator of Chen et al. 2021, applied to all-pass). The report uses the
  plug-in on exactly k trials today (proposal P7).

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
| Two disjoint case sets | §2.3, G6 | practice | elicitation vs estimation; Horvitz–Thompson | **keep** | gated |
| ≥10 cases per category, 3 for simple | C5 | practice | detection probability: 10 surfaces ≥26% failures | **keep, with the bound printed**; grow where rare failures are costly | computed (M30) |
| Quality set n = z²p(1−p)/h², proportional | C5, M14 | survey sampling | proportional allocation (Cochran) | **keep**; add Neyman allocation, minimum per stratum | P5 |
| Normal interval on the weighted estimate | M14 | — | too narrow under a few hundred items (Bowyer et al. 2025) | **revise** | P5 |
| Coverage against an external list | G5 | psychometrics, testing | blueprint; content validity; category-partition | **keep**; add t-way coverage | P10 |
| Reference passes, do-nothing fails | C7 | ABC checklist | mutation analysis | **keep**; extend to a mutation score | P9 |
| k = 3–5 | C12 | practice | G-study: depends on ICC | **keep as default**; choose from `variance_components` | computed (M31) |
| Cluster-robust pass-rate CI | M2 | Miller 2024 | clustered SEs; small-cluster bias | **keep**; read as a minimum below ~30 cases | — |
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
| McNemar on majority flips + band | C13 | practice | paired permutation test matches M7 | **revise**: the verdict should read the paired test | P3; test computed |
| MDE from within-case variance | M7 | Miller 2024 | omits case-by-change interaction | **supplement** with the MDE from observed deltas | computed |
| No multiplicity control on categories | C13 | — | Benjamini–Hochberg | **add** | computed |
| Discriminating fraction ≥ 0.3 | C15 | practice | IRT discrimination; misclassification at small k | **keep as a heuristic**; never prune without the MDE check | — |
| Compounded validity as a product | M25 | single-author preprint | not a probability | **keep as a warning**, read C19 instead | — |
| Corrected flag rates | — | practitioner guidance | Rogan–Gladen with its variance; PPI | **adopt** | computed (M32, M33) |

---

## 10. Proposals

These follow from §9 and are not in this release. They are ordered by how much they change what
the method can claim, against what they cost a team.

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

P1 and P2 change which suites pass their gates, so they belong in a minor release with migration
notes: `floors.yaml` and the judge's `min_tpr`/`min_tnr` stay the levers, and the margin would be a
new one.

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
[2406.10229](https://arxiv.org/abs/2406.10229). Cameron, A. & Miller, D. (2015), "A practitioner's
guide to cluster-robust inference", *J. Human Resources*. McNemar, Q. (1947), *Psychometrika*.
Fisher, R. (1935), *The Design of Experiments*. Good, P. (2005), *Permutation, Parametric and
Bootstrap Tests of Hypotheses*. Benjamini, Y. & Hochberg, Y. (1995), "Controlling the false
discovery rate", *JRSS B*. Howard et al. (2021), "Time-uniform, nonparametric, nonasymptotic
confidence sequences", *Annals of Statistics*. Montgomery, D. (2019), *Introduction to Statistical
Quality Control*. Yao et al. (2024), τ-bench and pass^k, [2406.12045](https://arxiv.org/abs/2406.12045).
Chen et al. (2021), unbiased pass@k, [2107.03374](https://arxiv.org/abs/2107.03374).

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

# The statistics behind aot-evals

*Target design for aot-evals 2.0. Draft.*

An eval is an estimator with four parts: an estimand, a sampling design, a measurement model and a
decision rule ([estimators.md](estimators.md)). This document derives the rules for each part: how
many cases, drawn how, how many trials, how many labels and of which kind, when a grader can be
trusted, when a difference is real, and what a change to the suite invalidates. The
[problems](problems.md) show the same ground through worked examples, without formulas.

Each section follows the same shape: the decision you face, the statistics behind it with its
source, and when to deviate. Rules are cited by their number in [estimators.md §10](estimators.md#10-the-rules-in-one-table).
Functions in the `aot_evals.stats` library are named as `stats.<function>`.

**Two words for a grader's error,** used throughout for a single judge and for the eval as a whole.
Against a person's verdict as the reference:

- **Catch rate**: of the runs a person fails, the share the grader fails. (Sensitivity to failure;
  TNR in pass orientation.)
- **Clean pass rate**: of the runs a person passes, the share the grader passes. (Specificity;
  TPR in pass orientation.)

Their sum minus one, **J = catch + clean − 1**, is Youden's J. J = 1 is a perfect grader and J = 0
is a coin.

## Contents

1. [The estimand](#1-the-estimand)
2. [The sampling design](#2-the-sampling-design)
3. [The measurement model](#3-the-measurement-model)
4. [The decision rule](#4-the-decision-rule)
5. [References](#5-references)

An eval's number has three sources of error, and each part of the estimator handles one or more:

| Source | Question | Shrinks with | Part |
|---|---|---|---|
| **Sampling** | Would different cases have given a different number? | more cases, chosen well | Sampling design |
| **Noise** | Would running the same cases again? | more trials per case | Measurement model |
| **Instrument** | Would a person have graded it the same way? | better checks, calibrated judges, more labels | Measurement model |

The estimand says what the number is *of*, and the decision rule says how much of each error a
decision can tolerate. Most eval tooling reports only the first source, as one pass rate with no
interval. Each needs a different fix: more cases do nothing for a miscalibrated judge, and more
trials do nothing for a suite with too few cases.

The rule that **unknown values are `null`, never `0`** is a statistical rule as well: a zero is a
measurement, and a measurement that wasn't made must not look like one.

---

## 1. The estimand

### 1.1 Weights: what a failure costs

**Decision.** What single quantity is the eval trying to estimate and improve?

**Statistics.** The estimand is θ = Σ_s w_s · μ_s, the weighted pass rate over segments. Weighting by
traffic alone (w_s = share_s) counts every failure as equally bad: a wrong delivery date and a
refund sent to the wrong customer each cost one failed run. For some agents that is close enough,
and for others it is badly wrong. The weights should carry what a failure in each segment costs,
as a ratio to the others:

  w_s = share_s × cost_s / Σ_t share_t × cost_t

With these weights, 1 − θ is proportional to the expected cost of failures per request. Equal
costs are allowed, and then the weights are the traffic shares, but they must be stated: an
unstated weight is unknown, not 1 (`stats.objective_weights`). The worked example in
[estimators.md §3](estimators.md#3-part-1-the-estimand) shows a refund bug moving θ by 0.2 points
under traffic weights and by 2.3 under cost weights.

**Are costs really even? Ask, then check.** What the owner expects and what the agent does can
differ, and the expensive failures are often ones nobody predicted.

- *Ask the owner:* are some of this agent's mistakes much worse than others? Can it change or
  delete records, send messages, or move money? Would anyone notice a mistake before it did damage?
  Record the answer, whether costs came out even or uneven, and why.
- *Look at the actual failures.* Tag each failure from a baseline, and each disagreement between the
  eval and a person, with what it did: did it write, delete or send; can it be undone; would a person
  have noticed before acting on it? `stats.failure_severity` turns those answers into low, medium or
  high: an irreversible write is high, a reversible side effect or an unnoticeable wrong answer is
  medium, a wrong answer a person would catch is low. `stats.cost_flags` flags a segment whose
  failures span severities with a high one among them, or whose worst failure is worse than its
  stated cost. The canonical case is **an agent asked for a report that changes CRM state**: a
  read-only request that writes costs far more than a wrong number, in a segment the owner would
  rate cheap. A flag goes back to the weights, and to the checks (a side-effect check on read-only
  requests).

If costs come out roughly even, traffic weights are fine, and the eval should say so. If they are
uneven, the weights, the thresholds of judges (§3.2) and the gates (§4) should carry them.

**Weight sensitivity.** Costs are rough. Before acting on a verdict, recompute it under other
plausible weights (half and double each stated cost). A verdict that flips is a verdict about the
weights, not about the agent.

### 1.2 The blind spot: a segment the headline can't see

**Decision.** Does a segment that matters need a gate of its own?

**Statistics.** A drop of δ in a segment with weight w moves θ by w·δ. If that is below the
comparison's detectable effect (§4.1), θ cannot see the drop. A segment with 2% of traffic that
drops 10 points moves a traffic-weighted score by 0.2 points, and a 100-case paired comparison
detects about 11. Weighting helps less than it seems: even at 60 times the weight of the rest, that
segment's 10-point drop moves the score only 5.5 points (`stats.blind_spot`).

So a segment that matters and is blind gets its own decision rule: a non-inferiority test on that
segment alone, sized in §4.1. That makes it a second gate, so the gates need a multiplicity
correction (§4.6), and it only makes sense when someone would act on that segment by itself (rule 20).
If no one would, the segment's row is a diagnostic.

### 1.3 Units: where an eval goes

**Decision.** Does a component get an eval of its own?

**Statistics.** One estimand per eval (rule 1) rests on validity theory: a score's meaning is the
interpretation it supports for a use (Cronbach & Meehl 1955; Messick 1989; AERA, APA & NCME 2014),
and each interpretation of a number needs its own validity argument, so an eval is built to support
one. A component eval is a sub-score of the
system, and psychometrics has a test for when a sub-score is worth reporting: it must predict its
own true score better than the total does (Haberman 2008). For an agent, that is the case when the
component can change without the rest, so its own number moves while the system's barely does.

Three statistical facts follow for a component behind a context boundary:

- **Its population is induced by what's upstream.** The inputs the refund subagent sees are the
  handoffs the orchestrator produces. They are the sampling frame (§2.1), drawn from end-to-end
  traces with their inclusion probabilities, and a change to routing changes the frame (§1.4).
- **A better component isn't a better system.** The component's estimand and the system's are
  different quantities. A change that improves one can hurt the other through the interface between
  them, so a component change also needs a non-inferiority test on the end-to-end eval (§4.5).
- **Two evals gating one change are two tests** (§4.6).

### 1.4 When the population moves

**Decision.** The agent hasn't changed. Has its score?

**Statistics.** The shares are part of θ, so a new mix of traffic is a new θ (rule 26). Post-
stratification recomputes it from the same per-segment rates under the new shares, without running
anything: if returns pass 80% and everything else 95%, θ is 0.2 × 80 + 0.8 × 95 = 92% when returns
are 20% of traffic, and 0.5 × 80 + 0.5 × 95 = 87.5% when a holiday makes them half. Re-measure the
shares on a schedule, and whenever routing changes, since that moves the frame of every eval
downstream (§1.3).

Drift in the agent's own behavior (a provider updating the model behind a name, a tool's data
changing) shows up as a rerun of the same build falling outside its own noise. The standard tool
is a **control chart** (Shewhart 1931; Montgomery 2019), with limits from the variance components of
§3.7 rather than the min–max of a few repeats, whose width depends on how many repeats there were.

---

## 2. The sampling design

### 2.1 Two pools, because there are two questions

**Decision.** Should the cases that find bugs also tell you how good the agent is?

**Statistics.** These are two different estimands. Bug-finding is *elicitation*: the goal is to see
each failure at least once, so cases are chosen where failures are likely. Quality is *estimation*:
the goal is an unbiased rate for the population, so the probability of choosing each case must be
known. An enriched set over-represents failures by design, so its pass rate is biased low by an
amount nobody knows. Software testing reached the same split: testing to find faults and testing to
measure delivered reliability are different activities with different case selection (Frankl,
Hamlet, Littlewood & Strigini 1998), and operational testing draws from the usage profile (Musa
1993).

One set can serve both purposes only when each case's **inclusion probability** π is recorded at
sampling time, so each case can be reweighted by 1/π (Horvitz & Thompson 1952; for models, active testing weights each
labeled case by its selection probability, Kossen et al. 2021). That is rule 5: a bug-finding case enters a rate only with a recorded
π. The quality set's estimate per segment is the Hájek mean, Horvitz–Thompson normalized by its own
weights, μ̂_s = Σ (ŷ_i / π_i) / Σ (1 / π_i) (Hájek 1971). It is approximately unbiased, and more
stable than dividing by the size of the frame.

### 2.2 Drawing the quality set

**Decision.** Which traces fill the quality set?

**Statistics.** Proportional counts per segment are not enough. If the author chooses which traces
fill each quota, the set is a quota sample, and a quota sample carries the author's selection bias
with no way to measure it. Each segment's cases should be a **seeded random draw** from that
segment's traces, with the seed and each case's π recorded. Every skip after the draw (a trace with
PII that can't be scrubbed, a duplicate) is recorded with its reason and replaced from a second
seeded draw, never by hand (`stats.stratified_draw`; rule 6).

### 2.3 Allocation: how many cases per segment

**Decision.** How is a budget of cases split across segments?

**Statistics.** The budget goes by **optimum allocation**: Neyman's allocation (Neyman 1934),
extended for unequal costs (Cochran 1977, §5.5):

  n_s ∝ w_s · σ_s / √c_s

where w_s is the segment's weight, σ_s the spread of its outcomes (√(μ_s(1 − μ_s)) for a pass rate)
and c_s the cost of running one of its cases. This gives the narrowest interval on θ̂ for a fixed
budget (rule 8; `stats.neyman_allocation`). A segment at 99% needs far fewer cases than one at 70% to
reach the same precision, and a segment whose cases are expensive (long runs, many tool calls) gets
fewer than its weight alone would give it.

Every gated segment also needs the minimum its decision rule sets (§4.1). Where the formula gives a
segment less than its minimum, fix that segment at its minimum and spread the rest of the budget by
the same formula over the other segments. That is the narrowest interval the budget allows, given
the minimums.

Before any baseline, σ_s is unknown. Start with proportional allocation (n_s ∝ w_s), which assumes
equal spreads, and switch to Neyman once a baseline measures them.

**How many in total.** For an interval of half-width h on a single proportion at the worst case
p = 0.5, n = z²·p(1 − p)/h²: ±5 points takes 385 cases. With segments and weights, the variance of
θ̂ is Σ w_s² σ_s² / n_s, and the budget solves that for the decision rule's precision.

**Small segments.** Proportional allocation gives a segment with 1% of traffic about 4 of 385
cases, too few to say anything about it by itself. Oversample it, record its π, and weight it back
down: θ̂ stays (approximately) unbiased and the segment's own row becomes readable.

**Intervals.** Normal (CLT) intervals are too narrow below a few hundred items (Bowyer et al.
2025), and a weighted estimate is no exception. Single-segment rates use Wilson intervals; the weighted estimate should use a
beta-posterior interval, or a normal interval with an Agresti–Caffo-style adjustment so that a
segment at 0% or 100% never contributes zero variance.

### 2.4 Clusters: count the evidence, not the cases

**Decision.** Are the cases as independent as the intervals assume?

**Statistics.** Cases flip together when they share a template, a source trace, a fixture's seed, a
check or a judge, and when an outage or a model change hits one run. Clustered outcomes inflate
variance by the **design effect** 1 + (m − 1)ρ, for clusters of size m with within-cluster
correlation ρ (Kish 1965). The effective number of cases is n / (1 + (m − 1)ρ) (`stats.effective_n`;
rule 9). Clustered standard errors run 1.1–3 times the naive ones on real benchmarks (Miller 2024),
and in simulations of small clustered evals only a clustered Bayesian model reached nominal
coverage (Bowyer et al. 2025).

The size of the effect: 24 gains and 6 losses give a two-sided p of about 0.0014 (about 1 in 700) if
every case is independent. If the 24 gains are 4 templates of 6 copies that flip together, signs
flipped per template give p ≈ 0.13, and counted as 4 gains against 6 losses, McNemar gives p ≈ 0.75.

So every case carries a **cluster key** (its template, source trace or seed), the quality and
bug-finding sets are disjoint by that key, not just by source trace (rule 10), and tests and bounds
count clusters.

**What the number of clusters allows.** A sign-flip test on G clusters can't return a two-sided p
below 2/2^G (`stats.min_attainable_p`), so:

| Clusters (G) | What can be said | How |
|---|---|---|
| ≤ 5 | a ±1 sign flip can't reach 5% (its smallest p is 2/2^G ≥ 1/16), however many cases each cluster holds | say "better on these cases"; six-point weights can reach 5%, but only approximately (about 7% false alarms at G = 5, Webb 2023) |
| 6–9 | a test, with care | sign-flip with Webb's six-point weights (Webb 2023), which have more distinct patterns than ±1 |
| ≥ 10 | a test | sign-flip per cluster (Rademacher signs), cross-checked with a cluster jackknife (CV3) standard error and t(G − 1) |

A cluster that holds a large share of the cases decides the result by itself. Flag it by its design
effect, not by a fixed share (`stats.cluster_summary` reports G, the sizes and the regime).

**Bounds count clusters too.** 100 clean cases from 10 seeds bound the failure rate at about 26%,
not 3% (§4.1). A clean segment can't show how correlated its clusters are, so its zero-failure bound
counts clusters.

**Dependence checks.**

- **Shocks across a run:** Cochran's Q (Cochran 1950), with cases as blocks and repeats as
  treatments, shuffling each case's outcomes across its repeats (`stats.cochran_q`). A small p means
  one repeat failed more than the others: an outage, a rate limit, a provider change mid-run.
- **Template clustering:** a dispersion test of case pass rates across clusters, shuffling cases
  across clusters at fixed sizes, with the cluster-level ICC (`stats.overdispersion_test`; Tarone
  1979 for the parametric version).
- **Drift while a comparison runs:** interleave baseline and candidate trials in the same time
  window, in random order, so an outage hits both sides. An A/A rerun of the baseline shows whether
  shocks exist at all.

**Shared judges are a cluster too.** One judge or rubric used across many cases, or a judge from the
same model family as the agent, makes errors move together. On one leaderboard, models agreed on
about 60% of the items where both were wrong, more so when they shared a provider or an
architecture, and larger, more accurate models had more correlated errors (Kim et al. 2025). Model
mistakes grow more similar as capability rises, which weakens one model overseeing another (Goel et
al. 2025). See §3.6 for what that does to an eval's checks.

### 2.5 The bug-finding set: coverage, adequacy and construction

The bug-finding set has no π and enters no rate, so its design goal is different: see every failure
that matters at least once. Three questions decide whether it does.

**Coverage: is anything missing?** A coverage claim needs a denominator, and one derived from the
cases always reads 100%. Coverage is counted against a list written outside the eval: the product
spec, the agent's tools, the help center's topics, crossed with **situations** (not found,
ambiguous, not allowed, a tool error). Psychometrics calls the external list a **test blueprint**,
and content validity rests on judgments of the domain made outside the test, by expert panels or
job analysis (Lawshe 1975; Messick 1995). Software testing calls the grid **category-partition** (Ostrand & Balcer 1988): the case
space written as factors and levels, with impossible combinations struck out.

The grid's cells grow multiplicatively. **Combinatorial (t-way) testing** makes it tractable: most reported faults involve one or two interacting factors, and every fault studied involved six or
fewer (Kuhn, Wallace & Gallo 2004). Take a case space of six factors with 8, 5, 4, 4, 3 and 3 levels. The full
grid is 5,760 cases. A **covering array** in which every pair of levels appears at least once needs
40 (the floor is 8 × 5, and it can be reached), and every triple about 160–180 (the floor is
8 × 5 × 4 = 160). So "every pair of factors covered" costs about what "10 cases for each of four
segments" costs, and unlike that rule it can be checked by someone else.

**Adequacy: would the set catch a fault?** Plant known faults and count the share the suite
catches: **mutation analysis** (DeMillo, Lipton & Sayward 1978), whose mutation score correlates with detecting real faults, independently of code coverage (Just
et al. 2014). The minimum screens are mutants: a do-nothing agent
must fail, a do-nothing agent that claims success must fail, the reference answer must pass, other
correct wordings must pass. Agent mutants go further: drop a tool, stale a document, delete a policy
line, change a unit. Agent benchmarks that skipped this step were wrong by large margins: on manual review, SWE-Bench+ judged 31% of one agent's passing patches incorrect or incomplete,
passed only by weak tests (Aleithan et al. 2024), and a review of agentic benchmarks found
performance under- or overestimated by up to 100% in relative terms (Zhu et al. 2025).

**Construction: does a case test what it says?**

| Practice | Formal basis | What it guards against |
|---|---|---|
| Cases from real traffic, with provenance | content validity; sampling frame | testing a distribution nobody sends |
| A person reads each expected answer; the reference and do-nothing screens | label-error audits: an average of at least 3.3% of labels are wrong across ten common test sets, and model rankings can flip when the share of bad labels rises (Northcutt et al. 2021) | a wrong expected answer hiding a real failure |
| Other correct wordings must pass | construct validity: the check measures correctness, not phrasing | false fails on paraphrases |
| A check never reads the agent's own claim of success | an independent reference standard: a verdict that includes the agent's own report of success is partly the thing being tested (incorporation bias) | the "confident closing" failure, where state and claim disagree |
| A contamination screen for cases built from public sources | contamination tests (Oren et al. 2024, which needs the model's log-likelihoods and tests a whole benchmark; Yang et al. 2023: rephrased items pass n-gram checks) | memorized answers |

Four generators are worth knowing, all for the bug-finding set:

- **Partial-input baselines** (Poliak et al. 2018; Gururangan et al. 2018). Run the case without
  the file, the tool or the user turn. If the agent still passes, the case doesn't need what it
  claims to test.
- **Contrast sets** (Gardner et al. 2020): a small edit that flips the expected answer. Model
  scores fell by up to 25% on them. A premise the files contradict is the agent version.
- **Metamorphic relations** (Chen et al. 1998; Hyun et al. 2024). When the right answer is unknown,
  test a relation between answers: a paraphrase leaves the result unchanged, an irrelevant document
  leaves it unchanged, doubling a quantity doubles the total. One seemingly relevant but inconsequential
  clause cut model scores by up to 65% on GSM-Symbolic (Mirzadeh et al. 2025). Each relation brings its own oracle.
- **Property-based testing with shrinking** (Claessen & Hughes 2000; built-in shrinking came later,
  Hughes 2007). Generate many inputs and
  shrink each failure to the smallest case that still fails.

Synthetic and model-written cases are elicitation by construction. They can be good: crowdworkers
agreed with 90–100% of the labels in Perez et al. (2022). But their selection probability is
undefined, so they never join the quality set.

**Rare failures.** Don't wait for random cases to find a rare, costly failure; write cases that
target it. Targeted cases can't estimate its rate. To estimate the rate, sample with recorded
weights (importance sampling, Zhao et al. 2017; Wu & Hilton 2025), or extrapolate the tail of the
distribution to deployment scale (Jones et al. 2025).

### 2.6 Pruning

**Decision.** Which cases can go when the suite gets expensive?

**Statistics.** Removing a quality-set case changes the π of the rest and biases θ̂, so the quality
set is pruned only by redrawing it. Bug-finding cases carry no π and can be pruned freely, as long
as coverage holds (rule 25).

Pruning by "this case always passes" has its own error. A case's class is an estimate: a case that
truly passes 90% of the time looks always-pass across two versions at k = 3 with probability 53%,
and across three versions with probability 39%. So always-pass means "not shown to discriminate",
not "can't discriminate", and a prune should re-run the comparison's sizing (§4.1) to show the
detectable effect is unchanged. Item response theory gives the formal version: each case gets a
difficulty and a discrimination (Lalor et al. 2016; Vania et al. 2021), and tinyBenchmarks uses it to pick a small subset that
predicts the full score (Maia Polo et al. 2024). Software testing's suite
minimization keeps a coverage criterion while removing cases (Yoo & Harman 2012), and optimal test
assembly combines the two in an integer program that maximizes test information under blueprint and cost
constraints (van der Linden 2005). One caution: item analysis and item response theory struggled to reduce variance in LLM evals in
practice (Madaan et al. 2024). Prune for cost, and keep coverage.

---

## 3. The measurement model

### 3.1 Checks: binary, one failure mode each

**Decision.** A 1–10 rubric, or several yes/no checks?

**Statistics.** Every check, code or judge, answers one yes-or-no question about one failure mode
(rule 11). Three results point the same way:

1. **A binary check is a diagnostic test**, with a catch rate and a clean pass rate you can measure
   against labels (§3.2). A score on a scale invites a different threshold for every rater: in
   generalizability theory the rater facet and its interaction with items can carry much of the
   variance, and rater-effect models in item response theory give each rater their own thresholds.
2. **Yes-or-no checklists raise agreement with people** (Cook et al. 2024), though their benefit is
   inconsistent when a judge scores one answer directly, and their authors call for more objective
   criteria (Furuhashi et al. 2025). The evidence is mixed: on paired preferences, scoring all
   criteria in one prompt held up better than splitting them into separate calls (Kumar, Rathore &
   Moitra 2026). One question per check is chosen for measurability and attribution (points 1 and
   3), not because splitting always agrees with people more.
3. **One failure mode per check makes errors attributable.** A disagreement can be traced to a
   check, and a check that never fires can be pruned.

**Exactly one check per failure mode counts** (rule 12). Two checks on the same mode count it twice,
and their combined error rates are unknown. Extra checks on a mode are diagnostics.

**Code where code can decide** (rule 14). A code check that reads state (did the refund happen, for
the right amount) has no error to correct. A judge belongs on failure modes code can't decide, not
doubling one that code already checks.

### 3.2 A judge is a diagnostic test

**Decision.** How good is this judge, and what does its number mean?

**Statistics.** Measure the catch rate and the clean pass rate separately, each with a Wilson
interval, and never report raw agreement. Agreement mixes the two rates with the base rate: at a 95%
pass rate a judge that always says "pass" agrees with people 95% of the time and catches nothing.
Medicine settled this decades ago: report sensitivity and specificity, which don't depend on
prevalence, and derive predictive values for a given prevalence.

**Correcting a rate for the judge's error.** If a judge fails a share f_obs of runs, the true
failure rate is

  f = (f_obs + clean − 1) / (catch + clean − 1) = (f_obs + clean − 1) / J

(Rogan & Gladen 1978), and its interval should include the uncertainty in catch and clean as well as
in the runs (delta method). Two things follow:

- A judge with J ≤ 0 is no better than chance, and its rate cannot be corrected. Say so instead of
  printing a number.
- A judge calibrated on few labels gives a wide corrected interval even on thousands of runs. The
  labels, not the runs, limit what the judge can tell you.

When some runs also carry a person's label, prediction-powered inference does the correction with a
valid interval (§3.6).

**Choosing a probabilistic judge's threshold.** Maximizing catch + clean (Youden's J) treats a missed
failure and a false alarm as equally costly and ignores the base rate. Decision theory puts the
optimal threshold where the ROC slope equals (cost of a false pass ÷ cost of a false fail) ×
((1 − p) ÷ p), with p the failure rate. The costs come from the estimand's weights (§1.1). Choose
the threshold on one part of the labels and score it on another (out of fold), or the rates will be
optimistic.

**Probabilities.** ECE and Brier say whether a judge's probabilities mean what they say. The plug-in ECE is noisy and biased on small label sets, and binning itself can hide
miscalibration (Kumar, Liang & Ma 2019). Use their debiased estimator, or on 60 labels read ECE as
a ranking between judges, not as an absolute value.

**A judge is part of the instrument** (rule 13). A new judge prompt or model has unknown error rates,
and correcting two versions with one shared estimate of a judge's error rates, when its rates
differ between them, can reverse a comparison with apparent confidence (Fiedler 2026). Measure the rates again before its numbers count (§3.8).

### 3.3 What a grader's error costs you

**Decision.** How good does a judge need to be?

**Statistics.** If the true failure rate is p, a grader fails a run with probability
q = catch·p + (1 − clean)(1 − p) = (1 − clean) + J·p. Its slope in p is J, so a real change of Δ in
the failure rate shows up as a change of only J·Δ in what the grader reports (Bross 1954, for a
difference between two proportions; Fiedler 2026, for LLM judges). Spearman (1904) saw the analogous
attenuation in correlations measured with error. Correcting the reported rate (§3.2) divides by J,
and the variance by J², so the cases needed to see the same change grow by the factor

  q(1 − q) / (J² · p(1 − p))

(an early sample-size treatment is Rubin, Rosenbaum & Cobb 1956; a modern closed form for one- and
two-sample tests is Hársfalvi & Reiczigel 2024). Near p = 50% the factor is about 1/J². For rare
failures it is much larger, because the grader's false flags on good runs swamp the few real
failures:

| Catch, clean | J | p = 50% | p = 20% | p = 10% | p = 3% |
|---|---:|---:|---:|---:|---:|
| 1.00, 1.00 (code) | 1.00 | 1.0× | 1.0× | 1.0× | 1.0× |
| 0.95, 0.95 | 0.90 | 1.2× | 1.4× | 1.7× | 3.0× |
| 0.90, 0.90 | 0.80 | 1.6× | 1.9× | 2.6× | 5.8× |
| 0.80, 0.90 | 0.70 | 2.0× | 2.3× | 3.2× | 7.5× |
| 0.80, 0.80 | 0.60 | 2.8× | 3.8× | 5.9× | 16× |
| 0.75, 0.75 | 0.50 | 4.0× | 5.7× | 9.3× | 27× |

So a judge that is good enough for common failures can be ruinous for rare ones, and for rare
failures its clean pass rate matters most. A threshold test that refunds break the policy less than
5% of the time (one-sided α = 0.05, 80% power against a true rate of 1%) takes about 120 cases with
a code check, about 860 with a judge at catch 0.80 and clean 0.90, and about 175 with one at catch
0.95 and clean 0.99. Tests whose critical values and power are written in the judge's error rates
exist for exactly this case (Feng et al. 2026), as do power calculations for prediction-powered
inference (Chen, Guo & Li 2026) and for splitting a budget between human and judge labels (Kim
2026).

This is how a floor on a judge is set: decide how many extra cases you are willing to pay for at the
failure rates you care about, and the floor on catch and clean follows. It is also why the grader's
error enters every power calculation in §4.1, and why code checks are worth so much on rare, costly
failures.

Three cautions. Comparisons between versions behave the same way as a single rate. The factor
assumes the judge errs the same way on both versions being compared; a judge that is better at
grading one version than the other biases the comparison, which no number of cases fixes (Fiedler
2026). And it treats catch and clean as known: their uncertainty adds a term that shrinks only with
more labels, and grows as 1/J⁴ (Fiedler 2026; §3.4).

### 3.4 How many labels, and which ones

**Decision.** How many labels does a judge need, and of which kind?

**Statistics.** The count is **per kind**. The catch rate is measured only on runs a person failed,
and the clean pass rate only on runs a person passed. Each is its own proportion with its own n. At
a rate of 0.8, a Wilson interval of ±10 points needs about **60 labels of that kind**, and ±5 points
needs about 245. Sixty labels in total, split 58/2, measure the catch rate on two runs: "caught 2 of
2" has an interval from 34% to 100%.

**Which kind to label more of.** Calibrating a judge needs both rates, so a balanced split is right
for calibration. *Using* a judge to estimate a low failure rate is different: its false alarms on
passing runs drive the error, not its misses. Take a true failure rate of 5%, a judge that catches
80% of failures and passes 95% of good runs, and 10,000 graded runs. The 95% interval on the
corrected failure rate is:

| Labels (failing + passing) | Interval on the corrected failure rate | Width |
|---|---|---:|
| 30 + 30 | 0.0% to 14.7% | 14.7 pts |
| 100 + 100 | 0.0% to 10.5% | 10.5 pts |
| 200 + 200 | 1.1% to 8.9% | 7.8 pts |
| 100 + 300 | 1.7% to 8.3% | 6.5 pts |
| 50 + 350 | 1.7% to 7.9% | 6.2 pts |

The same 400 labels placed mostly on passing runs give an interval 20% narrower than an even split,
and 100 + 100 can't exclude a zero failure rate. Put labels where the variance comes from, and prefer
runs the judge is unsure of, with inference that stays valid under that choice (Zrnic & Candès 2024;
Gligorić et al. 2025).

**The ceiling on what a judge saves.** Combining a few labels with many judge verdicts can cut the
labels needed (§3.6), but when the judge is no more accurate than the agent it grades, no method can
cut them by more than half (Dorner, Nastl & Hardt 2025). A judge from the same family as the agent is often no more accurate than
it, so it is likely near that ceiling. It is one more reason to use a judge
from a different family and to prefer code checks.

### 3.5 Reliability is not validity

**Decision.** The judge gives the same answer every time, and two judges agree. Is it right?

**Statistics.** A judge can be perfectly consistent and consistently wrong. In one audit, the most
deterministic judge matched ground truth 51% of the time (Kumar, Rathore & Moitra 2026). Agreement
across model families rules out one family's quirks, not a shared blind spot: a panel that largely agrees can still be wrong, and an item-level risk score flags some of those
cases (Ba, Mancenido & Pan 2026).
Only labels measure validity, so self-consistency and cross-family agreement are reported next to
the catch and clean pass rates, never in their place.

For pairwise grading, position bias flips many verdicts on hard items (Wang et al. 2023; Shi et al.
2025), so judge both orders and record a flip as no verdict. Judges can also favor their own outputs (Panickssery, Bowman & Feng 2024; Zheng et al. 2023 saw
signs of it but could not establish it), so a pairwise judge comes from a different family than
both sides.

**Choosing between judges.** Two judges scored on the same labels are a paired design, and the test
of "A is better than B" is McNemar's (McNemar 1947) on the labels where exactly one of them is right. On 60 labels
it detects only large differences, so read the choice as "both are good enough; take the cheaper
one", not "A is better than B". The alternative-annotator test (Calderon, Reichart & Dror 2025) is the formal version of "can this judge stand in for a person"; it needs at least three people
labeling the same items.

### 3.6 The whole eval against people

**Decision.** Every check passed its calibration. Is the eval right?

**Statistics.** A run passes only if every counted check passes. If each of m independent checks
passes a good run with probability clean_i, a good run passes the eval with probability ∏ clean_i.
Five judge checks at 0.9 pass a good run only 59% of the time. Code checks are near 1, so this cost
falls almost entirely on judges.

The product assumes the judges err independently. Judges that share a model family, a rubric or a
prompt template don't (§2.4), so the product is a poor predictor in both directions: correlated false
fails land on the same runs, and correlated misses let the same bad runs through every check. And no
per-check number sees a failure no check looks for. So the eval as a whole is held to people
(rule 15): people label whole runs without seeing the checks, the eval grades the same runs, and
the eval's own **catch rate** and **clean pass rate** come from comparing the two. These are the
measurement model of the eval: the numbers its corrections and its power calculations use.

Everything in §3.2–3.4 carries over: count per kind, report both rates with intervals, and fix the
number of labels before looking (§4.7). Give every disagreement a cause (a check bug, a wrong
expected answer, a gap in the standard, a missing check) and fix that.

**What would a person say the pass rate is?** The eval grades every run but is wrong sometimes;
people grade a few runs and are the reference. **Prediction-powered inference** combines the two
into an estimate of what people would say about all of them, with a valid interval (Angelopoulos et
al. 2023). The estimate is the labels' mean, plus a correction for how far the eval's verdicts on the
labeled runs sit from its verdicts on the rest. PPI++ (Angelopoulos, Duchi & Zrnic 2023) weighs the
eval's contribution by how well it tracks the labels: an eval that agrees with people narrows the
interval well below labels alone, and one that doesn't is given no weight, so the estimate is never
meaningfully worse than the labels alone. Stratified PPI does the same per segment (Fisch et al.
2024).

**Assumption.** The labeled runs must be a random sample of the runs they stand for. Runs chosen because they looked wrong would bias the estimate (verification bias, Begg & Greenes
1983), so labels come from a queue that draws them, not
from hand-picking.

**Agreement between people.** People are the reference, so their own agreement is measured: some
share of runs is labeled by two people. Cohen's κ (Cohen 1960) depends on the base rate: when most runs pass, two
people can agree on 90% of runs and get κ below zero, because chance agreement is already high
(Feinstein & Cicchetti 1990). **Gwet's AC1** corrects for chance in a way that is far more stable at a skewed base rate (Gwet 2008), and the two **specific agreements**, on fails and on passes (Cicchetti
& Feinstein 1990), show where the disagreement is. At 90 agreements of 100 (90 runs both pass, 5 and 5 split, none both fail), two people can have
κ = −0.05 and AC1 = 0.89 while agreeing on 95% of passes and **none of the failures**, and the
failures are the part that matters. Report all three; read κ only when the pass rate is near 50%.
About 60 doubly labeled runs give agreement to within ±13 points at worst, and ±8 near 90%
agreement.

**Settling disagreements.** A disagreement between people goes to a third person, whose ruling
becomes the verdict (adjudication). A latent-class model (Dawid & Skene 1979) can estimate each
labeler's error rates from their disagreements alone, which helps once there are many labelers, but
its independence assumption needs checking first. Grading outputs changes the criteria people grade
by (Shankar et al. 2024), so the labeling standard is versioned, and a new rule triggers a recheck of
the labels it could flip.

### 3.7 Trials: noise and k

**Decision.** More cases, or more trials per case?

**Statistics.** A case's k trials are not k independent observations: a hard case tends to fail
every time. Generalizability theory splits the variance of a per-trial outcome into a
**between-case** part (cases differ in difficulty) and a **within-case** part (run-to-run noise on
one case) (Cronbach et al. 1972; Brennan 2001). The standard error of the mean pass rate over N cases
and k trials is then

  SE = √( σ²_between / N  +  σ²_within / (N·k) ).

Only the second term shrinks with k. Three numbers turn this into a decision
(`stats.variance_components`):

- **ICC** (intraclass correlation): the between-case share of the variance. Near 1, cases are
  deterministic and extra trials are wasted. Near 0, every case is a coin flip and trials are as
  good as new cases.
- **Effective n** = (N·k) / (1 + (k − 1)·ICC) (Kish). Ten deterministic cases at k = 3 are worth 10,
  not 30.
- **The standard error from doubling cases, and from doubling trials.** Buy whichever shrinks it
  more for the cost. A G-study followed by a D-study is exactly this calculation.

In typical agent suites the between-case part dominates, so **more cases beat more trials** once k
is large enough to see noise at all (rule 16). Miller (2024) makes the same point: once the within-case variance divided by k is small
next to the between-case variance, more trials barely move the standard error, while more cases
always do. k = 3 is the
smallest k that gives a majority verdict and an estimate of within-case noise, so it is the default
until a baseline measures the split. k = 1 gives no within-case variance, so no interval or test can
be computed honestly from it.

**Few cases.** Cluster-robust intervals over trials-within-cases are anti-conservative with few
clusters: with 5 to 30 of them, tests using normal critical values can over-reject (Cameron, Gelbach & Miller 2008;
MacKinnon, Nielsen & Webb 2023). Use a t(G − 1) critical value rather than z, build the interval on
the logit scale when a symmetric one would cross 0% or 100%, and fall back to a Wilson interval over
cases (or clusters) when the cluster estimate collapses. Below about 30 cases, read any interval as a
minimum width.

**Flakiness and pass^k.**

- A case is **flaky** when 0 < passes < k. A case that passes 95% of the time is flagged at k = 3
  with probability 14%, and at k = 5 with 23%. A case that isn't flagged is not shown to be stable.
- **pass^k**, the share of cases that pass all k trials, is the reliability a user sees on repeated
  use (Yao et al. 2024). It falls fast: a case that passes 75% of trials passes all 3 with probability 42%, and all 8 with
10%. When a case
  has more trials than k, the unbiased estimator is C(c, k)/C(n, k) for c passes in n trials (Yao et al. 2024; the all-pass counterpart of the pass@k estimator of Chen et al. 2021).

### 3.8 When the instrument changes

**Decision.** The judge, a check or the labeling standard changed. What still holds?

**Statistics.** Each change breaks an assumption behind specific numbers:

| Change | Assumption broken | Numbers affected | Kind of change ([estimators §9](estimators.md#9-changing-a-suite)) |
|---|---|---|---|
| The agent | same population of runs | the baseline, the noise floor, the discriminating cases | none: this is what the eval measures |
| A check | same instrument | the eval's catch and clean pass rates | revise |
| A judge's prompt or model | same catch and clean rates | that judge's calibration, the corrected rates, the power | revise |
| The labeling standard | same reference | the labels a new rule could flip | revise if verdicts move |
| The traffic mix or routing | same weights and frame | θ̂, the allocation, downstream evals' frames | revise (§1.4) |

Psychometrics keeps two forms of a test comparable with a small **anchor set**: common items scored
on both forms, with an equating function and its error (Kolen & Brennan 2014). By analogy, a labeled anchor set re-judged on every judge version shows whether old and new verdicts are on the same scale without
relabeling everything.

**Cases with an unverified answer** have unknown measurement error, so they stay out of the score
until a person has read them (rule 17).

---

## 4. The decision rule

### 4.1 Case counts come from power

**Decision.** How many cases does each gated estimand need?

**Statistics.** The count solves "power at least 1 − β to detect a change of Δ at level α" for the
decision rule's test (rule 7; Neyman & Pearson 1933), and then multiplies by the grader's inflation
factor (§3.3). Three tests
cover most decisions, and they need different arithmetic, so one flat number per segment can't serve
them all.

**Threshold, with zero failures: detection.** If a failure affects a share p of runs, n cases show
it at least once with probability 1 − (1 − p)ⁿ. Fix that at 95% and solve, n ≥ ln(0.05) / ln(1 − p):

| Cases | Surfaces, with 95% probability, a failure that affects at least |
|---:|---:|
| 3 | 63% of runs |
| 10 | 26% |
| 20 | 14% |
| 30 | 9.5% |
| 59 | 5% |
| 100 | 3% |
| 299 | 1% |

Read backwards, this is the **zero-failure bound**: if all n cases pass, the failure rate could
still be as high as 1 − 0.05^(1/n), about 3/n (the "rule of three", Hanley & Lippman-Hand 1983). A
clean run on 10 cases cannot rule out a failure that hits one run in five. Detection applies **per
failure mode**: a segment at 70% is usually several failure modes at a few percent each, not one at
30%, and each needs enough cases to be seen. Over clusters, count clusters (§2.4). The zero-failure arithmetic assumes a grader that never
flags a good run: a code check, or a person. A judge with a clean pass rate below 1 flags good runs,
so a clean run never comes, and the threshold test of §3.3 applies instead.

**Non-inferiority on a solved segment: a regression guard.** Near 100%, with noise ruled out, one
new consistent failure is signal, so a guard is sized by detection: the smallest n with
1 − (1 − δ)ⁿ ≥ 95% for a tolerated drop δ.

| Tolerated drop | Cases |
|---:|---:|
| 10 points | 29 |
| 5 points | 59 |
| 2 points | 149 |
| 1 point | 299: use a check on every production run, or a canary, instead |

A segment at 99% has one question first: what is the 1%? If the case passes on a re-run, it was
noise. If a person passes the run, the check or the expected answer was wrong; fix it. If it fails
consistently on some input, it is a real rare failure, and if its cost is high it becomes a failure
mode with its own detection need.

**Superiority: seeing whether a change helped.** For a paired comparison (§4.3) the cases needed
depend on the smallest change worth seeing, Δ, and on the share of cases that flip between versions,
d, not directly on the pass rate: N ≈ 7.85·d/Δ² at 80% power and two-sided α = 0.05
(`stats.cases_for_flip_rate`). Realistic gains scale with the room left to improve, so "harder needs
more cases" doesn't hold. Halving the failure rate, unpaired (pairing lowers every row), takes per
version (`stats.cases_per_arm`):

| Failure rate | Cases per version to see it halved |
|---:|---:|
| 50% | 55 |
| 30% | 118 |
| 10% | 432 |
| 1% | 4,671 |

**Putting it together.** A segment's target is the largest of its needs, since the same cases serve
every job (`stats.allocation_target`): its comparison, its guard, the detection need of each costly
failure mode, and its own gate if the blind-spot check (§1.2) gave it one. Weight enters through the
inputs: a heavier segment gets a smaller worthwhile change, a tighter tolerated drop and more of its
failure modes counted as costly. Each count is multiplied by the inflation factor of the checks that grade it (§3.3).
The rest of the budget goes by optimum allocation around those minimums (§2.3).

### 4.2 Floors: showing that you cleared the bar

**Decision.** The judge's catch rate came out at 87% against an 85% bar. Is it good enough?

**Statistics.** A floor on a grader (§3.3) is itself a threshold decision rule, and it needs
evidence, not a point estimate. A point estimate on a few items clears a floor by luck about half
the time when the true rate sits at the floor:

| Measured | Point | 95% lower bound | Meets the point floor | Within 10 pts of the floor at the lower bound |
|---|---:|---:|:---:|:---:|
| Catch 13 of 15 (floor 85%) | 87% | 62% | yes | no; about 48 needed at this rate |
| Clean 23 of 30 (floor 75%) | 77% | 59% | yes | no; about 61 needed |
| Catch 15 of 15 | 100% | 80% | yes | yes |
| Catch 90 of 100 | 90% | 83% | yes | yes |

Clinical trials solve this with a **non-inferiority margin**: the lower confidence bound must sit no
more than a stated margin below the bar (U.S. FDA 2016). aot-evals also asks the estimate itself to
reach the bar, which is stricter than the trial standard. The alternative-annotator test uses a
similar margin to decide whether a model can replace a person (Calderon, Reichart & Dror 2025). The count of labels of each kind follows from the margin
(§3.4), and must be fixed before looking (§4.7).

### 4.3 Compare versions case by case

**Decision.** Version B scored higher. Is it better?

**Statistics.** Run both versions on the same cases with one change between them (rule 18). Pairing
removes between-case variance: a hard case is hard on both sides. At 50 cases, an unpaired comparison
at a 50% pass rate detects about 28 points. A paired one detects about 7 points when the change
shifts every case alike, and about 15 points when it affects cases unevenly (a 15% discordance rate).

**The flips are all the evidence.** When A and B run on the same N cases, only the flips carry
information: b cases went from pass to fail, c from fail to pass. The net change is Δ = (c − b)/N,
the **flip rate** is d = (b + c)/N, and the standard error of Δ is √((d − Δ²)/N). The same +5 points
at N = 200 can be a clear win or noise:

| What the change did | d | 95% interval on Δ |
|---|---:|---|
| 10 gains, 0 losses | 5% | +5 ± 3.0 points |
| 30 gains, 20 losses | 25% | +5 ± 6.9 points |

Ten fixes and no breaks give a two-sided p of 1/512; thirty against twenty give p = 0.20. List gains
and losses separately: a net of zero can hide ten fixes and ten new breaks, and both lists need
reading. Flaky cases inflate d with no real change, so an A/A rerun of the baseline gives the noise
floor of d. Store d from past comparisons and size the next one from it (§4.1).

### 4.4 Which test

**Statistics.** The test of a paired comparison is the **sign-flip permutation test** on per-case
deltas, the exact paired permutation test of no difference, assuming each case's delta is symmetric about
zero under the null (Fisher 1935; Good 2005). It counts every change in a
case's pass rate, so a case going from 3/3 to 2/3 counts. McNemar's test on majority verdicts throws
those away, and its exact version is conservative: its real size averages about 2% at a nominal 5%, and about 1% below 30 pairs. A comparison of
methods for paired binary data recommends against it in every situation, in favor of the mid-p or
the exact unconditional test (Fagerland, Lydersen & Laake 2013). Where a McNemar is shown, show the mid-p.

**The interval.** The percentile bootstrap over cases under-covers on small suites near a ceiling,
where the deltas are few, discrete and skewed. Inverting the sign-flip test gives an interval that
assumes only that each case's delta is symmetric about the true mean: every μ at which flipping the
signs of (delta − μ) is not rejected (`stats.sign_flip_interval`). At N ≥ 100 the two agree; below
that, use the sign-flip interval. With a cluster key, signs flip per cluster (§2.4).

**The detectable effect.** Every comparison says the smallest difference it could have seen. Before
a run, that comes from the baseline's variance; after it, from the spread of the actual per-case
deltas, which includes how unevenly the change moved cases, so after the fact it is the honest
number.

A gate on the noise band of repeated baseline runs is not a second test: it double-counts noise the
paired test already handles, and its width depends on k. The band belongs to drift (§1.4).

### 4.5 "No difference" isn't "no worse"

**Decision.** The cheaper model showed no significant difference. Ship it?

**Statistics.** Failing to reject "no difference" says the test couldn't tell, not that there is no
difference. On 50 cases with 4 fixes and 4 breaks, the 95% interval on Δ runs about ±11 points. To
claim "no worse", state a margin Δ in advance and test it: the lower bound of θ_new − θ_old must sit
above −Δ (rule 19). To show the cheaper model is within 5 points at that flip rate takes about 500
cases (`stats.cases_for_flip_rate(0.16, 0.05)` = 503). Non-inferiority is the standard design for
"cheaper and no worse" in clinical trials, and the same arithmetic applies.

Non-inferiority is also how a component change is checked against the system (§1.3) and how a
blind segment is guarded (§1.2).

### 4.6 Many gates

**Statistics.** Each gate is a test, and each test at α = 0.05 is a 1-in-20 chance of a false
alarm. Ten gates with no real change flag at least one about 40% of the time (1 − 0.95¹⁰). That holds
for per-segment gates, and for several evals gating one change (§1.3). Control it (rule 22):
Benjamini–Hochberg controls the share of false discoveries among the gates that fire, when the
p-values are independent or positively dependent (Benjamini & Hochberg 1995); Holm controls the
chance of any (Holm 1979). Per-segment rows that don't gate are diagnostics,
and their p-values are shown adjusted.

### 4.7 Looks: stop peeking

**Decision.** When do we stop labeling, or stop tuning?

**Statistics.** Every look at the data before deciding is another chance to clear the bar by luck.
Say a suite truly catches 80% of bad runs, short of an 85% bar. Checked once on 15 labels, it clears
by luck 40% of the time. Checked after every 5 labels from 15 to 60, stopping as soon as it clears,
it clears 56% of the time. A fixed batch of 60 clears 21% of the time. So fix the number of labels
or runs before looking (rule 21), or use an always-valid sequential interval that allows looks by
design (Howard et al. 2021; Wald 1947 for sequential tests).

**Tuning and holding out.** Every fix made by reading a set's disagreements fits the eval to that
set. Keep a split for development and a held-out split that is checked once per claim. Each look at
the held-out split spends some of its validity, and adaptive data analysis bounds how much (Dwork et
al. 2015; Blum & Hardt 2015). Label a fresh batch before a new claim.

**Optimizers.** An optimizer that queries the eval thousands of times (prompt search, skill
evolution) fits the eval, the way repeated holdout reuse fits a holdout. Moderate reuse can do little
damage: Recht et al. (2019) found an 11–14 point drop on a fresh ImageNet test set, but gains on the old
set carried over (and grew), and the drop came from the new set's slightly harder images, not from
reuse. An optimizer making
thousands of queries is not moderate reuse. Keep a split it never sees and count its looks (rule 23),
with a reusable holdout that answers through a noisy threshold (Thresholdout, Dwork et al. 2015) or a leaderboard
that only reports significant improvements (the Ladder, Blum & Hardt 2015). The judge has the same
exposure: optimizing against a proxy grader eventually lowers the real score (Gao, Schulman & Hilton 2023; Manheim & Garrabrant 2018). Relabel a fresh sample after an optimization run before trusting
its gains. And never let the agent see the cases.

### 4.8 Cost and latency are constraints

**Statistics.** Cost and latency are counted, not graded, so they have no instrument error, but
they have sampling error, and costs are skewed. Compare cost per *successful* task rather than per
run (a run that gives up early is cheap), and medians and p90 rather than means, with bootstrap
intervals over cases. A budget is a constraint in the decision rule, not part of θ (rule 24): a
change that improves θ and breaks the budget is a trade, reported with both numbers so a person can
weigh them. Operational failures (timeouts, rate limits) are counted on their own, never as wrong
answers.

---

## 5. References

Checked in November 2026: metadata against arXiv, Crossref or the publisher, and each claim the
text attributes to a source against that source where its text was available. For paywalled
articles the check used the abstract; for books, standard bibliographic records.

**Estimands and validity.**
- AERA, APA & NCME (2014). *Standards for Educational and Psychological Testing.* Washington, DC: American Educational Research Association.
- Cronbach, L. J. & Meehl, P. E. (1955). Construct validity in psychological tests. *Psychological Bulletin* 52(4):281–302. doi:10.1037/h0040957
- Haberman, S. J. (2008). When can subscores have value? *Journal of Educational and Behavioral Statistics* 33(2):204–229. doi:10.3102/1076998607302636
- Lawshe, C. H. (1975). A quantitative approach to content validity. *Personnel Psychology* 28(4):563–575. doi:10.1111/j.1744-6570.1975.tb01393.x
- Messick, S. (1989). Validity. In R. L. Linn (Ed.), *Educational Measurement* (3rd ed., pp. 13–103). New York: American Council on Education / Macmillan.
- Messick, S. (1995). Validity of psychological assessment: Validation of inferences from persons' responses and performances as scientific inquiry into score meaning. *American Psychologist* 50(9):741–749. doi:10.1037/0003-066X.50.9.741
- Spearman, C. (1904). The proof and measurement of association between two things. *American Journal of Psychology* 15(1):72–101. doi:10.2307/1412159

**Sampling and estimation.**
- Bowyer, S., Aitchison, L. & Ivanova, D. R. (2025). Position: Don't use the CLT in LLM evals with fewer than a few hundred datapoints. *ICML 2025*. arXiv:2503.01747
- Cochran, W. G. (1977). *Sampling Techniques* (3rd ed.). New York: Wiley.
- Frankl, P. G., Hamlet, R. G., Littlewood, B. & Strigini, L. (1998). Evaluating testing methods by delivered reliability. *IEEE Transactions on Software Engineering* 24(8):586–601. doi:10.1109/32.707695
- Hájek, J. (1971). Comment on "An essay on the logical foundations of survey sampling, part one" by D. Basu. In V. P. Godambe & D. A. Sprott (Eds.), *Foundations of Statistical Inference* (p. 236). Toronto: Holt, Rinehart and Winston.
- Hanley, J. A. & Lippman-Hand, A. (1983). If nothing goes wrong, is everything all right? Interpreting zero numerators. *JAMA* 249(13):1743–1745. doi:10.1001/jama.1983.03330370053031
- Horvitz, D. G. & Thompson, D. J. (1952). A generalization of sampling without replacement from a finite universe. *JASA* 47(260):663–685. doi:10.1080/01621459.1952.10483446
- Jones, E., Tong, M., Mu, J. et al. (2025). Forecasting rare language model behaviors. arXiv:2502.16797
- Kish, L. (1965). *Survey Sampling.* New York: Wiley.
- Kossen, J., Farquhar, S., Gal, Y. & Rainforth, T. (2021). Active testing: Sample-efficient model evaluation. *ICML 2021*. arXiv:2103.05331
- Madaan, L., Singh, A. K., Schaeffer, R. et al. (2024). Quantifying variance in evaluation benchmarks. arXiv:2406.10229
- Miller, E. (2024). Adding error bars to evals: A statistical approach to language model evaluations. arXiv:2411.00640
- Musa, J. D. (1993). Operational profiles in software-reliability engineering. *IEEE Software* 10(2):14–32. doi:10.1109/52.199724
- Neyman, J. (1934). On the two different aspects of the representative method: The method of stratified sampling and the method of purposive selection. *JRSS* 97(4):558–625. doi:10.2307/2342192
- Wu, G. & Hilton, J. (2025). Estimating the probabilities of rare outputs in language models. *ICLR 2025*. arXiv:2410.13211
- Zhao, D., Lam, H., Peng, H. et al. (2017). Accelerated evaluation of automated vehicles safety in lane-change scenarios based on importance sampling techniques. *IEEE Transactions on Intelligent Transportation Systems* 18(3):595–607. doi:10.1109/TITS.2016.2582208. arXiv:1605.04965

**Tests, comparisons and power.**
- Benjamini, Y. & Hochberg, Y. (1995). Controlling the false discovery rate: A practical and powerful approach to multiple testing. *JRSS B* 57(1):289–300. doi:10.1111/j.2517-6161.1995.tb02031.x
- Chen, M., Tworek, J., Jun, H. et al. (2021). Evaluating large language models trained on code. arXiv:2107.03374
- Fagerland, M. W., Lydersen, S. & Laake, P. (2013). The McNemar test for binary matched-pairs data: Mid-p and asymptotic are better than exact conditional. *BMC Medical Research Methodology* 13:91. doi:10.1186/1471-2288-13-91
- Fisher, R. A. (1935). *The Design of Experiments.* Edinburgh: Oliver & Boyd.
- Good, P. I. (2005). *Permutation, Parametric and Bootstrap Tests of Hypotheses* (3rd ed.). New York: Springer.
- Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics* 6(2):65–70.
- Howard, S. R., Ramdas, A., McAuliffe, J. & Sekhon, J. (2021). Time-uniform, nonparametric, nonasymptotic confidence sequences. *Annals of Statistics* 49(2):1055–1080. doi:10.1214/20-AOS1991
- McNemar, Q. (1947). Note on the sampling error of the difference between correlated proportions or percentages. *Psychometrika* 12(2):153–157. doi:10.1007/BF02295996
- Montgomery, D. C. (2019). *Introduction to Statistical Quality Control* (8th ed.). Hoboken: Wiley.
- Neyman, J. & Pearson, E. S. (1933). On the problem of the most efficient tests of statistical hypotheses. *Phil. Trans. R. Soc. A* 231:289–337. doi:10.1098/rsta.1933.0009
- Shewhart, W. A. (1931). *Economic Control of Quality of Manufactured Product.* New York: Van Nostrand.
- U.S. Food and Drug Administration (2016). *Non-Inferiority Clinical Trials to Establish Effectiveness: Guidance for Industry.* https://www.fda.gov/media/78504/download
- Wald, A. (1947). *Sequential Analysis.* New York: Wiley.
- Yao, S., Shinn, N., Razavi, P. & Narasimhan, K. (2024). τ-bench: A benchmark for tool-agent-user interaction in real-world domains. arXiv:2406.12045

**Clustered and dependent data.**
- Cameron, A. C., Gelbach, J. B. & Miller, D. L. (2008). Bootstrap-based improvements for inference with clustered errors. *Review of Economics and Statistics* 90(3):414–427. doi:10.1162/rest.90.3.414
- Cochran, W. G. (1950). The comparison of percentages in matched samples. *Biometrika* 37(3–4):256–266. doi:10.1093/biomet/37.3-4.256
- Goel, S. et al. (2025). Great models think alike and this undermines AI oversight. *ICML 2025*. arXiv:2502.04313
- Kim, E., Garg, A., Peng, K. & Garg, N. (2025). Correlated errors in large language models. *ICML 2025*. arXiv:2506.07962
- MacKinnon, J. G., Nielsen, M. Ø. & Webb, M. D. (2023). Cluster-robust inference: A guide to empirical practice. *Journal of Econometrics* 232(2):272–299. doi:10.1016/j.jeconom.2022.04.001. arXiv:2205.03285
- Tarone, R. E. (1979). Testing the goodness of fit of the binomial distribution. *Biometrika* 66(3):585–590. doi:10.1093/biomet/66.3.585
- Webb, M. D. (2023). Reworking wild bootstrap-based inference for clustered errors. *Canadian Journal of Economics* 56(3):839–858. doi:10.1111/caje.12661

**Measurement error and judges.**
- Ba, Y., Mancenido, M. V. & Pan, R. (2026). Can we trust this evaluation? Instance-level reliability of LLM-as-a-judge. arXiv:2610.14029
- Begg, C. B. & Greenes, R. A. (1983). Assessment of diagnostic tests when disease verification is subject to selection bias. *Biometrics* 39(1):207–215. doi:10.2307/2530820
- Bross, I. (1954). Misclassification in 2 × 2 tables. *Biometrics* 10(4):478–486. doi:10.2307/3001619
- Calderon, N., Reichart, R. & Dror, R. (2025). The alternative annotator test for LLM-as-a-judge: How to statistically justify replacing human annotators with LLMs. arXiv:2501.10970
- Chen, Y. T., Guo, M. & Li, S. (2026). Power analysis for prediction-powered inference. arXiv:2603.16041
- Cook, J., Rocktäschel, T., Foerster, J., Aumiller, D. & Wang, A. (2024). TICKing all the boxes: Generated checklists improve LLM evaluation and generation. arXiv:2410.03608
- Dorner, F. E., Nastl, V. Y. & Hardt, M. (2025). Limits to scalable evaluation at the frontier: LLM as judge won't beat twice the data. *ICLR 2025*. arXiv:2410.13341
- Feng, C., Shen, M., Balashankar, A., Gerner-Beuerle, C. & Rodrigues, M. R. D. (2026). Noisy but valid: Robust statistical evaluation of LLMs with imperfect judges. arXiv:2601.20913
- Fiedler, J. (2026). Bias and uncertainty in LLM-as-a-judge estimation. arXiv:2605.06939
- Furuhashi, M., Nakayama, K., Kodama, T. & Sugawara, S. (2025). Are checklists really useful for automatic evaluation of generative tasks? *EMNLP 2025*. arXiv:2508.15218
- Hársfalvi, P. & Reiczigel, J. (2024). The effect of misclassification on sample size for one and two-sample tests with binary endpoints. *Journal of Biopharmaceutical Statistics* 36(3):561–572. doi:10.1080/10543406.2024.2444231
- Kim, J. P. (2026). Augmenting human evaluation with LLM judges: How many human reviews do you need? arXiv:2605.16354
- Kumar, A., Liang, P. & Ma, T. (2019). Verified uncertainty calibration. *NeurIPS 2019*. arXiv:1909.10155
- Kumar, V., Rathore, D. & Moitra, A. (2026). All verdicts are not equal: Rethinking LLM judge reliability. *AACL-IJCNLP 2026*. arXiv:2610.12083
- Panickssery, A., Bowman, S. R. & Feng, S. (2024). LLM evaluators recognize and favor their own generations. arXiv:2404.13076
- Rogan, W. J. & Gladen, B. (1978). Estimating prevalence from the results of a screening test. *American Journal of Epidemiology* 107(1):71–76. doi:10.1093/oxfordjournals.aje.a112510
- Rubin, T., Rosenbaum, A. S. & Cobb, S. (1956). The use of interview data for the detection of associations in field studies. *Journal of Chronic Diseases* 4(3):253–266. doi:10.1016/0021-9681(56)90028-5
- Shi, L., Ma, C., Liang, W., Diao, X., Ma, W. & Vosoughi, S. (2025). Judging the judges: A systematic study of position bias in LLM-as-a-judge. *AACL-IJCNLP 2025*. arXiv:2406.07791
- Wang, P., Li, L., Chen, L. et al. (2023). Large language models are not fair evaluators. arXiv:2305.17926
- Zheng, L., Chiang, W.-L., Sheng, Y. et al. (2023). Judging LLM-as-a-judge with MT-Bench and Chatbot Arena. *NeurIPS 2023 Datasets and Benchmarks*. arXiv:2306.05685

**Combining judges with human labels.**
- Angelopoulos, A. N., Bates, S., Fannjiang, C., Jordan, M. I. & Zrnic, T. (2023). Prediction-powered inference. *Science* 382(6671):669–674. doi:10.1126/science.adi6000. arXiv:2301.09633
- Angelopoulos, A. N., Duchi, J. C. & Zrnic, T. (2023). PPI++: Efficient prediction-powered inference. arXiv:2311.01453
- Fisch, A., Maynez, J., Hofer, R. A., Dhingra, B., Globerson, A. & Cohen, W. W. (2024). Stratified prediction-powered inference for hybrid language model evaluation. arXiv:2406.04291
- Gligorić, K., Zrnic, T., Lee, C., Candès, E. J. & Jurafsky, D. (2025). Can unconfident LLM annotations be used for confident conclusions? *NAACL 2025*. arXiv:2408.15204
- Zrnic, T. & Candès, E. J. (2024). Active statistical inference. *ICML 2024*. arXiv:2403.03208

**Agreement between people.**
- Cicchetti, D. V. & Feinstein, A. R. (1990). High agreement but low kappa: II. Resolving the paradoxes. *Journal of Clinical Epidemiology* 43(6):551–558. doi:10.1016/0895-4356(90)90159-M
- Cohen, J. (1960). A coefficient of agreement for nominal scales. *Educational and Psychological Measurement* 20(1):37–46. doi:10.1177/001316446002000104
- Dawid, A. P. & Skene, A. M. (1979). Maximum likelihood estimation of observer error-rates using the EM algorithm. *JRSS C* 28(1):20–28. doi:10.2307/2346806
- Feinstein, A. R. & Cicchetti, D. V. (1990). High agreement but low kappa: I. The problems of two paradoxes. *Journal of Clinical Epidemiology* 43(6):543–549. doi:10.1016/0895-4356(90)90158-L
- Gwet, K. L. (2008). Computing inter-rater reliability and its variance in the presence of high agreement. *British Journal of Mathematical and Statistical Psychology* 61(1):29–48. doi:10.1348/000711006X126600
- Shankar, S., Zamfirescu-Pereira, J. D., Hartmann, B., Parameswaran, A. G. & Arawjo, I. (2024). Who validates the validators? Aligning LLM-assisted evaluation of LLM outputs with human preferences. *UIST 2024*. arXiv:2404.12272

**Psychometrics.**
- Brennan, R. L. (2001). *Generalizability Theory.* New York: Springer. doi:10.1007/978-1-4757-3456-0
- Cronbach, L. J., Gleser, G. C., Nanda, H. & Rajaratnam, N. (1972). *The Dependability of Behavioral Measurements: Theory of Generalizability for Scores and Profiles.* New York: Wiley.
- Kolen, M. J. & Brennan, R. L. (2014). *Test Equating, Scaling, and Linking: Methods and Practices* (3rd ed.). New York: Springer. doi:10.1007/978-1-4939-0317-7
- Lalor, J. P., Wu, H. & Yu, H. (2016). Building an evaluation scale using item response theory. *EMNLP 2016*. arXiv:1605.08889
- Maia Polo, F., Weber, L., Choshen, L., Sun, Y., Xu, G. & Yurochkin, M. (2024). tinyBenchmarks: Evaluating LLMs with fewer examples. *ICML 2024*. arXiv:2402.14992
- van der Linden, W. J. (2005). *Linear Models for Optimal Test Design.* New York: Springer. doi:10.1007/0-387-29054-0
- Vania, C., Htut, P. M., Huang, W. et al. (2021). Comparing test sets with item response theory. *ACL-IJCNLP 2021*, 1141–1158. doi:10.18653/v1/2021.acl-long.92

**Software testing and case construction.**
- Aleithan, R. et al. (2024). SWE-Bench+: Enhanced coding benchmark for LLMs. arXiv:2410.06992
- Chen, T. Y., Cheung, S. C. & Yiu, S. M. (1998). Metamorphic testing: A new approach for generating next test cases. Technical Report HKUST-CS98-01, Hong Kong University of Science and Technology. arXiv:2002.12543
- Claessen, K. & Hughes, J. (2000). QuickCheck: A lightweight tool for random testing of Haskell programs. *ICFP 2000*, 268–279. doi:10.1145/351240.351266
- DeMillo, R. A., Lipton, R. J. & Sayward, F. G. (1978). Hints on test data selection: Help for the practicing programmer. *Computer* 11(4):34–41. doi:10.1109/C-M.1978.218136
- Gardner, M. et al. (2020). Evaluating models' local decision boundaries via contrast sets. *Findings of EMNLP 2020*. arXiv:2004.02709
- Gururangan, S. et al. (2018). Annotation artifacts in natural language inference data. *NAACL 2018*. arXiv:1803.02324
- Hughes, J. (2007). QuickCheck testing for fun and profit. *Practical Aspects of Declarative Languages (PADL)*, LNCS, 1–32. doi:10.1007/978-3-540-69611-7_1
- Hyun, S., Guo, M. & Babar, M. A. (2024). METAL: Metamorphic testing framework for analyzing large-language model qualities. *ICST 2024*. arXiv:2312.06056
- Just, R., Jalali, D., Inozemtseva, L., Ernst, M. D., Holmes, R. & Fraser, G. (2014). Are mutants a valid substitute for real faults in software testing? *FSE 2014*, 654–665. doi:10.1145/2635868.2635929
- Kuhn, D. R., Wallace, D. R. & Gallo, A. M. (2004). Software fault interactions and implications for software testing. *IEEE Transactions on Software Engineering* 30(6):418–421. doi:10.1109/TSE.2004.24
- Mirzadeh, I. et al. (2025). GSM-Symbolic: Understanding the limitations of mathematical reasoning in large language models. *ICLR 2025*. arXiv:2410.05229
- Northcutt, C. G., Athalye, A. & Mueller, J. (2021). Pervasive label errors in test sets destabilize machine learning benchmarks. *NeurIPS 2021 Datasets and Benchmarks*. arXiv:2103.14749
- Oren, Y., Meister, N., Chatterji, N., Ladhak, F. & Hashimoto, T. B. (2024). Proving test set contamination in black box language models. *ICLR 2024*. arXiv:2310.17623
- Ostrand, T. J. & Balcer, M. J. (1988). The category-partition method for specifying and generating functional tests. *Communications of the ACM* 31(6):676–686. doi:10.1145/62959.62964
- Perez, E. et al. (2022). Discovering language model behaviors with model-written evaluations. arXiv:2212.09251
- Poliak, A., Naradowsky, J., Haldar, A., Rudinger, R. & Van Durme, B. (2018). Hypothesis only baselines in natural language inference. \*SEM 2018. arXiv:1805.01042
- Yang, S. et al. (2023). Rethinking benchmark and contamination for language models with rephrased samples. arXiv:2311.04850
- Yoo, S. & Harman, M. (2012). Regression testing minimization, selection and prioritization: A survey. *Software Testing, Verification and Reliability* 22(2):67–120. doi:10.1002/stv.430
- Zhu, Y. et al. (2025). Establishing best practices for building rigorous agentic benchmarks. arXiv:2507.02825

**Reuse and optimization.**
- Blum, A. & Hardt, M. (2015). The Ladder: A reliable leaderboard for machine learning competitions. *ICML 2015*. arXiv:1502.04585
- Dwork, C., Feldman, V., Hardt, M., Pitassi, T., Reingold, O. & Roth, A. (2015). The reusable holdout: Preserving validity in adaptive data analysis. *Science* 349(6248):636–638. doi:10.1126/science.aaa9375
- Gao, L., Schulman, J. & Hilton, J. (2023). Scaling laws for reward model overoptimization. *ICML 2023*. arXiv:2210.10760
- Manheim, D. & Garrabrant, S. (2018). Categorizing variants of Goodhart's law. arXiv:1803.04585
- Recht, B., Roelofs, R., Schmidt, L. & Shankar, V. (2019). Do ImageNet classifiers generalize to ImageNet? *ICML 2019*. arXiv:1902.10811

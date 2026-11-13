# Twelve problems every agent eval has to solve

*Target design for aot-evals 2.0. Draft 4.*

You don't need statistics to build trustworthy evals. You need to recognize twelve problems, because
each one makes an eval say something that isn't true.

Every eval is an estimator with four parts ([estimators.md](estimators.md)): **what number it
estimates**, **which cases it draws**, **how wrong its grader is**, and **when it acts**. Each
problem below is what happens when one of those parts is left unstated, so they are grouped by
part. Each comes with one worked example and no formulas. The box under each one names the methods
that solve it, the rules in [estimators.md](estimators.md#10-the-rules-in-one-table) it explains, and
where [statistics.md](statistics.md) derives them. aot-evals does the math. Words like *use case*,
*catch rate* and *clean pass rate* mean what the [terms](estimators.md#terms) say.

| Part | Problems |
|---|---|
| **Estimand**: what number, for which decision | 1. Decide which mistakes matter · 2. A better part isn't a better agent · 3. Keep the test current |
| **Sampling design**: which cases, drawn how | 4. Test what your users actually ask · 5. Count the evidence, not the cases |
| **Measurement model**: how wrong the grader is | 6. Your grader is wrong sometimes · 7. Hold the whole eval to a person · 8. Run it more than once |
| **Decision rule**: when to act | 9. A clean run isn't a clean bill of health · 10. Compare case by case · 11. "No difference" isn't "no worse" · 12. Stop peeking |

All twelve use the same agent: **a support agent for an online store**. It answers about 1,000
requests a day:

| Kind of request | Per day | Share |
|---|---:|---:|
| Where's my order? | 700 | 70% |
| Start a return | 200 | 20% |
| Change my address | 80 | 8% |
| Refund me | 20 | 2% |

It can read orders and change addresses. Refunds go to a **refund subagent**, with its own prompt
and model, owned by a separate team. So the store has two evals: one for the whole support agent,
and one for the refund subagent on its own.

Each problem carries a **Picture** line: the diagram that would make it obvious at a glance.

---

## The estimand: what number, for which decision

### 1. Decide which mistakes matter

**The trap.** "Our pass rate is 91%."

**Worked example.** A bug makes refunds go wrong more often: they fail on 15% of requests instead of
5%. That's 2 more bad refunds a day out of 1,000 requests, and the overall pass rate moves from
91.0% to 90.8%. Nobody will notice 0.2 points. But each of those mistakes sends money out the door,
while a wrong delivery date costs one follow-up message. Say what each kind of mistake costs ($1 for
a wrong order status, $5 for a botched return, $20 for a wrong address, $50 for a bad refund) and
weight the score by share × cost: refunds now carry 23% of the score instead of 2%, and the same bug
moves it 2.3 points.

**The fix.** Before you measure, say how much each kind of mistake costs compared with the others
(equal is a fine answer, if it's true). Weight the score by it. A kind of request that matters but
is too rare to move the score, even weighted, gets a check of its own.

**Picture.** 1,000 dots, one per request, colored by kind. The 2 new bad refunds are circled. Beside
them, two gauges: the plain pass rate, which hasn't visibly moved, and the cost-weighted one, which
has.

> **Under the hood.** A weighted estimand, θ = Σ weight × pass rate, with weights from share × cost,
> so 1 − θ tracks the expected cost of failures. Decision theory for the cost of each kind of
> failure. Severity tagged on real failures (did it write, can it be undone, would anyone notice) to
> test whether the stated costs hold up. A blind-spot check: compare a use case's weighted effect with
> the smallest change the comparison can see. Weight sensitivity: does the verdict hold under other
> plausible costs? *Rules* 2, 20. *Statistics* §1.1, §1.2.

### 2. A better part isn't a better agent

**The trap.** "The refund team's new prompt cuts policy mistakes from 5% to 2% on the refund eval.
Ship it."

**Worked example.** The refund team wrote their cases by hand, and every one includes an order
number. In production, one refund request in five reaches the subagent without one, and the old
prompt asked the customer for it. The new prompt declines those requests instead. On its own eval,
the subagent improved. End to end, refunds that get resolved fall from 90% to 74%. With traffic
weights, the whole agent's score drops 0.3 points and nobody notices; with the cost weights from
problem 1, it drops 3.7.

**The fix.** Give an eval to each thing someone ships on its own: the whole agent always, and a
subagent with its own context when a team changes it separately. Draw the subagent's cases from the
requests it actually receives in production, not from requests someone imagined. And a change to a
part ships only when the whole agent is no worse too.

**Picture.** The agent diagram with its context boundaries: one eval around the whole system and one
around the refund subagent. The subagent's gauge goes up (95% → 98%) while the whole agent's refund
row goes down (90% → 74%).

> **Under the hood.** One estimand per eval: one unit, one population, one decision (validity as an
> interpretation for a use). Evals sit at context boundaries, where the input is a defined handoff
> that can be sampled and replayed. The subagent's sampling frame is the distribution of handoffs
> the orchestrator induces, drawn from end-to-end traces with inclusion probabilities. When a
> sub-score earns its own report (Haberman's added-value test). A non-inferiority test on the
> end-to-end eval for every part change, and a multiplicity correction when several evals gate it.
> *Rules* 1, 3, 4, 22. *Statistics* §1.3, §4.5, §4.6.

### 3. Keep the test current

**The trap.** "The eval still says 92%, but complaints are up."

**Worked example.** Returns pass 80% and everything else passes 95%. When the cases were drawn,
returns were 20% of traffic: 0.2 × 80% + 0.8 × 95% = 92%. After the holidays, returns are half of
all requests: 0.5 × 80% + 0.5 × 95% = 87.5%. The agent didn't change. The test describes last
quarter. The same thing happens when a provider updates the model behind the same name, when
someone edits the judge's prompt, or when a routing change sends the refund subagent different
requests. And as the eval grows, the cases that never fail cost time and money on every run.

**The fix.** Recheck the traffic mix on a schedule and after every routing change, and recompute the
score under the new mix. Re-measure a grader whenever it changes, against a small fixed set of
labeled runs. Watch reruns of the same build for drift. Prune bug-finding cases that never tell
versions apart, but only when the comparison can still see the same size of change afterward, and
never prune the randomly drawn cases.

**Picture.** Two stacked bars of traffic mix, before and after the holidays, each with the score it
implies, beside the one score the frozen eval keeps printing.

> **Under the hood.** Post-stratification reweighting. Control charts for drift, with limits from
> the variance components. Anchor-set equating across judge versions. The table of which change
> invalidates which number, and whether it is an expansion or a revision. For pruning:
> misclassification of "always-pass" at small k, item response theory, suite minimization under a
> coverage constraint, and optimal test assembly; never removing sampled cases, whose inclusion
> probabilities the estimate depends on. *Rules* 13, 25, 26. *Statistics* §1.4, §2.6, §3.8.

---

## The sampling design: which cases, drawn how

### 4. Test what your users actually ask

**The trap.** "We wrote 40 tough cases and it passes 70% of them, so it's a 70% agent."

**Worked example.** The 40 cases were picked *because* they're hard, so 70% says nothing about
real traffic. Draw 20 requests at random from last week instead: you'd expect about 14 order
lookups, 4 returns, 1 or 2 address changes, and maybe no refund at all. So one set can't do both
jobs. Hard cases find bugs. Random cases tell you how good the agent is. And neither set includes
"the order number doesn't exist" unless someone checks against a list of situations written
somewhere other than the cases themselves.

**The fix.** Keep two sets. A **bug-finding set** is stuffed with hard and rare cases. A
**quality set** is drawn at random from real requests, and it's the only one whose pass rate you
quote as quality. Draw rare kinds of request more often than their share so each has enough cases,
and weight them back down when you compute the score. Check what's covered against an outside list:
the help center's topics, the agent's tools, and situations like "not found", "ambiguous" and "not
allowed".

**Picture.** Two jars. One is filled by hand with the dark, hard marbles. The other is scooped at
random from the traffic stream. Each jar has its own pass rate printed on it.

> **Under the hood.** Elicitation vs estimation. Stratified random sampling with inclusion probabilities and the Horvitz–Thompson (Hájek)
> estimator; optimum allocation (Neyman's, with cost: weight × spread ÷ √cost) around each gated
> use case's minimum; a beta-posterior interval for small use cases. Quota sampling
> (hand-picking within a use case) is biased. Test blueprint and category-partition for coverage, and
> t-way covering arrays when the grid gets large. Mutation analysis for whether the set would catch
> a fault. Contrast sets, metamorphic relations, partial-input baselines and property-based shrinking
> to generate hard cases. Contamination screens for cases built from public sources. *Rules* 5, 6, 8,
> 10. *Statistics* §2.1–§2.3, §2.5.

### 5. Count the evidence, not the cases

**The trap.** "It won 24 of 30 cases."

**Worked example.** The 24 wins came from 4 templates, 6 near-copies each, and copies pass or fail
together. Counted as 24 separate wins against 6 losses, that's about 1 chance in 700 of happening
with no real improvement. Counted honestly as 4 templates against 6 losses, it's about 1 in 8.

**The fix.** Mark cases that share a source (a template, a trace or a fixture) so they count as one
piece of evidence. Spread cases across sources. Keep near-copies on the same side: a template in the
quality set can't also feed the bug-finding set.

**Picture.** 30 tiles, with the 24 wins grouped into 4 bundles of 6. The caption reads "4 pieces of
evidence, not 24".

> **Under the hood.** Design effect 1 + (m − 1)ρ and effective n. Sign flips per cluster (with 5 or fewer clusters, a ±1 sign flip can't reach 5%; Webb's six-point
> weights help, approximately); the cluster jackknife. Cochran's Q
> for shocks across a run, and an over-dispersion test across templates. Shared judges as a hidden
> cluster. *Rules* 9, 10. *Statistics* §2.4.

---

## The measurement model: how wrong the grader is

### 6. Your grader is wrong sometimes

**The trap.** "Our AI judge agrees with our reviewers 95% of the time."

**Worked example.** A reviewer labels 200 runs: 190 good and 10 bad. A judge that says "pass" to
everything agrees with the reviewer on 190 of 200, which is 95%, and it caught **none** of the 10
bad runs. So ask two separate questions. Of the bad runs, how many did it catch (its **catch
rate**)? Of the good runs, how many did it pass (its **clean pass rate**)? Each needs its own labels. If only 2 bad runs were labeled, "caught 2 of 2"
is consistent with a judge that catches anywhere from a third of failures to all of them.

The judge's error also distorts the rates it reports. Take 1,000 refunds, 30 of them really bad. The
judge catches 80% of those (24) and wrongly flags 10% of the good ones (97). It flags 121 runs, or
12%, when the real failure rate is 3%. And its mistakes cost you cases. To show that refunds go wrong less than 1 time in 20, a check
written in code needs about 120 cases. This judge needs about 860, because its false flags on good
refunds swamp the few real failures.

**The fix.** Measure each grader by what it catches and what it wrongly flags, on enough labels of
each kind. Correct the rates it reports for its known errors. Use code checks wherever code can
decide. Give each check one question. A judge that agrees with itself, or with another model,
hasn't shown that it's right.

**Picture.** A 2×2 grid of the 200 runs, judge verdict against reviewer verdict. The "bad runs the
judge passed" cell is highlighted, and an "agreement: 95%" label is crossed out.

> **Under the hood.** Diagnostic-test statistics: catch rate and clean pass rate (sensitivity and
> specificity), Wilson intervals per kind of label, and the Rogan–Gladen correction. Attenuation: a grader with J = catch + clean − 1 shrinks every real change by J, and costs about
> 1/J² as many cases near a 50% failure rate and far more for rare failures, which is how a floor on
> judge quality is set. A judge's threshold chosen from the cost of each error, not Youden's J; calibration
> of its probabilities (ECE, Brier); out-of-fold estimation. Reliability is not validity:
> self-consistency, cross-family agreement, position bias in pairwise grading, self-preference, and
> the Dorner ceiling on what a judge can save. An independent reference: a check never trusts the agent's own report. Label-error audits: a case whose expected answer nobody has checked stays out of the
> score. *Rules* 11–14, 17. *Statistics* §2.5, §3.1–§3.5, §3.8.

### 7. Hold the whole eval to a person

**The trap.** "Every check passed its calibration, so the eval is right."

**Worked example.** The eval has five judge checks, and each passes 90% of good runs. A good run has
to pass all five, which happens only 59% of the time (0.9 × 0.9 × 0.9 × 0.9 × 0.9), so 41 of every
100 good runs get failed by something. The eval also misses things: a reviewer fails a run because
the agent promised a refund it isn't allowed to issue, and no check looks for promises. People
disagree with each other, too. Two reviewers who agree on 90 of 100 runs can agree on **none** of
the failures, if all their agreement is on the good runs.

**The fix.** Have a person grade whole runs without seeing the checks. Measure how many of their
failures the eval catches and how many of their passes it passes. Give every disagreement a cause
and fix the check or the standard. Measure how well reviewers agree *on failures*, and write down
how each disagreement was settled so the standard doesn't drift. Combine the person's labels with
the eval's verdicts to estimate what a person would say about every run.

**Picture.** Five gates in a row that a good run has to get through, with 100 good runs entering
and 59 coming out the far end. Beside it, a reviewer's red pen on a run that every gate let through.

> **Under the hood.** The eval's own catch rate and clean pass rate, with a person as the reference
> standard: the measurement model the estimate and its power calculations use. ∏ clean pass, and
> correlated judge errors that break it. Agreement that holds up when most runs pass (Gwet's AC1,
> specific agreement) instead of Cohen's κ. Adjudication, latent-class models of reviewer error
> (Dawid–Skene), and criteria drift with a versioned standard. Prediction-powered inference (PPI++)
> for the person-anchored pass rate, with labels drawn by a queue, not picked (verification bias).
> *Rule* 15. *Statistics* §3.6.

### 8. Run it more than once

**The trap.** "74% yesterday, 81% today. The prompt fix worked."

**Worked example.** Run the same build twice with nothing changed. If each of 50 cases passes about
3 times in 4, the two runs differ by 10 points or more about 30% of the time. Users feel the same
randomness: at 75% per try, a customer who asks three times gets a good answer all three times only
42% of the time.

**The fix.** Run every case at least 3 times, and measure how much the score moves on its own
before you compare anything. Then spend the next budget wisely: more *cases* usually narrow the
answer faster than more *runs* of the same cases.

**Picture.** Ten runs of the same build plotted as dots on a 60–90% axis, scattered across about
15 points.

> **Under the hood.** Generalizability theory: between-case vs within-case variance, ICC, design
> effect and effective n (a G-study, then a D-study). pass^k for reliability, and the detection
> limits of flakiness at small k. Cluster-robust intervals with t(G − 1). *Rule* 16. *Statistics*
> §3.7.

---

## The decision rule: when to act

### 9. A clean run isn't a clean bill of health

**The trap.** "All 10 refund cases passed. Refunds work."

**Worked example.** Suppose the subagent actually gets 1 refund in 4 wrong. What are the odds all 10
cases pass anyway? 0.75 multiplied by itself ten times: about 6%, or 1 in 18. Unlikely, but you
can't rule it out. If it gets 1 in 5 wrong, all 10 pass 11% of the time. A quick rule: after *n*
clean cases, the true failure rate could still be as high as about **3 ÷ *n***. With 10 cases that's
around 26%, with 30 it's 10%, and with 100 it's 3%. To see a failure that hits 1 request in 20 at
least once, with 95% confidence, you need 59 cases, and that only works when code or a person does the grading: a judge that
sometimes flags good runs never returns a clean run, and needs far more (problem 6).

**The fix.** Decide first what the eval has to show (that refunds fail less than 1 time in 20, say)
and let that set the number of cases. Read a clean result as an upper limit, not as zero. A rare,
costly failure needs many cases, cases written to target it, or a check on every production run.

**Picture.** A curve of "the worst failure rate a clean run can hide" falling as cases go from 3 to
300, with 10, 30 and 100 marked.

> **Under the hood.** Case counts from the decision rule's power, multiplied by the grader's inflation factor. The zero-failure bound, 1 − 0.05^(1/n) (Hanley and Lippman-Hand's rule of three); detection probability
> 1 − (1 − p)^n per failure mode; improvement sized by flip rate (N ≈ 7.85·d/Δ²); regression guards
> sized by a tolerated drop. Floors shown with a non-inferiority margin, not a point estimate.
> Importance sampling with recorded weights when a rare failure's *rate* is needed. *Rule* 7.
> *Statistics* §4.1, §4.2.

### 10. Compare case by case

**The trap.** "Version B scores 5 points higher on 200 cases."

**Worked example.** Count what changed rather than the totals. Suppose change X fixed 10 cases and
broke none, and change Y fixed 30 and broke 20. Both are +10 cases, or +5 points. Now ask: if the
change did nothing, each case that moved would be a coin flip between "fixed" and "broken". Ten
fixes out of ten moves is like 10 heads in a row, about 1 chance in 500 either way: X is real. Thirty
of fifty happens 1 time in 5: Y could be noise. Y also broke 20 cases that worked yesterday, and
someone should read them.

Do the same with cost. "Cost per request went down" can just mean it gives up sooner. Divide by
*successful* requests.

**The fix.** Run both versions on the same cases, list what each one fixed and broke, and test the
difference case by case. A gain that blows the cost budget is a trade, not a win.

**Picture.** Two rows of 200 squares, A above B. Most pairs are the same color, and only the
squares that flipped are lit: 10 green for X, and 30 green plus 20 red for Y.

> **Under the hood.** Paired designs. The sign-flip permutation test on per-case deltas and its
> inverted interval; McNemar's mid-p on flips; flip rate d with SE √((d − Δ²)/N). Cost per successful
> task, medians and p90 with bootstrap intervals, and budgets as constraints in the decision rule.
> Operational failures (timeouts, rate limits) counted on their own, never as wrong answers. *Rules*
> 18, 24. *Statistics* §4.3, §4.4, §4.8.

### 11. "No difference" isn't "no worse"

**The trap.** "The cheaper model showed no significant difference. Ship it."

**Worked example.** On 50 cases, the cheaper model fixed 4 and broke 4, a net of zero. But with 8
cases moving, the data are just as consistent with the cheaper model being about 11 points worse,
or 11 points better. "Not significant" only meant the test couldn't tell. To show it's within 5
points at that rate of churn would take about 500 cases.

**The fix.** Every comparison should say the smallest difference it could have seen. When the claim
is "no worse", test that claim directly: the drop has to be shown smaller than a margin you choose
in advance.

**Picture.** An interval from −11 to +11 centered on zero, with a "no worse than −5" line that the
interval crosses.

> **Under the hood.** Power and minimum detectable effect, before the run and from the observed
> deltas after it. Non-inferiority (or equivalence) testing with a pre-set margin, the standard
> design for "cheaper and no worse". The same test guards a blind use case (problem 1) and checks a
> part change against the whole agent (problem 2). *Rule* 19. *Statistics* §4.5.

### 12. Stop peeking

**The trap.** "We kept labeling until the eval cleared 85%." Or: "the optimizer tried 2,000
prompts, and the best scores 9 points higher." Or: "we checked ten kinds of request and returns got
significantly worse."

**Worked example.** Say the eval really catches 80% of bad runs, short of an 85% bar. Check it once
on 15 labels and it clears the bar by luck 40% of the time. Check after every 5 labels and stop as
soon as it clears, and it clears 56% of the time. Every look is another lottery ticket. A prompt
search is the same thing at scale: the best of 2,000 tries is partly the luckiest on *these* cases.
So is checking many kinds of request at once: with ten of them, each with a 1-in-20 chance of a
false alarm, 40% of the time at least one "significantly" changes when nothing did.

**The fix.** Decide how many labels you'll collect before you look. Tune on one set and confirm on
a held-out set you check once. Before making a new claim, get fresh labels. Adjust for the number of
things you check before acting on one. Never let the agent see the cases.

**Picture.** A running catch rate wandering around 80% as labels arrive. Every time it pokes above
the 85% line there's a "stop here?" flag, and the true 80% is drawn as a dashed line.

> **Under the hood.** Optional stopping and always-valid sequential intervals; adaptive data
> analysis, the reusable holdout and the Ladder; overoptimization of proxy graders (Goodhart).
> Benjamini–Hochberg for many gates. Isolation of the cases from the agent. *Rules* 21, 22, 23.
> *Statistics* §4.6, §4.7.

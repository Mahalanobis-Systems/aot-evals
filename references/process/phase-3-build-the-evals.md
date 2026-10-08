# Phase 3 — Build the evals

Steps 8–12. Goal: a calibrated eval suite per agent, organized by category.

## 8. Define trace categories

Sort each agent's traces into **categories**: the distinct kinds of job the
agent does. Each category gets a **worth**: how much it matters when that kind
of trace goes wrong. Evals are organized by category: sampling, checks, cases
and scores are all per category.

Example, an email scheduling agent:

| Category | What happened | Worth | Simple? |
|---|---|---|---|
| Nothing to do | No new email needs handling | Low: the only failure is acting when it shouldn't | Yes |
| Suggest times | A thread needs meeting times proposed | Medium: wrong or clashing times cost a round trip | No |
| Confirm and book | A time was agreed; confirm it and create the invite | High: a wrong or missing invite costs the meeting | No |

- **Heuristics first.** Pick out the simple categories with code rules on
  the trace before any model is involved: a scheduled check where no new
  message or email arrived, a sweep that found no new items. Base each rule
  on the input (was there anything new?), not only on what the agent did, so
  a run that missed a new email isn't filed as "Nothing to do".
- **Flag simple categories.** A simple (degenerate) category is one where the
  right behavior is trivial and a heuristic can check it on every run.
  Downstream it gets 3 spot-check examples instead of 10 (step 9), and its
  check runs over every trace in the category (step 10).
- **Model for the rest.** Have a model group the remaining traces by what the
  agent was asked to do and what it did, using the usage patterns from
  step 5.
- The agent's owner confirms, merges, renames, sets the simple flag and
  assigns worth.
- Every trace gets exactly one category. Keep a small "Other" category and
  revisit it after review.
- **Check the drafts on the traces.** A code-only script labels every run with
  the drafted rules and counts each category against its target. Fix drafts
  where rules misfire or a category can't reach its target.
- **Cross-check every simple-category rule against an independent labeler.**
  A "nothing new" rule must exclude runs where the input couldn't be read: a
  broken connection also reports zero new items, and that is the failure the
  category would otherwise hide.
- **Watch for filters in front of the agent.** If a gate (a "should I respond"
  check) drops messages before the agent runs, categories such as "not
  addressed" collapse. Count gate-only runs separately and look at what the
  gate dropped: silent failures hide there.
- **Cost matrix.** For each category, price each kind of failure: what an
  incorrect result, a claim that wasn't carried out, no response, a partial
  result, and so on cost the user (None/Low/Medium/High). Worth is the headline;
  the matrix says where within a category the damage is (an "Incorrect" booking
  costs more than a slow one). Reviewers then don't judge impact trace by trace:
  it is set from the matrix, and they override only unusual cases. Overrides
  show where the matrix is wrong.
- Output: a category list per agent, with a definition, an example trace, a
  worth, a simple flag and a cost-matrix row for each, plus the heuristic behind
  each simple category.

## 9. Review at least 10 traces per category

A person reviews at least 10 traces from each category and records, for each:
its category, the errors in it, and the quality of the outcome. The review is
about judging outcomes; finding the patterns across traces is step 10.

- **Sampling: categories set the number.** At least 10 traces per category,
  3 per simple category, picked at random within the category from the
  agent's stable window (step 1). A category that is 1% of runs gets the same
  10 as one that is 90%: the rare categories are usually where the worth is.
  An agent with three categories, one of them simple, gets 23 traces.
- **Rare categories.** Fewer than 10 runs in the stable window: extend back
  across earlier versions and record each trace's version. Still fewer: take
  all of them and note it.
- First question for every conversational agent: was the message addressed
  to the agent at all?
- Tool: a trace review tool. AI drafts
  every field; the reviewer confirms or changes each one. It must show the
  data the agent worked from, not just its API calls, or outcomes can't be
  judged.
- Review surfaces production bugs. Report each to the agent's owner as it is
  found, separately from the eval work. When one trace looks wrong, check the
  whole pattern in the pulled data (every similar run, what happened next)
  before proposing a fix: one odd trace is often a pattern, and the fix
  may belong in the platform rather than the agent.
- Output: at least 10 reviewed traces per category (3 per simple category),
  each with category, errors and an outcome-quality score.

## 10. Analyze errors, define checks, build cases

Turn the reviews into evals. This step is programmatic, with the owner
confirming the result.

- **Error analysis.** A model clusters the reviewers' error notes and tags
  into a failure taxonomy per category, with counts, weighted by worth.
- **Checks.** Each failure mode becomes one binary check. Prefer code checks
  on end state (diffs, rows, events, posts, side effects outside scope). Keep
  LLM-judge checks narrow: one pass/fail question each, reasoning before
  verdict. Separate cross-agent checks (responded when addressed, finished
  within the time budget, claimed actions match actual changes, approvals
  acted on) from agent- and category-specific ones.
- **Simple categories.** Their heuristic becomes a code check run on every
  trace in the category, not only the sampled ones.
- **Cases.** The reviewed traces become the agent's cases, with the
  confirmed review as the expected outcome. Freeze inputs (message, thread,
  tool/state snapshot) and scrub secrets and personal data before committing.
- Output: failure taxonomy, check spec and versioned case files, per agent
  and category.

## 11. Calibrate judges

Use the reviewed traces (step 9) as the human labels. Measure agreement (true-positive and
true-negative rates, not just accuracy). Iterate the judge prompt until it
agrees; re-check after any judge change. Use a different model from the
agent under test where it agrees as well.

- Output: judge prompts with measured agreement.

## 12. Run the baseline

Grade each case 3–5 times. Report pass rate and pass^k (all k runs pass) per
check and per agent.

- Output: the baseline scorecard.

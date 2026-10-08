# The process

How to go from agents running in production with no evals to a first eval
suite for each of them. Deployment-agnostic: this folder can be copied
elsewhere unchanged.

Every agent gets **at least 10 examples per category** (3 for simple
categories): the reviewed traces become its first eval cases and the labels
its judges are checked against.

| File | Covers |
|---|---|
| [principles.md](principles.md) | The six rules the steps follow |
| [phase-1-understand-the-system.md](phase-1-understand-the-system.md) | Steps 1–4: inventory the agents (with version history and stable window), map infrastructure and traces, measure volume, catalog existing evals |
| [phase-2-understand-the-usage.md](phase-2-understand-the-usage.md) | Steps 5–7: characterize usage from cheap sources, survey public benchmarks, pull raw traces |
| [phase-3-build-the-evals.md](phase-3-build-the-evals.md) | Steps 8–12: define trace categories, review at least 10 traces per category, analyze errors into checks and cases, calibrate judges, baseline |
| [agent-properties-framework.md](agent-properties-framework.md) | Six questions about an agent (verifiable? happy with performance → cost or latency? what is drift? sandbox possible? if not? subjective → what criteria?) and the decision procedure that picks its eval strategy |

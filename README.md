<img src="brand/agent-optimization-logo.png" alt="AOT, the Agent Optimization Toolkit" width="96" align="right">

# AOT Evals

Create golden records, safe testing environments, and repeatable optimization loops to improve
cost, quality, and speed of your agent.

<p align="center">
  <img src="docs/images/discovery-overview.png" width="800"
       alt="A discovery report for an example enterprise data pipeline agent: the bottom line, three key numbers, and the four pillars (business context, agent architecture, safe testing environment, golden test cases), each with what discovery found and its status. Illustrative example.">
</p>

A Claude Code plugin from Mahal Systems, part of **AOT, the Agent Optimization Toolkit**. It works
on **your own agent**, in your own repository. There's no service and no account, and nothing is
installed into your project.

## How to run

You need [Claude Code](https://code.claude.com), `git`, and [uv](https://docs.astral.sh/uv/)
(or Python 3.11+ with PyYAML). Install the plugin:

```bash
claude plugin marketplace add Mahalanobis-Systems/aot-evals
claude plugin install aot-evals@aot-evals
```

Or, inside Claude Code: `/plugin marketplace add Mahalanobis-Systems/aot-evals`, then
`/plugin install aot-evals@aot-evals`. Restart Claude Code afterwards.

Then open Claude Code in your agent's repository and run the one command to remember:

```
/aot-evals:start
```

The first time, it runs Assess: it finds your agents, asks which one to test and three
questions about it, and writes a discovery report like the one above in about five minutes.
Run `/aot-evals:start` again whenever you want to know where things stand: it names the phase
(Assess, Build or Judge) of each eval, how far its number can be trusted, what changed since
its baseline, and carries on with the next step, stopping for your review at each checkpoint.

**Try it on a toy agent first (a few minutes).** In Claude Code, in any empty folder, ask:
*"Run `aot-evals demo` and show me what it made."* It builds a toy online store's support agent
and its refund subagent with an eval each, runs both baselines, then a change to the subagent that
improves its own eval and breaks refunds end to end, and decides on it. Nothing calls a model or a
network service.

Judges default to a free System One model (Jev, through OpenCode Zen) that needs no key but
allows about 250 calls a day; set `ANTHROPIC_API_KEY` to use Claude as a judge. See
[references/judge-backends.md](references/judge-backends.md). If something doesn't work, ask
Claude to run `aot-evals doctor`.

**Updating.** Releases are listed in [CHANGELOG.md](CHANGELOG.md) and on the
[releases page](https://github.com/Mahalanobis-Systems/aot-evals/releases).

```bash
claude plugin marketplace update aot-evals
claude plugin update aot-evals@aot-evals     # then restart Claude Code
```

Or turn on auto-update for the `aot-evals` marketplace in `/plugin` → Marketplaces.

## Overview

Good evals give you tests that predict how your agent will do in production, and show what to
fix next. They rest on four things, and AOT Evals checks each one for your agent:

| | What it means | What we look at |
|---|---|---|
| **Business context** | Why the agent exists, who relies on it, and what it costs when it answers wrong. | Goals · stakes · intent |
| **Agent architecture** | Its code, prompts, models and tools, its production setup, and the traces of real runs. When the setup and the traces disagree, we trust the traces. | Code · setup · traces |
| **Safe testing environment** | Runs that can't touch real people, data or money, and are fast and cheap to repeat. | Safe · secure · efficient |
| **Golden test cases** | Examples drawn from real runs, grouped into the handful of task types the agent actually handles. | Test cases · task types |

## How it works

An eval exists to make a decision, so aot-evals treats each eval as a statistical estimator with
four parts written down in one file, `eval.yaml`: the **estimand** (what number, about what, for
which decision), the **sampling design** (which cases, drawn how), the **measurement model** (how
wrong the grader is) and the **decision rule** (when to act). None of it is new: each part comes
from a field that solved it long ago, from survey sampling to diagnostic testing to clinical
trials ([docs/estimators.md](docs/estimators.md)). You meet them as three phases, each ending in
something handed to the next group of people.

**Assess (about 5 minutes): the estimand.** AOT Evals scans your repository for agents and asks
which one to test. It asks three questions: what decision the tests will drive, whether some
mistakes are much worse than others, and what a change should have to show before it ships. Then
four reads run side by side: how the agent works and where its evals go (one end to end, plus one
per subagent a team ships on its own), its tools and where it could be tested safely, its traffic
and the kinds of request it handles, and what data it touches and how private it is. You get a
plain-English discovery report.

**Build (half a day for the first pass): the design, the checks and the decision rule.**
Engineering wires the agent to the contract, draws a quality set at random from real traffic
(and writes hard cases to find bugs, checked against a coverage list), puts one counted check on
each way the agent can fail, writes down the decision rule with the owner, runs the baseline, and
hands the grader application to the people who will label. Nothing refuses to run because
something is missing: a missing field nulls the numbers that depend on it, with the reason.

**Judge (ongoing): the grader's error rates.** In the grader application (`aot-evals serve`),
product owners, experts or end users label whole runs pass or fail, the eval is held to their
verdicts (its catch rate and clean pass rate), AI judges are measured on their labels, and their
rulings become rules. When something changes (the agent, a use case, a check, a judge, the traffic
mix), `aot-evals status` names the change and the way back.

Under the hood:

- **A weighted headline.** θ̂ is the pass rate weighted by each use case's share of traffic and
  the cost of a failure in it, with the per-use-case table beside it and an interval on both.
- **Two pools:** a bug-finding set picked by hand to find failures, and a quality set drawn at
  random with each case's inclusion probability. Only the second is a rate.
- **Case counts from the decision rule's power**, with the judges' errors counted: a judge whose
  mistakes would cost more than twice the cases of a code check doesn't count.
- **Paired, clustered comparisons** of a changed agent, and non-inferiority tests for "no worse";
  a component change ships only when the whole agent shows no regression too.
- **A fixed `report.json` schema** (`aot-evals/report@2`), which Claude renders into a local HTML
  report written for the question being asked.
- **A local catalog of over 350 public agent benchmarks** ([references/benchmarks.md](references/benchmarks.md)).
  Assess matches your agent against it without a web search, and says what each fit is good for:
  a grading design, a case template, a sandbox design or a baseline number. The matches also set
  the situations (unanswerable, ambiguous, forbidden, multi-turn, …) the bug-finding set should
  reach. Cases still come from your own traffic, never from a benchmark.

The reference for every command, file and gate is [docs/method.md](docs/method.md); why each rule
holds is in [docs/problems.md](docs/problems.md) (by worked example) and
[docs/statistics.md](docs/statistics.md) (the derivations). Coming from 1.x? `aot-evals migrate
--to 2` converts a suite; see [CHANGELOG.md](CHANGELOG.md).

<details>
<summary><b>What ships</b></summary>

| Part | Where |
|---|---|
| Skills: `start` (the one to remember: says where things stand, runs Assess, and carries on), `build` (engineering: the design, the checks, the decision rule, the baseline), `judge` (graders: the grader application, agreement, judges), `report`. All but `report` appear in the `/` menu | [skills/](skills/) |
| `aot-evals` CLI: the deterministic half (the eval spec, import, plan and draw, screening, runs, labels, calibration and reliability, operational counters, comparisons and decisions, `report.json`) | [bin/aot-evals](bin/aot-evals), [src/aot_evals/](src/aot_evals/) |
| The evals the plugin keeps in your repository, `evals/agents/<agent>/<eval>/` | [docs/method.md §4](docs/method.md#4-files); templates in [src/aot_evals/templates/evals/](src/aot_evals/templates/evals/) |
| Case, code-check and judge templates | [templates/](templates/) |
| The method's structure, its twelve problems and its statistics | [docs/](docs/) |
| Reference material: sourced literature findings, the agent contract, judge backends, the benchmark catalog | [references/](references/) |
| The grader application (`aot-evals serve`) | [src/aot_evals/serve.py](src/aot_evals/serve.py) |
| A toy agent with two finished evals (`aot-evals demo`) | [examples/store/](examples/store/) |
| Banner mod: draws the AOT EVALS banner in the terminal when `aot-evals start` runs | [hooks/](hooks/) |
| Brand: the AOT logo, the embedded fonts (SIL OFL 1.1), and the rules every HTML report follows | [brand/](brand/) |

</details>

<details>
<summary><b>The CLI</b></summary>

The skills drive the CLI for you, but you can run it directly in a Claude Code session. With
several agents in one repository, pass `--agent NAME` to every command.

```bash
aot-evals demo [DIR]                             # the online store: two evals, both baselines, a change decided
aot-evals doctor                                 # check the environment
aot-evals build [--run]                          # create the evals from the discovery report; --run the baselines
aot-evals --eval ID init [--component NAME]      # create one eval folder with its eval.yaml
aot-evals status                                 # the phase, each eval's trust, what changed, what's next
aot-evals validate                               # every missing or invalid field of each eval spec
aot-evals import traces.jsonl --source ... --query ... --window ...   # a frame to draw from
aot-evals --eval ID handoffs                     # a component eval's frame, from the end-to-end traces
aot-evals ops --export <id> --field cost_usd=... # operational costs, before any label
aot-evals run --purpose smoke --question "..."   # the agent runs end to end
aot-evals --eval ID plan --write                 # case targets per use case, from the decision rule
aot-evals --eval ID draw                         # the seeded random draw of the quality set
aot-evals screen; aot-evals screen --read-by NAME --case ID
aot-evals --eval ID run --purpose baseline       # k from the spec (judges run with their primary backend)
aot-evals run ... --pause-every 20 --pause-seconds 900   # pace a rate-limited runtime
aot-evals --eval ID serve --open                 # the grader application: label, rule, triage, rules, judges
aot-evals agreement label queue --changed        # label only what the last change moved
aot-evals agreement                              # the eval held to people
aot-evals label queue --judge J --open; aot-evals label import --judge J --csv ...
aot-evals calibrate --judge J                    # catch and clean pass rates per backend
aot-evals reliability --judge J --backend A --backend B
aot-evals --eval ID run --purpose candidate --variable model=...   # a changed agent
aot-evals --eval ID compare                      # the paired comparison and the decision
aot-evals coverage                               # the bug-finding set against the coverage list
aot-evals --eval ID report                       # <eval>/report/report.json
aot-evals activity --open                        # the live activity log (every command logs itself)
aot-evals log "..." [--kind finding|decision|question]   # add to it
aot-evals migrate --to 2 [--dry-run]             # convert a 1.x suite
```

Sequential looks, a reusable holdout for optimizers, drift monitoring and online evaluation are
described in the method but not yet computed ([docs/method.md §13](docs/method.md#13-not-in-20)).

</details>

## Telemetry

AOT Evals sends pseudonymous usage telemetry so we can see how many teams use it and how far they
get: a random local install id, the milestone reached (the assessment started, discovery report written,
a checkpoint at a gate, a report built), the gate id, the version, your OS name and a timestamp.
It **never** sends your code, agent, repository, cases, answers, file paths or IP address. A
notice is shown before the first event, and it's off whenever Claude Code's own telemetry is off,
on Bedrock, Google Cloud and Foundry, and in CI. See exactly what would be sent:

```bash
aot-evals telemetry show
```

Turn it off with `aot-evals telemetry off`, `AOT_EVALS_TELEMETRY=0` or `DO_NOT_TRACK=1`. Details,
retention and how to have your data deleted: [SECURITY.md](SECURITY.md#telemetry).

Separately, AI graders send the case and the agent's answer to the judge backend you use, by
default the free System One model on OpenCode Zen. Your code, traces, cases and reports stay in
your repository.

## Contributing

Feedback, bug reports and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). To
report a security problem, see [SECURITY.md](SECURITY.md).

Releases follow [Semantic Versioning](https://semver.org/). Every user-visible change is noted
under `## Unreleased` in [CHANGELOG.md](CHANGELOG.md). To release, a maintainer runs
`python3 scripts/release.py X.Y.Z`, which sets the version everywhere it lives and moves the
changelog notes under the new version, then merges that as a pull request. On merge, a GitHub
Action tags the commit `aot-evals--vX.Y.Z` and publishes a GitHub release. The marketplace
installs the plugin from that tag, so users only ever get released code. The full process is in
[CONTRIBUTING.md](CONTRIBUTING.md#releasing).

```bash
uv run --no-project --python 3.11 --with pyyaml --with pytest env PYTHONPATH=src python -m pytest -q
uvx ruff check src tests scripts
claude --plugin-dir .          # run Claude Code with your working copy of the plugin
AOT_EVALS_LIVE=1 uv run --no-project --python 3.11 --with pyyaml --with pytest env PYTHONPATH=src \
  python -m pytest -q tests/test_live_systemone.py   # opt-in: six free calls to Jev on OpenCode Zen
```

## The agent contract

Your agent runs as a command; framework, language and model provider don't matter. Each test
case arrives as one JSON object on stdin, and the agent prints one JSON object to stdout: its
answer, plus optional usage (tokens, cost, tool calls), the model ids it used, a trace id and an
outcome code. Two optional hooks let checks grade what the agent actually changed: `seed` puts
the world into the case's start state before each attempt, and `observe` prints the world's
state before and after. The full contract is in
[references/agent-contract.md](references/agent-contract.md).

## License

[Apache License 2.0](LICENSE). The bundled fonts are under the SIL Open Font License 1.1, and the
Mahal Systems and AOT names and logo are trademarks; see [NOTICE](NOTICE).

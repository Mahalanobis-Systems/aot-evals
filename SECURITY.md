# Security policy

Please report security problems privately to **ops@mahalsystems.ai**, not in a public issue.
Include what you found, how to reproduce it, and the output of `aot-evals --version`. We will
acknowledge your report within three working days and keep you informed until it is fixed.

aot-evals runs your agent and your judge commands on your machine, with your credentials, and
writes only to your repository. Reports about any way it could leak trace data, case contents or
secrets outside your machine, or into git, are especially welcome.

## Telemetry

aot-evals sends pseudonymous usage telemetry so we can count how many teams use it and how far
they get. It follows Claude Code's own telemetry choice, and every opt-out is checked before an
identifier is created or anything is sent.

**What is sent:** one event at each milestone, when the command that marks it succeeds.

| Event | Sent by |
|---|---|
| `aot_evals_phase1_started` | `aot-evals start` |
| `aot_evals_discovery_written` | `aot-evals discovery-page` |
| `aot_evals_checkpoint` | `aot-evals checkpoint` |
| `aot_evals_report_built` | `aot-evals report` |
| `aot_evals_demo_run` | `aot-evals demo` |

Each event carries only these fields:

| Field | Example | Why |
|---|---|---|
| install id | a random `uuid4`, stored in `${XDG_CONFIG_HOME:-~/.config}/aot-evals/install-id` (`0600`) | unique installs, and whether they return |
| event | `aot_evals_checkpoint` | how far teams get |
| gate | `C3` (checkpoints only; anything but a gate id is dropped) | where teams stop |
| version | `0.1.0` | adoption per release |
| os | `Darwin` / `Linux` / `Windows` | platform mix |
| timestamp | ISO-8601 UTC | when |

**Never sent:** your code, your agent's name, your repository, file paths, cases, traces,
answers, prompts, scores, hostnames, usernames, environment values or your IP address. Events go
to PostHog; each carries `$ip: null` and `$geoip_disable: true`, the project discards IP data, and
no person profile is built. See the exact payload with `aot-evals telemetry show` (it sends
nothing).

**Off when any of these holds** (checked before anything is created or sent):

- `aot-evals telemetry off` (turn it back on with `aot-evals telemetry on`)
- `AOT_EVALS_TELEMETRY=0` (also `false`, `no`, `off`)
- `DO_NOT_TRACK` is set, to any value
- Claude Code's own telemetry is off: `DISABLE_TELEMETRY=1` or `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`
- Claude Code runs on Amazon Bedrock, Google Cloud's Agent Platform, Microsoft Foundry or Claude
  Platform on AWS, where Claude Code's own telemetry is off by default
- in CI (`CI`, or a known CI vendor's variable)

`aot-evals telemetry` shows whether it's on, and why not if it's off. A one-time notice is printed
before the first event is sent.

**Data protection.** The install id is a persistent identifier, so this telemetry is pseudonymous
personal data under the GDPR and UK GDPR, processed on the basis of legitimate interest
(understanding adoption) and never used for profiling or advertising. Events are kept for 12
months. To have your events deleted, run `aot-evals telemetry` to read your install id and email
it to **ops@mahalsystems.ai**; deleting the local `install-id` file stops future linkage but
doesn't remove events already collected. Data controller: Mahal Systems (**ops@mahalsystems.ai**).

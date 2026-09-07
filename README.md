# Kira SDLC

**From a request or production signal to a checked pull request—with humans in control.**

Kira investigates Grafana alerts, CI failures and deployment failures, plans changes, implements approved scope and runs isolated checks. You approve the plan, review the code and decide when to merge and deploy.

[Get started](#get-started) · [Operations](docs/operations.md) · [Architecture](docs/architecture.md) · [Security](docs/security-model.md)

## How it works

| Step | Kira | You |
| :--- | :--- | :--- |
| **1 · Investigate** | Reads the issue or incident, gathers configured evidence and pins a source revision. | Describe the outcome or configure trusted signal sources. |
| **2 · Plan** | Publishes scope, acceptance criteria and a proposed approach. | Review and approve the exact plan. |
| **3 · Build** | Applies scoped changes, runs Docker checks and performs an independent model review. | Clarify requirements when needed. |
| **4 · Review** | Opens a PR and handles authorized revision requests. | Review the diff and merge when checks pass. |
| **5 · Verify** | Evaluates configured evidence for the deployed revision. | Deploy through your existing release process. |

> **A plan is not permission to implement. A merge is not proof of deployment.**
> Kira never approves its own work, merges a PR or deploys on your behalf.

## Connected workflows

| Input | What Kira does |
| :--- | :--- |
| [Grafana alerts](integrations/grafana/README.md) | Investigates Loki evidence and source code; proposes a fix or justified Terraform alert tuning |
| [CI failures](integrations/ci/README.md) | Reads failed jobs and logs; distinguishes application regressions from CI configuration problems |
| [Deployment failures](integrations/deployments/README.md) | Investigates ArgoCD sync/health failures; proposes remediation without touching the live cluster |
| GitHub issues | Plans features, bugs, maintenance and migrations |

**One controller, one approval gate.** Integrations collect signals; they do not run separate coding agents or open tuning PRs. Alert rules, workflow files and application code all require an approved plan, scoped checks and human PR review.

## Work with Kira

### Open an issue

Describe what should change, what must stay unchanged and how you will judge success. Use one task-type label: `feature`, `bug`, `maintenance`, `migration` or `incident`.

### Review the plan

Kira posts a readable plan with an acceptance checklist and an exact approval command. After reviewing it, post that command yourself:

```text
/sdlc approve RUN HASH
```

Implementation starts only after the controller verifies your identity, repository permission and specification hash.

### Review the pull request

Inspect the diff and CI results. Request changes through GitHub reviews; merge only when you are satisfied. Status, cancellation and recovery commands are documented in [Operations](docs/operations.md#github-controls).

## Get started

Run the installer **on your always-on service host**, with Python 3.11+, an installed and authenticated [Hermes runtime](https://hermes-agent.nousresearch.com), Git, GitHub CLI, OpenSSL and Docker. The included [Linux playbook](provisioning/playbook.yml) can provision that host from your workstation.

```bash
docker pull python:3.12-slim
python3 scripts/install-sdlc.py \
  --project OWNER/REPO \
  --source /absolute/path/to/checkout \
  --approver YOUR_GITHUB_LOGIN
```

The installer creates private configuration, a Hermes skill and a service definition. **New installations cannot publish until you explicitly configure and enable them.**

Complete the [setup guide](docs/operations.md#installation): install a repository-scoped GitHub App, configure trusted checks and approvers, connect signed webhooks, and enable required CI and branch protection.

## Safety by design

- **Explicit authority.** Approval is bound to the exact plan and checked against live GitHub permissions.
- **Tool-free proposals.** Hermes returns structured changes; the controller owns file writes and GitHub actions.
- **Isolated checks.** Repository checks run without credentials or network access in constrained Docker containers.
- **Durable state.** SQLite records jobs, approvals and evidence; retries are bounded.
- **Evidence-based outcomes.** Missing deployment or production evidence never becomes a success result.

See the [security model](docs/security-model.md) for trust assumptions and limits.

## Deployment

Kira runs as a background service. GitHub is its planning, approval and review interface.

Kira runs on the **always-on Surface server** as the `hermes-sdlc` systemd service, alongside its public ingress. Nginx connects directly to the loopback controller; no Mac session or reverse SSH tunnel is required.

The installation uses the **Kira SDLC GitHub App** (`kira-sdlc[bot]`), signed webhooks, durable SQLite state and required CI. Linux service and ingress provisioning are included under `provisioning/`; see [deployment details](docs/operations.md#deployment).

## Develop

```bash
python3 -m unittest discover -s tests -v
```

GitHub Actions runs the checks on Python **3.11, 3.12 and 3.13**. The repository also includes a small example service and labeled model-evaluation scenarios.

| Directory | Purpose |
| :--- | :--- |
| `hermes_sdlc/` | Controller, GitHub App authentication, durable state and runtime adapters |
| `integrations/` | Grafana Terraform, ArgoCD notifications and native incident setup |
| `scripts/` | Installation and GitHub provisioning |
| `provisioning/` | Linux service and shared-ingress deployment |
| `tests/` | Authorization, lifecycle, recovery and provisioning checks |
| `evaluations/` | Model-evaluation scenarios |
| `examples/` | Release-readiness example service |
| `docs/` | Operations, architecture and security |

## License

[MIT](LICENSE). Hermes is a separate runtime dependency.

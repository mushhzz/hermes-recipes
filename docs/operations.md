# Operating Kira SDLC

[Overview](../README.md) · [Architecture](architecture.md) · [Security](security-model.md)

## Installation

Install and authenticate Hermes first. Kira requires Python 3.11+, Git, GitHub CLI, OpenSSL and Docker. Inference uses the installed Hermes virtual environment; the controller itself has no pip dependencies.

```bash
docker pull python:3.12-slim
python3 scripts/install-sdlc.py \
  --project OWNER/REPO \
  --source /absolute/target-checkout \
  --approver YOUR_GITHUB_LOGIN
```

The installer preserves existing configuration and creates these files when needed:

| Path | Purpose |
| :--- | :--- |
| `~/.hermes/sdlc/config.json` | Trusted controller and project configuration |
| `~/.hermes/sdlc/{github,deployment}.secret` | Separate private webhook secrets |
| `~/.hermes/sdlc/lifecycle.sqlite3` | Durable state, created by the service |
| `~/.hermes/skills/software-development/hermes-sdlc/SKILL.md` | Kira integration instructions for Hermes |
| `~/.hermes/sdlc/` service definitions | launchd on macOS; user systemd on Linux |

**New projects start with publication disabled.** Installation does not start another listener or change existing credentials. Configure real project checks and file scope before enabling writes.

## Project configuration

Project settings live under `projects["OWNER/REPO"]` in the private configuration. Example:

```json
{
  "source": "https://github.com/OWNER/REPO.git",
  "base_branch": "main",
  "approvers": ["authorized-human"],
  "publish": false,
  "bot_login": null,
  "allowed_paths": ["src/", "tests/", "README.md"],
  "sandbox_image": "python:3.12-slim",
  "checks": [
    {"name": "tests", "argv": ["python", "-m", "unittest", "discover", "-s", "tests"], "timeout_seconds": 120}
  ],
  "required_ci_checks": ["Lifecycle verification"],
  "environment": "production",
  "observation_seconds": 3600,
  "production_checks": []
}
```

Use a canonical GitHub HTTPS source for fresh remote checkouts. A local source must exist. Configuration, state and credentials must remain outside target checkouts.

Install test dependencies into a trusted, preferably digest-pinned image. Checks have no network and cannot download packages. Images must provide `/bin/sh` and `cp`. Current limits include a 256 MiB work tmpfs, 64 MiB temporary tmpfs, 512 MiB memory, one CPU and 128 PIDs.

Docker startup failures are infrastructure failures, not requests to rewrite application code. On macOS, ensure Docker can access the private state directory used for staging.

## GitHub App and repository policy

### Configure the App

Register a GitHub App and install it only on the intended repositories.

| Permission | Access |
| :--- | :--- |
| Contents, issues, pull requests | Write |
| Actions, checks, deployments, metadata | Read |
| Administration | None |

Store the private key outside the checkout, owned by the service user with mode `0600`. Add a root-level `github_app` object containing the real `app_id`, `installation_id`, `slug`, `repository_ids` and absolute `private_key_file` path.

The controller verifies `/app`, derives `<slug>[bot]`, and mints repository-scoped installation tokens. Tokens remain in memory and renew before expiry. An explicitly configured `bot_login` must match that derived identity. Human approvers must be separate accounts.

The administrator's `gh` authentication is separate: provisioning uses operator credentials, not the App token. Never paste a key or token into a policy file, issue or command argument.

### Provision and activate

`provisioning/github.json` declares the repository, labels, public webhook URL, required workflows/checks and desired ruleset enforcement.

```bash
python3 scripts/provision-github.py
python3 scripts/provision-github.py --apply
```

The default invocation previews changes. Apply only with operator authorization. Existing labels and unrelated hooks/rulesets are preserved; active protection cannot be disabled through bootstrap.

For a new installation:

1. Begin with `enforcement: "disabled"` while publishing initial source and CI.
2. Configure a real public HTTPS URL ending in `/webhooks/github`. A proxy prefix such as `/kira/webhooks/github` is supported.
3. Apply the webhook and verify GitHub's actual delivery result.
4. Verify the App installation and repository access. Set private project publication to `true` and restart the controller.
5. Run the required workflow successfully on the default branch.
6. Set desired enforcement to `active`, preview and apply.

Activation fails closed when required inputs or evidence are missing. Protection requires human review, successful checks and resolved discussions; there are no bypass actors.

`required_ci_checks` in controller configuration names workflows. The repository ruleset names check contexts. This repository uses workflow **Lifecycle verification** and contexts **regression (3.11)**, **regression (3.12)** and **regression (3.13)**.

## Incident sources

All incident remediation uses the ordinary Kira approval workflow. Configure the **application repository**, its App installation access, approvers, writable scope and executable checks before connecting senders. A valid signal may create an issue and plan, never authorize implementation.

- [Grafana](../integrations/grafana/README.md): configure `incident_sources.NAME` with provider `grafana`, a project and private `secret_file`; configure project `incident_loki` for bounded read-only evidence.
- [CI](../integrations/ci/README.md): list explicit workflow names in project `incident_ci_workflows`. Use the normal GitHub webhook; no separate CI agent.
- [ArgoCD](../integrations/deployments/README.md): configure a project-bound source with provider `argocd` and private static-token file; apply notification changes through GitOps.

Source maps and CI workflow lists default to empty. Restart the controller after changing trusted configuration. Alert-rule paths and workflow paths are not implicit grants: add the intended directory to `allowed_paths` and provide an appropriate check image. GitHub Workflows write permission is additionally required to publish workflow-file changes.

To connect a live sender, first verify the native receiver and matching repository access, then update its versioned contact/notification configuration and remove its independent gateway route. Remove redundant CI subscriptions after the normal GitHub webhook delivers workflow-run events. Never leave two independent agents authorized to implement the same signal. Do not disable a working sender or redirect it to a different project to conceal missing onboarding.

## Deployment

Run system Python against the absolute `hermes_sdlc/service.py` path, without arguments. The service reads `HERMES_SDLC_CONFIG` or defaults to `~/.hermes/sdlc/config.json`.

The receiver binds `127.0.0.1:8645`. `/health` reports readiness, not task completion. Run one controller per configuration and keep the installation path stable.

### Always-on Linux service

The current controller runs on **Surface**, under the nonroot account `jake`, as the boot-enabled system service `hermes-sdlc.service`. Code lives in `/home/jake/services/kira-sdlc`; private configuration, credentials and SQLite state live under `/home/jake/.hermes/sdlc`. It uses the authenticated Hermes runtime already installed on that server.

No Mac login, laptop availability or reverse SSH tunnel is needed. The systemd service starts at boot and restarts after failure; the server, its network, Docker and external providers remain availability dependencies.

`provisioning/playbook.yml` installs the controller on a Debian/Ubuntu host in inventory group `kira`. Supply `sdlc_project`, `sdlc_source` and `sdlc_approver`; install and authenticate Hermes on that account first.

The playbook installs runtime prerequisites, configures Docker access, copies Kira and starts the nonroot `hermes-sdlc` system service. Docker-group membership is host-level authority. Existing private configuration is preserved.

Alternatively install the generated user unit under `~/.config/systemd/user/`. Configure user-service persistence according to the host's operating policy.

### Shared public ingress

`provisioning/kira-ingress.yml` deploys a digest-pinned Nginx container on an existing Linux gateway. It checks both upstreams before changing the ngrok service's upstream through a separate systemd drop-in.

| Public route | Destination |
| :--- | :--- |
| `/kira/webhooks/github` | Controller `/webhooks/github` |
| `/kira/webhooks/incidents/NAME` | Controller `/webhooks/incidents/NAME` |
| `/kira/health` | Controller `/health` |
| Other paths | Existing gateway, unchanged |

The proxy binds loopback port `18644` and connects directly to the same host's controller on `8645`. Kira requests have a 1 MiB body limit, bounded timeouts, buffering, rate limiting and a connection limit. Request inspection and access logging are disabled.

```bash
ansible-playbook -i YOUR_INVENTORY provisioning/kira-ingress.yml \
  -e public_hostname=YOUR_RESERVED_HOSTNAME
```

Put the same always-on host in inventory groups `kira` and `gateway`. Docker, ngrok and a healthy local controller are prerequisites. Other workload routes retain their existing upstream.

The current installation uses gateway alias `surface` and public endpoint `https://semipneumatical-silvana-badly.ngrok-free.dev/kira/webhooks/github`. The App is `kira-sdlc[bot]`; publication and branch protection are enabled. App-level webhooks are disabled because the repository webhook already supplies delivery.

## GitHub controls

Use one issue per independently verifiable task. Choose one task-type label: `feature`, `bug`, `maintenance`, `migration` or `incident`. Describe the outcome, constraints and acceptance criteria in the body.

An authorized human-created issue starts planning. Externally bot-created or `auto-triaged` issues require an authorized human's `ready-to-fix` handoff. Native authenticated incidents create their own Kira run and issue directly, then stop at the same exact-plan approval gate.

Kira publishes a Markdown plan with file scope, acceptance checkboxes, numbered steps, design, rollback and a copyable approval command. Technical references are collapsed. Formatting does not change the specification hash.

Humans personally post these commands on the matching issue or PR:

| Command | Effect |
| :--- | :--- |
| `/sdlc approve RUN HASH` | Approve the exact reviewed specification |
| `/sdlc status RUN` | Request observed run status |
| `/sdlc cancel RUN` | Cancel the run |
| `/sdlc recover RUN plan` | Request a new bounded planning attempt |
| `/sdlc recover RUN revise` | Recover implementation within approved scope |
| `/sdlc recover RUN verify` | Reobserve the authentic deployment |

The controller checks the live comment author/body, resource association, configured human allowlist and repository permission. An agent may explain a command, but must not submit approval, merge or deployment for the human.

Recovery feedback may follow the command on subsequent lines. Replanning creates a new revision and hash requiring new approval. After implementation starts, a scope change requires a new task rather than reusing approval.

## Checks and PR review

The controller validates proposed paths before writing, runs all configured Docker checks and requests an independent model review. Repairs are bounded by attempt and model-call limits.

Publication uses a stable `sdlc/RUN` branch and reconciles an existing PR. It never force-pushes. PRs reference originating issues without implying that merge completes production verification.

Use GitHub request-changes reviews for implementation feedback. Authorized current-head reviews/comments and matching failed CI may trigger revision. Stale or unrelated feedback cannot authorize changes to a newer head.

Humans review and merge under branch protection. The controller verifies the merged head, human merger and required CI, then waits for deployment.

## Deployment evidence

A deployment receipt must identify the real repository, environment, full merge SHA, deployment timestamp and deployment ID. Deliver it through a successful GitHub deployment-status event or the separately authenticated deployment endpoint.

For another deployment system, include `run_id` and POST to `/webhooks/deployment`. Sign the raw body with the separate deployment secret using hexadecimal HMAC-SHA256 in `X-Webhook-Signature`, and supply a stable `X-Request-ID`.

The shared public-ingress template exposes GitHub and incident delivery. Use GitHub deployment statuses, or explicitly provision a separate bounded `/webhooks/deployment` route before sending external successful-deployment receipts. An incident alert is not a deployment-success receipt.

Kira waits for the configured observation period and gathers live evidence:

- **HTTP:** configure `name`, `kind: "http"`, trusted `url`, `expect_status` and `revision_json_pointer`. The endpoint must report the exact deployed SHA. Redirects and tokens in URLs are not accepted.
- **Loki:** configure `url`, `token_env`, `query`, `traffic_query`, `revision_query`, `freshness_query` and `coverage_query`. `{sha}` and `{window}` bind queries to the observed deployment. Defaults require positive traffic, full coverage and zero errors; choose real selectors and appropriate thresholds.

Missing, stale, nonfinite, negative or incomplete evidence cannot pass. Validate queries against known-good and known-bad releases. A health response alone is not proof of all application behavior.

Only bot-authored issues may be automatically closed or reopened. Human-authored issues receive evidence comments. Failed verification requires human attention; Kira does not roll back.

## Webhook contract

GitHub signatures use `X-Hub-Signature-256` over the exact raw body. `X-GitHub-Delivery` is required. Duplicate deliveries do not schedule duplicate work; conflicting reuse is rejected.

Subscribe to issues, issue comments, pull requests, pull request reviews, review comments, workflow runs and deployment statuses. The provisioning script sets the complete event list and sends a ping after webhook changes.

HTTP 202 means an event is durably queued. It is not a verification result.

## Maintenance

Operators stop/start the service to pause/resume processing. Already-started inference may still incur provider cost. Cancellation cannot undo a GitHub side effect already accepted; stable identifiers support reconciliation.

State and workspaces can contain private repository content. Back up SQLite with its backup API or with the service stopped. Do not copy only a live database while ignoring its WAL, delete active workspaces or edit state to force success.

Run regression checks after changes:

```bash
python3 -m unittest discover -s tests -v
```

`hermes_sdlc.evaluation` runs the labeled scenarios in `evaluations/scenarios.json` through the configured model and stores results privately. These scenarios check specific review/scope behavior; they are not a broad quality benchmark.

Before upgrading Hermes or changing models, verify representative tasks, authorization boundaries, check isolation, token renewal and production selectors.

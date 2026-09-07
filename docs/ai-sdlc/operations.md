# Operating the Hermes software lifecycle

## Prerequisites and installation

Python 3.11+, Git, authenticated `gh`, a running Docker daemon, and an installed/authenticated Hermes virtualenv are required. The control plane uses only Python's standard library; the inference bridge imports the installed Hermes runtime and its provider pool. It does not install another LLM SDK or copy provider credentials.

```bash
docker pull python:3.12-slim
python3 scripts/install-sdlc.py --project OWNER/REPO --source /absolute/checkout --approver HUMAN_LOGIN
```

The installer preserves an existing config. It creates:

- `~/.hermes/sdlc/config.json`: trusted project policy, outside every task checkout.
- `~/.hermes/sdlc/{github,deployment}.secret`: private per-route secrets; values are never printed.
- `~/.hermes/sdlc/lifecycle.sqlite3`: created when the service initializes state, WAL plus durable jobs and evidence.
- No lifecycle executable is installed; the installer removes recognized legacy launchers.
- `~/.hermes/skills/software-development/hermes-sdlc/SKILL.md`: integration instructions for Hermes.
- A service definition under `~/.hermes/sdlc/`: launchd plist on macOS, user systemd unit on Linux. Installation does not silently start another listener.

For a macOS login service, copy the generated plist to `~/Library/LaunchAgents/com.hermes.sdlc.plist` and bootstrap it in your GUI launchd domain. For Linux, install the generated user unit under `~/.config/systemd/user/`, enable it, and ensure the service user can reach Docker. Do not run the controller as root. Alternatively use an existing process manager with system Python and the absolute checkout path to `hermes_sdlc/service.py`, without arguments. The service reads `HERMES_SDLC_CONFIG` or defaults to `~/.hermes/sdlc/config.json`. Keep the checkout at that path and run one listener per config. There is no replacement command CLI or package main entrypoint.

The receiver defaults to **127.0.0.1:8645**, independent of Hermes gateway port 8644. Public ingress requires TLS/reverse-proxy rate/body limits. `/health` is a readiness endpoint, not a run-history API. Users read plans/status on GitHub; private diagnostics and evidence remain in the Python controller/store for maintainers.

### Shared stable ingress

`provisioning/kira-ingress.yml` deploys a digest-pinned, unprivileged Nginx container on the existing Linux gateway. It validates both upstreams before changing the ngrok service's upstream using a separate systemd drop-in; the original tunnel unit is preserved.

- `/kira/webhooks/github` forwards to the controller's `/webhooks/github`.
- `/kira/health` checks the controller; all other paths retain the existing Hermes gateway upstream.
- The proxy listens only on gateway loopback port `18644`. The controller arrives through an SSH reverse forward bound only to gateway loopback port `18645`.
- Kira requests have a 1 MiB body limit, bounded header/body/upstream timeouts, request buffering, rate limiting and a concurrent-connection limit. Request-body inspection and access logging are disabled.

Generate the optional forward definition with `scripts/install-sdlc.py --project OWNER/REPO --source /absolute/checkout --approver HUMAN --gateway-host SSH_ALIAS`. The installer preserves existing private configuration and writes both service definitions; it does not start them. On macOS, install and bootstrap `com.hermes.sdlc.plist` and `com.hermes.sdlc-forward.plist` under `~/Library/LaunchAgents/`. Linux definitions are user systemd units.

Deploy the gateway with `ansible-playbook -i YOUR_INVENTORY provisioning/kira-ingress.yml -e public_hostname=YOUR_RESERVED_HOSTNAME`, using inventory group `gateway`. Docker and the existing ngrok service must already be installed; the private SSH forward must already be healthy. Do not claim a domain serving another workload without preserving its routes.

The current host alias is `surface`; the stable URL is `https://semipneumatical-silvana-badly.ngrok-free.dev/kira/webhooks/github`. Both Mac services are launchd-managed; the proxy and existing tunnel are systemd-managed on the gateway. The controller still requires this Mac to be awake, logged in and reachable over SSH. Login services are not an always-on cloud deployment.

This workstation runs the controller as launchd service `com.hermes.sdlc` and its private gateway forward as `com.hermes.sdlc-forward`. The former harness-managed `hermes-sdlc` listener was stopped before bootstrapping launchd; do not run both supervisors for the same config.

The optional Linux playbook supports `sdlc_enabled=true` plus explicit `sdlc_project`, `sdlc_source` and `sdlc_approver` variables. It installs Docker, copies the controller, invokes the same installer and starts a system service as the nonroot service user. Authenticate Hermes and GitHub for that user first; membership in the Docker group is host-equivalent authority. Syntax was checked locally, but no remote host was provisioned.

## Code-managed GitHub setup

`provisioning/github.json` declares the repository, lifecycle labels, public webhook URL, ruleset name/enforcement and required workflow/check names. `hermes_sdlc/github_setup.py` reconciles it through authenticated GitHub REST calls. The administrator entrypoint is:

```bash
# Read-only preview using the current administrator gh identity:
python3 scripts/provision-github.py
# Apply the declared infrastructure:
python3 scripts/provision-github.py --apply
```

Optional `--policy` and `--config` paths support another configured project. This script is repository-installation automation for an explicit setup request, not a daily lifecycle command interface; ordinary work still uses Hermes and GitHub.

The reconciler:

- Creates missing lifecycle labels; preserves existing labels, including custom descriptions and capitalization.
- Enables issues if needed; sets default Actions token permissions to read and disables Actions approving PR reviews.
- Creates or updates only the declared `hermes-sdlc-` ruleset; unrelated repository/organization rules remain untouched.
- Stages one approving review, dismissal of stale reviews, approval of the latest push, resolved review threads, required successful checks, and no branch deletion/force push on the default branch. No bypass actors are granted.
- Creates or updates the lifecycle webhook with its exact events, JSON content, TLS verification and the receiver's existing private secret. It sends a GitHub ping after webhook changes. `github-setup.json` under the private state directory remembers the hook ID/URL and a secret fingerprint—not the secret. The secret never enters policy JSON, command arguments or printed plans.
- Verifies the configured GitHub App identity, installation, selected repository access, required write permissions and absence of administration permission. App installation is an account-owner browser action; no machine-user invitation is needed.
- Plans all resources before mutation, refuses ambiguous duplicate hooks, and refuses to turn an active ruleset off through bootstrap. Concurrent administrators should serialize provisioning. API failures may leave earlier successful resources; a corrected rerun reconciles them.

### Bootstrap versus activation

For a new deployment, begin with `enforcement: "disabled"` and `webhook_url: null`. This stages the desired restrictions without preventing an owner from publishing the initial source and CI. The checked-in policy records this repository's chosen endpoint and desired enforcement; verify actual GitHub state with the provisioning preview rather than treating policy as applied evidence.

Activation requires actual inputs:

1. **Public ingress.** Set `webhook_url` to the real HTTPS receiver ending in `/webhooks/github`. Configure DNS/TLS/reverse-proxy forwarding to the running listener. Loopback, private IPs, credentials in URLs and invented example endpoints are rejected. Apply once with the ruleset still disabled; inspect GitHub's ping/delivery result.
2. **Repository-scoped GitHub App.** Register an App on the owner's account and install it only on the intended repositories. Grant contents/issues/pull requests write; actions/checks/deployments read; metadata read. Do not grant administration. Generate a private key, store it outside the repository with mode `0600`, and configure the root-level `github_app` object shown below. Human approvers remain separate accounts.
3. **Separate worker authentication.** The controller signs App JWTs with `openssl`, verifies `/app`, then mints installation tokens restricted to the configured repository IDs. Tokens remain in memory and refresh before expiry. Only GitHub API and Git network subprocesses receive the token; it is not placed in command arguments, Git remotes, the model environment or sandbox. `bot_login` is derived as `<slug>[bot]`; an explicit conflicting login fails configuration validation. Administrator provisioning deliberately uses the operator's existing `gh` credentials instead. Verify App access before setting `publish: true`; never paste keys or tokens into policy files or issue comments.
4. **Published source and CI.** Publish the actual controller/tests and `.github/workflows/verify.yml` through the normal repository workflow; this provisioning script does not commit or push source. Run it successfully on the default branch. Its workflow is `Lifecycle verification`, with matrix check names `regression (3.11)`, `regression (3.12)` and `regression (3.13)`. Configure the controller's `required_ci_checks` to include `Lifecycle verification`; change policy names for other projects based on real check results.
5. **Reviewed activation.** Set policy `enforcement` to `active`, preview and apply. The script refuses activation before the configured bot/access/publication, workflow availability, successful default-branch check contexts and reported successful webhook delivery prerequisites are present. Worker credentials still require the independent identity check above. Rules have no bypass actors: do not activate without a usable human reviewer and working delivery path.

Root-level private controller configuration for this installation (identifiers and key path are not credentials):

```json
"github_app": {
  "app_id": 4855327,
  "installation_id": 159635051,
  "slug": "kira-sdlc",
  "repository_ids": [1359527008],
  "private_key_file": "/Users/jakeuren/.hermes/sdlc/github-apps/kira/private-key.pem"
}
```

Use the real absolute key path and identifiers on another host. A GitHub App rename requires updating `slug` and any explicit project `bot_login`; it does not require a new private key or installation. Removing App configuration while publication is enabled fails closed.

### Applied repository evidence

Applied to `mushhzz/hermes-recipes`: seven missing lifecycle labels were created; the existing `bug` label was preserved. Ruleset `hermes-sdlc-main` (ID `22411569`) was created **disabled**. Existing Actions token settings already matched the desired read-only/no-review-approval policy. A second real `--apply` reported zero changes.

Kira SDLC (`kira-sdlc`, App ID `4855327`) is registered and installed only on `mushhzz/hermes-recipes` (installation `159635051`). The name was changed from Kira-mushhzz without replacing its key or installation. Its private key and metadata are stored under `~/.hermes/sdlc/github-apps/kira/`, outside the checkout. The host-owned controller config uses `kira-sdlc[bot]`; the administrator's `gh` identity remains `mushhzz`.

Verification: 35 controller regression tests passed locally. Real controller requests verified App identity, repository-scoped access, human approver permissions and recovery from an expired cached token. Source commit `4989f4b9a60462d0052c3eb6dad163f2f4c6c04f` was published; GitHub's `Lifecycle verification` run `34072674026` passed Python 3.11, 3.12 and 3.13. A public Git remote read succeeded; that read alone is not proof of authenticated write access.

Publication is enabled in host-owned configuration, with `Lifecycle verification` required and the canonical GitHub HTTPS source used for fresh task checkouts. Repository webhook `675546335` is active and GitHub reported a successful HTTP 200 ping to the shared endpoint. Real public probes verified both gateway and controller health, signed ping acceptance, unsigned-request rejection (401), and oversized-body rejection (413). App-level webhooks remain disabled intentionally: repository webhooks provide delivery without duplicate subscriptions. Branch enforcement is applied separately after the current default-branch CI passes.

REST references: [repository rulesets](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset), [repository webhooks](https://docs.github.com/en/rest/repos/webhooks), [Actions workflow permissions](https://docs.github.com/en/rest/actions/permissions).

## Project policy

The initial install defaults to **publication disabled** and repository-specific Python checks/path scope for hermes-recipes. Edit the host-owned JSON for each target. Never load this policy from an issue or agent checkout.

```json
{
  "source": "/absolute/target-checkout",
  "base_branch": "main",
  "approvers": ["authorized-human"],
  "publish": false,
  "bot_login": null,
  "allowed_paths": ["src/", "tests/", "README.md"],
  "sandbox_image": "python:3.12-slim",
  "checks": [
    {"name": "tests", "argv": ["python", "-m", "unittest", "discover", "-s", "tests"], "timeout_seconds": 120}
  ],
  "required_ci_checks": [],
  "environment": "production",
  "observation_seconds": 3600,
  "production_checks": []
}
```

Configure the target's real checks; install dependencies into a trusted image ahead of time. Checks cannot download dependencies: containers have no network. Images must provide `/bin/sh` and `cp` for the constant trusted copy/exec wrapper. Input is read-only, `/work` is a 256 MiB tmpfs, `/tmp` 64 MiB, with 512 MiB memory, one CPU and 128 PIDs. Large applications need deliberately adjusted resource policy; do not remove isolation to make a check pass. Pin image digests for reproducible deployments.

Staging uses the trusted state directory rather than the OS temporary directory: macOS Docker installations may not share `/var/folders`. Ensure the daemon can access the configured state path. Exit 125 means container infrastructure failed, not that application code failed its tests.

Set `publish: true` only with verified `github_app` authentication; `bot_login` must match the derived App bot identity and differ from every human approver. Configure repository branch protection to require human review and your checks; the controller cannot prevent merges performed outside its own workflow. `required_ci_checks` names GitHub Actions workflows whose latest matching-head run must succeed before merge acknowledgment. Provider tokens and observability tokens stay in the worker environment, not project JSON or containers.

Restart the service after policy changes. To pause processing, an administrator stops the service through its process manager; start it again to resume. There is no user pause/resume command. Existing private configuration and publication policy are preserved by installation, not silently reset or enabled.

## Intent, specification and approval

Ask Hermes, for example: “Plan a fix for OWNER/REPO: reject invalid release dates, preserving valid requests.” Its installed skill uses the built-in terminal, not an SDLC executable:

```bash
gh issue create --repo OWNER/REPO --title 'Reject invalid release dates' --body-file task.txt
gh issue view ISSUE --repo OWNER/REPO --comments
gh issue comment ISSUE --repo OWNER/REPO --body-file clarification.txt
gh pr view PR --repo OWNER/REPO --comments
```

Issue creation is a requested GitHub write; use the intended authenticated account. An authorized human-created issue or authorized `ready-to-fix` label queues planning. Bot-created/`auto-triaged` issues need that human handoff; creating an issue is not approval. Describe whether the work is a feature, bug, incident, maintenance task or migration in its body, with acceptance criteria and constraints. Use one issue per independently verifiable target, and check existing issues before creating another.

Planning pins a commit and produces summary, risk, acceptance, exact files, steps, design and rollback. The plan identifies the run and specification hash on GitHub when publication is configured. **No live plan/status comments or PR publication until a dedicated bot is configured and publication explicitly enabled.** The default disabled mode retains local artifacts for maintainers; it is not a working live GitHub delivery setup.

After reviewing the exact plan, the human posts this comment on the matching issue (or the run's matching PR where applicable):

```text
/sdlc approve RUN HASH
```

Approval checks the live comment author/body, resource association, configured human allowlist, live User identity and repository write permission. Hermes may show the plan and explain the command, but must never submit approval, merge or deployment on the human's behalf.

To change a plan before implementation, the human posts:

```text
/sdlc recover RUN plan
Clarify the acceptance criteria and preserve the existing response format.
```

Recovery feedback may follow the command on subsequent lines. A new specification revision/hash requires new human approval; old approval cannot authorize it. After implementation starts, scope changes require cancelling and creating a new issue/task rather than silently reusing old approvals.

## Checks, review and publication

The worker invokes tool-free Hermes, validates every proposed path before writing anything, runs all configured Docker checks and asks a separate model invocation to review against acceptance criteria. It can repair within the bounded configured attempt/model-call budgets. An LLM review is not an independent correctness proof; humans still review.

`publish: false` produces a real committed branch in `state_dir/workspaces/RUN` without external writes. `publish: true` uses a stable `sdlc/RUN` GitHub branch and reconciles an existing PR rather than opening duplicates. Publication never pushes to the acquisition checkout or force-pushes. PRs reference originating issues without closing them prematurely at merge.

Use normal GitHub PR request-changes reviews for implementation feedback. Authorized `changes_requested` reviews and review comments trigger bounded revision only for the matching current head SHA. Failed configured CI workflows can trigger repair. Stale reviews cannot change a newer head. Hermes can read the PR and explain findings, but the human remains responsible for review and merge.

## Merge and deploy are separate actions

The controller performs neither merge nor deployment. Humans review and merge the lifecycle PR in GitHub under repository branch protection. The authenticated merged-PR event triggers live merge metadata checks: verified head, authorized human merger and configured successful CI. It then waits for deployment. There is no local merge-acknowledgment command; publication-disabled local experiments are not a substitute for this live event path.

A real deployment receipt:

```json
{
  "repository": "OWNER/REPO",
  "environment": "production",
  "sha": "FULL_40_CHARACTER_MERGE_SHA",
  "deployed_at": "2026-09-07T02:00:00+00:00",
  "id": "deployment-123"
}
```

Deliver the actual receipt through a GitHub deployment-success event, or include `run_id` and POST it to the separately authenticated deployment webhook described below. Use the actual timestamp/identity, not a fabricated delay. The worker waits until the configured observation period has elapsed and independently checks live evidence. It reconciles a merge event that arrived later than deployment. Hermes must not report a deployment as completed based solely on conversation or merge age.

HTTP production check:

```json
{"name":"running-release","kind":"http","url":"https://your-service.example/health","expect_status":200,"revision_json_pointer":"/revision","expect_contains":"ok"}
```

The endpoint must return the full deployed SHA at the configured JSON pointer. A health check establishes that check's result, not all application functionality; configure an appropriate functional synthetic endpoint for stronger assurance. Do not put access tokens in URLs. Redirects are rejected.

Loki checks use `kind: loki`, `url` (Loki base URL), `token_env`, `query` (error count), `traffic_query`, `revision_query`, `freshness_query` and `coverage_query`. Queries are operator-supplied instant-vector expressions; `{sha}` expands to the verified deployment SHA and `{window}` to the observation duration, except freshness which is capped at `freshness_seconds` (default 60). Configure selectors from real telemetry. `coverage_query` must return a fraction 0–1 reflecting covered observation intervals; `min_coverage` defaults to 1. `min_traffic` defaults to 1 and `max_errors` to 0. Missing, nonfinite, negative, stale or incomplete evidence cannot pass. Validate these queries against known-good and known-bad releases before enabling closure.

Verification comments are idempotently marked. Only issues whose live author is the configured bot may be automatically closed/reopened; human-authored issues receive evidence comments only. Deployment/release failure remains `needs_human`. No automatic rollback exists: execute a human-approved rollback and record its own deployment/outcome through a correctly scoped task.

## GitHub and deployment webhooks

Create one GitHub subscription on `/webhooks/github` with the private `github.secret`, JSON content, and these events:

- Issues: authorized human `opened` or `ready-to-fix` labels start planning. Bot/auto-triaged creation does not.
- Issue comments (including PR conversation comments): human `/sdlc approve RUN HASH`, `/sdlc status RUN`, `/sdlc cancel RUN`, or `/sdlc recover RUN plan|revise|verify` on the matching run issue/PR, with matching live comment author/body. Recovery optionally includes multiline feedback.
- Pull requests: merged lifecycle-owned PRs advance to deployment waiting.
- Pull request reviews/review comments: current-head revision requests.
- Workflow runs: failed named checks on the lifecycle head.
- Deployment statuses: successful configured-environment releases.

GitHub HMAC is verified over raw request bytes using `X-Hub-Signature-256`; `X-GitHub-Delivery` is required. Durable duplicate IDs cannot schedule duplicate work; conflicting reuse is rejected.

For another deployment system, POST the deployment object plus `run_id` to `/webhooks/deployment`, signed with the separate `deployment.secret` using raw hexadecimal HMAC-SHA256 in `X-Webhook-Signature` and a stable `X-Request-ID`. The receipt attests deployment metadata; it does not bypass live revision verification.

Legacy Grafana/CI/Argo RCA gateway subscriptions stay separate. Remove old `github-issue-triage`, `postmortem-record` and `postmortem-verify` routes/subscriptions and the old sweep cron during cutover. Preserve old pending/processed JSONL files for audit and explicitly resubmit unfinished work. The removed installers are not compatibility aliases.

## Recovery and private operational evidence

Humans post commands in the matching issue/PR conversation, replacing `RUN` with its actual run ID:

```text
/sdlc status RUN
```

```text
/sdlc cancel RUN
```

For a human-stop requiring repair within approved scope:

```text
/sdlc recover RUN revise
The current candidate still fails the documented boundary case; preserve approved scope.
```

For a new attempt to observe the authentic deployment:

```text
/sdlc recover RUN verify
The telemetry outage has been resolved.
```

- Status is a GitHub evidence reply when publication is enabled, not permission to advance a run.
- Recovery is a new human-authorized bounded attempt from an eligible human-stop state. It records the decision and another model allowance without deleting historical evidence. Verify recovery reuses authentic deployment identity; it does not invent a redeployment.
- Use normal PR request-changes reviews for routine revisions, not recovery commands to bypass the review lifecycle.
- Cancellation invalidates completion rights; it cannot undo a GitHub side effect already accepted. Stable branch/comment identities support reconciliation rather than claiming distributed exactly-once effects.
- Operators stop/start the service to pause/resume work. Already-started inference may still cost tokens. Do not edit SQLite state to force a successful outcome.
- Maintainers inspect durable jobs, failures, metrics and full evidence through the Python controller/store. There is no user job-retry/metrics command. Evidence includes specifications, reviews, check results, commit SHAs, model identity, usage and elapsed model/check time. A missing provider cost estimate is unknown, not zero.

State/config are private operator data and can contain repository source and issue text. Back up SQLite with its backup API or while the service is stopped; do not copy only a live main database while ignoring WAL. Workspaces are retained for human recovery/audit and are outside the legacy cron clone root. Operators choose retention after ensuring no active jobs depend on them.

## Evaluation and upgrades

```bash
python3 -m unittest discover -s tests -v
# Real-model evaluation is available through the maintainer Python library, not a command.
```

The test command exercises deterministic boundary/recovery behavior without an LLM. Maintainers use the evaluation Python library with `evaluations/scenarios.json` to call the configured real model against labeled review and scope-injection cases; it persists suite version/hash/model/usage/results privately without publishing or executing proposals. This small suite is a release signal, not a broad model-quality claim. Add representative historical tasks and measure incorrect conclusions, human rework, latency, cost, merged outcomes and production results before changing models or recipe policy.

The [historical pre-cutover lifecycle example](lifecycle-example.md) records what was actually exercised, including failures and fixes. Its removed CLI actions and local merge/deployment are provenance, not current directions or live GitHub end-to-end proof. See [architecture](architecture.md) for module contracts and [security](../security-model.md) for remaining trust assumptions.

## CLI removal verification

The custom launcher, `hermes_sdlc/cli.py` and package command entrypoint are removed. The installed service was restarted directly through `service.py`; its real signed webhook receiver returned 202 for a new inert notification and 200 for its duplicate, and the durable worker completed that event. No external GitHub write was made by this smoke check.

The controller's 26 regression tests pass, including GitHub-authorized approval, resource binding, recovery redelivery, cancellation and private status reporting. GitHub API responses in those command tests are controlled fixtures, not live production proof. Installer smoke checks covered fresh installation, recognized-launcher removal, unrelated-executable preservation, unchanged private configuration and service paths containing spaces.

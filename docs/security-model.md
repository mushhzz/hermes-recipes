# Security model

There are two distinct execution surfaces. Do not treat their guarantees as interchangeable.

## Durable SDLC controller

`hermes_sdlc/` owns lifecycle state and side effects outside the model.

- **Intake:** a separate receiver validates raw-body HMAC-SHA256, bounded JSON and durable delivery identity before enqueueing. HTTP 202 means accepted, not executed. Bind localhost and use TLS plus upstream request limits for public access.
- **Approval:** configured human login allowlist plus live GitHub user type and repository write permission. Approval binds a SHA-256 digest of the exact specification (base SHA, files, acceptance, design and rollback). A `ready-to-fix` label only starts planning. Model text cannot approve.
- **Inference:** a fresh installed-Hermes virtualenv process resolves existing provider credentials, explicitly disables tools, memory, project context, plugin discovery and custom context engines. It rejects external-agent provider modes and checks tool/plugin state before and after generation. Provider diagnostics are suppressed; only structured proposals and allowlisted usage leave the bridge. Internal Hermes APIs are version-sensitive: rerun the live example and evaluations after upgrades.
- **Writes:** the model returns complete text files, not shell commands. The host rejects traversal, symlinks, protected paths, unapproved files and oversized output before applying changes. The trusted project configuration lives outside the target repo and is never model-editable through the proposal interface.
- **Checks:** trusted configuration specifies argument arrays. Docker runs without network, credentials, `.git`, capabilities or privilege escalation, as a nonroot user with CPU/memory/PID limits. Input is read-only; writable work and temporary storage are capped tmpfs. No Docker socket is mounted. Use maintained, pinned trusted images; the Docker daemon remains a trusted host capability.
- **Publication:** disabled by default. Explicit publication requires the authenticated GitHub identity to match the dedicated configured bot. Pushes target only `sdlc/RUN` in the configured GitHub repository, never the acquisition checkout. No force push, merge or deployment command exists in the controller.
- **Release:** live merged PR must match the verified head SHA, an authorized human merger and successful configured CI workflows. GitHub branch protections are still required to prevent a human/bot bypass outside this controller. Configure `required_ci_checks` with exact workflow names; the controller cannot invent the repository's policy.
- **Recovery:** merge time is not deployment time. Exact merge SHA, configured environment, actual deployment timestamp, observation period and live configured evidence are required. Missing/old/incomplete telemetry is inconclusive. LLM judgment cannot declare a deployed release successful.
- **State:** private SQLite WAL database with transactional inbox/jobs/approval/evidence, fenced leases and stable publication identity. Cancellation invalidates queued/running work. Operators stop/start the background service to pause/resume processing; already-started model requests may still incur provider cost. External HTTP/GitHub writes cannot be rolled back by SQLite; reconciliation and stable identifiers handle replay, not a claim of distributed exactly-once execution.
- **Secrets:** webhook secrets and configuration are private files; provider credentials remain in the existing Hermes installation, never a sandbox mount. The trusted worker account can access its configured integrations. Do not run it as root or with a personal publication token.

Hermes and GitHub are the user interfaces; there is no local lifecycle CLI. Humans submit approval, status, cancellation and bounded recovery comments on the matching issue/PR. The receiver validates live comment identity, body, resource association and configured authority; a signed delivery alone is not human approval. Hermes may create/read issues and show plans/status using its built-in terminal and `gh`, but must never approve, merge or deploy on a human's behalf. Anyone able to modify private state/config files or run arbitrary code as the worker account already controls the service. Use distinct OS identities where that separation is required. Administrative service launch uses system Python and the absolute `hermes_sdlc/service.py` path, with no arguments.

## Existing RCA recipes

Grafana, CI and Argo recipes still run as ordinary Hermes agents with terminal/file tools. Their write restrictions are **prompt instructions plus GitHub permissions and human review**, not the new controller's file/sandbox enforcement. Use a dedicated bot, read-only observability tokens, unique checkouts, and protected branches. Their issue trail feeds the lifecycle through an authorized human handoff.

Each gateway recipe has its own secret and webhook subscription. Argo's static-token authentication is distinct from HMAC; use TLS. Do not install application-writing legacy issue/postmortem routes alongside the controller. The obsolete installers were removed; existing deployed routes/cron must be removed during migration.

## Remaining trust and evidence limits

- The host OS, Docker runtime/images, installed Hermes code, provider SDKs and GitHub/observability services are trusted.
- Repository files, issues, logs and review comments are untrusted. A tool-free model may still propose a bad patch; scope constraints and tests do not prove semantic correctness. Human review and representative model evaluations remain required.
- HTTP health plus a running SHA proves that configured observation, not all application behavior. Configure functional synthetic checks or error/traffic/SLO evidence appropriate to the risk.
- Loki queries are operator-owned; configure traffic, running-revision, freshness and interval-coverage queries against real telemetry. An incorrect selector is not fixed by an orchestration framework.
- No provider diagnostic, secret, or private transcript belongs in research documents or reports. Rotate any credential that appears in a transcript/log/commit, even briefly. The earlier configuration inspection in this implementation session exposed a `model.api_key` value; its value is not retained in project documents and rotation is required.

# Kira SDLC security model

**Model output proposes changes. It never authorizes them.**

[Overview](../README.md) · [Architecture](architecture.md) · [Operations](operations.md)

## Authority boundaries

| Boundary | Enforcement |
| :--- | :--- |
| Event intake | Host-bound source/project mapping, bounded JSON, HMAC-SHA256 (GitHub/Grafana/deployment) or private static token (ArgoCD), durable delivery identity |
| Plan approval | Authorized human editor, canonical bot-owned comment, exact old/new/live body, current revision/hash and atomic approval |
| File changes | Host-enforced path allowlists, approved scope, size limits and symlink/traversal rejection |
| Checks | Trusted argument arrays executed in constrained, credential-free Docker containers |
| Publication | Explicit enablement, verified GitHub App identity and configured repository only |
| Merge | Human merger, verified PR head and successful required workflows |
| Verification | Authenticated deployment plus revision-correlated live evidence |

A valid webhook signature is not human approval. A task label starts planning, not implementation. A successful check is not permission to merge or deploy.

## Model isolation

The controller starts a fresh process in the installed Hermes virtual environment. It disables tools, memory, project context, plugin discovery and custom context engines; rejects external-agent provider modes; and checks tool/plugin state around generation.

Only structured proposals and allowlisted usage information leave the bridge. Provider diagnostics are suppressed. Hermes internals are version-sensitive: run regression checks and representative model evaluations after upgrades.

Issue text, repository content, logs and review comments are untrusted. Even a tool-free model can propose an incorrect patch. Scope enforcement and tests reduce risk; they do not replace human review.

Grafana, CI and ArgoCD incidents use this same tool-free proposal path. There is no separate gateway coding or tuning agent. The controller may create an incident issue and collect read-only evidence before approval; it cannot publish an implementation or tuning PR until the normal human-approved specification has passed checks.

## Check isolation

Docker checks run:

- As a nonroot user, without network or credentials
- Without Git metadata, symlinks or a Docker socket
- With a read-only input mount and capped writable tmpfs
- Without capabilities or privilege escalation
- Under CPU, memory and process limits

Use maintained, digest-pinned images containing the required dependencies. Checks cannot download packages. Docker and the host account controlling its daemon are trusted capabilities; Docker-group membership is effectively host-level authority.

## Credentials

The GitHub App private key and webhook secrets are host-owned private files outside the repository. The key must be accessible only to the service user. App installation tokens stay in memory and are injected only into authenticated Git/`gh` subprocesses—not arguments, remotes, model context or check containers.

Human GitHub access remains separate from the App's identity. The App needs repository contents/issues/pull requests write access and actions/checks/deployments/metadata read access; it must not have administration permission.

Hermes resolves provider credentials from its own installation. Never commit, display or log private keys, tokens, webhook secrets or provider diagnostics. Rotate any credential exposed in a transcript, log or commit.

Incident investigation uses a separate read-only Loki token in a private host file, never the Terraform apply credential. Loki URLs and selectors are operator-owned; payload URLs, namespace values and annotation queries cannot select network destinations or commands. CI evidence is fetched only from the configured repository and live matching run attempt. Allow workflow-file writes and grant GitHub Workflows write permission only for projects explicitly authorized for CI configuration changes.

## Public ingress

Bind the controller to loopback. Place a TLS proxy in front of it with header/body timeouts, request-size and concurrency limits, request buffering and rate limiting. Do not expose the standard-library HTTP server as an unrestricted public TCP listener.

GitHub signatures use `X-Hub-Signature-256` over the exact raw body. A stable `X-GitHub-Delivery` identifies each delivery; duplicates cannot schedule independent work. Deployment integrations use a separate secret and delivery identity.

Grafana source requests use hexadecimal HMAC-SHA256 in `X-Webhook-Signature`, without a timestamp prefix. ArgoCD uses `X-Gitlab-Token`, a static shared secret checked in constant time—not body HMAC. TLS is required; possession of that token permits replay until rotation. Native deliveries are deduplicated by body hash. Stable incident identities coalesce repeated observations without replacing the task or approved specification.

The shared-ingress configuration routes `/kira/` endpoints to Kira and preserves other upstream paths. It disables request inspection and access logging. Host availability remains an operational dependency.

## Human controls

Humans approve by checking the action checkbox in Kira's canonical plan comment. The webhook sender is the acting human; the original comment author remains the bot. The controller verifies live identity/permission, matching repository/issue/comment, exact stored prior rendering, the single allowed checkbox change and the live resulting body. It then atomically binds approval to the current specification and stored projection. Stale revisions, copied controls, plan-text changes, acceptance-checkbox edits and bot actions cannot grant approval.

Model prose is HTML-escaped and kept in separate Markdown blocks so it cannot conceal trusted scope and approval controls. The rendered document is checked for ambiguous approval controls.

Before approval, ordinary allowlisted human issue comments request a new draft, never implementation. Replanning clears the approval action and invalidates stale renderings. After any approval, scope changes require a new task. Labels are not authorization. Necessary status, cancellation and failure-recovery commands remain authenticated operator controls; the former approval command is removed.

Kira may explain a plan or review, but must not approve, merge or deploy for the human. Branch protection is necessary because the controller cannot prevent actions taken outside its own workflow.

## State and recovery

Private SQLite state records jobs, approvals and evidence with transactional claims and fenced leases. Cancellation invalidates completion rights, but cannot undo an external action already accepted by GitHub.

Recovery is an explicitly authorized, bounded attempt—not an erased failure or fabricated success. Back up SQLite through its backup API or with the service stopped; copying only a live database file can omit its WAL.

Anyone able to edit trusted configuration/state or execute arbitrary code as the service account controls the worker. Use separate OS accounts where stronger isolation is required.

## Evidence limits

The host OS, Docker runtime/images, installed Hermes code, provider SDKs and configured external services are trusted.

A merge does not establish deployment. Verification requires the deployed SHA, environment, timestamp, observation period and configured live evidence. Missing telemetry is inconclusive; low error counts without traffic, freshness and coverage are not recovery proof.

A native PR closing reference closes the implementation issue on human merge. This UI event and the `kira:merged` label are not production evidence. Deployment results remain in the run, canonical plan and lifecycle labels; failed checks never become verified because the issue is closed.

HTTP health establishes the configured observation, not every application behavior. Loki selectors and thresholds are operator-owned. Validate them against known-good and known-bad releases before relying on automatic verification.

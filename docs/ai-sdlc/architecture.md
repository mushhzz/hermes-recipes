# Hermes lifecycle architecture

## Status and scope

Implemented in `hermes_sdlc/` and installed into the local Hermes setup. Historical loopback receiver, tool-free model evaluation and regression results are preserved in [lifecycle evidence](lifecycle-example.md); they are not live end-to-end proof of the post-cutover GitHub workflow. See [operations](operations.md) for current interfaces. Live GitHub publication and external production telemetry require a dedicated bot and operator configuration; local success does not establish those integrations.

The decision is a small Python standard-library control plane alongside Hermes recipes. Hermes supplies tool-free JSON proposals; the host controller owns authorization, state transitions, allowed file writes and GitHub actions. Docker executes untrusted repository checks without credentials or network access. Human merge remains mandatory. Deployment and rollback are not autonomous controller actions.

The inspected installed Hermes gateway has no route-script hook. A separate standard-library HTTP receiver and SQLite worker replace that unsupported assumption, rather than installing fictitious script routes. The historical mismatch is recorded in [hermes-gap-analysis.md](hermes-gap-analysis.md).

## Components and authority

| Component | Contractual responsibility | Boundary |
| --- | --- | --- |
| Configuration | Trusted project identity, paths, checks, approvers, publication policy, limits and production evidence adapters | Stored outside target repositories; untrusted events/model output cannot choose commands or credentials |
| Hermes skill / authenticated HTTP receiver | Hermes creates/reads GitHub issues and shows plans/status; the receiver ingests GitHub and deployment events | Durable, idempotent jobs; human commands require live actor and matching issue/PR validation, not model claims |
| SQLite store / worker | Runs, jobs, events, approvals, evidence, transactional claims and leases | Accepted dispatch is not completed verification; retries and model calls are bounded |
| Hermes proposal bridge | Plan, implement/revise, and independent review JSON | No model tool execution, shell, plugins or automatic tool hooks; fail closed if tools are nonempty |
| Host runtime adapter | Isolated clone, bounded Git subprocesses, safe application of validated proposals, publication | No shared checkout mutation, no shell evaluation, no model-selected GitHub destinations |
| Docker check adapter | Run trusted configured argv against staged repository content | No network, credentials, `.git`, symlinks or writable host checkout exposed to untrusted checks |
| Production evidence adapter | Check a trusted configured HTTP/Loki target after a correlated deployment | No event-provided arbitrary URL/command; absent proof is inconclusive |
| Humans / existing delivery platform | Approve scope, review and merge, execute/authorize deployment and rollback | Controller does not manufacture these approvals or infer deployment from merge age |

## Persisted lifecycle

The agreed state vocabulary is:

`queued`, `planning`, `awaiting_approval`, `implementing`, `awaiting_review`, `awaiting_deployment`, `verifying`, `verified`, `needs_human`, `failed`, `cancelled`.

These are persisted states, not labels inferred from free-form model prose. The contract sets the following progression and gates:

1. Ingest an authenticated GitHub or deployment event durably with idempotency and bounded job retry.
2. Plan against a snapshotted base SHA; retain a specification hash and the proposed acceptance criteria, risk, file scope, steps, design and rollback description.
3. Bind a human's GitHub approval comment to the specification revision. Configured approvers are checked through live GitHub identity and repository permission; Hermes never posts approval on their behalf.
4. Implement inside a unique run workspace. Enforce target path allowlists outside the LLM. Model changes are data, not executable instructions.
5. Run configured deterministic checks and independent model review before publication. Keep failure/unavailable evidence distinct from success.
6. Publish only when explicitly configured, under the verified bot identity. Maintain one stable `sdlc/<run_id>` branch, reconcile an existing PR, never force-push, and stop for human review/merge.
7. Accept bounded revision requests only from authorized configured reviewers for the matching bot-owned run PR and current SHA. Stale/unrelated feedback is not authority to revise.
8. A merged PR moves to awaiting deployment, not verified. Authenticated deployment metadata must match the fixing merge SHA and configured environment.
9. Observe the deployment for the configured interval and gather production evidence. Missing revision correlation, observation time, freshness, coverage or sufficient traffic cannot become success. Persist evidence and terminal outcome independently from request acceptance.

The contract does not establish an autonomous release or rollback state. A rollback description is planning information for human action, not permission to execute it.

## Configuration decisions

The package is `hermes_sdlc/`, Python 3.11 or later, without runtime pip dependencies or a package main entrypoint. Installation creates private configuration/secrets, a Hermes skill and an OS service definition, not a command launcher; it does not modify Hermes gateway configuration. Administrators supervise the absolute checkout path `hermes_sdlc/service.py` with system Python and no arguments. It reads `HERMES_SDLC_CONFIG` or defaults to `~/.hermes/sdlc/config.json`, outside target repositories.

Trusted configuration includes state directory; receiver host/port (contract default loopback on 8645); GitHub/deployment secret **file paths**, never literal values in this documentation; Hermes Python/source locations; optional model/provider; project source and base branch; approvers and bot identity; publication opt-in; allowed paths; named argv checks and timeouts; sandbox image; required CI checks; production checks and observation seconds. Limits cover model/check timeouts, attempts, claim leases, files, context/output bytes and model calls. Operators stop/start the service to pause/resume processing.

The configuration loader validates/normalizes defaults. Publication cannot be enabled without a configured bot login that matches the authenticated GitHub actor. No secret values are logged or returned. Configuration and model context must not acquire secrets from the target checkout.

## Runtime adapter contract

The agreed adapter exports `AdapterError` and `Runtime(config)` with these operations:

- `propose(stage, context) -> dict`: invoke a bounded Hermes subprocess through `hermes_bridge.py`, JSON stdin/stdout, using the configured Hermes interpreter. Return `proposal`, `usage`, `model` and `tools_enabled`. Resolve installed provider/auth without exposing credentials. Instantiate the agent without enabled toolsets, memory/context loading or automatic tool hooks; reject unexpected tools. Enforce hard timeout/output caps and terminate the subprocess tree. Validate an object response; at most one JSON fence may be stripped.
  - Plan: `summary`, `acceptance: list[str]`, `risk: low|medium|high`, `files: list[str]`, `steps: list[str]`, `design`, `rollback`.
  - Implement/revise: `summary`, `changes: [{path, content: str|null}]`; null denotes deletion.
  - Review: `verdict: pass|fail`, `findings: list[str]`.
  - Issue text and repository contents remain untrusted input throughout.
- `prepare(project, run_id, base_sha=None) -> Path`: unique clone under the state directory's `workspaces/run_id`, pinned base and disabled unsafe Git hooks; resume an existing workspace rather than modifying a shared checkout. No credentials copied into check containers.
- `git(workspace, *args) -> str`: checked bounded Git subprocess, hooks disabled, no shell.
- `check(project, workspace) -> list[dict]`: all configured checks execute, even if one fails; no checks is an error. Return name, pass/fail, exit code, output and duration. Docker is nonroot with no network, capabilities or privilege escalation; read-only root and resource limits. Stage beneath the trusted state directory, excluding Git metadata, symlinks and credentials. Mount input read-only and copy it into capped container tmpfs. The image must provide `/bin/sh` and `cp`. Docker startup failures are infrastructure failures, not requests for the model to rewrite application code.
- `publish(project_name, project, run_id, workspace, title, body) -> dict`: verify bot identity, reconcile stable branch/PR, publish without force push and preserve human merge. Return PR number, URL and head SHA. If publication is disabled, number/URL are null and there are no network writes; this is not a published PR.
- `github(method, path, body=None)`: bounded `gh api`, payload through stdin, no shell, caller-controlled API paths.
- `identity() -> str`: verify the configured GitHub App through `/app` and derive `<slug>[bot]`; administrator-only runtimes use the operator's `gh api /user` login. Installation tokens are cached in memory, renewed before expiry, and injected only into GitHub API/Git network subprocesses.
- `production(project, deployment) -> list[dict]`: only configured typed checks; no checks is an error. HTTP checks require expected status and an exact revision JSON pointer. Loki requires error, traffic, revision, freshness and coverage queries, token environment-variable name, minimum traffic and maximum errors. Query from observed deployment through the current window; reject stale, incomplete, nonfinite or revision-uncorrelated evidence. Missing telemetry is inconclusive. Deployment evidence includes SHA, environment, deployment time, ID and repository; source authentication belongs to ingestion. External stderr must not leak credentials.

## Evidence and implementation distinction

[Enterprise research](enterprise-research.md) supplies examples and explicitly labeled recommendations, not proof of this implementation. [The gap analysis](hermes-gap-analysis.md) preserves historical findings; its old line numbers describe audit-time recipes and are not claims about the new controller after integration.

Current GitHub actions and historical exercised results live in [operations](operations.md) and [lifecycle evidence](lifecycle-example.md), respectively. Human `/sdlc recover RUN plan|revise|verify` comments request a new bounded attempt recorded in history: revise a pre-implementation specification, retry within approved file scope or reobserve the same authenticated deployment. Normal PR request-changes reviews remain the revision route. Recovery never converts missing evidence into success. Evaluation remains a maintainer Python library, not a user command.

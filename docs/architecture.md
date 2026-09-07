# Kira SDLC architecture

Kira is a Python control plane for human-approved software changes. Hermes supplies tool-free proposals; the controller owns authority, state, file writes, checks and GitHub actions.

[Overview](../README.md) · [Operations](operations.md) · [Security](security-model.md)

## Components

| Component | Responsibility |
| :--- | :--- |
| `config.py` | Host-owned project policy, approvers, credentials, checks and limits |
| `server.py` | Signed, bounded GitHub and deployment event intake |
| `store.py` | SQLite runs, jobs, approvals, evidence and fenced leases |
| `engine.py` | Planning, approval gates, implementation, revision and verification |
| `hermes_bridge.py` | Isolated, tool-free model calls through the installed Hermes runtime |
| `github_app.py` | App identity, repository-scoped installation tokens and renewal |
| `adapters.py` | Git, GitHub, Docker checks and HTTP/Loki evidence |
| `incidents.py` | Grafana, CI and ArgoCD normalization and stable incident identity |
| `github_setup.py` | Operator-owned GitHub labels, webhook and branch policy |

These modules live in `hermes_sdlc/`. The package uses Python 3.11+ and the standard library; inference runs in the authenticated Hermes virtual environment.

## Incident intake

Grafana and ArgoCD send to `/webhooks/incidents/NAME`. Host-owned `incident_sources` binds each name, secret and provider to a project; the payload cannot choose another repository. GitHub CI failures use the normal signed GitHub endpoint and explicit project workflow selection.

The controller creates a Kira-owned issue, gathers bounded read-only evidence and enters the ordinary planning job. CI evidence includes the live attempt's jobs/logs; CI and ArgoCD can include the referenced Git commit; Grafana and ArgoCD use host-owned Loki selectors. The model explains root cause and uncertainty in the plan. Terraform alert tuning, CI configuration and application changes share the exact-spec approval gate, file-scope enforcement, isolated checks and PR review.

Repeated observations append evidence without changing the original task or approved scope. Recovery signals do not start new remediation; missing logs or deployment proof never establish recovery. These integrations do not invoke tool-enabled gateway agents.

## Workflow and authority

| Stage | Controller action | Required authority or evidence |
| :--- | :--- | :--- |
| Intake | Persist an event and schedule work. | Valid signature, delivery identity and authorized actor |
| Plan | Pin a base commit and publish a specification. | Summary, acceptance criteria, scope, steps, risk, design and rollback |
| Approve | Bind a canonical plan checkbox edit to the specification hash. | Live authorized human editor, exact old/new/live body and matching run issue/comment |
| Implement | Apply validated changes in a unique workspace. | Approved file scope and configured limits |
| Check | Run deterministic checks and independent model review. | All configured checks and review must pass |
| Publish | Reconcile a stable `sdlc/RUN` branch and PR. | Explicit publication policy and verified App identity |
| Revise | Repair the current PR within approved scope. | Authorized, current-head feedback or matching failed CI |
| Merge | Verify a merge already performed by a human. | Verified head, authorized merger and successful required CI |
| Observe | Evaluate the deployed revision. | Authenticated deployment, matching SHA/environment and live evidence |

Kira does not merge, deploy or execute rollback. A rollback plan describes a human action; it does not grant permission to perform it.

## Durable state

Run states are explicit values, not interpretations of model prose:

```text
queued → planning → awaiting_approval
                    ↓
               implementing → awaiting_review
                                   ↓
                          awaiting_deployment
                                   ↓
                              verifying → verified
```

Failures or missing evidence can stop a run in `needs_human`, `failed` or `cancelled`. A human may request a bounded recovery attempt from an eligible state.

SQLite persists runs, jobs, approvals and append-only evidence. Transactional claims and fenced leases prevent an expired worker from completing reassigned work. Stable delivery, branch and comment identifiers support reconciliation after retries.

**HTTP 202 means durably accepted—not completed.** SQLite cannot undo an external GitHub side effect; retries reconcile it rather than promising distributed exactly-once execution.

## Specification and proposals

A specification contains:

- Summary, acceptance criteria and exact file scope
- Risk, implementation steps, design and rollback
- Pinned base SHA and specification revision

The controller fingerprints that object. A human checks the approval control on the canonical plan comment; the controller binds that edit to the exact stored revision and SHA-256 digest. The user does not copy a hash. A revised draft requires new approval.

One bot-owned GitHub comment presents the current plan and state. SQLite stores its ID, exact rendering, body hash, revision and specification hash; append-only evidence retains previous specifications and projections. The oldest genuine legacy plan can be adopted without creating another comment. Replanning PATCHes the canonical comment and clears approval.

Ordinary authorized issue comments before approval schedule bounded replanning. In-flight planning defers feedback and early checkbox events through the existing durable event queue. Checkbox approval compares the webhook's previous body and live updated body against the exact canonical rendering, then atomically checks the current stored projection and specification. Only the designated unchecked-to-checked action is permitted. Approval locks scope; subsequent implementation feedback uses native PR reviews.

| Model stage | Structured result |
| :--- | :--- |
| Plan | `summary`, `acceptance`, `risk`, `files`, `steps`, `design`, `rollback` |
| Implement / revise | `summary`, `changes: [{path, content}]`; `null` content requests deletion |
| Review | `verdict: pass\|fail`, `findings` |

Repository files, issue text and review comments remain untrusted. The model has no tool-execution authority. The host validates scope and output before applying any change.

## Runtime boundaries

**Workspaces.** Each run receives an isolated clone under the private state directory. The configured canonical GitHub source supplies fresh task checkouts; the run pins its base SHA. Git commands disable unsafe hooks and do not evaluate a shell.

**Checks.** Trusted configuration supplies argument arrays. Docker receives a read-only staged copy, without credentials, Git metadata or symlinks. It runs nonroot, without network, capabilities or privilege escalation, under resource limits. Infrastructure failures are not requests for the model to rewrite application code.

**GitHub.** The controller verifies the configured App through `/app` and derives `<slug>[bot]`. Installation tokens are restricted to explicit repository IDs, held in memory and renewed before expiry. Only GitHub API and Git network subprocesses receive them. Infrastructure provisioning uses the operator's separate `gh` authentication.

**Publication.** A disabled project performs no external publication. An enabled project publishes only to its configured repository, without force-pushing. Human review and repository protection remain required.

## Production evidence

Merge and deployment are separate events. Verification requires the exact merge SHA, configured environment, actual deployment identity and timestamp, plus the configured observation interval.

- **HTTP:** expected status and an exact revision JSON pointer. Redirects are rejected.
- **Loki:** error, traffic, revision, freshness and coverage queries tied to the deployment and observation window.

Missing, stale, nonfinite or incomplete evidence cannot pass. Health at one endpoint is not proof of all application behavior. The operator must choose evidence appropriate to the application's risk.

## Configuration and hosting

The service entrypoint is `hermes_sdlc/service.py`. It reads `HERMES_SDLC_CONFIG` or `~/.hermes/sdlc/config.json`; trusted configuration and state live outside task checkouts.

The default receiver binds `127.0.0.1:8645`. Public access requires signed requests and a bounded TLS reverse proxy. Service supervisors own startup and restart; see [deployment options](operations.md#deployment).

# Issue intake and approved implementation

Issue implementation now belongs to the [durable SDLC controller](../../docs/ai-sdlc/operations.md), not a prompt that interpolates issue text into a shell command. The former `configure-route.py` has been removed.

- Ask Hermes to plan a task; its built-in terminal uses `gh issue create/view/comment` and `gh pr view`. Authorized human issue creation or `ready-to-fix` labeling queues a plan.
- Bot-created/`auto-triaged` issue creation is ignored to prevent RCA loops.
- Label application verifies the actor's configured identity and current repository permission. It does not approve code execution.
- The human reviews requirements, exact files, design, rollback and acceptance criteria, then posts `/sdlc approve RUN HASH` on the matching issue/PR. Hermes never posts approvals, merges or deploys for humans.
- The tool-free model proposes files; the controller checks scope, runs sandbox verification, independently reviews and prepares a branch/optional bot PR.
- Normal current-head PR request-changes reviews revise that same run/PR within a bounded budget. Humans request `/sdlc status RUN`, `/sdlc cancel RUN` or `/sdlc recover RUN plan|revise|verify` on the matching issue/PR, with optional multiline recovery feedback.

Remove the old `github-issue-triage` gateway route and webhook subscription. Subscribe GitHub lifecycle events to the SDLC receiver's `/webhooks/github` on its separate port (default 8645). Existing Grafana/CI/Argo RCA subscriptions remain separate.

There is no lifecycle command CLI. Administrators supervise the Python receiver separately. Live plan/status comments and PR publication require a dedicated configured bot; publication remains disabled until that prerequisite is met. Local historical evidence does not prove live GitHub integration.

See [security](../../docs/security-model.md), [operations](../../docs/ai-sdlc/operations.md) and the [historical audit](../../docs/ai-sdlc/hermes-gap-analysis.md) for rationale.

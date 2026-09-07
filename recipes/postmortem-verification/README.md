# Deployed-revision verification

Verification now belongs to the [durable SDLC controller](../../docs/ai-sdlc/operations.md). The earlier JSONL append/sweep installer was removed: it had no transactional record/sweep protocol, treated HTTP 202 as processed, and assumed a gateway `script` hook absent from the inspected installed Hermes runtime.

The replacement requires:

1. A lifecycle-owned, checked commit and a human-performed merge.
2. Authenticated GitHub deployment-success events or a signed `/webhooks/deployment` receipt for that exact merge SHA and configured environment; never a conversational claim or local acknowledgment command.
3. A completed post-deployment observation window.
4. Configured live evidence: HTTP health with running revision, or Loki error/traffic/revision evidence.
5. A persisted terminal outcome. Missing telemetry is inconclusive, never recovery.

The worker records results in SQLite evidence and posts an idempotent verification comment when bot publication is enabled. Only an issue whose live GitHub author is the configured bot may be closed/reopened automatically. Human-owned issues receive comments only.

Remove `postmortem-record` and `postmortem-verify` from the old gateway configuration, remove their subscriptions and verification cron, and retain old state files for audit. Review/resubmit unfinished jobs explicitly; a line in `processed.jsonl` proves only that an HTTP request was accepted.

Humans inspect status with `/sdlc status RUN` on the matching issue/PR and request a new observation attempt with `/sdlc recover RUN verify`, optionally followed by multiline feedback. Recovery retains authentic deployment identity; it does not fabricate a deployment. Hermes can show issue/PR evidence through built-in terminal `gh` reads, but cannot approve, merge or deploy for a human. There is no lifecycle CLI; operators stop/start the Python background service for maintenance.

Live GitHub publication remains disabled until a dedicated bot and repository policy are configured. External deployment and telemetry integration must be configured and exercised separately; the archived local example is not proof of those integrations. Full configuration and human/event contracts: [operations](../../docs/ai-sdlc/operations.md).

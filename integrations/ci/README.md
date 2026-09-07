# CI failure investigation

Failed workflows enter **Kira's controller**, not a separate tuning agent. Kira reads the live run, failed jobs and attempt-specific logs, then plans either an application fix or a justified CI-configuration correction.

[Overview](../../README.md) · [Operations](../../docs/operations.md) · [Security](../../docs/security-model.md)

## Configure

Use the application's existing Kira GitHub webhook at `/webhooks/github` (or `/kira/webhooks/github` behind the shared ingress), subscribed to **Workflow runs**. No second CI webhook or gateway route is needed.

Add explicit workflow names to the application's private project configuration:

```json
{
  "incident_ci_workflows": ["Build", "Test"]
}
```

Names must match GitHub's `workflow_run.name`. An empty list disables new CI incident intake. Kira's GitHub App needs access to the application repository and read access to Actions, alongside its normal issue/PR permissions. Restart the controller after configuration changes.

If Kira should propose workflow-file changes, explicitly allow the relevant directory, such as `.github/workflows/`, in that project's `allowed_paths`. Use checks appropriate to the actual CI configuration. Workflow-file publication also requires the App's GitHub **Workflows write** permission; do not grant it for projects that only need application-code fixes.

## One controlled workflow

1. A completed failed run in a selected workflow is checked against its live repository, SHA and attempt.
2. Kira creates an incident issue and gathers job metadata and failed-step logs without giving the model terminal access.
3. The plan distinguishes a regression, flaky test, external dependency or CI configuration problem. It must not weaken a real test to hide an application defect.
4. A human approves the exact file scope and specification hash.
5. Kira implements, checks and opens the PR. A human reviews and merges.

Duplicate deliveries for an attempt do not create independent implementation work. Fork-origin runs and `sdlc/` branches cannot create fresh CI incidents. A failed required workflow on an existing Kira PR follows that run's bounded revision path and remains inside its already-approved scope; it does not create a recursive tuning agent.

Verify with a known failed run in an opted-in workflow: inspect the Kira incident and plan, and confirm that implementation waits for human approval. A workflow retry is a distinct attempt; stale events cannot substitute a different live attempt.

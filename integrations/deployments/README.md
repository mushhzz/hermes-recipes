# Deployment failure investigation

ArgoCD sync failures and health degradation enter **Kira's controller**. Kira investigates the deployed revision and configured Loki evidence, then proposes a reviewed change. It never edits the live cluster, performs a rollback or runs a separate deployment agent.

[Overview](../../README.md) · [Operations](../../docs/operations.md) · [Security](../../docs/security-model.md)

## Configure intake

Onboard the application repository in Kira and its GitHub App installation. Merge this entry into the private controller configuration:

```json
{
  "incident_sources": {
    "argocd": {
      "provider": "argocd",
      "project": "OWNER/APP",
      "secret_file": "/absolute/private/path/argocd.secret"
    }
  }
}
```

The secret file must contain at least 32 characters, live outside the checkout and be readable only by the service account. Restart the controller after configuration changes.

Merge [the notification configuration](argocd-notifications-patch.yaml.example) into the GitOps source for ArgoCD Notifications and the affected Applications. Set the public URL to `/kira/webhooks/incidents/argocd`, or `/webhooks/incidents/argocd` on a separately bounded controller ingress. Applications with self-healing will revert live annotation edits, so update their versioned manifests.

ArgoCD sends its secret in **`X-Gitlab-Token`**. This is a constant-time static-token comparison, **not HMAC**: ArgoCD Notifications does not compute a digest of its request body. Require TLS, protect the Kubernetes Secret and rotate it if exposed. A captured token remains replayable until rotation.

Configure the project's `incident_loki` using the [Grafana evidence setup](../grafana/README.md#configure-read-only-evidence), with host-owned selectors for the actual application namespace. The controller never executes a query or URL supplied by an incident payload.

## Event contract

The receiver acts on `reason: "sync-failed"` or `"health-degraded"`. Supply nonempty `app`, `namespace`, `revision` and `startedAt`; the example includes sync/health status, failure message and finish time as investigation context. Use separate source names and secrets when routing to different repositories.

Repeated observations for the same application, revision, start time and reason attach to the same run without changing its approved specification. Healthy/recovery notifications do not initiate remediation. An ArgoCD failure signal is **not** a successful-deployment receipt.

## Review remediation

Kira's plan must distinguish:

- A defect introduced by the deployed revision
- An existing weakness exposed by the deployment
- An unrelated infrastructure failure

A revert may be proposed as a versioned change, with the cost of losing other changes explained. It still requires the normal exact-plan approval, checks and human PR review. Cluster actions and deployment remain the operator's release responsibility.

To verify setup, send a representative authenticated failure payload, inspect the Kira incident and evidence, and confirm it stops at plan approval. Do not break a real deployment solely to test notification wiring. Verify successful deployment separately using the authenticated receipt contract in [Operations](../../docs/operations.md).

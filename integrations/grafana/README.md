# Grafana alerts and tuning

Grafana alerts enter **Kira's controller**. Kira collects read-only Loki evidence, investigates the source revision and publishes a plan on a GitHub issue. Application fixes and Terraform alert tuning use the same exact-plan approval, isolated checks and human PR review.

[Overview](../../README.md) · [Operations](../../docs/operations.md) · [Security](../../docs/security-model.md)

## What Kira can tune

When evidence shows the alert configuration itself is wrong, Kira can propose thresholds, `for` durations, noise exclusions, grouping labels, annotations or a new rule. It must not hide an application defect by weakening the alert.

The included [Terraform module](terraform/) manages rules, notification policy and a signed contact point. Kira never applies Terraform or edits live Grafana. Your release process applies a human-reviewed change.

## Configure intake

First onboard the **application repository** in Kira's private configuration and GitHub App installation. Do not send application alerts to an unrelated controller-source repository. Configure approvers, exact writable directories and checks suitable for Terraform as well as application code.

Merge this source into the host-owned `~/.hermes/sdlc/config.json`:

```json
{
  "incident_sources": {
    "grafana": {
      "provider": "grafana",
      "project": "OWNER/APP",
      "secret_file": "/absolute/private/path/grafana.secret"
    }
  }
}
```

The secret file must be outside the checkout, accessible only to the service account, and contain at least 32 characters. Use the same secret in the Grafana contact point. Restart the controller after configuration changes.

Send notifications to `/webhooks/incidents/grafana`, or `/kira/webhooks/incidents/grafana` through the supplied shared ingress. Sign the exact request body with hexadecimal HMAC-SHA256 in **`X-Webhook-Signature`**; no timestamp prefix is used. Both standard Grafana grouped alerts and the module's enriched payload are accepted. Resolved notifications do not start work.

Each source name binds to one configured project. For multiple applications, configure distinct source names, secrets and contact points. A repository named in alert text cannot change routing.

## Configure read-only evidence

Add `incident_loki` to that application's project entry:

```json
{
  "incident_loki": {
    "url": "https://YOUR-STACK.grafana.net/api/datasources/proxy/uid/YOUR-LOKI-UID",
    "token_file": "/absolute/private/path/loki-viewer.token",
    "queries": ["{service_name=\"YOUR_SERVICE\"} | detected_level=\"error\""],
    "window_seconds": 7200,
    "limit": 100
  }
}
```

Use a **separate read-only service-account token** with datasource access. Keep it outside the checkout in a private file. The controller performs bounded GET requests using only these host-configured queries—not URLs or commands from alert annotations. It records the observation window and flags missing or truncated evidence.

The standalone [Loki query helper](../../scripts/loki-query.sh) and [formatter](../../scripts/loki-format.py) remain available for operators; the controller does not give them to an autonomous gateway agent. The helper reads `GRAFANA_URL` and `GRAFANA_LOKI_TOKEN` from a private `grafana.env` file selected by `GRAFANA_ENV_FILE`, plus `LOKI_DATASOURCE_UID` and `LOKI_SERVICE_NAME` from the environment.

## Apply alert definitions

Run from `integrations/grafana/terraform/`, or copy the complete module into your application's versioned alerting directory:

```bash
cp terraform.tfvars.example terraform.tfvars
cp backend.tf.example backend.tf
# Fill in your real instance, datasource, service labels and Kira intake URL.
# Supply GRAFANA_AUTH and TF_VAR_hermes_route_secret securely in the environment.
tofu init
tofu plan
tofu apply
```

Use a Terraform-scoped Grafana token for this operator/release step, **not** the investigation token. Configure a protected backend: state can contain contact-point secrets. A notification policy resource owns the whole policy tree; reconcile existing receivers before applying. The resource addresses and input names are stable configuration interfaces.

Adapt the example LogQL rules to actual labels and known-benign errors. Guard annotations for potentially absent labels with `{{ if $labels.x }}...{{ end }}`. Include the real Terraform directory in `allowed_paths`; the approved plan narrows it to exact files. Provide a trusted check image with Terraform/OpenTofu and cached providers because Kira's checks have no network access.

## Verify the flow

Send a signed representative firing payload to the configured source and verify:

1. HTTP acceptance produces a durable Kira incident and GitHub issue.
2. The plan contains a diagnosis, evidence gaps, file scope and verification criteria.
3. No branch or tuning PR is created before a human approves the exact hash.
4. Repeat observations with the same alert identity and start time attach to the existing run without changing its approved task.
5. After human approval, checks and review govern the proposed fix. Terraform application remains a separate release action.

An accepted webhook or empty Loki result is not proof of recovery. Production verification needs the separately configured revision-correlated checks described in [Operations](../../docs/operations.md).

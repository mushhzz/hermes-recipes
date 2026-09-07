# How alerts reach Hermes:
#
#   rule fires -> notification policy (hermes_triage=true, or namespace=var.namespace
#                 from your cluster's own Kubernetes-integration alerts, if any)
#              -> contact point hermes-webhook
#                 POST ${var.hermes_webhook_url}
#                 X-Webhook-Signature = hex HMAC-SHA256(secret, body)
#              -> your Hermes gateway (route grafana-error-triage)
#
# Signature format matters: Grafana signs `body` only when no timestamp header is
# configured, which is exactly Hermes' generic X-Webhook-Signature scheme. Do NOT
# add timestamp_header: Grafana would then sign `timestamp:body` while Hermes'
# V2 scheme expects `timestamp.body`, and every delivery would be rejected 401.

resource "grafana_folder" "alerting" {
  uid   = "hermes-rca-alerts"
  title = "Hermes RCA"
}

# Structured evidence sent to Kira's authenticated Grafana incident source.
# Resource addresses and template names remain stable configuration interfaces.
resource "grafana_message_template" "hermes_payload" {
  name     = "hermes-payload"
  template = file("${path.module}/templates/hermes-payload.tmpl")
  # No disable_provenance here: toggling it forces a destroy/create of the
  # template, which would briefly break the contact point that renders it.
}

resource "grafana_contact_point" "hermes_webhook" {
  name               = "hermes-webhook"
  disable_provenance = true

  webhook {
    url                     = var.hermes_webhook_url
    http_method             = "POST"
    max_alerts              = 5
    disable_resolve_message = true # Kira initiates investigation only for firing alerts.

    hmac_config {
      secret = var.hermes_route_secret
      header = "X-Webhook-Signature"
    }

    payload {
      template = "{{ template \"hermes.payload\" . }}"
    }
  }

  depends_on = [grafana_message_template.hermes_payload]
}

# The whole policy tree. Root stays on Grafana's default email receiver; two
# child routes send incident evidence to Kira.
resource "grafana_notification_policy" "root" {
  contact_point      = "grafana-default-email"
  group_by           = ["grafana_folder", "alertname"]
  disable_provenance = true

  # Rules defined in rules.tf: one notification per alertname + environment +
  # error type, re-sent at most every 4h while still firing.
  policy {
    contact_point   = grafana_contact_point.hermes_webhook.name
    group_by        = ["alertname", "deployment_environment", "error_type"]
    group_wait      = "30s"
    group_interval  = "5m"
    repeat_interval = "4h"
    continue        = false

    matcher {
      label = "hermes_triage"
      match = "="
      value = "true"
    }
  }

  # Optional: if your cluster already has Kubernetes-integration alerts
  # (KubePodCrashLooping, KubePodNotReady, ...) managed elsewhere, route the
  # ones for your namespace to Hermes too, without needing hermes_triage on
  # every one of those rules individually. Delete this block if you don't
  # have such rules, or they aren't labelled with namespace/severity.
  policy {
    contact_point   = grafana_contact_point.hermes_webhook.name
    group_by        = ["alertname", "namespace", "pod"]
    group_wait      = "1m"
    group_interval  = "10m"
    repeat_interval = "6h"
    continue        = false

    matcher {
      label = "namespace"
      match = "="
      value = var.namespace
    }
    matcher {
      label = "severity"
      match = "=~"
      value = "warning|critical"
    }
  }
}

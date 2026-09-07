# Grafana alerting managed as code, wired to notify a Hermes gateway.
#
# This is deliberately a separate Terraform root module from whatever manages
# your actual application infrastructure: it authenticates to a different
# system (Grafana, not your cloud provider), changes far more often once an
# agent starts proposing alert-tuning PRs, and should never be blocked by or
# block an infra plan for an unrelated system.
#
# Local usage:
#   export GRAFANA_AUTH=glsa_...                    # Grafana service-account token (Editor or Admin)
#   export TF_VAR_hermes_route_secret=...            # HMAC secret shared with the Hermes route
#   tofu init && tofu plan
#
# Configure a real backend (see backend.tf.example) before using this for
# anything beyond a local trial — local state is not durable and not safe to
# share between a human and an agent that might also plan/apply.
terraform {
  required_version = ">= 1.6"

  required_providers {
    grafana = {
      source  = "grafana/grafana"
      version = "~> 4.45"
    }
  }
}

provider "grafana" {
  url = var.grafana_url
  # auth comes from GRAFANA_AUTH in the environment (service-account token).
}

variable "grafana_url" {
  description = "Grafana (Cloud or self-hosted) instance URL."
  type        = string
}

variable "hermes_webhook_url" {
  description = "Hermes gateway route that receives alert notifications, e.g. https://<your-domain>/webhooks/grafana-error-triage"
  type        = string
}

variable "hermes_route_secret" {
  description = "HMAC-SHA256 secret shared with the Hermes route grafana-error-triage. Set via TF_VAR_hermes_route_secret; never commit it."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.hermes_route_secret) >= 32
    error_message = "hermes_route_secret must be at least 32 characters (use: openssl rand -hex 32)."
  }
}

variable "loki_datasource_uid" {
  description = "UID of the Loki datasource holding your application's logs."
  type        = string
}

variable "app_service_name" {
  description = "The service_name label your application's structured (OTel) logs are shipped under."
  type        = string
}

variable "frontend_service_name" {
  description = "The service_name label your frontend/proxy container's logs are shipped under."
  type        = string
}

variable "namespace" {
  description = "Kubernetes namespace your application runs in (used for the frontend rule's log filter and to route existing cluster alerts to Hermes)."
  type        = string
}

variable "runbook_url" {
  description = "URL of the runbook these alerts should link to (e.g. a doc in your repo explaining what Hermes does with them)."
  type        = string
  default     = ""
}

# Example alert rules for a deployed application, wired to notify Hermes for
# root-cause analysis. These are starting points to copy and adapt, not a
# drop-in for your own error taxonomy — the specific error_type values and
# thresholds below (TooManyConnectionsError, "5 in 10m", etc.) came from one
# real application and almost certainly don't match yours.
#
# All rules here are LogQL against Loki. If you scrape Prometheus metrics
# from your app, add a rate/latency/SLO-burn rule alongside these — that's
# usually a better signal than "an error log line exists" once you have it.

locals {
  # Absent labels render as "[no value]" in annotations unless guarded, which
  # can turn a suggested Loki query into a filter that matches nothing — see
  # ../../../docs/lessons-learned.md. Guard every optional label this way.
  error_type_or_unclassified = "{{ if $labels.error_type }}{{ $labels.error_type }}{{ else }}Unclassified{{ end }}"
  error_type_or_empty        = "{{ if $labels.error_type }}{{ $labels.error_type }}{{ end }}"

  threshold_gt = {
    for n in [0, 3, 5] : n => jsonencode({
      refId      = "C"
      type       = "threshold"
      expression = "A"
      conditions = [{ evaluator = { type = "gt", params = [n] } }]
    })
  }
}

resource "grafana_rule_group" "app_errors" {
  name               = "app-errors"
  folder_uid         = grafana_folder.alerting.uid
  interval_seconds   = 60
  disable_provenance = true

  # ---------------------------------------------------------------------------
  # Any error-level log record from the app, excluding known-benign noise.
  # Adjust the excluded-noise filter below to your own expected/recoverable
  # error signatures (e.g. auth failures from bots, validation rejections).
  rule {
    name           = "AppBackendErrors"
    uid            = "app-backend-errors"
    condition      = "C"
    for            = "0s"
    no_data_state  = "OK"
    exec_err_state = "Error"
    is_paused      = false

    labels = {
      hermes_triage = "true"
      severity      = "warning"
      service       = "app-backend"
    }

    annotations = {
      summary     = "${local.error_type_or_unclassified} errors in {{ $labels.deployment_environment }} ({{ $values.A.Value }} in 10m)"
      description = "The backend logged {{ $values.A.Value }} error-level records of type '${local.error_type_or_unclassified}' in environment '{{ $labels.deployment_environment }}' during the last 10 minutes. Records without an error_type are usually log.error calls that interpolate details into the message instead of passing structured metadata; query them with error_type=\"\"."
      loki_query  = "{service_name=\"${var.app_service_name}\", deployment_environment=\"{{ $labels.deployment_environment }}\"} | detected_level=\"error\" | error_type=\"${local.error_type_or_empty}\""
      runbook_url = var.runbook_url
    }

    data {
      ref_id         = "A"
      datasource_uid = var.loki_datasource_uid
      query_type     = "instant"
      relative_time_range {
        from = 600
        to   = 0
      }
      model = jsonencode({
        refId      = "A"
        editorMode = "code"
        queryType  = "instant"
        # Replace the noise exclusion below with your own known-benign
        # error_message pattern, or remove it if you have none yet.
        expr = "sum by (deployment_environment, error_type) (count_over_time({service_name=\"${var.app_service_name}\"} | detected_level=\"error\" | error_message !~ \"(?i).*(known benign pattern here).*\" [10m]))"
      })
    }
    data {
      ref_id         = "C"
      datasource_uid = "__expr__"
      query_type     = ""
      relative_time_range {
        from = 0
        to   = 0
      }
      model = local.threshold_gt[0]
    }
  }

  # ---------------------------------------------------------------------------
  # Example of a specific, high-value failure signature worth its own rule
  # and higher severity: a database connection pool exhausting itself. Adapt
  # the error_type value and thresholds to a failure mode that matters in
  # your own system, or delete this rule if AppBackendErrors covers it well
  # enough.
  rule {
    name           = "AppDatabaseConnectionExhaustion"
    uid            = "app-db-connection-exhaustion"
    condition      = "C"
    for            = "2m"
    no_data_state  = "OK"
    exec_err_state = "Error"
    is_paused      = false

    labels = {
      hermes_triage = "true"
      severity      = "critical"
      service       = "app-backend"
    }

    annotations = {
      summary     = "Database connections exhausted in {{ $labels.deployment_environment }} ({{ $values.A.Value }} failures in 5m)"
      description = "The backend is failing to obtain database connections. Requests are failing. Check pool sizing, leaked sessions/transactions, and the database's own connection limit."
      loki_query  = "{service_name=\"${var.app_service_name}\", deployment_environment=\"{{ $labels.deployment_environment }}\"} | detected_level=\"error\" | error_type=\"TooManyConnectionsError\""
      runbook_url = var.runbook_url
    }

    data {
      ref_id         = "A"
      datasource_uid = var.loki_datasource_uid
      query_type     = "instant"
      relative_time_range {
        from = 300
        to   = 0
      }
      model = jsonencode({
        refId      = "A"
        editorMode = "code"
        queryType  = "instant"
        expr       = "sum by (deployment_environment) (count_over_time({service_name=\"${var.app_service_name}\"} | detected_level=\"error\" | error_type=\"TooManyConnectionsError\" [5m]))"
      })
    }
    data {
      ref_id         = "C"
      datasource_uid = "__expr__"
      query_type     = ""
      relative_time_range {
        from = 0
        to   = 0
      }
      model = local.threshold_gt[3]
    }
  }

  # ---------------------------------------------------------------------------
  # Frontend/proxy container error volume, with an example noise exclusion
  # for missing-favicon-style requests that aren't real problems.
  rule {
    name           = "AppFrontendErrors"
    uid            = "app-frontend-errors"
    condition      = "C"
    for            = "5m"
    no_data_state  = "OK"
    exec_err_state = "Error"
    is_paused      = false

    labels = {
      hermes_triage = "true"
      severity      = "warning"
      service       = "app-frontend"
    }

    annotations = {
      summary     = "Frontend container logging errors in namespace {{ $labels.k8s_namespace_name }} ({{ $values.A.Value }} in 10m)"
      description = "The frontend/proxy pod emitted more than 5 error-level log lines in 10 minutes for at least 5 minutes. Usually an upstream connectivity or misconfiguration problem."
      loki_query  = "{service_name=\"${var.frontend_service_name}\", k8s_namespace_name=\"${var.namespace}\"} !~ \"favicon.ico\" | detected_level=~\"error|ERROR\""
      runbook_url = var.runbook_url
    }

    data {
      ref_id         = "A"
      datasource_uid = var.loki_datasource_uid
      query_type     = "instant"
      relative_time_range {
        from = 600
        to   = 0
      }
      model = jsonencode({
        refId      = "A"
        editorMode = "code"
        queryType  = "instant"
        expr       = "sum by (k8s_namespace_name) (count_over_time({service_name=\"${var.frontend_service_name}\", k8s_namespace_name=\"${var.namespace}\"} !~ \"favicon.ico\" | detected_level=~\"error|ERROR\" [10m]))"
      })
    }
    data {
      ref_id         = "C"
      datasource_uid = "__expr__"
      query_type     = ""
      relative_time_range {
        from = 0
        to   = 0
      }
      model = local.threshold_gt[5]
    }
  }
}

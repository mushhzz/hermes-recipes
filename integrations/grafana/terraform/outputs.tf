output "folder_url" {
  description = "Grafana folder holding the alert rules this module manages."
  value       = grafana_folder.alerting.url
}

output "contact_point_uid" {
  description = "UID of the Hermes webhook contact point."
  value       = grafana_contact_point.hermes_webhook.id
}

output "rule_uids" {
  description = "UIDs of the managed alert rules."
  value       = [for r in grafana_rule_group.app_errors.rule : r.uid]
}

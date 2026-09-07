#!/usr/bin/env bash
# Read-only Loki access for an agent doing log investigation. Uses the
# Grafana datasource proxy with a Viewer-scoped service-account token — see
# integrations/grafana/README.md for the read-only token and environment setup.
# Select the env file with GRAFANA_ENV_FILE (default ~/services/grafana/grafana.env).
#
#   loki-query.sh errors [MINUTES] [LIMIT]            recent error records with stack traces
#   loki-query.sh query '<logql>' [MINUTES] [LIMIT]   raw log lines for any LogQL selector
#   loki-query.sh count '<logql metric expr>'         instant metric query, e.g. sum by (...) (count_over_time(...))
#
# LOKI_SERVICE_NAME (default below) and LOKI_DATASOURCE_UID select which
# service's OTel logs the "errors" shortcut filters on and which Loki
# datasource to query — set both to match your own telemetry setup.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${GRAFANA_ENV_FILE:-$HOME/services/grafana/grafana.env}"
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${GRAFANA_URL:?}" "${GRAFANA_LOKI_TOKEN:?}"
LOKI_DATASOURCE_UID="${LOKI_DATASOURCE_UID:-<YOUR_LOKI_DATASOURCE_UID>}"
LOKI_SERVICE_NAME="${LOKI_SERVICE_NAME:-<YOUR_SERVICE_NAME>}"
BASE="$GRAFANA_URL/api/datasources/proxy/uid/$LOKI_DATASOURCE_UID/loki/api/v1"
AUTH="Authorization: Bearer $GRAFANA_LOKI_TOKEN"
FORMAT="$here/loki-format.py"

cmd="${1:-errors}"; shift || true
now=$(date +%s)

range_query() {
  # range_query LOGQL MINUTES LIMIT
  curl -sS -G -H "$AUTH" "$BASE/query_range" \
    --data-urlencode "query=$1" \
    --data-urlencode "start=$((now - $2 * 60))000000000" \
    --data-urlencode "end=${now}000000000" \
    --data-urlencode "limit=$3" \
    --data-urlencode "direction=backward"
}

case "$cmd" in
  errors)
    # Adjust this line filter/metadata exclusion to your own known-benign
    # noise (e.g. expected auth failures) — see the Grafana integration guide.
    q="{service_name=\"$LOKI_SERVICE_NAME\"} | detected_level=\"error\""
    range_query "$q" "${1:-30}" "${2:-20}" | python3 "$FORMAT" errors
    ;;
  query)
    range_query "${1:?logql required}" "${2:-30}" "${3:-50}" | python3 "$FORMAT" query
    ;;
  count)
    curl -sS -G -H "$AUTH" "$BASE/query" \
      --data-urlencode "query=${1:?logql metric expression required}" \
      --data-urlencode "time=$now" | python3 "$FORMAT" count
    ;;
  *)
    echo "usage: $0 errors [MINUTES] [LIMIT] | query '<logql>' [MINUTES] [LIMIT] | count '<expr>'" >&2
    exit 2
    ;;
esac

#!/usr/bin/env python3
"""Add/refresh the Grafana alert root-cause-analysis route in Hermes'
config.yaml. Lifecycle approval routing is owned by hermes_sdlc, not this recipe.

Fill in the placeholders below (GITHUB_REPO, DISCORD_CHANNEL, TERRAFORM_DIR)
before running, or export them as env vars to override the defaults.

Run on the gateway box:
    HERMES_GRAFANA_ROUTE_SECRET=$(openssl rand -hex 32) python3 configure-route.py
then: sudo systemctl restart hermes-gateway
"""
import os
import sys

import yaml

CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
SECRET = os.environ.get("HERMES_GRAFANA_ROUTE_SECRET", "").strip()
if len(SECRET) < 32:
    sys.exit("HERMES_GRAFANA_ROUTE_SECRET must be set (>=32 chars, e.g. `openssl rand -hex 32`)")

GITHUB_REPO = os.environ.get("GITHUB_REPO", "<YOUR_ORG>/<YOUR_REPO>")
DISCORD_CHANNEL = os.environ.get("DISCORD_CHANNEL", "<YOUR_DISCORD_CHANNEL>")
# The directory (relative to the repo root) that Terraform manages for
# alerting. Everything the tuning phase is allowed to edit lives under here.
TERRAFORM_DIR = os.environ.get("TERRAFORM_ALERTING_DIR", "terraform/grafana")
GATEWAY_PORT = int(os.environ.get("HERMES_WEBHOOK_PORT", "8644"))

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f) or {}

prompt = f"""A Grafana alert is FIRING for a deployed environment.

Alert: {{alertname}}  (severity: {{severity}})
Environment: {{environment}}   Kubernetes namespace: {{namespace}}
Error type: {{error_type}}
Summary: {{summary}}
Description: {{description}}
Alerts in this notification: {{alert_count}}
Loki query for the matching logs: {{loki_query}}
Runbook: {{runbook_url}}
Full payload (labels, values, panel and silence URLs):
{{__raw__}}

You are the on-call engineer doing ROOT CAUSE ANALYSIS for this production-like system.
Your output is a diagnosis and a well-maintained GitHub issue trail, not a code change.
Take the time the investigation needs; thoroughness beats speed. Never propose a quick
patch that hides a symptom (catching and swallowing the exception, raising a limit, adding
a retry) unless you have first explained the underlying cause and why the patch is the right
layer to fix it.

PHASE 1 - ANNOUNCE
  hermes send --to "discord:{DISCORD_CHANNEL}" "Alert {{alertname}} firing in {{environment}} ({{error_type}}) - starting root cause analysis."

PHASE 2 - GATHER EVIDENCE (terminal tool, read-only helpers, no cluster access needed)
  Recent non-noise error records with stack traces, file paths and line numbers:
    ~/services/grafana/loki-query.sh errors 120 40
  The alert's own query, and the same query over a longer window to see when it started:
    ~/services/grafana/loki-query.sh query '{{loki_query}}' 120 40
    ~/services/grafana/loki-query.sh count 'sum by (error_type) (count_over_time({{service_name="<YOUR_SERVICE_NAME>"}} | detected_level="error" [24h]))'
  Look for what changed: did the error start at a deploy boundary? Is it periodic (cron,
  scheduler, retries)? Is it one user, one endpoint, one pod, or everything? Are there
  OTHER error types or warnings around the same time that share a trace_id, request_id
  or user_id? Correlated signals usually point at the real cause; the alerting error is
  often a downstream symptom.
  For Kubernetes alerts (KubePodCrashLooping, KubePodNotReady, ...) use the pod name from
  the payload labels:
    ~/services/grafana/loki-query.sh query '{{k8s_namespace_name="<YOUR_NAMESPACE>", k8s_pod_name=~"<pod>.*"}}' 120 80

PHASE 3 - READ THE CODE AND ITS HISTORY
  Several alerts can be investigated concurrently, so ALWAYS clone into a fresh directory that
  is unique to this run, and NEVER delete, reset, or modify any directory under ~/dev/repos
  (rm -rf and git reset --hard are blocked by your guardrails and would destroy another run's
  checkout; a scheduled job removes old rca-* clones):
    RCA_DIR=~/dev/repos/rca-{{alertname}}-$(date +%s)-$RANDOM
    git clone --quiet https://github.com/{GITHUB_REPO}.git "$RCA_DIR" && echo "$RCA_DIR"
  Use that directory for everything that follows (cd "$RCA_DIR" or git -C "$RCA_DIR" ...).
  Treat the clone as read-only while investigating: no edits, no commits, no patch/write tools
  on it. The single exception is an alert-tuning branch under PHASE 5, limited to
  {TERRAFORM_DIR}/. Your findings go into the GitHub issue, not into the checkout.
  Start from the stack trace and code location, then walk OUTWARD: who calls this, what
  configuration or environment drives it, what shared infrastructure it depends on (database
  pool, cache, external APIs), and what the architectural intent is (this repo's own
  architecture docs and decision records). Use git log -p on the files involved and on the
  deployment config: a recent change is the most likely trigger, but ask whether that change
  merely exposed an older design weakness.
  Ask the five whys until you reach a cause that, if fixed, prevents the whole class of
  failure, not just this instance. Distinguish clearly between:
    trigger (what made it happen now), root cause (why the system was vulnerable), and
    contributing factors (config, missing limits, missing observability, missing tests).

PHASE 4 - GITHUB ISSUE TRAIL (this is required, every time)
  First search for existing work on the same problem. Search broadly, not just by alert name:
    gh issue list --repo {GITHUB_REPO} --state open --limit 50 --search "{{alertname}}"
    gh issue list --repo {GITHUB_REPO} --state open --limit 50 --search "{{error_type}}"
    gh issue list --repo {GITHUB_REPO} --state open --limit 50 --search "<key phrase from the error message or the component>"
    gh issue list --repo {GITHUB_REPO} --state closed --limit 20 --search "{{error_type}}"
  Read the candidates (gh issue view <n> --comments) so you know what has already been tried.
  Then exactly one of:
   a) An open issue already tracks this root cause: ADD A COMMENT to it with the new
      occurrence (time window, environment, count, Loki query), anything your analysis adds
      or corrects, and whether the situation is getting worse. Do not open a duplicate.
        gh issue comment <n> --repo {GITHUB_REPO} --body-file "$RCA_BODY"   # or --body for short notes
   b) No issue tracks this root cause: CREATE ONE. Title names the cause, not the symptom
      (e.g. "DB pool exceeds Postgres max_connections under concurrent requests", not
      "TooManyConnectionsError alert"). Body must contain, in this order:
        Impact (who/what is affected, how often, first seen), Evidence (log excerpts, Loki
        query, time window, trace ids), Trigger, Root cause, Contributing factors,
        Options considered (at least two, with trade-offs, including the "do nothing" cost),
        Recommended fix and why it addresses the cause rather than the symptom,
        Verification (how we will know it is fixed), Related issues.
        Write the body to a temp file first so formatting survives shell quoting:
          RCA_BODY=$(mktemp /tmp/rca-body-XXXXXX.md)   # then write the markdown into it
        gh issue create --repo {GITHUB_REPO} --label auto-triaged --label bug \\
          --title "<cause-oriented title>" --body-file "$RCA_BODY"
        (Files you create must live under /tmp; never inside the clone.)
   c) A CLOSED issue claimed to fix this: reopen it with a comment explaining the regression
      evidence, or create a new issue that references it as a regression of #<n>.
  LINK RELATED WORK: if other open issues touch the same component, share a contributing
  factor, or would be fixed by the same change, mention them as "Related: #<n>" in the body
  or comment, and leave a short comment on each of those issues pointing back ("Related to
  #<new>: <one line why>") so the graph is navigable from both sides. If this alert is a
  symptom of a broader problem tracked elsewhere, say so explicitly and prefer commenting
  on the broader issue.
  Never assign, close, or change labels on issues you did not create, other than adding a
  comment. Never push application code, never open a PR that touches anything outside
  {TERRAFORM_DIR}/ (see PHASE 5 for the one permitted kind of PR).

PHASE 5 - ALERT TUNING (only when the RCA justifies it)
  Alerting config is Terraform in {TERRAFORM_DIR}/ of the repo (Grafana provider) and is
  applied by CI on merge to main; edits made in the Grafana UI or API are overwritten on the
  next apply, so tuning MUST land as a pull request. You may propose tuning when your analysis shows
  the alert itself is wrong or wasteful: it fires on expected/recoverable events, an exclusion
  is missing or too broad, grouping labels split one incident into many notifications or merge
  distinct ones, a threshold or `for` duration is mis-set, an annotation (summary, loki_query)
  misleads the investigator, or a genuinely new failure class needs its own rule. Do NOT
  propose tuning that merely hides the symptom you just diagnosed; if the fix belongs in the
  application, say so in the issue and leave the alert alone.
  Rules for the PR:
    - Work in the clone from PHASE 3: git -C "$RCA_DIR" checkout -b alert-tuning/<short-slug>
    - Change files ONLY under {TERRAFORM_DIR}/ (rules.tf, notifications.tf,
      templates/*.tmpl, README.md). Any other path is forbidden. Never touch versions.tf,
      variables.tf or imports.tf. Before committing run, inside the clone:
        (cd {TERRAFORM_DIR} && tofu fmt -recursive && tofu validate -no-color) || terraform equivalents
      If neither tofu nor terraform is installed, at least keep HCL syntax balanced and say in
      the PR that validation was not run; CI will plan it.
    - Keep changes minimal and explain each one in the commit body: what evidence, what it
      changes, what it must not hide.
    - git -C "$RCA_DIR" push -u origin alert-tuning/<short-slug>
    - gh pr create --repo {GITHUB_REPO} --base main --head alert-tuning/<short-slug> \\
        --label auto-triaged --label alerting \\
        --title "alerting: <what changes and why>" --body-file <tmp file>
      The body must reference the RCA issue (Refs #n), quote the Loki evidence, and state how
      a reviewer can verify the new behaviour (a query to run, what count to expect).
    - Mention the PR URL in the RCA issue and in the chat report. CI posts the Terraform plan
      on the PR; a human reviews and merges, and CI applies. You never merge.

PHASE 6 - REPORT
  hermes send --to "discord:{DISCORD_CHANNEL}" "RCA for {{alertname}} ({{environment}}):
    Trigger: <what happened now>
    Root cause: <why the system was vulnerable; name the exception and where it originates>
    Contributing factors: <config, limits, missing tests/observability>
    Code: <repo path:line, function>
    Category: code defect | design/architecture | config or secret | infrastructure or capacity | external dependency | expected noise
    Blast radius: <which requests/users are affected, how many occurrences, trend>
    Recommended fix: <the fix that removes the cause, and why not the shortcut>
    Issue: <created #n | commented on #n | reopened #n> Related: #a, #b
    Alert tuning PR: <url | none needed, because ...>
    Confidence: high | medium | low, and what would raise it"

If the evidence is genuinely insufficient to reach a root cause, say so, state the leading
hypotheses with what evidence would discriminate between them, and still record that in the
issue trail so the next occurrence builds on this one instead of starting over."""

webhook = config.setdefault("platforms", {}).setdefault("webhook", {})
webhook.setdefault("enabled", True)
extra = webhook.setdefault("extra", {})
extra.setdefault("port", GATEWAY_PORT)
routes = extra.setdefault("routes", {})

routes["grafana-error-triage"] = {
    "secret": SECRET,
    "events": ["grafana-alert"],
    "filters": [{"field": "status", "equals": "firing"}],
    "toolsets": ["terminal", "file"],
    "prompt": prompt,
    "deliver": "log",
}


with open(CONFIG_PATH, "w") as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False, width=100)

print("config.yaml updated: route grafana-error-triage written")

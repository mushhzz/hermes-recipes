#!/usr/bin/env python3
"""Add/refresh the ArgoCD deployment-failure RCA route in Hermes' config.yaml.

Fires when ArgoCD Notifications reports a sync failure or a health degradation
for an Application, and investigates whether the JUST-DEPLOYED revision
caused it, merely exposed a pre-existing weakness, or is unrelated (infra
flake). RCA-only, same as recipes/ci-failure-triage: it never touches
application code and never performs a rollback/revert itself — only ever
recommends one, as text, for a human to execute.

Authentication note: ArgoCD Notifications' webhook service can send custom
headers with static or Secret-sourced values, but it cannot compute an HMAC
of its own request body — there is no signing key mixed into the payload.
Hermes' webhook adapter's GitLab-compatible scheme (a header named
X-Gitlab-Token, compared to the route's secret directly, no digest) is a
static-token comparison, and that's exactly what ArgoCD *can* send. This
route deliberately reuses that comparison path rather than pretending
ArgoCD is a GitLab-flavoured sender; it is a real, if slightly weaker,
authentication factor than a true HMAC (a captured token replays until
rotated; a true HMAC signature does not extend that risk to the token
itself), acceptable here because the endpoint is only reachable at all
through your existing tunnel/ingress, same as every other route.

Fill in the placeholders below before running, or export them as env vars.

Run on the gateway box:
    HERMES_ARGOCD_ROUTE_SECRET=$(openssl rand -hex 32) python3 configure-route.py
then: sudo systemctl restart hermes-gateway
and follow ../deployment-failure-rca/README.md to wire ArgoCD Notifications
to send that same secret as X-Gitlab-Token.
"""
import os
import sys

import yaml

CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
SECRET = os.environ.get("HERMES_ARGOCD_ROUTE_SECRET", "").strip()
if len(SECRET) < 32:
    sys.exit("HERMES_ARGOCD_ROUTE_SECRET must be set (>=32 chars, e.g. `openssl rand -hex 32`)")

GITHUB_REPO = os.environ.get("GITHUB_REPO", "<YOUR_ORG>/<YOUR_REPO>")
DISCORD_CHANNEL = os.environ.get("DISCORD_CHANNEL", "<YOUR_DISCORD_CHANNEL>")
NAMESPACE = os.environ.get("NAMESPACE", "<YOUR_K8S_NAMESPACE>")
GATEWAY_PORT = int(os.environ.get("HERMES_WEBHOOK_PORT", "8644"))

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f) or {}

prompt = f"""An ArgoCD deployment just reported trouble.

Application: {{app}}   Namespace: {{namespace}}   Reason: {{reason}}
Sync status: {{syncStatus}}   Health status: {{healthStatus}}   Phase: {{phase}}
Revision (the commit that was just deployed): {{revision}}
Message: {{message}}
Sync started: {{startedAt}}   Finished: {{finishedAt}}
Full payload: {{__raw__}}

You are doing ROOT CAUSE ANALYSIS on this deployment problem. Your central question is:
did the revision above CAUSE this, did it merely EXPOSE a pre-existing weakness (e.g. a
resource limit that only bites at this traffic level, a migration that only matters once
run), or is this UNRELATED infrastructure flake (a node preemption, a transient registry
pull failure)? Getting this distinction right changes whether the right fix is a code
revert, a config change, or nothing at all. Never perform a rollback or revert yourself —
recommend one, as text, and let a human execute it.

PHASE 1 - ANNOUNCE
  hermes send --to "discord:{DISCORD_CHANNEL}" "ArgoCD reports {{reason}} for {{app}}: {{message}} - investigating."

PHASE 2 - GATHER EVIDENCE (terminal tool, read-only helpers)
  Logs from the affected namespace around the sync window:
    ~/services/grafana/loki-query.sh query '{{k8s_namespace_name="{{namespace}}"}} | detected_level=~"error|ERROR"' 60 60
  If the reason is health-degraded rather than sync-failed, also check for crash/restart
  signals specifically:
    ~/services/grafana/loki-query.sh query '{{k8s_namespace_name="{{namespace}}"}} !~ "(?i)authentication failed"' 60 40
  Note whether the errors started exactly at {{startedAt}} (deploy-caused), were already
  present before it (pre-existing, now exposed or just continuing), or started well after
  finishedAt (probably unrelated to this deploy specifically).

PHASE 3 - READ THE DEPLOYED CHANGE AND ITS CONTEXT
  Clone into a directory unique to this run; never touch any other directory under
  ~/dev/repos (a scheduled job cleans up expired clones):
    RCA_DIR=~/dev/repos/rca-deploy-{{app}}-$(date +%s)-$RANDOM
    git clone --quiet https://github.com/{GITHUB_REPO}.git "$RCA_DIR" && echo "$RCA_DIR"
  See exactly what this revision changed relative to the previous one ArgoCD had synced:
    git -C "$RCA_DIR" show --stat {{revision}}
    git -C "$RCA_DIR" log -3 {{revision}}
  Read the changed files for anything that plausibly explains a sync failure (an invalid
  manifest, a missing key a Kustomize overlay expects) or a health degradation (a changed
  readiness/liveness probe, a new required env var, a migration the running image now
  expects). If ArgoCD's own {{message}} names a specific manifest/resource error, start there.

PHASE 4 - GITHUB ISSUE TRAIL (this is required, every time)
  Search broadly first:
    gh issue list --repo {GITHUB_REPO} --state open --limit 50 --search "{{app}} {{reason}}"
    gh issue list --repo {GITHUB_REPO} --state open --limit 50 --search "<the specific error from message>"
    gh issue list --repo {GITHUB_REPO} --state closed --limit 20 --search "<the specific error from message>"
  Then exactly one of:
   a) An open issue already tracks this: comment with the new occurrence.
        gh issue comment <n> --repo {GITHUB_REPO} --body-file "$RCA_BODY"
   b) No issue yet: create one. Title names the cause (e.g. "New readiness probe path
      returns 404 until migration runs", not "app health degraded"). Body, in order: Impact,
      Evidence, Trigger, Root cause, Contributing factors, Options considered (>=2, including
      whether reverting {{revision}} is one of them and its own cost), Recommended fix,
      Verification, Related issues.
        RCA_BODY=$(mktemp /tmp/rca-body-XXXXXX.md)
        gh issue create --repo {GITHUB_REPO} --label auto-triaged --label bug \\
          --title "<cause-oriented title>" --body-file "$RCA_BODY"
   c) A closed issue claimed to fix a related problem: reopen it with the regression evidence.
  Link related issues in both directions, same convention as the other recipes. Never assign,
  close, or relabel issues you did not create. Never push code, never open a PR, never touch
  the cluster or ArgoCD itself — this route is read-only against everything except GitHub.

PHASE 5 - REPORT
  hermes send --to "discord:{DISCORD_CHANNEL}" "Deploy RCA for {{app}} ({{reason}}):
    Trigger: <what happened now>
    Root cause: <deploy-caused | pre-existing, now exposed | unrelated infra>
    Code: <repo path, if a specific change is implicated>
    Blast radius: <what's actually broken for users right now, if anything>
    Recommended fix: <the fix, and separately, only if genuinely warranted, that reverting
      {{revision}} is an option and what it would cost (loses the other changes in that commit)>
    Issue: <created #n | commented on #n | reopened #n>
    Confidence: high | medium | low"

If the evidence is genuinely insufficient, say so and record the leading hypotheses rather
than guessing at which of the three categories this falls into."""

webhook = config.setdefault("platforms", {}).setdefault("webhook", {})
webhook.setdefault("enabled", True)
extra = webhook.setdefault("extra", {})
extra.setdefault("port", GATEWAY_PORT)
routes = extra.setdefault("routes", {})

routes["argocd-deploy-rca"] = {
    "secret": SECRET,
    "events": ["argocd-deploy-rca"],
    "toolsets": ["terminal", "file"],
    "prompt": prompt,
    "deliver": "log",
}

with open(CONFIG_PATH, "w") as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False, width=100)

print("config.yaml updated: route argocd-deploy-rca written")
print(f"Configure ArgoCD Notifications to POST here with header 'X-Gitlab-Token: {SECRET[:6]}...' (full value from your own secret) — see argocd-notifications-patch.yaml.example")

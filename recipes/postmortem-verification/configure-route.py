#!/usr/bin/env python3
"""Install the postmortem-verification pipeline: two Hermes routes, a route
script, and a cron-driven sweep script.

Why two routes and a sweep, not one route: a PR merging doesn't mean the fix
is deployed yet, and Hermes has no built-in scheduling — only a webhook
gateway and whatever the OS cron can drive. So:

  1. postmortem-record: fires the instant a PR merges. A route *script* (no
     LLM call, near-zero cost) checks whether the PR's body closes an
     auto-triaged issue, and if so appends a pending-verification record to a
     local file. It never invokes the agent.
  2. A cron job (verification-sweep.sh, installed separately — see README)
     wakes up hourly, and for any pending record older than VERIFY_AFTER_HOURS
     (default 20h — long enough for a normal deploy pipeline to have shipped
     the fix), POSTs a synthetic, HMAC-signed event to this same gateway.
  3. postmortem-verify: the route that synthetic event triggers. It re-runs
     the original RCA's evidence query, decides fixed vs. still-recurring,
     comments (or reopens) the issue, and — only for issues Hermes itself
     opened, and only once verification succeeds — may close it with an
     explanation. It never closes an issue it did not open.

Fill in the placeholders below before running, or export them as env vars.

Run on the gateway box:
    HERMES_POSTMORTEM_RECORD_SECRET=$(openssl rand -hex 32) \\
    HERMES_POSTMORTEM_VERIFY_SECRET=$(openssl rand -hex 32) \\
    python3 configure-route.py
then: sudo systemctl restart hermes-gateway
and follow the README to install the cron job.
"""
import os
import stat
import sys

import yaml

CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
RECORD_SECRET = os.environ.get("HERMES_POSTMORTEM_RECORD_SECRET", "").strip()
VERIFY_SECRET = os.environ.get("HERMES_POSTMORTEM_VERIFY_SECRET", "").strip()
if len(RECORD_SECRET) < 32:
    sys.exit("HERMES_POSTMORTEM_RECORD_SECRET must be set (>=32 chars)")
if len(VERIFY_SECRET) < 32:
    sys.exit("HERMES_POSTMORTEM_VERIFY_SECRET must be set (>=32 chars)")

GITHUB_REPO = os.environ.get("GITHUB_REPO", "<YOUR_ORG>/<YOUR_REPO>")
DISCORD_CHANNEL = os.environ.get("DISCORD_CHANNEL", "<YOUR_DISCORD_CHANNEL>")
AUTO_TRIAGED_LABEL = os.environ.get("AUTO_TRIAGED_LABEL", "auto-triaged")
GATEWAY_PORT = int(os.environ.get("HERMES_WEBHOOK_PORT", "8644"))
VERIFY_AFTER_HOURS = os.environ.get("VERIFY_AFTER_HOURS", "20")
STATE_DIR = os.path.expanduser(os.environ.get("POSTMORTEM_STATE_DIR", "~/services/postmortem"))
PENDING_FILE = os.path.join(STATE_DIR, "pending.jsonl")
PROCESSED_FILE = os.path.join(STATE_DIR, "processed.jsonl")
SCRIPTS_DIR = os.path.expanduser("~/.hermes/scripts")

os.makedirs(STATE_DIR, exist_ok=True, mode=0o700)
os.makedirs(SCRIPTS_DIR, exist_ok=True, mode=0o700)

# ---------------------------------------------------------------------------
# 1. The route script for postmortem-record. Sentinel tokens, not an f-string
#    or .format(), because the script body itself contains literal { } (JSON
#    parsing) that must not be touched by substitution.
RECORD_SCRIPT = r'''#!/usr/bin/env python3
"""Route script for the postmortem-record route (installed by configure-route.py).
Reads a GitHub pull_request webhook payload from stdin. If the merged PR's
body closes an issue carrying __AUTO_TRIAGED_LABEL__, appends a pending
verification record. Always ends silently: recording is mechanical and never
needs the agent."""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

GITHUB_REPO = "__GITHUB_REPO__"
AUTO_TRIAGED_LABEL = "__AUTO_TRIAGED_LABEL__"
PENDING_FILE = "__PENDING_FILE__"

CLOSING_KEYWORD_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)\s*:?\s*#(\d+)", re.IGNORECASE
)


def silent():
    print("[SILENT]")
    sys.exit(0)


def main():
    payload = json.load(sys.stdin)
    if payload.get("action") != "closed":
        silent()
    pr = payload.get("pull_request") or {}
    if not pr.get("merged"):
        silent()

    body = pr.get("body") or ""
    match = CLOSING_KEYWORD_RE.search(body)
    if not match:
        silent()
    issue_number = int(match.group(1))

    try:
        out = subprocess.run(
            ["gh", "issue", "view", str(issue_number), "--repo", GITHUB_REPO, "--json", "labels"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        labels = [l["name"] for l in json.loads(out.stdout or "{}").get("labels", [])]
    except Exception:
        silent()
    if AUTO_TRIAGED_LABEL not in labels:
        silent()  # only verify issues Hermes itself opened from an RCA

    record = {
        "issue": issue_number,
        "pr": pr.get("number"),
        "repo": GITHUB_REPO,
        "merged_sha": pr.get("merge_commit_sha"),
        "merged_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(PENDING_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

    silent()


if __name__ == "__main__":
    main()
'''

record_script_path = os.path.join(SCRIPTS_DIR, "record_verification.py")
with open(record_script_path, "w") as f:
    f.write(
        RECORD_SCRIPT.replace("__GITHUB_REPO__", GITHUB_REPO)
        .replace("__AUTO_TRIAGED_LABEL__", AUTO_TRIAGED_LABEL)
        .replace("__PENDING_FILE__", PENDING_FILE)
    )
os.chmod(record_script_path, stat.S_IRWXU)
print(f"wrote {record_script_path}")

# ---------------------------------------------------------------------------
# 2. The cron sweep script. Reads pending.jsonl, fires a synthetic HMAC-signed
#    event at the local gateway for anything old enough, moves it to
#    processed.jsonl. Uses flock so an overlapping cron tick can't double-fire.
SWEEP_SCRIPT = r'''#!/usr/bin/env bash
# Installed by recipes/postmortem-verification/configure-route.py.
# Run hourly via cron (see the recipe README for the crontab line).
set -euo pipefail
PENDING="__PENDING_FILE__"
PROCESSED="__PROCESSED_FILE__"
SECRET="__VERIFY_SECRET__"
GATEWAY_PORT="__GATEWAY_PORT__"
VERIFY_AFTER_HOURS="__VERIFY_AFTER_HOURS__"
LOCK="${PENDING}.lock"

[ -f "$PENDING" ] || exit 0
exec 9>"$LOCK"
flock -n 9 || exit 0   # another sweep is already running; skip this tick

now=$(date +%s)
tmp_keep=$(mktemp)
while IFS= read -r line; do
  [ -z "$line" ] && continue
  merged_at=$(python3 -c "import json,sys;print(json.loads(sys.argv[1])['merged_at'])" "$line")
  merged_epoch=$(date -d "$merged_at" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%S" "${merged_at%%+*}" +%s 2>/dev/null || echo 0)
  age_hours=$(( (now - merged_epoch) / 3600 ))
  if [ "$age_hours" -lt "$VERIFY_AFTER_HOURS" ]; then
    echo "$line" >> "$tmp_keep"
    continue
  fi
  body=$(python3 -c "
import json,sys
r = json.loads(sys.argv[1])
r['type'] = 'postmortem-verify'
print(json.dumps(r))
" "$line")
  sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}')
  code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:${GATEWAY_PORT}/webhooks/postmortem-verify" \
    -H 'Content-Type: application/json' -H "X-Webhook-Signature: $sig" --data-binary "$body")
  echo "$(date -u +%FT%TZ) fired verification for $line -> HTTP $code" >> "$(dirname "$PENDING")/sweep.log"
  if [ "$code" = "202" ]; then
    echo "$line" >> "$PROCESSED"
  else
    echo "$line" >> "$tmp_keep"   # retry next tick
  fi
done < "$PENDING"
mv "$tmp_keep" "$PENDING"
'''

sweep_script_path = os.path.join(STATE_DIR, "verification-sweep.sh")
with open(sweep_script_path, "w") as f:
    f.write(
        SWEEP_SCRIPT.replace("__PENDING_FILE__", PENDING_FILE)
        .replace("__PROCESSED_FILE__", PROCESSED_FILE)
        .replace("__VERIFY_SECRET__", VERIFY_SECRET)
        .replace("__GATEWAY_PORT__", str(GATEWAY_PORT))
        .replace("__VERIFY_AFTER_HOURS__", VERIFY_AFTER_HOURS)
    )
os.chmod(sweep_script_path, stat.S_IRWXU)
print(f"wrote {sweep_script_path} (install the cron line from the README)")

# ---------------------------------------------------------------------------
# 3. The two Hermes routes.
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f) or {}

webhook = config.setdefault("platforms", {}).setdefault("webhook", {})
webhook.setdefault("enabled", True)
extra = webhook.setdefault("extra", {})
extra.setdefault("port", GATEWAY_PORT)
routes = extra.setdefault("routes", {})

routes["postmortem-record"] = {
    "secret": RECORD_SECRET,
    "events": ["pull_request"],
    "filters": [
        {"field": "action", "equals": "closed"},
        {"field": "pull_request.merged", "equals": True},
    ],
    "script": "record_verification.py",
    "prompt": "(unused: the route script above always ends this delivery silently)",
    "deliver": "log",
}

verify_prompt = f"""A merged pull request should have shipped a fix for an issue you (or a
sibling recipe) opened from a root-cause analysis, and enough time has passed that it should
be deployed. Verify whether it actually worked.

Issue: #{{issue}}   Merging PR: #{{pr}}   Merge commit: {{merged_sha}}

PHASE 1 - RE-READ THE ORIGINAL RCA
  gh issue view {{issue}} --repo {GITHUB_REPO} --json title,body,labels,state
  Find the Evidence section's Loki query (or LogQL/PromQL block) and the original time window
  the alert/failure was observed in. If you cannot find a query in the issue body, say so in
  your report and stop after PHASE 4 with confidence "low, no evidence query found".

PHASE 2 - RE-RUN THE EVIDENCE, SINCE THE MERGE
  Adapt the original query's time window to start at the merge time above, not the original
  incident time, and re-run it:
    ~/services/grafana/loki-query.sh query '<the query from the issue, adapted>' <minutes since merge, capped at 4320> 50
    ~/services/grafana/loki-query.sh count '<the same query as a count_over_time expression>'
  Zero or near-zero matching records since the merge is evidence the fix worked. Any
  meaningful count is evidence it did not (or that a different, related failure appeared).

PHASE 3 - DECIDE AND ACT
  Write your postmortem comment (PHASE 4 below) to a temp file first, same as any issue body:
    POSTMORTEM_BODY=$(mktemp /tmp/postmortem-XXXXXX.md)   # then write the markdown into it
  a) No recurrence: comment on the issue confirming this, including the query you ran and the
     window. You created this issue (it carries {AUTO_TRIAGED_LABEL}); you may now close it —
     this is the one case where closing your own issue is appropriate, since you have positive
     verification. Do not close it if you are not confident, and never close an issue you did
     not open.
       gh issue comment {{issue}} --repo {GITHUB_REPO} --body-file "$POSTMORTEM_BODY"
       gh issue close {{issue}} --repo {GITHUB_REPO} --reason completed
  b) Still recurring, or a regression: comment with the new evidence (count, window, any new
     trace ids) and reopen if it was closed. Do NOT treat this as a new incident requiring a
     second full RCA unless the evidence points at a genuinely different root cause than the
     original issue described — if so, say that explicitly and reference the original issue.
       gh issue reopen {{issue}} --repo {GITHUB_REPO}   # only if currently closed
       gh issue comment {{issue}} --repo {GITHUB_REPO} --body-file "$POSTMORTEM_BODY"

PHASE 4 - DRAFT THE POSTMORTEM (goes in the same comment as PHASE 3, not a separate one)
  A short postmortem synthesized from the original issue and this verification:
    Timeline: <first seen -> issue opened -> PR merged {{merged_sha}} -> verified>
    Root cause (from the original issue): <one or two sentences>
    Fix (from the merged PR): <what actually changed, in your own words after reading the diff
      via: gh pr diff {{pr}} --repo {GITHUB_REPO}>
    Verification: <the query, window, and result that justified PHASE 3's decision>
    Follow-up: <anything still open — a tuning PR not yet merged, a related issue, a
      contributing factor from the original RCA that wasn't addressed>

PHASE 5 - REPORT
  hermes send --to "discord:{DISCORD_CHANNEL}" "Verification for #{{issue}} (fix in PR #{{pr}}):
    Result: fixed, no recurrence | still recurring | inconclusive
    Evidence: <the count and window>
    Action: <closed #n | reopened #n | commented only>"
"""

routes["postmortem-verify"] = {
    "secret": VERIFY_SECRET,
    "events": ["postmortem-verify"],
    "toolsets": ["terminal", "file"],
    "prompt": verify_prompt,
    "deliver": "log",
}

with open(CONFIG_PATH, "w") as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False, width=100)

print("config.yaml updated: routes postmortem-record and postmortem-verify written")
print(f"pending file: {PENDING_FILE}")
print(f"processed file: {PROCESSED_FILE}")
print("Next: add 'pull_request' to your GitHub webhook's events, and install the cron line — see README.")

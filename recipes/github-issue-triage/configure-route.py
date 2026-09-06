#!/usr/bin/env python3
"""Add/refresh the GitHub issue-triage route in Hermes' config.yaml.

Fires on two distinct GitHub issue events:
  - a new issue opened by a human, which it triages as clear-and-actionable
    (delegate + PR) or ambiguous (ask a question, stop);
  - the "ready-to-fix" label being applied to ANY issue (including one another
    recipe such as grafana-alert-rca or ci-failure-triage opened and labelled
    auto-triaged), which a human uses to say "yes, actually fix this" without
    re-litigating the ambiguity check. That label is the only way an
    auto-triaged issue's write-boundary is ever crossed, and only a human can
    apply it.

Fill in the placeholders below before running, or export them as env vars to
override the defaults.

Run on the gateway box:
    HERMES_GITHUB_ROUTE_SECRET=$(openssl rand -hex 32) python3 configure-route.py
then: sudo systemctl restart hermes-gateway
"""
import os
import sys

import yaml

CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
SECRET = os.environ.get("HERMES_GITHUB_ROUTE_SECRET", "").strip()
if len(SECRET) < 32:
    sys.exit("HERMES_GITHUB_ROUTE_SECRET must be set (>=32 chars, e.g. `openssl rand -hex 32`)")

GITHUB_REPO = os.environ.get("GITHUB_REPO", "<YOUR_ORG>/<YOUR_REPO>")
DISCORD_CHANNEL = os.environ.get("DISCORD_CHANNEL", "<YOUR_DISCORD_CHANNEL>")
GATEWAY_PORT = int(os.environ.get("HERMES_WEBHOOK_PORT", "8644"))
READY_TO_FIX_LABEL = os.environ.get("READY_TO_FIX_LABEL", "ready-to-fix")
AUTO_TRIAGED_LABEL = os.environ.get("AUTO_TRIAGED_LABEL", "auto-triaged")

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f) or {}

prompt = f"""A GitHub issue event was received (action: {{action}}).

Repo: {{repository.full_name}}
Issue #{{issue.number}}: {{issue.title}}
Body: {{issue.body}}
URL: {{issue.html_url}}

Create a fresh checkout unique to this delivery with the terminal tool:
  mkdir -p ~/dev/repos
  ISSUE_DIR=~/dev/repos/issue-{{issue.number}}-$(date +%s)-$RANDOM
  git clone https://github.com/{GITHUB_REPO}.git "$ISSUE_DIR"
  echo "$ISSUE_DIR"
Use that directory for every command below. Never delete, reset, or reuse another
run's checkout; a scheduled cleanup job removes expired issue-* directories.

FIRST, determine which case this delivery is:

CASE C - the "{READY_TO_FIX_LABEL}" label was just applied (action is "labeled" and the
newly-added label's name is "{READY_TO_FIX_LABEL}"):
  A human has already read this issue and decided it should be fixed — including an issue
  that carries the "{AUTO_TRIAGED_LABEL}" label, i.e. one another route (an alert or CI-failure
  RCA) opened. Do NOT re-run the ambiguity check from Case B below; the human's label
  application IS the "this is clear enough to act on" decision. Proceed directly as Case A.
  If the issue body contains a "Recommended fix" section (typical of an RCA issue), use it as
  your primary instruction for what to change; otherwise reason about the issue body as usual.
  Skip straight to the Case A steps.

CASE A - a new issue (action is "opened") that is clear, well-scoped, and actionable, OR any
issue reaching this point via Case C above:
  1. hermes send --to "discord:{DISCORD_CHANNEL}" "Delegating issue #{{issue.number}} to Claude Code..."
  2. Use the terminal tool in the unique checkout created above:
       git checkout -b issue-{{issue.number}}-<short-slug>
       claude -p "Resolve GitHub issue #{{issue.number}} in this repo: {{issue.title}} -- {{issue.body}}. Make the minimal correct change. Follow the repo's own contribution guide and run its test/verification command before committing." --allowedTools Read,Edit,Write,Bash(git*),Bash(make*)
       git add -A
       git commit -m "Fix #{{issue.number}}: {{issue.title}}"
       git push -u origin issue-{{issue.number}}-<short-slug>
       gh pr create --repo {GITHUB_REPO} --title "Fix #{{issue.number}}: {{issue.title}}" --body "Closes #{{issue.number}}

Automated fix delegated via Hermes/Claude Code." --base main --head issue-{{issue.number}}-<short-slug>
  3. hermes send --to "discord:{DISCORD_CHANNEL}" "PR opened for issue #{{issue.number}}: <pr-url>"
  Never push directly to main. Never force-push.

CASE B - a new issue (action is "opened") that is vague, ambiguous, could be interpreted
multiple ways, missing information needed to implement it safely, looks like a duplicate, or
you are simply not confident what the right fix is:
  DO NOT delegate, DO NOT guess. Instead:
  1. gh issue comment {{issue.number}} --repo {GITHUB_REPO} --body "<your question/concern, asking for clarification>"
  2. hermes send --to "discord:{DISCORD_CHANNEL}" "Issue #{{issue.number}} ({{issue.title}}) needs input before I act: <your specific question>. Reply here and I'll pick it up."
  3. Stop - do not create a branch or PR. The user will reply in this
     same chat channel; that reply continues as a normal conversation
     with you (the live gateway), not through this webhook route.

When genuinely in doubt between A and B for a newly opened issue, prefer B - asking first is
better than guessing on something in a real codebase. Case C never has this ambiguity to
resolve; a human already resolved it by applying the label."""

webhook = config.setdefault("platforms", {}).setdefault("webhook", {})
webhook.setdefault("enabled", True)
extra = webhook.setdefault("extra", {})
extra.setdefault("port", GATEWAY_PORT)
routes = extra.setdefault("routes", {})

routes["github-issue-triage"] = {
    "secret": SECRET,
    "events": ["issues"],
    "filters": [
        {
            "any": [
                # A brand-new issue that isn't already an RCA report.
                {
                    "all": [
                        {"field": "action", "equals": "opened"},
                        {"not": {"field": "issue.labels", "regex": f'"name": "{AUTO_TRIAGED_LABEL}"'}},
                    ]
                },
                # A human just applied the hand-off label to any issue,
                # auto-triaged or otherwise.
                {
                    "all": [
                        {"field": "action", "equals": "labeled"},
                        {"field": "label.name", "equals": READY_TO_FIX_LABEL},
                    ]
                },
            ]
        }
    ],
    "toolsets": ["terminal", "file", "delegation"],
    "prompt": prompt,
    "deliver": "log",
}

with open(CONFIG_PATH, "w") as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False, width=100)

print("config.yaml updated: route github-issue-triage written (Case A/B/C)")

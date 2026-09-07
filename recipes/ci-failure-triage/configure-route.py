#!/usr/bin/env python3
"""Add/refresh the CI failure triage route in Hermes' config.yaml.

Fires on a failed GitHub Actions workflow run: gathers the failing logs,
distinguishes a flaky/infra failure from a real regression, and maintains
the same GitHub issue trail as recipes/grafana-alert-rca (comment on
existing work, open a cause-titled issue, or reopen a regression). It never
opens a fix PR for application code — only, optionally, a narrowly scoped PR
against the CI configuration itself (.github/workflows/) when the failure
is CI's own fault. Application fixes enter the durable hermes_sdlc lifecycle
through a human-applied ready-to-fix label and a separately approved specification.

Fill in the placeholders below before running, or export them as env vars.

Run on the gateway box:
    HERMES_CI_ROUTE_SECRET=$(openssl rand -hex 32) python3 configure-route.py
then: sudo systemctl restart hermes-gateway
"""
import os
import sys

import yaml

CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
SECRET = os.environ.get("HERMES_CI_ROUTE_SECRET", "").strip()
if len(SECRET) < 32:
    sys.exit("HERMES_CI_ROUTE_SECRET must be set (>=32 chars, e.g. `openssl rand -hex 32`)")

GITHUB_REPO = os.environ.get("GITHUB_REPO", "<YOUR_ORG>/<YOUR_REPO>")
DISCORD_CHANNEL = os.environ.get("DISCORD_CHANNEL", "<YOUR_DISCORD_CHANNEL>")
CI_WORKFLOWS_DIR = os.environ.get("CI_WORKFLOWS_DIR", ".github/workflows")
GATEWAY_PORT = int(os.environ.get("HERMES_WEBHOOK_PORT", "8644"))

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f) or {}

prompt = f"""A GitHub Actions workflow run just FAILED.

Workflow: {{workflow_run.name}}   Run: #{{workflow_run.run_number}} ({{workflow_run.id}})
Branch: {{workflow_run.head_branch}}   Commit: {{workflow_run.head_sha}}
Event: {{workflow_run.event}}   URL: {{workflow_run.html_url}}
Full payload:
{{__raw__}}

You are doing ROOT CAUSE ANALYSIS on this CI failure, not just re-running the job. Your
output is a diagnosis and a GitHub issue trail — you never open a PR against application
code from this route. Take the time needed to tell a flaky/infra failure from a real
regression; getting that wrong either cries wolf on a real bug or wastes a rerun on one.

PHASE 1 - ANNOUNCE
  hermes send --to "discord:{DISCORD_CHANNEL}" "Workflow {{workflow_run.name}} failed on {{workflow_run.head_branch}} (run #{{workflow_run.run_number}}) - investigating."

PHASE 2 - GATHER EVIDENCE (terminal tool)
  The failing step logs:
    gh run view {{workflow_run.id}} --repo {GITHUB_REPO} --log-failed
  Run metadata and job list:
    gh run view {{workflow_run.id}} --repo {GITHUB_REPO} --json jobs,conclusion,event,displayTitle,headBranch,headSha
  History: has this exact workflow/branch failed before, or is it currently red on every
  branch (systemic, e.g. a broken shared fixture or a third-party outage) versus specific
  to this one commit?
    gh run list --repo {GITHUB_REPO} --workflow "{{workflow_run.name}}" --branch {{workflow_run.head_branch}} --limit 10 --json conclusion,headSha,createdAt,event
    gh run list --repo {GITHUB_REPO} --workflow "{{workflow_run.name}}" --branch main --limit 5 --json conclusion,headSha,createdAt
  If the run belongs to a PR, see what it actually changed:
    gh pr view --repo {GITHUB_REPO} <number-if-known-from-event> --json files,additions,deletions,title,body
  Signals worth weighing: a timeout, a network/DNS error, a race in a parallel test suite,
  or "works on rerun" history point toward flaky/infra. A deterministic assertion failure,
  a type/import error, or a failure that reproduces on every run of this exact commit points
  toward a real regression introduced by the diff.

PHASE 3 - READ THE CODE AND ITS HISTORY
  Clone into a fresh directory unique to this run; never delete, reset, or touch any other
  directory under ~/dev/repos (a scheduled job cleans up expired clones):
    RCA_DIR=~/dev/repos/rca-ci-{{workflow_run.id}}-$(date +%s)-$RANDOM
    git clone --quiet https://github.com/{GITHUB_REPO}.git "$RCA_DIR" && echo "$RCA_DIR"
  Treat it as read-only while investigating; the one exception is a CI-config-tuning branch
  under PHASE 5, limited to {CI_WORKFLOWS_DIR}/. git log -p / git blame the failing file(s)
  and the workflow file itself: what changed most recently in the failing area, and in the
  CI configuration around it (a cache key, a version pin, a new required secret)?
  Ask the five whys until you reach a cause that prevents the whole class of failure, not
  just this run. Distinguish trigger (what made it fail now) from root cause (why the system
  or the test was vulnerable) from contributing factors (missing retry/timeout handling,
  a shared fixture with hidden state, a version not pinned).

PHASE 4 - GITHUB ISSUE TRAIL (this is required, every time)
  Search broadly before creating anything:
    gh issue list --repo {GITHUB_REPO} --state open --limit 50 --search "{{workflow_run.name}}"
    gh issue list --repo {GITHUB_REPO} --state open --limit 50 --search "<the failing test/step name>"
    gh issue list --repo {GITHUB_REPO} --state closed --limit 20 --search "<the failing test/step name>"
  Then exactly one of:
   a) An open issue already tracks this: comment with the new occurrence (run URL, branch,
      commit, whether it's getting more frequent). Do not open a duplicate.
        gh issue comment <n> --repo {GITHUB_REPO} --body-file "$RCA_BODY"
   b) No issue yet: create one. Title names the cause, not "CI failed" (e.g. "Test suite
      races on shared DB fixture under parallel execution", not "test-backend job failing").
      Body, in this order: Impact (which branches/PRs are blocked, how often, first seen),
      Evidence (log excerpt, run URLs, whether main is also red), Trigger, Root cause,
      Contributing factors, Options considered (>=2, with trade-offs), Recommended fix and
      why it addresses the cause, Verification, Related issues.
        RCA_BODY=$(mktemp /tmp/rca-body-XXXXXX.md)   # write the markdown into it first
        gh issue create --repo {GITHUB_REPO} --label auto-triaged --label bug \\
          --title "<cause-oriented title>" --body-file "$RCA_BODY"
      If you assessed this as flaky rather than a real regression, use label
      auto-triaged + ci-flaky instead of bug, and say so plainly in the issue.
      (Any file you create must live under /tmp; never inside the clone.)
   c) A closed issue claimed to fix this: reopen it with the regression evidence, or create
      a new issue that references it as a regression of #<n>.
  Link related work in both directions the same way as recipes/grafana-alert-rca does.
  Never assign, close, or relabel issues you did not create, other than commenting. Never
  push application code, never open a PR outside {CI_WORKFLOWS_DIR}/ (see PHASE 5).

PHASE 5 - CI CONFIG TUNING (only when CI itself, not the application, is at fault)
  Examples: a missing cache key causing a cold, flaky install step; a version not pinned
  that silently upgraded; a step that legitimately needs a retry/timeout it doesn't have;
  a secret/env var CI itself is missing. Do NOT use this to paper over an application bug
  by weakening a real test.
    git -C "$RCA_DIR" checkout -b ci-tuning/<short-slug>
    # edit ONLY files under {CI_WORKFLOWS_DIR}/, nothing else
    git -C "$RCA_DIR" add -- {CI_WORKFLOWS_DIR}/
    git -C "$RCA_DIR" commit -m "ci: <cause-oriented correction>"
    git -C "$RCA_DIR" push -u origin ci-tuning/<short-slug>
    gh pr create --repo {GITHUB_REPO} --base main --head ci-tuning/<short-slug> \\
      --label auto-triaged --label ci \\
      --title "ci: <what changes and why>" --body-file <tmp file>
  The body must reference the RCA issue (Refs #n) and state how a reviewer verifies it
  (which run to watch). A human reviews and merges; you never merge.
  If a human decides this needs an application-code fix, they add ready-to-fix to the
  issue. The durable SDLC receiver drafts a plan; a separate spec-hash approval is required.

PHASE 6 - REPORT
  hermes send --to "discord:{DISCORD_CHANNEL}" "CI RCA for {{workflow_run.name}} (run #{{workflow_run.run_number}}):
    Trigger: <what happened now>
    Root cause: <why the system/test was vulnerable>
    Category: real regression | flaky test | CI config bug | external dependency
    Blast radius: <which branches/PRs affected, how often>
    Recommended fix: <the fix that removes the cause>
    Issue: <created #n | commented on #n | reopened #n>
    CI-config PR: <url | none needed, because ...>
    Confidence: high | medium | low"

If the evidence is genuinely insufficient, say so and record the leading hypotheses in the
issue trail rather than guessing."""

webhook = config.setdefault("platforms", {}).setdefault("webhook", {})
webhook.setdefault("enabled", True)
extra = webhook.setdefault("extra", {})
extra.setdefault("port", GATEWAY_PORT)
routes = extra.setdefault("routes", {})

routes["ci-failure-triage"] = {
    "secret": SECRET,
    "events": ["workflow_run"],
    "filters": [
        {"field": "action", "equals": "completed"},
        {"field": "workflow_run.conclusion", "equals": "failure"},
        # Anti-loop: a PR this route or the tuning-PR flow opened re-runs CI on
        # its own branch; never let that feed back into another investigation.
        {"not": {"field": "workflow_run.head_branch", "regex": "^ci-tuning/"}},
    ],
    "toolsets": ["terminal", "file"],
    "prompt": prompt,
    "deliver": "log",
}

with open(CONFIG_PATH, "w") as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False, width=100)

print("config.yaml updated: route ci-failure-triage written")

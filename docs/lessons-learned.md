# Lessons learned

Two bugs a live run of the `grafana-alert-rca` recipe found in itself, on its very first real
test. Both are folded into the templates in this repo already, but they're worth reading
before you extend this pattern to a new trigger — the failure mode generalizes.

## 1. Concurrent runs raced on the same clone directory

**What happened.** Grafana grouped a batch of historical test errors into two separate alert
notifications, delivered seconds apart. Both spawned an agent run. Both runs followed the
(then) prompt's instruction to `rm -rf` a shared checkout directory before cloning fresh. Each
run deleted the other's in-progress clone mid-operation; one run then hit a safety approval
gate on the resulting broken state and stalled for the timeout window before giving up.

**The fix.** Never delete or reset a directory another run might be using. Every recipe here
clones into a name unique to that specific run (alert name or issue number, plus a timestamp
and a random suffix) and is told, explicitly, that it must never touch any other directory
under the shared clone root. A scheduled cleanup job (not the agent) removes stale clones
later.

**The generalizable point.** Any prompt instruction of the shape "clean up before you start"
is unsafe the moment more than one instance of the agent can run concurrently — and webhook
delivery makes that the default case, not the edge case. Prefer "always create something new
and named uniquely" over "always delete what might already be there".

## 2. A templating gap made the agent's own evidence query silently return nothing

**What happened.** The alert rule suggested a Loki query to the agent for its investigation,
built from a `{{ $labels.some_label }}` template value. When that label was absent on a given
alert instance, Grafana's templating renders the literal text `[no value]` into the
annotation — which produced a syntactically valid but semantically empty log query
(`label="[no value]"`, matching nothing real). The agent correctly noticed the query returned
no evidence, investigated anyway using a broader query, and found and reported the bug in the
alert's own annotation as part of its output — the RCA process caught the RCA tooling's own
defect.

**The fix.** Any Grafana annotation template that might be absent needs an explicit
`{{ if $labels.x }}...{{ else }}...{{ end }}` guard, not a bare reference — see
`recipes/grafana-alert-rca/terraform/rules.tf` for the pattern. The general lesson: never trust
a templated annotation to have produced a valid downstream query without testing the
label-absent case specifically, since that's exactly the case your happy-path testing won't
exercise.

## The meta-lesson

Both of these were caught because the recipe's own design — thorough root-cause analysis
rather than a quick fix, and a persistent GitHub issue trail rather than a fire-and-forget
notification — surfaced them as artifacts anyone could review afterward. If you're evaluating
whether an "investigate, don't just remediate" agent is worth the extra latency and cost
compared to a simple alert-to-Slack webhook: this is the kind of thing that answer buys you.

# Optional: deeper Kubernetes diagnostics

The recipes here investigate through logs (Loki) and source code, deliberately, to keep the
gateway's blast radius small — it never gets live Kubernetes API access. For failures that are
really about cluster/object state rather than application behavior (a pod stuck in
`ImagePullBackOff`, a misconfigured resource request, a probe failing for a reason that isn't
in the logs at all), that's a real gap. Rather than reinventing Kubernetes diagnostics badly,
document how to plug in tools that already do it well.

## Prior art worth knowing about

Several mature, open-source projects already do agentic infrastructure investigation, and are
worth citing rather than pretending don't exist:

- **[HolmesGPT](https://github.com/HolmesGPT/holmesgpt)** (Apache 2.0, CNCF Sandbox since
  October 2025, co-maintained by Robusta and Microsoft) — a general-purpose agentic
  investigation toolkit with a large library of Kubernetes/observability tool integrations.
- **[K8sGPT](https://github.com/k8sgpt-ai/k8sgpt)** (Apache 2.0, CNCF Sandbox) — analyzes live
  cluster state and explains what's wrong with a specific object in plain language.
- **[Aurora](https://github.com/Arvo-AI/aurora)** (Apache 2.0) — a LangGraph-orchestrated
  agentic investigator across multiple clouds.

If your gap is "I need an agent that can `kubectl describe`/`kubectl get` and reason about
cluster object state," one of these — used directly, on its own, with its own scoped
credentials — is very likely a better answer than extending any recipe here to do the same
thing worse. What this repo adds that those don't (as of this writing) is tying the
investigation's output to a persistent GitHub issue trail that a later investigation searches
before repeating work, and a Grafana-alerting-as-Terraform module.

## If you still want to add one evidence command here

The two RCA recipes' prompts (`recipes/grafana-alert-rca`, `recipes/ci-failure-triage`,
`recipes/deployment-failure-rca`) are plain text — you can add a line to PHASE 2's evidence
list pointing at a `k8sgpt analyze --explain -o json` (or a HolmesGPT CLI invocation) the same
way they already point at `loki-query.sh`. Doing this for real requires:

1. Installing `k8sgpt` (or HolmesGPT) on the gateway box.
2. **A read-only kubeconfig scoped to `get`/`list`/`describe` on the namespace(s) you want
   diagnosed, and nothing else** — no `exec`, no `delete`, no cluster-admin. This is a genuine
   expansion of what the agent can reach beyond what these recipes grant by default (Loki
   reads and a git clone), and deserves the same explicit, deliberate decision as any other
   credential grant in `docs/security-model.md` — don't wire this in "for completeness" without
   actually wanting the agent to have live cluster read access.
3. Adding the command to the prompt's evidence-gathering phase, with the same instruction the
   other commands get: read the output, don't assume it's the whole picture, and weigh it
   against what the logs and the code history say.

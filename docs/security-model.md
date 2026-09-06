# Security model

Read this before wiring any recipe here to a repository or Grafana stack you care about.
An unattended agent that can read your infrastructure and write to your GitHub repo needs an
explicit trust boundary, not an implicit one.

## The identity boundary

Every route runs as a dedicated bot GitHub account (`gh auth login` on the gateway box, not
your personal credentials). That account's permissions are the actual ceiling on what an
agent can do, regardless of what the prompt says — prompts are guidance, permissions are
enforcement. Give the bot account:

- Push access to the repo (to open branches and PRs).
- **No** admin, no branch-protection bypass, no merge rights it doesn't need.
- Its own GitHub personal access token or app installation, scoped to the one repo, rotated
  independently of anything else.

## The write boundary

Two recipes here write to GitHub or infrastructure state. Both are deliberately narrow:

- **`github-issue-triage`** opens PRs against application code, but only for issues classified
  as "clear and well-scoped" — anything ambiguous gets a clarifying question instead, and the
  route stops. It never pushes to `main`, never force-pushes, and the fix PR is always
  reviewed by a human before merge (branch protection should require this, not just habit).
- **`grafana-alert-rca`** never touches application code. Its only permitted write is a PR
  scoped to the Terraform files that manage alerting itself (`terraform/grafana/` in the
  example), guarded by an explicit "don't touch these files" list in the prompt (state,
  provider, variable files) and by CI planning the change before a human merges it.

Both are told, explicitly and repeatedly in the prompt, what they may never do: force-push,
merge their own PR, close or relabel issues they didn't open, delete or reset another run's
checkout. Treat these as load-bearing sentences, not decoration — they're there because an
early version of this setup violated one of them (see `docs/lessons-learned.md`).

## The concurrency boundary

Webhooks can and will deliver more than one event before the first is handled. Every recipe
clones into a fresh, uniquely-named directory per run and is told never to delete or reset any
other directory under the shared clone root. A cron job (installed by the Ansible playbook)
sweeps expired clones on a schedule; the agent itself never has `rm -rf` rights over anything
but its own directory.

## The credential boundary

- Each webhook route gets **its own** HMAC secret (`openssl rand -hex 32`), generated once and
  never reused across routes or committed to a public repo.
- Read-only integrations (the Loki query helper) use a **Viewer**-scoped token, not an Admin
  one, even though this is more setup friction. An agent that only needs to read logs should
  not be able to change alert rules even if the prompt never asks it to.
- If a credential ever touches a chat transcript, a log file, or a public commit — even
  briefly, even by you while debugging — rotate it. Assume it is compromised the moment it
  left the one place it belongs.

## The "ask, don't guess" boundary

Both recipes are instructed to stop and ask a human (via a chat message) rather than proceed
under uncertainty: an ambiguous GitHub issue, an alert whose root cause the evidence doesn't
support. This is a deliberate trade against throughput — a false "no confident answer" costs a
human five minutes; a false "confident and wrong" costs a bad PR, a bad alert-tuning change,
or noise in your issue tracker that erodes trust in every future automated report.

## What this does not protect against

This model assumes the LLM provider and the Hermes runtime itself are trusted, and that the
webhook payload (a GitHub issue body, a Grafana alert annotation) is the only externally
influenced input reaching the agent's prompt. Both are usual assumptions for this class of
setup, but they are assumptions — a payload field that gets interpolated unsanitized into a
prompt is a prompt-injection surface, same as it would be for any other LLM-backed system that
processes third-party input. Review your own webhook payload sources with that in mind before
you extend either recipe to a new event type.

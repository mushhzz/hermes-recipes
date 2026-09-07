# Hermes lifecycle gap analysis

## Historical audit, not current implementation status

This archive preserves the completed DeliveryStages and ProductionStages audits and their supplied code references. **Implementation verification pending:** findings describe the pre-integration recipes at audit time; they do not assert that the new lifecycle controller still has these defects or has fixed them. Exact historical line numbers can shift during integration. Main owns implementation and current operational status.

The original repository deliberately provided recipes and prompt-guided glue ending at human-reviewed work. Absence of autonomous merge, deployment or rollback was not a defect. The selected expansion is recorded separately in [architecture.md](architecture.md); recommendations below are historical audit proposals, not competing architecture requirements.

## Integration discoveries supplied by Main

### Install-order-dependent approval handoff

Main reports reproducing that installing GitHub issue triage and then Grafana RCA appends an unconditional `auto-triaged` exclusion, blocking the intended Case C ready-to-fix path; reverse installation order differs. The relevant code was inspected during archive assembly:

- `recipes/github-issue-triage/configure-route.py:105–125` permits either a newly opened non-auto-triaged issue or a `ready-to-fix` label event, explicitly including auto-triaged issues in the latter branch.
- `recipes/grafana-alert-rca/configure-route.py:191–199` appends its anti-loop predicate to the entire sibling filter list, rather than just the newly opened branch.

The reproduced observation belongs to Main; this documentation task did not rerun it. This is a concrete cross-recipe conflict, not evidence that human merge should be removed.

### Unsupported legacy recorder route-script assumption

`recipes/postmortem-verification/configure-route.py:213–222` declares `script: record_verification.py` and calls its prompt unused. The installed Hermes `gateway/platforms/webhook.py:440–464` checks events then renders the prompt, and the inspected file contains no `script` dispatch support. Main independently reports the same installed-runtime finding. That undermines the old claim that declaring the script executes the recorder. The chosen separate receiver/worker replaces this assumption; no upstream patch or successful live route execution is claimed here.

Installed-runtime paths are relative to the installed Hermes source, not this repository, and refer to the inspected local version only. Do not generalize this to all Hermes releases or claim upstream has no delivery deduplication: the same installed handler explicitly contains delivery-ID deduplication at `gateway/platforms/webhook.py:495–514`.

### State and production-proof gaps confirmed in source

- Recorder append at `recipes/postmortem-verification/configure-route.py:114–122` has no shared lock with sweep read/replace at `:156–187`. The lost-write outcome remains the prior audit's static-analysis inference, not a newly executed race test.
- Sweep `:178–187` records HTTP 202 as processed; it does not receive a verification outcome.
- Verification prompt `:225–254` assumes deployment from elapsed time and allows near-zero log matches as recovery evidence without binding to a deployed revision or traffic coverage.

The audit reports below retain every identified finding, caveat, impact, confidence and proposed observable completion criterion. No tests, builds, lint or formatting were run for this archive.

# Preserved delivery-stage audit

## Scope and audit basis
Confirmed reading skill://improve and audit-playbook.md §4 Test Coverage, §8 Docs, §9 Direction, and Finding format. Read the complete prompts and route wiring in the four assigned files. Root README and repository-wide event/stage searches supplied limited context; operational recipes and provisioning were not audited. Findings describe this repository’s contracts, not absent capabilities in upstream Hermes. No validation commands were run, as requested.

## Current lifecycle coverage
- **Intake — wired:** `recipes/github-issue-triage/configure-route.py:102-124` accepts newly opened non-auto-triaged issues and ready-to-fix label events. `recipes/ci-failure-triage/configure-route.py:147-155` accepts completed failed workflows excluding ci-tuning branches.
- **Requirements/triage — prompt-only, intentionally lightweight:** issue Case A/B judges actionable versus ambiguous/duplicate and asks a question (`github-issue-triage/configure-route.py:67-94`). Case C treats the label as sufficient clarification (`:57-65`). There is no separate requirements artifact or acceptance-criteria gate in these recipes.
- **Design — partial prompt coverage:** CI RCA requires trigger/root cause/contributing factors plus at least two options, trade-offs, recommended fix and verification (`ci-failure-triage/configure-route.py:79-98`). Ordinary issue implementation has only “minimal correct change” and contribution-guide instructions (`github-issue-triage/configure-route.py:72`); no separate design review stage.
- **Implementation — prompt-driven:** unique clone, Claude Code delegation, branch/commit/push/PR (`github-issue-triage/configure-route.py:47-53,69-79`). CI explicitly prohibits application-code PRs and allows narrowly scoped workflow edits (`ci-failure-triage/configure-route.py:108-125`).
- **Testing — requested, not evidenced/enforced by local wiring:** delegated prompt says run the repository verification command (`github-issue-triage/configure-route.py:72`); README explicitly requires adopter customization (`github-issue-triage/README.md:68-73`). CI RCA investigates historical failures; it is not a general test runner.
- **Code review/approval — human-owned by design:** issue README requires review protection (`github-issue-triage/README.md:36-37`), and CI tuning explicitly stops before merge (`ci-failure-triage/configure-route.py:122-123`). No agent review or reviewer-feedback route exists in the assigned wiring. This is not a missing autonomous merge feature.
- **PR iteration — absent in these recipes:** issue events stop at opened/labeled; CI failures create/comment on issues rather than revise an existing application PR. No reviewer-comment, changes-requested, successful-check, or synchronize continuation is wired (`github-issue-triage/configure-route.py:102-128`; `ci-failure-triage/configure-route.py:84-125,147-159`).

## Current-recipe reliability findings (recommended order)

### [DEL-01 / P1] Complete the CI-config edit→commit→PR transition
- **Evidence:** `recipes/ci-failure-triage/configure-route.py:116-121` creates a branch, instructs editing, pushes, then creates a PR, but never stages or commits changes. Contrast the explicit staging and commit in `recipes/github-issue-triage/configure-route.py:73-75`.
- **Impact:** [INFERENCE] Following the supplied sequence literally pushes the unchanged branch; the proposed edit never reaches GitHub and PR creation can fail for lack of commits. An LLM may infer the missing steps, but that is not a complete recipe contract.
- **Fix sketch:** Make the minimal publication sequence explicit, including creating a commit containing only allowed CI-config changes and stopping/reporting when there is no actual change or publication fails.
- **Observable completion:** A CI-config correction produces a remote commit containing the correction and a PR diff limited to the configured directory; a no-change/failing publication produces an explicit non-success report rather than a claimed PR.
- **Impact:** High for the recipe’s only code-writing path. **Effort:** S. **Change risk:** LOW, completes existing intended behavior. **Confidence:** HIGH for the omission; runtime failure is inferred, not reproduced.

### [DEL-02 / P1] Ground CI diagnosis in the failed revision, not the default checkout
- **Evidence:** `recipes/ci-failure-triage/configure-route.py:39-40` exposes the failed run SHA, and `:63-68` asks about the PR diff/exact-commit behavior. However, `:70-78` clones the repository’s default branch then immediately requests git log/blame; it never selects the failed revision or explains PR merge-ref handling.
- **Impact:** [INFERENCE] A failure on a non-default branch, older commit, or PR synthetic merge can be diagnosed using different code/history. This undermines RCA accuracy and the recommended fix handed to issue triage.
- **Fix sketch:** Specify resolution of the run’s actual tested revision and relevant PR/base context before code inspection; report missing/unfetchable revisions instead of silently analyzing current main. Keep diagnosis revision separate from the base chosen for a tuning PR.
- **Observable completion:** For a failed run whose code differs from main, cited files/history correspond to the tested revision and the RCA records that revision. Unavailable revisions yield an explicit evidence limitation.
- **Impact:** High diagnostic correctness. **Effort:** M. **Change risk:** MED, PR merge refs/forks and historical revisions require careful handling. **Confidence:** HIGH for missing binding; misdiagnosis consequence is inferred.

### [DEL-03 / P1] Turn verification from a suggestion into a publication contract
- **Evidence:** `recipes/github-issue-triage/configure-route.py:72-79` tells Claude Code to run a generic command, then instructs commit/push/PR without an explicit success gate or evidence capture. `recipes/github-issue-triage/README.md:68-73` tells adopters to customize the command/tool allowlist; `ci-failure-triage/configure-route.py:116-123` defers verification to a reviewer watching a future run.
- **Impact:** No recipe-level distinction between verified, failed verification, unavailable verification, or delegation failure. [INFERENCE] A PR can be presented as a completed fix without observable evidence that the configured checks ran successfully. This is not proof that Hermes ignores command errors, nor an argument for building a product-wide test platform.
- **Fix sketch:** Define adopter-supplied verification and allowed execution tools, require recorded outcome before publication, and specify blocked/draft reporting where checks cannot run. Include actual verification evidence and known limitations in the PR rather than the current generic body.
- **Observable completion:** A passing change reports command/result against the committed revision; a failing or unavailable check cannot produce an ordinary success announcement or review-ready claim. A representative non-make adopter command is either explicitly supported or clearly rejected during configuration.
- **Impact:** High reviewer trust and reliable unattended handoff. **Effort:** M. **Change risk:** MED, stricter gates can block repositories lacking a configured command. **Confidence:** HIGH for absent local contract; runtime behavior remains untested.

### [DEL-04 / P2, quick win] Correct shared-webhook setup advice
- **Evidence:** `recipes/github-issue-triage/README.md:50-52` says an existing webhook can be shared with another recipe and cites the CI README as justification. `recipes/ci-failure-triage/README.md:38-42` says exactly the opposite: dispatch is by URL, requiring a separate subscription/path/secret.
- **Impact:** Adopters following issue setup can fail to deliver events to the intended route even though both recipes appear configured.
- **Fix sketch:** Use the existing correct CI recipe wording: one webhook subscription per recipe route; adding another event to a webhook does not dispatch to another route.
- **Observable completion:** Both setup documents consistently identify separate endpoint/secret/event selections, with no instruction to share one subscription across recipe paths.
- **Impact:** Medium, direct setup failure with very low fix cost. **Effort:** S. **Change risk:** LOW. **Confidence:** HIGH.

### [DEL-05 / P2] Preserve clarification and current issue context across the handoff
- **Evidence:** `recipes/github-issue-triage/configure-route.py:42-45,72` supplies the issue title/body, not its discussion. Case B asks a GitHub question but directs the answer to normal chat (`:86-90`); the route only subscribes to issue opened/labeled (`:104-120`). Case C explicitly skips ambiguity checking and prioritizes the issue body’s recommended fix (`:57-65`).
- **Impact:** Replies on the GitHub issue do not trigger this route. [INFERENCE] If a human clarifies/corrects an RCA in comments then applies ready-to-fix without rewriting the body, delegation can miss that decision and implement the earlier proposal. Chat may work through upstream Hermes, but this repo does not specify issue-to-chat context correlation or persistence.
- **Fix sketch:** Establish a documented continuation contract using current issue body plus relevant discussion/approved decision. An explicit label remains a sufficient trigger; a new conversational runtime is unnecessary. If chat is retained, identify which issue a reply resumes and write the clarified decision back to GitHub.
- **Observable completion:** A clarified ambiguous issue and an RCA corrected in comments both delegate the latest agreed scope after approval, retaining an auditable question→decision→PR link. A reply for another issue cannot silently resume this one.
- **Impact:** Medium/high correctness of the supervised handoff. **Effort:** M. **Change risk:** MED, context selection must not reinterpret ordinary comments as authorization. **Confidence:** HIGH on missing discussion input/trigger; MED on upstream chat behavior.

### [DEL-06 / P2] Reconcile existing issue work before starting another independent fix
- **Evidence:** Every accepted delivery gets a fresh clone (`recipes/github-issue-triage/configure-route.py:47-53`) and branches/opens a PR (`:69-79`), with no lookup of an existing linked PR or active fix. Opened and ready-to-fix are independent accepted events (`:111-120`). The README’s handoff exercise opens an issue and then labels it (`recipes/github-issue-triage/README.md:58-61`), potentially exercising both paths on a clear issue.
- **Impact:** [INFERENCE] Distinct legitimate opened/label/relabel events can trigger competing fixes, branch collisions or multiple PRs; isolated clones prevent filesystem races but not semantic duplication. This is independent of whether upstream Hermes deduplicates identical webhook deliveries.
- **Fix sketch:** Before implementation, reconcile the issue’s current state and existing linked active PR/work; reuse or report it rather than unconditionally starting a new fix. Clarify how a deliberately requested retry differs from duplicate initiation.
- **Observable completion:** Opening a clear issue then applying/reapplying ready-to-fix results in one active fix/PR or an explicit human-selected retry, not competing independent work. Already closed issues are not blindly implemented from stale events.
- **Impact:** Medium reliability/cost/reviewer confusion. **Effort:** M. **Change risk:** MED, avoid incorrectly suppressing intentional retries. **Confidence:** HIGH for absence in recipe; MED for unobserved runtime consequences.

## Optional lifecycle expansion — not blockers to the stated recipe scope

### [DIR-01] Add an opt-in requirements/design checkpoint for work beyond small fixes
- **Evidence:** `recipes/github-issue-triage/README.md:3-5` intentionally scopes automation to clear small fixes; `configure-route.py:67-72` goes straight from judgment to implementation. CI already has a reusable reasoning shape: options/trade-offs/recommendation/verification (`recipes/ci-failure-triage/configure-route.py:95-98`).
- **Value:** Extend intake to larger work without treating a broad ready-to-fix label as a complete specification. Missing upstream stages are requirement elicitation, explicit acceptance criteria, task decomposition and design approval—not hidden product defects.
- **Fix sketch:** Optional recipe producing a GitHub-native scope/acceptance/design decision for human approval before delegating implementation; retain the existing fast path for genuinely small fixes.
- **Observable completion:** An ambiguous multi-part request produces an approved scope, non-goals and observable acceptance criteria before code starts; rejection/needs-input produces no implementation.
- **Effort:** L. **Risk:** MED, adds friction and potentially an unwanted workflow. **Confidence:** HIGH grounding, maintainer-dependent strategic value.

### [DIR-02] Add supervised review-feedback and CI-repair iteration on the existing PR
- **Evidence:** Issue route’s final action is the PR announcement (`recipes/github-issue-triage/configure-route.py:76-79`), with only issues events (`:104-124`); CI real regressions lead to an issue and another label handoff (`recipes/ci-failure-triage/configure-route.py:84-109,124-125`). Human review/merge is explicit (`github-issue-triage/README.md:26,36-37`).
- **Value:** Fill the missing code-review and PR-iteration stages: reviewer changes and red checks would revise the already proposed branch instead of requiring manual chat work or another issue-to-new-PR cycle.
- **Fix sketch:** Opt-in, explicitly authorized continuation for bot-owned PRs; incorporate actionable review feedback or correlated CI diagnosis, verify, update the same PR and request human review again. Preserve no autonomous merge and keep autonomous application edits out of the CI RCA route itself.
- **Observable completion:** A changes-requested review or approved repair request results in one bounded update to the existing PR with evidence; stale feedback, unrelated PRs and repeated events cannot create new fix loops. Human approval remains necessary to merge.
- **Effort:** L. **Risk:** HIGH, recurring write automation expands scope and needs reliable correlation/authorization. **Confidence:** HIGH that the stage is absent here; strategy is optional.

## Boundaries and rejected overclaims
- Do not label absent autonomous merge, full product planning or AI review as current defects: root README explicitly ends the agent’s job at a reviewable PR (`README.md:96-97`).
- Do not claim upstream Hermes has no sessions, retry/dedup or scheduling capabilities; those were not audited.
- Do not call this repository’s lack of CI/tests itself a surprise product blocker: it is explicitly documented (`README.md`, What you’ll need to bring yourself). For current reliability changes, focused route/prompt contract examples would be useful, but no tests were run or added in this review.
- CI tuning anti-loop exclusion is deliberate (`ci-failure-triage/configure-route.py:155`); it also means its own failures receive no further RCA from this route. That is a documented trade-off, not a reason to remove the guard.
- Human-authorization enforcement, trust boundaries and provisioning belong to Main; relevant Case C filter evidence was passed separately.

# Preserved production-stage audit

## Scope and coverage
Confirmed reading the required playbook sections and Finding format. Inspected all three target configure scripts, including generated Python/Bash scripts, their READMEs, Argo event template, relevant Grafana notification/rule settings, and directly invoked Loki helpers. No issue/CI recipe or provisioning audit. All failure consequences below are static-analysis inferences, not reproduced runtime results. No assumptions about missing upstream Hermes features.

**Present, executable:** failed/degraded Argo notification wiring with sync-operation `oncePer` (`recipes/deployment-failure-rca/argocd-notifications-patch.yaml.example:69–76`); firing-only Grafana route and grouping/repeat intervals (`recipes/grafana-alert-rca/configure-route.py:182–188`, `recipes/grafana-alert-rca/terraform/notifications.tf:64–68`); PR eligibility lookup and JSONL recording; sweep locking between sweep processes, age gating and retry on non-202 HTTP responses (`recipes/postmortem-verification/configure-route.py:79–124,156–187`).

**Present, prompt-guided rather than deterministic:** cause-vs-trigger distinction, correlated log investigation, read-only source history, search/comment/create/reopen issue trail and confidence reporting (`recipes/grafana-alert-rca/configure-route.py:56–128,159–174`); human-reviewed Terraform alert-tuning PRs (`:130–157`); deployment-caused/pre-existing/unrelated diagnosis and rollback recommendation, explicitly no rollback execution (`recipes/deployment-failure-rca/configure-route.py:59–65,93–123`); query extraction, verification judgment, issue transitions and postmortem (`recipes/postmortem-verification/configure-route.py:231–276`). These are real recipe functionality, but not guaranteed structured transitions.

## Prioritized correctness / reliability findings

### [CORRECTNESS-P1] Prevent recorder/sweep races from dropping verification work
- **Evidence:** Recorder appends without acquiring the sweep lock (`recipes/postmortem-verification/configure-route.py:121–122`). Only the sweep takes `flock` (`:156–158`); it reads pending into a separate keep-file, then replaces pending (`:161–187`).
- **Impact:** [INFERENCE] A record appended after the reader reaches EOF but before `mv`, or written through an already-open old inode, can disappear from the live queue. The existing lock prevents overlapping sweeps, not concurrent record writes.
- **Effort:** M. **Risk:** MED—queue-format/locking changes must preserve already-pending jobs. **Confidence:** HIGH.
- **Fix sketch:** Use one consistent transactional protocol for all state writers, either a shared lock covering append/read/replace or a small transactional store. Keep the solution local to the recipe.
- **Observable completion criteria:** Concurrent enqueue while a sweep finalizes retains every unique job; process interruption leaves valid recoverable state; two sweeps cannot claim the same active job.

### [CORRECTNESS-P2] Track verification completion, not merely accepted dispatch
- **Evidence:** A `202` appends the original record to processed, then removes it from pending (`recipes/postmortem-verification/configure-route.py:178–187`). Verification route only supplies a prompt and `deliver: log` (`:279–284`); prompt has GitHub/chat actions but no completion acknowledgment (`:245–276`). Recorder performs no identity lookup before append (`:114–122`).
- **Impact:** [INFERENCE] An accepted job whose investigation later fails or is inconclusive has no recipe-managed follow-up. Duplicate PR deliveries enqueue duplicates. A sweep crash after dispatch but before queue replacement re-dispatches already-accepted work. README's “only runs once per merged fix” claim is unsupported (`recipes/postmortem-verification/README.md:47–49`). This does not claim upstream Hermes lacks retry/deduplication; the recipe neither connects those facilities nor records their outcome.
- **Effort:** M. **Risk:** MED—retrying GitHub mutations requires idempotent side effects. **Confidence:** HIGH.
- **Fix sketch:** Give jobs stable repo/PR/issue/revision identities and separate pending, dispatched and terminal outcome states. Use available upstream completion facilities if supported; otherwise an explicit recipe acknowledgment plus lease/reconciliation.
- **Observable completion criteria:** HTTP acceptance alone never marks an issue verified; failed/inconclusive jobs are visible and resumable; duplicate delivery/restart creates one logical verification and no duplicate terminal comment; terminal records include outcome/evidence/window.

### [CORRECTNESS-P3] Distinguish actual fixing relationships from incidental issue references
- **Evidence:** Closing regex explicitly accepts `refs?` (`recipes/postmortem-verification/configure-route.py:79–80`), then `.search` selects only its first match (`:98–101`). Grafana alert-tuning PRs are explicitly instructed to contain `Refs #n` (`recipes/grafana-alert-rca/configure-route.py:151–155`). Recorder exceptions become successful `[SILENT]` exits and nonzero `gh` status is not checked (`recipes/postmortem-verification/configure-route.py:84–86,103–112`).
- **Impact:** [INFERENCE] An alert-tuning/reference-only PR is treated as shipping the application fix and may lead to premature closure; a PR fixing several issues verifies only the first (or none if its first reference is ineligible). Transient GitHub lookup failures silently lose verification eligibility.
- **Effort:** M. **Risk:** MED—existing users may intentionally rely on `Refs` semantics. **Confidence:** HIGH.
- **Fix sketch:** Define explicit fixing vs related-only links, enumerate every supported fixing link, and deduplicate identities. Distinguish ineligible deliveries from retryable lookup failure. Preserve support for an explicit opt-in verification relationship if desired rather than treating every reference as a fix.
- **Observable completion criteria:** `Refs #n` alone does not assert a fix; two genuine closing relationships enqueue both eligible issues; unrelated first references do not hide later fixes; GitHub timeout/rate-limit produces retriable state, not silent discard.

### [VERIFICATION-P4] Gate closure on deployed revision, adequate observation, and telemetry coverage
- **Evidence:** Eligibility is based solely on elapsed hours (`recipes/postmortem-verification/configure-route.py:164–169`); recorded `merged_at` is webhook handling time, not PR timestamp (`:114–119`). Prompt omits a rendered merge timestamp (`:225–229`) while telling the agent to use “merge time above” (`:237–240`). Zero/near-zero matches count as successful evidence and permit closure (`:242–254`). Empty successful count results print `0 (no series)` (`scripts/loki-format.py:56–60`). README advertises waiting until actually deployed (`recipes/postmortem-verification/README.md:3–5`) but admits the fixed-delay heuristic (`:99–101`).
- **Impact:** [INFERENCE] A delayed/failed rollout can be judged before the fix is live; pre-deploy recurrences within the since-merge window can falsely fail a working fix. Quiet traffic, incorrect selector, or missing ingestion can be mistaken for recovery. API-error handling already exists in the formatter (`scripts/loki-format.py:13–15`), so this is specifically a missing successful-data coverage signal, not swallowed Loki API errors.
- **Effort:** L (coarse). **Risk:** MED—some projects lack deployment metadata/traffic metrics; they must remain inconclusive rather than get false green results. **Confidence:** HIGH.
- **Fix sketch:** Correlate merge/artifact to observed app/environment deployment success, anchor observation after deployment, and require fresh telemetry plus relevant workload/synthetic coverage and explicit failure thresholds before closure. A delayed timer can remain a fallback readiness check, never proof of deployment.
- **Observable completion criteria:** Unshipped revision, absent telemetry, insufficient traffic, or incomplete window cannot close the issue; healthy deployed revision under representative traffic can; recurrence before deployment is distinguished from recurrence after deployment; evidence records exact app/environment/revision/time bounds. Documentation accurately labels fallback behavior.

### [CORRECTNESS-P5] Anchor deployment RCA to the actual rollout range and event window
- **Evidence:** Payload supplies one `.app.status.sync.revision` and operation timestamps, not previous successful deployed revision (`recipes/deployment-failure-rca/argocd-notifications-patch.yaml.example:60–66`). Prompt claims to inspect the change relative to the previously synced revision, but supplies `git show --stat` and `git log -3` (`recipes/deployment-failure-rca/configure-route.py:85–87`), and clones the default branch without checking out the event revision (`:83–88`). Queries described as around the sync window are fixed last-60-minute queries (`:70–78`); helper endpoints are relative to now (`scripts/loki-query.sh:27–36`).
- **Impact:** [INFERENCE] Multi-commit rollouts can be attributed using only the last commit; source reads may use newer default-branch content. Delayed delivery/investigation can miss the actual failure window. The failed sync's revision is called “just deployed” even though deployment may not have succeeded (`recipes/deployment-failure-rca/configure-route.py:54`).
- **Effort:** M. **Risk:** LOW/MED—metadata availability varies by Argo deployment shape. **Confidence:** HIGH for mismatch; MED for exact Argo revision semantics without upstream/runtime inspection.
- **Fix sketch:** Carry or retrieve attempted revision, last successful revision and effective running artifact distinctly; inspect the full delta at pinned revisions; support explicit start/end query bounds with a pre-rollout baseline. Report unknown provenance rather than implying a verified deployed SHA.
- **Observable completion criteria:** A rollout spanning several commits includes all changes; a failed sync distinguishes attempted from running revision; delayed events still query their historical window; all cited code matches the event revision.

## Grounded direction options (not defects in an intentionally RCA-only recipe)

### [DIRECTION-D1] Add recovery and mitigation acknowledgment to the incident trail
- **Evidence:** Grafana suppresses resolved messages (`recipes/grafana-alert-rca/terraform/notifications.tf:39`) and route accepts only firing (`recipes/grafana-alert-rca/configure-route.py:185`). Argo subscribes only to failed/degraded (`recipes/deployment-failure-rca/argocd-notifications-patch.yaml.example:69–76`). Revert action stops at a human recommendation (`recipes/deployment-failure-rca/configure-route.py:64–65,120–121`).
- **Gap not present in these recipes:** No linked success/recovery event, acknowledgment/owner/escalation workflow, or record that a human actually applied the recommended mitigation and it worked. GitHub issue searches and notification grouping are present; they are not a stable incident-state correlation mechanism.
- **Impact:** Operators lack an auditable detection → acknowledgment → mitigation → verified recovery timeline, especially when recovery occurs via rollback/config correction rather than a fixing PR.
- **Effort:** M/L (coarse). **Risk:** MED—must not auto-close RCA work merely because a service recovered. **Confidence:** HIGH for repository gap.
- **Fix sketch:** Add optional correlated recovery/mitigation receipt events and an explicit incident owner acknowledgment, retaining human-controlled rollback. Do not introduce autonomous rollback by default.
- **Observable completion criteria:** One incident links firing/degraded and recovery events; a recorded human rollback includes target revision and outcome; restored service does not imply root-cause remediation; outstanding unacknowledged incidents are observable.

### [DIRECTION-D2] Persist an evidence contract and actionable production learning
- **Evidence:** RCA Evidence/Verification sections are natural-language requirements (`recipes/grafana-alert-rca/configure-route.py:108–112`, `recipes/deployment-failure-rca/configure-route.py:102–105`); verifier scans only issue body for Loki/LogQL/PromQL content and gives up when absent (`recipes/postmortem-verification/configure-route.py:231–241`), although it invokes only the Loki helper. Deployment failures can occur before application logs exist (`recipes/deployment-failure-rca/README.md:9–11`). Follow-up is just text in a postmortem comment (`recipes/postmortem-verification/configure-route.py:262–270`). Grafana example rules explicitly suggest rate/latency/SLO-burn signals but implement LogQL examples (`recipes/grafana-alert-rca/terraform/rules.tf:7–9`).
- **Gap not present in these recipes:** No machine-readable evidence kind/query/scope/expected-result contract, non-log verification path for manifest/sync failures, or explicit accepted follow-up owner/status linking postmortem learning back into remediation work. Current output is useful GitHub knowledge, not a guaranteed completed learning loop.
- **Impact:** Strong RCA conclusions cannot reliably transfer into verification, especially for no-log deployment failures; residual contributing factors remain prose rather than tracked work.
- **Effort:** M for evidence schema and typed verifier hooks; L for optional broader follow-up integration (coarse). **Risk:** MED—avoid turning a recipe repository into a workflow product, and retain human approval for new work.
- **Fix sketch:** Add a compact evidence block supporting log, deployment-health and smoke/SLO result kinds; allow explicit reviewed follow-up links/status. Start with the existing deployment and Loki mechanisms, not a generic plugin platform.
- **Observable completion criteria:** An RCA with no application logs can be verified against actual deployment/resource/smoke evidence; unsupported evidence types stay inconclusive; query updates in follow-up comments are not silently missed; accepted postmortem follow-ups have tracked issue links and completion evidence.

## Priority recommendation
Stabilize state preservation and outcome tracking first (P1/P2), correct fixing-link eligibility (P3), then prevent false verification (P4). Improve event/revision attribution (P5) before broadening automated release feedback. D1/D2 are maintainer options for completing the loop while preserving the repository's recipes/configuration identity and deliberate human rollback boundary. Targeted deterministic acceptance scenarios for the embedded recorder/sweep should accompany any later implementation; none were run or added in this review.

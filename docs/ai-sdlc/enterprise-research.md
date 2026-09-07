# Enterprise AI software lifecycle research

Compiled 2026-09-07 from completed research and supplied cached primary-source extracts. This is a research archive, not a claim that Hermes implements these systems. Metrics retain source denominators, dates, caveats and uncertainty.

## Evidence inventory

Stripe Minions and Spotify Honk are real internal production coding systems built inside existing developer platforms—not autonomous replacements for the entire SDLC. Stripe documents explicit deterministic blueprints and a two-CI-run handback; Spotify documents fleet orchestration, constrained coding workers, mandatory verification and intent judges, with a June 2026 update showing multi-OS CI and a shift toward review/prioritization bottlenecks. All numerical outcomes are first-party self-reports, not independently validated causal productivity estimates.

Uber demonstrates a deployed, precision-first AI second reviewer with explicit feedback and staged rollout; Google demonstrates deployed human-accepted review fixes and a measured migration case study, while warning that offline scores and generated-code counts are not delivered productivity. Four serial Firecrawl network calls; no source edits or tests.

# Preserved research: coding-agent platforms

## Evidence method and dates
Four focused network CLI calls: Stripe Part 2 scrape; attempted Spotify supplied URL (404); one Firecrawl search with full content for three canonical Spotify articles; June 2026 Spotify update scrape. Stripe Part 1 reused Main's cached first-party result. Only research caches created; no source edits, builds, tests or repository validation. Search returned no search ID, so none invented for feedback. Sources are first-party accounts of actual internal adoption. June Spotify article also markets Spotify Portal, and the Part 2 Anthropic endorsement is vendor testimony; neither is independent validation.

## Case 1 — Stripe Minions
**Primary sources:**
- Alistair Gray, *Minions: Stripe’s one-shot, end-to-end coding agents*, **2026-02-09**: https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents
- Alistair Gray, *Minions…Part 2*, **2026-02-19**: https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2

### Actual operational workflow
1. **Intake:** usually tag the Slack app in the thread discussing a change; CLI/web also available. Docs, feature-flag and ticketing UIs have invocation integrations. CI-generated flaky-test tickets offer a user-triggered Minion fix. This is not evidence of universal automatic incident-to-PR execution.
2. **Context:** Slack thread plus links; relevant MCP tools prefetch likely-looking links deterministically before agent startup. Subdirectory/file-pattern rules reuse Cursor conventions and are synchronized for Claude Code rather than duplicating knowledge. Toolshed provides internal docs, tickets, builds and Sourcegraph; nearly 500 tools exist centrally in Part 2, but Minions receive a deliberately small curated subset, optionally expanded by user-selected thematic groups. Do not imply every run gets 500 tools.
3. **Execution:** forked Goose harness on a dedicated prewarmed devbox, an AWS EC2 environment already used by humans. One logical task has a clean environment; multiple runs parallelize without competing over working directories. Warmup includes source checkout, Bazel/type caches and code-generation services.
4. **Deterministic versus agent stages:** code-defined *blueprints* are state-machine-like graphs. Agent nodes implement a task and repair CI failures; deterministic nodes run configured linters and push changes. Nodes can alter tools, prompts and conversation context. Teams can encode specialized migrations in custom blueprints.
5. **Safety:** QA environment; no real user data, production services or arbitrary network egress. Part 1 describes isolation from internet. Separate internal security controls prevent destructive MCP actions. Full local agent permission is justified by the devbox blast-radius boundary, not unrestricted access to Stripe.
6. **Feedback:** deterministic local lint node and local iteration before push; CI runs relevant tests from a >3-million-test corpus, applies available autofixes, then lets an agent try failures without autofixes. At most two pushes/CI runs. After the second, branch goes back to the human for scrutiny even if it still fails. A typical successful run ends CI-green, but this is not an unconditional guarantee.
7. **Human gates:** operator inspects branch/prepared PR. If acceptable, engineer opens PR and asks another Stripe engineer to review. Otherwise sends another instruction or edits manually. Human review remains even for fully agent-written merged PRs. No agent-controlled merge policy, deployment approvals, staged rollout, rollback, or post-release checks described.

### Metrics with caveats
- **Over 1,000 completely Minion-produced merged PRs/week** Feb 9; **over 1,300/week** Feb 19. Counts refer to merged, human-reviewed PRs with no human-written code, not all attempts. No total Stripe PR denominator, rejection rate, attempt success rate, task-size distribution, change-failure rate, cost/PR, or causal productivity comparison supplied. The two snapshots do not establish a durable growth trend.
- **~10-second ready devbox** is a provisioning target/operational description, not end-to-end coding latency or percentile SLA.
- Part 1 local lint executable **<5 seconds**; Part 2 describes cached pre-push fixes **usually well under one second**. These are different levels of specificity, not necessarily a contradictory benchmark.
- **>3 million tests** describes the available corpus; relevant tests are selected, not all executed for every change.
- **At most two CI runs** is a hard orchestration/cost boundary, not an efficacy metric.
- Formal offline eval design, model comparisons and benchmark results are **not disclosed**.

### Short source excerpts
- Part 1: “while they’re human-reviewed, they contain no human-written code.”
- Part 1: “If the code looks good, the engineer opens the PR and requests a review from another Stripe engineer.”
- Part 2: “those particular nodes don’t invoke an LLM at all—they just run code.”
- Part 2: “After the second push and CI run, we send the branch back to its human operator for manual scrutiny.”
- Part 2: “minions don’t have access to real user data, Stripe’s production services, or arbitrary network egress.”

### Hermes implications [INFERENCE]
Use an explicit recipe control plane for required checkout, lint, push, CI and handoff steps; do not ask the delegate to remember required controls. Preserve bounded repair budgets and a distinct incomplete/needs-human outcome. Prefetch incident/ticket context, share repository rules, and keep tool permissions task-scoped. Treat prepared branch, review-ready PR, approved merge and deployed outcome as different persisted states.

## Case 2 — Spotify Honk and Fleet Management
**Primary sources:**
- Max Charas and Marc Bruggmann, *1,500+ PRs Later: Spotify’s Journey with Our Background Coding Agent (Honk, Part 1)*, **November 2025**: https://engineering.atspotify.com/2025/11/spotifys-background-coding-agent-part-1
- Same authors, *Background Coding Agents: Context Engineering (Honk, Part 2)*, **November 2025**: https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2
- Same authors, *Background Coding Agents: Predictable Results Through Strong Feedback Loops (Honk, Part 3)*, **December 2025**: https://engineering.atspotify.com/2025/12/feedback-loops-background-coding-agents-part-3
- Spotify Engineering, *Coding Is No Longer the Constraint: Scaling Developer Experience to Teams and Agents at Spotify*, **2026-06-03**, summarizing chief architect Niklas Gustavsson's talk: https://engineering.atspotify.com/2026/6/code-with-claude-coding-is-no-longer-the-constraint
**Date caveat:** Parts 1–3 extracted article body/metadata do not expose exact publication days; months are established by canonical URLs. Do not invent days. June date appears explicitly in the page. Supplied /2025/11/background-coding-agents-part-1 is a 404; use corrected canonical URL above.

### Actual operational workflow, late 2025
1. **Fleet intake:** engineers define natural-language migrations, replacing the code-transformation portion of existing Fleet Management. Infrastructure still selects repositories, runs containerized jobs, opens PRs, gets reviews and manages merging. Targets include Java records, breaking Scio upgrades, Backstage frontend migration and schema-preserving configuration updates.
2. **Ad hoc intake:** Slack/GitHub Enterprise users first converse with an interactive workflow agent that gathers task context and creates a prompt for the background coder. ADR creation from Slack and product-manager small proposals are concrete examples. Planning/context gathering is distinct from code modification.
3. **Harness:** internal CLI delegates to interchangeable coding agents/models, integrates local MCP formatting/linting, judge, GCP logs and MLflow traces. Early Goose/Aider trials and a homegrown loop were insufficient. Claude Code became best performing for roughly 50 migrations by Part 2, with multi-step task management and subagents.
4. **Important historical limit:** 10 turns per session and three session retries apply to the **earlier homegrown loop**, not a documented current Claude Code/Honk retry limit. That loop had users enumerate files, suffered too-broad/too-narrow context selection and multi-file context exhaustion.
5. **Context and tools:** static, versionable migration prompts specify preconditions including when not to act, concrete examples, one change at a time, and a verifiable end state, ideally tests. Late-2025 coding worker has no documentation or remote code-search tools; humans/workflow agents condense context beforehand. Worker can see relevant source, edit files, invoke verify, use restricted Git (never push/change origin), and allowlisted Bash. Pushing, Slack interaction and prompt construction live outside it.
6. **Sandbox:** container with limited permissions, few binaries and virtually no surrounding-system access. This is stronger and more specific than merely saying “agent runs in CI.”
7. **Deterministic verification:** verifiers activate based on repository contents (e.g. pom.xml). A generic verify tool hides build-system details and returns distilled relevant errors, conserving context. All relevant verifiers must pass before PR creation; Claude Code stop hook enforces this. Failure means no PR and an error to user.
8. **Intent judge:** after deterministic formatting/build/test checks, an LLM judges original prompt against diff to catch off-scope refactors or disabled flaky tests. It is in the same verification loop and can send the agent back to correct scope. It is **not proof of functional correctness**.
9. **Human/release gates:** existing Fleet workflow retains review/merge infrastructure, but Parts 1–3 do not specify a universal human-review requirement for every agent-generated PR. Do not equate “merged into production codebase” with observed runtime deployment success. Rollout strategies, approval tiers, rollback triggers and postdeployment checks are not explained.

### What changed by June 3, 2026
- Honk runs **Claude Agent SDK inside Spotify's harness, in Kubernetes pods**, enabling concurrent cloud sessions.
- Trusted tools can run builds in **CI across multiple operating systems**. This supersedes Part 3's Linux-x86-only verifier limitation and its future plan for broader OS support. Do not repeat that old restriction as current.
- Fleetshift lets humans manage target selection, scheduling, progress and which PRs need attention; Honk performs modifications. Slack thread context still starts ad hoc work. Honk v2 introduces shared sessions, team projects and Chirp orchestration; article does not quantify deployment/adoption of these new collaboration features.
- Backstage exposes ownership, docs and communication capabilities through MCP/CLI to Claude; standardization plus static analysis/linting gives immediate policy feedback. This broad platform statement updates the ecosystem, but is insufficient to say every Honk worker now receives every Backstage capability.
- Review and decisions have become constraints: Spotify is learning where to auto-merge safe work and focus human judgment. The specific risk policy and Honk-only auto-merge fraction remain unknown.

### Numerical claims and denominators
- Part 1: **>1,500 agent-generated PRs merged** cumulatively; no fixed observation period beyond investigation beginning “last February,” no attempt denominator. **Hundreds of developers** interacting; no precise cohort size.
- Part 1: **60–90% total time saving for these migrations versus writing code by hand**. Examples are listed, but number of measured migrations, timing methodology, counterfactual selection, review cost treatment, variance and independent verification are absent. Not a claim for all software work.
- Part 1: **around half of Spotify PRs automated since mid-2024** is the broader Fleet Management system, including deterministic transformations—not Honk's AI share.
- Part 3: across **thousands of sessions**, judge **vetoes about a quarter**, and agent **course-corrects half of vetoed cases**. Conditional denominator matters: half of approximately 25%, not half of all sessions. No exact N, time window, false-positive rate or adjudicated correctness labels. Authors explicitly say no judge eval investment yet.
- June: **>99% of engineers use AI coding tools weekly**; **94% report improved productivity**; **76% increase in PR frequency**. These are org-wide AI-tool/adoption and perception metrics, not Honk-specific throughput or causal speedup. Exact engineer N, survey response rate, baseline period and confounder controls not stated.
- June: **>2.5 million automated maintenance PRs to date, vast majority auto-merged without a human in loop**. This is longstanding Fleet Management, emphatically **not 2.5 million AI-authored PRs**.
- June: recent backend **Java migration took three days**; exact service count, work size and comparison baseline absent. Speaker contrasts a single engineer/few days with hundreds of teams/weeks or months; treat as a case report rather than controlled benchmark.

### Limitations and eval maturity
Late-2025 authors explicitly lack structured prompt/model evaluation and judge evals; they name CI-green-but-functionally-wrong output as the most serious failure. Passing CI, judge approval, and merged PR count are all imperfect proxies for solving the real request. June article does not establish that these eval gaps were resolved. It notes fragmented codebases perform worse and more coding creates more review/prioritization load. No Honk-only spend, latency distribution, production defect rate, rollback rate or postrelease success metric is provided.

### Short source excerpts
- Part 1: “All the surrounding Fleet Management infrastructure — targeting repositories, opening pull requests, getting reviews, and merging into production — remains exactly the same.”
- Part 2: “we don’t currently have code search or documentation tools exposed to our agent.”
- Part 3: “If one of the verifiers fails, the PR isn’t opened and the user is presented with an error message.”
- Part 3: “We have yet to invest in evals for our judge.”
- Part 3: “the judge vetoes about a quarter of them. When that happens, the agent is able to course correct half the time.”
- June: “Honk runs Claude using the Agent SDK, wrapped inside our own harness and deployed in Kubernetes pods”.
- June: “The flip side: we now have 76% more PRs to review.”

### Hermes implications [INFERENCE]
Add non-incident intake paths (planned migration, maintenance, feature request, ADR) while keeping one delegated implementation core. Represent target selection and batch progress explicitly rather than creating a giant autonomous agent prompt. Build a stable verification adapter that chooses repository-specific checks and emits concise evidence. Distinguish deterministic failures, scope-judge warnings/rejections and human review states. Record prompt/recipe/model versions and run outcomes to enable real evals; do not substitute an unvalidated LLM judge or merged count for delayed operational verification. Keep existing incident/RCA-to-delayed-verification strength as a differentiator because these accounts do not demonstrate that full closed loop.

## Comparative conclusion for roadmap
**Strongly supported common pattern:** invest in a predictable environment, clear task/context handoff, shared human-and-agent tooling, limited coding-worker authority, deterministic validation, observable PR lifecycle, and explicit places for human judgment.
**Useful difference:** Stripe's blueprint has an actual bounded CI repair outer loop already in February; Spotify's December account only proposed CI-result reaction, though June confirms multi-OS CI build verification. Do not assume the latter proves exactly the same post-PR repair loop.
**Human-gate distinction:** Stripe explicitly documents another engineer reviewing Minion PRs. Spotify retains mature fleet review/merge controls and also auto-merges substantial broader automation; neither extreme (“all Spotify AI code merges itself” or “every Spotify automation PR requires a human”) is supported.
**Not established by either case:** end-to-end autonomous discovery → requirements approval → architecture → implementation → security approval → rollout → monitored verification → rollback. Hermes should build explicit transitions and evidence contracts for the missing lifecycle, not market delegated PR creation as the complete SDLC.

# Preserved research: review and measurement

## 1. Uber — uReview: deployed AI second reviewer, not replacement approver

**Primary source:** “uReview: Scalable, Trustworthy GenAI for Code Review at Uber,” **August 12, 2025**, by Uber engineers. Requested URL https://www.uber.com/en-US/blog/ureview/ redirects to https://www.uber.com/us/en/blog/ureview/ . This is a first-party operational account, not independent validation or vendor setup guidance.

### Actual workflow and human controls
- Developer submits a diff on Uber’s Phabricator-based review platform. CI invokes uReview, excluding configuration/generated code and experimental directories, then supplies nearby functions, classes and imports.
- Three specialized assistants cover standard bugs/error handling, Uber best practices, and AppSec. Candidate comments undergo secondary-model grading with thresholds per assistant/language/category, semantic deduplication, and suppression of historically low-value categories. Comments arrive inline on the ordinary review surface.
- Engineers mark comments Useful/Not Useful with optional notes. Category, confidence, assistant identity and feedback flow through Kafka to Hive for analysis. Negative-feedback examples become regression benchmarks.
- It is an additional reviewer; the article does not establish automatic approval, merge permission or a hard blocking gate. “Fixer” proposes code changes for human or AI comments, but the article explicitly concentrates on Commenter, so it does not establish Fixer deployment or success rates.
- Rollout proceeded one team/assistant at a time, with dashboards and go/hold decisions. Engineers A/B-tested fixes and tuned thresholds. CI integration avoids relying on voluntary local IDE usage. Existing deterministic linters remain preferred for simple/syntactic rules.

### Evaluation and numerical results, with caveats
- Intro claims **over 90% of approximately 65,000 weekly landed diffs** analyzed. The same article later says **65,000 per month** when discussing costs and separately **over 10,000 commits/week excluding configuration files** in its savings calculation. These units/denominators conflict; quote with this explicit warning rather than flattening into a confident volume claim.
- Deployed across **six monorepos**: Go, Java, Android, iOS, TypeScript, Python. Reports **4-minute median** review latency; no tail latency given.
- **75% usefulness** is based on engineers who interact/rate the tool; participation rate and sample size are not supplied. It is not independently labeled precision across all comments.
- **Over/about 65% addressed** means an automated proxy: rerun uReview **five times on the final commit**; consider a comment addressed only if none reproduces a semantically similar comment, with deletion adjustments. This measures model non-reproduction, not independently verified bug correction. The article claims five reruns virtually eliminate missed detections but supplies no numerical validation of that claim.
- Human-written comparison: **51%** judged bugs by the author and addressed in the same changeset. Not directly comparable to the AI automated-address metric; not a randomized head-to-head trial and not evidence AI outperforms humans overall.
- Curated human-annotated “golden comments” commits are used for precision/recall/F1 and predeployment model selection. Claude 4 Sonnet generator + o4-mini-high grader ranked best; GPT-4.1 grader with the same generator was **4.5 F1 points lower**. Dataset size, absolute best F1 and generalization evidence are not provided in prose.
- **~1,500 hours/week / nearly 39 developer-years annually** is modeled counterfactual savings: internal benchmark assumes a second human would spend **10 minutes/commit**, applied to eligible review volume. This is not directly observed reclaimed work time. Rough stated inputs do not exactly reproduce 1,500 hours, another reason to label approximate. The “order of magnitude cheaper” than third-party tools claim lacks disclosed cost accounting and inherits the inconsistent diff volume.

### Direct supporting excerpts
- Role: “designed to augment the code review process with a second AI reviewer.”
- Address-rate method: “A comment is considered addressed if none of the re-runs reproduce a semantically similar comment.”
- Human-control/rollout: “make objective go/hold decisions for each release.”
- Critical limitation: “only has access to the code, and not to other artifacts like past PRs, feature flag configurations, database schemas, technical documentation.”
- Scope limitation: “much better at catching bugs that are evident from analyzing the source code alone.”

### Limits and Hermes implications
The source explicitly says richer context, performance/test-coverage review and reviewer-focused risk-understanding tools are future work. Despite earlier language about internal-system integration, its limitations section says actual context is code-only; do not describe it as an architecture-aware reviewer. [INFERENCE/recommendation] For Hermes, add a premerge second-review stage with specialized checks, evidence/confidence metadata, deduplication and bounded comment volume. Preserve human approval for architectural/context-dependent decisions. Keep separate metrics for developer usefulness, independently established correctness, patch acceptance, and final production outcome. Adopt curated incident/patch benchmarks and staged go/hold rollout; do not reuse the five-rerun heuristic as proof a production incident was fixed.

## 2. Google — deployed review-fix assistance plus an internal migration case study

### Primary sources and status
1. **May 23, 2023:** “Resolving code review comments with ML,” https://research.google/blog/resolving-code-review-comments-with-ml/ . First-party account of beta followed by full internal launch.
2. **June 6, 2024:** “AI in software engineering at Google: Progress and the path ahead,” https://research.google/blog/ai-in-software-engineering-at-google-progress-and-the-path-ahead/ . Engineering owners describe deployed internal tools and distinguish future agent ambitions.
3. **2024 conference publication listing** (exact day not stated on retrieved page): “Resolving Code Review Comments with Machine Learning,” https://research.google/pubs/resolving-code-review-comments-with-machine-learning/ . Author abstract reports deployment and evolution toward suggesting edits to reviewers at review time.
4. **April 13, 2025** arXiv submission: “Migrating Code At Scale With LLMs At Google,” https://arxiv.org/abs/2504.09691 ; matching publisher author abstract https://dl.acm.org/doi/10.1145/3696630.3728542 . Real internal migration case study, not company-wide autonomous rollout. Full body was not retrieved within the four-call research scope; findings below are restricted to the author abstract, not ACM’s separately labeled AI-generated summary or DX’s secondary account.

### Deployed workflow, automation and human gates
- Review-comment assistance is trained on real reviewed code, reviewer comments and author edits, following DIDACT’s task/activity-oriented approach rather than source code alone.
- Each new reviewer comment triggers a suggested patch. Confidence filtering and additional heuristics decide whether to expose it in the code-review UI/IDE. The human previews, applies and rates the edit; the IDE supports a **three-way merge** if the working copy changed meanwhile. This is human-accepted assistance, not automated merge/release.
- A small curated dataset supports offline precision/recall model selection. Internal beta user feedback identifies repeated failure patterns and informs serving filters. Instrumentation logs previews and applies, exposing losses through the entire opportunity-to-application funnel.
- Initial hidden/less-discoverable suggestions were often ignored; moving a prominent “Show ML-edit” button beside the reviewer comment improved adoption. Conflicts were handled with an “open IDE merge view” path rather than silently overwriting changes.
- By June 2024, deployed internal tools included inline completion, comment resolution, contextual adaptation of pasted code, natural-language edits and predicting build fixes. This supports a breadth-of-workflow claim, but the inspected overview supplies no build-fix safety/test-pass metric; do not invent one. The 2023 review article illustrates generated tests following existing patterns, not an evaluated autonomous test-generation platform.
- Migration study combines **change-location discovery + an LLM** to help developers carry out migrations. Detailed test gating, review policy and agent architecture are not established by its abstract, so those should not be asserted from this evidence.

### Results and empirical methodology
**Review-fix funnel, 2023:**
- Calibrated to **50% target precision**: half the suggested edits on the evaluation dataset judged correct, deliberately trading quantity for quality. This is an offline calibration target, not a claim safe unattended execution.
- Offline model “addresses **52% of comments** with a target precision of 50%.” Online, predictions above target confidence exist for **around 50% of relevant reviewer comments**; the operational eligibility denominator matters.
- **40–50% of previewed suggestions** are applied by authors; not 40–50% of all reviewer comments.
- Preview rate rose from **~20% of generated suggestions in beta to ~40% at launch** after UX changes. Overall fraction of reviewer comments addressed with an ML edit doubled beta→launch. This is a combined evolving-product comparison, not an isolated randomized estimate for one change.
- **More than 70%** of applied edits are applied in the review tool, **fewer than 30%** in the IDE; a channel split, not correctness rates.
- The 2024 research abstract reports **7.5% of all reviewer comments** addressed via applied ML edit; June 2024 overview reports **>8%**. These are different report snapshots, not conflicting estimates to average together.
- “Hundreds of thousands of hours annually” was **expected/projected** in the 2023 article; its **12-week A/B experiment** is explicitly future work, not a completed causal productivity result. The retrieved 2024 abstract still uses future-tense language for the time-savings extrapolation.

**Measurement discipline, June 2024:**
- Engineers emphasize online A/B experiments and UX research because offline metrics are rough proxies. They track acceptances, rejections/corrections, build outcomes and change submissions across tools.
- If using the completion numbers at all: **37% acceptance** denominator is suggestions displayed **>750 ms while user is not typing**; **50% of code characters** means accepted AI characters divided by manually typed + accepted AI characters, **excluding copy-paste**. Neither measures half of delivered production code nor a 50% productivity improvement. These are not the centerpiece of this case.

**Migration study, April 2025:**
- **39 distinct migrations**, **three developers**, **12 months**; **595 submitted code changes containing 93,574 edits**.
- **74.45% of code changes** and **69.46% of edits** were generated by the LLM. These denominators concern the studied migration work, not all Google code or all attempted agent tasks.
- Developers **estimated 50% lower total migration time compared with earlier manual migrations**, and reported high satisfaction. This is a small, observational case study and retrospective self-estimate against historical work, not randomized causal evidence or independently measured enterprise productivity.
- Submission counts demonstrate real work shipped into the codebase; the abstract does not quantify escaped defects, rollbacks, behavior preservation or production impact.

### Direct supporting excerpts
- Human control: “The suggestion is shown as part of the comment and can be previewed, applied and rated as helpful or not helpful.” (2023)
- Trust tradeoff: “Incorrect suggested edits take the developers time and reduce the developers’ trust in the feature.” (2023)
- Causality caveat: “A 12-week A/B experiment across all Google developers will further measure the impact.” (2023)
- Online evaluation: “offline metrics are often only rough proxies of user value.” (2024 overview)
- Workflow integration: “Experiments requiring the user to remember to trigger the feature have failed to scale.” (2024 overview)
- Migration methodology: “39 distinct migrations undertaken by three developers over twelve months.” (2025 author abstract)
- Migration savings qualifier: “estimated a 50% reduction on the total time spent on the migration compared to earlier manual migrations.” (2025 author abstract)

### Limits and Hermes implications
The June 2024 overview calls diagnosis-to-land-a-fix automation only “initial evidence of feasibility,” not an established end-to-end Google SDLC. [INFERENCE/recommendation] Hermes should expand beyond incident-driven PR generation through bounded workflow-triggered recipes: reviewer-comment→proposed edit, build-failure→candidate repair, migration target discovery→small patches. Put preview/apply and conflict-aware rebase/merge handling in existing review surfaces, not an optional separate chat UX. Instrument opportunity→eligible→generated→shown→previewed→applied→merged→verified outcomes, and include review effort/latency, correction and rollback costs. Use historical incident/change traces as task-specific eval data, then validate usefulness through staged online comparison. Treat migration time savings as hypotheses to measure locally, not expected guarantees.

# Additional cached evidence: methodology, internal deployments, and measurement

These sections distill the four supplied search caches, not new web research. Publication dates are from cached article metadata or explicit body dates. Short excerpts support the summaries; source pages are not mirrored. Vendor methodology is not evidence that the vendor operates that entire lifecycle internally.

## AWS AI-DLC — vendor methodology and workflow guidance

**Sources:** [AI-Driven Development Life Cycle: Reimagining Software Engineering](https://aws.amazon.com/blogs/devops/ai-driven-development-life-cycle/) (2025-07-31); [Open-Sourcing Adaptive Workflows for AI-Driven Development Life Cycle (AI-DLC)](https://aws.amazon.com/blogs/devops/open-sourcing-adaptive-workflows-for-ai-driven-development-life-cycle-ai-dlc/) (2025-11-29); [AI-Driven Development Lifecycle for Financial Services](https://aws.amazon.com/blogs/industries/ai-driven-development-lifecycle-for-financial-services/) (2026-05-26; modified 2026-06-08).

The introduction defines three phases: **Inception**, transforming business intent into requirements, stories and units through team “Mob Elaboration”; **Construction**, proposing architecture, domain models, code and tests through “Mob Construction”; and **Operations**, applying accumulated context to infrastructure-as-code and deployments with oversight. Repository-resident plans, requirements and designs carry context between sessions. AI proposes plans and clarifying questions; people validate before execution. “Bolts” replace long sprints in the methodology, but the terminology does not itself demonstrate better results.

Supporting excerpt: AI “implements solutions only after receiving human validation.” This is a prescribed collaboration model, not a measured fleet deployment or enforced runtime authorization boundary.

The adaptive-workflows article rejects mandatory identical steps for every defect, infrastructure port, feature and security patch. Both stage selection and depth should match intent and complexity, with human validation of the proposed breadth and depth. Its Amazon Q Rules/Kiro Steering implementation is described as a workflow scaffold, not a demonstrated hard security control. It warns about process atrophy when humans accept automation passively, asks for recorded approvals and rationale, and calls for tools to slow down when execution outruns validation. Supporting excerpt: “Approved plans are executed, and stakeholders again review and validate the final artifacts.” Claims of velocity, quality and validation by engaged teams have no disclosed sample, controlled comparison, defect rate or cost accounting in the cached article.

The financial-services article extends this guidance to traceability, continuous review, high-fidelity testing, security/resilience checks, IaC, production monitoring feeding future inception, and risk-based release categorization. It recommends mature DevSecOps, fast CI/CD, integration architecture and explicit accountability before scaling; suggests executive alignment, technical enablement and hands-on pilots; and lists counterbalancing metrics including time to deploy/recover, failed deployments, severity, technical debt and customer NPS. These are recommendations, not established regulatory approval or proof that steering files enforce compliance. Supporting excerpt: “AI-DLC amplifies existing capabilities. It does not compensate for foundational gaps.” Product/security assertions in this promotional article are not independently validated here.

### Deployment anecdotes embedded in the guidance: do not conflate them with the method

- **Amazon Bedrock Mantle:** the financial-services article attributes to Andy Jassy's 2025 shareholder letter a rebuild of the inference engine by **six engineers in 76 days using Kiro**, against an original estimate of **40 engineers for one year**. It describes production infrastructure and says some practices later formed part of AI-DLC. This archive has the AWS article's attribution, not an independently retrieved shareholder letter or engineering postmortem. The baseline is an estimate, not a matched manual implementation. Scope equivalence, person-hours, review/security effort, cost, failures and postrelease reliability are unspecified. Do not convert this into a general causal speedup or proof every AI-DLC phase was deployed as described.
- **Unnamed European financial institution:** vendor reports **one product owner + 12 developers / 15 features per sprint** changing to **one product owner + 3 developers / 35 features per sprint**, and **nine external contractor FTEs** removed. No institution identity, sprint length, feature-size normalization, observation period, quality outcomes or causal controls supplied. This is a vendor-reported customer anecdote, not Amazon's internal deployment or a transferable productivity guarantee.
- **CTS-SW illustration:** **1,000 developers at $130K annually = $130M**, hypothetical **15% improvement**, approximately **$20M cost avoidance for $2M investment**, described as **10x return**. This is rounded scenario arithmetic, not observed financial ROI; it does not establish net return or an audited causal saving.

## Amazon Q — actual internal Java modernization, self-reported estimates

**Sources:** [Amazon Q Developer just reached a $260 million dollar milestone](https://aws.amazon.com/blogs/devops/amazon-q-developer-just-reached-a-260-million-dollar-milestone/) (2024-08-01); [Andy Jassy's internal Java upgrade account](https://x.com/ajassy/status/1826608791741493281?lang=en) (2024-08-22).

The AWS post describes actual migration of **tens of thousands of production applications from Java 8/11 to Java 17** with Q Developer, for **over a thousand developers**. This is a bounded modernization deployment, distinct from AI-DLC's later general method. The product section describes analysis, stepwise planning and developer collaboration before edits, but does not disclose a complete internal harness, validation pipeline, merge policy, deployment approval, rollback or postrelease evaluation design. Its “end-to-end” claim concerns application upgrading, not independent ownership of every software lifecycle stage.

The reported **over 4,500 developer-years** is an estimate against manual dependency migration: the post says a dependency can typically take a day or more, applications have dozens, and automation can migrate many in minutes. Supporting excerpt: “we estimated the time saved by looking at the number of Java dependencies we migrated.” This is counterfactual modeled effort, not 4,500 observed years freed, measured headcount reduction or randomized productivity evidence. Distribution, dependency complexity, accounting for review and failed upgrades, uncertainty and baseline audit are not disclosed.

The **$260M annual cost savings** is an annualized infrastructure/performance estimate from Java 17, based on removed hosts—not salary savings from the estimated developer-years. Supporting excerpt: “we looked at the number of hosts we were able to remove.” AWS calls both estimates conservative, but this archive cannot independently validate that qualifier. Do not add these as if they are the same benefit measured twice or attribute all runtime gains to generated code rather than the version upgrade.

Jassy's later post reports average upgrade time from **typically 50 developer-days to a few hours**, **more than 50% of production Java systems upgraded in under six months**, and **79% of auto-generated code reviews shipped without additional changes**. These are first-party executive claims, not independent corroboration of the blog. The 79% denominator is generated reviews, not all attempted upgrades or proof of correctness; “production Java systems” lacks a precise system count. The time comparison is a historical typical manual baseline, not a controlled experiment; no tail latency, failure rate, escaped defects or cost-per-attempt is supplied. The blog and later post are dated snapshots; do not invent consistency checks or exact total populations from rounded numbers. Reddit commentary returned in the search is excluded as primary evidence.

## Microsoft, Accenture and an anonymous Fortune 100 company — randomized assistance experiments

**Sources:** [Microsoft Research publication](https://www.microsoft.com/en-us/research/publication/the-effects-of-generative-ai-on-high-skilled-work-evidence-from-three-field-experiments-with-software-developers/) (body: June 2025); [SSRN author abstract](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4945566) (posted 2024-09-05, written 2025-08-20, revised 2025-08-21); [MIT-hosted draft](https://economics.mit.edu/sites/default/files/inline-files/draft_copilot_experiments.pdf) (February 2025). These are versions of the **same study**, not three independent replications of its pooled estimate. Only the draft abstract/introduction and the two abstract pages are used here; no full-paper methods audit is claimed.

Companies randomized access to GitHub Copilot code-completion assistance as part of ordinary workplace activity. **Three experiments, 4,867 developers**; the draft says experiments lasted **2–8 months**, after which all groups gained access. This is evidence about deployed developer assistance—not autonomous agents, release approval or full-lifecycle delegation. The anonymous organization is an electronics manufacturing company in the draft; do not infer its identity.

The pooled preferred instrumental-variable estimate is a **26.08% increase in weekly completed tasks among tool users (SE 10.3%)**. Supporting abstract excerpt: “Though each experiment is noisy”; SSRN adds that results vary across experiments. Random assignment supports stronger causal inference than self-reported company case studies, but the estimate is not a simple universal treatment-assignment effect, a 26% time reduction, or a guarantee for Hermes. The draft pools and weights periods with larger treatment-status differences. It describes low initial Microsoft uptake followed by control access, a few hundred Accenture participants, and short treatment-status differences during the anonymous company's staggered rollout as power limitations. Take-up, implementation context and estimand matter.

Secondary draft estimates are **13.55% more commits (SE 10.0%)** and **38.38% more compilations (SE 12.55%)**. Compilation count is not a successful-build rate; commit/task output is not final customer value or a production defect measure. Less experienced developers adopted more and benefited more; at Microsoft, tenure/job-title subgroups showed significant gains for newer/junior workers but not longer-tenured/senior workers. This is not proof of zero senior benefit in every setting. The cited extracts do not establish security, escaped defects, rollback, long-term maintainability or end-to-end lifecycle cost effects. Publication-date/version differences are retained rather than assigning the same date to every source.

## DORA — industry measurement, not a single internal agent deployment

**Sources:** [State of AI-assisted Software Development 2025](https://dora.dev/dora-report-2025/) (2025 report landing page); [DORA report announcement](https://cloud.google.com/blog/products/ai-machine-learning/announcing-the-2025-dora-report) (2025-09-23); [DORA 2025: Year in review](https://dora.dev/insights/dora-2025-year-in-review/) (2026-01-07). The full downloadable report and its statistical appendices were not retrieved in this archive; claims below are limited to these official summaries. DORA is presented by Google Cloud with research partners; it is not an independent audit of the vendor case studies above.

The announcement cites **over 100 hours of qualitative data** and survey responses from **nearly 5,000 technology professionals worldwide**. **90% of respondents use AI at work**, **more than 80% believe it improves productivity**, and **30% report little/no trust in AI-generated code**. These are survey-sample adoption, belief and trust statistics, not all developers worldwide or measured individual causal speedups. It also reports **90% of organizations adopted at least one platform** and an association of platform quality with AI value; the summary does not give a separate organization count or sampling/response weighting details.

The central result is an amplifier relationship: AI exposes existing organizational strengths and weaknesses. The 2025 summary reports positive relationships of adoption with **delivery throughput and product performance**, unlike the prior year's throughput result, while a **negative relationship with delivery stability persists**. Supporting excerpt: “AI adoption does continue to have a negative relationship with software delivery stability.” These are reported associations; the summary does not establish causality or universal changes for every team. Do not turn a change across report years into a controlled longitudinal claim.

Recommendations are foundational testing/version control/fast feedback, loosely coupled systems, high-quality internal platforms, clear policy and internal context, and user-centered goals. Cluster analysis identifies **seven team archetypes**, and the companion capabilities model identifies **seven capabilities**; these are different constructs, not two names for the same seven metrics. The year-in-review distinguishes the March generative-AI impact report, September state report and December capabilities model. It also says delivery performance metrics evolved from four to five; it does not enumerate them in the inspected summary, so none are invented here.

The takeaway is to measure stability and outcomes alongside generated work and throughput, not merely increase coding volume. The year-in-review's claim “AI improves throughput, but often at the cost of stability if your foundation isn’t solid” is a research-program interpretation, not evidence that a particular Hermes deployment already meets those foundations.

## Cross-source interpretation boundaries

- Internal deployments: Stripe, Spotify, Uber, Google's review tools/migrations and Amazon's Java upgrades. AWS Mantle is an attributed internal case inside vendor guidance, with a weaker retrieved evidence chain.
- Vendor methodology: AWS AI-DLC and its regulated-industry guidance. Prescribed controls and steering files are not observed enforcement or certified compliance.
- Causal workplace evidence: randomized completion assistance at Microsoft/Accenture/anonymous company, with uptake, estimand and uncertainty caveats.
- Industry associations: DORA's mixed qualitative/survey summaries, not an agent implementation or causal test of one.
- None establishes a complete, unattended enterprise lifecycle from approved requirements through trustworthy production outcome. Earlier Hermes recommendations in the preserved reports are labeled inferences; the implementation contract, not those recommendations, defines the selected design in [architecture.md](architecture.md).

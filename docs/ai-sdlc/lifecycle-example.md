# Historical pre-cutover lifecycle: release-readiness service

## Result

This is immutable provenance from the **pre-cutover CLI experiment**. The CLI actions below are obsolete historical observations, not instructions. Current users work through Hermes and GitHub; administrators run the Python background receiver. This run does **not** prove the new GitHub-only workflow was exercised end to end.

Run `796953d45d5145f3a933` reached **`verified`** after a real model-generated implementation, Docker checks, independent model review, a concrete human-review revision, local merge, container deployment and exact-revision HTTP verification.

- Final commit: `f2224bc757dab0f45eaf065dd2ce045c2cd73cd8`.
- Approved specification hash: `771c36fe6d513361ff5cd22bad45d57b001b525a77c8a4ce3a9057b5ea2149fd`.
- Model/provider: installed Hermes `gpt-5.5` through `openai-codex`; tools disabled.
- Final application checks: **18 passing tests** inside `python:3.12-slim`, nonroot, no network or credentials, read-only input and bounded writable tmpfs.
- Production evidence: HTTP 200, exact final revision, `inconclusive: false`, `passed: true`.
- Deployment recorded at `2026-09-06T23:36:48.061825+00:00`; observed at `2026-09-06T23:36:59.303083+00:00`, exceeding the example's two-second minimum observation interval.
- [Complete structured lifecycle evidence](lifecycle-evidence.json), including failed attempts, reviews, checks, usage and HTTP smoke results.
- [Generated application source and tests](../../examples/release-readiness/README.md). Application code and README are unchanged from the final merged revision; the archived test helper additionally closes HTTP error responses on Python 3.14 and omits an incidental error-wording assertion.

This is a **local deployment experiment**, not a claim of public production availability, real-user load, GitHub PR publication or Loki recovery verification. The user explicitly requested an original lifecycle build; that delegation covered review/approval and merge of this isolated example. The controller itself did not grant approval or merge autonomously.

## What was built

A Python standard-library HTTP service answers whether a release has completed an observation interval:

- `/health`: status and exact `RELEASE_SHA`.
- `/readiness?deployed_at=...&observation_seconds=...`: readiness, elapsed/remaining seconds and revision.
- Future deployment timestamps are not ready, including with a zero-second interval.
- Invalid queries return JSON 400; unknown routes return JSON 404.
- Timezone-aware parsing and a pure explicit-time calculation enable deterministic boundary tests.

The source repo began with only a README. The approved scope was `app.py`, `tests/test_app.py`, and `README.md`. Main did not manually implement or patch the service: implementation and defect repair both came through Hermes proposals and controller-enforced checks.

## Actual progression and failures

1. Submitted an original feature to an isolated Git repository under `~/.hermes/sdlc/examples/release-readiness/source`. Publication was disabled.
2. Hermes planned against base `034302de81696e433d1bfb77dbc3d96c6984a597`. CLI approval authenticated `mushhzz` and checked current repository permissions through GitHub.
3. Two implementation calls failed inside Hermes. Their exact upstream cause was not established; they were not relabeled successes. Added secret-safe exception/enum diagnostics without exposing provider stderr. Bounded retry exhausted and the run required human recovery.
4. Explicit recovery produced complete code, but actual Docker execution returned exit 125: macOS temporary paths under `/var/folders` were unavailable to the Docker daemon. The model could not repair that host infrastructure failure. Moved staging beneath the trusted state directory; Docker startup errors now stop code repair rather than requesting application rewrites.
5. The real candidate then passed 16 tests in Docker. Explicit recovery retained the candidate, reran checks and obtained independent review. Commit `c24566c3e74050fcc25bc0d6077f718d828eaff0` entered `awaiting_review`.
6. Launched that candidate for review. A 5,000-digit `observation_seconds` caused `RemoteDisconnected`: Python's integer conversion limit raised an uncaught `ValueError`. Submitted the concrete HTTP reproduction using `hermes-sdlc revise`, not a manual application edit.
7. Hermes repaired duration parsing without disabling Python's security limit and added regressions. All 18 tests and another independent model review passed. The final reviewed SHA became `f2224bc757dab0f45eaf065dd2ce045c2cd73cd8`.
8. Explicitly fast-forward merged the isolated source repo and acknowledged that actual merge with `hermes-sdlc merged`. No remote branch was pushed.
9. Deployed the merged application in a nonroot, read-only, resource-bounded container on loopback port 8767. The final container mounted only `app.py`, not the checkout or credentials. The old candidate container needed explicit removal because terminating a Docker client did not remove its daemon-owned container.
10. Exercised six actual HTTP scenarios, recorded a deployment receipt, and ran the durable verification job. The controller independently fetched `/health` and matched the final SHA after the configured interval. State became `verified`.

## HTTP smoke results

| Scenario | Observed response |
| --- | --- |
| Health | 200, status `ok`, final revision |
| Old deployment, two-second interval | 200, `ready: true`, remaining zero |
| Future deployment, zero-second interval | 200, `ready: false`, elapsed zero |
| Missing readiness parameters | 400 JSON |
| Unknown route | 404 JSON |
| 5,000-digit duration | 400 JSON, `observation_seconds is too large` |

The oversized-duration scenario failed before the lifecycle revision and passed on the deployed revised service. This is an observed bug fix, not merely a newly green test.

## Other historical verification

- Controller: `python3 -m unittest discover -s tests -v` — 20 passing boundary/recovery/concurrency/authentication scenarios.
- Model evaluation: three of three labeled cases passed with the real installed model; see [evaluation-results.json](evaluation-results.json). Cases cover rejecting an authentication bypass despite passing tests, accepting a correct boundary implementation without stylistic noise, and respecting file scope despite injected task text. This small suite is not a productivity benchmark.
- Provisioning: `ansible-playbook --syntax-check -i provisioning/inventory.example.ini provisioning/playbook.yml` passed. No remote machine was provisioned.
- Installed CLI: `hermes-sdlc doctor` found Hermes, Git, GitHub CLI, Docker daemon and the check image; publication disabled and root-project production checks absent were reported explicitly.
- Installed listener: `/health` returned ready; authenticated GitHub ping returned 200. The regression suite separately exercised durable 202 receipt, duplicate 200 and invalid-signature 401.

## Re-run the generated application

```bash
cd examples/release-readiness
RELEASE_SHA=f2224bc757dab0f45eaf065dd2ce045c2cd73cd8 python3 app.py --host 127.0.0.1 --port 8767
# Separate terminal:
curl http://127.0.0.1:8767/health
python3 -m unittest discover -s tests -v
```

The revision above identifies the original isolated example build, not a future commit of this containing repository. Set the real deployed revision when modifying/releasing the service. The example container is stopped after validation; the source and durable evidence remain.

Inspect the retained [structured lifecycle evidence](lifecycle-evidence.json) for this run's history; no current command can replay the removed CLI. To repeat the lifecycle rather than merely launch the archived application, ask Hermes to create a new GitHub issue with the requirements, review the resulting specification and approve its new run/hash yourself on GitHub. Use normal PR reviews/human merge and authenticated deployment events as described in [operations](operations.md). Configure a dedicated bot and real delivery integration first; do not reuse this historical SHA or receipt as evidence of a new release.

## Boundaries not exercised

No live GitHub PR creation, bot push, remote CI revision event, issue close/reopen, public webhook ingress, external deployment integration or Loki queries were performed. Those adapters are implemented but require a dedicated bot identity, repository policy, trusted delivery receipts and actual telemetry configuration. Human merge/deploy/rollback authority is deliberately retained. A short local HTTP observation establishes endpoint/revision health only, not sustained service reliability or business success.

"""Bounded lifecycle orchestration. Model text never authorizes side effects."""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .adapters import Runtime, AdapterError, timestamp
from .config import safe_path, ConfigurationError
from .store import Store, Conflict, fingerprint
from .incidents import normalize

SHA = re.compile(r'^[0-9a-f]{40}$')
KINDS = {'feature', 'bug', 'incident', 'maintenance', 'migration'}

APPROVAL_UNCHECKED = '- [ ] Approve this revision for implementation'
APPROVAL_CHECKED = '- [x] Approve this revision for implementation'

class Deferred(RuntimeError):
    """Authenticated event arrived before its lifecycle prerequisite."""


def _plan_comment(run_id, spec, digest, *, state='awaiting_approval', approved_by=None, changes=()):
    """Present the unchanged, fingerprinted specification for human review."""
    from html import escape

    def text(value):
        # Model prose cannot open HTML/Markdown constructs around trusted controls.
        return re.sub(r'([\\`*_\[\]{}()#+.!|>~-])', r'\\\1', escape(value))

    def items(values, numbered=False):
        return '\n'.join(
            (f'{index}. ' if numbered else '- ') + text(value).replace('\n', '\n   ')
            for index, value in enumerate(values, 1))

    scope = '\n'.join('- <code>' + escape(path) + '</code>' for path in spec['files'])
    status = state.replace('_', ' ').capitalize()
    if state in {'planning', 'awaiting_approval'}:
        status = 'Awaiting human approval'
    approval = (
        f'Approved by **{escape(approved_by)}** for revision **{spec["revision"]}**.'
        if approved_by else
        APPROVAL_UNCHECKED if state in {'planning', 'awaiting_approval'} else
        'Approval is unavailable while this run is ' + status.lower() + '.')
    return (
        '## Kira · Implementation plan\n\n'
        + text(spec['summary']) + '\n\n'
        + f'**Risk:** {spec["risk"].capitalize()} · **Status:** {status} · **Revision:** {spec["revision"]}\n\n'
        + ('### Changed since previous revision\n\n' + '\n'.join('- ' + item for item in changes) + '\n\n' if changes else '')
        + '### Scope\n\n' + scope + '\n\n'
        + '### Acceptance criteria\n\n' + items(spec['acceptance']) + '\n\n'
        + '### Implementation steps\n\n' + items(spec['steps'], numbered=True) + '\n\n'
        + '### Design\n\n' + text(spec['design']) + '\n\n'
        + '### Rollback\n\n' + text(spec['rollback']) + '\n\n'
        + '### Approve this plan\n\n'
        + 'Discuss changes in an ordinary issue comment before approving. '
          'Approval authorizes implementation only—not PR merge or deployment.\n\n'
        + approval + '\n\n'
        + '<details>\n<summary>Specification reference</summary>\n\n'
        + f'- **Run:** `{run_id}`\n'
        + f'- **Base commit:** `{spec["base_sha"]}`\n'
        + f'- **Revision:** {spec["revision"]}\n'
        + f'- **SHA-256:** `{digest}`\n\n'
        + '</details>'
    )


class Engine:
    def __init__(self, config, runtime=None):
        self.config = config
        self.store = Store(config['state_dir'])
        self.runtime = runtime or Runtime(config)

    def submit(self, project, kind, title, body, key=None, metadata=None, *, coalesce=False):
        if project not in self.config['projects'] or kind not in KINDS:
            raise Conflict('Unknown project or work kind')
        if not isinstance(title, str) or not title.strip() or not isinstance(body, str) or not body.strip():
            raise Conflict('A title and explicit task are required')
        if len(title) > 256 or len(body.encode()) > self.config['limits']['max_context_bytes']:
            raise Conflict('Task exceeds input limits')
        return self.store.create(project, kind, title, body, key, metadata, coalesce=coalesce)

    def incident(self, project, source, provider, payload):
        observation = normalize(provider, payload)
        if observation is None:
            return
        key = f'incident:{source}:{observation["identity"]}'
        self.submit(project, 'incident', observation['title'], observation['body'], key,
                    {'incident': {**observation, 'source': source, 'observed_at': time.time()}},
                    coalesce=True)

    def authorize(self, project_name, actor):
        project = self.config['projects'][project_name]
        if actor not in project['approvers'] or actor == project.get('bot_login'):
            raise Conflict('Actor is not an approved human reviewer')
        user = self.runtime.github('GET', f'/users/{actor}')
        if user.get('type') != 'User':
            raise Conflict('Automation identities cannot approve work')
        permission = self.runtime.github('GET', f'/repos/{project_name}/collaborators/{actor}/permission')
        if permission.get('permission') not in {'write', 'maintain', 'admin'}:
            raise Conflict('Approver no longer has repository write permission')


    def context(self, run, workspace, selected=None):
        paths = self.runtime.git(workspace, 'ls-files').splitlines()
        files, size = {}, 0
        maximum = self.config['limits']['max_context_bytes']
        candidates = selected if selected is not None else paths
        for relative in candidates:
            try:
                safe_path(relative)
            except ConfigurationError:
                continue
            source = workspace / relative
            if source.is_symlink() or not source.resolve().is_relative_to(workspace.resolve()):
                continue
            if not source.is_file() or source.stat().st_size > maximum:
                continue
            try:
                text = source.read_text()
            except (UnicodeError, OSError):
                continue
            if size + len(text.encode()) > maximum:
                if selected is not None:
                    raise AdapterError('Approved context exceeds budget; split the task')
                continue
            size += len(text.encode())
            files[relative] = text
        project = self.config['projects'][run['project']]
        return {'title': run['title'], 'task': run['body'], 'kind': run['kind'],
                'repository_files': paths[:5000], 'files': files, 'allowed_paths': project['allowed_paths'],
                'checks': [{'name': c['name'], 'argv': c['argv']} for c in project['checks']],
                'specification': run['data'].get('spec'), 'base_sha': run['data'].get('base_sha')}

    def propose(self, job, stage, context):
        run = self.store.get(job['run_id'])
        count = run['data'].get('model_calls', 0)
        if count >= self.config['limits']['max_model_calls']:
            raise AdapterError('Model call budget exhausted; human intervention required')
        self.store.checkpoint(job, {'model_calls': count + 1}, 'model_started', {'stage': stage, 'call': count + 1})
        start = time.monotonic()
        result = self.runtime.propose(stage, context)
        self.store.checkpoint(job, {}, 'model_completed', {'stage': stage, 'model': result.get('model'),
                              'usage': result.get('usage', {}), 'duration_seconds': time.monotonic() - start})
        return result['proposal']

    def plan(self, job):
        run = self.store.get(job['run_id'])
        project = self.config['projects'][run['project']]
        if run['data'].get('incident'):
            if project['publish'] and not run['data'].get('issue'):
                issue = self.runtime.incident_issue(run['project'], project, run)
                self.store.checkpoint(job, {'issue': issue}, 'incident_issue', {'number': issue})
                run = self.store.get(run['id'])
        workspace = self.runtime.prepare(project, run['id'])
        if run['data'].get('incident') and 'incident_evidence' not in run['data']:
            evidence = self.runtime.incident_evidence(run['project'], project, run['data']['incident'], workspace)
            self.store.checkpoint(job, {'incident_evidence': evidence}, 'incident_evidence', {'results': evidence})
        base = self.runtime.git(workspace, 'rev-parse', 'HEAD')
        self.store.checkpoint(job, {'workspace': str(workspace), 'base_sha': base}, 'base_pinned', {'sha': base})
        run = self.store.get(run['id'])
        context = self.context(run, workspace)
        if run['data'].get('incident'):
            context['incident_evidence'] = run['data'].get('incident_evidence', [])
        context['feedback'] = job['payload'].get('feedback', '')
        spec = self.propose(job, 'plan', context)
        required = ('summary', 'design', 'rollback')
        if any(not isinstance(spec.get(k), str) or not spec[k].strip() for k in required):
            raise AdapterError('Plan lacks summary, design or rollback')
        for key in ('acceptance', 'steps', 'files'):
            if not isinstance(spec.get(key), list) or not spec[key] or not all(isinstance(v, str) and v.strip() for v in spec[key]):
                raise AdapterError(f'Plan needs a nonempty {key} list')
        if spec.get('risk') not in {'low', 'medium', 'high'}:
            raise AdapterError('Plan has no recognized risk classification')
        if len(spec['files']) > self.config['limits']['max_files'] or len(set(spec['files'])) != len(spec['files']):
            raise AdapterError('Plan has duplicate or excessive file scope')
        for path in spec['files']:
            safe_path(path, project['allowed_paths'])
        spec['base_sha'] = base
        spec['revision'] = run['data'].get('spec_revision', 0)
        previous = run['data'].get('spec')
        changes = [key.replace('_', ' ').capitalize() + ' updated.'
                   for key in ('summary', 'acceptance', 'files', 'steps', 'design', 'rollback')
                   if previous and previous.get(key) != spec.get(key)]
        digest = fingerprint(spec)
        self.store.checkpoint(job, {'spec': spec, 'spec_hash': digest, 'plan_changes': changes},
                              'specification', {'spec': spec, 'digest': digest})
        self.publish_plan(run['id'])
        self.store.finish(job, 'awaiting_approval')

    def apply_changes(self, workspace, project, spec, proposal):
        changes = proposal.get('changes')
        if not isinstance(changes, list) or len(changes) > self.config['limits']['max_files']:
            raise AdapterError('Proposal needs bounded file changes')
        seen = set()
        total = 0
        staged = []
        # Validate the entire proposal before writing a single file.
        for change in changes:
            if not isinstance(change, dict):
                raise AdapterError('Malformed file change')
            relative = safe_path(change.get('path'), project['allowed_paths'])
            if relative not in spec['files'] or relative in seen:
                raise AdapterError('Change is outside the approved file set or duplicated')
            seen.add(relative)
            content = change.get('content')
            if content is not None and not isinstance(content, str):
                raise AdapterError('File contents must be UTF-8 text or null deletion')
            total += len((content or '').encode())
            if total > self.config['limits']['max_output_bytes']:
                raise AdapterError('Proposed file contents exceed output budget')
            target = workspace / relative
            if not target.resolve().is_relative_to(workspace.resolve()) or target.is_symlink():
                raise AdapterError('Symlink/path traversal in proposed change')
            for parent in target.parents:
                if parent == workspace:
                    break
                if parent.is_symlink():
                    raise AdapterError('Symlink parent in proposed change')
            staged.append((target, content))
        for target, content in staged:
            if content is None:
                if target.exists() and not target.is_file():
                    raise AdapterError('Only files can be deleted')
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)

    def implement(self, job):
        run = self.store.get(job['run_id'])
        project = self.config['projects'][run['project']]
        spec = run['data']['spec']
        if fingerprint(spec) != run['data']['spec_hash']:
            raise Conflict('Specification changed after approval')
        if not any(e['kind'] == 'approved' and e['value']['spec_hash'] == run['data']['spec_hash'] for e in self.store.history(run['id'])):
            raise Conflict('No approval for this specification')
        workspace = self.runtime.prepare(project, run['id'], run['data']['base_sha'])
        feedback = job['payload'].get('feedback', '')
        # Each job has a checkpointed successful commit: crash retries publish that commit,
        # rather than asking a nondeterministic model to regenerate an already-reviewed diff.
        completion_key = f'job_{job["id"]}_verified_sha'
        if not run['data'].get(completion_key):
            for attempt in range(self.config['limits']['max_attempts']):
                context = self.context(self.store.get(run['id']), workspace, spec['files'])
                context['feedback'] = feedback
                proposal = self.propose(job, 'revise' if feedback or job['action'] == 'revise' else 'implement', context)
                self.apply_changes(workspace, project, spec, proposal)
                checks = self.runtime.check(project, workspace)
                self.store.checkpoint(job, {}, 'checks', {'attempt': attempt + 1, 'results': checks})
                if any(c['exit_code'] == 125 for c in checks):
                    raise AdapterError('Docker could not start a check container; fix sandbox configuration before retrying')
                if not checks or not all(c['passed'] for c in checks):
                    feedback = {'failed_checks': checks}
                    continue
                review_context = self.context(self.store.get(run['id']), workspace, spec['files'])
                review_context['checks'] = checks
                review_context['diff'] = self.runtime.git(workspace, 'diff', '--no-ext-diff', run['data']['base_sha'])
                verdict = self.propose(job, 'review', review_context)
                if verdict.get('verdict') not in {'pass', 'fail'} or not isinstance(verdict.get('findings'), list):
                    raise AdapterError('Independent review returned no valid verdict')
                self.store.checkpoint(job, {}, 'review', verdict)
                if verdict['verdict'] != 'pass':
                    feedback = {'review_findings': verdict['findings']}
                    continue
                self.runtime.git(workspace, 'add', '--', *spec['files'])
                changed = self.runtime.git(workspace, 'diff', '--cached', '--name-only').splitlines()
                if not changed:
                    if self.runtime.git(workspace, 'rev-parse', 'HEAD') == run['data']['base_sha']:
                        raise AdapterError('Implementation produced no change')
                else:
                    if any(path not in spec['files'] for path in changed):
                        raise AdapterError('Staged diff exceeds approved scope')
                    self.runtime.git(workspace, 'commit', '-m', f"sdlc: {run['title']} [{run['id']}]")
                sha = self.runtime.git(workspace, 'rev-parse', 'HEAD')
                self.store.checkpoint(job, {completion_key: sha, 'head_sha': sha}, 'verified_commit', {'sha': sha})
                break
            else:
                self.store.finish(job, 'needs_human', evidence=('repair_budget_exhausted', {'feedback': feedback}))
                self.comment(self.store.get(run['id']), f'repair-exhausted-{job["id"]}', self.status_text(run['id']))
                return
        run = self.store.get(run['id'])
        body = f"Kira SDLC run `{run['id']}`\n\nSpecification: `{run['data']['spec_hash']}`\n\n" + spec['summary']
        if run['data'].get('issue'):
            body += f"\n\nRefs #{run['data']['issue']} (closure requires production verification)"
        body += '\n\nDeterministic checks and an independent proposal review passed. Human review and merge are still required.'
        pr = self.runtime.publish(run['project'], project, run['id'], workspace, run['title'], body)
        self.store.finish(job, 'awaiting_review', {'pr': pr, 'head_sha': pr['head_sha']}, ('review_ready', pr))
        if pr.get('merged_sha'):
            self.merged(run['id'], pr['merged_sha'])

    def publish_plan(self, run_id):
        run = self.store.get(run_id)
        project = self.config['projects'][run['project']]
        spec = run['data'].get('spec')
        number = run['data'].get('issue')
        if not project['publish'] or not number or not spec:
            return
        if self.runtime.identity() != project['bot_login']:
            raise AdapterError('Wrong identity for publishing lifecycle evidence')
        digest = run['data'].get('spec_hash')
        approved_by = next((e['value']['actor'] for e in self.store.history(run_id)
                            if e['kind'] == 'approved' and e['value']['spec_hash'] == digest), None)
        tag = f'<!-- hermes-sdlc:{run_id}:plan -->'
        body = _plan_comment(run_id, spec, digest or fingerprint(spec), state=run['state'],
                             approved_by=approved_by, changes=run['data'].get('plan_changes', []))
        controls = int(not approved_by and run['state'] in {'planning', 'awaiting_approval'})
        if body.count(APPROVAL_UNCHECKED) != controls or APPROVAL_CHECKED in body:
            raise AdapterError('Plan rendering contains ambiguous approval controls')
        body += '\n\n' + tag
        metadata = run['data'].get('plan_comment')
        endpoint = f'/repos/{run["project"]}/issues'
        if metadata:
            comment = self.runtime.github('GET', f'{endpoint}/comments/{metadata["id"]}')
        else:
            # Reconcile both an interrupted POST and pre-cutover plans, oldest first.
            comment = None
            page = 1
            legacy = re.compile(r'<!-- hermes-sdlc:' + re.escape(run_id) + r':plan-[0-9a-f]{64} -->$')
            while comment is None:
                comments = self.runtime.github('GET', f'{endpoint}/{number}/comments?per_page=100&page={page}')
                comment = next((c for c in comments if c.get('user', {}).get('login') == project['bot_login']
                                and (c.get('body', '').endswith(tag) or legacy.search(c.get('body', '')))), None)
                if len(comments) < 100:
                    break
                page += 1
        if comment:
            if (comment.get('user', {}).get('login') != project['bot_login']
                    or comment.get('issue_url') != f'https://api.github.com/repos/{run["project"]}/issues/{number}'):
                raise Conflict('Canonical plan is not owned by the bot on the run issue')
            # Do not erase a legitimate click while its signed event is still queued.
            pending_click = (body.count(APPROVAL_UNCHECKED) == 1
                             and comment['body'] == body.replace(APPROVAL_UNCHECKED, APPROVAL_CHECKED, 1))
            if comment['body'] != body and not pending_click:
                self.runtime.github('PATCH', f'{endpoint}/comments/{comment["id"]}', {'body': body})
        else:
            comment = self.runtime.github('POST', f'{endpoint}/{number}/comments', {'body': body})
        self.store.record_plan_comment(run, comment['id'], body)

    def plan_interaction(self, name, payload):
        comment = payload.get('comment', {})
        actor = payload.get('sender', {}).get('login')
        project = self.config['projects'][name]
        if actor not in project['approvers'] or actor == project['bot_login']:
            return
        number = payload.get('issue', {}).get('number')
        run = next((r for r in self.store.list(name) if r['data'].get('issue') == number), None)
        if run is None:
            return
        action = payload.get('action')
        if action == 'created':
            body = comment.get('body', '').strip()
            if not body or body.startswith('/'):
                return
            if any(e['kind'] == 'approved' for e in self.store.history(run['id'])):
                return
            self.authorize(name, actor)
            self.live_human_comment(name, payload)
            request_id = f'github:{name}:{comment["id"]}'
            if any(e['kind'] == 'human_recovery' and e['value'].get('request_id') == request_id
                   for e in self.store.history(run['id'])):
                return
            if run['state'] in {'queued', 'planning'}:
                raise Deferred('Feedback waits for the current planning checkpoint')
            if run['state'] not in {'awaiting_approval', 'needs_human'}:
                return
            self.store.recover(run['id'], 'plan', actor, body, request_id=request_id)
            self.publish_plan(run['id'])
            return
        if action != 'edited':
            return
        metadata = run['data'].get('plan_comment')
        if (metadata is None and run['state'] in {'queued', 'planning'}
                and comment.get('user', {}).get('login') == project['bot_login']
                and comment.get('body', '').endswith(f'<!-- hermes-sdlc:{run["id"]}:plan -->')):
            raise Deferred('Approval waits for canonical comment publication')
        if not metadata or metadata['id'] != comment.get('id'):
            return
        self.authorize(name, actor)
        if run['state'] in {'queued', 'planning'} and not any(
                e['kind'] == 'approved' for e in self.store.history(run['id'])):
            raise Deferred('Approval waits for the planning publication checkpoint')
        before = payload.get('changes', {}).get('body', {}).get('from')
        after = comment.get('body')
        # A replay after successful approval has no further effect, even after UI refresh.
        if any(e['kind'] == 'approved' and e['value']['spec_hash'] == metadata['spec_hash']
               for e in self.store.history(run['id'])):
            self.publish_plan(run['id'])
            return
        live = self.runtime.github('GET', f'/repos/{name}/issues/comments/{metadata["id"]}')
        valid = (
            metadata['spec_hash'] == run['data'].get('spec_hash')
            and metadata['revision'] == run['data']['spec']['revision']
            and before == metadata['body'] and before.count(APPROVAL_UNCHECKED) == 1
            and APPROVAL_CHECKED not in before
            and after == before.replace(APPROVAL_UNCHECKED, APPROVAL_CHECKED, 1)
            and live.get('body') == after
            and live.get('user', {}).get('login') == project['bot_login']
            and comment.get('user', {}).get('login') == project['bot_login']
            and live.get('issue_url') == f'https://api.github.com/repos/{name}/issues/{number}')
        if not valid:
            self.publish_plan(run['id'])
            raise Conflict('Only the current plan approval checkbox may change')
        self.store.approve(run['id'], metadata['spec_hash'], actor, plan_comment=metadata)
        self.publish_plan(run['id'])

    def live_human_comment(self, name, payload):
        comment = payload['comment']
        actor = payload.get('sender', {}).get('login')
        live = self.runtime.github('GET', f'/repos/{name}/issues/comments/{comment["id"]}')
        if (live.get('body') != comment.get('body') or live.get('user', {}).get('login') != actor
                or comment.get('user', {}).get('login') != actor or live.get('user', {}).get('type') != 'User'
                or live.get('issue_url') != f'https://api.github.com/repos/{name}/issues/{payload["issue"]["number"]}'):
            raise Conflict('Comment does not match its live human author and issue')
        return live

    def comment(self, run, marker, text):
        project = self.config['projects'][run['project']]
        number = run['data'].get('issue') or (run['data'].get('pr') or {}).get('number')
        if not project['publish'] or not number:
            return
        if self.runtime.identity() != project['bot_login']:
            raise AdapterError('Wrong identity for publishing lifecycle evidence')
        tag = f'<!-- hermes-sdlc:{run["id"]}:{marker} -->'
        comments = self.runtime.github('GET', f'/repos/{run["project"]}/issues/{number}/comments?per_page=100')
        for comment in comments:
            if tag in comment['body'] and comment['user']['login'] == project['bot_login']:
                return
        self.runtime.github('POST', f'/repos/{run["project"]}/issues/{number}/comments', {'body': text + '\n\n' + tag})

    def merged(self, run_id, sha, actor=None, pr=None):
        run = self.store.get(run_id)
        project = self.config['projects'][run['project']]
        if not SHA.fullmatch(sha):
            raise Conflict('A full merge SHA is required')
        if run['state'] == 'awaiting_deployment' and run['data'].get('merge_sha') == sha:
            return
        if project['publish']:
            number = (run['data'].get('pr') or {}).get('number')
            live = self.runtime.github('GET', f'/repos/{run["project"]}/pulls/{number}')
            if not live.get('merged') or live.get('merge_commit_sha') != sha or live['head']['sha'] != run['data']['head_sha']:
                raise Conflict('Live merged PR does not match the verified commit')
            actor = live['merged_by']['login']
            if live['merged_by'].get('type') != 'User':
                raise Conflict('Merge must be performed by a human, not automation')
            self.authorize(run['project'], actor)
            required = project['required_ci_checks']
            if required:
                workflows = self.runtime.github('GET', f'/repos/{run["project"]}/actions/runs?head_sha={run["data"]["head_sha"]}&per_page=100')['workflow_runs']
                latest = {}
                for workflow in workflows:
                    key = workflow['name']
                    if key not in latest or (workflow['id'], workflow.get('run_attempt', 1)) > (latest[key]['id'], latest[key].get('run_attempt', 1)):
                        latest[key] = workflow
                if any(name not in latest or latest[name].get('conclusion') != 'success' for name in required):
                    raise Conflict('Required CI workflows are not successful for the verified SHA')
        elif actor:
            self.authorize(run['project'], actor)
            workspace = Path(run['data']['workspace'])
            if not self.runtime.git(workspace, 'merge-base', '--is-ancestor', run['data']['head_sha'], sha) == '':
                raise Conflict('Merged commit must include the verified implementation')
        else:
            raise Conflict('A verified human merge acknowledgment is required')
        if actor == project.get('bot_login'):
            raise Conflict('Bot cannot approve its own merge')
        self.store.transition(run_id, 'awaiting_deployment', {'awaiting_review'}, {'merge_sha': sha}, ('merged', {'sha': sha, 'actor': actor}))
        self.publish_plan(run_id)

    def deployed(self, run_id, deployment):
        run = self.store.get(run_id)
        project = self.config['projects'][run['project']]
        if deployment.get('repository') != run['project'] or deployment.get('environment') != project['environment']:
            raise Conflict('Deployment repository/environment does not match the run')
        if deployment.get('sha') != run['data'].get('merge_sha'):
            raise Conflict('Deployment is not the merged revision')
        start = timestamp(deployment['deployed_at'])
        if start > time.time() + 30 or start < run['created']:
            raise Conflict('Deployment timestamp is outside the run lifetime')
        if not isinstance(deployment.get('id'), (str, int)):
            raise Conflict('Deployment identity required')
        self.store.schedule(run_id, 'verify', {'deployment': deployment}, f'{run_id}:deployment:{deployment["id"]}',
                            {'awaiting_deployment', 'needs_human'}, {'deployment': deployment},
                            available=start + project['observation_seconds'])
        self.publish_plan(run_id)

    def verify(self, job):
        run = self.store.get(job['run_id'])
        project = self.config['projects'][run['project']]
        deployment = job['payload'].get('deployment')
        if deployment != run['data'].get('deployment'):
            raise Conflict('Verification job no longer matches the active deployment')
        results = self.runtime.production(project, deployment)
        passed = bool(results) and all(r.get('passed') and not r.get('inconclusive') for r in results)
        self.comment(run, f'verification-{job["id"]}', '## Deployment verification\n\n' + json.dumps(results, indent=2))
        if project['publish'] and run['data'].get('issue'):
            # Only operate on issues created by the configured bot, never labels as ownership proof.
            issue = self.runtime.github('GET', f'/repos/{run["project"]}/issues/{run["data"]["issue"]}')
            if issue['user']['login'] == project['bot_login']:
                self.runtime.github('PATCH', f'/repos/{run["project"]}/issues/{issue["number"]}',
                                    {'state': 'closed' if passed else 'open'})
        self.store.finish(job, 'verified' if passed else 'needs_human', {'production_evidence': results},
                          ('production_verified' if passed else 'production_inconclusive_or_failed', {'results': results}))

    def find_pr(self, project, number, branch=None):
        for run in self.store.list(project):
            if (run['data'].get('pr') or {}).get('number') == number or branch == f'sdlc/{run["id"]}':
                return run
        return None

    def github_command(self, name, payload):
        comment = payload.get('comment', {})
        body = comment.get('body', '').strip()
        header, _, feedback = body.partition('\n')
        match = re.fullmatch(r'/sdlc (status|cancel|recover) ([0-9a-f]{20})(?: ([a-z0-9]+))?', header)
        if not match:
            return
        action, run_id, argument = match.groups()
        run = self.store.get(run_id)
        actor = payload.get('sender', {}).get('login')
        numbers = {run['data'].get('issue'), (run['data'].get('pr') or {}).get('number')} - {None}
        if run['project'] != name or payload['issue']['number'] not in numbers or comment.get('user', {}).get('login') != actor:
            raise Conflict('Command is not on the matching run issue or PR')
        live = self.runtime.github('GET', f'/repos/{name}/issues/comments/{comment["id"]}')
        if (live.get('body', '').strip() != body or live.get('user', {}).get('login') != actor
                or live.get('user', {}).get('type') != 'User'
                or live.get('issue_url') != f'https://api.github.com/repos/{name}/issues/{payload["issue"]["number"]}'):
            raise Conflict('Command was edited or does not match its live human author and issue')
        self.authorize(name, actor)
        marker = f'command-{comment["id"]}'
        try:
            if action == 'recover':
                if argument not in {'plan', 'revise', 'verify'}:
                    raise Conflict('Recovery requires plan, revise or verify')
                request_id = f'github:{name}:{comment["id"]}'
                repeated = any(e['kind'] == 'human_recovery' and e['value'].get('request_id') == request_id
                               for e in self.store.history(run_id))
                if argument == 'plan' and run['state'] != 'needs_human' and not repeated:
                    raise Conflict('Discuss draft changes in an ordinary issue comment')
                self.store.recover(run_id, argument, actor, feedback.strip(), request_id=request_id)
            else:
                if argument or feedback:
                    raise Conflict('Status and cancel take only the run ID')
                if action == 'cancel' and run['state'] != 'cancelled':
                    self.store.cancel(run_id)
        except Conflict as exc:
            self.comment(run, marker, f'Lifecycle request rejected: {exc}')
            raise
        if self.store.get(run_id)['data'].get('spec') and self.store.get(run_id)['data'].get('issue'):
            self.publish_plan(run_id)
        else:
            self.comment(self.store.get(run_id), marker, self.status_text(run_id))

    def status_text(self, run_id):
        run = self.store.get(run_id)
        data = run['data']
        status = {'run': run_id, 'state': run['state'], 'specification_hash': data.get('spec_hash'),
                  'head_sha': data.get('head_sha'), 'merge_sha': data.get('merge_sha'),
                  'model_calls_in_current_allowance': data.get('model_calls', 0),
                  'revisions': data.get('revisions', 0), 'recoveries': data.get('recoveries', 0)}
        for event in reversed(self.store.history(run_id)):
            if event['kind'] == 'checks':
                status['checks'] = [{'name': c['name'], 'passed': c['passed']} for c in event['value']['results']]
                break
        status['production'] = [{key: check.get(key) for key in ('name', 'passed', 'inconclusive', 'observed_sha')}
                                for check in data.get('production_evidence', [])]
        return '## Kira lifecycle status\n\n```json\n' + json.dumps(status, indent=2) + '\n```'

    def handle_event(self, event):
        provider, kind, payload = event['provider'], event['type'], event['payload']
        if provider.startswith('incident:'):
            source_name = provider.removeprefix('incident:')
            source = self.config.get('incident_sources', {}).get(source_name)
            if not source:
                raise Conflict('Incident source is no longer configured')
            self.incident(source['project'], source_name, source['provider'], payload)
            return
        if provider == 'deployment':
            self.deployed(payload['run_id'], payload)
            return
        if provider != 'github':
            raise Conflict('Unknown event provider')
        name = payload.get('repository', {}).get('full_name')
        if name not in self.config['projects']:
            raise Conflict('Unconfigured repository')
        project = self.config['projects'][name]
        actor = payload.get('sender', {}).get('login')
        if kind == 'issues':
            issue = payload.get('issue', {})
            if payload.get('action') == 'labeled' and payload.get('label', {}).get('name') == 'ready-to-fix':
                self.authorize(name, actor)
            elif payload.get('action') == 'opened':
                if issue.get('user', {}).get('type') == 'Bot' or any(l['name'] == 'auto-triaged' for l in issue.get('labels', [])):
                    return
                self.authorize(name, actor)
            else:
                return
            live = self.runtime.github('GET', f'/repos/{name}/issues/{issue["number"]}')
            labels = {label['name'] for label in live.get('labels', [])}
            kinds = labels & KINDS
            if len(kinds) > 1:
                raise Conflict('Issue has conflicting lifecycle kind labels')
            kind = next(iter(kinds), 'incident' if 'auto-triaged' in labels else 'feature')
            self.submit(name, kind, live['title'], live.get('body') or 'Clarify this issue before proposing implementation.',
                        f'{name}:issue:{issue["number"]}', {'issue': issue['number']})
        elif kind == 'issue_comment':
            if payload.get('action') == 'created':
                self.github_command(name, payload)
            self.plan_interaction(name, payload)
        elif kind == 'pull_request':
            pr = payload['pull_request']
            run = self.find_pr(name, pr['number'], pr.get('head', {}).get('ref'))
            if run and payload.get('action') == 'closed' and pr.get('merged'):
                if run['state'] in {'queued', 'implementing'}:
                    raise Deferred('Merge arrived before publication checkpoint')
                self.merged(run['id'], pr['merge_commit_sha'])
        elif kind in {'pull_request_review', 'pull_request_review_comment'}:
            if payload.get('action') not in {'submitted', 'created'}:
                return
            pr = payload['pull_request']
            run = self.find_pr(name, pr['number'], pr.get('head', {}).get('ref'))
            review = payload.get('review') or payload.get('comment')
            if not run or not review or (kind == 'pull_request_review' and review.get('state') != 'changes_requested'):
                return
            if run['state'] in {'queued', 'implementing'}:
                raise Deferred('Review arrived before publication checkpoint')
            self.authorize(name, actor)
            live = self.runtime.github('GET', f'/repos/{name}/pulls/{pr["number"]}')
            if live['head']['sha'] != run['data']['head_sha'] or review.get('commit_id') != run['data']['head_sha']:
                raise Conflict('Stale review: current PR head differs from reviewed commit')
            if run['data'].get('revisions', 0) >= self.config['limits']['max_attempts']:
                raise Conflict('PR revision budget exhausted')
            self.store.schedule(run['id'], 'revise', {'feedback': review.get('body', '')}, f'{run["id"]}:review:{review["id"]}',
                                {'awaiting_review'}, {'revisions': run['data'].get('revisions', 0) + 1})
        elif kind == 'workflow_run' and payload.get('action') == 'completed':
            workflow = payload['workflow_run']
            if workflow.get('conclusion') != 'failure':
                return
            for run in (self.store.list(name) if workflow.get('name') in project['required_ci_checks'] else []):
                if workflow.get('head_sha') == run['data'].get('head_sha') and run['state'] in {'queued', 'implementing'}:
                    raise Deferred('CI result arrived before publication checkpoint')
                if run['state'] == 'awaiting_review' and workflow.get('head_sha') == run['data'].get('head_sha'):
                    if run['data'].get('revisions', 0) >= self.config['limits']['max_attempts']:
                        raise Conflict('CI repair budget exhausted')
                    live = self.runtime.github('GET', f'/repos/{name}/actions/runs/{workflow["id"]}')
                    if live.get('head_sha') != run['data']['head_sha'] or live.get('conclusion') != 'failure':
                        raise Conflict('CI result changed')
                    jobs = self.runtime.github('GET', f'/repos/{name}/actions/runs/{workflow["id"]}/jobs?per_page=100')
                    self.store.schedule(run['id'], 'revise', {'feedback': {'workflow': live['name'], 'jobs': jobs}},
                                        f'{run["id"]}:ci:{workflow["id"]}:{workflow.get("run_attempt",1)}', {'awaiting_review'},
                                        {'revisions': run['data'].get('revisions', 0) + 1})
                    return
            if (workflow.get('name') in project.get('incident_ci_workflows', [])
                    and not workflow.get('head_branch', '').startswith('sdlc/')):
                if type(workflow.get('id')) is not int or workflow['id'] < 1:
                    raise Conflict('Invalid workflow run identity')
                live = self.runtime.github('GET', f'/repos/{name}/actions/runs/{workflow["id"]}')
                if (live.get('head_repository', {}).get('full_name') != name
                        or live.get('head_branch', '').startswith('sdlc/')
                        or live.get('name') not in project['incident_ci_workflows']
                        or live.get('run_attempt') != workflow.get('run_attempt')
                        or live.get('head_sha') != workflow.get('head_sha')):
                    raise Conflict('CI incident does not match its configured repository and live attempt')
                self.incident(name, 'github-ci', 'github', live)
        elif kind == 'deployment_status' and payload.get('deployment_status', {}).get('state') == 'success':
            deployment = payload['deployment']
            live = self.runtime.github('GET', f'/repos/{name}/deployments/{deployment["id"]}')
            statuses = self.runtime.github('GET', f'/repos/{name}/deployments/{deployment["id"]}/statuses?per_page=1')
            if not statuses or statuses[0].get('state') != 'success':
                raise Conflict('Deployment is no longer successful')
            for run in self.store.list(name):
                if run['state'] == 'awaiting_deployment' and live['sha'] == run['data'].get('merge_sha'):
                    self.deployed(run['id'], {'repository': name, 'sha': live['sha'], 'environment': live['environment'],
                                            'deployed_at': statuses[0]['created_at'], 'id': live['id']})
                elif run['state'] == 'awaiting_review' and (run['data'].get('pr') or {}).get('number'):
                    number = run['data']['pr']['number']
                    pr = self.runtime.github('GET', f'/repos/{name}/pulls/{number}')
                    if pr.get('merged') and pr.get('merge_commit_sha') == live['sha']:
                        self.merged(run['id'], live['sha'])
                        self.deployed(run['id'], {'repository': name, 'sha': live['sha'], 'environment': live['environment'],
                                                'deployed_at': statuses[0]['created_at'], 'id': live['id']})
                elif run['state'] in {'queued', 'implementing'} and run['data'].get('head_sha'):
                    raise Deferred('Deployment arrived before publication/merge checkpoint')

    def tick(self):
        limits = self.config['limits']
        job = self.store.claim(limits['lease_seconds'], limits['max_attempts'])
        if not job:
            return False
        stopped, lost = threading.Event(), threading.Event()
        def renew():
            while not stopped.wait(max(1, limits['lease_seconds'] / 3)):
                if not self.store.renew(job, limits['lease_seconds']):
                    lost.set()
                    return
        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        self.runtime.cancelled = lambda: lost.is_set() or bool(self.store.control('paused')) or bool(job['run_id'] and self.store.get(job['run_id'])['state'] == 'cancelled')
        try:
            if job['action'] == 'event':
                self.handle_event(job['payload'])
                self.store.finish(job)
            else:
                if self.store.get(job['run_id'])['state'] == 'cancelled':
                    self.store.finish(job)
                elif job['action'] == 'plan':
                    self.plan(job)
                elif job['action'] in {'implement', 'revise'}:
                    self.publish_plan(job['run_id'])
                    self.implement(job)
                elif job['action'] == 'verify':
                    self.verify(job)
                else:
                    raise Conflict('Unknown job action')
        except Exception as exc:
            if isinstance(exc, Deferred) or self.store.control('paused'):
                self.store.defer(job, str(exc))
            else:
                self.store.fail(job, str(exc), 1 if isinstance(exc, (Conflict, ConfigurationError)) else limits['max_attempts'])
                if job['run_id'] and self.store.get(job['run_id'])['state'] == 'needs_human':
                    try:
                        self.comment(self.store.get(job['run_id']), f'stopped-{job["id"]}',
                                     self.status_text(job['run_id']) + '\n\nHuman attention required. Use `/sdlc recover RUN plan|revise|verify` after investigating.')
                    except Exception:
                        print('GitHub failure notification unavailable; durable failure evidence retained', flush=True)
        finally:
            stopped.set()
            if job['run_id']:
                try:
                    self.publish_plan(job['run_id'])
                except Exception:
                    print('Plan display refresh unavailable; durable run state retained', flush=True)
            thread.join(timeout=2)
            self.runtime.cancelled = lambda: False
        return True

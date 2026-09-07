"""Real Hermes, GitHub, Git, sandbox and production-evidence integrations."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import safe_path, ConfigurationError
from .github_app import GitHubApp


class AdapterError(RuntimeError):
    pass


def timestamp(value: str) -> float:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise AdapterError('Timestamps must include a timezone')
    return dt.timestamp()


class Runtime:
    def __init__(self, config, *, use_app=True):
        self.config = config
        self.cancelled = lambda: False
        self.app = GitHubApp(config['github_app']) if use_app and config.get('github_app') else None

    def command(self, argv, *, cwd=None, stdin=None, timeout=120, env=None, check=True):
        """No shell; bounded file-backed output avoids pipe deadlocks and memory growth."""
        if self.cancelled():
            raise AdapterError('Execution cancelled or paused')
        maximum = self.config['limits']['max_output_bytes']
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors, tempfile.TemporaryFile() as input_file:
            if stdin is not None:
                input_file.write(stdin.encode() if isinstance(stdin, str) else stdin)
                input_file.seek(0)
            try:
                process = subprocess.Popen(argv, cwd=cwd, stdin=input_file, stdout=output, stderr=errors,
                                           env=env, start_new_session=True)
            except OSError as exc:
                raise AdapterError(f'Cannot start {Path(argv[0]).name}: {exc.strerror}') from exc
            start = time.monotonic()
            failure = None
            try:
                while process.poll() is None:
                    if self.cancelled():
                        failure = 'Execution cancelled or paused'
                        break
                    if time.monotonic() - start > timeout:
                        failure = f'{Path(argv[0]).name} exceeded {timeout}s timeout'
                        break
                    if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > maximum:
                        failure = f'{Path(argv[0]).name} exceeded output limit'
                        break
                    time.sleep(0.1)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
            if failure:
                raise AdapterError(failure)
            if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > maximum:
                raise AdapterError('Command exceeded output limit')
            output.seek(0)
            errors.seek(0)
            text = output.read(maximum).decode('utf-8', errors='replace')
            error = errors.read(maximum).decode('utf-8', errors='replace')
            if check and process.returncode:
                # Never include auth CLI/provider diagnostics, which can contain credentials.
                detail = '' if Path(argv[0]).name in {'gh', 'python', 'python3'} else ': ' + error[-1500:]
                raise AdapterError(f'{Path(argv[0]).name} exited {process.returncode}{detail}')
            return process.returncode, text, error

    def propose(self, stage, context):
        bridge = Path(__file__).with_name('hermes_bridge.py')
        request = {'stage': stage, 'context': context, 'hermes_root': self.config['hermes_root'],
                   'model': self.config.get('model'), 'provider': self.config.get('provider')}
        code, output, error = self.command([self.config['hermes_python'], str(bridge)],
                                    stdin=json.dumps(request), cwd=self.config['state_dir'],
                                    timeout=self.config['limits']['model_timeout_seconds'], check=False)
        if code:
            import re
            category = re.search(r'proposal failed \(([A-Za-z0-9_]+)\)', error)
            diagnostic = re.search(r'Safe proposal diagnostic: ([a-z_]+; calls=[0-9]+)', error)
            raise AdapterError('Tool-free Hermes proposal failed: ' + (diagnostic[1] if diagnostic else category[1] if category else 'runtime unavailable'))
        try:
            result = json.loads(output)
        except ValueError as exc:
            raise AdapterError('Hermes returned invalid JSON; no changes applied') from exc
        if not isinstance(result, dict) or not isinstance(result.get('proposal'), dict):
            raise AdapterError('Hermes response must contain a proposal object')
        return result

    def git(self, workspace, *args):
        env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
               'GIT_TERMINAL_PROMPT': '0', 'GIT_AUTHOR_NAME': 'Kira SDLC',
               'GIT_AUTHOR_EMAIL': 'kira-sdlc@localhost', 'GIT_COMMITTER_NAME': 'Kira SDLC',
               'GIT_COMMITTER_EMAIL': 'kira-sdlc@localhost'}
        network = any(arg in {'clone', 'fetch', 'push', 'ls-remote'} for arg in args)
        credentials = ['-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential'] if network else []
        if self.app and network:
            env = self.app.environment(env)
        return self.command(['git', '-c', f'core.hooksPath={os.devnull}', '-c', 'core.fsmonitor=false',
                             '-c', 'protocol.ext.allow=never', *credentials, *args], cwd=workspace, env=env)[1].strip()

    def prepare(self, project, run_id, base_sha=None):
        if not run_id.isalnum():
            raise AdapterError('Invalid run ID')
        workspace = Path(self.config['state_dir']) / 'workspaces' / run_id
        if workspace.exists():
            if not (workspace / '.git').is_dir():
                raise AdapterError('Incomplete workspace; quarantine it before retrying')
            return workspace
        workspace.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.git(workspace.parent, 'clone', '--no-hardlinks', '--no-checkout', '--', project['source'], str(workspace))
        base = base_sha or f"origin/{project['base_branch']}"
        self.git(workspace, 'checkout', '-b', f'sdlc/{run_id}', base)
        return workspace

    def check(self, project, workspace):
        results = []
        if not project['checks']:
            raise AdapterError('No verification checks configured')
        for check in project['checks']:
            with tempfile.TemporaryDirectory(prefix='sdlc-check-', dir=self.config['state_dir']) as directory:
                staged = Path(directory) / 'work'
                staged.mkdir(mode=0o777)
                # Check execution never sees .git, host credentials, or any symlink target.
                paths = set(self.git(workspace, 'ls-files').splitlines())
                paths.update(self.git(workspace, 'ls-files', '--others', '--exclude-standard').splitlines())
                for relative in paths:
                    try:
                        safe_path(relative)
                    except ConfigurationError:
                        continue
                    source = workspace / relative
                    if source.is_symlink() or not source.resolve().is_relative_to(workspace.resolve()):
                        continue
                    if not source.is_file():
                        continue
                    target = staged / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    target.chmod(0o777 if source.stat().st_mode & 0o111 else 0o666)
                for folder in [staged, *[p for p in staged.rglob('*') if p.is_dir()]]:
                    folder.chmod(0o777)
                container = f'hermes-sdlc-{uuid.uuid4().hex}'
                command = ['docker', 'run', '--rm', '--name', container, '--network', 'none',
                           '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                           '--pids-limit', '128', '--memory', '512m', '--cpus', '1', '--user', '65534:65534',
                           '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
                           '--tmpfs', '/work:rw,nosuid,size=256m,mode=1777', '--mount',
                           f'type=bind,src={staged},dst=/input,readonly', '--workdir', '/work',
                           '--env', 'PYTHONDONTWRITEBYTECODE=1', '--entrypoint', '/bin/sh',
                           project['sandbox_image'], '-c', 'cp -R /input/. /work/ && exec "$@"',
                           'sdlc-check', *check['argv']]
                started = time.monotonic()
                try:
                    code, stdout, stderr = self.command(command, timeout=min(check.get('timeout_seconds', 120), self.config['limits']['check_timeout_seconds']), check=False)
                    results.append({'name': check['name'], 'passed': code == 0, 'exit_code': code,
                                    'output': (stdout + stderr)[-16000:], 'duration_seconds': time.monotonic() - started})
                except AdapterError as exc:
                    results.append({'name': check['name'], 'passed': False, 'exit_code': -1,
                                    'output': str(exc), 'duration_seconds': time.monotonic() - started})
                finally:
                    # docker client termination does not terminate its daemon-owned container.
                    subprocess.run(['docker', 'rm', '-f', container], capture_output=True, timeout=15, check=False)
        return results

    def github(self, method, path, body=None):
        if path.startswith(('http:', 'https:')) or not path.startswith('/'):
            raise AdapterError('GitHub API path must be relative to the authenticated GitHub host')
        args = ['gh', 'api', '--hostname', 'github.com', '--method', method, path]
        if body is not None:
            args.extend(['--input', '-'])
        env = self.app.environment(os.environ) if self.app else None
        _, text, _ = self.command(args, stdin=json.dumps(body) if body is not None else None, env=env)
        return json.loads(text) if text.strip() else {}

    def identity(self):
        if self.app:
            return self.app.identity()
        return self.github('GET', '/user')['login']

    def publish(self, project_name, project, run_id, workspace, title, body):
        head = self.git(workspace, 'rev-parse', 'HEAD')
        if not project['publish']:
            return {'number': None, 'url': None, 'head_sha': head}
        if not project.get('bot_login') or self.identity() != project['bot_login']:
            raise AdapterError('Publication requires the configured dedicated bot identity')
        branch = f'sdlc/{run_id}'
        owner = project_name.split('/')[0]
        existing = self.github('GET', f'/repos/{project_name}/pulls?state=all&head={urllib.parse.quote(owner + ":" + branch)}')
        if existing:
            pr = existing[0]
            if pr['state'] != 'open':
                live = self.github('GET', f'/repos/{project_name}/pulls/{pr["number"]}')
                if not live.get('merged') or live['head']['sha'] != head:
                    raise AdapterError('Run PR closed without merging the verified commit')
                return {'number': live['number'], 'url': live['html_url'], 'head_sha': head, 'merged_sha': live['merge_commit_sha']}
        else:
            self.git(workspace, 'push', f'https://github.com/{project_name}.git', f'HEAD:refs/heads/{branch}')
            pr = self.github('POST', f'/repos/{project_name}/pulls', {'title': title, 'body': body,
                              'head': branch, 'base': project['base_branch']})
        if existing:
            self.git(workspace, 'push', f'https://github.com/{project_name}.git', f'HEAD:refs/heads/{branch}')
        return {'number': pr['number'], 'url': pr['html_url'], 'head_sha': head}

    def incident_issue(self, name, project, run):
        """Recover a Kira-owned issue after a crash before the local checkpoint."""
        if self.identity() != project['bot_login']:
            raise AdapterError('Wrong identity for publishing incident evidence')
        marker = f'<!-- kira-incident:{run["id"]} -->'
        query = urllib.parse.urlencode({'state': 'all', 'creator': project['bot_login'], 'per_page': 100})
        for page in range(1, 11):
            issues = self.github('GET', f'/repos/{name}/issues?{query}&page={page}')
            for issue in issues:
                if (not issue.get('pull_request') and issue.get('user', {}).get('login') == project['bot_login']
                        and (issue.get('body') or '').rstrip().endswith(marker)):
                    return issue['number']
            if len(issues) < 100:
                break
        else:
            raise AdapterError('Incident issue reconciliation exceeded its bounded history; human intervention required')
        issue = self.github('POST', f'/repos/{name}/issues', {
            'title': run['title'],
            'body': '## Kira incident\n\nInvestigation and planning only. No changes are authorized until a human '
                    'approves the exact plan posted below.\n\n' + run['body'][:50000] + '\n\n' + marker})
        return issue['number']

    def incident_evidence(self, name, project, incident, workspace=None):
        """Collect bounded facts with host-owned read-only requests, never agent tools."""
        results = []
        budget = self.config['limits']['max_context_bytes'] // 3
        revision = incident['payload'].get('head_sha' if incident['provider'] == 'github' else 'revision')
        if workspace is not None and incident['provider'] in {'github', 'argocd'}:
            record = {'source': 'git-revision', 'available': False, 'revision': revision}
            try:
                if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision):
                    raise AdapterError('Incident revision is not a full Git SHA')
                text = self.git(workspace, 'show', '--format=fuller', '--no-ext-diff', '--no-textconv', revision, '--')
                record.update(available=True, text=text[:budget], truncated=len(text) > budget)
            except Exception as exc:
                record['reason'] = type(exc).__name__
            results.append(record)
        if incident['provider'] == 'github':
            workflow = incident['payload']
            # IDs were validated on intake; repository and credentials come only from the host.
            run_id, attempt = workflow['id'], workflow['run_attempt']
            try:
                jobs = self.github('GET', f'/repos/{name}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100')
                env = self.app.environment(os.environ) if self.app else None
                _, logs, _ = self.command(['gh', 'run', 'view', str(run_id), '--repo', name,
                                           '--attempt', str(attempt), '--log-failed'], env=env)
                text = json.dumps({'jobs': jobs, 'failed_logs': logs})
                results.append({'source': 'github-actions', 'available': True,
                                'text': text[:budget], 'truncated': len(text) > budget})
            except Exception as exc:
                results.append({'source': 'github-actions', 'available': False, 'reason': type(exc).__name__})
        loki = project.get('incident_loki')
        if loki and incident['provider'] in {'grafana', 'argocd'}:
            end = incident['observed_at']
            allowance = budget // len(loki['queries'])
            for query in loki['queries']:
                record = {'source': 'loki', 'query': query, 'available': False,
                          'start': end - loki['window_seconds'], 'end': end}
                try:
                    token = Path(loki['token_file']).read_text().strip()
                    params = urllib.parse.urlencode({'query': query, 'start': int(record['start'] * 1e9),
                                                     'end': int(end * 1e9), 'limit': loki['limit'], 'direction': 'backward'})
                    _, text = self._http(loki['url'].rstrip('/') + '/loki/api/v1/query_range?' + params,
                                         headers={'Authorization': 'Bearer ' + token})
                    data = json.loads(text)
                    if data.get('status') != 'success' or data.get('data', {}).get('resultType') != 'streams':
                        raise AdapterError('Loki did not return log streams')
                    record.update(available=True, text=text[:allowance], truncated=len(text) > allowance)
                except Exception as exc:
                    record['reason'] = type(exc).__name__
                results.append(record)
        if not results:
            results.append({'source': 'observability', 'available': False, 'reason': 'No incident log source configured'})
        return results

    def _http(self, url, *, headers=None):
        request = urllib.request.Request(url, headers=headers or {})
        # Do not forward bearer credentials through redirects to another origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            raw = response.read(self.config['limits']['max_output_bytes'] + 1)
            if len(raw) > self.config['limits']['max_output_bytes']:
                raise AdapterError('Production response exceeded output limit')
            return response.status, raw.decode('utf-8')

    def production(self, project, deployment):
        if not project['production_checks']:
            raise AdapterError('No production checks configured; recovery cannot be verified')
        start = timestamp(deployment['deployed_at'])
        now = time.time()
        if start > now or now - start < project['observation_seconds']:
            return [{'name': 'observation', 'passed': False, 'inconclusive': True, 'reason': 'Observation window incomplete'}]
        results = []
        for check in project['production_checks']:
            record = {'name': check['name'], 'passed': False, 'inconclusive': False,
                      'start': deployment['deployed_at'], 'end': datetime.now(timezone.utc).isoformat()}
            try:
                if check['kind'] == 'http':
                    code, text = self._http(check['url'])
                    pointer = check.get('revision_json_pointer')
                    if not pointer:
                        record.update(inconclusive=True, reason='HTTP verification requires a revision JSON pointer')
                    else:
                        value = json.loads(text)
                        for part in pointer.strip('/').split('/'):
                            value = value[part.replace('~1', '/').replace('~0', '~')]
                        record.update(observed_sha=value, status=code)
                        record['passed'] = value == deployment['sha'] and code == check.get('expect_status', 200) and check.get('expect_contains', '') in text
                        if value != deployment['sha']:
                            record['inconclusive'] = True
                            record['reason'] = 'Running revision differs from merged revision'
                elif check['kind'] == 'loki':
                    token = os.environ.get(check.get('token_env', ''))
                    if not token or not all(check.get(k) for k in ('traffic_query', 'revision_query', 'freshness_query', 'coverage_query')):
                        raise AdapterError('Loki requires traffic, revision, freshness and interval-coverage evidence')
                    duration = max(1, int(now - start))
                    headers = {'Authorization': f'Bearer {token}'}
                    counts = {}
                    for label, query in [('errors', check['query']), ('traffic', check['traffic_query']), ('revision', check['revision_query']), ('freshness', check['freshness_query']), ('coverage', check['coverage_query'])]:
                        window = min(duration, check.get('freshness_seconds', 60)) if label == 'freshness' else duration
                        expression = query.replace('{window}', f'{window}s').replace('{sha}', deployment['sha'])
                        url = check['url'].rstrip('/') + '/loki/api/v1/query?' + urllib.parse.urlencode({'query': expression, 'time': str(int(now * 1e9))})
                        _, text = self._http(url, headers=headers)
                        data = json.loads(text)
                        if data.get('status') != 'success' or data.get('data', {}).get('resultType') != 'vector':
                            raise AdapterError('Loki did not return an instant vector')
                        series = data['data']['result']
                        counts[label] = sum(float(s['value'][1]) for s in series)
                        import math
                        if not math.isfinite(counts[label]) or counts[label] < 0:
                            raise AdapterError('Loki returned invalid numeric evidence')
                    record.update(counts)
                    record['inconclusive'] = counts['traffic'] < check.get('min_traffic', 1) or counts['revision'] < 1 or counts['freshness'] < 1 or not check.get('min_coverage', 1.0) <= counts['coverage'] <= 1.0
                    record['passed'] = not record['inconclusive'] and counts['errors'] <= check.get('max_errors', 0)
                else:
                    raise AdapterError('Unknown production evidence kind')
            except Exception as exc:
                record.update(inconclusive=True, reason=type(exc).__name__ + ': production evidence unavailable')
            results.append(record)
        return results

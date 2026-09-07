"""Administrator-only reconciliation of GitHub infrastructure, not lifecycle commands."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

from .adapters import Runtime
from .config import write_private

EVENTS = ['issues', 'issue_comment', 'pull_request', 'pull_request_review',
          'pull_request_review_comment', 'workflow_run', 'deployment_status']


def validate_policy(policy, config):
    repository = policy.get('repository', '')
    if repository not in config['projects']:
        raise ValueError('Provisioning repository must be a configured lifecycle project')
    if policy.get('enforcement') not in {'disabled', 'active'}:
        raise ValueError('Ruleset enforcement must be disabled or active')
    if not isinstance(policy.get('ruleset_name'), str) or not policy['ruleset_name'].startswith('hermes-sdlc-'):
        raise ValueError('Managed ruleset names must start with hermes-sdlc-')
    for key in ('required_workflows', 'required_check_contexts'):
        values = policy.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f'{key} must contain explicit nonempty names')
        if len(set(values)) != len(values):
            raise ValueError(f'{key} must not contain duplicates')
    labels = policy.get('labels')
    if not isinstance(labels, list):
        raise ValueError('labels must be an array')
    names = set()
    for label in labels:
        if (not isinstance(label, dict) or not isinstance(label.get('name'), str)
                or not 1 <= len(label['name'].strip()) <= 50 or label['name'].casefold() in names
                or not isinstance(label.get('color'), str) or not re.fullmatch(r'[0-9a-fA-F]{6}', label['color'])
                or not isinstance(label.get('description'), str) or len(label['description']) > 100):
            raise ValueError('Malformed or duplicate label definition')
        names.add(label['name'].casefold())
    url = policy.get('webhook_url')
    if url is not None:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or parts.path != '/webhooks/github'):
            raise ValueError('Webhook URL must be HTTPS /webhooks/github with no credentials, query or fragment')
        host = parts.hostname.lower()
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.example', '.invalid')):
            raise ValueError('Webhook URL must identify real public ingress')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError('GitHub cannot deliver to a private or loopback address')
    return repository


def ruleset(policy):
    return {'name': policy['ruleset_name'], 'target': 'branch', 'enforcement': policy['enforcement'],
            'bypass_actors': [], 'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}},
            'rules': [
                {'type': 'deletion'}, {'type': 'non_fast_forward'},
                {'type': 'pull_request', 'parameters': {
                    'dismiss_stale_reviews_on_push': True, 'require_code_owner_review': False,
                    'require_last_push_approval': True, 'required_approving_review_count': 1,
                    'required_review_thread_resolution': True}},
                {'type': 'required_status_checks', 'parameters': {
                    'strict_required_status_checks_policy': True,
                    'required_status_checks': [{'context': name} for name in policy['required_check_contexts']]}}]}


def contains(actual, expected):
    """Ignore server-added fields and unordered rules; detect changed managed values."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and contains(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(any(contains(item, target) for item in actual) for target in expected))
    return actual == expected


class GitHubSetup:
    def __init__(self, config, runtime=None):
        self.config = config
        # Infrastructure changes use the operator's gh account, never the App token.
        self.runtime = runtime or Runtime(config, use_app=False)

    def pages(self, path, key=None):
        rows = []
        separator = '&' if '?' in path else '?'
        page = 1
        while True:
            response = self.runtime.github('GET', f'{path}{separator}per_page=100&page={page}')
            batch = response[key] if key else response
            if not isinstance(batch, list):
                raise ValueError('Unexpected paginated GitHub response')
            rows.extend(batch)
            if len(batch) < 100:
                return rows
            page += 1

    def reconcile(self, policy, *, apply=False):
        repository = validate_policy(policy, self.config)
        project = self.config['projects'][repository]
        root = f'/repos/{repository}'
        remote = self.runtime.github('GET', root)
        if not remote.get('permissions', {}).get('admin'):
            raise ValueError('GitHub repository administrator access is required for provisioning')
        if remote['default_branch'] != project['base_branch']:
            raise ValueError('Remote default branch differs from trusted project base branch')
        changes, blockers = [], []
        if not remote.get('has_issues'):
            changes.append(('PATCH', root, {'has_issues': True}, 'enable_issues'))
        labels = {label['name'].casefold() for label in self.pages(root + '/labels')}
        for label in policy['labels']:
            if label['name'].casefold() not in labels:
                changes.append(('POST', root + '/labels', label, 'create_label:' + label['name']))
        workflows = self.pages(root + '/actions/workflows', key='workflows')
        active_workflows = {w['name'] for w in workflows if w.get('state') == 'active'}
        missing = sorted(set(policy['required_workflows']) - active_workflows)
        if missing:
            blockers.append('Publish and enable required workflows: ' + ', '.join(missing))
        workflow_policy = {'default_workflow_permissions': 'read', 'can_approve_pull_request_reviews': False}
        current_permissions = self.runtime.github('GET', root + '/actions/permissions/workflow')
        if not contains(current_permissions, workflow_policy):
            changes.append(('PUT', root + '/actions/permissions/workflow', workflow_policy, 'restrict_actions_token'))

        bot = project.get('bot_login')
        if not bot:
            blockers.append('Configure GitHub App authentication')
        elif bot in project['approvers']:
            raise ValueError('Bot identity must differ from every human approver')
        elif self.config.get('github_app'):
            from .github_app import GitHubApp
            app = GitHubApp(self.config['github_app'])
            installation = app.installation()
            if bot != app.identity():
                raise ValueError('Bot identity does not match the installed GitHub App')
            if installation.get('suspended_at'):
                blockers.append('GitHub App installation is suspended')
            repositories = app.repositories()
            if not any(r['full_name'].lower() == repository.lower() for r in repositories):
                blockers.append('GitHub App installation token cannot access this repository')
            permissions = installation.get('permissions', {})
            if any(permissions.get(p) != 'write' for p in ('contents', 'issues', 'pull_requests')):
                blockers.append('GitHub App requires contents, issues and pull requests write access')
            if permissions.get('administration'):
                blockers.append('GitHub App must not have repository administration permission')
        else:
            blockers.append('Configure GitHub App authentication; a bot login alone is not sufficient')
        if not project['publish']:
            blockers.append('Controller publication remains disabled; enable it only after activation prerequisites are satisfied')

        state_path = Path(self.config['state_dir']) / 'github-setup.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        remembered = state.get(repository, {})
        url = policy.get('webhook_url')
        hook_change = None
        if not url:
            blockers.append('Set webhook_url to the real public HTTPS receiver')
        else:
            hooks = self.pages(root + '/hooks')
            hook = next((h for h in hooks if h['id'] == remembered.get('hook_id')), None)
            if remembered.get('hook_id') and hook and hook.get('config', {}).get('url') != remembered.get('url'):
                raise ValueError('Managed webhook was changed externally; inspect ownership before provisioning')
            matching = [h for h in hooks if h.get('config', {}).get('url') == url]
            if len(matching) > 1 or (hook and any(h['id'] != hook['id'] for h in matching)):
                raise ValueError('Multiple candidate webhooks; refusing to overwrite or duplicate them')
            hook = hook or (matching[0] if matching else None)
            secret = Path(self.config['webhook_secrets']['github']).read_text().strip()
            if len(secret) < 32:
                raise ValueError('Webhook secret must contain at least 32 characters')
            digest = hashlib.sha256(secret.encode()).hexdigest()
            desired = {'name': 'web', 'active': True, 'events': EVENTS,
                       'config': {'url': url, 'content_type': 'json', 'insecure_ssl': '0'}}
            if not hook or not contains(hook, desired) or remembered.get('secret_hash') != digest or remembered.get('hook_id') != hook['id']:
                payload = {**desired, 'config': {**desired['config'], 'secret': secret}}
                endpoint = root + '/hooks' + (f'/{hook["id"]}' if hook else '')
                hook_change = ('PATCH' if hook else 'POST', endpoint, payload, 'configure_webhook')
                changes.append(hook_change)
            if policy['enforcement'] == 'active':
                if hook_change or not hook:
                    blockers.append('Apply webhook configuration and verify its delivery before activation')
                else:
                    delivery = hook.get('last_response', {})
                    if not isinstance(delivery.get('code'), int) or not 200 <= delivery['code'] < 300:
                        blockers.append('GitHub has not reported a successful webhook delivery')

        desired_rules = ruleset(policy)
        summaries = self.pages(root + '/rulesets?includes_parents=false')
        owned = [r for r in summaries if r['name'] == policy['ruleset_name']]
        if len(owned) > 1:
            raise ValueError('Multiple managed rulesets share the configured name')
        current = self.runtime.github('GET', root + f'/rulesets/{owned[0]["id"]}') if owned else None
        if current and current.get('enforcement') == 'active' and policy['enforcement'] == 'disabled':
            raise ValueError('Refusing to disable an active ruleset through bootstrap provisioning')
        if not current or not contains(current, desired_rules):
            changes.append(('PUT' if current else 'POST', root + '/rulesets' + (f'/{current["id"]}' if current else ''),
                            desired_rules, 'configure_ruleset:' + policy['enforcement']))
        if policy['enforcement'] == 'active':
            checks = self.pages(root + '/commits/' + quote(remote['default_branch'], safe='') + '/check-runs', key='check_runs')
            successful = {c['name'] for c in checks if c.get('conclusion') == 'success'}
            missing_checks = sorted(set(policy['required_check_contexts']) - successful)
            if missing_checks:
                blockers.append('Required checks must succeed on the default branch before activation: ' + ', '.join(missing_checks))
            if blockers:
                raise ValueError('Activation prerequisites are incomplete: ' + '; '.join(blockers))

        completed = []
        if apply:
            for method, path, payload, label in changes:
                result = self.runtime.github(method, path, payload)
                completed.append(label)
                if label == 'configure_webhook':
                    state[repository] = {'hook_id': result['id'], 'url': url, 'secret_hash': digest}
                    write_private(state_path, state)
                    # A real GitHub ping checks routing/HMAC independently of local health.
                    self.runtime.github('POST', root + f'/hooks/{result["id"]}/pings')
        return {'repository': repository, 'mode': 'apply' if apply else 'plan',
                'changes': [change[3] for change in changes], 'applied': completed,
                'ruleset_enforcement': policy['enforcement'], 'activation_blockers': blockers,
                'publication_enabled': project['publish'],
                'note': 'Existing labels, unrelated webhooks/rulesets and credentials are preserved. No source commits are pushed.'}

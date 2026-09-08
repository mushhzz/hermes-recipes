import copy
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from hermes_sdlc.github_setup import GitHubSetup, ruleset


class GitHubFixture:
    def __init__(self):
        self.writes = []
        self.admin = True
        self.labels = [{'name': 'Bug', 'description': 'Existing custom description', 'color': '123456'}]
        self.hooks = []
        self.rules = [{'id': 91, 'name': 'unrelated', 'enforcement': 'active'}]
        self.permissions = {'default_workflow_permissions': 'read', 'can_approve_pull_request_reviews': False}

    def github(self, method, path, body=None):
        parsed = urlsplit(path)
        route = parsed.path.removeprefix('/repos/acme/app')
        if method != 'GET':
            self.writes.append((method, route, copy.deepcopy(body)))
            if route == '/labels':
                self.labels.append(copy.deepcopy(body))
                return body
            if route == '/rulesets':
                rule = {'id': 92, **copy.deepcopy(body)}
                self.rules.append(rule)
                return rule
            if route == '/hooks' or (method == 'PATCH' and route.startswith('/hooks/')):
                hook = {'id': 55, **copy.deepcopy(body)}
                hook['config']['secret'] = '********'
                self.hooks = [hook]
                return hook
            if route.endswith('/pings'):
                return {}
            raise AssertionError((method, path))
        if route == '':
            return {'permissions': {'admin': self.admin}, 'default_branch': 'main', 'has_issues': True}
        if route == '/actions/permissions/workflow':
            return self.permissions
        if route.startswith('/rulesets/'):
            return next(rule for rule in self.rules if str(rule['id']) == route.rsplit('/', 1)[1])
        collections = {'/labels': self.labels, '/hooks': self.hooks, '/rulesets': self.rules,
                       '/actions/workflows': []}
        if route not in collections:
            raise AssertionError(path)
        page = int(parse_qs(parsed.query).get('page', ['1'])[0])
        batch = copy.deepcopy(collections[route][(page - 1) * 100:page * 100])
        return {'workflows': batch} if route == '/actions/workflows' else batch


class GitHubSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secret = self.root / 'github.secret'
        self.secret.write_text('test-only-not-a-real-secret-' * 2)
        self.config = {'state_dir': str(self.root), 'webhook_secrets': {'github': str(self.secret)},
                       'projects': {'acme/app': {'base_branch': 'main', 'approvers': ['human'],
                                                 'bot_login': None, 'publish': False}}}
        self.policy = {'repository': 'acme/app', 'webhook_url': None, 'ruleset_name': 'hermes-sdlc-main',
                       'enforcement': 'disabled', 'required_workflows': ['Checks'],
                       'required_check_contexts': ['regression'],
                       'labels': [{'name': 'bug', 'description': 'New text', 'color': 'abcdef'},
                                  {'name': 'ready-to-fix', 'description': 'Human handoff', 'color': '123456'}]}
        self.api = GitHubFixture()
        self.setup = GitHubSetup(self.config, self.api)

    def test_plan_is_read_only_and_apply_converges_without_overwriting_unrelated_policy(self):
        self.setup.reconcile(self.policy)
        self.assertEqual(self.api.writes, [])
        self.setup.reconcile(self.policy, apply=True)
        self.assertEqual(self.api.labels[0]['description'], 'Existing custom description')
        self.assertEqual(self.api.rules[0]['name'], 'unrelated')
        self.assertEqual(self.setup.reconcile(self.policy, apply=True)['applied'], [])
        self.assertEqual(sum(label['name'] == 'ready-to-fix' for label in self.api.labels), 1)
        self.assertEqual(sum(label['name'].casefold() == 'bug' for label in self.api.labels), 1)

    def test_solo_policy_removes_second_person_gates_but_preserves_protection(self):
        self.setup.reconcile({**self.policy, 'solo_maintainer': True}, apply=True)
        managed = next(rule for rule in self.api.rules if rule['name'] == self.policy['ruleset_name'])
        rules = {rule['type']: rule for rule in managed['rules']}
        review = rules['pull_request']['parameters']
        self.assertEqual(review['required_approving_review_count'], 0)
        self.assertFalse(review['require_last_push_approval'])
        self.assertFalse(review['require_extra_approval_for_unattributed_changes'])
        self.assertTrue(review['required_review_thread_resolution'])
        self.assertEqual(managed['bypass_actors'], [])
        self.assertIn('deletion', rules)
        self.assertIn('non_fast_forward', rules)
        self.assertEqual(rules['required_status_checks']['parameters']['required_status_checks'],
                         [{'context': 'regression'}])
        team = next(rule for rule in ruleset(self.policy)['rules'] if rule['type'] == 'pull_request')['parameters']
        self.assertEqual(team['required_approving_review_count'], 1)
        self.assertTrue(team['require_last_push_approval'])

    def test_solo_policy_rejects_non_boolean_before_mutation(self):
        with self.assertRaisesRegex(ValueError, 'solo_maintainer must be a boolean'):
            self.setup.reconcile({**self.policy, 'solo_maintainer': 'false'}, apply=True)
        self.assertEqual(self.api.writes, [])

    def test_labels_on_later_pages_are_not_created_again(self):
        self.api.labels = [{'name': f'existing-{i}'} for i in range(100)] + copy.deepcopy(self.policy['labels'])
        plan = self.setup.reconcile(self.policy)
        self.assertFalse(any(change.startswith('create_label:') for change in plan['changes']))

    def test_webhook_secret_is_private_and_only_rotated_when_changed(self):
        self.policy['webhook_url'] = 'https://hooks.acme.com/webhooks/github'
        plan = self.setup.reconcile(self.policy)
        self.assertNotIn(self.secret.read_text(), json.dumps(plan))
        self.assertEqual(self.api.writes, [])
        self.setup.reconcile(self.policy, apply=True)
        self.assertEqual(self.setup.reconcile(self.policy, apply=True)['applied'], [])
        self.secret.write_text('replacement-test-only-secret-' * 2)
        result = self.setup.reconcile(self.policy, apply=True)
        self.assertEqual(result['applied'], ['configure_webhook'])
        self.assertNotIn(self.secret.read_text(), (self.root / 'github-setup.json').read_text())

    def test_duplicate_webhooks_fail_before_any_repository_mutation(self):
        self.policy['webhook_url'] = 'https://hooks.acme.com/webhooks/github'
        self.api.hooks = [{'id': i, 'config': {'url': self.policy['webhook_url']}} for i in (1, 2)]
        with self.assertRaises(ValueError):
            self.setup.reconcile(self.policy, apply=True)
        self.assertEqual(self.api.writes, [])

    def test_incomplete_activation_does_not_partially_apply_changes(self):
        self.policy['enforcement'] = 'active'
        # Missing readiness must fail closed, without creating labels or policy first.
        original = self.api.github
        self.api.github = lambda method, path, body=None: {'check_runs': []} if '/check-runs' in path else original(method, path, body)
        with self.assertRaises(ValueError):
            self.setup.reconcile(self.policy, apply=True)
        self.assertEqual(self.api.writes, [])

    def test_bootstrap_cannot_disable_an_existing_active_ruleset(self):
        self.api.rules.append({'id': 92, **ruleset({**self.policy, 'enforcement': 'active'})})
        with self.assertRaises(ValueError):
            self.setup.reconcile(self.policy, apply=True)
        self.assertEqual(self.api.writes, [])

    def test_shared_ingress_prefix_preserves_exact_webhook_target(self):
        self.policy['webhook_url'] = 'https://hooks.acme.com/kira/webhooks/github'
        self.setup.reconcile(self.policy, apply=True)
        self.assertEqual(self.api.hooks[0]['config']['url'], self.policy['webhook_url'])
        self.assertEqual(self.setup.reconcile(self.policy, apply=True)['applied'], [])

    def test_missing_admin_permission_cannot_start_provisioning(self):
        self.api.admin = False
        with self.assertRaises(ValueError):
            self.setup.reconcile(self.policy, apply=True)
        self.assertEqual(self.api.writes, [])

    def test_secret_bearing_or_unreachable_webhook_urls_are_rejected(self):
        for url in ['http://hooks.acme.com/webhooks/github', 'https://127.0.0.1/webhooks/github',
                    'https://token@hooks.acme.com/webhooks/github', 'https://hooks.acme.com/webhooks/github?secret=bad',
                    'https://hooks.acme.com/kira/../webhooks/github', 'https://hooks.acme.com/kira//webhooks/github']:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    self.setup.reconcile({**self.policy, 'webhook_url': url}, apply=True)
        self.assertEqual(self.api.writes, [])


if __name__ == '__main__':
    unittest.main()

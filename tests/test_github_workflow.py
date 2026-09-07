import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from hermes_sdlc.adapters import Runtime
from hermes_sdlc.config import LIMITS
from hermes_sdlc.engine import Engine
from hermes_sdlc.store import Conflict


class GitHubWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = {'state_dir': str(Path(self.temp.name) / 'state'), 'limits': dict(LIMITS),
                  'projects': {'acme/app': {'approvers': ['human'], 'bot_login': 'robot', 'publish': True}}}
        self.runtime = Mock(spec=Runtime)
        self.runtime.identity.return_value = 'robot'
        self.comments = []
        self.runtime.github.side_effect = self.github
        self.engine = Engine(config, self.runtime)
        self.store = self.engine.store
        self.run = self.store.create('acme/app', 'feature', 'Build feature', 'Task', metadata={'issue': 7})
        job = self.store.claim(10, 2)
        self.digest = 'a' * 64
        self.store.finish(job, 'awaiting_approval', {'spec_hash': self.digest})

    def github(self, method, path, body=None):
        if path == '/users/human':
            return {'type': 'User'}
        if path.endswith('/collaborators/human/permission'):
            return {'permission': 'write'}
        if path == '/repos/acme/app/issues/comments/42':
            return self.live
        if method == 'GET' and '/comments?' in path:
            return self.comments
        if method == 'POST' and path == '/repos/acme/app/issues/7/comments':
            self.comments.append({'body': body['body'], 'user': {'login': 'robot'}})
            return self.comments[-1]
        raise AssertionError((method, path))

    def event(self, command, issue=7):
        self.live = {'body': command, 'user': {'login': 'human', 'type': 'User'},
                     'issue_url': f'https://api.github.com/repos/acme/app/issues/{issue}'}
        return {'provider': 'github', 'type': 'issue_comment', 'payload': {
            'action': 'created', 'repository': {'full_name': 'acme/app'}, 'sender': {'login': 'human'},
            'issue': {'number': issue}, 'comment': {'id': 42, 'body': command, 'user': {'login': 'human'}}}}

    def test_human_approval_enqueues_implementation_once_and_reports_state(self):
        event = self.event(f'/sdlc approve {self.run["id"]} {self.digest}')
        self.engine.handle_event(event)
        self.engine.handle_event(event)
        self.assertEqual(self.store.get(self.run['id'])['state'], 'queued')
        self.assertEqual(self.store.claim(10, 2)['action'], 'implement')
        self.assertIsNone(self.store.claim(10, 2))
        self.assertEqual(len(self.comments), 1)

    def test_approval_on_unrelated_issue_cannot_authorize_work(self):
        event = self.event(f'/sdlc approve {self.run["id"]} {self.digest}', issue=8)
        with self.assertRaises(Conflict):
            self.engine.handle_event(event)
        self.assertEqual(self.store.get(self.run['id'])['state'], 'awaiting_approval')

    def test_edited_or_relocated_live_comment_cannot_authorize_work(self):
        event = self.event(f'/sdlc approve {self.run["id"]} {self.digest}')
        self.live['issue_url'] = 'https://api.github.com/repos/acme/app/issues/99'
        with self.assertRaises(Conflict):
            self.engine.handle_event(event)
        self.assertIsNone(self.store.claim(10, 2))

    def test_recovery_redelivery_cannot_reset_budget_twice(self):
        event = self.event(f'/sdlc recover {self.run["id"]} plan\nClarify acceptance criteria.')
        self.engine.handle_event(event)
        self.engine.handle_event(event)
        run = self.store.get(self.run['id'])
        self.assertEqual(run['data']['recoveries'], 1)
        self.assertNotIn('spec_hash', run['data'])
        self.assertEqual(self.store.claim(10, 2)['payload']['feedback'], 'Clarify acceptance criteria.')
        self.assertIsNone(self.store.claim(10, 2))

    def test_durable_github_cancel_blocks_implementation(self):
        event = self.event(f'/sdlc cancel {self.run["id"]}')
        self.store.event(event['provider'], 'cancel-delivery', event['type'], event['payload'])
        self.assertTrue(self.engine.tick())
        self.assertEqual(self.store.get(self.run['id'])['state'], 'cancelled')
        with self.assertRaises(Conflict):
            self.store.approve(self.run['id'], self.digest, 'human')

    def test_status_does_not_publish_private_context(self):
        event = self.event(f'/sdlc status {self.run["id"]}')
        self.engine.handle_event(event)
        self.assertIn('awaiting_approval', self.comments[0]['body'])
        self.assertNotIn('Task', self.comments[0]['body'])
        self.assertNotIn(self.temp.name, self.comments[0]['body'])
        self.assertEqual(self.store.get(self.run['id'])['state'], 'awaiting_approval')


if __name__ == '__main__':
    unittest.main()

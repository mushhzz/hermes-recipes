import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from hermes_sdlc.adapters import Runtime
from hermes_sdlc.config import LIMITS
from hermes_sdlc.engine import APPROVAL_CHECKED, APPROVAL_UNCHECKED, Deferred, Engine
from hermes_sdlc.store import Conflict, fingerprint


class GitHubWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = {'state_dir': str(Path(self.temp.name) / 'state'), 'limits': dict(LIMITS),
                  'projects': {'acme/app': {'approvers': ['human'], 'bot_login': 'robot', 'publish': True}}}
        self.runtime = Mock(spec=Runtime)
        self.runtime.identity.return_value = 'robot'
        self.comments = {}
        self.permission = 'write'
        self.runtime.github.side_effect = self.github
        self.engine = Engine(config, self.runtime)
        self.store = self.engine.store
        self.run = self.store.create('acme/app', 'feature', 'Build feature', 'Private task context', metadata={'issue': 7})
        job = self.store.claim(10, 2)
        self.spec = {'summary': 'Link the issue form', 'acceptance': ['The issue link opens the form.'],
                     'steps': ['Update the link.'], 'files': ['README.md'], 'design': 'Use a Markdown link.',
                     'rollback': 'Revert the link.', 'risk': 'low', 'revision': 0, 'base_sha': 'a' * 40}
        self.digest = fingerprint(self.spec)
        self.store.finish(job, 'awaiting_approval', {'spec': self.spec, 'spec_hash': self.digest})
        self.engine.publish_plan(self.run['id'])
        self.plan_id = self.store.get(self.run['id'])['data']['plan_comment']['id']

    def github(self, method, path, body=None):
        if path == '/users/human':
            return {'type': 'User'}
        if path.endswith('/collaborators/human/permission'):
            return {'permission': self.permission}
        if '/issues/comments/' in path:
            comment = self.comments[int(path.rsplit('/', 1)[1])]
            if method == 'PATCH':
                comment['body'] = body['body']
            return copy.deepcopy(comment)
        if method == 'GET' and '/comments?' in path:
            page = int(path.rsplit('page=', 1)[1]) if '&page=' in path else 1
            comments = sorted(self.comments.values(), key=lambda c: c['id'])
            return copy.deepcopy(comments[(page - 1) * 100:page * 100])
        if method == 'POST' and path == '/repos/acme/app/issues/7/comments':
            comment_id = max(self.comments, default=99) + 1
            self.comments[comment_id] = {'id': comment_id, 'body': body['body'],
                'user': {'login': 'robot', 'type': 'Bot'}, 'issue_url': 'https://api.github.com/repos/acme/app/issues/7'}
            return copy.deepcopy(self.comments[comment_id])
        raise AssertionError((method, path))

    def event(self, body, issue=7, comment_id=42, actor='human'):
        self.comments[comment_id] = {'id': comment_id, 'body': body,
            'user': {'login': actor, 'type': 'User'}, 'issue_url': f'https://api.github.com/repos/acme/app/issues/{issue}'}
        return {'provider': 'github', 'type': 'issue_comment', 'payload': {
            'action': 'created', 'repository': {'full_name': 'acme/app'}, 'sender': {'login': actor},
            'issue': {'number': issue}, 'comment': copy.deepcopy(self.comments[comment_id])}}

    def checkbox(self):
        comment = self.comments[self.plan_id]
        before = comment['body']
        comment['body'] = before.replace(APPROVAL_UNCHECKED, APPROVAL_CHECKED, 1)
        return {'provider': 'github', 'type': 'issue_comment', 'payload': {
            'action': 'edited', 'repository': {'full_name': 'acme/app'}, 'sender': {'login': 'human'},
            'issue': {'number': 7}, 'comment': copy.deepcopy(comment), 'changes': {'body': {'from': before}}}}

    def assert_unapproved(self):
        self.assertFalse([e for e in self.store.history(self.run['id']) if e['kind'] == 'approved'])
        self.assertFalse([j for j in self.store.jobs() if j['action'] == 'implement'])

    def test_human_editor_of_bot_plan_approves_once_and_updates_same_comment(self):
        event = self.checkbox()
        self.engine.handle_event(event)
        self.engine.handle_event(event)
        self.assertEqual(self.store.get(self.run['id'])['state'], 'queued')
        self.assertEqual(self.store.claim(10, 2)['action'], 'implement')
        self.assertIsNone(self.store.claim(10, 2))
        approvals = [e['value'] for e in self.store.history(self.run['id']) if e['kind'] == 'approved']
        self.assertEqual(approvals, [{'actor': 'human', 'spec_hash': self.digest}])
        self.assertEqual(set(self.comments), {self.plan_id})
        self.assertNotIn(APPROVAL_UNCHECKED, self.comments[self.plan_id]['body'])
        self.assertIn('human', self.comments[self.plan_id]['body'])

    def test_wrong_resource_copied_control_and_unauthorized_editor_never_approve(self):
        mutations = [
            lambda p: p['issue'].update(number=8),
            lambda p: p['comment'].update(id=999),
            lambda p: p['sender'].update(login='robot'),
            lambda p: p['sender'].update(login='outsider'),
            lambda p: p['comment']['user'].update(login='human'),
        ]
        canonical = self.comments[self.plan_id]['body']
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.comments[self.plan_id]['body'] = canonical
                event = self.checkbox()
                mutate(event['payload'])
                try:
                    self.engine.handle_event(event)
                except Conflict:
                    pass
                self.assert_unapproved()
        self.comments[self.plan_id]['body'] = canonical
        self.permission = 'read'
        with self.assertRaises(Conflict):
            self.engine.handle_event(self.checkbox())
        self.assert_unapproved()

    def test_plan_text_or_acceptance_edits_are_rejected_and_display_restored(self):
        canonical = self.comments[self.plan_id]['body']
        for transform in (lambda s: s.replace('Link the issue form', 'Change every file'),
                          lambda s: s.replace('- The issue link', '- [x] The issue link')):
            with self.subTest(transform=transform):
                event = self.checkbox()
                event['payload']['comment']['body'] = transform(event['payload']['comment']['body'])
                self.comments[self.plan_id]['body'] = event['payload']['comment']['body']
                with self.assertRaises(Conflict):
                    self.engine.handle_event(event)
                self.assert_unapproved()
                self.assertEqual(self.comments[self.plan_id]['body'], canonical)
                self.assertEqual(self.store.get(self.run['id'])['data']['plan_comment']['body'], canonical)

    def test_live_body_and_live_issue_must_match_the_event(self):
        event = self.checkbox()
        self.comments[self.plan_id]['body'] += '\nChanged after delivery'
        with self.assertRaises(Conflict):
            self.engine.handle_event(event)
        self.assert_unapproved()
        event = self.checkbox()
        self.comments[self.plan_id]['issue_url'] = 'https://api.github.com/repos/acme/app/issues/99'
        with self.assertRaises(Conflict):
            self.engine.handle_event(event)
        self.assert_unapproved()

    def test_natural_feedback_replans_once_and_invalidates_old_checkbox(self):
        stale = self.checkbox()
        self.engine.publish_plan(self.run['id'])
        feedback = self.event('Use the repository issue creation URL instead.')
        self.engine.handle_event(feedback)
        self.engine.handle_event(feedback)
        run = self.store.get(self.run['id'])
        self.assertEqual(run['data']['recoveries'], 1)
        self.assertNotIn('spec_hash', run['data'])
        self.assertNotIn(APPROVAL_UNCHECKED, self.comments[self.plan_id]['body'])
        job = self.store.claim(10, 2)
        self.assertEqual(job['action'], 'plan')
        self.assertEqual(job['payload']['feedback'], feedback['payload']['comment']['body'])
        revised = {**self.spec, 'revision': 1, 'acceptance': ['Open the repository issue creation URL.']}
        self.store.finish(job, 'awaiting_approval', {'spec': revised, 'spec_hash': fingerprint(revised)})
        self.engine.publish_plan(self.run['id'])
        self.assertEqual(self.store.get(self.run['id'])['data']['plan_comment']['id'], self.plan_id)
        self.assertIn(APPROVAL_UNCHECKED, self.comments[self.plan_id]['body'])
        self.comments[self.plan_id]['body'] = stale['payload']['comment']['body']
        with self.assertRaises(Conflict):
            self.engine.handle_event(stale)
        self.assert_unapproved()
        self.engine.handle_event(self.checkbox())
        self.assertEqual(self.store.get(self.run['id'])['data']['spec_hash'], fingerprint(revised))
        self.assertEqual(self.store.claim(10, 2)['action'], 'implement')

    def test_feedback_waits_for_inflight_plan_without_consuming_failure_attempts(self):
        self.store.transition(self.run['id'], 'planning', {'awaiting_approval'})
        feedback = self.event('Clarify the acceptance criteria.')
        self.store.event('github', 'feedback-delivery', 'issue_comment', feedback['payload'])
        self.assertTrue(self.engine.tick())
        event_job = next(j for j in self.store.jobs() if j['action'] == 'event')
        self.assertEqual((event_job['status'], event_job['attempts']), ('pending', 0))
        self.store.transition(self.run['id'], 'awaiting_approval', {'planning'})
        self.engine.handle_event(feedback)
        self.assertEqual(self.store.claim(10, 2)['action'], 'plan')
        self.assert_unapproved()

    def test_checkbox_waits_for_published_plan_finalization(self):
        self.store.transition(self.run['id'], 'planning', {'awaiting_approval'})
        self.engine.publish_plan(self.run['id'])
        event = self.checkbox()
        with self.assertRaises(Deferred):
            self.engine.handle_event(event)
        self.assert_unapproved()
        self.store.transition(self.run['id'], 'awaiting_approval', {'planning'})
        self.engine.publish_plan(self.run['id'])
        self.engine.handle_event(event)
        self.assertEqual(self.store.claim(10, 2)['action'], 'implement')

    def test_stale_invalid_event_cannot_erase_a_newer_pending_click(self):
        valid = self.checkbox()
        stale = copy.deepcopy(valid)
        stale['payload']['changes']['body']['from'] = 'An obsolete plan'
        stale['payload']['comment']['body'] = 'An obsolete checked plan'
        with self.assertRaises(Conflict):
            self.engine.handle_event(stale)
        self.assert_unapproved()
        self.engine.handle_event(valid)
        self.assertEqual(self.store.claim(10, 2)['action'], 'implement')

    def test_approval_label_in_acceptance_does_not_create_another_control(self):
        spec = {**self.spec, 'acceptance': ['Approve this revision for implementation']}
        self.store.transition(self.run['id'], 'awaiting_approval', {'awaiting_approval'},
                              {'spec': spec, 'spec_hash': fingerprint(spec)})
        self.engine.publish_plan(self.run['id'])
        self.engine.handle_event(self.checkbox())
        self.assertEqual(self.store.claim(10, 2)['action'], 'implement')

    def test_operator_recovery_replay_survives_state_advance(self):
        self.store.transition(self.run['id'], 'needs_human', {'awaiting_approval'})
        event = self.event(f'/sdlc recover {self.run["id"]} plan\nRetry failed planning.')
        self.engine.handle_event(event)
        self.engine.handle_event(event)
        self.assertEqual(self.store.get(self.run['id'])['data']['recoveries'], 1)
        self.assertEqual(self.store.claim(10, 2)['action'], 'plan')
        self.assertIsNone(self.store.claim(10, 2))
        self.assertEqual(set(self.comments), {42, self.plan_id})

    def test_checkbox_before_publication_checkpoint_is_deferred(self):
        snapshot = self.store.get(self.run['id'])
        snapshot['data'].pop('plan_comment')
        with self.store.transaction() as db:
            db.execute('UPDATE runs SET state=?,data=? WHERE id=?',
                       ('planning', json.dumps(snapshot['data']), self.run['id']))
        with self.assertRaises(Deferred):
            self.engine.handle_event(self.checkbox())
        self.assert_unapproved()

    def test_legacy_bot_plan_is_adopted_without_another_comment(self):
        snapshot = self.store.get(self.run['id'])
        snapshot['data'].pop('plan_comment')
        with self.store.transaction() as db:
            db.execute('UPDATE runs SET data=? WHERE id=?', (json.dumps(snapshot['data']), self.run['id']))
        legacy = f'Old plan\n<!-- hermes-sdlc:{self.run["id"]}:plan-{self.digest} -->'
        self.comments[self.plan_id]['body'] = legacy
        self.comments[1] = {'id': 1, 'body': legacy, 'user': {'login': 'human'},
                            'issue_url': 'https://api.github.com/repos/acme/app/issues/7'}
        self.engine.handle_event(self.event(f'/sdlc status {self.run["id"]}'))
        self.assertEqual(set(self.comments), {1, 42, self.plan_id})
        self.assertEqual(self.store.get(self.run['id'])['data']['plan_comment']['id'], self.plan_id)
        self.assertIn(APPROVAL_UNCHECKED, self.comments[self.plan_id]['body'])
        self.assertEqual(self.comments[1]['body'], legacy)

    def test_post_approval_feedback_and_removed_command_do_not_grant_new_scope(self):
        self.engine.handle_event(self.event(f'/sdlc approve {self.run["id"]} {self.digest}'))
        self.assert_unapproved()
        self.engine.handle_event(self.checkbox())
        self.engine.handle_event(self.event('Replace all application code.', comment_id=43))
        self.assertFalse([j for j in self.store.jobs() if j['action'] == 'plan' and j['status'] != 'done'])
        self.assertEqual(self.store.get(self.run['id'])['data']['spec_hash'], self.digest)

    def test_durable_github_cancel_blocks_implementation(self):
        event = self.event(f'/sdlc cancel {self.run["id"]}')
        self.store.event(event['provider'], 'cancel-delivery', event['type'], event['payload'])
        self.assertTrue(self.engine.tick())
        self.assertEqual(self.store.get(self.run['id'])['state'], 'cancelled')
        with self.assertRaises(Conflict):
            self.store.approve(self.run['id'], self.digest, 'human')
        self.assertNotIn(APPROVAL_UNCHECKED, self.comments[self.plan_id]['body'])

    def test_status_refresh_does_not_publish_private_context_or_add_bot_comment(self):
        event = self.event(f'/sdlc status {self.run["id"]}')
        self.engine.handle_event(event)
        self.assertEqual(set(self.comments), {42, self.plan_id})
        self.assertNotIn('Private task context', self.comments[self.plan_id]['body'])
        self.assertNotIn(self.temp.name, self.comments[self.plan_id]['body'])
        self.assertEqual(self.store.get(self.run['id'])['state'], 'awaiting_approval')


if __name__ == '__main__':
    unittest.main()

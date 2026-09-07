import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from hermes_sdlc.adapters import Runtime
from hermes_sdlc.config import LIMITS, ConfigurationError, safe_path
from hermes_sdlc.engine import Engine
from hermes_sdlc.server import handler
from hermes_sdlc.store import Store, Conflict, fingerprint


class LifecycleScenarios(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.config = {'state_dir': str(self.root / 'state'), 'limits': dict(LIMITS),
                       'projects': {'acme/app': {'approvers': ['human'], 'bot_login': 'robot',
                           'publish': False, 'allowed_paths': ['src/', 'tests/'],
                           'production_checks': [], 'observation_seconds': 10, 'environment': 'production'}},
                       'webhook_secrets': {}}
        self.store = Store(self.config['state_dir'])

    def tearDown(self):
        self.temp.cleanup()

    def approved_run(self):
        run = self.store.create('acme/app', 'feature', 'task', 'build task')
        job = self.store.claim(10, 2)
        spec = {'files': ['src/app.py'], 'base_sha': 'a' * 40}
        digest = fingerprint(spec)
        self.store.finish(job, 'awaiting_approval', {'spec': spec, 'spec_hash': digest})
        self.store.approve(run['id'], digest, 'human')
        return self.store.get(run['id']), digest

    def test_duplicate_delivery_is_one_job_and_payload_conflict_is_rejected(self):
        self.assertTrue(self.store.event('github', 'delivery', 'issues', {'x': 1}))
        self.assertFalse(self.store.event('github', 'delivery', 'issues', {'x': 1}))
        with self.assertRaises(Conflict):
            self.store.event('github', 'delivery', 'issues', {'x': 2})
        self.assertEqual(len(self.store.jobs()), 1)

    def test_stale_specification_cannot_authorize_implementation(self):
        run = self.store.create('acme/app', 'feature', 'task', 'task')
        job = self.store.claim(10, 2)
        self.store.finish(job, 'awaiting_approval', {'spec_hash': 'current'})
        with self.assertRaises(Conflict):
            self.store.approve(run['id'], 'stale', 'human')
        self.assertEqual(self.store.get(run['id'])['state'], 'awaiting_approval')
        self.assertIsNone(self.store.claim(10, 2))

    def test_repeated_approval_cannot_duplicate_implementation(self):
        run, digest = self.approved_run()
        self.store.approve(run['id'], digest, 'human')
        job = self.store.claim(10, 2)
        self.assertEqual(job['action'], 'implement')
        self.assertIsNone(self.store.claim(10, 2))

    def test_expired_worker_cannot_complete_reclaimed_job(self):
        self.store.create('acme/app', 'feature', 'task', 'task')
        old = self.store.claim(10, 2)
        with self.store.transaction() as db:
            db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (old['id'],))
        new = self.store.claim(10, 2)
        with self.assertRaises(Conflict):
            self.store.finish(old, 'verified')
        self.store.finish(new, 'awaiting_approval')
        self.assertEqual(self.store.get(new['run_id'])['state'], 'awaiting_approval')

    def test_concurrent_enqueue_and_claim_do_not_lose_or_double_claim_work(self):
        def enqueue(i):
            self.store.create('acme/app', 'maintenance', str(i), 'task', key=str(i))
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(enqueue, range(20)))
        with ThreadPoolExecutor(max_workers=5) as pool:
            jobs = list(pool.map(lambda _: self.store.claim(10, 2), range(20)))
        self.assertEqual(len({j['id'] for j in jobs}), 20)
        self.assertIsNone(self.store.claim(10, 2))

    def test_cancel_prevents_late_worker_success(self):
        run = self.store.create('acme/app', 'feature', 'task', 'task')
        job = self.store.claim(10, 2)
        self.store.cancel(run['id'])
        with self.assertRaises(Conflict):
            self.store.finish(job, 'verified')
        self.assertEqual(self.store.get(run['id'])['state'], 'cancelled')

    def test_pause_stops_claiming(self):
        self.store.create('acme/app', 'feature', 'task', 'task')
        self.store.control('paused', True)
        self.assertIsNone(self.store.claim(10, 2))
        self.store.control('paused', False)
        self.assertIsNotNone(self.store.claim(10, 2))

    def test_malicious_proposal_cannot_write_any_files_before_scope_validation(self):
        engine = Engine(self.config)
        workspace = self.root / 'workspace'
        workspace.mkdir()
        proposal = {'changes': [{'path': 'src/app.py', 'content': 'valid'}, {'path': '../escape', 'content': 'bad'}]}
        with self.assertRaises(ConfigurationError):
            engine.apply_changes(workspace, self.config['projects']['acme/app'], {'files': ['src/app.py']}, proposal)
        self.assertFalse((workspace / 'src/app.py').exists())
        self.assertFalse((self.root / 'escape').exists())

    def test_symlink_parent_cannot_escape_workspace(self):
        engine = Engine(self.config)
        workspace = self.root / 'workspace'
        workspace.mkdir()
        (workspace / 'src').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            engine.apply_changes(workspace, self.config['projects']['acme/app'], {'files': ['src/app.py']},
                                 {'changes': [{'path': 'src/app.py', 'content': 'bad'}]})
        self.assertFalse((self.root / 'app.py').exists())

    def test_protected_paths_stay_protected_even_with_broad_project_scope(self):
        for path in ['.git/config', 'src/../../escape', '.env', 'src/private.key']:
            with self.subTest(path=path), self.assertRaises(ConfigurationError):
                safe_path(path)

    def test_wrong_revision_cannot_schedule_production_verification(self):
        engine = Engine(self.config)
        run = self.store.create('acme/app', 'bug', 'task', 'task')
        job = self.store.claim(10, 2)
        self.store.finish(job, 'awaiting_deployment', {'merge_sha': 'a' * 40})
        with self.assertRaises(Conflict):
            engine.deployed(run['id'], {'repository': 'acme/app', 'sha': 'b' * 40,
                           'environment': 'production', 'deployed_at': datetime.now(timezone.utc).isoformat(), 'id': 1})
        self.assertIsNone(self.store.claim(10, 2))

    def test_deployment_window_delays_verification_and_duplicate_cannot_repeat(self):
        engine = Engine(self.config)
        run = self.store.create('acme/app', 'bug', 'task', 'task')
        job = self.store.claim(10, 2)
        self.store.finish(job, 'awaiting_deployment', {'merge_sha': 'a' * 40})
        deployment = {'repository': 'acme/app', 'sha': 'a' * 40, 'environment': 'production',
                      'deployed_at': datetime.now(timezone.utc).isoformat(), 'id': 1}
        engine.deployed(run['id'], deployment)
        engine.deployed(run['id'], deployment)
        self.assertIsNone(self.store.claim(10, 2))
        self.assertEqual(sum(j['action'] == 'verify' for j in self.store.jobs()), 1)

    def test_no_telemetry_cannot_be_called_recovery(self):
        with self.assertRaises(RuntimeError):
            Runtime(self.config).production(self.config['projects']['acme/app'], {})

    def test_expired_lease_cannot_be_resurrected_without_reclaim(self):
        self.store.create('acme/app', 'feature', 'task', 'task')
        job = self.store.claim(10, 2)
        with self.store.transaction() as db:
            db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (job['id'],))
        self.assertFalse(self.store.renew(job, 10))
        with self.assertRaises(Conflict):
            self.store.finish(job, 'verified')

    def test_failed_verification_can_reobserve_same_real_deployment(self):
        run = self.store.create('acme/app', 'bug', 'task', 'task')
        job = self.store.claim(10, 2)
        deployment = {'id': 42, 'sha': 'a' * 40}
        self.store.finish(job, 'needs_human', {'deployment': deployment})
        self.store.recover(run['id'], 'verify', 'human')
        recovered = self.store.claim(10, 2)
        self.assertEqual(recovered['payload']['deployment'], deployment)
        self.assertEqual(self.store.get(run['id'])['state'], 'verifying')

    def test_retry_cannot_replay_failed_job_after_successor(self):
        run = self.store.create('acme/app', 'bug', 'task', 'task')
        old = self.store.claim(10, 2)
        self.store.fail(old, 'network failed', 1)
        self.store.recover(run['id'], 'plan', 'human', 'try again')
        with self.assertRaises(Conflict):
            self.store.retry(old['id'])

    def test_approved_scope_cannot_be_replanned_before_first_commit(self):
        run, digest = self.approved_run()
        job = self.store.claim(10, 2)
        self.store.finish(job, 'needs_human')
        with self.assertRaises(Conflict):
            self.store.recover(run['id'], 'plan', 'human', 'scope changed')
        self.assertEqual(self.store.get(run['id'])['data']['spec_hash'], digest)
        self.assertIsNone(self.store.claim(10, 2))

    def test_submission_keys_are_project_scoped_and_reject_changed_intent(self):
        first = self.store.create('acme/app', 'bug', 'task', 'same', key='ticket')
        second = self.store.create('acme/other', 'bug', 'task', 'same', key='ticket')
        self.assertNotEqual(first['id'], second['id'])
        with self.assertRaises(Conflict):
            self.store.create('acme/app', 'bug', 'task', 'different', key='ticket')

    def test_administrative_pause_does_not_consume_failure_allowance(self):
        self.store.create('acme/app', 'bug', 'task', 'same')
        job = self.store.claim(10, 2)
        self.store.defer(job, 'paused', seconds=0)
        next_job = self.store.claim(10, 2)
        self.assertEqual(next_job['attempts'], 1)

    def test_webhook_requires_signature_and_acknowledges_only_durable_queue(self):
        secret = b'test-only-secret-at-least-32-bytes-long'
        secret_file = self.root / 'secret'
        secret_file.write_bytes(secret)
        self.config['webhook_secrets']['github'] = str(secret_file)
        engine = Engine(self.config)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(engine))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/webhooks/github'
        body = json.dumps({'repository': {'full_name': 'acme/app'}, 'action': 'opened'}).encode()
        headers = {'Content-Type': 'application/json', 'X-GitHub-Event': 'issues', 'X-GitHub-Delivery': 'one'}
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers))
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()
            headers['X-Hub-Signature-256'] = 'sha256=' + hmac.new(secret, body, hashlib.sha256).hexdigest()
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers)) as response:
                self.assertEqual(response.status, 202)
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers)) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(len(engine.store.jobs()), 1)
            self.assertEqual(engine.store.list(), [])  # receiving an event is not executing its task
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()

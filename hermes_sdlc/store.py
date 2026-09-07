"""Transactional inbox, leased jobs, approvals and append-only lifecycle evidence."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Conflict(RuntimeError):
    pass


class Store:
    def __init__(self, state_dir: str | Path):
        self.root = Path(state_dir)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.path = self.root / 'lifecycle.sqlite3'
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, project TEXT NOT NULL, kind TEXT NOT NULL,
                    title TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL,
                    data TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    dedup_key TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, run_id TEXT REFERENCES runs(id),
                    action TEXT NOT NULL, payload TEXT NOT NULL, job_key TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    available REAL NOT NULL, lease_until REAL, token TEXT, error TEXT);
                CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status,available,lease_until);
                CREATE TABLE IF NOT EXISTS evidence (
                    id INTEGER PRIMARY KEY, run_id TEXT REFERENCES runs(id),
                    kind TEXT NOT NULL, value TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals (
                    run_id TEXT NOT NULL REFERENCES runs(id), digest TEXT NOT NULL,
                    actor TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(run_id,digest));
                CREATE TABLE IF NOT EXISTS controls (name TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=30000')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            if db.in_transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def _job(self, db, run_id, action, payload, key, available=None):
        db.execute('INSERT OR IGNORE INTO jobs(run_id,action,payload,job_key,available) VALUES(?,?,?,?,?)',
                   (run_id, action, canonical(payload), key, time.time() if available is None else available))

    def _evidence(self, db, run_id, kind, value):
        db.execute('INSERT INTO evidence(run_id,kind,value,created) VALUES(?,?,?,?)',
                   (run_id, kind, canonical(value), time.time()))

    @staticmethod
    def _run(row):
        if row is None:
            raise Conflict('Unknown run')
        result = dict(row)
        result['data'] = json.loads(result['data'])
        return result

    def create(self, project, kind, title, body, key=None, metadata=None, *, coalesce=False):
        run_id = uuid.uuid4().hex[:20]
        key = f'{project}:{key or run_id}'
        now = time.time()
        with self.transaction() as db:
            previous = db.execute('SELECT * FROM runs WHERE dedup_key=?', (key,)).fetchone()
            if previous:
                if coalesce and previous['project'] == project and previous['kind'] == kind:
                    self._evidence(db, previous['id'], 'incident_repeated', {'observation': body})
                    return self._run(previous)
                if (previous['project'], previous['kind'], previous['title'], previous['body']) != (project, kind, title, body):
                    raise Conflict('Submission key reused with a different task')
                return self._run(previous)
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (run_id, project, kind, title, body, 'queued', canonical(metadata or {}), now, now, key))
            self._job(db, run_id, 'plan', {}, f'{run_id}:plan:0')
            self._evidence(db, run_id, 'created', {'kind': kind, 'project': project})
            return self._run(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())

    def get(self, run_id):
        with self.transaction() as db:
            return self._run(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())

    def list(self, project=None):
        with self.transaction() as db:
            rows = db.execute('SELECT * FROM runs WHERE (? IS NULL OR project=?) ORDER BY created DESC', (project, project)).fetchall()
            return [self._run(row) for row in rows]

    def history(self, run_id):
        with self.transaction() as db:
            return [{**dict(row), 'value': json.loads(row['value'])} for row in db.execute('SELECT * FROM evidence WHERE run_id=? ORDER BY id', (run_id,))]

    def event(self, provider, delivery, event_type, payload):
        key = f'event:{provider}:{delivery}'
        with self.transaction() as db:
            existing = db.execute('SELECT payload FROM jobs WHERE job_key=?', (key,)).fetchone()
            envelope = {'provider': provider, 'type': event_type, 'payload': payload}
            if existing and existing['payload'] != canonical(envelope):
                raise Conflict('Delivery ID reused with a different payload')
            self._job(db, None, 'event', envelope, key)
            return not bool(existing)

    def approve(self, run_id, digest, actor, *, plan_comment=None):
        with self.transaction() as db:
            run = self._run(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())
            if run['data'].get('spec_hash') != digest:
                raise Conflict('Approval does not match the current specification')
            if db.execute('SELECT 1 FROM approvals WHERE run_id=? AND digest=?', (run_id, digest)).fetchone():
                return
            if plan_comment is not None and run['data'].get('plan_comment') != plan_comment:
                raise Conflict('Published plan changed before approval')
            if run['state'] != 'awaiting_approval':
                raise Conflict('Run is not awaiting approval')
            db.execute('INSERT INTO approvals VALUES(?,?,?,?)', (run_id, digest, actor, time.time()))
            db.execute('UPDATE runs SET state=?,updated=? WHERE id=?', ('queued', time.time(), run_id))
            self._job(db, run_id, 'implement', {}, f'{run_id}:implement:{digest}')
            self._evidence(db, run_id, 'approved', {'actor': actor, 'spec_hash': digest})

    def record_plan_comment(self, snapshot, comment_id, body):
        """Checkpoint the exact GitHub projection without overwriting a newer revision."""
        with self.transaction() as db:
            run = self._run(db.execute('SELECT * FROM runs WHERE id=?', (snapshot['id'],)).fetchone())
            if (run['state'], run['data'].get('spec_hash')) != (snapshot['state'], snapshot['data'].get('spec_hash')):
                raise Conflict('Plan changed during publication')
            metadata = {'id': comment_id, 'body': body, 'body_hash': hashlib.sha256(body.encode()).hexdigest(),
                        'spec_hash': run['data'].get('spec_hash'), 'revision': run['data']['spec']['revision']}
            if run['data'].get('plan_comment') == metadata:
                return
            run['data']['plan_comment'] = metadata
            db.execute('UPDATE runs SET data=?,updated=? WHERE id=?',
                       (canonical(run['data']), time.time(), run['id']))
            self._evidence(db, run['id'], 'plan_published', metadata)

    def schedule(self, run_id, action, payload, key, states, updates=None, available=None):
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM jobs WHERE job_key=?', (key,)).fetchone():
                return
            run = self._run(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())
            if run['state'] not in states:
                raise Conflict(f"Cannot {action} from {run['state']}")
            if db.execute("SELECT 1 FROM jobs WHERE run_id=? AND status IN ('pending','running')", (run_id,)).fetchone():
                raise Conflict('Run already has active work')
            data = {**run['data'], **(updates or {})}
            state = 'verifying' if action == 'verify' else 'queued'
            db.execute('UPDATE runs SET data=?,state=?,updated=? WHERE id=?', (canonical(data), state, time.time(), run_id))
            self._job(db, run_id, action, payload, key, available)
            self._evidence(db, run_id, 'scheduled', {'action': action, 'key': key})

    def transition(self, run_id, state, states, updates=None, evidence=None):
        with self.transaction() as db:
            run = self._run(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())
            if run['state'] not in states:
                raise Conflict(f"Cannot transition {run['state']} to {state}")
            data = {**run['data'], **(updates or {})}
            db.execute('UPDATE runs SET state=?,data=?,updated=? WHERE id=?', (state, canonical(data), time.time(), run_id))
            if evidence:
                self._evidence(db, run_id, evidence[0], evidence[1])

    def control(self, name, value=None):
        with self.transaction() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO controls VALUES(?,?)', (name, canonical(value)))
            row = db.execute('SELECT value FROM controls WHERE name=?', (name,)).fetchone()
            return json.loads(row[0]) if row else None

    def claim(self, lease_seconds, max_attempts):
        now = time.time()
        with self.transaction() as db:
            if self._paused(db):
                return None
            exhausted = db.execute("SELECT * FROM jobs WHERE status='running' AND lease_until<? AND attempts>=?", (now, max_attempts)).fetchall()
            for row in exhausted:
                db.execute("UPDATE jobs SET status='failed',error='lease expired; retry budget exhausted' WHERE id=?", (row['id'],))
                if row['run_id']:
                    db.execute("UPDATE runs SET state='needs_human',updated=? WHERE id=? AND state!='cancelled'", (now, row['run_id']))
            row = db.execute("SELECT * FROM jobs WHERE (status='pending' AND available<=?) OR (status='running' AND lease_until<? AND attempts<?) ORDER BY id LIMIT 1", (now, now, max_attempts)).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET status='running',token=?,lease_until=?,attempts=attempts+1 WHERE id=?", (token, now + lease_seconds, row['id']))
            if row['run_id']:
                state = {'plan': 'planning', 'implement': 'implementing', 'revise': 'implementing', 'verify': 'verifying'}[row['action']]
                db.execute("UPDATE runs SET state=?,updated=? WHERE id=? AND state!='cancelled'", (state, now, row['run_id']))
            result = dict(row)
            result.update(token=token, attempts=row['attempts'] + 1, payload=json.loads(row['payload']))
            return result

    @staticmethod
    def _paused(db):
        row = db.execute("SELECT value FROM controls WHERE name='paused'").fetchone()
        return row and json.loads(row[0])

    def renew(self, job, seconds):
        with self.transaction() as db:
            result = db.execute("UPDATE jobs SET lease_until=? WHERE id=? AND token=? AND status='running' AND lease_until>?", (time.time() + seconds, job['id'], job['token'], time.time()))
            return result.rowcount == 1 and not self._paused(db)

    def checkpoint(self, job, updates, kind, value):
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM jobs WHERE id=? AND token=? AND status='running' AND lease_until>?", (job['id'], job['token'], time.time())).fetchone():
                raise Conflict('Job lease was lost')
            run = self._run(db.execute('SELECT * FROM runs WHERE id=?', (job['run_id'],)).fetchone())
            if run['state'] == 'cancelled':
                raise Conflict('Run cancelled')
            db.execute('UPDATE runs SET data=?,updated=? WHERE id=?', (canonical({**run['data'], **updates}), time.time(), run['id']))
            self._evidence(db, run['id'], kind, value)

    def finish(self, job, state=None, updates=None, evidence=None):
        with self.transaction() as db:
            changed = db.execute("UPDATE jobs SET status='done',lease_until=NULL WHERE id=? AND token=? AND status='running' AND lease_until>?", (job['id'], job['token'], time.time()))
            if not changed.rowcount:
                raise Conflict('Job lease was lost')
            if job['run_id']:
                run = self._run(db.execute('SELECT * FROM runs WHERE id=?', (job['run_id'],)).fetchone())
                if run['state'] != 'cancelled':
                    db.execute('UPDATE runs SET state=?,data=?,updated=? WHERE id=?', (state or run['state'], canonical({**run['data'], **(updates or {})}), time.time(), run['id']))
                    if evidence:
                        self._evidence(db, run['id'], evidence[0], evidence[1])

    def fail(self, job, error, max_attempts):
        with self.transaction() as db:
            retry = job['attempts'] < max_attempts
            changed = db.execute("UPDATE jobs SET status=?,error=?,available=?,lease_until=NULL WHERE id=? AND token=? AND status='running'",
                                 ('pending' if retry else 'failed', str(error)[:2000], time.time() + min(60, 5 * job['attempts']), job['id'], job['token']))
            if changed.rowcount and job['run_id']:
                db.execute("UPDATE runs SET state=?,updated=? WHERE id=? AND state!='cancelled'", ('queued' if retry else 'needs_human', time.time(), job['run_id']))
                self._evidence(db, job['run_id'], 'error', {'action': job['action'], 'error': str(error)[:2000], 'retry': retry})

    def defer(self, job, reason, seconds=5):
        """Dependency delay or administrative pause does not consume failure attempts."""
        with self.transaction() as db:
            changed = db.execute("UPDATE jobs SET status='pending',attempts=max(0,attempts-1),available=?,lease_until=NULL,error=? WHERE id=? AND token=? AND status='running'",
                                 (time.time() + seconds, reason, job['id'], job['token']))
            if changed.rowcount and job['run_id']:
                db.execute("UPDATE runs SET state='queued',updated=? WHERE id=? AND state!='cancelled'", (time.time(), job['run_id']))

    def recover(self, run_id, action, actor, feedback='', request_id=None):
        """Explicit operator decision starts a bounded new attempt, preserving old evidence."""
        with self.transaction() as db:
            run = self._run(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())
            if request_id is not None:
                previous = db.execute(
                    "SELECT value FROM evidence WHERE run_id=? AND kind='human_recovery' AND json_extract(value, '$.request_id')=?",
                    (run_id, request_id)).fetchone()
                if previous:
                    value = json.loads(previous['value'])
                    if (value['action'], value['actor'], value['feedback']) != (action, actor, feedback):
                        raise Conflict('Recovery request identity reused with different intent')
                    return
            if run['state'] not in {'needs_human', 'awaiting_approval'}:
                raise Conflict('Recovery requires a human-stop state')
            if db.execute("SELECT 1 FROM jobs WHERE run_id=? AND status IN ('pending','running')", (run_id,)).fetchone():
                raise Conflict('Run already has active work')
            data = run['data']
            sequence = data.get('recoveries', 0) + 1
            data['recoveries'] = sequence
            if action == 'plan':
                if data.get('head_sha') or db.execute('SELECT 1 FROM approvals WHERE run_id=?', (run_id,)).fetchone():
                    raise Conflict('Submit a new task to change scope after approval')
                data.pop('spec_hash', None)
                data['spec_revision'] = data.get('spec_revision', 0) + 1
            elif action == 'verify':
                if not data.get('deployment'):
                    raise Conflict('No authenticated deployment to re-observe')
            elif action == 'revise':
                if not data.get('spec_hash') or data.get('merge_sha'):
                    raise Conflict('No approved, unmerged implementation to resume')
            else:
                raise Conflict('Unknown recovery action')
            # The operator explicitly authorizes another model-call allowance, not an
            # invisible reset. Total historical calls remain in append-only evidence.
            data['model_calls'] = 0
            db.execute("UPDATE runs SET state='queued',data=?,updated=? WHERE id=?", (canonical(data), time.time(), run_id))
            payload = {'feedback': feedback}
            if action == 'verify':
                payload['deployment'] = data['deployment']
            self._job(db, run_id, action, payload, f'{run_id}:recovery:{sequence}:{action}')
            self._evidence(db, run_id, 'human_recovery', {'action': action, 'actor': actor, 'feedback': feedback,
                                                       'sequence': sequence, 'request_id': request_id})

    def cancel(self, run_id):
        with self.transaction() as db:
            self._run(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())
            db.execute("UPDATE runs SET state='cancelled',updated=? WHERE id=?", (time.time(), run_id))
            db.execute("UPDATE jobs SET status='cancelled' WHERE run_id=? AND status IN ('pending','running')", (run_id,))
            self._evidence(db, run_id, 'cancelled', {})

    def retry(self, job_id):
        with self.transaction() as db:
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job or job['status'] != 'failed':
                raise Conflict('Only failed jobs can be retried')
            if job['run_id']:
                run = self._run(db.execute('SELECT * FROM runs WHERE id=?', (job['run_id'],)).fetchone())
                if run['state'] != 'needs_human':
                    raise Conflict('Cannot retry historical work in the current lifecycle state')
                latest = db.execute('SELECT max(id) FROM jobs WHERE run_id=?', (job['run_id'],)).fetchone()[0]
                if latest != job_id or db.execute("SELECT 1 FROM jobs WHERE run_id=? AND status IN ('pending','running')", (job['run_id'],)).fetchone():
                    raise Conflict('Only the latest failed job with no active successor can be retried')
            db.execute("UPDATE jobs SET status='pending',attempts=0,available=? WHERE id=?", (time.time(), job_id))
            if job['run_id']:
                db.execute("UPDATE runs SET state='queued',updated=? WHERE id=? AND state!='cancelled'", (time.time(), job['run_id']))

    def jobs(self):
        with self.transaction() as db:
            return [dict(r) for r in db.execute('SELECT id,run_id,action,status,attempts,available,error FROM jobs ORDER BY id')]

    def metrics(self):
        with self.transaction() as db:
            states = {r[0]: r[1] for r in db.execute('SELECT state,count(*) FROM runs GROUP BY state')}
            actions = {r[0]: r[1] for r in db.execute('SELECT kind,count(*) FROM evidence GROUP BY kind')}
            return {'runs_by_state': states, 'events_by_kind': actions, 'jobs_by_state': {r[0]:r[1] for r in db.execute('SELECT status,count(*) FROM jobs GROUP BY status')}, 'paused': bool(self._paused(db))}

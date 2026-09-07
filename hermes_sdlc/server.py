"""Small authenticated event ingress. HTTP acceptance means durably queued, not done."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .engine import Engine
from .store import Conflict


def handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Never log URLs, webhook bodies or authentication material.

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/health':
                self.reply(200, {'service': 'hermes-sdlc', 'status': 'ready', 'paused': bool(engine.store.control('paused'))})
            else:
                self.reply(404, {'error': 'not found'})

        def do_POST(self):
            provider = {'/webhooks/github': 'github', '/webhooks/deployment': 'deployment'}.get(self.path)
            source_name = self.path.removeprefix('/webhooks/incidents/') if self.path.startswith('/webhooks/incidents/') else None
            source = engine.config.get('incident_sources', {}).get(source_name)
            if source:
                provider = 'incident:' + source_name
            if not provider:
                self.reply(404, {'error': 'not found'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024 * 1024 or self.headers.get('Transfer-Encoding'):
                    self.reply(413, {'error': 'body must be bounded JSON'})
                    return
                self.connection.settimeout(10)
                body = self.rfile.read(length)
                if len(body) != length:
                    self.reply(400, {'error': 'incomplete request'})
                    return
                secret_file = source['secret_file'] if source else engine.config['webhook_secrets'].get(provider)
                if not secret_file:
                    self.reply(503, {'error': 'route not configured'})
                    return
                secret = Path(secret_file).read_bytes().strip()
                if len(secret) < 32:
                    self.reply(503, {'error': 'route secret invalid'})
                    return
                if source and source['provider'] == 'argocd':
                    supplied = self.headers.get('X-Gitlab-Token', '')
                    expected = secret.decode('utf-8')
                else:
                    prefix = 'sha256=' if provider == 'github' else ''
                    supplied = self.headers.get('X-Hub-Signature-256' if provider == 'github' else 'X-Webhook-Signature', '')
                    expected = prefix + hmac.new(secret, body, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(supplied, expected):
                    self.reply(401, {'error': 'invalid signature'})
                    return
                delivery = self.headers.get('X-GitHub-Delivery' if provider == 'github' else 'X-Request-ID')
                if source:
                    delivery = hashlib.sha256(body).hexdigest()
                if not delivery or len(delivery) > 200:
                    self.reply(400, {'error': 'delivery identity required'})
                    return
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError('object required')
                kind = 'incident' if source else (self.headers.get('X-GitHub-Event', '') if provider == 'github' else 'deployment')
                if provider == 'github' and kind not in {'ping','issues','issue_comment','pull_request','pull_request_review','pull_request_review_comment','workflow_run','deployment_status'}:
                    self.reply(400, {'error': 'unsupported event'})
                    return
                if kind == 'ping':
                    self.reply(200, {'status': 'ready'})
                    return
                new = engine.store.event(provider, delivery, kind, payload)
                self.reply(202 if new else 200, {'status': 'queued' if new else 'duplicate'})
            except Conflict as exc:
                self.reply(409, {'error': str(exc)})
            except (ValueError, KeyError):
                self.reply(400, {'error': 'invalid event'})
            except Exception:
                self.reply(503, {'error': 'event not accepted; retry delivery'})
    return Handler


def serve(config):
    engine = Engine(config)
    server = ThreadingHTTPServer((config['listen']['host'], config['listen']['port']), handler(engine))
    server.daemon_threads = True
    stop = threading.Event()
    def work():
        while not stop.is_set():
            try:
                if not engine.tick():
                    stop.wait(1)
            except Exception:
                # No secrets/event body in supervisor diagnostics. Durable jobs remain resumable.
                print('SDLC worker error; retrying durable queue', flush=True)
                stop.wait(3)
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    print(f'hermes-sdlc ready at http://{config["listen"]["host"]}:{server.server_port}', flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=5)

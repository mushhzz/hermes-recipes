"""GitHub App credentials stay in the controller; installation tokens stay in memory."""
import base64
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime


class AppAuthError(RuntimeError):
    pass


class GitHubApp:
    def __init__(self, settings):
        self.settings = settings
        self._access = None
        self._expires = 0
        self._login = None
        self._lock = threading.RLock()

    def _jwt(self):
        def encode(value):
            return base64.urlsafe_b64encode(value).rstrip(b'=')
        now = int(time.time())
        unsigned = b'.'.join(encode(json.dumps(value, separators=(',', ':')).encode()) for value in (
            {'alg': 'RS256', 'typ': 'JWT'},
            {'iat': now - 60, 'exp': now + 540, 'iss': str(self.settings['app_id'])}))
        try:
            signed = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', self.settings['private_key_file']],
                                    input=unsigned, capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            raise AppAuthError('GitHub App signing executable unavailable') from None
        if signed.returncode:
            raise AppAuthError('GitHub App private-key signing failed')
        return (unsigned + b'.' + encode(signed.stdout)).decode()

    def _request(self, path, token, body=None):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        request = urllib.request.Request('https://api.github.com' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'Hermes-SDLC-App'})
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise AppAuthError('GitHub App response exceeds size limit')
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise AppAuthError(f'GitHub App authentication request returned HTTP {code}') from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise AppAuthError('GitHub App authentication response unavailable or invalid') from None

    def identity(self):
        with self._lock:
            if self._login is None:
                app = self._request('/app', self._jwt())
                if app.get('id') != self.settings['app_id'] or app.get('slug') != self.settings['slug']:
                    raise AppAuthError('Private key does not match the configured GitHub App')
                self._login = app['slug'] + '[bot]'
            return self._login

    def token(self):
        with self._lock:
            if self._access and time.time() < self._expires - 60:
                return self._access
            self.identity()
            result = self._request(f'/app/installations/{self.settings["installation_id"]}/access_tokens', self._jwt(),
                                   {'repository_ids': self.settings['repository_ids']})
            token = result.get('token')
            expires = datetime.fromisoformat(result['expires_at'].replace('Z', '+00:00')).timestamp()
            if not isinstance(token, str) or not token or expires <= time.time() + 60:
                raise AppAuthError('GitHub App returned an unusable installation token')
            self._access, self._expires = token, expires
            return token

    def installation(self):
        self.identity()
        return self._request(f'/app/installations/{self.settings["installation_id"]}', self._jwt())

    def repositories(self):
        return self._request('/installation/repositories?per_page=100', self.token())['repositories']

    def environment(self, base):
        # Override personal tokens only for authenticated Git/gh subprocesses.
        env = {key: value for key, value in base.items()
               if key not in {'GH_TOKEN', 'GITHUB_TOKEN', 'GH_DEBUG', 'GIT_CURL_VERBOSE'} and not key.startswith('GIT_TRACE')}
        env['GH_TOKEN'] = self.token()
        return env

"""Trusted, host-owned lifecycle configuration; never loaded from a task checkout."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath

DEFAULT_CONFIG = Path.home() / '.hermes/sdlc/config.json'
LIMITS = dict(model_timeout_seconds=180, check_timeout_seconds=300, max_attempts=2,
              lease_seconds=900, max_files=30, max_context_bytes=120000,
              max_output_bytes=1000000, max_model_calls=8)


class ConfigurationError(ValueError):
    pass


def safe_path(value: str, allowed: list[str] | None = None) -> str:
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ConfigurationError('Invalid repository path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or str(path) != value:
        raise ConfigurationError(f'Non-canonical repository path: {value!r}')
    forbidden = {'.git', '.hermes', '.ssh', '.aws', '.kube', 'node_modules', '.venv', '__pycache__'}
    if any(p in forbidden or p == '.env' or p.startswith('.env.') or p.endswith(('.pem', '.key')) for p in path.parts):
        raise ConfigurationError(f'Protected repository path: {value}')
    if allowed is not None and not any(value == p or (p.endswith('/') and value.startswith(p)) for p in allowed):
        raise ConfigurationError(f'Path outside project write scope: {value}')
    return value


def load(path: str | Path = DEFAULT_CONFIG) -> dict:
    path = Path(path).expanduser().resolve()
    config = json.loads(path.read_text())
    config['_path'] = str(path)
    config['state_dir'] = str(Path(config['state_dir']).expanduser().resolve())
    config['limits'] = {**LIMITS, **config.get('limits', {})}
    if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in config['limits'].values()):
        raise ConfigurationError('Limits must be positive integers')
    config.setdefault('listen', {'host': '127.0.0.1', 'port': 8645})
    config.setdefault('webhook_secrets', {})
    config.setdefault('model', None)
    config.setdefault('provider', None)
    root = Path(config.get('hermes_root', Path.home() / '.hermes/hermes-agent')).expanduser().resolve()
    config['hermes_root'] = str(root)
    config.setdefault('hermes_python', str(root / 'venv/bin/python'))
    if not config.get('projects'):
        raise ConfigurationError('At least one project is required')
    app = config.get('github_app')
    if app is not None:
        if not isinstance(app, dict):
            raise ConfigurationError('github_app must be an object')
        ids = [app.get('app_id'), app.get('installation_id')]
        repositories = app.get('repository_ids')
        if not isinstance(repositories, list) or not 1 <= len(repositories) <= 100:
            raise ConfigurationError('GitHub App requires 1–100 explicit repository IDs')
        if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in ids + repositories):
            raise ConfigurationError('GitHub App and repository IDs must be positive integers')
        if not isinstance(app.get('slug'), str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', app['slug']):
            raise ConfigurationError('GitHub App requires its registered slug')
        key = app.get('private_key_file')
        if not isinstance(key, str) or not Path(key).is_absolute():
            raise ConfigurationError('GitHub App private key requires an absolute host-owned path')
        key = Path(key).resolve()
        if not key.is_file() or key.stat().st_mode & 0o077 or key.stat().st_uid != os.getuid():
            raise ConfigurationError('GitHub App private key must be owned by this user and inaccessible to others')
        app['private_key_file'] = str(key)
    for name, project in config['projects'].items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
            raise ConfigurationError('Project names must be owner/repository')
        project.setdefault('base_branch', 'main')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', project['base_branch']) or '..' in project['base_branch']:
            raise ConfigurationError('Invalid base branch')
        project.setdefault('publish', False)
        project.setdefault('bot_login', None)
        if app:
            login = app['slug'] + '[bot]'
            if project['bot_login'] not in (None, login):
                raise ConfigurationError('Configured bot does not match the GitHub App slug')
            project['bot_login'] = login
        project.setdefault('approvers', [])
        project.setdefault('required_ci_checks', [])
        project.setdefault('production_checks', [])
        project.setdefault('environment', 'production')
        project.setdefault('observation_seconds', 3600)
        if not isinstance(project['observation_seconds'], int) or project['observation_seconds'] < 0:
            raise ConfigurationError('observation_seconds must be nonnegative')
        if project['publish'] and (not app or not project['approvers']):
            raise ConfigurationError('Publication requires GitHub App authentication and human approvers')
        if project['bot_login'] in project['approvers']:
            raise ConfigurationError('The publishing bot cannot approve its own work')
        if not project.get('allowed_paths'):
            raise ConfigurationError('Every project needs explicit allowed_paths')
        for p in project['allowed_paths']:
            safe_path(p.rstrip('/'))
        if not project.get('checks'):
            raise ConfigurationError('Every project needs at least one executable check')
        for check in project['checks']:
            if not check.get('name') or not isinstance(check.get('argv'), list) or not check['argv'] or not all(isinstance(a, str) and '\x00' not in a for a in check['argv']):
                raise ConfigurationError('Checks require name and nonempty argv strings')
        if not project.get('sandbox_image'):
            raise ConfigurationError('A trusted sandbox_image is required')
        source = project.get('source', '')
        if source.startswith('https://'):
            if source != f'https://github.com/{name}.git':
                raise ConfigurationError('Remote source must match the configured GitHub repository')
        else:
            project['source'] = str(Path(source).expanduser().resolve())
            if not source or not Path(project['source']).is_dir():
                raise ConfigurationError('Project source checkout is missing')
        state = Path(config['state_dir'])
        if not source.startswith('https://') and (state == Path(project['source']) or state.is_relative_to(project['source'])):
            raise ConfigurationError('State and trusted configuration must live outside the target checkout')
        if not source.startswith('https://') and path.is_relative_to(project['source']):
            raise ConfigurationError('Trusted config must live outside the target checkout')
        if app and not source.startswith('https://') and Path(app['private_key_file']).is_relative_to(project['source']):
            raise ConfigurationError('GitHub App private key must live outside the target checkout')
    return config


def write_private(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

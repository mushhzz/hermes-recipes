"""Versioned proposal evaluations: objective contracts, not judge-only quality scores."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .adapters import Runtime
from .config import safe_path
from .store import fingerprint


def evaluate(config, suite_path):
    suite = json.loads(Path(suite_path).read_text())
    runtime = Runtime(config)
    results = []
    for case in suite['cases']:
        started = time.monotonic()
        try:
            response = runtime.propose(case['stage'], case['context'])
            proposal = response['proposal']
            failures = []
            expectation = case['expect']
            if case['stage'] == 'review':
                if proposal.get('verdict') != expectation['verdict']:
                    failures.append('Incorrect pass/fail judgment for the labeled behavior')
            elif case['stage'] == 'plan':
                paths = proposal.get('files', [])
                if not paths or not proposal.get('acceptance'):
                    failures.append('No actionable plan')
                for path in paths:
                    safe_path(path, expectation['allowed_paths'])
                if any(path not in paths for path in expectation.get('required_files', [])):
                    failures.append('Required implementation/test scope omitted')
            else:
                raise ValueError('Evaluation stage unsupported')
            results.append({'id': case['id'], 'passed': not failures, 'failures': failures,
                            'proposal': proposal, 'usage': response.get('usage', {}),
                            'model': response.get('model'), 'duration_seconds': time.monotonic() - started})
        except Exception as exc:
            results.append({'id': case['id'], 'passed': False, 'failures': [type(exc).__name__],
                            'duration_seconds': time.monotonic() - started})
    report = {'suite_version': suite['version'], 'suite_hash': fingerprint(suite),
              'created_at': datetime.now(timezone.utc).isoformat(), 'passed': all(r['passed'] for r in results),
              'cases': results, 'interpretation': 'Small labeled contract suite, not a general correctness or productivity benchmark.'}
    target = Path(config['state_dir']) / 'evaluations'
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = target / f'{time.time_ns()}.json'
    path.write_text(json.dumps(report, indent=2))
    path.chmod(0o600)
    return {'report': str(path), **report}

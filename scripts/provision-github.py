#!/usr/bin/env python3
"""Reconcile repository infrastructure; daily lifecycle work stays in Hermes/GitHub."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hermes_sdlc.config import DEFAULT_CONFIG, load
from hermes_sdlc.github_setup import GitHubSetup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, default=ROOT / 'provisioning/github.json')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--apply', action='store_true', help='Apply the declared repository infrastructure; default is read-only planning')
    args = parser.parse_args()
    result = GitHubSetup(load(args.config)).reconcile(json.loads(args.policy.read_text()), apply=args.apply)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'GitHub provisioning stopped: {exc}. Earlier successful changes may remain; rerun after resolving the error.', file=sys.stderr)
        sys.exit(1)

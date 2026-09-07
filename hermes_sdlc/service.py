"""Background receiver for Hermes/GitHub workflows; not an operator CLI."""
import os
import sys
from pathlib import Path

# Service managers execute this file directly, independently of their working directory.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_sdlc.config import DEFAULT_CONFIG, load
from hermes_sdlc.server import serve


def main():
    if len(sys.argv) != 1:
        raise SystemExit('This is a background service, not a CLI. Use Hermes and GitHub.')
    serve(load(os.environ.get('HERMES_SDLC_CONFIG', str(DEFAULT_CONFIG))))


if __name__ == '__main__':
    main()

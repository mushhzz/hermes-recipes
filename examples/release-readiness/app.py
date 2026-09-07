#!/usr/bin/env python3
"""Release readiness HTTP service.

This module intentionally uses only the Python standard library.  The
``calculate_readiness`` function is pure and accepts an explicit timezone-aware
``now`` value so tests and callers can evaluate boundary conditions
reproducibly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class BadRequest(ValueError):
    """Raised when client-provided input is invalid."""


class ReleaseReadinessHandler(BaseHTTPRequestHandler):
    """HTTP handler for release-readiness routes."""

    revision = ""
    server_version = "ReleaseReadiness/1.0"

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._send_json(200, {"status": "ok", "revision": self.revision})
            return

        if parsed.path == "/readiness":
            self._handle_readiness(parsed.query)
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        """Silence default stderr request logging for cleaner tests/CLI output."""

    def _handle_readiness(self, query: str) -> None:
        try:
            params = parse_qs(query, keep_blank_values=True)
            deployed_at = parse_deployed_at(_single_query_value(params, "deployed_at"))
            observation_seconds = parse_observation_seconds(
                _single_query_value(params, "observation_seconds")
            )
            result = calculate_readiness(
                deployed_at=deployed_at,
                observation_seconds=observation_seconds,
                now=datetime.now(timezone.utc),
                revision=self.revision,
            )
        except BadRequest as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_json(200, result)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _single_query_value(params: dict[str, list[str]], name: str) -> str:
    values = params.get(name)
    if not values or values[0] == "":
        raise BadRequest(f"missing {name}")
    if len(values) != 1:
        raise BadRequest(f"multiple {name} values are not allowed")
    return values[0]


def validate_release_sha(value: str | None) -> str:
    """Validate and return a full lowercase 40-character hexadecimal SHA."""

    if value is None:
        raise ValueError(
            "RELEASE_SHA is required and must be a 40-character lowercase hexadecimal git SHA"
        )
    if not _SHA_RE.fullmatch(value):
        raise ValueError(
            "RELEASE_SHA must be exactly a 40-character lowercase hexadecimal git SHA"
        )
    return value


def parse_deployed_at(value: str) -> datetime:
    """Parse a timezone-aware ISO8601 deployment timestamp."""

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BadRequest("deployed_at must be a valid timezone-aware ISO8601 timestamp") from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BadRequest("deployed_at must include an explicit timezone")
    return parsed


def parse_observation_seconds(value: str) -> int:
    """Parse a nonnegative integer observation duration in seconds."""

    if not re.fullmatch(r"[0-9]+", value):
        raise BadRequest("observation_seconds must be a nonnegative integer")

    max_digits = sys.get_int_max_str_digits()
    if max_digits and len(value) > max_digits:
        raise BadRequest("observation_seconds is too large")

    try:
        return int(value)
    except ValueError as exc:
        raise BadRequest("observation_seconds is too large") from exc


def calculate_readiness(
    deployed_at: datetime,
    observation_seconds: int,
    now: datetime,
    revision: str,
) -> dict[str, Any]:
    """Calculate release readiness for an explicit timezone-aware current time.

    Future deployments report zero elapsed seconds and are never ready.
    Readiness becomes true exactly when elapsed time is greater than or equal to
    the observation duration.
    """

    if deployed_at.tzinfo is None or deployed_at.utcoffset() is None:
        raise ValueError("deployed_at must be timezone-aware")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if observation_seconds < 0:
        raise ValueError("observation_seconds must be nonnegative")

    raw_elapsed_seconds = (
        now.astimezone(timezone.utc) - deployed_at.astimezone(timezone.utc)
    ).total_seconds()
    elapsed_seconds = max(0, int(raw_elapsed_seconds))
    remaining_seconds = max(0, observation_seconds - elapsed_seconds)
    ready = raw_elapsed_seconds >= 0 and elapsed_seconds >= observation_seconds

    return {
        "ready": ready,
        "elapsed_seconds": elapsed_seconds,
        "remaining_seconds": remaining_seconds,
        "revision": revision,
    }


def make_handler(revision: str) -> type[ReleaseReadinessHandler]:
    """Create a request handler class bound to a validated release revision."""

    validate_release_sha(revision)

    class Handler(ReleaseReadinessHandler):
        pass

    Handler.revision = revision
    return Handler


def build_server(host: str, port: int, revision: str) -> ThreadingHTTPServer:
    """Build a ThreadingHTTPServer for the given bind address and revision."""

    return ThreadingHTTPServer((host, port), make_handler(revision))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release readiness HTTP service")
    parser.add_argument("--host", default="127.0.0.1", help="address to bind")
    parser.add_argument("--port", type=int, default=8767, help="port to bind")
    args = parser.parse_args(argv)

    try:
        revision = validate_release_sha(os.environ.get("RELEASE_SHA"))
    except ValueError as exc:
        print(f"startup error: {exc}", file=sys.stderr)
        return 2

    server = build_server(args.host, args.port, revision)
    print(f"serving release readiness on http://{args.host}:{args.port} revision={revision}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

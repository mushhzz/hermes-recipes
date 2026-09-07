import json
import threading
import unittest
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import app


REVISION = "0123456789abcdef0123456789abcdef01234567"


class ReadinessCalculationTests(unittest.TestCase):
    def test_readiness_boundary_exactly_at_observation_duration(self):
        deployed_at = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        now = datetime.fromisoformat("2026-01-01T00:05:00+00:00")

        result = app.calculate_readiness(deployed_at, 300, now, REVISION)

        self.assertTrue(result["ready"])
        self.assertEqual(result["elapsed_seconds"], 300)
        self.assertEqual(result["remaining_seconds"], 0)
        self.assertEqual(result["revision"], REVISION)

    def test_readiness_before_boundary(self):
        deployed_at = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        now = datetime.fromisoformat("2026-01-01T00:04:59+00:00")

        result = app.calculate_readiness(deployed_at, 300, now, REVISION)

        self.assertFalse(result["ready"])
        self.assertEqual(result["elapsed_seconds"], 299)
        self.assertEqual(result["remaining_seconds"], 1)

    def test_future_timestamp_is_not_ready_and_nonnegative(self):
        deployed_at = datetime.fromisoformat("2026-01-01T00:10:00+00:00")
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")

        result = app.calculate_readiness(deployed_at, 60, now, REVISION)

        self.assertFalse(result["ready"])
        self.assertEqual(result["elapsed_seconds"], 0)
        self.assertEqual(result["remaining_seconds"], 60)

    def test_future_timestamp_is_not_ready_for_zero_observation_duration(self):
        deployed_at = datetime.fromisoformat("2026-01-01T00:00:01+00:00")
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")

        result = app.calculate_readiness(deployed_at, 0, now, REVISION)

        self.assertFalse(result["ready"])
        self.assertEqual(result["elapsed_seconds"], 0)
        self.assertEqual(result["remaining_seconds"], 0)

    def test_timezone_offsets_are_normalized(self):
        deployed_at = app.parse_deployed_at("2026-01-01T02:00:00+02:00")
        now = datetime.fromisoformat("2026-01-01T00:01:00+00:00")

        result = app.calculate_readiness(deployed_at, 60, now, REVISION)

        self.assertTrue(result["ready"])
        self.assertEqual(result["elapsed_seconds"], 60)
        self.assertEqual(result["remaining_seconds"], 0)

    def test_trailing_z_timestamp_is_accepted(self):
        deployed_at = app.parse_deployed_at("2026-01-01T00:00:00Z")

        self.assertEqual(deployed_at.tzinfo, timezone.utc)

    def test_timezone_naive_timestamp_is_rejected(self):
        with self.assertRaises(app.BadRequest):
            app.parse_deployed_at("2026-01-01T00:00:00")

    def test_invalid_observation_seconds_rejected(self):
        for value in ["-1", "1.5", "abc", ""]:
            with self.subTest(value=value):
                with self.assertRaises(app.BadRequest):
                    app.parse_observation_seconds(value)

    def test_oversized_observation_seconds_rejected(self):
        with self.assertRaises(app.BadRequest):
            app.parse_observation_seconds("9" * 5000)

    def test_release_sha_validation(self):
        self.assertEqual(app.validate_release_sha(REVISION), REVISION)
        invalid_values = [None, "", "0123", REVISION.upper(), "g" * 40, REVISION + "0"]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    app.validate_release_sha(value)

    def test_main_fails_clearly_when_release_sha_absent(self):
        original = app.os.environ.pop("RELEASE_SHA", None)
        try:
            self.assertEqual(app.main(["--host", "127.0.0.1", "--port", "0"]), 2)
        finally:
            if original is not None:
                app.os.environ["RELEASE_SHA"] = original


class HTTPRouteTests(unittest.TestCase):
    def setUp(self):
        self.server = app.build_server("127.0.0.1", 0, REVISION)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def get_json(self, path):
        request = Request(self.base_url + path, method="GET")
        try:
            with urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8")
                return response.status, json.loads(body), response.headers.get("Content-Type")
        except HTTPError as exc:
            with exc:
                body = exc.read().decode("utf-8")
                return exc.code, json.loads(body), exc.headers.get("Content-Type")

    def test_health_route(self):
        status, payload, content_type = self.get_json("/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok", "revision": REVISION})
        self.assertEqual(content_type, "application/json")

    def test_readiness_route_ready_for_old_deployment(self):
        deployed_at = quote("2000-01-01T00:00:00+00:00")

        status, payload, _ = self.get_json(
            f"/readiness?deployed_at={deployed_at}&observation_seconds=1"
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ready"])
        self.assertGreaterEqual(payload["elapsed_seconds"], 1)
        self.assertEqual(payload["remaining_seconds"], 0)
        self.assertEqual(payload["revision"], REVISION)

    def test_readiness_route_future_deployment(self):
        deployed_at = quote("2999-01-01T00:00:00+00:00")

        status, payload, _ = self.get_json(
            f"/readiness?deployed_at={deployed_at}&observation_seconds=60"
        )

        self.assertEqual(status, 200)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["elapsed_seconds"], 0)
        self.assertEqual(payload["remaining_seconds"], 60)
        self.assertEqual(payload["revision"], REVISION)

    def test_readiness_route_accepts_timezone_offset(self):
        deployed_at = quote("2000-01-01T05:30:00+05:30")

        status, payload, _ = self.get_json(
            f"/readiness?deployed_at={deployed_at}&observation_seconds=1"
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["revision"], REVISION)

    def test_invalid_readiness_inputs_return_400_json(self):
        cases = [
            "/readiness",
            "/readiness?deployed_at=2026-01-01T00%3A00%3A00%2B00%3A00",
            "/readiness?observation_seconds=1",
            "/readiness?deployed_at=not-a-date&observation_seconds=1",
            "/readiness?deployed_at=2026-01-01T00%3A00%3A00&observation_seconds=1",
            "/readiness?deployed_at=2026-01-01T00%3A00%3A00Z&observation_seconds=-1",
            "/readiness?deployed_at=2026-01-01T00%3A00%3A00Z&observation_seconds=1.5",
        ]

        for path in cases:
            with self.subTest(path=path):
                status, payload, content_type = self.get_json(path)
                self.assertEqual(status, 400)
                self.assertIn("error", payload)
                self.assertEqual(content_type, "application/json")

    def test_oversized_observation_seconds_returns_400_json(self):
        status, payload, content_type = self.get_json(
            "/readiness?deployed_at=2026-01-01T00%3A00%3A00Z&observation_seconds="
            + "9" * 5000
        )

        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        self.assertEqual(content_type, "application/json")

    def test_unknown_route_returns_404_json(self):
        status, payload, content_type = self.get_json("/unknown")

        self.assertEqual(status, 404)
        self.assertEqual(content_type, "application/json")


if __name__ == "__main__":
    unittest.main()

# Release Readiness

A small Python standard-library HTTP service for checking whether a deployment has completed its observation window.

## Requirements

- Python 3.9 or newer.
- No third-party packages.
- `RELEASE_SHA` must be set before startup and must be exactly a full 40-character lowercase hexadecimal git SHA.

Invalid or missing `RELEASE_SHA` values fail startup with a clear error.

## Run

```sh
export RELEASE_SHA=0123456789abcdef0123456789abcdef01234567
python app.py --host 127.0.0.1 --port 8767
```

## Endpoints

### `GET /health`

Returns service health and the running release revision.

Example:

```sh
curl http://127.0.0.1:8767/health
```

Response:

```json
{"status":"ok","revision":"0123456789abcdef0123456789abcdef01234567"}
```

### `GET /readiness`

Checks whether a deployment has soaked for at least the requested observation duration.

Query parameters:

- `deployed_at`: ISO8601 timestamp with an explicit timezone, for example `2026-01-01T12:00:00Z` or `2026-01-01T07:00:00-05:00`.
- `observation_seconds`: nonnegative integer duration in seconds.

Example:

```sh
curl 'http://127.0.0.1:8767/readiness?deployed_at=2026-01-01T12:00:00Z&observation_seconds=3600'
```

Response shape:

```json
{"elapsed_seconds":3600,"ready":true,"remaining_seconds":0,"revision":"0123456789abcdef0123456789abcdef01234567"}
```

Future deployment timestamps are not ready. Readiness becomes `true` exactly when elapsed seconds are greater than or equal to `observation_seconds`. Missing, invalid, timezone-naive, negative, or noninteger inputs return HTTP 400 JSON errors.

Unknown routes return HTTP 404 JSON errors.

## Test

```sh
python -m unittest discover -s tests -v
```

#!/usr/bin/env python3
"""Format Loki API JSON (stdin) for an agent's investigation. Companion to
loki-query.sh.

usage: loki-format.py errors|query|count
"""
import datetime
import json
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "query"
d = json.load(sys.stdin)
if d.get("status") != "success":
    print("loki error:", json.dumps(d)[:800])
    sys.exit(1)
result = d.get("data", {}).get("result", [])


def when(ns: str, fmt: str) -> str:
    return datetime.datetime.fromtimestamp(int(ns) / 1e9, datetime.timezone.utc).strftime(fmt)


if mode == "errors":
    rows = []
    for s in result:
        st = s["stream"]
        for ts, line in s["values"]:
            rows.append((int(ts), st, line))
    rows.sort(key=lambda r: r[0], reverse=True)
    for ts, st, line in rows:
        print(f"=== {when(ts, '%Y-%m-%d %H:%M:%SZ')} env={st.get('deployment_environment')} pod={st.get('k8s_pod_name')}")
        print(f"    {line}")
        # Adjust this list of structured-metadata keys to whatever your own
        # logging setup attaches (trace ids, request ids, code location, ...).
        for k in ("error_type", "error_message", "code_file_path", "code_function_name",
                  "code_line_number", "trace_id", "request_id", "user_id", "action", "status_code"):
            if st.get(k):
                print(f"    {k}: {st[k]}")
        if st.get("exception_stacktrace"):
            print("    stacktrace:")
            for l in st["exception_stacktrace"].splitlines()[-25:]:
                print("      " + l)
    if not rows:
        print("no matching error records in window")

elif mode == "query":
    keep = ("service_name", "deployment_environment", "k8s_pod_name", "k8s_container_name",
            "detected_level", "error_type")
    for s in result:
        print("### stream:", json.dumps({k: v for k, v in s["stream"].items() if k in keep}))
        for ts, line in s["values"]:
            print(f"{when(ts, '%H:%M:%SZ')} {line[:1500]}")
    if not result:
        print("no log lines matched")

elif mode == "count":
    for r in result:
        print(r["value"][1], json.dumps(r["metric"]))
    if not result:
        print("0 (no series)")

else:
    sys.exit(f"unknown mode {mode}")

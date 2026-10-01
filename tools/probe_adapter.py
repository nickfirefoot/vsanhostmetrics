#!/usr/bin/env python3
"""Drive a built adapter image's own HTTP endpoints, headless.

`mp-test` is interactive: it prompts, and with stdin closed it hangs until it
is killed. That makes it useless for verifying a build in a script, which is
exactly when verification matters -- after changing the base image, after
purging OS packages, before cutting a release.

This talks to the same endpoints Operations calls. It starts the image's
swagger server, posts /test and /collect built from the connection already
saved in the SDK project's connections.json, reports what came back, and
removes the container.

    tools/probe_adapter.py --image isdk_vsanhostmetrics-test:1.3.1 \
                           --project ~/vsan-host-metrics

Credentials are read from connections.json at run time and streamed straight
to curl's stdin. No request body is ever written to disk -- an earlier version
of this left one containing the vCenter password in /tmp.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

READY_TIMEOUT = 60
CALL_TIMEOUT = 300


def build_body(project: str, name: str | None) -> dict:
    """Translate connections.json into the AdapterConfig the server expects."""
    with open(os.path.join(project, "connections.json"), encoding="utf-8") as fh:
        conns = json.load(fh)["connections"]
    conn = next((c for c in conns if c["name"] == name), None) if name else conns[0]
    if conn is None:
        sys.exit(f"no connection named {name!r} in connections.json")

    cred = conn["credential"]
    return {
        "adapterKey": {
            "name": conn["name"],
            "adapterKind": "VsanHostMetrics",
            "objectKind": "VsanHostMetrics",
            "identifiers": [
                {"key": k, "value": v["value"],
                 "isPartOfUniqueness": v.get("part_of_uniqueness", False)}
                for k, v in conn["identifiers"].items()
            ],
        },
        "credentialConfig": {
            "credentialKey": cred["credential_kind_key"],
            "credentialFields": [
                {"key": k, "value": v["value"], "isPassword": bool(v.get("password"))}
                for k, v in cred.items() if isinstance(v, dict)
            ],
        },
        "clusterConnectionInfo": None,
        "certificateConfig": {"certificates": []},
        "collectionNumber": 1,
        "collectionWindow": {"startTime": 0, "endTime": 0},
    }


def post(port: int, path: str, body: dict) -> tuple[dict, float]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    start = time.time()
    with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
        return json.loads(resp.read() or b"{}"), time.time() - start


def wait_ready(port: int) -> None:
    for _ in range(READY_TIMEOUT):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/apiVersion", timeout=2).read()
            return
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(1)
    sys.exit("server never answered /apiVersion")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--project", default=os.path.expanduser("~/vsan-host-metrics"))
    ap.add_argument("--connection", default=None,
                    help="connection name in connections.json; default is the first")
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--container", default="adapter-probe")
    args = ap.parse_args()

    body = build_body(args.project, args.connection)

    subprocess.run(["docker", "rm", "-f", args.container],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    subprocess.run(["docker", "run", "-d", "--name", args.container,
                    "-p", f"{args.port}:8080", args.image],
                   stdout=subprocess.DEVNULL, check=True)
    try:
        wait_ready(args.port)
        print(f"server up: {args.image}")

        result, secs = post(args.port, "test", body)
        errors = result.get("errorMessage") or result.get("errors")
        print(f"  /test     {secs:5.1f}s  {'FAILED: ' + str(errors) if errors else 'no errors'}")
        if errors:
            return 1

        result, secs = post(args.port, "collect", body)
        if result.get("errorMessage"):
            print(f"  /collect  {secs:5.1f}s  FAILED: {result['errorMessage']}")
            return 1

        objs = result.get("result") or []
        kinds = collections.Counter(o.get("key", {}).get("objectKind") for o in objs)
        metrics = sum(len(o.get("metrics") or []) for o in objs)
        props = sum(len(o.get("properties") or []) for o in objs)
        print(f"  /collect  {secs:5.1f}s  no errors")
        print(f"    objects    {len(objs)}")
        print(f"    metrics    {metrics}")
        print(f"    properties {props}")
        print(f"    kinds      {len(kinds)}")
        print("    largest    " + ", ".join(f"{k}={n}" for k, n in kinds.most_common(6)))
        if not objs or not metrics:
            print("  EMPTY COLLECTION -- treat as failure")
            return 1
        return 0
    finally:
        subprocess.run(["docker", "rm", "-f", args.container],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    sys.exit(main())

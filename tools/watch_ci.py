#!/usr/bin/env python3
"""Report NEW failed CI runs on this repo. Silent when nothing new failed.

    python3 tools/watch_ci.py              # report new failures
    python3 tools/watch_ci.py --baseline   # record current state, say nothing

Exists because four consecutive branch pushes failed CI and the operator found
out from four GitHub notification emails before this session noticed. A tag
build was being watched; branch pushes were not, so the suites were "green"
only in a local shell.

State in ~/.local/state/pack-issues/ci-seen.json, so a re-armed monitor does
not re-report history -- the first version had no baseline and immediately
replayed three old failures.
"""
import json
import os
import sys
import urllib.error
import urllib.request

REPO = "nickfirefoot/vsanhostmetrics"
STATE = os.path.expanduser("~/.local/state/pack-issues/ci-seen.json")
BAD = ("failure", "timed_out", "cancelled", "startup_failure")


def token():
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        if os.environ.get(key):
            return os.environ[key]
    path = os.path.expanduser("~/github.env")
    if not os.path.exists(path):
        sys.exit("no token: ~/github.env not found")
    for line in open(path):
        line = line.strip().removeprefix("export ").strip()
        if "=" not in line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        if k.strip() in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
            return v.strip().strip("'\"")
    sys.exit("no token in ~/github.env")


def main():
    baseline = "--baseline" in sys.argv
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/runs?per_page=20",
        headers={"Authorization": f"Bearer {token()}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "pack-ci-watch"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            runs = json.load(r).get("workflow_runs", [])
    except urllib.error.HTTPError as e:
        print(f"!! CI API HTTP {e.code}", flush=True)   # never print the token
        return 0
    except Exception as e:
        print(f"!! CI API {type(e).__name__}", flush=True)
        return 0

    try:
        seen = set(json.load(open(STATE)))
    except Exception:
        seen = set()

    new = []
    for r in runs:
        if r.get("status") != "completed":
            continue
        key = f"{r['id']}"
        if key in seen:
            continue
        seen.add(key)
        if r.get("conclusion") in BAD and not baseline:
            new.append(f"CI {r['conclusion'].upper()} {r['head_sha'][:8]} "
                       f"{r['head_branch']} -> {r['html_url']}")

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sorted(seen), f)
    os.replace(tmp, STATE)

    for line in new:
        print(line, flush=True)
    if baseline:
        print(f"CI baseline recorded: {len(seen)} runs", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

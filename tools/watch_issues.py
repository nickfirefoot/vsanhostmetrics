#!/usr/bin/env python3
"""Report new issue activity across the three management pack repositories.

    python3 tools/watch_issues.py            # print new activity, update state
    python3 tools/watch_issues.py --baseline # record current state, print nothing
    python3 tools/watch_issues.py --all      # ignore state, print everything open

Designed to be the command behind a Monitor or a cron entry: it prints ONE LINE
per new item and nothing at all when there is nothing new, so a quiet repo
produces no noise.

State lives in ~/.local/state/pack-issues/seen.json, outside any repository.
The token is read from ~/github.env and is never printed, including in errors.

Why all three repos in one tool: an issue filed against one pack is routinely
caused by another -- the parent/child relationship damage was reported against
this pack and involved two others. Watching them separately is how that gets
missed.
"""
import json
import os
import sys
import urllib.error
import urllib.request

REPOS = [
    "nickfirefoot/vsanhostmetrics",
    "nickfirefoot/Vmwarenetstats",
    "nickfirefoot/memorytieradvancedmonitoring",
]
STATE = os.path.expanduser("~/.local/state/pack-issues/seen.json")
API = "https://api.github.com"


def token():
    """Read a GitHub token from ~/github.env without echoing it anywhere."""
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        if os.environ.get(key):
            return os.environ[key]
    path = os.path.expanduser("~/github.env")
    if not os.path.exists(path):
        sys.exit("no token: ~/github.env not found and no GITHUB_TOKEN in env")
    for line in open(path):
        line = line.strip().lstrip("export ").strip()
        if "=" not in line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        if k.strip() in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
            return v.strip().strip("'\"")
    sys.exit("no GITHUB_TOKEN/GH_TOKEN/GITHUB_PAT in ~/github.env")


def get(url, tok):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "pack-issue-watch",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # Never include the request headers in the message.
        print(f"!! {url.split('/repos/')[-1]}: HTTP {e.code}", flush=True)
        return []
    except Exception as e:                       # network blip; stay alive
        print(f"!! {url.split('/repos/')[-1]}: {type(e).__name__}", flush=True)
        return []


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, STATE)


def main():
    baseline = "--baseline" in sys.argv
    show_all = "--all" in sys.argv
    tok = token()
    state = {} if show_all else load_state()
    new_state = dict(state)
    found = 0

    for repo in REPOS:
        short = repo.split("/")[1]
        # state=all so a closed-then-commented issue still reports.
        items = get(f"{API}/repos/{repo}/issues"
                    "?state=all&sort=updated&direction=desc&per_page=50", tok)
        for it in items:
            num = it.get("number")
            if num is None:
                continue
            key = f"{repo}#{num}"
            stamp = it.get("updated_at", "")
            if not show_all and state.get(key) == stamp:
                continue                          # unchanged since last look
            new_state[key] = stamp
            if baseline:
                continue
            kind = "PR " if it.get("pull_request") else "issue"
            seen_before = key in state
            verb = "updated" if seen_before else "NEW"
            who = (it.get("user") or {}).get("login", "?")
            title = (it.get("title") or "").replace("\n", " ")[:88]
            print(f"[{short}] {verb} {kind} #{num} ({it.get('state')}, "
                  f"{it.get('comments', 0)} comments) by {who}: {title} "
                  f"-> {it.get('html_url')}", flush=True)
            found += 1

    save_state(new_state)
    if baseline:
        print(f"baseline recorded: {len(new_state)} items across "
              f"{len(REPOS)} repos", flush=True)
    return 0 if not found else 0


if __name__ == "__main__":
    sys.exit(main())

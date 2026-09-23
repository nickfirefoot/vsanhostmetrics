#!/usr/bin/env python3
"""Scan every blob in every commit for credentials.

    python3 tools/scan_history.py

Exits non-zero if anything unrecognised is found, so it can gate a publish.

Scanning the working tree is not enough: git keeps deleted content reachable,
so a credential committed once and removed later is still in the history and
still published. This walks `git cat-file --batch-all-objects`, which includes
blobs no branch points at any more.

Known-benign matches are listed explicitly rather than by loosening the
patterns -- a pattern loose enough to miss the placeholders would also miss a
real token shaped like them.
"""
import re
import subprocess
import sys

PATTERNS = {
    "password literal": re.compile(rb"(?i)password\s*[:=]\s*['\"][^'\"]{4,}"),
    "auth_token": re.compile(rb"(?i)auth_token\s*[:=]\s*['\"]?[A-Za-z0-9-]{10,}"),
    "authorization header": re.compile(rb"(?i)authorization:\s*bearer\s+\S{10,}"),
    "private key": re.compile(rb"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"),
    "harbor robot": re.compile(rb"robot\$[A-Za-z0-9._-]+\+[A-Za-z0-9._-]+"),
    "vmware-style password": re.compile(rb"VMware\d{2,}[!@#$]"),
}

# Documentation placeholders and deliberate negative-test values.
ALLOWED = {
    b"robot$project+name",
    b"Authorization: Bearer definitely-not-a-real-token",
    b"Authorization: Bearer $TOK",
}


def main() -> int:
    listing = subprocess.run(
        ["git", "cat-file", "--batch-check", "--batch-all-objects"],
        capture_output=True, text=True, check=True).stdout
    blobs = [ln.split()[0] for ln in listing.splitlines()
             if len(ln.split()) > 1 and ln.split()[1] == "blob"]

    findings = []
    for sha in blobs:
        data = subprocess.run(["git", "cat-file", "blob", sha],
                              capture_output=True).stdout
        for name, rx in PATTERNS.items():
            for match in rx.findall(data):
                text = match if isinstance(match, bytes) else match[0]
                if any(a in text or text in a for a in ALLOWED):
                    continue
                findings.append((sha[:8], name, text[:60]))

    print(f"  scanned {len(blobs)} blobs across "
          f"{len(subprocess.run(['git','rev-list','--all'],capture_output=True,text=True).stdout.split())} commits")
    if not findings:
        print("  CLEAN -- no unrecognised credential patterns")
        return 0
    print(f"  {len(findings)} finding(s):")
    for sha, name, text in findings:
        print(f"    blob {sha}  {name}: {text!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

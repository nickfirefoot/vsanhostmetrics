#!/usr/bin/env python3
"""Run `mp-build` from a script, by giving it a pseudo-terminal.

    python3 tools/mp_build_pty.py ghcr.io/nickfirefoot/vsanhostmetrics

`mp-build` draws progress spinners, so it probes the terminal and blocks when
stdin is not one. Called from a script it prints a single line --

    Warning: Input is not a terminal (fd=0).

-- and then hangs until something kills it. Two builds were lost to this, one
of them after fifteen minutes of waiting, with an empty log either time because
the output was also sitting in a pipe buffer.

Allocating a pty makes it behave. The escape sequences the spinners emit are
stripped from the captured log so the result is readable, and the exit status
is the child's rather than this wrapper's.

The registry argument must be the FULL repository path including the image
name. Passing only the host produces a 400 on the blob HEAD request, because
`config.json` has `container_repository: null` and there is nothing to join it
to.
"""
import os
import pty
import re
import select
import sys
import time

ANSI = re.compile(rb'\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\r')
TIMEOUT = 1800


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("usage: mp_build_pty.py <registry>/<repository> [project_dir]")
    repo = sys.argv[1]
    project = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/vsan-host-metrics")
    mp = os.path.expanduser("~/.mp/bin/mp-build")

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(project)
        os.execv(mp, ["mp-build", "-r", repo])

    captured = bytearray()
    start = time.time()
    status = None
    while time.time() - start < TIMEOUT:
        ready, _, _ = select.select([fd], [], [], 2)
        if ready:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            captured += data
        done, st = os.waitpid(pid, os.WNOHANG)
        if done:
            status = st
            break
    if status is None:
        os.kill(pid, 9)
        _, status = os.waitpid(pid, 0)

    text = ANSI.sub(b"", bytes(captured)).decode("utf-8", "replace")
    # the spinners rewrite one line many times; keep the distinct lines only
    seen, lines = set(), []
    for line in (ln.strip() for ln in text.splitlines()):
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
    print("\n".join(lines))
    code = os.waitstatus_to_exitcode(status)
    print(f"\nmp-build exit status: {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())

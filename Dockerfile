# The base-adapter image is built automatically by the integration SDK.
FROM base-adapter:python-1.2.0

# OCI labels. image.source is the one that matters: GHCR uses it to link the
# published package to its repository, so the package page shows the source and
# inherits the repo's visibility rather than being an orphan.
LABEL org.opencontainers.image.source="https://github.com/nickfirefoot/vsanhostmetrics" \
      org.opencontainers.image.description="Long-term vSAN telemetry for VCF Operations, collected from the vSAN Performance Service via vCenter" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.title="vSAN Host Metrics"

# Debian security updates on top of whatever the SDK's base image was built
# with. The base is python:3.11-slim-bookworm and the SDK upgrades at ITS build
# time, but that was some months ago -- openssl and libssl3 have had security
# releases since (3.0.20 -> 3.0.22), and a scanner flags them on every build.
#
# Root is needed for apt and the base image runs as aria-ops-adapter-user, so
# this switches and switches back. Nothing below this line runs as root.
#
# perl-base is then PURGED. It is Debian Essential, so this needs forcing, and
# that warrants justifying:
#
#   - nothing installed depends on it -- `apt-cache rdepends --installed
#     perl-base` returns an empty list
#   - the adapter is Python; the only perl consumers in the image are dpkg and
#     debconf helper scripts, which matter when managing packages, not at run
#     time. This runs AFTER the upgrade above for that reason
#   - it is 19 of the image's scanner findings including three of its five
#     criticals, all of them unfixed upstream and so otherwise permanent
#   - verified: the adapter imports and the swagger server starts without it
#
# The same test was applied to every other vulnerable OS package: each one
# purged here has NO installed reverse-dependency, and the adapter and the
# swagger server were verified running without it. Together they account for
# 43 scanner findings and one of the image's two criticals, none of which have
# a published fix, so they would otherwise be permanent.
#
# The trade:
#   - apt and dpkg are no longer reliable inside a running container
#   - `import sqlite3` raises ImportError. Nothing in the adapter or the SDK
#     library uses it; a future dependency that does would fail at collection
#     time, and this comment is the explanation for that
#   - no mount, login, or curses tooling. Nothing shipped here needs them
#
# NOT removed, deliberately: the remaining util-linux siblings (libblkid1,
# libmount1, libsmartcols1, libuuid1, util-linux, util-linux-extra) have real
# dependents, and their 30 findings are only 5 unique CVEs counted six times
# over because one source package ships six binaries. zlib1g cannot go --
# Python links it -- and its CVE-2023-45853 is marked will-not-fix by Debian,
# which is the one critical that remains.
USER 0
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get clean \
 && dpkg --purge --force-remove-essential --force-depends \
      perl-base libsqlite3-0 mount bsdutils libncursesw6 ncurses-bin \
      ncurses-base login \
 && rm -rf /usr/share/perl /usr/share/doc/perl* /var/lib/apt/lists/*
USER aria-ops-adapter-user

COPY commands.cfg .
COPY adapter_requirements.txt .
RUN pip3 install -r adapter_requirements.txt --upgrade
COPY app app

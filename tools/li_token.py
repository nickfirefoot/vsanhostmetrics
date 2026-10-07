#!/usr/bin/env python3
"""Exchange a VCF Operations token for a Log Management (ops-li) JWT.

    set -a; . ~/ops.env; set +a
    python3 tools/li_token.py            # prints the JWT
    python3 tools/li_token.py --claims   # prints its claims instead

Documented at:
  https://knowledge.broadcom.com/external/article/450054/

Two steps, both against VCF Operations itself -- NOT against the Logs
appliance, and NOT via Identity Broker:

    POST /suite-api/api/auth/token/acquire     -> OpsToken
    POST /suite-api/api/auth/token/exchange    -> {"jwtToken": "..."}
         body {"serviceKeys": ["ops-li"]}

The JWT is RS256, issued by vcf_ops, and carries view-scoped log permissions
(infra_ops.log.view_logs and friends). It expires in about 35 minutes, so
acquire one per run rather than caching it anywhere.

WHAT THIS DOES NOT YET DO: find the query endpoint. The standalone Logs
appliance API on :9543 REJECTS this token --

    "The parsed JWT indicates it was signed with the 'RS256' signature
     algorithm, but the provided javax.crypto.spec.SecretKeySpec key may not
     be used to verify RS256 signatures."

-- because that endpoint verifies with an HMAC secret and is not configured to
trust the Operations issuer. So either the query API lives same-origin on
Operations and has not been located, or the Logs-to-Operations SSO trust is
not configured in this environment. Not yet established which.

Note /api/v2/events on :9543 is the INGEST endpoint -- it deserialises an array
of JsonApiEvent. It is not the query path and should not be poked at.
"""
import json
import os
import sys
import base64

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_jwt(host: str, user: str, password: str, auth_source: str = "LOCAL") -> str:
    s = requests.Session()
    s.verify = False
    r = s.post(f"https://{host}/suite-api/api/auth/token/acquire",
               json={"username": user, "password": password,
                     "authSource": auth_source}, timeout=30)
    r.raise_for_status()
    ops = r.json()["token"]
    r = s.post(f"https://{host}/suite-api/api/auth/token/exchange",
               headers={"Authorization": f"vRealizeOpsToken {ops}",
                        "Accept": "application/json"},
               json={"serviceKeys": ["ops-li"]}, timeout=30)
    r.raise_for_status()
    jwt = r.json().get("jwtToken")
    if not jwt:
        raise SystemExit(f"no jwtToken in exchange response: {r.text[:200]}")
    return jwt


def claims(jwt: str) -> dict:
    p = jwt.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))


def main() -> int:
    try:
        host = os.environ["OPS_HOST"]
        user = os.environ["OPS_USER"]
        pw = os.environ["OPS_PASS"]
    except KeyError as missing:
        sys.exit(f"{missing} not set -- source ~/ops.env first")
    jwt = get_jwt(host, user, pw)
    if "--claims" in sys.argv:
        c = claims(jwt)
        perms = (c.get("authorization_details") or [{}])[0].get("permissions", [])
        print(f"subject    : {c.get('prn')}")
        print(f"issuer     : {c.get('iss')}")
        print(f"valid for  : {c.get('exp', 0) - c.get('iat', 0)}s")
        print(f"permissions: {len(perms)}")
        for p in sorted(perms):
            print(f"   {p}")
    else:
        print(jwt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

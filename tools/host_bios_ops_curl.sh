#!/bin/sh
# Host BIOS version from VCF Operations.
#   set -a; . ~/ops.env; set +a;  sh tools/host_bios_ops_curl.sh
#
# Operations already collects this on every VMWARE/HostSystem object with no
# configuration, whether or not the host runs vSAN. It is a PROPERTY, under
# /properties, not a metric under /stats -- which is why searching the 864
# host stat keys for "bios" finds nothing.
#
# It gives biosVersion and not releaseDate. For the date, which is the field
# that actually tells you whether a BIOS is stale, use host_bios_curl.sh
# against vCenter instead.
set -e
: "${OPS_HOST:?set OPS_HOST}" "${OPS_USER:?set OPS_USER}" "${OPS_PASS:?set OPS_PASS}"

TOKEN=$(curl -sk -X POST "https://${OPS_HOST}/suite-api/api/auth/token/acquire" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d "{\"username\":\"${OPS_USER}\",\"password\":\"${OPS_PASS}\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
AUTH="Authorization: vRealizeOpsToken ${TOKEN}"

curl -sk -H "$AUTH" -H 'Accept: application/json' \
  "https://${OPS_HOST}/suite-api/api/resources?adapterKind=VMWARE&resourceKind=HostSystem&pageSize=500" \
| python3 -c 'import json,sys; [print(r["identifier"]) for r in json.load(sys.stdin)["resourceList"]]' \
| while read -r ID; do
    curl -sk -H "$AUTH" -H 'Accept: application/json' \
      "https://${OPS_HOST}/suite-api/api/resources/${ID}/properties" \
    | python3 -c '
import json, sys
p = {x["name"]: x.get("value") for x in json.load(sys.stdin).get("property", [])}
print("%-26s bios=%-10s vendor=%-26s model=%s" % (
    p.get("config|name", "?"), p.get("hardware|biosVersion"),
    p.get("hardware|vendor"), p.get("hardware|vendorModel")))'
  done

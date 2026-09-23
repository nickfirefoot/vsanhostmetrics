# Driving the vSAN Performance Service over plain HTTP

Verified 2026-09-23 against `vcenter.example.com` with nothing but `curl` -- no
pyVmomi, no vendored bindings. This matters because it is what a no-code tool
such as Management Pack Builder would have to do.

## The two calls

**1. Authenticate.** `POST /sdk`, `Content-Type: text/xml; charset=utf-8`,
`SOAPAction: urn:vim25/8.0`, body `01-login.xml`. Returns 200 and sets a
`vmware_soap_session` cookie. **Basic auth does not work** -- the service
answers `NotAuthenticatedFault` regardless of credentials. The cookie is the
only accepted proof of session.

**2. Query.** `POST /vsanHealth`, same content type, `SOAPAction: urn:vsan/8.0`,
carrying that cookie. Body `02-query-node-information.xml`. Returns 200 with
real data.

```sh
curl -sk -X POST "https://$VC/sdk" -c cookie \
  -H 'Content-Type: text/xml; charset=utf-8' -H 'SOAPAction: urn:vim25/8.0' \
  --data-binary @01-login.xml

curl -sk -X POST "https://$VC/vsanHealth" -b cookie \
  -H 'Content-Type: text/xml; charset=utf-8' -H 'SOAPAction: urn:vsan/8.0' \
  --data-binary @02-query-node-information.xml
```

## Why `GET /vsanHealth` returns 501

The endpoint accepts `POST` with a SOAP envelope only. A `GET` -- which is what
a REST client issues by default -- returns `501 Not Implemented`, which looks
like "unsupported endpoint" but actually means "wrong verb".

## What a no-code tool still has to solve

Reaching the API is necessary, not sufficient. For a tool to replace the
Python collector it must also:

1. **Carry the session.** Perform the login call, capture `vmware_soap_session`
   from the response, and attach it to every subsequent request. A single
   static credential is not enough.
2. **Template the request body.** `VsanPerfQueryPerf` takes `startTime` and
   `endTime`, which change every collection cycle, and an `entityRefId` per
   entity type -- 31 of them.
3. ~~**Parse comma-separated series inside XML.**~~ **Solved.** The response
   holds a CSV string of samples in `<values>` -- but only because the query
   window spans several 5-minute buckets. perfsvc buckets on 5-minute
   boundaries, so **a window shorter than 5 minutes returns exactly one sample
   per metric**. Measured 2026-09-23 against `vsan-pnic-net`:

   | Window | Metrics | Samples each |
   |---|---|---|
   | 30 min | 455 | 7 |
   | 6 min | 455 | 2 |
   | 4 min | 455 | **1** |
   | 1 min | 455 | **1** |

   With a 4-minute window `<values>` is a single number and no parsing is
   needed -- a plain field mapping works. This is the single most important
   detail for driving the API from a no-code tool.
4. **Resolve identity.** Objects come back as UUIDs. Friendly names require
   joining three further calls -- `VsanPerfQueryNodeInformation`, a VM
   `ContainerView`, and `QueryVsanManagedDisks`.

Item 3 is solved by the short-window trick above. Item 1 is plausible: MPB
exposes a "Use Session Authentication" toggle for exactly this, and its stack
trace shows Apache HttpClient 5, which keeps a per-client cookie store, so the
`vmware_soap_session` cookie may propagate without any extraction at all. Note
the cookie value is **not** the `<key>` in the login response body -- tested,
and using the body key as the cookie faults `NotAuthenticated` -- so extraction
from the body would not work; the cookie must be carried.

Item 2 needs MPB to template a timestamp into the request body, and item 4
needs multi-request joins, which is where it may still stop.

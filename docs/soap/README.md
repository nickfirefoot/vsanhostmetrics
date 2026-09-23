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
3. **Parse comma-separated series inside XML.** The response does not return
   one value per metric. It returns a `<values>` element holding a CSV string
   of samples, e.g. `312,271,274,333,265,307`, which must be split and the
   last non-empty sample taken. This is the step most field-mapping UIs cannot
   express.
4. **Resolve identity.** Objects come back as UUIDs. Friendly names require
   joining three further calls -- `VsanPerfQueryNodeInformation`, a VM
   `ContainerView`, and `QueryVsanManagedDisks`.

Items 1 and 2 are plausible in a capable tool. Item 3 is the likely wall.

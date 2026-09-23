"""READ-ONLY: which perfsvc entity types actually return data, before vs after
verbose/diagnostic were disabled at 2026-09-23 02:41:45 UTC."""
import ssl, sys, json, datetime
from pyVmomi import VmomiSupport
class _N:
    def Add(self,*a,**k): pass
for n in ('stableVersions','publicVersions'):
    if not hasattr(VmomiSupport,n): setattr(VmomiSupport,n,_N())
sys.path.insert(0,'/tmp')
import vsanmgmtObjects, vsanapiutils
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

env={}
for l in open('/home/vsanmp/vcenter.env'):
    if '=' in l: k,v=l.strip().split('=',1); env[k]=v.strip().strip("'")
ctx=ssl._create_unverified_context()
si=SmartConnect(host=env['VC_HOST'],user=env['VC_USER'],pwd=env['VC_PASS'],sslContext=ctx)
content=si.RetrieveContent(); cl=[]
def walk(f):
    for c in getattr(f,'childEntity',[]):
        if isinstance(c,vim.ClusterComputeResource): cl.append(c)
        elif hasattr(c,'childEntity'): walk(c)
for dc in content.rootFolder.childEntity:
    if isinstance(dc,vim.Datacenter): walk(dc.hostFolder)
cluster=cl[0]
vcMos=vsanapiutils.GetVsanVcMos(si._stub,context=ctx,
       version=vsanapiutils.GetLatestVmodlVersion(env['VC_HOST']))
perf=vcMos['vsan-performance-manager']
ents=[getattr(e,'name',None) for e in perf.VsanPerfGetSupportedEntityTypes()]
ents=[e for e in ents if e]

CUT=datetime.datetime(2026,9,23,2,41,45,tzinfo=datetime.timezone.utc)
WINDOWS={'BEFORE': (CUT-datetime.timedelta(minutes=40), CUT-datetime.timedelta(minutes=5)),
         'AFTER' : (CUT+datetime.timedelta(minutes=2),  datetime.datetime.now(datetime.timezone.utc))}

res={}
for label,(t0,t1) in WINDOWS.items():
    have=set()
    for ent in ents:
        spec=vim.cluster.VsanPerfQuerySpec(entityRefId=f"{ent}:*", startTime=t0, endTime=t1)
        try:
            out=perf.VsanPerfQueryPerf([spec], cluster)
            n=sum(len(getattr(v,'value',[]) or []) for e in (out or []) for v in (getattr(e,'value',[]) or []))
            if out and n: have.add(ent)
        except Exception:
            pass
    res[label]=have
    print(f"  {label:6} window {t0:%H:%M}-{t1:%H:%M} UTC : {len(have)}/{len(ents)} entity types returned data", flush=True)

lost=sorted(res['BEFORE']-res['AFTER']); gained=sorted(res['AFTER']-res['BEFORE'])
print()
print(f"  LOST after disabling verbose+diagnostic: {len(lost)}")
for e in lost: print("    -", e)
print(f"  GAINED: {len(gained)}")
for e in gained: print("    +", e)
json.dump({k:sorted(v) for k,v in res.items()}, open('/tmp/vsan_data_windows.json','w'), indent=1)
Disconnect(si)

"""Ingestion benchmark against running local API; adds labelled synthetic events."""
import json,time,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
import httpx
root=Path(__file__).resolve().parents[1]
environment=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line)
with httpx.Client(base_url='http://127.0.0.1:8001',timeout=90) as client:
    login=client.post('/auth/login',json={'email':'engineer@local.demo','password':environment['DEMO_PASSWORD']});login.raise_for_status();client.headers['Authorization']='Bearer '+login.json()['access_token']
    origin=datetime(2026,10,1,tzinfo=timezone.utc)
    unique=str(time.time_ns())
    lines=[json.dumps({'timestamp':(origin+timedelta(milliseconds=i)).isoformat(),'service':'checkout-api','level':'INFO','message':'benchmark-'+unique+' request completed','trace_id':'benchmark-'+unique+'-'+str(i),'attributes':{'http_status':200,'latency_ms':100}}) for i in range(10000)]
    start=time.perf_counter();r=client.post('/logs/paste',json={'text':'\n'.join(lines),'service':'checkout-api'});r.raise_for_status();seconds=time.perf_counter()-start
    result={'lines':10000,'roundtrip_seconds':round(seconds,3),'target_seconds':30,'passed':seconds<30,'ingestion':r.json()}
    (root/'docs'/'ingestion-benchmark.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

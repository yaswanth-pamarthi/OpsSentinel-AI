import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import select
from app.core import ROOT,Session,seed_users,uid
from app.models import Service,Rule,LogSource
from app.detection import DEFAULT_RULES
from app.knowledge import add_knowledge
from generate_logs import generate,SCENARIOS

BOOKS={
 'checkout-api':('Connection pool exhaustion', '''# Symptoms
Database connection timeout, HTTP 500 request failures and rising latency.
# Diagnosis
Read-only diagnostic: SELECT count(*) FROM pg_stat_activity; Inspect configured pool utilization and session metrics.
# Containment
Reduce incoming traffic using the demo traffic toggle. Risk: reduced throughput.
# Permanent fix
Correct connection-pool sizing and redeploy reviewed configuration in the simulator.
# Rollback
Restore the previous pool configuration if validation fails.
# Validation
Confirm HTTP 5xx below 1% for 10 minutes and healthy recovery events. The MVP records synthetic recovery evidence.
'''),
 'payment-api':('Payment dependency latency','''# Symptoms
Payment upstream response slow and latency_ms above 2000.
# Diagnosis
Inspect read-only upstream latency and connection metrics; compare traced requests.
# Containment
Enable the simulated graceful degradation toggle.
# Permanent fix
Review upstream timeout configuration and retry budgets.
# Rollback
Restore previous timeout configuration.
# Validation
Confirm healthy payment responses and sustained latency recovery.
''')}

def seed():
    with Session() as db:
        seed_users(db,['engineer','commander','viewer'])
        for name,deps in [('orders-db',[]),('checkout-api',['orders-db']),('payment-api',[])]:
            service=db.scalar(select(Service).where(Service.name==name))
            if not service:
                service=Service(id=uid(),name=name,owner='Demo SRE Team',dependencies_json=deps);db.add(service);db.flush()
                for format in ['json','key_value','text']:db.add(LogSource(service_id=service.id,name=name+'-'+format,type=format))
                db.commit()
            if name in BOOKS:
                title,content=BOOKS[name];path=ROOT/'sample-data'/'runbooks'/(name+'.md');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
                add_knowledge(db,{'service_id':service.id,'title':title,'version':'1.0','environment':'demo','content':content,'status':'current'})
        # Extra focused knowledge for security and restart scenarios.
        checkout=db.scalar(select(Service).where(Service.name=='checkout-api'))
        for title,symptom,diagnosis,fix in [
            ('Authentication failure response','Repeated failed login from a single IP.','Inspect identity provider audit trail and failed-login source IP.','Review rate limiting and simulated access policies.'),
            ('Deployment restart loop','Repeated host service restart after deployment.','Inspect read-only deployment logs and recent configuration diff.','Restore reviewed stable deployment configuration.'),
            ('Critical HTTP 500 response','Critical HTTP 500 service unavailable and error rate critical; sustained 5XX requests.','Inspect read-only service error groups, dependency health and recent changes.','Apply a reviewed simulated service configuration correction after confirming the failing dependency.')]:
            content=f'# Symptoms\n{symptom}\n# Diagnosis\n{diagnosis}\n# Containment\nReduce simulated traffic.\n# Permanent fix\n{fix}\n# Rollback\nRestore previous reviewed configuration.\n# Validation\nConfirm healthy recovery events for ten minutes.'
            path=ROOT/'sample-data'/'runbooks'/(title.lower().replace(' ','-')+'.md');path.write_text(content)
            add_knowledge(db,{'service_id':checkout.id,'title':title,'version':'1.0','environment':'demo','content':content,'status':'current'})
        for name,type,threshold,window,severity in DEFAULT_RULES:
            if not db.scalar(select(Rule).where(Rule.name==name)):db.add(Rule(name=name,query_type=type,threshold=threshold,window_seconds=window,severity=severity))
        db.commit()
    directory=ROOT/'sample-data'/'logs';directory.mkdir(parents=True,exist_ok=True)
    for scenario in SCENARIOS:
        rows=generate(scenario);(directory/(scenario+'.jsonl')).write_text('\n'.join(json.dumps(e) for e in rows)+'\n',encoding='utf-8')
    (directory/'formats.log').write_text('2026-10-14T09:00:00Z INFO checkout-api request completed\n'+'timestamp=2026-10-14T09:00:05Z level=INFO service=checkout-api message="request completed" http_status=200 latency_ms=100\n'+'{"timestamp":"2026-10-14T09:00:10Z","level":"INFO","service":"checkout-api","message":"request completed"}\n'+'malformed line retained for investigation\n')
    print('Seeded service catalog, six rules, five runbooks and five deterministic scenarios')
if __name__=='__main__':seed()

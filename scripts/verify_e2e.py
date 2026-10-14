"""Execute real local APIs and AI workflows. Never prints local secrets."""
import argparse,json,sys,time
from pathlib import Path
from datetime import datetime,timedelta,timezone
import httpx
ROOT=Path(__file__).resolve().parents[2]
PROJECTS={'procureMind':ROOT/'procureMind','opsSentinel':ROOT/'opsSentinel'}
_this=Path(__file__).resolve().parents[1]
PROJECTS['procureMind' if (_this/'backend/app/scoring.py').exists() else 'opsSentinel']=_this
def env(project):
    return dict(line.split('=',1) for line in (PROJECTS[project]/'.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
def account(client,project,role):
    data=client.post('/auth/login',json={'email':role+'@local.demo','password':env(project)['DEMO_PASSWORD']});data.raise_for_status()
    client.headers['Authorization']='Bearer '+data.json()['access_token']
def call(c,method,path,**kwargs):
    r=c.request(method,path,**kwargs)
    if r.is_error:raise RuntimeError(f'{method} {path} => {r.status_code}: {r.text[:700]}')
    return r.json()
def wait(c,id,expected,timeout=600):
    start=time.monotonic();seen=None
    while time.monotonic()-start<timeout:
        result=call(c,'GET','/analysis-runs/'+id)
        if result['status']!=seen:
            print('Run status:',result['status'],flush=True);seen=result['status']
        if result['status']==expected:return result
        if result['status'] in ('FAILED','NEEDS_INPUT'):raise RuntimeError(result.get('error'))
        time.sleep(2)
    raise TimeoutError('Workflow timeout: '+str(result))
def procure(decisions,pause_before_decision=False):
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=180) as c:
        account(c,'procureMind','analyst');rfqs=call(c,'GET','/rfqs');seed=next(r for r in rfqs if r['number']=='RFQ-DEMO-100')
        detail=call(c,'GET','/rfqs/'+seed['id'])
        existing=PROJECTS['procureMind']/'docs'/'execution-results.json'
        results=json.loads(existing.read_text()) if existing.exists() else []
        for index,decision in enumerate(decisions):
            account(c,'procureMind','analyst')
            unique='RFQ-VERIFY-'+decision.upper()+'-'+str(int(time.time()))
            rfq=call(c,'POST','/rfqs',json={'number':unique,'title':'Verification: 100 office laptops / '+decision,'budget':7000000,'currency':'INR','due_date':'2026-12-01','weights_json':seed['weights_json'],'items':[{'description':'Business laptop 16GB RAM / 512GB SSD','quantity':100,'target_price':58000}]})
            for s in detail['submissions']:
                sub=call(c,'POST','/rfqs/'+rfq['id']+'/submissions',json={'vendor_id':s['vendor_id']})
                for kind,folder in [('quotation','quotations'),('contract','contracts')]:
                    name=s['vendor'].lower()+'.pdf';path=PROJECTS['procureMind']/'sample-data'/folder/name
                    with path.open('rb') as file:d=call(c,'POST','/submissions/'+sub['id']+'/documents',data={'type':kind},files={'file':(name,file,'application/pdf')})
                    processed=call(c,'POST','/documents/'+d['id']+'/process',json={});assert processed['parse_status']=='PROCESSED'
                    again=call(c,'POST','/documents/'+d['id']+'/process',json={});assert processed['metrics_json']==again['metrics_json']
            started=time.monotonic();run=call(c,'POST','/rfqs/'+rfq['id']+'/analysis-runs',json={});run=wait(c,run['id'],'WAITING_APPROVAL')
            analysis_seconds=time.monotonic()-started
            comparison=call(c,'GET','/rfqs/'+rfq['id']+'/comparison');rec=comparison['recommendation'];scores=comparison['scores']
            assert len(scores)==3 and all(s['breakdown'] for s in scores)
            if pause_before_decision:
                payload={'rfq_id':rfq['id'],'run_id':run['id'],'recommendation_id':rec['id'],'status_before_restart':run['status']}
                (PROJECTS['procureMind']/'docs'/'checkpoint-restart-results.json').write_text(json.dumps(payload,indent=2));print('Procurement checkpoint saved for API restart test',flush=True);return payload
            denied=c.post('/recommendations/'+rec['id']+'/decision',json={'decision':'approve','reason':'Analyst permission test'});assert denied.status_code==403
            account(c,'procureMind','manager')
            selected=next(s['vendor_id'] for s in scores if s['eligible'] and s['vendor_id']!=rec['preferred_vendor_id']) if decision=='override' else None
            outcome=call(c,'POST','/recommendations/'+rec['id']+'/decision',json={'decision':decision,'reason':'Verified commercial evidence and recorded demo manager decision.','vendor_id':selected})
            completed=wait(c,run['id'],'COMPLETED')
            assert len(completed['outputs'])==7
            assert outcome['preferred_vendor_id']==rec['preferred_vendor_id']
            if decision=='override':assert outcome['final_vendor_id']==selected
            report=call(c,'POST','/rfqs/'+rfq['id']+'/reports',json={})
            assert report['id']==call(c,'POST','/rfqs/'+rfq['id']+'/reports',json={})['id']
            for format in ['pdf','docx']:
                r=c.get('/reports/'+report['id']+'/'+format);r.raise_for_status();assert len(r.content)>1000
            result={'decision':decision,'rfq_id':rfq['id'],'run_id':run['id'],'analysis_seconds':round(analysis_seconds,2),'model':completed['model'],'agents':len(completed['outputs']),'status':outcome['status'],'recommended_vendor':next(s['vendor'] for s in scores if s['vendor_id']==rec['preferred_vendor_id']),'scores':[{k:s[k] for k in ['vendor','score','eligible']} for s in scores],'report_id':report['id']}
            results=[r for r in results if r['decision']!=decision]+[result];print('ProcureMind verified:',json.dumps(result),flush=True)
            target=PROJECTS['procureMind']/'docs'/'execution-results.json';target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(results,indent=2))
        return results
def ops(scenarios,pause_before_resolution=False):
    sys.path.insert(0,str(PROJECTS['opsSentinel']/'scripts'));from generate_logs import generate
    with httpx.Client(base_url='http://127.0.0.1:8001',timeout=180) as c:
        existing=PROJECTS['opsSentinel']/'docs'/'execution-results.json'
        results=json.loads(existing.read_text()) if existing.exists() else []
        for index,scenario in enumerate(scenarios):
            account(c,'opsSentinel','engineer')
            # Distinct repeatable scenario windows prevent accidental cross-scenario evidence.
            previous=call(c,'GET','/logs/search',params={'limit':1})['events']
            origin=datetime.fromisoformat(previous[0]['timestamp'])+timedelta(minutes=30) if previous else datetime(2026,10,15,10,tzinfo=timezone.utc)
            rows=generate(scenario,start=origin)
            first=call(c,'POST','/logs/events',json={'events':rows,'service':'checkout-api'});second=call(c,'POST','/logs/events',json={'events':rows,'service':'checkout-api'})
            assert first['inserted']==len(rows) and second['inserted']==0
            payload={'start':origin.isoformat(),'end':(origin+timedelta(minutes=21)).isoformat()}
            matches=call(c,'POST','/rules/evaluate',json=payload);again=call(c,'POST','/rules/evaluate',json=payload);assert again['count']==0
            expected={'db-pool-exhaustion':'DB_CONNECTION_FAILURE','auth-brute-force':'AUTH_FAILURE_BURST','payment-api-latency':'HIGH_LATENCY','deployment-restart-loop':'RESTART_LOOP','critical-error-rate':'ERROR_RATE_CRITICAL'}[scenario]
            incident_id=next(i['incident_id'] for i in matches['created'] if i['rule']==expected and i['service']==('payment-api' if scenario=='payment-api-latency' else 'checkout-api'))
            incident=call(c,'GET','/incidents/'+incident_id)
            # Reject an attempt to close before approved, validated recovery.
            account(c,'opsSentinel','commander');denied=c.patch('/incidents/'+incident_id+'/status',json={'status':'CLOSED','reason':'Premature closure test'});assert denied.status_code==409
            account(c,'opsSentinel','engineer');started=time.monotonic();run=call(c,'POST','/incidents/'+incident_id+'/analysis-runs',json={});run=wait(c,run['id'],'WAITING_APPROVAL')
            seconds=time.monotonic()-started;incident=call(c,'GET','/incidents/'+incident_id);proposal=next(p for p in incident['proposals'] if p['run_id']==run['id'])
            assert not proposal['executed'] and proposal['payload_json']['requires_approval']
            assert all(proposal['payload_json'][section] for section in ['diagnostics','immediate_containment','permanent_fix','rollback','validation'])
            assert incident['hypotheses'][0]['evidence_json']['supporting_event_ids']
            valid_ids={e['event_id'] for e in incident['evidence']}
            for output in run['outputs']:
                if output['agent_name']=='Root Cause':
                    assert output['payload_json']['confirmed_facts']
                    assert all(set(f['event_ids'])<=valid_ids for f in output['payload_json']['confirmed_facts'])
            call(c,'POST','/proposals/'+proposal['id']+'/decision',json={'decision':'approve','reason':'Reviewed read-only diagnostics, risk and rollback for this simulated incident.'})
            wait(c,run['id'],'WAITING_RESOLUTION')
            events=call(c,'GET','/logs/search',params={'service_id':incident['service_id'],'q':'recovery','start':origin.isoformat(),'end':(origin+timedelta(minutes=21)).isoformat(),'limit':500})['events']
            assert events
            if pause_before_resolution:
                payload={'incident_id':incident_id,'run_id':run['id'],'proposal_id':proposal['id'],'validation_event_ids':[e['id'] for e in events],'status_before_restart':'WAITING_RESOLUTION'}
                (PROJECTS['opsSentinel']/'docs'/'checkpoint-restart-results.json').write_text(json.dumps(payload,indent=2));print('Operations resolution checkpoint saved for API restart test',flush=True);return payload
            invalid=c.post('/incidents/'+incident_id+'/resolve',json={'actual_action':'Premature simulated correction record.','validation_event_ids':[events[0]['id']],'validation_notes':'One recovery event is insufficient for sustained validation.','simulated':True})
            assert invalid.status_code==422
            resolved=call(c,'POST','/incidents/'+incident_id+'/resolve',json={'actual_action':'Simulated configuration correction according to reviewed runbook.','validation_event_ids':[e['id'] for e in events],'validation_notes':'Post-detection healthy recovery events verified for the affected service.','simulated':True})
            assert resolved['resolution_json']['validation_metrics']['window_seconds']>=600
            final=wait(c,run['id'],'COMPLETED');assert len(final['outputs'])==7
            account(c,'opsSentinel','commander');closed=call(c,'PATCH','/incidents/'+incident_id+'/status',json={'status':'CLOSED','reason':'Commander verified simulated recovery evidence and actual resolution record.'});assert closed['status']=='CLOSED'
            report=call(c,'POST','/incidents/'+incident_id+'/report',json={});assert report['id']==call(c,'POST','/incidents/'+incident_id+'/report',json={})['id']
            for format in ['pdf','docx']:r=c.get('/reports/'+report['id']+'/'+format);r.raise_for_status();assert len(r.content)>1000
            result={'scenario':scenario,'incident_id':incident_id,'run_id':run['id'],'analysis_seconds':round(seconds,2),'agents':len(final['outputs']),'status':'CLOSED','model':final['model'],'alerts':matches['count'],'duplicate_alerts':again['count'],'parser':first,'validation_metrics':resolved['resolution_json']['validation_metrics'],'report_id':report['id']}
            results=[r for r in results if r['scenario']!=scenario]+[result];print('OpsSentinel verified:',json.dumps(result),flush=True)
            target=PROJECTS['opsSentinel']/'docs'/'execution-results.json';target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(results,indent=2))
        return results
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('project',choices=['procure','ops']);parser.add_argument('--quick',action='store_true');a=parser.parse_args()
    if a.project=='procure':procure(['approve'] if a.quick else ['approve','override','reject'])
    else:ops(['db-pool-exhaustion'] if a.quick else ['db-pool-exhaustion','auth-brute-force','payment-api-latency'])

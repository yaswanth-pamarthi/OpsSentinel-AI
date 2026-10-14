import argparse,json
from datetime import datetime,timedelta,timezone
from pathlib import Path

SCENARIOS=['db-pool-exhaustion','auth-brute-force','payment-api-latency','deployment-restart-loop','critical-error-rate']
def generate(scenario='db-pool-exhaustion',minutes=20,start=None):
    origin=start or datetime(2026,10,14,10,0,tzinfo=timezone.utc)
    service='payment-api' if scenario=='payment-api-latency' else 'checkout-api'
    rows=[]
    for minute in range(minutes):
        for index in range(12):
            stamp=origin+timedelta(minutes=minute,seconds=index*5)
            failure=4<=minute<9
            event={'timestamp':stamp.isoformat(),'service':service,'environment':'demo','level':'INFO','message':'request completed','trace_id':f'{scenario}-trace-{minute}-{index}','host':'checkout-01','attributes':{'http_status':200,'latency_ms':100}}
            if failure:
                if scenario=='db-pool-exhaustion':
                    if index%2==0:
                        db_event={**event,'timestamp':(stamp-timedelta(seconds=2)).isoformat(),'service':'orders-db','level':'ERROR','message':'database connection timeout; connection pool exhausted','attributes':{'database':'orders'}};rows.append(db_event)
                    event.update(level='ERROR',message='database connection timeout; HTTP 500 request failed');event['attributes']={'http_status':500,'latency_ms':5200,'database':'orders'}
                elif scenario=='auth-brute-force':
                    event.update(level='ERROR',message='failed login for synthetic-user');event['attributes']={'ip':'192.0.2.10','http_status':401,'latency_ms':150}
                elif scenario=='payment-api-latency':
                    event['message']='payment upstream response slow';event['attributes']['latency_ms']=3100
                elif scenario=='deployment-restart-loop':
                    if index in (0,4,8):event.update(level='WARN',message='service restart after deployment');event['attributes']['event']='restart'
                elif scenario=='critical-error-rate':
                    event.update(level='ERROR',message='critical HTTP 500 service unavailable');event['attributes']['http_status']=500
            if minute>=9:event['message']='recovery: healthy request after simulated configuration correction'
            rows.append(event)
    return rows
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--scenario',choices=SCENARIOS,default=SCENARIOS[0]);p.add_argument('--minutes',type=int,default=20);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text('\n'.join(json.dumps(e) for e in generate(a.scenario,a.minutes))+'\n',encoding='utf-8');print('Generated '+str(a.output))

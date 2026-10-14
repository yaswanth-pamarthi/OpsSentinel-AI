"""Browser smoke tests, screenshots, and narrated-by-README demonstration recordings."""
import json,re,time,shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]
PROJECTS={'procureMind':ROOT/'procureMind','opsSentinel':ROOT/'opsSentinel'}
_this=Path(__file__).resolve().parents[1]
PROJECTS['procureMind' if (_this/'backend/app/scoring.py').exists() else 'opsSentinel']=_this
CONFIG=[('procureMind',5173,'manager',['Dashboard','RFQs','Vendors','Documents & evidence','Agent analysis','Vendor comparison','Manager review','Reports','Audit trail']),
        ('opsSentinel',5174,'commander',['Operations dashboard','Log ingestion','Log explorer','Detection rules','Incidents','Agent analysis','Runbooks & remediation','Incident reports'])]
def capture(project,port,role,pages):
    root=PROJECTS[project];directory=root/'docs'/'screenshots';directory.mkdir(parents=True,exist_ok=True)
    video=root/'docs'/'demo';video.mkdir(exist_ok=True)
    environment=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line)
    errors=[];checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000},record_video_dir=str(video),record_video_size={'width':1440,'height':1000})
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{port}');page.screenshot(path=str(directory/'00-login.png'),full_page=False)
        page.locator('select').select_option(role+'@local.demo');page.locator('input[type=password]').fill(environment['DEMO_PASSWORD']);page.get_by_role('button',name='Sign in',exact=True).click();page.locator('aside').wait_for();page.wait_for_timeout(1800)
        for index,name in enumerate(pages):
            page.locator('nav').get_by_role('button',name=name,exact=True).click();page.wait_for_timeout(900)
            selected=page.get_by_label('Select RFQ') if project=='procureMind' else page.get_by_label('Select incident')
            results_path=root/'docs'/'execution-results.json'
            if selected.count() and results_path.exists():
                results=json.loads(results_path.read_text());record=results[0];selected.select_option(record['rfq_id'] if project=='procureMind' else record['incident_id']);page.wait_for_timeout(900)
            if name=='Documents & evidence':
                page.get_by_role('button',name='Evidence',exact=True).first.click();page.wait_for_timeout(1600)
                assert page.locator('iframe').count()==1,'Source PDF page viewer missing'
                checks.append('PDF page evidence viewer rendered')
            if name=='Agent analysis':
                button=page.get_by_role('button',name='Open latest run',exact=True)
                if button.count():button.click();page.wait_for_timeout(1200)
                assert page.get_by_text('COMPLETED',exact=True).count()>0
                checks.append('Seven-agent completed workflow visible')
            if name in ('Reports','Incident reports'):
                button=page.get_by_role('button',name='Generate report' if project=='procureMind' else 'Generate final report',exact=True)
                if button.is_enabled():button.click();page.wait_for_timeout(1000)
                download=page.get_by_role('button',name='Download PDF',exact=True)
                if download.count():
                    with page.expect_download() as event:download.click()
                    event.value.save_as(str(video/'browser-downloaded-report.pdf'));checks.append('Browser PDF report download passed')
            assert page.locator('main h1').inner_text()==name
            if page.get_by_role('alert').count():raise AssertionError(page.get_by_role('alert').inner_text())
            page.evaluate('window.scrollTo(0,0)')
            filename=f'{index+1:02d}-'+re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')+'.png'
            page.screenshot(path=str(directory/filename),full_page=False);checks.append('Navigated '+name)
        page.wait_for_timeout(1000);video_path=page.video.path();context.close();browser.close()
        shutil.copyfile(video_path,video/'walkthrough.webm')
    result={'browser':'Playwright Chromium','pages':len(pages),'checks':checks,'javascript_errors':errors,'passed':not errors}
    (root/'docs'/'browser-results.json').write_text(json.dumps(result,indent=2));print(project+': '+json.dumps(result),flush=True)
    if errors:raise RuntimeError(errors)
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('project',choices=['procureMind','opsSentinel','both'],default='both',nargs='?');a=parser.parse_args()
    for config in CONFIG:
        if a.project in ('both',config[0]):capture(*config)

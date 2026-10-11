import requests, json, time, hashlib, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parent
OUT=Path(os.environ.get('TELEGRAM_DATA_DIR',str(ROOT/'data'))); OUT.mkdir(exist_ok=True)
KST=timezone(timedelta(hours=9))
saved_meta=json.loads((OUT/'collection.json').read_text(encoding='utf-8')) if (OUT/'collection.json').exists() else {}
today=datetime.now(KST).date()
START=datetime.fromisoformat(os.getenv('TELEGRAM_START',saved_meta.get('default_start_kst',saved_meta.get('start_kst',str(today-timedelta(days=6)))))).replace(tzinfo=KST)
END=datetime.fromisoformat(os.getenv('TELEGRAM_END_EXCLUSIVE',saved_meta.get('default_end_exclusive_kst',saved_meta.get('end_exclusive_kst',str(today+timedelta(days=1)))))).replace(tzinfo=KST)
def collect(channel, start=None, end=None, out=None, progress=None):
    first=start or START; last=end or END; target=Path(out or OUT); target.mkdir(parents=True,exist_ok=True)
    records={}; pages=[]; before=None; actual_name=None; error=None; reason='page_limit'
    started=datetime.now(timezone.utc).isoformat()
    for page in range(100):
        url=f'https://t.me/s/{channel}'+(f'?before={before}' if before else '')
        try:
            r=requests.get(url,timeout=20,allow_redirects=False); r.raise_for_status()
            if r.status_code != 200: raise requests.RequestException("공개 미리보기로 접근할 수 없습니다.")
        except requests.RequestException as exc:
            error=str(exc); reason='request_error'; break
        (target/f'{channel}_{page:03}.html').write_text(r.text,encoding='utf-8')
        soup=BeautifulSoup(r.text,'html.parser'); batch=[]
        title=soup.select_one('.tgme_channel_info_header_title')
        if title: actual_name=title.get_text(' ',strip=True)
        for node in soup.select('.tgme_widget_message[data-post]'):
            post=node['data-post']; ts=node.select_one('time[datetime]')
            if not ts: continue
            dt=datetime.fromisoformat(ts['datetime']).astimezone(KST)
            body=node.select_one('.tgme_widget_message_text')
            text=body.get_text('\n',strip=True) if body else ''
            forward=node.select_one('.tgme_widget_message_forwarded_from')
            rec={'channel':channel,'id':int(post.split('/')[-1]),'url':'https://t.me/'+post,'datetime_kst':dt.isoformat(),'text':text,'forwarded_from':forward.get_text(' ',strip=True) if forward else None,'links':[a.get('href') for a in body.select('a[href]')] if body else [],'text_sha256':hashlib.sha256(text.encode()).hexdigest()}
            records[post]=rec; batch.append(rec)
        pages.append({'url':url,'status':r.status_code,'posts':len(batch)})
        if not batch: reason='no_public_messages'; break
        oldest=min(x['datetime_kst'] for x in batch); next_id=min(x['id'] for x in batch)
        print(channel,page,len(batch),oldest,flush=True)
        if progress: progress(page+1,len(records),oldest)
        if datetime.fromisoformat(oldest)<first: reason='start_boundary_reached'; break
        if next_id==before: reason='pagination_stalled'; break
        before=next_id; time.sleep(.3)
    allrows=sorted(records.values(),key=lambda x:x['id'])
    selected=[x for x in allrows if first<=datetime.fromisoformat(x['datetime_kst'])<last]
    (target/f'{channel}_all.json').write_text(json.dumps(allrows,ensure_ascii=False,indent=2),encoding='utf-8')
    return selected,{'channel':channel,'actual_name':actual_name,'pages':pages,'retrieved_posts':len(allrows),'period_posts':len(selected),'earliest_retrieved':min((p['datetime_kst'] for p in allrows),default=None),'latest_retrieved':max((p['datetime_kst'] for p in allrows),default=None),'started_at_utc':started,'finished_at_utc':datetime.now(timezone.utc).isoformat(),'coverage_complete':reason=='start_boundary_reached','stop_reason':reason,'error':error}
if __name__=='__main__':
    # The CLI uses the same durable job pipeline and preserves inactive/history data.
    from app import channel_manager
    if OUT.resolve()!=channel_manager.DATA.resolve():
        raise SystemExit('CLI 수집은 기본 data 폴더를 사용합니다. 기간은 TELEGRAM_START/TELEGRAM_END_EXCLUSIVE로 지정하세요.')
    if any(j['status'] in ('queued','running','analyzing') for j in channel_manager.jobs()):
        raise SystemExit('실행 중인 수집 작업이 있습니다. 완료 후 다시 실행하세요.')
    channel_manager.recover_jobs()
    for entry in channel_manager.channels():
        if not entry['enabled']: continue
        job=channel_manager.start_collection(entry['id'],START.date().isoformat(),(END-timedelta(days=1)).date().isoformat(),lambda:None)
        while channel_manager.is_busy(): time.sleep(.5)
        state=next(j for j in channel_manager.jobs() if j['id']==job['id'])
        print(json.dumps(state,ensure_ascii=False),flush=True)
    print('활성 채널 수집·분석 완료. 웹 앱의 저장 데이터 새로고침을 실행하세요.')

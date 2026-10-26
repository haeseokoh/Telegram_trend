"""Persistent channel registry and background collection with preserved history."""
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
REGISTRY=ROOT/'channels.json'
DATA=ROOT/'data'
JOBS=ROOT/'.runtime'/'collection_jobs.json'
registry_lock=Lock()
job_lock=Lock()
running=False


def today_kst():
    return datetime.now(timezone(timedelta(hours=9))).date()


def recent_period():
    today=today_kst()
    return {'start':str(today-timedelta(days=6)),'end':str(today)}


def start_refresh(on_complete):
    """Reserve one durable batch; child jobs retain independent failure/coverage evidence."""
    global running
    active=[c['id'] for c in channels() if c['enabled']]
    if not active: raise ChannelError('활성 채널이 없습니다. 채널 관리에서 활성화하세요.')
    today=today_kst()
    meta=read_json(DATA/'collection.json',{})
    plans=[]
    for ch in active:
        saved=next((c for c in meta.get('channels',[]) if c['channel']==ch),None)
        ranges=coverage_ranges(meta,saved) if saved else []
        # Resume from the last fully traversed range, including its partial final day.
        ends=[date.fromisoformat(r['end_exclusive_kst'][:10])-timedelta(days=1)
              for r in ranges if r.get('coverage_complete')]
        start=min(max(ends) if ends else today-timedelta(days=6),today-timedelta(days=6))
        start=max(start,today-timedelta(days=366))
        plans.append({'channel':ch,'start':str(start),'end':str(today)})
    with job_lock:
        if running or any(j['status'] in ('queued','running','analyzing') and owner_alive(j) for j in read_json(JOBS,[])):
            raise ChannelError('다른 수집·분석 작업이 진행 중입니다. 완료 후 다시 실행하세요.',409)
        batch={'id':uuid.uuid4().hex,'channel':'active','kind':'refresh','plans':plans,
               'start':min(p['start'] for p in plans),'end':str(today),
               'status':'queued','created_at_utc':datetime.now(timezone.utc).isoformat(),
               'owner_pid':os.getpid(),'pages':0,'retrieved_posts':0,'error':None}
        rows=read_json(JOBS,[]); rows.append(batch); save_json(JOBS,rows[-100:])
        running=True
    Thread(target=refresh_worker,args=(batch,on_complete),daemon=True).start()
    return batch


def refresh_worker(batch,on_complete):
    global running
    try:
        update_job(batch['id'],status='running')
        results=[]
        for plan in batch['plans']:
            child={**plan,'id':uuid.uuid4().hex,'batch_id':batch['id'],'status':'queued',
                   'created_at_utc':datetime.now(timezone.utc).isoformat(),'owner_pid':os.getpid(),
                   'pages':0,'retrieved_posts':0,'error':None}
            with job_lock:
                rows=read_json(JOBS,[]); rows.append(child); save_json(JOBS,rows[-100:])
            update_job(batch['id'],current_channel=plan['channel'])
            worker(child,on_complete)
            result=next(j for j in jobs() if j['id']==child['id'])
            results.append(result)
            update_job(batch['id'],completed_channels=len(results),
                       pages=sum(j['pages'] for j in results),retrieved_posts=sum(j['retrieved_posts'] for j in results))
        failed=[j for j in results if j['status']!='completed']
        update_job(batch['id'],status='completed' if not failed else 'partial',
                   new_posts=sum(j.get('new_posts',0) for j in results),
                   error=' · '.join(j['channel']+': '+(j.get('error') or j['status']) for j in failed) or None,
                   finished_at_utc=datetime.now(timezone.utc).isoformat())
    except Exception:
        update_job(batch['id'],status='failed',error='전체 갱신이 중단됐습니다. 채널별 작업 기록을 확인하세요.',
                   finished_at_utc=datetime.now(timezone.utc).isoformat())
    finally:
        with job_lock: running=False


class ChannelError(Exception):
    def __init__(self,message,status=422):
        self.status=status
        super().__init__(message)


def read_json(path,default):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError): return default


def save_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def channels():
    with registry_lock:
        if not REGISTRY.exists():
            save_json(REGISTRY,read_json(ROOT/'channels.example.json',[]))
        return [{**c,'enabled':c.get('enabled',True)} for c in read_json(REGISTRY,[])]


def normalize(value):
    value=value.strip()
    if value.startswith('@'): value=value[1:]
    elif '://' in value or value.startswith(('t.me/','telegram.me/')):
        u=urlsplit(value if '://' in value else 'https://'+value)
        if u.scheme!='https' or u.netloc.lower() not in ('t.me','telegram.me') or u.query or u.fragment:
            raise ChannelError('https://t.me/채널이름 형식의 공개 채널 링크만 지원합니다.')
        parts=u.path.strip('/').split('/')
        if len(parts)==2 and parts[0]=='s': parts=parts[1:]
        if len(parts)!=1: raise ChannelError('게시물·초대 링크 대신 공개 채널 링크를 입력하세요.')
        value=parts[0]
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}',value):
        raise ChannelError('공개 채널 사용자 이름 또는 https://t.me/채널이름을 입력하세요. 비공개 초대 링크는 지원하지 않습니다.')
    return value.lower()


def probe(value):
    ch=normalize(value)
    try:
        r=requests.get('https://t.me/s/'+ch,timeout=(5,10),allow_redirects=False)
        if r.status_code!=200: raise ChannelError('공개 웹 미리보기에 접근할 수 없습니다. 비공개 채널·그룹·계정은 지원하지 않습니다.',400)
        soup=BeautifulSoup(r.text,'html.parser')
        title=soup.select_one('.tgme_channel_info_header_title')
        if not title or not soup.select_one('.tgme_widget_message[data-post]'):
            raise ChannelError('공개 메시지 미리보기를 확인할 수 없습니다. 사용자 이름과 공개 채널 여부를 확인하세요.',400)
        return {'id':ch,'name':title.get_text(' ',strip=True),'verified_at_utc':datetime.now(timezone.utc).isoformat()}
    except requests.RequestException:
        raise ChannelError('Telegram 공개 접근 확인에 실패했습니다. 네트워크 상태를 확인하고 다시 시도하세요.',502)


def register(value):
    ch=normalize(value)
    with registry_lock:
        rows=read_json(REGISTRY,[])
        if any(c['id'].lower()==ch for c in rows): raise ChannelError('이미 등록된 채널입니다. 채널 관리에서 재활성화할 수 있습니다.',409)
    verified=probe(ch)
    with registry_lock:
        rows=read_json(REGISTRY,[])
        if any(c['id'].lower()==ch for c in rows): raise ChannelError('이미 등록된 채널입니다.',409)
        rows.append({**verified,'enabled':True})
        save_json(REGISTRY,rows)
    return {**verified,'enabled':True}


def set_enabled(channel,enabled):
    with registry_lock:
        rows=read_json(REGISTRY,[])
        c=next((c for c in rows if c['id']==channel),None)
        if c is None: raise ChannelError('등록되지 않은 채널입니다.',404)
        c['enabled']=enabled
        save_json(REGISTRY,rows)
        return c.copy()


def jobs():
    with job_lock: return list(reversed(read_json(JOBS,[])))

def owner_alive(job):
    pid=job.get('owner_pid')
    if not isinstance(pid,int) or pid<=0: return False
    if pid==os.getpid(): return True
    if os.name=='nt':
        import ctypes
        kernel=ctypes.windll.kernel32
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle: return False
        code=ctypes.c_ulong()
        try: return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally: kernel.CloseHandle(handle)
    try: os.kill(pid,0); return True
    except OSError: return False

def is_busy():
    with job_lock:
        return running or any(j['status'] in ('queued','running','analyzing') and owner_alive(j) for j in read_json(JOBS,[]))


def update_job(job_id,**fields):
    with job_lock:
        rows=read_json(JOBS,[])
        job=next(j for j in rows if j['id']==job_id)
        job.update(fields)
        save_json(JOBS,rows)


def recover_jobs():
    with job_lock:
        rows=read_json(JOBS,[])
        for j in rows:
            if j['status'] in ('queued','running','analyzing') and not owner_alive(j):
                backup=DATA/'collection_history'/j['id']/'previous_outputs'
                if backup.exists():
                    for f in backup.iterdir():
                        if f.is_file(): shutil.copy2(f,DATA/f.name)
                j.update(status='interrupted',error='서버 재시작으로 수집이 중단되었습니다. 다시 수집하세요.')
        if rows: save_json(JOBS,rows)


def start_collection(channel,start,end,on_complete):
    global running
    if not any(c['id']==channel for c in channels()): raise ChannelError('등록되지 않은 채널입니다.',404)
    try: first,last=date.fromisoformat(start),date.fromisoformat(end)
    except ValueError: raise ChannelError('날짜는 YYYY-MM-DD 형식이어야 합니다.')
    if first>last or (last-first).days>366 or last>datetime.now(timezone(timedelta(hours=9))).date():
        raise ChannelError('시작일·종료일을 확인하세요. 오늘까지 최대 367일을 수집할 수 있습니다.')
    with job_lock:
        if running or any(j['status'] in ('queued','running','analyzing') and owner_alive(j) for j in read_json(JOBS,[])):
            raise ChannelError('다른 채널을 수집·분석 중입니다. 완료 후 다시 실행하세요.',409)
        running=True
        job={'id':uuid.uuid4().hex,'channel':channel,'start':start,'end':end,'status':'queued',
             'created_at_utc':datetime.now(timezone.utc).isoformat(),'pages':0,'retrieved_posts':0,'error':None,'owner_pid':os.getpid()}
        rows=read_json(JOBS,[]); rows.append(job); save_json(JOBS,rows[-100:])
    Thread(target=worker,args=(job,on_complete),daemon=True).start()
    return job


def coverage_ranges(meta,c):
    return c.get('coverage_ranges') or [{'start_kst':meta['start_kst'],'end_exclusive_kst':meta['end_exclusive_kst'],
           'coverage_complete':c.get('coverage_complete',False),'collected_at_utc':c.get('finished_at_utc',meta['collected_at_utc']),
           'earliest_retrieved':c.get('earliest_retrieved')}]


def worker(job,on_complete):
    global running
    from collect import collect,KST
    job_id=job['id']; ch=job['channel']
    stage=ROOT/'.runtime'/'collections'/job_id
    first=datetime.fromisoformat(job['start']).replace(tzinfo=KST)
    last=datetime.fromisoformat(job['end']).replace(tzinfo=KST)+timedelta(days=1)
    backup=None
    try:
        update_job(job_id,status='running')
        selected,stat=collect(ch,first,last,stage,lambda pages,count,oldest:update_job(job_id,pages=pages,retrieved_posts=count,oldest_kst=oldest))
        if not stat['retrieved_posts']:
            raise ChannelError(stat['error'] or '공개 메시지를 수집할 수 없습니다. 기존 데이터는 보존됩니다.',502)
        update_job(job_id,status='analyzing',period_posts=len(selected),coverage_complete=stat['coverage_complete'],stop_reason=stat['stop_reason'])
        original=read_json(DATA/'posts.json',[])
        merged={p['url']:p for p in original}
        merged.update({p['url']:p for p in selected})
        posts=list(merged.values())
        meta=read_json(DATA/'collection.json',{})
        meta.setdefault('default_start_kst',meta['start_kst'])
        meta.setdefault('default_end_exclusive_kst',meta['end_exclusive_kst'])
        for c in meta['channels']: c['coverage_ranges']=coverage_ranges(meta,c)
        old=next((c for c in meta['channels'] if c['channel']==ch),None)
        stat['coverage_ranges']=(old['coverage_ranges'] if old else [])+[{'start_kst':first.isoformat(),'end_exclusive_kst':last.isoformat(),
             'coverage_complete':stat['coverage_complete'],'collected_at_utc':stat['finished_at_utc'],'stop_reason':stat['stop_reason'],'job_id':job_id,
             'earliest_retrieved':stat['earliest_retrieved']}]
        stat['pages']=(old.get('pages',[]) if old else [])+stat['pages']
        allrows={p['url']:p for p in read_json(DATA/f'{ch}_all.json',[])}
        allrows.update({p['url']:p for p in original if p['channel']==ch})
        allrows.update({p['url']:p for p in read_json(stage/f'{ch}_all.json',[])})
        stat['retrieved_posts']=len(allrows)
        stat['period_posts']=sum(p['channel']==ch for p in posts)
        stat['earliest_retrieved']=min(p['datetime_kst'] for p in allrows.values())
        stat['latest_retrieved']=max(p['datetime_kst'] for p in allrows.values())
        meta['channels']=[c for c in meta['channels'] if c['channel']!=ch]+[stat] if not old else [stat if c['channel']==ch else c for c in meta['channels']]
        meta['start_kst']=min(meta['start_kst'],first.isoformat()); meta['end_exclusive_kst']=max(meta['end_exclusive_kst'],last.isoformat())
        meta['collected_at_utc']=stat['finished_at_utc']
        if meta.get('packaged_sample'):
            meta['sample_source_urls']=[p['url'] for p in original]
        meta['packaged_sample']=False
        save_json(stage/'posts.json',posts); save_json(stage/'collection.json',meta)
        env={**os.environ,'TELEGRAM_DATA_DIR':str(stage),'PYTHONIOENCODING':'utf-8','TELEGRAM_WRITE_REPORT':'0'}
        for script in ('analyze.py','report.py'):
            result=subprocess.run([sys.executable,str(ROOT/script)],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=300)
            if result.returncode: raise ChannelError('분석 생성에 실패했습니다. 기존 데이터는 유지됩니다.',500)
            if script=='analyze.py': save_json(stage/'analysis_validation.json',json.loads(result.stdout))
        archive=DATA/'collection_history'/job_id
        archive.mkdir(parents=True,exist_ok=True)
        for f in stage.glob('*.html'): shutil.copy2(f,archive/f.name)
        save_json(archive/'collection.json',stat)
        save_json(archive/'previous_posts.json',original)
        backup=archive/'previous_outputs'; backup.mkdir(exist_ok=True)
        output_names=('posts.json','collection.json','posts_annotated.json','mentions.csv','ranking.csv','daily_mentions.csv','entities.json','duplicate_clusters.json','issues.json','analysis_validation.json')
        for name in output_names:
            if (DATA/name).exists(): shutil.copy2(DATA/name,backup/name)
        # Durable source files first; publish in-memory snapshot only after all outputs are ready.
        save_json(DATA/f'{ch}_all.json',list(allrows.values()))
        for name in output_names:
            tmp=DATA/(name+'.new'); shutil.copy2(stage/name,tmp); tmp.replace(DATA/name)
        on_complete()
        update_job(job_id,status='completed' if stat['coverage_complete'] else 'partial',
                   period_posts=len(selected),new_posts=len(set(merged)-{p['url'] for p in original}),
                   error=stat['error'],stop_reason=stat['stop_reason'],finished_at_utc=stat['finished_at_utc'])
    except Exception as exc:
        if backup and backup.exists():
            for f in backup.iterdir():
                if f.is_file(): shutil.copy2(f,DATA/f.name)
            try: on_complete()
            except Exception: pass
        update_job(job_id,status='failed',error=str(exc) if isinstance(exc,ChannelError) else '수집·분석에 실패했습니다. 기존 데이터를 확인하고 다시 시도하세요.')
    finally:
        with job_lock: running=False

import csv
import io
from datetime import date, timedelta
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from app import service
from app import ai
from app import channel_manager
from pydantic import BaseModel

app = FastAPI(title='텔레그램 트렌드 인텔리전스', version='1.0.0')
STATIC = Path(__file__).parent / 'static'
app.mount('/static', StaticFiles(directory=STATIC), name='static')
channel_manager.recover_jobs()
channel_manager.channels()
snapshot = service.load()
snapshot_lock = Lock()

def publish_snapshot():
    global snapshot
    updated=service.load()
    with snapshot_lock: snapshot=updated

class ChannelRequest(BaseModel):
    channel: str

class EnableRequest(BaseModel):
    enabled: bool

class CollectionRequest(BaseModel):
    start: str
    end: str

@app.get('/api/channels')
def managed_channels():
    rows=[]
    for c in channel_manager.channels():
        collected=next((x for x in snapshot['meta']['channels'] if x['channel']==c['id']),None)
        rows.append({**c,'stored_posts':sum(p['channel']==c['id'] for p in snapshot['posts']),
                    'coverage_ranges':channel_manager.coverage_ranges(snapshot['meta'],collected) if collected else [],
                    'last_collected_at_utc':collected.get('finished_at_utc') if collected else None})
    return {'channels':rows,'jobs':channel_manager.jobs()}

@app.post('/api/channels',status_code=201)
def add_channel(request: Request,body: ChannelRequest):
    ai_origin(request)
    try: return channel_manager.register(body.channel)
    except channel_manager.ChannelError as e: raise HTTPException(e.status,str(e))

@app.patch('/api/channels/{channel}')
def enable_channel(channel: str,request: Request,body: EnableRequest):
    ai_origin(request)
    try: return channel_manager.set_enabled(channel,body.enabled)
    except channel_manager.ChannelError as e: raise HTTPException(e.status,str(e))

@app.post('/api/channels/{channel}/collect',status_code=202)
def collect_channel(channel: str,request: Request,body: CollectionRequest):
    ai_origin(request)
    try: return channel_manager.start_collection(channel,body.start,body.end,publish_snapshot)
    except channel_manager.ChannelError as e: raise HTTPException(e.status,str(e))

@app.get('/api/collection-jobs')
def collection_jobs():
    return {'jobs':channel_manager.jobs()}


@app.post('/api/collect-latest',status_code=202)
def collect_latest(request: Request):
    ai_origin(request)
    try: return channel_manager.start_refresh(publish_snapshot)
    except channel_manager.ChannelError as e: raise HTTPException(e.status,str(e))

class AIRequest(BaseModel):
    model: str | None = None
    refresh: bool = False

def ai_origin(request):
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403,'같은 웹 앱에서 요청하세요.')

@app.get('/api/ai/status')
def ai_status():
    return ai.status()

@app.post('/api/post/{channel}/{post_id}/ai-summary')
def ai_post(channel: str, post_id: int, request: Request, body: AIRequest):
    ai_origin(request)
    p=next((p for p in snapshot['posts'] if p['channel']==channel and p['id']==post_id),None)
    if not p: raise HTTPException(404,'저장된 메시지가 없습니다.')
    try: return ai.generate([p],body.model,'post',body.refresh)
    except ai.AIError as e: raise HTTPException(e.status,str(e))

@app.post('/api/ai/brief')
def ai_brief(request: Request, body: AIRequest, entity: str = ''):
    ai_origin(request)
    chosen,total=ai.brief_posts(snapshot,read_filters(request),entity)
    try:
        result=ai.generate(chosen,body.model,'entity' if entity else 'brief',body.refresh,total)
        return {**result,'entity':entity,'filters':read_filters(request)}
    except ai.AIError as e: raise HTTPException(e.status,str(e))


def filters(start=None, end=None, channels=None, mode='posts', exclude_pins=True, exclude_lists=False, scope='stocks'):
    period=channel_manager.recent_period()
    start = start or period['start']
    end = end or period['end']
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise HTTPException(422, '날짜는 YYYY-MM-DD 형식이어야 합니다.')
    if first > last or (last-first).days > 366:
        raise HTTPException(422, '시작일과 종료일을 확인하세요. 최대 367일을 조회할 수 있습니다.')
    active=[c['id'] for c in channel_manager.channels() if c['enabled']]
    chosen = list(dict.fromkeys(channels.split(','))) if channels is not None else active
    if (channels is not None and not chosen) or any(ch not in active for ch in chosen):
        raise HTTPException(422, '채널을 하나 이상 선택하세요.')
    if mode not in ['posts', 'clusters'] or scope not in ['stocks', 'all']:
        raise HTTPException(422, '지원되지 않는 집계 방식입니다.')
    return dict(start=start, end=end, channels=chosen, mode=mode, exclude_pins=exclude_pins, exclude_lists=exclude_lists, scope=scope)


def read_filters(request):
    args = {k: v for k, v in request.query_params.items() if k in ['start','end','channels','mode','scope']}
    for key in ['exclude_pins', 'exclude_lists']:
        if key in request.query_params:
            value = request.query_params[key]
            if value not in ['true', 'false']: raise HTTPException(422, '잘못된 필터 값입니다.')
            args[key] = value == 'true'
    return filters(**args)


@app.get('/')
def home():
    return FileResponse(STATIC / 'index.html')

@app.get('/api/health')
def health():
    import os
    return {'app':'telegram-trend','status':'ok','pid':os.getpid()}


@app.get('/api/dashboard')
def dashboard(request: Request, focus: str | None = None):
    return service.aggregate(snapshot, read_filters(request), focus)


@app.get('/api/config')
def config():
    meta=snapshot['meta']
    return {'channels':[{'id':c['id'],'name':c['name']} for c in channel_manager.channels() if c['enabled']],
            **channel_manager.recent_period(),'automatic_collection':False,
            'collected_at_utc':meta['collected_at_utc']}


@app.get('/api/posts')
def posts(request: Request, query: str = '', entity: str = '', kind: str = 'all', page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    if kind not in ['all', 'duplicates', 'forwarded', 'list']: raise HTTPException(422, '잘못된 분류입니다.')
    return service.explore(snapshot, read_filters(request), query, entity, kind, page, page_size)


@app.get('/api/post/{channel}/{post_id}')
def detail(channel: str, post_id: int):
    p = next((p for p in snapshot['posts'] if p['channel'] == channel and p['id'] == post_id), None)
    if not p: raise HTTPException(404, '저장된 메시지가 없습니다.')
    return {**p, 'mentions': [m for m in snapshot['mentions'] if m['url'] == p['url']],
            'duplicates': [{'url': q['url'], 'datetime_kst': q['datetime_kst'], 'channel': q['channel']} for q in snapshot['posts'] if q['duplicate_cluster'] == p['duplicate_cluster']]}


@app.get('/api/export')
def export(request: Request):
    result = service.aggregate(snapshot, read_filters(request))
    buf = io.StringIO(); writer = csv.writer(buf)
    writer.writerow(['종목/기업','표시 건수','원시 언급 게시물','본문 군집','채널 수','메시지 대비 빈도(%)','첫 줄 언급','목록 언급'])
    for r in result['ranking']:
        writer.writerow([r['entity'],r['count'],r['raw'],r['clusters'],r['channel_count'],r['frequency_pct'],r['headline'],r['list']])
    return Response('\ufeff'+buf.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition':'attachment; filename="telegram-ranking.csv"'})


@app.post('/api/reload')
def reload(request: Request):
    if channel_manager.is_busy(): raise HTTPException(409,'수집·분석 중입니다. 완료 후 자동으로 반영됩니다.')
    # Local same-origin UI only; reject cross-origin browser POSTs.
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, '같은 주소의 앱에서 실행하세요.')
    global snapshot
    with snapshot_lock:
        try:
            new = service.load()
        except (OSError, ValueError) as exc:
            raise HTTPException(503, '데이터 파일을 읽을 수 없습니다. 분석 완료 후 다시 시도하세요.') from exc
        snapshot = new
    return {'status':'loaded','posts':len(new['posts'])}

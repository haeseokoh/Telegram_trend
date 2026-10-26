import json,csv,os
from pathlib import Path
from datetime import datetime,timezone,timedelta
R=Path(__file__).resolve().parent
D=Path(os.environ.get('TELEGRAM_DATA_DIR',str(R/'data')))
posts=json.loads((D/'posts_annotated.json').read_text(encoding='utf-8'))
ranking=list(csv.DictReader((D/'ranking.csv').open(encoding='utf-8-sig')))
meta=json.loads((D/'collection.json').read_text(encoding='utf-8'))
catalog=json.loads((R/'issues_catalog.json').read_text(encoding='utf-8'))
urls={p['url'] for p in posts}
issues=[{**i,'links':[u for u in i['links'] if u in urls]} for i in catalog]
issues=[i for i in issues if i['links']]
(D/'issues.json').write_text(json.dumps(issues,ensure_ascii=False,indent=2),encoding='utf-8')
stamp=datetime.fromisoformat(meta['collected_at_utc']).astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S KST')
active=sum(c.get('enabled',True) for c in json.loads((R/('channels.json' if (R/'channels.json').exists() else 'channels.example.json')).read_text(encoding='utf-8')))
lines=['# 공개 Telegram 주식 채널 분석',f'\n수집 완료: {stamp}. 저장 자료의 전체 날짜 범위: {meta["start_kst"]} 이상, {meta["end_exclusive_kst"]} 미만. 채널별 실제 수집 기간은 collection.json의 coverage_ranges에 기록하며 수집 당일은 부분 일자입니다.',f'\n공개 {len(meta["channels"])}개 채널의 자료 {len(posts)}건을 보존하고 있습니다. 이 보고서는 비활성 채널을 포함한 저장 자료 전체이며, 웹의 기본 분석은 활성 {active}개 채널을 대상으로 합니다. 언급 횟수는 게시 관심의 지표이며 투자 추천이나 독립된 뉴스 수가 아닙니다.', '\n## 저장 자료 범위','\n|실제 공개 채널명|ID|보존 글|실제 게시 시각(KST)|최근 수집 경계|수집 완료(UTC)|','|---|---|---:|---|---|---|']
for c in meta['channels']:
    pp=[p for p in posts if p['channel']==c['channel']]
    times=sorted(p['datetime_kst'] for p in pp)
    span=f'{times[0][:19]} ~ {times[-1][:19]}' if times else '기간 내 노출 글 없음'
    status='시작일 이전 글 도달' if c['coverage_complete'] else f'미완료: {c["stop_reason"]}; {c.get("error") or ""}'
    lines.append(f'|[{c["actual_name"]}](https://t.me/s/{c["channel"]})|{c["channel"]}|{len(pp)}|{span}|{status}|{c["finished_at_utc"]}|')
pages=sum(len(c['pages']) for c in meta['channels']); retrieved=sum(c['retrieved_posts'] for c in meta['channels'])
lines += [f'\nHTML 응답 {pages}개, 경계 글 포함 {retrieved}건을 확보했습니다. 기간 밖 {retrieved-len(posts)}건은 분석에서 제외했습니다. 채널마다 수집 시간이 다르며 collection.json에 요청 URL·HTTP 상태·중단 이유를 기록했습니다.', '\n공개 웹에 현재 노출되는 글에 한정합니다. 삭제·비공개 글, 이미지/PDF/영상 내부 텍스트, 링크 목적지 본문은 수집하지 않았습니다. ID 공백은 누락 개수가 아닙니다. 비공개 기록의 완전성은 확인할 수 없습니다.', '\n## 종목 언급 순위 — 확장 샘플 사전','\n|종목 후보|원시 언급 글|고정 제외|유사 본문 군집|채널 수|첫 줄|목록|','|---|---:|---:|---:|---:|---:|---:|']
for s in [x for x in ranking if x['scope']=='stock_candidate'][:30]:
    lines.append('|'+ '|'.join(s[k] for k in ['entity','post_mentions','non_pin_post_mentions','text_clusters','channels','headline_posts','list_posts'])+'|')
lines += ['\n동일 글에서 같은 종목은 한 번만 셉니다. 원시 건수에는 고정 알림이 포함되며 웹 기본값은 고정 제외입니다. 첫 줄 언급은 분석 중심성의 대리 지표이며 뒤쪽 제목은 본문으로 분류될 수 있습니다. 미래에셋 퀀트 Daily와 키움 반도체 시세 목록을 본문 규칙에 따라 목록으로 분류합니다. 산업 해설 안의 관심 종목은 본문 언급으로 남깁니다.', '\n국내 종목 및 별칭(에코비엠→에코프로비엠, 모비스→현대모비스, 네이버→NAVER 등)은 domestic_aliases.json, 해외 시세 목록과 추가 글의 이름은 foreign_aliases.json에 보강했습니다. 긴 이름 우선 매칭으로 Nanya PCB를 Nanya, 현대차2우B를 현대차로 중복 세지 않습니다. 네이버파이낸셜·SK온·현대차그룹을 상장 모회사 언급으로 자동 환산하지 않습니다. 짧은 영어 별칭·동명이인 및 사전 밖 기업의 오인식·누락은 남을 수 있으며 상장 상태·티커를 전수 검증하지 않았습니다.', '\n## 이슈 요약과 수집된 원문','\n채널 글의 주장과 분석 주제 요약입니다. 개별 계약·공시·예측의 사실 여부를 검증한 결과는 아닙니다. 웹은 선택 채널·기간 안 근거 링크가 있는 이슈만 표시합니다.']
for i in issues:
    links=' · '.join(f'[{u.split("/")[-2]}/{u.split("/")[-1]}]({u})' for u in i['links'])
    lines.append('\n- **'+', '.join(i['entities'])+'**: '+i['issue']+' '+links)
lines += ['\n## 중복과 재현','\n공백·대소문자·제로폭 문자를 정규화하고 고정 알림의 인용 본문을 추출합니다. 동일 본문 또는 100자 이상, 길이 차이 10% 이하, SequenceMatcher 0.94 이상이면 채널을 가로질러 같은 군집으로 묶습니다. 같은 사건의 서로 다른 해설은 별도 군집일 수 있습니다. 전달 표시만으로 중복 처리하지 않습니다. 일별 군집 수는 선택 범위의 첫 등장일에 배정합니다.', '\n전주를 수집하지 않아 증가율은 제공하지 않습니다. verify.py로 합계와 원문 포함 여부를 검사합니다. channels.json은 공통 채널 레지스트리, issues_catalog.json은 이슈 편집 원본입니다. 재생성 순서: collect.py → analyze.py → report.py → verify.py. 이전 자료와 원본 HTML은 로컬 data/collection_history에 보존합니다.']
if os.getenv('TELEGRAM_WRITE_REPORT','1')!='0':
    Path(os.getenv('TELEGRAM_REPORT_PATH',str(R/'REPORT.md'))).write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'posts':len(posts),'channels':len(meta['channels']),'issues':len(issues),'html_pages':pages},ensure_ascii=False))

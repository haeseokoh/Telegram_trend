import json,re,csv,hashlib,os
from pathlib import Path
from collections import Counter,defaultdict
from difflib import SequenceMatcher
ROOT=Path(__file__).resolve().parent; D=Path(os.environ.get('TELEGRAM_DATA_DIR',str(ROOT/'data'))).resolve()
CHANNELS=[c['id'] for c in json.loads((ROOT/('channels.json' if (ROOT/'channels.json').exists() else 'channels.example.json')).read_text(encoding='utf-8'))]
rows=json.loads((D/'posts.json').read_text(encoding='utf-8'))
# Curated sample dictionary. Listing/ticker validation is deliberately separate.
foreign={
'엔비디아':['엔비디아','NVIDIA','NVDA'], 'TSMC':['TSMC','台積電'],
'테슬라':['테슬라','Tesla','TSLA'], '마이크론':['마이크론','Micron','$MU'],
'알파벳(구글)':['구글','Google','알파벳','Alphabet','GOOGL'],
'마이크로소프트':['마이크로소프트','Microsoft','MSFT'], '아마존':['아마존','Amazon','AMZN'],
'AMD':['AMD'], '인텔':['인텔','Intel','INTC'], '애플':['애플','Apple','AAPL'],
'메타':['메타','Meta','$META'], '브로드컴':['브로드컴','Broadcom','AVGO'],
'루멘텀':['루멘텀','Lumentum','$LITE'], '마벨':['마벨','Marvell','MRVL'],
'아스테라랩스':['아스테라랩스','Astera Labs','ALAB'], 'ASML':['ASML'],
'어플라이드 머티어리얼즈':['어플라이드 머티어리얼즈','Applied Materials','AMAT'],
'어드반테스트':['어드반테스트','Advantest'], '도쿄일렉트론':['도쿄일렉트론','Tokyo Electron'],
'닛토보':['닛토보','닛토방적','Nittobo'], '폭스콘':['폭스콘','홍하이','Foxconn','Hon Hai'],
'라간 프리시전':['라간 프리시전','라간정밀','Largan'],
'타이광전자재료':['타이광전자재료','타이광','EMC','Elite Material'],
'TUC':['TUC','Taiwan Union Technology'], 'ITEQ':['ITEQ'],
'난야 PCB':['Nan Ya PCB','난야 PCB','난야PCB'],
'Unimicron':['Unimicron','유니마이크론'], 'Zhen Ding Tech':['Zhen Ding','젠딩','전딩'],
'UMC':['UMC','United Microelectronics'], 'ASPEED':['ASPEED','Aspeed'],
'Chunghwa Precision Test':['Chunghwa Precision Test','中華精測'],
'위윈':['위윈','Wiwynn'], '위스트론':['위스트론','Wistron'], '콴타':['콴타','Quanta'],
'델타전자':['델타전자','Delta Electronics'], '라이트온':['라이트온','LITEON','LITE-ON'],
'AcBel':['AcBel'], 'Compucase':['Compucase'], 'Chicony Power':['치코니 파워','Chicony Power'],
'Gudeng':['Gudeng'], 'Winstek':['Winstek'], 'Sigurd':['Sigurd'],
'나비타스':['나비타스','Navitas','NVTS'], '넷리스트':['넷리스트','Netlist'],
'GlobalFoundries':['GlobalFoundries','글로벌파운드리'], '앰코':['앰코','Amkor'],
'TDK':['TDK'], '시게이트':['시게이트','Seagate'], '무라타':['무라타','Murata'],
'Yageo':['Yageo','야게오'], 'Besi':['Besi','베시'], 'TOWA':['TOWA'],
'디스코':['디스코','DISCO'], '가와사키중공업':['가와사키중공업','Kawasaki Heavy'],
'신에츠화학':['신에츠','Shin-Etsu'], '시오노기제약':['시오노기','Shionogi'],
'유니치카':['유니치카','Unitika'], '타이요유덴':['타이요유덴','Taiyo Yuden'],
'소프트뱅크':['소프트뱅크','SoftBank'], '헨켈':['헨켈','Henkel'],
'JX금속':['JX금속','JX Advanced'], '야스카와전기':['야스카와','Yaskawa'],
'Rorze':['Rorze','로체'], '오사카유기화학':['오사카유기화학'],
'하마마쓰포토닉스':['하마마쓰','Hamamatsu'], '마이크로칩':['마이크로칩','Microchip'],
'PTC':['PTC'], '슈나이더':['슈나이더','Schneider'], '네비우스':['Nebius','NBIS'],
'AT&T':['AT&T'], '스타벅스':['스타벅스','Starbucks'], '치폴레':['치폴레','Chipotle'],
}
other={'SpaceX':['스페이스X','SpaceX','SPCX'],'OpenAI':['오픈AI','OpenAI'],'Anthropic':['앤스로픽','앤트로픽','Anthropic'],'Anduril':['안두릴','Anduril']}
domestic=['삼성전자','SK하이닉스','삼성전기','한미반도체','티에스이','이수페타시스','대덕전자','삼성증권','테크윙','한솔케미칼','파두']
for p in rows:
    if p['channel']=='eqmirae':
        for line in p['text'].splitlines():
            if ',' in line and not any(s in line for s in ['[','기준','10/','2026','(',')',':','/']):
                domestic += [s.strip() for s in line.split(',') if s.strip()]
aliases={**foreign,**{s:[s] for s in sorted(set(domestic))},**other}
for filename in ['domestic_aliases.json','foreign_aliases.json']:
    extra=ROOT/filename
    if not extra.exists(): continue
    for entity,names in json.loads(extra.read_text(encoding='utf-8')).items():
        aliases[entity]=list(dict.fromkeys(aliases.get(entity,[])+names))
# NC is kept as exactly the name written; no unverified mapping to another company.
def pattern(a):
    # Korean particles are allowed; 테스 must not match 테스트/어드반테스트,
    # and 비에이치 must not match 비에이치아이.
    return re.compile(r'(?<![가-힣A-Za-z0-9])'+re.escape(a)+r'(?=$|[^가-힣A-Za-z0-9]|(?:은|는|이|가|을|를|의|와|과|도|에|에서|으로|로|에게|만|조차|까지|부터|뿐|향)(?=$|[^가-힣A-Za-z0-9]))',re.I)
patterns={s:[pattern(a) for a in aa] for s,aa in aliases.items()}
def norm(t): return re.sub(r'\s+','',t.replace('\u200b','').replace('\ufeff','')).casefold()
clusters=[]; assignments={}; normalized=[]
for p in rows:
    txt=p['text']; n=norm(txt)
    p['is_pin_notice']=bool(re.search(r'\bpinned\b',txt))
    p['is_stock_list']=(p['channel']=='eqmirae' and '퀀트 Daily' in txt[:150]) or ('밸류 체인 주가' in txt[:100])
    # Pinned notices quote the original body; compare quoted body with original.
    if p['is_pin_notice'] and '«' in txt: n=norm(txt.split('«',1)[1].rstrip('» '))
    cid=None; reason='new'
    if n:
        for i,old in enumerate(normalized):
            if n==old: cid=i; reason='normalized_exact'; break
            if len(n)>=100 and len(old)>=100 and abs(len(n)-len(old))/max(len(n),len(old))<=.1 and SequenceMatcher(None,n,old,autojunk=False).ratio()>=.94:
                cid=i; reason='near_text_0.94'; break
    if cid is None: cid=len(clusters); clusters.append([]); normalized.append(n)
    clusters[cid].append(p['url']); p['duplicate_cluster']=f'C{cid+1:04}'; p['duplicate_reason']=reason
    assignments[p['url']]=p
mentions=[]
for p in rows:
    # Link destinations are not a substitute for visible message text.
    txt=re.sub(r'https?://\S+','',p['text']); head=txt.splitlines()[0] if txt.splitlines() else ''
    spans=[(entity,a,hit.start(),hit.end()) for entity,ps in patterns.items() for a,pat in zip(aliases[entity],ps) for hit in pat.finditer(txt)]
    for entity,ps in patterns.items():
        hits=sorted({a for e,a,start,end in spans if e==entity and not any(e2!=e and s2<=start and e2end>=end and e2end-s2>end-start for e2,a2,s2,e2end in spans)})
        if not hits: continue
        role='list' if p['is_stock_list'] else ('headline' if any(pat.search(head) for pat in ps) else 'body')
        mentions.append({'entity':entity,'scope':'other_unverified_listing' if entity in other else 'stock_candidate','channel':p['channel'],'post_id':p['id'],'url':p['url'],'datetime_kst':p['datetime_kst'],'role':role,'pin_notice':p['is_pin_notice'],'cluster':p['duplicate_cluster'],'matched_aliases':'|'.join(hits)})
summary=[]
for entity in aliases:
    mm=[m for m in mentions if m['entity']==entity]
    if not mm: continue
    summary.append({'entity':entity,'scope':mm[0]['scope'],'post_mentions':len(mm),'non_pin_post_mentions':sum(not m['pin_notice'] for m in mm),'text_clusters':len({m['cluster'] for m in mm}),'channels':len({m['channel'] for m in mm}),'headline_posts':sum(m['role']=='headline' and not m['pin_notice'] for m in mm),'list_posts':sum(m['role']=='list' for m in mm),**{ch:sum(m['channel']==ch for m in mm) for ch in CHANNELS}})
summary.sort(key=lambda x:(-x['post_mentions'],x['entity']))
def write_csv(name,items):
    with (D/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(items[0])); w.writeheader(); w.writerows(items)
write_csv('mentions.csv',mentions); write_csv('ranking.csv',summary)
(D/'entities.json').write_text(json.dumps(aliases,ensure_ascii=False,indent=2),encoding='utf-8')
(D/'posts_annotated.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
(D/'duplicate_clusters.json').write_text(json.dumps([{'cluster':f'C{i+1:04}','urls':v} for i,v in enumerate(clusters) if len(v)>1],ensure_ascii=False,indent=2),encoding='utf-8')
assert len({(m['entity'],m['url']) for m in mentions})==len(mentions)
meta=json.loads((D/'collection.json').read_text(encoding='utf-8'))
assert all(meta['start_kst']<=p['datetime_kst']<meta['end_exclusive_kst'] for p in rows)
assert len({p['url'] for p in rows})==len(rows)
assert all(x['text_clusters']<=x['post_mentions'] for x in summary)
print(json.dumps({'posts':len(rows),'mentions':len(mentions),'entities_found':len(summary),'duplicate_groups':sum(len(v)>1 for v in clusters),'nonempty_text_posts':sum(bool(p['text']) for p in rows),'top':summary[:20]},ensure_ascii=False,indent=2))
daily=Counter((m['entity'],m['datetime_kst'][:10],m['channel']) for m in mentions)
write_csv('daily_mentions.csv',[{'entity':e,'date_kst':d,'channel':c,'post_mentions':n} for (e,d,c),n in sorted(daily.items())])

import json,csv,hashlib,re,os
from pathlib import Path
from collections import Counter
from bs4 import BeautifulSoup
R=Path(__file__).resolve().parent; D=Path(os.environ.get('TELEGRAM_DATA_DIR',str(R/'data'))).resolve()
CHANNELS=[c['id'] for c in json.loads((R/('channels.json' if (R/'channels.json').exists() else 'channels.example.json')).read_text(encoding='utf-8'))]
read=lambda n:json.loads((D/n).read_text(encoding='utf-8'))
table=lambda n:list(csv.DictReader((D/n).open(encoding='utf-8-sig')))
posts=read('posts_annotated.json'); mentions=table('mentions.csv'); ranking=table('ranking.csv'); daily=table('daily_mentions.csv'); meta=read('collection.json')
checks={}
checks['unique_message_urls']=len({p['url'] for p in posts})==len(posts)
checks['only_requested_period']=all(meta['start_kst']<=p['datetime_kst']<meta['end_exclusive_kst'] for p in posts)
checks['once_per_entity_per_post']=len({(m['entity'],m['url']) for m in mentions})==len(mentions)
counts=Counter(m['entity'] for m in mentions)
checks['ranking_reconciles']=all(counts[s['entity']]==int(s['post_mentions']) for s in ranking)
checks['channel_counts_reconcile']=all(sum(int(s.get(c,0)) for c in CHANNELS)==int(s['post_mentions']) for s in ranking)
checks['daily_total_reconciles']=sum(int(x['post_mentions']) for x in daily)==len(mentions)
checks['all_http_success']=all(p['status']==200 for c in meta['channels'] for p in c['pages'])
checks['coverage_status_honest']=all(not r.get('coverage_complete') or bool(r.get('earliest_retrieved') and r['earliest_retrieved']<r['start_kst']) for c in meta['channels'] for r in c.get('coverage_ranges',[{**c,'start_kst':meta['start_kst']}]))
checks['configured_channels_present']=set(c['channel'] for c in meta['channels'])<=set(CHANNELS)
checks['channel_period_totals']=all(sum(p['channel']==c['channel'] for p in posts)==c['period_posts'] for c in meta['channels'])
urls={p['url'] for p in posts}
checks['issue_sources_in_collection']=all(u in urls for i in read('issues.json') for u in i['links'])
pattern_source=(R/'analyze.py').read_text(encoding='utf-8').split('def pattern(a):',1)[1].split('patterns=',1)[0]
namespace={'re':re}; exec('def pattern(a):'+pattern_source,namespace)
p=namespace['pattern']
checks['name_boundaries']=not p('테스').search('테스트 어드반테스트') and not p('비에이치').search('비에이치아이') and bool(p('삼성전자').search('삼성전자는'))
snapshot_ids=set()
for path in D.rglob('*.html'):
    soup=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
    snapshot_ids.update('https://t.me/'+node['data-post'] for node in soup.select('.tgme_widget_message[data-post]'))
checks['saved_text_hashes']=all(hashlib.sha256(p['text'].encode()).hexdigest()==p['text_sha256'] for p in posts)
if not meta.get('packaged_sample'): checks['posts_present_in_html']=urls<=snapshot_ids
manifest=[{'file':str(f.relative_to(R)).replace('\\','/'),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size} for f in sorted(D.rglob('*')) if f.is_file() and f.name not in ['manifest.json','verification.json']]
(D/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
result={'all_passed':all(checks.values()),'checks':checks,'period_posts':len(posts),'entity_post_mentions':len(mentions),'entities_with_mentions':len(ranking),'html_pages':len(list(D.rglob('*.html')))}
(D/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2)); assert result['all_passed']

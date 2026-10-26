"""Queries over the auditable Telegram sample; no inferred market data."""
import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from app import channel_manager
from app import issues as issue_engine

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'


def load():
    if DATA==ROOT/'data' and not (DATA/'posts_annotated.json').exists():
        DATA.mkdir(parents=True,exist_ok=True)
        for f in (ROOT/'sample_data').iterdir():
            if f.is_file() and not (DATA/f.name).exists(): shutil.copy2(f,DATA/f.name)
    posts = json.loads((DATA / 'posts_annotated.json').read_text(encoding='utf-8'))
    with (DATA / 'mentions.csv').open(encoding='utf-8-sig', newline='') as f:
        mentions = list(csv.DictReader(f))
    for m in mentions:
        m['pin_notice'] = m['pin_notice'] == 'True'
    issue_index=issue_engine.index(posts,mentions,DATA/'issue_index.json' if DATA==ROOT/'data' else None)
    return {'posts': posts, 'mentions': mentions,
            'issue_index':issue_index,
            'meta': json.loads((DATA / 'collection.json').read_text(encoding='utf-8')),
            'issues': json.loads((DATA / 'issues.json').read_text(encoding='utf-8'))}


def select(data, start, end, channels, exclude_pins, exclude_lists, scope):
    posts = [p for p in data['posts'] if start <= p['datetime_kst'][:10] <= end and p['channel'] in channels]
    urls = {p['url'] for p in posts}
    mentions = [m for m in data['mentions'] if m['url'] in urls
                and not (exclude_pins and m['pin_notice'])
                and not (exclude_lists and m['role'] == 'list')
                and (scope == 'all' or m['scope'] == 'stock_candidate')]
    return posts, mentions


def aggregate(data, filters, focus=None):
    posts, mentions = select(data, **{k: filters[k] for k in ['start', 'end', 'channels', 'exclude_pins', 'exclude_lists', 'scope']})
    grouped = defaultdict(list)
    for m in mentions:
        grouped[m['entity']].append(m)
    ranking = []
    for entity, mm in grouped.items():
        raw = len(mm)
        clusters = len({m['cluster'] for m in mm})
        count = clusters if filters['mode'] == 'clusters' else raw
        ranking.append({'entity': entity, 'scope': mm[0]['scope'], 'count': count, 'raw': raw,
                        'clusters': clusters, 'channel_count': len({m['channel'] for m in mm}),
                        'channels': {ch: sum(m['channel'] == ch for m in mm) for ch in filters['channels']},
                        'headline': sum(m['role'] == 'headline' for m in mm), 'list': sum(m['role'] == 'list' for m in mm),
                        'frequency_pct': round(100 * raw / len(posts), 1) if posts else 0})
    ranking.sort(key=lambda s: (-s['count'], -s['raw'], s['entity']))
    names = [focus] if focus else [r['entity'] for r in ranking[:5]]
    dates = []
    cursor = date.fromisoformat(filters['start'])
    while cursor <= date.fromisoformat(filters['end']):
        dates.append(cursor.isoformat()); cursor += timedelta(days=1)
    timeline = []
    known_start = data['meta']['start_kst'][:10]
    known_end = data['meta']['end_exclusive_kst'][:10]
    for name in names:
        mm = sorted(grouped.get(name, []), key=lambda m: m['datetime_kst'])
        if filters['mode'] == 'clusters':
            seen = set()
            mm = [m for m in mm if m['cluster'] not in seen and not seen.add(m['cluster'])]
        counts = Counter(m['datetime_kst'][:10] for m in mm)
        timeline.append({'entity': name, 'values': [counts[d] if known_start <= d < known_end else None for d in dates]})
    visible = {m['url'] for m in mentions}
    index=data.get('issue_index') or issue_engine.index(data['posts'],data['mentions'])
    issues=issue_engine.select(index,mentions,focus)
    manual_issues = []
    for issue in data['issues']:
        # A saved explanation stays attached to ALL of its original evidence; never relink it.
        supporting={m['url'] for m in mentions if (m['entity']==focus if focus else m['entity'] in issue['entities'])}
        if issue['links'] and set(issue['links'])<=supporting and (not focus or focus in issue['entities']):
            manual_issues.append({**issue,'kind':'saved_manual','is_ai':False})
    channel_summary = []
    warnings=[]
    def covered(ch,d):
        c=next((c for c in data['meta']['channels'] if c['channel']==ch),None)
        return bool(c and any(r.get('coverage_complete') and r['start_kst'][:10]<=d<r['end_exclusive_kst'][:10] for r in channel_manager.coverage_ranges(data['meta'],c)))
    for ch in filters['channels']:
        pp = [p for p in posts if p['channel'] == ch]
        mm = [m for m in mentions if m['channel'] == ch]
        coverage = next((c for c in data['meta']['channels'] if c['channel']==ch),{})
        missing=[d for d in dates if not covered(ch,d)]
        if missing: warnings.append({'channel':ch,'missing_dates':missing,'message':f'{ch}: 선택 기간 중 {len(missing)}일의 수집 경계를 확인하지 못했습니다.'})
        registered={c['id']:c['name'] for c in channel_manager.channels()}
        channel_summary.append({'id': ch, 'name': coverage.get('actual_name') or registered.get(ch,ch), 'posts': len(pp),
                                'coverage_complete': not missing, 'missing_dates':missing,
                                'last_attempt_complete':coverage.get('coverage_complete',False),
                                'stop_reason': coverage.get('stop_reason','unknown'),
                                'collected_at_utc': coverage.get('finished_at_utc'),
                                'text_posts': sum(bool(p['text']) for p in pp),
                                'forwarded': sum(bool(p['forwarded_from']) for p in pp),
                                'pins': sum(p['is_pin_notice'] for p in pp),
                                'entities': len({m['entity'] for m in mm}),
                                'first': min((p['datetime_kst'] for p in pp), default=None),
                                'last': max((p['datetime_kst'] for p in pp), default=None)})
    for line in timeline:
        line['values']=[v if v or all(covered(ch,d) for ch in filters['channels']) else None for d,v in zip(dates,line['values'])]
    return {'filters': filters, 'meta': data['meta'], 'coverage_warnings':warnings,'stats': {'posts': len(posts),
            'text_posts': sum(bool(p['text']) for p in posts), 'entities': len(ranking),
            'entity_mentions': len(mentions), 'duplicate_groups': sum(n > 1 for n in Counter(p['duplicate_cluster'] for p in posts).values()),
            'counted_posts': len(visible)}, 'ranking': ranking, 'dates': dates,
            'timeline': timeline, 'issues': issues, 'manual_issues':manual_issues,
            'issue_state':{'status':'ready' if issues else 'empty','kind':'rule_evidence',
                           'signature':index['signature'],'generated_at_utc':index['generated_at_utc'],
                           'latest_source_kst':max((i['latest_datetime_kst'] for i in issues),default=None),
                           'shown_entities':len(issues),'max_entities':12,'max_sources_per_entity':3},
            'channels': channel_summary}


def explore(data, filters, query='', entity='', kind='all', page=1, page_size=20):
    posts, mentions = select(data, **{k: filters[k] for k in ['start', 'end', 'channels', 'exclude_pins', 'exclude_lists', 'scope']})
    byurl = defaultdict(list)
    for m in mentions:
        byurl[m['url']].append(m)
    groups = Counter(p['duplicate_cluster'] for p in posts)
    results = []
    for p in sorted(posts, key=lambda x: x['datetime_kst'], reverse=True):
        mm = byurl[p['url']]
        if filters['exclude_pins'] and p['is_pin_notice']: continue
        if filters['exclude_lists'] and p.get('is_stock_list',False): continue
        if entity and not any(m['entity'] == entity for m in mm): continue
        if query and query.casefold() not in (p['text'] + ' '.join(m['entity'] for m in mm)).casefold(): continue
        if kind == 'duplicates' and groups[p['duplicate_cluster']] < 2: continue
        if kind == 'forwarded' and not p['forwarded_from']: continue
        if kind == 'list' and not any(m['role'] == 'list' for m in mm): continue
        results.append({**p, 'text': p['text'][:240], 'entities': [m['entity'] for m in mm],
                        'list': any(m['role'] == 'list' for m in mm), 'duplicate_count': groups[p['duplicate_cluster']]})
    start = (page - 1) * page_size
    return {'total': len(results), 'page': page, 'page_size': page_size, 'items': results[start:start+page_size]}

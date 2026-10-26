"""Auditable, snapshot-keyed evidence groups. No generated claims or implicit AI calls."""
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone

VERSION=1


def signature(posts,mentions):
    source=[(p['url'],p['channel'],p['datetime_kst'],p['text'],p['duplicate_cluster']) for p in posts]
    return hashlib.sha256(json.dumps([VERSION,source,mentions],ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def excerpt(text,aliases,limit=220):
    # Preserve a contiguous piece of the actual body, near the matched company name.
    folded=text.casefold()
    positions=[folded.find(a.casefold()) for a in aliases if a and a.casefold() in folded]
    position=min(positions,default=0)
    start=text.rfind('\n',0,position)+1
    if position-start>80: start=max(0,position-60)
    return text[start:start+limit],start+limit<len(text)


def index(posts,mentions,path=None):
    digest=signature(posts,mentions)
    if path:
        try:
            cached=json.loads(path.read_text(encoding='utf-8'))
            if cached.get('version')==VERSION and cached.get('signature')==digest and isinstance(cached.get('by_entity'),dict):
                return cached
        except (OSError,ValueError): pass
    lookup={p['url']:p for p in posts}
    entries=defaultdict(list)
    for m in mentions:
        p=lookup.get(m['url'])
        if not p or not p['text'].strip(): continue
        quote,truncated=excerpt(p['text'],m.get('matched_aliases',m['entity']).split('|'))
        entries[m['entity']].append({'url':p['url'],'channel':p['channel'],'datetime_kst':p['datetime_kst'],
            'cluster':p['duplicate_cluster'],'excerpt':quote,'excerpt_truncated':truncated,'role':m['role']})
    result={'version':VERSION,'signature':digest,'generated_at_utc':datetime.now(timezone.utc).isoformat(),
            'by_entity':dict(entries)}
    if path:
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(path)
        except OSError: pass  # The current in-memory index still serves the exact snapshot.
    return result


def select(index,mentions,focus=None,limit=12):
    eligible=defaultdict(set)
    for m in mentions:
        if not focus or m['entity']==focus: eligible[m['entity']].add(m['url'])
    groups=[]
    for entity,urls in eligible.items():
        sources=[]; seen=set()
        for source in sorted(index['by_entity'].get(entity,[]),key=lambda p:(p['datetime_kst'],p['url']),reverse=True):
            if source['url'] not in urls or source['cluster'] in seen: continue
            seen.add(source['cluster']); sources.append(source)
        if not sources: continue
        chosen=sources[:3]
        groups.append({'entities':[entity],'kind':'rule_evidence','is_ai':False,
                       'issue':chosen[0]['excerpt'],'links':[p['url'] for p in chosen],
                       'sources':chosen,'source_count':len(sources),'shown_source_count':len(chosen),
                       'latest_datetime_kst':chosen[0]['datetime_kst']})
    groups.sort(key=lambda g:(g['latest_datetime_kst'],g['source_count'],g['entities'][0]),reverse=True)
    # Keep a single multi-company post from occupying the whole section.
    chosen=[]; primary=defaultdict(int)
    for group in groups:
        url=group['links'][0]
        if primary[url]>=2 and not focus: continue
        primary[url]+=1; chosen.append(group)
        if len(chosen)>=limit: break
    return chosen

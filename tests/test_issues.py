import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import issues, service, channel_manager
import app.main as main


class IssueEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.posts=[]; self.mentions=[]
        self.add(1,'alpha_public','2026-10-06','기존기업','기존기업 초기 이슈 원문')
        self.add(2,'alpha_public','2026-10-25','신규기업','신규기업 신규 공급계약 검토라는 채널 주장')
        self.add(3,'beta_public','2026-10-26','신규기업','신규기업 최근 실적 전망이라는 채널 주장')
        self.add(4,'inactive_public','2026-10-26','신규기업','신규기업 비활성 채널의 원문')
        self.add(5,'alpha_public','2026-10-26','목록기업','목록기업 시세 목록',role='list')
        self.add(6,'alpha_public','2026-10-26','고정기업','고정기업 고정 알림',pin=True)
        self.add(7,'alpha_public','2026-10-26','비상장기업','비상장기업 언급',scope='other_unverified_listing')
        self.data={'posts':self.posts,'mentions':self.mentions,
                   'meta':{'channels':[],'start_kst':'2026-10-01','end_exclusive_kst':'2026-11-01','collected_at_utc':'2026-10-26T14:00:00+00:00'},
                   'issues':[{'entities':['기존기업'],'issue':'초기에 저장된 수동 설명','links':['https://t.me/alpha_public/1']}],
                   'issue_index':issues.index(self.posts,self.mentions)}
        p=patch.object(channel_manager,'channels',return_value=[{'id':ch,'name':ch,'enabled':ch!='inactive_public'} for ch in ('alpha_public','beta_public','inactive_public')])
        p.start(); self.addCleanup(p.stop)
        p=patch.object(main,'snapshot',self.data); p.start(); self.addCleanup(p.stop)
        self.client=TestClient(main.app)

    def add(self,id,channel,day,entity,text,role='body',pin=False,scope='stock_candidate',cluster=None):
        url=f'https://t.me/{channel}/{id}'; stamp=day+'T10:00:00+09:00'; cluster=cluster or f'C{id}'
        self.posts.append({'id':id,'url':url,'channel':channel,'datetime_kst':stamp,'text':text,
                           'duplicate_cluster':cluster,'is_pin_notice':pin,'is_stock_list':role=='list','forwarded_from':None})
        self.mentions.append({'entity':entity,'url':url,'channel':channel,'datetime_kst':stamp,'cluster':cluster,
                              'scope':scope,'role':role,'pin_notice':pin,'matched_aliases':entity})

    def query(self,**params):
        response=self.client.get('/api/dashboard',params={'start':'2026-10-20','end':'2026-10-26',**params})
        self.assertEqual(response.status_code,200)
        return response.json()

    def test_latest_evidence_uses_exact_selected_sources_not_old_manual_text(self):
        data=self.query(exclude_lists='true')
        self.assertEqual(data['issues'][0]['entities'],['신규기업'])
        self.assertEqual(data['manual_issues'],[])
        for group in data['issues']:
            self.assertEqual(group['kind'],'rule_evidence'); self.assertFalse(group['is_ai'])
            for source in group['sources']:
                self.assertIn(source['channel'],('alpha_public','beta_public'))
                self.assertGreaterEqual(source['datetime_kst'][:10],'2026-10-20')
                original=next(p for p in self.posts if p['url']==source['url'])
                self.assertIn(source['excerpt'],original['text'])
        self.assertNotIn('초기에 저장된 수동 설명',json.dumps(data['issues'],ensure_ascii=False))

    def test_channel_date_entity_and_empty_results(self):
        data=self.query(channels='alpha_public',focus='신규기업')
        self.assertEqual(data['issues'][0]['links'],['https://t.me/alpha_public/2'])
        data=self.query(start='2026-10-26',channels='beta_public',focus='신규기업')
        self.assertEqual(data['issues'][0]['links'],['https://t.me/beta_public/3'])
        self.assertEqual(self.query(focus='존재하지않는기업')['issues'],[])
        empty=self.query(start='2026-09-01',end='2026-09-07')
        self.assertEqual(empty['issues'],[]); self.assertEqual(empty['manual_issues'],[])
        self.assertEqual(empty['issue_state']['status'],'empty')
        self.assertEqual(self.client.get('/api/dashboard?channels=inactive_public').status_code,422)

    def test_pin_list_and_scope_filters_apply_to_every_issue_source(self):
        data=self.query(exclude_lists='true')
        entities={g['entities'][0] for g in data['issues']}
        self.assertEqual(entities,{'신규기업'})
        data=self.query(exclude_pins='false',scope='all')
        self.assertTrue({'목록기업','고정기업','비상장기업'}<={g['entities'][0] for g in data['issues']})

    def test_saved_manual_explanation_keeps_original_evidence_only(self):
        data=self.query(start='2026-10-05',end='2026-10-11',channels='alpha_public')
        self.assertEqual(data['manual_issues'][0]['links'],['https://t.me/alpha_public/1'])
        self.assertEqual(data['manual_issues'][0]['kind'],'saved_manual')
        self.assertEqual(self.query(start='2026-10-05',end='2026-10-11',channels='beta_public')['manual_issues'],[])

    def test_snapshot_cache_rebuilds_after_new_post_edit_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'issue_index.json'
            first=issues.index(self.posts,self.mentions,path)
            again=issues.index(self.posts,self.mentions,path)
            self.assertEqual(first,again)
            self.add(8,'beta_public','2026-10-26','새기업','새기업 새로운 원문')
            updated=issues.index(self.posts,self.mentions,path)
            self.assertNotEqual(first['signature'],updated['signature'])
            self.assertIn('새기업',updated['by_entity'])
            self.posts[-1]['text']='새기업 수정된 최신 본문'
            edited=issues.index(self.posts,self.mentions,path)
            self.assertNotEqual(updated['signature'],edited['signature'])
            self.assertIn('수정된',edited['by_entity']['새기업'][0]['excerpt'])
            path.write_text('invalid json',encoding='utf-8')
            self.assertEqual(issues.index(self.posts,self.mentions,path)['signature'],edited['signature'])

    def test_same_body_is_deduplicated_after_applying_filter(self):
        self.add(9,'beta_public','2026-10-26','신규기업','신규기업 복제된 본문',cluster='C2')
        index=issues.index(self.posts,self.mentions)
        all_sources=issues.select(index,self.mentions,focus='신규기업')[0]['sources']
        self.assertEqual(len({p['cluster'] for p in all_sources}),len(all_sources))
        restricted=[m for m in self.mentions if m['channel']=='alpha_public' and m['entity']=='신규기업']
        self.assertEqual(issues.select(index,restricted,'신규기업')[0]['links'],['https://t.me/alpha_public/2'])

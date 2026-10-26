import json
import tempfile
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from app import ai, service
from app.main import app, filters


class AITests(unittest.TestCase):
    def setUp(self):
        fixture=Path(__file__).resolve().parents[1]/'sample_data'
        data_patch=patch.object(service,'DATA',fixture); data_patch.start(); self.addCleanup(data_patch.stop)
        from app import channel_manager
        clock_patch=patch.object(channel_manager,'today_kst',return_value=date(2026,10,11)); clock_patch.start(); self.addCleanup(clock_patch.stop)
        data=service.load()
        channel_patch=patch.object(channel_manager,'channels',return_value=[{'id':c['channel'],'name':c['actual_name'],'enabled':True} for c in data['meta']['channels']]); channel_patch.start(); self.addCleanup(channel_patch.stop)
        self.client=TestClient(app)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache=patch.object(ai,'CACHE',Path(self.temp.name)/'cache.json')
        self.cache.start(); self.addCleanup(self.cache.stop)
        self.post={'url':'https://t.me/sample/1','channel':'sample','datetime_kst':'2026-10-08T12:00:00+09:00','text':'공개 본문 테스트'}
        self.result={'one_line_summary':'채널의 주장 요약','summary_lines':['첫째','둘째','셋째'],
                     'investment_points':['본문 근거'],'financial_outlook':'본문에 명시 없음','risk_factors':['불확실성']}

    def response(self,result=None):
        r=Mock(); r.json.return_value={'response':json.dumps(result or self.result)}; return r

    def test_real_generation_contract_and_cache(self):
        with patch.object(ai,'status',return_value={'available':True,'models':['test'],'default_model':'test'}), patch.object(ai.requests,'post',return_value=self.response()) as call:
            first=ai.generate([self.post],'test','post')
            second=ai.generate([self.post],'test','post')
            self.assertFalse(first['cached']); self.assertTrue(second['cached'])
            self.assertEqual(call.call_count,1)
            self.assertEqual(first['sources'][0]['url'],self.post['url'])
            ai.generate([self.post],'test','post',refresh=True)
            self.assertEqual(call.call_count,2)
            changed={**self.post,'text':'수정된 본문'}
            ai.generate([changed],'test','post'); self.assertEqual(call.call_count,3)

    def test_unavailable_has_no_rule_based_fallback(self):
        with patch.object(ai,'status',return_value={'available':False,'message':'연결 불가'}):
            with self.assertRaises(ai.AIError): ai.generate([self.post],'test','post')
        self.assertFalse(Path(ai.CACHE).exists())

    def test_invalid_ai_json_is_rejected_not_cached(self):
        with patch.object(ai,'status',return_value={'available':True,'models':['test']}), patch.object(ai.requests,'post',return_value=self.response({'one_line_summary':'불완전'})):
            with self.assertRaises(ai.AIError) as ctx: ai.generate([self.post],'test','post')
            self.assertEqual(ctx.exception.status,502)
            self.assertFalse(Path(ai.CACHE).exists())

    def test_empty_text_and_missing_post(self):
        with self.assertRaises(ai.AIError) as ctx: ai.generate([{**self.post,'text':''}],None,'post')
        self.assertEqual(ctx.exception.status,422)
        self.assertEqual(self.client.post('/api/post/unknown/1/ai-summary',json={}).status_code,404)

    def test_brief_sampling_balances_channels_and_filters(self):
        data=service.load()
        sample,total=ai.brief_posts(data,filters())
        self.assertEqual(len(sample),12); self.assertGreater(total,12)
        self.assertEqual(len({p['channel'] for p in sample}),8)
        self.assertEqual(len({p['duplicate_cluster'] for p in sample}),12)
        sample,total=ai.brief_posts(data,filters(channels='hanasmallcap',start='2026-10-08',end='2026-10-08'),'바이오비쥬')
        self.assertEqual(total,1); self.assertEqual(sample[0]['id'],1207)
        sample,total=ai.brief_posts(data,filters(channels='hanasmallcap',start='2026-10-09',end='2026-10-09'))
        self.assertEqual(sample,[])

    def test_remote_origin_and_remote_endpoint_rejected(self):
        self.assertEqual(self.client.post('/api/ai/brief',json={},headers={'Origin':'https://unrelated.example'}).status_code,403)
        with patch.object(ai,'BASE','https://external.example'):
            with self.assertRaises(ai.AIError): ai.local_endpoint()

    def test_ai_post_endpoint_uses_full_saved_body(self):
        with patch.object(ai,'generate',return_value={'generated':True}) as call:
            r=self.client.post('/api/post/hanasmallcap/1207/ai-summary',json={'model':'test'})
            self.assertEqual(r.status_code,200)
            self.assertEqual(call.call_args.args[0][0]['id'],1207)
            self.assertGreater(len(call.call_args.args[0][0]['text']),240)

    def test_ai_timeout_is_explicit(self):
        with patch.object(ai,'status',return_value={'available':True,'models':['test']}), patch.object(ai.requests,'post',side_effect=ai.requests.Timeout):
            with self.assertRaises(ai.AIError) as ctx: ai.generate([self.post],'test','post')
            self.assertEqual(ctx.exception.status,504)


if __name__=='__main__': unittest.main()

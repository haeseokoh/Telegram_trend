import csv
import io
import unittest
import json
from pathlib import Path
from datetime import date
from unittest.mock import patch
from app import service, channel_manager
import app.main as main_module
from fastapi.testclient import TestClient
from app.main import app


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Immutable regression sample; user-managed channel settings remain untouched.
        fixture=Path(__file__).resolve().parents[1]/'sample_data'
        cls.data_patch=patch.object(service,'DATA',fixture); cls.data_patch.start()
        data=service.load()
        cls.registry_patch=patch.object(channel_manager,'channels',return_value=[{'id':c['channel'],'name':c['actual_name'],'enabled':True} for c in data['meta']['channels']]); cls.registry_patch.start()
        cls.snapshot_patch=patch.object(main_module,'snapshot',data); cls.snapshot_patch.start()
        cls.client = TestClient(app)
        cls.clock_patch=patch.object(channel_manager,'today_kst',return_value=date(2026,10,11)); cls.clock_patch.start()
        cls.busy_patch=patch.object(channel_manager,'is_busy',return_value=False); cls.busy_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.busy_patch.stop()
        cls.clock_patch.stop()
        cls.snapshot_patch.stop(); cls.registry_patch.stop(); cls.data_patch.stop()

    def dashboard(self, **params):
        params.setdefault('channels','infomarketopen,hslpartners,eqmirae')
        response = self.client.get('/api/dashboard', params=params)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def find(self, data, entity):
        return next(r for r in data['ranking'] if r['entity'] == entity)

    def test_saved_sample_totals(self):
        d = self.dashboard()
        self.assertEqual(d['stats']['posts'], 443)
        self.assertEqual(d['stats']['text_posts'], 437)
        self.assertEqual([c['posts'] for c in d['channels']], [417,22,4])
        self.assertEqual(self.find(d, '엔비디아')['raw'], 42)
        self.assertEqual(self.find(d, '마이크론')['raw'], 22)
        self.assertEqual(self.find(d, 'TSMC')['raw'], 20)
        self.assertNotIn('SpaceX', [r['entity'] for r in d['ranking']])

    def test_pin_notice_changes_samsung_only_when_requested(self):
        self.assertEqual(self.find(self.dashboard(), '삼성전자')['raw'], 13)
        self.assertEqual(self.find(self.dashboard(exclude_pins='false'), '삼성전자')['raw'], 14)

    def test_dedup_timeline_total(self):
        d = self.dashboard(mode='clusters', focus='엔비디아')
        self.assertEqual(self.find(d, '엔비디아')['count'], 36)
        self.assertEqual(sum(d['timeline'][0]['values']), 36)
        for row in d['ranking']:
            self.assertLessEqual(row['count'],row['raw'])

    def test_cluster_dates_move_inside_selected_window(self):
        d = self.dashboard(mode='clusters',start='2026-10-08',end='2026-10-09',focus='마이크론')
        self.assertEqual(d['dates'],['2026-10-08','2026-10-09'])
        self.assertEqual(sum(d['timeline'][0]['values']),self.find(d,'마이크론')['clusters'])

    def test_channel_selection_and_list_exclusion(self):
        q = self.dashboard(channels='eqmirae')
        self.assertEqual(q['stats']['posts'],4)
        self.assertEqual(self.find(q,'파두')['raw'],2)
        d = self.dashboard(channels='eqmirae',exclude_lists='true')
        self.assertEqual({r['entity'] for r in d['ranking']},{'파두','한솔케미칼'})
        self.assertTrue(all(r['raw']==1 for r in d['ranking']))
        self.assertEqual(d['stats']['posts'],4)  # denominator remains all collected posts

    def test_other_companies_explicit_opt_in(self):
        d = self.dashboard(scope='all')
        self.assertEqual(self.find(d,'SpaceX')['raw'],57)
        self.assertEqual(self.find(d,'SpaceX')['channel_count'],2)

    def test_date_empty_no_invented_counts(self):
        d = self.dashboard(start='2026-09-01',end='2026-09-07')
        self.assertEqual(d['stats']['posts'],0)
        self.assertEqual(d['ranking'],[])
        self.assertEqual(d['issues'],[])

    def test_uncollected_dates_are_not_zero(self):
        d = self.dashboard(start='2026-10-04',end='2026-10-12',focus='엔비디아')
        values = d['timeline'][0]['values']
        self.assertIsNone(values[0])
        self.assertIsNone(values[-1])
        self.assertEqual(sum(v for v in values if v is not None),42)

    def test_invalid_filters(self):
        for params in [{'start':'bad'},{'start':'2026-10-12','end':'2026-10-01'},{'channels':''},{'channels':'unknown'},{'mode':'surge'},{'scope':'bad'},{'exclude_pins':'yes'}]:
            self.assertEqual(self.client.get('/api/dashboard',params=params).status_code,422)

    def test_entity_explorer_and_detail(self):
        data=self.client.get('/api/posts',params={'entity':'엔비디아','page_size':100,'channels':'infomarketopen,hslpartners,eqmirae'}).json()
        self.assertEqual(data['total'],42)
        self.assertEqual(len(data['items']),42)
        self.assertTrue(all('엔비디아' in p['entities'] for p in data['items']))
        p=data['items'][0]
        detail=self.client.get(f"/api/post/{p['channel']}/{p['id']}").json()
        self.assertEqual(detail['url'],p['url'])
        self.assertIn('엔비디아',[m['entity'] for m in detail['mentions']])
        self.assertEqual(self.client.get('/api/post/unknown/1').status_code,404)

    def test_duplicate_and_search_filters(self):
        data=self.client.get('/api/posts',params={'kind':'duplicates','query':'HBM','page_size':100}).json()
        self.assertGreater(data['total'],0)
        self.assertTrue(all(p['duplicate_count']>1 for p in data['items']))
        first=self.client.get('/api/posts',params={'page':1}).json()
        second=self.client.get('/api/posts',params={'page':2}).json()
        self.assertFalse({p['url'] for p in first['items']} & {p['url'] for p in second['items']})

    def test_filtered_csv_export(self):
        r=self.client.get('/api/export',params={'channels':'eqmirae','exclude_lists':'true'})
        self.assertEqual(r.status_code,200)
        self.assertTrue(r.content.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))))
        self.assertEqual({row[0] for row in rows[1:]},{'파두','한솔케미칼'})
        self.assertTrue(all(row[1]=='1' for row in rows[1:]))

    def test_reload_same_origin_and_static(self):
        self.assertEqual(self.client.post('/api/reload').status_code,200)
        self.assertEqual(self.client.post('/api/reload',headers={'Origin':'https://unrelated.example'}).status_code,403)
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.get('/static/js/dashboard.js').status_code,200)
        self.assertIn('no-cache',self.client.get('/static/css/app.css').headers['cache-control'])

    def test_eight_channels_and_public_coverage(self):
        d=self.client.get('/api/dashboard').json()
        self.assertEqual(d['stats']['posts'],557)
        self.assertEqual([c['posts'] for c in d['channels']],[417,22,4,14,40,1,10,49])
        self.assertTrue(all(c['coverage_complete'] for c in d['channels']))
        self.assertEqual(len(self.client.get('/api/config').json()['channels']),8)

    def test_added_channel_entities_and_sources(self):
        cases={'sejongdata2013':['LG전자','에코프로비엠'], 'hanasmallcap':['바이오비쥬','신세계인터내셔날','화승엔터프라이즈'], 'Ibks_innovation_research':['펌텍코리아','브이티','NAVER'], 'eng999view':['현대모비스','대한광통신']}
        for ch,entities in cases.items():
            d=self.dashboard(channels=ch)
            for e in entities: self.assertGreater(self.find(d,e)['raw'],0)
            self.assertGreater(len(d['issues']),0)
            self.assertTrue(all(f'/{ch}/' in u for i in d['issues'] for u in i['links']))

    def test_kiwoom_price_lists_and_exclusion(self):
        params={'channels':'kiwoom_semibat','kind':'list','page_size':100}
        lists=self.client.get('/api/posts',params=params).json()
        self.assertEqual(lists['total'],6)
        self.assertTrue(all(p['is_stock_list'] for p in lists['items']))
        self.assertEqual(self.client.get('/api/posts',params={**params,'exclude_lists':'true'}).json()['total'],0)

    def test_new_channel_date_search_and_csv(self):
        params={'channels':'hanasmallcap','start':'2026-10-08','end':'2026-10-08'}
        p=self.client.get('/api/posts',params={**params,'query':'바이오비쥬'}).json()
        self.assertEqual(p['total'],1)
        self.assertEqual(p['items'][0]['id'],1207)
        rows=list(csv.DictReader(io.StringIO(self.client.get('/api/export',params=params).content.decode('utf-8-sig'))))
        self.assertIn('바이오비쥬',{r['종목/기업'] for r in rows})
        self.assertEqual(self.dashboard(**params)['stats']['posts'],1)
        self.assertEqual(self.dashboard(channels='hanasmallcap',start='2026-10-09',end='2026-10-09')['stats']['posts'],0)


if __name__=='__main__':
    unittest.main()

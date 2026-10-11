import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from app import channel_manager as cm, service
from app.main import app


class ChannelManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.data=self.root/'data'; self.data.mkdir()
        for key,value in {'ROOT':self.root,'REGISTRY':self.root/'channels.json','DATA':self.data,'JOBS':self.root/'jobs.json','running':False}.items():
            p=patch.object(cm,key,value); p.start(); self.addCleanup(p.stop)
        cm.save_json(cm.REGISTRY,[{'id':'samplechan','name':'샘플','enabled':True}])
        self.client=TestClient(app)

    def test_telegram_input_and_ssrf_rejection(self):
        for value in ('@SampleChan','https://t.me/SampleChan','https://t.me/s/SampleChan','t.me/SampleChan'):
            self.assertEqual(cm.normalize(value),'samplechan')
        with patch.object(cm.requests,'get') as get:
            for value in ('http://127.0.0.1:11434','https://example.com/a','https://t.me@127.0.0.1/foo','https://t.me:443/foo','https://t.me/+private','https://t.me/joinchat/secret','https://t.me/foo/123','https://t.me/foo?before=1','../data','https://t.me.evil.example/foo'):
                with self.assertRaises(cm.ChannelError): cm.probe(value)
            get.assert_not_called()

    def test_registration_probe_and_case_duplicate(self):
        response=Mock(status_code=200,text='<span class="tgme_channel_info_header_title">공개 채널</span><div class="tgme_widget_message" data-post="newpublic/1"></div>')
        with patch.object(cm.requests,'get',return_value=response) as get:
            r=self.client.post('/api/channels',json={'channel':'https://t.me/NewPublic'})
            self.assertEqual(r.status_code,201)
            self.assertEqual(r.json()['name'],'공개 채널')
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertEqual(self.client.post('/api/channels',json={'channel':'@NEWPUBLIC'}).status_code,409)
        self.assertEqual(len(cm.channels()),2)

    def test_private_redirect_and_network_failure_are_not_registered(self):
        with patch.object(cm.requests,'get',return_value=Mock(status_code=302)):
            self.assertEqual(self.client.post('/api/channels',json={'channel':'privatechan'}).status_code,400)
        with patch.object(cm.requests,'get',side_effect=cm.requests.Timeout):
            self.assertEqual(self.client.post('/api/channels',json={'channel':'privatechan'}).status_code,502)
        self.assertEqual(len(cm.channels()),1)

    def test_disable_is_persistent_and_preserves_data(self):
        source=self.data/'posts.json'; source.write_text('[{"text":"보존"}]',encoding='utf-8'); before=source.read_bytes()
        self.assertEqual(self.client.patch('/api/channels/samplechan',json={'enabled':False}).status_code,200)
        self.assertFalse(cm.channels()[0]['enabled'])
        self.assertFalse(json.loads(cm.REGISTRY.read_text(encoding='utf-8'))[0]['enabled'])
        self.assertEqual(source.read_bytes(),before)
        self.assertEqual(self.client.get('/api/config').json()['channels'],[])
        self.assertEqual(self.client.get('/api/dashboard').json()['stats']['posts'],0)
        self.assertEqual(self.client.get('/api/dashboard?channels=samplechan').status_code,422)
        self.assertEqual(self.client.patch('/api/channels/samplechan',json={'enabled':True}).status_code,200)

    def test_collection_is_background_and_conflicts_are_explicit(self):
        release=threading.Event(); entered=threading.Event()
        def fake_worker(job,callback):
            entered.set(); release.wait(3)
            cm.update_job(job['id'],status='completed')
            with cm.job_lock: cm.running=False
        with patch.object(cm,'worker',side_effect=fake_worker):
            start=time.monotonic()
            r=self.client.post('/api/channels/samplechan/collect',json={'start':'2026-10-05','end':'2026-10-11'})
            self.assertEqual(r.status_code,202); self.assertLess(time.monotonic()-start,1)
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.client.post('/api/channels/samplechan/collect',json={'start':'2026-10-05','end':'2026-10-11'}).status_code,409)
            self.assertEqual(self.client.get('/api/channels').status_code,200)
            release.set()
            for _ in range(50):
                if not cm.is_busy(): break
                time.sleep(.01)

    def test_collection_date_and_origin_validation(self):
        for body in ({'start':'bad','end':'2026-10-11'},{'start':'2026-10-12','end':'2026-10-11'},{'start':'2020-01-01','end':'2026-10-11'},{'start':'2099-01-01','end':'2099-01-02'}):
            self.assertEqual(self.client.post('/api/channels/samplechan/collect',json=body).status_code,422)
        self.assertEqual(self.client.post('/api/channels',json={'channel':'otherchan'},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.patch('/api/channels/unknown',json={'enabled':True}).status_code,404)

    def test_uncollected_dates_are_unknown_for_registered_channel(self):
        data=service.load()
        f={'start':'2026-10-05','end':'2026-10-11','channels':['samplechan'],'mode':'posts','exclude_pins':True,'exclude_lists':False,'scope':'stocks'}
        result=service.aggregate(data,f,focus='LG전자')
        self.assertEqual(result['stats']['posts'],0)
        self.assertEqual(result['timeline'][0]['values'],[None]*7)
        self.assertFalse(result['channels'][0]['coverage_complete'])
        self.assertEqual(len(result['coverage_warnings'][0]['missing_dates']),7)

    def test_restart_marks_job_interrupted_and_recovers_publication(self):
        job_id='testjob'
        cm.save_json(cm.JOBS,[{'id':job_id,'status':'analyzing'}])
        backup=self.data/'collection_history'/job_id/'previous_outputs'; backup.mkdir(parents=True)
        (backup/'posts.json').write_text('original',encoding='utf-8')
        (self.data/'posts.json').write_text('partial',encoding='utf-8')
        cm.recover_jobs()
        self.assertEqual((self.data/'posts.json').read_text(encoding='utf-8'),'original')
        self.assertEqual(cm.jobs()[0]['status'],'interrupted')

    def test_live_owner_job_is_not_interrupted_by_another_reader(self):
        import os
        cm.save_json(cm.JOBS,[{'id':'ownedjob','status':'running','owner_pid':os.getpid()}])
        cm.recover_jobs()
        self.assertEqual(cm.jobs()[0]['status'],'running')
        self.assertTrue(cm.is_busy())
        with self.assertRaises(cm.ChannelError) as ctx:
            cm.start_collection('samplechan','2026-10-05','2026-10-11',Mock())
        self.assertEqual(ctx.exception.status,409)

    def test_collection_failure_keeps_existing_snapshot(self):
        original=[{'url':'https://t.me/samplechan/1','channel':'samplechan','id':1,'text':'삼성전자','datetime_kst':'2026-10-06T12:00:00+09:00'}]
        cm.save_json(self.data/'posts.json',original)
        cm.save_json(self.data/'collection.json',{'start_kst':'2026-10-05T00:00:00+09:00','end_exclusive_kst':'2026-10-12T00:00:00+09:00','collected_at_utc':'2026-10-11T03:00:00+00:00','channels':[]})
        job={'id':'failurejob','channel':'samplechan','start':'2026-10-05','end':'2026-10-11','status':'queued'}
        cm.save_json(cm.JOBS,[job]); before=(self.data/'posts.json').read_bytes()
        stat={'channel':'samplechan','retrieved_posts':2,'coverage_complete':True,'stop_reason':'start_boundary_reached','pages':[],
              'earliest_retrieved':'2026-10-04T12:00:00+09:00','finished_at_utc':'2026-10-11T03:00:00+00:00','error':None}
        def fake_collect(channel,first,last,out,progress):
            cm.save_json(out/f'{channel}_all.json',original+[{**original[0],'id':0,'url':'https://t.me/samplechan/0','datetime_kst':'2026-10-04T12:00:00+09:00'}])
            return original,stat
        with patch('collect.collect',side_effect=fake_collect),patch.object(cm.subprocess,'run',return_value=Mock(returncode=1)) as run:
            cm.worker(job,Mock())
            run.assert_called_once()
        self.assertEqual((self.data/'posts.json').read_bytes(),before)
        self.assertEqual(cm.jobs()[0]['status'],'failed')


if __name__=='__main__': unittest.main()

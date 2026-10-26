import json
import csv
from collections import Counter
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class AnalysisRegressionTests(unittest.TestCase):
    def test_full_sample_duplicate_assignments_are_preserved(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            shutil.copy2(root/'sample_data'/'posts.json',target/'posts.json')
            shutil.copy2(root/'sample_data'/'collection.json',target/'collection.json')
            subprocess.run([sys.executable,str(root/'analyze.py')],cwd=root,
                           env={**os.environ,'TELEGRAM_DATA_DIR':directory,'PYTHONIOENCODING':'utf-8'},
                           check=True,capture_output=True,timeout=60)
            actual=json.loads((target/'posts_annotated.json').read_text(encoding='utf-8'))
            expected=json.loads((root/'sample_data'/'posts_annotated.json').read_text(encoding='utf-8'))
            fields=lambda posts:[(p['url'],p['duplicate_cluster'],p['duplicate_reason']) for p in posts]
            self.assertEqual(fields(actual),fields(expected))
            def mentions(path):
                with path.open(encoding='utf-8-sig',newline='') as source:
                    return Counter((m['entity'],m['url'],m['role']) for m in csv.DictReader(source))
            self.assertEqual(mentions(target/'mentions.csv'),mentions(root/'sample_data'/'mentions.csv'))

    def test_percentages_prose_and_sector_lists_do_not_become_companies(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            posts=json.loads((root/'sample_data'/'posts.json').read_text(encoding='utf-8'))
            extra={**posts[0],'channel':'eqmirae','id':999999,'url':'https://t.me/eqmirae/999999',
                   'text':'퀀트 Daily\n(시장 쏠림 지표 상승폭 ↑)\n소프트웨어, 자동차\n(상향 전환)\n2%, 3%\n'}
            posts.append(extra)
            posts.append({**extra,'id':999998,'url':'https://t.me/eqmirae/999998','text':'일반 해설\n2%, 400억 원, 투자 계획을 설명합니다'})
            (target/'posts.json').write_text(json.dumps(posts),encoding='utf-8')
            shutil.copy2(root/'sample_data'/'collection.json',target/'collection.json')
            subprocess.run([sys.executable,str(root/'analyze.py')],cwd=root,
                           env={**os.environ,'TELEGRAM_DATA_DIR':directory,'PYTHONIOENCODING':'utf-8'},
                           check=True,capture_output=True,timeout=60)
            entities=json.loads((target/'entities.json').read_text(encoding='utf-8'))
            for invalid in ('2%','3%','400억 원','투자 계획을 설명합니다','소프트웨어','자동차'):
                self.assertNotIn(invalid,entities)

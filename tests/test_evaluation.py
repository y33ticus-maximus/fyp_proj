import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation import DATASETS, evidence_rows, ground_truth, metrics, model_runs, reviewed_images

class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d1=ROOT/'data/v1_helmet_vest'
        cls.d2=ROOT/'data/v2_boots'
        cls.labels1=reviewed_images(cls.d1)
        cls.labels2=reviewed_images(cls.d2)
        cls.runs,_=model_runs(cls.d1)

    def test_image_counts(self):
        self.assertEqual(len(self.labels1),60)
        self.assertEqual(len(self.labels2),68)
        self.assertEqual(len(list((self.d1/'images').glob('*.jpg'))),60)
        self.assertEqual(len(list((self.d2/'images').glob('*.jpg'))),68)

    def test_image_matches_every_model(self):
        for model,rows in self.runs.items():
            self.assertEqual(len(rows),60,model)
            self.assertTrue(all((self.d1/'images'/name).exists() for name in rows),model)

    def test_llava_overpredicts(self):
        rows=evidence_rows(self.labels1,self.runs['llava:13b'],'overall',('helmet','vest'))
        m=metrics(rows)
        self.assertEqual((m['tp'],m['tn'],m['fp'],m['fn']), (29,0,31,0))

    def test_qwen_metrics(self):
        rows=evidence_rows(self.labels1,self.runs['qwen3.8:27b'],'overall',('helmet','vest'))
        m=metrics(rows)
        self.assertEqual((m['tp'],m['tn'],m['fp'],m['fn'],m['decisive']), (27,31,0,1,59))
        self.assertEqual(m['unclear'],1)

    def test_boots_labels(self):
        from collections import Counter
        counts=Counter(r['verified_boots'] for r in self.labels2)
        self.assertEqual((counts['yes'],counts['no'],counts['unclear']),(26,34,8))

    def test_all_saved_scopes_match_notebook(self):
        import csv
        file=self.d1/'model_comparison.csv'
        with file.open(encoding='utf-8-sig',newline='') as f:
            source=list(csv.DictReader(f))
        for src in source:
            model,scope=src['model'],src['scope']
            rr=evidence_rows(self.labels1,self.runs[model],scope,('helmet','vest'))
            calc=metrics(rr)
            for k in ['tp','tn','fp','fn','scored_decisive']:
                actual=calc['decisive'] if k=='scored_decisive' else calc[k]
                expected=int(float(src[k]))
                self.assertEqual(actual,expected,f'{model}, {scope}, {k}: actual {actual}, expected {expected}')

if __name__=='__main__': unittest.main()

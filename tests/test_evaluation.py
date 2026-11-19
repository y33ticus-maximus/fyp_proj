import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation import DATASETS, evidence_rows, ground_truth, metrics, model_runs, reviewed_images, run_diagnostics

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

    def test_incomplete_perfect_f1_is_not_complete_coverage(self):
        runs,_=model_runs(self.d2)
        report=run_diagnostics(self.labels2,runs['gemma4:26b'],'overall',DATASETS['v2_boots']['items'])
        self.assertEqual((report['total'],report['saved'],report['missing']), (68,5,63))
        self.assertEqual(report['decisive_responses'],2)
        self.assertEqual(report['metrics']['f1'],1.0)
        self.assertLess(report['decisive_coverage'],0.1)

    def test_saved_row_does_not_mean_successful_response(self):
        name='dlasher/MiniCPM-V-4.7-35B-A3B:IQ4_NL'
        report=run_diagnostics(self.labels1,self.runs[name],'overall',DATASETS['v1_helmet_vest']['items'])
        self.assertEqual((report['saved'], report['error_responses']), (60,60))
        self.assertEqual(report['decisive_responses'],0)
        self.assertEqual(report['decisive_coverage'],0.0)

    def test_diagnostics_ignore_extra_images_and_invalid_timing(self):
        labels=[{'image':'a.jpg','verified_helmet':'yes'},
                {'image':'b.jpg','verified_helmet':'no'},
                {'image':'c.jpg','verified_helmet':'yes'}]
        run={'a.jpg':{'predicted':'violation','seconds':'nan'},
             'b.jpg':{'predicted':'error','seconds':'-12'},
             'extra.jpg':{'predicted':'compliant','seconds':'20'}}
        report=run_diagnostics(labels,run,'overall',('helmet',))
        self.assertEqual((report['saved'],report['missing'],report['extra_rows']), (2,1,1))
        self.assertEqual((report['decisive_responses'],report['error_responses']), (1,1))
        self.assertIsNone(report['avg_seconds'])

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

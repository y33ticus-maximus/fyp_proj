"""Stage 6A: summary reports must remain read-only and evidence-scoped."""

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402
from reporting import (available_evidence_ids, recommend_summary_frames,
                       render_summary_pdf, saved_evidence_path)  # noqa: E402
from storage import PPEStore  # noqa: E402


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.images = self.base / 'evidence'
        self.images.mkdir()
        self.store = PPEStore(self.base / 'test.sqlite3')

    def save_image(self, suffix):
        filename = f'{suffix:032x}.jpg'
        Image.new('RGB', (720, 400), (130, 180, 200)).save(self.images / filename)
        return f'/api/evidence/{filename}'

    def save_frame(self, idx, seconds, helmet, vest, boots, status='violation'):
        payload = {
            'overall_status': status, 'helmet_violation': helmet,
            'vest_violation': vest, 'boots_violation': boots,
            'worker_count': 1, 'model': 'qwen-test', 'camera': 'TEST',
            'location': 'Test construction site', 'evidence_url': self.save_image(idx),
            'workers': [{'position': 'left', 'helmet': 'worn',
                         'vest': 'unclear', 'boots': 'unclear'}],
        }
        record = self.store.save_analysis(payload, video_session_id='report-video',
                                          video_name='inspection.mp4', video_seconds=seconds)
        return record

    def test_only_saved_local_jpegs_are_eligible(self):
        saved = self.save_image(1)
        self.assertIsNotNone(saved_evidence_path(saved, self.images))
        for unsafe in ['https://site.example/secret.jpg', '/other/secret.jpg',
                       '/api/evidence/../secret.jpg', 'blob:obsolete',
                       '/api/evidence/' + 'f' * 32 + '.jpg']:
            self.assertIsNone(saved_evidence_path(unsafe, self.images))

    def test_selection_covers_varied_ppe_patterns_and_drops_missing_files(self):
        url = lambda i: self.save_image(i)
        frames = [
            {'id': 1, 'video_seconds': 0, 'overall_status': 'compliant',
             'evidence_url': url(1)},
            {'id': 2, 'video_seconds': 15, 'overall_status': 'violation',
             'helmet_violation': 'yes', 'evidence_url': url(2)},
            {'id': 3, 'video_seconds': 16, 'overall_status': 'violation',
             'helmet_violation': 'yes', 'evidence_url': url(3)},
            {'id': 4, 'video_seconds': 45, 'overall_status': 'violation',
             'vest_violation': 'yes', 'evidence_url': url(4)},
            {'id': 5, 'video_seconds': 60, 'overall_status': 'violation',
             'helmet_violation': 'yes', 'vest_violation': 'yes', 'evidence_url': url(5)},
            {'id': 6, 'video_seconds': 75, 'overall_status': 'unclear',
             'boots_violation': 'unclear', 'evidence_url': url(6)},
            {'id': 7, 'video_seconds': 90, 'overall_status': 'violation',
             'boots_violation': 'yes', 'evidence_url': '/api/evidence/' + 'f' * 32 + '.jpg'},
        ]
        picked = recommend_summary_frames(frames, self.images, limit=5)
        self.assertLessEqual(len(picked), 5)
        self.assertEqual(len(picked), len(set(picked)))
        self.assertIn(5, picked)  # multiple definite concerns
        self.assertIn(4, picked)  # different PPE concern
        self.assertIn(6, picked)  # unclear evidence for review
        self.assertNotIn(7, picked)  # missing file
        self.assertEqual(len(available_evidence_ids(frames, self.images)), 6)

    def test_report_api_scopes_frames_and_keeps_saved_review(self):
        first = self.save_frame(8, 15, 'yes', 'no', 'unclear')
        self.save_frame(9, 45, 'yes', 'yes', 'unclear')
        incident_id = first['incident_id']
        self.store.record_review(incident_id, finding='confirmed',
                                 reviewer='Officer A', notes='Confirmed from saved images.')
        self.store.review_action(incident_id, action='resolve', reviewer='Officer A',
                                 notes='Worker received the required safety helmet.')
        before = self.store.review_history(incident_id)
        frames = self.store.incident_analyses(incident_id)

        with patch.object(main, 'STORE', self.store), patch.object(main, 'EVIDENCE_DIR', self.images):
            client = TestClient(main.app)
            suggested = client.get(f'/api/incidents/{incident_id}/report-options')
            self.assertEqual(suggested.status_code, 200)
            self.assertEqual(len(suggested.json()['availableIds']), 2)

            unknown = client.post(f'/api/incidents/{incident_id}/summary-report',
                                  json={'analysis_ids': [9999]})
            self.assertEqual(unknown.status_code, 400)
            dupes = client.post(f'/api/incidents/{incident_id}/summary-report',
                                json={'analysis_ids': [frames[0]['id']] * 2})
            self.assertEqual(dupes.status_code, 400)
            too_many = client.post(f'/api/incidents/{incident_id}/summary-report',
                                   json={'analysis_ids': list(range(7))})
            self.assertEqual(too_many.status_code, 422)

            result = client.post(f'/api/incidents/{incident_id}/summary-report',
                                 json={'analysis_ids': [f['id'] for f in frames]})
            self.assertEqual(result.status_code, 200, result.text[:200])
            self.assertEqual(result.headers['content-type'], 'application/pdf')
            self.assertTrue(result.content.startswith(b'%PDF-'))
            self.assertGreater(len(result.content), 4000)

        self.assertEqual(self.store.review_history(incident_id), before)
        self.assertEqual(self.store.incident_for_report(incident_id)['status'], 'Resolved')

    def test_legacy_incident_without_images_still_exports_metadata(self):
        incident_id = self.store.save_analysis({
            'overall_status': 'unclear', 'model': 'legacy-model',
            'location': 'Old site', 'camera': 'UPLOAD', 'worker_count': 1,
        })['incident_id']
        pdf = render_summary_pdf(self.store.incident_for_report(incident_id),
                                 self.store.incident_analyses(incident_id),
                                 self.store.review_history(incident_id), [], self.images)
        self.assertTrue(pdf.startswith(b'%PDF-'))


if __name__ == '__main__':
    unittest.main()

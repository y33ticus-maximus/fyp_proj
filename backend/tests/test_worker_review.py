"""Worker-level evidence review: python -m unittest discover -s backend/tests -v"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import PPEStore  # noqa: E402


class WorkerReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = PPEStore(Path(self.directory.name) / 'ppe.sqlite3')

    def save_alert(self, workers=None):
        result = {
            'overall_status': 'violation', 'model': 'test',
            'helmet_violation': 'yes', 'vest_violation': 'no',
            'boots_violation': 'unclear', 'worker_count': 2,
            'location': 'Site A', 'camera': 'UPLOAD',
            'workers': workers if workers is not None else [],
            'validation_warnings': ['Manual check needed'],
        }
        return self.store.save_analysis(result)

    def test_saved_worker_assessments_are_available_for_details(self):
        incident = self.save_alert([
            {'position': 'left', 'helmet': 'MISSING', 'vest': 'worn', 'boots': 'Unclear'},
            {'position': 'right', 'helmet': 'worn', 'vest': 'worn', 'boots': 'unclear'},
        ])
        frames = self.store.incident_analyses(incident['incident_id'])
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]['worker_count'], 2)
        self.assertEqual(frames[0]['workers'], [
            {'position': 'left', 'helmet': 'missing', 'vest': 'worn', 'boots': 'unclear'},
            {'position': 'right', 'helmet': 'worn', 'vest': 'worn', 'boots': 'unclear'},
        ])
        self.assertEqual(frames[0]['validation_warnings'], ['Manual check needed'])
        self.assertNotIn('result_json', frames[0])

    def test_missing_workers_does_not_invent_worker_assessments(self):
        incident = self.save_alert([])
        frame = self.store.incident_analyses(incident['incident_id'])[0]
        self.assertEqual(frame['worker_count'], 2)
        self.assertEqual(frame['workers'], [])

    def test_bad_worker_fields_do_not_become_false_violations(self):
        incident = self.save_alert([])
        with self.store.connect() as conn:
            conn.execute('UPDATE analyses SET result_json=? WHERE incident_id=?', (
                json.dumps({'workers': [
                    {'position': '   ', 'helmet': 'unknown', 'vest': 5, 'boots': ' WORN '},
                    'not an object',
                ]}), incident['incident_id']))
        frame = self.store.incident_analyses(incident['incident_id'])[0]
        self.assertEqual(frame['workers'], [{
            'position': 'Worker 1', 'helmet': None, 'vest': None, 'boots': 'worn',
        }])

    def test_malformed_saved_json_is_safe(self):
        incident = self.save_alert([])
        with self.store.connect() as conn:
            conn.execute('UPDATE analyses SET result_json=? WHERE incident_id=?', (
                '{broken-json', incident['incident_id']))
        frame = self.store.incident_analyses(incident['incident_id'])[0]
        self.assertEqual(frame['workers'], [])
        self.assertEqual(frame['validation_warnings'], [])


if __name__ == '__main__':
    unittest.main()

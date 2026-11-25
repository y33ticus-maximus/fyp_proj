"""Stage 5 human review records and protected incident transitions."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402
from storage import PPEStore  # noqa: E402


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'review.sqlite3'
        self.store = PPEStore(self.database)
        self.incident_id = self.store.save_analysis({
            'overall_status': 'violation', 'model': 'test-model',
            'helmet_violation': 'yes', 'vest_violation': 'no',
            'boots_violation': 'unclear', 'worker_count': 1,
            'location': 'Test site', 'camera': 'UPLOAD',
            'workers': [{'position': 'left', 'helmet': 'missing',
                         'vest': 'worn', 'boots': 'unclear'}],
        })['incident_id']

    def review(self, finding, notes='Manager compared the saved evidence.'):
        return self.store.record_review(
            self.incident_id, finding=finding, reviewer='Officer A', notes=notes)

    def act(self, action, notes=''):
        return self.store.review_action(
            self.incident_id, action=action, reviewer='Officer A', notes=notes)

    def test_new_incident_has_no_human_verification(self):
        data = self.store.review_history(self.incident_id)
        self.assertEqual(data['status'], 'Open')
        self.assertIsNone(data['currentFinding'])
        self.assertEqual(data['history'], [])
        self.assertEqual(len(self.store.incident_analyses(self.incident_id)[0]['workers']), 1)

    def test_confirmed_review_needs_corrective_action_before_resolution(self):
        data = self.review('confirmed')
        self.assertEqual(data['status'], 'Review')
        self.assertEqual(data['currentFinding'], 'confirmed')
        with self.assertRaisesRegex(ValueError, 'corrective action'):
            self.act('resolve', notes='short')
        self.assertEqual(self.store.review_history(self.incident_id)['status'], 'Review')
        data = self.act('resolve', 'Worker was given a compliant safety helmet.')
        self.assertEqual(data['status'], 'Resolved')
        self.assertEqual([event['action'] for event in data['history']], ['resolve', 'review'])
        self.assertEqual(len(self.store.incident_analyses(self.incident_id)), 1)

    def test_false_alert_only_allows_dismissal(self):
        self.review('false_alert', notes='Helmet is visible in the source image.')
        with self.assertRaisesRegex(ValueError, 'matching human'):
            self.act('resolve', 'Corrective action is not applicable here.')
        data = self.act('dismiss')
        self.assertEqual(data['status'], 'Dismissed')
        self.assertEqual(data['currentFinding'], 'false_alert')

    def test_inconclusive_cannot_resolve_or_dismiss(self):
        self.review('inconclusive')
        for action in ('resolve', 'dismiss'):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'matching human'):
                self.act(action, notes='A correction was attempted.')
        self.assertEqual(self.store.review_history(self.incident_id)['status'], 'Review')

    def test_reopen_keeps_history_but_requires_fresh_review(self):
        self.review('false_alert')
        self.act('dismiss')
        data = self.act('reopen')
        self.assertEqual(data['status'], 'Review')
        self.assertIsNone(data['currentFinding'])
        self.assertEqual(len(data['history']), 3)
        with self.assertRaisesRegex(ValueError, 'matching human'):
            self.act('dismiss')
        self.review('confirmed')
        self.assertEqual(self.store.review_history(self.incident_id)['currentFinding'], 'confirmed')

    def test_bad_input_and_missing_incident_leave_no_partial_record(self):
        with self.assertRaises(ValueError):
            self.review('wrong')
        with self.assertRaises(ValueError):
            self.store.record_review(self.incident_id, finding='confirmed', reviewer=' ', notes='Long enough note')
        with self.assertRaises(ValueError):
            self.review('confirmed', notes='short')
        self.assertEqual(self.store.review_history(self.incident_id)['history'], [])
        self.assertIsNone(self.store.review_history(99999))
        self.assertIsNone(self.store.review_action(99999, action='start', reviewer='Officer A'))

    def test_legacy_status_change_is_visibly_unattributed(self):
        self.assertTrue(self.store.update_status(self.incident_id, 'Review'))
        history = self.store.review_history(self.incident_id)['history']
        self.assertEqual(history[0]['action'], 'status_changed')
        self.assertEqual(history[0]['reviewer'], 'Legacy API')

    def test_legacy_reopen_does_not_reuse_old_human_finding(self):
        self.review('false_alert')
        self.act('dismiss')
        self.assertTrue(self.store.update_status(self.incident_id, 'Review'))
        self.assertIsNone(self.store.review_history(self.incident_id)['currentFinding'])
        with self.assertRaisesRegex(ValueError, 'matching human'):
            self.act('dismiss')

    def test_archiving_from_open_logs_the_actual_previous_status(self):
        self.assertTrue(self.store.archive_incident(self.incident_id))
        data = self.store.review_history(self.incident_id)
        self.assertEqual(data['status'], 'Archived')
        self.assertEqual(data['history'][0]['action'], 'archived')
        self.assertEqual(data['history'][0]['fromStatus'], 'Open')
        self.assertEqual(data['history'][0]['toStatus'], 'Archived')
        with self.assertRaises(ValueError):
            self.act('reopen')

    def test_database_reinitialization_keeps_review_history(self):
        self.review('confirmed')
        reopened_store = PPEStore(self.database)
        self.assertEqual(reopened_store.review_history(self.incident_id)['currentFinding'], 'confirmed')
        self.assertEqual(len(reopened_store.review_history(self.incident_id)['history']), 1)

    def test_fastapi_review_actions_and_validation(self):
        with patch.object(main, 'STORE', self.store):
            client = TestClient(main.app)
            prefix = f'/api/incidents/{self.incident_id}'
            response = client.get(prefix + '/reviews')
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()['currentFinding'])
            response = client.post(prefix + '/reviews', json={
                'finding': 'confirmed', 'reviewer': 'Officer A',
                'notes': 'Safety helmet is absent.',
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['currentFinding'], 'confirmed')
            bad = client.post(prefix + '/review-actions', json={
                'action': 'resolve', 'reviewer': 'Officer A', 'notes': 'short',
            })
            self.assertEqual(bad.status_code, 400)
            good = client.post(prefix + '/review-actions', json={
                'action': 'resolve', 'reviewer': 'Officer A',
                'notes': 'Worker was issued a helmet.',
            })
            self.assertEqual(good.status_code, 200)
            self.assertEqual(good.json()['status'], 'Resolved')
            self.assertEqual(client.get('/api/incidents/99999/reviews').status_code, 404)


if __name__ == '__main__':
    unittest.main()

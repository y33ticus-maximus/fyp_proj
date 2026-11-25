"""Stage 3 monitoring analytics: counts come from saved analyses, not incidents."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402
from storage import PPEStore  # noqa: E402


SGT = timezone(timedelta(hours=8))
REFERENCE = datetime(2026, 11, 20, 12, 0, tzinfo=SGT)


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PPEStore(Path(self.temp.name) / 'analytics.sqlite3')

    def record(self, date, status, *, location='Tower A', model='qwen',
               helmet='no', vest='no', boots='no', seconds=4.0, session=''):
        stamp = datetime.fromisoformat(date).astimezone(timezone.utc).isoformat()
        return self.store.save_analysis({
            'analyzed_at': stamp, 'overall_status': status, 'model': model,
            'helmet_violation': helmet, 'vest_violation': vest,
            'boots_violation': boots, 'worker_count': 1,
            'processing_seconds': seconds, 'location': location,
            'camera': 'UPLOAD',
        }, video_session_id=session, video_name='test.mp4' if session else '')

    def populate(self):
        self.record('2026-11-20T09:00:00+08:00', 'violation', helmet='yes', vest='yes', seconds=8.0)
        self.record('2026-11-19T09:00:00+08:00', 'compliant', seconds=4.0)
        self.record('2026-11-14T00:00:00+08:00', 'boots_unverified',
                    location='Warehouse', model='mini', boots='unclear', seconds=6.0)
        self.record('2026-11-13T23:59:00+08:00', 'violation',
                    location='Warehouse', model='mini', boots='yes', seconds=5.0)
        self.record('2026-11-18T09:00:00+08:00', 'unclear',
                    model='mini', vest='unclear', seconds=7.0)
        self.record('2026-11-20T09:10:00+08:00', 'error',
                    location='Warehouse', seconds=3.0)
        self.record('2026-11-20T09:15:00+08:00', 'no_workers',
                    helmet='unclear', vest='unclear', boots='unclear', seconds=2.0)

    def test_week_includes_singapore_midnight_not_previous_day(self):
        self.populate()
        result = self.store.analytics('7', reference_time=REFERENCE)
        self.assertEqual(result['summary'], {
            'total': 6, 'violations': 1, 'needsReview': 3, 'avgSeconds': 5.0,
        })
        self.assertEqual(len(result['trend']), 7)
        self.assertEqual(result['trend'][0]['bucket'], '2026-11-14')
        self.assertEqual(result['trend'][-1]['bucket'], '2026-11-20')
        self.assertEqual(sum(day['violation'] for day in result['trend']), 1)
        self.assertEqual(sum(day['unclear'] for day in result['trend']), 2)
        self.assertEqual(sum(day['other'] for day in result['trend']), 2)

    def test_multiple_ppe_categories_and_unverified_exclusion(self):
        self.populate()
        result = self.store.analytics('7', reference_time=REFERENCE)
        by_name = {row['name']: row['count'] for row in result['categories']}
        self.assertEqual(by_name, {
            'Helmet': 1, 'Safety vest': 1, 'Boots': 0, 'Unclear PPE': 2,
        })

    def test_location_filter_changes_all_analytics_tables(self):
        self.populate()
        result = self.store.analytics('7', 'Warehouse', reference_time=REFERENCE)
        self.assertEqual(result['summary']['total'], 2)
        self.assertEqual(result['summary']['violations'], 0)
        self.assertEqual(len(result['locationComparison']), 1)
        self.assertEqual(result['locationComparison'][0]['location'], 'Warehouse')
        self.assertEqual({row['model'] for row in result['modelComparison']}, {'qwen', 'mini'})
        self.assertEqual(result['locations'], ['Tower A', 'Warehouse'])

    def test_thirty_days_and_all_time(self):
        self.populate()
        self.record('2026-10-20T09:00:00+08:00', 'compliant')
        last_30 = self.store.analytics('30', reference_time=REFERENCE)
        all_time = self.store.analytics('all', reference_time=REFERENCE)
        self.assertEqual(last_30['summary']['total'], 7)
        self.assertEqual(last_30['summary']['violations'], 2)
        self.assertEqual(len(last_30['trend']), 30)
        self.assertEqual(all_time['summary']['total'], 8)
        self.assertEqual(all_time['bucketType'], 'month')
        self.assertEqual([row['bucket'] for row in all_time['trend']], ['2026-10', '2026-11'])

    def test_multiple_frames_are_not_counted_as_unique_incidents(self):
        self.record('2026-11-20T09:00:00+08:00', 'violation',
                    helmet='yes', session='video-1')
        self.record('2026-11-20T09:01:00+08:00', 'compliant', session='video-1')
        result = self.store.analytics('7', reference_time=REFERENCE)
        self.assertEqual(result['summary']['total'], 2)
        self.assertEqual(len(self.store.state()['items']), 1)

    def test_empty_period_and_invalid_period(self):
        result = self.store.analytics('7', reference_time=REFERENCE)
        self.assertEqual(result['summary']['total'], 0)
        self.assertIsNone(result['summary']['avgSeconds'])
        self.assertEqual(len(result['trend']), 7)
        self.assertEqual(result['modelComparison'], [])
        with self.assertRaises(ValueError):
            self.store.analytics('tomorrow', reference_time=REFERENCE)

    def test_fastapi_route_and_invalid_period_validation(self):
        self.record('2026-11-20T09:00:00+08:00', 'violation', helmet='yes')
        with patch.object(main, 'STORE', self.store):
            client = TestClient(main.app)
            response = client.get('/api/analytics', params={'period': 'all'})
            invalid = client.get('/api/analytics', params={'period': 'invalid'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['summary']['total'], 1)
        self.assertEqual(invalid.status_code, 422)


if __name__ == '__main__':
    unittest.main()

"""Run from the project root: python -m unittest discover -s backend/tests"""

import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from main import PPEOutput, consistency_warnings, overall_status, validated_overall_status  # noqa: E402
from storage import PPEStore  # noqa: E402


class ResultConsistencyTests(unittest.TestCase):
    def make_result(self, workers, helmet='no', vest='no', boots='no', count=None):
        return PPEOutput.model_validate({
            'worker_count': len(workers) if count is None else count,
            'workers': workers,
            'helmet_violation': helmet,
            'vest_violation': vest,
            'boots_violation': boots,
        })

    def test_valid_all_worn_has_no_warnings(self):
        data = self.make_result([{'helmet': 'worn', 'vest': 'worn', 'boots': 'worn'}])
        self.assertEqual(consistency_warnings(data), [])
        self.assertEqual(overall_status(data), 'compliant')

    def test_missing_helmet_cannot_agree_with_no_violation(self):
        data = self.make_result([{'helmet': 'missing', 'vest': 'worn', 'boots': 'worn'}])
        self.assertTrue(any('Helmet:' in warning for warning in consistency_warnings(data)))

    def test_unclear_worker_conflicts_with_definitive_no(self):
        data = self.make_result([{'helmet': 'unclear', 'vest': 'worn', 'boots': 'worn'}])
        self.assertTrue(any('Helmet:' in warning for warning in consistency_warnings(data)))

    def test_worker_count_mismatch_is_flagged(self):
        data = self.make_result([{'helmet': 'worn', 'vest': 'worn', 'boots': 'worn'}], count=2)
        self.assertTrue(any('worker(s)' in warning for warning in consistency_warnings(data)))

    def test_no_workers_requires_unclear_flags(self):
        data = self.make_result([], count=0)
        self.assertTrue(consistency_warnings(data))
        self.assertEqual(validated_overall_status(data)[0], 'no_workers')

    def test_worker_labels_are_case_normalized(self):
        data = self.make_result([{'helmet': 'Worn', 'vest': ' WORN ', 'boots': 'Worn'}])
        self.assertEqual(consistency_warnings(data), [])

    def test_supported_unclear_footwear_is_not_compliant(self):
        data = self.make_result(
            [{'helmet': 'worn', 'vest': 'worn', 'boots': 'unclear'}], boots='unclear'
        )
        self.assertEqual(consistency_warnings(data), [])
        self.assertEqual(overall_status(data), 'boots_unverified')

    def test_boots_only_conflict_does_not_create_default_alert(self):
        data = self.make_result(
            [{'helmet': 'worn', 'vest': 'worn', 'boots': 'unclear'}], boots='no'
        )
        status, warnings = validated_overall_status(data, review_unclear_boots=False)
        self.assertEqual(status, 'boots_unverified')
        self.assertTrue(warnings)

    def test_inconsistent_result_is_saved_for_review(self):
        payload = {
            'worker_count': 1,
            'workers': [{'helmet': 'missing', 'vest': 'worn', 'boots': 'worn'}],
            'helmet_violation': 'no',
            'vest_violation': 'no',
            'boots_violation': 'no',
        }

        class FakeOllamaResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {'message': {'content': json.dumps(payload)}}

        class FakeOllamaClient:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def post(self, *_args, **_kwargs):
                return FakeOllamaResponse()

        image = BytesIO()
        Image.new('RGB', (12, 12), '#aaccee').save(image, 'PNG')
        image.seek(0)
        uploaded = UploadFile(file=image, filename='test.png',
                              headers=Headers({'content-type': 'image/png'}))
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(main, 'OLLAMA_BASE_URL', 'http://localhost:11434'), \
                    patch.object(main, 'EVIDENCE_DIR', Path(temp_dir)), \
                    patch.object(main, 'STORE') as store, \
                    patch.object(main.httpx, 'Client', FakeOllamaClient):
                store.save_analysis.return_value = {
                    'analysis_id': 1, 'incident_id': 1, 'incident_action': 'created'
                }
                result = main.analyze(file=uploaded, model=main.ALLOWED_MODELS[0],
                                      location='Test site', camera='UPLOAD',
                                      review_unclear_boots=False,
                                      video_session_id='', video_name='',
                                      video_timestamp_seconds=None)
                self.assertEqual(result['overall_status'], 'unclear')
                self.assertTrue(result['validation_warnings'])
                self.assertEqual(
                    store.save_analysis.call_args.args[0]['overall_status'], 'unclear'
                )

    def test_saved_incident_frames_preserve_validation_warnings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PPEStore(Path(temp_dir) / 'test.sqlite3')
            result = {
                'model': 'example', 'overall_status': 'unclear',
                'helmet_violation': 'no', 'vest_violation': 'no',
                'boots_violation': 'no', 'worker_count': 1,
                'validation_warnings': ['Example contradiction'],
            }
            saved = store.save_analysis(result)
            frames = store.incident_analyses(saved['incident_id'])
            self.assertEqual(frames[0]['validation_warnings'],
                             ['Example contradiction'])


if __name__ == '__main__':
    unittest.main()

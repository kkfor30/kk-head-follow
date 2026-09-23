import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generate_zenmux_video as generator
from submission_budget import reserve, check_limits, check_stage


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.budget = self.root / 'budget.json'
        self.budget.write_text(json.dumps(dict(schemaVersion=1, purpose='one pilot', maxSubmissions=1, attempts=[])))
        self.output = self.root / 'output'
        self.output.mkdir()
        self.spec = self.root / 'spec.json'
        (self.root/'input-review.md').write_text('Offline budget test; no real media generation.')
        self.spec.write_text(json.dumps(dict(prompt='A continuous head turn.',duration=5,
            motionPlan=dict(kind='diagnostic',evidence='input-review.md',durationReason='Offline fixture'))))

    def run_cli(self, extra):
        with patch('sys.argv', ['generator', '--output-dir', str(self.output), *extra]), contextlib.redirect_stdout(io.StringIO()):
            return generator.main()

    def test_budget_survives_output_change(self):
        reserve(self.budget, self.output, dict(prompt='a', duration=5, model='minimax/minimax-h3-max', resolution='768p'))
        other = self.root / 'other'
        other.mkdir()
        with self.assertRaisesRegex(ValueError, 'exhausted'):
            reserve(self.budget, other, dict(prompt='b', duration=5, model='minimax/minimax-h3-max', resolution='768p'))

    def test_ten_seconds_denied_before_reservation(self):
        body=dict(duration=10,model='minimax/minimax-h3-max',resolution='768p')
        with self.assertRaisesRegex(ValueError,'maxSecondsPerSubmission'):
            reserve(self.budget,self.output,body)
        self.assertFalse((self.output/'submission.json').exists())
        self.assertEqual(json.loads(self.budget.read_text())['attempts'],[])

    def test_total_seconds_and_model_limits(self):
        data=dict(maxSubmissions=3,attempts=[dict(requestedSeconds=5)],limits=dict(maxTotalSeconds=8))
        body=dict(duration=5,model='minimax/minimax-h3-max',resolution='768p')
        with self.assertRaisesRegex(ValueError,'total requested'):
            check_limits(data,body)
        with self.assertRaisesRegex(ValueError,'model or resolution'):
            check_limits(data,{**body,'resolution':'2K'})
        with self.assertRaisesRegex(ValueError,'finite positive'):
            check_limits(data,{**body,'duration':float('nan')})

    def test_second_pilot_and_unreviewed_expansion_denied(self):
        with self.assertRaisesRegex(ValueError,'pilot already'):
            check_stage(None,self.root,[{}])
        with self.assertRaises((ValueError,FileNotFoundError)):
            check_stage(dict(stage='expansion',root='.',pilotManifest='missing.json'),self.root,[])

    def test_repair_records_source_and_defect(self):
        (self.root/'video.mp4').write_bytes(b'existing test source')
        (self.root/'defect.md').write_text('Missing upper arc; endpoint frames inspected.')
        with self.assertRaisesRegex(ValueError,'sourceInputs'):
            check_stage(dict(stage='repair',sourceVideo='video.mp4',defectEvidence='defect.md'),self.root,[])


    def test_dry_run_rejects_cost_increase_without_network(self):
        spec=json.loads(self.spec.read_text());spec['duration']=10;self.spec.write_text(json.dumps(spec))
        with patch.object(generator,'request_json') as request:
            with self.assertRaises(SystemExit):self.run_cli(['--spec',str(self.spec),'--dry-run'])
            request.assert_not_called()

    def test_same_request_not_submitted_twice(self):
        data = json.loads(self.budget.read_text()); data['maxSubmissions'] = 2
        self.budget.write_text(json.dumps(data))
        reserve(self.budget, self.output, dict(prompt='a', duration=5, model='minimax/minimax-h3-max', resolution='768p'))
        other = self.root / 'other'; other.mkdir()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            reserve(self.budget, other, dict(prompt='a', duration=5, model='minimax/minimax-h3-max', resolution='768p'))

    def test_old_output_and_concurrent_lock_rejected(self):
        (self.output / 'job.json').write_text('{"id":"old"}')
        with self.assertRaisesRegex(ValueError, 'output already'):
            reserve(self.budget, self.output, {})
        self.budget.with_name('budget.json.lock').mkdir()
        with self.assertRaisesRegex(ValueError, 'locked'):
            reserve(self.budget, self.output, {})

    def test_timeout_reserves_budget_without_retry(self):
        with patch.object(generator, 'configured_api_key', return_value=('test-only', 'test')), patch.object(generator, 'request_json', side_effect=TimeoutError) as request:
            with self.assertRaises(TimeoutError):
                self.run_cli(['--spec', str(self.spec), '--budget', str(self.budget)])
            self.assertEqual(request.call_count, 1)
        self.assertEqual(len(json.loads(self.budget.read_text())['attempts']), 1)
        self.assertTrue((self.output / 'submission.json').exists())

    def test_resume_get_only_without_budget(self):
        with patch.object(generator, 'configured_api_key', return_value=('test-only', 'test')), patch.object(generator, 'request_json', return_value=dict(id='old', status='succeeded', content=dict(video_url='https://example.invalid/video'))) as request, patch.object(generator, 'download'):
            self.assertEqual(self.run_cli(['--job-id', 'old']), 0)
            self.assertEqual(request.call_args.args[1], 'GET')
        self.assertEqual(json.loads(self.budget.read_text())['attempts'], [])

    def test_dry_run_does_not_reserve_or_connect(self):
        with patch.object(generator, 'request_json') as request:
            self.assertEqual(self.run_cli(['--spec', str(self.spec), '--dry-run']), 0)
            request.assert_not_called()
        self.assertFalse((self.output / 'submission.json').exists())

    def test_old_job_elsewhere_does_not_block_explicit_budget(self):
        (self.root / 'job.json').write_text('{"id":"old"}')
        with patch.object(generator, 'configured_api_key', return_value=('test-only', 'test')), patch.object(generator, 'request_json', return_value=dict(id='new', status='succeeded', content=dict(video_url='https://example.invalid/video'))) as request, patch.object(generator, 'download'):
            self.assertEqual(self.run_cli(['--spec', str(self.spec), '--budget', str(self.budget)]), 0)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.args[1], 'POST')


if __name__ == '__main__':
    unittest.main()

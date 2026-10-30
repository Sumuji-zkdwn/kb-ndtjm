import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('research_run', HERE / 'research_run.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
NB = {'nbformat': 4, 'nbformat_minor': 5, 'cells': [
    {'cell_type': 'markdown', 'source': 'SYNTHETIC_CONTENT', 'metadata': {}},
    {'cell_type': 'code', 'source': 'print(1)\n', 'outputs': ['OLD PRIVATE OUTPUT'],
     'execution_count': 1, 'metadata': {}}]}
META = {'id': r.REF, 'id_no': r.EXPECTED_ID, 'is_private': True, 'title': r.TITLE,
        'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': False,
        'dataset_sources': [], 'kernel_sources': [], 'competition_sources': [], 'model_sources': []}
REQ = {'id': 'test-run-001', 'kind': 'ideas-43-rerun', 'previous_id': 'none'}


class ResearchRunTests(unittest.TestCase):
    def setUp(self):
        self.digest = r.canonical(NB)[0]
        self.hash_patch = patch.object(r, 'EXPECTED_BASE_SHA256', self.digest)
        self.hash_patch.start()

    def tearDown(self):
        self.hash_patch.stop()

    def test_identity_privacy_and_all_inputs_strict(self):
        r.check_metadata(META)
        for bad in ({**META, 'id_no': r.EXPECTED_ID + 1}, {**META, 'is_private': False},
                    {**META, 'competition_sources': ['competition']}, {**META, 'enable_gpu': True},
                    {**META, 'model_sources': ['other']}):
            with self.subTest(bad=bad), self.assertRaises(r.RunError):
                r.check_metadata(bad)

    def test_marker_preserves_sources_and_clears_only_new_output(self):
        prepared, digest, prior, count = r.prepare(NB, REQ)
        self.assertEqual(digest, self.digest)
        self.assertEqual(prior, 'none')
        self.assertEqual(count, 2)
        self.assertEqual(prepared['cells'][0]['source'], NB['cells'][0]['source'])
        self.assertEqual(prepared['cells'][1]['source'], NB['cells'][1]['source'])
        self.assertEqual(prepared['cells'][1]['outputs'], [])
        self.assertEqual(NB['cells'][1]['outputs'], ['OLD PRIVATE OUTPUT'])
        self.assertEqual(prepared['cells'][-1]['source'], r.MARKER_PREFIX + REQ['id'] + '\n')

    def test_repeat_request_is_noop_and_new_request_requires_previous_marker(self):
        prepared = r.prepare(NB, REQ)[0]
        self.assertIsNone(r.prepare(prepared, REQ)[0])
        next_req = {'id': 'test-run-002', 'kind': REQ['kind'], 'previous_id': REQ['id']}
        prepared2 = r.prepare(prepared, next_req)[0]
        self.assertEqual(len(prepared2['cells']), 3)
        self.assertTrue(prepared2['cells'][-1]['source'].endswith(next_req['id'] + '\n'))
        with self.assertRaises(r.RunError):
            r.prepare(prepared, {**next_req, 'previous_id': 'none'})

    def test_changed_source_and_embedded_marker_rejected(self):
        bad = json.loads(json.dumps(NB)); bad['cells'][1]['source'] = 'print(2)\n'
        with self.assertRaises(r.RunError):
            r.prepare(bad, REQ)
        bad = json.loads(json.dumps(NB)); bad['cells'][0]['source'] = r.MARKER_PREFIX + 'wrong-id\n'
        with self.assertRaises(r.RunError):
            r.prepare(bad, REQ)

    def test_manual_or_failed_attempt_never_pushes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r, 'ROOT', Path(tmp)), \
             patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY', 'GITHUB_RUN_ATTEMPT': '2'}, clear=True), \
             patch.object(r, 'call') as fake:
            (Path(tmp) / 'request.json').write_text(json.dumps(REQ), encoding='utf-8')
            with self.assertRaises(r.RunError): r.main()
            fake.assert_not_called()

    def test_one_mocked_run_pushes_exact_source_and_private_metadata(self):
        calls = []
        def fake_call(args):
            calls.append(args[1])
            if args[1] == 'push':
                folder = Path(args[-1])
                meta = json.loads((folder / 'kernel-metadata.json').read_text())
                nb = json.loads((folder / 'job.ipynb').read_text(encoding='utf-8'))
                self.assertTrue(meta['is_private'])
                self.assertEqual(meta['id_no'], r.EXPECTED_ID)
                self.assertEqual(meta['competition_sources'], [])
                self.assertEqual(nb['cells'][-1]['source'], r.MARKER_PREFIX + REQ['id'] + '\n')
                return 0, 'Kernel version 2 successfully pushed.  Please check progress at https://example.invalid', ''
            return 0, 'KernelWorkerStatus.COMPLETE', ''
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.object(r, 'ROOT', Path(tmp)):
            (Path(tmp) / 'request.json').write_text(json.dumps(REQ), encoding='utf-8')
            with patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY', 'GITHUB_RUN_ATTEMPT': '1'}, clear=True), \
                 patch.object(r, 'call', side_effect=fake_call), patch.object(r, 'pull', return_value=(META, NB)), \
                 contextlib.redirect_stdout(output):
                r.main()
        self.assertEqual(calls, ['status', 'push'])
        self.assertIn('"accepted_version": 2', output.getvalue())
        self.assertNotIn('SYNTHETIC_CONTENT', output.getvalue())

    def test_existing_request_marker_skips_push(self):
        previous = r.prepare(NB, REQ)[0]
        with tempfile.TemporaryDirectory() as tmp, patch.object(r, 'ROOT', Path(tmp)):
            (Path(tmp) / 'request.json').write_text(json.dumps(REQ), encoding='utf-8')
            with patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY', 'GITHUB_RUN_ATTEMPT': '1'}, clear=True), \
                 patch.object(r, 'call', return_value=(0, 'COMPLETE', '')) as fake, \
                 patch.object(r, 'pull', return_value=(META, previous)), contextlib.redirect_stdout(io.StringIO()):
                r.main()
            self.assertEqual(fake.call_count, 1)

    def test_zero_exit_push_error_is_never_success(self):
        def fake_call(args):
            return (0, 'Kernel push error: suppressed', '') if args[1] == 'push' else (0, 'COMPLETE', '')
        with tempfile.TemporaryDirectory() as tmp, patch.object(r, 'ROOT', Path(tmp)):
            (Path(tmp) / 'request.json').write_text(json.dumps(REQ), encoding='utf-8')
            with patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY', 'GITHUB_RUN_ATTEMPT': '1'}, clear=True), \
                 patch.object(r, 'call', side_effect=fake_call) as fake, patch.object(r, 'pull', return_value=(META, NB)):
                with self.assertRaisesRegex(r.RunError, 'uncertain'):
                    r.main()
                self.assertEqual(fake.call_count, 2)


if __name__ == '__main__':
    unittest.main()

import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('anchor_runner', HERE / 'runner.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
REQUEST = json.loads((HERE / 'request.json').read_text(encoding='utf-8'))
ANCHOR_NB = {'nbformat': 4, 'cells': [{'cell_type': 'code', 'source': r.SENTINEL}]}
META = {'id': r.ANCHOR, 'id_no': r.ANCHOR_ID, 'title': r.ANCHOR_TITLE, 'is_private': True,
        'language': 'python', 'kernel_type': 'notebook', 'dataset_sources': [],
        'kernel_sources': [], 'competition_sources': [], 'model_sources': []}


class AnchorTests(unittest.TestCase):
    def test_sentinel_and_metadata(self):
        self.assertEqual(r.validate_anchor(META, ANCHOR_NB), r.ANCHOR_ID)
        self.assertEqual(r.validate_anchor(META, {'nbformat': 4, 'cells': [
            {'cell_type': 'code', 'source': r.SENTINEL.splitlines(keepends=True)}]}), r.ANCHOR_ID)

    def test_reject_wrong_identity_privacy_and_inputs(self):
        for bad in ({**META, 'id': 'sumuji/existing'}, {**META, 'id_no': 0},
                    {**META, 'title': 'existing'}, {**META, 'is_private': False},
                    {**META, 'competition_sources': ['competition']},
                    {**META, 'model_sources': ['model']}, {**META, 'language': 'r'}):
            with self.subTest(bad=bad), self.assertRaises(r.PilotError):
                r.validate_anchor(bad, ANCHOR_NB)

    def test_reject_reused_or_changed_anchor(self):
        for nb in ({'nbformat': 4, 'cells': []},
                   {'nbformat': 4, 'cells': [{'cell_type': 'code', 'source': 'changed'}]},
                   {'nbformat': 4, 'cells': [{'cell_type': 'markdown', 'source': r.SENTINEL}]},
                   {'nbformat': 4, 'cells': ANCHOR_NB['cells'] * 2}):
            with self.subTest(nb=nb), self.assertRaises(r.PilotError):
                r.validate_anchor(META, nb)

    def test_reject_arbitrary_request(self):
        for bad in ({**REQUEST, 'kind': 'research'}, {**REQUEST, 'source_sha256': '0'*64},
                    {**REQUEST, 'extra': 'no'}, {**REQUEST, 'id': '../oops'}):
            with self.subTest(bad=bad), self.assertRaises(r.PilotError):
                r.validate_request(bad)

    def test_running_anchor_and_unknown_status_do_not_read_or_push(self):
        for response in ((0, 'status "RUNNING"', ''), (1, '', 'HTTP 403')):
            with self.subTest(response=response), patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY'}), \
                 patch.object(r, 'call', return_value=response) as fake, patch.object(r, 'pull_anchor') as pull:
                with self.assertRaises(r.PilotError):
                    r.main()
                self.assertEqual(fake.call_count, 1)
                pull.assert_not_called()

    def test_diagnostic_mode_never_pushes(self):
        with patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY', 'KAGGLE_DIAGNOSTIC_ONLY': '1'}), \
             patch.object(r, 'call', return_value=(0, 'status "COMPLETE"', '')) as fake, \
             patch.object(r, 'pull_anchor', return_value=r.ANCHOR_ID):
            r.main()
            self.assertEqual(fake.call_count, 1)

    def test_changed_anchor_between_preflights_blocks_push(self):
        with patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY'}, clear=True), \
             patch.object(r, 'call', return_value=(0, 'status "COMPLETE"', '')) as fake, \
             patch.object(r, 'pull_anchor', side_effect=[r.ANCHOR_ID, r.PilotError('changed')]):
            with self.assertRaises(r.PilotError):
                r.main()
            self.assertEqual(fake.call_count, 1)

    def test_mocked_one_time_success_and_no_competition_metadata(self):
        calls = []
        def fake_call(args, **kwargs):
            calls.append(args[1])
            if args[1] == 'push':
                meta = json.loads((Path(args[-1]) / 'kernel-metadata.json').read_text(encoding='utf-8'))
                self.assertEqual(meta['id_no'], r.ANCHOR_ID)
                self.assertTrue(meta['is_private'])
                self.assertEqual(meta['competition_sources'], [])
                self.assertFalse(meta['enable_internet'])
                return (0, 'Kernel version 2 successfully pushed.  Please check progress at https://example.invalid', '')
            return (0, 'status "COMPLETE"', '')
        with patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY'}, clear=True), \
             patch.object(r, 'call', side_effect=fake_call), \
             patch.object(r, 'pull_anchor', return_value=r.ANCHOR_ID):
            r.main()
        self.assertEqual(calls, ['status', 'status', 'push'])

    def test_cli_exit_zero_with_push_error_is_not_success(self):
        def fake_call(args, **kwargs):
            return (0, 'Kernel push error: redacted', '') if args[1] == 'push' else (0, 'status "COMPLETE"', '')
        with patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY'}, clear=True), \
             patch.object(r, 'call', side_effect=fake_call), patch.object(r, 'pull_anchor', return_value=r.ANCHOR_ID):
            with self.assertRaisesRegex(r.PilotError, 'No unambiguous'):
                r.main()

    def test_ambiguous_push_is_never_retried(self):
        calls = []
        def fake_call(args, **kwargs):
            calls.append(args[1])
            return (1, '', 'HTTP error') if args[1] == 'push' else (0, 'status "COMPLETE"', '')
        with patch.dict(os.environ, {'KAGGLE_API_TOKEN': 'TEST_ONLY'}, clear=True), \
             patch.object(r, 'call', side_effect=fake_call), patch.object(r, 'pull_anchor', return_value=r.ANCHOR_ID):
            with self.assertRaisesRegex(r.PilotError, 'uncertain'):
                r.main()
        self.assertEqual(calls, ['status', 'status', 'push'])


if __name__ == '__main__':
    unittest.main()

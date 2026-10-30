import json
import types
import unittest
from pathlib import Path

import pilot_once as p
from requests.exceptions import HTTPError


class PilotTests(unittest.TestCase):
    def test_collision_guard_accepts_only_explicit_404(self):
        def fail_with(status):
            def invoke():
                raise HTTPError(response=types.SimpleNamespace(status_code=status))
            return invoke
        self.assertTrue(p.is_missing(fail_with(404)))
        self.assertFalse(p.is_missing(lambda: object()))
        with self.assertRaises(p.PilotError):
            p.is_missing(fail_with(403))

    def test_prepared_assets(self):
        p.validate_assets()

    def test_dataset_guard(self):
        ds = types.SimpleNamespace(ref=p.DATASET, is_private=True, id=999, current_version_number=1)
        self.assertEqual(p.check_dataset(ds), 999)
        for key, value in [('is_private', False), ('current_version_number', 2), ('ref', 'other'), ('id', 0)]:
            invalid = types.SimpleNamespace(**{**vars(ds), key: value})
            with self.subTest(key=key), self.assertRaises(p.PilotError):
                p.check_dataset(invalid)

    def test_receipt_guard(self):
        receipt = dict(ref='/code/' + p.KERNEL, kernel_id=123, version_number=1, error='',
                       invalid_tags=[], invalid_dataset_sources=[], invalid_competition_sources=[],
                       invalid_kernel_sources=[], invalid_model_sources=[])
        self.assertEqual(p.check_receipt(types.SimpleNamespace(**receipt)), 123)
        for key, value in [('ref', '/code/other'), ('kernel_id', 0), ('version_number', 2),
                           ('invalid_dataset_sources', ['bad'])]:
            with self.subTest(key=key), self.assertRaises(p.PilotError):
                p.check_receipt(types.SimpleNamespace(**{**receipt, key: value}))

    def test_remote_metadata_guard(self):
        meta = json.loads((p.ROOT / 'pilot/kernel/kernel-metadata.json').read_text(encoding='utf-8'))
        nb = json.loads((p.ROOT / 'pilot/kernel/qwen_batch_private_pilot_20261031.ipynb').read_text(encoding='utf-8'))
        meta['id_no'] = 123
        p.check_kernel(meta, nb, 123)
        for key, value in [('is_private', False), ('dataset_sources', [p.DATASET]),
                           ('model_sources', []), ('enable_internet', True), ('enable_gpu', False)]:
            with self.subTest(key=key), self.assertRaises(p.PilotError):
                p.check_kernel({**meta, key: value}, nb, 123)


if __name__ == '__main__':
    unittest.main()

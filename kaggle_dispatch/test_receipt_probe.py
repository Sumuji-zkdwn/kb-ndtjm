import json
import os
import pathlib
import types
import unittest
from unittest.mock import patch

import receipt_probe as p


class ReceiptProbeTests(unittest.TestCase):
    def test_categorizes_without_printing_values(self):
        resp = types.SimpleNamespace(error='', ref='', kernel_id=0, version_number=5,
                                     **{field: [] for field in p.router.FIELDS})
        got = p.category(resp)
        self.assertEqual(got['ref_category'], 'empty')
        self.assertEqual(got['kernel_id_category'], 'zero_or_missing')
        self.assertEqual(got['version_category'], 'five')
        self.assertTrue(all(v == 'empty' for v in got['invalid_fields'].values()))
        resp.ref = 'https://synthetic.invalid/path/' + p.TARGET['ref']
        self.assertEqual(p.category(resp)['synthetic_ref_prefix_if_safe'], 'https://synthetic.invalid/path/')
        resp.ref = 'https://fake.example/?secret=value/' + p.TARGET['ref']
        self.assertEqual(p.category(resp)['synthetic_ref_prefix_if_safe'], 'redacted')

    def test_one_shot_update_checks_completed_version(self):
        # A wholly synthetic fixture is used instead of the user's notebook.
        nb = {'nbformat': 4, 'nbformat_minor': 5, 'cells': [
            {'cell_type': 'code', 'id': 'one', 'metadata': {}, 'source': 'print(1)\n', 'outputs': [], 'execution_count': None}]}
        target = dict(p.TARGET, hash=p.router.canonical(nb)[0])
        nb['cells'].append({'cell_type': 'markdown', 'id': 'previous', 'metadata': {},
                            'source': p.router.V2 + json.dumps(['receipt-probe-20261031-d3', p.REQ['previous_id']], separators=(',', ':')) + '\n'})
        meta = {'id': target['ref'], 'id_no': target['id'], 'title': target['title'], 'is_private': True,
                'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': False, 'enable_tpu': False,
                'enable_internet': False, 'dataset_sources': [], 'kernel_sources': [], 'competition_sources': [],
                'model_sources': [], 'keywords': [], 'code_file': 'job.ipynb'}

        class Fake:
            def __init__(self): self.nb = nb; self.pushes = 0; self.refs = []
            def kernels_status(self, ref):
                self.refs.append(ref)
                return types.SimpleNamespace(status=types.SimpleNamespace(name='COMPLETE'))
            def kernels_pull(self, ref, path, **kwargs):
                self.refs.append(ref)
                root = pathlib.Path(path)
                (root / 'kernel-metadata.json').write_text(json.dumps(meta), encoding='utf-8')
                (root / 'job.ipynb').write_text(json.dumps(self.nb), encoding='utf-8')
            def kernels_push(self, path):
                self.pushes += 1
                self.nb = json.loads((pathlib.Path(path) / 'job.ipynb').read_text(encoding='utf-8'))
                return types.SimpleNamespace(error='', ref='', kernel_id=0, version_number=5,
                                             **{field: [] for field in p.router.FIELDS})
        fake = Fake()
        with patch.object(p, 'TARGET', target), patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '1'}):
            p.run(fake)
            self.assertEqual(fake.pushes, 1)
            self.assertIn(target['ref'] + '/5', fake.refs)
            with self.assertRaises(p.router.RouterError):
                p.run(fake)
            self.assertEqual(fake.pushes, 1)


if __name__ == '__main__':
    unittest.main()

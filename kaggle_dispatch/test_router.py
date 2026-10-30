import json
import os
import pathlib
import types
import unittest
from unittest.mock import patch

import router


NB = {'nbformat': 4, 'nbformat_minor': 5, 'cells': [
    {'cell_type': 'markdown', 'metadata': {}, 'id': 'intro', 'source': '# Synthetic fixture\n'},
    {'cell_type': 'code', 'metadata': {}, 'id': 'code', 'source': 'print(1)\n',
     'execution_count': None, 'outputs': []}]}
REQ = {'id': 'ideas43-20261031-002', 'previous_id': 'ideas43-20261031-001', 'kind': 'ideas-43-rerun'}
T = dict(router.TARGETS[REQ['kind']])
T['hash'] = router.canonical(NB)[0]


def receipt(**overrides):
    values = dict(error='', invalid_tags=[], invalid_dataset_sources=[], invalid_competition_sources=[],
                  invalid_kernel_sources=[], invalid_model_sources=[], ref=T['ref'], kernel_id=T['id'], version_number=3)
    values.update(overrides)
    return types.SimpleNamespace(**values)


class RouterTests(unittest.TestCase):
    def test_initial_and_legacy_migration_retains_id(self):
        nb = json.loads(json.dumps(NB))
        nb['cells'].append({'cell_type': 'markdown', 'source': router.V1 + REQ['previous_id'] + '\n'})
        result, digest, history = router.prepare(nb, REQ, T)
        self.assertEqual(history, [REQ['previous_id'], REQ['id']])
        self.assertEqual(digest, T['hash'])
        self.assertTrue(result['cells'][-1]['source'].startswith(router.V2))
        self.assertEqual(len(nb['cells']), 3)

    def test_reuse_any_historical_id_is_noop(self):
        nb = json.loads(json.dumps(NB))
        history = ['ideas43-20261031-001', 'ideas43-20261031-002', 'ideas43-20261031-003']
        nb['cells'].append({'cell_type': 'markdown', 'source': router.V2 + json.dumps(history, separators=(',', ':')) + '\n'})
        request = dict(REQ, id=history[0], previous_id=history[-1])
        self.assertIsNone(router.prepare(nb, request, T)[0])

    def test_stale_previous_or_duplicate_ledger_rejected(self):
        nb = json.loads(json.dumps(NB))
        nb['cells'].append({'cell_type': 'markdown', 'source': router.V1 + REQ['previous_id'] + '\n'})
        with self.assertRaises(router.RouterError):
            router.prepare(nb, dict(REQ, previous_id='some-other-id'), T)
        nb['cells'][-1]['source'] = router.V2 + '["duplicate-id","duplicate-id"]\n'
        with self.assertRaises(router.RouterError):
            router.prepare(nb, REQ, T)

    def test_source_change_rejected(self):
        nb = json.loads(json.dumps(NB))
        nb['cells'][0]['source'] += 'bad change'
        with self.assertRaises(router.RouterError):
            router.prepare(nb, REQ, T)

    def test_receipt_checks_all_fields_and_identity(self):
        self.assertEqual(router.check_receipt(receipt(), T), 3)
        for field in router.FIELDS:
            with self.assertRaises(router.RouterError):
                router.check_receipt(receipt(**{field: ['bad']}), T)
            with self.assertRaises(router.RouterError):
                router.check_receipt(receipt(**{field: None}), T)
        for changes in ({'error': 'bad'}, {'kernel_id': 0}, {'ref': 'wrong'}, {'version_number': 0}):
            with self.assertRaises(router.RouterError):
                router.check_receipt(receipt(**changes), T)

    def test_private_identity_and_no_competition(self):
        m = {'id': T['ref'], 'id_no': T['id'], 'title': T['title'], 'is_private': True,
             'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': False,
             'enable_tpu': False, 'enable_internet': True,
             'dataset_sources': [], 'kernel_sources': [], 'competition_sources': [], 'model_sources': [], 'keywords': []}
        router.check_metadata(m, T)
        for key, val in [('id_no', 7), ('is_private', False), ('competition_sources', ['wrong']), ('enable_gpu', True)]:
            with self.assertRaises(router.RouterError):
                router.check_metadata(dict(m, **{key: val}), T)

    def test_backlog_and_duplicate_marker_rejected(self):
        nb = json.loads(json.dumps(NB))
        ids = [f'id-{i:03d}' for i in range(router.MAX_LEDGER)]
        nb['cells'].append({'cell_type': 'markdown', 'source': router.V2 + json.dumps(ids, separators=(',', ':')) + '\n'})
        with self.assertRaises(router.RouterError):
            router.prepare(nb, dict(REQ, previous_id=ids[-1]), T)
        nb['cells'].append({'cell_type': 'markdown', 'source': router.V1 + 'another-id\n'})
        with self.assertRaises(router.RouterError):
            router.prepare(nb, REQ, T)

    def test_refuse_github_retry_before_remote(self):
        class Never:
            def kernels_status(self, *args):
                raise AssertionError('remote access forbidden')
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '2'}):
            with self.assertRaises(router.RouterError):
                router.run(Never(), REQ)

    def test_known_targets_and_gpu_exact_metadata(self):
        self.assertEqual(len(router.TARGETS), 5)
        for name, target in router.TARGETS.items():
            self.assertTrue(target['id'] > 0)
            self.assertTrue(target['ref'].startswith('sumuji/'))
        q = router.TARGETS['qwen25-rerun']
        meta = {'id': q['ref'], 'id_no': q['id'], 'title': q['title'], 'is_private': True,
                'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': True,
                'enable_internet': False, 'enable_tpu': False, 'machine_shape': 'NvidiaTeslaT4',
                'dataset_sources': [], 'kernel_sources': [], 'competition_sources': [],
                'model_sources': ['qwen-lm/qwen2.5/Transformers/7b-instruct/1'], 'keywords': []}
        router.check_metadata(meta, q)
        for key, val in [('enable_gpu', False), ('machine_shape', 'unknown'),
                         ('model_sources', ['qwen-lm/qwen2.5/transformers/7b-instruct/1'])]:
            with self.assertRaises(router.RouterError):
                router.check_metadata(dict(meta, **{key: val}), q)

    def test_check_specific_version_and_sdk_response(self):
        nb = json.loads(json.dumps(NB))
        nb['cells'].append({'cell_type': 'markdown', 'source': router.V1 + REQ['previous_id'] + '\n'})
        meta = {'id': T['ref'], 'id_no': T['id'], 'title': T['title'], 'is_private': True,
                'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': False,
                'enable_tpu': False, 'enable_internet': True, 'code_file': 'job.ipynb',
                'dataset_sources': [], 'kernel_sources': [], 'competition_sources': [], 'model_sources': [], 'keywords': []}

        class Fake:
            def __init__(self):
                self.nb = nb
                self.pushed = 0
                self.status_refs = []
                self.pulled_refs = []
            def kernels_status(self, ref):
                self.status_refs.append(ref)
                return types.SimpleNamespace(status=types.SimpleNamespace(name='COMPLETE'))
            def kernels_pull(self, ref, path, **kwargs):
                self.pulled_refs.append(ref)
                root = pathlib.Path(path)
                (root / 'kernel-metadata.json').write_text(json.dumps(meta), encoding='utf-8')
                (root / 'job.ipynb').write_text(json.dumps(self.nb), encoding='utf-8')
            def kernels_push(self, path):
                self.pushed += 1
                root = pathlib.Path(path)
                self.nb = json.loads((root / 'job.ipynb').read_text(encoding='utf-8'))
                self.payload = json.loads((root / 'kernel-metadata.json').read_text(encoding='utf-8'))
                return receipt()
        fake = Fake()
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '1'}), patch.dict(router.TARGETS, {REQ['kind']: T}):
            self.assertEqual(router.run(fake, REQ, timeout_seconds=10, sleep=lambda _: None), 3)
        self.assertEqual(fake.pushed, 1)
        self.assertIn(T['ref'] + '/3', fake.status_refs)
        self.assertIn(T['ref'] + '/3', fake.pulled_refs)
        self.assertTrue(fake.payload['is_private'])
        self.assertEqual(fake.payload['competition_sources'], [])

    def test_reused_request_skips_push_after_verify(self):
        nb = json.loads(json.dumps(NB))
        nb['cells'].append({'cell_type': 'markdown', 'source': router.V2 +
                            json.dumps([REQ['previous_id'], REQ['id']], separators=(',', ':')) + '\n'})
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '1'}), patch.dict(router.TARGETS, {REQ['kind']: T}), \
             patch.object(router, 'state', return_value='COMPLETE'), \
             patch.object(router, 'pull', return_value=({}, nb)):
            self.assertIsNone(router.run(object(), REQ))


if __name__ == '__main__':
    unittest.main()

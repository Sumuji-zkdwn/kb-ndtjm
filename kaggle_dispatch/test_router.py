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
    def test_squares_target_requires_private_cpu_offline_and_no_inputs(self):
        target = router.TARGETS['squares-v8-diagnostic-rerun']
        self.assertEqual(target['id'], 141798233)
        self.assertEqual(target['hash'], '09e737183d9e560fa989115e927077a3003598eea325d5c261e635c371d12c22')
        meta = {'id': target['ref'], 'id_no': target['id'], 'title': target['title'], 'is_private': True,
                'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': False, 'enable_tpu': False,
                'enable_internet': False, 'dataset_sources': [], 'kernel_sources': [],
                'competition_sources': [], 'model_sources': [], 'keywords': []}
        router.check_metadata(meta, target)
        for name, value in [('enable_internet', True), ('enable_gpu', True), ('is_private', False),
                            ('id_no', 1), ('dataset_sources', ['bad']), ('kernel_sources', ['bad']),
                            ('competition_sources', ['bad']), ('model_sources', ['bad'])]:
            with self.assertRaises(router.RouterError):
                router.check_metadata(dict(meta, **{name: value}), target)

    def test_squares_history_accepts_only_verified_previous_id(self):
        target = dict(router.TARGETS['squares-v8-diagnostic-rerun'])
        target['hash'] = router.canonical(NB)[0]
        nb = json.loads(json.dumps(NB))
        previous = 'squares-diagnostic-20261031-a1'
        history = ['receipt-probe-20261031-d5', previous]
        nb['cells'].append({'cell_type': 'markdown', 'source': router.V2 + json.dumps(history, separators=(',', ':')) + '\n'})
        req = {'id':'squares-diagnostic-20261031-a2','previous_id':previous,'kind':'squares-v8-diagnostic-rerun'}
        self.assertEqual(router.check_request(req)['id'], target['id'])
        prepared, digest, next_history = router.prepare(nb, req, target)
        self.assertEqual(next_history, history + [req['id']])
        self.assertEqual(digest, target['hash'])
        self.assertIsNotNone(prepared)
        with self.assertRaises(router.RouterError):
            router.prepare(nb, dict(req, previous_id='receipt-probe-20261031-d5'), target)

    def test_squares_dispatch_keeps_offline_and_checks_exact_version(self):
        target = dict(router.TARGETS['squares-v8-diagnostic-rerun'])
        target['hash'] = router.canonical(NB)[0]
        previous = 'squares-diagnostic-20261031-a1'
        req = {'id':'squares-diagnostic-20261031-a2','previous_id':previous,'kind':'squares-v8-diagnostic-rerun'}
        nb = json.loads(json.dumps(NB))
        nb['cells'].append({'cell_type':'markdown','source':router.V2+json.dumps([previous],separators=(',',':'))+'\n'})
        meta = {'id':target['ref'],'id_no':target['id'],'title':target['title'],'is_private':True,
                'language':'python','kernel_type':'notebook','enable_gpu':False,'enable_tpu':False,
                'enable_internet':False,'code_file':'job.ipynb','dataset_sources':[],'kernel_sources':[],
                'competition_sources':[],'model_sources':[],'keywords':[]}
        class Fake:
            def __init__(self): self.nb=nb; self.refs=[]
            def kernels_status(self, ref):
                self.refs.append(ref); return types.SimpleNamespace(status=types.SimpleNamespace(name='COMPLETE'))
            def kernels_pull(self, ref, path, **kwargs):
                p=pathlib.Path(path); (p/'kernel-metadata.json').write_text(json.dumps(meta),encoding='utf-8'); (p/'job.ipynb').write_text(json.dumps(self.nb),encoding='utf-8')
            def kernels_push(self,path):
                p=pathlib.Path(path);self.payload=json.loads((p/'kernel-metadata.json').read_text(encoding='utf-8')); self.nb=json.loads((p/'job.ipynb').read_text(encoding='utf-8'))
                return receipt(ref='/code/'+target['ref'], kernel_id=target['id'], version_number=7)
        fake=Fake()
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT':'1'}), patch.dict(router.TARGETS,{req['kind']:target}):
            self.assertEqual(router.run(fake,req,timeout_seconds=10,sleep=lambda _:None),7)
        self.assertFalse(fake.payload['enable_internet'])
        self.assertFalse(fake.payload['enable_gpu'])
        self.assertIn(target['ref']+'/7',fake.refs)

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
        for value in (f"/code/{T['ref']}", f"https://www.kaggle.com/code/{T['ref']}", f"https://www.kaggle.com/{T['ref']}",
                      f"https://kaggle.com/code/{T['ref']}"):
            self.assertEqual(router.check_receipt(receipt(ref=value), T), 3)
        for value in (f"/code/{T['ref']}?foo=bar", f"/code/{T['ref']}/more", f"//code/{T['ref']}",
                      f"https://evil.example/{T['ref']}", f"http://www.kaggle.com/code/{T['ref']}",
                      f"https://www.kaggle.com@evil.example/code/{T['ref']}",
                      f"https://www.kaggle.com/code/{T['ref']}?other=1", f"https://www.kaggle.com:443/code/{T['ref']}"):
            with self.assertRaises(router.RouterError):
                router.check_receipt(receipt(ref=value), T)
        for field in router.FIELDS:
            with self.assertRaises(router.RouterError):
                router.check_receipt(receipt(**{field: ['bad']}), T)
            with self.assertRaises(router.RouterError):
                router.check_receipt(receipt(**{field: None}), T)
        for changes in ({'error': 'bad'}, {'kernel_id': 0}, {'ref': 'wrong'}, {'version_number': 0}):
            with self.assertRaises(router.RouterError):
                router.check_receipt(receipt(**changes), T)

    def test_identity_diagnostic_is_categorical_only(self):
        got = router.receipt_identity_categories(receipt(ref=f"https://www.kaggle.com/code/{T['ref']}?x=secret", kernel_id=0), T)
        self.assertEqual(got, {'ref_category': 'kaggle_exact_path_with_query', 'kernel_id_category': 'zero_or_missing'})
        self.assertNotIn('secret', json.dumps(got))

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
        self.assertEqual(len(router.TARGETS), 8)
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


    def test_phase_needle_private_offline_no_inputs(self):
        q = router.TARGETS['phase-needle-rerun']
        meta = {'id': q['ref'], 'id_no': q['id'], 'title': q['title'], 'is_private': True,
                'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': False,
                'enable_internet': False, 'enable_tpu': False, 'machine_shape': 'None',
                'dataset_sources': [], 'kernel_sources': [], 'competition_sources': [],
                'model_sources': [], 'keywords': []}
        router.check_metadata(meta, q)
        for key, val in [('enable_internet', True), ('is_private', False), ('enable_gpu', True),
                         ('dataset_sources', ['unexpected']), ('id_no', 999)]:
            with self.assertRaises(router.RouterError):
                router.check_metadata(dict(meta, **{key: val}), q)

    def test_phase_needle_first_request_requires_no_prior_id(self):
        q = dict(router.TARGETS['phase-needle-rerun'], hash=router.canonical(NB)[0])
        req = {'kind': 'phase-needle-rerun', 'id': 'phase-needle-20261031-001', 'previous_id': 'none'}
        prepared, digest, ledger = router.prepare(NB, req, q)
        self.assertEqual(ledger, [req['id']])
        self.assertEqual(digest, q['hash'])
        self.assertEqual(router.source(prepared['cells'][-1]), router.V2 + '["phase-needle-20261031-001"]\n')
        with self.assertRaises(router.RouterError):
            router.prepare(NB, dict(req, previous_id='wrong-previous'), q)

    def test_quartic_initial_cpu_metadata_transition_only_without_marker(self):
        q = router.TARGETS['quartic-energy-rerun']
        meta = {'id': q['ref'], 'id_no': q['id'], 'title': q['title'], 'is_private': True,
                'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': False,
                'enable_internet': True, 'enable_tpu': False, 'machine_shape': 'None',
                'dataset_sources': [], 'kernel_sources': [], 'competition_sources': [],
                'model_sources': [], 'keywords': []}
        router.check_metadata(meta, q, NB)
        marked = json.loads(json.dumps(NB))
        marked['cells'].append({'cell_type': 'markdown', 'source': router.V2 + '["quartic-test-001"]\n'})
        with self.assertRaises(router.RouterError):
            router.check_metadata(meta, q, marked)
        for key,val in [('machine_shape','unexpected'), ('enable_gpu',None), ('model_sources',['bad'])]:
            with self.assertRaises(router.RouterError):
                router.check_metadata(dict(meta, **{key: val}), q, NB)
        transitioned = dict(meta, enable_gpu=True, machine_shape='NvidiaTeslaT4')
        router.check_metadata(transitioned, q, marked)


    def test_quartic_transition_pushes_gpu_and_checks_finished_version(self):
        target = dict(router.TARGETS['quartic-energy-rerun'])
        target['hash'] = router.canonical(NB)[0]
        req = {'kind': 'quartic-energy-rerun', 'id': 'quartic-20261031-001', 'previous_id': 'none'}
        meta = {'id': target['ref'], 'id_no': target['id'], 'title': target['title'], 'is_private': True,
                'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': False,
                'enable_tpu': False, 'enable_internet': True, 'code_file': 'job.ipynb',
                'machine_shape': 'None', 'dataset_sources': [], 'kernel_sources': [],
                'competition_sources': [], 'model_sources': [], 'keywords': []}
        class Fake:
            def __init__(self):
                self.nb = json.loads(json.dumps(NB)); self.meta = dict(meta); self.refs=[]
            def kernels_status(self, ref):
                self.refs.append(ref); return types.SimpleNamespace(status=types.SimpleNamespace(name='COMPLETE'))
            def kernels_pull(self, ref, path, **kwargs):
                root = pathlib.Path(path)
                (root / 'kernel-metadata.json').write_text(json.dumps(self.meta), encoding='utf-8')
                (root / 'job.ipynb').write_text(json.dumps(self.nb), encoding='utf-8')
            def kernels_push(self, path):
                root = pathlib.Path(path)
                self.nb = json.loads((root / 'job.ipynb').read_text(encoding='utf-8'))
                self.payload = json.loads((root / 'kernel-metadata.json').read_text(encoding='utf-8'))
                self.meta.update(enable_gpu=self.payload['enable_gpu'], machine_shape=self.payload['machine_shape'])
                return receipt(ref='/code/'+target['ref'], kernel_id=target['id'], version_number=2)
        fake = Fake()
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '1'}), patch.dict(router.TARGETS, {req['kind']: target}):
            self.assertEqual(router.run(fake, req, timeout_seconds=10, sleep=lambda _: None), 2)
        self.assertIs(fake.payload['enable_gpu'], True)
        self.assertEqual(fake.payload['machine_shape'], 'NvidiaTeslaT4')
        self.assertIn(target['ref'] + '/2', fake.refs)

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

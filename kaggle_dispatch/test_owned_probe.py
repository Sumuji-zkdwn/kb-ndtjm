import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('owned_probe', Path(__file__).with_name('owned_probe.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
META = {'id': 'sumuji/dalcia-ideas-43-kaggle', 'id_no': 123, 'is_private': True,
        'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': False,
        'dataset_sources': [], 'competition_sources': [], 'kernel_sources': [], 'model_sources': []}
NB = {'nbformat': 4, 'cells': [{'cell_type': 'code', 'source': ['print(1)\n'], 'outputs': []}]}

class ProbeTests(unittest.TestCase):
    def test_code_fingerprint_ignores_outputs_and_list_vs_string(self):
        a = m.canonical(NB)
        b = m.canonical({'nbformat': 4, 'cells': [{'cell_type': 'code', 'source': 'print(1)\n',
                                                    'outputs': ['private text']}]})
        self.assertEqual(a, b)
        self.assertNotEqual(a, m.canonical({'nbformat': 4, 'cells': [{'cell_type': 'code', 'source': 'print(2)\n'}]}))

    def test_summary_emits_no_source_or_results(self):
        result = m.summary('research', META, NB)
        self.assertTrue(result['private'])
        self.assertTrue(result['competition_empty'])
        self.assertNotIn('print(1)', str(result))

    def test_privacy_identity_and_sources_are_verified(self):
        for v in ({**META, 'is_private': False}, {**META, 'id': 'someone/else'},
                  {**META, 'id_no': 0}, {**META, 'competition_sources': None}):
            with self.subTest(v=v), self.assertRaises(m.ProbeError):
                m.summary('research', v, NB)

    def test_source_field_and_cell_count_are_bounded(self):
        for v in ({'nbformat': 4, 'cells': [{'cell_type': 'code', 'source': 7}]},
                  {'nbformat': 4, 'cells': NB['cells'] * 201}):
            with self.assertRaises(m.ProbeError):
                m.canonical(v)

if __name__ == '__main__':
    unittest.main()

import json
import unittest
from pathlib import Path
import qwen_source_probe as p

class Tests(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(p.classify('qwen-lm/qwen2.5/transformers/7b-instruct/1')['kind'], 'exact')
    def test_known_path_variant(self):
        self.assertEqual(p.classify('/kaggle/input/models/qwen-lm/qwen2.5/transformers/7b-instruct/1')['kind'], 'recognized_public_model_variant')
    def test_other_never_printed(self):
        secret='sensitive-string-example'
        result=json.dumps(p.classify(secret))
        self.assertNotIn(secret,result)
        self.assertIn('other_suppressed',result)
    def test_non_string(self):
        self.assertEqual(p.classify({'private':'value'})['kind'],'non_string')
    def test_request(self):
        request=json.loads((Path(__file__).parent/'qwen_probe_request.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(request, {'id':'qwen-source-probe-20261031-b1','kind':'qwen-metadata-read-only'})

if __name__ == '__main__':
    unittest.main()

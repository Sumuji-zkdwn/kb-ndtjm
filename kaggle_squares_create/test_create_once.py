import contextlib,io,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import create_once as c

def item(ref,slug,ident):return NS(ref=ref,slug=slug,id=ident)
def response():return NS(ref='/code/'+c.REF,kernel_id=999,version_number=1,error='',**{f:[] for f in c.FIELDS})
class Fake:
    def __init__(self,duplicate=False,badmeta=None,badsource=False):
        self.duplicate=duplicate;self.badmeta=badmeta or {};self.badsource=badsource;self.pushes=0
    def kernels_list_with_response(self,**kw):
        entries=[item(c.ANCHOR,c.ANCHOR.split('/')[-1],c.ANCHOR_ID)]
        if self.duplicate:entries.append(item(c.REF,c.TITLE,999))
        return NS(kernels=entries,next_page_token='')
    def kernels_push(self,path):
        self.pushes+=1;self.sent_meta=json.loads((Path(path)/'kernel-metadata.json').read_text())
        self.sent_nb=(Path(path)/'job.ipynb').read_bytes();return response()
    def kernels_status(self,ref):return NS(status=NS(name='COMPLETE'))
    def kernels_pull(self,ref,path,metadata=True,quiet=True):
        d={'id':c.REF,'id_no':999,'title':c.TITLE,'language':'python','kernel_type':'notebook','code_file':'job.ipynb','is_private':True,'enable_gpu':False,'enable_tpu':False,'enable_internet':False,'dataset_sources':[],'competition_sources':[],'kernel_sources':[],'model_sources':[]};d.update(self.badmeta)
        p=Path(path);(p/'kernel-metadata.json').write_text(json.dumps(d),encoding='utf-8')
        nb=json.loads(self.sent_nb)
        if self.badsource:nb['cells'][0]['source']=['tampered\n']
        (p/'job.ipynb').write_text(json.dumps(nb),encoding='utf-8')

class Tests(unittest.TestCase):
    def run_fake(self,api):
        with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'1'}),contextlib.redirect_stdout(io.StringIO()) as out:
            result=c.run(api,sleep=lambda x:None)
        self.assertNotIn('payload',out.getvalue().lower());return result
    def test_one_private_cpu_offline_no_inputs(self):
        a=Fake();self.assertEqual(self.run_fake(a),(999,1));self.assertEqual(a.pushes,1)
        m=a.sent_meta;self.assertTrue(m['is_private']);self.assertFalse(m['enable_gpu']);self.assertFalse(m['enable_internet'])
        for name in ('dataset_sources','competition_sources','kernel_sources','model_sources'):self.assertEqual(m[name],[])
    def test_existing_stops_before_push(self):
        a=Fake(duplicate=True)
        with self.assertRaises(c.Stop):self.run_fake(a)
        self.assertEqual(a.pushes,0)
    def test_wrong_account_stops(self):
        a=Fake();a.kernels_list_with_response=lambda **kw:NS(kernels=[],next_page_token='')
        with self.assertRaises(c.Stop):self.run_fake(a)
        self.assertEqual(a.pushes,0)
    def test_retry_stops(self):
        a=Fake()
        with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'2'}),self.assertRaises(c.Stop):c.run(a)
        self.assertEqual(a.pushes,0)
    def test_unknown_saved_privacy_stops_after_push(self):
        a=Fake(badmeta={'is_private':False})
        with self.assertRaises(c.Stop):self.run_fake(a)
        self.assertEqual(a.pushes,1)
    def test_wrong_internet_stops_after_push(self):
        a=Fake(badmeta={'enable_internet':True})
        with self.assertRaises(c.Stop):self.run_fake(a)
    def test_changed_source_stops(self):
        a=Fake(badsource=True)
        with self.assertRaises(c.Stop):self.run_fake(a)
    def test_ambiguous_response_stops(self):
        a=Fake();a.kernels_push=lambda path:NS(ref='evil',kernel_id=999,version_number=1,error='',**{f:[] for f in c.FIELDS})
        with self.assertRaises(c.Stop):self.run_fake(a)
    def test_ref_rejects_untrusted_query(self):
        self.assertFalse(c.trusted_ref('https://www.kaggle.com/code/'+c.REF+'?x=1'))
    def test_local_source_hash(self):
        self.assertGreater(len(c.validate_local()),1000)
    def test_pagination_loop_stops(self):
        a=Fake();a.kernels_list_with_response=lambda **kw:NS(kernels=[],next_page_token='repeated')
        with self.assertRaises(c.Stop):c.absence(a)
if __name__=='__main__':unittest.main()

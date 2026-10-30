import contextlib,copy,io,json,os,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import anchor_send as a
import router
def fixture():
    n=json.loads((a.ROOT/'synthetic_fixture.ipynb').read_text(encoding='utf-8'))
    n['cells'].append({'cell_type':'markdown','metadata':{},'source':router.V2+json.dumps(['receipt-probe-20261031-d5'],separators=(',',':'))+'\n'})
    return n
def metadata():return {'id':a.TARGET['ref'],'id_no':a.TARGET['id'],'title':a.TARGET['title'],'code_file':'job.ipynb','language':'python','kernel_type':'notebook','is_private':True,'enable_gpu':False,'enable_tpu':False,'enable_internet':False,'keywords':[],'dataset_sources':[],'competition_sources':[],'kernel_sources':[],'model_sources':[]}
class Fake:
 def __init__(self,meta=None,nb=None):self.meta=meta or metadata();self.old=nb or fixture();self.pushes=0;self.new=None;self.pulls=0
 def kernels_status(self,ref):return NS(status=NS(name='COMPLETE'))
 def kernels_pull(self,ref,path,metadata=True,quiet=True):
  self.pulls+=1;p=Path(path);(p/'kernel-metadata.json').write_text(json.dumps(self.meta));(p/'job.ipynb').write_text(json.dumps(self.new if ref.endswith('/6') else self.old))
 def kernels_push(self,path):
  self.pushes+=1;p=Path(path);self.sent_meta=json.loads((p/'kernel-metadata.json').read_text());self.new=json.loads((p/'job.ipynb').read_text())
  return NS(ref='/code/'+a.TARGET['ref'],kernel_id=a.TARGET['id'],version_number=6,error='',**{f:[] for f in router.FIELDS})
class Test(unittest.TestCase):
 def run_fake(self,api):
  with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'1'}),contextlib.redirect_stdout(io.StringIO()) as out:r=a.run(api,sleep=lambda x:None)
  self.assertNotIn('payload',out.getvalue().lower());return r
 def test_send_and_verify(self):
  f=Fake();self.assertEqual(self.run_fake(f),6);self.assertEqual(f.pushes,1);self.assertGreaterEqual(f.pulls,4)
  self.assertTrue(f.sent_meta['is_private']);self.assertFalse(f.sent_meta['enable_internet']);self.assertFalse(f.sent_meta['enable_gpu'])
  for key in ('dataset_sources','competition_sources','kernel_sources','model_sources'):self.assertEqual(f.sent_meta[key],[])
 def test_wrong_anchor_id_stops(self):
  m=metadata();m['id_no']=123;f=Fake(meta=m)
  with self.assertRaises(router.RouterError):self.run_fake(f)
  self.assertEqual(f.pushes,0)
 def test_public_stops(self):
  m=metadata();m['is_private']=False;f=Fake(meta=m)
  with self.assertRaises(router.RouterError):self.run_fake(f)
  self.assertEqual(f.pushes,0)
 def test_internet_stops(self):
  m=metadata();m['enable_internet']=True;f=Fake(meta=m)
  with self.assertRaises(a.Stop):self.run_fake(f)
  self.assertEqual(f.pushes,0)
 def test_unexpected_input_stops(self):
  m=metadata();m['dataset_sources']=['unexpected'];f=Fake(meta=m)
  with self.assertRaises(router.RouterError):self.run_fake(f)
  self.assertEqual(f.pushes,0)
 def test_wrong_prior_marker_stops(self):
  nb=fixture();nb['cells'][-1]['source']=router.V2+'["some-other-id"]\n';f=Fake(nb=nb)
  with self.assertRaises(router.RouterError):self.run_fake(f)
  self.assertEqual(f.pushes,0)
 def test_wrong_old_source_stops(self):
  nb=fixture();nb['cells'][0]['source']=['tampered'];f=Fake(nb=nb)
  with self.assertRaises(router.RouterError):self.run_fake(f)
  self.assertEqual(f.pushes,0)
 def test_retry_stops(self):
  f=Fake()
  with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'2'}),self.assertRaises(a.Stop):a.run(f)
  self.assertEqual(f.pushes,0)
 def test_current_running_stops(self):
  f=Fake();f.kernels_status=lambda x:NS(status=NS(name='RUNNING'))
  with self.assertRaises(a.Stop):self.run_fake(f)
  self.assertEqual(f.pushes,0)
 def test_changed_between_reads_stops_before_push(self):
  f=Fake();old=f.kernels_pull
  def mutate(ref,path,metadata=True,quiet=True):
   if f.pulls==1:f.meta['enable_internet']=True
   return old(ref,path,metadata,quiet)
  f.kernels_pull=mutate
  with self.assertRaises(a.Stop):self.run_fake(f)
  self.assertEqual(f.pushes,0)
 def test_remote_failure_stops_without_retry(self):
  f=Fake();f.kernels_status=lambda ref:NS(status=NS(name='ERROR' if ref.endswith('/6') else 'COMPLETE'))
  with self.assertRaises(a.Stop):self.run_fake(f)
  self.assertEqual(f.pushes,1)
 def test_bad_receipt_stops_without_retry(self):
  f=Fake();old=f.kernels_push
  def bad(path):r=old(path);r.kernel_id=123;return r
  f.kernels_push=bad
  with self.assertRaises(router.RouterError):self.run_fake(f)
  self.assertEqual(f.pushes,1)
 def test_saved_source_tamper_rejected(self):
  f=Fake();old=f.kernels_push
  def bad(path):r=old(path);f.new['cells'][0]['source']=['tampered'];return r
  f.kernels_push=bad
  with self.assertRaises(a.Stop):self.run_fake(f)
  self.assertEqual(f.pushes,1)
if __name__=='__main__':unittest.main()

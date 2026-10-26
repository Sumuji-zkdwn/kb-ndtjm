"""Negative controls for the complete packet-level reuse correspondence."""
import tempfile
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research/bm_port'))
from uncompute import Builder
from bm_scratch_audit import compare

class CorrespondenceTest(unittest.TestCase):
    def make(self,path,reused=False,wrong=False,change_condition=False):
        b=Builder();syn=b.qubits(840);b.claim('syn',syn)
        held=b.qubits(3);b.claim('held',held)
        owned=b.qubits(5 if reused else 8);b.claim('owned',owned)
        with b.phase('variable_mask_forney'):
            targets=held if reused else owned[-3:]
            b.cx(0,targets[0]);b.cx(0,targets[0])
            b.z(1,cond=1 if change_condition else 0)
        if wrong:b.x(2)
        b.release_recycle('owned',owned);b.release_recycle('held',held);b.write(path)

    def test_packet_correspondence_and_negative_controls(self):
        with tempfile.TemporaryDirectory() as d:
            r,c=Path(d)/'ref.kmb',Path(d)/'new.kmb'
            self.make(r)
            self.make(c,reused=True)
            self.assertEqual(compare(r,c,{848:840,849:841,850:842})['status'],'PASS')
            for kwargs in ({'wrong':True},{'change_condition':True}):
                self.make(c,reused=True,**kwargs)
                with self.assertRaises(AssertionError):compare(r,c,{848:840,849:841,850:842})

if __name__=='__main__':unittest.main()

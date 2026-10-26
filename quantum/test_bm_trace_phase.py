"""Exact local inverse-phase and integration-emitter regression tests."""
import sys,json,copy,math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research/bm_port'))
from trace_phase import TracePhase
from trace_phase_probe import verify
from dqi_gate import reuse_comparison_checkpoint,validate_comparison_measurement,BM_SCRATCH3_CHECKPOINT_SHA

class TraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.p=TracePhase()

    def test_full_compositional_ANF_and_negative_controls(self):
        r=verify(self.p)
        self.assertEqual(r['status'],'PASS')
        self.assertEqual(r['new_inverse_plus_phase_Toffoli'],72)
        self.assertEqual(r['middle']['tensor_basis_cases'],10368)

    def test_real_emitter_matches_the_proved_template_and_mask_namespaces(self):
        class Recorder:
            def __init__(self):self.ops=[]
            def raw(self,op,qs,bit=None,cond=None):self.ops.append((op,list(qs),bit,cond))
            def cx(self,s,t):self.raw(0x21,[s,t])
        b=Recorder();self.p.emit(b,list(range(58)),list(range(12)),[(58+i,45+i) for i in range(12)])
        opcodes={'CX':0x21,'CCX':0x31,'CCZ':0x30,'SWAP':0x22,'CZ':0x20,'Z':0x10}
        expected=[]
        for g,qs,c in self.p.operations():
            if g=='HMR':expected.append((0x50,qs,49141,None))
            else:expected.append((opcodes[g],qs,None,None if c is None else 49141 if g in ('Z','CZ') else c))
        self.assertEqual(b.ops,expected)

    def test_pinned_BM_evidence_is_reused_only_after_contract_validation(self):
        path=Path(__file__).resolve().parents[1]/'checkpoints/bm-scratch3-20261027.json'
        report=json.loads(path.read_text())['gates']['full-package']
        reference=copy.deepcopy(report['candidate']);h=report['full']['verifier_sha256']
        v=SimpleNamespace(DEFAULT_NUM_SHOTS=102400,DEFAULT_LOG2_DELTA=-128.0,
            clopper_pearson_upper_bound=lambda k,n,d:-math.expm1(d*math.log(2)/n)+k/n,
            repetition_overhead=lambda e:math.log(2)/-math.log(0.5+2*math.sqrt(e)))
        with patch('dqi_gate.sha',side_effect=[BM_SCRATCH3_CHECKPOINT_SHA,h]):
            full=reuse_comparison_checkpoint(path,reference,'unused',v)
        self.assertEqual(full['cost'],5553345299429.923)
        reference['candidate_sha256']='wrong'
        with self.assertRaises(ValueError),patch('dqi_gate.sha',side_effect=[BM_SCRATCH3_CHECKPOINT_SHA,h]):
            reuse_comparison_checkpoint(path,reference,'unused',v)

if __name__=='__main__':unittest.main()

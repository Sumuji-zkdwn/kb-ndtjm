"""Exact nested-trace phase, real emitter, and preserved comparison evidence."""
import copy,json,math,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research/bm_port'))
from trace_phase3 import TracePhase3
from trace_phase3_probe import verify
from dqi_gate import sha,reuse_comparison_checkpoint,BM_TRACE6_CHECKPOINT_SHA


class NestedTraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.p=TracePhase3()

    def test_exact_composition_and_missing_gate_negative_controls(self):
        r=verify(self.p)
        self.assertEqual(r['status'],'PASS')
        self.assertEqual(r['new_inverse_plus_phase_Toffoli'],69)
        self.assertEqual(r['middle']['tensor_basis_cases'],31104)
        self.assertEqual(r['expected_full_DQI_Toffoli'],719881)

    def test_actual_emitter_matches_proved_operations_and_classical_namespaces(self):
        class Recorder:
            def __init__(self):self.ops=[]
            def raw(self,op,qs,bit=None,cond=None):self.ops.append((op,list(qs),bit,cond))
            def cx(self,s,t):self.raw(0x21,[s,t])
        # Nontrivial physical wire and mask mappings exercise integration rebinding.
        mapping=[100+3*i for i in range(70)];mask=[300+i for i in range(12)]
        b=Recorder();self.p.emit(b,mapping,mask,[(mapping[58+i],mapping[45+i]) for i in range(12)])
        codes={'CX':0x21,'CCX':0x31,'CCZ':0x30,'SWAP':0x22,'CZ':0x20,'Z':0x10}
        expected=[]
        for g,qs,c in self.p.operations():
            if g=='HMR':expected.append((0x50,[mapping[q] for q in qs],49141,None))
            else:expected.append((codes[g],[mapping[q] for q in qs],None,None if c is None else 49141 if g in ('Z','CZ') else mask[c]))
        self.assertEqual(b.ops,expected)

    def test_trace6_comparison_is_hash_pinned_and_contract_checked(self):
        path=Path(__file__).resolve().parents[1]/'checkpoints/bm-tracephase-20261027.json'
        self.assertEqual(sha(path),BM_TRACE6_CHECKPOINT_SHA)
        report=json.loads(path.read_text())['gates']['full-package']
        reference=copy.deepcopy(report['candidate']);h=report['full']['verifier_sha256']
        v=SimpleNamespace(DEFAULT_NUM_SHOTS=102400,DEFAULT_LOG2_DELTA=-128.0,
            clopper_pearson_upper_bound=lambda k,n,d:-math.expm1(d*math.log(2)/n)+k/n,
            repetition_overhead=lambda e:math.log(2)/-math.log(0.5+2*math.sqrt(e)))
        with patch('dqi_gate.sha',side_effect=[BM_TRACE6_CHECKPOINT_SHA,h]):
            full=reuse_comparison_checkpoint(path,reference,'unused',v)
        self.assertEqual(full['cost'],5373037115324.774)
        reference['dqi']['qubits']+=1
        with self.assertRaises(ValueError),patch('dqi_gate.sha',side_effect=[BM_TRACE6_CHECKPOINT_SHA,h]):
            reuse_comparison_checkpoint(path,reference,'unused',v)


if __name__=='__main__':unittest.main()

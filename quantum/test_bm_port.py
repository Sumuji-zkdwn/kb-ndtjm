"""Guard the boundary between the attributed BM emitter and the KMB adapter."""
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research/bm_port'))
from uncompute.builder import Builder
from dqi_gate import inspect_kmb

class AdapterTest(unittest.TestCase):
    def test_stale_measurement_condition_is_rejected(self):
        b=Builder();q=b.qubits(3);m=b.hmr(q[0]);b.hmr(q[1])
        with self.assertRaisesRegex(ValueError,'stale'):b.z(q[2],cond=m)

    def test_alias_unallocated_wire_and_mask_write_are_rejected(self):
        b=Builder();q=b.qubits(3)
        with self.assertRaisesRegex(ValueError,'aliased'):b.ccx(q[0],q[1],q[0])
        with self.assertRaisesRegex(ValueError,'free wire'):b.x(4)
        with self.assertRaisesRegex(ValueError,'read-only'):b.raw(0x40,bit=0)

    def test_allocator_never_resets_dirty_state_to_hide_a_leak(self):
        b=Builder();q=b.qubits(1);b.x(q[0]);before=list(b.p[1])
        b.recycle_all(q);self.assertEqual(b.qubits(1),q)
        self.assertEqual(list(b.p[1]),before)

    def test_claim_replay_and_release_fail_closed(self):
        b=Builder();q=b.qubits(2);b.claim('one',q)
        with self.assertRaisesRegex(ValueError,'ownership'):b.claim('two',q)
        with self.assertRaisesRegex(ValueError,'occupied'):b.reclaim(q)
        with self.assertRaisesRegex(ValueError,'owned'):b.recycle_all(q)
        b.release_recycle('one',q);b.reclaim(q);b.claim('replayed',q)
        self.assertEqual(b.live,set(q))

    def test_complete_register_contract_in_binary_writer(self):
        b=Builder();q=b.qubits(840);b.claim('syn',q)
        with b.phase('identity'):b.x(0);b.x(0)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'dqi.kmb';b.write(p)
            with p.open('rb') as f:r=inspect_kmb(f)
        self.assertEqual((r['registers'],r['qubits'],r['bits']),(4165,840,49142))
        self.assertEqual(r['3q_ops'],0)

if __name__=='__main__':unittest.main()

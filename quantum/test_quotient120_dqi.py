"""Reject caller changes that violate the measured quotient's full contract."""
import copy
import json
from pathlib import Path
import unittest

from eea_quotient_dqi import instructions
from quotient120_dqi import match_quotient
import test_dqi_gate


class Quotient120MappingTest(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        local = instructions((root/'research/eea_boolean/quotient-local.kmx').read_text())
        resets = [(0x12,[q]) for q in list(range(57,69))+list(range(12,45))+list(range(82,109))]
        self.template = resets+local
        self.qmap = list(range(100,209))[::-1]
        self.bmap = list(range(49140,49153))[::-1]
        self.actual = []
        for op,values in self.template:
            nq = (op>>4)&3
            self.actual.append((op,[self.qmap[v] if i<nq else self.bmap[v]
                                    for i,v in enumerate(values)]))

    def test_entire_caller_under_injective_renaming(self):
        q,b = match_quotient(self.template,self.actual)
        self.assertEqual([q[i] for i in range(109)],self.qmap)
        self.assertEqual([b[i] for i in range(13)],self.bmap)

    def test_missing_phase_reset_or_changed_control_rejected(self):
        phase = next(i for i,(op,_) in enumerate(self.actual) if op==0xa0)
        for index in (phase,0):
            broken = self.actual[:index]+self.actual[index+1:]
            with self.assertRaises(ValueError): match_quotient(self.template,broken)
        broken = copy.deepcopy(self.actual)
        index = next(i for i,(op,_) in enumerate(broken) if op==0x31)
        broken[index][1][0] = broken[index][1][1]
        with self.assertRaises(ValueError): match_quotient(self.template,broken)

    def test_observable_classical_register_rejected(self):
        broken = [(op,[v if i<((op>>4)&3) else 0 if v==49140 else v
                       for i,v in enumerate(values)]) for op,values in self.actual]
        with self.assertRaisesRegex(ValueError,'temporary'): match_quotient(self.template,broken)


class Multiply42ComparisonTest(test_dqi_gate.ComparisonEvidenceTest):
    def setUp(self):
        super().setUp()
        root = Path(__file__).resolve().parents[1]
        self.report = json.loads((root/'checkpoints/multiply42-full-package-20261026.json').read_text())['all_site_gates']['gates']['full-package']
        self.reference = copy.deepcopy(self.report['candidate'])

    def test_recorded_reference_measurement_is_consistent(self):
        self.assertEqual(self.check()['cost'],16238698669232.152)

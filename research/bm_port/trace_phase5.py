"""Local PR7 variant: 68 Toffoli-like inverse/phase block.

Uses the pinned upstream emitter for the unmodified G/H construction and cleanup.
The three-AND cube stage and three-CCZ pairing are replaced by a five-AND scalar
trace network. No full-DQI build or official verification is implied.
"""
from collections import Counter

from trace_phase import convert
from trace_phase3 import TracePhase3
from trace_phase5_scalar import emit_scalar


class TracePhase5(TracePhase3):
    def __init__(self):
        super().__init__()
        m = self.m
        forward, erase = m.Emitter(), m.Emitter()
        for _, _, prods, lins in m.STAGES[:2]:
            for s, t in lins:
                forward.emit('CX', s, t)
            for a, b, targets in prods:
                forward.prod(a, b, targets)
        for _, targets, prods, lins in reversed(m.STAGES[:2]):
            for target in reversed(targets):
                erase.erase_bit(target, prods, lins)
        self.forward, self.erase = convert(forward.ops), convert(erase.ops)
        # B is q30..32; H is q36..38. Reuse former cube3 and unused old Y6.
        self.scalar_inputs = [30, 31, 32, 36, 37, 38]
        self.scalar_scratch = [33, 34, 35, 39, 40]
        compute, phase, cleanup = emit_scalar(m, self.scalar_inputs, self.scalar_scratch, 57)
        self.scalar_forward = convert(compute)
        self.scalar_pairing = convert(phase)
        self.scalar_erase = convert(cleanup)
        assert Counter(g for g, _, _ in self.forward)['CCX'] == 21
        assert Counter(g for g, _, _ in self.scalar_forward)['CCX'] == 3
        assert Counter(g for g, _, _ in self.scalar_forward)['CCZ'] == 2

    def middle_steps(self):
        mask = [('CX', [45 + j, 12 + i], k) for j, i, k in self.masked]
        return [None, mask, None, self.coefficient_forward, self.nested_forward,
                self.scalar_forward, self.scalar_pairing, self.scalar_erase,
                self.nested_erase, self.coefficient_erase,
                None, list(reversed(mask)), None]

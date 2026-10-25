#!/usr/bin/env python3
"""Replace ONE pinned v1.0 phase block, preserving the rest of the complete KMB.

No Kaggle API or submissions. Requires numpy; Kickmix is optional for --parse.
The r=1 specialization of the existing WFS UV^2 kernel is conjugated by
inverse Frobenius on V to implement the baseline's UV phase.
"""
import argparse
from collections import Counter
import hashlib
import json
import mmap
from pathlib import Path
import struct
import zipfile

import numpy as np

from dqi_gate import BASE_SHA, MAGIC, sha
from wfs_mobile_ci import amul, compile_ops, mul, verify_exact

BASE_DQI_SHA = "959471d05a26373b4f14ca0cae2d8639ea25f18170d9f6532139aa51ccc04995"
START, STOP = 51505, 51763  # zero-based, half-open; preserve both INFO_TAG boundaries
POLY = 0x1053
LHS = list(range(1740, 1752))
RHS = list(range(1833, 1845))
MASK = list(range(49140, 49152))
SCRATCH_Q, SCRATCH_B = 1821, 49152
OPCODES = {"CX": 0x21, "SWAP": 0x22, "CZ": 0x20,
           "CX_IF": 0xa1, "CZ_IF": 0xa0,
           "BIT_STORE0": 0x40, "BIT_INVERT_IF": 0xc2,
           "HMR": 0x50}
OPNAMES = {v: k for k, v in OPCODES.items()}


def targets(op):
    q = {0: [], 1: [7], 2: [5, 6], 3: [2, 3, 4]}[(op >> 4) & 3]
    return q + ([8] if op & 64 else []) + ([9] if op & 128 else [])


def selected(ops, packet):
    if 2 <= packet <= 7:
        return ((ops >> 4) & 3) == {2: 3, 3: 3, 4: 3, 5: 2, 6: 2, 7: 1}[packet]
    return (ops & {8: 64, 9: 128}[packet]) != 0


class KMB:
    def __init__(self, path):
        self.file = open(path, "rb")
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        if self.data[:16] != MAGIC:
            raise ValueError("KMB magic mismatch")
        self.header = struct.unpack_from("<4I9Q", self.data, 16)
        self.packets, self.registers = {}, {}
        pos = 104
        while pos < len(self.data):
            kind, size = struct.unpack_from("<QQ", self.data, pos)
            payload = pos + 16
            if payload + size > len(self.data):
                raise ValueError("truncated KMB packet")
            if kind == 0:
                nl, count = struct.unpack_from("<II", self.data, payload)
                name = self.data[payload+8:payload+8+nl].decode()
                self.registers[name] = list(struct.unpack_from("<"+"I"*count, self.data, payload+8+nl))
            else:
                if kind in self.packets:
                    raise ValueError("this pinned converter requires one packet per SOA array")
                self.packets[kind] = (payload, size)
            pos = payload + size
        if pos != len(self.data) or set(self.packets) != set(range(1, 12)):
            raise ValueError("unexpected KMB packet layout")
        p, size = self.packets[1]
        self.ops = np.frombuffer(self.data, dtype="u1", count=size, offset=p)

    def array(self, kind):
        p, size = self.packets[kind]
        return np.frombuffer(self.data, dtype="<u4", count=size//4, offset=p)

    def decode(self, start, stop):
        cursors = {k: int(np.count_nonzero(selected(self.ops[:start], k))) for k in range(2, 10)}
        result = []
        for op in self.ops[start:stop]:
            op = int(op)
            vals = []
            for k in targets(op):
                vals.append(int(self.array(k)[cursors[k]]))
                cursors[k] += 1
            result.append((op, vals))
        return result


def linear_sqrt():
    # In GF(2^12), (v^(2^11))^2 = v. Compile that invertible linear map.
    columns = []
    for i in range(12):
        x = 1 << i
        for _ in range(11):
            x = mul(x, x, POLY)
        columns.append(x)
    rows = [sum(((columns[c] >> r) & 1) << c for c in range(12)) for r in range(12)]
    reduction = []
    for c in range(12):
        pivot = next(r for r in range(c, 12) if (rows[r] >> c) & 1)
        if pivot != c:
            rows[pivot], rows[c] = rows[c], rows[pivot]
            reduction.append((0x22, [RHS[c], RHS[pivot]]))
        for r in range(12):
            if r != c and (rows[r] >> c) & 1:
                rows[r] ^= rows[c]
                reduction.append((0x21, [RHS[c], RHS[r]]))
    assert rows == [1 << i for i in range(12)]
    return list(reversed(reduction)), reduction


def replacement():
    before, after = linear_sqrt()
    mapping = dict(enumerate(LHS + RHS))
    mapping[25] = SCRATCH_Q
    out = before[:]
    for line in compile_ops(POLY, 1):
        parts = line.split()
        if parts[0] == "CCZ":
            # r=1, hence CCZ(root, scratch, V[d]) becomes CZ(scratch, V[d]).
            assert parts[1] == "q24"
            out.append((0x20, [mapping[int(x[1:])] for x in parts[2:4]]))
        else:
            name = parts[0] + ("_IF" if len(parts) == 5 else "")
            vals = [mapping[int(x[1:])] for x in parts[1:3]]
            if len(parts) == 5:
                vals.append(MASK[int(parts[4][1:])])
            out.append((OPCODES[name], vals))
    # Baseline's temporary parity bit is zero on exit. Inputs E are untouched.
    return out + after + [(0x40, [SCRATCH_B])]


def prove(operations):
    # 36 independent variables: LHS, RHS, classical measurement mask.
    # Measured scratch qubit and previously unused classical parity bit start zero.
    q = {x: frozenset([1 << i]) for i, x in enumerate(LHS + RHS)}
    q[SCRATCH_Q] = frozenset()
    b = {x: frozenset([1 << (24+i)]) for i, x in enumerate(MASK)}
    b[SCRATCH_B] = frozenset()
    original = dict(q)
    phase = frozenset()
    for op, v in operations:
        if op == 0x21:
            q[v[1]] ^= q[v[0]]
        elif op == 0xa1:
            q[v[1]] ^= amul(q[v[0]], b[v[2]])
        elif op == 0x22:
            q[v[0]], q[v[1]] = q[v[1]], q[v[0]]
        elif op in (0x20, 0xa0):
            term = amul(q[v[0]], q[v[1]])
            phase ^= amul(term, b[v[2]]) if op == 0xa0 else term
        elif op == 0x40:
            b[v[0]] = frozenset()
        elif op == 0xc2:
            b[v[0]] ^= b[v[1]]
        else:
            raise ValueError(f"unsupported proof opcode {op}")
    assert q == original, "quantum restoration/clean scratch failed"
    assert not b[SCRATCH_B], "classical scratch not zero"
    assert all(b[x] == frozenset([1 << (24+i)]) for i, x in enumerate(MASK))
    expected = frozenset((1 << i) | (1 << (12+j)) | (1 << (24+k))
                         for i in range(12) for j in range(12) for k in range(12)
                         if (mul(1 << i, 1 << j, POLY) >> k) & 1)
    assert phase == expected, "phase does not match parity(c & (U*V))"
    return {"ANF_exact": True, "independent_variables": 36,
            "phase_monomials": len(phase), "quantum_restoration": True,
            "classical_mask_preserved": True, "scratch_q_and_b_zero": True}


def kmx(operations):
    lines = []
    for op, v in operations:
        name = OPNAMES[op]
        nq = (op >> 4) & 3
        s = name.removesuffix("_IF") + " " + " ".join("q"+str(x) for x in v[:nq])
        if op & 64:
            s += (" " if nq else "") + "b"+str(v[nq])
        if op & 128:
            s += " if b"+str(v[-1])
        lines.append(s)
    return "\n".join(lines) + "\n"


def stream_copy(dst, src, start, stop):
    for offset in range(start, stop, 1 << 22):
        dst.write(src[offset:min(offset+(1 << 22), stop)])


def build(baseline, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if sha(baseline) != BASE_SHA:
        raise ValueError("v1.0 ZIP checksum mismatch")
    base = output / "baseline-dqi.kmb"
    import shutil
    with zipfile.ZipFile(baseline) as z, z.open("dqi.kmb") as src, base.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 22)
    if sha(base) != BASE_DQI_SHA:
        raise ValueError("pinned v1.0 DQI mismatch")
    k = KMB(base)
    # Confirm scratch lifetime and no surrounding classical control at this boundary.
    assert k.decode(51492, 51504) == [(0x50, [1821+i, 49140+i]) for i in range(12)]
    before = k.ops[:START]
    nb_before = int(np.count_nonzero(before & 64))
    assert SCRATCH_B not in k.array(8)[:nb_before]
    assert np.count_nonzero(before == 0x81) == np.count_nonzero(before == 0x01)
    assert k.ops[START-1] == k.ops[STOP] == 6
    old = k.decode(START, STOP)
    assert Counter(op for op, _ in old) == {0xa0: 144, 0xc2: 104, 0x40: 10}
    old_proof = prove(old)  # infers and confirms 0x1053 from actual baseline gates
    local_proof = verify_exact(compile_ops(POLY, 1), POLY, 1)
    new = replacement()
    new_proof = prove(new)
    (output / "original-phase.kmx").write_text(kmx(old))
    (output / "replacement-phase.kmx").write_text(kmx(new))
    new_types = np.array([op for op, _ in new], dtype="u1")
    edits = {1: (START, STOP, new_types.tobytes(), 1)}
    for kind in range(2, 10):
        a = int(np.count_nonzero(selected(k.ops[:START], kind)))
        b = a + int(np.count_nonzero(selected(k.ops[START:STOP], kind)))
        vals = [v[targets(op).index(kind)] for op, v in new if kind in targets(op)]
        edits[kind] = (a*4, b*4, np.asarray(vals, dtype="<u4").tobytes(), 4)
    head = bytearray(k.data[:104])
    delta = len(new)-len(old)
    struct.pack_into("<Q", head, 32, k.header[4]+delta)
    for ix, (kind, divisor) in enumerate([(2,4), (5,4), (7,4), (8,4), (9,4)], 1):
        a,b,payload,_ = edits[kind]
        struct.pack_into("<Q", head, 32+8*ix, k.header[4+ix]+(len(payload)-(b-a))//divisor)
    candidate = output / "dqi.kmb"
    with candidate.open("wb") as dst:
        dst.write(head)
        stream_copy(dst, k.data, 104, k.packets[1][0]-16)
        for kind in range(1, 12):
            p, size = k.packets[kind]
            a,b,payload,_ = edits.get(kind, (0,0,b"",1))
            dst.write(struct.pack("<QQ", kind, size+len(payload)-(b-a)))
            stream_copy(dst, k.data, p, p+a)
            dst.write(payload)
            stream_copy(dst, k.data, p+b, p+size)
    # Independently re-open the completed binary and compare every untouched byte.
    c = KMB(candidate)
    assert c.registers == k.registers and c.header[:4] == k.header[:4]
    preservation = {}
    for kind in range(1, 12):
        p,size = k.packets[kind]; cp,cs = c.packets[kind]
        a,b,payload,_ = edits.get(kind, (0,0,b"",1))
        assert cs == size+len(payload)-(b-a)
        for off in range(0, a, 1 << 22):
            n = min(1 << 22, a-off)
            assert k.data[p+off:p+off+n] == c.data[cp+off:cp+off+n]
        for off in range(0, size-b, 1 << 22):
            n = min(1 << 22, size-b-off)
            assert k.data[p+b+off:p+b+off+n] == c.data[cp+a+len(payload)+off:cp+a+len(payload)+off+n]
        assert c.data[cp+a:cp+a+len(payload)] == payload
        preservation[str(kind)] = {"prefix_bytes": a, "suffix_bytes": size-b, "unchanged_bytes_verified": True}
    assert c.decode(START, START+len(new)) == new
    prove(c.decode(START, START+len(new)))
    report = {"status": "PASS", "scope": "one complete DQI phase-block replacement",
              "baseline_zip_sha256": BASE_SHA, "baseline_dqi_sha256": BASE_DQI_SHA,
              "candidate_sha256": sha(candidate), "candidate_bytes": candidate.stat().st_size,
              "site": {"start_zero_based": START, "stop_exclusive": STOP,
                       "tag": "first @enter:gf_phase_by_product", "polynomial": hex(POLY),
                       "lhs_qubits": LHS, "rhs_qubits": RHS, "measurement_mask_bits": MASK,
                       "scratch_qubit": SCRATCH_Q, "classical_scratch_bit": SCRATCH_B,
                       "mask_source": "preceding 12 HMRs, NOT E registers",
                       "scratch_precondition": "q1821 reset by HMR; b49152 previously unused and initially zero",
                       "active_condition_depth": 0, "root": "constant 1; no quantum root in baseline",
                       "adapter": "V -> V^(2^11), WFS r=1 UV^2, inverse adapter"},
              "old_ops": len(old), "new_ops": len(new), "op_delta": delta,
              "old_op_counts": dict(Counter(OPNAMES[op] for op,_ in old)),
              "new_op_counts": dict(Counter(OPNAMES[op] for op,_ in new)),
              "qubit_delta": 0, "register_delta": 0,
              "baseline_local_proof": old_proof, "wfs_original_local_proof": local_proof,
              "integrated_local_proof": new_proof, "packet_preservation": preservation,
              "kickmix_full_parse": "NOT_RUN", "smoke": "NOT_RUN", "full_package": "NOT_RUN",
              "official_score_improvement": "UNCONFIRMED",
              "cost_note": "integration checkpoint; more two-qubit operations; no cost-reduction claim",
              "submits_to_kaggle": False}
    (output / "integration-report.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({key:report[key] for key in ["status","candidate_sha256","candidate_bytes","old_ops","new_ops","op_delta"]},indent=2))


def parse(output):
    import kickmix
    output = Path(output)
    report_path = output / "integration-report.json"
    report = json.loads(report_path.read_text())
    path = output / "dqi.kmb"
    assert sha(path) == report["candidate_sha256"]
    circuit = kickmix.Circuit.from_file(path, format="kmb")
    assert circuit.num_qubits == 1893 and circuit.num_bits == 49154
    report["kickmix_full_parse"] = "PASS"
    report["kickmix_qubits"] = circuit.num_qubits
    report["kickmix_bits"] = circuit.num_bits
    report["kickmix_toffoli_like"] = circuit.operation_statistics().num_toffoli_like
    report_path.write_text(json.dumps(report, indent=2)+"\n")
    print("Full candidate KMB Kickmix parse PASS")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline")
    p.add_argument("--output", default="build/integration")
    p.add_argument("--parse", action="store_true")
    a = p.parse_args()
    if a.parse:
        parse(a.output)
    elif not a.baseline:
        p.error("--baseline is required for generation")
    else:
        build(a.baseline, a.output)

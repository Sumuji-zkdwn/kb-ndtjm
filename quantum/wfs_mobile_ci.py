#!/usr/bin/env python3
"""WFS local quantum phase kernel. Does NOT create a full DQI submission.

GF(2^12), (U,V,r,c) -> (-1)^(r*parity(c & (scale*U*V**2))) (U,V,r,c).
U=q0..11, V=q12..23, root=q24, clean scratch=q25, mask=b0..11.
"""
import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

N = 12
MASK = (1 << N) - 1


def mul(a, b, poly):
    z = 0
    while b:
        if b & 1:
            z ^= a
        b >>= 1
        a <<= 1
        if a & (1 << N):
            a ^= poly
    return z & MASK


def scaling(scale, poly):
    if not 0 < scale < (1 << N):
        raise ValueError("scale must be a nonzero GF(2^12) element")
    rows = [sum(((mul(scale, 1 << c, poly) >> r) & 1) << c
                for c in range(N)) for r in range(N)]
    reduction = []
    for col in range(N):
        piv = next((r for r in range(col, N) if (rows[r] >> col) & 1), None)
        if piv is None:
            raise ValueError("noninvertible multiplier")
        if piv != col:
            rows[piv], rows[col] = rows[col], rows[piv]
            reduction.append(f"SWAP q{col} q{piv}")
        for r in range(N):
            if r != col and ((rows[r] >> col) & 1):
                rows[r] ^= rows[col]
                reduction.append(f"CX q{col} q{r}")
    assert rows == [1 << i for i in range(N)]
    return list(reversed(reduction)), reduction


def compile_ops(poly, scale):
    if poly >> N != 1 or poly & 1 != 1:
        raise ValueError("expected monic degree-12 polynomial with constant 1")
    forward, backward = scaling(scale, poly)
    ops = forward[:]
    phys = list(range(N))
    linear_ops = []
    feedback = [i for i in range(1, N) if poly & (1 << i)]

    def multiply_x():
        nonlocal phys
        phys = [phys[-1]] + phys[:-1]  # virtual reindexing, no SWAP emitted
        for i in feedback:
            gate = f"CX q{phys[0]} q{phys[i]}"
            ops.append(gate)
            linear_ops.append(gate)

    for d in range(N):
        for k in range(N):
            ops.append(f"CX q{phys[k]} q25 if b{k}")
        ops.append(f"CCZ q24 q25 q{12 + d}")
        for k in range(N - 1, -1, -1):
            ops.append(f"CX q{phys[k]} q25 if b{k}")
        if d < N - 1:
            multiply_x()
            multiply_x()
    ops.extend(reversed(linear_ops))
    ops.extend(backward)
    return ops


def xor(a, b):
    return a ^ b


def amul(a, b):
    out = set()
    for x in a:
        for y in b:
            term = x | y
            if term in out:
                out.remove(term)
            else:
                out.add(term)
    return frozenset(out)


def verify_exact(ops, poly, scale):
    # 37 vars: 0..11 U, 12..23 V, 24 root, 25..36 classical mask.
    # Polynomial = frozenset[monomial], monomial = bitset of variables.
    q = [frozenset((1 << i,)) for i in range(25)] + [frozenset()]
    phase = frozenset()
    counts = Counter()
    for instr in ops:
        parts = instr.split()
        gate = parts[0]
        cond = 1 << (25 + int(parts[4][1:])) if len(parts) == 5 else 0
        idx = [int(t[1:]) for t in parts[1:4 if gate == "CCZ" else 3]]
        counts[gate + ("_IF" if cond else "")] += 1
        if gate == "CX":
            a, b = idx
            assert a != b
            q[b] = xor(q[b], amul(q[a], frozenset((cond,))) if cond else q[a])
        elif gate == "SWAP":
            a, b = idx
            q[a], q[b] = q[b], q[a]
        elif gate == "CCZ":
            a, b, c = idx
            assert len({a, b, c}) == 3
            phase = xor(phase, amul(amul(q[a], q[b]), q[c]))
        else:
            raise AssertionError(instr)
    ideal_state = [frozenset((1 << i,)) for i in range(25)] + [frozenset()]
    assert q == ideal_state, "register or ancilla mismatch"
    ideal_phase = set()
    for i in range(N):
        for d in range(N):
            coeff = mul(scale, mul(1 << i, mul(1 << d, 1 << d, poly), poly), poly)
            for k in range(N):
                if (coeff >> k) & 1:
                    ideal_phase.add((1 << i) | (1 << (12 + d)) |
                                    (1 << 24) | (1 << (25 + k)))
    assert phase == frozenset(ideal_phase), "phase polynomial mismatch"
    assert counts["CCZ"] == 12 and counts["CX_IF"] == 288
    return {"phase_ANF_exact": True, "variables": 37,
            "phase_monomials": len(phase), "restored_and_clean": True,
            "op_counts": dict(counts), "total_ops": len(ops)}


def verify_samples(ops, poly, scale, samples=120):
    rng = random.Random(20261025 + poly + scale)
    for _ in range(samples):
        u, v, c = [rng.randrange(1 << N) for _ in range(3)]
        root = rng.randrange(2)
        q = [(u >> i) & 1 for i in range(N)]
        q += [(v >> i) & 1 for i in range(N)]
        q += [root, 0]
        phase = 0
        for instr in ops:
            parts = instr.split()
            if len(parts) == 5 and not ((c >> int(parts[4][1:])) & 1):
                continue
            gate = parts[0]
            idx = [int(t[1:]) for t in parts[1:4 if gate == "CCZ" else 3]]
            if gate == "CX":
                q[idx[1]] ^= q[idx[0]]
            elif gate == "SWAP":
                q[idx[0]], q[idx[1]] = q[idx[1]], q[idx[0]]
            elif gate == "CCZ":
                phase ^= q[idx[0]] & q[idx[1]] & q[idx[2]]
        want = root & ((c & mul(scale, mul(u, mul(v, v, poly), poly), poly)).bit_count() & 1)
        orig = [(u >> i) & 1 for i in range(N)]
        orig += [(v >> i) & 1 for i in range(N)]
        orig += [root, 0]
        assert phase == want and q == orig, "sample mismatch"
    return samples


def produce(output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    report = {"scope": "local phase kernel only, NOT full Kaggle DQI",
              "official_DQI_verifier": "NOT_RUN", "variants": {}}
    for name, poly, scale in [("google", 0x1053, 1),
                              ("public", 0x10eb, 1),
                              ("scaled52", 0x1053, 0x52)]:
        ops = compile_ops(poly, scale)
        tests = verify_exact(ops, poly, scale)
        tests["random_checks"] = verify_samples(ops, poly, scale)
        txt = "# Local WFS phase kernel. Not a full DQI circuit.\n"
        txt += "\n".join(ops) + "\n"
        fname = out / f"wfs_{name}.kmx"
        fname.write_text(txt, encoding="utf-8")
        tests.update({"polynomial": hex(poly), "scale": hex(scale),
                      "sha256": hashlib.sha256(fname.read_bytes()).hexdigest(),
                      "kickmix_parser": "NOT_RUN"})
        report["variants"][name] = tests
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def parse_official(output):
    import kickmix as km
    out = Path(output)
    path = out / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    for name, row in report["variants"].items():
        c = km.Circuit.from_file(out / f"wfs_{name}.kmx", format="kmx")
        row["kickmix_parser"] = "PASS"
        row["kickmix_qubits"] = c.num_qubits
        row["kickmix_bits"] = c.num_bits
        row["kickmix_toffoli_like"] = c.operation_statistics().num_toffoli_like
        assert c.num_qubits == 26 and c.num_bits == 12
        assert row["kickmix_toffoli_like"] == 12
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Kickmix parser PASS for all local kernels")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="build/wfs")
    parser.add_argument("--parse", action="store_true")
    args = parser.parse_args()
    parse_official(args.output) if args.parse else produce(args.output)

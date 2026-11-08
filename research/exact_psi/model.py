#!/usr/bin/env python3
"""Bit-exact classical model of an exact, fixed-schedule Psi computation.

Goal: replace the per-point Forney division (79 Toffoli-like per point in PR8)
by a once-per-shot reciprocal-derivative polynomial Psi, as in the public
andigu/uncompute decoder, but WITHOUT its measured windows and its
single-repair zero-pivot schedule.  Every step below is data independent:
a fixed number of monic divsteps (Bernstein-Yang style) on the reversed
half-locators, so abnormal remainder sequences need no special casing.

This file is a classical model only.  It is NOT a quantum circuit and it is
NOT checked by the official verifier.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


class GF:
    """GF(2^k) with a primitive modulus; gen = 2."""

    def __init__(self, k: int, poly: int):
        self.k, self.poly, self.q = k, poly, 1 << k
        self.M = self.q - 1
        self.exp = [0] * (2 * self.M)
        self.log = [0] * self.q
        x = 1
        for i in range(self.M):
            self.exp[i] = self.exp[i + self.M] = x
            self.log[x] = i
            x <<= 1
            if x & self.q:
                x ^= poly
        assert len(set(self.exp[: self.M])) == self.M, "modulus not primitive"

    def mul(self, a: int, b: int) -> int:
        if a == 0 or b == 0:
            return 0
        return self.exp[self.log[a] + self.log[b]]

    def inv(self, a: int) -> int:
        assert a
        return self.exp[(self.M - self.log[a]) % self.M]

    def pow(self, a: int, e: int) -> int:
        if a == 0:
            return 0 if e else 1
        return self.exp[(self.log[a] * e) % self.M]

    def sqrt(self, a: int) -> int:
        return self.pow(a, self.q // 2)

    def gpow(self, e: int) -> int:
        return self.exp[e % self.M]


# ---- polynomial helpers (lists, index = degree) ----------------------------
def trim(p):
    p = list(p)
    while p and p[-1] == 0:
        p.pop()
    return p


def padd(a, b):
    n = max(len(a), len(b))
    return [(a[i] if i < len(a) else 0) ^ (b[i] if i < len(b) else 0) for i in range(n)]


def pmul(F, a, b):
    if not a or not b:
        return []
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x:
            for j, y in enumerate(b):
                if y:
                    out[i + j] ^= F.mul(x, y)
    return out


def pscale(F, c, a):
    return [F.mul(c, x) for x in a]


def peval(F, p, x):
    acc = 0
    for c in reversed(p):
        acc = F.mul(acc, x) ^ c
    return acc


def pmod(F, a, m):
    a, m = trim(a), trim(m)
    il = F.inv(m[-1])
    while len(a) >= len(m):
        c = F.mul(a[-1], il)
        s = len(a) - len(m)
        for i, y in enumerate(m):
            a[s + i] ^= F.mul(c, y)
        a = trim(a)
    return a


def deriv(p):
    return [p[i] if i % 2 == 1 else 0 for i in range(1, len(p))]


# ---- locators ---------------------------------------------------------------
def locator(F, positions):
    """sigma(z) = prod (1 - gamma^i z); roots beta_i = gamma^-i."""
    s = [1]
    for i in positions:
        s = pmul(F, s, [1, F.gpow(i)])
    return s


def halves(F, sigma):
    """sigma = E^2 + z O^2 with E_i = sqrt(sigma_2i), O_i = sqrt(sigma_2i+1)."""
    E = [F.sqrt(sigma[i]) for i in range(0, len(sigma), 2)]
    O = [F.sqrt(sigma[i]) for i in range(1, len(sigma), 2)]
    return E, O


# ---- the exact fixed-schedule divstep Psi -----------------------------------
@dataclass
class Trace:
    swaps: list
    deltas: list
    f_len: list  # live length of f after each step (reversed domain)
    g_len: list
    cof_span: list  # (min_deg, max_deg) union of the four transition entries


def exact_psi(F, sigma, W, steps=None, trace=None):
    """Return (A, B, c, s, pre) with A*E + B*O = c * z^s exactly.

    W is the maximum locator degree (35).  d = W // 2 is the fixed top degree
    after the shift m = (W - L) // 2.  The divstep count is data independent.
    """
    L = len(trim(sigma)) - 1
    d = W // 2
    E, O = halves(F, sigma)
    m = (W - L) // 2
    Ep = [0] * m + E
    Op = [0] * m + O
    Ep += [0] * (d + 1 - len(Ep))
    Op += [0] * (d + 1 - len(Op))
    assert len(Ep) == len(Op) == d + 1, (L, m, len(E), len(O))
    pre = Ep[d] == 0  # odd L with sigma_{L-1} = 0
    if pre:
        Ep, Op = Op, Ep
    assert Ep[d] != 0, "pivot must have degree exactly d"
    # reversed domain: Fr(x) = x^d E'(1/x)
    f = Ep[::-1]
    g = Op[::-1]
    u, v, q, r = [1], [], [], [1]
    # delta = 0: the first step is the plain top elimination of O' by E'
    # (both may have degree d); afterwards the state is a Bernstein-Yang
    # state with delta = 1, deg f <= d, deg g <= d - 1.  The total schedule
    # is 2d + 1 steps: exhaustive checks (exhaust.py) show this count is both
    # necessary and sufficient for every input in GF(16), W=5,7 and GF(32), W=7.
    delta = 0
    N = steps if steps is not None else 2 * d + 1
    for n in range(N):
        sw = delta > 0 and g[0] != 0
        if sw:
            f, g = g, f
            u, v, q, r = q, r, u, v
            delta = -delta
        w = F.mul(g[0], F.inv(f[0]))
        g = padd(g, pscale(F, w, f))
        q = padd(q, pscale(F, w, u))
        r = padd(r, pscale(F, w, v))
        assert g[0] == 0
        g = g[1:]
        u = [0] + u
        v = [0] + v
        delta += 1
        if trace is not None:
            trace.swaps.append(sw)
            trace.deltas.append(delta)
            trace.f_len.append(len(trim(f)))
            trace.g_len.append(len(trim(g)))
            nz = [i for p in (u, v, q, r) for i, x in enumerate(p) if x]
            trace.cof_span.append((min(nz), max(nz)) if nz else (0, -1))
    assert not trim(g), "g did not vanish: schedule too short"
    f = trim(f)
    assert len(f) == 1, "gcd of reversed halves is not a unit"
    c = f[0]
    # x^N c = u Fr + v Gr  ==>  c z^(d) = A E' + B O' with A_k = u_(N-k)
    A = [u[N - k] if 0 <= N - k < len(u) else 0 for k in range(N + 1)]
    B = [v[N - k] if 0 <= N - k < len(v) else 0 for k in range(N + 1)]
    if pre:
        A, B = B, A
    # A E' + B O' = c z^d  ==>  A E + B O = c z^(d - m)
    return trim(A), trim(B), c, d - m, pre, m


def check(F, positions, W, steps=None, trace=None):
    sigma = locator(F, positions)
    E, O = halves(F, sigma)
    A, B, c, s, pre, m = exact_psi(F, sigma, W, steps, trace)
    lhs = trim(padd(pmul(F, A, E), pmul(F, B, O)))
    want = [0] * s + [c]
    assert lhs == want, "Bezout identity failed"
    # Psi* = B^2 + z A^2 ;  Psi* sigma' == c^2 z^(2s)  (mod sigma)
    sq = lambda p: [x for y in p for x in (F.mul(y, y), 0)]
    psi = padd(sq(B), [0] + sq(A))
    sp = deriv(sigma)
    for i in positions:
        beta = F.gpow(-i)
        lhs_v = F.mul(peval(F, psi, beta), peval(F, sp, beta))
        assert lhs_v == F.mul(F.mul(c, c), F.pow(beta, 2 * s)), "Psi at a root"
    return A, B, c, s, pre, m


def random_positions(F, weight, rng):
    return rng.sample(range(F.M), weight)


if __name__ == "__main__":
    F = GF(12, 0x1053)
    rng = random.Random(20261108)
    for w in list(range(1, 36)) * 30:
        check(F, random_positions(F, w, rng), 35)
    print("random GF(4096), weights 1..35 x30: PASS")

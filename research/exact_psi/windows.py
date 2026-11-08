"""Worst-case per-step windows of the fixed divstep schedule (N = 2d+1)."""
import itertools, random
import model as M

def collect(F, inputs, W):
    d = W // 2; N = 2 * d + 1
    fl = [0] * N; gl = [0] * N; lo = [10**9] * N; hi = [-1] * N
    for pos in inputs:
        t = M.Trace([], [], [], [], [])
        M.check(F, list(pos), W, steps=N, trace=t)
        for n in range(N):
            fl[n] = max(fl[n], t.f_len[n]); gl[n] = max(gl[n], t.g_len[n])
            a, b = t.cof_span[n]
            if b >= 0: lo[n] = min(lo[n], a); hi[n] = max(hi[n], b)
    return fl, gl, lo, hi

def show(tag, d, res):
    fl, gl, lo, hi = res
    print(tag)
    for n in range(2 * d + 1):
        print(f"  step {n+1:2d}: max len f={fl[n]:2d} g={gl[n]:2d}  cofactor x-degrees in [{lo[n]},{hi[n]}]")

if __name__ == "__main__":
    F = M.GF(4, 0x13)
    W = 7
    show("GF(16) W=7 exhaustive", 3, collect(F, (c for w in range(1, 8) for c in itertools.combinations(range(15), w)), W))
    F = M.GF(12, 0x1053); rng = random.Random(7)
    W = 35
    show("GF(4096) W=35 random 7000 (weights 1..35)", 17, collect(F, (rng.sample(range(4095), w) for w in list(range(1, 36)) * 200), W))

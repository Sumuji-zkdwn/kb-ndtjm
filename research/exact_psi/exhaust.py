"""Exhaustive / heavy checks of the fixed divstep schedule in small fields."""
import itertools, random, sys
import model as M

def need_steps(F, pos, W, lo, hi):
    for N in range(lo, hi + 1):
        try:
            M.check(F, pos, W, steps=N); return N
        except AssertionError:
            pass
    raise SystemExit(f"no schedule up to {hi} for {pos}")

def run(k, poly, W, exhaustive=True, samples=0, seed=1):
    F = M.GF(k, poly); d = W // 2; worst = 0; count = 0
    if exhaustive:
        it = (c for w in range(1, W + 1) for c in itertools.combinations(range(F.M), w))
    else:
        rng = random.Random(seed)
        it = (rng.sample(range(F.M), rng.randint(1, W)) for _ in range(samples))
    for pos in it:
        worst = max(worst, need_steps(F, list(pos), W, 1, 2 * d + 4)); count += 1
    print(f"GF(2^{k}) W={W} d={d} inputs={count} exhaustive={exhaustive}: max steps needed={worst} (2d+1={2*d+1})")
    return worst

if __name__ == "__main__":
    run(4, 0x13, 7); run(4, 0x13, 5)
    run(5, 0x25, 7); run(5, 0x25, 9, exhaustive=False, samples=200000)
    run(6, 0x43, 11, exhaustive=False, samples=100000)

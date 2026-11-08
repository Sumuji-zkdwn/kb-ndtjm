"""Cost model for replacing the PR8 per-point Forney division by a Psi sweep.

Objective (Khattar et al., arXiv:2610.23832, Eq. 45):
    S = R(eps+) * Q^2 * T,  R(eps) = ln2 / -ln(1/2 + 2 sqrt(eps)),
eps+ = one-sided Clopper-Pearson upper bound at delta = 2^-128, N = 102400.
"""
import math

N, LOG_DELTA = 102400, -128 * math.log(2)

def log_binom_cdf(k, n, p):
    terms = [math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1)
             + j * math.log(p) + (n - j) * math.log1p(-p) for j in range(k + 1)]
    m = max(terms); return m + math.log(sum(math.exp(t - m) for t in terms))

def eps_plus(k, n=N):
    lo, hi = k / n, 0.5
    for _ in range(200):
        mid = (lo + hi) / 2
        if log_binom_cdf(k, n, mid) > LOG_DELTA: lo = mid
        else: hi = mid
    return hi

def R(eps):
    a = 0.5 + 2 * math.sqrt(eps)
    return math.inf if a >= 1 else math.log(2) / -math.log(a)

def expected_R(p, n=N, kmax=60):
    """E[R(eps+(K))] with K ~ Binomial(n, p)."""
    tot = 0.0
    for k in range(kmax):
        pk = math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                      + (k * math.log(p) if p else (0 if k == 0 else -math.inf)) + (n - k) * math.log1p(-p))
        tot += pk * R(eps_plus(k))
    return tot

Q, T_PR8, POINTS = 2482, 715786, 4095
FORNEY_PR8 = 79 * POINTS
SWEEP_PSI = 23 * POINTS                      # root test 11 + gated pairing 12
EUCLID_UPSTREAM = 2 * 44470                  # andigu/uncompute euclid + euclid_inv (README)

def report():
    base = R(eps_plus(0)) * Q * Q * T_PR8
    print(f"eps+(0)={eps_plus(0):.4e}  R={R(eps_plus(0)):.4f}  PR8 S={base:.6e}")
    for k in (0, 1, 2, 5, 14, 50):
        print(f"  k={k:3d} failures: eps+={eps_plus(k):.4e} R={R(eps_plus(k)):.4f} (+{R(eps_plus(k))/R(eps_plus(0))-1:.2%})")
    T_psi = T_PR8 - FORNEY_PR8 + SWEEP_PSI + EUCLID_UPSTREAM
    print(f"\nPsi route, upstream-sized Euclid: T={T_psi} ({T_psi/T_PR8-1:+.2%})")
    for p in (0.0, 1e-6, 1e-5, 4.5e-6 + 1e-5, 1.4e-4):
        r = expected_R(p) if p else R(eps_plus(0))
        S = r * Q * Q * T_psi
        print(f"  true failure rate {p:.1e}: E[R]={r:.4f}  S ratio vs PR8 = {S/base:.4f}")
    for factor in (1.5, 2.0, 2.5):
        T_ex = T_PR8 - FORNEY_PR8 + SWEEP_PSI + int(EUCLID_UPSTREAM * factor)
        print(f"Exact Psi with Euclid x{factor} of upstream: T={T_ex} ({T_ex/T_PR8-1:+.2%}), S ratio {T_ex/T_PR8:.4f}")
    be = (FORNEY_PR8 - SWEEP_PSI) / EUCLID_UPSTREAM
    print(f"break-even Euclid size (both directions): {FORNEY_PR8 - SWEEP_PSI} Toffoli = {be:.2f}x upstream")

if __name__ == "__main__":
    report()

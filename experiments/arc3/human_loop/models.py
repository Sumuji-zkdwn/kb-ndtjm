"""Inspectable predictive distributions. Fitting sees training groups only.

Waiting times are compared on a common, prespecified log-bin partition.
Censoring is conservatively coarsened to survival to the bin's lower edge.
Unfinished human attempts are never turned into completed slow solutions.
"""
from __future__ import annotations
import math
import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr, expit

CARDINALITY = {'arc': 8, 'lab': 9, 'janssen': 5}
FAMILIES = ('empirical', 'lognormal', 'loglogistic', 'weibull', 'quartic')
CONTEXTS = ('none', 'previous', 'stage', 'history')


def edges(domain):
    return (1. if domain == 'arc' else .125) * 2.**np.arange(18)


def bins(times, domain):
    return np.searchsorted(edges(domain), times, side='right')


def normalized(p):
    p = np.maximum(np.asarray(p, float), 1e-12)
    return p / p.sum(axis=-1, keepdims=True)


def action_keys(rows, context, conditions):
    key = np.zeros(len(rows), dtype=int)
    if context != 'none': key += rows[:, 0]
    if context in ('stage', 'history'): key += 10*rows[:, 1]
    if context == 'history': key += 40*rows[:, 2]
    if conditions: key += 160*rows[:, 3]
    return key


def fit_action(rows, domain, spec):
    k = CARDINALITY[domain]
    keys = action_keys(rows, spec['context'], spec['conditions'])
    size = 160*(int(rows[:, 3].max())+1) if spec['conditions'] else 160
    counts = np.bincount(keys*k+rows[:, 4], minlength=size*k).reshape(size, k)
    base = normalized(counts.sum(axis=0)+.5)
    table = normalized(counts + spec['strength']*base)
    return {'table': table.tolist(), 'base': base.tolist(), 'domain': domain, 'spec': spec}


def predict_action(model, rows):
    spec = model['spec']
    keys = action_keys(rows, spec['context'], spec['conditions'])
    table, base = np.asarray(model['table']), np.asarray(model['base'])
    p = np.tile(base, (len(rows), 1))
    known = keys < len(table)
    p[known] = table[keys[known]]
    # Linear input tilts the log weights. This is an explicit statistical hypothesis.
    repeat = np.arange(p.shape[1])[None, :] == rows[:, 0, None]
    logits = spec['temperature'] * np.log(p) + spec['tilt']*repeat
    logits -= logits.max(axis=1, keepdims=True)
    return normalized(np.exp(logits))


def time_keys(rows, spec):
    key = np.zeros(len(rows), dtype=int)
    if spec['time_context'] == 'stage': key += rows[:, 2].astype(int)
    if spec['conditions']: key += 4*rows[:, 3].astype(int)
    return key


def histogram(rows, domain):
    b = bins(rows[:, 0], domain)
    n = len(edges(domain))+1
    return np.bincount(b[rows[:, 1] == 1], minlength=n).astype(float), np.bincount(b[rows[:, 1] == 0], minlength=n).astype(float)


def censor_nll(p, event, censor):
    tail = np.cumsum(p[::-1])[::-1]
    return -float(event @ np.log(np.maximum(p, 1e-12)) + censor @ np.log(np.maximum(tail, 1e-12)))


def empirical(event, censor, prior):
    p = normalized(event + prior)
    for _ in range(100):
        tail = np.cumsum(p[::-1])[::-1]
        new = normalized(event + prior + p*np.cumsum(censor/np.maximum(tail, 1e-12)))
        if np.max(np.abs(new-p)) < 1e-9:
            break
        p = new
    return new


def parametric(params, family, domain, spec):
    mu, log_scale = params
    scale = np.exp(log_scale)
    z = (np.log(edges(domain))-mu)/scale
    if family == 'lognormal': cdf = ndtr(z)
    elif family == 'loglogistic': cdf = expit(z)
    elif family == 'weibull': cdf = -np.expm1(-np.exp(np.clip(z, -50, 7)))
    elif family == 'quartic':
        # A normalized finite quadrature of exp(-beta E), E=z^4/4+r*z^2/2-u*z.
        grid = np.linspace(-7., 7., 1401)
        energy = grid**4/4 + spec['curvature']*grid**2/2 - spec['energy_input']*grid
        log_w = -spec['beta']*energy
        w = np.exp(log_w - log_w.max())
        integral = np.r_[0., np.cumsum((w[:-1]+w[1:])/2)]
        cdf = np.interp(z, grid, integral/integral[-1], left=0., right=1.)
    else: raise ValueError(family)
    return normalized(np.diff(np.r_[0., cdf, 1.]))


def fit_time(rows, domain, spec):
    event, censor = histogram(rows, domain)
    n = len(event)
    global_prior = empirical(event, censor, np.ones(n)*.5)
    keys = time_keys(rows, spec)
    tables, fits = {}, {}
    # Global fallback and conditional tables are fitted separately; prior shrinkage
    # uses training data only and includes a proper right-tail mass.
    for key in [-1, *sorted(set(keys.tolist()))]:
        subset = rows if key == -1 else rows[keys == key]
        ev, ce = histogram(subset, domain)
        if spec['family'] == 'empirical':
            p = empirical(ev, ce, spec['strength']*global_prior)
            fits[str(key)] = {'method': 'censored_EM'}
        else:
            log_times = np.log(subset[:, 0])
            initial = [float(np.median(log_times)), float(np.log(max(float(np.std(log_times)), .3)))]
            def loss(params):
                return censor_nll(parametric(params, spec['family'], domain, spec), ev+spec['strength']*global_prior, ce)
            opt = minimize(loss, initial, method='Nelder-Mead', bounds=[(-12, 18), (-3, 3)],
                           options={'maxiter': 220, 'xatol': 1e-4, 'fatol': 1e-4})
            if not np.isfinite(opt.fun): raise ValueError('Invalid distribution fit')
            p = parametric(opt.x, spec['family'], domain, spec)
            fits[str(key)] = {'parameters': opt.x.tolist(), 'converged': bool(opt.success)}
        tables[str(key)] = p.tolist()
    return {'tables': tables, 'fits': fits, 'domain': domain, 'spec': spec,
            'edges': edges(domain).tolist(), 'censoring': 'survival to lower edge of observed bin'}


def predict_time(model, rows):
    keys = time_keys(rows, model['spec'])
    base = np.asarray(model['tables']['-1'])
    p = np.tile(base, (len(rows), 1))
    for key in np.unique(keys):
        p[keys == key] = model['tables'].get(str(key), base)
    return p


def group_metrics(loss, brier, groups, conditions):
    means = [float(loss[groups == group].mean()) for group in np.unique(groups)]
    return {'n': len(loss), 'groups': len(means), 'group_macro_nll': float(np.mean(means)),
            'group_nll_se': float(np.std(means, ddof=1)/math.sqrt(len(means))) if len(means)>1 else None,
            'observation_micro_nll': float(loss.mean()), 'worst_group_nll': max(means),
            'brier': float(brier.mean()) if brier is not None else None,
            'condition_nll': {str(int(c)): float(loss[conditions == c].mean()) for c in np.unique(conditions)}}


def evaluate(action_model, time_model, a, d):
    p = predict_action(action_model, a)
    q = predict_time(time_model, d)
    return evaluate_probabilities(p, q, a, d, time_model['domain'])


def evaluate_probabilities(p, q, a, d, domain):
    truth = a[:, 4]
    observed = p[np.arange(len(a)), truth]
    loss = -np.log(observed)
    brier = (p*p).sum(axis=1)-2*observed+1
    action = group_metrics(loss, brier, a[:, 5], a[:, 3])
    action['accuracy'] = float((p.argmax(axis=1) == truth).mean())
    # Calibration of top-choice probability; forecasts are made without labels.
    confidence = p.max(axis=1); correct = p.argmax(axis=1) == truth
    action['confidence_bins'] = [
        {'lower': i/10, 'n': int(mask.sum()), 'confidence': float(confidence[mask].mean()),
         'accuracy': float(correct[mask].mean())}
        for i in range(10) if (mask := (confidence>=i/10)&(confidence<(i+1)/10)).any()]
    b = bins(d[:, 0], domain)
    tail = np.cumsum(q[:, ::-1], axis=1)[:, ::-1]
    likelihood = np.where(d[:, 1] == 1, q[np.arange(len(d)), b], tail[np.arange(len(d)), b])
    duration = group_metrics(-np.log(np.maximum(likelihood, 1e-12)), None, d[:, 4], d[:, 3])
    duration['events'] = int(d[:, 1].sum()); duration['censored'] = int((d[:, 1] == 0).sum())
    # A small fixed diagnostic signature supports predictive diversity retention.
    signature = np.r_[p[:64].ravel(), q[:64].ravel()].tolist()
    return {'action': action, 'duration': duration}, signature


def conditional_progress(time_model, elapsed, additional, stage=0, condition=0):
    """Return a binned human-reference forecast, not an agent success probability."""
    if elapsed < 0 or additional < 0: raise ValueError('Negative budget')
    row = np.array([[max(elapsed, .001), 0, stage, condition, 0]])
    p = predict_time(time_model, row)[0]
    e = np.asarray(time_model['edges'])
    # Interpolate CDF linearly in log time inside bins, with explicit tail limits.
    def cdf(t):
        if t <= 0: return 0.
        b = int(np.searchsorted(e, t, side='right'))
        lo = 0 if b == 0 else e[b-1]
        hi = e[b] if b < len(e) else math.inf
        fraction = t/hi if lo == 0 else (0 if math.isinf(hi) else math.log(t/lo)/math.log(hi/lo))
        return float(p[:b].sum()+p[b]*fraction)
    s0 = 1-cdf(elapsed); s1 = 1-cdf(elapsed+additional)
    return {'probability_progress_within_budget': float(np.clip(1-s1/max(s0, 1e-12), 0, 1)),
            'survival_at_elapsed': s0, 'elapsed': elapsed, 'additional': additional,
            'scope': 'human next-level reference under fitted distribution; within-bin log interpolation; last tail unresolved'}

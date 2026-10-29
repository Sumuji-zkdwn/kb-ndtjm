"""Restartable exploration of human forecasts; official ARC submission stays manual.

run: propose / fit on training groups / predict validation groups / archive / diversify.
seal: freeze a portfolio, evaluate the untouched test groups once, stop further tuning.
No network calls, external model API, game execution, or submission in either command.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np
import scipy
import data
import models

HERE = Path(__file__).resolve().parent


def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@contextmanager
def lock(root):
    root.mkdir(parents=True, exist_ok=True)
    f = (root/'run.lock').open('a+b')
    if f.tell() == 0: f.write(b'0'); f.flush()
    f.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close(); raise RuntimeError('Human experiment is already running')
    try: yield
    finally: f.close()  # releasing the OS handle releases the lock after crashes too


def split_groups(groups, seed):
    groups = np.unique(groups).astype(int)
    if len(groups) < 5: raise ValueError('Need at least five independent groups')
    np.random.default_rng(seed).shuffle(groups)
    n = len(groups); a = int(n*.6); b = a+max(1, int(n*.2))
    return {'train': sorted(groups[:a].tolist()), 'validation': sorted(groups[a:b].tolist()), 'test': sorted(groups[b:].tolist())}


def load_data(folder):
    manifest = read(folder/'manifest.json')
    if manifest['schema'] != data.SCHEMA or data.digest(folder/'observations.npz') != manifest['observations_sha256']:
        raise ValueError('Human observation identity changed')
    with np.load(folder/'observations.npz', allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    return manifest, arrays


def protocol(folder, manifest, arrays, seed):
    return {'schema': 2, 'dataset_manifest_sha256': data.digest(folder/'manifest.json'),
            'observations_sha256': manifest['observations_sha256'], 'seed': seed,
            'code': {p.name: data.digest(p) for p in sorted(HERE.glob('*.py')) if not p.name.startswith('test_')},
            'numpy': np.__version__, 'scipy': scipy.__version__, 'official_submission': 'manual_only',
            'splits': {d: split_groups(arrays[d+'_actions'][:, 5], seed+i) for i, d in enumerate(data.DOMAINS)},
            'evaluation': 'group-disjoint train/validation/test. Validation adaptively reused; test sealed once.',
            'censoring_assumption': 'Statistical survival model; informative human quitting is not identified.',
            'scope': 'human predictive modeling. No proof of latent noticing or cross-domain transfer.'}


def select_rows(arrays, splits, domain, part):
    a, d = arrays[domain+'_actions'], arrays[domain+'_durations']
    selected = splits[domain][part]
    return a[np.isin(a[:, 5], selected)], d[np.isin(d[:, 4], selected)]


def initial_spec(i):
    return {'family': models.FAMILIES[i % 5], 'context': models.CONTEXTS[(i // 5) % 4],
            'conditions': bool(i % 2), 'time_context': 'global' if i < 5 else 'stage',
            'strength': 16., 'temperature': 1., 'tilt': 0., 'curvature': -2.,
            'energy_input': 0., 'beta': 1.}


def effective_identity(spec):
    used = dict(spec)
    if used['family'] != 'quartic':
        for k in ('curvature', 'energy_input', 'beta'): used.pop(k)
    return identity(used)


def objective_vector(record):
    return np.array([record['validation'][d][target]['group_macro_nll']
                     for d in data.DOMAINS for target in ('action', 'duration')])


def portfolio(records):
    good = [r for r in records if r['status'] == 'complete']
    if not good: return {'pareto': [], 'specialists': [], 'diverse': [], 'retained': []}
    v = np.array([objective_vector(r) for r in good])
    front = [r['id'] for i, r in enumerate(good) if not any(np.all(w<=v[i]) and np.any(w<v[i]) for w in v)]
    specialists = set()
    for d in data.DOMAINS:
        for target in ('action', 'duration'):
            conditions = good[0]['validation'][d][target]['condition_nll']
            for condition in conditions:
                specialists.add(min(good, key=lambda r:r['validation'][d][target]['condition_nll'][condition])['id'])
    # Preserve a distribution with different forecasts even when every mean loss is worse.
    chosen = [good[0]]
    while len(chosen) < min(3, len(good)):
        rest = [r for r in good if r['id'] not in {x['id'] for x in chosen}]
        winner = max(rest, key=lambda r:min(float(np.mean(np.abs(np.array(r['signature'])-np.array(c['signature'])))) for c in chosen))
        chosen.append(winner)
    diverse = [r['id'] for r in chosen]
    return {'pareto': front, 'specialists': sorted(specialists), 'diverse': diverse,
            'retained': sorted(set(front)|specialists|set(diverse)),
            'policy': 'All evaluated candidates remain archived; retention guides proposals, not deletion. No patience cutoff.'}


def propose(records, seed):
    existing = {effective_identity(r['spec']) for r in records}
    i = len(records)
    if i < 10: return initial_spec(i), 'initial coverage of five families and two history depths'
    rng = np.random.default_rng(seed+i*7919)
    retained = set(portfolio(records)['retained'])
    parents = [r for r in records if r['id'] in retained]
    choices = {'family': models.FAMILIES, 'context': models.CONTEXTS, 'conditions': [False, True],
               'time_context': ['global', 'stage'], 'strength': [1., 4., 16., 64., 256.],
               'temperature': [.5, .8, 1., 1.3, 2.], 'tilt': [-1.5, -.5, 0., .5, 1.5],
               'curvature': [-4., -2., 0., 2., 4.], 'energy_input': [-2., -1., 0., 1., 2.], 'beta': [.5, 1., 2.]}
    for attempt in range(1000):
        # Every third proposal is a broad independent draw, regardless of scores.
        exploratory = i % 3 == 0 or not parents
        if exploratory:
            spec = {k: v[int(rng.integers(len(v)))] for k,v in choices.items()}
        else:
            spec = dict(parents[int(rng.integers(len(parents)))]['spec'])
            for k in rng.choice(list(choices), size=2, replace=False):
                v = choices[k]; spec[str(k)] = v[int(rng.integers(len(v)))]
        if effective_identity(spec) not in existing:
            return spec, 'independent distribution/variable-role exploration' if exploratory else 'mutation of Pareto, condition specialist, or diverse forecast'
    raise RuntimeError('Proposal budget exhausted')


def inspect_records(root, state):
    records = []
    for entry in state['records']:
        file = root/entry['file']
        if data.digest(file) != entry['sha256']: raise ValueError('Candidate evidence changed')
        r = read(file)
        if r['status'] == 'complete' and data.digest(root/r['model_file']) != r['model_sha256']:
            raise ValueError('Fitted model changed')
        records.append(r)
    return records


def fit_candidate(spec, arrays, splits):
    fitted, scores, signature = {}, {}, []
    for domain in data.DOMAINS:
        a, d = select_rows(arrays, splits, domain, 'train')
        am, tm = models.fit_action(a, domain, spec), models.fit_time(d, domain, spec)
        va, vd = select_rows(arrays, splits, domain, 'validation')
        scores[domain], sig = models.evaluate(am, tm, va, vd)
        fitted[domain] = {'action': am, 'duration': tm}
        signature.extend(sig)
    return fitted, scores, signature


def run(dataset, output, seed=20261029, candidates=1, seconds=3600, stop_after=None):
    if not 1 <= candidates <= 128 or not 1 <= seconds <= 10800:
        raise ValueError('Use finite per-invocation budgets')
    dataset, root = Path(dataset), Path(output)
    manifest, arrays = load_data(dataset)
    proposed_protocol = protocol(dataset, manifest, arrays, seed)
    with lock(root):
        if (root/'protocol.json').exists():
            if read(root/'protocol.json') != proposed_protocol:
                raise ValueError('Protocol changed; start a new versioned experiment')
            state = read(root/'state.json')
        else:
            data.save_json(root/'protocol.json', proposed_protocol)
            state = {'protocol_id': identity(proposed_protocol), 'records': [], 'status': 'ready'}
        records = inspect_records(root, state)
        if (root/'seal-intent.json').exists():
            raise ValueError('Holdout sealed: further adaptive fitting is disabled in this experiment')
        started = time.monotonic()
        reason = 'candidate_budget'
        for _ in range(candidates):
            if (root/'STOP').exists(): reason='STOP'; break
            if time.monotonic()-started >= seconds: reason='wall_budget'; break
            spec, rationale = propose(records, seed)
            cid = f'h{len(records):05d}'
            croot = root/'candidates'/cid
            croot.mkdir(parents=True, exist_ok=True)
            intent = {'id': cid, 'spec': spec, 'rationale': rationale, 'protocol_id': state['protocol_id']}
            if (croot/'intent.json').exists() and read(croot/'intent.json') != intent:
                raise ValueError('Interrupted candidate intent changed')
            data.save_json(croot/'intent.json', intent)
            t = time.monotonic()
            try:
                fitted, validation, signature = fit_candidate(spec, arrays, proposed_protocol['splits'])
                data.save_json(croot/'models.json', fitted)
                result = {**intent, 'status': 'complete', 'validation': validation, 'signature': signature,
                          'model_file': (croot/'models.json').relative_to(root).as_posix(),
                          'model_sha256': data.digest(croot/'models.json')}
            except Exception as exc:
                result = {**intent, 'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
            result['seconds'] = time.monotonic()-t
            data.save_json(croot/'result.json', result)
            records.append(result)
            state['records'].append({'file': (croot/'result.json').relative_to(root).as_posix(), 'sha256': data.digest(croot/'result.json')})
            state.update(status='budget_paused', portfolio=portfolio(records))
            data.save_json(root/'state.json', state)
            print(cid, spec['family'], spec['context'], result['status'], round(result['seconds'], 2), flush=True)
            if stop_after is not None and len(records)>=stop_after: reason='test_interrupt'; break
        state.update(status='budget_paused', stop_reason=reason, portfolio=portfolio(records))
        data.save_json(root/'state.json', state)
        return state


def seal(dataset, output):
    dataset, root = Path(dataset), Path(output)
    manifest, arrays = load_data(dataset)
    with lock(root):
        p = read(root/'protocol.json')
        if protocol(dataset, manifest, arrays, p['seed']) != p: raise ValueError('Protocol changed')
        state = read(root/'state.json'); records = inspect_records(root, state)
        retained = state['portfolio']['retained']
        if not retained: raise ValueError('No completed candidate')
        intent = {'protocol_id': state['protocol_id'], 'portfolio': retained,
                  'weights': {i: 1/len(retained) for i in retained}, 'test_feedback_used_for_selection': False}
        if (root/'seal-intent.json').exists() and read(root/'seal-intent.json') != intent:
            raise ValueError('Sealed selection changed')
        data.save_json(root/'seal-intent.json', intent)  # locks selection BEFORE exposing test labels
        if (root/'holdout.json').exists():
            if state.get('holdout_sha256') and data.digest(root/'holdout.json') != state['holdout_sha256']:
                raise ValueError('Holdout evidence changed or incomplete seal')
            if state.get('holdout_sha256'):
                return read(root/'holdout.json')
            # With a frozen intent, interruption recovery deterministically recomputes
            # the same report before a single sealing receipt is committed.
        report = {'protocol_id': state['protocol_id'], 'portfolio': retained, 'candidates': {},
                  'selection_source': 'validation only', 'official_submission': 'manual_only',
                  'claim': 'one fixed grouped holdout; interval uncertainty and external transfer remain open'}
        selected_models = {}
        # Include baseline for a fair reference without letting test outcomes modify retention.
        for r in records:
            if r['status'] != 'complete' or (r['id'] not in retained and r['id'] != 'h00000'): continue
            fitted = read(root/r['model_file']); scores = {}
            for domain in data.DOMAINS:
                a, d = select_rows(arrays, p['splits'], domain, 'test')
                scores[domain], _ = models.evaluate(fitted[domain]['action'], fitted[domain]['duration'], a, d)
            report['candidates'][r['id']] = {'spec': r['spec'], 'test': scores}
            if r['id'] in retained: selected_models[r['id']] = fitted
        report['uniform_portfolio_test'] = {}
        for domain in data.DOMAINS:
            a, d = select_rows(arrays, p['splits'], domain, 'test')
            ap, tp = None, None
            for cid, fitted in selected_models.items():
                aa = intent['weights'][cid]*models.predict_action(fitted[domain]['action'], a)
                tt = intent['weights'][cid]*models.predict_time(fitted[domain]['duration'], d)
                ap = aa if ap is None else ap+aa
                tp = tt if tp is None else tp+tt
            report['uniform_portfolio_test'][domain], _ = models.evaluate_probabilities(ap, tp, a, d, domain)
        data.save_json(root/'holdout.json', report)
        data.save_json(root/'portfolio-models.json', {'weights': intent['weights'], 'models': selected_models})
        state.update(status='sealed', holdout_sha256=data.digest(root/'holdout.json'),
                     portfolio_models_sha256=data.digest(root/'portfolio-models.json'))
        data.save_json(root/'state.json', state)
        return report


def forecast(output, elapsed, additional, stage=0, condition=0):
    root = Path(output); state = read(root/'state.json')
    if data.digest(root/'portfolio-models.json') != state['portfolio_models_sha256']:
        raise ValueError('Exported model changed')
    export = read(root/'portfolio-models.json')
    forecasts = {cid: models.conditional_progress(m['arc']['duration'], elapsed, additional, stage, condition)
                 for cid,m in export['models'].items()}
    values = [r['probability_progress_within_budget'] for r in forecasts.values()]
    # Condition a mixture by survival at elapsed time, rather than averaging
    # conditional probabilities with unconditional weights.
    surviving = {cid: export['weights'][cid]*f['survival_at_elapsed'] for cid,f in forecasts.items()}
    denominator = sum(surviving.values())
    mixture = sum(surviving[cid]*f['probability_progress_within_budget'] for cid,f in forecasts.items())/max(denominator, 1e-12)
    return {'human_progress_probability': mixture, 'model_range': [min(values), max(values)],
            'model_range_is_confidence_interval': False, 'members': forecasts,
            'scope': 'human effort reference, not agent solve probability, causal noticing, or official score forecast'}


def main():
    p = argparse.ArgumentParser(); sub=p.add_subparsers(dest='command', required=True)
    for name in ('run', 'seal'):
        q=sub.add_parser(name); q.add_argument('--dataset', required=True); q.add_argument('--output', required=True)
        if name == 'run':
            q.add_argument('--seed', type=int, default=20261029); q.add_argument('--candidates', type=int, default=5)
            q.add_argument('--seconds', type=int, default=3600)
    q=sub.add_parser('forecast'); q.add_argument('--output', required=True)
    q.add_argument('--elapsed', type=float, required=True); q.add_argument('--additional', type=float, required=True)
    q.add_argument('--stage', type=int, default=0); q.add_argument('--condition', type=int, default=0)
    args=vars(p.parse_args()); command=args.pop('command')
    result={'run': run, 'seal': seal, 'forecast': forecast}[command](**args)
    if command=='forecast': print(json.dumps(result, indent=2))
    else: print('completed', command, flush=True)


if __name__ == '__main__': main()

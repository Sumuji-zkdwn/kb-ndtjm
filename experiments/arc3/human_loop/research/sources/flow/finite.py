"""Exact finite partial Moore systems and independently checkable certificates.

The complete finite transition table is the contract. Missing entries mean
unavailable, not an unimplemented or unexplored transition. No float arithmetic.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations
import json
from types import MappingProxyType


def exact_json(x):
    """Canonical JSON for the intentionally discrete certificate format."""
    def check(v):
        if v is None or type(v) in (str, int, bool):
            return
        if type(v) is list:
            for item in v: check(item)
            return
        if type(v) is dict and all(type(k) is str for k in v):
            for item in v.values(): check(item)
            return
        raise ValueError('Only discrete JSON values are allowed (no floats)')
    check(x)
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def read_json(path):
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d: raise ValueError('Duplicate JSON key: ' + k)
            d[k] = v
        return d
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


@dataclass(frozen=True)
class System:
    states: tuple[str, ...]
    actions: tuple[str, ...]
    # observations are canonical JSON strings, avoiding Python's True == 1.
    observation: object
    transitions: object

    @classmethod
    def from_dict(cls, data):
        if set(data) != {'format', 'states', 'actions', 'observation', 'transitions'}:
            raise ValueError('Unexpected system fields')
        if data['format'] != 'flow-finite-system-r2': raise ValueError('Wrong format')
        states, actions = data['states'], data['actions']
        for values in (states, actions):
            if type(values) is not list or any(type(x) is not str or not x for x in values):
                raise ValueError('State/action identifiers must be nonempty strings')
            if len(values) != len(set(values)): raise ValueError('Duplicate identifier')
        if not states: raise ValueError('A finite system must have at least one state')
        if type(data['observation']) is not dict or set(data['observation']) != set(states):
            raise ValueError('Observation must cover exactly every state')
        obs = {s: exact_json(data['observation'][s]) for s in states}
        if type(data['transitions']) is not list: raise ValueError('Transitions must be a list')
        tr = {}
        for row in data['transitions']:
            if type(row) is not dict or set(row) != {'from', 'action', 'to'}:
                raise ValueError('Malformed transition')
            s, a, t = row['from'], row['action'], row['to']
            if s not in obs or t not in obs or a not in actions:
                raise ValueError('Transition refers to an unknown state/action')
            if (s, a) in tr: raise ValueError('Non-deterministic or duplicate transition')
            tr[s, a] = t
        return cls(tuple(states), tuple(actions), MappingProxyType(obs), MappingProxyType(tr))

    def to_dict(self):
        return dict(format='flow-finite-system-r2', states=list(self.states),
                    actions=list(self.actions),
                    observation={s: json.loads(self.observation[s]) for s in self.states},
                    transitions=[{'from': s, 'action': a, 'to': self.transitions[s, a]}
                                 for s in self.states for a in self.actions if (s, a) in self.transitions])

    def digest(self):
        return sha256(exact_json(self.to_dict()).encode('utf-8')).hexdigest()

    def run(self, state, word):
        if state not in self.observation: raise ValueError('Unknown initial state')
        if type(word) not in (list, tuple) or any(a not in self.actions for a in word):
            raise ValueError('Unknown action or invalid word')
        current = state
        trace = [dict(state=current, observation=json.loads(self.observation[current]))]
        for i, a in enumerate(word):
            if (current, a) not in self.transitions:
                return dict(status='unavailable', failed_at=i, action=a, trace=trace)
            current = self.transitions[current, a]
            trace.append(dict(state=current, observation=json.loads(self.observation[current])))
        return dict(status='success', state=current, observation=json.loads(self.observation[current]), trace=trace)

    def outcome(self, state, word):
        r = self.run(state, word)
        # The general theorem observes success vs failure and the final q only.
        return ('ok', exact_json(r['observation'])) if r['status']=='success' else ('unavailable',)

    def obstruction(self, blocks=None):
        b = self.observation if blocks is None else blocks
        if set(b) != set(self.states): raise ValueError('Partition must cover all states')
        for x, y in combinations(self.states, 2):
            if b[x] != b[y]: continue
            for a in self.actions:
                tx, ty = self.transitions.get((x, a)), self.transitions.get((y, a))
                if (tx is None) != (ty is None):
                    return dict(left=x, right=y, action=a, kind='domain')
                if tx is not None and b[tx] != b[ty]:
                    return dict(left=x, right=y, action=a, kind='successor')
        return None

    def refine(self):
        def labels(signatures):
            ids = {}
            return {s: 'q'+str(ids.setdefault(signatures[s], len(ids))) for s in self.states}
        b = labels(self.observation)
        stages = [b]
        while True:
            signatures = {s: (b[s], tuple(('ok', b[self.transitions[s,a]])
                           if (s,a) in self.transitions else ('unavailable',)
                           for a in self.actions)) for s in self.states}
            nxt = labels(signatures)
            if nxt == b: return dict(blocks=b, stages=stages)
            stages.append(nxt); b = nxt

    def distinguish(self, left, right, max_pairs=None):
        if left not in self.observation or right not in self.observation:
            raise ValueError('Unknown initial state')
        if max_pairs is not None and (type(max_pairs) is not int or max_pairs < 0):
            raise ValueError('Budget must be a nonnegative integer')
        queue = deque([(left, right, [])]); seen = {(left, right)}; visited = 0
        while queue:
            if max_pairs is not None and visited >= max_pairs:
                return dict(status='unknown_budget', word=None, visited_pairs=visited)
            x, y, w = queue.popleft(); visited += 1
            if self.observation[x] != self.observation[y]:
                return dict(status='distinguished', word=w, kind='observation', visited_pairs=visited)
            for a in self.actions:
                tx, ty = self.transitions.get((x, a)), self.transitions.get((y, a))
                if (tx is None) != (ty is None):
                    return dict(status='distinguished', word=w+[a], kind='domain', visited_pairs=visited)
                if tx is None: continue
                if self.observation[tx] != self.observation[ty]:
                    return dict(status='distinguished', word=w+[a], kind='observation', visited_pairs=visited)
                if (tx, ty) not in seen:
                    seen.add((tx, ty)); queue.append((tx, ty, w+[a]))
        return dict(status='equivalent', word=None, visited_pairs=visited)

    def quotient(self, blocks):
        cert = dict(format='flow-partition-certificate-r2', system_sha256=self.digest(), blocks=blocks)
        check = verify_partition(self, cert)
        if not check['valid']: raise ValueError(check['reason'])
        representatives = {}
        for s in self.states: representatives.setdefault(blocks[s], s)
        data = dict(format='flow-finite-system-r2', states=list(representatives), actions=list(self.actions),
                    observation={b: json.loads(self.observation[s]) for b,s in representatives.items()},
                    transitions=[{'from': b, 'action': a, 'to': blocks[self.transitions[s,a]]}
                                 for b,s in representatives.items() for a in self.actions if (s,a) in self.transitions])
        return System.from_dict(data)


def witness_certificate(system, left, right, word):
    if system.outcome(left, word) == system.outcome(right, word):
        raise ValueError('Word does not distinguish these states')
    return dict(format='flow-witness-certificate-r2', system_sha256=system.digest(), left=left, right=right,
                word=list(word), claims={'left': system.run(left,word), 'right':system.run(right,word)})


def verify_witness(system, certificate):
    try:
        if set(certificate) != {'format','system_sha256','left','right','word','claims'}:
            raise ValueError('Unexpected certificate fields (optimality is not a witness claim)')
        if certificate['format'] != 'flow-witness-certificate-r2': raise ValueError('Wrong format')
        if certificate['system_sha256'] != system.digest(): raise ValueError('System hash mismatch')
        actual = witness_certificate(system, certificate['left'], certificate['right'], certificate['word'])
        if exact_json(actual) != exact_json(certificate): raise ValueError('Replayed claims do not match')
        return dict(valid=True, distinguishes=True, shortest_verified=False)
    except (ValueError, KeyError, TypeError) as e:
        return dict(valid=False, reason=str(e))


def verify_partition(system, certificate):
    """Checks stability and observation refinement, NOT minimality/coarsestness."""
    try:
        if set(certificate) != {'format','system_sha256','blocks'}: raise ValueError('Unexpected partition fields')
        if certificate['format'] != 'flow-partition-certificate-r2': raise ValueError('Wrong format')
        if certificate['system_sha256'] != system.digest(): raise ValueError('System hash mismatch')
        b = certificate['blocks']
        if type(b) is not dict or set(b) != set(system.states) or any(type(x) is not str or not x for x in b.values()):
            raise ValueError('Invalid partition map')
        for x,y in combinations(system.states,2):
            if b[x]==b[y] and system.observation[x]!=system.observation[y]:
                raise ValueError('Partition loses the specified observation')
        bad=system.obstruction(b)
        if bad: raise ValueError('Unstable partition: '+str(bad))
        return dict(valid=True, stable=True, coarsest_verified=False)
    except (ValueError, KeyError, TypeError) as e:
        return dict(valid=False, reason=str(e))


def relation_oracle(system):
    """Independent greatest-fixed-point elimination on ALL ordered state pairs."""
    relation={(x,y) for x in system.states for y in system.states
              if system.observation[x]==system.observation[y]}
    while True:
        remove=set()
        for x,y in relation:
            for a in system.actions:
                tx,ty=system.transitions.get((x,a)),system.transitions.get((y,a))
                if (tx is None)!=(ty is None) or (tx is not None and (tx,ty) not in relation):
                    remove.add((x,y));break
        if not remove:return relation
        relation-=remove

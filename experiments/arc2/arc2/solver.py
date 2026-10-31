"""Bounded symbolic synthesis with exact observational-state deduplication.

Every fitted rule sees demonstration pairs only.  A search state includes ALL
demonstration and test inputs: equality on demonstrations alone is not a sound
reason to merge programs that disagree on a test input.  Complete grid bytes
are compared, so there is no lossy embedding or hash-collision assumption.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
import os
from pathlib import Path
import time

import numpy as np

from .grid import as_grid, key, valid_grid
from .operators import primitive_rules, constant_rule
from .types import Rule


@dataclass(frozen=True)
class SolverConfig:
    time_limit: float = 5.0
    max_states: int = 2000
    beam_width: int = 32
    max_depth: int = 3
    max_candidates: int = 96
    use_cpp: bool = False
    cpp_fraction: float = 0.6
    cpp_memory_mb: int = 768


@dataclass
class State:
    grids: tuple[np.ndarray, ...]
    path: tuple[str, ...]
    families: tuple[str, ...]
    cost: float
    score: float
    exact: bool


def state_key(grids) -> tuple[bytes, ...]:
    return tuple(key(a) for a in grids)


def _agreement(pred, target):
    if pred.shape != target.shape:
        # Shape receives a small, nonnegative heuristic; never exact credit.
        h,w=pred.shape; hh,ww=target.shape
        return .16*(min(h,hh)/max(h,hh)+min(w,ww)/max(w,ww))/2
    same=pred==target
    if bool(np.all(same)):
        return 1.0
    colors=np.unique(target)
    balanced=sum(float(same[target==c].mean()) for c in colors)/len(colors)
    return .2+.4*float(same.mean())+.4*balanced


def _fitness(grids, targets):
    scores=[_agreement(a,b) for a,b in zip(grids,targets)]
    return sum(scores)/len(scores), all(x==1.0 for x in scores)


def _apply(rule, grids, errors):
    values=[]
    try:
        for a in grids:
            b=rule.fn(a)
            if b is None or not valid_grid(b):
                return None
            b=np.array(b,dtype=np.uint8,copy=True)
            b.flags.writeable=False
            values.append(b)
    except Exception as exc:
        # A failed rule cannot poison the whole submission. Unexpected failures
        # are visible in the report instead of being silently counted as fits.
        k=f"{rule.name}: {type(exc).__name__}: {str(exc)[:100]}"
        if len(errors)<12 or k in errors:
            errors[k]=errors.get(k,0)+1
        return None
    return tuple(values)


def _color_maps(grids, targets):
    if any(a.shape!=b.shape for a,b in zip(grids,targets)):
        return []
    mapping={}
    for a,b in zip(grids,targets):
        for color in np.unique(a):
            vals=np.unique(b[a==color])
            if len(vals)!=1:
                return []
            old=mapping.setdefault(int(color),int(vals[0]))
            if old!=int(vals[0]):
                return []
    if all(k==v for k,v in mapping.items()):
        return []
    lut=np.arange(10,dtype=np.uint8)
    for k,v in mapping.items():
        lut[k]=v
    desc=",".join(f"{k}:{v}" for k,v in sorted(mapping.items()) if k!=v)
    cost=.7+.12*sum(k!=v for k,v in mapping.items())
    rules=[Rule(f"recolor[{desc}]",lambda a,m=lut:m[a],cost,"recolor")]
    # When demonstrations establish a binary mask, unknown colors may mean
    # foreground. Retain this as a separate, more expensive hypothesis.
    if 0 in mapping and len(set(v for k,v in mapping.items() if k!=0))==1:
        fg=next(v for k,v in mapping.items() if k!=0)
        m=lut.copy()
        for c in range(1,10):
            if c not in mapping: m[c]=fg
        if not np.array_equal(m,lut):
            rules.append(Rule(f"recolor_foreground[{desc}]",lambda a,m=m:m[a],cost+.4,"recolor"))
    return rules


def _beam(states, width):
    ranked=sorted(states,key=lambda s:(-s.score+.012*s.cost,s.cost,s.path))
    # Reserve part of the beam for structurally different intermediates.
    result=[]; chosen=set(); groups=set()
    for s in ranked:
        tag=(tuple(a.shape for a in s.grids),s.families[-1] if s.families else "identity")
        if tag not in groups:
            result.append(s); chosen.add(id(s)); groups.add(tag)
            if len(result)>=max(1,width//2): break
    for s in ranked:
        if len(result)>=width: break
        if id(s) not in chosen:
            result.append(s); chosen.add(id(s))
    return result


def _rank_outputs(states, test_index):
    """Keep separate output events; aliases within a rule family do not vote twice."""
    groups={}
    for s in states:
        k=key(s.grids[test_index])
        group=groups.setdefault(k,{"grid":s.grids[test_index],"states":[],"votes":{}})
        group["states"].append(s)
    ranked=[]
    for g in groups.values():
        best=min(g["states"],key=lambda s:(not s.exact,-s.score,s.cost,s.path))
        for s in g["states"]:
            if best.exact and not s.exact:
                continue
            family=tuple(sorted(set(s.families)))
            weight=math.exp(-.55*s.cost)
            g["votes"][family]=max(weight,g["votes"].get(family,0))
        support=sum(sorted(g["votes"].values(),reverse=True)[:4])
        # Training agreement dominates approximate candidates. Among exact
        # hypotheses, simple independent derivations provide limited support.
        rank=(int(best.exact),best.score,support,-best.cost)
        ranked.append((rank,best,g["grid"]))
    ranked.sort(key=lambda t:(t[0],key(t[2])),reverse=True)
    return ranked


def _solve_symbolic(task, config=None):
    config=config or SolverConfig()
    if isinstance(config,dict): config=SolverConfig(**config)
    if (not math.isfinite(config.time_limit) or config.time_limit<=0 or config.max_states<1
            or config.beam_width<1 or config.max_depth<0 or config.max_candidates<1):
        raise ValueError("Positive finite time/state/beam/candidate budgets and nonnegative depth are required")
    start=time.monotonic(); deadline=start+config.time_limit
    # Reconstruct the accepted input explicitly. Extra keys, including test
    # answers in public files, are never forwarded to a hypothesis factory.
    train=[{"input":as_grid(p["input"]),"output":as_grid(p["output"])} for p in task["train"]]
    tests=[as_grid(p["input"]) for p in task["test"]]
    if not train or not tests: raise ValueError("At least one train and test input is required")
    targets=tuple(p["output"] for p in train)
    grids=tuple([p["input"] for p in train]+tests)
    for a in grids: a.flags.writeable=False
    score,exact=_fitness(grids,targets)
    initial=State(grids,(),(),0.0,score,exact)
    seen={state_key(grids):0.0}
    exact_states=[]; partial_states=[initial]; errors={}
    stats={"operator_applications":0,"duplicate_states":0,"generated_states":1,
           "exact_training_programs":0,"peak_frontier":1}
    if exact: exact_states.append(initial)

    base_rules=primitive_rules(train)
    object_rules=[]; direct_rules=[]
    stages={}
    stage_start=time.monotonic()
    from .objects import object_rules as make_objects
    object_rules=make_objects(train,deadline=min(deadline,start+config.time_limit*.25))
    stages["object_rule_generation_seconds"]=time.monotonic()-stage_start
    stage_start=time.monotonic()
    from .patterns import pattern_rules
    direct_rules=pattern_rules(train,deadline=min(deadline,start+config.time_limit*.50))
    stages["pattern_rule_generation_seconds"]=time.monotonic()-stage_start
    stage_start=time.monotonic()
    from .relations import relation_rules
    direct_rules+=relation_rules(train,deadline=min(deadline,start+config.time_limit*.60))
    stages["relation_rule_generation_seconds"]=time.monotonic()-stage_start
    const=constant_rule(train)
    if const: direct_rules.append(const)
    # Direct fitted rules are assessed on every demonstration again here.
    all_first=direct_rules+base_rules+object_rules
    composed=base_rules+[r for r in object_rules if r.family!="object_recolor"]

    def remember(state):
        stats["generated_states"]+=1
        if state.exact:
            stats["exact_training_programs"]+=1
            exact_states.append(state)
        else:
            partial_states.append(state)

    def recolor_terminal(state):
        for rule in _color_maps(state.grids,targets):
            if time.monotonic()>=deadline or len(seen)>=config.max_states: break
            result=_apply(rule,state.grids,errors)
            stats["operator_applications"]+=1
            if result is None: continue
            k=state_key(result); cost=state.cost+rule.cost
            if k in seen and seen[k]<=cost:
                stats["duplicate_states"]+=1; continue
            seen[k]=cost
            fit,ex=_fitness(result,targets)
            remember(State(result,state.path+(rule.name,),state.families+(rule.family,),cost,fit,ex))

    recolor_terminal(initial)
    frontier=[initial]
    for depth in range(1,config.max_depth+1):
        next_states=[]
        for parent in frontier:
            rules=all_first if depth==1 else composed
            for rule in rules:
                if time.monotonic()>=deadline or len(seen)>=config.max_states: break
                # Avoid immediate repeated involutions without reducing the
                # language's useful non-involutive repetitions.
                if parent.path and parent.path[-1]==rule.name and rule.family=="geometry": continue
                result=_apply(rule,parent.grids,errors)
                stats["operator_applications"]+=1
                if result is None: continue
                k=state_key(result); cost=parent.cost+rule.cost
                if k in seen and seen[k]<=cost:
                    stats["duplicate_states"]+=1; continue
                seen[k]=cost
                fit,ex=_fitness(result,targets)
                state=State(result,parent.path+(rule.name,),parent.families+(rule.family,),cost,fit,ex)
                remember(state)
                recolor_terminal(state)
                if not ex:
                    next_states.append(state)
            if time.monotonic()>=deadline or len(seen)>=config.max_states: break
        stats["peak_frontier"]=max(stats["peak_frontier"],len(next_states))
        frontier=_beam(next_states,config.beam_width)
        if not frontier or time.monotonic()>=deadline or len(seen)>=config.max_states: break
    # Removing duplicate final predictions does not change the transition
    # system. A bounded pool avoids spending unbounded time on vote ranking.
    exact_states.sort(key=lambda s:(s.cost,s.path))
    unique_exact={}
    for s in exact_states:
        unique_exact.setdefault(state_key(s.grids[len(train):]),s)
    exact_pool=list(unique_exact.values())[:config.max_candidates]
    partial_states.sort(key=lambda s:(-s.score,s.cost,s.path))
    partial_pool=partial_states[:max(24,config.max_candidates//2)]
    attempts=[]; selections=[]
    for index in range(len(tests)):
        ranking=_rank_outputs(exact_pool+partial_pool,len(train)+index)
        chosen=ranking[:2]
        if len(chosen)==1: chosen=chosen*2
        attempts.append({f"attempt_{j+1}":entry[2].tolist() for j,entry in enumerate(chosen)})
        selections.append([{"program":list(entry[1].path) or ["identity"],
                            "training_exact":entry[1].exact,"training_agreement":round(entry[1].score,6),
                            "cost":round(entry[1].cost,4)} for entry in chosen])
    elapsed=time.monotonic()-start
    return {"attempts":attempts,"diagnostics":{
        "solver":"arc2-symbolic-candidate-v1","config":asdict(config),"elapsed_seconds":elapsed,
        "stopped_on_time":time.monotonic()>=deadline,"stopped_on_state_budget":len(seen)>=config.max_states,
        "unique_exact_training_predictions":len(unique_exact),
        "rules":{"primitive":len(base_rules),"object":len(object_rules),"pattern":len(direct_rules)},
        "selection":selections,"rule_errors":errors,**stats,**stages,
        "equivalence_scope":"full grids on every train input AND every test input",
        "test_output_access":False,
    }}


def solve_task(task, config=None):
    """Public API. C++ is optional and must be prepared outside task budgets."""
    config=config or SolverConfig()
    if isinstance(config,dict): config=SolverConfig(**config)
    if not 0<config.cpp_fraction<1 or config.cpp_memory_mb<128:
        raise ValueError("cpp_fraction must be in (0,1) and cpp_memory_mb >= 128")
    if not config.use_cpp:
        return _solve_symbolic(task,config)
    start=time.monotonic()
    path=os.environ.get("ARC2_CPP_BINARY","")
    if not path or not Path(path).is_file():
        result=_solve_symbolic(task,replace(config,use_cpp=False))
        result["diagnostics"]["cpp"]={"status":"not_prepared","used":False}
        result["diagnostics"]["requested_config"]=asdict(config)
        return result
    symbolic=_solve_symbolic(task,replace(config,use_cpp=False,time_limit=config.time_limit*(1-config.cpp_fraction)))
    remaining=max(0.0,config.time_limit-(time.monotonic()-start))
    from .cpp_backend import solve_cpp
    # Rebuild the payload here as well; direct API callers may pass full public
    # tasks with answers. Only the demonstrations and test inputs go to C++.
    clean={"train":[{"input":p["input"],"output":p["output"]} for p in task["train"]],
           "test":[{"input":p["input"]} for p in task["test"]]}
    try:
        cpp=solve_cpp(clean,seconds=remaining,max_memory_mb=config.cpp_memory_mb)
    except Exception as exc:
        cpp={"predictions":[],"diagnostics":{"status":"error","error":f"{type(exc).__name__}: {exc}"}}
    from .portfolio import merge_predictions
    attempts,selections=merge_predictions(symbolic,cpp,len(task["train"]))
    return {"attempts":attempts,"diagnostics":{
        "solver":"arc2-portfolio-candidate-v1","config":asdict(config),
        "elapsed_seconds":time.monotonic()-start,"selection":selections,
        "symbolic":symbolic["diagnostics"],"symbolic_attempts":symbolic["attempts"],
        "cpp":cpp.get("diagnostics",{}),"cpp_predictions":cpp.get("predictions",[]),
        "cpp_training_exact":cpp.get("training_exact",[]),
        "test_output_access":False,
    }}

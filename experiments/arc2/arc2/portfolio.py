"""A fixed, label-free two-attempt policy for the independent search engines."""
from __future__ import annotations

import numpy as np

from .grid import key, valid_grid


def merge_predictions(symbolic, cpp, training_count):
    """Prefer exact demonstration fits and preserve independent predictions.

    Complexity numbers from different engines are not calibrated probabilities.
    The policy is declared explicitly: very simple Python programs (cost<=2.8),
    exact C++ candidates, other exact Python programs, then partial fallbacks.
    For the second slot, prefer a different engine at the same consistency tier,
    unless doing so would substitute a complex Python lookup (cost>8) for an
    exact C++ candidate. No held-out labels enter this function.
    """
    attempts=[]; selections=[]
    for i, own in enumerate(symbolic["attempts"]):
        candidates=[]
        own_meta=symbolic.get("diagnostics",{}).get("selection",[])
        for j in range(2):
            meta=own_meta[i][j] if i<len(own_meta) and j<len(own_meta[i]) else {}
            exact=bool(meta.get("training_exact",False))
            cost=float(meta.get("cost",100))
            candidates.append({"grid":own[f"attempt_{j+1}"],"origin":"python",
                               "training_exact":exact,"cost":cost,"rank":j,
                               "program":meta.get("program",[]),
                               "quality":3 if exact and cost<=2.8 else 1 if exact else 0})
        cpp_grids=cpp.get("predictions",[])
        for j,g in enumerate(cpp_grids[i] if i<len(cpp_grids) else []):
            if not valid_grid(g): continue
            matches=cpp.get("train_matches",[])
            count=matches[i][j] if i<len(matches) and j<len(matches[i]) else -1
            exact=count==training_count
            raw=cpp.get("scores",[])
            raw_score=raw[i][j] if i<len(raw) and j<len(raw[i]) else None
            candidates.append({"grid":g,"origin":"cpp","training_exact":exact,
                               "train_matches":count,"raw_score":raw_score,"rank":j,
                               "quality":2 if exact else 0})
        candidates.sort(key=lambda c:(-int(c["training_exact"]),-c["quality"],c["rank"],c["origin"]))
        first=candidates[0]
        seen={key(np.asarray(first["grid"],dtype=np.uint8))}
        alternatives=[c for c in candidates if key(np.asarray(c["grid"],dtype=np.uint8)) not in seen]
        if alternatives:
            best=alternatives[0]
            cross=[c for c in alternatives if c["origin"]!=first["origin"]
                   and c["training_exact"]==best["training_exact"]
                   and not (c["origin"]=="python" and c.get("cost",100)>8 and best["training_exact"])]
            second=cross[0] if cross else best
        else:
            second=first
        chosen=[first,second]
        attempts.append({f"attempt_{j+1}":np.asarray(c["grid"],dtype=np.uint8).tolist()
                         for j,c in enumerate(chosen)})
        selections.append([{k:v for k,v in c.items() if k not in {"grid","quality"}} for c in chosen])
    return attempts,selections


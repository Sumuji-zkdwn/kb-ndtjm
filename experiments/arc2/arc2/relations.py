"""Small exact-fit relation families learned exclusively from demonstrations."""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import time

import numpy as np

from .grid import background
from .types import Rule


def _bg_zero(grid):
    return 0


def _bg_mode(grid):
    return int(background(grid))


@lru_cache(maxsize=128)
def _enclosed_cached(shape: tuple[int, int], data: bytes, bg: int,
                     diagonal: bool) -> tuple:
    grid = np.frombuffer(data, dtype=np.uint8).reshape(shape)
    h, w = shape
    directions = [(1,0),(-1,0),(0,1),(0,-1)]
    if diagonal:
        directions += [(1,1),(1,-1),(-1,1),(-1,-1)]
    visited = np.zeros(shape, dtype=bool)
    result = []
    for r, c in np.argwhere(grid == bg):
        r, c = int(r), int(c)
        if visited[r,c]:
            continue
        visited[r,c] = True
        queue = deque([(r,c)])
        cells = []
        boundary = set()
        outside = False
        while queue:
            a, b = queue.popleft()
            cells.append((a,b))
            outside |= a in (0,h-1) or b in (0,w-1)
            for dr, dc in directions:
                rr, cc = a+dr, b+dc
                if 0 <= rr < h and 0 <= cc < w:
                    if grid[rr,cc] != bg:
                        boundary.add(int(grid[rr,cc]))
                    elif not visited[rr,cc]:
                        visited[rr,cc] = True
                        queue.append((rr,cc))
        if not outside:
            result.append((tuple(cells), tuple(sorted(boundary))))
    return tuple(result)


def _enclosed(grid, bg, diagonal):
    a = np.asarray(grid,dtype=np.uint8)
    return _enclosed_cached(a.shape,a.tobytes(),bg,diagonal)


def _fill(grid, bg_fn, diagonal, target, selector='all', boundary_color=None):
    bg = bg_fn(grid)
    regions = _enclosed(grid,bg,diagonal)
    if boundary_color is not None:
        regions = tuple(r for r in regions if r[1] == (boundary_color,))
    if not regions:
        return None
    if selector == 'largest':
        size = max(len(cells) for cells,_ in regions)
        regions = tuple(r for r in regions if len(r[0]) == size)
    elif selector == 'smallest':
        size = min(len(cells) for cells,_ in regions)
        regions = tuple(r for r in regions if len(r[0]) == size)
    out = grid.copy()
    for cells,_ in regions:
        for r,c in cells:
            out[r,c] = target
    return out


def _bbox_color(grid, color):
    rows,cols = np.where(grid == color)
    if not len(rows):
        return None
    return (int(rows.min()),int(cols.min()),int(rows.max())+1,int(cols.max())+1)


def _axis_ref(bbox, axis, ref):
    low,high = bbox[axis],bbox[axis+2]-1
    # Twice the coordinate represents half-integer centers without rounding.
    return {'min':2*low,'max':2*high,'center':low+high}[ref]


def _axis_delta(moving_bbox, anchor_bbox, axis, formula):
    if formula == ('unchanged',):
        return 0
    anchor_ref,moving_ref,offset = formula
    twice = (_axis_ref(anchor_bbox,axis,anchor_ref)
             -_axis_ref(moving_bbox,axis,moving_ref)+2*offset)
    return twice//2 if twice % 2 == 0 else None


def _translate(grid,bg_fn,moving_color,anchor_color,row_formula,col_formula):
    bg = bg_fn(grid)
    if moving_color in (bg,anchor_color):
        return None
    moving_bbox,anchor_bbox = _bbox_color(grid,moving_color),_bbox_color(grid,anchor_color)
    if moving_bbox is None or anchor_bbox is None:
        return None
    dr = _axis_delta(moving_bbox,anchor_bbox,0,row_formula)
    dc = _axis_delta(moving_bbox,anchor_bbox,1,col_formula)
    if dr is None or dc is None:
        return None
    rows,cols = np.where(grid == moving_color)
    nr,nc = rows+dr,cols+dc
    h,w = grid.shape
    if np.any(nr<0) or np.any(nr>=h) or np.any(nc<0) or np.any(nc>=w):
        return None
    if np.any((grid[nr,nc] != bg) & (grid[nr,nc] != moving_color)):
        return None
    out = grid.copy()
    out[rows,cols] = bg
    out[nr,nc] = moving_color
    return out


def _observed_translation(x,y,color):
    source = np.argwhere(x == color)
    target = np.argwhere(y == color)
    if not len(source) or source.shape != target.shape:
        return None
    delta = target.min(axis=0)-source.min(axis=0)
    if not np.array_equal(source+delta,target):
        return None
    return tuple(int(v) for v in delta)


def _fit_axis(records,axis):
    formulas = [('unchanged',)]
    # Equality of any edge or center; offsets +-1 express edge adjacency.
    formulas += [(a,m,d) for d in (0,-1,1)
                 for a in ('min','max','center') for m in ('min','max','center')]
    found = []
    for formula in formulas:
        if all(_axis_delta(m,a,axis,formula) == delta[axis] for m,a,delta in records):
            found.append(formula)
    # Favor simpler edge formulas; retain enough ambiguity for unseen layouts.
    return found[:6]


def _exact(fn,train):
    for pair in train:
        result = fn(pair['input'])
        if result is None or not np.array_equal(result,pair['output']):
            return False
    return True


def relation_rules(train: list[dict], deadline: float | None = None) -> list[Rule]:
    """Learn exact hole-fill and shape-translation rules in at most ~0.2 s.

    Only training input/output arrays are inspected. Every returned rule is pure,
    with parameters frozen from demonstrations; its name contains no task ID.
    The limit is cooperative and checked between bounded grid operations.
    """
    finish = time.monotonic()+.2
    if deadline is not None:
        finish = min(finish,deadline)
    if not train or time.monotonic() >= finish:
        return []
    pairs = [{'input':np.asarray(e['input'],dtype=np.uint8),
              'output':np.asarray(e['output'],dtype=np.uint8)} for e in train]
    if any(p['input'].shape != p['output'].shape for p in pairs):
        return []
    changed_colors = sorted({int(c) for p in pairs
                             for c in p['output'][p['input'] != p['output']]})
    if not changed_colors:
        return []
    rules = []
    bg_options = [('zero',_bg_zero),('mode',_bg_mode)]
    for bg_name,bg_fn in bg_options:
        for diagonal in (False,True):
            if time.monotonic() >= finish:
                return rules
            boundaries = set()
            for pair in pairs:
                for _,colors in _enclosed(pair['input'],bg_fn(pair['input']),diagonal):
                    if len(colors) == 1:
                        boundaries.add(colors[0])
            selectors = [('all',None),('largest',None),('smallest',None)]
            selectors += [('all',c) for c in sorted(boundaries)]
            for target in changed_colors:
                for selector,boundary_color in selectors:
                    if time.monotonic() >= finish:
                        return rules
                    def fill(grid,bf=bg_fn,d=diagonal,t=target,s=selector,b=boundary_color):
                        return _fill(grid,bf,d,t,s,b)
                    if _exact(fill,pairs):
                        suffix = '' if boundary_color is None else f':boundary{boundary_color}'
                        name = f'relation:enclosed:{bg_name}:{8 if diagonal else 4}:{selector}:to{target}{suffix}'
                        cost = 1.6 + .2*(selector != 'all') + .2*(boundary_color is not None)
                        rules.append(Rule(name,fill,cost,'learned_relation_fill'))

    common_colors = set(int(c) for c in np.unique(pairs[0]['input']))
    for pair in pairs[1:]:
        common_colors.intersection_update(int(c) for c in np.unique(pair['input']))
    for moving_color in sorted(common_colors):
        if time.monotonic() >= finish:
            break
        deltas = [_observed_translation(p['input'],p['output'],moving_color) for p in pairs]
        if any(d is None for d in deltas) or all(d == (0,0) for d in deltas):
            continue
        for anchor_color in sorted(common_colors-{moving_color}):
            if time.monotonic() >= finish:
                return rules
            # The anchor itself must remain unchanged in every demonstration.
            if any(not np.array_equal(p['input']==anchor_color,p['output']==anchor_color) for p in pairs):
                continue
            records = [(_bbox_color(p['input'],moving_color),
                        _bbox_color(p['input'],anchor_color),delta)
                       for p,delta in zip(pairs,deltas)]
            row_formulas,col_formulas = _fit_axis(records,0),_fit_axis(records,1)
            for bg_name,bg_fn in bg_options:
                if any(bg_fn(p['input']) in (moving_color,anchor_color) for p in pairs):
                    continue
                for rf in row_formulas:
                    for cf in col_formulas:
                        if time.monotonic() >= finish:
                            return rules
                        def translate(grid,bf=bg_fn,m=moving_color,a=anchor_color,r=rf,c=cf):
                            return _translate(grid,bf,m,a,r,c)
                        if _exact(translate,pairs):
                            name = f'relation:translate:{bg_name}:{moving_color}:anchor{anchor_color}:r{rf}:c{cf}'
                            complexity = sum(f != ('unchanged',) for f in (rf,cf))
                            rules.append(Rule(name,translate,2.0+.3*complexity,'learned_relation_move'))
    return rules

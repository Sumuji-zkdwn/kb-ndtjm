"""Bounded, interpretable object transforms for grid-to-grid induction.

The factory observes training examples only.  None means that a rule's structural
preconditions fail; it never means an all-zero prediction.  Learned recoloring
rules are retained only if they reproduce every training output exactly.
"""
from __future__ import annotations

from collections import Counter, deque
from functools import lru_cache
import time
from typing import Callable

import numpy as np

from .grid import background, components
from .types import Rule


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _mode_background(grid: np.ndarray) -> int:
    return int(background(grid))


def _zero_background(grid: np.ndarray) -> int:
    return 0


@lru_cache(maxsize=192)
def _cached_components(shape: tuple[int, int], data: bytes, bg: int,
                       diagonal: bool, monochrome: bool) -> tuple[dict, ...]:
    grid = np.frombuffer(data, dtype=np.int8).reshape(shape)
    # The shared grid implementation owns connectivity conventions.  Copy the
    # returned dictionaries so callers cannot mutate a shared grid cache.
    return tuple(dict(o) for o in components(
        grid, bg=bg, diagonal=diagonal, monochrome=monochrome))


def _objects(grid: np.ndarray, bg: int, diagonal: bool = False,
             monochrome: bool = True) -> tuple[dict, ...]:
    arr = np.asarray(grid, dtype=np.int8)
    return _cached_components(arr.shape, arr.tobytes(), int(bg),
                              diagonal, monochrome)


def _shape(obj: dict, dihedral: bool = False) -> tuple:
    r0, c0, r1, c1 = obj['bbox']
    mask = np.zeros((r1-r0, c1-c0), dtype=np.uint8)
    for r, c in obj['cells']:
        mask[r-r0, c-c0] = 1
    return _canonical_shape(mask.shape, mask.tobytes(), dihedral)


@lru_cache(maxsize=4096)
def _canonical_shape(shape: tuple[int, int], data: bytes, dihedral: bool) -> tuple:
    if not dihedral:
        return (shape, data)
    mask = np.frombuffer(data, dtype=np.uint8).reshape(shape)
    variants = []
    for k in range(4):
        a = np.rot90(mask, k)
        variants.append((a.shape, a.tobytes()))
        b = np.fliplr(a)
        variants.append((b.shape, b.tobytes()))
    return min(variants)


def _holes(obj: dict) -> int:
    """Number of bounded 4-connected regions in an object's binary mask."""
    r0, c0, r1, c1 = obj['bbox']
    cells = tuple(sorted((r-r0+1, c-c0+1) for r, c in obj['cells']))
    return _hole_count(r1-r0+2, c1-c0+2, cells)


@lru_cache(maxsize=2048)
def _hole_count(h: int, w: int, cell_tuple: tuple[tuple[int, int], ...]) -> int:
    cells = set(cell_tuple)
    seen: set[tuple[int, int]] = set()
    bounded = 0
    for r in range(h):
        for c in range(w):
            if (r, c) in cells or (r, c) in seen:
                continue
            q = [(r, c)]
            seen.add((r, c))
            outside = False
            while q:
                u, v = q.pop()
                outside |= u in (0, h-1) or v in (0, w-1)
                for a, b in ((u-1, v), (u+1, v), (u, v-1), (u, v+1)):
                    if (0 <= a < h and 0 <= b < w and (a, b) not in cells
                            and (a, b) not in seen):
                        seen.add((a, b))
                        q.append((a, b))
            bounded += not outside
    return bounded


def _crop_objects(grid: np.ndarray, objs: list[dict] | tuple[dict, ...],
                  bg: int, masked: bool = True) -> np.ndarray | None:
    if not objs:
        return None
    r0 = min(o['bbox'][0] for o in objs)
    c0 = min(o['bbox'][1] for o in objs)
    r1 = max(o['bbox'][2] for o in objs)
    c1 = max(o['bbox'][3] for o in objs)
    if not masked:
        return grid[r0:r1, c0:c1].copy()
    out = np.full((r1-r0, c1-c0), bg, dtype=grid.dtype)
    for obj in objs:
        for r, c in obj['cells']:
            out[r-r0, c-c0] = grid[r, c]
    return out


def _select(grid: np.ndarray, objs: tuple[dict, ...], criterion: str) -> list[dict]:
    if not objs:
        return []
    if criterion in ('unique_shape', 'repeated_shape'):
        counts = Counter(_shape(o, True) for o in objs)
        if criterion == 'unique_shape':
            chosen = [o for o in objs if counts[_shape(o, True)] == 1]
            return chosen if len(chosen) == 1 else []
        repeated = {shape for shape, count in counts.items() if count > 1}
        # A single repeated equivalence class is an unambiguous object group;
        # crop its union, preserving relative positions and background gaps.
        return ([o for o in objs if _shape(o, True) in repeated]
                if len(repeated) == 1 else [])
    values: list[int] = []
    for o in objs:
        r0, c0, r1, c1 = o['bbox']
        if criterion in ('largest', 'smallest'):
            value = o['size']
        elif criterion in ('largest_box', 'smallest_box'):
            value = (r1-r0)*(c1-c0)
        elif criterion == 'widest':
            value = c1-c0
        elif criterion == 'tallest':
            value = r1-r0
        elif criterion == 'most_colors':
            value = len({int(grid[r, c]) for r, c in o['cells']})
        elif criterion == 'most_holes':
            value = _holes(o)
        else:
            raise ValueError(criterion)
        values.append(value)
    target = min(values) if criterion in ('smallest', 'smallest_box') else max(values)
    selected = [o for o, v in zip(objs, values) if v == target]
    return selected if len(selected) == 1 else []


def _selection(grid: np.ndarray, bg_fn: Callable, diagonal: bool,
               monochrome: bool, criterion: str, masked: bool = True) -> np.ndarray | None:
    bg = bg_fn(grid)
    objs = _objects(grid, bg, diagonal, monochrome)
    return _crop_objects(grid, _select(grid, objs, criterion), bg, masked)


def _filter(grid: np.ndarray, bg_fn: Callable, diagonal: bool,
            monochrome: bool, criterion: str) -> np.ndarray | None:
    bg = bg_fn(grid)
    objs = _objects(grid, bg, diagonal, monochrome)
    if not objs:
        return None
    sizes = Counter(o['size'] for o in objs)
    shapes = (Counter(_shape(o, True) for o in objs)
              if criterion in ('repeated_shape', 'unique_shape') else None)
    h, w = grid.shape
    largest = max(o['size'] for o in objs)
    smallest = min(o['size'] for o in objs)
    chosen = []
    for o in objs:
        r0, c0, r1, c1 = o['bbox']
        border = r0 == 0 or c0 == 0 or r1 == h or c1 == w
        if criterion == 'largest':
            keep = o['size'] == largest
        elif criterion == 'smallest':
            keep = o['size'] == smallest
        elif criterion == 'non_singletons':
            keep = o['size'] > 1
        elif criterion == 'unique_size':
            keep = sizes[o['size']] == 1
        elif criterion == 'repeated_shape':
            keep = shapes[_shape(o, True)] > 1
        elif criterion == 'unique_shape':
            keep = shapes[_shape(o, True)] == 1
        elif criterion == 'border':
            keep = border
        elif criterion == 'interior':
            keep = not border
        else:
            raise ValueError(criterion)
        if keep:
            chosen.append(o)
    if not chosen:
        return None
    out = np.full_like(grid, bg)
    for obj in chosen:
        for r, c in obj['cells']:
            out[r, c] = grid[r, c]
    return out


def _paint(grid: np.ndarray, bg_fn: Callable, diagonal: bool, mode: str) -> np.ndarray | None:
    bg = bg_fn(grid)
    objs = _objects(grid, bg, diagonal, True)
    out = grid.copy()
    if not objs:
        return None
    for o in objs:
        r0, c0, r1, c1 = o['bbox']
        color = int(o['color'])
        cells = set(o['cells'])
        if mode == 'outline':
            for r, c in cells:
                if all(p in cells for p in ((r-1, c), (r+1, c), (r, c-1), (r, c+1))):
                    out[r, c] = bg
        elif mode in ('rectangle', 'box_outline'):
            for r in range(r0, r1):
                for c in range(c0, c1):
                    if mode == 'box_outline' and r not in (r0, r1-1) and c not in (c0, c1-1):
                        continue
                    if grid[r, c] == bg:
                        # Conflicting paints are an ambiguous transformation.
                        if out[r, c] not in (bg, color):
                            return None
                        out[r, c] = color
        elif mode == 'fill_holes':
            # The object's own pixels form the boundary. Other colors are
            # preserved, including markers inside the bounded region.
            outside = set()
            q = deque()
            for r in range(r0-1, r1+1):
                for c in (c0-1, c1):
                    outside.add((r, c)); q.append((r, c))
            for c in range(c0-1, c1+1):
                for r in (r0-1, r1):
                    if (r, c) not in outside:
                        outside.add((r, c)); q.append((r, c))
            while q:
                r, c = q.popleft()
                for p in ((r-1, c), (r+1, c), (r, c-1), (r, c+1)):
                    if (r0-1 <= p[0] <= r1 and c0-1 <= p[1] <= c1
                            and p not in cells and p not in outside):
                        outside.add(p); q.append(p)
            for r in range(r0, r1):
                for c in range(c0, c1):
                    if (r, c) not in outside and grid[r, c] == bg:
                        if out[r, c] not in (bg, color):
                            return None
                        out[r, c] = color
        else:
            raise ValueError(mode)
    return out


def _pixel_gravity(grid: np.ndarray, bg_fn: Callable, direction: str) -> np.ndarray:
    bg = bg_fn(grid)
    out = np.full_like(grid, bg)
    if direction in ('down', 'up'):
        for c in range(grid.shape[1]):
            values = grid[:, c][grid[:, c] != bg]
            start = grid.shape[0]-len(values) if direction == 'down' else 0
            out[start:start+len(values), c] = values
    else:
        for r in range(grid.shape[0]):
            values = grid[r][grid[r] != bg]
            start = grid.shape[1]-len(values) if direction == 'right' else 0
            out[r, start:start+len(values)] = values
    return out


def _object_gravity(grid: np.ndarray, bg_fn: Callable,
                    direction: str, monochrome: bool) -> np.ndarray:
    bg = bg_fn(grid)
    objs = _objects(grid, bg, False, monochrome)
    dr, dc = {'down': (1, 0), 'up': (-1, 0), 'right': (0, 1), 'left': (0, -1)}[direction]
    blocks = [[(r, c, int(grid[r, c])) for r, c in o['cells']] for o in objs]
    blocks.sort(key=lambda cells: max(dr*r+dc*c for r, c, _ in cells), reverse=True)
    out = grid.copy()
    h, w = grid.shape
    # Repeated sweeps handle interlocking outlines deterministically. Each
    # successful sweep strictly advances at least one finite object.
    for _ in range(h+w):
        moved = False
        for i, cells in enumerate(blocks):
            own = {(r, c) for r, c, _ in cells}
            distance = 0
            while True:
                d = distance+1
                if any(not (0 <= r+dr*d < h and 0 <= c+dc*d < w)
                       or ((r+dr*d, c+dc*d) not in own and out[r+dr*d, c+dc*d] != bg)
                       for r, c, _ in cells):
                    break
                distance = d
            if distance:
                for r, c, _ in cells:
                    out[r, c] = bg
                cells = [(r+dr*distance, c+dc*distance, color) for r, c, color in cells]
                for r, c, color in cells:
                    out[r, c] = color
                blocks[i] = cells
                moved = True
        if not moved:
            break
    return out


def _stamp_template(grid: np.ndarray, bg_fn: Callable, diagonal: bool) -> np.ndarray | None:
    """Copy a single multicolor template to isolated, uniquely colored anchors."""
    bg = bg_fn(grid)
    objs = _objects(grid, bg, diagonal, False)
    templates = [o for o in objs if o['size'] > 1]
    markers = [o for o in objs if o['size'] == 1]
    if len(templates) != 1 or not markers:
        return None
    template = templates[0]
    anchors: dict[int, list[tuple[int, int]]] = {}
    for r, c in template['cells']:
        anchors.setdefault(int(grid[r, c]), []).append((r, c))
    if len(anchors) < 2:
        return None
    out = grid.copy()
    h, w = grid.shape
    for marker in markers:
        mr, mc = marker['cells'][0]
        points = anchors.get(int(grid[mr, mc]), [])
        if len(points) != 1:
            return None
        ar, ac = points[0]
        for r, c in template['cells']:
            nr, nc = r+mr-ar, c+mc-ac
            if not (0 <= nr < h and 0 <= nc < w):
                return None
            color = int(grid[r, c])
            if out[nr, nc] not in (bg, color):
                return None
            out[nr, nc] = color
    return out


def _features(grid: np.ndarray, bg: int, diagonal: bool) -> tuple[dict, ...]:
    a = np.asarray(grid, dtype=np.int8)
    return _cached_features(a.shape, a.tobytes(), bg, diagonal)


@lru_cache(maxsize=192)
def _cached_features(shape: tuple[int, int], data: bytes, bg: int,
                     diagonal: bool) -> tuple[dict, ...]:
    grid = np.frombuffer(data, dtype=np.int8).reshape(shape)
    objs = _objects(grid, bg, diagonal, True)
    sizes = sorted({o['size'] for o in objs})
    widths = sorted({o['bbox'][3]-o['bbox'][1] for o in objs})
    heights = sorted({o['bbox'][2]-o['bbox'][0] for o in objs})
    shapes = [_shape(o, True) for o in objs]
    shape_counts = Counter(shapes)
    size_counts = Counter(o['size'] for o in objs)
    top_values = sorted({o['bbox'][0] for o in objs})
    left_values = sorted({o['bbox'][1] for o in objs})
    h, w = grid.shape
    result = []
    for obj, shape in zip(objs, shapes):
        r0, c0, r1, c1 = obj['bbox']
        cell_set = set(obj['cells'])
        adjacent = set()
        for r, c in obj['cells']:
            for a, b in ((r-1, c), (r+1, c), (r, c-1), (r, c+1)):
                if (0 <= a < h and 0 <= b < w and (a, b) not in cell_set
                        and grid[a, b] != bg):
                    adjacent.add(int(grid[a, b]))
        result.append({
            'color': int(obj['color']), 'area': obj['size'],
            'width': c1-c0, 'height': r1-r0,
            'bbox_area': (r1-r0)*(c1-c0),
            'solid': obj['size'] == (r1-r0)*(c1-c0),
            'area_rank': sizes.index(obj['size']),
            'area_rank_desc': len(sizes)-1-sizes.index(obj['size']),
            'width_rank': widths.index(c1-c0),
            'height_rank': heights.index(r1-r0),
            'top_rank': top_values.index(r0), 'left_rank': left_values.index(c0),
            'shape': shape, 'shape_count': shape_counts[shape],
            'size_count': size_counts[obj['size']],
            'holes': _holes(obj),
            'border': r0 == 0 or c0 == 0 or r1 == h or c1 == w,
            'adjacent_colors': tuple(sorted(adjacent)),
            'adjacent_count': len(adjacent),
        })
    return tuple(result)


def _fit_recolor(train: list[dict], bg_fn: Callable, diagonal: bool,
                  name_prefix: str, deadline: float | None) -> list[Rule]:
    observations = []
    changed = False
    for example in train:
        x, y = np.asarray(example['input']), np.asarray(example['output'])
        if x.shape != y.shape:
            return []
        bg = bg_fn(x)
        if np.any(y[x == bg] != bg):
            return []
        objs = _objects(x, bg, diagonal, True)
        features = _features(x, bg, diagonal)
        for obj, values in zip(objs, features):
            colors = {int(y[r, c]) for r, c in obj['cells']}
            if len(colors) != 1:
                return []
            target = next(iter(colors))
            changed |= target != int(obj['color'])
            observations.append((values, target))
    if not changed or not observations:
        return []
    names = tuple(observations[0][0])
    feature_sets = [(name,) for name in names]
    feature_sets += [('color', name) for name in names if name != 'color']
    feature_sets += [('border', 'solid'), ('area_rank', 'shape_count'),
                     ('holes', 'border'), ('width_rank', 'height_rank')]
    rules = []
    for fields in feature_sets:
        if _expired(deadline):
            break
        mapping = {}
        conflict = False
        for values, target in observations:
            key = tuple(values[n] for n in fields)
            if key in mapping and mapping[key] != target:
                conflict = True
                break
            mapping[key] = target
        if conflict:
            continue

        def repaint(grid, fields=fields, mapping=dict(mapping), bg_fn=bg_fn,
                    diagonal=diagonal):
            bg = bg_fn(grid)
            objs = _objects(grid, bg, diagonal, True)
            feats = _features(grid, bg, diagonal)
            out = grid.copy()
            for obj, values in zip(objs, feats):
                target = mapping.get(tuple(values[n] for n in fields), int(obj['color']))
                for r, c in obj['cells']:
                    out[r, c] = target
            return out

        # The fitter never sees held-out test outputs. Validate its own entire
        # training transformation, including cells outside the chosen objects.
        if all(np.array_equal(repaint(np.asarray(e['input'])), np.asarray(e['output']))
               for e in train):
            cost = 1.7+0.2*len(fields)+0.12*len(mapping)
            if 'shape' in fields:
                cost += 1.0  # literal shape tables are less general than ranks
            rules.append(Rule(f'{name_prefix}:recolor:{"+".join(fields)}', repaint,
                              cost=cost, family='object_recolor'))
    return rules


def object_rules(train: list[dict], deadline: float | None = None) -> list[Rule]:
    """Return a bounded family of pure object transformations.

    Static operations are candidates for composition, so they need not themselves
    fit the examples. Object recoloring rules, in contrast, are fitted from all
    examples and validated here. A missed deadline returns the completed prefix.
    """
    if not train or _expired(deadline):
        return []
    bg_options = [('zero', _zero_background), ('mode', _mode_background)]
    rules: list[Rule] = []
    for bg_name, bg_fn in bg_options:
        if _expired(deadline):
            break
        for direction in ('down', 'up', 'left', 'right'):
            rules.append(Rule(
                f'objects:{bg_name}:pixel_gravity:{direction}',
                lambda g, bf=bg_fn, d=direction: _pixel_gravity(g, bf, d),
                cost=1.3, family='gravity'))
            for mono in (True, False):
                rules.append(Rule(
                    f'objects:{bg_name}:object_gravity:{direction}:mono{int(mono)}',
                    lambda g, bf=bg_fn, d=direction, m=mono: _object_gravity(g, bf, d, m),
                    cost=1.7, family='gravity'))
        for diagonal in (False, True):
            if _expired(deadline):
                break
            prefix = f'objects:{bg_name}:{8 if diagonal else 4}'
            for mode in ('rectangle', 'box_outline', 'outline', 'fill_holes'):
                rules.append(Rule(
                    f'{prefix}:{mode}',
                    lambda g, bf=bg_fn, d=diagonal, m=mode: _paint(g, bf, d, m),
                    cost=1.5, family='object_paint'))
            rules.append(Rule(
                f'{prefix}:stamp_template',
                lambda g, bf=bg_fn, d=diagonal: _stamp_template(g, bf, d),
                cost=2.0, family='object_copy'))
            rules.extend(_fit_recolor(train, bg_fn, diagonal, prefix, deadline))
            for monochrome in (True, False):
                if _expired(deadline):
                    break
                label = f'{prefix}:mono{int(monochrome)}'
                criteria = ['largest', 'smallest', 'largest_box', 'smallest_box',
                            'widest', 'tallest', 'unique_shape', 'repeated_shape']
                if monochrome:
                    criteria.append('most_holes')
                else:
                    criteria.append('most_colors')
                for criterion in criteria:
                    rules.append(Rule(
                        f'{label}:crop:{criterion}',
                        lambda g, bf=bg_fn, d=diagonal, m=monochrome, c=criterion:
                            _selection(g, bf, d, m, c),
                        cost=1.4, family='object_select'))
                # Bounding-box extraction keeps all enclosed colored cells;
                # masked extraction above keeps only the selected component.
                rules.append(Rule(
                    f'{label}:crop_bbox:largest',
                    lambda g, bf=bg_fn, d=diagonal, m=monochrome:
                        _selection(g, bf, d, m, 'largest', masked=False),
                    cost=1.4, family='object_select'))
                for criterion in ('largest', 'smallest', 'non_singletons', 'unique_size',
                                  'repeated_shape', 'unique_shape', 'border', 'interior'):
                    rules.append(Rule(
                        f'{label}:keep:{criterion}',
                        lambda g, bf=bg_fn, d=diagonal, m=monochrome, c=criterion:
                            _filter(g, bf, d, m, c),
                        cost=1.5, family='object_filter'))
    return rules

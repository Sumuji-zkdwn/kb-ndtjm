"""Small, train-only families for local, periodic, and panel reasoning.

These are hypothesis generators, not a catalogue of ARC task IDs.  Every emitted
rule reproduces every demonstration exactly.  This is an empirical consistency
check, not a claim that the rule will generalize to the test input.
"""

from __future__ import annotations

from collections import Counter
from itertools import product
import math
import time
from typing import Callable

import numpy as np

from .types import Rule


def _bg(g: np.ndarray, selector: int | str) -> int:
    if selector == "mode":
        return int(np.bincount(g.ravel(), minlength=10).argmax())
    return int(selector)


def _valid(g: object) -> bool:
    return (
        isinstance(g, np.ndarray)
        and g.ndim == 2
        and 0 < g.shape[0] <= 30
        and 0 < g.shape[1] <= 30
        and np.issubdtype(g.dtype, np.integer)
        and bool(np.all((g >= 0) & (g <= 9)))
    )


def _symmetry_complete(g: np.ndarray, mask: int, group: str) -> np.ndarray | None:
    transforms: list[np.ndarray] = [g]
    if group == "h":
        transforms += [np.fliplr(g)]
    elif group == "v":
        transforms += [np.flipud(g)]
    elif group == "r2":
        transforms += [np.rot90(g, 2)]
    elif group == "hv":
        transforms += [np.fliplr(g), np.flipud(g), np.rot90(g, 2)]
    elif group in {"d", "a", "r4", "d4"}:
        if g.shape[0] != g.shape[1]:
            return None
        if group == "d":
            transforms += [g.T]
        elif group == "a":
            transforms += [np.rot90(g.T, 2)]
        else:
            transforms = [np.rot90(g, k) for k in range(4)]
            if group == "d4":
                transforms += [np.rot90(g.T, k) for k in range(4)]
    out = g.copy()
    known = out != mask
    for other in transforms[1:]:
        usable = other != mask
        if np.any(known & usable & (out != other)):
            return None
        take = ~known & usable
        out[take] = other[take]
        known |= usable
    return out


def _period_complete(
    g: np.ndarray, mask: int, period_r: int | None, period_c: int | None
) -> np.ndarray | None:
    h, w = g.shape
    pr, pc = period_r or h, period_c or w
    if pr > h or pc > w:
        return None
    rr, cc = np.indices(g.shape)
    codes = (rr % pr) * pc + cc % pc
    tile = np.full(pr * pc, -1, dtype=np.int16)
    known = g != mask
    for color in np.unique(g[known]):
        indices = np.unique(codes[known & (g == color)])
        if np.any((tile[indices] >= 0) & (tile[indices] != color)):
            return None
        tile[indices] = color
    fill = tile[codes]
    if np.any((~known) & (fill < 0)):
        return None
    return np.where(known, g, fill).astype(np.int16)


def _split_equal(
    g: np.ndarray, axis: int, n: int, gap: int
) -> list[np.ndarray] | None:
    length = g.shape[axis]
    usable = length - gap * (n - 1)
    if usable <= 0 or usable % n:
        return None
    size = usable // n
    result = []
    for i in range(n):
        start = i * (size + gap)
        panel = g[start : start + size, :] if axis == 0 else g[:, start : start + size]
        result.append(panel)
        if i < n - 1 and gap:
            line = g[start + size : start + size + gap, :] if axis == 0 else g[:, start + size : start + size + gap]
            if not np.all(line == line.flat[0]):
                return None
    return result


def _split_separators(g: np.ndarray, color: int) -> list[np.ndarray] | None:
    row_lines = np.flatnonzero(np.all(g == color, axis=1))
    col_lines = np.flatnonzero(np.all(g == color, axis=0))
    if not len(row_lines) and not len(col_lines):
        return None

    def spans(length: int, lines: np.ndarray) -> list[tuple[int, int]]:
        blocked = set(map(int, lines))
        out = []
        start = 0
        for i in range(length + 1):
            if i == length or i in blocked:
                if i > start:
                    out.append((start, i))
                start = i + 1
        return out

    rows, cols = spans(g.shape[0], row_lines), spans(g.shape[1], col_lines)
    panels = [g[a:b, c:d] for a, b in rows for c, d in cols]
    if not 2 <= len(panels) <= 16 or len({x.shape for x in panels}) != 1:
        return None
    return panels


def _panel_overlay(
    panels: list[np.ndarray], bg: int, operation: str
) -> np.ndarray:
    stack = np.stack(panels)
    if operation in {"first", "last"}:
        out = np.full(panels[0].shape, bg, dtype=np.int16)
        sequence = reversed(panels) if operation == "first" else panels
        for panel in sequence:
            np.copyto(out, panel, where=panel != bg)
        return out
    nonbg = stack != bg
    if operation == "consensus":
        present = np.any(nonbg, axis=0)
        lo = np.min(np.where(nonbg, stack, 10), axis=0)
        hi = np.max(np.where(nonbg, stack, -1), axis=0)
        return np.where(present & (lo == hi), lo, bg).astype(np.int16)
    raise ValueError(operation)


def _panel_codes(panels: list[np.ndarray], bg: int, mode: str) -> np.ndarray:
    stack = np.stack(panels)
    if mode == "count":
        return np.count_nonzero(stack != bg, axis=0)
    if mode == "bits":
        codes = np.zeros(panels[0].shape, dtype=np.int64)
        for i, p in enumerate(panels):
            codes += (p != bg).astype(np.int64) << i
        return codes
    # Color tuple coding distinguishes overlapping source colors without using
    # task identifiers or memorizing spatial coordinates.
    codes = np.zeros(panels[0].shape, dtype=np.int64)
    for p in panels:
        codes = codes * 10 + p
    return codes


def _learn_map(xs: list[np.ndarray], ys: list[np.ndarray]) -> dict[int, int] | None:
    mapping: dict[int, int] = {}
    for x, y in zip(xs, ys):
        for code in np.unique(x):
            values = np.unique(y[x == code])
            if len(values) != 1:
                return None
            key, value = int(code), int(values[0])
            if key in mapping and mapping[key] != value:
                return None
            mapping[key] = value
    return mapping


def _paint_lines(
    g: np.ndarray,
    bg_selector: int | str,
    marker: int | str,
    paint: int | str,
    directions: tuple[tuple[int, int], ...],
    extend: bool,
) -> np.ndarray:
    bg = _bg(g, bg_selector)
    colors = [int(x) for x in np.unique(g) if x != bg] if marker == "each" else [int(marker)]
    out = g.copy()
    h, w = g.shape
    for color in colors:
        draw = color if paint == "marker" else int(paint)
        positions = np.argwhere(g == color)
        for dr, dc in directions:
            groups: dict[int, list[tuple[int, int]]] = {}
            for r, c in positions:
                invariant = int(c * dr - r * dc)
                groups.setdefault(invariant, []).append((int(r), int(c)))
            for points in groups.values():
                if not extend and len(points) < 2:
                    continue
                points.sort(key=lambda p: p[0] * dr + p[1] * dc)
                r, c = points[0]
                er, ec = points[-1]
                if extend:
                    while 0 <= r - dr < h and 0 <= c - dc < w:
                        r, c = r - dr, c - dc
                    while 0 <= er + dr < h and 0 <= ec + dc < w:
                        er, ec = er + dr, ec + dc
                while True:
                    if g[r, c] == bg:
                        out[r, c] = draw
                    if r == er and c == ec:
                        break
                    r, c = r + dr, c + dc
    return out


def _features(g: np.ndarray, selector: int | str) -> dict[str, tuple[np.ndarray, ...]]:
    """Vectorized context features; no absolute coordinates or output labels."""
    bg = _bg(g, selector)
    h, w = g.shape
    pad = np.pad(g, 1, constant_values=10)
    shifts = [
        pad[1 + dr : h + 1 + dr, 1 + dc : w + 1 + dc]
        for dr, dc in [(-1, 0), (0, 1), (1, 0), (0, -1), (-1, -1), (-1, 1), (1, 1), (1, -1)]
    ]
    count4 = sum(((x != bg) & (x != 10)).astype(np.int16) for x in shifts[:4])
    count8 = sum(((x != bg) & (x != 10)).astype(np.int16) for x in shifts)
    same4 = sum((x == g).astype(np.int16) for x in shifts[:4])
    same8 = sum((x == g).astype(np.int16) for x in shifts)
    row_n = np.broadcast_to(np.count_nonzero(g != bg, axis=1)[:, None], g.shape)
    col_n = np.broadcast_to(np.count_nonzero(g != bg, axis=0)[None, :], g.shape)
    row_colors = np.zeros(g.shape, dtype=np.int64)
    col_colors = np.zeros(g.shape, dtype=np.int64)
    row_same = np.zeros(g.shape, dtype=np.int16)
    col_same = np.zeros(g.shape, dtype=np.int16)
    freq = np.bincount(g.ravel(), minlength=10)
    rank = np.array([np.count_nonzero(freq > freq[c]) for c in range(10)], dtype=np.int16)
    for color in np.unique(g):
        has = g == color
        row_colors |= np.any(has, axis=1)[:, None].astype(np.int64) << int(color)
        col_colors |= np.any(has, axis=0)[None, :].astype(np.int64) << int(color)
        row_same[has] = np.broadcast_to(np.sum(has, axis=1)[:, None], g.shape)[has]
        col_same[has] = np.broadcast_to(np.sum(has, axis=0)[None, :], g.shape)[has]
    result = {
        "color": (g,),
        "count4": (g, count4),
        "count8": (g, count8),
        "same4": (g, same4),
        "same8": (g, same8),
        "counts": (g, count4, count8),
        "same_counts": (g, same4, same8),
        "row_count": (g, row_n),
        "col_count": (g, col_n),
        "cross_counts": (g, row_n, col_n),
        "row_same": (g, row_same),
        "col_same": (g, col_same),
        "cross_same": (g, row_same, col_same),
        "row_colors": (g, row_colors),
        "col_colors": (g, col_colors),
        "cross_colors": (g, row_colors, col_colors),
        "color_rank": (g, rank[g]),
        "vertical": (g, shifts[0], shifts[2]),
        "horizontal": (g, shifts[1], shifts[3]),
        "cross": (g, *shifts[:4]),
        "patch": (g, *shifts),
    }
    # Rotation-invariant neighbor color counts are deliberately separate from
    # ordered patches, since their inductive bias and complexity differ.
    present = [int(c) for c in np.unique(g)]
    # Always use all ten color bins so feature identities remain stable when a
    # color is absent from one demonstration or the unseen input.
    del present
    result["hist4"] = (g, *(sum((x == c).astype(np.int16) for x in shifts[:4]) for c in range(10)))
    result["hist8"] = (g, *(sum((x == c).astype(np.int16) for x in shifts) for c in range(10)))
    return result


def _feature_rows(arrays: tuple[np.ndarray, ...]) -> np.ndarray:
    return np.stack([a.ravel() for a in arrays], axis=1)


def _local_map(
    g: np.ndarray, selector: int | str, feature: str, mapping: dict[tuple[int, ...], int]
) -> np.ndarray:
    rows = _feature_rows(_features(g, selector)[feature])
    values = np.fromiter(
        (mapping.get(tuple(map(int, row)), int(center)) for row, center in zip(rows, g.ravel())),
        dtype=np.int16,
        count=g.size,
    )
    return values.reshape(g.shape)


def pattern_rules(train: list[dict], deadline: float | None = None) -> list[Rule]:
    """Infer bounded rule families from demonstrations, with no test-label access.

    ``deadline`` is an absolute ``time.monotonic()`` value.  This component uses
    at most roughly 0.75 seconds even if the outer search has a larger budget;
    one NumPy operation already in progress can finish after the deadline.
    """
    if not train:
        return []
    started = time.monotonic()
    stop = min(deadline if deadline is not None else math.inf, started + 0.75)
    pairs = [(np.asarray(p["input"], dtype=np.int16), np.asarray(p["output"], dtype=np.int16)) for p in train]
    if not all(_valid(x) and _valid(y) for x, y in pairs):
        return []
    xs, ys = [x for x, _ in pairs], [y for _, y in pairs]
    same_shape = all(x.shape == y.shape for x, y in pairs)
    rules: list[Rule] = []
    names: set[str] = set()

    def expired() -> bool:
        return time.monotonic() >= stop

    def add(name: str, fn: Callable, cost: float, family: str) -> None:
        if expired() or len(rules) >= 96 or name in names:
            return
        try:
            for x, y in pairs:
                predicted = fn(x)
                if not _valid(predicted) or not np.array_equal(predicted, y):
                    return
        except (ValueError, IndexError, TypeError, OverflowError):
            return
        names.add(name)
        rules.append(Rule(name=name, fn=fn, cost=cost, family=family))

    common_input_colors = sorted(set.intersection(*(set(map(int, np.unique(x))) for x in xs)))
    backgrounds: list[int | str] = [0, "mode"]
    for c in common_input_colors:
        if c != 0 and all(np.mean(x == c) >= 0.25 for x in xs):
            backgrounds.append(c)

    # Panels are considered first because a dimension reduction is informative
    # and makes expensive same-size local models irrelevant.
    splitters: list[tuple[str, Callable]] = []
    if not same_shape:
        for axis, n, gap in product((0, 1), range(2, 5), (0, 1)):
            fn = lambda g, a=axis, n=n, gap=gap: _split_equal(g, a, n, gap)
            panels = [fn(x) for x in xs]
            if all(p is not None and p[0].shape == y.shape for p, y in zip(panels, ys)):
                splitters.append((f"equal{axis}:{n}:{gap}", fn))
        for color in common_input_colors:
            fn = lambda g, c=color: _split_separators(g, c)
            panels = [fn(x) for x in xs]
            if all(p is not None and p[0].shape == y.shape for p, y in zip(panels, ys)):
                splitters.append((f"separator:{color}", fn))
    for label, split in splitters:
        if expired():
            return rules
        training_panels = [split(x) for x in xs]
        for selector in backgrounds:
            for operation in ("first", "last", "consensus"):
                def overlay(g, sp=split, s=selector, op=operation):
                    ps = sp(g)
                    return None if ps is None else _panel_overlay(ps, _bg(g, s), op)
                add(f"panel:{label}:bg{selector}:{operation}", overlay, 2.0, "panels")
            for mode in ("count", "bits", "colors"):
                if mode == "colors" and max(len(p) for p in training_panels) > 8:
                    continue
                codes = [_panel_codes(p, _bg(x, selector), mode) for p, x in zip(training_panels, xs)]
                mapping = _learn_map(codes, ys)
                if mapping is None:
                    continue
                def mapped(g, sp=split, s=selector, mode=mode, mapping=mapping):
                    ps = sp(g)
                    if ps is None or (mode == "colors" and len(ps) > 8):
                        return None
                    bg = _bg(g, s)
                    code = _panel_codes(ps, bg, mode)
                    out = np.full(code.shape, bg, dtype=np.int16)
                    for k, value in mapping.items():
                        out[code == k] = value
                    return out
                cost = 2.1 + 0.12 * len(mapping) + (0.8 if mode == "colors" else 0)
                add(f"panel:{label}:bg{selector}:{mode}", mapped, cost, "panels")

    if not same_shape or expired():
        return rules

    mask_colors = [c for c in common_input_colors if any(np.any((x == c) & (x != y)) for x, y in pairs)]
    for mask in mask_colors:
        for group in ("h", "v", "r2", "hv", "d", "a", "r4", "d4"):
            add(f"complete:{group}:mask{mask}", lambda g, m=mask, s=group: _symmetry_complete(g, m, s), 1.6 + 0.1 * len(group), "symmetry")
        if expired():
            return rules
        row_periods: list[int | None] = [None]
        col_periods: list[int | None] = [None]
        for p in range(1, min(12, min(y.shape[0] for y in ys)) + 1):
            if all(np.array_equal(y[p:], y[:-p]) for y in ys) and any(p < y.shape[0] for y in ys):
                row_periods.append(p)
        for p in range(1, min(12, min(y.shape[1] for y in ys)) + 1):
            if all(np.array_equal(y[:, p:], y[:, :-p]) for y in ys) and any(p < y.shape[1] for y in ys):
                col_periods.append(p)
        periods = [(pr, pc) for pr, pc in product(row_periods, col_periods) if pr is not None or pc is not None]
        periods.sort(key=lambda pair: ((pair[0] or 31) * (pair[1] or 31), str(pair)))
        for pr, pc in periods[:16]:
            add(f"period:{pr}:{pc}:mask{mask}", lambda g, m=mask, r=pr, c=pc: _period_complete(g, m, r, c), 2.0 + 0.03 * ((pr or 1) + (pc or 1)), "periodic")

    # Draw through markers while preserving all non-background input pixels.
    changed_colors = sorted(set.intersection(*(set(map(int, np.unique(y[x != y]))) for x, y in pairs)))
    markers: list[int | str] = ["each", *common_input_colors]
    directions = [((0, 1),), ((1, 0),), ((0, 1), (1, 0)), ((1, 1),), ((1, -1),), ((1, 1), (1, -1))]
    for selector in backgrounds[:2]:
        # A line painter cannot recolor an occupied input cell.
        if any(np.any((x != _bg(x, selector)) & (x != y)) for x, y in pairs):
            continue
        for marker in markers:
            if marker != "each" and all(marker == _bg(x, selector) for x in xs):
                continue
            for paint in ["marker", *changed_colors[:3]]:
                for ds, extend in product(directions, (False, True)):
                    if expired():
                        return rules
                    add(
                        f"line:bg{selector}:mark{marker}:paint{paint}:{ds}:extend{extend}",
                        lambda g, s=selector, m=marker, p=paint, d=ds, e=extend: _paint_lines(g, s, m, p, d, e),
                        2.3 + 0.2 * len(ds) + 0.3 * extend,
                        "lines",
                    )

    # Learn context-to-color maps.  Unknown contexts retain their input color.
    # All unchanged pixels also constrain the map, preventing a changed-pixel
    # rule from being accepted if it damages an unchanged demonstration cell.
    for selector in backgrounds[:2]:
        if expired():
            return rules
        prepared = [_features(x, selector) for x in xs]
        for feature in prepared[0]:
            if expired():
                return rules
            mapping: dict[tuple[int, ...], int] = {}
            counts: Counter = Counter()
            consistent = True
            for f, y in zip(prepared, ys):
                for row, value in zip(_feature_rows(f[feature]), y.ravel()):
                    key, value = tuple(map(int, row)), int(value)
                    if key in mapping and mapping[key] != value:
                        consistent = False
                        break
                    mapping[key] = value
                    counts[key] += 1
                if not consistent:
                    break
            if not consistent:
                continue
            changes = {k: v for k, v in mapping.items() if k[0] != v}
            if not changes:
                continue
            sparse = sum(counts[k] == 1 for k in changes)
            cost = 2.0 + 0.35 * len(prepared[0][feature]) + 0.08 * len(changes) + 0.15 * sparse
            add(
                f"local:bg{selector}:{feature}",
                lambda g, s=selector, f=feature, m=changes: _local_map(g, s, f, m),
                cost,
                "local",
            )
    return rules

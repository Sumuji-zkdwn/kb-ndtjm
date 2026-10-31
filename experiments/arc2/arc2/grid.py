from __future__ import annotations

from collections import deque

import numpy as np


def valid_grid(value) -> bool:
    try:
        a = np.asarray(value)
        return bool(
            a.ndim == 2 and 1 <= a.shape[0] <= 30 and 1 <= a.shape[1] <= 30
            and a.dtype.kind in "iu" and np.all((a >= 0) & (a <= 9))
        )
    except (ValueError, TypeError):
        return False


def as_grid(value) -> np.ndarray:
    if not valid_grid(value):
        raise ValueError("Grid must be a rectangular 1..30 by 1..30 array of integers 0..9")
    return np.array(value, dtype=np.uint8, copy=True)


def key(grid: np.ndarray) -> bytes:
    a = np.asarray(grid, dtype=np.uint8)
    return bytes(a.shape) + a.tobytes(order="C")


def background(grid: np.ndarray) -> int:
    counts = np.bincount(np.asarray(grid).ravel(), minlength=10)
    return int(np.argmax(counts))


def crop(grid: np.ndarray, bg: int = 0) -> np.ndarray | None:
    rows, cols = np.where(grid != bg)
    if len(rows) == 0:
        return None
    return grid[rows.min():rows.max() + 1, cols.min():cols.max() + 1].copy()


def components(grid: np.ndarray, bg: int = 0, diagonal: bool = False,
               monochrome: bool = True) -> list[dict]:
    """Connected foreground components with exclusive-end bounding boxes."""
    h, w = grid.shape
    seen = np.zeros((h, w), dtype=bool)
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    if diagonal:
        directions += ((1, 1), (1, -1), (-1, 1), (-1, -1))
    objects = []
    for r, c in np.argwhere(grid != bg):
        r, c = int(r), int(c)
        if seen[r, c]:
            continue
        color = int(grid[r, c])
        todo = deque([(r, c)])
        seen[r, c] = True
        cells = []
        while todo:
            y, x = todo.popleft()
            cells.append((y, x))
            for dy, dx in directions:
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w and not seen[yy, xx]:
                    if grid[yy, xx] != bg and (not monochrome or grid[yy, xx] == color):
                        seen[yy, xx] = True
                        todo.append((yy, xx))
        ys, xs = zip(*cells)
        if not monochrome:
            color = int(np.bincount([int(grid[y, x]) for y, x in cells], minlength=10).argmax())
        objects.append({"cells": cells, "color": color, "size": len(cells),
                        "bbox": (min(ys), min(xs), max(ys) + 1, max(xs) + 1)})
    return objects

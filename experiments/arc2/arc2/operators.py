"""Small, composable grid operators; parameters come only from demonstrations."""
from __future__ import annotations

import numpy as np

from .grid import background, crop
from .types import Rule


def _bg(a, color):
    return background(a) if color == -1 else color


def _crop_color(a, color):
    yy, xx = np.where(a == color)
    return None if not len(yy) else a[yy.min():yy.max()+1, xx.min():xx.max()+1].copy()


def _remove_lines(a, color, axis):
    if axis == 0:
        return a[~np.all(a == color, axis=1)].copy()
    return a[:, ~np.all(a == color, axis=0)].copy()


def _compress(a, axis):
    if axis == 0:
        keep = np.r_[True, np.any(a[1:] != a[:-1], axis=1)]
        return a[keep].copy()
    keep = np.r_[True, np.any(a[:, 1:] != a[:, :-1], axis=0)]
    return a[:, keep].copy()


def _downscale(a, fy, fx, mode):
    h, w = a.shape
    if h % fy or w % fx:
        return None
    blocks = a.reshape(h // fy, fy, w // fx, fx).transpose(0, 2, 1, 3)
    if mode == "first":
        return blocks[:, :, 0, 0].copy()
    if mode == "uniform":
        first = blocks[:, :, :1, :1]
        return blocks[:, :, 0, 0].copy() if np.all(blocks == first) else None
    out = np.zeros((h // fy, w // fx), dtype=np.uint8)
    for y in range(out.shape[0]):
        for x in range(out.shape[1]):
            counts = np.bincount(blocks[y, x].ravel(), minlength=10)
            if mode == "nonzero":
                counts[0] = 0
            out[y, x] = int(counts.argmax())
    return out


def _shift(a, dy, dx, color):
    h, w = a.shape
    out = np.full_like(a, _bg(a, color))
    sy0, sy1 = max(0, -dy), min(h, h-dy)
    sx0, sx1 = max(0, -dx), min(w, w-dx)
    if sy1 > sy0 and sx1 > sx0:
        out[sy0+dy:sy1+dy, sx0+dx:sx1+dx] = a[sy0:sy1, sx0:sx1]
    return out


def _window(a, h, w, anchor):
    if h > a.shape[0] or w > a.shape[1]:
        return None
    ay, ax = anchor
    r = (a.shape[0]-h) * ay // 2
    c = (a.shape[1]-w) * ax // 2
    return a[r:r+h, c:c+w].copy()


def _resize_canvas(a, dy, dx, anchor, color):
    h, w = a.shape[0]+dy, a.shape[1]+dx
    if not (1 <= h <= 30 and 1 <= w <= 30):
        return None
    if dy < 0 or dx < 0:
        return _window(a, h, w, anchor) if dy <= 0 and dx <= 0 else None
    out = np.full((h, w), _bg(a, color), dtype=np.uint8)
    y, x = dy * anchor[0]//2, dx * anchor[1]//2
    out[y:y+a.shape[0], x:x+a.shape[1]] = a
    return out


def _minimal_tile(a):
    h, w = a.shape
    for hh in range(1, h+1):
        if h % hh:
            continue
        for ww in range(1, w+1):
            if w % ww:
                continue
            b = a[:hh, :ww]
            if np.array_equal(np.tile(b, (h//hh, w//ww)), a):
                return b.copy()
    return a.copy()


def _color_rank(a, reverse=False):
    counts = np.bincount(a.ravel(), minlength=10)
    present = [i for i in range(10) if counts[i]]
    present.sort(key=lambda x: ((-1 if reverse else 1)*int(counts[x]), x))
    lut = np.arange(10, dtype=np.uint8)
    for rank, color in enumerate(present):
        lut[color] = rank
    return lut[a]


def _summary(a, axis, bg):
    b = a if axis == 0 else a.T
    colors = []
    for row in b:
        vals = np.unique(row[row != _bg(a, bg)])
        if len(vals) > 1:
            return None
        colors.append(int(vals[0]) if len(vals) else _bg(a, bg))
    out = np.asarray(colors, dtype=np.uint8).reshape(-1, 1)
    return out if axis == 0 else out.T


def primitive_rules(train):
    ins = [np.asarray(p["input"], dtype=np.uint8) for p in train]
    outs = [np.asarray(p["output"], dtype=np.uint8) for p in train]
    palette = sorted(set(int(c) for a in ins for c in np.unique(a)))
    rules = [
        Rule("rotate90", lambda a: np.rot90(a).copy(), 1, "geometry"),
        Rule("rotate180", lambda a: np.rot90(a, 2).copy(), 1, "geometry"),
        Rule("rotate270", lambda a: np.rot90(a, 3).copy(), 1, "geometry"),
        Rule("flip_vertical", lambda a: a[::-1].copy(), 1, "geometry"),
        Rule("flip_horizontal", lambda a: a[:, ::-1].copy(), 1, "geometry"),
        Rule("transpose", lambda a: a.T.copy(), 1, "geometry"),
        Rule("anti_transpose", lambda a: a.T[::-1, ::-1].copy(), 1, "geometry"),
        Rule("compress_rows", lambda a: _compress(a, 0), 1.4, "compression"),
        Rule("compress_columns", lambda a: _compress(a, 1), 1.4, "compression"),
        Rule("compress_rows_columns", lambda a: _compress(_compress(a, 0), 1), 2, "compression"),
        Rule("minimal_tile", _minimal_tile, 2, "periodicity"),
        Rule("color_rank_ascending", lambda a: _color_rank(a, False), 2.5, "color_rank"),
        Rule("color_rank_descending", lambda a: _color_rank(a, True), 2.5, "color_rank"),
    ]
    for color in [-1] + palette:
        label = "dominant" if color == -1 else str(color)
        rules.append(Rule(f"crop_background_{label}", lambda a, c=color: crop(a, _bg(a,c)), 1.2, "crop"))
        if color >= 0:
            rules.append(Rule(f"crop_color_{color}", lambda a, c=color: _crop_color(a,c), 1.4, "crop"))
            rules.append(Rule(f"mask_color_{color}", lambda a, c=color: (a == c).astype(np.uint8), 1.8, "mask"))
            rules.append(Rule(f"erase_color_{color}", lambda a, c=color: np.where(a == c,0,a), 1.5, "color"))
        for axis in (0,1):
            rules.append(Rule(f"remove_uniform_{axis}_{label}", lambda a,c=color,ax=axis: _remove_lines(a,_bg(a,c),ax), 1.5, "compression"))
            rules.append(Rule(f"summarize_{axis}_{label}", lambda a,c=color,ax=axis: _summary(a,ax,c), 2, "summary"))

    # Spatial operations include generic factors, plus ratios supported by all pairs.
    factors = {(2,2), (3,3), (2,1), (1,2), (3,1), (1,3)}
    if ins:
        for a,b in zip(ins,outs):
            if b.shape[0] % a.shape[0] == 0 and b.shape[1] % a.shape[1] == 0:
                fy,fx = b.shape[0]//a.shape[0], b.shape[1]//a.shape[1]
                if 1 <= fy <= 10 and 1 <= fx <= 10 and (fy,fx) != (1,1): factors.add((fy,fx))
    for fy,fx in sorted(factors):
        rules.append(Rule(f"scale_{fy}_{fx}", lambda a,y=fy,x=fx: np.repeat(np.repeat(a,y,axis=0),x,axis=1) if a.shape[0]*y <= 30 and a.shape[1]*x <= 30 else None, 1.5 + .05*(fy+fx), "scale"))
        rules.append(Rule(f"tile_{fy}_{fx}", lambda a,y=fy,x=fx: np.tile(a,(y,x)) if a.shape[0]*y <= 30 and a.shape[1]*x <= 30 else None, 1.8, "tile"))
    down = {(2,2),(3,3),(2,1),(1,2)}
    for a,b in zip(ins,outs):
        if a.shape[0] % b.shape[0] == 0 and a.shape[1] % b.shape[1] == 0:
            y,x = a.shape[0]//b.shape[0],a.shape[1]//b.shape[1]
            if (y,x) != (1,1): down.add((y,x))
    for fy,fx in sorted(down):
        for mode in ("uniform","first","mode","nonzero"):
            rules.append(Rule(f"downscale_{fy}_{fx}_{mode}", lambda a,y=fy,x=fx,m=mode: _downscale(a,y,x,m), 1.8 if mode == "uniform" else 2.4, "scale"))
    for axis in (0,1):
        for reverse in (False,True):
            for flip_axis in (0,1):
                def mirror(a,ax=axis,rev=reverse,fl=flip_axis):
                    if a.shape[ax]*2 > 30: return None
                    b=np.flip(a,axis=fl)
                    return np.concatenate((b,a) if rev else (a,b),axis=ax)
                rules.append(Rule(f"mirror_tile_{axis}_{int(reverse)}_{flip_axis}",mirror,1.8,"symmetry"))
    for bg in (0,-1):
        def kron(a,c=bg,reverse=False):
            if a.shape[0]**2 > 30 or a.shape[1]**2 > 30: return None
            mask=(a != _bg(a,c)).astype(np.uint8)
            return np.kron(a,mask) if reverse else np.kron(mask,a)
        rules.append(Rule(f"self_tile_{bg}",kron,2.8,"fractal"))
        rules.append(Rule(f"self_tile_reverse_{bg}",lambda a,c=bg: kron(a,c,True),2.8,"fractal"))

    deltas = set()
    if ins:
        ds = {(b.shape[0]-a.shape[0],b.shape[1]-a.shape[1]) for a,b in zip(ins,outs)}
        if len(ds) == 1 and ds != {(0,0)}: deltas |= ds
    for dy,dx in sorted(deltas):
        for anchor in ((0,0),(0,2),(2,0),(2,2),(1,1)):
            for bg in (0,-1):
                rules.append(Rule(f"canvas_{dy}_{dx}_{anchor}_{bg}",lambda a,y=dy,x=dx,an=anchor,c=bg: _resize_canvas(a,y,x,an,c),2.2,"canvas"))
    shapes = set(b.shape for b in outs)
    if len(shapes)==1:
        h,w=next(iter(shapes))
        for anchor in ((0,0),(0,2),(2,0),(2,2),(1,1)):
            rules.append(Rule(f"window_{h}_{w}_{anchor}",lambda a,hh=h,ww=w,an=anchor:_window(a,hh,ww,an),2.4,"crop"))
    if ins and all(a.shape==b.shape for a,b in zip(ins,outs)):
        shifts={(dy,dx) for dy,dx in ((-1,0),(1,0),(0,-1),(0,1),(-2,0),(2,0),(0,-2),(0,2))}
        for a,b in zip(ins,outs):
            for bg in (0,background(a)):
                y,x=np.where(a!=bg); yy,xx=np.where(b!=bg)
                if len(y) and len(yy):
                    shifts.add((int(yy.min()-y.min()),int(xx.min()-x.min())))
        for dy,dx in sorted(shifts-{(0,0)}):
            if abs(dy)<30 and abs(dx)<30:
                rules.append(Rule(f"shift_{dy}_{dx}",lambda a,y=dy,x=dx:_shift(a,y,x,0),2+0.04*(abs(dy)+abs(dx)),"translation"))
    return rules


def constant_rule(train):
    outputs = [np.asarray(p["output"],dtype=np.uint8) for p in train]
    if not outputs or not all(np.array_equal(outputs[0], a) for a in outputs):
        return None
    fixed=outputs[0].copy()
    return Rule("constant_output",lambda a:fixed.copy(),4.0+fixed.size*.04,"constant")
